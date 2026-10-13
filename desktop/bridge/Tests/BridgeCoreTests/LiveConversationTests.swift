import Foundation
import XCTest
@testable import BridgeCore

/// §5.7 (2026-10-13): what a linked conversation now sends besides answers — the answer as it is
/// being written (`partial`), words typed in a Mac window, "working"/"queued" lines — and who
/// started each turn, so only what the phone asked for (or a finished job) rings it.
final class LiveConversationTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)

    func testNoPartialsUnlessAPhoneAskedForThem() {
        let m = FrameMapper(conversationID: "c1")
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": "a"], now: t0).isEmpty)
        XCTAssertTrue(m.flush(now: t0 + 5).isEmpty)
        XCTAssertEqual(m.phoneMessages(for: ["type": "stream_end", "message_id": 1], now: t0 + 6).first?.body["text"] as? String, "a")
    }

    func testTheAnswerBeingWrittenComesAtMostOncePerSecondAndOnlyWhenItChanged() {
        let m = FrameMapper(conversationID: "c1")
        m.partials = true
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
        let first = m.phoneMessages(for: ["type": "stream_chunk", "content": "Three "], now: t0)
        XCTAssertEqual(first.count, 1)
        XCTAssertEqual(first[0].type, "chat.event")
        XCTAssertEqual(first[0].body["kind"] as? String, "partial")
        XCTAssertEqual(first[0].body["text"] as? String, "Three ")
        XCTAssertEqual(first[0].body["final"] as? Bool, false)
        XCTAssertFalse(Wire.shouldNotify(type: "chat.event", body: first[0].body), "a partial never rings")
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": "flights"], now: t0 + 0.4).isEmpty)
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": " found"], now: t0 + 0.8).isEmpty)
        XCTAssertTrue(m.flush(now: t0 + 0.9).isEmpty, "not yet a second")
        let held = m.flush(now: t0 + 1.0)
        XCTAssertEqual(held.map { $0.body["text"] as? String }, ["Three flights found"], "the whole reply so far")
        XCTAssertTrue(m.flush(now: t0 + 2.5).isEmpty, "nothing new, nothing sent")
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": ""], now: t0 + 3).isEmpty, "unchanged")
        let next = m.phoneMessages(for: ["type": "stream_chunk", "content": "."], now: t0 + 3.1)
        XCTAssertEqual(next.first?.body["text"] as? String, "Three flights found.")
        XCTAssertEqual(Set([first[0], held[0], next[0]].map { $0.body["message_id"] as? String }).count, 1,
                       "one bubble for the turn")
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": "!"], now: t0 + 3.5).isEmpty)
        let end = m.phoneMessages(for: ["type": "stream_end", "message_id": 77], now: t0 + 3.6)
        XCTAssertEqual(end.first?.body["message_id"] as? String, "77", "the final keeps the stored id (history merge)")
        XCTAssertEqual(end.first?.body["partial_id"] as? String, first[0].body["message_id"] as? String,
                       "and names the partial it replaces")
        XCTAssertEqual(end.first?.body["text"] as? String, "Three flights found.!")
        XCTAssertTrue(m.flush(now: t0 + 9).isEmpty, "a turn's end drops the partial it held")
    }

    func testEveryTurnEndDropsAHeldPartial() {
        let ends: [[String: Any]] = [["type": "stream_end", "message_id": 5], ["type": "error", "message": "x"],
                                     ["type": "message", "role": "arslan", "message_id": 6, "content": "done"],
                                     ["type": "job_update", "job_id": "j", "phase": "finished", "outcome": "done"]]
        for end in ends {
            let m = FrameMapper(conversationID: "c1")
            m.partials = true
            _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
            _ = m.phoneMessages(for: ["type": "stream_chunk", "content": "a"], now: t0)
            _ = m.phoneMessages(for: ["type": "stream_chunk", "content": "b"], now: t0 + 0.2)
            _ = m.phoneMessages(for: end, now: t0 + 0.3)
            XCTAssertTrue(m.flush(now: t0 + 5).filter { $0.body["kind"] as? String == "partial" }.isEmpty, "\(end["type"]!)")
        }
    }

    func testAVeryLongAnswerStopsSendingPartialsTheFinalStillComes() {
        let m = FrameMapper(conversationID: "c1")
        m.partials = true
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
        let big = String(repeating: "x", count: FrameMapper.partialLimit + 1)
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": big], now: t0).isEmpty)
        XCTAssertEqual(m.phoneMessages(for: ["type": "stream_end", "message_id": 1], now: t0 + 1).first?.body["kind"] as? String, "message")
    }

    func testWordsTypedOnTheMacAreForwardedThePhonesOwnAreNot() {
        let m = FrameMapper(conversationID: "c1")
        XCTAssertTrue(m.phoneMessages(for: ["type": "message", "role": "user", "message_id": 9, "content": "mine",
                                            "source": "phone"]).isEmpty, "the phone already has its own words")
        let typed = m.phoneMessages(for: ["type": "message", "role": "user", "message_id": 10, "content": "and this"])
        XCTAssertEqual(typed.count, 1)
        let body = typed[0].body
        XCTAssertEqual(body["kind"] as? String, "message")
        XCTAssertEqual(body["role"] as? String, "user")
        XCTAssertEqual(body["source"] as? String, "mac")
        XCTAssertEqual(body["message_id"] as? String, "10")
        XCTAssertEqual(body["text"] as? String, "and this")
        XCTAssertEqual(body["final"] as? Bool, true)
        XCTAssertFalse(Wire.shouldNotify(type: "chat.event", body: body), "your own words never ring your phone")
        XCTAssertTrue(m.phoneMessages(for: ["type": "message", "role": "user", "message_id": 10, "content": "and this"]).isEmpty,
                      "once")
    }

    func testTheMacsWordsAreReadFromHistoryWhenATurnStarts() {
        // Today's backend sends no frame for words typed in a window; the Bridge reads the newest
        // rows when a turn starts. Rows the socket's history already had are not news.
        let m = FrameMapper(conversationID: "c1")
        _ = m.phoneMessages(for: ["type": "history", "messages": [["message_id": 14, "role": "user", "content": "old"],
                                                                  ["message_id": 15, "role": "arslan", "content": "ok"]]])
        let rows: [[String: Any]] = [["id": "14", "role": "user", "text": "old", "source": "mac"],
                                     ["id": "15", "role": "assistant", "text": "ok"],
                                     ["id": "16", "role": "user", "text": "from the phone", "source": "phone"],
                                     ["id": "17", "role": "user", "text": "typed at the desk", "source": "mac"]]
        let got = m.macMessages(from: rows)
        XCTAssertEqual(got.map { $0.body["message_id"] as? String }, ["17"])
        XCTAssertEqual(got.first?.body["text"] as? String, "typed at the desk")
        XCTAssertTrue(m.macMessages(from: rows).isEmpty, "once")
        // Without the socket's history (a mapper that never saw one), only what follows the last answer is news.
        let fresh = FrameMapper(conversationID: "c2")
        XCTAssertEqual(fresh.macMessages(from: rows).map { $0.body["message_id"] as? String }, ["17"])
    }

    func testWorkingAndQueuedBecomeProgressLinesUnderTheSameTwoSecondRule() {
        let m = FrameMapper(conversationID: "c1")
        XCTAssertTrue(m.phoneMessages(for: ["type": "working", "elapsed_s": 15], now: t0).isEmpty,
                      "no turn open: a late beat after the end says nothing")
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
        let working = m.phoneMessages(for: ["type": "working", "elapsed_s": 15], now: t0)
        XCTAssertEqual(working.first?.body["kind"] as? String, "progress")
        XCTAssertEqual(working.first?.body["text"] as? String, "Working…")
        XCTAssertTrue(m.phoneMessages(for: ["type": "queued"], now: t0 + 1).isEmpty, "held: two seconds")
        XCTAssertEqual(m.flush(now: t0 + 2).first?.body["text"] as? String, "Queued behind the current turn")
        _ = m.phoneMessages(for: ["type": "tool_call", "tool": "read_file", "args_summary": "a.md"], now: t0 + 3)
        XCTAssertTrue(m.phoneMessages(for: ["type": "tool_call", "tool": "web_search", "args_summary": "q"], now: t0 + 3.5).isEmpty)
        XCTAssertTrue(m.phoneMessages(for: ["type": "working", "elapsed_s": 30], now: t0 + 4).isEmpty)
        XCTAssertEqual(m.flush(now: t0 + 5).first?.body["text"] as? String, "web_search: q",
                       "a beat never replaces a real step held back")
        _ = m.phoneMessages(for: ["type": "stream_end", "message_id": 3], now: t0 + 6)
        XCTAssertTrue(m.phoneMessages(for: ["type": "working", "elapsed_s": 45], now: t0 + 9).isEmpty)
    }

    func testOnlyTheTurnsThePhoneStartedRing() {
        let m = FrameMapper(conversationID: "c1")
        _ = m.phoneMessages(for: ["type": "message", "role": "user", "message_id": 1, "content": "q", "source": "phone"], now: t0)
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0)
        let phoneTurn = m.phoneMessages(for: ["type": "stream_end", "message_id": 2], now: t0 + 1)[0].body
        XCTAssertEqual(phoneTurn["origin"] as? String, "phone")
        XCTAssertTrue(Wire.shouldNotify(type: "chat.event", body: phoneTurn))
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0 + 2)
        _ = m.macMessages(from: [["id": "2", "role": "assistant", "text": "a"], ["id": "3", "role": "user", "text": "typed", "source": "mac"]])
        let macTurn = m.phoneMessages(for: ["type": "stream_end", "message_id": 4], now: t0 + 3)[0].body
        XCTAssertEqual(macTurn["origin"] as? String, "mac", "read from history once the turn started")
        XCTAssertFalse(Wire.shouldNotify(type: "chat.event", body: macTurn), "the user is at the Mac")
        _ = m.phoneMessages(for: ["type": "message", "role": "user", "message_id": 5, "content": "typed too"], now: t0 + 4)
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0 + 4)
        let macError = m.phoneMessages(for: ["type": "error", "message": "boom"], now: t0 + 5)[0].body
        XCTAssertEqual(macError["origin"] as? String, "mac", "or from a frame before it")
        XCTAssertFalse(Wire.shouldNotify(type: "chat.event", body: macError))
        _ = m.phoneMessages(for: ["type": "stream_start"], now: t0 + 6)
        let unknownTurn = m.phoneMessages(for: ["type": "stream_end", "message_id": 6], now: t0 + 7)[0].body
        XCTAssertNil(unknownTurn["origin"], "no evidence (a schedule, or no phone reads the Mac's words): unknown")
        XCTAssertTrue(Wire.shouldNotify(type: "chat.event", body: unknownTurn), "and it rings, as before")
        // A background job's result rings by the job's origin; a job the Mac started still rings when it ends
        // (job.event), as before.
        _ = m.phoneMessages(for: ["type": "job_update", "job_id": "jp", "phase": "running", "origin": "phone"])
        let result = m.phoneMessages(for: ["type": "message", "role": "arslan", "message_id": 8, "content": "done", "job_id": "jp"])[0].body
        XCTAssertEqual(result["origin"] as? String, "phone")
        XCTAssertTrue(Wire.shouldNotify(type: "chat.event", body: result))
        let unknown = m.phoneMessages(for: ["type": "message", "role": "arslan", "message_id": 9, "content": "x", "job_id": "j?"])[0].body
        XCTAssertNil(unknown["origin"])
        XCTAssertTrue(Wire.shouldNotify(type: "chat.event", body: unknown), "unknown origin: rings, as before")
        let finished = m.phoneMessages(for: ["type": "job_update", "job_id": "jm", "phase": "finished", "outcome": "done",
                                             "origin": "mac"])[0]
        XCTAssertTrue(Wire.shouldNotify(type: finished.type, body: finished.body))
        let phoneJob = FrameMapper.jobEvent(["job_id": "jp", "phase": "finished", "outcome": "done", "origin": "phone"], conversationID: "c1")
        XCTAssertTrue(Wire.shouldNotify(type: "job.event", body: phoneJob), "§5.7 item 9: a phone's finished task rings")
    }
}
