from contextlib import contextmanager
import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from kt2_sim import KT2Sim
from kt2_sim.runtime import Runtime
from kt2_sim.server import Controller, make_server


@contextmanager
def service():
    with KT2Sim() as q:
        runtime=Runtime(q)
        c=Controller(runtime)
        server=make_server(c,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield c,f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown();server.server_close();thread.join(2)


def post(base,path,fields=None,headers=None,raw=None):
    req=Request(base+path,data=raw if raw is not None else urlencode(fields or {}).encode(),
                headers={"Content-Type":"application/x-www-form-urlencoded",**(headers or {})})
    return urlopen(req,timeout=3)


def test_firmware_http_flow_and_busy_response():
    with service() as (c,base):
        assert json.load(urlopen(base+'/ping'))['model']=='B4KT2'
        with post(base,'/py',{'code':'from actions import walk\nq.play(walk(q), 3)\nprint("done")'}) as r:
            assert json.load(r)['status']=='OK'
        with pytest.raises(HTTPError) as e:
            post(base,'/py',{'code':'print("second")'})
        assert e.value.code==409
        c.advance()
        assert c.runtime.q.data.time==pytest.approx(1.44)
        assert b'done' in urlopen(base+'/log').read()
        assert urlopen(base+'/log').read()==b''


def test_stop_cancels_even_queued_program():
    with service() as (c,base):
        post(base,'/py',{'code':'while True: pass'}).close()
        post(base,'/api',{'p':'/py/vm/break'}).close()
        c.advance()
        assert 'stopped' in c.runtime.last_error
        assert not c.pending


def test_scene_reset_clears_error_and_resumes_from_origin():
    with service() as (c,base):
        post(base,'/py',{'code':'raise ValueError("example")'}).close()
        c.advance()
        assert c.runtime.last_error
        post(base,'/sim/reset').close()
        c.advance()
        assert c.runtime.last_error is None
        assert c.runtime.q.data.time == 0
        assert c.state['position'][:2] == [0,0]


def test_invalid_program_origin_and_unimplemented_endpoint():
    with service() as (c,base):
        for path,fields,headers,status in [
            ('/py',{'code':'if:'},{},400),
            ('/py',{'code':'print(1)'},{'Origin':'https://example.com'},403),
            ('/api',{'p':'/sys/erase'},{},501),
        ]:
            with pytest.raises(HTTPError) as e: post(base,path,fields,headers)
            assert e.value.code==status
        assert not c.pending and c.runtime.q.data.time==0


def test_virtual_files_never_touch_host_filesystem():
    with service() as (c,base):
        post(base,'/file?path=/my/demo.py',raw=b'print(42)').close()
        assert urlopen(base+'/file?path=/my/demo.py').read()==b'print(42)'
        assert c.files=={'/my/demo.py':'print(42)'}
        with pytest.raises(HTTPError) as e:
            post(base,'/file?path=/my/../../outside',raw=b'bad')
        assert e.value.code==400


def test_hardware_pose_route_validates_frames_and_connection_without_moving_simulator():
    with service() as (c,base):
        for payload in ('not-json','[]','[[0,0,0,0,0]]','[[91,0,0,0,1]]','[[NaN,0,0,0,1]]'):
            with pytest.raises(HTTPError) as e:
                post(base,'/hardware/pose',{'frames':payload})
            assert e.value.code==400
        with pytest.raises(HTTPError) as e:
            post(base,'/hardware/pose',{'frames':'[[-60,-60,75,75,0.5]]'})
        assert e.value.code==409
        assert c.runtime.q.data.time==0


def test_hardware_routes_default_to_disconnected_and_reject_non_robot_targets():
    with service() as (c,base):
        assert json.load(urlopen(base+'/hardware/state'))['status']=='disconnected'
        for host in ('127.0.0.1','8.8.8.8','robot.example'):
            with pytest.raises(HTTPError) as e:
                post(base,'/hardware/connect',{'host':host})
            assert e.value.code==400
        with pytest.raises(HTTPError) as e:
            post(base,'/hardware/py',{'code':'q.play([])'})
        assert e.value.code==404
        post(base,'/hardware/disconnect').close()
        assert c.runtime.q.data.time==0
        with pytest.raises(HTTPError) as e:
            post(base,'/hardware/action',{'action':'walk_forward'})
        assert e.value.code==409
        with pytest.raises(HTTPError) as e:
            post(base,'/hardware/action',{'action':'flip'})
        assert e.value.code==400
