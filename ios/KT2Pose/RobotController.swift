import Combine
import Foundation
import PoseCore

private final class NoRobotRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

@MainActor final class RobotController: ObservableObject {
    @Published private(set) var status = "Join xiaogui Wi-Fi, then connect"
    @Published private(set) var identity: String?
    @Published private(set) var busy = false
    @Published private(set) var armed = false
    @Published private(set) var error: String?
    @Published private(set) var lastCommandID: String?
    @Published private(set) var motionState = "idle"
    @Published private(set) var supportedMotions = [String]()
    var onChange: (() -> Void)?
    private var lastAction: String?
    private var walkCyclesCompleted = 0
    private var walkFramesPlayed = 0
    private var walkElapsedMs = 0
    private var operation: Task<Void, Never>?
    private var stopTask: Task<Void, Never>?
    private var stopRequested = false
    private let redirect = NoRobotRedirect()
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.allowsCellularAccess = false; config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 2; config.timeoutIntervalForResource = 3
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config, delegate: redirect, delegateQueue: nil)
    }()
    var canMove: Bool { identity != nil && armed && !busy && !stopRequested && !supportedMotions.isEmpty }
    func canPerform(_ action: String) -> Bool { canMove && supportedMotions.contains(action) }
    var snapshot: [String: Any] {
        ["status": status, "identity": identity as Any? ?? NSNull(), "busy": busy, "armed": armed,
         "can_move": canMove, "can_stop": identity != nil, "error": error as Any? ?? NSNull(),
         "command_id": lastCommandID as Any? ?? NSNull(), "motion": motionState,
         "action": lastAction as Any? ?? NSNull(), "walk_cycles_completed": walkCyclesCompleted,
         "walk_frames_played": walkFramesPlayed,
         "walk_elapsed_ms": walkElapsedMs,
         "host": "192.168.4.1", "supported_motions": supportedMotions,
         "limits": ["cycles_max": 10, "degrees_min": 5, "degrees_max": 90, "step_ms_min": 50, "step_ms_max": 120]]
    }
    func setArmed(_ value: Bool) {
        if !value { if busy { stop() }; armed = false }
        else if identity != nil && !busy { armed = true; stopRequested = false }
        onChange?()
    }
    @discardableResult func connect() -> Bool {
        guard !busy else { return false }
        armed = false; identity = nil; supportedMotions = []; busy = true; error = nil; stopRequested = false
        status = "Checking 192.168.4.1…"; onChange?()
        operation = Task {
            do {
                let name = try RobotProgram.verifyIdentity(try await request("/ping"))
                guard !stopRequested else { return }
                identity = name; status = "Reading robot motion options…"; onChange?()
                let token = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                try Self.requireOK(try await request("/py", body: RobotProgram.formBody(code: try RobotProgram.capabilities(token: token))))
                let capabilities = try await readResult(prefix: "@KT2CAP:\(token):", timeout: 5)
                guard !stopRequested else { return }
                supportedMotions = RobotProgram.supported(actions: capabilities["actions"] as? [String] ?? [], methods: capabilities["q_methods"] as? [String] ?? [])
                guard !supportedMotions.isEmpty else { throw RobotError("Robot motion API is unavailable") }
                status = "Robot connected — enable motion to drive"
            } catch { if !stopRequested { status = "Robot unavailable"; self.error = error.localizedDescription } }
            if !stopRequested { busy = false; operation = nil; onChange?() }
        }
        return true
    }
    @discardableResult func move(_ action: String, id: String = UUID().uuidString, cycles: Int = 5, degrees: Int = 30, stepMs: Int = 80) -> Bool {
        guard canPerform(action), (try? MotionParameters(cycles: cycles, degrees: degrees, stepMs: stepMs)) != nil else { return false }
        busy = true; error = nil; lastCommandID = id; motionState = "submitting"
        lastAction = action; walkCyclesCompleted = 0; walkFramesPlayed = 0; walkElapsedMs = 0
        let isWalking = action == "walk_forward" || action == "walk_back"
        switch action {
        case "walk_forward", "walk_back": status = "\(cycles) \(action == "walk_forward" ? "forward" : "backward") cycles…"
        case "turn_left", "turn_right": status = "Turning \(action == "turn_left" ? "left" : "right") \(degrees)°…"
        default: status = "Moving to \(action.replacingOccurrences(of: "_", with: " "))…"
        }
        onChange?()
        operation = Task {
            do {
                _ = try RobotProgram.verifyIdentity(try await request("/ping"))
                guard !stopRequested else { return }
                let token = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                let code = try RobotProgram.motion(action: action, token: token, cycles: cycles, degrees: degrees, stepMs: stepMs)
                try Self.requireOK(try await request("/py", body: RobotProgram.formBody(code: code)))
                guard !stopRequested else { return }
                motionState = "running"; onChange?()
                let prefix = "@KT2PHONE:\(token):"
                let timeout = isWalking ? max(12, Double(cycles) * 2.5 + 5) : 12
                let deadline = ProcessInfo.processInfo.systemUptime + timeout
                var buffer = "", complete = false
                while !stopRequested && !complete {
                    try await Task.sleep(nanoseconds: 120_000_000)
                    if stopRequested { return }
                    buffer += String(decoding: try await request("/log"), as: UTF8.self)
                    guard !stopRequested else { return }
                    guard buffer.utf8.count < 65536 else { throw RobotError("Robot log overflow") }
                    while let newline = buffer.firstIndex(of: "\n") {
                        let line = String(buffer[..<newline]); buffer.removeSubrange(...newline)
                        guard line.hasPrefix(prefix), let data = line.dropFirst(prefix.count).data(using: .utf8),
                              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                        if message["kind"] as? String == "error" { throw RobotError(message["error"] as? String ?? "Robot motion failed") }
                        if message["kind"] as? String == "progress", isWalking,
                           let cycle = message["cycle"] as? Int, let frames = message["frames_played"] as? Int,
                           cycle == walkCyclesCompleted + 1, cycle <= cycles, frames > walkFramesPlayed {
                            walkCyclesCompleted = cycle; walkFramesPlayed = frames
                            walkElapsedMs = message["elapsed_ms"] as? Int ?? 0
                            status = "Walking \(action == "walk_forward" ? "forward" : "backward") — \(cycle)/\(cycles) cycles"
                            onChange?()
                        }
                        if message["kind"] as? String == "done" {
                            guard !isWalking || walkCyclesCompleted == cycles else { throw RobotError("Robot did not confirm all walking cycles") }
                            complete = true
                        }
                    }
                    if !complete && ProcessInfo.processInfo.systemUptime > deadline { throw RobotError("Motion completion was not confirmed") }
                }
                if !stopRequested {
                    motionState = "completed"
                    status = isWalking ? "Walk completed — \(cycles) \(cycles == 1 ? "cycle" : "cycles")" : "Motion completed"
                }
            } catch {
                if !stopRequested {
                    self.error = error.localizedDescription; armed = false; motionState = "unconfirmed"
                    status = "Motion failed — stopping"
                    do { try Self.requireOK(try await request("/api?p=%2Fpy%2Fvm%2Fbreak&v=null")); status = "Stop acknowledged" }
                    catch { status = "Stop unconfirmed"; self.error = "\(self.error ?? "") · \(error.localizedDescription)" }
                }
            }
            if !stopRequested { busy = false; operation = nil; onChange?() }
        }
        return true
    }
    func stop(reason: String = "Stop requested") {
        armed = false
        guard stopTask == nil else { onChange?(); return }
        stopRequested = true; busy = true; status = reason; motionState = "stopping"; onChange?()
        let previous = operation
        // Wait for any in-flight POST before VM-break, so a delayed submission
        // cannot start a walk after Stop has already been acknowledged.
        stopTask = Task {
            await previous?.value
            if identity != nil {
                do {
                    try Self.requireOK(try await request("/api?p=%2Fpy%2Fvm%2Fbreak&v=null"))
                    status = "Stop acknowledged"; motionState = "stopped"; error = nil
                } catch { status = "Stop unconfirmed"; motionState = "unconfirmed"; self.error = error.localizedDescription }
            } else { status = "Disconnected"; motionState = "idle" }
            busy = false; operation = nil; stopTask = nil; onChange?()
        }
    }
    func linkLost() { if busy || armed { stop(reason: "USB lost — stopping") } }
    private func readResult(prefix: String, timeout: Double) async throws -> [String: Any] {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        var buffer = ""
        while !stopRequested && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 120_000_000)
            if stopRequested { throw CancellationError() }
            buffer += String(decoding: try await request("/log"), as: UTF8.self)
            guard buffer.utf8.count < 65536 else { throw RobotError("Robot log overflow") }
            while let newline = buffer.firstIndex(of: "\n") {
                let line = String(buffer[..<newline]); buffer.removeSubrange(...newline)
                if line.hasPrefix(prefix), let data = line.dropFirst(prefix.count).data(using: .utf8),
                   let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { return value }
            }
        }
        throw RobotError("Robot capability check was not confirmed")
    }
    private func request(_ path: String, body: Data? = nil) async throws -> Data {
        var request = URLRequest(url: URL(string: "http://192.168.4.1" + path)!)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let body { request.httpMethod = "POST"; request.httpBody = body; request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), data.count <= 262144 else {
            throw RobotError("Robot HTTP request failed")
        }
        return data
    }
    private static func requireOK(_ data: Data) throws {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any], object["status"] as? String == "OK" else {
            throw RobotError("Robot did not acknowledge the request")
        }
    }
}
