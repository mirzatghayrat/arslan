import Foundation
import XCTest
@testable import BridgeCore

final class FrameMapperTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_790_985_600)

    func testAStreamedAnswerReachesThePhoneOnceAndFinal() {
        let m = FrameMapper(conversationID: "c1")
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_start"]).isEmpty)
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": "Three "]).isEmpty)
        XCTAssertTrue(m.phoneMessages(for: ["type": "stream_chunk", "content": "flights"]).isEmpty)
        let out = m.phoneMessages(for: ["type": "stream_end", "message_id": 7])
        XCTAssertEqual(out.count, 1)
        XCTAssertEqual(out[0].type, "chat.event")
        XCTAssertEqual(out[0].body["text"] as? String, "Three flights")
        XCTAssertEqual(out[0].body["final"] as? Bool, true)
        XCTAssertEqual(out[0].body["message_id"] as? String, "7", "the stored message's id, as chat.history has it")
        let withRun = m.phoneMessages(for: ["type": "stream_end", "message_id": 8, "run_id": 87])
        XCTAssertEqual(withRun.first?.body["run_id"] as? Int, 87, "what the reply did, for review")
        XCTAssertTrue(Wire.shouldNotify(type: out[0].type, body: out[0].body))
    }

    func testCardsShowOneOfThePhonesSixRisks() {
        func risk(_ frame: [String: Any]) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: frame.merging(["call_id": "k"]) { a, _ in a }).first?.body["risk"] as? String
        }
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "rm -rf old/", "reason": "recursive delete"]), "delete")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "brew install jq"]), "install")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "git push origin main"]), "publish")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "curl https://example.com"]), "send")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "git status", "remote_host": "box"]), "send")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "python3 tidy.py", "reason": "risk: MEDIUM"]), "write")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "ls", "sandbox": "retry"]), "install")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "format disk", "reason": "removes everything"]), "write",
                       "whole words only: 'removes' is not 'remove'")
        XCTAssertEqual(risk(["type": "propose_workspace_write", "path": "a.md"]), "write")
        XCTAssertEqual(risk(["type": "propose_schedule", "name": "n", "when": "w"]), "write")
        XCTAssertEqual(risk(["type": "propose_action", "kind": "browser_site", "target": "x.com"]), "send")
        XCTAssertEqual(risk(["type": "propose_action", "kind": "mac_script", "target": "Finder"]), "write")
        let six: Set = ["write", "send", "delete", "install", "payment", "publish"]
        for line in ["rm a", "pip install x", "git push", "ssh box", "echo hi", ""] {
            XCTAssertTrue(six.contains(FrameMapper.commandRisk(line, outside: false, remote: false)))
        }
    }

    func testProgressIsCoalescedToOneEveryTwoSecondsNewestWins() {
        let m = FrameMapper(conversationID: "c1")
        XCTAssertEqual(m.phoneMessages(for: ["type": "tool_call", "tool": "web_search", "args_summary": "a"], now: t0).count, 1)
        XCTAssertTrue(m.phoneMessages(for: ["type": "tool_call", "tool": "web_search", "args_summary": "b"], now: t0 + 0.5).isEmpty)
        XCTAssertTrue(m.phoneMessages(for: ["type": "tool_call", "tool": "read_file", "args_summary": "c"], now: t0 + 1).isEmpty)
        XCTAssertTrue(m.flush(now: t0 + 1.5).isEmpty)
        let held = m.flush(now: t0 + 2)
        XCTAssertEqual(held.first?.body["text"] as? String, "read_file: c")
        XCTAssertEqual(held.first?.body["final"] as? Bool, false)
        XCTAssertFalse(Wire.shouldNotify(type: "chat.event", body: held[0].body))
    }

    /// The traces from Codex's audit of iPhone build 7: a step held back, then the turn ends. Nothing
    /// of that turn may go out after its end. Stream_end already dropped it; the rest did not.
    func testATurnsEndDropsTheStepItHeldBack() {
        let ends: [(String, [[String: Any]])] = [
            ("background answer", [["type": "job_update", "job_id": "j", "phase": "finished", "outcome": "done"],
                                   ["type": "message", "role": "arslan", "message_id": 501, "content": "Done", "job_id": "j"]]),
            ("stopped job", [["type": "job_update", "job_id": "j", "phase": "finished", "outcome": "stopped"]]),
            ("answer alone", [["type": "message", "role": "arslan", "message_id": 501, "content": "Done", "job_id": "j"]]),
            ("turn error", [["type": "error", "message": "turn failed"]]),
            ("stream end", [["type": "stream_end", "message_id": 501]]),
        ]
        for (name, frames) in ends {
            let m = FrameMapper(conversationID: "c1")
            XCTAssertEqual(m.phoneMessages(for: ["type": "tool_call", "tool": "read", "args_summary": "first"], now: t0).count, 1)
            XCTAssertTrue(m.phoneMessages(for: ["type": "tool_call", "tool": "read", "args_summary": "held"], now: t0 + 0.5).isEmpty)
            for frame in frames { _ = m.phoneMessages(for: frame, now: t0 + 1) }
            XCTAssertTrue(m.flush(now: t0 + 3).isEmpty, "\(name): the held step belongs to a turn that is over")
        }
    }

    func testARunningJobsUpdateAndThePhonesOwnWordsKeepTheHeldStep() {
        for frame: [String: Any] in [["type": "job_update", "job_id": "j", "phase": "running", "step": "next"],
                                     ["type": "message", "role": "user", "message_id": 9, "content": "and this"]] {
            let m = FrameMapper(conversationID: "c1")
            _ = m.phoneMessages(for: ["type": "tool_call", "tool": "read", "args_summary": "first"], now: t0)
            _ = m.phoneMessages(for: ["type": "tool_call", "tool": "read", "args_summary": "held"], now: t0 + 0.5)
            _ = m.phoneMessages(for: frame, now: t0 + 1)
            XCTAssertEqual(m.flush(now: t0 + 3).first?.body["text"] as? String, "read: held", "still the same turn")
        }
    }

    func testCardsBecomeApprovalsAndAnswersBecomeTheWindowsFrames() throws {
        let m = FrameMapper(conversationID: "c1")
        let req = m.phoneMessages(for: ["type": "propose_run_command", "call_id": "k1", "pretty": "rm -rf old/",
                                        "reason": "delete"], now: t0)
        XCTAssertEqual(req.first?.type, "approval.request")
        XCTAssertEqual(req.first?.body["risk"] as? String, "delete")
        XCTAssertEqual(req.first?.body["expires_at"] as? String, ISO8601DateFormatter().string(from: t0 + 1800),
                       "an old frame: the Mac's 30-minute wait from now (0.1.61)")
        let frames = try m.backendFrames(for: "approval.answer", body: ["approval_id": "k1", "decision": "approve",
                                                                        "auth": "faceid", "ts": "t"])
        XCTAssertEqual(frames.first?["type"] as? String, "confirm_run_command")
        XCTAssertEqual(frames.first?["remember"] as? Bool, false)
        XCTAssertThrowsError(try m.backendFrames(for: "approval.answer", body: ["approval_id": "k1", "decision": "approve",
                                                                                "auth": "faceid", "ts": "t"])) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "approval_expired")      // answered once only
        }
    }

    /// S1b (v0.1.63): the window's schedule card gains `prompt` (the task's text). The phone's card is
    /// built from name / when / title / perm_kind / expires_at only, so it is the same with or without it:
    /// no change for the iPhone, no Bridge format change.
    func testAScheduleCardsPromptDoesNotChangeWhatThePhoneGets() throws {
        let frame: [String: Any] = ["type": "propose_schedule", "call_id": "s1", "name": "Inbox digest", "when": "daily 08:00",
                                    "title": "Schedule “Inbox digest”?", "perm_kind": "schedule", "expires_at": 1_790_987_000,
                                    "options": ["once"]]
        func phone(_ frame: [String: Any]) throws -> [String] {
            try FrameMapper(conversationID: "c1").phoneMessages(for: frame, now: t0).map { message in
                let body = try JSONSerialization.data(withJSONObject: message.body, options: [.sortedKeys])
                return message.type + " " + String(decoding: body, as: UTF8.self)
            }
        }
        let without = try phone(frame)
        let with = try phone(frame.merging(["prompt": "Summarise my inbox"]) { a, _ in a })
        XCTAssertEqual(without.count, 1)
        XCTAssertTrue(without.first?.hasPrefix("approval.request ") == true)
        XCTAssertEqual(with, without, "the phone's approval.request is identical with and without `prompt`")
        XCTAssertFalse(with.joined().contains("Summarise my inbox"), "the task's text never reaches the phone")
    }

    func testV2CardsUseTheirTitleRiskAndExpiry() throws {
        let m = FrameMapper(conversationID: "c1")
        let at = 1_790_987_400.75                        // the Mac sends Unix seconds as a float
        let req = m.phoneMessages(for: ["type": "propose_action", "call_id": "v1", "kind": "app", "target": "com.shop.app",
                                        "detail": "Buy", "title": "Pay $3?", "perm_kind": "money", "expires_at": at,
                                        "options": ["once"]], now: t0)
        XCTAssertEqual(req.first?.body["action"] as? String, "Pay $3?")
        XCTAssertEqual(req.first?.body["risk"] as? String, "payment")
        XCTAssertEqual(req.first?.body["expires_at"] as? String,
                       ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: at)), "the Mac's own expiry, not now + 1800")
        let whole = m.phoneMessages(for: ["type": "propose_schedule", "call_id": "v2", "name": "n", "when": "w",
                                          "title": "Schedule “n”?", "perm_kind": "schedule", "expires_at": 1_790_987_000], now: t0)
        XCTAssertEqual(whole.first?.body["expires_at"] as? String,
                       ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: 1_790_987_000)), "a whole number too")
        XCTAssertEqual(whole.first?.body["action"] as? String, "Schedule “n”?")
        func risk(_ frame: [String: Any]) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: frame.merging(["call_id": "k"]) { a, _ in a }).first?.body["risk"] as? String
        }
        XCTAssertEqual(risk(["type": "propose_action", "kind": "app", "perm_kind": "send"]), "send")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "ls", "perm_kind": "destructive"]), "delete")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "ls", "perm_kind": "outside"]), "install")
        XCTAssertEqual(risk(["type": "propose_action", "kind": "app", "perm_kind": "app_risky"]), "write",
                       "spec §A4: everything else is write")
        XCTAssertEqual(risk(["type": "propose_run_command", "pretty": "rm -rf build", "perm_kind": "command"]), "delete",
                       "a command card keeps its own words")
        XCTAssertEqual(risk(["type": "propose_action", "kind": "browser_site", "perm_kind": "site"]), "send")
        let old = FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "o1",
                                                                      "kind": "mac_script", "target": "Finder"], now: t0)
        XCTAssertEqual(old.first?.body["action"] as? String, "mac_script", "an old frame is mapped as before")
        XCTAssertEqual(old.first?.body["risk"] as? String, "write")
    }

    func testANewCapabilityNeverReachesThePhone() throws {
        let m = FrameMapper(conversationID: "c1")
        XCTAssertTrue(m.phoneMessages(for: ["type": "propose_action", "call_id": "cap", "kind": "capability",
                                            "target": "rea", "perm_kind": "capability"], now: t0).isEmpty)
        XCTAssertNil(m.cards["cap"])
        XCTAssertThrowsError(try m.backendFrames(for: "approval.answer", body: ["approval_id": "cap", "decision": "approve",
                                                                                "auth": "faceid"])) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "approval_expired")
        }
    }

    /// The guard keys on `perm_kind`, not on the Hands/web `kind`, and on every card type (fix round 1, M2).
    func testACapabilityIsKeyedOnPermKindOnAnyCardType() {
        let frames: [(String, [String: Any])] = [
            ("a mac_script action", ["type": "propose_action", "call_id": "cap2", "kind": "mac_script", "perm_kind": "capability"]),
            ("a run-command card", ["type": "propose_run_command", "call_id": "cap3", "pretty": "ls", "perm_kind": "capability"]),
        ]
        for (name, frame) in frames {
            let m = FrameMapper(conversationID: "c1")
            XCTAssertTrue(m.phoneMessages(for: frame, now: t0).isEmpty, "\(name): never on the phone")
            XCTAssertTrue(m.cards.isEmpty, "\(name): and no card is registered")
        }
        // The same frames without the capability kind are cards: the guard is not keyed on the card type.
        XCTAssertEqual(FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "k", "kind": "mac_script",
                                                                          "perm_kind": "app"], now: t0).count, 1)
    }

    func testAQuestionIsCutAt200CharactersNeverInsideOne() {
        func action(_ frame: [String: Any]) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "k", "kind": "app",
                                                                   "target": "T"].merging(frame) { _, new in new }, now: t0).first?.body["action"] as? String
        }
        XCTAssertEqual(action(["title": String(repeating: "x", count: 201)]), String(repeating: "x", count: 200))
        XCTAssertEqual(action(["title": String(repeating: "x", count: 200)])?.count, 200, "exactly 200 is kept")
        let family = "👨‍👩‍👧‍👦"                                    // one character, seven scalars
        XCTAssertEqual(action(["title": String(repeating: family, count: 250)]), String(repeating: family, count: 200))
        let accented = "e\u{301}"                              // a base and its combining mark
        XCTAssertEqual(action(["title": String(repeating: accented, count: 250)]), String(repeating: accented, count: 200))
        XCTAssertEqual(action(["title": "   \n\t "]), "app", "a blank question is no question: the kind's words")
        XCTAssertEqual(action(["title": "  Use Notes?  "]), "Use Notes?")
        for odd: Any in ["1790987000", NSNull()] {                           // not a number: the Mac's wait from now
            let at = FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "k", "kind": "app",
                                                                          "expires_at": odd], now: t0).first?.body["expires_at"] as? String
            XCTAssertEqual(at, ISO8601DateFormatter().string(from: t0 + 1800))
        }
    }

    /// Fix round 1, M4: the phone's card heading is one line, whatever the Mac's title held.
    func testAQuestionReachesThePhoneAsOneLine() {
        func action(_ frame: [String: Any]) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: ["call_id": "k"].merging(frame) { _, new in new }, now: t0)
                .first?.body["action"] as? String
        }
        let base: [String: Any] = ["type": "propose_action", "kind": "app", "target": "T"]
        XCTAssertEqual(action(base.merging(["title": "Run `a\nb`?"]) { _, new in new }), "Run `a b`?")
        XCTAssertEqual(action(base.merging(["title": "  Use \t Notes \r\n\n now?  "]) { _, new in new }), "Use Notes now?")
        // Collapsed before the cut: 100 words of "x" and three spaces are 400 characters raw, 199 once collapsed.
        let words = String(repeating: "x   ", count: 100)
        XCTAssertEqual(action(base.merging(["title": words]) { _, new in new }), Array(repeating: "x", count: 100).joined(separator: " "),
                       "the whole 199-character line, not the first 200 raw characters")
        // The kind's own words are one line too (a schedule's name is the user's text).
        XCTAssertEqual(action(["type": "propose_schedule", "name": "a\n\nb", "when": "w"]), "Schedule “a b”")
    }

    /// Fix round 1, M3: only a plausible Unix time is the Mac's own expiry; anything else is the Mac's wait from now.
    func testAnExpiryThatCannotBeTheMacsOwnIsTheMacsWaitFromNow() throws {
        func expires(_ value: Any?) -> String? {
            var frame: [String: Any] = ["type": "propose_action", "call_id": "k", "kind": "app", "target": "T"]
            frame["expires_at"] = value
            return FrameMapper(conversationID: "c").phoneMessages(for: frame, now: t0).first?.body["expires_at"] as? String
        }
        let iso = ISO8601DateFormatter()
        let now = t0.timeIntervalSince1970
        let fallback = iso.string(from: t0 + 1800)
        XCTAssertEqual(expires(now + 1234), iso.string(from: t0 + 1234), "a valid expiry is the Mac's own")
        XCTAssertEqual(expires(now + 7200), iso.string(from: t0 + 7200), "two hours ahead is the most")
        XCTAssertEqual(expires(now - 60), iso.string(from: t0 - 60), "a minute behind is the least")
        for (name, value) in [("true", true), ("false", false)] as [(String, Any)] {
            XCTAssertEqual(expires(value), fallback, "a JSON \(name) is no time")
        }
        let parsed = try JSONSerialization.jsonObject(with: Data(#"{"expires_at": true}"#.utf8)) as? [String: Any]
        XCTAssertEqual(expires(parsed?["expires_at"]), fallback, "a parsed JSON true is no time (it would read as 1970)")
        XCTAssertEqual(expires(0), fallback)
        XCTAssertEqual(expires(-5), fallback)
        XCTAssertEqual(expires(now + 10 * 86_400), fallback, "ten days ahead is not a card's wait")
        XCTAssertEqual(expires(now + 7201), fallback, "just past two hours")
        XCTAssertEqual(expires(now - 61), fallback, "just past a minute behind")
        XCTAssertEqual(expires(now - 3600), fallback, "long over")
        XCTAssertEqual(expires(Double.nan), fallback)
        XCTAssertEqual(expires(Double.infinity), fallback)
        // Near the epoch the bounds alone would let a bool through (`true` reads as one second), so it is
        // refused as a bool: a clock at 1970 is the one place only the bool check can tell.
        let epoch = Date(timeIntervalSince1970: 0)
        func atEpoch(_ value: Any?) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "k", "kind": "app",
                                                                  "expires_at": value as Any], now: epoch).first?.body["expires_at"] as? String
        }
        XCTAssertEqual(atEpoch(true), iso.string(from: epoch + 1800), "true is not one second past 1970")
        XCTAssertEqual(atEpoch(parsed?["expires_at"]), iso.string(from: epoch + 1800), "nor is a parsed JSON true")
        XCTAssertEqual(atEpoch(1), iso.string(from: epoch + 1), "while a real 1 is a number")
    }

    /// ③Hands asks through `decide()` since #179: its cards are `propose_action` frames of the Hands
    /// action kinds (`desktop_app`, `desktop_risky`…) carrying the permission layer's `perm_kind`.
    /// Only a payment has a risk word of its own on the phone.
    private func handsCard(_ frame: [String: Any]) -> [String: Any]? {
        FrameMapper(conversationID: "c").phoneMessages(for: frame.merging(["type": "propose_action", "call_id": "h"]) { a, _ in a },
                                                       now: t0).first?.body
    }

    func testAHandsPaymentCardIsAPaymentOnThePhone() {
        let pay = handsCard(["kind": "desktop_risky", "target": "com.shop.app", "detail": "Click Buy",
                             "title": "Pay $3 in Shop?", "perm_kind": "money", "options": ["once"]])
        XCTAssertEqual(pay?["risk"] as? String, "payment", "a payment step is a payment on the phone too")
        XCTAssertEqual(pay?["action"] as? String, "Pay $3 in Shop?")
        XCTAssertEqual(handsCard(["kind": "desktop_risky", "target": "com.mail.app", "title": "Send it?",
                                  "perm_kind": "app_risky", "options": ["once"]])?["risk"] as? String, "write",
                       "the other once-only Hands step is today's write")
    }

    func testAHandsAppCardKeepsTodaysRuleAndTheSameAnswer() throws {
        XCTAssertNil(FrameMapper.permRisk("app"), "an app grant has no risk word of its own")
        let app = handsCard(["kind": "desktop_app", "target": "Notes", "detail": "Use Notes", "title": "Use Notes?",
                             "perm_kind": "app", "options": ["task", "conversation", "always"]])
        XCTAssertEqual(app?["risk"] as? String, "write", "today's rule: the kind is not browser_site")
        XCTAssertEqual(app?["action"] as? String, "Use Notes? (for this task)", "the phone's yes on an app card is for this task, and says so")
        // The phone's yes is the frame it always was and asks for no scope (the Mac takes the first choice).
        let m = FrameMapper(conversationID: "c")
        _ = m.phoneMessages(for: ["type": "propose_action", "call_id": "h2", "kind": "desktop_app", "target": "Notes",
                                  "perm_kind": "app"], now: t0)
        let answer = try m.backendFrames(for: "approval.answer", body: ["approval_id": "h2", "decision": "approve", "auth": "faceid"])
        XCTAssertEqual(answer.first?["type"] as? String, "confirm_action")
        XCTAssertEqual(answer.first?["source"] as? String, "phone")
        XCTAssertNil(answer.first?["scope"])
    }

    func testAYesNeedsFaceIDOrTouchIDAndNothingElse() throws {
        func answer(_ auth: String, _ decision: String = "approve") throws -> String? {
            let m = FrameMapper(conversationID: "c1")
            _ = m.phoneMessages(for: ["type": "propose_workspace_write", "call_id": "w", "path": "a.txt", "reason": "r"], now: t0)
            return try m.backendFrames(for: "approval.answer", body: ["approval_id": "w", "decision": decision, "auth": auth, "ts": "t"]).first?["type"] as? String
        }
        XCTAssertEqual(try answer("faceid"), "confirm_workspace_write")
        XCTAssertEqual(try answer("touchid"), "confirm_workspace_write", "iPhone SE approves with Touch ID")
        XCTAssertEqual(try answer("none"), "cancel_workspace_write", "no proof, no yes")
        XCTAssertEqual(try answer("passcode"), "cancel_workspace_write", "only biometric proof counts")
        XCTAssertEqual(try answer("touchid", "deny"), "cancel_workspace_write")
    }

    func testHowTheMacDecidedACardReachesThePhoneOnce() throws {
        let m = FrameMapper(conversationID: "c1")
        for id in ["p", "m", "x", "d"] { _ = m.phoneMessages(for: ["type": "propose_schedule", "call_id": id, "name": "n", "when": "w"]) }
        let answer = try m.backendFrames(for: "approval.answer", body: ["approval_id": "p", "decision": "approve", "auth": "faceid"])
        XCTAssertEqual(answer.first?["source"] as? String, "phone")
        XCTAssertEqual(m.cards["p"], .schedule, "still open until the Mac says how it ended")

        func result(_ frame: [String: Any]) -> [String: String]? {
            let out = m.phoneMessages(for: frame)
            guard out.count == 1, out[0].type == "approval.result" else { return out.isEmpty ? nil : [:] }
            return out[0].body.mapValues { "\($0)" }
        }
        XCTAssertEqual(result(["type": "card_resolved", "call_id": "p", "outcome": "approved", "by": "phone"]),
                       ["approval_id": "p", "outcome": "done"])
        XCTAssertEqual(result(["type": "card_resolved", "call_id": "m", "outcome": "approved", "by": "mac"]),
                       ["approval_id": "m", "outcome": "done", "detail": "answered_on_mac"])
        XCTAssertEqual(result(["type": "card_resolved", "call_id": "d", "outcome": "declined", "by": "mac"]),
                       ["approval_id": "d", "outcome": "denied", "detail": "answered_on_mac"])
        XCTAssertEqual(result(["type": "card_resolved", "call_id": "x", "outcome": "expired"]),
                       ["approval_id": "x", "outcome": "expired"])
        XCTAssertTrue(Wire.shouldNotify(type: "approval.result", body: ["approval_id": "x", "outcome": "expired"]))
        XCTAssertNil(result(["type": "card_resolved", "call_id": "p", "outcome": "approved"]), "once")
        XCTAssertNil(result(["type": "card_resolved", "call_id": "never-shown", "outcome": "approved"]))
        XCTAssertTrue(m.cards.isEmpty)
        XCTAssertThrowsError(try m.backendFrames(for: "approval.answer", body: ["approval_id": "m", "decision": "deny", "auth": "none"])) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "approval_expired")      // the Mac already answered it
        }
    }

    /// Final review (PR 2b), M1: a card the Mac's Inbox or island answered is "answered on the Mac" too — the phone is told
    /// the Mac decided it, not that it did. Only the phone's own answer carries no detail; an expiry has no `by` at all.
    func testAnInboxOrIslandAnswerIsAnsweredOnTheMacLikeAWindowsAnswer() {
        let m = FrameMapper(conversationID: "c1")
        for id in ["w", "i", "s", "p", "n"] { _ = m.phoneMessages(for: ["type": "propose_schedule", "call_id": id, "name": "n", "when": "w"]) }
        func detail(_ id: String, _ outcome: String, _ by: String?) -> String? {
            var frame: [String: Any] = ["type": "card_resolved", "call_id": id, "outcome": outcome]
            if let by = by { frame["by"] = by }
            return m.phoneMessages(for: frame).first?.body["detail"] as? String
        }
        XCTAssertEqual(detail("w", "approved", "mac"), "answered_on_mac")
        XCTAssertEqual(detail("i", "approved", "inbox"), "answered_on_mac", "the Inbox is the Mac")
        XCTAssertEqual(detail("s", "declined", "island"), "answered_on_mac", "so is the island")
        XCTAssertNil(detail("p", "approved", "phone"), "the phone's own answer needs no explaining")
        XCTAssertNil(detail("n", "expired", nil), "an expiry has no one who answered")
    }

    /// Final review (PR 2b), M1: a card for several apps (`permissions.decide_many`) joins their bundle ids with U+001E; the
    /// phone's card is one line, comma-separated, and never shows a control character.
    func testAManyAppCardsTargetReachesThePhoneAsOneLine() {
        let target = handsCard(["kind": "app", "target": "com.apple.Notes\u{1e}com.apple.mail", "detail": "· Notes — look and act\n· Mail — look and act",
                                "title": "Use Notes, Mail for this: tidy?", "perm_kind": "app", "options": ["task", "conversation", "always"]])?["target"] as? String
        XCTAssertEqual(target, "com.apple.Notes, com.apple.mail")
        XCTAssertFalse((target ?? "").unicodeScalars.contains { $0.value == 0x1e }, "no control character reaches the card")
        XCTAssertEqual(handsCard(["kind": "desktop_app", "target": "com.apple.Notes"])?["target"] as? String, "com.apple.Notes", "one app is unchanged")
    }

    /// Final review (PR 2b), M2: the phone's Approve on an app, a site or a Shortcut card is "for this task" (the Mac takes the first,
    /// narrowest choice), and the card says so — ending the heading, within the same 200-character cut. Any other kind says nothing.
    func testATaskFirstCardSaysThePhonesYesIsForThisTask() {
        func action(_ frame: [String: Any]) -> String? {
            FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_action", "call_id": "k", "kind": "desktop_app", "target": "T"]
                .merging(frame) { _, new in new }, now: t0).first?.body["action"] as? String
        }
        for kind in ["app", "site", "shortcut"] {
            XCTAssertEqual(action(["title": "Use Notes?", "perm_kind": kind]), "Use Notes? (for this task)", kind)
        }
        for kind in ["money", "app_risky", "command", "outside", "schedule", "folder", "workspace_write", "takeover", "send", "destructive", "made_up"] {
            XCTAssertEqual(action(["title": "Use Notes?", "perm_kind": kind]), "Use Notes?", "\(kind): the phone's yes is not described as for the task")
        }
        XCTAssertEqual(action(["title": "Use Notes?"]), "Use Notes?", "an old frame has no permission kind")
        XCTAssertEqual(action(["perm_kind": "app"]), "desktop_app (for this task)", "no title: the kind's own words, then the scope")
        XCTAssertEqual(action(["title": "  Use \n Notes?  ", "perm_kind": "site"]), "Use Notes? (for this task)", "one line first")
        XCTAssertEqual(action(["kind": "", "perm_kind": "app"]), "(for this task)", "nothing to say but the scope: no leading space")
        // A card of another type that carries the kind says it too (an app card may ride a command frame).
        XCTAssertEqual(FrameMapper(conversationID: "c").phoneMessages(for: ["type": "propose_run_command", "call_id": "r", "pretty": "ls",
            "title": "Run `ls`?", "perm_kind": "app"], now: t0).first?.body["action"] as? String, "Run `ls`? (for this task)")
        // Within the cut: the question gives way, the words stay whole, and the heading is never longer than 200 characters.
        let suffix = " (for this task)"
        let long = action(["title": String(repeating: "x", count: 250), "perm_kind": "app"])
        XCTAssertEqual(long?.count, 200)
        XCTAssertEqual(long, String(repeating: "x", count: 200 - suffix.count) + suffix)
        let exact = action(["title": String(repeating: "y", count: 200 - suffix.count), "perm_kind": "shortcut"])
        XCTAssertEqual(exact, String(repeating: "y", count: 200 - suffix.count) + suffix, "a question that just fits is kept whole")
        let family = "👨‍👩‍👧‍👦"                                            // one character, seven scalars
        let emoji = action(["title": String(repeating: family, count: 250), "perm_kind": "site"])
        XCTAssertEqual(emoji, String(repeating: family, count: 200 - suffix.count) + suffix, "never cut inside a character")
        XCTAssertEqual(action(["title": String(repeating: "a ", count: 120), "perm_kind": "app"])?.hasSuffix("a (for this task)"), true,
                       "a cut that ends on a space does not leave two")
    }

    func testOutsideTheSandboxSaysSoAndOnlyFaceIDApproves() throws {
        let m = FrameMapper(conversationID: "c1")
        let req = m.phoneMessages(for: ["type": "propose_run_command", "call_id": "k2", "pretty": "brew install jq",
                                        "sandbox": "outside"])
        XCTAssertEqual(req.first?.body["risk"] as? String, "install")
        XCTAssertEqual(req.first?.body["action"] as? String, "Run a command outside the sandbox")
        let frames = try m.backendFrames(for: "approval.answer", body: ["approval_id": "k2", "decision": "approve",
                                                                        "auth": "voice", "ts": "t"])
        XCTAssertEqual(frames.first?["type"] as? String, "cancel_run_command", "anything but Face ID is a no")
    }

    func testEachCardKindAnswersWithItsOwnFrame() throws {
        let m = FrameMapper(conversationID: "c1")
        _ = m.phoneMessages(for: ["type": "propose_workspace_write", "call_id": "w", "action": "Write", "path": "a.md"])
        _ = m.phoneMessages(for: ["type": "propose_schedule", "call_id": "s", "name": "Daily", "when": "9:00"])
        _ = m.phoneMessages(for: ["type": "propose_action", "call_id": "a", "kind": "mac_script", "target": "Finder"])
        XCTAssertEqual(try m.backendFrames(for: "approval.answer", body: ["approval_id": "w", "decision": "deny", "auth": "none"]).first?["type"] as? String, "cancel_workspace_write")
        XCTAssertEqual(try m.backendFrames(for: "approval.answer", body: ["approval_id": "s", "decision": "approve", "auth": "faceid"]).first?["type"] as? String, "confirm_schedule")
        XCTAssertEqual(try m.backendFrames(for: "approval.answer", body: ["approval_id": "a", "decision": "approve", "auth": "faceid"]).first?["type"] as? String, "confirm_action")
    }

    func testJobsMapToTheProtocolStatesAndPhoneWordsAreMarked() throws {
        let m = FrameMapper(conversationID: "c1")
        func state(_ phase: String, _ outcome: String?) -> String? {
            var f: [String: Any] = ["type": "job_update", "job_id": "j", "conversation_id": "c1", "goal": "Tidy",
                                    "phase": phase, "step": "", "detail": "d",
                                    "criteria": [["id": "1", "description": "a", "status": "passed"],
                                                 ["id": "2", "description": "b", "status": "failed"]]]
            if let outcome { f["outcome"] = outcome }
            let body = m.phoneMessages(for: f).first?.body
            XCTAssertEqual(body?["completed"] as? Int, 1)
            XCTAssertEqual(body?["total"] as? Int, 2)
            let checks = body?["criteria"] as? [[String: String]]
            XCTAssertEqual(checks, [["text": "a", "status": "passed"], ["text": "b", "status": "failed"]])
            return body?["state"] as? String
        }
        XCTAssertEqual(state("running", nil), "running")
        XCTAssertEqual(state("finished", "done"), "done")
        XCTAssertEqual(state("finished", "blocked"), "stuck")
        XCTAssertEqual(state("finished", "out_of_budget"), "partial")
        XCTAssertEqual(state("finished", "interrupted"), "stopped")
        let bare = m.phoneMessages(for: ["type": "job_update", "job_id": "j", "conversation_id": "c1", "goal": "Tidy", "phase": "running"]).first?.body
        XCTAssertNil(bare?["criteria"])
        let send = try m.backendFrames(for: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c"])
        XCTAssertEqual(send.first?["source"] as? String, "phone")
        XCTAssertEqual(send.first?["type"] as? String, "user_message")
    }
}
