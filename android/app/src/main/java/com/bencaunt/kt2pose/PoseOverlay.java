package com.bencaunt.kt2pose;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.View;
import org.json.JSONObject;

final class PoseOverlay extends View {
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private JSONObject packet; private float[] vp; private long updated;
    PoseOverlay(Context c) { super(c); setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO); }
    void update(JSONObject packet,float[] vp) { this.packet=packet;this.vp=vp;updated=Json.now();invalidate(); }
    @Override protected void onDraw(Canvas canvas) {
        if(packet==null || vp==null || Json.now()-updated>500 || !packet.optString("camera_tracking").equals("normal")) return;
        JSONObject estimate=packet.optJSONObject("robot_estimate"),tag=packet.optJSONObject("tag");
        if(estimate==null && tag==null) return;
        double[] transform=Json.doubles((estimate!=null?estimate:tag).optJSONArray("world_from_tag"));
        float[] origin=project(transform[3],transform[7],transform[11]);if(origin==null) return;
        String[] labels={"X · right","Y · forward","Z · up"}; int[] colors={0xFFFF7878,0xFF6DE4B6,0xFF78B8FF};
        for(int axis=0;axis<3;axis++) {
            float[] end=project(transform[3]+transform[axis]*.055,transform[7]+transform[4+axis]*.055,transform[11]+transform[8+axis]*.055);
            if(end==null) continue;
            paint.setColor(colors[axis]);paint.setStrokeWidth(6);canvas.drawLine(origin[0],origin[1],end[0],end[1],paint);
            double angle=Math.atan2(end[1]-origin[1],end[0]-origin[0]);
            for(int sign=-1;sign<=1;sign+=2) canvas.drawLine(end[0],end[1],end[0]-(float)Math.cos(angle+sign*.5)*18,end[1]-(float)Math.sin(angle+sign*.5)*18,paint);
            paint.setTextSize(14*getResources().getDisplayMetrics().scaledDensity);paint.setShadowLayer(4,1,1,Color.BLACK);
            canvas.drawText(labels[axis],end[0]+8,end[1]-10,paint);paint.clearShadowLayer();
        }
    }
    private float[] project(double x,double y,double z) {
        double w=vp[3]*x+vp[7]*y+vp[11]*z+vp[15];if(w<=0) return null;
        return new float[]{(float)((vp[0]*x+vp[4]*y+vp[8]*z+vp[12])/w+1)*getWidth()/2,
            (float)(1-(vp[1]*x+vp[5]*y+vp[9]*z+vp[13])/w)*getHeight()/2};
    }
}
