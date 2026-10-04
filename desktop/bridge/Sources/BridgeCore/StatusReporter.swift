// status.snapshot (docs/specs/mobile-bridge-protocol.md §5.3): what the island shows, for the phone's
// home screen. Arslan builds it from the island feed (/api/v1/phone/status); the Bridge adds its own
// name and the time, and sends it when something the phone shows has changed, or as a heartbeat —
// the phone counts a Mac that has been silent for 90 s as offline.
import Foundation

public final class StatusReporter {
    public static let heartbeat: TimeInterval = 60        // under the phone's 90 s
    public static let headlineSpacing: TimeInterval = 2    // mascot, cards waiting, which jobs and their state
    public static let detailSpacing: TimeInterval = 15     // a job's step and progress
    let backend: BackendReads
    let mailbox: Mailbox
    let deviceName: String
    var lastSent: Date?
    var lastHeadline = "", lastDetail = ""

    public init(backend: BackendReads, mailbox: Mailbox, deviceName: String) {
        (self.backend, self.mailbox, self.deviceName) = (backend, mailbox, deviceName)
    }

    /// One look (about every 2 s): send to every paired phone if it is time to.
    public func tick(now: Date = Date()) async {
        guard !mailbox.peers.isEmpty, let body = try? await snapshot(now: now) else { return }
        let (headline, detail) = Self.signature(body)
        guard Self.shouldSend(headline: headline, detail: detail, lastHeadline: lastHeadline,
                              lastDetail: lastDetail, lastSent: lastSent, now: now) else { return }
        (lastSent, lastHeadline, lastDetail) = (now, headline, detail)
        for peer in mailbox.peers.keys.sorted() {
            _ = try? await mailbox.send(type: "status.snapshot", body: body, to: peer, now: now)
        }
    }

    /// At once, to one phone (it just said hello).
    public func send(to peer: String, now: Date = Date()) async {
        guard let body = try? await snapshot(now: now) else { return }
        _ = try? await mailbox.send(type: "status.snapshot", body: body, to: peer, now: now)
    }

    func snapshot(now: Date) async throws -> [String: Any] {
        var body = try await backend.json("/api/v1/phone/status")
        body["jobs"] = (body["jobs"] as? [[String: Any]] ?? []).map { FrameMapper.jobEvent($0, conversationID: "") }
        body["device_name"] = deviceName
        body["last_seen"] = ISO8601DateFormatter().string(from: now)
        return body
    }

    static func signature(_ body: [String: Any]) -> (headline: String, detail: String) {
        let jobs = body["jobs"] as? [[String: Any]] ?? []
        let headline = ["\(body["presence"] ?? "")", "\(body["mascot"] ?? "")", "\(body["waiting_approvals"] ?? "")",
                        jobs.map { "\($0["id"] ?? ""):\($0["state"] ?? "")" }.joined(separator: ",")].joined(separator: "|")
        let detail = jobs.map { "\($0["id"] ?? ""):\($0["current_step"] ?? ""):\($0["completed"] ?? "")/\($0["total"] ?? "")" }
            .joined(separator: ",")
        return (headline, detail)
    }

    static func shouldSend(headline: String, detail: String, lastHeadline: String, lastDetail: String,
                           lastSent: Date?, now: Date) -> Bool {
        guard let lastSent else { return true }
        let gap = now.timeIntervalSince(lastSent)
        if gap >= heartbeat { return true }
        if headline != lastHeadline { return gap >= headlineSpacing }
        if detail != lastDetail { return gap >= detailSpacing }
        return false
    }
}
