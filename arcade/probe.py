#!/usr/bin/env python3
"""Reproducible gates before building the Gauntlet streaming service."""
import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent


def run(args, timeout=90, env=None):
    start = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall = time.monotonic() - start
    return dict(command=args, returncode=result.returncode, wall_seconds=wall,
                cpu_seconds=after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                stdout=result.stdout, stderr=result.stderr)


def mame_command():
    binary = shutil.which('mame') or '/usr/games/mame'
    if not Path(binary).exists():
        raise SystemExit('MAME is not installed. Run install-dependencies.sh first.')
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['encode', 'verify', 'benchmark'])
    parser.add_argument('--rompath', default='/srv/avrana/roms/arcade')
    parser.add_argument('--game', default='gaunt2')
    args = parser.parse_args()
    if args.mode == 'encode':
        if not shutil.which('ffmpeg'):
            raise SystemExit('FFmpeg is not installed.')
        # Synthetic video tests the real hardware encoder, not Gauntlet speed.
        results = []
        for width, height in [(640, 480), (960, 720)]:
            results.append(run(['ffmpeg', '-hide_banner', '-nostdin', '-f', 'lavfi',
                '-i', f'testsrc2=size={width}x{height}:rate=60', '-frames:v', '600',
                '-an', '-c:v', 'h264_v4l2m2m', '-b:v', '2500k', '-g', '60',
                '-bf', '0', '-pix_fmt', 'yuv420p', '-f', 'null', '-']))
        # Runtime registration matters: finding a kernel device alone is insufficient.
        if shutil.which('gst-inspect-1.0'):
            results.append(run(['gst-inspect-1.0', 'v4l2h264enc']))
            results.append(run(['gst-inspect-1.0', 'webrtcbin']))
    else:
        rompath = str(Path(args.rompath).resolve())
        command = [mame_command(), '-noreadconfig', '-rompath', rompath]
        verified = run(command + ['-verifyroms', args.game])
        results = [verified]
        if args.mode == 'benchmark' and verified['returncode'] == 0:
            for directory in ['cfg', 'nvram', 'state', 'snap', 'diff']:
                (ROOT / 'runtime' / directory).mkdir(parents=True, exist_ok=True)
            for option, directory in [('cfg_directory', 'cfg'), ('nvram_directory', 'nvram'),
                                       ('state_directory', 'state'), ('snapshot_directory', 'snap'),
                                       ('diff_directory', 'diff')]:
                command += ['-' + option, str(ROOT / 'runtime' / directory)]
            # -bench is unthrottled with video/sound disabled: CPU headroom only.
            results.append(run(command + [args.game, '-bench', '30'], env={**os.environ, 'SDL_VIDEODRIVER': 'dummy'}))
    report = {'mode': args.mode, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'results': results,
              'notes': 'CPU is process CPU time, not end-to-end latency. No viewer scaling claim.'}
    output = ROOT / 'evidence' / (args.mode + '-' + str(time.time_ns()) + '.json')
    output.write_text(json.dumps(report, indent=2) + '\n')
    for result in results:
        print(' '.join(result['command']))
        print(result['stdout'][-3500:] + result['stderr'][-3500:])
        print('Exit:', result['returncode'], 'Wall seconds:', round(result['wall_seconds'], 2))
    print('Saved:', output)
    raise SystemExit(int(any(result['returncode'] for result in results)))


if __name__ == '__main__':
    main()
