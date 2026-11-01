// status.snapshot.mac (IPB, docs/specs/mobile-bridge-protocol.md §5.11): the Mac's own state, read by the
// Bridge on slow clocks of its own, and riding the snapshots that are already sent.
import Foundation
import XCTest
@testable import BridgeCore

final class FakeProbe: MacProbe {
    var ticks: [CPUTicks] = []
    var batteryReading: MacBattery? = MacBattery(level: 80, charging: false, minutesLeft: 240)
    var memoryReading: MacMemory? = MacMemory(usedBytes: 12 << 30, totalBytes: 32 << 30, pressureLevel: 1)
    var diskReading: MacDisk? = MacDisk(freeBytes: 412_340_000_000, totalBytes: 994_660_000_000)
    var networkReading: MacNetwork? = MacNetwork(kind: "wifi", quality: "good")
    var calls: [String: Int] = [:]
    let osVersion = "macOS 26.1"

    func battery() -> MacBattery? { calls["battery", default: 0] += 1; return batteryReading }
    func cpuTicks() -> CPUTicks? { calls["cpu", default: 0] += 1; return ticks.isEmpty ? nil : ticks.removeFirst() }
    func memory() -> MacMemory? { calls["memory", default: 0] += 1; return memoryReading }
    func disk() -> MacDisk? { calls["disk", default: 0] += 1; return diskReading }
    func network() -> MacNetwork? { networkReading }
}

