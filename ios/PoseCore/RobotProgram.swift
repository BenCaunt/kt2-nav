import Foundation

public enum RobotProgram {
    public static let actions = ["walk_forward", "walk_back", "turn_left", "turn_right", "stand", "crouch", "look_up", "look_down"]
    public static func verifyIdentity(_ data: Data) throws -> String {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw RobotError("Invalid robot identity") }
        let label = "\(object["model"] ?? "") \(object["v"] ?? "")"
        let full = label + " \(object["ver"] ?? "")"
        guard object["simulation"] as? Bool != true, !full.uppercased().contains("SIM"),
              label.uppercased().range(of: #"(?<![A-Z0-9])B4KT2(?![A-Z0-9])"#, options: .regularExpression) != nil,
              object["status"] as? String ?? "OK" == "OK" else { throw RobotError("Endpoint is not the physical B4KT2") }
        return label.trimmingCharacters(in: .whitespaces)
    }
    public static func capabilities(token: String) throws -> String {
        guard token.range(of: #"^[0-9a-f]{32}$"#, options: .regularExpression) != nil else { throw RobotError("Invalid probe token") }
        return """
        import actions
        try:
            import ujson as json
        except ImportError:
            import json
        print('@KT2CAP:\(token):' + json.dumps({'actions': dir(actions), 'q_methods': dir(q)}))

        """
    }
    public static func supported(actions: [String], methods: [String]) -> [String] {
        guard methods.contains("play"), methods.contains("frame") else { return [] }
        var result = ["stand"]
        if actions.contains("walk") { result += ["walk_forward", "walk_back"] }
        if actions.contains("c_pivot") { result += ["turn_left", "turn_right"] }
        if actions.contains("ofs_stand_low") { result.append("crouch") }
        if actions.contains("ofs_head_up") { result.append("look_up") }
        if actions.contains("ofs_head_down") { result.append("look_down") }
        return result
    }
    public static func motion(action: String, token: String, cycles: Int = 1, degrees: Int = 30, stepMs: Int = 80) throws -> String {
        _ = try MotionParameters(cycles: cycles, degrees: degrees, stepMs: stepMs)
        guard actions.contains(action), token.range(of: #"^[0-9a-f]{32}$"#, options: .regularExpression) != nil else {
            throw RobotError("Unsupported motion")
        }
        let gait = action == "walk_back" ? "actions.walk(q, x=-1)" : "actions.walk(q)"
        let body: String
        switch action {
        case "walk_forward", "walk_back":
            // Use the frame-at-a-time path verified on this robot. Recreate the
            // native gait each cycle so one-shot iterators are not reused.
            body = """
                    import time
                    walk_started = time.ticks_ms()
                    frames_played = 0
                    for cycle in range(\(cycles)):
                        cycle_frames = 0
                        for frame in \(gait):
                            frame_started = time.ticks_ms()
                            q.play(frame)
                            remaining_ms = \(stepMs) - time.ticks_diff(time.ticks_ms(), frame_started)
                            if remaining_ms > 0:
                                time.sleep_ms(remaining_ms)
                            cycle_frames += 1
                            frames_played += 1
                        if cycle_frames == 0:
                            raise ValueError('Robot returned an empty walking gait')
                        print(prefix + json.dumps({'kind': 'progress', 'cycle': cycle + 1, 'frames_played': frames_played, 'elapsed_ms': time.ticks_diff(time.ticks_ms(), walk_started)}))
                    q.play(q.frame(-75, -75, 75, 75, 0.3))
            """
        case "turn_left", "turn_right":
            body = """
                    actions.c_pivot(q, \(action == "turn_left" ? degrees : -degrees))
                    q.play(q.frame(-75, -75, 75, 75, 0.3))
            """
        case "crouch", "look_up", "look_down":
            let offset = ["crouch":"ofs_stand_low", "look_up":"ofs_head_up", "look_down":"ofs_head_down"][action]!
            body = "        q.play(q.frame(0, 0, 0, 0, 0.4, ofs=actions.\(offset)))"
        default: body = "        q.play(q.frame(-75, -75, 75, 75, 0.3))"
        }
        return """
        def _kt2_phone_\(token)():
            import actions
            try:
                import ujson as json
            except ImportError:
                import json
            prefix = '@KT2PHONE:\(token):'
            print(prefix + json.dumps({'kind': 'start'}))
            try:
        \(body)
            except Exception as exc:
                print(prefix + json.dumps({'kind': 'error', 'error': str(exc)}))
            else:
                print(prefix + json.dumps({'kind': 'done'}))
        try:
            _kt2_phone_\(token)()
        finally:
            del _kt2_phone_\(token)

        """
    }
    public static func formBody(code: String) -> Data {
        let unreserved = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
        return Data(("code=" + code.addingPercentEncoding(withAllowedCharacters: unreserved)!).utf8)
    }
}

public struct MotionParameters: Decodable {
    public let cycles: Int
    public let degrees: Int
    public let stepMs: Int
    public init(cycles: Int = 1, degrees: Int = 30, stepMs: Int = 80) throws {
        guard (1...10).contains(cycles), (5...90).contains(degrees) else { throw RobotError("Use 1–10 walking cycles and a 5–90° turn") }
        guard (50...120).contains(stepMs) else { throw RobotError("Walking frame interval must be 50–120 ms") }
        self.cycles = cycles; self.degrees = degrees; self.stepMs = stepMs
    }
    private enum CodingKeys: String, CodingKey { case cycles, degrees; case stepMs = "step_ms" }
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(cycles: values.decodeIfPresent(Int.self, forKey: .cycles) ?? 1,
                      degrees: values.decodeIfPresent(Int.self, forKey: .degrees) ?? 30,
                      stepMs: values.decodeIfPresent(Int.self, forKey: .stepMs) ?? 80)
    }
}

public struct RobotError: LocalizedError {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}
