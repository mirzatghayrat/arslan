// The Bridge's own lines in the system log (Console, `log show --predicate 'subsystem == "com.arslan.desktop.bridge"'`):
// what failed and where, never message content.
import Foundation
import os

public enum BridgeLog {
    static let logger = Logger(subsystem: "com.arslan.desktop.bridge", category: "bridge")

    public static func error(_ what: String, _ error: Error) {
        logger.error("\(what, privacy: .public) failed: \(String(describing: error), privacy: .public)")
    }

    public static func info(_ message: String) {
        logger.info("\(message, privacy: .public)")
    }
}
