import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

/// A backend that also deletes and takes multipart uploads (§5.7).
final class FilesBackend: BackendReads {
    var answers: [String: Result<[String: Any], BridgeError>] = [:]
    var asked: [String] = []
    var posted: [(String, [String: Any])] = []
    var uploads: [(path: String, field: String, filename: String, mime: String, data: Data)] = []
    var deleted: [String] = []
    func json(_ path: String) async throws -> [String: Any] {
        asked.append(path)
        guard let answer = answers[path] else { throw BridgeError.code("mac_busy") }
        return try answer.get()
    }
    func post(_ path: String, body: [String: Any]) async throws -> [String: Any] {
        posted.append((path, body))
        if path == "/api/v1/phone/inbox", answers["POST " + path] == nil {          // saves like the real one
            let name = body["name"] as? String ?? "file"
            return ["path": "/ws/Inbox/iPhone/2026-10-13/" + name, "name": name, "mime_type": body["mime_type"] ?? "",
                    "size": Data(base64Encoded: body["data"] as? String ?? "")?.count ?? -1]
        }
        guard let answer = answers["POST " + path] else { throw BridgeError.code("mac_busy") }
        return try answer.get()
    }
    func delete(_ path: String) async throws -> [String: Any] {
        deleted.append(path)
        guard let answer = answers["DELETE " + path] else { throw BridgeError.code("mac_busy") }
        return try answer.get()
    }
    func upload(_ path: String, field: String, filename: String, mimeType: String, data: Data) async throws -> [String: Any] {
        uploads.append((path, field, filename, mimeType, data))
        guard let answer = answers["UPLOAD " + path + " " + filename] else { throw BridgeError.code("mac_busy") }
        return try answer.get()
    }
}

/// Channels that can be closed (a deleted conversation, a link no longer live).
final class ClosingChannels: ConversationChannels {
    var opened: [String: FakeChannel] = [:]
    var openCount = 0
    var closed: [String] = []
    func open(conversationID: String, onFrame: @escaping ([String: Any]) async -> Void) -> ControlChannel {
        if let c = opened[conversationID] { return c }
        openCount += 1
        let c = FakeChannel(onFrame: onFrame)
        opened[conversationID] = c
        return c
    }
    func close(conversationID: String) { closed.append(conversationID); opened[conversationID] = nil }
}

