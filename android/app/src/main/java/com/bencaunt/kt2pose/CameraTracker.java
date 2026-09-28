package com.bencaunt.kt2pose;

import android.app.Activity;
import android.media.Image;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import com.google.ar.core.*;
import com.google.ar.core.exceptions.NotYetAvailableException;
import org.json.JSONArray;
import org.json.JSONObject;
import org.opencv.android.OpenCVLoader;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** ARCore texture preview plus one in-flight luma detection; no camera frames leave the phone. */
final class CameraTracker implements GLSurfaceView.Renderer {
    interface Listener { void observation(JSONObject packet, float[] viewProjection, long capturedAt); void cameraError(String error); }
    private final Activity activity;
    final GLSurfaceView surface;
    private final Listener listener;
    private final ExecutorService detectorWorker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean processing = new AtomicBoolean();
    private final AtomicInteger generation = new AtomicInteger();
    private final PositionFilter filter = new PositionFilter();
    private MarkerDetector detector;
    private volatile Session session;
    private String sessionId;
    private long lastTimestamp, sequence;
    private int texture, program, positionAttribute, uvAttribute, width=1, height=1;
    private final FloatBuffer quad = floats(-1,-1, 1,-1, -1,1, 1,1), uv = floats(0,0,0,0,0,0,0,0);

