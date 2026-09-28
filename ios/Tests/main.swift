import Foundation
import simd
import PoseCore

func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    precondition(value(), message)
}
func near(_ a: Float, _ b: Float) -> Bool { abs(a-b) < 1e-5 }

var cv = matrix_identity_float4x4
cv.columns.3 = SIMD4(0.1, 0.2, 1, 1)
let converted = PoseMath.worldFromTag(camera: matrix_identity_float4x4, cvTag: cv)
expect(converted.columns.3 == SIMD4(0.1, -0.2, -1, 1), "OpenCV -> ARKit axes")
var camera = simd_float4x4(simd_quatf(angle: .pi / 2, axis: SIMD3(0, 1, 0)))
camera.columns.3 = SIMD4(2, 3, 4, 1)
let result = PoseMath.worldFromTag(camera: camera, cvTag: cv)
expect(near(result.columns.3.x,1) && near(result.columns.3.y,2.8) && near(result.columns.3.z,3.9), "Rotated and translated camera composition")
let rotation = simd_float3x3(columns: (
    SIMD3(result.columns.0.x,result.columns.0.y,result.columns.0.z),
    SIMD3(result.columns.1.x,result.columns.1.y,result.columns.1.z),
    SIMD3(result.columns.2.x,result.columns.2.y,result.columns.2.z)))
expect(near(simd_determinant(rotation), 1), "Right handed rotation")
var m = matrix_identity_float4x4
m.columns.3 = SIMD4(1,2,3,1)
expect(PoseMath.rowMajor(m) == [1,0,0,1,0,1,0,2,0,0,1,3,0,0,0,1], "Row-major translation")
expect(PoseMath.fromRowMajor(PoseMath.rowMajor(m)) == m, "Matrix round trip")
expect(ReceiverAddress.url("192.168.1.20")?.absoluteString == "ws://192.168.1.20:8766/ingest", "Local URL")
expect(ReceiverAddress.url("My-Mac.local:9000")?.port == 9000, "mDNS hostname")
for host in ["8.8.8.8", "example.com", "010.1.2.3", "192.168.1.1/other", "user@192.168.1.1", "192.168.999.2", "192.168.1.2:0", "192.168.1.1?token=x", "ws://192.168.1.1"] {
    expect(ReceiverAddress.url(host) == nil, "Reject malformed/nonlocal receiver: \(host)")
}
var packet = PosePacket(sessionId: "test", sequence: 1, frameTimestampS: 10, sentUnixS: 20,
    cameraTracking: "limited", cameraTrackingReason: "initializing", worldFromCamera: PoseMath.rowMajor(camera),
    imageResolution: [1920,1440], intrinsics: CameraIntrinsics(fx: 1000, fy: 1000, cx: 960, cy: 720), tagStatus: "not_detected", tag: nil)
expect(!packet.navigationReady, "Missing tag is not usable")
let missing = try JSONSerialization.jsonObject(with: packet.json()) as! [String: Any]
expect(missing["frame_timestamp_s"] as? Double == 10 && missing["session_id"] as? String == "test", "Wire keys")
expect(missing["tag"] == nil, "Missing tag must not retain previous pose")
packet.tag = TagPose(cvCameraFromTag: PoseMath.rowMajor(cv), worldFromTag: PoseMath.rowMajor(result),
    cornersPx: [800,600,870,600,870,670,800,670], reprojectionErrorPx: 0.2, alternateErrorPx: 1,
    minimumEdgePx: 70, poseAmbiguous: false)
packet.tagStatus = "detected"
expect(!packet.navigationReady, "Limited ARKit tracking invalidates world pose")
packet.cameraTracking = "normal"
packet.cameraTrackingReason = ""
expect(packet.navigationReady, "Valid observation is usable")
let withTag = try JSONSerialization.jsonObject(with: packet.json()) as! [String: Any]
let tag = withTag["tag"] as! [String: Any]
expect(tag["cv_camera_from_tag"] != nil && tag["world_from_tag"] != nil, "Tag transform wire keys")
expect(tag["side_length_m"] as? Double == 0.025, "Use black edge, not sticker size")
expect(tag["pose_ambiguous"] as? Bool == false, "Ambiguity wire flag")
if CommandLine.arguments.count == 2 {
    try packet.json().write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
}
packet.tag?.poseAmbiguous = true
expect(!packet.navigationReady, "Ambiguous tag invalidates navigation pose")
print("PASS: axis conversion, matrix composition, serialization, local URLs and tracking quality gates.")
try runPositionFilterChecks()

