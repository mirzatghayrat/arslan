// Inbox and outbox over an envelope store (docs/specs/mobile-bridge-protocol.md §2, §4.5, §4.8, §5.3).
// The store is CloudKit in the app (CloudKitStore) and in-memory in tests; everything here is
// independent of it: verification, replay window, duplicates, acks, deleting on ack.
import CryptoKit
import Foundation

/// One CloudKit `Envelope` record. Only the fields CloudKit indexes are in clear text; the
/// receiver trusts the signed header inside `sealed`, never these.
public struct EnvelopeRecord: Equatable {
    public var id: String, to: String, from: String, seq: Int64, kind: String, notify: Bool
    public var sealed: Data, asset: Data?, createdAt: Date

    public init(id: String, to: String, from: String, seq: Int64, kind: String, notify: Bool,
                sealed: Data, asset: Data? = nil, createdAt: Date = Date()) {
        (self.id, self.to, self.from, self.seq, self.kind, self.notify) = (id.lowercased(), to, from, seq, kind, notify)
        (self.sealed, self.asset, self.createdAt) = (sealed, asset, createdAt)
    }
}

public protocol EnvelopeStore {
    func save(_ record: EnvelopeRecord) async throws
    /// New records since `token`, and the token to continue from.
    func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?)
    func delete(ids: [String]) async throws
}

public struct Peer {
    public let deviceID: String
    public let signing: Curve25519.Signing.PublicKey
    public let exchange: Curve25519.KeyAgreement.PublicKey
    public init(deviceID: String, signing: Curve25519.Signing.PublicKey, exchange: Curve25519.KeyAgreement.PublicKey) {
        (self.deviceID, self.signing, self.exchange) = (deviceID, signing, exchange)
    }
}

public struct Received {
    public let from: String
    public let type: String
    public let envelope: [String: Any]
    public let asset: Data?
}

/// What the Bridge must remember across restarts (§4.5, §4.8): its sequence counter, each phone's
/// replay window and the envelopes already acted on, its place in the change feed, and which of its
/// own records still wait for an ack (so a late ack still deletes them). Without it, a restarted
/// Bridge sent seq 1, 2, 3 … again and the phone dropped every message as a replay.
public struct MailboxMemory: Codable, Equatable {
    public var nextSeq: Int64 = 1
    public var windows: [String: ReplayWindow] = [:]
    public var processed: [String] = []          // oldest first, capped
    public var awaitingAck: [String] = []        // oldest first, capped
    public var toDelete: [String] = []           // acked records not yet deleted (a delete that failed is retried)
    public var token: Data?
    public init() {}
    static let cap = 4096
}

public protocol MailboxMemoryStore: AnyObject {
    func load() -> MailboxMemory?
    func save(_ memory: MailboxMemory) throws
}

/// One small JSON file in the Bridge's Application Support folder (nothing secret in it).
public final class FileMemoryStore: MailboxMemoryStore {
    let url: URL
    public init(deviceID: String, directory: URL? = nil) throws {
        let base = try directory ?? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                            appropriateFor: nil, create: true).appendingPathComponent("ArslanBridge")
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        url = base.appendingPathComponent("mailbox-\(deviceID).json")
    }
    public func load() -> MailboxMemory? { (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode(MailboxMemory.self, from: $0) } }
    public func save(_ memory: MailboxMemory) throws { try JSONEncoder().encode(memory).write(to: url, options: [.atomic]) }
}

public final class InMemoryMemoryStore: MailboxMemoryStore {
    public var memory: MailboxMemory?
    public init() {}
    public func load() -> MailboxMemory? { memory }
    public func save(_ memory: MailboxMemory) throws { self.memory = memory }
}

/// This device's side of the conversation with its paired peers.
public final class Mailbox {
    public let deviceID: String
    let signing: Curve25519.Signing.PrivateKey
    let exchange: Curve25519.KeyAgreement.PrivateKey
    let store: EnvelopeStore
    public internal(set) var peers: [String: Peer] = [:]
    var windows: [String: ReplayWindow] = [:]
    var processed: Set<String> = []                 // envelope ids already acted on
    var processedOrder: [String] = []
    var sentAwaitingAck: [String: EnvelopeRecord] = [:]
    var awaitingFromBefore: Set<String> = []        // our records sent before a restart, not yet acked
    public private(set) var toDelete: Set<String> = []   // acked, waiting for CloudKit to delete them
    var nextSeq: Int64
    public var token: Data?
    let memoryStore: MailboxMemoryStore?

