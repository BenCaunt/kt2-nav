import math

import numpy as np
import pytest

from kt2_sim import Frame, KT2Sim
from kt2_sim import actions
from kt2_sim.runtime import Runtime


@pytest.fixture
def q():
    with KT2Sim() as robot:
        yield robot


def test_free_robot_stands_on_real_contacts(q):
    assert q.model.nq == 11 and q.model.nu == 4
    assert sum(q.model.body_mass) == pytest.approx(0.16)
    q.sleep(2)
    state = q.observe()
    assert 0.045 < state["position"][2] < 0.052
    assert all(state["feet_contact"].values())
    assert max(abs(v) for v in state["rpy_deg"][:2]) < 1
    assert state["accel_m_s2"][2] == pytest.approx(9.81, abs=0.05)


@pytest.mark.parametrize("direction", [1, -1])
def test_walk_direction_without_base_injection(q, direction):
    q.sleep(0.5)
    start = q.data.qpos[:3].copy()
    q.play(actions.walk(q, x=direction), 6)
    q.play(actions.stand(q))
    q.sleep(0.3)
    state = q.observe()
    assert direction * (state["position"][0] - start[0]) > 0.12
    assert abs(state["position"][1] - start[1]) < 0.07
    assert abs(state["rpy_deg"][0]) < 15
    assert abs(state["rpy_deg"][1]) < 15
    assert not np.any(q.data.qfrc_applied)
    assert not np.any(q.data.xfrc_applied)


def test_frame_order_symmetry_repeat_and_timing(q):
    original = q.f(-10, -20, 30, 40, 0.1, 0.02)
    assert q.f(*original.angles, x=-1).angles == (-30, -40, 10, 20)
    assert q.f(*original.angles, y=-1).angles == (-20, -10, 40, 30)
    frame = q.f(1, 2, 3, 4, 0.1, 0.02, ofs=actions.ofs_stand)
    assert frame.angles == (-74, -73, 78, 79)
    q.play([frame], 3, dly=0.04)
    assert q.data.time == pytest.approx(0.48)
    assert q.target.tolist() == list(frame.angles)
    q.play(q.frame(-75,-75,75,75,0))
    assert q.data.time == pytest.approx(0.482)


def test_limits_fail_before_partial_execution(q):
    with pytest.raises(ValueError):
        q.play([q.f(-75,-75,75,75), Frame((200,0,0,0))])
    assert q.data.time == 0
    for args in [(math.nan,0,0,0), (0,0,0,0,-1), (0,0,0,0,math.inf)]:
        with pytest.raises(ValueError):
            q.f(*args)


def test_servo_force_limit_and_slew(q):
    before = q.data.ctrl.copy()
    q.play(q.f(0,0,0,0,0))
    assert np.max(np.abs(q.data.ctrl - before)) <= math.radians(600) * q.model.opt.timestep + 1e-9
    assert np.max(np.abs(q.data.actuator_force)) <= 0.120001


def test_original_vendor_snippet_and_module_isolation(q):
    r = Runtime(q)
    assert r.execute("from actions import walk\nq.play(walk(q), 3)\nimport imu\nprint(imu.get_p())")
    assert q.data.time == pytest.approx(1.44)
    assert r.drain_log().strip()
    assert "actions" not in __import__("sys").modules
    with KT2Sim() as second:
        other = Runtime(second)
        assert other.execute("import imu\nfrom time import sleep\nsleep(.2)\nled.on(0xff0000)")
        assert second.data.time == pytest.approx(.2)
        assert q.data.time == pytest.approx(1.44)
        assert second.led_color == (1,0,0)


def test_python_exception_and_timeout_leave_runtime_usable(q):
    r = Runtime(q, max_wall_seconds=.05)
    assert not r.execute("while True: pass")
    assert "time limit" in r.last_error
    assert not r.busy
    assert r.execute("print('recovered')")
    assert "recovered" in r.drain_log()
    assert not r.execute("q.missing_method()")
    assert "AttributeError" in r.last_error


def test_imu_reset_changes_reference_not_physics(q):
    r = Runtime(q)
    angle = math.radians(35)
    q.data.qpos[3:7] = [math.cos(angle / 2),0,0,math.sin(angle / 2)]
    import mujoco
    mujoco.mj_forward(q.model,q.data)
    assert r.imu.get_y() == pytest.approx(35)
    before = q.data.qpos.copy()
    r.imu.reset_y()
    assert r.imu.get_y() == pytest.approx(0)
    np.testing.assert_array_equal(before, q.data.qpos)


@pytest.mark.parametrize("name", [
    "stand", "walk", "xtrans", "seesaw", "spring", "bark", "shake_hand", "push", "pounce",
    "turn_over", "flip", "folded_flip", "left_punch", "right_punch", "slide", "left_split",
    "right_split", "throw", "left_back_flip", "right_back_flip", "double_flip", "left_flip",
    "right_flip", "back_flip", "left_kick", "right_kick", "bound", "faint",
])
def test_recovered_action_names_generate_executable_frames(q, name):
    q.play(getattr(actions,name)(q))
    assert q.data.time > 0
    assert np.isfinite(q.data.qpos).all()


def test_pivot_supports_direct_and_wrapped_forms(q):
    q.sleep(.5)
    before = q.observe()["rpy_deg"][2]
    q.play(actions.c_pivot(q,30))
    after = q.observe()["rpy_deg"][2]
    assert 20 < after - before < 45
