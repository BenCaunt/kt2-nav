import json
import threading
import time
import types

import numpy as np
import pytest

from kt2_sim import KT2Sim
from kt2_sim.hardware import HardwareBridge, PacketReader, motion_program, telemetry_program, validate_frames, validate_host, verify_identity
from kt2_sim.runtime import Runtime


@pytest.mark.parametrize('host', ['127.0.0.1', '169.254.169.254', '8.8.8.8', '0.0.0.0',
                                 '192.168.4.1:80', 'http://192.168.4.1', 'robot.local', '::1'])
def test_only_explicit_private_ipv4_targets(host):
    with pytest.raises(ValueError):
        validate_host(host)
    assert validate_host('192.168.4.1') == '192.168.4.1'


@pytest.mark.parametrize('identity', [
    {'model':'B4KT2','simulation':True}, {'model':'B4KT2','ver':'SIM-0.1'},
    {'model':'OTHER'}, {'model':'NOTB4KT2'}, {'model':'B4KT2','status':'NG'}, [],
])
def test_rejects_wrong_identity_and_simulation(identity):
    with pytest.raises(ValueError):
        verify_identity(json.dumps(identity))


def test_fragmented_logs_ignore_foreign_packets_and_corruption():
    reader=PacketReader('a'*32)
    text='unrelated output\n@KT2SYNC:'+'b'*32+':{"kind":"sample"}\n'
    text+='@KT2SYNC:'+'a'*32+':not-json\n'
    text+='@KT2SYNC:'+'a'*32+':{"kind":"sample","values":{"get_p":10}}\n'
    assert reader.feed(text[:-5]) == []
    assert reader.feed(text[-5:]) == [{'kind':'sample','values':{'get_p':10}}]


def test_generated_program_reads_sensors_without_motor_commands():
    with KT2Sim() as q:
        runtime=Runtime(q)
        token='a'*32
        before=q.target.copy()
        # A call to either method would fail this execution, even for stand().
        q.play=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('motor command'))
        q.update=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('calibration write'))
        assert runtime.execute(telemetry_program(token)), runtime.last_error
        packets=PacketReader(token).feed(runtime.drain_log())
        samples=[p for p in packets if p['kind']=='sample']
        assert len(samples)==10 and packets[-1]['kind']=='end'
        assert samples[-1]['values']['get_az']==pytest.approx(1,abs=.01)
        assert 'play' in packets[0]['q_methods']
        assert q.data.time==pytest.approx(1)
        np.testing.assert_array_equal(q.target,before)
        assert not any(k.startswith('_kt2_sensor_') for k in runtime.globals)


class ScriptedTransport:
    def __init__(self, *, identity=None, fail_logs=False):
        self.identity=identity or {'status':'OK','model':'B4KT2','ver':'V260201'}
        self.requests=[]
        self.reader_code=''
        self.ready=threading.Event()
        self.delivered=False
        self.fail_logs=fail_logs

    def request(self,path,fields=None):
        self.requests.append((path,fields))
        if path=='/ping': return json.dumps(self.identity)
        if path=='/py':
            self.reader_code=fields['code']
            return '{"status":"OK"}'
        if self.fail_logs: raise TimeoutError('link lost')
        if not self.delivered:
            self.delivered=True
            token=self.reader_code.split('@KT2SYNC:')[1].split(':')[0]
            sample={'kind':'sample','values':{'get_r':10,'get_p':-20,'get_y':30,'get_az':1},'device_ms':1234}
            self.ready.set()
            return '@KT2SYNC:'+token+':'+json.dumps(sample)+'\n'
        return ''


def test_connection_identity_gate_live_sample_and_stale_handling():
    transport=ScriptedTransport()
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    try:
        bridge.connect('192.168.4.1')
        assert transport.ready.wait(1)
        # Taking the lock ensures a sample is accepted before inspecting it.
        deadline=time.monotonic()+1
        while bridge.snapshot()['samples']==0 and time.monotonic()<deadline:
            time.sleep(.005)
        s=bridge.snapshot()
        assert s['fresh'] and s['orientation_deg_assumed']==[10,-20,30]
        assert s['joint_feedback'] is None and s['position_feedback'] is None
        with bridge.lock: bridge.received-=3
        assert bridge.snapshot()['status']=='stale'
        assert bridge.snapshot()['orientation_deg_assumed'] is None
        with pytest.raises(RuntimeError): bridge.connect('192.168.4.2')
    finally:
        bridge.close()
    assert bridge.snapshot()['status']=='disconnected'
    assert not bridge.snapshot()['fresh']
    assert not bridge.worker.is_alive()
    assert all(path in ('/ping','/py','/log') for path,_ in transport.requests)


