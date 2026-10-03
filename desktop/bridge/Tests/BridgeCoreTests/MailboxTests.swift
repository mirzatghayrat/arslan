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