final class PhoneFilesTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)
    static let newPhone = ["partial", "mac_messages", "files_out", "delete"]

    struct Pair {
        let mac: Mailbox, phone: Mailbox, channels: ClosingChannels, backend: FilesBackend, links: ConversationLinks
    }

    func pair(capabilities: [String]? = PhoneFilesTests.newPhone) async throws -> Pair {
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
        return Pair(mac: mac, phone: phone, channels: channels, backend: backend, links: links)
    }

    func run(_ p: Pair, now: Date? = nil) async throws {
        for received in try await p.mac.receive() { await p.links.handle(received, now: now ?? t0) }
    }

    func body(_ r: Received) -> [String: Any] { r.envelope["body"] as? [String: Any] ?? [:] }

    func reference(_ id: String, _ name: String, _ data: Data, _ mime: String) -> [String: Any] {
        ["id": id, "name": name, "size": data.count, "mime_type": mime,
         "sha256": SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()]
    }

    // ------------------------------------------------------------------ hello and what each phone gets

    func testTheMacSaysWhatItCanDo() async throws {
        let p = try await pair(capabilities: nil)
        try await p.phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": []], to: "mac-1")
        try await run(p)
        let heard = try await p.phone.receive()
        let hello = try XCTUnwrap(heard.first { $0.type == "hello" })
        let caps = Set(body(hello)["capabilities"] as? [String] ?? [])
        XCTAssertTrue(caps.isSuperset(of: ["chat", "approvals", "jobs", "history", "files", "status", "review", "tasks", "touchid"]),
                      "everything it said before")
        XCTAssertTrue(caps.isSuperset(of: ["files_in", "partial", "delete", "live", "mac_messages"]))
    }

    func testOnlyAPhoneThatSaidPartialAndMacMessagesGetsThem() async throws {
        // Today's iPhone (1.0 build 17) answers an unknown chat.event kind with unknown_type and would show
        // the Mac's words as an answer: it gets neither, while a newer phone beside it gets both.
        let store = MemoryStore(), backend = FilesBackend(), channels = ClosingChannels()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        var phones: [String: Mailbox] = [:]
        for id in ["iphone-new", "iphone-old"] {
            let phone = Mailbox(deviceID: id, signing: .init(), exchange: .init(), store: store)
            mac.add(peer: Peer(deviceID: id, signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
            phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
            phones[id] = phone
        }
        let links = ConversationLinks(channels: channels, mailbox: mac, backend: backend)
        try await phones["iphone-new"]!.send(type: "hello", body: ["capabilities": Self.newPhone], to: "mac-1")
        try await phones["iphone-old"]!.send(type: "hello", body: ["capabilities": ["chat"]], to: "mac-1")
        try await phones["iphone-new"]!.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "hi", "attachments": [], "client_msg_id": "c1"], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received, now: t0) }
        for phone in phones.values { _ = try await phone.receive() }
        XCTAssertEqual(mac.capabilities["iphone-new"], Set(Self.newPhone))
        let chat = try XCTUnwrap(channels.opened["c-1"])
        await chat.onFrame(["type": "history", "messages": [["message_id": 1, "role": "user", "content": "x"]]])
        await chat.onFrame(["type": "stream_start"])
        await chat.onFrame(["type": "stream_chunk", "content": "Hel"])
        await chat.onFrame(["type": "message", "role": "user", "message_id": 5, "content": "typed on the Mac"])
        await chat.onFrame(["type": "stream_end", "message_id": 6])
        let new = try await phones["iphone-new"]!.receive().filter { $0.type == "chat.event" }.map(body)
        let old = try await phones["iphone-old"]!.receive().filter { $0.type == "chat.event" }.map(body)
        XCTAssertEqual(new.map { $0["kind"] as? String }, ["partial", "message", "message"])
        XCTAssertEqual(new[1]["role"] as? String, "user")
        XCTAssertEqual(old.map { $0["kind"] as? String }, ["message"], "the final answer only")
        XCTAssertNil(old[0]["role"])
    }

    func testCapabilitiesSurviveARestartAndGoWithThePhone() throws {
        let memory = InMemoryMemoryStore()
        let before = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: MemoryStore(), memoryStore: memory)
        before.add(peer: Peer(deviceID: "iphone-1", signing: Curve25519.Signing.PrivateKey().publicKey,
                              exchange: Curve25519.KeyAgreement.PrivateKey().publicKey))
        before.setCapabilities(["partial"], for: "iphone-1")
        let after = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: MemoryStore(), memoryStore: memory)
        XCTAssertEqual(after.capabilities["iphone-1"], ["partial"])
        try after.remove(peer: "iphone-1")
        XCTAssertNil(after.capabilities["iphone-1"])
        XCTAssertNil(memory.memory?.capabilities["iphone-1"])
        // A file written before 2026-10-13 has no capabilities: read as none.
        let old = try JSONDecoder().decode(MailboxMemory.self, from: Data(#"{"nextSeq": 5}"#.utf8))
        XCTAssertEqual(old.capabilities, [:])
    }

    func testTheMacsWordsAreReadOnlyWhenAPhoneWantsThem() async throws {
        for wants in [true, false] {
            let p = try await pair(capabilities: wants ? Self.newPhone : ["chat"])
            p.backend.answers["/api/v1/phone/conversations/c-7/history?limit=200"] = .success(["conversation_id": "c-7", "messages": []])
            p.backend.answers["/api/v1/phone/conversations/c-7/history?limit=8"] = .success(["conversation_id": "c-7", "messages": [
                ["id": "3", "role": "assistant", "text": "earlier"], ["id": "4", "role": "user", "text": "at the desk", "source": "mac"]]])
            try await p.phone.send(type: "chat.history", body: ["conversation_id": "c-7", "limit": 200], to: "mac-1")
            try await run(p)
            _ = try await p.phone.receive()
            await p.channels.opened["c-7"]?.onFrame(["type": "stream_start"])
            let events = try await p.phone.receive().filter { $0.type == "chat.event" }.map(body)
            XCTAssertEqual(p.backend.asked.contains("/api/v1/phone/conversations/c-7/history?limit=8"), wants)
            XCTAssertEqual(events.map { $0["text"] as? String }, wants ? ["at the desk"] : [])
        }
    }

    // ------------------------------------------------------------------ files from the phone

    func testAMessageWaitsForItsFilesThenGoesAsOneTurnWithPicturesAndText() async throws {
        let p = try await pair()
        let photo = Data([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]), pdf = Data("%PDF-1.7 invoice".utf8)
        p.backend.answers["UPLOAD /api/v1/extract invoice.pdf"] = .success(["text": "Total: 42 EUR", "chars": 13])
        let photoRef = reference("f-photo", "IMG_0042.jpg", photo, "image/jpeg")
        let pdfRef = reference("f-pdf", "invoice.pdf", pdf, "application/pdf")
        // The send can arrive before its files (CloudKit's order is not the phone's).
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "What is this?",
                                                         "attachments": [photoRef, pdfRef], "client_msg_id": "m1"], to: "mac-1")
        try await run(p)
        XCTAssertTrue(p.channels.opened["c-1"]?.sent.isEmpty ?? true, "held until every file is here")
        try await p.phone.send(type: "file.offer", body: photoRef, to: "mac-1", asset: photo)
        try await run(p, now: t0 + 5)
        XCTAssertTrue(p.channels.opened["c-1"]?.sent.isEmpty ?? true, "one still missing")
        try await p.phone.send(type: "file.offer", body: pdfRef, to: "mac-1", asset: pdf)
        try await run(p, now: t0 + 10)
        let sent = try XCTUnwrap(p.channels.opened["c-1"]?.sent)
        XCTAssertEqual(sent.count, 1, "one user_message")
        let frame = sent[0]
        XCTAssertEqual(frame["type"] as? String, "user_message")
        XCTAssertEqual(frame["source"] as? String, "phone")
        XCTAssertEqual(frame["content"] as? String, """
            What is this?

            Attached from iPhone: IMG_0042.jpg → /ws/Inbox/iPhone/2026-10-13/IMG_0042.jpg
            Attached from iPhone: invoice.pdf → /ws/Inbox/iPhone/2026-10-13/invoice.pdf
            """)
        let images = try XCTUnwrap(frame["images"] as? [[String: Any]])
        XCTAssertEqual(images.count, 1)
        XCTAssertEqual(images[0]["name"] as? String, "IMG_0042.jpg")
        XCTAssertEqual(images[0]["mime_type"] as? String, "image/jpeg")
        XCTAssertEqual(images[0]["data"] as? String, photo.base64EncodedString())
        XCTAssertEqual(frame["attached_context"] as? String, "=== invoice.pdf ===\nTotal: 42 EUR")
        // Saved through the backend with the bytes the phone vouched for; the text read once, by its name.
        XCTAssertEqual(p.backend.posted.filter { $0.0 == "/api/v1/phone/inbox" }.map { $0.1["name"] as? String }, ["IMG_0042.jpg", "invoice.pdf"])
        XCTAssertEqual(p.backend.posted.first?.1["sha256"] as? String, photoRef["sha256"] as? String)
        XCTAssertEqual(p.backend.uploads.map(\.filename), ["invoice.pdf"], "pictures are not sent for text")
        XCTAssertEqual(p.backend.uploads.first?.field, "file")
        XCTAssertEqual(p.backend.uploads.first?.data, pdf)
        // The phone's retry of the same message runs nothing twice.
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "What is this?",
                                                         "attachments": [photoRef, pdfRef], "client_msg_id": "m1"], to: "mac-1")
        try await run(p, now: t0 + 11)
        XCTAssertEqual(p.channels.opened["c-1"]?.sent.count, 1)
    }

    func testAFileFromThePhoneIsCheckedLikeOneFromTheMac() async throws {
        // §4.6 holds both ways: Seal.open checks the asset hash, the AEAD, the size and the sha256
        // before the Bridge ever sees the bytes. A tampered asset is dropped: nothing saved, no ack.
        let store = MemoryStore(), backend = FilesBackend()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let links = ConversationLinks(channels: ClosingChannels(), mailbox: mac, backend: backend)
        let data = Data("receipt".utf8)
        var record = try await phone.send(type: "file.offer", body: reference("f-1", "r.txt", data, "text/plain"), to: "mac-1", asset: data)
        var asset = try XCTUnwrap(record.asset)
        asset[asset.count - 1] ^= 0x01
        record.asset = asset
        try await store.save(record)
        let got = try await mac.receive()
        for received in got { await links.handle(received, now: t0) }
        XCTAssertTrue(got.isEmpty, "dropped before anything acts on it")
        XCTAssertTrue(backend.posted.isEmpty)
        // And a reference whose size or hash disagrees with intact bytes never opens either.
        let liar = reference("f-2", "r.txt", Data("other".utf8), "text/plain")
        _ = try await phone.send(type: "file.offer", body: liar, to: "mac-1", asset: data)
        let second = try await mac.receive()
        XCTAssertTrue(second.isEmpty)
    }

    func testAMessageWhoseFilesNeverCameGivesUpAfter120SecondsAndRunsOnTheRetry() async throws {
        let p = try await pair()
        let data = Data("notes".utf8)
        let ref = reference("f-late", "notes.txt", data, "text/plain")
        p.backend.answers["UPLOAD /api/v1/extract notes.txt"] = .success(["text": "notes"])
        let send = try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "read this", "attachments": [ref], "client_msg_id": "m2"], to: "mac-1")
        try await run(p)
        await p.links.flush(now: t0 + 119)
        let early = try await p.phone.receive()
        XCTAssertTrue(early.filter { $0.type == "error" }.isEmpty, "still inside its 120 s")
        await p.links.flush(now: t0 + 120)
        let late = try await p.phone.receive()
        let error = try XCTUnwrap(late.first { $0.type == "error" })
        XCTAssertEqual(body(error)["code"] as? String, "file_unavailable")
        XCTAssertEqual(body(error)["related_id"] as? String, send.id, "it answers that chat.send")
        XCTAssertTrue(p.channels.opened["c-1"]?.sent.isEmpty ?? true)
        // Not counted as done: the phone sends the file and the message again, and it runs.
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: data)
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "read this", "attachments": [ref], "client_msg_id": "m2"], to: "mac-1")
        try await run(p, now: t0 + 200)
        XCTAssertEqual(p.channels.opened["c-1"]?.sent.count, 1)
    }

    func testALaterMessageWaitsBehindOneHeldForItsFilesInTheSameConversationOnly() async throws {
        let p = try await pair()
        let data = Data([0x89, 0x50, 0x4e, 0x47])
        let ref = reference("f-png", "shot.png", data, "image/png")
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "look", "attachments": [ref], "client_msg_id": "a"], to: "mac-1")
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "and then?", "attachments": [], "client_msg_id": "b"], to: "mac-1")
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "other", "text": "meanwhile", "attachments": [], "client_msg_id": "c"], to: "mac-1")
        try await run(p)
        XCTAssertTrue(p.channels.opened["c-1"]?.sent.isEmpty ?? true, "in order: the second waits for the first")
        XCTAssertEqual(p.channels.opened["other"]?.sent.compactMap { $0["content"] as? String }, ["meanwhile"])
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: data)
        try await run(p, now: t0 + 3)
        XCTAssertEqual(p.channels.opened["c-1"]?.sent.compactMap { ($0["content"] as? String)?.components(separatedBy: "\n").first },
                       ["look", "and then?"])
    }

    func testTooManyFilesAFileWithoutBytesAndUnreadableTextAreHandled() async throws {
        let p = try await pair()
        let refs = (0..<11).map { reference("f\($0)", "f\($0).txt", Data("x".utf8), "text/plain") }
        let tooMany = try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "all", "attachments": refs, "client_msg_id": "x"], to: "mac-1")
        let bare = try await p.phone.send(type: "file.offer", body: refs[0], to: "mac-1")            // no asset
        try await run(p)
        let errors = try await p.phone.receive().filter { $0.type == "error" }.map(body)
        XCTAssertEqual(errors.map { $0["code"] as? String }, ["too_many_files", "malformed"])
        XCTAssertEqual(errors.map { $0["related_id"] as? String }, [tooMany.id, bare.id])
        // A file the backend cannot read as text is still sent: its path, and a note instead of text.
        let blob = Data([0, 1, 2])
        let ref = reference("f-bin", "data.bin", blob, "application/octet-stream")
        p.backend.answers["UPLOAD /api/v1/extract data.bin"] = .failure(.code("mac_busy"))
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: blob)
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: blob)              // offered twice
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "", "attachments": [ref], "client_msg_id": "y"], to: "mac-1")
        try await run(p)
        let frame = try XCTUnwrap(p.channels.opened["c-1"]?.sent.first)
        XCTAssertEqual(frame["content"] as? String,
                       "Attached from iPhone: data.bin → /ws/Inbox/iPhone/2026-10-13/data.bin (its text could not be read; open the file itself)")
        XCTAssertNil(frame["attached_context"])
        XCTAssertNil(frame["images"])
        XCTAssertEqual(p.backend.posted.filter { $0.0 == "/api/v1/phone/inbox" }.count, 1, "saved once")
    }

    func testAPictureIsShownOnceAndForgottenAfterTenMinutes() async throws {
        let p = try await pair()
        let photo = Data([0xff, 0xd8, 9])
        let ref = reference("f-old", "old.jpg", photo, "image/jpeg")
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: photo)
        try await run(p)
        await p.links.flush(now: t0 + 601)
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "this", "attachments": [ref], "client_msg_id": "late"], to: "mac-1")
        try await run(p, now: t0 + 602)
        let frame = try XCTUnwrap(p.channels.opened["c-1"]?.sent.first)
        XCTAssertNil(frame["images"], "its bytes were dropped after ten minutes")
        XCTAssertTrue((frame["content"] as? String ?? "").contains("old.jpg → /ws/Inbox/iPhone/2026-10-13/old.jpg (not shown"))
    }

    func testAPictureTooBigForOneMessageIsSavedButNotShown() async throws {
        let p = try await pair()
        let big = Data(repeating: 7, count: ConversationLinks.visionImageMax + 1)
        let ref = reference("f-big", "big.png", big, "image/png")
        try await p.phone.send(type: "file.offer", body: ref, to: "mac-1", asset: big)
        try await p.phone.send(type: "chat.send", body: ["conversation_id": "c-1", "text": "big", "attachments": [ref], "client_msg_id": "b"], to: "mac-1")
        try await run(p)
        let frame = try XCTUnwrap(p.channels.opened["c-1"]?.sent.first)
        XCTAssertNil(frame["images"])
        XCTAssertTrue((frame["content"] as? String ?? "").contains("(not shown to the model as a picture; open the file itself)"))
    }

    func testAHistoryTooBigForOneEnvelopeLosesItsOldestMessagesAndSaysSo() async throws {
        // The backend trims to 560 KB; slashes the Mac's JSON escapes can still push it over the
        // 800,000-byte record. Then the Bridge drops the oldest until it fits.
        let p = try await pair(capabilities: nil)
        let messages = (1...300).map { ["id": String($0), "role": "user", "text": String(repeating: "/", count: 2_000), "ts": "t",
                                        "attachments": [] as [Any]] as [String: Any] }
        p.backend.answers["/api/v1/phone/conversations/c-1/history?limit=200"] = .success(["conversation_id": "c-1", "messages": messages])
        try await p.phone.send(type: "chat.history", body: ["conversation_id": "c-1", "limit": 200], to: "mac-1")
        try await run(p)
        let got = try await p.phone.receive().filter { $0.type != "ack" }
        XCTAssertEqual(got.map(\.type), ["chat.history.result"])
        let kept = body(got[0])["messages"] as? [[String: Any]] ?? []
        XCTAssertEqual(body(got[0])["truncated"] as? Bool, true)
        XCTAssertEqual(kept.last?["id"] as? String, "300", "the newest stay")
        XCTAssertGreaterThan(kept.count, 50)
        XCTAssertLessThan(kept.count, 300)
    }

    // ------------------------------------------------------------------ delete

    func testDeletingAConversationFromThePhone() async throws {
        let p = try await pair()
        p.backend.answers["DELETE /api/v1/conversations/c-9"] = .success(["ok": true, "deleted": ["arslan_messages": 4]])
        p.backend.answers["DELETE /api/v1/conversations/gone"] = .success(["ok": true, "deleted": ["arslan_messages": 0, "arslan_summaries": 0]])
        p.backend.answers["DELETE /api/v1/conversations/c-404"] = .failure(.code("not_found"))
        p.backend.answers["/api/v1/phone/conversations/c-9/history?limit=50"] = .success(["conversation_id": "c-9", "messages": []])
        try await p.phone.send(type: "chat.history", body: ["conversation_id": "c-9", "limit": 50], to: "mac-1")
        try await run(p)
        _ = try await p.phone.receive()
        XCTAssertNotNil(p.channels.opened["c-9"])
        var ids: [String] = []
        for id in ["c-9", "pocket", "gone", "c-404"] {
            ids.append(try await p.phone.send(type: "conversation.delete", body: ["conversation_id": id], to: "mac-1").id)
        }
        let missing = try await p.phone.send(type: "conversation.delete", body: [:], to: "mac-1")
        try await run(p)
        let got = try await p.phone.receive().filter { $0.type != "ack" }
        XCTAssertEqual(got.first?.type, "conversation.deleted")
        XCTAssertEqual(body(got[0])["conversation_id"] as? String, "c-9")
        XCTAssertFalse(Wire.shouldNotify(type: got[0].type, body: body(got[0])))
        let errors = got.dropFirst().map { (body($0)["code"] as? String, body($0)["related_id"] as? String) }
        XCTAssertEqual(errors.map(\.0), ["not_found", "not_found", "not_found", "malformed"], "the retired pocket is not there (Q1 #4)")
        XCTAssertEqual(errors.map(\.1), [ids[1], ids[2], ids[3], missing.id])
        XCTAssertEqual(p.backend.deleted, ["/api/v1/conversations/c-9", "/api/v1/conversations/gone", "/api/v1/conversations/c-404"])
        XCTAssertEqual(p.channels.closed, ["c-9"], "its socket closed")
        XCTAssertEqual(ConversationLinks.message("not_found"), "That conversation is no longer on the Mac.")
    }

    func testADeletedConversationsSocketNeverReconnects() async {
        let socket = WebSocketControl(port: 9, token: "t", path: "/ws/arslan/gone")    // nothing listens on 9
        socket.stop()
        await socket.run()                       // returns at once, instead of retrying every 1…30 s for ever
        XCTAssertNil(socket.task)
    }

    // ------------------------------------------------------------------ live links

    func testTheNewestConversationsAndRunningJobsAreLinkedOnceAtStartAndAfterEachList() async throws {
        let p = try await pair(capabilities: nil)
        p.backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": ["c-1", "c-2", "task-9"]])
        p.backend.answers["/api/v1/phone/conversations?limit=100"] = .success(["conversations": []])
        await p.links.linkLive(now: t0)
        XCTAssertEqual(Set(p.channels.opened.keys), ["c-1", "c-2", "task-9"])
        try await p.phone.send(type: "conversations.list", body: ["limit": 100], to: "mac-1")
        try await run(p)
        p.backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": ["c-3", "c-1"]])
        try await p.phone.send(type: "conversations.list", body: ["limit": 100], to: "mac-1")
        try await run(p)
        XCTAssertEqual(Set(p.channels.opened.keys), ["c-1", "c-2", "task-9", "c-3"])
        XCTAssertEqual(p.channels.openCount, 4, "never opened twice")
        XCTAssertEqual(p.backend.asked.filter { $0.hasPrefix("/api/v1/phone/live") }.count, 3)
        let result = try await p.phone.receive().filter { $0.type == "conversations.result" }
        XCTAssertEqual(result.count, 2, "the list itself still answers")
    }

    func testNoPhoneNoSockets() async {
        let backend = FilesBackend(), channels = ClosingChannels()
        backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": ["c-1"]])
        let lonely = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: MemoryStore())
        await ConversationLinks(channels: channels, mailbox: lonely, backend: backend).linkLive(now: t0)
        XCTAssertTrue(channels.opened.isEmpty)
        XCTAssertEqual(backend.asked, [])
    }

    func testOldIdleLinksAreClosedPastTheCapNeverOneWithACard() async throws {
        let p = try await pair(capabilities: nil)
        let many = (0..<(ConversationLinks.maxLinks + 5)).map { "old-\($0)" }
        p.backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": many])
        await p.links.linkLive(now: t0)
        await p.channels.opened["old-0"]?.onFrame(["type": "propose_schedule", "call_id": "s1", "name": "n", "when": "w"])
        p.backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": ["new-1"]])
        await p.links.linkLive(now: t0 + 60)
        XCTAssertEqual(p.channels.closed, [], "touched a minute ago: kept")
        await p.links.linkLive(now: t0 + 3600)
        XCTAssertEqual(p.channels.opened.count, ConversationLinks.maxLinks)
        XCTAssertNotNil(p.channels.opened["old-0"], "a card waits there")
        XCTAssertNotNil(p.channels.opened["new-1"], "live")
    }

    // ------------------------------------------------------------------ the Mac's files, attached to their answer

    func testFilesMadeByATurnOrAJobSayWhichAnswerTheyBelongTo() async throws {
        let p = try await pair(capabilities: nil)
        let file: [String: Any] = ["id": "run_7_ab_plan.md", "name": "plan.md", "size": 8, "mime_type": "text/markdown", "sha256": "00"]
        p.backend.answers["/api/v1/phone/runs/7/files"] = .success(["files": [file]])
        p.backend.answers["/api/v1/phone/runs/8/files"] = .success(["files": [file.merging(["id": "run_8_x.csv"]) { _, b in b }]])
        p.backend.answers["/api/v1/phone/runs/9/files"] = .success(["files": [file.merging(["id": "run_9_y.txt"]) { _, b in b }]])
        p.backend.answers["/api/v1/phone/live?limit=20"] = .success(["conversation_ids": ["c-1"]])
        await p.links.linkLive(now: t0)
        let c1 = try XCTUnwrap(p.channels.opened["c-1"])
        await c1.onFrame(["type": "stream_start"])
        await c1.onFrame(["type": "stream_end", "message_id": 3, "run_id": 7])
        await c1.onFrame(["type": "stream_end", "message_id": 3, "run_id": 7])           // the same run again: offered once
        // A job: its card says it finished, then its result arrives; the files go with the result.
        await c1.onFrame(["type": "job_update", "job_id": "job-1", "phase": "finished", "outcome": "done", "run_id": 8])
        await c1.onFrame(["type": "message", "role": "arslan", "message_id": 12, "content": "Done.", "job_id": "job-1", "run_id": 8])
        // A job that ended without a result message (stopped): its files come after a short wait.
        await c1.onFrame(["type": "job_update", "job_id": "job-2", "phase": "finished", "outcome": "stopped", "run_id": 9])
        await p.links.flush(now: Date().addingTimeInterval(1))
        XCTAssertFalse(p.backend.asked.contains("/api/v1/phone/runs/9/files"), "waits for a result message first")
        await p.links.flush(now: Date().addingTimeInterval(3))
        let offers = try await p.phone.receive().filter { $0.type == "file.offer" }.map(body)
        XCTAssertEqual(offers.map { $0["id"] as? String }, ["run_7_ab_plan.md", "run_8_x.csv", "run_9_y.txt"])
        XCTAssertEqual(offers.map { $0["conversation_id"] as? String }, ["c-1", "c-1", "c-1"])
        XCTAssertEqual(offers.map { $0["message_id"] as? String }, ["3", "12", nil])
        XCTAssertEqual(offers.map { $0["run_id"] as? Int }, [7, 8, 9])
        XCTAssertEqual(offers.map { $0["job_id"] as? String }, [nil, "job-1", "job-2"])
        XCTAssertTrue(offers.allSatisfy { !Wire.shouldNotify(type: "file.offer", body: $0) })
    }
}
