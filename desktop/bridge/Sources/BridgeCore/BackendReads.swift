// What the Bridge reads from Arslan for a paired phone (docs/specs/mobile-bridge-protocol.md §5.3):
// the conversation list, a conversation's history, the files a turn made and one file's bytes —
// /api/v1/phone/* on the local backend, with the same token the sockets use. Since §5.7
// (2026-10-13) also: saving a file the phone sent, reading its text (/api/v1/extract) and
// deleting a conversation (DELETE /api/v1/conversations/<id>).
import Foundation

public protocol BackendReads {
    /// GET one JSON object. Throws a BridgeError carrying the code the phone should see.
    func json(_ path: String) async throws -> [String: Any]
    /// POST a JSON body, get one JSON object back (starting or stopping a task).
    func post(_ path: String, body: [String: Any]) async throws -> [String: Any]
    /// DELETE, one JSON object back (a conversation the phone deleted). A 404 is `not_found`.
    func delete(_ path: String) async throws -> [String: Any]
    /// POST one file as multipart/form-data (`field`, with its file name), one JSON object back.
    func upload(_ path: String, field: String, filename: String, mimeType: String, data: Data) async throws -> [String: Any]
}

extension BackendReads {
    public func delete(_ path: String) async throws -> [String: Any] { throw BridgeError.code("mac_busy") }
    public func upload(_ path: String, field: String, filename: String, mimeType: String, data: Data) async throws -> [String: Any] {
        throw BridgeError.code("mac_busy")
    }
}

public final class LocalBackend: BackendReads {
    let port: Int, token: String

    public init(port: Int, token: String) { (self.port, self.token) = (port, token) }

    public func json(_ path: String) async throws -> [String: Any] { try await call(path, method: "GET", body: nil) }

    public func post(_ path: String, body: [String: Any]) async throws -> [String: Any] {
        try await call(path, method: "POST", body: body)
    }

    public func delete(_ path: String) async throws -> [String: Any] {
        try await call(path, method: "DELETE", body: nil, notFound: "not_found")
    }

    /// Reading a long PDF's text can take a while: two minutes, not thirty seconds.
    public func upload(_ path: String, field: String, filename: String, mimeType: String, data: Data) async throws -> [String: Any] {
        let boundary = "arslan-bridge-\(UUID().uuidString)"
        var payload = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"\(Self.headerSafe(filename))\"\r\n".utf8)
        payload += Data("Content-Type: \(Self.headerSafe(mimeType))\r\n\r\n".utf8) + data + Data("\r\n--\(boundary)--\r\n".utf8)
        return try await send(path, method: "POST", contentType: "multipart/form-data; boundary=\(boundary)", payload: payload,
                              timeout: 120)
    }

    /// A file name inside a multipart header: printable ASCII without quotes, else "file" with the
    /// name's extension (what /extract reads the kind from).
    static func headerSafe(_ name: String) -> String {
        if name.allSatisfy({ $0.isASCII && !$0.isNewline && $0 != "\"" && $0 != "\\" && ($0.asciiValue ?? 0) >= 32 }), !name.isEmpty {
            return name
        }
        let ext = (name as NSString).pathExtension
        return ext.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) && !ext.isEmpty ? "file.\(ext)" : "file"
    }

    func call(_ path: String, method: String, body: [String: Any]?, notFound: String = "file_unavailable") async throws -> [String: Any] {
        let payload = try body.map { try JSONSerialization.data(withJSONObject: $0) }
        return try await send(path, method: method, contentType: body == nil ? nil : "application/json", payload: payload,
                              notFound: notFound)
    }

    func send(_ path: String, method: String, contentType: String?, payload: Data?, timeout: TimeInterval = 30,
              notFound: String = "file_unavailable") async throws -> [String: Any] {
        guard let url = URL(string: "http://127.0.0.1:\(port)\(path)") else { throw BridgeError.code("malformed") }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        request.httpBody = payload
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(status: (response as? HTTPURLResponse)?.statusCode ?? 0, notFound: notFound)
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BridgeError.code("mac_busy")
        }
        return object
    }

    /// The backend's status → the code the phone sees (§5.4). A 404 is the file reads'
    /// `file_unavailable`, or `not_found` for a conversation (§5.7).
    static func check(status: Int, notFound: String = "file_unavailable") throws {
        switch status {
        case 200: return
        case 404: throw BridgeError.code(notFound)
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
