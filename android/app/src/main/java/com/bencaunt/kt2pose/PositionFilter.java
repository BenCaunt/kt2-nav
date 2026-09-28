package com.bencaunt.kt2pose;

import org.json.JSONObject;
import java.util.Arrays;

/** Six-state constant-velocity Kalman filter; same tuning and expiry as iPhone. */
final class PositionFilter {
    private double[] state, covariance, orientation;
    private double frameTime = -1, observationTime = -1;
    private String session;
    private boolean accepted;
    void reset() { state = covariance = orientation = null; frameTime = observationTime = -1; session = null; accepted = false; }
    JSONObject update(JSONObject packet) {
        double time = packet.optDouble("frame_timestamp_s");
        if (!Double.isFinite(time) || time < 0) return null;
        String id = packet.optString("session_id");
        if (!id.equals(session)) { reset(); session = id; }
        if (time <= frameTime) return estimate();
        if (!packet.optString("camera_tracking").equals("normal")) {
            state = covariance = orientation = null; observationTime = -1; frameTime = time; accepted = false; return null;
        }
        if (time - observationTime > 1) { state = covariance = orientation = null; observationTime = -1; }
        if (state != null && frameTime >= 0) predict(time - frameTime);
        frameTime = time; accepted = false;
        JSONObject tag = packet.optJSONObject("tag");
        if (tag != null && !tag.optBoolean("pose_ambiguous", true)) {
            double[] transform = Json.doubles(tag.optJSONArray("world_from_tag"));
            double[] camera = Json.doubles(packet.optJSONArray("world_from_camera"));
            double[] point = {transform[3],transform[7],transform[11]}, ray = {point[0]-camera[3],point[1]-camera[7],point[2]-camera[11]};
            double sigma = Math.min(.04, Math.max(.006, .008 * 50 / tag.optDouble("minimum_edge_px") * (1 + tag.optDouble("reprojection_error_px"))));
            double variance = sigma*sigma, length2 = ray[0]*ray[0]+ray[1]*ray[1]+ray[2]*ray[2];
            double[] noise = new double[9];
            for (int r=0;r<3;r++) for (int c=0;c<3;c++) noise[r*3+c] = (r==c ? variance : 0) + (length2 > .0001 ? 8*variance*ray[r]*ray[c]/length2 : 0);
            if (state == null) {
                state = new double[]{point[0],point[1],point[2],0,0,0}; covariance = new double[36];
                for (int r=0;r<3;r++) for (int c=0;c<3;c++) covariance[r*6+c] = noise[r*3+c];
                for (int r=3;r<6;r++) covariance[r*6+r] = .04;
                accepted = true;
            } else accepted = correct(point, noise);
            if (accepted) { observationTime = time; orientation = transform; }
        }
        return estimate();
    }
    private void predict(double dt) {
        double[] f = PoseMath.identity(6);
        for (int i=0;i<3;i++) f[i*6+i+3] = dt;
        state = PoseMath.multiply(f, state, 6,6,1);
        covariance = PoseMath.multiply(PoseMath.multiply(f,covariance,6,6,6),PoseMath.transpose(f,6,6),6,6,6);
        for (int i=0;i<3;i++) {
            covariance[i*6+i] += .0225*dt*dt*dt/3;
            covariance[i*6+i+3] += .0225*dt*dt/2;
            covariance[(i+3)*6+i] += .0225*dt*dt/2;
            covariance[(i+3)*6+i+3] += .0225*dt;
        }
    }
    private boolean correct(double[] point, double[] noise) {
        double[] residual = new double[3], innovation = noise.clone();
        for (int r=0;r<3;r++) { residual[r] = point[r]-state[r]; for (int c=0;c<3;c++) innovation[r*3+c] += covariance[r*6+c]; }
        double[] inverse = PoseMath.inverse3(innovation), weighted = PoseMath.multiply(inverse,residual,3,3,1);
        double distance = 0; for (int i=0;i<3;i++) distance += residual[i]*weighted[i];
        if (!Double.isFinite(distance) || distance > 16.27) return false;
        double[] cross = new double[18];
        for (int r=0;r<6;r++) for (int c=0;c<3;c++) cross[r*3+c] = covariance[r*6+c];
        double[] k = PoseMath.multiply(cross,inverse,6,3,3), correction = PoseMath.multiply(k,residual,6,3,1);
        for (int i=0;i<6;i++) state[i] += correction[i];
        double[] a = PoseMath.identity(6);
        for (int r=0;r<6;r++) for (int c=0;c<3;c++) a[r*6+c] -= k[r*3+c];
        double[] p = PoseMath.multiply(PoseMath.multiply(a,covariance,6,6,6),PoseMath.transpose(a,6,6),6,6,6);
        double[] krk = PoseMath.multiply(PoseMath.multiply(k,noise,6,3,3),PoseMath.transpose(k,6,3),6,3,6);
        for (int r=0;r<6;r++) for (int c=0;c<6;c++) covariance[r*6+c] = (p[r*6+c]+p[c*6+r]+krk[r*6+c]+krk[c*6+r])/2;
        return true;
    }
    private JSONObject estimate() {
        if (state == null || observationTime < 0 || frameTime-observationTime > 1) return null;
        double[] std = new double[3], pp = new double[9], transform = orientation.clone();
        for (int i=0;i<3;i++) {
            std[i] = Math.sqrt(Math.max(0,covariance[i*6+i]));
            if (!Double.isFinite(std[i]) || std[i] > .15) return null;
            transform[i*4+3] = state[i];
            for (int j=0;j<3;j++) pp[i*3+j] = covariance[i*6+j];
        }
        return Json.obj("mode", accepted ? "filtered" : "predicted", "position_world_m", Json.array(Arrays.copyOfRange(state,0,3)),
            "velocity_world_mps", Json.array(Arrays.copyOfRange(state,3,6)), "position_std_m", Json.array(std),
            "position_covariance_m2", Json.array(pp), "world_from_tag", Json.array(transform), "observation_age_s", frameTime-observationTime);
    }
}
