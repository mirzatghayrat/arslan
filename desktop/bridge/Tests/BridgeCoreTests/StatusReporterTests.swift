import Foundation
import XCTest
@testable import BridgeCore

final class StatusReporterTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)

    func status(mascot: String = "working", waiting: Int = 0, step: String = "Sorting", phase: String = "running") -> [String: Any] {
        ["presence": "online", "mascot": mascot, "waiting_approvals": waiting, "high_risk_mac_only": false,
         "jobs": [["job_id": "j1", "conversation_id": "trip", "goal": "Tidy downloads", "phase": phase, "step": step,
                   "outcome": NSNull(), "detail": NSNull(),
                   "criteria": [["id": "c1", "status": "passed"], ["id": "c2", "status": "pending"]]]]]
    }

    func pair() -> (Mailbox, Mailbox, FakeBackend, StatusReporter) {
        let store = MemoryStore()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        let backend = FakeBackend()
        return (mac, phone, backend, StatusReporter(backend: backend, mailbox: mac, deviceName: "Studio Mac"))
    }

    func testTheSnapshotIsTheIslandsStateWithTheMacsNameAndTime() async throws {
        let (_, phone, backend, reporter) = pair()
        backend.answers["/api/v1/phone/status"] = .success(status())
        await reporter.tick(now: t0)
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["status.snapshot"])
        let body = got[0].envelope["body"] as? [String: Any] ?? [:]
        XCTAssertEqual(body["device_name"] as? String, "Studio Mac")
        XCTAssertEqual(body["last_seen"] as? String, ISO8601DateFormatter().string(from: t0))
        XCTAssertEqual(body["mascot"] as? String, "working")
        let job = try XCTUnwrap((body["jobs"] as? [[String: Any]])?.first)
        XCTAssertEqual(job["id"] as? String, "j1")
        XCTAssertEqual(job["state"] as? String, "running")
        XCTAssertEqual(job["title"] as? String, "Tidy downloads")
        XCTAssertEqual(job["current_step"] as? String, "Sorting")
        XCTAssertEqual([job["completed"] as? Int, job["total"] as? Int], [1, 2])
        XCTAssertEqual(job["conversation_id"] as? String, "trip")
        XCTAssertFalse(Wire.shouldNotify(type: "status.snapshot", body: body), "a snapshot never rings")
    }

    func testItIsSentOnChangeAndAsAHeartbeatNotEveryLook() async throws {
        let (_, phone, backend, reporter) = pair()
        func look(_ seconds: TimeInterval, _ s: [String: Any]) async -> Bool {
            backend.answers["/api/v1/phone/status"] = .success(s)
            await reporter.tick(now: t0 + seconds)
            return !((try? await phone.receive()) ?? []).filter { $0.type == "status.snapshot" }.isEmpty
        }
        var sent: [Bool] = []
        sent.append(await look(0, status()))                          // first look: send
        sent.append(await look(2, status()))                          // nothing changed
        sent.append(await look(3, status(mascot: "approval", waiting: 1)))   // changed, but 3 s after: send
        sent.append(await look(4, status(mascot: "working")))         // changed again 1 s later: held
        sent.append(await look(6, status(mascot: "working")))         // still changed, now 3 s after: send
        sent.append(await look(10, status(step: "Moving")))           // only the step: held (< 15 s)
        sent.append(await look(21, status(step: "Moving")))           // 15 s after the last send: send
        sent.append(await look(60, status(step: "Moving")))           // nothing new, 39 s: held
        sent.append(await look(81, status(step: "Moving")))           // 60 s: heartbeat
        sent.append(await look(83, status(phase: "finished")))        // a job's state is the headline
        XCTAssertEqual(sent, [true, false, true, false, true, false, true, false, true, true])
    }

    func testNoPhoneNoReading() async {
        let store = MemoryStore()
        let lonely = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let backend = FakeBackend()
        await StatusReporter(backend: backend, mailbox: lonely, deviceName: "Mac").tick(now: t0)
        XCTAssertEqual(backend.asked, [])
    }

    func testAPhoneSayingHelloGetsTheStatusAtOnce() async throws {
        let (mac, phone, backend, reporter) = pair()
        backend.answers["/api/v1/phone/status"] = .success(status(mascot: "idle"))
        let links = ConversationLinks(channels: FakeChannels(), mailbox: mac, backend: backend)
        links.status = reporter
        try await phone.send(type: "hello", body: ["app_version": "1", "protocol_version": 1, "capabilities": []], to: "mac-1")
        for received in try await mac.receive() { await links.handle(received) }
        let got = try await phone.receive()
        XCTAssertEqual(got.map(\.type), ["hello", "status.snapshot"])
        XCTAssertTrue(((got[0].envelope["body"] as? [String: Any])?["capabilities"] as? [String] ?? []).contains("status"))
    }
}