def test_identity_failure_never_submits_a_program():
    transport=ScriptedTransport(identity={'model':'Other'})
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    bridge.connect('192.168.4.1')
    bridge.worker.join(1)
    assert bridge.snapshot()['status']=='error'
    assert transport.requests==[('/ping',None)]


def test_network_failure_is_visible_and_never_retries_program():
    transport=ScriptedTransport(fail_logs=True)
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    bridge.connect('192.168.4.1')
    bridge.worker.join(1)
    assert bridge.snapshot()['status']=='error'
    assert 'link lost' in bridge.snapshot()['error']
    assert sum(path=='/py' for path,_ in transport.requests)==1


def test_orientation_preview_keeps_simulation_state_separate(monkeypatch):
    import mujoco
    captured=[]
    poses=[]
    class Renderer:
        def __init__(self,*args,**kwargs): pass
        def update_scene(self,data,**kwargs):
            captured.append(data.body('shell').xmat.copy())
            poses.append(data.qpos.copy())
        def render(self): return np.zeros((2,2,3),dtype=np.uint8)
        def close(self): pass
    monkeypatch.setattr(mujoco,'Renderer',Renderer)
    with KT2Sim() as q:
        q.sleep(.5)
        before=q.data.qpos.copy()
        before_time=q.data.time
        q.render(orientation_deg=[0,0,90],joint_targets_deg=[-60,-65,80,85])
        np.testing.assert_allclose(captured[-1].reshape(3,3),[[0,-1,0],[1,0,0],[0,0,1]],atol=1e-12)
        np.testing.assert_array_equal(q.data.qpos,before)
        np.testing.assert_allclose(np.rad2deg(poses[-1][7:]),[-60,-65,80,85])
        assert q.data.time==before_time


@pytest.mark.parametrize('action', ['walk_forward','walk_back','stand'])
def test_native_motion_program_runs_one_cycle_and_reports_completion(action):
    token='c'*32
    with KT2Sim() as q:
        runtime=Runtime(q)
        # Match the connected firmware: walk exists, actions.stand does not.
        runtime.modules['actions']=types.SimpleNamespace(walk=runtime.modules['actions'].walk)
        assert runtime.execute(motion_program(token,action)),runtime.last_error
        packets=PacketReader(token).feed(runtime.drain_log())
        assert packets[0]['kind']=='motion_start'
        assert [p['kind'] for p in packets[-2:]]==['motion_done','end']
        samples=[p for p in packets if p['kind']=='sample']
        assert len(samples)==(1 if action=='stand' else 17)
        assert all(p['values'] and not p['errors'] for p in samples)
        assert samples[-1]['joint_targets_deg']==[-75,-75,75,75]
        if action!='stand':
            assert samples[0]['device_ms']<samples[-1]['device_ms']
            assert samples[0]['joint_targets_deg'] is None
        assert q.data.time==pytest.approx(.3 if action=='stand' else .78)
        assert q.target.tolist()==[-75,-75,75,75]


def test_motion_program_reports_device_exception():
    with KT2Sim() as q:
        runtime=Runtime(q)
        def broken(*args,**kwargs): raise ValueError('motor driver unavailable')
        q.play=broken
        assert runtime.execute(motion_program('c'*32,'stand'))
        packets=PacketReader('c'*32).feed(runtime.drain_log())
        assert packets[1]=={'kind':'motion_error','error':'motor driver unavailable'}
        assert packets[-1]['kind']=='end'
    with pytest.raises(ValueError): motion_program('c'*32,'walk_forward); reboot()')


def until(predicate):
    deadline=time.monotonic()+2
    while not predicate():
        if time.monotonic()>deadline: raise AssertionError('Condition not reached')
        time.sleep(.005)


