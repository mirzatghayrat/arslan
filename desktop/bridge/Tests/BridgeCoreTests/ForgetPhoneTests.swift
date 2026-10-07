import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

/// Found 2026-10-07 on a real iPhone (TestFlight 1.0 (11)): each pairing gives the phone a new id and
/// unpairing on the phone never tells the Mac, so Settings listed four "iPhone"s, the Bridge kept
/// writing to the old ids, and 1,602 of its records waited in the user's iCloud for acks that could
/// never come. A fresh phone paged through all of them looking for its pair.accept and gave up (§3.3).
final class ForgetPhoneTests: XCTestCase {
    let macSigning = Curve25519.Signing.PrivateKey(), macExchange = Curve25519.KeyAgreement.PrivateKey()
    let keys = ["iphone-1": (Curve25519.Signing.PrivateKey(), Curve25519.KeyAgreement.PrivateKey()),
                "iphone-2": (Curve25519.Signing.PrivateKey(), Curve25519.KeyAgreement.PrivateKey())]

    func peer(_ id: String) -> Peer { Peer(deviceID: id, signing: keys[id]!.0.publicKey, exchange: keys[id]!.1.publicKey) }
    func mac(_ store: EnvelopeStore, memory: MailboxMemoryStore, peers: [String] = ["iphone-1", "iphone-2"]) -> Mailbox {
        let mac = Mailbox(deviceID: "mac-1", signing: macSigning, exchange: macExchange, store: store, memoryStore: memory)
        peers.forEach { mac.add(peer: peer($0)) }
        return mac
    }
    func phone(_ id: String, _ store: EnvelopeStore) -> Mailbox {
        let phone = Mailbox(deviceID: id, signing: keys[id]!.0, exchange: keys[id]!.1, store: store)
        phone.add(peer: Peer(deviceID: "mac-1", signing: macSigning.publicKey, exchange: macExchange.publicKey))
        return phone
    }

