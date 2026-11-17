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

extension VectorTests {
    /// §5.13: the Bridge builds vectors (a)–(d) from the Mac's install card: the same fields, the Mac's
    /// `phone_can_approve` (or the absent rule), and the phone's no becomes the window's cancel.
    func testTheCapabilityCardVectorsAreWhatTheBridgeSends() throws {
        let bodies = try XCTUnwrap(try load("messages.json")["examples"] as? [[String: Any]]).compactMap { e -> (String, [String: Any])? in
            let env = e["envelope"] as? [String: Any]
            return (env?["type"] as? String ?? "", env?["body"] as? [String: Any] ?? [:])
        }
        let cards = bodies.filter { $0.0 == "approval.request" && $0.1["perm_kind"] as? String == "capability" }.map(\.1)
        XCTAssertEqual(cards.count, 3)
        for vector in cards {
            var frame: [String: Any] = ["type": "propose_capability", "call_id": vector["approval_id"] as Any,
                                        "name": "excel-mcp-server", "source_url": vector["target"] as Any,
                                        "phone": ["source": vector["source"], "abilities": vector["abilities"], "checks": vector["checks"]]
                                            .compactMapValues { $0 }]
            if let can = vector["phone_can_approve"] { frame["phone_can_approve"] = can }
            let m = FrameMapper(conversationID: "c1")
            let sent = try XCTUnwrap(m.phoneMessages(for: frame).first?.body)
            for key in ["action", "target", "risk", "perm_kind", "source", "abilities", "checks"] {
                func json(_ value: Any?) throws -> Data? {
                    try value.map { try JSONSerialization.data(withJSONObject: [$0], options: [.sortedKeys]) }
                }
                XCTAssertEqual(try json(sent[key]), try json(vector[key]), key)
            }
            XCTAssertEqual(sent["phone_can_approve"] as? Bool, vector["phone_can_approve"] as? Bool ?? false, "(c): absent is no")
            let deny = try XCTUnwrap(bodies.first { $0.0 == "approval.answer" && $0.1["approval_id"] as? String == vector["approval_id"] as? String }?.1)
            XCTAssertEqual(try m.backendFrames(for: "approval.answer", body: deny).first?["type"] as? String, "cancel_capability")
        }
        let results = bodies.filter { $0.0 == "sub_session.history.result" }.map(\.1)
        XCTAssertFalse(results.isEmpty)
        XCTAssertTrue(results.allSatisfy { FrameMapper.flag($0["view_only"]) == true }, "view_only is the literal true")
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
