// Phone ↔ conversations (docs/specs/mobile-bridge-protocol.md §5.3, §6.1). One link per active
// conversation: a channel to /ws/arslan/<id> and a FrameMapper. The phone's words go in as the
// frames a window sends (marked source "phone"); answers, progress, cards and jobs go back to
// the paired phones.
import CryptoKit
import Foundation

public protocol ConversationChannels {
    /// Open (or reuse) the channel for a conversation; frames from the backend go to `onFrame`.
    func open(conversationID: String, onFrame: @escaping ([String: Any]) async -> Void) -> ControlChannel
}

public final class ConversationLinks {
    public static let pocket = "pocket"                // "no conversation_id" = the pocket conversation
    public static let fileLimit = 20 * 1024 * 1024     // §4.6
    let channels: ConversationChannels
    let mailbox: Mailbox
    let backend: BackendReads
    var links: [String: (channel: ControlChannel, mapper: FrameMapper)] = [:]
    var executed: Set<String> = []                     // client_msg_ids already run (§5.3: once)
    public var status: StatusReporter?                 // a phone saying hello gets the status at once

    public init(channels: ConversationChannels, mailbox: Mailbox, backend: BackendReads = NoBackend()) {
        (self.channels, self.mailbox, self.backend) = (channels, mailbox, backend)
    }

    func link(_ conversationID: String) -> (channel: ControlChannel, mapper: FrameMapper) {
        if let existing = links[conversationID] { return existing }
        let mapper = FrameMapper(conversationID: conversationID)
        let channel = channels.open(conversationID: conversationID) { [weak self] frame in
            await self?.deliver(mapper.phoneMessages(for: frame))
            // A finished turn offers the files it made (references only; the bytes come on file.get).
            if frame["type"] as? String == "stream_end", let run = frame["run_id"] as? Int { await self?.offerFiles(ofRun: run) }
        }
        links[conversationID] = (channel, mapper)
        return (channel, mapper)
    }

    func offerFiles(ofRun run: Int) async {
        guard let files = (try? await backend.json("/api/v1/phone/runs/\(run)/files"))?["files"] as? [[String: Any]] else { return }
        await deliver(files.map { ("file.offer", $0) })
    }

    func deliver(_ messages: [FrameMapper.Message]) async {
        for message in messages {
            for peer in mailbox.peers.keys.sorted() {
                _ = try? await mailbox.send(type: message.type, body: message.body, to: peer)
            }
        }
    }

    /// Held progress lines whose 2 seconds have passed (called about once a second).
    public func flush(now: Date = Date()) async {
        for (_, link) in links { await deliver(link.mapper.flush(now: now)) }
    }

    /// One message from a paired phone.
    public func handle(_ received: Received) async {
        let body = received.envelope["body"] as? [String: Any] ?? [:]
        do {
            switch received.type {
            case "chat.send":
                let clientID = body["client_msg_id"] as? String ?? ""
                guard clientID.isEmpty || !executed.contains(clientID) else { return }
                let link = link(body["conversation_id"] as? String ?? Self.pocket)
                for frame in try link.mapper.backendFrames(for: "chat.send", body: body) { try await link.channel.send(frame) }
                // Only once it reached Arslan: a message that failed to go through runs on the phone's retry.
                if !clientID.isEmpty { executed.insert(clientID) }
            case "approval.answer":
                let id = body["approval_id"] as? String ?? ""
                guard let link = links.values.first(where: { $0.mapper.cards[id] != nil }) else {
                    throw BridgeError.code("approval_expired")
                }
                for frame in try link.mapper.backendFrames(for: "approval.answer", body: body) { try await link.channel.send(frame) }
            case "conversations.list":
                let limit = min(max(body["limit"] as? Int ?? 20, 1), 100)
                let result = try await backend.json("/api/v1/phone/conversations?limit=\(limit)")
                _ = try await mailbox.send(type: "conversations.result", body: result, to: received.from)
            case "chat.history":
                let id = body["conversation_id"] as? String ?? Self.pocket
                let limit = min(max(body["limit"] as? Int ?? 50, 1), 200)
                let result = try await backend.json("/api/v1/phone/conversations/\(id.pathSegment)/history?limit=\(limit)")
                _ = try await mailbox.send(type: "chat.history.result", body: result, to: received.from)
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
                _ = try await mailbox.send(type: "hello", body: ["app_version": "mac", "protocol_version": Wire.version,
                                                                "capabilities": ["chat", "approvals", "jobs", "history", "files",
                                                                                 "status"]],
                                           to: received.from)
                await status?.send(to: received.from)
            case "error":
                return                                 // never answer an error with an error
            default:
                throw BridgeError.code("unknown_type")
            }
        } catch let error as BridgeError {
            let related = (received.envelope["id"] as? String)?.lowercased() ?? ""
            _ = try? await mailbox.send(type: "error", body: ["code": error.code, "message": Self.message(error.code),
                                                             "related_id": related], to: received.from)
        } catch {
            _ = try? await mailbox.send(type: "error", body: ["code": "mac_busy", "message": Self.message("mac_busy")],
                                        to: received.from)
        }
    }

    static func message(_ code: String) -> String {
        switch code {
        case "approval_expired": return "That card is no longer open on the Mac."
        case "unknown_type": return "This Mac does not do that yet."
        case "file_unavailable": return "That file is no longer on the Mac."
        case "too_large": return "That file is too large to send to the phone."
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
}
