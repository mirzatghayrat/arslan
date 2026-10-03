// The v1 wire format (docs/specs/mobile-bridge-protocol.md §4–§5), CryptoKit only.
// Checked against spec/mobile-bridge/vectors by Tests/BridgeCoreTests.
import CryptoKit
import Foundation

public enum BridgeError: Error, Equatable {
    case code(String)
    public var code: String { if case let .code(c) = self { return c }; return "" }
}

public enum Wire {
    public static let protocolName = "arslan-bridge/v1"
    public static let version = 1
    public static let kinds: Set<String> = ["msg", "ack", "control"]
    public static let maxSealedBytes = 800_000

    static func lp(_ s: String) -> Data {
        let raw = Data(s.utf8)
        var length = UInt32(raw.count).bigEndian
        return Data(bytes: &length, count: 4) + raw
    }

    /// §4.3: twelve length-prefixed UTF-8 fields in a fixed order.
    public static func headerBytes(_ h: Header, includeAsset: Bool = true) -> Data {
        [protocolName, String(h.v), h.id.lowercased(), h.from, h.to, String(h.seq), h.kind, h.ephemeral,
         (h.pairingID ?? "").lowercased(), includeAsset ? (h.assetHash ?? "") : "", h.signingKey ?? "",
         h.notify ? "1" : "0"].reduce(Data()) { $0 + lp($1) }
    }

    static func derive(_ shared: SharedSecret, salt: Data, purpose: String, from: String, to: String) -> SymmetricKey {
        let info = Data("\(protocolName)/\(purpose)".utf8) + lp(from) + lp(to)
        return shared.hkdfDerivedSymmetricKey(using: SHA256.self, salt: salt, sharedInfo: info, outputByteCount: 32)
    }

    static let controlTypes: Set<String> = ["pair.request", "pair.accept", "pair.reject", "hello", "device.revoked"]

    /// §5.1: the clear-text coarse kind a message type travels under.
    public static func kind(of type: String) -> String {
        type == "ack" ? "ack" : (controlTypes.contains(type) ? "control" : "msg")
    }

    /// §5.2: the one clear-text bit that asks for a user-visible alert.
    public static func shouldNotify(type: String, body: [String: Any]) -> Bool {
        switch type {
        case "approval.request", "device.revoked", "error": return true
        case "approval.result": return ["failed", "expired"].contains(body["outcome"] as? String ?? "")
        case "chat.event":
            let kind = body["kind"] as? String
            return kind == "error" || (kind == "message" && body["final"] as? Bool == true)
        case "job.event": return ["done", "partial", "stuck", "stopped"].contains(body["state"] as? String ?? "")
        default: return false
        }
    }
}

public struct Header: Equatable {
    public var v: Int, id: String, from: String, to: String, seq: Int64, kind: String, ephemeral: String, notify: Bool
    public var pairingID: String?, assetHash: String?, signingKey: String?

    public init(v: Int = Wire.version, id: String, from: String, to: String, seq: Int64, kind: String,
                ephemeral: String, notify: Bool, pairingID: String? = nil, assetHash: String? = nil,
                signingKey: String? = nil) {
        (self.v, self.id, self.from, self.to, self.seq, self.kind) = (v, id, from, to, seq, kind)
        (self.ephemeral, self.notify, self.pairingID, self.assetHash, self.signingKey) =
            (ephemeral, notify, pairingID, assetHash, signingKey)
    }

    public init(json: [String: Any]) throws {
        guard let v = json["v"] as? Int, let id = json["id"] as? String, let from = json["from"] as? String,
              let to = json["to"] as? String, let seq = (json["seq"] as? NSNumber)?.int64Value,
              let kind = json["kind"] as? String, let eph = json["ephemeral"] as? String,
              let notify = json["notify"] as? Bool else { throw BridgeError.code("malformed") }
        self.init(v: v, id: id, from: from, to: to, seq: seq, kind: kind, ephemeral: eph, notify: notify,
                  pairingID: json["pairing_id"] as? String, assetHash: json["asset_hash"] as? String,
                  signingKey: json["signing_key"] as? String)
    }
}

public struct Packet {
    public var header: Header
    public var sealed: Data          // nonce(12) || ciphertext || tag(16)
    public var signature: Data       // Ed25519, 64 bytes

    public init(header: Header, sealed: Data, signature: Data) {
        (self.header, self.sealed, self.signature) = (header, sealed, signature)
    }

    public init(json: [String: Any]) throws {
        guard let h = json["header"] as? [String: Any], let s = json["sealed"] as? String,
              let sig = json["signature"] as? String, let sealed = Data(base64Encoded: s),
              let signature = Data(base64Encoded: sig) else { throw BridgeError.code("malformed") }
        header = try Header(json: h)
        self.sealed = sealed
        self.signature = signature
    }
}

public struct Opened {
    public let envelope: [String: Any]
    public let plaintext: Data
    public let asset: Data?
}

