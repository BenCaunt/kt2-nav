import SwiftUI
import PoseCore

struct ContentView: View {
    @StateObject private var model = TrackerModel()
    @Environment(\.scenePhase) private var phase
    @State private var showReset = false
    private let green = Color(red: 0.62, green: 0.91, blue: 0.71)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("KT2 Pose").font(.largeTitle.bold())
                        Spacer()
                        Text("STANDARD TAG").font(.caption2.weight(.semibold)).foregroundStyle(green)
                    }
                    Text("Robot on Wi-Fi. Mac over USB.").foregroundStyle(.secondary)
                    TimelineView(.periodic(from: .now, by: 1.0 / 30)) { tick in
                        let fresh = model.lastObservation.map { tick.date.timeIntervalSince($0) < 0.5 } ?? false
                        let estimate = model.displayEstimate(at: ProcessInfo.processInfo.systemUptime)
                        ZStack(alignment: .bottomLeading) {
                            CameraPreview(session: model.tracker.session, packet: model.packet, fresh: fresh, estimate: estimate)
                            if !model.cameraRunning {
                                VStack(spacing: 12) {
                                    Image(systemName: "viewfinder").font(.system(size: 44, weight: .light))
                                    Text("Point at the sticker on your KT2")
                                    Text("25 mm marker · ArUco ID 0").font(.caption).foregroundStyle(.secondary)
                                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                            }
                            if model.cameraRunning {
                                Label(estimate?.isPredicted == true ? "Predicting position" : tagStatus(fresh: fresh), systemImage: estimate?.isPredicted == true ? "clock.arrow.circlepath" : model.packet?.navigationReady == true && fresh ? "checkmark.circle.fill" : "viewfinder")
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(estimate?.isPredicted == true ? .orange : .primary)
                                    .padding(12).background(.ultraThinMaterial, in: Capsule()).padding(14)
                            }
                        }.frame(height: 270).clipShape(RoundedRectangle(cornerRadius: 22))
                    }
                    HStack(spacing: 18) {
                        Text("X · right").foregroundStyle(.red)
                        Text("Y · forward").foregroundStyle(green)
                        Text("Z · up").foregroundStyle(.cyan)
                    }.font(.caption.bold())
                    HStack {
                        Button(model.cameraRunning ? "Stop camera" : "Start camera", systemImage: model.cameraRunning ? "stop.fill" : "camera.fill") {
                            model.cameraRunning ? model.stopCamera() : model.startCamera()
                        }.buttonStyle(.borderedProminent).tint(green).foregroundStyle(.black)
                        Spacer()
                        Button("Reset origin", systemImage: "arrow.counterclockwise") { showReset = true }
                            .font(.subheadline).disabled(!model.cameraRunning)
                    }
                    TimelineView(.periodic(from: .now, by: 1.0 / 30)) { tick in
                        let fresh = model.lastObservation.map { tick.date.timeIntervalSince($0) < 0.5 } ?? false
                        let estimate = model.displayEstimate(at: ProcessInfo.processInfo.systemUptime)
                        PoseMapView(camera: fresh && model.packet?.cameraTracking == "normal" ? model.packet?.worldFromCamera : nil,
                            rawTag: fresh && model.packet?.navigationReady == true ? model.packet?.tag?.worldFromTag : nil,
                            estimate: estimate, trail: model.trail,
                            waitingMessage: !model.cameraRunning ? "Start camera to track the robot" : model.packet?.cameraTracking != "normal" ? "Move the phone slowly to establish tracking" : "Show the tag to reacquire position")
                    }
                    RobotControls(robot: model.robot)
                    VStack(alignment: .leading, spacing: 10) {
                        Label("USB to Mac", systemImage: "cable.connector").font(.headline)
                        Text(model.streamStatus).font(.subheadline).foregroundStyle(model.streamConnected ? green : .secondary)
                        LabeledContent("Pairing code") { Text(model.pairingCode).font(.system(.body, design: .monospaced).bold()).textSelection(.enabled) }
                        Text("Plug into your Mac and run Start KT2 USB.command. Keep this app open; Personal Hotspot is not needed.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.padding(18).background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
                    if let problem = model.problem {
                        Label(problem, systemImage: "exclamationmark.circle").font(.subheadline).foregroundStyle(.orange)
                    }
                    if let p = model.packet {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Last observation").fontWeight(.semibold).foregroundStyle(.secondary)
                            LabeledContent("ARKit", value: p.cameraTrackingReason.isEmpty ? p.cameraTracking : p.cameraTrackingReason.replacingOccurrences(of: "_", with: " "))
                            if let tag = p.tag {
                                LabeledContent("Tag error", value: String(format: "%.2f px", tag.reprojectionErrorPx))
                                LabeledContent("Tag x / y / z", value: coordinates(tag.worldFromTag))
                            }
                            LabeledContent("Camera x / y / z", value: coordinates(p.worldFromCamera))
                        }.font(.caption).monospacedDigit()
                    }
                    Text("Join xiaogui in iPhone Wi-Fi settings. Your Mac can stay on its usual internet network. Only poses and robot status travel over USB; camera images stay on the phone.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(20)
            }
            .background(Color(red: 0.06, green: 0.095, blue: 0.075))
            .toolbar(.hidden, for: .navigationBar)
            .confirmationDialog("Reset the AR world origin? The Mac's trail will clear.", isPresented: $showReset, titleVisibility: .visible) {
                Button("Reset origin") { model.resetWorld() }
            }
        }
        .preferredColorScheme(.dark)
        .safeAreaInset(edge: .bottom, spacing: 0) { RobotStopBar(robot: model.robot) }
        .onChange(of: phase) { _, newPhase in
            if newPhase == .background { model.suspend() }
            else if newPhase == .active { model.resume() }
        }
    }
    private func tagStatus(fresh: Bool) -> String {
        guard fresh, let p = model.packet else { return "Waiting for camera frames" }
        if p.cameraTracking != "normal" { return "Move the phone slowly to establish tracking" }
        guard let tag = p.tag else {
            return p.tagStatus == "duplicate" ? "Two ID 0 tags visible — keep only one" :
                   p.tagStatus == "too_small" ? "Move closer to the tag" : "Looking for the tag"
        }
        return tag.poseAmbiguous ? "Tilt the view slightly — pose is ambiguous" : "Tracking KT2"
    }
    private func coordinates(_ m: [Double]) -> String {
        String(format: "%.3f / %.3f / %.3f m", m[3], m[7], m[11])
    }
}

