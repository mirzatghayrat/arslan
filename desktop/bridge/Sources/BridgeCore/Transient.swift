// CloudKit's "try again in a moment" (another write to the zone at the same instant, a busy
// server, a rate limit, a dropped connection): the Bridge waits as told and tries again a few
// times, instead of losing the reply it was sending. Measured 2026-10-04 on a real iPhone: a
// "Zone Busy" lost one run.result; the phone's quick review then spun until it gave up.
import CloudKit
import Foundation

public enum Transient {
    public static let attempts = 4
    static let passing: Set<CKError.Code> = [.zoneBusy, .serviceUnavailable, .requestRateLimited, .networkFailure]

    /// How long to wait before trying again after `attempt` tries, or nil: not a passing error, or
    /// tried enough. A partial failure counts when every item failed for a passing reason.
    public static func delay(after error: Error, attempt: Int) -> TimeInterval? {
        guard attempt < attempts, let ck = error as? CKError else { return nil }
        var waits: [TimeInterval?] = []
        if ck.code == .partialFailure, let items = ck.partialErrorsByItemID?.values, !items.isEmpty {
            for item in items {
                guard let inner = item as? CKError, passing.contains(inner.code) || inner.code == .batchRequestFailed else { return nil }
                waits.append(inner.retryAfterSeconds)
            }
        } else {
            guard passing.contains(ck.code) else { return nil }
            waits.append(ck.retryAfterSeconds)
        }
        let told = waits.compactMap { $0 }.max() ?? Double(attempt)
        return min(10, max(0.5, told))
    }

    public static func retrying<T>(_ body: () async throws -> T) async throws -> T {
        var attempt = 1
        while true {
            do { return try await body() }
            catch {
                guard let wait = delay(after: error, attempt: attempt) else { throw error }
                attempt += 1
                try await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
            }
        }
    }
}
