package com.bencaunt.kt2pose;

import org.json.JSONObject;
import org.opencv.calib3d.Calib3d;
import org.opencv.core.*;
import org.opencv.objdetect.ArucoDetector;
import org.opencv.objdetect.DetectorParameters;
import org.opencv.objdetect.Objdetect;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

final class MarkerDetector {
    private final ArucoDetector detector;
    record Result(String status, JSONObject tag) { }
    private record Candidate(double[] transform, double error) { }
    MarkerDetector() {
        DetectorParameters parameters = new DetectorParameters();
        parameters.set_cornerRefinementMethod(Objdetect.CORNER_REFINE_SUBPIX);
        detector = new ArucoDetector(Objdetect.getPredefinedDictionary(Objdetect.DICT_4X4_50), parameters);
    }
    Result detect(byte[] pixels, int width, int height, double[] intrinsics, double[] worldCamera) {
        List<Mat> owned = new ArrayList<>(), corners = new ArrayList<>(), rotations = new ArrayList<>(), translations = new ArrayList<>();
        try {
            Mat image = own(owned,new Mat(height,width,CvType.CV_8UC1)); image.put(0,0,pixels);
            Mat ids = own(owned,new Mat()); detector.detectMarkers(image,corners,ids);
            int selected = -1;
            for (int i=0;i<ids.rows();i++) if ((int)ids.get(i,0)[0] == 0) {
                if (selected >= 0) return new Result("duplicate",null); selected = i;
            }
            if (selected < 0) return new Result("not_detected",null);
            float[] raw = new float[8]; corners.get(selected).get(0,0,raw);
            Point[] points = new Point[4]; double[] flat = new double[8]; double edge = Double.POSITIVE_INFINITY;
            for (int i=0;i<4;i++) { points[i] = new Point(raw[2*i],raw[2*i+1]); flat[2*i] = raw[2*i]; flat[2*i+1]=raw[2*i+1]; }
            for (int i=0;i<4;i++) edge = Math.min(edge,Math.hypot(points[i].x-points[(i+1)%4].x,points[i].y-points[(i+1)%4].y));
            if (edge < 24) return new Result("too_small",null);
            double h=.0125;
            MatOfPoint3f object = own(owned,new MatOfPoint3f(new Point3(-h,h,0),new Point3(h,h,0),new Point3(h,-h,0),new Point3(-h,-h,0)));
            MatOfPoint2f observed = own(owned,new MatOfPoint2f(points));
            Mat k = own(owned,Mat.eye(3,3,CvType.CV_64F));
            k.put(0,0,intrinsics[0],0,intrinsics[2],0,intrinsics[1],intrinsics[3],0,0,1);
            MatOfDouble distortion = own(owned,new MatOfDouble());
            Calib3d.solvePnPGeneric(object,observed,k,distortion,rotations,translations,false,Calib3d.SOLVEPNP_IPPE_SQUARE);
            List<Candidate> candidates = new ArrayList<>();
            for (int n=0;n<rotations.size();n++) {
                Mat r = own(owned,new Mat()); Calib3d.Rodrigues(rotations.get(n),r);
                double[] t = new double[3], rotation = new double[9]; translations.get(n).get(0,0,t); r.get(0,0,rotation);
                double[] transform = PoseMath.identity(4);
                for (int row=0;row<3;row++) { transform[row*4+3]=t[row]; for (int col=0;col<3;col++) transform[row*4+col]=rotation[row*3+col]; }
                boolean inFront = true;
                for (Point3 p : object.toArray()) if (!(rotation[6]*p.x+rotation[7]*p.y+t[2] > 0)) inFront = false;
                if (!inFront) continue;
                MatOfPoint2f projected = own(owned,new MatOfPoint2f());
                Calib3d.projectPoints(object,rotations.get(n),translations.get(n),k,distortion,projected);
                Point[] q = projected.toArray(); double sum=0;
                for (int i=0;i<4;i++) sum += Math.pow(q[i].x-points[i].x,2)+Math.pow(q[i].y-points[i].y,2);
                double error=Math.sqrt(sum/4);
                if (Double.isFinite(error)) candidates.add(new Candidate(transform,error));
            }
            candidates.sort(Comparator.comparingDouble(Candidate::error));
            if (candidates.isEmpty() || candidates.get(0).error > 2.5) return new Result("pose_failed",null);
            Candidate best=candidates.get(0); Double alternate=null; boolean ambiguous=false;
            if (candidates.size()>1) {
                Candidate other=candidates.get(1); alternate=other.error;
                double trace=0; for (int r=0;r<3;r++) for (int c=0;c<3;c++) trace += best.transform[r*4+c]*other.transform[r*4+c];
                double angle=Math.toDegrees(Math.acos(Math.max(-1,Math.min(1,(trace-1)/2))));
                ambiguous = angle > 10 && alternate-best.error < .35;
            }
            return new Result("detected",Json.obj("dictionary","DICT_4X4_50","id",0,"side_length_m",.025,
                "cv_camera_from_tag",Json.array(best.transform),"world_from_tag",Json.array(PoseMath.worldFromTag(worldCamera,best.transform)),
                "corners_px",Json.array(flat),"reprojection_error_px",best.error,"alternate_error_px",alternate,
                "minimum_edge_px",edge,"pose_ambiguous",ambiguous));
        } finally {
            for (Mat m : owned) m.release(); for (Mat m : corners) m.release();
            for (Mat m : rotations) m.release(); for (Mat m : translations) m.release();
        }
    }
    private static <T extends Mat> T own(List<Mat> list,T mat) { list.add(mat); return mat; }
}
