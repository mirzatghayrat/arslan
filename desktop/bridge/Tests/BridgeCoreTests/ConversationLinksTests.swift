import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class FakeChannel: ControlChannel {
    var sent: [[String: Any]] = []
    let onFrame: ([String: Any]) async -> Void
    init(onFrame: @escaping ([String: Any]) async -> Void) { self.onFrame = onFrame }
    func send(_ frame: [String: Any]) async throws { sent.append(frame) }
}

final class FakeChannels: ConversationChannels {
    var opened: [String: FakeChannel] = [:]
    func open(conversationID: String, onFrame: @escaping ([String: Any]) async -> Void) -> ControlChannel {
        if let c = opened[conversationID] { return c }
        let c = FakeChannel(onFrame: onFrame)
        opened[conversationID] = c
        return c
    }
}

final class ConversationLinksTests: XCTestCase {
    func setUpPair() -> (MemoryStore, Mailbox, Mailbox, FakeChannels, ConversationLinks) {
        let store = MemoryStore()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let channels = FakeChannels()
        return (store, mac, phone, channels, ConversationLinks(channels: channels, mailbox: mac))
    }

    func testThePhonesWordsGoToTheirConversationOnceMarkedFromPhone() async throws {
        let (_, mac, phone, channels, links) = setUpPair()
        try await phone.send(type: "chat.send", body: ["text": "find flights", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        try await phone.send(type: "chat.send", body: ["text": "find flights", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        try await phone.send(type: "chat.send", body: ["conversation_id": "c-42", "text": "hi", "attachments": [], "client_msg_id": "c2"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        XCTAssertEqual(channels.opened["pocket"]?.sent.count, 1, "the same client_msg_id runs once")
        XCTAssertEqual(channels.opened["pocket"]?.sent.first?["source"] as? String, "phone")
        XCTAssertEqual(channels.opened["c-42"]?.sent.first?["content"] as? String, "hi")
    }

    func testAnswersAndCardsGoBackAndTheApprovalReachesItsConversation() async throws {
        let (_, mac, phone, channels, links) = setUpPair()
        try await phone.send(type: "chat.send", body: ["text": "tidy", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let pocket = try XCTUnwrap(channels.opened["pocket"])
        await pocket.onFrame(["type": "propose_run_command", "call_id": "k1", "pretty": "rm old/", "reason": "delete"])
        await pocket.onFrame(["type": "stream_start"])
        await pocket.onFrame(["type": "stream_chunk", "content": "Done."])
        await pocket.onFrame(["type": "stream_end"])
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["approval.request", "chat.event"])
        XCTAssertEqual((got[1].envelope["body"] as? [String: Any])?["text"] as? String, "Done.")
        try await phone.send(type: "approval.answer", body: ["approval_id": "k1", "decision": "approve", "auth": "faceid", "ts": "t"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        XCTAssertEqual(pocket.sent.last?["type"] as? String, "confirm_run_command")
    }

    func testAnApprovalGoesToTheConversationThatHoldsTheCard() async throws {
        let (_, mac, phone, channels, links) = setUpPair()
        try await phone.send(type: "chat.send", body: ["text": "a", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        try await phone.send(type: "chat.send", body: ["conversation_id": "c-42", "text": "b", "attachments": [], "client_msg_id": "c2"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let other = try XCTUnwrap(channels.opened["c-42"]), pocket = try XCTUnwrap(channels.opened["pocket"])
        await other.onFrame(["type": "propose_workspace_write", "call_id": "w9", "action": "Write", "path": "a.md"])
        await pocket.onFrame(["type": "propose_schedule", "call_id": "s7", "name": "Daily", "when": "9:00"])
        _ = try await phone.receive()
        try await phone.send(type: "approval.answer", body: ["approval_id": "w9", "decision": "approve", "auth": "faceid", "ts": "t"], to: "mac-1")
        try await phone.send(type: "approval.answer", body: ["approval_id": "s7", "decision": "approve", "auth": "faceid", "ts": "t"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        // Each answer reaches the conversation that holds its card, whatever the order.
        XCTAssertEqual(other.sent.compactMap { $0["type"] as? String }.filter { $0.hasPrefix("confirm_") }, ["confirm_workspace_write"])
        XCTAssertEqual(pocket.sent.compactMap { $0["type"] as? String }.filter { $0.hasPrefix("confirm_") }, ["confirm_schedule"])
    }

    func testAnUnknownCardOrTypeAnswersWithAnError() async throws {
        let (_, mac, phone, _, links) = setUpPair()
        try await phone.send(type: "approval.answer", body: ["approval_id": "gone", "decision": "approve", "auth": "faceid", "ts": "t"], to: "mac-1")
        try await phone.send(type: "file.get", body: ["file_id": "f"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let errors = try await phone.receive().filter { $0.type == "error" }
        XCTAssertEqual(errors.compactMap { ($0.envelope["body"] as? [String: Any])?["code"] as? String }.sorted(),
                       ["approval_expired", "unknown_type"])
        XCTAssertTrue(errors.allSatisfy { _ in Wire.shouldNotify(type: "error", body: [:]) })
    }
}
