// Arslan Bridge — the Mac side of the iPhone companion (docs/specs/mobile-bridge-protocol.md).
//
// Step 2 of the plan: an empty shell. It exists so the hard part of shipping a nested,
// separately signed helper app (Arslan.app/Contents/Helpers/ArslanBridge.app) is proven
// in CI — build, signature, notarization, fresh-install check — before any CloudKit,
// pairing or backend code is written.
//
//   ArslanBridge --version    prints the version and protocol, exits 0
//   ArslanBridge --selftest   checks the CryptoKit primitives the protocol uses, prints JSON
//   ArslanBridge --cloudkit-probe   one live round trip in the private zone (needs the
//                                   signed app, the schema deployed, an iCloud account)
//   ArslanBridge              waits until its stdin closes (Arslan quit), then exits
//
// The real Bridge will read the backend token from stdin (never env or a file).
import BridgeCore
import CryptoKit
import Foundation

let protocolVersion = 1

func bundleVersion() -> String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
}

/// One round of each primitive the wire format needs: X25519 + HKDF-SHA256 +
/// ChaCha20-Poly1305 + Ed25519. Proves the shipped, hardened binary can run them.
func selftest() -> Bool {
    let recipient = Curve25519.KeyAgreement.PrivateKey()
    let ephemeral = Curve25519.KeyAgreement.PrivateKey()
    guard let shared = try? ephemeral.sharedSecretFromKeyAgreement(with: recipient.publicKey),
          let back = try? recipient.sharedSecretFromKeyAgreement(with: ephemeral.publicKey) else { return false }
    let info = Data("arslan-bridge/v1/message".utf8)
    let key = shared.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(), sharedInfo: info, outputByteCount: 32)
    let keyBack = back.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(), sharedInfo: info, outputByteCount: 32)
    let header = Data("header".utf8)
    guard let box = try? ChaChaPoly.seal(Data("hello".utf8), using: key, authenticating: header),
          let opened = try? ChaChaPoly.open(box, using: keyBack, authenticating: header),
          opened == Data("hello".utf8) else { return false }
    let signer = Curve25519.Signing.PrivateKey()
    guard let signature = try? signer.signature(for: box.combined) else { return false }
    return signer.publicKey.isValidSignature(signature, for: box.combined)
}

let arguments = CommandLine.arguments.dropFirst()
if arguments.contains("--version") {
    print("ArslanBridge \(bundleVersion()) protocol \(protocolVersion)")
    exit(0)
}
if arguments.contains("--selftest") {
    let ok = selftest()
    print("{\"bridge_selftest\": \"\(ok ? "passed" : "failed")\", \"protocol\": \(protocolVersion), \"version\": \"\(bundleVersion())\"}")
    exit(ok ? 0 : 1)
}
if arguments.contains("--cloudkit-probe") {
    // Zone, one record to ourselves, read it back through the change feed, delete it.
    let store = CloudKitStore(containerID: "iCloud.dev.aralem.arslan")
    let id = UUID().uuidString.lowercased()
    do {
        try await store.ensureZone()
        let start = try await store.changes(since: nil).token
        try await store.save(EnvelopeRecord(id: id, to: "probe", from: "probe", seq: 1, kind: "control",
                                            notify: false, sealed: Data("probe".utf8)))
        let seen = try await store.changes(since: start).records.contains { $0.id == id }
        try await store.delete(ids: [id])
        print("{\"cloudkit_probe\": \"\(seen ? "passed" : "not_seen")\"}")
        exit(seen ? 0 : 1)
    } catch {
        print("{\"cloudkit_probe\": \"failed\", \"error\": \"\(String(describing: error).prefix(300))\"}")
        exit(2)
    }
}
// Lifecycle: Arslan holds our stdin open; when Arslan quits, stdin closes and so do we.
while let _ = readLine(strippingNewline: true) {}
exit(0)
