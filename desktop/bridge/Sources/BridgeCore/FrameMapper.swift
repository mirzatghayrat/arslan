// Backend frames ↔ protocol messages for one conversation (docs/specs/mobile-bridge-protocol.md §5.3, §6).
// The Bridge is a "remote window" on /ws/arslan/{conversation_id}: answers, progress and cards go
// to the phone; the phone's words and approvals come back as the frames a window would send.
import Foundation

public enum CardKind: String {
    case runCommand = "run_command", workspaceWrite = "workspace_write", schedule, action
}

public final class FrameMapper {
    public static let progressInterval: TimeInterval = 2      // §5.3: at most one progress per 2 s
    public static let partialInterval: TimeInterval = 1       // §5.7: at most one partial per second
    /// §5.7: past this many UTF-8 bytes the answer stops coming as partials (each one carries the
    /// whole reply so far, and must fit one envelope); the final message still comes.
    public static let partialLimit = 100_000
    public let conversationID: String
    /// §5.7: send the answer as it is written (`partial`) — set while a paired phone asked for it.
    public var partials = false
    var reply = ""
    var messageID = UUID().uuidString.lowercased()            // the turn's own id until the stored one is known
    var lastProgress: Date?
    var heldProgress: String?
    var lastPartial: Date?
    var sentPartial = ""                                      // the reply as the last partial had it
    var heldPartial = false                                   // a newer reply waits for its second
    var turnOpen = false                                      // between a turn's stream_start and its end
    var phoneSpoke = false                                    // the phone's words came back: its turn is next
    var macSpoke = false                                      // words typed on the Mac came: their turn is next
    var turnOrigin: String?                                   // who started the turn now streaming: phone / mac / unknown
    var jobOrigins: [String: String] = [:]                    // job id → who started it (from job_update)
    var seenUpTo: Int?                                        // newest stored message id this mapper knows of
    public private(set) var cards: [String: CardKind] = [:]   // open until the Mac says how it ended
    public var title: String?                                  // the conversation's title, for cards
    var answered: Set<String> = []                             // the phone answers a card once

    public init(conversationID: String) { self.conversationID = conversationID }

    public typealias Message = (type: String, body: [String: Any])

