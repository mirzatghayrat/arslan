// BRG1 (docs/plans/0164/BRG1-mailbox-races.md): the Bridge's four loops (the poll, the held progress lines, the
// status snapshot, the sweep) and a phone's hello all reach one Mailbox at the same time. A `seq` must never
// repeat (the phone drops a repeated one as a replay, protocol §4.8), and the in-memory sets must never be
// changed from two tasks at once.
import Foundation
import XCTest
@testable import BridgeCore

/// A store safe to call from several tasks (MemoryStore's behaviour, under a lock), so a failure here is the
/// Mailbox's, not the test store's.
final class LockedStore: EnvelopeStore, @unchecked Sendable {
    private var stored: [String: EnvelopeRecord] = [:]
    private var log: [String] = []
    private let lock = NSLock()
    private func locked<T>(_ body: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return body() }

    func save(_ record: EnvelopeRecord) async throws { locked { log.append(record.id); stored[record.id] = record } }
    func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) {
        locked {
            let start = token.flatMap { Int(String(decoding: $0, as: UTF8.self)) } ?? 0
            var seen = Set<String>()
            let fresh = log[min(start, log.count)...].reversed().filter { seen.insert($0).inserted }.reversed()
                .compactMap { stored[$0] }
            return (fresh, Data(String(log.count).utf8))
        }
    }
    func delete(ids: [String]) async throws { locked { ids.forEach { stored[$0] = nil } } }
    func ages() async throws -> [(id: String, createdAt: Date)] { locked { stored.values.map { ($0.id, $0.createdAt) } } }
    func recipients(of ids: [String]) async throws -> [String: String] {
        locked { ids.reduce(into: [:]) { out, id in if let r = stored[id] { out[id] = r.to } } }
    }
    var records: [EnvelopeRecord] { locked { Array(stored.values) } }
}

/// The status endpoint's answer, and nothing kept between calls (FakeBackend records each call).
final class StatusOnlyBackend: BackendReads, @unchecked Sendable {
    func json(_ path: String) async throws -> [String: Any] {
        ["presence": "online", "mascot": "idle", "waiting_approvals": 0, "high_risk_mac_only": false, "jobs": []]
    }
    func post(_ path: String, body: [String: Any]) async throws -> [String: Any] { [:] }
}

final class MailboxConcurrencyTests: XCTestCase {
    func pair(_ store: EnvelopeStore) -> (Mailbox, Mailbox) {
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        return (mac, phone)
    }

    func testSendsFromSeveralTasksNeverShareASeq() async throws {
        let store = LockedStore()
        let (mac, _) = pair(store)
        await withTaskGroup(of: Void.self) { group in
            for lane in 0..<4 {
                group.addTask {
                    for k in 0..<150 {
                        _ = try? await mac.send(type: "chat.event", body: ["conversation_id": "c\(lane)", "kind": "progress",
                                                                          "message_id": "m\(k)", "text": "t", "final": false],
                                                to: "iphone-1")
                    }
                }
            }
        }
        let seqs = store.records.filter { $0.from == "mac-1" }.map(\.seq)
        XCTAssertEqual(seqs.count, 600)
        XCTAssertEqual(Set(seqs).count, seqs.count, "a repeated seq is dropped by the phone as a replay")
        XCTAssertEqual(mac.unacknowledged.count, 600, "every send is waiting for its ack")
    }

    func testSendingWithdrawingAndReadingAcksAtOnce() async throws {
        let store = LockedStore()
        let (mac, phone) = pair(store)
        await withTaskGroup(of: Void.self) { group in
            group.addTask {                                         // the snapshot loop: send, withdraw the older one
                var last: String?
                for _ in 0..<200 {
                    guard let record = try? await mac.send(type: "status.snapshot", body: ["presence": "online"], to: "iphone-1")
                    else { continue }
                    if let older = last { try? mac.withdraw(older) }
                    last = record.id
                }
            }
            group.addTask {                                         // the phone reads and acks
                for _ in 0..<50 { _ = try? await phone.receive(); await Task.yield() }
            }
            group.addTask {                                         // the poll: reads the acks, deletes
                for _ in 0..<50 { _ = try? await mac.receive(); await Task.yield() }
            }
        }
        _ = try await phone.receive()
        _ = try await mac.receive()
        try await mac.deleteAcknowledged()
        XCTAssertLessThanOrEqual(mac.unacknowledged.count, 1, "acked or withdrawn, except at most the newest")
    }

