// The CloudKit side of EnvelopeStore (docs/specs/mobile-bridge-protocol.md §2): private
// database, zone ArslanBridge, record type Envelope. Completion-handler operations, because
// the Bridge supports macOS 11 (CloudKit's async methods start at macOS 12).
import CloudKit
import Foundation

public final class CloudKitStore: EnvelopeStore {
    public static let zoneName = "ArslanBridge"
    public static let recordType = "Envelope"
    let database: CKDatabase
    let zoneID: CKRecordZone.ID

    public init(containerID: String) {
        database = CKContainer(identifier: containerID).privateCloudDatabase
        zoneID = CKRecordZone.ID(zoneName: Self.zoneName, ownerName: CKCurrentUserDefaultName)
    }

    func run(_ operation: CKDatabaseOperation) { operation.qualityOfService = .userInitiated; database.add(operation) }

    /// Create the zone if it does not exist (idempotent).
    public func ensureZone() async throws {
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
            let op = CKModifyRecordZonesOperation(recordZonesToSave: [CKRecordZone(zoneID: zoneID)], recordZoneIDsToDelete: nil)
            op.modifyRecordZonesCompletionBlock = { _, _, error in
                if let error { done.resume(throwing: error) } else { done.resume() }
            }
            run(op)
        }
    }

    public func save(_ record: EnvelopeRecord) async throws {
        let ck = CKRecord(recordType: Self.recordType, recordID: CKRecord.ID(recordName: record.id, zoneID: zoneID))
        ck["to"] = record.to as CKRecordValue
        ck["from"] = record.from as CKRecordValue
        ck["seq"] = NSNumber(value: record.seq)
        ck["kind"] = record.kind as CKRecordValue
        ck["notify"] = NSNumber(value: record.notify ? 1 : 0)
        ck["sealed"] = record.sealed as CKRecordValue
        ck["createdAt"] = record.createdAt as CKRecordValue
        var assetFile: URL?
        if let asset = record.asset {
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("arslan-bridge-\(record.id).bin")
            try asset.write(to: url, options: [.atomic])
            ck["asset"] = CKAsset(fileURL: url)
            assetFile = url
        }
        defer { assetFile.map { try? FileManager.default.removeItem(at: $0) } }
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
            let op = CKModifyRecordsOperation(recordsToSave: [ck], recordIDsToDelete: nil)
            op.savePolicy = .allKeys          // a retry re-saves the same record unchanged (§4.5)
            op.modifyRecordsCompletionBlock = { _, _, error in
                if let error { done.resume(throwing: error) } else { done.resume() }
            }
            run(op)
        }
    }

    public func changes(since token: Data?) async throws -> (records: [EnvelopeRecord], token: Data?) {
        var records: [EnvelopeRecord] = []
        var current = token
        var more = true
        while more {
            let previous = try current.flatMap {
                try NSKeyedUnarchiver.unarchivedObject(ofClass: CKServerChangeToken.self, from: $0)
            }
            let page: (records: [EnvelopeRecord], token: CKServerChangeToken?, more: Bool) =
                try await withCheckedThrowingContinuation { done in
                    let config = CKFetchRecordZoneChangesOperation.ZoneConfiguration()
                    config.previousServerChangeToken = previous
                    let op = CKFetchRecordZoneChangesOperation(recordZoneIDs: [zoneID], configurationsByRecordZoneID: [zoneID: config])
                    var got: [EnvelopeRecord] = []
                    var newToken: CKServerChangeToken?
                    var moreComing = false
                    op.recordChangedBlock = { record in
                        if let envelope = Self.envelope(from: record) { got.append(envelope) }
                    }
                    op.recordZoneFetchCompletionBlock = { _, token, _, isMore, error in
                        if error == nil { newToken = token; moreComing = isMore }
                    }
                    op.fetchRecordZoneChangesCompletionBlock = { error in
                        if let error { done.resume(throwing: error) } else { done.resume(returning: (got, newToken, moreComing)) }
                    }
                    run(op)
                }
            records += page.records
            more = page.more
            if let next = page.token {
                current = try NSKeyedArchiver.archivedData(withRootObject: next, requiringSecureCoding: true)
            }
        }
        return (records, current)
    }

    public func delete(ids: [String]) async throws {
        guard !ids.isEmpty else { return }
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
            let op = CKModifyRecordsOperation(recordsToSave: nil,
                                              recordIDsToDelete: ids.map { CKRecord.ID(recordName: $0, zoneID: zoneID) })
            op.modifyRecordsCompletionBlock = { _, _, error in
                if let error { done.resume(throwing: error) } else { done.resume() }
            }
            run(op)
        }
    }

    /// Whether a record with this id exists in the zone (a direct fetch, not the change feed).
    public func exists(id: String) async throws -> Bool {
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Bool, Error>) in
            let op = CKFetchRecordsOperation(recordIDs: [CKRecord.ID(recordName: id, zoneID: zoneID)])
            op.fetchRecordsCompletionBlock = { records, error in
                if let ck = error as? CKError, ck.code == .partialFailure,
                   let inner = ck.partialErrorsByItemID?.values.first as? CKError, inner.code == .unknownItem {
                    done.resume(returning: false)
                } else if let ck = error as? CKError, ck.code == .unknownItem {
                    done.resume(returning: false)
                } else if let error {
                    done.resume(throwing: error)
                } else {
                    done.resume(returning: !(records ?? [:]).isEmpty)
                }
            }
            run(op)
        }
    }

    static func envelope(from record: CKRecord) -> EnvelopeRecord? {
        guard record.recordType == recordType, let to = record["to"] as? String, let from = record["from"] as? String,
              let seq = (record["seq"] as? NSNumber)?.int64Value, let kind = record["kind"] as? String,
              let sealed = record["sealed"] as? Data else { return nil }
        let asset = (record["asset"] as? CKAsset)?.fileURL.flatMap { try? Data(contentsOf: $0) }
        return EnvelopeRecord(id: record.recordID.recordName, to: to, from: from, seq: seq, kind: kind,
                              notify: ((record["notify"] as? NSNumber)?.intValue ?? 0) == 1, sealed: sealed, asset: asset,
                              createdAt: (record["createdAt"] as? Date) ?? record.creationDate ?? Date())
    }
}