    func testRemovingAPhoneDeletesWhatWaitsForItsAckAndNothingOfAnotherPhones() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let mac = mac(store, memory: memory)
        try await phone("iphone-2", store).send(type: "hello", body: [:], to: "mac-1")
        _ = try await mac.receive()
        XCTAssertNotNil(memory.memory?.heard["iphone-2"])
        let gone = try await mac.send(type: "status.snapshot", body: [:], to: "iphone-2")
        let kept = try await mac.send(type: "status.snapshot", body: [:], to: "iphone-1")
        try mac.remove(peer: "iphone-2")
        try await mac.deleteAcknowledged()
        XCTAssertNil(memory.memory?.heard["iphone-2"], "a removed phone is not remembered as heard")
        XCTAssertNil(store.records[gone.id], "nobody will ever ack it now")
        XCTAssertNotNil(store.records[kept.id], "the phone still paired keeps its record")
        XCTAssertEqual(mac.unacknowledged.map(\.id), [kept.id])
        XCTAssertEqual(memory.memory?.awaitingAck, [kept.id], "and a restart does not wait for the removed one either")
        _ = try await phone("iphone-1", store).receive()          // the paired phone's ack still clears its own
        _ = try await mac.receive()
        XCTAssertNil(store.records[kept.id])
    }

    func testTheRecipientIsRememberedSoARemovalAfterARestartStillFindsItsRecords() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let before = mac(store, memory: memory)
        let gone = try await before.send(type: "chat.event", body: ["kind": "message"], to: "iphone-2")
        let kept = try await before.send(type: "chat.event", body: ["kind": "message"], to: "iphone-1")
        XCTAssertEqual(memory.memory?.awaitingTo, [gone.id: "iphone-2", kept.id: "iphone-1"])
        let after = mac(store, memory: memory)                        // Arslan restarted
        try after.remove(peer: "iphone-2")
        try await after.deleteAcknowledged()
        XCTAssertNil(store.records[gone.id], "found by the remembered recipient")
        XCTAssertNotNil(store.records[kept.id])
        XCTAssertEqual(memory.memory?.awaitingAck, [kept.id])
        XCTAssertEqual(memory.memory?.awaitingTo, [kept.id: "iphone-1"])
    }

    func testAtStartUpWhatWaitsForAPhoneNoLongerPairedIsDeleted() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let before = mac(store, memory: memory)
        let gone = try await before.send(type: "status.snapshot", body: [:], to: "iphone-2")
        let kept = try await before.send(type: "status.snapshot", body: [:], to: "iphone-1")
        let after = mac(store, memory: memory, peers: ["iphone-1"])   // iphone-2 was removed by a Bridge that kept its records
        let dropped = try await after.dropOrphans()
        try await after.deleteAcknowledged()
        XCTAssertEqual(dropped, 1)
        XCTAssertNil(store.records[gone.id])
        XCTAssertNotNil(store.records[kept.id], "a paired phone's record is never touched")
        XCTAssertEqual(memory.memory?.awaitingAck, [kept.id])
    }

    func testTheCleanUpAlsoCoversWhatThisRunSent() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let mac = mac(store, memory: memory)
        let gone = try await mac.send(type: "status.snapshot", body: [:], to: "iphone-2")
        let kept = try await mac.send(type: "status.snapshot", body: [:], to: "iphone-1")
        mac.peers["iphone-2"] = nil                                   // no longer paired, its record still waiting
        let dropped = try await mac.dropOrphans()
        try await mac.deleteAcknowledged()
        XCTAssertEqual(dropped, 1)
        XCTAssertNil(store.records[gone.id])
        XCTAssertNotNil(store.records[kept.id])
        XCTAssertEqual(mac.unacknowledged.map(\.id), [kept.id])
    }

    func testIdsRememberedWithoutARecipientAreLookedUpAndOnlyAnUnpairedPhonesAreDeleted() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let before = mac(store, memory: memory)
        let gone = try await before.send(type: "status.snapshot", body: [:], to: "iphone-2")
        let kept = try await before.send(type: "status.snapshot", body: [:], to: "iphone-1")
        var legacy = try XCTUnwrap(memory.memory)                     // as a Bridge before 2026-10-07 wrote it
        legacy.awaitingTo = [:]
        legacy.awaitingAck.append("already-gone")
        memory.memory = legacy
        let after = mac(store, memory: memory, peers: ["iphone-1"])
        let dropped = try await after.dropOrphans()
        XCTAssertEqual(dropped, 1)
        try await after.deleteAcknowledged()
        XCTAssertNil(store.records[gone.id], "its recipient read from the store: a phone no longer paired")
        XCTAssertNotNil(store.records[kept.id])
        XCTAssertEqual(memory.memory?.awaitingAck, [kept.id], "an id the store no longer has stops being waited for")
        XCTAssertEqual(memory.memory?.awaitingTo, [kept.id: "iphone-1"], "and the looked-up recipient is kept from now on")
    }

    func testWhenTheLookupFailsNothingIsDeleted() async throws {
        final class NoLookup: EnvelopeStore {
            let inner = MemoryStore()
            var deleted: [String] = []
            func save(_ record: EnvelopeRecord) async throws { try await inner.save(record) }
            func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) { try await inner.changes(since: token) }
            func delete(ids: [String]) async throws { deleted += ids; try await inner.delete(ids: ids) }
            func ages() async throws -> [(id: String, createdAt: Date)] { try await inner.ages() }
            func recipients(of ids: [String]) async throws -> [String: String] { throw URLError(.notConnectedToInternet) }
        }
        let store = NoLookup(), memory = InMemoryMemoryStore()
        let before = mac(store, memory: memory)
        let a = try await before.send(type: "status.snapshot", body: [:], to: "iphone-2")
        let b = try await before.send(type: "status.snapshot", body: [:], to: "iphone-1")
        var legacy = try XCTUnwrap(memory.memory); legacy.awaitingTo = [:]; memory.memory = legacy
        let after = mac(store, memory: memory, peers: ["iphone-1"])
        do { _ = try await after.dropOrphans(); XCTFail("offline") } catch {}
        try after.remove(peer: "iphone-2")                            // nor does a removal guess
        try await after.deleteAcknowledged()
        XCTAssertEqual(store.deleted, [])
        XCTAssertEqual(Set(memory.memory?.awaitingAck ?? []), [a.id, b.id], "still waited for; looked up again next start")
    }

    func testAFileFromAnOlderBridgeStillLoads() throws {
        let old = #"{"nextSeq": 42, "windows": {}, "processed": ["p"], "awaitingAck": ["a1"], "toDelete": [], "token": "AQI="}"#
        let memory = try JSONDecoder().decode(MailboxMemory.self, from: Data(old.utf8))
        XCTAssertEqual(memory.nextSeq, 42)
        XCTAssertEqual(memory.processed, ["p"], "what was acted on is not forgotten (it would run twice)")
        XCTAssertEqual(memory.awaitingAck, ["a1"])
        XCTAssertEqual(memory.awaitingTo, [:]); XCTAssertEqual(memory.heard, [:])
        XCTAssertEqual(memory.token, Data([1, 2]))
    }
}
