// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "KT2PoseCore",
    platforms: [.macOS(.v13), .iOS(.v17)],
    products: [.library(name: "PoseCore", targets: ["PoseCore"]),
               .executable(name: "PoseCoreChecks", targets: ["PoseCoreChecks"])],
    targets: [.target(name: "PoseCore", path: "PoseCore"),
              .executableTarget(name: "PoseCoreChecks", dependencies: ["PoseCore"], path: "Tests")]
)
