// The Bridge at run time (docs/specs/mobile-bridge-protocol.md §6.1): Arslan's control channel on
// one side, the envelope store on the other. Pairing traffic from unpaired phones goes to the
// PairingHost and, as a pending request, to Arslan's window; paired phones go through the Mailbox.
import CoreImage
import CryptoKit
import Foundation

public protocol ControlChannel: AnyObject {
    func send(_ frame: [String: Any]) async throws
}

public enum QRCode {
    /// The pairing URI as a PNG, rendered locally (Core Image), so Arslan's window needs no QR library.
    public static func png(_ text: String, scale: CGFloat = 8) -> Data? {
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        filter.setValue(Data(text.utf8), forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let image = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: scale, y: scale)) else { return nil }
        return CIContext().pngRepresentation(of: image, format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
    }
}

public final class BridgeRuntime {
    public let identity: Identity
    let identities: IdentityStore
    let store: EnvelopeStore
    public let mailbox: Mailbox
    let pairing: PairingHost
    let control: ControlChannel
    let version: String
    var pending: [String: PairRequest] = [:]          // request_id → request, until the user decides

    public init(identities: IdentityStore, store: EnvelopeStore, control: ControlChannel, macName: String,
                containerID: String, version: String, memory: ((String) throws -> MailboxMemoryStore)? = nil) throws {
        identity = try identities.identity()
        (self.identities, self.store, self.control, self.version) = (identities, store, control, version)
        mailbox = Mailbox(deviceID: identity.deviceID, signing: identity.signing, exchange: identity.exchange, store: store,
                          memoryStore: try memory?(identity.deviceID))
        for phone in try identities.phones() { if let peer = phone.peer { mailbox.add(peer: peer) } }
        pairing = PairingHost(macID: identity.deviceID, macName: macName, containerID: containerID,
                              signing: identity.signing, exchange: identity.exchange)
    }

    public func hello() async throws {
        try await control.send(["type": "bridge.hello", "device_id": identity.deviceID, "version": version,
                                "protocol": Wire.version])
        try await sendDevices()
    }

    /// Settings › iPhone's list. `state` is "connecting" until the Mac has read an authenticated
    /// message from that phone, then "connected" with `last_seen` (to the minute, §3.3).
    func sendDevices() async throws {
        let iso = ISO8601DateFormatter()
        let items = try identities.phones().map { phone -> [String: Any] in
            var item: [String: Any] = ["device_id": phone.deviceID, "name": phone.name,
                                       "paired_at": iso.string(from: phone.pairedAt), "state": "connecting"]
            if let heard = mailbox.heard[phone.deviceID] { item["state"] = "connected"; item["last_seen"] = iso.string(from: heard) }
            return item
        }
        try await control.send(["type": "devices", "items": items])
    }

    /// Forget a phone: its keys, and what we sent it that it never acknowledged (§3.3).
    func forget(_ id: String, sparing: Set<String> = []) throws {
        try identities.revoke(id)
        try mailbox.remove(peer: id, sparing: sparing)
    }

    /// At start-up, before the first poll: delete what still waits for a phone that is gone (§3.3).
    public func tidy() async {
        do {
            let dropped = try await mailbox.dropOrphans()
            if dropped > 0 { BridgeLog.notice("clean-up: \(dropped) envelopes for phones no longer paired") }
            try await mailbox.deleteAcknowledged()
        } catch { BridgeLog.error("deleting envelopes for phones no longer paired", error) }   // tried again next start
    }

    /// One frame from Arslan's control channel.
    public func handleControl(_ frame: [String: Any], now: Date = Date()) async throws {
        switch frame["type"] as? String {
        case "pairing.new":
            let (uri, _) = try pairing.newCode(now: now)
            try await control.send(["type": "pairing.code", "uri": uri, "qr_png": QRCode.png(uri)?.base64EncodedString() ?? "",
                                    "expires_at": ISO8601DateFormatter().string(from: now.addingTimeInterval(PairingCode.maxValidity))])
        case "pairing.decide":
            guard let id = frame["request_id"] as? String, let request = pending.removeValue(forKey: id) else { return }
            let accept = frame["accept"] as? Bool == true
            let (record, peer) = try pairing.decide(request, accept ? .accept : .reject("declined_on_mac"), now: now)
            try await store.save(record)
            if let peer {
                try identities.save(phone: PairedPhone(deviceID: request.phoneID, name: request.phoneName,
                                                       signing: request.signing, exchange: request.exchange, pairedAt: now))
                mailbox.add(peer: peer)
                // §3.3: the same phone paired before under other ids. Removed as Settings › Remove does,
                // but told nothing: those identities are gone from the phone. An unknown id matches
                // nothing; the phone's own new id is never one of them (it would unpair itself).
                for old in request.replaces where old != request.phoneID { try forget(old) }
                try await sendDevices()
                await deleteQueued()
            }
        case "devices.list":
            try await sendDevices()
        case "device.revoke":
            guard let id = frame["device_id"] as? String else { return }
            var farewell: Set<String> = []
            if mailbox.isPaired(id) {          // tell the phone first, while its key still opens our message
                if let sent = try? await mailbox.send(type: "device.revoked", body: ["reason": "removed_on_mac"], to: id, now: now) {
                    farewell.insert(sent.id)   // left for the phone to read; the 7-day clean-up takes it
                }
            }
            try forget(id, sparing: farewell)
            try await sendDevices()
            await deleteQueued()
        default:
            return
        }
    }

    func deleteQueued() async {
        do { try await mailbox.deleteAcknowledged() }
        catch { BridgeLog.error("deleting acknowledged records", error) }   // retried next round
    }

    /// One look at the store. Returns the paired phones' messages to act on.
    public func poll(now: Date = Date()) async throws -> [Received] {
        let (records, next) = try await store.changes(since: mailbox.token)
        var forMailbox: [EnvelopeRecord] = []
        for record in records where record.to == identity.deviceID {
            guard !mailbox.isPaired(record.from), record.kind == "control" else {
                forMailbox.append(record)
                continue
            }
            guard let (request, answered) = try? pairing.open(record, now: now) else { continue }   // not a live code's
            if let answered {
                try await store.save(answered)                        // a retry: the same answer again
            } else if pending[request.requestID] == nil {
                pending[request.requestID] = request
                try await control.send(["type": "pairing.request", "request_id": request.requestID,
                                        "pairing_id": request.pairingID, "phone_id": request.phoneID,
                                        "phone_name": request.phoneName])
            }
        }
        let heardBefore = mailbox.heard
        var received = try await mailbox.process(forMailbox, now: now)
        // §3.3: a phone that unpaired itself says so (iPhone 1.0, 2026-10-10: it unpaired and the Mac
        // kept listing it as connected). Forgotten as Settings › Remove does, without a farewell (it has
        // gone), and nothing else from it in this batch is acted on. Only the sender, who signed it: a
        // phone can remove itself, never another.
        let leaving = Set(received.filter { $0.type == "device.revoked" }.map(\.from))
        received.removeAll { leaving.contains($0.from) }
        for id in leaving { try forget(id); BridgeLog.notice("a phone unpaired itself") }
        mailbox.token = next          // only once this batch is acted on and remembered
        try mailbox.remember()
        await deleteQueued()
        // A phone heard from for the first time (connecting → connected), or its last_seen moved on
        // (at most once a minute per phone, Mailbox.heardResolution), or one that left: Settings gets the new list.
        if mailbox.heard != heardBefore || !leaving.isEmpty {
            do { try await sendDevices() } catch { BridgeLog.error("sending the device list", error) }
        }
        return received
    }
}
