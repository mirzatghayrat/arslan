import Foundation
import XCTest
@testable import BridgeCore

final class WebSocketControlTests: XCTestCase {
    func testASocketIsThereTheMomentItIsOpened() {
        let socket = WebSocketControl(port: 9, token: "t", path: "/ws/arslan/pocket")
        XCTAssertNil(socket.currentTask)
        socket.start()
        XCTAssertNotNil(socket.currentTask, "a frame sent right after opening must not find no socket")
        XCTAssertEqual(socket.currentTask?.originalRequest?.url?.path, "/ws/arslan/pocket")
        XCTAssertEqual(socket.currentTask?.originalRequest?.value(forHTTPHeaderField: "Origin"), "http://127.0.0.1:9")
    }

    func testTheChannelsStartTheirSocketsOnOpen() {
        let channels = WebSocketChannels(port: 9, token: "t")
        let socket = channels.open(conversationID: "c 1") { _ in } as? WebSocketControl
        XCTAssertNotNil(socket?.currentTask)
        XCTAssertTrue(channels.open(conversationID: "c 1") { _ in } === socket, "one socket per conversation")
    }

    /// `send` runs on the poll loop and the conversation links while `stop` and `run` touch the socket from
    /// other tasks: under TSan an unlocked `task` or `stopped` fails this.
    func testSendingAndStoppingFromOtherTasksDoNotRace() async {
        let socket = WebSocketControl(port: 9, token: "t", path: "/ws/arslan/race")    // nothing listens on 9
        socket.start()
        await withTaskGroup(of: Void.self) { group in
            for _ in 0..<8 { group.addTask { try? await socket.send(["type": "ping"]) } }
            group.addTask { socket.stop() }
        }
        do {
            try await socket.send(["type": "ping"])
            XCTFail("a stopped socket took a frame")
        } catch {
            XCTAssertEqual(error as? BridgeError, .code("mac_busy"))
        }
    }
}
