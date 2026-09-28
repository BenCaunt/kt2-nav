import Foundation
import PoseCore

func filterPacket(_ time: Double, position: [Double]?, session: String = "filter-test", tracking: String = "normal") -> PosePacket {
    var tag: TagPose?
    if let p = position {
        let world = [1.0,0,0,p[0], 0,0,1,p[1], 0,-1,0,p[2], 0,0,0,1]
        let cv = [1.0,0,0,p[0], 0,0,-1,-p[1], 0,1,0,-p[2], 0,0,0,1]
        tag = TagPose(cvCameraFromTag: cv, worldFromTag: world, cornersPx: [800,600,870,600,870,670,800,670],
            reprojectionErrorPx: 0.2, alternateErrorPx: 1, minimumEdgePx: 70, poseAmbiguous: false)
    }
    return PosePacket(sessionId: session, sequence: Int(time * 1000), frameTimestampS: time, sentUnixS: 100 + time,
        cameraTracking: tracking, cameraTrackingReason: tracking == "normal" ? "" : "relocalizing",
        worldFromCamera: [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1], imageResolution: [1920,1440],
        intrinsics: CameraIntrinsics(fx: 1000, fy: 1000, cx: 960, cy: 720), tagStatus: tag == nil ? "not_detected" : "detected", tag: tag)
}

func runPositionFilterChecks() throws {
    var filter = RobotPositionFilter()
    expect(filter.update(filterPacket(0, position: nil)) == nil, "No prediction before first tag")
    var estimate: RobotEstimate!
    var rawError = 0.0, filteredError = 0.0
    // A known 8 cm/s trajectory with alternating measurement jitter.
    for index in 1...90 {
        let t = Double(index) / 15
        let truth = 0.1 + 0.08 * t
        let noise = index.isMultiple(of: 2) ? 0.014 : -0.014
        estimate = filter.update(filterPacket(t, position: [truth + noise, -0.2, -0.5]))
        expect(estimate != nil && !estimate.isPredicted, "Accept plausible moving-tag observations")
        if index > 30 {
            rawError += noise * noise
            filteredError += pow(estimate.positionWorldM[0] - truth, 2)
        }
    }
    expect(filteredError < rawError * 0.5, "Filter reduces jitter on constant-velocity motion")
    expect(abs(estimate.velocityWorldMps[0] - 0.08) < 0.04, "Learn velocity from tag observations")
    let before = estimate!
    let duplicate = filter.update(filterPacket(6, position: [99,99,99]))!
    expect(duplicate.positionWorldM == before.positionWorldM, "Duplicate timestamps cannot update state")
    expect(duplicate.positionCovarianceM2 == before.positionCovarianceM2, "Duplicate timestamps cannot shrink covariance")
    let outlier = filter.update(filterPacket(6.05, position: [5,-0.2,-0.5]))!
    expect(outlier.isPredicted && outlier.positionWorldM[0] < 1, "Reject isolated pose jumps")
    estimate = filter.update(filterPacket(6.4, position: nil))
    expect(estimate != nil && estimate.isPredicted, "Predict through short occlusion")
    expect(abs(estimate.positionWorldM[0] - (0.1 + 0.08 * 6.4)) < 0.03, "Prediction follows learned velocity")
    expect(estimate.horizontalUncertainty.majorStdM > before.horizontalUncertainty.majorStdM, "Occlusion grows ellipse")
    let projectedOnce = filter.estimate(at: 6.6)!
    let projectedAgain = filter.estimate(at: 6.6)!
    expect(projectedOnce.positionWorldM == projectedAgain.positionWorldM, "Repeated UI projections do not accumulate drift")
    expect(filter.estimate(at: 7.01) == nil, "Expire after one second without an accepted observation")
    estimate = filter.update(filterPacket(7.1, position: [1.5,-0.2,-0.5]))
    expect(estimate != nil && estimate.velocityWorldMps == [0,0,0], "Reacquire after expiry with no stale velocity")
    expect(filter.update(filterPacket(7.2, position: [1.5,-0.2,-0.5], tracking: "limited")) == nil, "Invalidate on ARKit tracking loss")
    expect(filter.update(filterPacket(7.3, position: nil)) == nil, "Do not coast through a changed ARKit world")
    estimate = filter.update(filterPacket(1, position: [-0.2,-0.2,-0.5], session: "new-origin"))
    expect(estimate!.positionWorldM[0] == -0.2, "New session resets timestamps and world origin")
    var ambiguous = filterPacket(1.1, position: [4,-0.2,-0.5], session: "new-origin")
    ambiguous.tag?.poseAmbiguous = true
    expect(filter.update(ambiguous)?.isPredicted == true, "Ambiguous tag is not a filter measurement")
    filter.reset()
    expect(filter.estimate(at: 1.2) == nil, "Camera stop clears estimator")

    // A diagonal viewing ray must produce a rotated depth-uncertainty ellipse.
    let initial = filter.update(filterPacket(0, position: [0.4,-0.1,-0.4]))!
    let ellipse = initial.horizontalUncertainty
    expect(ellipse.majorStdM > ellipse.minorStdM * 2, "Keep anisotropic depth uncertainty")
    expect(abs(abs(ellipse.angleRadians) - .pi / 4) < 0.05, "Ellipse rotation follows covariance")
    expect(initial.positionCovarianceM2[2] < 0, "Preserve world X/Z cross covariance")
    let covariance = initial.positionCovarianceM2
    expect(zip(covariance, [covariance[0],covariance[3],covariance[6],covariance[1],covariance[4],covariance[7],covariance[2],covariance[5],covariance[8]]).allSatisfy { abs($0 - $1) < 1e-12 }, "Covariance is symmetric")
    var export = filterPacket(0.1, position: nil)
    export.robotEstimate = filter.update(export)
    let encoded = try JSONSerialization.jsonObject(with: export.json()) as! [String: Any]
    let wire = encoded["robot_estimate"] as! [String: Any]
    expect(wire["position_covariance_m2"] != nil && wire["velocity_world_mps"] != nil, "Export covariance and velocity over USB")
    expect(!export.navigationReady && encoded["tag"] == nil, "A prediction never invents a raw tag observation")
    print("PASS: Kalman smoothing, velocity, occlusion, outliers, expiry, resets and rotated uncertainty ellipse.")
    if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--filter-packet" {
        try export.json().write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
    }
}
