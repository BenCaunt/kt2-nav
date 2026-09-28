from actions import ofs_stand

q.play(q.f(0, 0, 0, 0, 0.4, ofs=ofs_stand))
q.play([
    q.frame(-45, -45, 85, 85, 0.4),
    q.frame(-85, -85, 45, 45, 0.4),
], 2, dly=0.2)
q.play(q.frame(0, 0, 0, 0, ofs=ofs_stand))
