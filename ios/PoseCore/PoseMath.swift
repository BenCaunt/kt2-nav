import Foundation
import simd

public enum PoseMath {
    // OpenCV: right, down, forward. ARKit camera: right, up, backward.
    public static let arCameraFromCVCamera = simd_float4x4(diagonal: SIMD4<Float>(1, -1, -1, 1))
    public static func worldFromTag(camera: simd_float4x4, cvTag: simd_float4x4) -> simd_float4x4 {
        camera * arCameraFromCVCamera * cvTag
    }
    public static func rowMajor(_ matrix: simd_float4x4) -> [Double] {
        (0..<4).flatMap { row in (0..<4).map { col in Double(matrix[col][row]) } }
    }
    public static func fromRowMajor(_ a: [Double]) -> simd_float4x4 {
        precondition(a.count == 16)
        return simd_float4x4(columns: (
            SIMD4(Float(a[0]), Float(a[4]), Float(a[8]), Float(a[12])),
            SIMD4(Float(a[1]), Float(a[5]), Float(a[9]), Float(a[13])),
            SIMD4(Float(a[2]), Float(a[6]), Float(a[10]), Float(a[14])),
            SIMD4(Float(a[3]), Float(a[7]), Float(a[11]), Float(a[15]))))
    }
}

public enum ReceiverAddress {
    public static func url(_ address: String) -> URL? {
        let address = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var c = URLComponents(string: "ws://" + address),
              let host = c.host?.lowercased(), c.user == nil, c.password == nil,
              c.path.isEmpty, c.query == nil, c.fragment == nil else { return nil }
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        let bytes = parts.compactMap { Int($0) }
        let isPrivateIP = parts.count == 4 && bytes.count == 4 &&
            parts.allSatisfy { !$0.isEmpty && $0.allSatisfy { $0.isASCII && $0.isNumber } } &&
            zip(parts, bytes).allSatisfy { String($0.0) == String($0.1) } &&
            bytes.allSatisfy { (0...255).contains($0) } &&
            (bytes[0] == 10 || (bytes[0] == 192 && bytes[1] == 168) ||
             (bytes[0] == 172 && (16...31).contains(bytes[1])) ||
             (bytes[0] == 169 && bytes[1] == 254))
        let isLocalName = host.hasSuffix(".local") && host.count > 6 &&
            host.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == ".") }
        guard isPrivateIP || isLocalName, (1...65535).contains(c.port ?? 8766) else { return nil }
        c.port = c.port ?? 8766
        c.path = "/ingest"
        return c.url
    }
}
