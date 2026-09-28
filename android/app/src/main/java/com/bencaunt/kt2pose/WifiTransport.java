package com.bencaunt.kt2pose;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/** Select Wi-Fi explicitly; Android may prefer cellular for a hotspot without internet. */
final class WifiTransport implements RobotController.Transport {
    private final ConnectivityManager connectivity;
    WifiTransport(Context context) { connectivity = context.getSystemService(ConnectivityManager.class); }
    @Override public String request(String path, String code) throws Exception {
        Network wifi = null;
        for (Network network : connectivity.getAllNetworks()) {
            NetworkCapabilities caps = connectivity.getNetworkCapabilities(network);
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                && !caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) { wifi = network; break; }
        }
        if (wifi == null) throw new IllegalStateException("Join xiaogui Wi-Fi and choose to stay connected without internet");
        HttpURLConnection connection = (HttpURLConnection) wifi.openConnection(new URL("http://192.168.4.1" + path), Proxy.NO_PROXY);
        connection.setConnectTimeout(2000); connection.setReadTimeout(2000);
        connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
        long deadline = Json.now() + 3500;
        try {
            if (code != null) {
                byte[] body = ("code=" + URLEncoder.encode(code, StandardCharsets.UTF_8.name())).getBytes(StandardCharsets.UTF_8);
                connection.setRequestMethod("POST"); connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                connection.setFixedLengthStreamingMode(body.length);
                try (var out = connection.getOutputStream()) { out.write(body); }
            }
            int response = connection.getResponseCode();
            if (response != 200) throw new IllegalStateException("Robot HTTP " + response);
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] chunk = new byte[4096]; int count;
                while ((count = input.read(chunk)) != -1) {
                    if (output.size() + count > 65536 || Json.now() > deadline) throw new IllegalStateException("Robot response exceeded limit");
                    output.write(chunk, 0, count);
                }
                return output.toString(StandardCharsets.UTF_8.name());
            }
        } finally { connection.disconnect(); }
    }
}
