import Foundation
import XCTest
@testable import BridgeCore

/// Q1b (docs/plans/0164/Q1-quick-ask.md, "Frame names, fixed"): quick questions and new conversations from the
/// phone, paging the list, turning a quick question into a chat, deleting the pocket, and the phone's send time.
final class QuickAskTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)
    static let quickPhone = PhoneFilesTests.newPhone + ["quick"]
    static let id = "phone-0b0c1d2e-3f40-4152-8a6b-7c8d9e0fa1b2"
    static let other = "phone-1b0c1d2e-3f40-4152-8a6b-7c8d9e0fa1b2"
    static let quickPath = "/api/v1/phone/conversations/\(id)/quick"

    struct Pair {
        let mac: Mailbox, phone: Mailbox, channels: ClosingChannels, backend: FilesBackend, links: ConversationLinks
    }

    func pair(capabilities: [String]? = QuickAskTests.quickPhone) async throws -> Pair {
        let store = MemoryStore(), backend = FilesBackend(), channels = ClosingChannels()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let links = ConversationLinks(channels: channels, mailbox: mac, backend: backend)
        if let capabilities {
            try await phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": capabilities], to: "mac-1")
            for received in try await mac.receive() { await links.handle(received, now: t0) }
            _ = try await phone.receive()
        }
        backend.asked = []
        return Pair(mac: mac, phone: phone, channels: channels, backend: backend, links: links)
    }

    @discardableResult
    func run(_ p: Pair) async throws -> [Received] {
        let got = try await p.mac.receive()
        for received in got { await p.links.handle(received, now: t0) }
        return got
    }

    func body(_ r: Received) -> [String: Any] { r.envelope["body"] as? [String: Any] ?? [:] }

    func heard(_ p: Pair) async throws -> [Received] { try await p.phone.receive().filter { $0.type != "ack" } }

    func errors(_ got: [Received]) -> [(code: String?, related: String?)] {
        got.filter { $0.type == "error" }.map { (body($0)["code"] as? String, body($0)["related_id"] as? String) }
    }

    func send(_ p: Pair, _ body: [String: Any]) async throws -> String {
        try await p.phone.send(type: "chat.send", body: body, to: "mac-1").id
    }

    func quick(_ text: String, client: String, id: String = QuickAskTests.id) -> [String: Any] {
        ["new_conversation_id": id, "conversation_kind": "quick", "text": text, "attachments": [], "client_msg_id": client]
    }

    func words(_ p: Pair, _ conversation: String) -> [String?] {
        p.channels.opened[conversation]?.sent.map { $0["content"] as? String } ?? []
    }

    // ------------------------------------------------------------------ hello

    func testTheMacSaysItTakesNewConversationsAndQuickQuestions() async throws {
        let p = try await pair(capabilities: nil)
        try await p.phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": []], to: "mac-1")
        try await run(p)
        let got = try await heard(p)
        let hello = try XCTUnwrap(got.first { $0.type == "hello" })
        XCTAssertTrue(Set(body(hello)["capabilities"] as? [String] ?? []).isSuperset(of: ["new_conversation", "quick"]))
    }

    // ------------------------------------------------------------------ chat.send

    func testANewQuickQuestionIsStoredFirstThenItsWordsGoToItsOwnConversation() async throws {
        let p = try await pair()
        p.backend.answers["POST " + Self.quickPath] = .success(["conversation_id": Self.id, "kind": "quick"])
        _ = try await send(p, quick("ramen near me?", client: "c1"))
        _ = try await send(p, quick("ramen near me?", client: "c1"))         // the phone's retry
        try await run(p)
        XCTAssertEqual(p.backend.posted.map(\.0), [Self.quickPath], "stored once")
        XCTAssertEqual(words(p, Self.id), ["ramen near me?"], "the same client_msg_id runs once")
        XCTAssertNil(p.channels.opened[ConversationLinks.pocket], "never the pocket")
    }

    func testWhenTheMacCannotStoreItTheWordsNeverReachArslan() async throws {
        for code in ["conversation_exists", "mac_busy", "bad_request"] {
            let p = try await pair()
            p.backend.answers["POST " + Self.quickPath] = .failure(.code(code))
            let sent = try await send(p, quick("ramen near me?", client: "c1"))
            try await run(p)
            XCTAssertTrue(p.channels.opened.values.allSatisfy { $0.sent.isEmpty }, "\(code): nothing went to Arslan")
            let refused = errors(try await heard(p))
            XCTAssertEqual(refused.map(\.code), [code])
            XCTAssertEqual(refused.map(\.related), [sent])
        }
    }

    func testRequestsTheMacCannotReadAreRefusedBeforeAnythingIsStoredOrSent() async throws {
        let p = try await pair()
        let cases: [[String: Any]] = [
            ["conversation_kind": "quick", "text": "a", "attachments": [], "client_msg_id": "b1"],     // a kind with no new id
            quick("b", client: "b2").merging(["conversation_kind": "sub"]) { $1 },                     // a kind there is not
            quick("c", client: "b3", id: "phone-123"),                                                 // not phone-<uuid>
            quick("d", client: "b4", id: "phone-0B0C1D2E-3F40-4152-8A6B-7C8D9E0FA1B2"),                 // not lowercase
            quick("e", client: "b5", id: "c-42"),
            quick("f", client: "b6").merging(["conversation_id": "c-42"]) { $1 },                      // two different ids
            quick("g", client: "b7", id: Self.id + "\n"),                                              // a line break after it
            quick("h", client: "b8", id: Self.id + "\r\n"),
            quick("i", client: "b9", id: Self.id + "\u{2028}"),
            quick("j", client: "b10", id: "x" + Self.id),                                              // something before it
            quick("k", client: "b11", id: "\n" + Self.id),
            quick("l", client: "b12", id: "phone-0b0c1d2e-3f40-1152-8a6b-7c8d9e0fa1b2"),               // a v1 UUID
            quick("m", client: "b13", id: "phone-0b0c1d2e-3f40-4152-7a6b-7c8d9e0fa1b2"),               // not the RFC variant
        ]
        var ids: [String] = []
        for c in cases { ids.append(try await send(p, c)) }
        try await run(p)
        XCTAssertTrue(p.backend.posted.isEmpty && p.backend.asked.isEmpty, "nothing stored or looked up")
        XCTAssertTrue(p.channels.opened.values.allSatisfy { $0.sent.isEmpty }, "nothing sent, not even to the pocket")
        let refused = errors(try await heard(p))
        XCTAssertEqual(refused.map(\.code), Array(repeating: "bad_request", count: cases.count))
        XCTAssertEqual(refused.map(\.related), ids)
    }

    func testTheSameIDTwiceIsOneConversation() async throws {
        let p = try await pair()
        p.backend.answers["POST " + Self.quickPath] = .success(["conversation_id": Self.id, "kind": "quick"])
        _ = try await send(p, quick("ramen?", client: "d1").merging(["conversation_id": Self.id]) { $1 })
        try await run(p)
        XCTAssertEqual(words(p, Self.id), ["ramen?"])
    }

    func testANewOrdinaryConversationGoesToItsOwnIDOnlyWhileItIsEmpty() async throws {
        let p = try await pair()
        p.backend.answers["/api/v1/phone/conversations/\(Self.id)/history?limit=1"] = .success(
            ["conversation_id": Self.id, "messages": []])
        p.backend.answers["/api/v1/phone/conversations/\(Self.other)/history?limit=1"] = .success(
            ["conversation_id": Self.other, "messages": [["id": "1", "role": "user", "text": "hi"]]])
        _ = try await send(p, ["new_conversation_id": Self.id, "text": "plan a trip", "attachments": [], "client_msg_id": "n1"])
        let taken = try await send(p, ["new_conversation_id": Self.other, "text": "hello", "attachments": [], "client_msg_id": "n2"])
        try await run(p)
        XCTAssertEqual(words(p, Self.id), ["plan a trip"])
        XCTAssertTrue(p.backend.posted.isEmpty, "an ordinary one is not stored as quick")
        XCTAssertEqual(words(p, Self.other), [], "never into a conversation that has messages")
        let refused = errors(try await heard(p))
        XCTAssertEqual(refused.map(\.code), ["conversation_exists"])
        XCTAssertEqual(refused.map(\.related), [taken])
    }

    /// §5.8: a refused send is not remembered as run, so the phone's retry runs it; a retry that dropped `quick`
    /// would start an ordinary chat with every tool, and nothing stored as quick.
    func testARetryThatDropsQuickIsRefusedAndOneThatRepeatsItRuns() async throws {
        let p = try await pair()
        p.backend.answers["POST " + Self.quickPath] = .failure(.code("mac_busy"))
        p.backend.answers["/api/v1/phone/conversations/\(Self.id)/history?limit=1"] = .success(
            ["conversation_id": Self.id, "messages": []])
        var dropped = quick("ramen near me?", client: "c1")
        dropped["conversation_kind"] = nil
        var refused = [try await send(p, quick("ramen near me?", client: "c1"))]
        try await run(p)
        for _ in 0..<2 { refused.append(try await send(p, dropped)) }               // a second try changes nothing
        try await run(p)
        XCTAssertTrue(p.backend.asked.isEmpty, "never looked up as an ordinary conversation")
        XCTAssertEqual(words(p, Self.id), [], "Arslan never sees it")
        let got = errors(try await heard(p))
        XCTAssertEqual(got.map(\.code), ["mac_busy", "bad_request", "bad_request"])
        XCTAssertEqual(got.map(\.related), refused)

        p.backend.answers["POST " + Self.quickPath] = .success(["conversation_id": Self.id, "kind": "quick"])
        _ = try await send(p, quick("ramen near me?", client: "c1"))
        try await run(p)
        XCTAssertEqual(p.backend.posted.map(\.0), [Self.quickPath, Self.quickPath], "stored as quick on the retry")
        XCTAssertEqual(words(p, Self.id), ["ramen near me?"])
    }

    func testARetryThatAddsQuickIsRefusedToo() async throws {
        let p = try await pair()
        p.backend.answers["POST " + Self.quickPath] = .success(["conversation_id": Self.id, "kind": "quick"])
        let ordinary: [String: Any] = ["new_conversation_id": Self.id, "text": "plan a trip", "attachments": [], "client_msg_id": "n1"]
        let first = try await send(p, ordinary)                                     // its history lookup fails
        try await run(p)
        let added = try await send(p, quick("plan a trip", client: "n1"))
        try await run(p)
        XCTAssertTrue(p.backend.posted.isEmpty, "never stored as quick")
        XCTAssertTrue(p.channels.opened.values.allSatisfy { $0.sent.isEmpty })
        let got = errors(try await heard(p))
        XCTAssertEqual(got.map(\.code), ["mac_busy", "bad_request"])
        XCTAssertEqual(got.map(\.related), [first, added])
    }

    func testANewConversationWhoseHistoryCannotBeReadIsRefused() async throws {
        let p = try await pair()                                                    // the lookup fails: the Mac is busy
        let sent = try await send(p, ["new_conversation_id": Self.id, "text": "plan a trip", "attachments": [], "client_msg_id": "n1"])
        try await run(p)
        XCTAssertEqual(p.backend.asked, ["/api/v1/phone/conversations/\(Self.id)/history?limit=1"])
        XCTAssertTrue(p.channels.opened.values.allSatisfy { $0.sent.isEmpty }, "not sent, not even to the pocket")
        let got = errors(try await heard(p))
        XCTAssertEqual(got.map(\.code), ["mac_busy"])
        XCTAssertEqual(got.map(\.related), [sent])
    }

    func testThePhonesSendTimeGoesWithItsWords() async throws {
        let p = try await pair()
        _ = try await send(p, ["text": "hi", "attachments": [], "client_msg_id": "s1"])
        let got = try await run(p)
        let ts = try XCTUnwrap(got.first { $0.type == "chat.send" }?.envelope["ts"] as? String)
        XCTAssertEqual(p.channels.opened[ConversationLinks.pocket]?.sent.first?["sent_at"] as? String, ts,
                       "INB2's presence check reads it (server/services/presence.py)")
    }

    // ------------------------------------------------------------------ the list

    func testTheListPassesKindAndBeforeAndBringsBackHasMore() async throws {
        let p = try await pair()
        let before = "2026-10-29T10:00:00+05:00"
        let path = "/api/v1/phone/conversations?limit=20&kind=quick&before=2026-10-29T10%3A00%3A00%2B05%3A00"
        p.backend.answers[path] = .success(["conversations": [["id": Self.id, "title": "Ramen", "updated_at": before, "kind": "quick"]],
                                            "has_more": true])
        try await p.phone.send(type: "conversations.list", body: ["limit": 20, "kind": "quick", "before": before], to: "mac-1")
        let unknown = try await p.phone.send(type: "conversations.list", body: ["limit": 20, "kind": "sub"], to: "mac-1").id
        try await run(p)
        XCTAssertEqual(p.backend.asked.first, path, "a + in the time must not reach the server as a space")
        XCTAssertFalse(p.backend.asked.contains { $0.contains("kind=sub") })
        let got = try await heard(p)
        let result = try XCTUnwrap(got.first { $0.type == "conversations.result" })
        XCTAssertEqual(body(result)["has_more"] as? Bool, true)
        XCTAssertEqual(errors(got).map(\.code), ["bad_request"])
        XCTAssertEqual(errors(got).map(\.related), [unknown])
    }

    // ------------------------------------------------------------------ conversation.update

    func testAQuickQuestionTurnsIntoAChat() async throws {
        let p = try await pair()
        let path = "/api/v1/phone/conversations/\(Self.id)/update"
        p.backend.answers["POST " + path] = .success(["conversation_id": Self.id, "kind": "chat"])
        p.backend.answers["POST /api/v1/phone/conversations/c-gone/update"] = .failure(.code("not_found"))
        p.backend.answers["POST /api/v1/phone/conversations/c-busy/update"] = .failure(.code("mac_busy"))
        try await p.phone.send(type: "conversation.update", body: ["conversation_id": Self.id, "kind": "chat"], to: "mac-1")
        var refused: [String] = []
        for b: [String: Any] in [["conversation_id": "c-gone", "kind": "chat"], ["conversation_id": "c-busy", "kind": "chat"],
                                 ["conversation_id": Self.id, "kind": "quick"], ["kind": "chat"]] {
            refused.append(try await p.phone.send(type: "conversation.update", body: b, to: "mac-1").id)
        }
        try await run(p)
        XCTAssertEqual(p.backend.posted.map(\.0), [path, "/api/v1/phone/conversations/c-gone/update",
                                                   "/api/v1/phone/conversations/c-busy/update"])
        XCTAssertEqual(p.backend.posted.first?.1 as? [String: String], ["kind": "chat"])
        let got = try await heard(p)
        let updated = try XCTUnwrap(got.first { $0.type == "conversation.updated" })
        XCTAssertEqual(body(updated)["conversation_id"] as? String, Self.id)
        XCTAssertEqual(body(updated)["kind"] as? String, "chat")
        XCTAssertEqual(errors(got).map(\.code), ["not_found", "mac_busy", "bad_request", "malformed"])
        XCTAssertEqual(errors(got).map(\.related), refused)
    }

    // ------------------------------------------------------------------ the pocket

    /// Two phones on one Mac: only the one that said `quick` lists its own conversations without Remote.
    func testOnlyThePhoneThatSaidQuickMayDeleteThePocket() async throws {
        let p = try await pair(capabilities: PhoneFilesTests.newPhone)
        let second = Mailbox(deviceID: "iphone-2", signing: .init(), exchange: .init(), store: p.mac.store)
        p.mac.add(peer: Peer(deviceID: "iphone-2", signing: second.signing.publicKey, exchange: second.exchange.publicKey))
        second.add(peer: Peer(deviceID: "mac-1", signing: p.mac.signing.publicKey, exchange: p.mac.exchange.publicKey))
        try await second.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": Self.quickPhone], to: "mac-1")
        try await run(p)
        _ = try await second.receive()
        p.backend.answers["DELETE /api/v1/conversations/pocket"] = .success(["ok": true, "deleted": ["arslan_messages": 3]])

        try await p.phone.send(type: "conversation.delete", body: ["conversation_id": "pocket"], to: "mac-1")
        try await run(p)
        XCTAssertEqual(p.backend.deleted, [], "the phone that never said quick still shows Remote")
        let first = try await heard(p)
        XCTAssertEqual(first.map(\.type), ["error"])

        try await second.send(type: "conversation.delete", body: ["conversation_id": "pocket"], to: "mac-1")
        try await run(p)
        XCTAssertEqual(p.backend.deleted, ["/api/v1/conversations/pocket"])
        let answered = try await second.receive().filter { $0.type != "ack" }
        XCTAssertEqual(answered.map(\.type), ["conversation.deleted"])
    }

    // ------------------------------------------------------------------ the backend's answers

    func testTheBackendsAnswersBecomeTheCodesThePhoneKnows() {
        func code(_ status: Int, _ body: String = "", notFound: String = "file_unavailable") -> String? {
            do { try LocalBackend.check(status: status, data: Data(body.utf8), notFound: notFound); return nil } catch {
                return (error as? BridgeError)?.code
            }
        }
        func says(_ detail: String) -> String { #"{"detail": "\#(detail)"}"# }
        XCTAssertNil(code(200, "<html>"))
        XCTAssertEqual(code(400, says("bad_request")), "bad_request")
        XCTAssertEqual(code(409, says("conversation_exists")), "conversation_exists")
        XCTAssertEqual(code(409, says("mac_busy")), "mac_busy")
        XCTAssertEqual(code(409), "mac_busy")
        XCTAssertEqual(code(409, "<html>"), "mac_busy")
        XCTAssertEqual(code(409, #"{"detail": [{"loc": ["query", "kind"]}]}"#), "mac_busy", "a validation error names no code")
        XCTAssertEqual(code(404, says("not_found")), "not_found")
        XCTAssertEqual(code(404, says("file_unavailable")), "file_unavailable", "the file reads, as before")
        XCTAssertEqual(code(404), "file_unavailable")
        XCTAssertEqual(code(404, notFound: "not_found"), "not_found")
        XCTAssertEqual(code(413), "too_large")
        XCTAssertEqual(code(422), "malformed")
        XCTAssertEqual(code(500, says("conversation_exists")), "mac_busy")
    }

    /// LocalBackend's own request path, answered in-process: the code rides in the refusal's body.
    func testLocalBackendReadsTheCodeInTheBackendsRefusal() async throws {
        URLProtocol.registerClass(StubBackend.self)
        defer { URLProtocol.unregisterClass(StubBackend.self) }
        let backend = LocalBackend(port: StubBackend.port, token: "t")
        for (status, body, expected) in [(409, #"{"detail": "conversation_exists"}"#, "conversation_exists"),
                                         (404, #"{"detail": "not_found"}"#, "not_found"),
                                         (409, #"{"detail": "busy"}"#, "mac_busy")] {
            StubBackend.answer = (status, body)
            do {
                _ = try await backend.post(Self.quickPath, body: [:])
                XCTFail("\(status) \(body) was taken as an answer")
            } catch {
                XCTAssertEqual((error as? BridgeError)?.code, expected, body)
            }
        }
        StubBackend.answer = (200, #"{"conversation_id": "x"}"#)
        let stored = try await backend.post(Self.quickPath, body: [:])
        XCTAssertEqual(stored["conversation_id"] as? String, "x")
    }
}

/// Answers requests to one port in-process, as `answer` says (tests only).
final class StubBackend: URLProtocol {
    static let port = 9                                 // the discard port: nothing real listens there
    static var answer: (status: Int, body: String) = (200, "{}")

    override class func canInit(with request: URLRequest) -> Bool { request.url?.port == port }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url, let response = HTTPURLResponse(url: url, statusCode: Self.answer.status, httpVersion: nil,
                                                                    headerFields: ["Content-Type": "application/json"]) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(Self.answer.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