class MotionTransport:
    def __init__(self, *, hold_sensor=False, hold_motion=False, motion_timeout=False, block_post=False, changed_identity=False):
        self.requests=[]
        self.current_code=''
        self.delivered=False
        self.hold_sensor=hold_sensor
        self.hold_motion=hold_motion
        self.release_motion=threading.Event()
        self.motion_finished=False
        self.motion_timeout=motion_timeout
        self.block_post=block_post
        self.changed_identity=changed_identity
        self.motion_started=threading.Event()
        self.release_post=threading.Event()
        self.pings=0

    def request(self,path,fields=None):
        self.requests.append((path,fields))
        if path=='/ping':
            self.pings+=1
            return json.dumps({'v':'OTHER' if self.changed_identity and self.pings>1 else 'B4KT2-V260201'})
        if path.startswith('/api?'):
            return '{"status":"OK"}'
        if path=='/py':
            self.current_code=fields['code']
            self.delivered=False
            self.motion_finished=False
            if '_kt2_motion_' in self.current_code:
                self.motion_started.set()
                if self.block_post and not self.release_post.wait(2): raise TimeoutError('blocked POST')
                if self.motion_timeout: raise TimeoutError('delivery uncertain')
            return '{"status":"OK"}'
        finishing=(self.delivered and '_kt2_motion_' in self.current_code and self.hold_motion
                   and self.release_motion.is_set() and not self.motion_finished)
        if self.delivered and not finishing: return ''
        self.delivered=True
        token=self.current_code.split('@KT2SYNC:')[1].split(':')[0]
        if '_kt2_motion_' in self.current_code:
            packets=[{'kind':'motion_start'},
                     {'kind':'sample','values':{'get_r':5,'get_p':10,'get_y':15},'joint_targets_deg':[-75,-75,75,75]}]
            if not self.hold_motion or finishing:
                packets += [{'kind':'motion_done'},{'kind':'end'}]
                self.motion_finished=True
        else:
            packets=[{'kind':'meta','q_methods':['play','frame'],'imu_methods':['get_p']},
                     {'kind':'sample','values':{'get_r':0,'get_p':0,'get_y':0}}]
            if not self.hold_sensor: packets.append({'kind':'end'})
        return ''.join('@KT2SYNC:'+token+':'+json.dumps(p)+'\n' for p in packets)

    def motion_posts(self):
        return [fields for path,fields in self.requests if path=='/py' and '_kt2_motion_' in fields['code']]


def test_motion_waits_for_sensor_end_runs_once_and_resumes_sensors():
    transport=MotionTransport()
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.01)
    try:
        bridge.connect('192.168.4.1')
        until(lambda:bridge.snapshot()['can_move'])
        bridge.queue_motion('walk_forward')
        until(lambda:bridge.snapshot()['motion']['status']=='completed')
        until(lambda:bridge.snapshot()['can_move'])
        assert len(transport.motion_posts())==1
        assert transport.pings==2
        paths=[path for path,_ in transport.requests]
        second_ping=paths.index('/ping',1)
        assert '/log' in paths[1:second_ping]
    finally: bridge.close()


def test_motion_samples_keep_preview_live_without_enabling_overlapping_commands():
    transport=MotionTransport(hold_motion=True)
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    try:
        bridge.connect('192.168.4.1')
        until(lambda:bridge.snapshot()['can_move'])
        assert not bridge.snapshot()['can_pose']
        with pytest.raises(RuntimeError,match='stand first'):
            bridge.queue_pose([[-60,-60,75,75,.5]])
        bridge.queue_motion('stand')
        until(lambda:bridge.snapshot()['motion']['status']=='running')
        s=bridge.snapshot()
        assert s['status']=='moving' and s['fresh']
        assert s['orientation_deg_assumed']==[5,10,15]
        assert not s['can_move'] and not s['can_pose']
        with pytest.raises(RuntimeError,match='already queued'):
            bridge.queue_pose([[-60,-60,75,75,.5]])
        with bridge.lock: bridge.received-=3
        assert bridge.snapshot()['status']=='moving'
        assert bridge.snapshot()['orientation_deg_assumed'] is None
        transport.release_motion.set()
        until(lambda:bridge.snapshot()['can_pose'])
        bridge.queue_pose([[-60,-60,75,75,.5]])
        until(lambda:len(transport.motion_posts())==2)
        until(lambda:bridge.snapshot()['can_pose'])
        bridge.stop_robot()
        until(lambda:bridge.snapshot()['status']=='stopped')
        assert bridge.snapshot()['joint_targets_deg'] is None
        assert not bridge.snapshot()['can_pose']
    finally: bridge.close()


