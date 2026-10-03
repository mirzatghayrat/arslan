import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class PairingHostTests: XCTestCase {
    let container = "iCloud.dev.aralem.arslan"

    /// What the phone does after scanning: its own keys, a pair.request sealed with the
    /// pairing key as salt, its signing key in the header.
    func phoneRequest(uri: String, now: Date, id: String = UUID().uuidString.lowercased(),
                      phoneSigning: Curve25519.Signing.PrivateKey = .init(),
                      phoneExchange: Curve25519.KeyAgreement.PrivateKey = .init(),
                      tamperKey: Bool = false, bodySigning: Curve25519.Signing.PublicKey? = nil) throws -> EnvelopeRecord {
        let code = try PairingCode.decode(uri, now: now, containerID: container)
        let body: [String: Any] = ["device_name": "Test iPhone",
                                   "signing_public_key": (bodySigning ?? phoneSigning.publicKey).rawRepresentation.base64EncodedString(),
                                   "exchange_public_key": phoneExchange.publicKey.rawRepresentation.base64EncodedString()]
        let env: [String: Any] = ["v": 1, "id": id, "seq": 1, "ts": "2026-10-03T00:00:00Z", "from": "iphone-t",
                                  "to": code.macDeviceID, "type": "pair.request", "body": body]
        let header = Header(id: id, from: "iphone-t", to: code.macDeviceID, seq: 1, kind: "control", ephemeral: "", notify: false,
                            pairingID: code.pairingID, signingKey: phoneSigning.publicKey.rawRepresentation.base64EncodedString())
        let salt = tamperKey ? Data(repeating: 7, count: 32) : code.pairingKey
        let p = try Seal.seal(plaintext: try JSONSerialization.data(withJSONObject: env, options: [.sortedKeys]),
                              type: "pair.request", header: header, senderSigning: phoneSigning,
                              recipientExchange: try .init(rawRepresentation: code.exchangePublicKey), salt: salt).packet
        let data = try JSONSerialization.data(withJSONObject: ["header": Mailbox.headerJSON(p.header),
                                                                "sealed": p.sealed.base64EncodedString(),
                                                                "signature": p.signature.base64EncodedString()])
        return EnvelopeRecord(id: id, to: code.macDeviceID, from: "iphone-t", seq: 1, kind: "control", notify: false, sealed: data)
    }

    func host() -> PairingHost {
        PairingHost(macID: "mac-t", macName: "Test Mac", containerID: container, signing: .init(), exchange: .init())
    }

    func testAcceptOnceThenTheRetryGetsTheSameAnswer() throws {
        let h = host(), now = Date()
        let (uri, _) = try h.newCode(now: now)
        let phoneExchange = Curve25519.KeyAgreement.PrivateKey()
        let req = try phoneRequest(uri: uri, now: now, phoneExchange: phoneExchange)
        let (request, answered) = try h.open(req, now: now)
        XCTAssertNil(answered)
        XCTAssertEqual(request.phoneName, "Test iPhone")
        let (record, peer) = try h.decide(request, .accept, now: now)
        XCTAssertEqual(peer?.deviceID, "iphone-t")
        // The phone opens the answer with the same salt and the pinned Mac key.
        let code = try PairingCode.decode(uri, now: now, containerID: container)
        let packet = try Packet(json: try XCTUnwrap(JSONSerialization.jsonObject(with: record.sealed) as? [String: Any]))
        let opened = try Seal.open(packet, recipientID: "iphone-t", recipientExchange: phoneExchange,
                                   senderSigning: try .init(rawRepresentation: code.signingPublicKey), salt: code.pairingKey)
        XCTAssertEqual(opened.envelope["type"] as? String, "pair.accept")
        XCTAssertEqual((opened.envelope["body"] as? [String: Any])?["mac_device_id"] as? String, "mac-t")
        XCTAssertEqual(packet.header.pairingID, code.pairingID)
        // A retry of the same request: the same answer, no second decision.
        let (_, again) = try h.open(req, now: now)
        XCTAssertEqual(again, record)
        XCTAssertThrowsError(try h.decide(request, .accept, now: now))
    }

    func testOnlyTheCodesKeyAndALiveCodeAreAccepted() throws {
        let h = host(), now = Date()
        let (uri, _) = try h.newCode(now: now)
        XCTAssertThrowsError(try h.open(try phoneRequest(uri: uri, now: now, tamperKey: true), now: now)) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "decrypt_failed")
        }
        XCTAssertThrowsError(try h.open(try phoneRequest(uri: uri, now: now), now: now.addingTimeInterval(601))) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "pairing_expired")
        }
        let other = host()
        _ = try other.newCode(now: now)
        XCTAssertThrowsError(try other.open(try phoneRequest(uri: uri, now: now), now: now)) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "pairing_invalid")
        }
    }

    func testTheBodyMustClaimTheKeyThatSignedIt() throws {
        let h = host(), now = Date()
        let (uri, _) = try h.newCode(now: now)
        let other = Curve25519.Signing.PrivateKey().publicKey
        XCTAssertThrowsError(try h.open(try phoneRequest(uri: uri, now: now, bodySigning: other), now: now)) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "malformed")
        }
    }

    func testASpentCodeRefusesAnotherRequest() throws {
        let h = host(), now = Date()
        let (uri, _) = try h.newCode(now: now)
        let (request, _) = try h.open(try phoneRequest(uri: uri, now: now), now: now)
        _ = try h.decide(request, .reject("declined_on_mac"), now: now)
        XCTAssertThrowsError(try h.open(try phoneRequest(uri: uri, now: now), now: now)) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "pairing_invalid")
        }
    }

    func testTheCodeDecodesOnThePhoneSide() throws {
        let h = host(), now = Date()
        let (uri, id) = try h.newCode(now: now)
        let code = try PairingCode.decode(uri, now: now, containerID: container)
        XCTAssertEqual(code.pairingID, id)
        XCTAssertEqual(code.expiresAt.timeIntervalSince(code.issuedAt), 600, accuracy: 1)
        XCTAssertThrowsError(try PairingCode.decode(uri, now: now, containerID: "iCloud.other"))
    }
}