for identity in [#"{"model":"B4KT2","status":"OK"}"#, #"{"v":"B4KT2-V260201"}"#] {
    expect((try? RobotProgram.verifyIdentity(Data(identity.utf8))) != nil, "Accept robot identity")
}
for identity in [#"{"model":"B4KT2-SIM"}"#, #"{"model":"B4KT2","simulation":true}"#, #"{"model":"OTHER"}"#, #"{"model":"B4KT2","status":"ERR"}"#] {
    expect((try? RobotProgram.verifyIdentity(Data(identity.utf8))) == nil, "Reject wrong robot identity")
}
expect((try? RobotProgram.motion(action: "eval", token: String(repeating: "a", count: 32))) == nil, "No arbitrary robot commands")
expect((try? RobotProgram.motion(action: "stand", token: "';boom()")) == nil, "No injected token")
expect((try? RobotProgram.motion(action: "walk_forward", token: String(repeating: "a", count: 32), cycles: 11)) == nil, "Bound walking repeats")
expect((try? RobotProgram.motion(action: "turn_left", token: String(repeating: "a", count: 32), degrees: 180)) == nil, "Bound turning angle")
expect((try? RobotProgram.motion(action: "walk_forward", token: String(repeating: "a", count: 32), stepMs: 0)) == nil, "Reject unpaced walking")
expect((try? RobotProgram.motion(action: "walk_forward", token: String(repeating: "a", count: 32), stepMs: 121)) == nil, "Bound walking interval")
expect((try? JSONDecoder().decode(MotionParameters.self, from: Data(#"{"cycles":true}"#.utf8))) == nil, "Reject boolean cycle count")
expect(RobotProgram.supported(actions: ["walk", "c_pivot", "ofs_stand_low"], methods: ["play", "frame"]) == ["stand", "walk_forward", "walk_back", "turn_left", "turn_right", "crouch"], "Discover supported motions")
expect(String(decoding: RobotProgram.formBody(code: "a+b & c\n"), as: UTF8.self) == "code=a%2Bb%20%26%20c%0A", "Robot form encoding")
print("PASS: robot identity, command allowlist and form encoding.")

if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--robot-programs" {
    var programs = [String: String]()
    for action in RobotProgram.actions { programs[action] = try RobotProgram.motion(action: action, token: String(repeating: "a", count: 32), cycles: 5, degrees: 30) }
    programs["probe"] = try RobotProgram.capabilities(token: String(repeating: "a", count: 32))
    try JSONSerialization.data(withJSONObject: programs).write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
}

// Uses the exact iPhone USB server on macOS; commands only acknowledge, never move hardware.
if CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--usb-server-check" {
    let relay = USBRelayServer()
    relay.onCommand = { id, action, parameters, canExecute, reply in reply(canExecute(), "SYNTHETIC CHECK: \(action) cycles=\(parameters.cycles) degrees=\(parameters.degrees) step_ms=\(parameters.stepMs)") }
    relay.start(token: CommandLine.arguments[2], port: UInt16(CommandLine.arguments[3])!)
    packet.sessionId = "SYNTHETIC-SWIFT-USB-CHECK"
    packet.tag?.poseAmbiguous = false
    var positionFilter = RobotPositionFilter()
    for i in 1...900 {
        packet.sequence = i; packet.frameTimestampS = ProcessInfo.processInfo.systemUptime
        packet.sentUnixS = Date().timeIntervalSince1970
        packet.robotEstimate = positionFilter.update(packet)
        relay.publish(packet: packet, robot: ["status": "SYNTHETIC", "armed": true, "can_move": true, "can_stop": true, "busy": false, "supported_motions": RobotProgram.actions])
        Thread.sleep(forTimeInterval: 1.0/15)
    }
    relay.stop()
}

// Optional end-to-end check of the SAME URLSessionWebSocketTask client used on iOS.
// Packets are visibly labelled synthetic; use an unrecorded test receiver.
if CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--stream-check" {
    let client = PoseStreamClient()
    let connected = DispatchSemaphore(value: 0)
    client.onStatus = { status, isConnected in
        print("Transport: \(status)")
        if isConnected { connected.signal() }
    }
    guard let url = ReceiverAddress.url(CommandLine.arguments[2]) else { fatalError("Invalid local receiver") }
    client.connect(url: url, token: CommandLine.arguments[3])
    expect(connected.wait(timeout: .now()+8) == .success, "WebSocket handshake")
    packet.sessionId = "SYNTHETIC-SWIFT-TRANSPORT-CHECK"
    packet.tag?.poseAmbiguous = false
    for i in 1...150 {
        packet.sequence = i
        packet.frameTimestampS = ProcessInfo.processInfo.systemUptime
        packet.sentUnixS = Date().timeIntervalSince1970
        var movingTag = cv
        movingTag.columns.3.x += 0.1 * sin(Float(i)/20)
        packet.tag?.cvCameraFromTag = PoseMath.rowMajor(movingTag)
        packet.tag?.worldFromTag = PoseMath.rowMajor(PoseMath.worldFromTag(camera: camera, cvTag: movingTag))
        client.submit(packet)
        Thread.sleep(forTimeInterval: 0.1)
    }
    client.disconnect()
    Thread.sleep(forTimeInterval: 0.2)
    print("PASS: native Swift WebSocket client connected and sent synthetic pose frames.")
}
