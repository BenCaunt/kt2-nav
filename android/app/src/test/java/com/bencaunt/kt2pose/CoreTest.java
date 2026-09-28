package com.bencaunt.kt2pose;

import org.junit.Test;
import org.json.JSONArray;
import org.json.JSONObject;
import static org.junit.Assert.*;
import java.nio.file.Files;
import java.nio.file.Path;

public class CoreTest {
    static JSONObject packet(double time,double x,boolean detected) {
        double[] cv=PoseMath.identity(4);cv[3]=x;cv[11]=.4;
        double[] world=PoseMath.worldFromTag(PoseMath.identity(4),cv);
        JSONObject tag=detected?Json.obj("dictionary","DICT_4X4_50","id",0,"side_length_m",.025,
            "cv_camera_from_tag",Json.array(cv),"world_from_tag",Json.array(world),"corners_px",new JSONArray(java.util.List.of(300,220,340,220,340,260,300,260)),
            "reprojection_error_px",.2,"alternate_error_px",null,"minimum_edge_px",40,"pose_ambiguous",false):null;
        return Json.obj("schema_version",1,"session_id","fixture","sequence",Math.round(time*1000),"frame_timestamp_s",time,
            "sent_unix_s",System.currentTimeMillis()/1000.0,"camera_tracking","normal","camera_tracking_reason","none",
            "world_from_camera",Json.array(PoseMath.identity(4)),"image_resolution",new JSONArray(java.util.List.of(640,480)),
            "intrinsics",Json.obj("fx",600,"fy",600,"cx",320,"cy",240),"tag_status",detected?"detected":"not_detected","tag",tag);
    }
    @Test public void rejectsWrongIdentityAndParameters() throws Exception {
        assertTrue(RobotProgram.identity("{\"v\":\"B4KT2-V260201\",\"status\":\"OK\"}").contains("B4KT2"));
        for(String s:new String[]{"{\"model\":\"B4KT2\",\"simulation\":true}","{\"model\":\"B4KT20\"}","{\"model\":\"B4KT2-SIM\"}","{}"}) {
            assertThrows(Exception.class,()->RobotProgram.identity(s));
        }
        assertThrows(IllegalArgumentException.class,()->new RobotProgram.Parameters(0,30,80));
        assertThrows(IllegalArgumentException.class,()->new RobotProgram.Parameters(11,30,80));
        assertThrows(IllegalArgumentException.class,()->new RobotProgram.Parameters(1,91,80));
        assertThrows(IllegalArgumentException.class,()->new RobotProgram.Parameters(1,30,49));
        assertThrows(IllegalArgumentException.class,()->RobotProgram.Parameters.from(Json.obj("cycles",true)));
        assertThrows(IllegalArgumentException.class,()->RobotProgram.Parameters.from(Json.obj("cycles",1.5)));
        assertThrows(IllegalArgumentException.class,()->RobotProgram.motion("walk_forward","injection",new RobotProgram.Parameters(1,30,80)));
    }
    @Test public void capabilityProbeRequiresFramePlayback() throws Exception {
        assertTrue(RobotProgram.supported(Json.obj("actions",new JSONArray(new String[]{"walk"}),"q_methods",new JSONArray(new String[]{"play"}))).isEmpty());
        assertEquals(java.util.List.of("stand","walk_forward","walk_back"),RobotProgram.supported(Json.obj("actions",new JSONArray(new String[]{"walk"}),"q_methods",new JSONArray(new String[]{"play","frame"}))));
    }
    @Test public void cameraTransformAndAxes() {
        double[] cv=PoseMath.identity(4);cv[3]=.1;cv[7]=.2;cv[11]=.3;
        double[] camera=PoseMath.identity(4);camera[3]=1;
        double[] world=PoseMath.worldFromTag(camera,cv);
        assertEquals(1.1,world[3],1e-12);assertEquals(-.2,world[7],1e-12);assertEquals(-.3,world[11],1e-12);
        assertEquals(-1,world[5],0);assertEquals(-1,world[10],0);
        assertArrayEquals(PoseMath.identity(4),PoseMath.fromColumnMajor(new float[]{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1}),0);
    }
    @Test public void filterLearnsVelocityAndPredictsBriefLoss() throws Exception {
        PositionFilter filter=new PositionFilter();JSONObject estimate=null;
        for(int i=0;i<40;i++)estimate=filter.update(packet(i*.05,i*.005,true));
        assertEquals(.1,estimate.getJSONArray("velocity_world_mps").getDouble(0),.02);
        JSONObject p=packet(2.2,0,false);estimate=filter.update(p);
        assertEquals("predicted",estimate.getString("mode"));assertEquals(.25,estimate.getDouble("observation_age_s"),1e-6);
        assertTrue(estimate.getJSONArray("position_world_m").getDouble(0)>.20);
        p.put("robot_estimate",estimate);writeFixture("predicted-packet.json",p);
        assertNull(filter.update(packet(3.1,0,false)));
    }
    @Test public void filterRejectsOutlierAndResetsAfterWorldLoss() throws Exception {
        PositionFilter filter=new PositionFilter();
        for(int i=0;i<20;i++)filter.update(packet(i*.05,0,true));
        JSONObject outlier=filter.update(packet(1,1,true));assertEquals("predicted",outlier.getString("mode"));
        assertEquals(0,outlier.getJSONArray("position_world_m").getDouble(0),.001);
        JSONObject limited=packet(1.1,0,true);limited.put("camera_tracking","limited");assertNull(filter.update(limited));
        assertNull(filter.update(packet(1.2,0,false)));
        JSONObject reset=packet(1.3,.8,true);reset.put("session_id","new-world");
        assertEquals(.8,filter.update(reset).getJSONArray("position_world_m").getDouble(0),1e-9);
    }
    @Test public void duplicateFramesDoNotRefreshFilter() throws Exception {
        PositionFilter filter=new PositionFilter();JSONObject first=filter.update(packet(1,.1,true));
        JSONObject repeated=filter.update(packet(1,.8,true));assertEquals(first.toString(),repeated.toString());
        JSONObject ambiguous=packet(1.2,.8,true);ambiguous.getJSONObject("tag").put("pose_ambiguous",true);
        assertEquals("predicted",filter.update(ambiguous).getString("mode"));
    }
    @Test public void filterCovarianceIsSymmetricAndOrientedAlongViewingRay() throws Exception {
        JSONObject e=new PositionFilter().update(packet(1,.3,true));double[] cov=Json.doubles(e.getJSONArray("position_covariance_m2"));
        assertTrue(cov[2]<0);assertEquals(cov[2],cov[6],1e-12);assertTrue(cov[8]>cov[4]);
    }
    @Test public void exportActualGeneratedProgramsForPythonExecution() throws Exception {
        JSONObject programs=new JSONObject();String token="1234567890abcdef1234567890abcdef"; // Synthetic test token. gitleaks:allow
        for(String action:RobotProgram.ACTIONS)programs.put(action,RobotProgram.motion(action,token,new RobotProgram.Parameters(5,30,80)));
        programs.put("probe",RobotProgram.capabilities(token));writeFixture("programs.json",programs);
    }
    private static void writeFixture(String name,JSONObject object) throws Exception {
        Path directory=Path.of(System.getProperty("kt2.test.output"));Files.createDirectories(directory);Files.write(directory.resolve(name),object.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }
}
