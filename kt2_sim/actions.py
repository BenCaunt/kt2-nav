"""Original approximate trajectories using the recovered vendor function names.

These are authored for this model, not decoded vendor gaits. Acrobatics are
joint-space attempts: the base is never teleported or artificially propelled.
"""
import math

ofs_stand = (-75, -75, 75, 75)
ofs_stand_low = (-40, -40, 40, 40)
ofs_head_down = (-45, -45, 85, 85)
ofs_head_up = (-85, -85, 45, 45)


def t_walk(d1, d2, d3, d4, t, T):
    if not math.isfinite(T) or T <= 0:
        raise ValueError("T must be positive and finite")
    phase = 2 * math.pi * t / T
    return tuple(a * math.sin(phase + p) for a, p in zip((d1, d2, d3, d4), (0, math.pi, math.pi / 2, 3 * math.pi / 2)))


def stand(q, *, ofs=ofs_stand, dt=0.3, **kw):
    return [q.f(0, 0, 0, 0, dt, ofs=ofs, **kw)]


def walk(q, x=1, y=1, z=1, *, ofs=ofs_stand, dt=0.03, amplitude=25):
    return [q.f(*t_walk(amplitude, amplitude, amplitude, amplitude, i / 16, 1),
                dt, ofs=ofs, x=x, y=y, z=z) for i in range(1, 17)]


def walk_left(q, *, dt=0.03, ofs=ofs_stand, y=1, x=1):
    frames = []
    for i in range(1, 17):
        phase = 2 * math.pi * i / 16
        angles = [25 * math.sin(phase + p) for p in (0, math.pi, -math.pi / 2, 3 * math.pi / 2)]
        frames.append(q.f(*angles, dt, ofs=ofs, x=x, y=y))
    return frames


def c_pivot(q, angle, **kw):
    """Execute an approximate turn. Returns [] for the vendor's wrapped-call form.

    Both `c_pivot(q, 90)` and `q.play(c_pivot(q, 90))` occur in the recovered UI.
    Heading feedback stops the simulation's approximate turning gait. Turning
    can also translate the body; the real robot's pivot implementation is unknown.
    """
    angle = float(angle)
    if not math.isfinite(angle) or abs(angle) > 720:
        raise ValueError("Pivot request must be within ±720 degrees")
    if angle:
        previous = q.observe()["rpy_deg"][2]
        turned = 0.0
        sign = 1 if angle > 0 else -1
        for _ in range(160):
            if sign * turned >= abs(angle) - 3:
                break
            q.play(walk_left(q, y=sign, **kw))
            heading = q.observe()["rpy_deg"][2]
            turned += (heading - previous + 180) % 360 - 180
            previous = heading
        else:
            raise TimeoutError("Simulated pivot did not reach the target heading")
        q.play(stand(q))
    return []


def _poses(q, poses, *, dt=0.18, x=1, y=1, z=1, ofs=None):
    return [q.f(*pose, dt, x=x, y=y, z=z, ofs=ofs) for pose in poses]


def xtrans(q, **kw):
    return _poses(q, [(-95,-95,55,55), (-55,-55,95,95), ofs_stand], **kw)


def seesaw(q, **kw):
    return _poses(q, [ofs_head_down, ofs_head_up, ofs_stand], **kw)


def spring(q, **kw):
    return _poses(q, [ofs_stand_low, (-90,-90,90,90), ofs_stand_low, ofs_stand], **kw)


def bark(q, **kw):
    return _poses(q, [ofs_head_down, (-95,-95,50,50), ofs_stand], **kw)


def shake_hand(q, **kw):
    return _poses(q, [(-85,-90,60,90), (-20,-90,60,90), (-45,-90,60,90), (-20,-90,60,90), ofs_stand], **kw)


def push(q, **kw):
    return _poses(q, [(-115,-115,45,45), (-35,-35,100,100), ofs_stand], **kw)


def pounce(q, dt=0.09, **kw):
    return _poses(q, [(-35,-35,35,35), (-115,-115,105,105), ofs_stand], dt=dt, **kw)


def bound(q, **kw):
    return pounce(q, **kw)


def left_punch(q, **kw):
    return _poses(q, [(-90,-85,50,95), (20,-85,50,95), (-110,-85,50,95), ofs_stand], **kw)


def right_punch(q, y=1, **kw):
    return left_punch(q, y=-y, **kw)


def left_kick(q, **kw):
    return _poses(q, [(-85,-85,40,90), (-85,-85,130,90), ofs_stand], **kw)


def right_kick(q, y=1, **kw):
    return left_kick(q, y=-y, **kw)


def left_split(q, **kw):
    return _poses(q, [(-20,-90,20,90), (-110,-90,110,90), ofs_stand], **kw)


def right_split(q, y=1, **kw):
    return left_split(q, y=-y, **kw)


def flip(q, dt=0.07, **kw):
    return _poses(q, [(-35,-35,40,40), (-145,-145,145,145), (75,75,75,75), ofs_stand], dt=dt, **kw)


def back_flip(q, x=1, **kw):
    return flip(q, x=-x, **kw)


def folded_flip(q, **kw):
    return _poses(q, [(-145,-145,145,145)], **kw) + flip(q, **kw)


def double_flip(q, **kw):
    return flip(q, **kw) * 2


def left_flip(q, dt=0.08, **kw):
    return _poses(q, [(-35,-90,35,90), (-145,-15,145,15), (80,-75,-80,75), ofs_stand], dt=dt, **kw)


def right_flip(q, y=1, **kw):
    return left_flip(q, y=-y, **kw)


def left_back_flip(q, x=1, **kw):
    return left_flip(q, x=-x, **kw)


def right_back_flip(q, x=1, y=1, **kw):
    return left_flip(q, x=-x, y=-y, **kw)


def turn_over(q, **kw):
    return left_flip(q, **kw)


def slide(q, **kw):
    return _poses(q, [(-20,-20,20,20), (-60,-60,60,60), (-20,-20,20,20), ofs_stand], **kw)


def throw(q, **kw):
    return push(q, **kw) + pounce(q, **kw)


def faint(q, **kw):
    return _poses(q, [(0,0,0,0)], **kw)


def one_key_reset(q):
    """Return joints to stand; does not reset or teleport the MuJoCo base."""
    q.play(stand(q))


def assembly_check(q):
    q.play(q.f(0,0,0,0,0.3,auto=0))
    for i, sign in enumerate((1,1,-1,-1)):
        pose = [0,0,0,0]
        pose[i] = sign * 30
        q.play([q.f(*pose,auto=0), q.f(0,0,0,0,auto=0)])
