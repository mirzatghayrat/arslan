// status.snapshot.mac (IPB, docs/specs/mobile-bridge-protocol.md §5.11): the Mac's own state for the phone's
// Overview rings. The Bridge reads it here, in the process that already looks every 2 s, each reading on a
// slow clock of its own, and it rides the snapshots StatusReporter already sends: it is not part of the send
// signature, so a CPU change never causes an iCloud write. Only `sleep` comes from the backend.
//
// None of these reads needs an entitlement or a TCC permission. The Wi-Fi name would (through Location), so
// it is never read: the network reading is the link's kind and state only, never a name or an address.
import Darwin
import Foundation
import IOKit.ps
import Network

public struct MacBattery: Equatable {
    public var level: Int, charging: Bool, minutesLeft: Int?
    public init(level: Int, charging: Bool, minutesLeft: Int?) { (self.level, self.charging, self.minutesLeft) = (level, charging, minutesLeft) }
}

public struct MacMemory: Equatable {
    public var usedBytes: UInt64, totalBytes: UInt64, pressureLevel: Int
    public init(usedBytes: UInt64, totalBytes: UInt64, pressureLevel: Int) {
        (self.usedBytes, self.totalBytes, self.pressureLevel) = (usedBytes, totalBytes, pressureLevel)
    }
}

public struct MacDisk: Equatable {
    public var freeBytes: Int64, totalBytes: Int64
    public init(freeBytes: Int64, totalBytes: Int64) { (self.freeBytes, self.totalBytes) = (freeBytes, totalBytes) }
}

/// All cores' busy and total ticks since boot; a percent is the delta between two samples.
public struct CPUTicks: Equatable {
    public var busy: UInt64, total: UInt64
    public init(busy: UInt64, total: UInt64) { (self.busy, self.total) = (busy, total) }
}

public struct MacNetwork: Equatable {
    public var kind: String, quality: String
    public init(kind: String, quality: String) { (self.kind, self.quality) = (kind, quality) }

    /// macOS reports the link's state, not its speed (the frame list's Decide 1): `good` when it is up and
    /// neither constrained (Low Data Mode) nor expensive (a phone hotspot), `fair` when it is up but one of
    /// them, `poor` when it is down.
    public static func from(satisfied: Bool, constrained: Bool, expensive: Bool, wifi: Bool, wired: Bool) -> MacNetwork {
        MacNetwork(kind: wifi ? "wifi" : wired ? "ethernet" : "other",
                   quality: !satisfied ? "poor" : (constrained || expensive) ? "fair" : "good")
    }
}

public protocol MacProbe: AnyObject {
    func battery() -> MacBattery?
    func cpuTicks() -> CPUTicks?
    func memory() -> MacMemory?
    func disk() -> MacDisk?
    func network() -> MacNetwork?
    var osVersion: String { get }
}

public final class MacState {
    public static let slowEvery: TimeInterval = 60        // battery, memory
    public static let cpuEvery: TimeInterval = 10
    public static let diskEvery: TimeInterval = 300
    public static let bucket: TimeInterval = 300           // the last hour as 12 five-minute averages
    public static let buckets = 12
    let probe: MacProbe
    var battery: MacBattery?, memory: MacMemory?, disk: MacDisk?
    var batteryAt: Date?, memoryAt: Date?, diskAt: Date?, cpuAt: Date?
    var lastTicks: CPUTicks?, cpuNow: Int?
    var bucketStart: Date?, bucketSum = 0, bucketCount = 0
    var closed: [(end: Date, average: Int)] = []

    public init(probe: MacProbe) { self.probe = probe }

