// The Bridge's end of /ws/bridge (docs/specs/mobile-bridge-protocol.md §6.1): the API token as
// the query parameter and the same-origin Origin header the backend requires in a packaged build.
// Reconnects with backoff; frames go to `onFrame`.
import Foundation

public final class WebSocketControl: NSObject, ControlChannel {
    let url: URL
    let origin: String
    var task: URLSessionWebSocketTask?
    var stopped = false
    /// `run`'s task makes and drops the socket while `send` (the poll loop, the conversation links) and `stop` reach
    /// it from others: `task` and `stopped` are only touched under this lock, never held across an `await` or a send.
    let socketLock = NSLock()
    func socketLocked<T>(_ body: () throws -> T) rethrows -> T {
        socketLock.lock()
        defer { socketLock.unlock() }
        return try body()
    }
    /// The socket right now, read under the lock.
    var currentTask: URLSessionWebSocketTask? { socketLocked { task } }
    lazy var session = URLSession(configuration: .ephemeral)
    public var onFrame: (([String: Any]) async -> Void)?
    public var onConnect: (() async -> Void)?

    /// `path` is /ws/bridge for the control channel, /ws/arslan/<id> for a conversation.
    public init(port: Int, token: String, path: String = "/ws/bridge") {
        var parts = URLComponents()
        (parts.scheme, parts.host, parts.port, parts.path) = ("ws", "127.0.0.1", port, path)
        parts.queryItems = [URLQueryItem(name: "token", value: token)]
        url = parts.url!
        origin = "http://127.0.0.1:\(port)"
    }

    public func send(_ frame: [String: Any]) async throws {
        guard let task = currentTask else { throw BridgeError.code("mac_busy") }    // between reconnects
        let text = String(decoding: try JSONSerialization.data(withJSONObject: frame), as: UTF8.self)
        try await task.send(.string(text))     // before the handshake completes, URLSession holds it
    }

    /// Create the socket now, so a frame sent right after opening has somewhere to go, and keep it
    /// up from a background task (see `run`).
    public func start() {
        let first = connect()
        Task { await self.run(startingWith: first) }
    }

    func connect() -> URLSessionWebSocketTask {
        var request = URLRequest(url: url)
        request.setValue(origin, forHTTPHeaderField: "Origin")
        let task = session.webSocketTask(with: request)
        socketLocked { self.task = task }
        task.resume()
        return task
    }

    /// Close for good (§5.7: the conversation was deleted, or its link is no longer kept): no reconnect.
    public func stop() {
        let task = socketLocked { () -> URLSessionWebSocketTask? in
            stopped = true
            defer { self.task = nil }
            return self.task
        }
        task?.cancel(with: .goingAway, reason: nil)    // outside the lock
        // The session is not invalidated: `run` may be about to make its next task on it, and a task
        // on an invalidated session throws. The loop sees `stopped` and makes none.
    }

    /// Connect, read until the socket fails, reconnect after 1, 2, 4 … 30 s. Returns only after `stop`.
    public func run(startingWith first: URLSessionWebSocketTask? = nil) async {
        var delay: UInt64 = 1
        var next = first
        while !socketLocked({ stopped }) {
            let task = next ?? connect()
            next = nil
            if socketLocked({ stopped }) { task.cancel(with: .goingAway, reason: nil); return }    // stopped while it was being made
            do {
                await onConnect?()
                while true {
                    let message = try await task.receive()
                    delay = 1
                    let data: Data
                    switch message {
                    case .string(let text): data = Data(text.utf8)
                    case .data(let raw): data = raw
                    @unknown default: continue
                    }
                    if let frame = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] { await onFrame?(frame) }
                }
            } catch {
                task.cancel(with: .goingAway, reason: nil)
                socketLocked { self.task = nil }
            }
            if socketLocked({ stopped }) { return }
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            delay = min(delay * 2, 30)
        }
    }
}