    CameraTracker(Activity activity, Listener listener) {
        this.activity=activity; this.listener=listener;
        surface=new GLSurfaceView(activity); surface.setEGLContextClientVersion(2);
        surface.setPreserveEGLContextOnPause(true); surface.setRenderer(this);
        surface.setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
    }
    boolean isRunning() { return session != null; }
    boolean owns(JSONObject packet) { return session != null && packet.optString("session_id").equals(sessionId); }
    void start() throws Exception {
        if (session != null) return;
        if (!OpenCVLoader.initLocal()) throw new IllegalStateException("OpenCV could not load");
        Session next = new Session(activity);
        try {
            // Prefer enough CPU image pixels for the small sticker, without 4K processing.
            CameraConfig best=null;
            for (CameraConfig c : next.getSupportedCameraConfigs(new CameraConfigFilter(next))) {
                int w=c.getImageSize().getWidth();
                if (w<=1920 && (best==null || w>best.getImageSize().getWidth())) best=c;
            }
            if (best != null) next.setCameraConfig(best);
            Config config=new Config(next);
            config.setFocusMode(Config.FocusMode.AUTO);
            config.setPlaneFindingMode(Config.PlaneFindingMode.DISABLED);
            config.setLightEstimationMode(Config.LightEstimationMode.DISABLED);
            config.setUpdateMode(Config.UpdateMode.LATEST_CAMERA_IMAGE);
            next.configure(config); next.resume();
            sessionId=UUID.randomUUID().toString(); lastTimestamp=0; sequence=0; generation.incrementAndGet(); session=next;
            surface.onResume();
            surface.setRenderMode(GLSurfaceView.RENDERMODE_CONTINUOUSLY);
        } catch (Exception e) { next.close(); throw e; }
    }
    void pause() {
        surface.setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
        surface.onPause(); generation.incrementAndGet();
        Session old=session; session=null;
        if (old != null) { old.pause(); old.close(); }
    }
    void close() { pause(); detectorWorker.shutdown(); }
    @Override public void onSurfaceCreated(GL10 gl, EGLConfig config) {
        int[] textures=new int[1]; GLES20.glGenTextures(1,textures,0); texture=textures[0];
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,texture);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_LINEAR);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES20.GL_TEXTURE_WRAP_S,GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES20.GL_TEXTURE_WRAP_T,GLES20.GL_CLAMP_TO_EDGE);
        program=GLES20.glCreateProgram();
        GLES20.glAttachShader(program,shader(GLES20.GL_VERTEX_SHADER,"attribute vec2 p; attribute vec2 uv; varying vec2 v; void main(){gl_Position=vec4(p,0.,1.);v=uv;}"));
        GLES20.glAttachShader(program,shader(GLES20.GL_FRAGMENT_SHADER,"#extension GL_OES_EGL_image_external : require\nprecision mediump float; uniform samplerExternalOES camera; varying vec2 v; void main(){gl_FragColor=texture2D(camera,v);}"));
        GLES20.glLinkProgram(program);
        positionAttribute=GLES20.glGetAttribLocation(program,"p"); uvAttribute=GLES20.glGetAttribLocation(program,"uv");
    }
    @Override public void onSurfaceChanged(GL10 gl,int width,int height) { this.width=width;this.height=height; GLES20.glViewport(0,0,width,height); }
    @Override public void onDrawFrame(GL10 gl) {
        GLES20.glClearColor(.035f,.065f,.075f,1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        Session current=session; if(current==null) return;
        int version=generation.get();
        try {
            current.setDisplayGeometry(activity.getWindowManager().getDefaultDisplay().getRotation(),width,height);
            current.setCameraTextureName(texture);
            Frame frame=current.update();
            if(frame.getTimestamp()==0) return;
            quad.position(0);uv.position(0);
            frame.transformCoordinates2d(Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES,quad,Coordinates2d.TEXTURE_NORMALIZED,uv);
            drawBackground();
            long timestamp=frame.getTimestamp();
            if(timestamp-lastTimestamp<66_666_666 || !processing.compareAndSet(false,true)) return;
            try (Image image=frame.acquireCameraImage()) {
                lastTimestamp=timestamp;
                int imageWidth=image.getWidth(),imageHeight=image.getHeight();
                Image.Plane plane=image.getPlanes()[0]; ByteBuffer source=plane.getBuffer();
                byte[] pixels=copyLuma(source,imageWidth,imageHeight,plane.getRowStride(),plane.getPixelStride());
                Camera camera=frame.getCamera();
                CameraIntrinsics intrinsics=camera.getImageIntrinsics();
                float[] focal=intrinsics.getFocalLength(),principal=intrinsics.getPrincipalPoint();
                double[] k={focal[0],focal[1],principal[0],principal[1]};
                float[] world=new float[16],view=new float[16],projection=new float[16],vp=new float[16];
                camera.getPose().toMatrix(world,0); camera.getViewMatrix(view,0);camera.getProjectionMatrix(projection,0,.01f,100);
                android.opengl.Matrix.multiplyMM(vp,0,projection,0,view,0);
                double[] worldCamera=PoseMath.fromColumnMajor(world);
                String tracking=camera.getTrackingState()==TrackingState.TRACKING ? "normal" : "limited";
                String reason=camera.getTrackingFailureReason().name().toLowerCase(java.util.Locale.ROOT);
                String id=sessionId; long seq=++sequence;
                long started=Json.now();
                detectorWorker.execute(() -> {
                    try {
                        if(detector==null) detector=new MarkerDetector();
                        MarkerDetector.Result result=detector.detect(pixels,imageWidth,imageHeight,k,worldCamera);
                        JSONObject packet=Json.obj("schema_version",1,"session_id",id,"sequence",seq,
                            "frame_timestamp_s",timestamp/1e9,"sent_unix_s",System.currentTimeMillis()/1000.0,
                            "camera_tracking",tracking,"camera_tracking_reason",reason,"world_from_camera",Json.array(worldCamera),
                            "image_resolution",new JSONArray(new int[]{imageWidth,imageHeight}),
                            "intrinsics",Json.obj("fx",k[0],"fy",k[1],"cx",k[2],"cy",k[3]),"tag_status",result.status(),"tag",result.tag());
                        JSONObject estimate=filter.update(packet); if(estimate!=null) packet.put("robot_estimate",estimate);
                        if(generation.get()==version && Json.now()-started<=500) listener.observation(packet,vp,started);
                    } catch(Exception e) { if(generation.get()==version) listener.cameraError("Marker processing: " + e.getMessage()); }
                    finally { processing.set(false); }
                });
            } catch(NotYetAvailableException e) { processing.set(false); }
            catch(Exception e) { processing.set(false); throw e; }
        } catch(Exception e) { if(generation.get()==version) listener.cameraError("Camera: " + e.getClass().getSimpleName() + " " + e.getMessage()); }
    }
    static byte[] copyLuma(ByteBuffer source,int width,int height,int rowStride,int pixelStride) {
        ByteBuffer data=source.duplicate(); int base=data.position(); byte[] pixels=new byte[width*height];
        for(int y=0;y<height;y++) {
            if(pixelStride==1) { data.position(base+y*rowStride);data.get(pixels,y*width,width); }
            else for(int x=0;x<width;x++) pixels[y*width+x]=data.get(base+y*rowStride+x*pixelStride);
        }
        return pixels;
    }
    private void drawBackground() {
        GLES20.glDisable(GLES20.GL_DEPTH_TEST);GLES20.glUseProgram(program);
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0);GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,texture);
        GLES20.glUniform1i(GLES20.glGetUniformLocation(program,"camera"),0);
        quad.position(0);uv.position(0);
        GLES20.glVertexAttribPointer(positionAttribute,2,GLES20.GL_FLOAT,false,0,quad);
        GLES20.glVertexAttribPointer(uvAttribute,2,GLES20.GL_FLOAT,false,0,uv);
        GLES20.glEnableVertexAttribArray(positionAttribute);GLES20.glEnableVertexAttribArray(uvAttribute);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP,0,4);
        GLES20.glDisableVertexAttribArray(positionAttribute);GLES20.glDisableVertexAttribArray(uvAttribute);
    }
    private static FloatBuffer floats(float... values) { FloatBuffer b=ByteBuffer.allocateDirect(values.length*4).order(ByteOrder.nativeOrder()).asFloatBuffer();b.put(values);b.position(0);return b; }
    private static int shader(int type,String source) {
        int s=GLES20.glCreateShader(type);GLES20.glShaderSource(s,source);GLES20.glCompileShader(s);return s;
    }
}
