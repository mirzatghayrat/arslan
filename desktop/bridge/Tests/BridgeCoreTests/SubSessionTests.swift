// §5.13 (SUB5f): a phone reads a sub-session and never writes to one.
import Foundation
import XCTest
@testable import BridgeCore

extension ConversationLinksTests {
    func testASubSessionsHistoryIsReadThroughItsCommanderAndNeverLinked() async throws {
        let backend = FakeBackend()
        let path = "/api/v1/phone/conversations/c3/sub-sessions/sub-1/history?limit=200"
        backend.answers[path] = .success(["conversation_id": "c3", "sub_session_id": "sub-1", "view_only": true, "messages": [
            ["id": "m7", "role": "user", "text": "Draft", "ts": "2026-10-03T00:00:00Z", "attachments": [], "source": "commander"]]])
        backend.answers["/api/v1/phone/conversations/c3/sub-sessions/elsewhere/history?limit=50"] = .failure(.code("not_found"))
        let (_, mac, phone, channels, links) = setUpPair(backend: backend)
        try await phone.send(type: "sub_session.history", body: ["conversation_id": "c3", "sub_session_id": "sub-1", "limit": 900],
                             to: "mac-1")
        try await phone.send(type: "sub_session.history", body: ["conversation_id": "c3", "sub_session_id": "elsewhere"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["sub_session.history.result", "error"])
        XCTAssertEqual(body(got[0])["view_only"] as? Bool, true)
        XCTAssertEqual(body(got[1])["code"] as? String, "not_found", "outside the commander's tree")
        XCTAssertEqual(backend.asked, [path, "/api/v1/phone/conversations/c3/sub-sessions/elsewhere/history?limit=50"])
        XCTAssertTrue(channels.opened.isEmpty, "a read never links: no socket, so nothing reaches the sub-session")
        XCTAssertTrue(backend.posted.isEmpty)
    }

    /// No write twin: the phone's words to a sub-session's id stay `not_found` (the Mac's history read refuses it, so
    /// it is never linked), and no request writes to a sub-session.
    func testAPhoneNeverWritesToASubSession() async throws {
        let backend = FakeBackend()
        backend.answers["/api/v1/phone/conversations/sub-1/history?limit=1"] = .failure(.code("not_found"))
        let (_, mac, phone, channels, links) = setUpPair(backend: backend)
        try await phone.send(type: "chat.send", body: ["conversation_id": "sub-1", "text": "go", "attachments": [],
                                                       "client_msg_id": "c1"], to: "mac-1")
        for type in ["sub_session.send", "sub_session.message", "sub_session.stop"] {
            try await phone.send(type: type, body: ["conversation_id": "c3", "sub_session_id": "sub-1", "text": "go"], to: "mac-1")
        }
        for received in try await mac.receive() { await links.handle(received) }
        let codes = try await phone.receive().map { body($0)["code"] as? String }
        XCTAssertEqual(codes, ["not_found", "unknown_type", "unknown_type", "unknown_type"])
        XCTAssertTrue(channels.opened.isEmpty)
        XCTAssertTrue(backend.posted.isEmpty)
        XCTAssertTrue(ConversationLinks.capabilities.contains("sub_sessions"))
    }
}
