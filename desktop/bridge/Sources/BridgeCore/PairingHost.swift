// The Mac's side of pairing (docs/specs/mobile-bridge-protocol.md §3.2), without UI: issue a
// one-time code, open the phone's pair.request, answer it once. The caller shows the
// "iPhone 'x' wants to connect" prompt between `open` and `decide`; nothing is trusted until
// both the pairing key and that click succeed.
import CryptoKit
import Foundation

public struct PairRequest: Equatable {
    public let pairingID: String, requestID: String, phoneID: String, phoneName: String
    public let signing: Data, exchange: Data
    /// Device ids this phone had in earlier pairings with this Mac (§3.3): removed on accept.
    public var replaces: [String] = []

    /// At most this many ids are taken from `replaces`; the rest is ignored.
    public static let maxReplaces = 8
}

public enum PairDecision: Equatable { case accept, reject(String) }

public final class PairingHost {
    struct Code {
        let key: Data
        let expires: Date
        var answered: (request: PairRequest, decision: PairDecision, record: EnvelopeRecord)?
    }

    public let macID: String, macName: String, containerID: String
    let signing: Curve25519.Signing.PrivateKey
    let exchange: Curve25519.KeyAgreement.PrivateKey
    var codes: [String: Code] = [:]
    var seq: Int64

    public init(macID: String, macName: String, containerID: String, signing: Curve25519.Signing.PrivateKey,
                exchange: Curve25519.KeyAgreement.PrivateKey, nextSeq: Int64 = 1) {
        (self.macID, self.macName, self.containerID, self.signing, self.exchange, self.seq) =
            (macID, macName, containerID, signing, exchange, nextSeq)
    }

    /// A fresh one-time code, valid 10 minutes; returns the QR URI and its pairing id.
    public func newCode(now: Date = Date()) throws -> (uri: String, pairingID: String) {
        let id = UUID().uuidString.lowercased()
        var key = Data(count: 32)
        guard key.withUnsafeMutableBytes({ SecRandomCopyBytes(kSecRandomDefault, 32, $0.baseAddress!) }) == errSecSuccess else {
            throw BridgeError.code("malformed")
        }
        let expires = now.addingTimeInterval(PairingCode.maxValidity)
        codes[id] = Code(key: key, expires: expires, answered: nil)
        let iso = ISO8601DateFormatter()
        let payload: [String: Any] = ["v": Wire.version, "pairing_id": id, "mac_device_id": macID, "device_name": macName,
                                      "signing_public_key": signing.publicKey.rawRepresentation.base64EncodedString(),
                                      "exchange_public_key": exchange.publicKey.rawRepresentation.base64EncodedString(),
                                      "pairing_key": key.base64EncodedString(), "container_id": containerID,
                                      "zone": PairingCode.zone, "issued_at": iso.string(from: now), "expires_at": iso.string(from: expires)]
        let json = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        let b64url = json.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        return (PairingCode.scheme + b64url, id)
    }

    /// Open a pair.request. Throws for anything not made with a live code's key.
    /// A retry of an already answered request returns it (the caller re-sends the answer).
    public func open(_ record: EnvelopeRecord, now: Date = Date()) throws -> (request: PairRequest, answered: EnvelopeRecord?) {
        guard let json = (try? JSONSerialization.jsonObject(with: record.sealed)) as? [String: Any] else {
            throw BridgeError.code("malformed")
        }
        let packet = try Packet(json: json)
        guard let pairingID = packet.header.pairingID?.lowercased(), let signingB64 = packet.header.signingKey,
              let signingRaw = Data(base64Encoded: signingB64), signingRaw.count == 32,
              let code = codes[pairingID] else { throw BridgeError.code("pairing_invalid") }
        if let answered = code.answered {
            guard answered.request.requestID == packet.header.id.lowercased() else { throw BridgeError.code("pairing_invalid") }
            return (answered.request, answered.record)
        }
        guard now < code.expires else { throw BridgeError.code("pairing_expired") }
        // Verified with the header's (not yet trusted) key; only the pairing key makes it trusted.
        let opened = try Seal.open(packet, recipientID: macID, recipientExchange: exchange,
                                   senderSigning: try Curve25519.Signing.PublicKey(rawRepresentation: signingRaw), salt: code.key)
        let body = opened.envelope["body"] as? [String: Any] ?? [:]
        guard opened.envelope["type"] as? String == "pair.request", body["signing_public_key"] as? String == signingB64,
              let exchangeB64 = body["exchange_public_key"] as? String, let exchangeRaw = Data(base64Encoded: exchangeB64),
              exchangeRaw.count == 32, let name = body["device_name"] as? String, !name.isEmpty
        else { throw BridgeError.code("malformed") }
        // §3.3: the first eight entries; anything that is not a string is skipped.
        let replaces = (body["replaces"] as? [Any] ?? []).prefix(PairRequest.maxReplaces).compactMap { $0 as? String }
        return (PairRequest(pairingID: pairingID, requestID: packet.header.id.lowercased(), phoneID: packet.header.from,
                            phoneName: name, signing: signingRaw, exchange: exchangeRaw, replaces: replaces), nil)
    }

    /// Answer once, after the user's click on the Mac. The code is spent either way.
    public func decide(_ request: PairRequest, _ decision: PairDecision, now: Date = Date()) throws -> (record: EnvelopeRecord, peer: Peer?) {
        guard var code = codes[request.pairingID], code.answered == nil else { throw BridgeError.code("pairing_invalid") }
        let type: String
        let body: [String: Any]
        switch decision {
        case .accept:
            type = "pair.accept"
            body = ["phone_device_id": request.phoneID, "mac_device_id": macID, "device_name": macName,
                    "signing_public_key": signing.publicKey.rawRepresentation.base64EncodedString(),
                    "exchange_public_key": exchange.publicKey.rawRepresentation.base64EncodedString()]
        case .reject(let reason):
            type = "pair.reject"
            body = ["reason": reason]
        }
        let id = UUID().uuidString.lowercased()
        let envelope: [String: Any] = ["v": Wire.version, "id": id, "seq": seq, "ts": ISO8601DateFormatter().string(from: now),
                                       "from": macID, "to": request.phoneID, "type": type, "body": body]
        let header = Header(id: id, from: macID, to: request.phoneID, seq: seq, kind: Wire.kind(of: type), ephemeral: "",
                            notify: false, pairingID: request.pairingID)
        seq += 1
        let phoneExchange = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: request.exchange)
        let sealed = try Seal.seal(plaintext: try JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys]),
                                   type: type, header: header, senderSigning: signing, recipientExchange: phoneExchange,
                                   salt: code.key).packet
        let data = try JSONSerialization.data(withJSONObject: ["header": Mailbox.headerJSON(sealed.header),
                                                                "sealed": sealed.sealed.base64EncodedString(),
                                                                "signature": sealed.signature.base64EncodedString()])
        let record = EnvelopeRecord(id: id, to: request.phoneID, from: macID, seq: header.seq, kind: sealed.header.kind,
                                    notify: false, sealed: data, createdAt: now)
        code.answered = (request, decision, record)
        codes[request.pairingID] = code
        let peer = decision == .accept
            ? Peer(deviceID: request.phoneID, signing: try .init(rawRepresentation: request.signing), exchange: phoneExchange)
            : nil
        return (record, peer)
    }
}
