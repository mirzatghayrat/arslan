// Backend frames ↔ protocol messages for one conversation (docs/specs/mobile-bridge-protocol.md §5.3, §6).
// The Bridge is a "remote window" on /ws/arslan/{conversation_id}: answers, progress and cards go
// to the phone; the phone's words and approvals come back as the frames a window would send.
import Foundation

public enum CardKind: String {
    case runCommand = "run_command", workspaceWrite = "workspace_write", schedule, action
}

public final class FrameMapper {
    public static let progressInterval: TimeInterval = 2      // §5.3: at most one progress per 2 s
    public static let cardTimeout: TimeInterval = 300         // the Mac's 5-minute card timeout
    public let conversationID: String
    var reply = ""
    var messageID = UUID().uuidString.lowercased()
    var lastProgress: Date?
    var heldProgress: String?
    public private(set) var cards: [String: CardKind] = [:]

    public init(conversationID: String) { self.conversationID = conversationID }

    public typealias Message = (type: String, body: [String: Any])

    /// One backend frame → what the phone should get (often nothing).
    public func phoneMessages(for frame: [String: Any], now: Date = Date()) -> [Message] {
        let iso = ISO8601DateFormatter()
        func card(_ kind: CardKind, _ action: String, _ target: String, _ risk: String) -> [Message] {
            guard let id = frame["call_id"] as? String else { return [] }
            cards[id] = kind
            return [("approval.request", ["approval_id": id, "action": action, "target": String(target.prefix(300)),
                                          "risk": risk, "task_id": conversationID, "task_title": "",
                                          "expires_at": iso.string(from: now.addingTimeInterval(Self.cardTimeout))])]
        }
        switch frame["type"] as? String {
        case "stream_start":
            reply = ""
            messageID = UUID().uuidString.lowercased()
            return []
        case "stream_chunk":
            reply += frame["content"] as? String ?? ""
            return []
        case "stream_end":
            heldProgress = nil
            return [("chat.event", ["conversation_id": conversationID, "kind": "message", "message_id": messageID,
                                    "text": reply, "final": true])]
        case "error":
            return [("chat.event", ["conversation_id": conversationID, "kind": "error", "message_id": messageID,
                                    "text": frame["message"] as? String ?? "", "final": true])]
        case "tool_call":
            let text = "\(frame["tool"] as? String ?? ""): \(frame["args_summary"] as? String ?? "")"
            if let last = lastProgress, now.timeIntervalSince(last) < Self.progressInterval {
                heldProgress = text                       // newest wins; flushed later
                return []
            }
            lastProgress = now
            return [progress(text)]
        case "propose_run_command":
            let outside = ["outside", "retry"].contains(frame["sandbox"] as? String ?? "")
            return card(.runCommand, outside ? "Run a command outside the sandbox" : "Run a command",
                        frame["pretty"] as? String ?? frame["command"] as? String ?? "",
                        outside ? "outside_sandbox" : (frame["reason"] as? String ?? "command"))
        case "propose_workspace_write":
            return card(.workspaceWrite, frame["action"] as? String ?? "Write a file", frame["path"] as? String ?? "", "write")
        case "propose_schedule":
            return card(.schedule, "Schedule “\(frame["name"] as? String ?? "")”", frame["when"] as? String ?? "", "schedule")
        case "propose_action":
            return card(.action, frame["kind"] as? String ?? "action", frame["target"] as? String ?? "", "other_app")
        case "job_update":
            return [("job.event", jobEvent(frame))]
        default:
            return []
        }
    }

    /// A held progress line, once its 2 seconds have passed.
    public func flush(now: Date = Date()) -> [Message] {
        guard let text = heldProgress, let last = lastProgress, now.timeIntervalSince(last) >= Self.progressInterval else { return [] }
        heldProgress = nil
        lastProgress = now
        return [progress(text)]
    }

    func progress(_ text: String) -> Message {
        ("chat.event", ["conversation_id": conversationID, "kind": "progress", "message_id": messageID,
                        "text": String(text.prefix(200)), "final": false])
    }

    func jobEvent(_ f: [String: Any]) -> [String: Any] {
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
        return body
    }

    /// A phone message → the frames a window would send. Throws `approval_expired` for a
    /// card the Mac no longer has open.
    public func backendFrames(for type: String, body: [String: Any]) throws -> [[String: Any]] {
        switch type {
        case "chat.send":
            return [["type": "user_message", "content": body["text"] as? String ?? "", "source": "phone"]]
        case "approval.answer":
            guard let id = body["approval_id"] as? String, let kind = cards.removeValue(forKey: id) else {
                throw BridgeError.code("approval_expired")
            }
            let approve = body["decision"] as? String == "approve" && body["auth"] as? String == "faceid"
            var frame: [String: Any] = ["type": "\(approve ? "confirm" : "cancel")_\(kind.rawValue)", "call_id": id]
            if approve && kind == .runCommand { frame["remember"] = false }    // a phone never grants "always"
            return [frame]
        default:
            throw BridgeError.code("unknown_type")
        }
    }
}
