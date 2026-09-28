package com.bencaunt.kt2pose;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

final class RobotProgram {
    static final List<String> ACTIONS = List.of("walk_forward", "walk_back", "turn_left", "turn_right", "stand", "crouch", "look_up", "look_down");
    private static final Pattern MODEL = Pattern.compile("(?<![A-Z0-9])B4KT2(?![A-Z0-9])");
    record Parameters(int cycles, int degrees, int stepMs) {
        Parameters {
            if (cycles < 1 || cycles > 10 || degrees < 5 || degrees > 90 || stepMs < 50 || stepMs > 120)
                throw new IllegalArgumentException("Use 1–10 cycles, 5–90 degrees, and 50–120 ms pace");
        }
        static Parameters from(JSONObject o) {
            return new Parameters(integer(o, "cycles", 1), integer(o, "degrees", 30), integer(o, "step_ms", 80));
        }
        private static int integer(JSONObject o, String key, int fallback) {
            if (!o.has(key)) return fallback;
            Object value = o.opt(key);
            if (!(value instanceof Integer)) throw new IllegalArgumentException("Integer required: " + key);
            return (Integer) value;
        }
    }
    static String identity(String text) throws Exception {
        JSONObject o = Json.parse(text);
        String label = (o.optString("model", "") + " " + o.optString("v", "")).trim();
        if (o.optBoolean("simulation") || (label + o.optString("ver")).toUpperCase(java.util.Locale.ROOT).contains("SIM")
            || !MODEL.matcher(label.toUpperCase(java.util.Locale.ROOT)).find() || !o.optString("status", "OK").equals("OK"))
            throw new IllegalArgumentException("Endpoint is not the physical B4KT2");
        return label;
    }
    static void token(String token) {
        if (!token.matches("[0-9a-f]{32}")) throw new IllegalArgumentException("Invalid program token");
    }
    static String capabilities(String token) {
        token(token);
        return "import actions\ntry:\n    import ujson as json\nexcept ImportError:\n    import json\n"
            + "print('@KT2CAP:" + token + ":' + json.dumps({'actions': dir(actions), 'q_methods': dir(q)}))\n";
    }
    static List<String> supported(JSONObject capabilities) {
        List<String> result = new ArrayList<>();
        JSONArray methods = capabilities.optJSONArray("q_methods"), actions = capabilities.optJSONArray("actions");
        if (!contains(methods, "play") || !contains(methods, "frame")) return result;
        result.add("stand");
        if (contains(actions, "walk")) result.addAll(List.of("walk_forward", "walk_back"));
        if (contains(actions, "c_pivot")) result.addAll(List.of("turn_left", "turn_right"));
        if (contains(actions, "ofs_stand_low")) result.add("crouch");
        if (contains(actions, "ofs_head_up")) result.add("look_up");
        if (contains(actions, "ofs_head_down")) result.add("look_down");
        return result;
    }
    private static boolean contains(JSONArray a, String text) {
        if (a != null) for (int i = 0; i < a.length(); i++) if (text.equals(a.optString(i))) return true;
        return false;
    }
    static String motion(String action, String token, Parameters p) {
        token(token);
        if (!ACTIONS.contains(action)) throw new IllegalArgumentException("Unsupported motion");
        String body;
        if (action.startsWith("walk_")) {
            body = "import time\nwalk_started = time.ticks_ms()\nframes_played = 0\nfor cycle in range(" + p.cycles + "):\n"
                + "    cycle_frames = 0\n    for frame in actions.walk(q" + (action.equals("walk_back") ? ", x=-1" : "") + "):\n"
                + "        frame_started = time.ticks_ms()\n        q.play(frame)\n"
                + "        remaining_ms = " + p.stepMs + " - time.ticks_diff(time.ticks_ms(), frame_started)\n"
                + "        if remaining_ms > 0:\n            time.sleep_ms(remaining_ms)\n"
                + "        cycle_frames += 1\n        frames_played += 1\n"
                + "    if cycle_frames == 0:\n        raise ValueError('Robot returned an empty walking gait')\n"
                + "    print(prefix + json.dumps({'kind': 'progress', 'cycle': cycle + 1, 'frames_played': frames_played, 'elapsed_ms': time.ticks_diff(time.ticks_ms(), walk_started)}))\n"
                + "q.play(q.frame(-75, -75, 75, 75, 0.3))";
        } else if (action.startsWith("turn_")) {
            body = "actions.c_pivot(q, " + (action.equals("turn_left") ? p.degrees : -p.degrees) + ")\nq.play(q.frame(-75, -75, 75, 75, 0.3))";
        } else if (action.equals("stand")) body = "q.play(q.frame(-75, -75, 75, 75, 0.3))";
        else {
            String offset = switch (action) { case "crouch" -> "ofs_stand_low"; case "look_up" -> "ofs_head_up"; default -> "ofs_head_down"; };
            body = "q.play(q.frame(0, 0, 0, 0, 0.4, ofs=actions." + offset + "))";
        }
        return "def _kt2_phone_" + token + "():\n    import actions\n    try:\n        import ujson as json\n    except ImportError:\n        import json\n"
            + "    prefix = '@KT2PHONE:" + token + ":'\n    print(prefix + json.dumps({'kind': 'start'}))\n    try:\n"
            + "        " + body.replace("\n", "\n        ") + "\n"
            + "    except Exception as exc:\n        print(prefix + json.dumps({'kind': 'error', 'error': str(exc)}))\n"
            + "    else:\n        print(prefix + json.dumps({'kind': 'done'}))\n"
            + "try:\n    _kt2_phone_" + token + "()\nfinally:\n    del _kt2_phone_" + token + "\n";
    }
}