    /// With a `memoryStore`, the counter, windows, processed ids and change token survive a restart,
    /// and the counter never starts below the current time in milliseconds — so even a lost file
    /// cannot make it repeat a number the phone has seen.
    public init(deviceID: String, signing: Curve25519.Signing.PrivateKey, exchange: Curve25519.KeyAgreement.PrivateKey,
                store: EnvelopeStore, nextSeq: Int64 = 1, memoryStore: MailboxMemoryStore? = nil, now: Date = Date()) {
        (self.deviceID, self.signing, self.exchange, self.store, self.nextSeq, self.memoryStore) =
            (deviceID, signing, exchange, store, nextSeq, memoryStore)
        guard let memoryStore else { return }
        let memory = memoryStore.load() ?? MailboxMemory()
        self.nextSeq = max(memory.nextSeq, Int64(now.timeIntervalSince1970 * 1000))
        windows = memory.windows
        processedOrder = memory.processed
        processed = Set(memory.processed)
        awaitingFromBefore = Set(memory.awaitingAck)
        toDelete = Set(memory.toDelete)
        token = memory.token
    }

    /// Write what must survive a restart (before any CloudKit write that depends on it).
    public func remember() throws {
        guard let memoryStore else { return }
        var memory = MailboxMemory()
        memory.nextSeq = nextSeq
        memory.windows = windows
        if processedOrder.count > MailboxMemory.cap {
            processedOrder.removeFirst(processedOrder.count - MailboxMemory.cap)
            processed = Set(processedOrder)
        }
        memory.processed = processedOrder
        memory.awaitingAck = Array((awaitingFromBefore.union(sentAwaitingAck.keys)).sorted().suffix(MailboxMemory.cap))
        memory.toDelete = Array(toDelete.sorted().suffix(MailboxMemory.cap))
        memory.token = token
        try memoryStore.save(memory)
    }

    public func add(peer: Peer) { peers[peer.deviceID] = peer }
    public func isPaired(_ deviceID: String) -> Bool { peers[deviceID] != nil }
    public func remove(peer deviceID: String) { peers[deviceID] = nil; windows[deviceID] = nil }

