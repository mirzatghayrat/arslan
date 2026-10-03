import CryptoKit
import Foundation
import XCTest
@testable import BridgeCore

final class IdentityTests: XCTestCase {
    func testTheIdentityIsCreatedOnceAndThenTheSame() throws {
        let secrets = MemorySecrets()
        let a = try IdentityStore(secrets: secrets).identity()
        let b = try IdentityStore(secrets: secrets).identity()
        XCTAssertEqual(a.deviceID, b.deviceID)
        XCTAssertTrue(a.deviceID.hasPrefix("mac-"))
        XCTAssertEqual(a.signing.rawRepresentation, b.signing.rawRepresentation)
        XCTAssertEqual(a.exchange.rawRepresentation, b.exchange.rawRepresentation)
        XCTAssertNotEqual(try IdentityStore(secrets: MemorySecrets()).identity().deviceID, a.deviceID)
    }

    func testPhonesArePairedReplacedAndRevoked() throws {
        let store = IdentityStore(secrets: MemorySecrets())
        let key = Curve25519.Signing.PrivateKey().publicKey.rawRepresentation
        let ex = Curve25519.KeyAgreement.PrivateKey().publicKey.rawRepresentation
        try store.save(phone: PairedPhone(deviceID: "iphone-1", name: "A", signing: key, exchange: ex, pairedAt: Date()))
        try store.save(phone: PairedPhone(deviceID: "iphone-2", name: "B", signing: key, exchange: ex, pairedAt: Date()))
        try store.save(phone: PairedPhone(deviceID: "iphone-1", name: "A2", signing: key, exchange: ex, pairedAt: Date()))
        XCTAssertEqual(try store.phones().map(\.name).sorted(), ["A2", "B"])
        XCTAssertNotNil(try store.phones().first?.peer)
        try store.revoke("iphone-1")
        XCTAssertEqual(try store.phones().map(\.deviceID), ["iphone-2"])
    }
}
