package com.bencaunt.kt2pose;

import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/** Same v1 protocol as iPhone; reached with adb forward tcp:8767 tcp:8767. */
final class UsbRelay implements AutoCloseable {
    private final String token;
    private final RobotController robot;
    private final Supplier<JSONObject> packet;
    private final ScheduledExecutorService watchdog = Executors.newSingleThreadScheduledExecutor();
    private volatile ServerSocket server;
    private volatile Client client;
    private volatile boolean closed;
    volatile String status = "Waiting for computer over USB";

    UsbRelay(String token, RobotController robot, Supplier<JSONObject> packet) {
        this.token = token; this.robot = robot; this.packet = packet;
    }
    void start(int port) throws Exception {
        ServerSocket listener = new ServerSocket(port, 1, InetAddress.getByName("127.0.0.1"));
        server = listener;
        thread("kt2-usb-accept", () -> {
            while (!closed) {
                try {
                    Socket socket = listener.accept();
                    synchronized (this) {
                        if (closed || client != null) { socket.close(); continue; }
                        client = new Client(socket); client.start();
                    }
                } catch (Exception e) { if (!closed) status = "USB listener: " + e.getMessage(); break; }
            }
        });
        watchdog.scheduleWithFixedDelay(() -> { Client c = client; if (c != null) c.tick(); }, 100, 200, TimeUnit.MILLISECONDS);
    }
    int port() { return server.getLocalPort(); }
    @Override public synchronized void close() {
        closed = true;
        try { if (server != null) server.close(); } catch (Exception ignored) { }
        Client c = client; if (c != null) c.disconnect();
        watchdog.shutdownNow(); status = "USB paused";
    }
    private static void thread(String name, Runnable body) {
        Thread t = new Thread(body, name); t.setDaemon(true); t.start();
    }
    private final class Client {
        final Socket socket;
        final Set<String> used = new HashSet<>();
        final ArrayDeque<String> controls = new ArrayDeque<>();
        boolean authenticated, disconnected;
        long heartbeat = Json.now();
        String lease, pending;
        Client(Socket socket) throws Exception {
            this.socket = socket; socket.setTcpNoDelay(true); socket.setSoTimeout(5000);
        }
        void start() {
            thread("kt2-usb-read", this::read);
            thread("kt2-usb-write", this::write);
        }
        synchronized void tick() {
            if (Json.now() - heartbeat > (authenticated ? 1500 : 5000)) { disconnect(); return; }
            if (authenticated && !disconnected) {
                pending = Json.obj("type", "state", "robot", robot.snapshot(), "packet", packet.get()).toString();
                notifyAll();
            }
        }
        void read() {
            try {
                InputStream input = socket.getInputStream();
                ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                int b;
                while ((b = input.read()) != -1) {
                    if (b == 10) {
                        handle(Json.parse(buffer.toString(StandardCharsets.UTF_8.name()))); buffer.reset();
                    } else { buffer.write(b); if (buffer.size() > 16384) break; }
                }
            } catch (Exception ignored) { }
            finally { disconnect(); }
        }
        void write() {
            try {
                while (true) {
                    String message;
                    synchronized (this) {
                        while (!disconnected && controls.isEmpty() && pending == null) wait();
                        if (disconnected) return;
                        if (!controls.isEmpty()) message = controls.remove();
                        else { message = pending; pending = null; }
                    }
                    socket.getOutputStream().write((message + "\n").getBytes(StandardCharsets.UTF_8));
                }
            } catch (Exception ignored) { }
            finally { disconnect(); }
        }
        synchronized void control(JSONObject message) {
            if (controls.size() >= 8) { disconnect(); return; }
            controls.add(message.toString()); notifyAll();
        }
        synchronized void handle(JSONObject message) {
            if (disconnected || closed || client != this) return;
            String type = message.optString("type");
            if (!authenticated) {
                if (!type.equals("hello") || !token.equals(message.optString("token")) || !(message.opt("version") instanceof Integer) || message.optInt("version") != 1) {
                    disconnect(); return;
                }
                authenticated = true; heartbeat = Json.now(); lease = UUID.randomUUID().toString();
                control(Json.obj("type", "ready", "version", 1, "lease", lease));
                status = "Computer connected over USB"; return;
            }
            if (type.equals("ping")) {
                heartbeat = Json.now(); lease = UUID.randomUUID().toString();
                control(Json.obj("type", "pong", "lease", lease)); return;
            }
            String id = message.optString("id"), action = message.optString("action");
            if (!type.equals("command") || !id.matches("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")) { disconnect(); return; }
            boolean accepted = false;
            String detail;
            try {
                if (!RobotProgram.ACTIONS.contains(action) && !action.equals("stop") && !action.equals("connect")) throw new IllegalArgumentException("Unsupported command");
                RobotProgram.Parameters parameters = RobotProgram.Parameters.from(message);
                if (used.contains(id) || used.size() >= 4096) throw new IllegalArgumentException("Repeated command or session limit reached");
                used.add(id);
                if (!action.equals("stop") && (!message.optString("lease").equals(lease) || Json.now() - heartbeat >= 1000))
                    throw new IllegalArgumentException("Command lease expired");
                // Runs immediately under this connection's lock; it cannot survive
                // disconnection or wait in a UI dispatch queue.
                if (action.equals("stop")) { robot.stop("USB Stop requested"); accepted = true; }
                else if (action.equals("connect")) accepted = robot.connect();
                else accepted = robot.move(action, id, parameters);
                detail = accepted ? "Accepted; watch robot motion state for completion" : "Connect robot, enable motion, and wait for the current operation";
            } catch (IllegalArgumentException e) { detail = e.getMessage(); }
            control(Json.obj("type", "command_result", "id", id, "accepted", accepted, "detail", detail));
        }
        synchronized void disconnect() {
            if (disconnected) return;
            disconnected = true;
            try { socket.close(); } catch (Exception ignored) { }
            controls.clear(); pending = null; notifyAll();
            if (authenticated) { robot.linkLost(); status = "USB disconnected — waiting for computer"; }
            // Volatile assignment after Stop ensures a replacement cannot arm
            // before the old connection has disarmed the controller.
            if (client == this) client = null;
        }
    }
}
