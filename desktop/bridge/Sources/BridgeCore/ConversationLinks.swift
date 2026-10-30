// Phone ↔ conversations (docs/specs/mobile-bridge-protocol.md §5.3, §5.7, §6.1). One link per active
// conversation: a channel to /ws/arslan/<id> and a FrameMapper. The phone's words go in as the
// frames a window sends (marked source "phone"); answers, progress, cards and jobs go back to
// the paired phones.
//
// Since §5.7 (2026-10-13): files the phone sends are saved in the workspace and go with the message
// that names them (pictures for the model to see, other files as their text); the newest
// conversations and those with a running job stay linked, so they are live on the phone; the phone
// can delete a conversation; and each phone gets only what its hello said it can show.
//
// An actor: phone messages (the poll loop), backend frames (one task per socket) and the
// once-a-second flush all touch the same links, held messages and files.
import CryptoKit
import Foundation

public protocol ConversationChannels {
    /// Open (or reuse) the channel for a conversation; frames from the backend go to `onFrame`.
    func open(conversationID: String, onFrame: @escaping ([String: Any]) async -> Void) -> ControlChannel
    /// Close a conversation's channel for good (it was deleted, or its link is no longer kept).
    func close(conversationID: String)
}

extension ConversationChannels {
    public func close(conversationID: String) {}
}

/// A refusal with its own words for the phone (the code is still one of §5.4's).
struct Refusal: Error {
    let code: String, message: String
}

