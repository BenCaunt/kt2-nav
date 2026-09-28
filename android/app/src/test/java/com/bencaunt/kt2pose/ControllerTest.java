package com.bencaunt.kt2pose;

import org.junit.Test;
import org.json.JSONObject;
import static org.junit.Assert.*;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import java.util.regex.Pattern;

public class ControllerTest {
    static class Fake implements RobotController.Transport {
        final List<String> calls=new CopyOnWriteArrayList<>();
        String logs="";boolean confirmCycles=true,failStop;CountDownLatch submitted,release;
        @Override public String request(String path,String code) throws Exception {
            calls.add(path);
            if(path.equals("/ping"))return "{\"model\":\"B4KT2\",\"v\":\"V260201\"}";
            if(path.equals("/py")) {
                var m=Pattern.compile("@KT2(CAP|PHONE):([a-f0-9]{32}):").matcher(code);assertTrue(m.find());String prefix=m.group();
                if(m.group(1).equals("CAP"))logs=prefix+"{\"actions\":[\"walk\",\"c_pivot\",\"ofs_stand_low\",\"ofs_head_up\",\"ofs_head_down\"],\"q_methods\":[\"play\",\"frame\"]}\n";
                else {
                    if(submitted!=null){submitted.countDown();assertTrue(release.await(3,TimeUnit.SECONDS));}
                    logs=(confirmCycles?prefix+"{\"kind\":\"progress\",\"cycle\":1,\"frames_played\":16,\"elapsed_ms\":1280}\n":"")+prefix+"{\"kind\":\"done\"}\n";
                }
                return "{\"status\":\"OK\"}";
            }
            if(path.equals("/log")){String result=logs;logs="";return result;}
            if(path.contains("break")){if(failStop)throw new IllegalStateException("offline");return "{\"status\":\"OK\"}";}
            throw new AssertionError(path);
        }
    }
    static void await(BooleanSupplier predicate) throws Exception {long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);while(!predicate.getAsBoolean()&&System.nanoTime()<end)Thread.sleep(10);assertTrue("Timed out",predicate.getAsBoolean());}
    static RobotController connected(Fake fake) throws Exception {
        RobotController r=new RobotController(fake);r.foreground(true);assertTrue(r.connect());await(()->!r.snapshot().optBoolean("busy"));assertFalse(r.snapshot().isNull("identity"));return r;
    }
    @Test public void requiresArmingAndNoQueueAndConfirmsCycles() throws Exception {
        Fake f=new Fake();RobotController r=connected(f);
        try {
            assertFalse(r.move("walk_forward",UUID.randomUUID().toString(),new RobotProgram.Parameters(1,30,80)));
            r.arm(true);assertTrue(r.move("walk_forward","test",new RobotProgram.Parameters(1,30,80)));
            assertFalse(r.move("stand","queued",new RobotProgram.Parameters(1,30,80)));
            await(()->!r.snapshot().optBoolean("busy"));assertEquals("completed",r.snapshot().optString("motion"));
            assertEquals(16,r.snapshot().optInt("walk_frames_played"));
        }finally{r.close();}
    }
    @Test public void stopWaitsForDelayedSubmissionAndDisarms() throws Exception {
        Fake f=new Fake();RobotController r=connected(f);f.submitted=new CountDownLatch(1);f.release=new CountDownLatch(1);
        try {
            r.arm(true);assertTrue(r.move("walk_forward","test",new RobotProgram.Parameters(1,30,80)));
            assertTrue(f.submitted.await(2,TimeUnit.SECONDS));r.stop("Stop");
            Thread.sleep(100);assertFalse(f.calls.stream().anyMatch(x->x.contains("break")));
            assertFalse(r.snapshot().optBoolean("armed"));f.release.countDown();
            await(()->!r.snapshot().optBoolean("busy"));assertEquals("stopped",r.snapshot().optString("motion"));
            assertTrue(f.calls.get(f.calls.size()-1).contains("break"));
        }finally{f.release.countDown();r.close();}
    }
    @Test public void missingProgressRequestsStopAndDoesNotClaimCompletion() throws Exception {
        Fake f=new Fake();f.confirmCycles=false;RobotController r=connected(f);
        try {
            r.arm(true);r.move("walk_forward","test",new RobotProgram.Parameters(1,30,80));await(()->!r.snapshot().optBoolean("busy"));
            assertEquals("unconfirmed",r.snapshot().optString("motion"));assertFalse(r.snapshot().optBoolean("armed"));
            assertTrue(f.calls.stream().anyMatch(x->x.contains("break")));
        }finally{r.close();}
    }
    @Test public void backgroundAndUsbLossDisarm() throws Exception {
        RobotController r=connected(new Fake());
        try {
            r.arm(true);r.linkLost();await(()->!r.snapshot().optBoolean("busy"));assertFalse(r.canMove());
            r.arm(true);r.foreground(false);await(()->!r.snapshot().optBoolean("busy"));
            r.arm(true);assertFalse(r.snapshot().optBoolean("armed"));assertFalse(r.connect());
        }finally{r.close();}
    }
    @Test public void failedStopIsReportedUnconfirmed() throws Exception {
        Fake f=new Fake();RobotController r=connected(f);f.failStop=true;
        try {r.stop("Stop");await(()->!r.snapshot().optBoolean("busy"));assertEquals("unconfirmed",r.snapshot().optString("motion"));assertEquals("offline",r.snapshot().optString("error"));}finally{r.close();}
    }
}
