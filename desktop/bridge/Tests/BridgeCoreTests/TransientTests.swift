import CloudKit
import XCTest
@testable import BridgeCore

final class TransientTests: XCTestCase {
    func testPassingErrorsWaitAsToldAndThenGiveUp() {
        let busy = CKError(.zoneBusy, userInfo: [CKErrorRetryAfterKey: 2.0])
        XCTAssertEqual(Transient.delay(after: busy, attempt: 1), 2)
        XCTAssertEqual(Transient.delay(after: CKError(.serviceUnavailable), attempt: 2), 2, "no hint: a second per try")
        XCTAssertEqual(Transient.delay(after: CKError(.zoneBusy, userInfo: [CKErrorRetryAfterKey: 60.0]), attempt: 1), 10, "never more than 10 s")
        XCTAssertNil(Transient.delay(after: busy, attempt: Transient.attempts), "tried enough")
        XCTAssertNil(Transient.delay(after: CKError(.permissionFailure), attempt: 1), "not a passing error")
        XCTAssertNil(Transient.delay(after: URLError(.badURL), attempt: 1))
    }

    func testAPartialFailureCountsOnlyWhenEveryItemCanBeTriedAgain() {
        let a = CKRecord.ID(recordName: "a"), b = CKRecord.ID(recordName: "b")
        let all = CKError(.partialFailure, userInfo: [CKPartialErrorsByItemIDKey: [a: CKError(.zoneBusy, userInfo: [CKErrorRetryAfterKey: 3.0]),
                                                                                b: CKError(.batchRequestFailed)]])
        XCTAssertEqual(Transient.delay(after: all, attempt: 1), 3)
        let mixed = CKError(.partialFailure, userInfo: [CKPartialErrorsByItemIDKey: [a: CKError(.zoneBusy), b: CKError(.permissionFailure)]])
        XCTAssertNil(Transient.delay(after: mixed, attempt: 1))
    }

    func testRetryingTriesAgainUntilItWorks() async throws {
        var calls = 0
        let value = try await Transient.retrying { () async throws -> Int in
            calls += 1
            if calls < 3 { throw CKError(.zoneBusy, userInfo: [CKErrorRetryAfterKey: 0.0]) }
            return 7
        }
        XCTAssertEqual(value, 7); XCTAssertEqual(calls, 3)
    }

    func testRetryingPassesOtherErrorsStraightOn() async {
        var calls = 0
        do {
            _ = try await Transient.retrying { () async throws -> Int in calls += 1; throw CKError(.permissionFailure) }
            XCTFail("thrown")
        } catch { XCTAssertEqual((error as? CKError)?.code, .permissionFailure) }
        XCTAssertEqual(calls, 1)
    }
}

final class PollPaceTests: XCTestCase {
    func testFastWhileThePhoneIsAroundSlowOtherwise() {
        let now = Date()
        XCTAssertEqual(PollPace.interval(lastHeard: nil, now: now), 10)
        XCTAssertEqual(PollPace.interval(lastHeard: now.addingTimeInterval(-5), now: now), 2)
        XCTAssertEqual(PollPace.interval(lastHeard: now.addingTimeInterval(-119), now: now), 2, "a heartbeat's ack is at most ~80 s apart")
        XCTAssertEqual(PollPace.interval(lastHeard: now.addingTimeInterval(-121), now: now), 10)
    }

    func testAnythingThePhoneWritesCountsAcksIncluded() async throws {
        let store = MemoryStore()
        let mac = Mailbox(deviceID: "mac-1", signing: .init(), exchange: .init(), store: store)
        let phone = Mailbox(deviceID: "iphone-1", signing: .init(), exchange: .init(), store: store)
        mac.add(peer: Peer(deviceID: "iphone-1", signing: phone.signing.publicKey, exchange: phone.exchange.publicKey))
        phone.add(peer: Peer(deviceID: "mac-1", signing: mac.signing.publicKey, exchange: mac.exchange.publicKey))
        XCTAssertNil(mac.lastHeard)
        try await mac.send(type: "status.snapshot", body: [:], to: "iphone-1")
        _ = try await phone.receive()                       // the phone acks it
        let got = try await mac.receive()
        XCTAssertTrue(got.isEmpty, "an ack is not acted on…")
        XCTAssertNotNil(mac.lastHeard, "…but it says the phone is there")
    }
}