public actor ConversationLinks {
    /// The pocket, the one conversation every phone shared before §5.8 ("Remote"), is retired (Q1 card, #4; the user,
    /// 2026-10-29): its old messages stay on the Mac as an ordinary conversation, read and continued there only.
    /// A phone frame that names it is refused `not_found` before anything reaches the Mac, and so is a chat.send or
    /// chat.history that names no conversation (which meant the pocket). It is never linked, so nothing about it
    /// reaches a phone, and it is never in a phone's list or status.
    public static let pocket = "pocket"
    /// §5.8: a conversation the phone starts names itself `phone-` and a lowercase UUID v4.
    static let phoneConversationID = try! NSRegularExpression(
        pattern: #"^phone-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\z"#)    // `$` takes a final line break
    public static let fileLimit = 20 * 1024 * 1024     // §4.6
    public static let maxAttachments = 10              // §5.7: files with one message
    public static let holdLimit: TimeInterval = 120    // §5.7: a message waits this long for its files
    public static let pictureKeep: TimeInterval = 600  // a picture's bytes, kept for the model until used
    public static let fileKeep: TimeInterval = 24 * 3600
    public static let liveCount = 20                   // §5.7: the newest conversations kept linked
    public static let maxLinks = 40                    // past this, idle links that are not live close
    public static let idleLink: TimeInterval = 15 * 60
    public static let jobFilesWait: TimeInterval = 2   // a finished job's result message, before its files go alone
    public static let pictureTypes: Set<String> = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    /// One message is one WebSocket frame, and uvicorn takes at most 16 MiB: pictures (base64, ×4/3)
    /// and the files' text must fit with room to spare. One picture over `visionImageMax` (the
    /// providers' own per-image limits) is saved and named, not shown.
    public static let visionImageMax = 3_500_000
    public static let visionTotalMax = 8 * 1024 * 1024
    public static let contextMax = 2_000_000           // UTF-8 bytes of the files' text in one message
    public static let fileTextMax = 400_000            // …and of any one file's

    let channels: ConversationChannels
    let mailbox: Mailbox
    let backend: BackendReads
    var links: [String: (channel: ControlChannel, mapper: FrameMapper)] = [:]
    var touched: [String: Date] = [:]                  // when the phone last used each link
    var executed: Set<String> = []                     // client_msg_ids already run (§5.3: once)
    var startedTasks: [String: [String: Any]] = [:]    // client_task_id → task.started (a retry gets the same)
    public let status: StatusReporter?                 // a phone saying hello gets the status at once

    /// A file the phone sent (§5.7): where it was saved, its text, and a picture's bytes until used.
    struct Inbound {
        let path: String, name: String, mime: String, size: Int, at: Date
        var picture: Data?
        let text: String?
    }
    var inbound: [String: Inbound] = [:]               // FileReference id → the saved file

    /// A chat.send waiting for its files (§5.7), in arrival order; one conversation's messages keep theirs.
    struct Held {
        let from: String, envelopeID: String, clientID: String, conversationID: String
        let body: [String: Any], fileIDs: [String], at: Date
        let sentAt: String?                            // the envelope's `ts`: when the phone sent it
    }
    var held: [Held] = []
    var releasing = false
    var unreadPartials: [String: String] = [:]         // "<phone>|<conversation>" → the partial not yet read
    var offeredRuns: Set<Int> = []                     // a run's files are offered once
    var jobFiles: [Int: (conversationID: String, jobID: String?, at: Date)] = [:]   // run → waiting for its result

    public init(channels: ConversationChannels, mailbox: Mailbox, backend: BackendReads = NoBackend(),
                status: StatusReporter? = nil) {
        (self.channels, self.mailbox, self.backend, self.status) = (channels, mailbox, backend, status)
    }

    @discardableResult
    func link(_ conversationID: String, now: Date = Date(), touch: Bool = true) throws -> (channel: ControlChannel, mapper: FrameMapper) {
        guard conversationID != Self.pocket else { throw BridgeError.code("not_found") }      // retired: never live
        if touch || touched[conversationID] == nil { touched[conversationID] = now }
        if let existing = links[conversationID] { return existing }
        let mapper = FrameMapper(conversationID: conversationID)
        let channel = channels.open(conversationID: conversationID) { [weak self] frame in
            await self?.arrived(frame, in: conversationID)
        }
        links[conversationID] = (channel, mapper)
        return (channel, mapper)
    }

    /// The link closes for good (§5.7): a deleted conversation, or one idle and no longer live.
    func unlink(_ conversationID: String) {
        guard links.removeValue(forKey: conversationID) != nil else { return }
        touched[conversationID] = nil
        held.removeAll { $0.conversationID == conversationID }
        unreadPartials = unreadPartials.filter { !$0.key.hasSuffix("|" + conversationID) }
        channels.close(conversationID: conversationID)
    }

    /// One frame from a conversation's socket.
    func arrived(_ frame: [String: Any], in conversationID: String, now: Date = Date()) async {
        guard let mapper = links[conversationID]?.mapper else { return }       // unlinked meanwhile
        let type = frame["type"] as? String
        // A card names its conversation on the phone; looked up once, at the first card.
        if type?.hasPrefix("propose_") == true, mapper.title == nil {
            mapper.title = await title(of: conversationID)
        }
        mapper.partials = anyPhone("partial")
        await deliver(mapper.phoneMessages(for: frame, now: now))
        switch type {
        case "stream_start":
            // §5.7: the backend sends no frame for words typed in a window; read them as the turn starts.
            if anyPhone("mac_messages") { await readMacWords(conversationID, mapper) }
        case "stream_end":
            // A finished turn offers the files it made (references only; the bytes come on file.get).
            if let run = frame["run_id"] as? Int {
                await offerFiles(ofRun: run, in: conversationID, messageID: (frame["message_id"] as? Int).map(String.init))
            }
        case "message":
            // A background job's result: its files go with it.
            if frame["role"] as? String == "arslan", let run = frame["run_id"] as? Int, let id = frame["message_id"] as? Int {
                jobFiles[run] = nil
                await offerFiles(ofRun: run, in: conversationID, messageID: String(id), jobID: frame["job_id"] as? String)
            }
        case "job_update":
            // A finished job's result message follows its card; a stopped or silent one sends none,
            // and then its files go alone after `jobFilesWait` (see `flush`).
            if frame["phase"] as? String == "finished", let run = frame["run_id"] as? Int, !offeredRuns.contains(run) {
                jobFiles[run] = (conversationID, frame["job_id"] as? String, now)
            }
        default:
            break
        }
    }

    func readMacWords(_ conversationID: String, _ mapper: FrameMapper) async {
        let path = "/api/v1/phone/conversations/\(conversationID.pathSegment)/history?limit=8"
        guard let rows = (try? await backend.json(path))?["messages"] as? [[String: Any]] else { return }
        await deliver(mapper.macMessages(from: rows))
    }

    func title(of conversationID: String) async -> String? {
        let list = (try? await backend.json("/api/v1/phone/conversations?limit=100"))?["conversations"] as? [[String: Any]] ?? []
        let title = list.first { $0["id"] as? String == conversationID }?["title"] as? String
        return (title?.isEmpty == false) ? title : nil
    }

    /// A run's files, offered once, each saying which conversation and answer it belongs to (§5.7).
    func offerFiles(ofRun run: Int, in conversationID: String, messageID: String? = nil, jobID: String? = nil) async {
        guard !offeredRuns.contains(run),
              let files = (try? await backend.json("/api/v1/phone/runs/\(run)/files"))?["files"] as? [[String: Any]],
              offeredRuns.insert(run).inserted else { return }
        await deliver(files.map { file in
            var body = file
            body["conversation_id"] = conversationID
            body["run_id"] = run
            if let messageID { body["message_id"] = messageID }
            if let jobID { body["job_id"] = jobID }
            return ("file.offer", body)
        })
    }

    func anyPhone(_ capability: String) -> Bool { mailbox.peers.keys.contains { mailbox.has(capability, $0) } }

    /// What a phone must have said in its hello to get this message (§5.7); nil = every phone.
    static func needs(_ message: FrameMapper.Message) -> String? {
        guard message.type == "chat.event" else { return nil }
        if message.body["kind"] as? String == "partial" { return "partial" }
        if message.body["role"] as? String == "user" { return "mac_messages" }
        return nil
    }

    func deliver(_ messages: [FrameMapper.Message]) async {
        for message in messages {
            let needed = Self.needs(message)
            for peer in mailbox.peers.keys.sorted() where needed.map({ mailbox.has($0, peer) }) ?? true {
                guard let record = try? await mailbox.send(type: message.type, body: message.body, to: peer) else { continue }
                guard message.type == "chat.event", let conversation = message.body["conversation_id"] as? String else { continue }
                // §5.7: a newer partial, or the turn's last word, takes back the partial the phone has
                // not read — so a phone left closed does not come back to a pile of them.
                let key = peer + "|" + conversation, kind = message.body["kind"] as? String
                if kind == "partial" {
                    if let older = unreadPartials.updateValue(record.id, forKey: key) { try? mailbox.withdraw(older) }
                } else if kind == "error" || (kind == "message" && message.body["role"] as? String != "user") {
                    if let older = unreadPartials.removeValue(forKey: key) { try? mailbox.withdraw(older) }
                }
            }
        }
    }

    /// About once a second: held progress lines and partials whose time has come, a finished job's
    /// files whose result never came, files kept too long, and messages whose files arrived or
    /// whose 120 seconds are up.
    public func flush(now: Date = Date()) async {
        let wantsPartials = anyPhone("partial")
        for (_, link) in links {
            link.mapper.partials = wantsPartials
            await deliver(link.mapper.flush(now: now))
        }
        for (run, wait) in jobFiles where now.timeIntervalSince(wait.at) >= Self.jobFilesWait {
            jobFiles[run] = nil
            await offerFiles(ofRun: run, in: wait.conversationID, jobID: wait.jobID)
        }
        for (id, file) in inbound {
            if now.timeIntervalSince(file.at) >= Self.fileKeep {
                inbound[id] = nil
            } else if file.picture != nil, now.timeIntervalSince(file.at) >= Self.pictureKeep {
                inbound[id]?.picture = nil
            }
        }
        await release(now: now)
    }

    /// The newest conversations and those with a running job, linked so they are live on the phone
    /// (§5.7): at start and after each `conversations.list`. Never opens one twice; past `maxLinks`,
    /// links nobody used for a while and that are no longer live close (never one holding a card).
    public func linkLive(now: Date = Date()) async {
        guard !mailbox.peers.isEmpty,
              let ids = (try? await backend.json("/api/v1/phone/live?limit=\(Self.liveCount)"))?["conversation_ids"] as? [String]
        else { return }
        for id in ids { _ = try? link(id, now: now, touch: false) }          // the pocket, if listed, stays unlinked
        guard links.count > Self.maxLinks else { return }
        let live = Set(ids)
        let idle = links.keys.filter { id in
            !live.contains(id) && links[id]?.mapper.cards.isEmpty == true
                && !held.contains { $0.conversationID == id } && now.timeIntervalSince(touched[id] ?? .distantPast) >= Self.idleLink
        }.sorted { (touched[$0] ?? .distantPast, $0) < (touched[$1] ?? .distantPast, $1) }
        for id in idle.prefix(links.count - Self.maxLinks) { unlink(id) }
    }

    // ------------------------------------------------------------------ files and held messages (§5.7)

    /// A file the phone sent, its bytes already decrypted and checked against the reference
    /// (Seal.open: asset hash, AEAD, size, sha256): saved in the workspace's Inbox/iPhone, its text
    /// read once (/api/v1/extract), a picture's bytes kept for the model.
    func receive(_ received: Received, _ body: [String: Any], now: Date) async throws {
        guard let id = body["id"] as? String, !id.isEmpty, id.count <= 200, let data = received.asset else {
            throw BridgeError.code("malformed")                   // a phone's file.offer always carries its bytes
        }
        guard data.count <= Self.fileLimit else { throw BridgeError.code("too_large") }
        if inbound[id] != nil { return }                          // offered again: saved once
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard body["size"] as? Int == data.count, (body["sha256"] as? String)?.lowercased() == digest else {
            throw BridgeError.code("malformed")
        }
        let name = (body["name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "file"
        let mime = (body["mime_type"] as? String ?? "application/octet-stream").lowercased()
        let saved = try await backend.post("/api/v1/phone/inbox", body: ["name": name, "mime_type": mime,
                                                                        "data": data.base64EncodedString(), "sha256": digest])
        guard let path = saved["path"] as? String, !path.isEmpty else { throw BridgeError.code("mac_busy") }
        let picture = Self.pictureTypes.contains(mime)
        var text: String?
        if !picture, let read = try? await backend.upload("/api/v1/extract", field: "file", filename: name, mimeType: mime, data: data),
           let words = read["text"] as? String, !words.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            text = Self.prefix(words, bytes: Self.fileTextMax)
        }
        inbound[id] = Inbound(path: path, name: name, mime: mime, size: data.count, at: now, picture: picture ? data : nil, text: text)
    }

    /// Run what can run, in order: a message whose files are all here, or answer one whose time is up.
    /// One conversation's later messages wait behind its earlier one.
    func release(now: Date) async {
        guard !releasing else { return }                         // the running pass picks up what changed
        releasing = true
        defer { releasing = false }
        while let (item, ready) = nextHeld(now: now) {
            if ready {
                await run(item)
            } else {
                // Not counted as done: the phone sends it again (§5.7).
                await refuse(Refusal(code: "file_unavailable", message: "The files for that message did not reach the Mac in time. Send it again."),
                             type: "chat.send", to: item.from, related: item.envelopeID)
            }
        }
    }

    func nextHeld(now: Date) -> (Held, Bool)? {
        var waiting: Set<String> = []
        for (index, item) in held.enumerated() where !waiting.contains(item.conversationID) {
            if item.fileIDs.allSatisfy({ inbound[$0] != nil }) { held.remove(at: index); return (item, true) }
            if now.timeIntervalSince(item.at) >= Self.holdLimit { held.remove(at: index); return (item, false) }
            waiting.insert(item.conversationID)
        }
        return nil
    }

    func run(_ item: Held) async {
        do {
            let link = try link(item.conversationID)
            var frames = try link.mapper.backendFrames(for: "chat.send", body: item.body)
            if !item.fileIDs.isEmpty, let first = frames.first { frames[0] = attach(item.fileIDs, to: first) }
            // INB2: whether the user is there for this turn reads when the phone sent it (server/services/presence.py).
            if let sentAt = item.sentAt, !frames.isEmpty { frames[0]["sent_at"] = sentAt }
            for frame in frames { try await link.channel.send(frame) }
            // Only once it reached Arslan: a message that failed to go through runs on the phone's retry.
            if !item.clientID.isEmpty { executed.insert(item.clientID) }
            for id in item.fileIDs { inbound[id]?.picture = nil }          // a picture is shown once
        } catch {
            await refuse(error, type: "chat.send", to: item.from, related: item.envelopeID)
        }
    }

    /// The message as the web composer would send it: pictures in `images`, other files' text in
    /// `attached_context`, and one line per file naming where it was saved, so the agent can open
    /// the original with its tools.
    func attach(_ ids: [String], to frame: [String: Any]) -> [String: Any] {
        var lines: [String] = [], pictures: [[String: Any]] = [], texts: [String] = []
        var pictureBytes = 0, textBytes = 0
        for id in ids {
            guard let file = inbound[id] else { continue }
            var note = ""
            if Self.pictureTypes.contains(file.mime) {
                if let bytes = file.picture, bytes.count <= Self.visionImageMax, pictureBytes + bytes.count <= Self.visionTotalMax {
                    pictures.append(["name": file.name, "mime_type": file.mime, "data": bytes.base64EncodedString()])
                    pictureBytes += bytes.count
                } else {
                    note = " (not shown to the model as a picture; open the file itself)"
                }
            } else if let text = file.text, textBytes < Self.contextMax {
                let block = Self.prefix("=== \(file.name) ===\n\(text)", bytes: Self.contextMax - textBytes)
                texts.append(block)
                textBytes += block.utf8.count + 2
            } else {
                note = " (its text could not be read; open the file itself)"
            }
            lines.append("Attached from iPhone: \(file.name) → \(file.path)\(note)")
        }
        var out = frame
        let text = frame["content"] as? String ?? ""
        let block = lines.joined(separator: "\n")
        out["content"] = text.isEmpty ? block : text + "\n\n" + block
        if !pictures.isEmpty { out["images"] = pictures }
        if !texts.isEmpty { out["attached_context"] = texts.joined(separator: "\n\n") }
        return out
    }

    /// The longest start of `text` that is at most `bytes` UTF-8 bytes, whole characters only.
    static func prefix(_ text: String, bytes: Int) -> String {
        guard text.utf8.count > bytes else { return text }
        var out = "", used = 0
        for character in text {
            let size = character.utf8.count
            if used + size > bytes { break }
            out.append(character)
            used += size
        }
        return out
    }

    /// `chat.history.result` in one envelope (§5.7): the backend trims to 560 KB, but the slashes
    /// JSONSerialization escapes can still push the sealed record past `Wire.maxSealedBytes`; then
    /// the oldest messages go, a quarter at a time, and the phone is told (`truncated`).
    func sendHistory(_ result: [String: Any], to peer: String) async throws {
        var body = result
        while true {
            do {
                _ = try await mailbox.send(type: "chat.history.result", body: body, to: peer)
                return
            } catch BridgeError.code("too_large") {
                var messages = body["messages"] as? [Any] ?? []
                guard messages.count > 1 else { throw BridgeError.code("too_large") }
                messages.removeFirst(max(1, messages.count / 4))
                (body["messages"], body["truncated"]) = (messages, true)
            }
        }
    }

    /// Where a chat.send goes (§5.8). A conversation the phone starts (`new_conversation_id`) is stored with its kind
    /// first, quick or chat, in the one call that also checks it is still empty; if the Mac can't store it, its words
    /// go nowhere. The Mac reads what a conversation is from what it stored, never from a message: one the phone
    /// made with no kind stored gets only the quick tools (#486 review, G1). `conversation_kind` means nothing
    /// without a new id. No id at all meant the pocket, which is retired (Q1 #4): `not_found`.
    func destination(of body: [String: Any]) async throws -> String {
        let named = body["conversation_id"] as? String
        guard let new = body["new_conversation_id"] as? String else {
            guard body["conversation_kind"] == nil else { throw BridgeError.code("bad_request") }
            guard let named else { throw BridgeError.code("not_found") }
            return named
        }
        let whole = NSRange(new.startIndex..., in: new)
        guard Self.phoneConversationID.firstMatch(in: new, range: whole) != nil, named == nil || named == new else {
            throw BridgeError.code("bad_request")
        }
        switch body["conversation_kind"] {
        case nil:
            _ = try await backend.post("/api/v1/phone/conversations/\(new.pathSegment)/chat", body: [:])
        case let kind as String where kind == "quick":
            _ = try await backend.post("/api/v1/phone/conversations/\(new.pathSegment)/quick", body: [:])
        default:
            throw BridgeError.code("bad_request")
        }
        return new
    }

    func refuse(_ error: Error, type: String, to peer: String, related: String) async {
        let code: String, message: String
        switch error {
        case let refusal as Refusal: (code, message) = (refusal.code, refusal.message)
        case let bridge as BridgeError: (code, message) = (bridge.code, Self.message(bridge.code))
        default:
            BridgeLog.error("handling \(type)", error)
            (code, message) = ("mac_busy", Self.message("mac_busy"))
        }
        if error is Refusal || error is BridgeError { BridgeLog.notice("phone: \(type) refused: \(code)") }
        _ = try? await mailbox.send(type: "error", body: ["code": code, "message": message, "related_id": related], to: peer)
    }

    // ------------------------------------------------------------------ phone messages

    /// One message from a paired phone.
    public func handle(_ received: Received, now: Date = Date()) async {
        let body = received.envelope["body"] as? [String: Any] ?? [:]
        let related = (received.envelope["id"] as? String)?.lowercased() ?? ""
        if received.type != "error" { BridgeLog.notice("phone: \(received.type)") }
        do {
            // Q1 #4: the retired pocket is not on the Mac for a phone, whatever the frame (`pocket` above).
            if received.type != "error", body["conversation_id"] as? String == Self.pocket { throw BridgeError.code("not_found") }
            switch received.type {
            case "chat.send":
                let clientID = body["client_msg_id"] as? String ?? ""
                guard clientID.isEmpty || (!executed.contains(clientID) && !held.contains { $0.clientID == clientID }) else { return }
                let attachments = body["attachments"] as? [[String: Any]] ?? []
                guard attachments.count <= Self.maxAttachments else {
                    throw Refusal(code: "too_many_files", message: Self.message("too_many_files"))
                }
                let ids = attachments.map { $0["id"] as? String ?? "" }
                guard !ids.contains(where: \.isEmpty) else { throw BridgeError.code("malformed") }
                let conversation = try await destination(of: body)
                try link(conversation, now: now)
                // §5.7: it runs once every file it names is here (at once when it names none).
                held.append(Held(from: received.from, envelopeID: related, clientID: clientID, conversationID: conversation,
                                 body: body, fileIDs: ids, at: now, sentAt: received.envelope["ts"] as? String))
                await release(now: now)
            case "file.offer":
                try await receive(received, body, now: now)
                await release(now: now)
            case "conversation.delete":
                guard let id = body["conversation_id"] as? String, !id.isEmpty else { throw BridgeError.code("malformed") }
                let result = try await backend.delete("/api/v1/conversations/\(id.pathSegment)")
                // The backend answers 200 for an id it has nothing for: nothing deleted = not there.
                if let counts = result["deleted"] as? [String: Any], !counts.isEmpty, counts.values.allSatisfy({ ($0 as? Int) == 0 }) {
                    throw BridgeError.code("not_found")
                }
                unlink(id)
                _ = try await mailbox.send(type: "conversation.deleted", body: ["conversation_id": id], to: received.from)
            case "conversation.update":
                // §5.8: a quick question becomes an ordinary chat; `chat` is the only target.
                guard let id = body["conversation_id"] as? String, !id.isEmpty else { throw BridgeError.code("malformed") }
                guard body["kind"] as? String == "chat" else { throw BridgeError.code("bad_request") }
                let result = try await backend.post("/api/v1/phone/conversations/\(id.pathSegment)/update", body: ["kind": "chat"])
                _ = try await mailbox.send(type: "conversation.updated",
                                           body: ["conversation_id": id, "kind": result["kind"] as? String ?? "chat"],
                                           to: received.from)
            case "approval.answer":
                let id = body["approval_id"] as? String ?? ""
                guard let link = links.values.first(where: { $0.mapper.cards[id] != nil }) else {
                    throw BridgeError.code("approval_expired")
                }
                for frame in try link.mapper.backendFrames(for: "approval.answer", body: body) { try await link.channel.send(frame) }
            case "conversations.list":
                let limit = min(max(body["limit"] as? Int ?? 20, 1), 100)
                var query = "limit=\(limit)"
                // §5.8: only quick questions (`kind: "quick"`), and the page strictly older than `before`.
                if let kind = body["kind"] {
                    guard kind as? String == "quick" else { throw BridgeError.code("bad_request") }
                    query += "&kind=quick"
                }
                if let before = body["before"] {
                    guard let time = before as? String else { throw BridgeError.code("bad_request") }
                    query += "&before=\(time.pathSegment)"                // a time's + must not arrive as a space
                }
                var result = try await backend.json("/api/v1/phone/conversations?\(query)")
                if let rows = result["conversations"] as? [[String: Any]] {            // Q1 #4: never the pocket
                    result["conversations"] = rows.filter { $0["id"] as? String != Self.pocket }
                }
                _ = try await mailbox.send(type: "conversations.result", body: result, to: received.from)
                await linkLive(now: now)                 // §5.7: what the list shows stays live
            case "chat.history":
                guard let id = body["conversation_id"] as? String else { throw BridgeError.code("not_found") }  // was the pocket
                let limit = min(max(body["limit"] as? Int ?? 50, 1), 200)
                let result = try await backend.json("/api/v1/phone/conversations/\(id.pathSegment)/history?limit=\(limit)")
                try link(id, now: now)      // the phone is looking at it: its progress, cards and results come live
                try await sendHistory(result, to: received.from)
            case "run.get":
                guard let run = body["run_id"] as? Int else { throw BridgeError.code("malformed") }
                let result = try await backend.json("/api/v1/phone/runs/\(run)")
                _ = try await mailbox.send(type: "run.result", body: result, to: received.from)
            case "task.start":
                let clientID = body["client_task_id"] as? String ?? ""
                if let done = startedTasks[clientID] {           // the phone retried: same answer, no second task
                    _ = try await mailbox.send(type: "task.started", body: done, to: received.from)
                    break
                }
                let started = try await backend.post("/api/v1/phone/tasks", body: [
                    "goal": body["goal"] as? String ?? "", "criteria": body["criteria"] as? [String] ?? []])
                guard let conversation = started["conversation_id"] as? String, let job = started["job_id"] as? String else {
                    throw BridgeError.code("mac_busy")
                }
                try link(conversation, now: now)    // its progress and result reach the phone
                let reply: [String: Any] = ["conversation_id": conversation, "job_id": job, "client_task_id": clientID]
                if !clientID.isEmpty { startedTasks[clientID] = reply }
                _ = try await mailbox.send(type: "task.started", body: reply, to: received.from)
            case "task.stop":
                guard let job = body["job_id"] as? String, !job.isEmpty else { throw BridgeError.code("malformed") }
                if let conversation = body["conversation_id"] as? String { try link(conversation, now: now) }   // to hear it stop
                _ = try await backend.post("/api/v1/phone/tasks/\(job.pathSegment)/stop", body: [:])
            case "file.get":
                guard let id = body["file_id"] as? String, !id.isEmpty else { throw BridgeError.code("malformed") }
                let got = try await backend.json("/api/v1/phone/files/\(id.pathSegment)")
                guard let file = got["file"] as? [String: Any], let data = Data(base64Encoded: got["data"] as? String ?? "") else {
                    throw BridgeError.code("mac_busy")
                }
                guard data.count <= Self.fileLimit else { throw BridgeError.code("too_large") }
                // The phone checks the bytes against this reference; never send one that would fail.
                let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
                guard file["sha256"] as? String == digest, file["size"] as? Int == data.count else {
                    throw BridgeError.code("file_unavailable")
                }
                _ = try await mailbox.send(type: "file.offer", body: file, to: received.from, asset: data)
            case "hello":
                // §5.7: what this phone can show; until it says hello it gets none of the new events.
                mailbox.setCapabilities(Set(body["capabilities"] as? [String] ?? []), for: received.from)
                _ = try await mailbox.send(type: "hello", body: ["app_version": "mac", "protocol_version": Wire.version,
                                                                // "touchid": a Touch ID yes counts (the phone
                                                                // holds one back from a Mac without it)
                                                                "capabilities": Self.capabilities], to: received.from)
                await status?.send(to: received.from)
                await linkLive(now: now)
            case "error":
                return                                 // never answer an error with an error
            default:
                throw BridgeError.code("unknown_type")
            }
        } catch {
            await refuse(error, type: received.type, to: received.from, related: related)
        }
    }

    /// What this Mac does (hello). §5.7 added files_in (files from the phone), partial (answers as
    /// they are written), delete (conversation.delete), live (the newest conversations stay linked)
    /// and mac_messages (words typed on the Mac are forwarded). §5.8 added new_conversation (a chat.send may
    /// start one) and quick (quick questions); a Mac that says quick always says new_conversation.
    public static let capabilities = ["chat", "approvals", "jobs", "history", "files", "status", "review", "tasks", "touchid",
                                      "files_in", "partial", "delete", "live", "mac_messages", "new_conversation", "quick"]

    static func message(_ code: String) -> String {
        switch code {
        case "approval_expired": return "That card is no longer open on the Mac."
        case "unknown_type": return "This Mac does not do that yet."
        case "file_unavailable": return "That file is no longer on the Mac."
        case "malformed": return "The Mac could not read that request."
        case "too_large": return "That file is too large to send to the phone."
        case "too_many_files": return "At most \(maxAttachments) files can go with one message."
        case "not_found": return "That conversation is no longer on the Mac."
        case "bad_request": return "The Mac could not read that request."
        case "conversation_exists": return "That conversation is already on the Mac."
        default: return "The Mac could not do that right now."
        }
    }
}

/// Real channels: one WebSocketControl on /ws/arslan/<id> per conversation, reconnecting on its own.
public final class WebSocketChannels: ConversationChannels {
    let port: Int, token: String
    var open: [String: WebSocketControl] = [:]

    public init(port: Int, token: String) { (self.port, self.token) = (port, token) }

    public func open(conversationID: String, onFrame: @escaping ([String: Any]) async -> Void) -> ControlChannel {
        if let existing = open[conversationID] { return existing }
        let path = "/ws/arslan/" + (conversationID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? conversationID)
        let socket = WebSocketControl(port: port, token: token, path: path)
        socket.onFrame = onFrame
        open[conversationID] = socket
        socket.start()
        return socket
    }

    public func close(conversationID: String) {
        open.removeValue(forKey: conversationID)?.stop()
    }
}
