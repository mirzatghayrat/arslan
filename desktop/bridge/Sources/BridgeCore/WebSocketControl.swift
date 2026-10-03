// The Bridge's end of /ws/bridge (docs/specs/mobile-bridge-protocol.md §6.1): the API token as
// the query parameter and the same-origin Origin header the backend requires in a packaged build.
// Reconnects with backoff; frames go to `onFrame`.
import Foundation

public final class WebSocketControl: NSObject, ControlChannel {
    let url: URL
    let origin: String
    var task: URLSessionWebSocketTask?
    lazy var session = URLSession(configuration: .ephemeral)
    public var onFrame: (([String: Any]) async -> Void)?
    public var onConnect: (() async -> Void)?

    public init(port: Int, token: String) {
        var parts = URLComponents()
        (parts.scheme, parts.host, parts.port, parts.path) = ("ws", "127.0.0.1", port, "/ws/bridge")
        parts.queryItems = [URLQueryItem(name: "token", value: token)]
        url = parts.url!
        origin = "http://127.0.0.1:\(port)"
    }

    public func send(_ frame: [String: Any]) async throws {
        guard let task else { throw BridgeError.code("mac_busy") }
        let text = String(decoding: try JSONSerialization.data(withJSONObject: frame), as: UTF8.self)
        try await task.send(.string(text))
    }

    /// Connect, read until the socket fails, reconnect after 1, 2, 4 … 30 s. Never returns.
    public func run() async {
        var delay: UInt64 = 1
        while true {
            var request = URLRequest(url: url)
            request.setValue(origin, forHTTPHeaderField: "Origin")
            let task = session.webSocketTask(with: request)
            self.task = task
            task.resume()
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
                self.task = nil
            }
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            delay = min(delay * 2, 30)
        }
    }
}
