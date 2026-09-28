package com.bencaunt.kt2pose;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class Json {
    private Json() {}
    static JSONObject obj(Object... entries) {
        JSONObject result = new JSONObject();
        try {
            for (int i = 0; i < entries.length; i += 2)
                result.put((String) entries[i], entries[i + 1] == null ? JSONObject.NULL : entries[i + 1]);
        } catch (JSONException e) { throw new IllegalArgumentException(e); }
        return result;
    }
    static JSONArray array(double[] values) {
        JSONArray result = new JSONArray();
        try { for (double value : values) result.put(value); }
        catch (JSONException e) { throw new IllegalArgumentException(e); }
        return result;
    }
    static double[] doubles(JSONArray a) {
        double[] result = new double[a.length()];
        for (int i = 0; i < result.length; i++) result[i] = a.optDouble(i);
        return result;
    }
    static JSONObject parse(String text) throws JSONException { return new JSONObject(text); }
    static long now() { return System.nanoTime() / 1_000_000; }
}