    /// One backend frame → what the phone should get (often nothing).
    public func phoneMessages(for frame: [String: Any], now: Date = Date()) -> [Message] {
        let iso = ISO8601DateFormatter()
        func card(_ kind: CardKind, _ action: String, _ target: String, _ risk: String) -> [Message] {
            guard let id = frame["call_id"] as? String else { return [] }
            // 0.1.61 §A4: installing code wants the whole card — a new capability never reaches the phone.
            if frame["perm_kind"] as? String == "capability" { return [] }
            cards[id] = kind
            // A card from the Mac's permission layer says its own question and when it runs out;
            // an older frame keeps the kind's words and the Mac's wait from now.
            let question = (frame["title"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let expires = (frame["expires_at"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
                ?? now.addingTimeInterval(Self.cardWait)
            return [("approval.request", ["approval_id": id, "action": String((question.isEmpty ? action : question).prefix(200)),
                                          "target": String(target.prefix(300)),
                                          "risk": Self.permRisk(frame["perm_kind"] as? String) ?? risk,
                                          "task_id": conversationID, "task_title": title ?? "Arslan",
                                          "expires_at": iso.string(from: expires)])]
        }
        switch frame["type"] as? String {
        case "stream_start":
            reply = ""
            messageID = UUID().uuidString.lowercased()
            (lastPartial, sentPartial, heldPartial, turnOpen) = (nil, "", false, true)
            // §5.7: whose words came just before says who started this turn; no evidence → unknown.
            turnOrigin = phoneSpoke ? "phone" : (macSpoke ? "mac" : nil)
            (phoneSpoke, macSpoke) = (false, false)
            return []
        case "stream_chunk":
            let chunk = frame["content"] as? String ?? ""
            guard !chunk.isEmpty else { return [] }
            reply += chunk
            guard partials else { return [] }
            // §5.7: the reply so far, at most once a second; a newer one waits for `flush`.
            if let last = lastPartial, now.timeIntervalSince(last) < Self.partialInterval {
                heldPartial = true
                return []
            }
            return partial(now: now)
        case "stream_end":
            endTurn()
            // The stored message's id, so the phone can merge this answer with `chat.history`.
            let partialID = messageID
            if let stored = frame["message_id"] as? Int { messageID = String(stored); see(stored) }
            var event: [String: Any] = ["conversation_id": conversationID, "kind": "message", "message_id": messageID,
                                        "text": reply, "final": true, "partial_id": partialID]
            if let run = frame["run_id"] as? Int { event["run_id"] = run }    // what the reply did, for review
            if let origin = turnOrigin { event["origin"] = origin }           // who asked (§5.7: who it rings)
            return [("chat.event", event)]
        case "message":
            guard let id = frame["message_id"] as? Int else { return [] }
            if frame["role"] as? String == "user" {
                // The phone's own words come back here (it has them; its turn is next). Words a Mac
                // window typed (no source "phone") go to the phone, marked, once (§5.7).
                if frame["source"] as? String == "phone" {
                    phoneSpoke = true
                    see(id)
                    return []
                }
                return userWords(id: id, text: frame["content"] as? String ?? "")
            }
            // A background task's result (its turn streams nothing).
            guard frame["role"] as? String == "arslan" else { return [] }
            endTurn()                                     // see `endsTurn`
            see(id)
            var event: [String: Any] = ["conversation_id": conversationID, "kind": "message", "message_id": String(id),
                                        "text": frame["content"] as? String ?? "", "final": true]
            if let job = frame["job_id"] as? String {
                event["job_id"] = job
                if let origin = jobOrigins[job] { event["origin"] = origin }
            }
            if let run = frame["run_id"] as? Int { event["run_id"] = run }
            return [("chat.event", event)]
        case "error":
            endTurn()                                     // see `endsTurn`
            var event: [String: Any] = ["conversation_id": conversationID, "kind": "error", "message_id": messageID,
                                        "text": frame["message"] as? String ?? "", "final": true]
            if let origin = turnOrigin { event["origin"] = origin }
            return [("chat.event", event)]
        case "history":
            // The socket's first frame: everything stored so far is not news (§5.7, the Mac's words).
            let ids = (frame["messages"] as? [[String: Any]] ?? []).compactMap { $0["message_id"] as? Int }
            seenUpTo = max(seenUpTo ?? 0, ids.max() ?? 0)
            return []
        case "tool_call":
            return progressLine("\(frame["tool"] as? String ?? ""): \(frame["args_summary"] as? String ?? "")", now: now)
        case "working":
            // §5.7: the backend's "still working" beat (every 15 s of a turn). Never after the turn's
            // end, and never in place of a real step held back.
            guard turnOpen, heldProgress == nil else { return [] }
            return progressLine("Working…", now: now)
        case "queued":
            return progressLine("Queued behind the current turn", now: now)
        case "propose_run_command":
            let outside = ["outside", "retry"].contains(frame["sandbox"] as? String ?? "")
            let line = frame["pretty"] as? String ?? frame["command"] as? String ?? ""
            let words = [line, frame["reason"] as? String ?? "", frame["rule"] as? String ?? ""].joined(separator: " ")
            return card(.runCommand, outside ? "Run a command outside the sandbox" : "Run a command", line,
                        Self.commandRisk(words, outside: outside, remote: frame["remote_host"] as? String != nil))
        case "propose_workspace_write":
            return card(.workspaceWrite, frame["action"] as? String ?? "Write a file", frame["path"] as? String ?? "", "write")
        case "propose_schedule":
            return card(.schedule, "Schedule “\(frame["name"] as? String ?? "")”", frame["when"] as? String ?? "", "write")
        case "propose_action":
            let kind = frame["kind"] as? String ?? "action"
            return card(.action, kind, frame["target"] as? String ?? "", kind == "browser_site" ? "send" : "write")
        case "card_resolved":
            // The Mac decided the card — the phone's own answer, a click in a Mac window (first
            // answer wins), or the 30 minutes running out. This is the phone's business receipt (§5.3).
            guard let id = frame["call_id"] as? String, cards.removeValue(forKey: id) != nil else { return [] }
            answered.remove(id)
            let outcome = ["approved": "done", "declined": "denied"][frame["outcome"] as? String ?? ""] ?? "expired"
            var body: [String: Any] = ["approval_id": id, "outcome": outcome]
            if frame["by"] as? String == "mac" { body["detail"] = "answered_on_mac" }
            return [("approval.result", body)]
        case "job_update":
            if let job = frame["job_id"] as? String, let origin = frame["origin"] as? String { jobOrigins[job] = origin }
            if frame["phase"] as? String == "finished" { endTurn() }    // see `endsTurn`
            return [("job.event", Self.jobEvent(frame, conversationID: conversationID))]
        default:
            return []
        }
    }

    /// How long the Mac waits on a card: 30 minutes since 0.1.61 (the server's `approvals.TIMEOUT_S`).
    /// A card from the permission layer says its own expiry; any other is counted from now.
    static let cardWait: TimeInterval = 1800

    /// 0.1.61 §A4: a card from the Mac's permission layer names its kind (`perm_kind`), and four of
    /// them have their own risk word. Any other kind (a command, an app, a write…) keeps the frame's
    /// own rules below. The words only decide how the phone's card looks.
    static func permRisk(_ permKind: String?) -> String? {
        switch permKind {
        case "money": return "payment"
        case "send": return "send"
        case "destructive": return "delete"
        case "outside": return "install"
        default: return nil
        }
    }

    /// The phone's card shows one of six risks (write, send, delete, install, payment, publish):
    /// how the card looks, never the decision, which stays on the Mac.
    static func commandRisk(_ text: String, outside: Bool, remote: Bool) -> String {
        if outside { return "install" }                   // it would run outside the sandbox
        let words = Set(text.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init))
        if !words.isDisjoint(with: ["rm", "rmdir", "delete", "remove", "trash", "unlink", "shred"]) { return "delete" }
        if !words.isDisjoint(with: ["install", "uninstall", "brew", "pip", "pip3", "npm", "gem", "cargo"]) { return "install" }
        if !words.isDisjoint(with: ["push", "publish", "deploy", "release", "upload"]) { return "publish" }
        if remote || !words.isDisjoint(with: ["send", "mail", "curl", "wget", "ssh", "scp", "rsync", "http", "https"]) {
            return "send"
        }
        return "write"
    }

    /// A turn's end drops the step it still holds back: stream_end, an answer to a background task
    /// (which streams nothing), an error, a job finishing. Before 2026-10-07 only stream_end did, and
    /// `flush` sent the old step after the end under a newer number; the phone showed "working" again
    /// (Codex's audit of iPhone build 7). One mapper per conversation: a chat turn running beside a
    /// job there loses at most its one held line, and its next step or its end comes anyway.
    static let endsTurn = "stream_end, message, error, finished job_update"

    /// What a turn's end drops: the step and the partial it still holds back (`endsTurn`).
    func endTurn() {
        heldProgress = nil
        heldPartial = false
        turnOpen = false
    }

    /// A held progress line, once its 2 seconds have passed; a held partial, once its second has.
    public func flush(now: Date = Date()) -> [Message] {
        var out: [Message] = []
        if heldPartial, let last = lastPartial, now.timeIntervalSince(last) >= Self.partialInterval { out += partial(now: now) }
        guard let text = heldProgress, let last = lastProgress, now.timeIntervalSince(last) >= Self.progressInterval else { return out }
        heldProgress = nil
        lastProgress = now
        return out + [progress(text)]
    }

    /// One progress line under the 2-second rule: sent now, or held (newest wins) for `flush`.
    func progressLine(_ text: String, now: Date) -> [Message] {
        if let last = lastProgress, now.timeIntervalSince(last) < Self.progressInterval {
            heldProgress = text                       // newest wins; flushed later
            return []
        }
        lastProgress = now
        return [progress(text)]
    }

    /// §5.7: the reply so far, under the turn's own id (the final message names it as `partial_id`).
    /// Only when it changed; never past `partialLimit`.
    func partial(now: Date) -> [Message] {
        heldPartial = false
        guard reply != sentPartial, reply.utf8.count <= Self.partialLimit else { return [] }
        (lastPartial, sentPartial) = (now, reply)
        return [("chat.event", ["conversation_id": conversationID, "kind": "partial", "message_id": messageID,
                                "text": reply, "final": false])]
    }

    func see(_ id: Int) { seenUpTo = max(seenUpTo ?? id, id) }

    /// Words typed in a Mac window, as the phone shows them ("on the Mac"); each stored message once.
    func userWords(id: Int, text: String) -> [Message] {
        if let seen = seenUpTo, id <= seen { return [] }
        see(id)
        // Evidence for who started a turn: read once it started (history), or before it (a frame).
        if turnOpen { turnOrigin = turnOrigin ?? "mac" } else { macSpoke = true }
        return [("chat.event", ["conversation_id": conversationID, "kind": "message", "message_id": String(id),
                                "text": text, "final": true, "role": "user", "source": "mac"])]
    }

    /// §5.7: today's backend sends no frame for words a Mac window typed, so when a turn starts the
    /// Bridge reads the newest stored messages (`/api/v1/phone/conversations/<id>/history`, oldest
    /// first) and forwards the user's words typed on the Mac that this mapper has not seen. Without
    /// the socket's `history` frame to say what is old, only what follows the last answer is news.
    public func macMessages(from rows: [[String: Any]]) -> [Message] {
        let parsed = rows.compactMap { row -> (id: Int, row: [String: Any])? in
            guard let id = Int(row["id"] as? String ?? "") else { return nil }
            return (id, row)
        }.sorted { $0.id < $1.id }
        if seenUpTo == nil, let lastAnswer = parsed.last(where: { $0.row["role"] as? String != "user" }) { seenUpTo = lastAnswer.id }
        var out: [Message] = []
        for (id, row) in parsed {
            if row["role"] as? String == "user", row["source"] as? String == "mac" {
                out += userWords(id: id, text: row["text"] as? String ?? "")
            } else {
                see(id)
            }
        }
        return out
    }

    func progress(_ text: String) -> Message {
        ("chat.event", ["conversation_id": conversationID, "kind": "progress", "message_id": messageID,
                        "text": String(text.prefix(200)), "final": false])
    }

    /// A backend job_update frame → a `job.event` body (also the entries of `status.snapshot` jobs).
    static func jobEvent(_ f: [String: Any], conversationID: String) -> [String: Any] {
        let outcome = f["outcome"] as? String
        let state: String
        switch (f["phase"] as? String, outcome) {
        case ("finished", "done"): state = "done"
        case ("finished", "blocked"): state = "stuck"
        case ("finished", "partial"), ("finished", "out_of_budget"): state = "partial"
        case ("finished", _): state = "stopped"
        default: state = "running"
        }
        let criteria = f["criteria"] as? [[String: Any]] ?? []
        var body: [String: Any] = ["id": f["job_id"] as? String ?? "", "conversation_id": f["conversation_id"] as? String ?? conversationID,
                                   "state": state, "title": f["goal"] as? String ?? "", "current_step": f["step"] as? String ?? "",
                                   "completed": criteria.filter { $0["status"] as? String == "passed" }.count, "total": criteria.count,
                                   "plan": [], "files": []]
        if state != "running", let detail = f["detail"] as? String, !detail.isEmpty { body["summary"] = detail }
        if let run = f["run_id"] as? Int { body["run_id"] = run }
        if let origin = f["origin"] as? String { body["origin"] = origin }
        // Each check with its own outcome, for the phone's checklist (pending/passed/failed/not_reached).
        if !criteria.isEmpty {
            body["criteria"] = criteria.map { ["text": $0["description"] as? String ?? "", "status": $0["status"] as? String ?? "pending"] }
        }
        return body
    }

    public static let biometricProof: Set<String> = ["faceid", "touchid"]

    /// A phone message → the frames a window would send. Throws `approval_expired` for a
    /// card the Mac no longer has open.
    public func backendFrames(for type: String, body: [String: Any]) throws -> [[String: Any]] {
        switch type {
        case "chat.send":
            return [["type": "user_message", "content": body["text"] as? String ?? "", "source": "phone"]]
        case "approval.answer":
            guard let id = body["approval_id"] as? String, let kind = cards[id], answered.insert(id).inserted else {
                throw BridgeError.code("approval_expired")
            }
            // A yes counts only with biometric proof the phone vouches for: Face ID or Touch ID (iPhone
            // SE). Anything else, "none" or unknown, is a no. Before 2026-10-06 only "faceid" counted,
            // so a Touch ID yes turned into a cancel (iPhone store audit).
            let approve = body["decision"] as? String == "approve" && FrameMapper.biometricProof.contains(body["auth"] as? String ?? "")
            // Marked, so the Mac can tell the other windows the phone answered it.
            var frame: [String: Any] = ["type": "\(approve ? "confirm" : "cancel")_\(kind.rawValue)", "call_id": id,
                                        "source": "phone"]
            if approve && kind == .runCommand { frame["remember"] = false }    // a phone never grants "always"
            return [frame]
        default:
            throw BridgeError.code("unknown_type")
        }
    }
}
