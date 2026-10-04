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

    func sendDevices() async throws {
        let iso = ISO8601DateFormatter()
        let items = try identities.phones().map { ["device_id": $0.deviceID, "name": $0.name,
                                                   "paired_at": iso.string(from: $0.pairedAt)] as [String: Any] }
        try await control.send(["type": "devices", "items": items])
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
                try await sendDevices()
            }
        case "devices.list":
            try await sendDevices()
        case "device.revoke":
            guard let id = frame["device_id"] as? String else { return }
            if mailbox.isPaired(id) {          // tell the phone first, while its key still opens our message
                _ = try? await mailbox.send(type: "device.revoked", body: ["reason": "removed_on_mac"], to: id, now: now)
            }
            try identities.revoke(id)
            mailbox.remove(peer: id)
            try await sendDevices()
        default:
            return
        }
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
        let received = try await mailbox.process(forMailbox)
        mailbox.token = next          // only once this batch is acted on and remembered
        try mailbox.remember()
        return received
    }
}