    /// Seal a message to a paired peer and put it in the store. The record is kept until the
    /// peer's `ack`; a retry re-sends this exact record (§4.5). `asset` (a `file.offer`'s bytes)
    /// travels encrypted in the record's asset, bound to the header by its hash (§4.6).
    @discardableResult
    public func send(type: String, body: [String: Any], to peerID: String, id: String = UUID().uuidString.lowercased(),
                     now: Date = Date(), asset: Data? = nil) async throws -> EnvelopeRecord {
        guard let peer = peers[peerID] else { throw BridgeError.code("not_paired") }
        let seq = nextSeq
        nextSeq += 1
        try remember()                      // §4.5: the counter is durable before the record exists
        let envelope: [String: Any] = ["v": Wire.version, "id": id, "seq": seq, "ts": ISO8601DateFormatter().string(from: now),
                                       "from": deviceID, "to": peerID, "type": type, "body": body]
        let plaintext = try JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys])
        let notify = Wire.shouldNotify(type: type, body: body)
        let header = Header(id: id, from: deviceID, to: peerID, seq: seq, kind: Wire.kind(of: type), ephemeral: "", notify: notify)
        let (sealed, sealedAsset) = try Seal.seal(plaintext: plaintext, type: type, header: header, senderSigning: signing,
                                                  recipientExchange: peer.exchange, asset: asset)
        let json: [String: Any] = ["header": Mailbox.headerJSON(sealed.header), "sealed": sealed.sealed.base64EncodedString(),
                                   "signature": sealed.signature.base64EncodedString()]
        let data = try JSONSerialization.data(withJSONObject: json)
        guard data.count <= Wire.maxSealedBytes else { throw BridgeError.code("too_large") }
        let record = EnvelopeRecord(id: id, to: peerID, from: deviceID, seq: seq, kind: sealed.header.kind,
                                    notify: notify, sealed: data, asset: sealedAsset, createdAt: now)
        try await store.save(record)
        if type != "ack" {                                  // an ack is not acknowledged
            sentAwaitingAck[record.id] = record
            try remember()                                  // so a restart still deletes it on its ack
        }
        return record
    }

    /// Fetch, verify and open what arrived; ack it; drop what the peer acknowledged.
    /// Returns the messages to act on (never a duplicate, never one that failed checks).
    public func receive() async throws -> [Received] {
        let (records, next) = try await store.changes(since: token)
        token = next
        let received = try await process(records)
        do { try await deleteAcknowledged() } catch { BridgeLog.error("deleting acknowledged records", error) }
        return received
    }

    /// The same, for records fetched by the caller (the runtime splits pairing traffic off first).
    public func process(_ records: [EnvelopeRecord]) async throws -> [Received] {
        var out: [Received] = []
        var acks: [String: [String]] = [:]
        for record in records where record.to == deviceID {
            guard let peer = peers[record.from],
                  let json = (try? JSONSerialization.jsonObject(with: record.sealed)) as? [String: Any],
                  let packet = try? Packet(json: json),
                  let opened = try? Seal.open(packet, recipientID: deviceID, recipientExchange: exchange,
                                              senderSigning: peer.signing, asset: record.asset) else { continue }
            let id = packet.header.id.lowercased()
            let type = opened.envelope["type"] as? String ?? ""
            lastHeard = Date()
            if processed.contains(id) {                    // a duplicate: ack again, act never
                if type != "ack" { acks[record.from, default: []].append(id) }
                continue
            }
            var window = windows[record.from] ?? ReplayWindow()
            guard window.accept(packet.header.seq) else { continue }
            windows[record.from] = window
            processed.insert(id)
            processedOrder.append(id)
            if type == "ack" {
                let ids = (opened.envelope["body"] as? [String: Any])?["ids"] as? [String] ?? []
                // Deleting is CloudKit work that can fail; it must never stop this batch from being
                // read. The acked ids are queued (and remembered) and deleted by `deleteAcknowledged`.
                let mine = ids.map { $0.lowercased() }.filter { sentAwaitingAck[$0] != nil || awaitingFromBefore.contains($0) }
                mine.forEach { sentAwaitingAck[$0] = nil; awaitingFromBefore.remove($0); toDelete.insert($0) }
                continue
            }
            acks[record.from, default: []].append(id)
            out.append(Received(from: record.from, type: type, envelope: opened.envelope, asset: opened.asset))
        }
        try remember()
        for (peer, ids) in acks { try await send(type: "ack", body: ["ids": ids], to: peer) }
        return out
    }

    /// Delete the records the phone acknowledged. A failure keeps them queued for the next round.
    public func deleteAcknowledged() async throws {
        guard !toDelete.isEmpty else { return }
        let batch = Array(toDelete.sorted().prefix(100))
        try await store.delete(ids: batch)
        batch.forEach { toDelete.remove($0) }
        try remember()
    }

    /// When a paired phone last wrote anything, acks included. While its app is open it acks
    /// every heartbeat, so this stays recent exactly as long as someone is looking (`PollPace`).
    public private(set) var lastHeard: Date?

    /// Records still waiting for an ack (to re-send, unchanged, with backoff).
    public var unacknowledged: [EnvelopeRecord] { Array(sentAwaitingAck.values) }

    static func headerJSON(_ h: Header) -> [String: Any] {
        var out: [String: Any] = ["v": h.v, "id": h.id, "from": h.from, "to": h.to, "seq": h.seq, "kind": h.kind,
                                  "ephemeral": h.ephemeral, "notify": h.notify]
        if let p = h.pairingID { out["pairing_id"] = p }
        if let a = h.assetHash { out["asset_hash"] = a }
        if let s = h.signingKey { out["signing_key"] = s }
        return out
    }
}

/// In-memory store: tests, and a stand-in until CloudKit is configured.
public final class MemoryStore: EnvelopeStore {
    public private(set) var records: [String: EnvelopeRecord] = [:]
    private var log: [String] = []                   // record ids in arrival order

    public init() {}

    /// Like CloudKit's change feed, a re-saved record shows up again as a change.
    public func save(_ record: EnvelopeRecord) async throws {
        log.append(record.id)
        records[record.id] = record
    }

    public func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) {
        let start = token.flatMap { Int(String(decoding: $0, as: UTF8.self)) } ?? 0
        var seen = Set<String>()
        let fresh = log[min(start, log.count)...].reversed().filter { seen.insert($0).inserted }.reversed()
            .compactMap { records[$0] }
        return (fresh, Data(String(log.count).utf8))
    }

    public func delete(ids: [String]) async throws { ids.forEach { records[$0] = nil } }
}

/// How often the Bridge reads the store: every 2 s while the phone wrote in the last two minutes
/// (its app is open: it acks each 60-s heartbeat), else every 10 s. Measured 2026-10-04: at a flat
/// 10 s a phone message waited up to 10 s before the Mac even saw it.
public enum PollPace {
    public static let active: TimeInterval = 2, idle: TimeInterval = 10, window: TimeInterval = 120
    public static func interval(lastHeard: Date?, now: Date = Date()) -> TimeInterval {
        guard let lastHeard, now.timeIntervalSince(lastHeard) < window else { return idle }
        return active
    }
}
