"""Check the real, collapsed Android status-bar window over ADB."""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
parser.add_argument('--adb', default='adb')
parser.add_argument('--expected-height', type=int, default=36)
parser.add_argument('--output', type=Path)
parser.add_argument('--screenshot', type=Path)
args = parser.parse_args()
adb = args.adb

def run(*command):
    result = subprocess.run([str(adb), '-s', args.serial, *command],
                            capture_output=True, timeout=20)
    result.check_returncode()
    return result.stdout

windows = run('shell', 'dumpsys', 'window', 'windows').decode(errors='replace')
match = re.search(r'Window #\d+ Window\{[^\n]* u0 StatusBar\}:\n(.*?)(?=\n  Window #|\Z)',
                  windows, re.S)
block = match.group(1) if match else ''
height = re.search(r'Requested w=\d+ h=(-?\d+)', block)
surface = re.search(r'Surface: shown=(\w+)', block)
report = {
    'serial': args.serial,
    'expected_height_px': args.expected_height,
    'height_px': int(height.group(1)) if height else None,
    'surface_shown': surface.group(1) == 'true' if surface else False,
}
report['passed'] = report['height_px'] == args.expected_height and report['surface_shown']
if args.screenshot:
    screenshot = run('exec-out', 'screencap', '-p')
    assert screenshot.startswith(b'\x89PNG'), 'Invalid screenshot'
    args.screenshot.write_bytes(screenshot)
if args.output:
    args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
