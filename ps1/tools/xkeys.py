#!/usr/bin/env python3
"""Test input for the headless PS1 instance: XTest key events into its PRIVATE
Xvfb display only (never uinput, so the live arcade's pads are untouched).

  xkeys.py [--display :N] SCRIPT...
Each SCRIPT item: KEY[:MS] (press, hold MS ms, default 120), +KEY / -KEY (hold /
release), 'sleep:MS', 'shot:NAME' (PNG via tools/shot.sh), or 'KEY1,KEY2[:MS]'
(press together, for simultaneous multi-player input). Key names are X keysyms
(Return, Up, z, KP_8, F1, 1 ...). The display defaults to $AVRANA_PS1_HOME/runtime/display.
"""
import ctypes, os, subprocess, sys, time

home = os.environ.get("AVRANA_PS1_HOME", os.path.expanduser("~/avrana-lab/ps1"))
args = sys.argv[1:]
if args[:1] == ["--display"]:
    disp, args = args[1], args[2:]
else:
    run = os.path.join(home, "runtime")
    try:  # only trust runtime/display while the PS1 RetroArch that wrote it is alive
        pid = open(os.path.join(run, "retroarch.pid")).read().strip()
        alive = open(f"/proc/{pid}/comm").read().strip() == "retroarch"
    except OSError:
        alive = False
    if not alive:
        sys.exit("no running PS1 RetroArch (stale runtime files?); refusing to guess a display")
    disp = open(os.path.join(run, "display")).read().strip()
    os.environ["XAUTHORITY"] = open(os.path.join(home, "runtime/xauthority")).read().strip()

x11 = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XStringToKeysym.restype = ctypes.c_ulong
x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
x11.XKeysymToKeycode.restype = ctypes.c_ubyte
x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XFlush.argtypes = [ctypes.c_void_p]
xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
dpy = x11.XOpenDisplay(disp.encode())
if not dpy:
    sys.exit(f"cannot open display {disp}")

def code(name):
    ks = x11.XStringToKeysym(name.encode())
    kc = x11.XKeysymToKeycode(dpy, ks) if ks else 0
    if not kc:
        sys.exit(f"unknown key {name!r}")
    return kc

def key(names, down):
    for n in names:
        xtst.XTestFakeKeyEvent(dpy, code(n), 1 if down else 0, 0)
    x11.XFlush(dpy)

here = os.path.dirname(os.path.abspath(__file__))
for item in args:
    if item.startswith("sleep:"):
        time.sleep(int(item[6:]) / 1000)
    elif item.startswith("shot:"):
        subprocess.run([os.path.join(here, "shot.sh"), item[5:]], check=True)
    elif item[0] in "+-" and len(item) > 1:
        key(item[1:].split(","), item[0] == "+")
    else:
        names, _, ms = item.partition(":")
        key(names.split(","), True)
        time.sleep(int(ms or 120) / 1000)
        key(names.split(","), False)
        time.sleep(0.05)
