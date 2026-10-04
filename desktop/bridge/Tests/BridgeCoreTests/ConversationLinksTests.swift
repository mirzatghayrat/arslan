import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class FakeChannel: ControlChannel {
    var sent: [[String: Any]] = []
    var failures = 0                                   // the next N sends fail (socket not up yet)
    let onFrame: ([String: Any]) async -> Void
    init(onFrame: @escaping ([String: Any]) async -> Void) { self.onFrame = onFrame }
    func send(_ frame: [String: Any]) async throws {
        if failures > 0 { failures -= 1; throw BridgeError.code("mac_busy") }
        sent.append(frame)
    }
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

final class FakeBackend: BackendReads {
    var answers: [String: Result<[String: Any], BridgeError>] = [:]
    var asked: [String] = []
    func json(_ path: String) async throws -> [String: Any] {
        asked.append(path)
        guard let answer = answers[path] else { throw BridgeError.code("mac_busy") }
        return try answer.get()
    }
}

final class ConversationLinksTests: XCTestCase {
    func setUpPair(backend: BackendReads = NoBackend()) -> (MemoryStore, Mailbox, Mailbox, FakeChannels, ConversationLinks) {
        let store = MemoryStore()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let channels = FakeChannels()
        return (store, mac, phone, channels, ConversationLinks(channels: channels, mailbox: mac, backend: backend))
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
        try await phone.send(type: "status.subscribe", body: [:], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let errors = try await phone.receive().filter { $0.type == "error" }
        XCTAssertEqual(errors.compactMap { ($0.envelope["body"] as? [String: Any])?["code"] as? String }.sorted(),
                       ["approval_expired", "unknown_type"])
        XCTAssertTrue(errors.allSatisfy { _ in Wire.shouldNotify(type: "error", body: [:]) })
    }

    func body(_ r: Received) -> [String: Any] { r.envelope["body"] as? [String: Any] ?? [:] }

    func testTheListAndAHistoryGoBackToThePhoneThatAsked() async throws {
        let backend = FakeBackend()
        let list: [String: Any] = ["conversations": [["id": "trip", "title": "Trip", "updated_at": "2026-10-03T09:30:15Z"]]]
        let history: [String: Any] = ["conversation_id": "pocket", "messages": [
            ["id": "3", "role": "assistant", "text": "Done.", "ts": "2026-10-03T09:30:15Z", "attachments": []]]]
        backend.answers["/api/v1/phone/conversations?limit=100"] = .success(list)
        backend.answers["/api/v1/phone/conversations/pocket/history?limit=50"] = .success(history)
        backend.answers["/api/v1/phone/conversations/a%20b%2Fc/history?limit=1"] = .success(["conversation_id": "a b/c", "messages": []])
        let (_, mac, phone, _, links) = setUpPair(backend: backend)
        try await phone.send(type: "conversations.list", body: ["limit": 500], to: "mac-1")
        try await phone.send(type: "chat.history", body: ["limit": 50], to: "mac-1")          // no id: the pocket conversation
        try await phone.send(type: "chat.history", body: ["conversation_id": "a b/c", "limit": 0], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["conversations.result", "chat.history.result", "chat.history.result"])
        XCTAssertEqual((body(got[0])["conversations"] as? [[String: Any]])?.first?["title"] as? String, "Trip")
        XCTAssertEqual((body(got[1])["messages"] as? [[String: Any]])?.first?["id"] as? String, "3")
        XCTAssertEqual(body(got[2])["conversation_id"] as? String, "a b/c", "an id is one path segment, never a path")
        XCTAssertTrue(got.allSatisfy { !Wire.shouldNotify(type: $0.type, body: body($0)) }, "history never rings")
    }

    func testAFileComesWithItsEncryptedBytesAndOnlyIfTheyMatch() async throws {
        let bytes = Data("# Day 1\n".utf8)
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let file: [String: Any] = ["id": "run_7_ab_plan.md", "name": "plan.md", "size": bytes.count,
                                   "mime_type": "text/markdown", "sha256": digest]
        let backend = FakeBackend()
        backend.answers["/api/v1/phone/files/run_7_ab_plan.md"] = .success(["file": file, "data": bytes.base64EncodedString()])
        backend.answers["/api/v1/phone/files/run_7_cd_changed.md"] = .success(
            ["file": file.merging(["id": "run_7_cd_changed.md"]) { _, b in b }, "data": Data("other".utf8).base64EncodedString()])
        backend.answers["/api/v1/phone/files/run_9_gone.md"] = .failure(.code("file_unavailable"))
        let (_, mac, phone, _, links) = setUpPair(backend: backend)
        for id in ["run_7_ab_plan.md", "run_7_cd_changed.md", "run_9_gone.md"] {
            try await phone.send(type: "file.get", body: ["file_id": id], to: "mac-1")
        }
        for received in try await mac.receive() { await links.handle(received) }
        let got = try await phone.receive()
        let offer = try XCTUnwrap(got.first { $0.type == "file.offer" })
        XCTAssertEqual(offer.asset, bytes, "decrypted by the phone's own key, checked against the header's hash")
        XCTAssertEqual(body(offer)["sha256"] as? String, digest)
        let errors = got.filter { $0.type == "error" }.map { body($0)["code"] as? String }
        XCTAssertEqual(errors, ["file_unavailable", "file_unavailable"], "changed bytes are never sent under the old reference")
    }

    func testAFinishedTurnOffersItsFilesWithoutTheirBytes() async throws {
        let backend = FakeBackend()
        let file: [String: Any] = ["id": "run_7_ab_plan.md", "name": "plan.md", "size": 8, "mime_type": "text/markdown", "sha256": "00"]
        backend.answers["/api/v1/phone/runs/7/files"] = .success(["files": [file]])
        let (_, mac, phone, channels, links) = setUpPair(backend: backend)
        try await phone.send(type: "chat.send", body: ["text": "plan", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let pocket = try XCTUnwrap(channels.opened["pocket"])
        await pocket.onFrame(["type": "stream_start"])
        await pocket.onFrame(["type": "stream_chunk", "content": "Here."])
        await pocket.onFrame(["type": "stream_end", "message_id": 3, "run_id": 7])
        await pocket.onFrame(["type": "stream_end", "message_id": 4])          // no run, nothing to ask
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["chat.event", "file.offer", "chat.event"])
        XCTAssertNil(got[1].asset)
        XCTAssertEqual(body(got[1])["id"] as? String, "run_7_ab_plan.md")
        XCTAssertEqual(backend.asked, ["/api/v1/phone/runs/7/files"])
    }

    func testAnErrorFromThePhoneIsNeverAnsweredWithAnError() async throws {
        let (_, mac, phone, _, links) = setUpPair()
        try await phone.send(type: "error", body: ["code": "unknown_type", "message": "?"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let got = try await phone.receive()
        XCTAssertTrue(got.filter { $0.type != "ack" }.isEmpty)
    }

    func testAMessageThatDidNotGoThroughRunsOnThePhonesRetry() async throws {
        let (_, mac, phone, channels, links) = setUpPair()
        let pocket = channels.open(conversationID: "pocket") { _ in } as! FakeChannel
        pocket.failures = 1
        let message: [String: Any] = ["text": "在干嘛", "attachments": [], "client_msg_id": "c1"]
        try await phone.send(type: "chat.send", body: message, to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        XCTAssertTrue(pocket.sent.isEmpty)
        let heard = try await phone.receive()
        XCTAssertEqual(heard.filter { $0.type == "error" }.count, 1, "the phone hears it failed")
        try await phone.send(type: "chat.send", body: message, to: "mac-1")          // the phone's retry
        try await phone.send(type: "chat.send", body: message, to: "mac-1")          // and a duplicate after it
        for received in try await mac.receive() { await links.handle(received) }
        XCTAssertEqual(pocket.sent.compactMap { $0["content"] as? String }, ["在干嘛"], "once, on the retry")
    }
}
