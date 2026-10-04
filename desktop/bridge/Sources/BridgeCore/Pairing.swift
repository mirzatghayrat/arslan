// The pairing QR code (docs/specs/mobile-bridge-protocol.md §3.1). The Mac makes the code;
// the phone validates it. Both sides keep the rules here so the shared vectors check both.
import Foundation

public struct PairingCode: Equatable {
    public static let scheme = "arslan://pair?payload="
    public static let maxBytes = 8192
    public static let maxValidity: TimeInterval = 600
    public static let clockSkew: TimeInterval = 30
    public static let zone = "ArslanBridge"

    public var pairingID: String, macDeviceID: String, deviceName: String
    public var signingPublicKey: Data, exchangePublicKey: Data, pairingKey: Data
    public var containerID: String, issuedAt: Date, expiresAt: Date

    static func iso(_ s: String?) -> Date? {
        guard let s else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)
    }

    static func key(_ any: Any?) throws -> Data {
        guard let s = any as? String, let d = Data(base64Encoded: s), d.count == 32 else { throw BridgeError.code("malformed") }
        return d
    }

    /// The phone's checks, in the order the reference applies them.
    public static func decode(_ uri: String, now: Date, containerID: String) throws -> PairingCode {
        guard uri.utf8.count <= maxBytes else { throw BridgeError.code("too_large") }
        guard let parts = URLComponents(string: uri), parts.scheme == "arslan", parts.host == "pair",
              parts.path.isEmpty || parts.path == "/", let items = parts.queryItems, items.count == 1,
              items[0].name == "payload", var text = items[0].value else { throw BridgeError.code("malformed") }
        text = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        text += String(repeating: "=", count: (4 - text.count % 4) % 4)
        guard let raw = Data(base64Encoded: text),
              let json = (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any] else {
            throw BridgeError.code("malformed")
        }
        guard json["v"] as? Int == Wire.version else { throw BridgeError.code("unsupported_version") }
        guard let mac = json["mac_device_id"] as? String, (1...128).contains(mac.utf8.count),
              let name = json["device_name"] as? String, (1...256).contains(name.utf8.count),
              let id = json["pairing_id"] as? String, let uuid = UUID(uuidString: id), uuid.uuidString.lowercased() == id.lowercased(),
              let issued = iso(json["issued_at"] as? String), let expires = iso(json["expires_at"] as? String),
              let container = json["container_id"] as? String, let zone = json["zone"] as? String
        else { throw BridgeError.code("malformed") }
        let signing = try key(json["signing_public_key"]), exchange = try key(json["exchange_public_key"])
        let pairingKey = try key(json["pairing_key"])
        guard container == containerID else { throw BridgeError.code("wrong_container") }
        guard zone == Self.zone else { throw BridgeError.code("malformed") }
        guard expires > issued, expires.timeIntervalSince(issued) <= maxValidity,
              issued <= now.addingTimeInterval(clockSkew) else { throw BridgeError.code("pairing_invalid") }
        guard now < expires else { throw BridgeError.code("pairing_expired") }
        return PairingCode(pairingID: id.lowercased(), macDeviceID: mac, deviceName: name, signingPublicKey: signing,
                           exchangePublicKey: exchange, pairingKey: pairingKey, containerID: container,
                           issuedAt: issued, expiresAt: expires)
    }
}
