package com.bencaunt.kt2pose;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.*;
import com.google.ar.core.ArCoreApk;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

public final class MainActivity extends Activity implements CameraTracker.Listener {
    private static final int BG=0xFF08171B, CARD=0xFF14292F, TEXT=0xFFEAF4F4, MUTED=0xFFA9C2C9, ACCENT=0xFF6DE4B6;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final Map<String,Button> motions=new LinkedHashMap<>();
    private RobotController robot;private CameraTracker camera;private UsbRelay relay;
    private PoseOverlay overlay;private PoseMap map;
    private TextView robotStatus,cameraStatus,usbStatus,trackingDetail;private Switch armed;
    private Button connect,cameraButton;private Spinner cycles,degrees,pace;
    private String pairingCode,cameraMessage="Camera is off",lastCameraError;
    private volatile JSONObject latestPacket;private JSONObject diagnostics;private long packetAt;
    private boolean resumed,pendingStart,installRequested,waitingForPermission,updating;
    private record PendingObservation(JSONObject packet,float[] viewProjection,long arrivedAt) { }
    private PendingObservation pendingObservation;
    private boolean deliveryQueued;
    private final Runnable tick=new Runnable(){@Override public void run(){if(resumed){refresh();main.postDelayed(this,200);}}};

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        byte[] random=new byte[4];new SecureRandom().nextBytes(random);StringBuilder code=new StringBuilder();for(byte b:random)code.append(String.format(java.util.Locale.ROOT,"%02X",b));pairingCode=code.toString();
        robot=new RobotController(new WifiTransport(this));camera=new CameraTracker(this,this);
        LinearLayout root=column();root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(bars.left,bars.top,bars.right,bars.bottom);return insets;});
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);LinearLayout content=column();content.setPadding(dp(20),dp(16),dp(20),dp(12));scroll.addView(content);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        TextView title=text("KT2 Pose",30,TEXT);title.setTypeface(null,Typeface.BOLD);content.addView(title);
        content.addView(text("ANDROID PREVIEW  /  0.1.0",11,ACCENT));
        TextView intro=text("Control your turtle. Track its place in the room.",14,MUTED);intro.setPadding(0,dp(8),0,dp(14));content.addView(intro);

        LinearLayout control=card(content,"Robot motion");
        robotStatus=text("Join xiaogui Wi-Fi, then connect",14,MUTED);control.addView(robotStatus);
        LinearLayout connection=row();connect=button("Connect",v->robot.connect());connection.addView(connect,weight());
        connection.addView(button("Wi-Fi settings",v->startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS))),weight());control.addView(connection);
        armed=new Switch(this);armed.setText("Enable motion");armed.setTextSize(16);armed.setTextColor(TEXT);armed.setPadding(0,dp(6),0,dp(6));
        armed.setOnCheckedChangeListener((b,value)->{if(!updating)robot.arm(value);});control.addView(armed);
        LinearLayout choices=row();cycles=selector(choices,"Walk cycles",new String[]{"1","2","3","4","5","6","7","8","9","10"},0);
        degrees=selector(choices,"Turn angle",new String[]{"15°","30°","45°","90°"},1);
        pace=selector(choices,"Walk pace",new String[]{"Slow","Normal","Brisk"},0);control.addView(choices);
        motionRow(control,"Forward","walk_forward","Back","walk_back");motionRow(control,"Turn left","turn_left","Turn right","turn_right");
        motionRow(control,"Stand","stand","Low","crouch");motionRow(control,"Head up","look_up","Head down","look_down");

        LinearLayout tracking=card(content,"Camera & marker");
        cameraStatus=text(cameraMessage,14,MUTED);tracking.addView(cameraStatus);
        cameraButton=button("Start camera",v->{if(camera.isRunning()){pendingStart=false;stopCamera();}else{pendingStart=true;startCamera();}});tracking.addView(cameraButton);
        FrameLayout preview=new FrameLayout(this);preview.setBackgroundColor(BG);
        preview.addView(camera.surface,new FrameLayout.LayoutParams(-1,-1));overlay=new PoseOverlay(this);preview.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        tracking.addView(preview,new LinearLayout.LayoutParams(-1,dp(270)));
        trackingDetail=text("ArUco 4×4 · ID 0 · 25 mm black square\nCamera images stay on this phone.",12,MUTED);trackingDetail.setPadding(0,dp(8),0,dp(8));tracking.addView(trackingDetail);
        map=new PoseMap(this);tracking.addView(map,new LinearLayout.LayoutParams(-1,dp(190)));
        TextView privacy=text("Tracking uses Google Play Services for AR. Google processes data as described in its Privacy Policy.",12,MUTED);tracking.addView(privacy);
        tracking.addView(button("Google Privacy Policy",v->startActivity(new Intent(Intent.ACTION_VIEW,android.net.Uri.parse("https://policies.google.com/privacy")))));

        LinearLayout usb=card(content,"USB to computer · optional");
        TextView token=text("Pairing code  " + pairingCode,21,ACCENT);token.setTypeface(Typeface.MONOSPACE);token.setTextIsSelectable(true);usb.addView(token);
        usbStatus=text("Waiting for computer over USB",14,MUTED);usb.addView(usbStatus);
        usb.addView(text("Phone-only controls need no cable. For the desktop map, enable USB debugging, connect a data cable, and start the Android receiver on your computer.",13,MUTED));
        LinearLayout about=card(content,"Help test this preview");
        about.addView(text("Built for Pixel 7 Pro / Android 13+. Physical Pixel camera tracking and robot operation are awaiting tester verification. Start with one slow walking cycle on a clear surface.",13,MUTED));
        about.addView(button("Save diagnostics",v->{diagnostics=diagnosticReport();Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT);i.setType("application/json");i.addCategory(Intent.CATEGORY_OPENABLE);i.putExtra(Intent.EXTRA_TITLE,"kt2-pose-diagnostics.json");startActivityForResult(i,20);}));
        LinearLayout footer=column();footer.setPadding(dp(16),dp(4),dp(16),dp(8));footer.setBackgroundColor(BG);
        Button stop=button("STOP ROBOT",v->robot.stop("Stop requested"));stop.setTextSize(18);stop.setTypeface(null,Typeface.BOLD);stop.setTextColor(Color.WHITE);stop.setBackgroundTintList(ColorStateList.valueOf(0xFFAC3346));footer.addView(stop,new LinearLayout.LayoutParams(-1,dp(58)));root.addView(footer);
        setContentView(root);
    }
    @Override protected void onResume() {
        super.onResume();resumed=true;robot.foreground(true);camera.surface.onResume();camera.surface.requestRender();
        relay=new UsbRelay(pairingCode,robot,()->latestPacket);
        try {relay.start(8767);}catch(Exception e){relay.status="USB unavailable: "+e.getMessage();}
        main.post(tick);if(pendingStart && !waitingForPermission)startCamera();
    }
    @Override protected void onPause() {
        resumed=false;main.removeCallbacks(tick);robot.foreground(false);
        if(relay!=null){relay.close();relay=null;}
        camera.pause();clearPose();cameraMessage="Camera paused — tap Start camera";super.onPause();
    }
    @Override protected void onDestroy() {camera.close();robot.close();super.onDestroy();}
    private void startCamera() {
        if(!resumed || camera.isRunning())return;
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED){if(!waitingForPermission){waitingForPermission=true;requestPermissions(new String[]{Manifest.permission.CAMERA},10);}return;}
        try {
            ArCoreApk.Availability availability=ArCoreApk.getInstance().checkAvailability(this);
            if(availability.isTransient()) {
                cameraMessage="Checking AR support…";main.postDelayed(()->{if(pendingStart && resumed)startCamera();},500);return;
            }
            if(!availability.isSupported())throw new IllegalStateException("AR tracking unavailable. Install/update Google Play Services for AR on an internet connection; robot controls still work.");
            if(ArCoreApk.getInstance().requestInstall(this,!installRequested)==ArCoreApk.InstallStatus.INSTALL_REQUESTED){installRequested=true;cameraMessage="Install Google Play Services for AR, then return";return;}
            camera.start();pendingStart=false;cameraMessage="Searching for marker — move phone slowly";lastCameraError=null;
        } catch(Exception e){pendingStart=false;lastCameraError=e.getClass().getSimpleName()+": "+e.getMessage();cameraMessage=e.getMessage()==null?"Camera could not start. Check permission and Google Play Services for AR.":e.getMessage();}
        refresh();
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(request,permissions,results);
        if(request==10){waitingForPermission=false;if(results.length>0 && results[0]==PackageManager.PERMISSION_GRANTED){pendingStart=true;startCamera();}else{pendingStart=false;cameraMessage="Camera permission denied. Enable it in Android app settings to track; robot controls still work.";refresh();}}
    }
    private void stopCamera(){camera.pause();camera.surface.onResume();camera.surface.requestRender();clearPose();cameraMessage="Camera is off";refresh();}
    private void clearPose(){latestPacket=null;synchronized(this){pendingObservation=null;}overlay.update(null,null);map.update(null);}
    @Override public void observation(JSONObject packet,float[] vp,long capturedAt) {
        synchronized(this){pendingObservation=new PendingObservation(packet,vp,capturedAt);if(deliveryQueued)return;deliveryQueued=true;}
        main.post(()->{
            PendingObservation next;synchronized(this){next=pendingObservation;pendingObservation=null;deliveryQueued=false;}
            if(next==null || !resumed || !camera.owns(next.packet()) || Json.now()-next.arrivedAt()>500)return;
            displayObservation(next.packet(),next.viewProjection(),next.arrivedAt());
        });
    }
    private void displayObservation(JSONObject packet,float[] vp,long capturedAt) {
            latestPacket=packet;packetAt=capturedAt;overlay.update(packet,vp);map.update(packet);
            String tracking=packet.optString("camera_tracking"),status=packet.optString("tag_status");JSONObject tag=packet.optJSONObject("tag");
            cameraMessage=!tracking.equals("normal")?"Move phone slowly · "+packet.optString("camera_tracking_reason"):tag!=null?(tag.optBoolean("pose_ambiguous")?"Marker found · orientation uncertain":"Marker tracked"):"Find marker · "+status.replace('_',' ');
            JSONObject estimate=packet.optJSONObject("robot_estimate");
            if(estimate!=null){double[] position=Json.doubles(estimate.optJSONArray("position_world_m"));trackingDetail.setText(String.format(java.util.Locale.ROOT,"%s · X %.1f / Y %.1f / Z %.1f cm\n25 mm marker · camera images stay on phone",estimate.optString("mode"),position[0]*100,position[1]*100,position[2]*100));}
            else trackingDetail.setText("ArUco 4×4 · ID 0 · 25 mm black square\nCamera images stay on this phone.");
    }
    @Override public void cameraError(String error) {main.post(()->{if(resumed){lastCameraError=error;cameraMessage=error;clearPose();}});}
    private void refresh() {
        JSONObject state=robot.snapshot();String error=state.optString("error","");
        setTextIfChanged(robotStatus,state.optString("status")+(error.isEmpty() || error.equals("null")?"":"\n"+error));
        updating=true;armed.setChecked(state.optBoolean("armed"));updating=false;
        armed.setEnabled(!state.optBoolean("busy")&&!state.isNull("identity"));connect.setEnabled(!state.optBoolean("busy"));
        for(Map.Entry<String,Button> entry:motions.entrySet()) {boolean supported=false;for(int i=0;i<state.optJSONArray("supported_motions").length();i++)if(entry.getKey().equals(state.optJSONArray("supported_motions").optString(i)))supported=true;entry.getValue().setEnabled(state.optBoolean("can_move")&&supported);}
        setTextIfChanged(cameraButton,camera.isRunning()?"Stop camera":"Start camera");setTextIfChanged(cameraStatus,cameraMessage);setTextIfChanged(usbStatus,relay==null?"USB paused":relay.status);
        if(latestPacket!=null && Json.now()-packetAt>500){clearPose();cameraMessage="Waiting for fresh camera frames…";}
        overlay.invalidate();map.invalidate();
    }
    private void move(String action) {
        int[] angles={15,30,45,90},timing={120,80,50};
        robot.move(action,UUID.randomUUID().toString(),new RobotProgram.Parameters(cycles.getSelectedItemPosition()+1,angles[degrees.getSelectedItemPosition()],timing[pace.getSelectedItemPosition()]));refresh();
    }
    private void motionRow(LinearLayout parent,String a,String actionA,String b,String actionB){LinearLayout r=row();Button first=button(a,v->move(actionA)),second=button(b,v->move(actionB));motions.put(actionA,first);motions.put(actionB,second);r.addView(first,weight());r.addView(second,weight());parent.addView(r);}
    private Spinner selector(LinearLayout parent,String label,String[] values,int selection){LinearLayout col=column();TextView name=text(label,11,MUTED);col.addView(name);Spinner spinner=new Spinner(this);ArrayAdapter<String> adapter=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,values);adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);spinner.setAdapter(adapter);spinner.setSelection(selection);spinner.setContentDescription(label);col.addView(spinner,new LinearLayout.LayoutParams(-1,dp(44)));parent.addView(col,weight());return spinner;}
    private LinearLayout card(LinearLayout parent,String title){LinearLayout view=column();view.setPadding(dp(14),dp(12),dp(14),dp(12));GradientDrawable background=new GradientDrawable();background.setColor(CARD);background.setCornerRadius(dp(18));view.setBackground(background);LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.bottomMargin=dp(14);parent.addView(view,lp);TextView heading=text(title,18,TEXT);heading.setTypeface(null,Typeface.BOLD);heading.setPadding(0,0,0,dp(8));view.addView(heading);return view;}
    private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
    private LinearLayout row(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.HORIZONTAL);v.setGravity(Gravity.CENTER_VERTICAL);return v;}
    private LinearLayout.LayoutParams weight(){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(dp(2),dp(2),dp(2),dp(2));return p;}
    private TextView text(String text,int size,int color){TextView v=new TextView(this);v.setText(text);v.setTextSize(size);v.setTextColor(color);v.setLineSpacing(dp(2),1);return v;}
    private Button button(String label,View.OnClickListener click){Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setTextColor(TEXT);b.setTextSize(14);b.setMinHeight(dp(48));b.setBackgroundTintList(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{0xFF1C343C,0xFF2C4A54}));b.setOnClickListener(click);return b;}
    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private static void setTextIfChanged(TextView view,String value){if(!view.getText().toString().equals(value))view.setText(value);}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=20 || result!=RESULT_OK || data==null || data.getData()==null)return;
        try(var output=getContentResolver().openOutputStream(data.getData())){
            JSONObject report=diagnostics==null?diagnosticReport():diagnostics;
            if(output!=null)output.write(report.toString(2).getBytes(StandardCharsets.UTF_8));Toast.makeText(this,"Diagnostics saved",Toast.LENGTH_SHORT).show();
        }catch(Exception e){Toast.makeText(this,"Could not save: "+e.getMessage(),Toast.LENGTH_LONG).show();}}
    private JSONObject diagnosticReport(){return Json.obj("app_version","0.1.0-preview","device",Build.MANUFACTURER+" "+Build.MODEL,"android",Build.VERSION.RELEASE,"sdk",Build.VERSION.SDK_INT,"camera_status",cameraMessage,"camera_error",lastCameraError,"robot",robot.snapshot(),"packet",latestPacket,"note","No images, Wi-Fi passwords, or pairing codes included.");}
}