public enum Seal {
    /// §4.4. `ephemeral` and `nonce` are drawn fresh per new message; a retry re-sends the
    /// persisted packet (§4.5). They are parameters so the vectors can be reproduced.
    public static func seal(plaintext: Data, type: String, header base: Header, senderSigning: Curve25519.Signing.PrivateKey,
                            recipientExchange: Curve25519.KeyAgreement.PublicKey,
                            ephemeral: Curve25519.KeyAgreement.PrivateKey = .init(), nonce: ChaChaPoly.Nonce = .init(),
                            salt: Data = Data(), asset: Data? = nil, assetNonce: ChaChaPoly.Nonce = .init())
        throws -> (packet: Packet, sealedAsset: Data?) {
        var header = base
        header.kind = Wire.kind(of: type)
        header.ephemeral = ephemeral.publicKey.rawRepresentation.base64EncodedString()
        let shared = try ephemeral.sharedSecretFromKeyAgreement(with: recipientExchange)
        var sealedAsset: Data?
        if let asset {
            let key = Wire.derive(shared, salt: salt, purpose: "asset", from: header.from, to: header.to)
            sealedAsset = try ChaChaPoly.seal(asset, using: key, nonce: assetNonce,
                                              authenticating: Wire.headerBytes(header, includeAsset: false)).combined
            header.assetHash = Data(SHA256.hash(data: sealedAsset!)).base64EncodedString()
        }
        let hb = Wire.headerBytes(header)
        let key = Wire.derive(shared, salt: salt, purpose: "message", from: header.from, to: header.to)
        let body = try ChaChaPoly.seal(plaintext, using: key, nonce: nonce, authenticating: hb).combined
        let signature = try senderSigning.signature(for: hb + body)
        return (Packet(header: header, sealed: body, signature: signature), sealedAsset)
    }

    /// §4.7, in order: shape → recipient → signature → decrypt → agreement → asset.
    public static func open(_ packet: Packet, recipientID: String, recipientExchange: Curve25519.KeyAgreement.PrivateKey,
                            senderSigning: Curve25519.Signing.PublicKey, salt: Data = Data(), asset: Data? = nil) throws -> Opened {
        let h = packet.header
        guard h.v == Wire.version else { throw BridgeError.code("unsupported_version") }
        guard Wire.kinds.contains(h.kind), h.seq > 0, packet.signature.count == 64,
              let ephemeralRaw = Data(base64Encoded: h.ephemeral), ephemeralRaw.count == 32,
              packet.sealed.count >= 28 else { throw BridgeError.code("malformed") }
        guard h.to == recipientID else { throw BridgeError.code("not_for_me") }
        let hb = Wire.headerBytes(h)
        guard senderSigning.isValidSignature(packet.signature, for: hb + packet.sealed) else {
            throw BridgeError.code("bad_signature")
        }
        let ephemeral = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: ephemeralRaw)
        let shared = try recipientExchange.sharedSecretFromKeyAgreement(with: ephemeral)
        let key = Wire.derive(shared, salt: salt, purpose: "message", from: h.from, to: h.to)
        let plaintext: Data
        do {
            plaintext = try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: packet.sealed), using: key, authenticating: hb)
        } catch { throw BridgeError.code("decrypt_failed") }
        guard let envelope = (try? JSONSerialization.jsonObject(with: plaintext)) as? [String: Any] else {
            throw BridgeError.code("malformed")
        }
        guard envelope["v"] as? Int == h.v, envelope["from"] as? String == h.from, envelope["to"] as? String == h.to,
              (envelope["seq"] as? NSNumber)?.int64Value == h.seq,
              (envelope["id"] as? String)?.lowercased() == h.id.lowercased(),
              Wire.kind(of: envelope["type"] as? String ?? "") == h.kind else { throw BridgeError.code("header_mismatch") }
        var opened: Data?
        if let hash = h.assetHash, !hash.isEmpty {
            guard let asset, Data(SHA256.hash(data: asset)).base64EncodedString() == hash else {
                throw BridgeError.code("asset_mismatch")
            }
            let assetKey = Wire.derive(shared, salt: salt, purpose: "asset", from: h.from, to: h.to)
            do {
                opened = try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: asset), using: assetKey,
                                             authenticating: Wire.headerBytes(h, includeAsset: false))
            } catch { throw BridgeError.code("asset_mismatch") }
            let body = envelope["body"] as? [String: Any] ?? [:]
            let digest = SHA256.hash(data: opened!).map { String(format: "%02x", $0) }.joined()
            guard envelope["type"] as? String == "file.offer", (body["size"] as? Int) == opened!.count,
                  body["sha256"] as? String == digest else { throw BridgeError.code("asset_mismatch") }
        }
        return Opened(envelope: envelope, plaintext: plaintext, asset: opened)
    }
}

/// §4.8: per sender, the last `size` sequence numbers; repeats and anything at or below
/// `highest - size` are dropped; out-of-order arrival inside the window is fine.
public struct ReplayWindow {
    public let size: Int64
    private var seen: Set<Int64> = []
    private var highest: Int64 = 0

    public init(size: Int64 = 1024) { self.size = size }

    public mutating func accept(_ seq: Int64) -> Bool {
        if seen.contains(seq) || seq <= highest - size { return false }
        seen.insert(seq)
        highest = max(highest, seq)
        seen = seen.filter { $0 > highest - size }
        return true
    }
}
