import ARKit
import Foundation
import PoseCore

/// Delegate callbacks remain cheap; at most one retained ARFrame is processed at once.
final class PoseTracker: NSObject, ARSessionDelegate {
    let session = ARSession()
    var onPacket: ((PosePacket) -> Void)?
    var onProblem: ((String) -> Void)?
    private let delegateQueue = DispatchQueue(label: "kt2.arkit.delegate")
    private let detectorQueue = DispatchQueue(label: "kt2.aruco", qos: .userInitiated)
    private let detector = KTMarkerDetector()
    private var running = false
    private var busy = false
    private var sessionID = UUID().uuidString
    private var sequence = 0
    private var lastFrameTime = -Double.infinity

    override init() {
        super.init()
        session.delegate = self
        session.delegateQueue = delegateQueue
    }
    func start(sessionID: String) {
        delegateQueue.async {
            self.sessionID = sessionID
            self.sequence = 0
            self.lastFrameTime = -.infinity
            self.running = true
            let config = ARWorldTrackingConfiguration()
            config.worldAlignment = .gravity
            config.isAutoFocusEnabled = true
            // Do not create image anchors for the moving robot; solve its pose per frame.
            self.session.run(config, options: [.resetTracking, .removeExistingAnchors])
        }
    }
    func stop() {
        delegateQueue.async {
            self.running = false
            self.sessionID = UUID().uuidString // Invalidate in-flight detections.
            self.session.pause()
        }
    }
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard running, !busy, frame.timestamp - lastFrameTime >= 1.0 / 15 else { return }
        busy = true
        lastFrameTime = frame.timestamp
        let epoch = sessionID
        sequence += 1
        let seq = sequence
        let processingStarted = ProcessInfo.processInfo.systemUptime
        detectorQueue.async {
            let detection = self.detector.detect(frame.capturedImage, intrinsics: frame.camera.intrinsics)
            let camera = frame.camera.transform
            let K = frame.camera.intrinsics
            var tag: TagPose?
            if detection.status == "detected" {
                tag = TagPose(cvCameraFromTag: PoseMath.rowMajor(detection.cameraFromTagCV),
                              worldFromTag: PoseMath.rowMajor(PoseMath.worldFromTag(camera: camera, cvTag: detection.cameraFromTagCV)),
                              cornersPx: detection.cornersPx.map { $0.doubleValue },
                              reprojectionErrorPx: detection.reprojectionErrorPx,
                              alternateErrorPx: detection.alternateErrorPx?.doubleValue,
                              minimumEdgePx: detection.minimumEdgePx,
                              poseAmbiguous: detection.poseAmbiguous)
            }
            let tracking = Self.trackingDescription(frame.camera.trackingState)
            let packet = PosePacket(sessionId: epoch, sequence: seq, frameTimestampS: frame.timestamp,
                sentUnixS: Date().timeIntervalSince1970, cameraTracking: tracking.0, cameraTrackingReason: tracking.1,
                worldFromCamera: PoseMath.rowMajor(camera), imageResolution: [CVPixelBufferGetWidth(frame.capturedImage), CVPixelBufferGetHeight(frame.capturedImage)],
                intrinsics: CameraIntrinsics(fx: Double(K[0][0]), fy: Double(K[1][1]), cx: Double(K[2][0]), cy: Double(K[2][1])),
                tagStatus: detection.status, tag: tag)
            self.delegateQueue.async {
                self.busy = false
                guard self.running, self.sessionID == epoch else { return }
                guard ProcessInfo.processInfo.systemUptime - processingStarted < 0.4 else { return }
                self.onPacket?(packet)
            }
        }
    }
    private static func trackingDescription(_ state: ARCamera.TrackingState) -> (String, String) {
        switch state {
        case .normal: return ("normal", "")
        case .notAvailable: return ("not_available", "Camera tracking unavailable")
        case .limited(let reason):
            switch reason {
            case .initializing: return ("limited", "initializing")
            case .excessiveMotion: return ("limited", "excessive_motion")
            case .insufficientFeatures: return ("limited", "insufficient_features")
            case .relocalizing: return ("limited", "relocalizing")
            @unknown default: return ("limited", "unknown")
            }
        }
    }
    func session(_ session: ARSession, didFailWithError error: Error) {
        running = false
        sessionID = UUID().uuidString
        onProblem?(error.localizedDescription)
    }
    func sessionWasInterrupted(_ session: ARSession) {
        running = false
        sessionID = UUID().uuidString
        onProblem?("Camera interrupted. Start the camera again to create a new world origin.")
    }
}
