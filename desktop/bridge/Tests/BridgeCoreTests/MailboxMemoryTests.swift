import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

/// Found on the real iPhone: after Arslan restarted (a new build installed), the Bridge counted from
/// seq 1 again and the phone dropped every message as a replay — "Mac 已离线", no replies.
final class MailboxMemoryTests: XCTestCase {
    let macSigning = Curve25519.Signing.PrivateKey(), macExchange = Curve25519.KeyAgreement.PrivateKey()
    let phoneSigning = Curve25519.Signing.PrivateKey(), phoneExchange = Curve25519.KeyAgreement.PrivateKey()

    func mac(_ store: MemoryStore, memory: MailboxMemoryStore?, now: Date = Date()) -> Mailbox {
        let mac = Mailbox(deviceID: "mac-1", signing: macSigning, exchange: macExchange, store: store, memoryStore: memory, now: now)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phoneSigning.publicKey, exchange: phoneExchange.publicKey))
        return mac
    }
    func phone(_ store: MemoryStore) -> Mailbox {
        let phone = Mailbox(deviceID: "iphone-1", signing: phoneSigning, exchange: phoneExchange, store: store)
        phone.add(peer: Peer(deviceID: "mac-1", signing: macSigning.publicKey, exchange: macExchange.publicKey))
        return phone
    }

    func testARestartedBridgeKeepsCountingSoThePhoneStillListens() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let phone = phone(store)
        let before = mac(store, memory: memory)
        for i in 0..<3 { try await before.send(type: "status.snapshot", body: ["n": i], to: "iphone-1") }
        let first = try await phone.receive()
        XCTAssertEqual(first.count, 3)
        let after = mac(store, memory: memory)                       // Arslan restarted
        try await after.send(type: "status.snapshot", body: ["n": 3], to: "iphone-1")
        let heard = try await phone.receive()
        XCTAssertEqual(heard.map(\.type), ["status.snapshot"], "the phone still takes the restarted Bridge's messages")
    }

    func testWithoutMemoryTheOldBridgeRepeatedNumbers() async throws {
        let store = MemoryStore(), phone = phone(store)
        let before = Mailbox(deviceID: "mac-1", signing: macSigning, exchange: macExchange, store: store)
        before.add(peer: Peer(deviceID: "iphone-1", signing: phoneSigning.publicKey, exchange: phoneExchange.publicKey))
        try await before.send(type: "status.snapshot", body: [:], to: "iphone-1")
        _ = try await phone.receive()
        let after = Mailbox(deviceID: "mac-1", signing: macSigning, exchange: macExchange, store: store)
        after.add(peer: Peer(deviceID: "iphone-1", signing: phoneSigning.publicKey, exchange: phoneExchange.publicKey))
        try await after.send(type: "status.snapshot", body: [:], to: "iphone-1")
        let heard = try await phone.receive()
        XCTAssertTrue(heard.isEmpty, "the bug this guards against: seq 1 again is a replay")
    }

    func testTheCounterNeverStartsBelowTheClockEvenWithoutAFile() async throws {
        let store = MemoryStore(), now = Date(timeIntervalSince1970: 1_790_000_000)
        let fresh = mac(store, memory: InMemoryMemoryStore(), now: now)
        let record = try await fresh.send(type: "status.snapshot", body: [:], to: "iphone-1")
        XCTAssertGreaterThanOrEqual(record.seq, 1_790_000_000_000)
        let memory = InMemoryMemoryStore()
        var saved = MailboxMemory(); saved.nextSeq = 1_800_000_000_000
        memory.memory = saved
        let ahead = mac(store, memory: memory, now: now)
        let next = try await ahead.send(type: "status.snapshot", body: [:], to: "iphone-1")
        XCTAssertEqual(next.seq, 1_800_000_000_000, "a saved counter ahead of the clock is kept")
        XCTAssertEqual(memory.memory?.nextSeq, 1_800_000_000_001, "saved before the record was written")
    }

    func testAfterARestartAPhoneMessageIsNotRunTwice() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let phone = phone(store)
        try await phone.send(type: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        let before = mac(store, memory: memory)
        let ran = try await before.receive()
        XCTAssertEqual(ran.map(\.type), ["chat.send"])
        let after = mac(store, memory: memory)
        after.token = nil                                         // even reading the whole feed again
        let again = try await after.receive()
        XCTAssertTrue(again.isEmpty, "remembered as done")
        let acks = store.records.values.filter { $0.from == "mac-1" }
        XCTAssertEqual(acks.count, 2, "but acknowledged again, so the phone can let go of it")
    }

    func testALateAckStillDeletesARecordSentBeforeTheRestart() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let phone = phone(store)
        let before = mac(store, memory: memory)
        let sent = try await before.send(type: "chat.event", body: ["kind": "message", "text": "done"], to: "iphone-1")
        let after = mac(store, memory: memory)                        // restarted before the phone acked
        _ = try await phone.receive()                                 // the phone reads it and acks
        _ = try await after.receive()
        XCTAssertNil(store.records[sent.id], "deleted although the Bridge that sent it is gone")
    }

    func testTheFileStoreRoundTrips() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = try FileMemoryStore(deviceID: "mac-1", directory: directory)
        XCTAssertNil(file.load())
        var memory = MailboxMemory(); memory.nextSeq = 42; memory.processed = ["a"]; memory.token = Data([1, 2])
        var window = ReplayWindow(); _ = window.accept(7); memory.windows = ["iphone-1": window]
        try file.save(memory)
        XCTAssertEqual(try FileMemoryStore(deviceID: "mac-1", directory: directory).load(), memory)
    }

    func testTheCounterIsSavedBeforeTheWriteSoAFailedWriteNeverReusesANumber() async throws {
        final class Offline: EnvelopeStore {
            func save(_ record: EnvelopeRecord) async throws { throw URLError(.notConnectedToInternet) }
            func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) { ([], nil) }
            func delete(ids: [String]) async throws {}
        }
        let memory = InMemoryMemoryStore()
        var saved = MailboxMemory(); saved.nextSeq = 1_900_000_000_000
        memory.memory = saved
        let mac = Mailbox(deviceID: "mac-1", signing: macSigning, exchange: macExchange, store: Offline(), memoryStore: memory)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phoneSigning.publicKey, exchange: phoneExchange.publicKey))
        do { try await mac.send(type: "ack", body: ["ids": []], to: "iphone-1"); XCTFail("offline") } catch {}
        XCTAssertEqual(memory.memory?.nextSeq, 1_900_000_000_001, "the number used is gone for good")
    }
}
