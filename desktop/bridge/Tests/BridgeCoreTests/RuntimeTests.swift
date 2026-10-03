import CoreImage
import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class FakeControl: ControlChannel {
    var sent: [[String: Any]] = []
    func send(_ frame: [String: Any]) async throws { sent.append(frame) }
    func last(_ type: String) -> [String: Any]? { sent.last { $0["type"] as? String == type } }
}

final class RuntimeTests: XCTestCase {
    let container = "iCloud.dev.aralem.arslan"

    func runtime(_ store: MemoryStore, _ control: FakeControl, secrets: MemorySecrets = MemorySecrets()) throws -> BridgeRuntime {
        try BridgeRuntime(identities: IdentityStore(secrets: secrets), store: store, control: control,
                          macName: "Test Mac", containerID: container, version: "0.1.53")
    }

    func testTheQRCodeDecodesBackToTheURI() throws {
        let uri = "arslan://pair?payload=eyJ2IjoxfQ"
        let png = try XCTUnwrap(QRCode.png(uri))
        XCTAssertEqual(Array(png.prefix(4)), [0x89, 0x50, 0x4E, 0x47])
        let image = try XCTUnwrap(CIImage(data: png))
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: nil, options: nil))
        let found = detector.features(in: image).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(found, [uri])
    }

    func testPairingRunsThroughArslansWindowAndOnlyAcceptsOnTheClick() async throws {
        let store = MemoryStore(), control = FakeControl()
        let secrets = MemorySecrets()
        let bridge = try runtime(store, control, secrets: secrets)
        try await bridge.hello()
        XCTAssertEqual(control.last("bridge.hello")?["device_id"] as? String, bridge.identity.deviceID)
        try await bridge.handleControl(["type": "pairing.new"])
        let uri = try XCTUnwrap(control.last("pairing.code")?["uri"] as? String)
        XCTAssertFalse((control.last("pairing.code")?["qr_png"] as? String ?? "").isEmpty)
        // The phone scans and asks.
        let phoneSigning = Curve25519.Signing.PrivateKey(), phoneExchange = Curve25519.KeyAgreement.PrivateKey()
        let request = try PairingHostTests().phoneRequest(uri: uri, now: Date(), phoneSigning: phoneSigning,
                                                          phoneExchange: phoneExchange)
        try await store.save(request)
        _ = try await bridge.poll()
        let pendingFrame = try XCTUnwrap(control.last("pairing.request"))
        XCTAssertEqual(pendingFrame["phone_name"] as? String, "Test iPhone")
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-t"), "nothing is trusted before the click")
        // A second look before the click does not ask twice.
        try await store.save(request)
        _ = try await bridge.poll()
        XCTAssertEqual(control.sent.filter { $0["type"] as? String == "pairing.request" }.count, 1)
        // The user's click in Arslan's window.
        try await bridge.handleControl(["type": "pairing.decide", "request_id": try XCTUnwrap(pendingFrame["request_id"] as? String),
                                        "accept": true])
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-t"))
        XCTAssertEqual((control.last("devices")?["items"] as? [[String: Any]])?.first?["device_id"] as? String, "iphone-t")
        XCTAssertTrue(store.records.values.contains { $0.to == "iphone-t" && $0.kind == "control" }, "pair.accept is in the store")
        // A restarted Bridge still knows the phone (Keychain).
        let restarted = try runtime(store, FakeControl(), secrets: secrets)
        XCTAssertTrue(restarted.mailbox.isPaired("iphone-t"))
        XCTAssertEqual(restarted.identity.deviceID, bridge.identity.deviceID)
    }

    func testDecliningPairsNothingAndRevokeTellsThePhoneThenForgetsIt() async throws {
        let store = MemoryStore(), control = FakeControl()
        let bridge = try runtime(store, control)
        try await bridge.handleControl(["type": "pairing.new"])
        let uri = try XCTUnwrap(control.last("pairing.code")?["uri"] as? String)
        try await store.save(try PairingHostTests().phoneRequest(uri: uri, now: Date()))
        _ = try await bridge.poll()
        let id = try XCTUnwrap(control.last("pairing.request")?["request_id"] as? String)
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": false])
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-t"))
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": true])   // too late
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-t"))

        // Pair another phone, then revoke it.
        try await bridge.handleControl(["type": "pairing.new"])
        let uri2 = try XCTUnwrap(control.last("pairing.code")?["uri"] as? String)
        try await store.save(try PairingHostTests().phoneRequest(uri: uri2, now: Date()))
        _ = try await bridge.poll()
        try await bridge.handleControl(["type": "pairing.decide",
                                        "request_id": try XCTUnwrap(control.last("pairing.request")?["request_id"] as? String),
                                        "accept": true])
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-t"))
        try await bridge.handleControl(["type": "device.revoke", "device_id": "iphone-t"])
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-t"))
        XCTAssertTrue(store.records.values.contains { $0.to == "iphone-t" && $0.kind == "control" && $0.notify },
                      "device.revoked went out (control, with an alert) before the key was forgotten")
        XCTAssertEqual((control.last("devices")?["items"] as? [Any])?.count, 0)
    }
}
