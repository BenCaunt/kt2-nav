from actions import stand, walk
import imu

q.play(stand(q))
q.play(walk(q), 3)
q.play(stand(q))
sleep(0.3)
print("Roll, pitch, yaw:", imu.get_r(), imu.get_p(), imu.get_y())
