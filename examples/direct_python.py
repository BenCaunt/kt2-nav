"""Use as an ordinary Python library, outside the compatibility runner."""
from kt2_sim import KT2Sim
from kt2_sim.actions import walk, stand

with KT2Sim() as q:
    q.play(stand(q))
    q.play(walk(q), 3)
    print(q.observe())