private struct RobotControls: View {
    @ObservedObject var robot: RobotController
    @State private var cycles = 5
    @State private var degrees = 30
    @State private var stepMs = 80
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Robot motion", systemImage: "gamecontroller.fill").font(.headline)
                Spacer()
                Button("Connect") { robot.connect() }.buttonStyle(.bordered).disabled(robot.busy)
            }
            Text(robot.status).font(.caption).foregroundStyle(.secondary)
            Toggle("Enable motion", isOn: Binding(get: { robot.armed }, set: { robot.setArmed($0) }))
                .disabled(robot.identity == nil || (robot.busy && !robot.armed)).tint(.green)
            Stepper("Walk · \(cycles) cycles", value: $cycles, in: 1...10).disabled(robot.busy)
                .font(.subheadline).monospacedDigit()
            Text("Walk pace").font(.caption).foregroundStyle(.secondary)
            Picker("Walk pace", selection: $stepMs) {
                Text("Slow").tag(120)
                Text("Normal").tag(80)
                Text("Brisk").tag(50)
            }.pickerStyle(.segmented).disabled(robot.busy)
            HStack(spacing: 10) {
                motionButton("Back", "arrow.down", "walk_back")
                motionButton("Stand", "figure.stand", "stand")
                motionButton("Forward", "arrow.up", "walk_forward")
            }
            Text("Turn angle").font(.caption).foregroundStyle(.secondary)
            Picker("Turn angle", selection: $degrees) {
                ForEach([15, 30, 45, 90], id: \.self) { Text("\($0)°").tag($0) }
            }.pickerStyle(.segmented).disabled(robot.busy)
            HStack(spacing: 10) {
                motionButton("Turn left", "arrow.uturn.left", "turn_left")
                motionButton("Turn right", "arrow.uturn.right", "turn_right")
            }
            HStack(spacing: 10) {
                motionButton("Low", "arrow.down.to.line", "crouch")
                motionButton("Head up", "arrow.up.right", "look_up")
                motionButton("Head down", "arrow.down.right", "look_down")
            }
            Text("Walks finish in stand. Turns use the robot's native angle routine. No queued motion.")
                .font(.caption2).foregroundStyle(.secondary)
            if let error = robot.error { Text(error).font(.caption).foregroundStyle(.orange) }
        }.padding(18).background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }
    private func motionButton(_ title: String, _ icon: String, _ action: String) -> some View {
        Button { robot.move(action, cycles: cycles, degrees: degrees, stepMs: stepMs) } label: {
            VStack(spacing: 6) { Image(systemName: icon).font(.title3); Text(title).font(.caption.bold()) }
                .frame(maxWidth: .infinity).padding(.vertical, 6)
        }.buttonStyle(.bordered).disabled(!robot.canPerform(action))
    }
}

private struct RobotStopBar: View {
    @ObservedObject var robot: RobotController
    var body: some View {
        if robot.identity != nil {
            Button { robot.stop() } label: {
                Label("STOP ROBOT", systemImage: "stop.fill").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 8)
            }.buttonStyle(.borderedProminent).tint(.red)
                .padding(.horizontal, 20).padding(.vertical, 10).background(.ultraThinMaterial)
        }
    }
}
