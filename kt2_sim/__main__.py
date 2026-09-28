import argparse
import json
import os
from pathlib import Path
import sys

from .robot import KT2Sim, SimulationStopped
from .runtime import Runtime

DEMO = """import actions
import imu
led.on(0x2dd4bf)
q.play(actions.stand(q))
q.play(actions.walk(q), 5)
q.play(actions.stand(q))
sleep(0.4)
led.on(0x60a5fa)
q.play(actions.seesaw(q), 2)
q.play(actions.shake_hand(q))
q.play(actions.stand(q))
sleep(0.5)
print('Position:', q.observe()['position'])
print('Pitch:', imu.get_p())
"""


def main():
    parser = argparse.ArgumentParser(description="KT2 MuJoCo simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run a KT2 Python file (or built-in demo)")
    run.add_argument("script", nargs="?", type=Path)
    run.add_argument("--view", action="store_true", help="Native viewer; automatically uses mjpython on macOS")
    run.add_argument("--record", type=Path, help="Save an MP4")
    run.add_argument("--snapshot", type=Path, help="Save final PNG")
    run.add_argument("--state", type=Path, help="Save final state JSON")
    run.add_argument("--hold", type=float, default=0, help="Additional simulated seconds at the end")
    web = sub.add_parser("serve", help="Local HTTP API and interactive workbench")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-render", action="store_true", help="HTTP API without camera images")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import serve
        serve(Runtime(KT2Sim(realtime=True)), port=args.port, render=not args.no_render)
        return
    if args.view and sys.platform == "darwin" and not os.environ.get("MJPYTHON_BIN"):
        # Cocoa needs MuJoCo's main-thread trampoline. Standalone uv Python
        # also needs its real lib directory, rather than the venv symlink's.
        launcher = Path(sys.executable).parent / "mjpython"
        if not launcher.exists():
            parser.error("Native viewing requires the mjpython launcher from the mujoco package")
        env = os.environ.copy()
        fallback = env.get("DYLD_FALLBACK_LIBRARY_PATH", "/usr/local/lib:/usr/lib")
        env["DYLD_FALLBACK_LIBRARY_PATH"] = str(Path(sys.base_prefix) / "lib") + ":" + fallback
        os.execve(launcher, [str(launcher), "-m", "kt2_sim", *sys.argv[1:]], env)
    code = args.script.read_text() if args.script else DEMO
    writer = None
    with KT2Sim(realtime=args.view) as q:
        if args.view:
            import mujoco.viewer
            q.viewer = mujoco.viewer.launch_passive(q.model, q.data, show_left_ui=False, show_right_ui=False)
            q.viewer.cam.distance = 0.3
            q.viewer.cam.azimuth = 135
            q.viewer.cam.elevation = -24
        if args.record:
            import imageio.v2 as imageio
            args.record.parent.mkdir(parents=True, exist_ok=True)
            writer = imageio.get_writer(str(args.record), fps=30, codec="libx264", quality=8)
            q.on_step = lambda robot: writer.append_data(robot.render())
        try:
            runtime = Runtime(q, max_wall_seconds=120)
            success = runtime.execute(code, str(args.script) if args.script else "<demo>")
            print(runtime.drain_log(), end="")
            q.sleep(args.hold)
            state = q.observe()
            print(json.dumps(state, indent=2))
            if args.snapshot:
                from PIL import Image
                args.snapshot.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(q.render()).save(args.snapshot)
            if args.state:
                args.state.parent.mkdir(parents=True, exist_ok=True)
                args.state.write_text(json.dumps(state, indent=2) + "\n")
            if not success:
                sys.exit(1)
        except SimulationStopped:
            pass
        finally:
            if writer:
                writer.close()


if __name__ == "__main__":
    main()