    func testReadingAcksWhileSending() async throws {
        let store = LockedStore()
        let (mac, phone) = pair(store)
        for k in 0..<300 { _ = try await mac.send(type: "chat.event", body: ["n": k], to: "iphone-1") }
        _ = try await phone.receive()                           // the phone acks all 300 in one go
        let acks = store.records.filter { $0.from == "iphone-1" }
        XCTAssertFalse(acks.isEmpty)
        await withTaskGroup(of: Void.self) { group in
            group.addTask { _ = try? await mac.process(acks) }  // the poll clears 300 acked sends…
            group.addTask {                                     // …while the snapshot loop keeps sending
                for k in 0..<300 { _ = try? await mac.send(type: "status.snapshot", body: ["n": k], to: "iphone-1") }
            }
        }
        XCTAssertEqual(mac.unacknowledged.count, 300, "the 300 acked are gone, the 300 new ones wait")
    }

    func testAStatusTickAndAHelloAtOnce() async throws {
        let store = LockedStore()
        let (mac, _) = pair(store)
        let reporter = StatusReporter(backend: StatusOnlyBackend(), mailbox: mac, deviceName: "Mac")
        let t0 = Date(timeIntervalSince1970: 1_790_985_600)
        await withTaskGroup(of: Void.self) { group in
            group.addTask { for k in 0..<150 { await reporter.tick(now: t0 + Double(k) * 61) } }
            group.addTask { for k in 0..<150 { await reporter.send(to: "iphone-1", now: t0 + Double(k) * 61 + 1) } }
        }
        XCTAssertLessThanOrEqual(mac.unacknowledged.count, 2, "each new snapshot withdraws the one before it")
    }
}

/// A control channel safe to call from several tasks (FakeControl records each frame unlocked).
final class LockedControl: ControlChannel, @unchecked Sendable {
    private var frames: [[String: Any]] = []
    private let lock = NSLock()
    private func locked<T>(_ body: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return body() }
    func send(_ frame: [String: Any]) async throws { locked { frames.append(frame) } }
    func all(_ type: String) -> [[String: Any]] { locked { frames.filter { $0["type"] as? String == type } } }
}

/// BRG1 follow-up: the poll loop opens pair requests (`PairingHost.open`, `pending`) while Arslan's control
/// channel makes codes and decides (`pairing.new`, `pairing.decide`), from another task.
final class RuntimeConcurrencyTests: XCTestCase {
    func testPairingCodesAndPollsAtOnce() async throws {
        let store = LockedStore(), control = LockedControl()
        let bridge = try BridgeRuntime(identities: IdentityStore(secrets: MemorySecrets()), store: store, control: control,
                                       macName: "Test Mac", containerID: "iCloud.dev.aralem.arslan", version: "0.1.64")
        await withTaskGroup(of: Void.self) { group in
            group.addTask { for _ in 0..<200 { try? await bridge.handleControl(["type": "pairing.new"]) } }
            group.addTask { for _ in 0..<300 { _ = try? await bridge.poll() } }
            group.addTask { for _ in 0..<6000 { _ = bridge.isPairing(); await Task.yield() } }   // the poll pace's read
        }
        XCTAssertEqual(control.all("pairing.code").count, 200)
    }

