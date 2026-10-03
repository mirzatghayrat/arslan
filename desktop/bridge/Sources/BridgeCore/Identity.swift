// The Bridge's identity and paired phones, persisted (docs/specs/mobile-bridge-protocol.md §4.1, §6).
// Private keys live only in the Bridge's own Keychain items (this device only, never synced);
// the backend never holds them. Tests use MemorySecrets.
import CryptoKit
import Foundation
import Security

public protocol SecretStore {
    func read(_ account: String) throws -> Data?
    func write(_ account: String, _ data: Data) throws
    func delete(_ account: String) throws
}

public final class MemorySecrets: SecretStore {
    var items: [String: Data] = [:]
    public init() {}
    public func read(_ account: String) throws -> Data? { items[account] }
    public func write(_ account: String, _ data: Data) throws { items[account] = data }
    public func delete(_ account: String) throws { items[account] = nil }
}

/// Generic-password items under the Bridge's service, readable after first unlock, this device only.
public final class KeychainSecrets: SecretStore {
    let service: String
    public init(service: String = "dev.aralem.arslan.bridge") { self.service = service }

    func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    public func read(_ account: String) throws -> Data? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw BridgeError.code("keychain_\(status)") }
        return out as? Data
    }

    public func write(_ account: String, _ data: Data) throws {
        let update = SecItemUpdate(query(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if update == errSecSuccess { return }
        guard update == errSecItemNotFound else { throw BridgeError.code("keychain_\(update)") }
        var q = query(account)
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(q as CFDictionary, nil)
        guard status == errSecSuccess else { throw BridgeError.code("keychain_\(status)") }
    }

    public func delete(_ account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw BridgeError.code("keychain_\(status)") }
    }
}

public struct Identity {
    public let deviceID: String
    public let signing: Curve25519.Signing.PrivateKey
    public let exchange: Curve25519.KeyAgreement.PrivateKey
}

public struct PairedPhone: Codable, Equatable {
    public let deviceID: String, name: String, signing: Data, exchange: Data, pairedAt: Date
    public var peer: Peer? {
        guard let s = try? Curve25519.Signing.PublicKey(rawRepresentation: signing),
              let e = try? Curve25519.KeyAgreement.PublicKey(rawRepresentation: exchange) else { return nil }
        return Peer(deviceID: deviceID, signing: s, exchange: e)
    }
}

public final class IdentityStore {
    static let identityAccount = "identity"
    static let phonesAccount = "phones"
    let secrets: SecretStore
    public init(secrets: SecretStore) { self.secrets = secrets }

    /// The Mac's identity, created once on first use.
    public func identity() throws -> Identity {
        if let raw = try secrets.read(Self.identityAccount),
           let d = try JSONSerialization.jsonObject(with: raw) as? [String: String],
           let id = d["device_id"], let s = d["signing"].flatMap({ Data(base64Encoded: $0) }),
           let e = d["exchange"].flatMap({ Data(base64Encoded: $0) }) {
            return Identity(deviceID: id, signing: try .init(rawRepresentation: s), exchange: try .init(rawRepresentation: e))
        }
        let fresh = Identity(deviceID: "mac-\(UUID().uuidString.lowercased())", signing: .init(), exchange: .init())
        let blob = try JSONSerialization.data(withJSONObject: [
            "device_id": fresh.deviceID, "signing": fresh.signing.rawRepresentation.base64EncodedString(),
            "exchange": fresh.exchange.rawRepresentation.base64EncodedString()])
        try secrets.write(Self.identityAccount, blob)
        return fresh
    }

    public func phones() throws -> [PairedPhone] {
        guard let raw = try secrets.read(Self.phonesAccount) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode([PairedPhone].self, from: raw)
    }

    public func save(phone: PairedPhone) throws {
        var all = try phones().filter { $0.deviceID != phone.deviceID }
        all.append(phone)
        try write(all)
    }

    /// Revoke: the phone's keys are forgotten; its messages no longer open.
    public func revoke(_ deviceID: String) throws { try write(try phones().filter { $0.deviceID != deviceID }) }

    func write(_ phones: [PairedPhone]) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try secrets.write(Self.phonesAccount, try encoder.encode(phones))
    }
}
