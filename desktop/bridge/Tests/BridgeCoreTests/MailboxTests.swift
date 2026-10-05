import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class MailboxTests: XCTestCase {
    func pair(_ store: MemoryStore) -> (Mailbox, Mailbox) {
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        return (mac, phone)
    }

    func testAMessageArrivesOnceIsAcknowledgedAndThenDeleted() async throws {
        let store = MemoryStore()
        let (mac, phone) = pair(store)
        let sent = try await phone.send(type: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        XCTAssertEqual(sent.kind, "msg")
        XCTAssertFalse(sent.notify)
        let got = try await mac.receive()
        XCTAssertEqual(got.map(\.type), ["chat.send"])
        XCTAssertEqual(phone.unacknowledged.count, 1)
        _ = try await phone.receive()                         // reads the Mac's ack
        XCTAssertTrue(phone.unacknowledged.isEmpty)
        XCTAssertNil(store.records[sent.id], "the original is deleted once acknowledged")
        XCTAssertTrue(mac.unacknowledged.isEmpty, "an ack is not itself acknowledged, so nothing waits on it")
    }

    func testTheDeviceThatReadsAnAckDeletesIt() async throws {
        let store = MemoryStore()
        let (mac, phone) = pair(store)
        let sent = try await phone.send(type: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        _ = try await mac.receive()                           // acts on it, writes an ack
        let ack = try XCTUnwrap(store.records.values.first { $0.from == "mac-1" })
        _ = try await phone.receive()                         // reads the ack
        XCTAssertNil(store.records[sent.id], "the original goes on its ack")
        XCTAssertNil(store.records[ack.id], "and so does the ack: nobody acknowledges an ack, so its reader is the only one who can")
        XCTAssertTrue(store.records.isEmpty, "a delivered message leaves nothing behind in the user's iCloud")

        try await store.save(ack)                             // the same ack shows up again (a retry, a slow feed)
        _ = try await phone.receive()
        XCTAssertNil(store.records[ack.id], "a duplicate ack is deleted too")
    }

    func testTheDailySweepDeletesEverythingOlderThanAWeekWhoeverWroteIt() async throws {
        let store = MemoryStore(), memory = InMemoryMemoryStore()
        let now = Date(timeIntervalSince1970: 1_790_985_600)
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store, memoryStore: memory)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let day: TimeInterval = 24 * 3600
        let stale = try await mac.send(type: "chat.event", body: ["kind": "message"], to: "iphone-1", now: now - 8 * day)
        let fresh = try await mac.send(type: "chat.event", body: ["kind": "message"], to: "iphone-1", now: now - 6 * day)
        let strayAck = try await phone.send(type: "ack", body: ["ids": []], to: "mac-1", now: now - 9 * day)
        let removedPhones = EnvelopeRecord(id: "old-phone-record", to: "mac-1", from: "iphone-gone", seq: 1, kind: "msg",
                                           notify: false, sealed: Data("{}".utf8), createdAt: now - 30 * day)
        try await store.save(removedPhones)

        let swept = try await mac.sweep(now: now)
        XCTAssertEqual(swept.deleted, 3); XCTAssertEqual(swept.kept, 1)
        XCTAssertEqual(Set(store.records.keys), [fresh.id], "only the week-old-or-newer envelope is left")
        XCTAssertNil(store.records[strayAck.id]); XCTAssertNil(store.records[stale.id])
        XCTAssertEqual(mac.unacknowledged.map(\.id), [fresh.id], "a swept record no longer waits for an ack")
        XCTAssertEqual(memory.memory?.awaitingAck, [fresh.id], "and a restart does not wait for it either")
        let again = try await mac.sweep(now: now)
        XCTAssertEqual(again.deleted, 0); XCTAssertEqual(again.kept, 1)
    }

    func testARetriedRecordIsAcknowledgedAgainButNotActedOnTwice() async throws {
        let store = MemoryStore()
        let (mac, phone) = pair(store)
        let sent = try await phone.send(type: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        let first = try await mac.receive()
        XCTAssertEqual(first.count, 1)
        try await store.save(sent)                            // the phone re-sends the same record
        let again = try await mac.receive()
        XCTAssertTrue(again.isEmpty)
        let acks = store.records.values.filter { $0.from == "mac-1" }
        XCTAssertEqual(acks.count, 2, "one ack per delivery")
    }

    func testOnlyPairedSignersAndOwnMessagesAreOpened() async throws {
        let store = MemoryStore()
        let (mac, phone) = pair(store)
        let stranger = Mailbox(deviceID: "iphone-x", signing: .init(), exchange: .init(), store: store)
        stranger.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        try await stranger.send(type: "chat.send", body: ["text": "let me in", "attachments": [], "client_msg_id": "s"], to: "mac-1")
        try await phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": []], to: "mac-1")
        let opened = try await mac.receive()
        XCTAssertEqual(opened.map(\.type), ["hello"])
        do {
            try await mac.send(type: "chat.event", body: [:], to: "iphone-x")
            XCTFail("sent to an unpaired device")
        } catch let error as BridgeError { XCTAssertEqual(error.code, "not_paired") }
    }

    func testAFinalReplyAsksForAnAlertAndProgressDoesNot() async throws {
        let store = MemoryStore()
        let (mac, _) = pair(store)
        let progress = try await mac.send(type: "chat.event", body: ["conversation_id": "p", "kind": "progress",
            "message_id": "m", "text": "…", "final": false], to: "iphone-1")
        let final = try await mac.send(type: "chat.event", body: ["conversation_id": "p", "kind": "message",
            "message_id": "m", "text": "done", "final": true], to: "iphone-1")
        XCTAssertFalse(progress.notify)
        XCTAssertTrue(final.notify)
        XCTAssertEqual(final.seq, progress.seq + 1)
    }
}
