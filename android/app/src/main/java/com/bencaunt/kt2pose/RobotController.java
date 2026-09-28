package com.bencaunt.kt2pose;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** One operation at a time. Stop is serialized after any in-flight submission. */
final class RobotController {
    interface Transport { String request(String path, String code) throws Exception; }
    private final Transport transport;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private boolean busy, armed, stopping, foreground;
    private String identity, error, commandId, action;
    private String status = "Join xiaogui Wi-Fi, then connect", motion = "idle";
    private List<String> supported = List.of();
    private int cyclesCompleted, framesPlayed, elapsedMs;

    RobotController(Transport transport) { this.transport = transport; }
    synchronized JSONObject snapshot() {
        return Json.obj("status", status, "identity", identity, "busy", busy, "armed", armed,
            "can_move", canMove(), "can_stop", identity != null, "error", error,
            "command_id", commandId, "motion", motion, "action", action, "host", "192.168.4.1",
            "walk_cycles_completed", cyclesCompleted, "walk_frames_played", framesPlayed, "walk_elapsed_ms", elapsedMs,
            "supported_motions", new JSONArray(supported), "limits", Json.obj("cycles_max", 10, "degrees_min", 5,
                "degrees_max", 90, "step_ms_min", 50, "step_ms_max", 120));
    }
    synchronized boolean canMove() { return foreground && identity != null && armed && !busy && !stopping && !supported.isEmpty(); }
    synchronized void foreground(boolean value) {
        foreground = value;
        if (!value) { if (busy || armed) stop("App paused — stopping"); armed = false; }
    }
    synchronized void arm(boolean value) {
        if (!value) { armed = false; if (busy) stop("Disarmed — stopping"); }
        else if (foreground && identity != null && !busy && !stopping && !supported.isEmpty()) armed = true;
    }
    synchronized boolean connect() {
        if (!foreground || busy || stopping) return false;
        busy = true; armed = false; identity = null; error = null; supported = List.of(); status = "Checking robot…";
        worker.execute(() -> {
            try {
                String label = RobotProgram.identity(transport.request("/ping", null));
                synchronized (this) { if (stopping) return; identity = label; }
                String token = token();
                synchronized (this) { if (stopping) return; }
                requireOK(transport.request("/py", RobotProgram.capabilities(token)));
                JSONObject cap = readCapability("@KT2CAP:" + token + ":");
                synchronized (this) {
                    if (stopping) return;
                    supported = RobotProgram.supported(cap);
                    if (supported.isEmpty()) throw new IllegalStateException("Motion API unavailable on this firmware");
                    status = "Connected — enable motion to drive";
                }
            } catch (Exception e) { synchronized (this) { if (!stopping) { status = "Robot unavailable"; error = describe(e); } } }
            finally { synchronized (this) { if (!stopping) busy = false; } }
        });
        return true;
    }
    synchronized boolean move(String requestedAction, String id, RobotProgram.Parameters parameters) {
        if (!canMove() || !supported.contains(requestedAction)) return false;
        busy = true; error = null; action = requestedAction; commandId = id;
        motion = "submitting"; status = "Sending " + action.replace('_', ' ') + "…";
        cyclesCompleted = framesPlayed = elapsedMs = 0;
        worker.execute(() -> runMotion(requestedAction, parameters));
        return true;
    }
    private void runMotion(String action, RobotProgram.Parameters p) {
        try {
            RobotProgram.identity(transport.request("/ping", null));
            synchronized (this) { if (stopping) return; }
            String token = token();
            requireOK(transport.request("/py", RobotProgram.motion(action, token, p)));
            synchronized (this) { if (stopping) return; motion = "running"; status = "Running " + action.replace('_', ' '); }
            boolean walking = action.startsWith("walk_");
            long deadline = Json.now() + (walking ? Math.max(12000, p.cycles() * 2500L + 5000) : 12000);
            String prefix = "@KT2PHONE:" + token + ":";
            StringBuilder buffer = new StringBuilder();
            while (!isStopping() && Json.now() < deadline) {
                Thread.sleep(120);
                if (isStopping()) return;
                buffer.append(transport.request("/log", null));
                checkBuffer(buffer);
                int newline;
                while ((newline = buffer.indexOf("\n")) >= 0) {
                    String line = buffer.substring(0, newline); buffer.delete(0, newline + 1);
                    if (!line.startsWith(prefix)) continue;
                    JSONObject message = Json.parse(line.substring(prefix.length()));
                    synchronized (this) {
                        if (stopping) return;
                        String kind = message.optString("kind");
                        if (kind.equals("error")) throw new IllegalStateException(message.optString("error", "Robot motion failed"));
                        if (kind.equals("progress") && walking && message.optInt("cycle") == cyclesCompleted + 1
                            && message.optInt("cycle") <= p.cycles() && message.optInt("frames_played") > framesPlayed) {
                            cyclesCompleted++; framesPlayed = message.optInt("frames_played"); elapsedMs = message.optInt("elapsed_ms");
                            status = "Walking — " + cyclesCompleted + "/" + p.cycles() + " cycles";
                        }
                        if (kind.equals("done")) {
                            if (walking && cyclesCompleted != p.cycles()) throw new IllegalStateException("Robot did not confirm every walking cycle");
                            motion = "completed"; status = "Motion completed"; return;
                        }
                    }
                }
            }
            if (!isStopping()) throw new IllegalStateException("Motion completion was not confirmed");
        } catch (Exception e) {
            synchronized (this) {
                if (stopping) return;
                armed = false; motion = "unconfirmed"; error = describe(e); status = "Motion failed — stopping";
            }
            try {
                requireOK(transport.request("/api?p=%2Fpy%2Fvm%2Fbreak&v=null", null));
                synchronized (this) { status = "Stop acknowledged after motion error"; }
            } catch (Exception stopError) {
                synchronized (this) { status = "Stop unconfirmed"; error += " · " + describe(stopError); }
            }
        } finally { synchronized (this) { if (!stopping) busy = false; } }
    }
    synchronized void stop(String reason) {
        armed = false;
        if (stopping) return;
        stopping = true; busy = true; motion = "stopping"; status = reason;
        // Do not cancel the worker: HTTP POST may already be in flight. Break
        // follows that request, so an acknowledged Stop cannot precede a late POST.
        worker.execute(() -> {
            try {
                boolean known; synchronized (this) { known = identity != null; }
                if (known) requireOK(transport.request("/api?p=%2Fpy%2Fvm%2Fbreak&v=null", null));
                synchronized (this) { motion = known ? "stopped" : "idle"; status = known ? "Stop acknowledged" : "Disconnected"; error = null; }
            } catch (Exception e) { synchronized (this) { motion = "unconfirmed"; status = "Stop unconfirmed"; error = describe(e); } }
            finally { synchronized (this) { stopping = false; busy = false; } }
        });
    }
    synchronized void linkLost() { if (busy || armed) stop("USB lost — stopping"); }
    synchronized void close() { foreground(false); worker.shutdown(); }
    private synchronized boolean isStopping() { return stopping; }
    private JSONObject readCapability(String prefix) throws Exception {
        long deadline = Json.now() + 5000;
        StringBuilder buffer = new StringBuilder();
        while (!isStopping() && Json.now() < deadline) {
            Thread.sleep(120);
            if (isStopping()) break;
            buffer.append(transport.request("/log", null)); checkBuffer(buffer);
            int newline;
            while ((newline = buffer.indexOf("\n")) >= 0) {
                String line = buffer.substring(0, newline); buffer.delete(0, newline + 1);
                if (line.startsWith(prefix)) return Json.parse(line.substring(prefix.length()));
            }
        }
        throw new IllegalStateException("Capability check was not confirmed");
    }
    static String token() { return UUID.randomUUID().toString().replace("-", ""); }
    static void requireOK(String text) throws Exception {
        JSONObject response = Json.parse(text);
        if (!response.optString("status").equals("OK")) throw new IllegalStateException("Robot rejected request: " + text);
    }
    private static void checkBuffer(StringBuilder buffer) {
        if (buffer.length() > 65536) throw new IllegalStateException("Robot log overflow");
    }
    private static String describe(Exception e) { return e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(); }
}
