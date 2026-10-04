// The Bridge's own lines in the system log (Console, `log show --predicate 'subsystem == "com.arslan.desktop.bridge"'`):
// what failed and where, never message content.
import Foundation
import os

public enum BridgeLog {
    static let logger = Logger(subsystem: "com.arslan.desktop.bridge", category: "bridge")

    public static func error(_ what: String, _ error: Error) {
        logger.error("\(what, privacy: .public) failed: \(String(describing: error), privacy: .public)")
    }

    /// Kept in the system log (info is not): what the phone asked and what was refused, by type
    /// and code only — the line that tells "never arrived" from "arrived and refused".
    public static func notice(_ message: String) {
        logger.notice("\(message, privacy: .public)")
    }

    public static func info(_ message: String) {
        logger.info("\(message, privacy: .public)")
    }
}