    func testOneRequestIsDecidedOnceWhateverAsksAtOnce() async throws {
        let store = LockedStore(), control = LockedControl()
        let bridge = try BridgeRuntime(identities: IdentityStore(secrets: MemorySecrets()), store: store, control: control,
                                       macName: "Test Mac", containerID: "iCloud.dev.aralem.arslan", version: "0.1.64")
        try await bridge.handleControl(["type": "pairing.new"])
        let uri = try XCTUnwrap(control.all("pairing.code").last?["uri"] as? String)
        try await store.save(try PairingHostTests().phoneRequest(uri: uri, now: Date(), phoneSigning: .init(),
                                                                 phoneExchange: .init(), phoneID: "iphone-x"))
        await withTaskGroup(of: Void.self) { group in               // the poll sees the request again and again…
            group.addTask { for _ in 0..<200 { _ = try? await bridge.poll() } }
            group.addTask {                                         // …while the click arrives
                while control.all("pairing.request").isEmpty { await Task.yield() }
                let id = control.all("pairing.request")[0]["request_id"] as? String ?? ""
                for _ in 0..<20 { try? await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": true]) }
            }
        }
        XCTAssertEqual(control.all("pairing.request").count, 1, "shown once")
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-x"))
    }
}

/// BRG1's review follow-ups (#657): what the lock and the send's order promise, each pinned on its own.
final class MailboxOrderTests: XCTestCase {
    /// A store whose delete takes a moment, as CloudKit's does, and that can refuse saves.
    final class SlowStore: EnvelopeStore, @unchecked Sendable {
        let inner = LockedStore()
        var refuseSaves = false
        /// Called with each record before it is kept: the counter the Mailbox remembered must be past it.
        var onSave: ((EnvelopeRecord) -> Void)?
        func save(_ record: EnvelopeRecord) async throws {
            if refuseSaves { throw BridgeError.code("cloudkit_down") }
            onSave?(record)
            try await inner.save(record)
        }
        func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) { try await inner.changes(since: token) }
        func delete(ids: [String]) async throws {
            try await Task.sleep(nanoseconds: 1_000_000)
            try await inner.delete(ids: ids)
        }
        func ages() async throws -> [(id: String, createdAt: Date)] { try await inner.ages() }
        func recipients(of ids: [String]) async throws -> [String: String] { try await inner.recipients(of: ids) }
    }

    func mailbox(_ store: EnvelopeStore, memory: MailboxMemoryStore? = nil) -> Mailbox {
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store, memoryStore: memory)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        return mac
    }

    func testDeletingWhileWithdrawing() async throws {
        let store = SlowStore()
        let mac = mailbox(store)
        var sent: [String] = []
        for _ in 0..<400 { sent.append(try await mac.send(type: "status.snapshot", body: ["presence": "online"], to: "iphone-1").id) }
        let ids = sent
        await withTaskGroup(of: Void.self) { group in
            group.addTask { for id in ids.dropLast() { try? mac.withdraw(id); await Task.yield() } }   // each newer one replaces it
            group.addTask { for _ in 0..<200 { try? await mac.deleteAcknowledged() } }               // the poll's deletes, slow
        }
        for _ in 0..<5 { try await mac.deleteAcknowledged() }
        XCTAssertEqual(mac.unacknowledged.map(\.id), [sent.last!], "only the newest snapshot still waits")
        XCTAssertTrue(mac.toDelete.isEmpty, "every withdrawn one was deleted")
    }

    func testASaveThatFailsLeavesNothingWaitingForAnAck() async throws {
        let store = SlowStore()
        let mac = mailbox(store)
        store.refuseSaves = true
        do {
            _ = try await mac.send(type: "chat.event", body: ["text": "hi"], to: "iphone-1")
            XCTFail("the save failed, so the send must too")
        } catch {}
        XCTAssertTrue(mac.unacknowledged.isEmpty, "a record that never reached the store is never re-sent")
        store.refuseSaves = false
        let next = try await mac.send(type: "chat.event", body: ["text": "hi"], to: "iphone-1")
        XCTAssertEqual(mac.unacknowledged.map(\.id), [next.id])
    }

    func testTheCounterIsRememberedBeforeEachRecordExists() async throws {
        let store = SlowStore(), memory = InMemoryMemoryStore()
        let mac = mailbox(store, memory: memory)
        var behind: [Int64] = []
        let lock = NSLock()
        store.onSave = { record in                                   // §4.5: a restart never re-uses a seq the phone saw
            lock.lock(); defer { lock.unlock() }
            if (memory.memory?.nextSeq ?? 0) <= record.seq { behind.append(record.seq) }
        }
        await withTaskGroup(of: Void.self) { group in
            for _ in 0..<3 {
                group.addTask { for _ in 0..<50 { _ = try? await mac.send(type: "chat.event", body: [:], to: "iphone-1") } }
            }
        }
        XCTAssertEqual(behind, [], "each saved record's seq is below the remembered counter")
    }
}
