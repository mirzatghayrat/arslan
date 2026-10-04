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
//   ArslanBridge              run mode: reads {"port","token","mac_name"} from stdin, connects to
//                             /ws/bridge and the private CloudKit zone, exits when stdin closes
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
    // One JSON line per step, so each result can be read on its own.
    let store = CloudKitStore(containerID: "iCloud.dev.aralem.arslan")
    let id = UUID().uuidString.lowercased()
    var step = "1_zone"
    func report(_ step: String, _ result: String, _ extra: String = "") {
        print("{\"step\": \"\(step)\", \"result\": \"\(result)\"\(extra)}")
    }
    do {
        try await store.ensureZone()
        report(step, "ok", ", \"zone\": \"ArslanBridge\"")
        let start = try await store.changes(since: nil).token
        step = "2_write"
        try await store.save(EnvelopeRecord(id: id, to: "probe", from: "probe", seq: 1, kind: "control",
                                            notify: false, sealed: Data("probe".utf8)))
        report(step, "ok", ", \"record\": \"\(id)\", \"bytes\": 5")
        step = "3_read_back"
        let seen = try await store.changes(since: start).records.first { $0.id == id }
        report(step, seen != nil && seen?.sealed == Data("probe".utf8) ? "ok" : "not_seen")
        step = "4_delete"
        try await store.delete(ids: [id])
        report(step, "ok")
        step = "5_confirm_deleted"
        let still = try await store.exists(id: id)
        report(step, still ? "STILL_THERE" : "ok", ", \"record\": \"\(id)\"")
        exit(seen != nil && !still ? 0 : 1)
    } catch {
        report(step, "failed", ", \"error\": \"\(String(describing: error).prefix(300).replacingOccurrences(of: "\"", with: "'"))\"")
        exit(2)
    }
}
// Run mode. Arslan starts us with one JSON line on stdin — {"port": …, "token": "…", "mac_name": "…"} —
// and holds stdin open; when Arslan quits, stdin closes and so do we. The token never goes through
// the environment or a file (protocol §6).
let containerID = "iCloud.dev.aralem.arslan"
guard let line = readLine(strippingNewline: true),
      let config = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any],
      let port = config["port"] as? Int, let token = config["token"] as? String else {
    FileHandle.standardError.write(Data("ArslanBridge: expected a config line on stdin\n".utf8))
    while let _ = readLine(strippingNewline: true) {}
    exit(0)
}
// --ephemeral (development): keys and envelopes in memory only — no Keychain, no iCloud.
let ephemeral = arguments.contains("--ephemeral")
let control = WebSocketControl(port: port, token: token)
let store: EnvelopeStore = ephemeral ? MemoryStore() : CloudKitStore(containerID: containerID)
let secrets: SecretStore = ephemeral ? MemorySecrets() : KeychainSecrets()
let macName = config["mac_name"] as? String ?? Host.current().localizedName ?? "Mac"
let runtime: BridgeRuntime
do {
    runtime = try BridgeRuntime(identities: IdentityStore(secrets: secrets), store: store, control: control,
                                macName: macName,
                                containerID: containerID, version: bundleVersion(),
                                memory: ephemeral ? nil : { try FileMemoryStore(deviceID: $0) })
} catch {
    FileHandle.standardError.write(Data("ArslanBridge: identity unavailable: \(error)\n".utf8))
    exit(1)
}
control.onConnect = { try? await runtime.hello() }
control.onFrame = { frame in try? await runtime.handleControl(frame) }
let backend = LocalBackend(port: port, token: token)
let links = ConversationLinks(channels: WebSocketChannels(port: port, token: token), mailbox: runtime.mailbox,
                              backend: backend)
let status = StatusReporter(backend: backend, mailbox: runtime.mailbox, deviceName: macName)
links.status = status
Task { await control.run() }
Task {
    if let cloud = store as? CloudKitStore {
        do { try await cloud.ensureZone() } catch { BridgeLog.error("creating the CloudKit zone", error) }
    }
    while true {                                   // §2: every 2 s while the phone app is open, else 10 s
        do { for received in try await runtime.poll() { await links.handle(received) } }
        catch { BridgeLog.error("reading the store", error) }
        try? await Task.sleep(nanoseconds: UInt64(PollPace.interval(lastHeard: runtime.mailbox.lastHeard) * 1_000_000_000))
    }
}
Task {
    while true {                                   // held progress lines, at most one per 2 s per conversation
        await links.flush()
        try? await Task.sleep(nanoseconds: 1_000_000_000)
    }
}
Task {
    while true {                                   // status.snapshot: on change, or a heartbeat every 60 s
        await status.tick()
        try? await Task.sleep(nanoseconds: 2_000_000_000)
    }
}
Task {                                             // §2: envelopes older than 7 days, once a day
    try? await Task.sleep(nanoseconds: 600 * 1_000_000_000)   // first let the polls read what waited meanwhile
    while true {
        do {
            let swept = try await runtime.mailbox.sweep()       // logged every time: how full the zone stays
            BridgeLog.notice("clean-up: deleted \(swept.deleted) envelopes older than 7 days, \(swept.kept) left")
        } catch { BridgeLog.error("deleting envelopes older than 7 days", error) }
        try? await Task.sleep(nanoseconds: 24 * 3600 * 1_000_000_000)
    }
}
// stdin closing means Arslan quit.
Thread.detachNewThread {
    while let _ = readLine(strippingNewline: true) {}
    exit(0)
}
dispatchMain()
