// The shared vectors (spec/mobile-bridge/vectors) from the Mac side. The iOS app's CI runs
// the same files; both must pass before a release (protocol §0).
import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class VectorTests: XCTestCase {
    static let vectors: URL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("spec/mobile-bridge/vectors")

    func load(_ rel: String) throws -> [String: Any] {
        let data = try Data(contentsOf: Self.vectors.appendingPathComponent(rel))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func names(_ dir: String) throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: Self.vectors.appendingPathComponent(dir).path)
            .filter { $0.hasSuffix(".json") }.sorted()
    }

    func b64(_ any: Any?) throws -> Data { try XCTUnwrap(Data(base64Encoded: try XCTUnwrap(any as? String))) }

    struct Identity {
        let id: String
        let signing: Curve25519.Signing.PrivateKey
        let exchange: Curve25519.KeyAgreement.PrivateKey
    }

    func identity(_ json: Any?) throws -> Identity {
        let d = try XCTUnwrap(json as? [String: Any])
        return Identity(id: try XCTUnwrap(d["deviceID"] as? String),
                        signing: try .init(rawRepresentation: try b64(d["signingKey"])),
                        exchange: try .init(rawRepresentation: try b64(d["exchangeKey"])))
    }

    func testThereAreVectorsToCheck() throws {
        XCTAssertGreaterThanOrEqual(try names("crypto").count, 11)
        XCTAssertGreaterThanOrEqual(try names("negative").count, 10)
    }

    func testEveryPositiveVectorOpensAndReseals() throws {
        for name in try names("crypto") {
            let v = try load("crypto/\(name)")
            let sender = try identity(v["sender"]), recipient = try identity(v["recipient"])
            let packetJSON = try XCTUnwrap(v["packet"] as? [String: Any])
            let packet = try Packet(json: packetJSON)
            XCTAssertEqual(Wire.headerBytes(packet.header), try b64(v["header_bytes"]), name)
            let salt = try b64(v["psk"])
            let asset = v["asset"] == nil ? nil : try b64(v["asset"])
            let opened = try Seal.open(packet, recipientID: recipient.id, recipientExchange: recipient.exchange,
                                       senderSigning: sender.signing.publicKey, salt: salt, asset: asset)
            XCTAssertEqual(opened.plaintext, try b64(v["plaintext"]), name)
            let type = try XCTUnwrap(opened.envelope["type"] as? String)
            XCTAssertEqual(packet.header.kind, Wire.kind(of: type), name)
            XCTAssertEqual(packet.header.notify,
                           Wire.shouldNotify(type: type, body: opened.envelope["body"] as? [String: Any] ?? [:]), name)
            if asset != nil { XCTAssertEqual(opened.asset, try b64(v["asset_plaintext"]), name) }
            // Re-seal with the vector's fixed ephemeral key and nonce: same ciphertext, same
            // header bytes; CryptoKit's own signature must verify (bytes may differ, §4.4).
            var base = packet.header
            base.assetHash = nil
            let eph = try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: try b64(v["ephemeral_private"]))
            let nonce = try ChaChaPoly.Nonce(data: try b64(v["nonce"]))
            let assetNonce = try ChaChaPoly.Nonce(data: v["asset_nonce"] == nil ? Data(count: 12) : try b64(v["asset_nonce"]))
            let resealed = try Seal.seal(plaintext: opened.plaintext, type: type, header: base, senderSigning: sender.signing,
                                         recipientExchange: recipient.exchange.publicKey, ephemeral: eph, nonce: nonce,
                                         salt: salt, asset: opened.asset, assetNonce: assetNonce)
            XCTAssertEqual(resealed.packet.sealed, packet.sealed, name)
            XCTAssertEqual(Wire.headerBytes(resealed.packet.header), Wire.headerBytes(packet.header), name)
            XCTAssertTrue(sender.signing.publicKey.isValidSignature(
                resealed.packet.signature, for: Wire.headerBytes(resealed.packet.header) + resealed.packet.sealed), name)
            if let a = asset { XCTAssertEqual(resealed.sealedAsset, a, name) }
        }
    }

    func testEveryNegativeVectorIsDroppedWithItsCode() throws {
        for name in try names("negative") {
            let n = try load("negative/\(name)")
            let base = try load("crypto/\(try XCTUnwrap(n["base"] as? String)).json")
            let sender = try identity(base["sender"]), recipient = try identity(base["recipient"])
            let signer = (n["signer"] as? String) == "mac-vector" ? try identity((try load("crypto/mac-message.json"))["sender"]) : sender
            let assetText = (n["asset"] as? String) ?? (base["asset"] as? String)
            let expected = try XCTUnwrap(n["expect_error"] as? String)
            do {
                let packet = try Packet(json: try XCTUnwrap(n["packet"] as? [String: Any]))
                _ = try Seal.open(packet, recipientID: recipient.id, recipientExchange: recipient.exchange,
                                  senderSigning: signer.signing.publicKey, salt: try b64(base["psk"]),
                                  asset: assetText.flatMap { Data(base64Encoded: $0) })
                XCTFail("\(name) opened; expected \(expected)")
            } catch let error as BridgeError {
                XCTAssertEqual(error.code, expected, name)
            }
        }
    }

    func testTheReplayWindowSteps() throws {
        let table = try load("replay-window.json")
        var window = ReplayWindow(size: Int64(try XCTUnwrap(table["window"] as? Int)))
        for step in try XCTUnwrap(table["steps"] as? [[String: Any]]) {
            XCTAssertEqual(window.accept(Int64(try XCTUnwrap(step["seq"] as? Int))), step["accept"] as? Bool, "\(step)")
        }
    }

    func testEveryMessageExampleTravelsUnderItsKindAndNotifyBit() throws {
        for example in try XCTUnwrap(try load("messages.json")["examples"] as? [[String: Any]]) {
            let env = try XCTUnwrap(example["envelope"] as? [String: Any])
            let type = try XCTUnwrap(env["type"] as? String)
            XCTAssertEqual(Wire.kind(of: type), example["kind"] as? String, type)
            XCTAssertEqual(Wire.shouldNotify(type: type, body: env["body"] as? [String: Any] ?? [:]),
                           example["notify"] as? Bool, type)
        }
    }
}

final class PairingVectorTests: XCTestCase {
    func testEveryPairingQRCase() throws {
        let url = VectorTests.vectors.appendingPathComponent("pairing-qr.json")
        let table = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        let container = try XCTUnwrap(table["container_id"] as? String)
        let cases = try XCTUnwrap(table["cases"] as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 9)
        for c in cases {
            let name = c["name"] as? String ?? "?"
            let now = Date(timeIntervalSince1970: try XCTUnwrap(c["now"] as? Double))
            let uri = try XCTUnwrap(c["uri"] as? String)
            if let expected = c["expect_error"] as? String {
                XCTAssertThrowsError(try PairingCode.decode(uri, now: now, containerID: container), name) {
                    XCTAssertEqual(($0 as? BridgeError)?.code, expected, name)
                }
            } else {
                let code = try PairingCode.decode(uri, now: now, containerID: container)
                XCTAssertEqual(code.pairingKey.count, 32, name)
                XCTAssertEqual(code.containerID, container, name)
            }
        }
    }
}
