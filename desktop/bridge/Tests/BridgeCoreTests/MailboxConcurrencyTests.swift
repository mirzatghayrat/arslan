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