final class MacStateTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)

    /// Ticks whose deltas give `percents`, one sample apart: busy grows by p of each 100 ticks.
    func ticks(_ percents: [Int]) -> [CPUTicks] {
        var busy: UInt64 = 5_000, total: UInt64 = 20_000
        var out = [CPUTicks(busy: busy, total: total)]
        for p in percents { busy += UInt64(p); total += 100; out.append(CPUTicks(busy: busy, total: total)) }
        return out
    }

    func testTheBlockHasEveryReadingInItsUnits() throws {
        let probe = FakeProbe()
        probe.ticks = ticks([37])
        let state = MacState(probe: probe)
        _ = state.block(now: t0, sleep: nil)
        let mac = state.block(now: t0 + 10, sleep: ["kept_awake": true])
        XCTAssertEqual(mac["taken_at"] as? String, ISO8601DateFormatter().string(from: t0 + 10))
        XCTAssertEqual(mac["battery"] as? [String: AnyHashable], ["level": 80, "charging": false, "minutes_left": 240])
        XCTAssertEqual((mac["cpu"] as? [String: Any])?["now"] as? Int, 37)
        XCTAssertEqual((mac["cpu"] as? [String: Any])?["last_hour"] as? [Int], [], "no full five minutes yet")
        XCTAssertEqual(mac["memory"] as? [String: AnyHashable], ["used_gb": 12.0, "total_gb": 32.0, "pressure": "normal"])
        XCTAssertEqual(mac["disk"] as? [String: AnyHashable], ["free_gb": 412.3, "total_gb": 994.7], "GB as Finder shows")
        XCTAssertEqual(mac["network"] as? [String: AnyHashable], ["kind": "wifi", "quality": "good"])
        XCTAssertEqual(mac["sleep"] as? [String: AnyHashable], ["kept_awake": true], "from the backend")
        XCTAssertEqual(mac["os_version"] as? String, "macOS 26.1")
    }

    func testMemoryIsGibibytesToOneDecimal() {
        let probe = FakeProbe()
        probe.memoryReading = MacMemory(usedBytes: UInt64(10.46 * Double(1 << 30)), totalBytes: 16 << 30, pressureLevel: 4)
        let memory = MacState(probe: probe).block(now: t0, sleep: nil)["memory"] as? [String: AnyHashable]
        XCTAssertEqual(memory, ["used_gb": 10.5, "total_gb": 16.0, "pressure": "critical"])
    }

    func testPressureWords() {
        XCTAssertEqual([1, 2, 4, 0, 7].map(MacState.pressure), ["normal", "warn", "critical", "normal", "normal"])
    }

    func testNetworkQualityIsTheLinkStateNotASpeed() {
        let cases: [(Bool, Bool, Bool, String)] = [(true, false, false, "good"), (true, true, false, "fair"),
                                                    (true, false, true, "fair"), (false, false, false, "poor")]
        for (satisfied, constrained, expensive, quality) in cases {
            XCTAssertEqual(MacNetwork.from(satisfied: satisfied, constrained: constrained, expensive: expensive,
                                           wifi: true, wired: false).quality, quality)
        }
        XCTAssertEqual(MacNetwork.from(satisfied: true, constrained: false, expensive: false, wifi: false, wired: true).kind, "ethernet")
        XCTAssertEqual(MacNetwork.from(satisfied: true, constrained: false, expensive: false, wifi: false, wired: false).kind, "other")
    }

    func testWhatIsNotKnownIsLeftOut() {
        let probe = FakeProbe()
        probe.batteryReading = nil                                      // a desktop Mac
        probe.networkReading = nil                                      // before the first path update
        probe.diskReading = nil
        let mac = MacState(probe: probe).block(now: t0, sleep: nil)
        XCTAssertNil(mac["battery"]); XCTAssertNil(mac["network"]); XCTAssertNil(mac["disk"])
        XCTAssertNil(mac["cpu"], "one sample has no delta yet")
        XCTAssertNil(mac["sleep"])
        XCTAssertNotNil(mac["taken_at"]); XCTAssertNotNil(mac["memory"])
        probe.batteryReading = MacBattery(level: 100, charging: true, minutesLeft: nil)
        let charging = MacState(probe: probe).block(now: t0, sleep: nil)["battery"] as? [String: AnyHashable]
        XCTAssertEqual(charging, ["level": 100, "charging": true], "no estimate, no minutes_left")
    }

    func testTheLastHourIsFiveMinuteAveragesOfFullBucketsOnly() throws {
        // A sample every 10 s for 11 minutes: 30 at 20 %, 30 at 50 %, 6 at 90 %.
        let percents = Array(repeating: 20, count: 30) + Array(repeating: 50, count: 30) + Array(repeating: 90, count: 6)
        let probe = FakeProbe()
        probe.ticks = ticks(percents)
        let state = MacState(probe: probe)
        var mac: [String: Any] = [:]
        for k in 0...percents.count { mac = state.block(now: t0 + Double(k) * 10, sleep: nil) }
        let cpu = try XCTUnwrap(mac["cpu"] as? [String: Any])
        XCTAssertEqual(cpu["last_hour"] as? [Int], [20, 50], "the third five minutes isn't full yet")
        XCTAssertEqual(cpu["now"] as? Int, 90)
    }

    func testAtMostTwelveBucketsAndNoneOlderThanAnHour() throws {
        let probe = FakeProbe()
        let count = 14 * 30                                         // 70 minutes of samples
        probe.ticks = ticks((0..<count).map { ($0 / 30) * 5 })      // bucket k averages 5k %
        let state = MacState(probe: probe)
        var mac: [String: Any] = [:]
        for k in 0...count { mac = state.block(now: t0 + Double(k) * 10, sleep: nil) }
        // Fourteen five-minute buckets; the last one closes only when a sample comes after it.
        XCTAssertEqual((mac["cpu"] as? [String: Any])?["last_hour"] as? [Int], (1..<13).map { $0 * 5 })
        // The Bridge stops looking with no phone paired: a gap leaves only the buckets of the last hour.
        probe.ticks = ticks([40])
        _ = state.block(now: t0 + Double(count) * 10 + 3000, sleep: nil)
        mac = state.block(now: t0 + Double(count) * 10 + 3010, sleep: nil)
        XCTAssertEqual((mac["cpu"] as? [String: Any])?["last_hour"] as? [Int], (12..<14).map { $0 * 5 })
    }

    func testEachReadingKeepsItsOwnClock() {
        let probe = FakeProbe()
        probe.ticks = ticks(Array(repeating: 10, count: 400))
        let state = MacState(probe: probe)
        for k in 0..<300 { _ = state.block(now: t0 + Double(k) * 2, sleep: nil) }   // a look every 2 s for 10 minutes
        XCTAssertEqual(probe.calls["cpu"], 60, "every 10 s")
        XCTAssertEqual(probe.calls["battery"], 10, "every minute")
        XCTAssertEqual(probe.calls["memory"], 10, "every minute")
        XCTAssertEqual(probe.calls["disk"], 2, "every five minutes")
    }

    func testTheSystemProbeSendsNoNetworkNameOrAddress() throws {
        let probe = SystemMacProbe()
        let state = MacState(probe: probe)
        _ = state.block(now: Date(), sleep: nil)
        Thread.sleep(forTimeInterval: 0.3)                          // the first path update
        let mac = state.block(now: Date() + 11, sleep: ["kept_awake": false])
        var readings = mac
        readings["taken_at"] = nil                                  // a time's colons would read as an IPv6 address
        let text = String(decoding: try JSONSerialization.data(withJSONObject: readings), as: UTF8.self)
        XCTAssertNil(text.range(of: #"\b\d{1,3}(\.\d{1,3}){3}\b"#, options: .regularExpression), text)
        XCTAssertNil(text.range(of: #"[0-9a-f]{1,4}(:[0-9a-f]{0,4}){2,7}"#, options: [.regularExpression, .caseInsensitive]), text)
        for word in ["ssid", "bssid", "en0", "interface", "address"] { XCTAssertFalse(text.lowercased().contains(word), word) }
        XCTAssertTrue(Set(mac.keys).isSubset(of: ["taken_at", "battery", "cpu", "memory", "disk", "network", "sleep", "os_version"]))
        let memory = try XCTUnwrap(mac["memory"] as? [String: Any])
        XCTAssertGreaterThan(memory["total_gb"] as? Double ?? 0, 0)
        XCTAssertNotNil((mac["cpu"] as? [String: Any])?["now"], "two samples 10 s apart")
        XCTAssertTrue((mac["os_version"] as? String ?? "").hasPrefix("macOS "))
    }
}

final class StatusReporterMacTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)

    func setUp(probe: FakeProbe) -> (Mailbox, FakeBackend, StatusReporter) {
        let store = MemoryStore()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let backend = FakeBackend()
        backend.answers["/api/v1/phone/status"] = .success(["presence": "online", "mascot": "idle", "waiting_approvals": 0,
                                                            "high_risk_mac_only": false, "jobs": [],
                                                            "mac": ["sleep": ["kept_awake": true]]])
        return (phone, backend, StatusReporter(backend: backend, mailbox: mac, deviceName: "Studio Mac",
                                               mac: MacState(probe: probe)))
    }

    func testTheSnapshotCarriesTheMacsStateWithTheBackendsSleep() async throws {
        let probe = FakeProbe()
        let (phone, _, reporter) = setUp(probe: probe)
        await reporter.tick(now: t0)
        let received = try await phone.receive()
        let body = try XCTUnwrap(received.first?.envelope["body"] as? [String: Any])
        let mac = try XCTUnwrap(body["mac"] as? [String: Any])
        XCTAssertEqual(mac["sleep"] as? [String: AnyHashable], ["kept_awake": true])
        XCTAssertEqual(mac["taken_at"] as? String, ISO8601DateFormatter().string(from: t0))
        XCTAssertNotNil(mac["memory"])
    }

    func testAChangeInTheMacsStateAloneNeverPosts() async throws {
        let probe = FakeProbe()
        probe.ticks = ticks()
        let (phone, _, reporter) = setUp(probe: probe)
        await reporter.tick(now: t0)
        let first = try await phone.receive()
        XCTAssertEqual(first.count, 1)
        for k in 1...29 {                                           // CPU, battery and memory all change
            probe.batteryReading = MacBattery(level: 80 - k, charging: false, minutesLeft: 200 - k)
            probe.memoryReading = MacMemory(usedBytes: UInt64(k) << 30, totalBytes: 32 << 30, pressureLevel: k % 2 == 0 ? 1 : 2)
            await reporter.tick(now: t0 + Double(k) * 2)
        }
        let held = try await phone.receive()
        XCTAssertEqual(held.count, 0, "an iCloud write per CPU tick would be the cost")
        await reporter.tick(now: t0 + 60)
        let beat = try await phone.receive()
        let body = try XCTUnwrap(beat.first?.envelope["body"] as? [String: Any])
        XCTAssertEqual(((body["mac"] as? [String: Any])?["battery"] as? [String: Any])?["level"] as? Int, 80 - 29,
                       "the heartbeat carries the newest readings")
    }

    func ticks() -> [CPUTicks] { (0..<40).map { CPUTicks(busy: UInt64($0 * 37), total: UInt64($0 * 100)) } }
}
