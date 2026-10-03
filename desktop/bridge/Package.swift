// swift-tools-version:5.7
// Arslan Bridge: the Mac side of the iPhone companion (docs/specs/mobile-bridge-protocol.md).
import PackageDescription

let package = Package(
    name: "ArslanBridge",
    platforms: [.macOS(.v11)],
    products: [.executable(name: "ArslanBridge", targets: ["ArslanBridge"])],
    targets: [
        .target(name: "BridgeCore"),
        .executableTarget(name: "ArslanBridge", dependencies: ["BridgeCore"]),
        .testTarget(name: "BridgeCoreTests", dependencies: ["BridgeCore"]),
    ]
)
