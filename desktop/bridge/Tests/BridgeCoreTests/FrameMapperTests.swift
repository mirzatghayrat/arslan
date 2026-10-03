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
        XCTAssertTrue(Wire.shouldNotify(type: out[0].type, body: out[0].body))
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

    func testCardsBecomeApprovalsAndAnswersBecomeTheWindowsFrames() throws {
        let m = FrameMapper(conversationID: "c1")
        let req = m.phoneMessages(for: ["type": "propose_run_command", "call_id": "k1", "pretty": "rm -rf old/",
                                        "reason": "delete"], now: t0)
        XCTAssertEqual(req.first?.type, "approval.request")
        XCTAssertEqual(req.first?.body["risk"] as? String, "delete")
        XCTAssertEqual(req.first?.body["expires_at"] as? String, ISO8601DateFormatter().string(from: t0 + 300))
        let frames = try m.backendFrames(for: "approval.answer", body: ["approval_id": "k1", "decision": "approve",
                                                                        "auth": "faceid", "ts": "t"])
        XCTAssertEqual(frames.first?["type"] as? String, "confirm_run_command")
        XCTAssertEqual(frames.first?["remember"] as? Bool, false)
        XCTAssertThrowsError(try m.backendFrames(for: "approval.answer", body: ["approval_id": "k1", "decision": "approve",
                                                                                "auth": "faceid", "ts": "t"])) {
            XCTAssertEqual(($0 as? BridgeError)?.code, "approval_expired")      // answered once only
        }
    }

    func testOutsideTheSandboxSaysSoAndOnlyFaceIDApproves() throws {
        let m = FrameMapper(conversationID: "c1")
        let req = m.phoneMessages(for: ["type": "propose_run_command", "call_id": "k2", "pretty": "brew install jq",
                                        "sandbox": "outside"])
        XCTAssertEqual(req.first?.body["risk"] as? String, "outside_sandbox")
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
            return body?["state"] as? String
        }
        XCTAssertEqual(state("running", nil), "running")
        XCTAssertEqual(state("finished", "done"), "done")
        XCTAssertEqual(state("finished", "blocked"), "stuck")
        XCTAssertEqual(state("finished", "out_of_budget"), "partial")
        XCTAssertEqual(state("finished", "interrupted"), "stopped")
        let send = try m.backendFrames(for: "chat.send", body: ["text": "hi", "attachments": [], "client_msg_id": "c"])
        XCTAssertEqual(send.first?["source"] as? String, "phone")
        XCTAssertEqual(send.first?["type"] as? String, "user_message")
    }
}