    /// The block for a snapshot built at `now`: every reading the Mac has, at most a minute old (disk: five),
    /// and `sleep` as the backend sent it. A reading the Mac doesn't have is left out.
    public func block(now: Date, sleep: [String: Any]?) -> [String: Any] {
        if due(batteryAt, Self.slowEvery, now) { (battery, batteryAt) = (probe.battery(), now) }
        if due(memoryAt, Self.slowEvery, now) { (memory, memoryAt) = (probe.memory(), now) }
        if due(diskAt, Self.diskEvery, now) { (disk, diskAt) = (probe.disk(), now) }
        if due(cpuAt, Self.cpuEvery, now) { sampleCPU(now); cpuAt = now }
        var out: [String: Any] = ["taken_at": ISO8601DateFormatter().string(from: now), "os_version": probe.osVersion]
        if let battery {
            var reading: [String: Any] = ["level": battery.level, "charging": battery.charging]
            if let minutes = battery.minutesLeft { reading["minutes_left"] = minutes }
            out["battery"] = reading
        }
        if let cpuNow {
            out["cpu"] = ["now": cpuNow, "last_hour": closed.filter { $0.end > now - 3600 }.suffix(Self.buckets).map(\.average)]
        }
        if let memory {
            out["memory"] = ["used_gb": tenths(Double(memory.usedBytes) / 1_073_741_824),
                             "total_gb": tenths(Double(memory.totalBytes) / 1_073_741_824),
                             "pressure": Self.pressure(memory.pressureLevel)]
        }
        if let disk {     // GB (10^9), as Finder shows
            out["disk"] = ["free_gb": tenths(Double(disk.freeBytes) / 1e9), "total_gb": tenths(Double(disk.totalBytes) / 1e9)]
        }
        if let network = probe.network() { out["network"] = ["kind": network.kind, "quality": network.quality] }
        if let kept = sleep?["kept_awake"] as? Bool { out["sleep"] = ["kept_awake": kept] }
        return out
    }

    /// `kern.memorystatus_vm_pressure_level`: 1 normal, 2 warn, 4 critical.
    static func pressure(_ level: Int) -> String { [2: "warn", 4: "critical"][level] ?? "normal" }

    func due(_ at: Date?, _ every: TimeInterval, _ now: Date) -> Bool { at.map { now.timeIntervalSince($0) >= every } ?? true }

    func tenths(_ value: Double) -> Double { (value * 10).rounded() / 10 }

    /// The percent of all cores busy since the last sample, and the five-minute buckets it falls in. A bucket
    /// counts once a sample comes after its end; with no sample in a bucket (no phone paired, the Bridge did not
    /// look) it is skipped, and only buckets that ended in the last hour are sent.
    func sampleCPU(_ now: Date) {
        guard let ticks = probe.cpuTicks() else { return }
        defer { lastTicks = ticks }
        guard let last = lastTicks, ticks.total > last.total, ticks.busy >= last.busy else { return }
        let percent = min(100, max(0, Int((Double(ticks.busy - last.busy) / Double(ticks.total - last.total) * 100).rounded())))
        cpuNow = percent
        var start = bucketStart ?? now
        if now.timeIntervalSince(start) >= Self.bucket {
            if bucketCount > 0 {
                closed.append((start + Self.bucket, Int((Double(bucketSum) / Double(bucketCount)).rounded())))
                closed = Array(closed.suffix(Self.buckets))
            }
            start += (now.timeIntervalSince(start) / Self.bucket).rounded(.down) * Self.bucket
            (bucketSum, bucketCount) = (0, 0)
        }
        bucketStart = start
        (bucketSum, bucketCount) = (bucketSum + percent, bucketCount + 1)
    }
}

/// The real readings, from public system calls only.
public final class SystemMacProbe: MacProbe {
    let monitor = NWPathMonitor()
    let lock = NSLock()
    var path: MacNetwork?

