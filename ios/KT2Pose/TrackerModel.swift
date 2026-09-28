import ARKit
import AVFoundation
import Combine
import PoseCore
import SwiftUI

@MainActor final class TrackerModel: ObservableObject {
    let tracker = PoseTracker()
    let robot = RobotController()
    private let relay = USBRelayServer()
    @Published var packet: PosePacket?
    @Published var cameraRunning = false
    @Published var streamConnected = false
    @Published var streamStatus = "Starting USB listener"
    @Published var problem: String?
    let pairingCode: String
    @Published var lastObservation: Date?
    @Published private(set) var trail = [PoseTrailPoint]()
    private var positionFilter = RobotPositionFilter()
    private var lastPacketUptime: Double?
    private var breakTrail = true
    private var startRequest = UUID()
    private var expectedSessionID: String?
    private var statusTimer: Timer?

    init() {
        if let saved = UserDefaults.standard.string(forKey: "usbPairingCode") { pairingCode = saved }
        else {
            pairingCode = UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12).uppercased()
            UserDefaults.standard.set(pairingCode, forKey: "usbPairingCode")
        }
        tracker.onPacket = { [weak self] packet in
            DispatchQueue.main.async {
                guard let self, self.cameraRunning, self.expectedSessionID == packet.sessionId else { return }
                var enriched = packet
                enriched.robotEstimate = self.positionFilter.update(packet)
                self.packet = enriched
                self.lastPacketUptime = ProcessInfo.processInfo.systemUptime
                if packet.cameraTracking != "normal" { self.trail.removeAll(); self.breakTrail = true }
                if let estimate = enriched.robotEstimate {
                    self.trail.append(PoseTrailPoint(position: estimate.positionWorldM,
                        predicted: estimate.isPredicted, startsSegment: self.breakTrail))
                    self.breakTrail = false
                    if self.trail.count > 240 { self.trail.removeFirst(self.trail.count - 240) }
                } else { self.breakTrail = true }
                self.lastObservation = Date()
                self.publish()
            }
        }
        tracker.onProblem = { [weak self] message in
            DispatchQueue.main.async {
                guard let self else { return }
                self.stopCamera()
                self.problem = message
            }
        }
        relay.onStatus = { [weak self] status, connected in
            DispatchQueue.main.async {
                self?.streamStatus = status
                self?.streamConnected = connected
            }
        }
        relay.onDisconnect = { [weak self] in Task { @MainActor in self?.robot.linkLost() } }
        relay.onCommand = { [weak self] id, action, parameters, canExecute, reply in
            Task { @MainActor in
                guard let self else { reply(false, "App unavailable"); return }
                guard action == "stop" || canExecute() else { reply(false, "USB command expired before execution"); return }
                if action == "stop" { self.robot.stop(); reply(true, "Stop requested; check robot status for acknowledgement") }
                else if action == "connect" { reply(self.robot.connect(), "Robot connection check requested") }
                else {
                    let accepted = self.robot.move(action, id: id, cycles: parameters.cycles, degrees: parameters.degrees, stepMs: parameters.stepMs)
                    reply(accepted, accepted ? "Motion accepted; check robot status for completion" : "Connect the robot, enable motion on the phone, and wait for the active command")
                }
            }
        }
        robot.onChange = { [weak self] in self?.publish() }
        resume()
    }
    private func publish() { relay.publish(packet: packet, robot: robot.snapshot) }
    func displayEstimate(at uptime: Double) -> RobotEstimate? {
        guard cameraRunning, let packet, let lastPacketUptime,
              uptime - lastPacketUptime < 0.5, packet.cameraTracking == "normal" else { return nil }
        return positionFilter.estimate(at: packet.frameTimestampS + max(0, uptime - lastPacketUptime))
    }
    private func resetEstimation() {
        positionFilter.reset(); trail.removeAll(); breakTrail = true; lastPacketUptime = nil
    }
    func resume() {
        relay.start(token: pairingCode)
        if statusTimer == nil { statusTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.publish() }
        } }
    }
    func suspend() {
        let task = UIApplication.shared.beginBackgroundTask(withName: "Stop KT2")
        robot.stop(reason: "App backgrounded — stopping")
        stopCamera(); relay.stop(); statusTimer?.invalidate(); statusTimer = nil
        Task { @MainActor in
            for _ in 0..<80 { if !robot.busy { break }; try? await Task.sleep(nanoseconds: 100_000_000) }
            if task != .invalid { UIApplication.shared.endBackgroundTask(task) }
        }
    }
    func startCamera() {
        guard ARWorldTrackingConfiguration.isSupported else {
            problem = "ARKit world tracking needs a supported physical iPhone. The simulator cannot track the tag."
            return
        }
        let request = UUID()
        startRequest = request
        func begin() {
            guard self.startRequest == request else { return }
            self.problem = nil
            self.packet = nil
            self.lastObservation = nil
            self.resetEstimation()
            self.cameraRunning = true
            UIApplication.shared.isIdleTimerDisabled = true
            let epoch = UUID().uuidString
            self.expectedSessionID = epoch
            self.tracker.start(sessionID: epoch)
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: begin()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { allowed in
                DispatchQueue.main.async {
                    guard self.startRequest == request else { return }
                    if allowed { begin() }
                    else { self.problem = "Camera access is required. Enable it in Settings > KT2 Pose." }
                }
            }
        default: problem = "Camera access is disabled. Enable it in Settings > KT2 Pose."
        }
    }
    func stopCamera() {
        startRequest = UUID()
        tracker.stop()
        cameraRunning = false
        expectedSessionID = nil
        packet = nil
        lastObservation = nil
        resetEstimation()
        publish()
        UIApplication.shared.isIdleTimerDisabled = false
    }
    func resetWorld() {
        if robot.busy || robot.armed { robot.stop(reason: "Origin reset — stopping") }
        stopCamera()
        startCamera()
    }
}
