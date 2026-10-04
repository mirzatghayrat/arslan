import Foundation
import XCTest
@testable import BridgeCore

final class WebSocketControlTests: XCTestCase {
    func testASocketIsThereTheMomentItIsOpened() {
        let socket = WebSocketControl(port: 9, token: "t", path: "/ws/arslan/pocket")
        XCTAssertNil(socket.task)
        socket.start()
        XCTAssertNotNil(socket.task, "a frame sent right after opening must not find no socket")
        XCTAssertEqual(socket.task?.originalRequest?.url?.path, "/ws/arslan/pocket")
        XCTAssertEqual(socket.task?.originalRequest?.value(forHTTPHeaderField: "Origin"), "http://127.0.0.1:9")
    }

    func testTheChannelsStartTheirSocketsOnOpen() {
        let channels = WebSocketChannels(port: 9, token: "t")
        let socket = channels.open(conversationID: "c 1") { _ in } as? WebSocketControl
        XCTAssertNotNil(socket?.task)
        XCTAssertTrue(channels.open(conversationID: "c 1") { _ in } === socket, "one socket per conversation")
    }
}