def test_joint_sequence_emits_intermediate_imu_and_targets_then_holds_final_pose():
    token='d'*32
    frames=[[-65,-70,80,85,.2],[-55,-65,85,80,.1]]
    with KT2Sim() as q:
        runtime=Runtime(q)
        assert runtime.execute(motion_program(token,'sequence',frames,[-75,-75,75,75]))
        packets=PacketReader(token).feed(runtime.drain_log())
        samples=[p for p in packets if p['kind']=='sample']
        assert len(samples)==6
        assert samples[0]['joint_targets_deg']==[-72.5,-73.75,76.25,77.5]
        assert samples[3]['joint_targets_deg']==frames[0][:4]
        assert samples[-1]['joint_targets_deg']==frames[-1][:4]
        assert all(p['values'] and not p['errors'] for p in samples)
        assert [p['device_ms'] for p in samples]==[50,100,150,200,250,300]
        assert q.target.tolist()==frames[-1][:4]
        assert q.data.time==pytest.approx(.3)
        assert [p['kind'] for p in packets[-2:]]==['motion_done','end']


@pytest.mark.parametrize('frames', [None, {}, [], [[0]*5]*33, [[0]*4],
    [[0,0,0,'q.stop()',1]], [[True,0,0,0,1]], [[float('nan'),0,0,0,1]],
    [[float('inf'),0,0,0,1]], [[10**1000,0,0,0,1]], [[91,0,0,0,1]],
    [[-91,0,0,0,1]], [[0,0,0,0,0]], [[0,0,0,0,3.1]], [[0,0,0,0,3]]*6])
def test_pose_validation_rejects_malformed_unbounded_and_non_numeric_commands(frames):
    with pytest.raises(ValueError): validate_frames(frames)


def test_queued_stop_prevents_any_physical_motion_submission():
    transport=MotionTransport(hold_sensor=True)
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    try:
        bridge.connect('192.168.4.1')
        until(lambda:bridge.snapshot()['can_move'])
        bridge.queue_motion('walk_forward')
        with pytest.raises(RuntimeError): bridge.queue_motion('walk_back')
        bridge.stop_robot()
        until(lambda:bridge.snapshot()['motion']['status']=='stop_acknowledged')
        bridge.worker.join(1)
        assert not transport.motion_posts()
        assert any(path=='/api?p=%2Fpy%2Fvm%2Fbreak&v=null' for path,_ in transport.requests)
    finally: bridge.close()


def test_stop_during_motion_post_never_allows_a_later_post():
    transport=MotionTransport(block_post=True)
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    try:
        bridge.connect('192.168.4.1')
        until(lambda:bridge.snapshot()['can_move'])
        bridge.queue_motion('walk_forward')
        assert transport.motion_started.wait(1)
        bridge.stop_robot()
        transport.release_post.set()
        until(lambda:bridge.snapshot()['motion']['status']=='stop_acknowledged')
        bridge.worker.join(1)
        assert len(transport.motion_posts())==1
        assert transport.requests[-1][0].startswith('/api?')
        assert not bridge.snapshot()['can_move']
    finally:
        transport.release_post.set()
        bridge.close()


@pytest.mark.parametrize('changed_identity', [False, True])
def test_failed_motion_is_never_replayed_or_carried_over_to_reconnection(changed_identity):
    transport=MotionTransport(motion_timeout=True,changed_identity=changed_identity)
    bridge=HardwareBridge(transport_factory=lambda host:transport,poll_interval=.005)
    try:
        bridge.connect('192.168.4.1')
        until(lambda:bridge.snapshot()['can_move'])
        bridge.queue_motion('walk_forward')
        bridge.worker.join(1)
        assert bridge.snapshot()['status']=='error'
        assert bridge.snapshot()['motion']['status']=='unconfirmed'
        assert len(transport.motion_posts())==(0 if changed_identity else 1)
        assert bridge.pending_action is None
        with pytest.raises(RuntimeError): bridge.queue_motion('walk_forward')
    finally: bridge.close()
