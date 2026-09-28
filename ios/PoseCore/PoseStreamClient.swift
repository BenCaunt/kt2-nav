import Foundation

/// One send in flight, one replaceable pending observation, no offline replay.
public final class PoseStreamClient {
    public var onStatus: ((String, Bool) -> Void)?
    private let queue = DispatchQueue(label: "kt2.websocket")
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var destination: URL?
    private var token = ""
    private var generation = UUID()
    private var desired = false
    private var ready = false
    private var sending = false
    private var sendID = UUID()
    private var pending: (text: String, time: TimeInterval)?

    public init() {}

    public func connect(url: URL, token: String) {
        queue.async {
            self.cancel()
            self.destination = url
            self.token = token
            self.desired = true
            self.open()
        }
    }
    public func disconnect() {
        queue.async {
            self.desired = false
            self.cancel()
            self.onStatus?("Disconnected", false)
        }
    }
    public func submit(_ packet: PosePacket) {
        guard let data = try? packet.json(), let text = String(data: data, encoding: .utf8) else { return }
        queue.async {
            guard self.ready else { return }
            self.pending = (text, ProcessInfo.processInfo.systemUptime)
            self.drain()
        }
    }
    private func cancel() {
        generation = UUID()
        socket?.cancel(with: .goingAway, reason: nil)
        session?.invalidateAndCancel()
        socket = nil; session = nil; ready = false; sending = false; pending = nil
    }
    private func open() {
        guard desired, let destination else { return }
        let epoch = generation
        onStatus?("Connecting…", false)
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 4
        config.waitsForConnectivity = false
        config.allowsCellularAccess = false
        let session = URLSession(configuration: config)
        self.session = session
        var request = URLRequest(url: destination)
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let socket = session.webSocketTask(with: request)
        self.socket = socket
        socket.resume()
        receive(socket, epoch: epoch)
        queue.asyncAfter(deadline: .now() + 5) {
            if self.generation == epoch && !self.ready { self.reconnect("Could not connect. Check Wi-Fi, address and pairing code.") }
        }
    }
    private func receive(_ socket: URLSessionWebSocketTask, epoch: UUID) {
        socket.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                guard self.generation == epoch else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message,
                       let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       json["type"] as? String == "ready", json["schema_version"] as? Int == 1 {
                        self.ready = true
                        self.onStatus?("Connected", true)
                    }
                    self.receive(socket, epoch: epoch)
                case .failure:
                    self.reconnect("Connection lost. Check Wi-Fi, address and pairing code; retrying…")
                }
            }
        }
    }
    private func drain() {
        guard ready, !sending, let socket, let observation = pending else { return }
        pending = nil
        guard ProcessInfo.processInfo.systemUptime - observation.time < 0.25 else { return }
        sending = true
        let epoch = generation
        let identifier = UUID()
        sendID = identifier
        socket.send(.string(observation.text)) { [weak self] error in
            guard let self else { return }
            self.queue.async {
                guard epoch == self.generation, identifier == self.sendID else { return }
                self.sending = false
                if error != nil { self.reconnect("Send failed; reconnecting…") }
                else { self.drain() }
            }
        }
        queue.asyncAfter(deadline: .now() + 1) {
            if self.generation == epoch && self.sendID == identifier && self.sending {
                self.reconnect("Stream stalled; reconnecting…")
            }
        }
    }
    private func reconnect(_ message: String) {
        cancel()
        guard desired else { return }
        onStatus?(message, false)
        let epoch = generation
        queue.asyncAfter(deadline: .now() + 1) {
            if self.desired && self.generation == epoch { self.open() }
        }
    }
}
