import Foundation

public struct CameraIntrinsics: Codable {
    public var fx: Double, fy: Double, cx: Double, cy: Double
    public init(fx: Double, fy: Double, cx: Double, cy: Double) {
        self.fx = fx; self.fy = fy; self.cx = cx; self.cy = cy
    }
}

public struct TagPose: Encodable {
    public let dictionary = "DICT_4X4_50"
    public let id = 0
    public let sideLengthM = 0.025
    public var cvCameraFromTag: [Double]
    public var worldFromTag: [Double]
    public var cornersPx: [Double]
    public var reprojectionErrorPx: Double
    public var alternateErrorPx: Double?
    public var minimumEdgePx: Double
    public var poseAmbiguous: Bool
    public init(cvCameraFromTag: [Double], worldFromTag: [Double], cornersPx: [Double], reprojectionErrorPx: Double,
                alternateErrorPx: Double?, minimumEdgePx: Double, poseAmbiguous: Bool) {
        self.cvCameraFromTag = cvCameraFromTag; self.worldFromTag = worldFromTag
        self.cornersPx = cornersPx; self.reprojectionErrorPx = reprojectionErrorPx
        self.alternateErrorPx = alternateErrorPx; self.minimumEdgePx = minimumEdgePx
        self.poseAmbiguous = poseAmbiguous
    }
}

public struct PosePacket: Encodable {
    public let schemaVersion = 1
    public var sessionId: String
    public var sequence: Int
    public var frameTimestampS: Double
    public var sentUnixS: Double
    public var cameraTracking: String
    public var cameraTrackingReason: String
    public var worldFromCamera: [Double]
    public var imageResolution: [Int]
    public var intrinsics: CameraIntrinsics
    public var tagStatus: String
    public var tag: TagPose?
    /// Separate from the raw observation; predictions do not set navigationReady.
    public var robotEstimate: RobotEstimate?
    public init(sessionId: String, sequence: Int, frameTimestampS: Double, sentUnixS: Double,
                cameraTracking: String, cameraTrackingReason: String, worldFromCamera: [Double],
                imageResolution: [Int], intrinsics: CameraIntrinsics, tagStatus: String, tag: TagPose?, robotEstimate: RobotEstimate? = nil) {
        self.sessionId = sessionId; self.sequence = sequence; self.frameTimestampS = frameTimestampS
        self.sentUnixS = sentUnixS; self.cameraTracking = cameraTracking
        self.cameraTrackingReason = cameraTrackingReason; self.worldFromCamera = worldFromCamera
        self.imageResolution = imageResolution; self.intrinsics = intrinsics
        self.tagStatus = tagStatus; self.tag = tag
        self.robotEstimate = robotEstimate
    }
    public var navigationReady: Bool { cameraTracking == "normal" && tag != nil && !tag!.poseAmbiguous }
    public func json() throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(self)
    }
}
