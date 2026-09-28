import Foundation
import Network

/// A loopback TCP listener reached through Apple's USB multiplexing service.
/// Newline JSON; one authenticated client, one replaceable observation, no replay.
public final class USBRelayServer {
    public var onStatus: ((String, Bool) -> Void)?
    public var onCommand: ((String, String, MotionParameters, @escaping () -> Bool, @escaping (Bool, String) -> Void) -> Void)?
    public var onDisconnect: (() -> Void)?
    private let queue = DispatchQueue(label: "kt2.usb-relay")
    private let queueKey = DispatchSpecificKey<Bool>()
    private var listener: NWListener?
    private var connection: NWConnection?
    private var timer: DispatchSourceTimer?
    private var token = ""
    private var buffer = Data()
    private var authenticated = false
    private var lastHeartbeat = 0.0
    private var lease = ""
    private var usedIDs = Set<String>()
    private var pending: Data?
    private var sending = false
    private var controls = [Data]()

    public init() { queue.setSpecific(key: queueKey, value: true) }
    public func start(token: String, port: UInt16 = 8767) {
        queue.async {
            guard self.listener == nil else { return }
            self.token = token
            do {
                let parameters = NWParameters.tcp
                parameters.allowLocalEndpointReuse = true
                parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!)
                let listener = try NWListener(using: parameters)
                self.listener = listener
                listener.stateUpdateHandler = { [weak self = self] state in
                    guard let self else { return }
                    switch state {
                    case .ready: self.onStatus?("Waiting for Mac over USB", false)
                    case .failed(let error):
                        self.onStatus?("USB listener: \(error.localizedDescription)", false)
                        self.closeClient(); self.listener?.cancel(); self.listener = nil
                    default: break
                    }
                }
                listener.newConnectionHandler = { [weak self = self] client in self?.accept(client) }
                listener.start(queue: self.queue)
                let timer = DispatchSource.makeTimerSource(queue: self.queue)
                timer.schedule(deadline: .now()+0.5, repeating: 0.25)
                timer.setEventHandler { [weak self = self] in
                    guard let self, self.connection != nil else { return }
                    if self.now - self.lastHeartbeat > (self.authenticated ? 1.5 : 5) { self.closeClient() }
                }
                self.timer?.cancel(); self.timer = timer; timer.resume()
            } catch { self.onStatus?("USB listener: \(error.localizedDescription)", false) }
        }
    }
    public func stop() {
        queue.async {
            self.closeClient(); self.listener?.cancel(); self.listener = nil
            self.timer?.cancel(); self.timer = nil
            self.onStatus?("USB paused", false)
        }
    }
    public func publish(packet: PosePacket?, robot: [String: Any]) {
        queue.async {
            guard self.authenticated else { return }
            var message: [String: Any] = ["type": "state", "robot": robot]
            if let packet, let data = try? packet.json(), let value = try? JSONSerialization.jsonObject(with: data) {
                message["packet"] = value
            }
            self.pending = Self.encode(message)
            self.flush()
        }
    }
    private var now: Double { ProcessInfo.processInfo.systemUptime }
    private static func encode(_ message: [String: Any]) -> Data? {
        guard var data = try? JSONSerialization.data(withJSONObject: message, options: [.sortedKeys]) else { return nil }
        data.append(10); return data
    }
    private func control(_ message: [String: Any]) {
        guard let data = Self.encode(message) else { return }
        guard controls.count < 8 else { closeClient(); return }
        controls.append(data); flush()
    }
    private func flush() {
        guard let connection, !sending else { return }
        let data: Data
        if !controls.isEmpty { data = controls.removeFirst() }
        else if let value = pending { data = value; pending = nil }
        else { return }
        sending = true
        connection.send(content: data, completion: .contentProcessed { [weak self, weak connection] error in
            guard let self, let connection, self.connection === connection else { return }
            self.sending = false
            if error != nil { self.closeClient() } else { self.flush() }
        })
    }
    private func accept(_ client: NWConnection) {
        guard connection == nil else { client.cancel(); return }
        connection = client; authenticated = false; buffer.removeAll(); lastHeartbeat = now
        client.stateUpdateHandler = { [weak self, weak client] state in
            guard let self, let client, self.connection === client else { return }
            switch state {
            case .ready: self.receive(client)
            case .failed, .cancelled: self.closeClient()
            default: break
            }
        }
        client.start(queue: queue)
    }
    private func receive(_ client: NWConnection) {
        client.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self, weak client] data, _, complete, error in
            guard let self, let client, self.connection === client else { return }
            if let data { self.buffer.append(data) }
            guard self.buffer.count <= 16384 else { self.closeClient(); return }
            while let end = self.buffer.firstIndex(of: 10) {
                let line = self.buffer.prefix(upTo: end)
                self.buffer.removeSubrange(...end)
                guard let message = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else {
                    self.closeClient(); return
                }
                self.handle(message, client: client)
                if self.connection !== client { return }
            }
            if complete || error != nil { self.closeClient() } else { self.receive(client) }
        }
    }
    private func handle(_ message: [String: Any], client: NWConnection) {
        let type = message["type"] as? String
        if !authenticated {
            guard type == "hello", message["token"] as? String == token,
                  message["version"] as? Int == 1 else { closeClient(); return }
            authenticated = true; lastHeartbeat = now; lease = UUID().uuidString; usedIDs.removeAll()
            control(["type": "ready", "version": 1, "lease": lease])
            onStatus?("Mac connected over USB", true)
            return
        }
        if type == "ping" {
            lastHeartbeat = now; lease = UUID().uuidString
            control(["type": "pong", "lease": lease]); return
        }
        guard type == "command", let id = message["id"] as? String,
              UUID(uuidString: id) != nil, let action = message["action"] as? String else { closeClient(); return }
        let result: (Bool, String) -> Void = { [weak self, weak client] ok, detail in
            guard let self else { return }
            self.queue.async {
                guard let client, self.connection === client else { return }
                self.control(["type": "command_result", "id": id, "accepted": ok, "detail": detail])
            }
        }
        guard (RobotProgram.actions + ["stop", "connect"]).contains(action) else {
            result(false, "Unsupported command"); return
        }
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let parameters = try? JSONDecoder().decode(MotionParameters.self, from: data) else {
            result(false, "Use integer cycles 1–10, degrees 5–90, and step_ms 50–120"); return
        }
        guard !usedIDs.contains(id), usedIDs.count < 4096 else { result(false, "Repeated command or session limit reached"); return }
        usedIDs.insert(id)
        guard action == "stop" || (message["lease"] as? String == lease && now-lastHeartbeat < 1.0) else {
            result(false, "Command lease expired; request again"); return
        }
        guard let onCommand else { result(false, "Robot control unavailable"); return }
        let received = now
        // Recheck at the consumer, after its hop to the main thread. A command
        // must not outlive its connection or sit waiting behind a blocked UI.
        let canExecute: () -> Bool = { [weak self, weak client] in
            guard let self, let client else { return false }
            let check = { self.connection === client && self.authenticated && self.now - received < 0.5 }
            if DispatchQueue.getSpecific(key: self.queueKey) != nil { return check() }
            return self.queue.sync(execute: check)
        }
        onCommand(id, action, parameters, canExecute, result)
    }
    private func closeClient() {
        let wasAuthenticated = authenticated
        let old = connection; connection = nil
        authenticated = false; pending = nil; controls.removeAll(); buffer.removeAll(); sending = false
        old?.cancel()
        if wasAuthenticated { onStatus?("USB disconnected — waiting for Mac", false); onDisconnect?() }
    }
}