    public init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let reading = MacNetwork.from(satisfied: path.status == .satisfied, constrained: path.isConstrained,
                                          expensive: path.isExpensive, wifi: path.usesInterfaceType(.wifi),
                                          wired: path.usesInterfaceType(.wiredEthernet))
            self?.lock.lock(); self?.path = reading; self?.lock.unlock()
        }
        monitor.start(queue: DispatchQueue(label: "arslan.bridge.network"))
    }

    deinit { monitor.cancel() }

    public var osVersion: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "macOS \(v.majorVersion).\(v.minorVersion)" + (v.patchVersion > 0 ? ".\(v.patchVersion)" : "")
    }

    public func network() -> MacNetwork? { lock.lock(); defer { lock.unlock() }; return path }

    public func battery() -> MacBattery? {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let list = IOPSCopyPowerSourcesList(info)?.takeRetainedValue() as? [CFTypeRef] else { return nil }
        for source in list {
            guard let d = IOPSGetPowerSourceDescription(info, source)?.takeUnretainedValue() as? [String: Any],
                  d[kIOPSTypeKey] as? String == kIOPSInternalBatteryType,
                  let current = d[kIOPSCurrentCapacityKey] as? Int, let max = d[kIOPSMaxCapacityKey] as? Int, max > 0
            else { continue }
            let onBattery = d[kIOPSPowerSourceStateKey] as? String == kIOPSBatteryPowerValue
            let minutes = d[kIOPSTimeToEmptyKey] as? Int ?? -1          // -1: macOS has no estimate yet
            return MacBattery(level: Swift.min(100, current * 100 / max), charging: d[kIOPSIsChargingKey] as? Bool ?? false,
                              minutesLeft: onBattery && minutes > 0 ? minutes : nil)
        }
        return nil                                                       // a Mac without a battery
    }

    public func cpuTicks() -> CPUTicks? {
        var count: natural_t = 0
        var info: processor_info_array_t?
        var infoCount: mach_msg_type_number_t = 0
        guard host_processor_info(mach_host_self(), PROCESSOR_CPU_LOAD_INFO, &count, &info, &infoCount) == KERN_SUCCESS,
              let info else { return nil }
        defer { vm_deallocate(mach_task_self_, vm_address_t(bitPattern: info), vm_size_t(Int(infoCount) * MemoryLayout<integer_t>.stride)) }
        var busy: UInt64 = 0, idle: UInt64 = 0
        for cpu in 0..<Int(count) {
            let base = cpu * Int(CPU_STATE_MAX)
            busy += UInt64(UInt32(bitPattern: info[base + Int(CPU_STATE_USER)])) + UInt64(UInt32(bitPattern: info[base + Int(CPU_STATE_SYSTEM)]))
                + UInt64(UInt32(bitPattern: info[base + Int(CPU_STATE_NICE)]))
            idle += UInt64(UInt32(bitPattern: info[base + Int(CPU_STATE_IDLE)]))
        }
        return CPUTicks(busy: busy, total: busy + idle)
    }

    /// "Memory Used" as Activity Monitor shows it: app memory (internal minus purgeable), wired and compressed.
    public func memory() -> MacMemory? {
        var stats = vm_statistics64()
        var size = mach_msg_type_number_t(MemoryLayout<vm_statistics64>.stride / MemoryLayout<integer_t>.stride)
        let ok = withUnsafeMutablePointer(to: &stats) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(size)) { host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &size) }
        }
        var total: UInt64 = 0, totalSize = MemoryLayout<UInt64>.size
        var pressure: Int32 = 0, pressureSize = MemoryLayout<Int32>.size
        guard ok == KERN_SUCCESS, sysctlbyname("hw.memsize", &total, &totalSize, nil, 0) == 0 else { return nil }
        if sysctlbyname("kern.memorystatus_vm_pressure_level", &pressure, &pressureSize, nil, 0) != 0 { pressure = 1 }
        let pages = UInt64(stats.internal_page_count) - UInt64(stats.purgeable_count) + UInt64(stats.wire_count)
            + UInt64(stats.compressor_page_count)
        return MacMemory(usedBytes: pages * UInt64(vm_kernel_page_size), totalBytes: total, pressureLevel: Int(pressure))
    }

    public func disk() -> MacDisk? {
        guard let values = try? URL(fileURLWithPath: "/").resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey,
                                                                                    .volumeTotalCapacityKey]),
              let free = values.volumeAvailableCapacityForImportantUsage, let total = values.volumeTotalCapacity else { return nil }
        return MacDisk(freeBytes: free, totalBytes: Int64(total))
    }
}
