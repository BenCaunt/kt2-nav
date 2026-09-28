package com.bencaunt.kt2pose;

import org.junit.Test;
import org.json.JSONObject;
import static org.junit.Assert.*;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

public class RelayTest {
    static class Peer implements AutoCloseable {
        final Socket socket;final BufferedReader reader;
        Peer(int port) throws Exception {socket=new Socket("127.0.0.1",port);socket.setSoTimeout(3500);reader=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));}
        void send(JSONObject message) throws Exception {socket.getOutputStream().write((message+"\n").getBytes(StandardCharsets.UTF_8));}
        JSONObject read(String type) throws Exception {for(int i=0;i<30;i++){String line=reader.readLine();if(line==null)return null;JSONObject o=Json.parse(line);if(o.optString("type").equals(type))return o;}throw new AssertionError("Missing "+type);}
        String hello(String token) throws Exception {send(Json.obj("type","hello","version",1,"token",token));JSONObject r=read("ready");return r==null?null:r.optString("lease");}
        @Override public void close() throws Exception {socket.close();}
    }
    @Test public void rejectsBadPairingAndCanReconnect() throws Exception {
        RobotController r=new RobotController(new ControllerTest.Fake());r.foreground(true);
        try(UsbRelay relay=new UsbRelay("ABCDEF12",r,()->null)) {
            relay.start(0);
            try(Peer p=new Peer(relay.port())){assertNull(p.hello("wrong"));}
            Thread.sleep(100);
            try(Peer p=new Peer(relay.port())){assertNotNull(p.hello("ABCDEF12"));}
        }finally{r.close();}
    }
    @Test public void leasesDuplicatesBoundsAndStop() throws Exception {
        RobotController r=ControllerTest.connected(new ControllerTest.Fake());
        try(UsbRelay relay=new UsbRelay("ABCDEF12",r,()->null)) {
            relay.start(0);
            try(Peer p=new Peer(relay.port())) {
                String lease=p.hello("ABCDEF12");String id=UUID.randomUUID().toString();
                p.send(Json.obj("type","command","id",id,"action","stand","lease","expired"));assertFalse(p.read("command_result").optBoolean("accepted"));
                r.arm(true);p.send(Json.obj("type","ping"));lease=p.read("pong").optString("lease");
                p.send(Json.obj("type","command","id",id,"action","stand","lease",lease));assertTrue(p.read("command_result").optString("detail").contains("Repeated"));
                p.send(Json.obj("type","command","id",UUID.randomUUID().toString(),"action","stand","cycles",1.5,"lease",lease));assertFalse(p.read("command_result").optBoolean("accepted"));
                p.send(Json.obj("type","command","id",UUID.randomUUID().toString(),"action","stop","lease","stale"));assertTrue(p.read("command_result").optBoolean("accepted"));
                ControllerTest.await(()->!r.snapshot().optBoolean("busy"));assertFalse(r.snapshot().optBoolean("armed"));
            }
        }finally{r.close();}
    }
    @Test public void heartbeatLossStopsAndDisconnectsEvenWhileSendingStates() throws Exception {
        RobotController r=ControllerTest.connected(new ControllerTest.Fake());
        try(UsbRelay relay=new UsbRelay("ABCDEF12",r,()->CoreTest.packet(1,0,true))) {
            relay.start(0);
            try(Peer p=new Peer(relay.port())) {
                p.hello("ABCDEF12");r.arm(true);assertNotNull(p.read("state"));
                Thread.sleep(1800);assertNull(p.read("ready"));
                ControllerTest.await(()->!r.snapshot().optBoolean("busy"));assertFalse(r.snapshot().optBoolean("armed"));
            }
        }finally{r.close();}
    }
    @Test public void oversizedInputClosesConnection() throws Exception {
        RobotController r=new RobotController(new ControllerTest.Fake());r.foreground(true);
        try(UsbRelay relay=new UsbRelay("ABCDEF12",r,()->null)) {
            relay.start(0);
            try(Peer p=new Peer(relay.port())) {
                p.hello("ABCDEF12");p.socket.getOutputStream().write("x".repeat(17000).getBytes(StandardCharsets.UTF_8));
                try{assertNull(p.read("ready"));}catch(java.net.SocketException expected){/* reset closes unread over-limit input */}
            }
        }finally{r.close();}
    }
}
