package com.bencaunt.kt2pose;

import android.content.Context;
import android.graphics.*;
import android.view.View;
import org.json.JSONObject;
import java.util.ArrayDeque;

final class PoseMap extends View {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final ArrayDeque<double[]> trail=new ArrayDeque<>();
    private JSONObject packet;private String session;private long sequence=-1,updated;
    PoseMap(Context context) { super(context);setContentDescription("Top-down camera and robot position map"); }
    void update(JSONObject value) {
        packet=value;updated=Json.now();
        if(value==null || !value.optString("session_id").equals(session) || !value.optString("camera_tracking").equals("normal")) { trail.clear();sequence=-1; }
        if(value!=null) {
            session=value.optString("session_id");JSONObject e=value.optJSONObject("robot_estimate");
            if(e!=null && value.optLong("sequence")!=sequence) {
                trail.add(Json.doubles(e.optJSONArray("position_world_m")));while(trail.size()>150) trail.remove();
            }
            sequence=value.optLong("sequence");
        }
        invalidate();
    }
    @Override protected void onDraw(Canvas c) {
        c.drawColor(0xFF102025);p.setStrokeWidth(1);p.setColor(0xFF254047);
        float scale=getWidth()/1.2f, cx=getWidth()/2f,cz=getHeight()/2f;
        for(float x=cx%(.1f*scale);x<getWidth();x+=.1f*scale)c.drawLine(x,0,x,getHeight(),p);
        for(float y=cz%(.1f*scale);y<getHeight();y+=.1f*scale)c.drawLine(0,y,getWidth(),y,p);
        p.setTextSize(12*getResources().getDisplayMetrics().scaledDensity);p.setColor(0xFFB4CBD0);
        c.drawText("TOP VIEW  ·  10 cm grid  ·  ellipse = 2σ",16,24*getResources().getDisplayMetrics().density,p);
        if(packet==null || Json.now()-updated>500 || !packet.optString("camera_tracking").equals("normal")) return;
        double[] camera=Json.doubles(packet.optJSONArray("world_from_camera"));JSONObject e=packet.optJSONObject("robot_estimate");
        double centerX=camera[3],centerZ=camera[11];
        if(e!=null) { double[] pos=Json.doubles(e.optJSONArray("position_world_m"));centerX=(centerX+pos[0])/2;centerZ=(centerZ+pos[2])/2; }
        p.setColor(0xFF4B827D);p.setStrokeWidth(3);double[] previous=null;
        for(double[] point:trail) {if(previous!=null)c.drawLine(cx+(float)(previous[0]-centerX)*scale,cz+(float)(previous[2]-centerZ)*scale,cx+(float)(point[0]-centerX)*scale,cz+(float)(point[2]-centerZ)*scale,p);previous=point;}
        arrow(c,cx+(float)(camera[3]-centerX)*scale,cz+(float)(camera[11]-centerZ)*scale,-camera[2],-camera[10],0xFF78B8FF,"Camera");
        if(e==null)return;
        double[] t=Json.doubles(e.optJSONArray("world_from_tag")),cov=Json.doubles(e.optJSONArray("position_covariance_m2"));
        float x=cx+(float)(t[3]-centerX)*scale,z=cz+(float)(t[11]-centerZ)*scale;
        double spread=Math.hypot(cov[0]-cov[8],2*cov[2]);float major=(float)(2*Math.sqrt(Math.max(0,(cov[0]+cov[8]+spread)/2))*scale),minor=(float)(2*Math.sqrt(Math.max(0,(cov[0]+cov[8]-spread)/2))*scale);
        int color=e.optString("mode").equals("predicted")?0xFFF6C56B:0xFF6DE4B6;
        c.save();c.rotate((float)Math.toDegrees(Math.atan2(2*cov[2],cov[0]-cov[8])/2),x,z);
        p.setColor(color);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(3);c.drawOval(x-major,z-minor,x+major,z+minor,p);p.setStyle(Paint.Style.FILL);c.restore();
        arrow(c,x,z,t[1],t[9],color,e.optString("mode").equals("predicted")?"Predicted":"Robot");
    }
    private void arrow(Canvas c,float x,float y,double dx,double dy,int color,String label) {
        p.setColor(color);c.drawCircle(x,y,7,p);p.setStrokeWidth(4);
        double length=Math.hypot(dx,dy);if(length>.01)c.drawLine(x,y,x+(float)(dx/length)*25,y+(float)(dy/length)*25,p);
        c.drawText(label,x+12,y-12,p);
    }
}
