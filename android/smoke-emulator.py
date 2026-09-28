"""Black-box signed-app / adb / desktop API smoke check on an emulator only.

Usage: python android/smoke-emulator.py --adb /path/to/adb --serial emulator-5554
Install the release APK first. This never connects to or moves a robot.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from kt2_tracking.receiver import PoseStore, create_app
from kt2_tracking.usb import AndroidUSBBridge


async def check(adb_path, serial):
    if not serial.startswith('emulator-'):
        raise SystemExit('This check is restricted to emulators; no robot hardware is needed.')

    async def adb(*args):
        process = await asyncio.create_subprocess_exec(adb_path, '-s', serial, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await process.communicate()
        if process.returncode:
            raise RuntimeError(err.decode())
        return out.decode()

    await adb('shell', 'am', 'start', '-n', 'com.bencaunt.kt2pose/.MainActivity')
    await asyncio.sleep(.5)
    token = None
    for _ in range(6):
        await adb('shell', 'uiautomator', 'dump', '/sdcard/kt2-smoke.xml')
        xml = await adb('shell', 'cat', '/sdcard/kt2-smoke.xml')
        for node in ET.fromstring(xml).iter('node'):
            match = re.search(r'Pairing code\s+([0-9A-F]{8})', node.get('text', ''))
            if match:
                token = match.group(1)
        if token:
            break
        await adb('shell', 'input', 'swipe', '720', '2450', '720', '450', '350')
    assert token, 'Pairing code not found in app UI'
    store = PoseStore()
    bridge = AndroidUSBBridge(token, store, port=18767, device=serial, adb=adb_path)

    async def eventually(predicate, timeout=10):
        end = asyncio.get_running_loop().time() + timeout
        while not predicate() and asyncio.get_running_loop().time() < end:
            await asyncio.sleep(.1)
        assert predicate(), bridge.snapshot()

    server = TestServer(create_app(token, store, usb=bridge))
    await server.start_server()
    try:
        await eventually(lambda: bridge.snapshot()['fresh'])
        async with ClientSession() as session:
            async with session.get(server.make_url('/api/state')) as response:
                state = await response.json()
                assert response.status == 200 and state['link']['connected']
                assert not state['link']['robot']['armed'] and not state['pose_ready']
            try:
                await bridge.command('walk_forward', require_tracking=False)
            except RuntimeError as e:
                assert 'enable motion' in str(e)
            else:
                raise AssertionError('Disarmed motion was accepted')
            async with session.post(server.make_url('/api/command'), json={'action': 'stop'}) as response:
                result = await response.json()
                assert response.status == 200, result
            await adb('shell', 'input', 'keyevent', 'KEYCODE_HOME')
            await eventually(lambda: not bridge.connected)
            # Simulate adb dropping a forward on unplug; the bridge must restore it.
            await adb('forward', '--remove', 'tcp:18767')
            await adb('shell', 'am', 'start', '-n', 'com.bencaunt.kt2pose/.MainActivity')
            await eventually(lambda: bridge.snapshot()['fresh'])
            assert not bridge.snapshot()['robot']['armed']
        print(json.dumps({'signed_app_usb': 'passed', 'desktop_http_api': 'passed',
            'disarmed_motion_rejection': 'passed', 'background_disconnect': 'passed',
            'forward_recreation_and_reconnect': 'passed', 'physical_robot_contacted': False}))
    finally:
        await server.close()
    assert 'tcp:18767' not in await adb('forward', '--list'), 'Our forward was not cleaned up'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', default='emulator-5554')
    args = parser.parse_args()
    asyncio.run(check(args.adb, args.serial))
