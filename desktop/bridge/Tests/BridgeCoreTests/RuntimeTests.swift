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

    func runtime(_ store: MemoryStore, _ control: FakeControl, secrets: MemorySecrets = MemorySecrets(),
                 memory: MailboxMemoryStore? = nil) throws -> BridgeRuntime {
        try BridgeRuntime(identities: IdentityStore(secrets: secrets), store: store, control: control,
                          macName: "Test Mac", containerID: container, version: "0.1.53", memory: memory.map { m in { _ in m } })
    }

    /// A phone scans a fresh code and asks; returns the request id once the Mac has shown it.
    func ask(_ bridge: BridgeRuntime, _ store: MemoryStore, _ control: FakeControl, phoneID: String,
             replaces: [Any]? = nil, signing: Curve25519.Signing.PrivateKey = .init(),
             exchange: Curve25519.KeyAgreement.PrivateKey = .init()) async throws -> String {
        try await bridge.handleControl(["type": "pairing.new"])
        let uri = try XCTUnwrap(control.last("pairing.code")?["uri"] as? String)
        try await store.save(try PairingHostTests().phoneRequest(uri: uri, now: Date(), phoneSigning: signing,
                                                                 phoneExchange: exchange, phoneID: phoneID, replaces: replaces))
        _ = try await bridge.poll()
        let frame = try XCTUnwrap(control.last("pairing.request"))
        XCTAssertEqual(frame["phone_id"] as? String, phoneID)
        return try XCTUnwrap(frame["request_id"] as? String)
    }

    func pair(_ bridge: BridgeRuntime, _ store: MemoryStore, _ control: FakeControl, phoneID: String,
              replaces: [Any]? = nil) async throws {
        let id = try await ask(bridge, store, control, phoneID: phoneID, replaces: replaces)
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": true])
    }

    func listed(_ control: FakeControl) -> [String] {
        (control.last("devices")?["items"] as? [[String: Any]] ?? []).compactMap { $0["device_id"] as? String }.sorted()
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

    // §3.3, found 2026-10-07: each pairing gives the phone a new id, so the same phone scanning again
    // became another row in Settings and the Bridge kept writing to the old ids for good.

    func testAPhoneThatPairsAgainReplacesItsOldIdsWhenAcceptedAndTheyAreToldNothing() async throws {
        let store = MemoryStore(), control = FakeControl(), secrets = MemorySecrets()
        let bridge = try runtime(store, control, secrets: secrets)
        try await pair(bridge, store, control, phoneID: "iphone-old")
        try await pair(bridge, store, control, phoneID: "iphone-other")
        let waiting = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-old")
        let others = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-other")
        let before = Set(store.records.keys), seqBefore = bridge.mailbox.nextSeq
        try await pair(bridge, store, control, phoneID: "iphone-new",
                       replaces: ["iphone-old", "iphone-unknown", 42, "iphone-new"])
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-old"), "the old identity is gone")
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-new"), "its own new id in the list never unpairs it")
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-other"), "another phone is untouched")
        XCTAssertEqual(listed(control), ["iphone-new", "iphone-other"], "Settings shows one row for the phone again")
        XCTAssertEqual(try IdentityStore(secrets: secrets).phones().map(\.deviceID).sorted(),
                       ["iphone-new", "iphone-other"], "its keys are forgotten too")
        XCTAssertNil(store.records[waiting.id], "what waited for the old id's ack is deleted")
        XCTAssertNotNil(store.records[others.id])
        let added = store.records.values.filter { !before.contains($0.id) && $0.from == bridge.identity.deviceID }
        XCTAssertEqual(added.map(\.to), ["iphone-new"], "only the pair.accept went out: nothing to the replaced id")
        XCTAssertEqual(bridge.mailbox.nextSeq, seqBefore, "the mailbox wrote nothing at all, not even a message it then deleted")
    }

    func testDecliningAPhoneThatListsReplacesRemovesNothing() async throws {
        let store = MemoryStore(), control = FakeControl()
        let bridge = try runtime(store, control)
        try await pair(bridge, store, control, phoneID: "iphone-old")
        let waiting = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-old")
        let id = try await ask(bridge, store, control, phoneID: "iphone-new", replaces: ["iphone-old"])
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": false])
        XCTAssertTrue(bridge.mailbox.isPaired("iphone-old"))
        XCTAssertEqual(listed(control), ["iphone-old"])
        XCTAssertNotNil(store.records[waiting.id])
    }

    func testRemovingAPhoneDeletesWhatWaitsForItButLeavesItsFarewell() async throws {
        let store = MemoryStore(), control = FakeControl()
        let bridge = try runtime(store, control)
        try await pair(bridge, store, control, phoneID: "iphone-a")
        try await pair(bridge, store, control, phoneID: "iphone-b")
        let waiting = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-a")
        let others = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-b")
        try await bridge.handleControl(["type": "device.revoke", "device_id": "iphone-a"])
        XCTAssertNil(store.records[waiting.id], "deleted at once, not left for the 7-day clean-up")
        XCTAssertNotNil(store.records[others.id], "another phone's record stays")
        let farewell = store.records.values.filter { $0.to == "iphone-a" && $0.kind == "control" && $0.notify }
        XCTAssertEqual(farewell.count, 1, "device.revoked stays for the phone to read")
        XCTAssertEqual(bridge.mailbox.unacknowledged.map(\.id), [others.id], "and nothing waits for the removed phone")
    }

    /// The phone's own side of a pairing as a Mailbox, for sending as that phone.
    func phoneSide(_ bridge: BridgeRuntime, _ store: MemoryStore, id: String, signing: Curve25519.Signing.PrivateKey,
                   exchange: Curve25519.KeyAgreement.PrivateKey) -> Mailbox {
        let phone = Mailbox(deviceID: id, signing: signing, exchange: exchange, store: store)
        phone.add(peer: Peer(deviceID: bridge.identity.deviceID, signing: bridge.identity.signing.publicKey,
                             exchange: bridge.identity.exchange.publicKey))
        return phone
    }

    /// §3.3: a phone that unpairs itself says so (iPhone 1.0, 2026-10-10: the phone unpaired and the
    /// Mac kept showing it connected). The Mac forgets it as Settings › Remove does, without the
    /// farewell, and nothing more from it reaches Arslan.
    func testAPhoneThatUnpairsItselfIsForgottenAndNothingMoreFromItIsActedOn() async throws {
        let store = MemoryStore(), control = FakeControl(), secrets = MemorySecrets(), memory = InMemoryMemoryStore()
        let bridge = try runtime(store, control, secrets: secrets, memory: memory)
        let signing = Curve25519.Signing.PrivateKey(), exchange = Curve25519.KeyAgreement.PrivateKey()
        let id = try await ask(bridge, store, control, phoneID: "iphone-t", signing: signing, exchange: exchange)
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": true])
        XCTAssertEqual(listed(control), ["iphone-t"])
        let phone = phoneSide(bridge, store, id: "iphone-t", signing: signing, exchange: exchange)
        try await phone.send(type: "conversations.list", body: [:], to: bridge.identity.deviceID)
        try await phone.send(type: "device.revoked", body: ["reason": "unpaired_on_phone"], to: bridge.identity.deviceID)
        let received = try await bridge.poll()
        XCTAssertTrue(received.isEmpty, "a phone that has gone is not answered")
        XCTAssertEqual(listed(control), [], "Settings › iPhone drops it at once")
        XCTAssertFalse(bridge.mailbox.isPaired("iphone-t"))
        let sentBefore = control.sent.count
        try await phone.send(type: "conversations.list", body: [:], to: bridge.identity.deviceID)
        _ = try await bridge.poll()
        XCTAssertFalse(control.sent.dropFirst(sentBefore).contains { $0["type"] as? String == "pairing.request" },
                       "a later message from its old key is not taken as a new pairing either")
        let restartedControl = FakeControl()
        try await runtime(store, restartedControl, secrets: secrets, memory: memory).hello()
        XCTAssertEqual(listed(restartedControl), [], "forgotten for good: its keys are gone")
    }

    func testAPhoneCanOnlyUnpairItselfNeverAnother() async throws {
        let store = MemoryStore(), control = FakeControl()
        let bridge = try runtime(store, control)
        let signing = Curve25519.Signing.PrivateKey(), exchange = Curve25519.KeyAgreement.PrivateKey()
        let a = try await ask(bridge, store, control, phoneID: "iphone-a", signing: signing, exchange: exchange)
        try await bridge.handleControl(["type": "pairing.decide", "request_id": a, "accept": true])
        try await pair(bridge, store, control, phoneID: "iphone-b")
        let phone = phoneSide(bridge, store, id: "iphone-a", signing: signing, exchange: exchange)
        try await phone.send(type: "device.revoked", body: ["reason": "unpaired_on_phone", "device_id": "iphone-b"],
                             to: bridge.identity.deviceID)
        _ = try await bridge.poll()
        XCTAssertEqual(listed(control), ["iphone-b"], "the sender is who signed it; a body naming another phone changes nothing")
    }

    func testAPhoneIsConnectingUntilHeardThenConnectedAndStaysSoAcrossARestart() async throws {
        let store = MemoryStore(), control = FakeControl(), secrets = MemorySecrets(), memory = InMemoryMemoryStore()
        let bridge = try runtime(store, control, secrets: secrets, memory: memory)
        let signing = Curve25519.Signing.PrivateKey(), exchange = Curve25519.KeyAgreement.PrivateKey()
        let id = try await ask(bridge, store, control, phoneID: "iphone-t", signing: signing, exchange: exchange)
        try await bridge.handleControl(["type": "pairing.decide", "request_id": id, "accept": true])
        var item = try XCTUnwrap((control.last("devices")?["items"] as? [[String: Any]])?.first)
        XCTAssertEqual(item["state"] as? String, "connecting", "paired, not heard from yet")
        XCTAssertNil(item["last_seen"])

        let phone = Mailbox(deviceID: "iphone-t", signing: signing, exchange: exchange, store: store)
        phone.add(peer: Peer(deviceID: bridge.identity.deviceID, signing: bridge.identity.signing.publicKey,
                             exchange: bridge.identity.exchange.publicKey))
        let t = Date(timeIntervalSince1970: 1_791_331_200)
        let frames = { control.sent.filter { $0["type"] as? String == "devices" }.count }
        let framesBefore = frames()
        _ = try await bridge.poll(now: t)                               // nothing from the phone yet
        XCTAssertEqual(frames(), framesBefore)
        try await phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": []],
                             to: bridge.identity.deviceID)
        _ = try await bridge.poll(now: t)
        XCTAssertEqual(frames(), framesBefore + 1, "the change to connected is sent at once")
        item = try XCTUnwrap((control.last("devices")?["items"] as? [[String: Any]])?.first)
        XCTAssertEqual(item["state"] as? String, "connected")
        XCTAssertEqual(item["last_seen"] as? String, ISO8601DateFormatter().string(from: t))

        _ = try await phone.receive()                                   // the phone acks the Mac's ack… every heartbeat
        try await phone.send(type: "conversations.list", body: [:], to: bridge.identity.deviceID)
        _ = try await bridge.poll(now: t + 30)
        XCTAssertEqual(frames(), framesBefore + 1, "not a new list for every message")
        try await phone.send(type: "conversations.list", body: [:], to: bridge.identity.deviceID)
        _ = try await bridge.poll(now: t + 61)
        XCTAssertEqual(frames(), framesBefore + 2, "last_seen moves on at most once a minute")
        XCTAssertEqual((control.last("devices")?["items"] as? [[String: Any]])?.first?["last_seen"] as? String,
                       ISO8601DateFormatter().string(from: t + 61))

        let restartedControl = FakeControl()
        let restarted = try runtime(store, restartedControl, secrets: secrets, memory: memory)
        try await restarted.hello()
        item = try XCTUnwrap((restartedControl.last("devices")?["items"] as? [[String: Any]])?.first)
        XCTAssertEqual(item["state"] as? String, "connected", "a restarted Bridge still knows it heard the phone")
        XCTAssertEqual(item["last_seen"] as? String, ISO8601DateFormatter().string(from: t + 61))
    }

    func testStartUpTidyDeletesWhatWaitsForAPhoneRemovedBeforeThisBuild() async throws {
        let store = MemoryStore(), control = FakeControl(), secrets = MemorySecrets(), memory = InMemoryMemoryStore()
        let bridge = try runtime(store, control, secrets: secrets, memory: memory)
        try await pair(bridge, store, control, phoneID: "iphone-a")
        try await pair(bridge, store, control, phoneID: "iphone-b")
        let gone = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-a")
        let kept = try await bridge.mailbox.send(type: "status.snapshot", body: [:], to: "iphone-b")
        try IdentityStore(secrets: secrets).revoke("iphone-a")          // how an older Bridge removed it: keys only
        var legacy = try XCTUnwrap(memory.memory); legacy.awaitingTo = [:]; memory.memory = legacy
        let restarted = try runtime(store, FakeControl(), secrets: secrets, memory: memory)
        await restarted.tidy()
        XCTAssertNil(store.records[gone.id])
        XCTAssertNotNil(store.records[kept.id])
    }
}
