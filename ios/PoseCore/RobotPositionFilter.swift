import Foundation
import simd

/// Translation only. Orientation is held from the last accepted tag observation.
public struct RobotEstimate: Encodable {
    public let mode: String
    public let positionWorldM: [Double]
    public let velocityWorldMps: [Double]
    public let positionStdM: [Double]
    /// Row-major 3x3 covariance, in world X/Y/Z, square metres.
    public let positionCovarianceM2: [Double]
    public let worldFromTag: [Double]
    public let observationAgeS: Double

    public var isPredicted: Bool { mode == "predicted" }
    public var horizontalUncertainty: (majorStdM: Double, minorStdM: Double, angleRadians: Double) {
        let a = positionCovarianceM2[0], b = positionCovarianceM2[2], c = positionCovarianceM2[8]
        let spread = hypot(a - c, 2 * b)
        return (sqrt(max(0, (a + c + spread) / 2)), sqrt(max(0, (a + c - spread) / 2)), atan2(2 * b, a - c) / 2)
    }
}

/// Six-state [position XYZ, velocity XYZ] Kalman filter, in ARKit world space.
/// Stores the 6x6 covariance as 3x3 PP, PV and VV blocks. Q integrates white
/// acceleration; measurements observe position, with larger error along depth.
public struct RobotPositionFilter {
    public static let predictionLimitS = 1.0
    public static let maximumPositionStdM = 0.15
    private static let accelerationPSD = 0.15 * 0.15
    private var state: State?
    private var sessionID: String?
    private var frameTime: Double?
    private var observationTime: Double?
    private var orientation = [Double]()
    private var acceptedCurrentFrame = false

    public init() {}
    public mutating func reset() { self = Self() }

    /// Never consumes a repeated measurement, including repeated USB status packets.
    @discardableResult public mutating func update(_ packet: PosePacket) -> RobotEstimate? {
        let time = packet.frameTimestampS
        guard time.isFinite, time >= 0 else { return nil }
        if sessionID != packet.sessionId { reset(); sessionID = packet.sessionId }
        if let previous = frameTime, time <= previous { return estimate(at: previous) }
        guard packet.cameraTracking == "normal" else {
            state = nil; observationTime = nil; orientation = []; frameTime = time
            acceptedCurrentFrame = false
            return nil
        }
        if let last = observationTime, time - last > Self.predictionLimitS {
            state = nil; observationTime = nil; orientation = []
        }
        if let previous = frameTime { state?.predict(dt: time - previous) }
        frameTime = time
        acceptedCurrentFrame = false
        if let tag = packet.tag, packet.navigationReady, tag.worldFromTag.count == 16,
           tag.worldFromTag.allSatisfy(\.isFinite), tag.minimumEdgePx.isFinite, tag.minimumEdgePx >= 24,
           tag.reprojectionErrorPx.isFinite, (0...2.5).contains(tag.reprojectionErrorPx) {
            let measurement = SIMD3(tag.worldFromTag[3], tag.worldFromTag[7], tag.worldFromTag[11])
            // Starting noise model, not a calibrated accuracy guarantee. A small
            // planar tag has poorer depth than lateral precision. Express that
            // camera-ray covariance in world coordinates, retaining correlations.
            let sigma = min(0.04, max(0.006, 0.008 * 50 / tag.minimumEdgePx * (1 + tag.reprojectionErrorPx)))
            var noise = matrix_identity_double3x3 * (sigma * sigma)
            if packet.worldFromCamera.count == 16, packet.worldFromCamera.allSatisfy(\.isFinite) {
                let camera = SIMD3(packet.worldFromCamera[3], packet.worldFromCamera[7], packet.worldFromCamera[11])
                let ray = measurement - camera
                if simd_length(ray) > 0.01 {
                    let direction = simd_normalize(ray)
                    let outer = simd_double3x3(columns: (direction * direction.x, direction * direction.y, direction * direction.z))
                    noise += outer * (8 * sigma * sigma) // Depth standard deviation = 3x lateral.
                }
            }
            if state == nil {
                state = State(position: measurement, pp: noise)
                acceptedCurrentFrame = true
            } else if state!.correct(measurement, noise: noise) {
                acceptedCurrentFrame = true
            }
            if acceptedCurrentFrame { observationTime = time; orientation = tag.worldFromTag }
        }
        return estimate(at: time)
    }

    /// Non-mutating projection for UI animation. Repainting cannot refresh the
    /// measurement time, advance the stored state, or reduce uncertainty.
    public func estimate(at time: Double) -> RobotEstimate? {
        guard time.isFinite, let frameTime, let observationTime, var projected = state,
              time >= frameTime, time - observationTime <= Self.predictionLimitS else { return nil }
        projected.predict(dt: time - frameTime)
        let uncertainty = (0..<3).map { sqrt(max(0, projected.pp[$0][$0])) }
        guard uncertainty.allSatisfy({ $0.isFinite && $0 <= Self.maximumPositionStdM }) else { return nil }
        var transform = orientation
        for index in 0..<3 { transform[index * 4 + 3] = projected.position[index] }
        let covariance = (0..<9).map { projected.pp[$0 % 3][$0 / 3] }
        let predicted = !acceptedCurrentFrame || time - observationTime > 0.15
        return RobotEstimate(mode: predicted ? "predicted" : "filtered", positionWorldM: (0..<3).map { projected.position[$0] },
            velocityWorldMps: (0..<3).map { projected.velocity[$0] }, positionStdM: uncertainty,
            positionCovarianceM2: covariance, worldFromTag: transform, observationAgeS: max(0, time - observationTime))
    }

    private struct State {
        var position: SIMD3<Double>
        var velocity = SIMD3<Double>(repeating: 0)
        var pp: simd_double3x3
        var pv = simd_double3x3(diagonal: SIMD3<Double>(repeating: 0))
        var vv = matrix_identity_double3x3 * 0.04

        mutating func predict(dt: Double) {
            guard dt > 0 else { return }
            position += velocity * dt
            let q = matrix_identity_double3x3 * RobotPositionFilter.accelerationPSD
            pp += (pv + pv.transpose) * dt + vv * (dt * dt) + q * (dt * dt * dt / 3)
            pv += vv * dt + q * (dt * dt / 2)
            vv += q * dt
        }

        mutating func correct(_ measurement: SIMD3<Double>, noise: simd_double3x3) -> Bool {
            let residual = measurement - position
            let innovation = pp + noise
            let inverse = innovation.inverse
            let distance = simd_dot(residual, inverse * residual)
            // 99.9% chi-square gate (3 DOF). Reject a single jump, then re-seed
            // after expiry if the robot really moved to a different location.
            guard distance.isFinite, distance <= 16.27 else { return false }
            let kp = pp * inverse, kv = pv.transpose * inverse
            position += kp * residual; velocity += kv * residual
            // Joseph-form block update; keep PP and VV explicitly symmetric.
            let a = matrix_identity_double3x3 - kp
            let newPP = a * pp * a.transpose + kp * noise * kp.transpose
            let newPV = a * (pv - pp * kv.transpose) + kp * noise * kv.transpose
            let newVV = vv - kv * pv - pv.transpose * kv.transpose + kv * innovation * kv.transpose
            pp = (newPP + newPP.transpose) * 0.5
            pv = newPV
            vv = (newVV + newVV.transpose) * 0.5
            return true
        }
    }
}
