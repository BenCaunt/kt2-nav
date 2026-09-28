package com.bencaunt.kt2pose;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import org.opencv.android.OpenCVLoader;
import org.opencv.core.*;
import org.opencv.calib3d.Calib3d;
import org.opencv.imgproc.Imgproc;
import org.opencv.objdetect.Objdetect;
import java.nio.ByteBuffer;

/** Executes the actual packaged arm64 OpenCV library on Android, without a camera. */
@RunWith(AndroidJUnit4.class)
public class NativeVisionTest {
    @Before public void loadNativeLibrary(){assertTrue(OpenCVLoader.initLocal());}
    private static byte[] bytes(Mat m){byte[] b=new byte[(int)m.total()];m.get(0,0,b);return b;}
    @Test public void recoversKnownPerspectivePoseWithCorrectWorldAxes() throws Exception {
        Mat marker=new Mat(),scene=new Mat(),k=Mat.eye(3,3,CvType.CV_64F),rotation=new Mat(3,1,CvType.CV_64F),translation=new Mat(3,1,CvType.CV_64F);
        MatOfPoint3f object=new MatOfPoint3f(new Point3(-.0125,.0125,0),new Point3(.0125,.0125,0),new Point3(.0125,-.0125,0),new Point3(-.0125,-.0125,0));
        MatOfPoint2f projected=new MatOfPoint2f(),source=new MatOfPoint2f(new Point(0,0),new Point(199,0),new Point(199,199),new Point(0,199));MatOfDouble distortion=new MatOfDouble();Mat homography=null;
        try {
            Objdetect.generateImageMarker(Objdetect.getPredefinedDictionary(Objdetect.DICT_4X4_50),0,200,marker);
            k.put(0,0,900,0,320,0,900,240,0,0,1);
            // Tag normal toward the camera, with enough tilt to resolve planar ambiguity.
            rotation.put(0,0,2.7,.15,.1);translation.put(0,0,.015,.008,.26);
            Calib3d.projectPoints(object,rotation,translation,k,distortion,projected);
            homography=Imgproc.getPerspectiveTransform(source,projected);
            Imgproc.warpPerspective(marker,scene,homography,new Size(640,480),Imgproc.INTER_LINEAR,Core.BORDER_CONSTANT,new Scalar(255));
            MarkerDetector.Result result=new MarkerDetector().detect(bytes(scene),640,480,new double[]{900,900,320,240},PoseMath.identity(4));
            assertEquals("detected",result.status());assertNotNull(result.tag());
            double[] cv=Json.doubles(result.tag().getJSONArray("cv_camera_from_tag")),world=Json.doubles(result.tag().getJSONArray("world_from_tag"));
            assertEquals(.26,cv[11],.006);assertEquals(.015,cv[3],.002);assertEquals(.008,cv[7],.002);
            assertEquals(-cv[7],world[7],1e-9);assertEquals(-cv[11],world[11],1e-9);
            assertTrue(result.tag().getDouble("reprojection_error_px")<1);
            var context=androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().getTargetContext();
            try(var out=context.openFileOutput("native-tag.json",0)){out.write(result.tag().toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        }finally{marker.release();scene.release();k.release();rotation.release();translation.release();object.release();projected.release();source.release();distortion.release();if(homography!=null)homography.release();}
    }
    @Test public void duplicateSmallAndMissingMarkersAreRejected() {
        Mat marker=new Mat(),scene=new Mat(480,640,CvType.CV_8UC1,new Scalar(255));
        try {
            MarkerDetector detector=new MarkerDetector();double[] k={600,600,320,240};
            assertEquals("not_detected",detector.detect(bytes(scene),640,480,k,PoseMath.identity(4)).status());
            Objdetect.generateImageMarker(Objdetect.getPredefinedDictionary(Objdetect.DICT_4X4_50),0,100,marker);
            Mat region=scene.submat(new Rect(50,100,100,100));marker.copyTo(region);region.release();
            region=scene.submat(new Rect(350,100,100,100));marker.copyTo(region);region.release();
            assertEquals("duplicate",detector.detect(bytes(scene),640,480,k,PoseMath.identity(4)).status());
            scene.setTo(new Scalar(255));Objdetect.generateImageMarker(Objdetect.getPredefinedDictionary(Objdetect.DICT_4X4_50),0,18,marker);
            region=scene.submat(new Rect(300,220,18,18));marker.copyTo(region);region.release();
            assertEquals("too_small",detector.detect(bytes(scene),640,480,k,PoseMath.identity(4)).status());
        }finally{marker.release();scene.release();}
    }
    @Test public void readsPaddedAndInterleavedLumaWithoutChangingBufferPosition() {
        ByteBuffer buffer=ByteBuffer.wrap(new byte[]{99,1,0,2,0,3,0,88,88,4,0,5,0,6});buffer.position(1);
        assertArrayEquals(new byte[]{1,2,3,4,5,6},CameraTracker.copyLuma(buffer,3,2,8,2));assertEquals(1,buffer.position());
    }
}
