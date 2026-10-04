// What the Bridge reads from Arslan for a paired phone (docs/specs/mobile-bridge-protocol.md §5.3):
// the conversation list, a conversation's history, the files a turn made and one file's bytes —
// /api/v1/phone/* on the local backend, with the same token the sockets use.
import Foundation

public protocol BackendReads {
    /// GET one JSON object. Throws a BridgeError carrying the code the phone should see.
    func json(_ path: String) async throws -> [String: Any]
    /// POST a JSON body, get one JSON object back (starting or stopping a task).
    func post(_ path: String, body: [String: Any]) async throws -> [String: Any]
}

public final class LocalBackend: BackendReads {
    let port: Int, token: String

    public init(port: Int, token: String) { (self.port, self.token) = (port, token) }

    public func json(_ path: String) async throws -> [String: Any] { try await call(path, method: "GET", body: nil) }

    public func post(_ path: String, body: [String: Any]) async throws -> [String: Any] {
        try await call(path, method: "POST", body: body)
    }

    func call(_ path: String, method: String, body: [String: Any]?) async throws -> [String: Any] {
        guard let url = URL(string: "http://127.0.0.1:\(port)\(path)") else { throw BridgeError.code("malformed") }
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(status: (response as? HTTPURLResponse)?.statusCode ?? 0)
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BridgeError.code("mac_busy")
        }
        return object
    }

    /// The backend's status → the code the phone sees (§5.4).
    static func check(status: Int) throws {
        switch status {
        case 200: return
        case 404: throw BridgeError.code("file_unavailable")      // only the file reads answer 404
        case 413: throw BridgeError.code("too_large")
        case 422: throw BridgeError.code("malformed")
        default: throw BridgeError.code("mac_busy")
        }
    }
}

/// No backend (tests that never read): every read is "busy".
public struct NoBackend: BackendReads {
    public init() {}
    public func json(_ path: String) async throws -> [String: Any] { throw BridgeError.code("mac_busy") }
    public func post(_ path: String, body: [String: Any]) async throws -> [String: Any] { throw BridgeError.code("mac_busy") }
}

extension String {
    /// This string as one URL path segment.
    var pathSegment: String {
        addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-._~"))) ?? ""
    }
}
