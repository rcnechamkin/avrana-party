#!/usr/bin/env python3
"""PS1 on the arcade's shared stream: ONE RetroArch/PCSX-ReARMed session, ONE
hardware H.264 encode and ONE Opus encode (arcade/stream.py), the same encoded
buffers fanned out to every connected phone.

Video is shared; input is individual. Each phone either owns exactly one
server-assigned controller slot (slot N = RetroArch user N) or watches. A slot's
button mask is replayed as XTest key events from that slot's fixed key bank into
the PS1 instance's PRIVATE Xvfb display (mode-xvfb.cfg binds the banks). No input
devices are created, so nothing can leak into the live arcade RetroArch, and a
client can never name a key, a device or another player's slot.

  stream_ps1.py <worms|bomberman> [--host ADDR ...] [--port 8198] [--capture 320x240]
"""
import argparse
import asyncio
import ctypes
import errno
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'arcade'))
import stream  # noqa: E402  arcade/stream.py: capture/encode/fanout machinery
from stream import Gst, GstWebRTC, GstSdp, web, log  # noqa: E402

PS1_HOME = Path(os.environ.get('AVRANA_PS1_HOME', Path.home() / 'avrana-lab/ps1'))
RUN = PS1_HOME / 'runtime'
stream.ROOT = PS1_HOME  # client-stats.jsonl / webrtc samples land in PS1_HOME/runtime
_AP = stream.ap_addresses()
stream.ap_addresses = lambda: _AP  # stream.summarize() would run `ip` per peer per second

# Controller slots per title come from the data profiles in ps1/titles/ (profiles.py).
# E.g. Worms is hot-seat (only port 1 is read), so one phone holds the pad and everyone
# else watches; Bomberman uses the Multitap on port 2 (user 1 = port 1, users 2-4 = 2A-2C).
sys.path.insert(0, str(HERE))
import profiles  # noqa: E402
GAMES = profiles.stream_slots()

# Bit order of the client's 14-bit button mask (PS1 digital pad).
BUTTONS = ('up', 'down', 'left', 'right', 'cross', 'circle', 'square', 'triangle',
           'l1', 'r1', 'l2', 'r2', 'start', 'select')
# X keysyms per slot, in BUTTONS order. MUST match input_playerN_* in mode-xvfb.cfg.
# Never use modifiers, scroll_lock (hotkey enable), num_lock or caps_lock here.
BANKS = (
    ('Up', 'Down', 'Left', 'Right', 'z', 'x', 'a', 's', 'q', 'w', 'e', 'r', 'Return', 'Shift_R'),
    ('t', 'g', 'f', 'h', 'v', 'b', 'n', 'm', 'y', 'u', 'i', 'o', '1', '2'),
    ('KP_8', 'KP_5', 'KP_4', 'KP_6', 'KP_1', 'KP_2', 'KP_7', 'KP_9', 'KP_0', 'KP_Decimal',
     'KP_Divide', 'KP_Multiply', 'KP_Enter', 'KP_Add'),
    ('F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F11', 'F12', 'Prior', 'Next', 'F9', 'F10'),
)
MASK_LIMIT = 1 << len(BUTTONS)
assert profiles.MAX_SLOTS <= len(BANKS), 'a profile could ask for more slots than there are key banks'
MIN_HOLD = 0.040      # RetroArch polls the keymap once per frame; shorter taps vanish.
STALE = 0.3           # release a slot's buttons if its phone goes quiet (as the arcade)
GRACE = 30.0          # a disconnected player's slot stays reserved for its token
RATE_LIMIT = 120      # messages/s per socket: beyond this, state messages are dropped
FLOOD_LIMIT = 1200    # messages/s per socket that close it (Wi-Fi/tunnels burst, so be lenient)
HELLO_TIMEOUT = 5.0   # s a new socket has to send its hello before it is closed


def parse_hello(text):
    """The first message on every socket: {"type": "hello", "role": "play"|"watch", "token": str|null}.
    Returns (watch, token). The token travels here, never in the URL, so it can't end up in an
    access log (nginx logs query strings). Raises ValueError on anything else."""
    if not isinstance(text, str) or len(text) > 512:
        raise ValueError('hello must be a short text message')
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('type') != 'hello':
        raise ValueError('first message must be a hello')
    role, token = data.get('role'), data.get('token')
    if role not in ('play', 'watch'):
        raise ValueError('role must be play or watch')
    if token is not None and not isinstance(token, str):
        raise ValueError('token must be a string or null')
    return role == 'watch', (None if role == 'watch' else token)


def die_with_parent():
    """In the run-ps1.sh child: SIGTERM it if this server dies, even by SIGKILL or a
    crash, so its trap stops RetroArch/Xvfb/Pulse instead of leaving orphans."""
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL('libc.so.6', use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


class X11:
    """The one XTest connection, to the PS1 instance's private display only: the
    display and its cookie come from files our own run-ps1.sh child wrote."""
    def __init__(self, display, xauthority):
        os.environ['XAUTHORITY'] = xauthority
        self.x = ctypes.CDLL('libX11.so.6')
        self.tst = ctypes.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.tst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.dpy = self.x.XOpenDisplay(display.encode())
        if not self.dpy:
            raise RuntimeError(f'cannot open PS1 display {display}')

    def keycode(self, name):
        code = self.x.XKeysymToKeycode(self.dpy, self.x.XStringToKeysym(name.encode()))
        if not code:
            raise RuntimeError(f'no keycode for {name}')
        return code

    def key(self, code, down):
        self.tst.XTestFakeKeyEvent(self.dpy, code, int(down), 0)

    def flush(self):
        self.x.XFlush(self.dpy)

    def close(self):
        self.x.XCloseDisplay(self.dpy)


class XTestPad:
    """One controller slot. Only ever touches its own bank of keycodes."""
    def __init__(self, x11, slot, loop):
        self.x11, self.loop = x11, loop
        self.codes = [x11.keycode(k) for k in BANKS[slot]]
        self.mask = 0            # what the owner wants held
        self.down = 0            # what is actually held in the X server
        self.pressed_at = [0.0] * len(BUTTONS)
        self.updated = time.monotonic()
        self.timer = None
        self.device = self       # stream.Stream.cleanup() calls pad.device.close()
        self.release_all()

    def set(self, mask):
        self.mask = mask
        self.updated = time.monotonic()
        self.apply()

    def apply(self):
        now = time.monotonic()
        wait = None
        for bit, code in enumerate(self.codes):
            want, have = self.mask >> bit & 1, self.down >> bit & 1
            if want and not have:
                self.x11.key(code, True)
                self.down |= 1 << bit
                self.pressed_at[bit] = now
            elif have and not want:
                left = self.pressed_at[bit] + MIN_HOLD - now
                if left > 0:
                    wait = left if wait is None else min(wait, left)
                    continue
                self.x11.key(code, False)
                self.down &= ~(1 << bit)
        self.x11.flush()
        if wait is not None and self.timer is None:
            self.timer = self.loop.call_later(wait, self.expire)

    def expire(self):
        self.timer = None
        self.apply()

    def release_all(self):
        """Unconditional: also clears keys a crashed bridge may have left down."""
        self.mask = self.down = 0
        for code in self.codes:
            self.x11.key(code, False)
        self.x11.flush()

    # stream.Stream.cleanup() compatibility
    def update(self, _values):
        self.release_all()

    def close(self):
        if self.timer:
            self.timer.cancel()
        self.release_all()


class PS1Stream(stream.Stream):
    def __init__(self, game, capture=(640, 480)):
        super().__init__()
        self.game = game
        self.capture = capture                # the private screen = the encoded video's size
        self.players = GAMES[game]
        self.owners = [None] * self.players   # slot -> dict(token, ws, grace)
        self.x11 = None

    async def startup(self, app):
        try:
            await self.start_session()
        except BaseException:
            await self.cleanup(app)   # aiohttp skips on_cleanup when startup fails
            raise

    def own_retroarch(self, env):
        """True once tools/ps1-pid.sh proves the PS1 RetroArch's identity AND it runs in
        the session of OUR run-ps1.sh child, so the runtime/display of a stale or
        foreign instance (possibly the arcade's display) is never captured."""
        try:  # /proc reads of a stuck process can stall: never hang startup on them
            r = subprocess.run([str(HERE / 'tools' / 'ps1-pid.sh')], env=env,
                               capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            return False
        if r.returncode:
            return False
        try:  # /proc/PID/stat fields after the last ") ": state ppid pgrp session ...
            session = int(Path(f'/proc/{r.stdout.strip()}/stat').read_text().rsplit(') ', 1)[1].split()[3])
        except (OSError, IndexError, ValueError):
            return False
        return session == self.emulator.pid   # start_new_session=True: it leads its own session

    async def start_session(self):
        self.loop = asyncio.get_running_loop()
        # Never delete runtime files here: until run-ps1.sh holds the lock they may belong
        # to a running instance. Stale ones are ignored below and removed under the lock.
        env = dict(os.environ, AVRANA_PS1_VIDEO='xvfb', AVRANA_PS1_HOME=str(PS1_HOME),
                   AVRANA_PS1_CAPTURE='%dx%d' % self.capture)
        self.emulator_log = open(RUN / 'logs' / f'launcher-{self.game}.out', 'w')
        # run-ps1.sh owns preflight, the single-instance lock, private Xvfb + Pulse.
        self.emulator = subprocess.Popen([str(HERE / 'run-ps1.sh'), self.game], env=env,
                                         stdout=self.emulator_log, stderr=subprocess.STDOUT,
                                         start_new_session=True, preexec_fn=die_with_parent)
        for _ in range(100):
            if self.emulator.poll() is not None:
                raise RuntimeError(f'run-ps1.sh exited; see {self.emulator_log.name}')
            if self.own_retroarch(env):
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError('PS1 display did not appear')
        display = (RUN / 'display').read_text().strip()
        self.x11 = X11(display, (RUN / 'xauthority').read_text().strip())
        self.pads = [XTestPad(self.x11, slot, self.loop) for slot in range(self.players)]
        await asyncio.sleep(2)  # let RetroArch map its window before capture starts
        self.pipeline = Gst.parse_launch(
            f'ximagesrc display-name={display} use-damage=false show-pointer=false ! '
            'video/x-raw,framerate=60/1 ! videoconvert ! video/x-raw,format=I420 ! '
            'v4l2h264enc name=video_encoder extra-controls="controls,video_bitrate=2500000,'
            'h264_i_frame_period=60,repeat_sequence_header=1" ! '
            'video/x-h264,profile=constrained-baseline,level=(string)3.1 ! '
            'h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! '
            'appsink name=video_out emit-signals=true sync=false max-buffers=2 drop=true '
            f'pulsesrc server=unix:{RUN}/pulse/native device=avrana_ps1.monitor ! '
            'audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! '
            'opusenc bitrate=64000 frame-size=20 ! '  # 20 ms: half the packets per viewer
            'appsink name=audio_out emit-signals=true sync=false max-buffers=4 drop=true')
        for media in ('video', 'audio'):
            self.pipeline.get_by_name(media + '_out').connect('new-sample', self.distribute, media)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Could not start capture pipeline')
        self.monitor = asyncio.create_task(self.watch())
        log.info('PS1 %s streaming: %d controller slot(s), display %s', self.game, self.players, display)

    async def watch(self):
        while True:
            await asyncio.sleep(0.1)
            for pad in self.pads:
                if pad.mask and time.monotonic() - pad.updated > STALE:
                    pad.set(0)
            msg = self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if msg:
                err, debug = msg.parse_error()
                self.error = str(err)
                log.error('Pipeline error: %s %s', err, debug)
            if self.emulator.poll() is not None:
                self.error = 'Emulator exited'
            if self.error:
                for ws in list(self.peers):
                    await ws.close(code=1011, message=b'Stream stopped')
                # Unlike the arcade, exit so a supervisor (or the operator) sees it.
                os.kill(os.getpid(), signal.SIGTERM)
                return

    # --- controller ownership -------------------------------------------------
    def claim(self, ws, token, watch):
        """Return (slot or None, token). Slots come only from this table."""
        if watch:
            return None, None
        if isinstance(token, str) and 8 <= len(token) <= 64:
            for slot, owner in enumerate(self.owners):
                if owner and hmac.compare_digest(owner['token'].encode(), token.encode()):
                    old = owner['ws']
                    if owner['grace']:
                        owner['grace'].cancel()
                        owner['grace'] = None
                    owner['ws'] = ws
                    if old is not None and not old.closed:  # one socket per token
                        asyncio.ensure_future(old.close(code=4001, message=b'Replaced by a newer connection'))
                    self.pads[slot].release_all()
                    return slot, owner['token']
        slot = next((s for s, o in enumerate(self.owners) if o is None), None)
        if slot is None:
            return None, None       # full: watch instead of being refused
        token = secrets.token_urlsafe(16)
        self.owners[slot] = dict(token=token, ws=ws, grace=None)
        self.pads[slot].release_all()
        return slot, token

    def release(self, slot, ws):
        owner = self.owners[slot]
        if owner and owner['ws'] is ws:    # not already taken over by a reconnect
            self.pads[slot].set(0)
            owner['ws'] = None
            owner['grace'] = self.loop.call_later(GRACE, self.expire_slot, slot, owner['token'])

    def leave(self, slot, ws):
        """Explicit Leave from the slot's current socket: free it now, with no grace period.
        (A dropped connection keeps the slot for GRACE seconds so a reload can reclaim it; a
        player who pressed Leave has given the token up, so holding the slot would only block
        the next player — for Worms, the only pad.)"""
        owner = self.owners[slot]
        if not owner or owner['ws'] is not ws:
            return False                # a replaced socket can't release the new owner's slot
        if owner['grace']:
            owner['grace'].cancel()
        self.owners[slot] = None
        self.pads[slot].release_all()
        log.info('Slot %d released by its player', slot + 1)
        return True

    def expire_slot(self, slot, token):
        owner = self.owners[slot]
        if owner and owner['token'] == token and owner['ws'] is None:
            self.owners[slot] = None
            self.pads[slot].release_all()
            log.info('Slot %d released after grace period', slot + 1)

    async def read_hello(self, ws):
        """Wait for the socket's hello; close it (1008) on timeout or anything else."""
        try:
            message = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT)
            if message.type != web.WSMsgType.TEXT:
                raise ValueError('hello must be text')
            return parse_hello(message.data)
        except (asyncio.TimeoutError, ValueError) as e:     # json errors are ValueErrors
            await ws.close(code=1008, message=f'Bad hello: {e}'.encode()[:120])
            return None

    async def websocket(self, request):
        if request.headers.get('Origin') != 'http://' + request.host:
            raise web.HTTPForbidden()
        if self.error:
            raise web.HTTPServiceUnavailable(text='Stream unavailable')
        ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=5)
        await ws.prepare(request)
        hello = await self.read_hello(ws)
        if hello is None:
            return ws
        watch, token = hello
        slot, token = self.claim(ws, token, watch)
        try:
            return await self.serve_peer(request, ws, slot, token)
        finally:
            if slot is not None:
                self.release(slot, ws)

    async def serve_peer(self, request, ws, slot, token):
        self.serial += 1
        rtc = Gst.ElementFactory.make('webrtcbin', f'peer_{self.serial}')
        rtc.set_property('bundle-policy', GstWebRTC.WebRTCBundlePolicy.MAX_BUNDLE)
        peer = dict(slot=slot, rtc=rtc, sources={}, remote=False, ice=[], sinks=[], caps_set=set(),
                    addr=request.remote, client={}, server={}, ack=stream.Window(120))
        transport = Gst.Pipeline.new(f'transport_{self.serial}')
        peer['pipeline'] = transport
        self.peers[ws] = peer
        async def send_ice(mline, candidate):
            if not ws.closed:
                await ws.send_json(dict(type='ice', candidate=candidate, sdpMLineIndex=mline))
        rtc.connect('on-ice-candidate', lambda _, mline, candidate:
                    asyncio.run_coroutine_threadsafe(send_ice(mline, candidate), self.loop))
        transport.add(rtc)
        last_seq, window_start, window_count = -1, time.monotonic(), 0
        try:
            # Per-viewer work is payload + DTLS/SRTP only; the encoders are shared.
            for media, pay, pt in [('video', 'h264parse ! rtph264pay config-interval=-1 aggregate-mode=zero-latency', 96),
                                   ('audio', 'rtpopuspay', 97)]:
                branch = Gst.parse_bin_from_description(
                    f'appsrc name=source is-live=true format=time block=false max-buffers=4 '
                    f'leaky-type=downstream ! {pay} pt={pt}', True)
                transport.add(branch)
                sink = rtc.request_pad_simple('sink_%u')
                peer['sinks'].append(sink)
                branch_src = branch.get_static_pad('src')
                if media == 'video':
                    branch_src.add_probe(Gst.PadProbeType.EVENT_UPSTREAM, self.on_upstream_event)
                if branch_src.link(sink) != Gst.PadLinkReturn.OK:
                    raise RuntimeError('Could not link WebRTC')
                sink.get_property('transceiver').set_property('direction', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY)
                peer['sources'][media] = branch.get_by_name('source')
            transport.use_clock(self.pipeline.get_clock())
            transport.set_start_time(Gst.CLOCK_TIME_NONE)
            transport.set_base_time(self.pipeline.get_base_time())
            transport.set_state(Gst.State.PLAYING)
            self.request_keyframe('join')
            for attempt in range(40):
                if all(sink.get_current_caps() for sink in peer['sinks']):
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError('Media caps did not reach WebRTC')
            await ws.send_json(dict(type='player', slot=0 if slot is None else slot + 1,
                                    token=token, game=self.game, slots=self.players,
                                    video=dict(width=self.capture[0], height=self.capture[1])))
            reply = await self.promise(rtc, 'create-offer', None)
            offer = reply.get_value('offer').copy()
            await self.promise(rtc, 'set-local-description', offer)
            await ws.send_json(dict(type='offer', sdp=offer.sdp.as_text()))
            log.info('Offer sent to %s (%s)', request.remote, f'player {slot + 1}' if slot is not None else 'spectator')
            stats_task = asyncio.create_task(self.peer_stats(peer, ws))
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    break
                now = time.monotonic()
                if now - window_start >= 1:
                    window_start, window_count = now, 0
                window_count += 1
                if window_count > FLOOD_LIMIT:
                    log.warning('Closing %s: more than %d messages/s', request.remote, FLOOD_LIMIT)
                    await ws.close(code=1008, message=b'Too many messages')
                    break
                if window_count > RATE_LIMIT:
                    continue            # over budget: drop; the next snapshot/heartbeat supersedes it
                data = json.loads(message.data)
                if not isinstance(data, dict):
                    raise ValueError('Invalid message')
                kind = data.get('type')
                if kind == 'state':
                    b, seq = data.get('b'), data.get('seq')
                    if type(b) is not int or not 0 <= b < MASK_LIMIT or type(seq) is not int:
                        raise ValueError('Invalid controller state')
                    if slot is None or not peer['remote'] or self.owners[slot] is None \
                            or self.owners[slot]['ws'] is not ws:
                        continue            # spectators / replaced sockets: never reaches a pad
                    if seq <= last_seq:
                        continue            # stale or replayed
                    last_seq = seq
                    self.pads[slot].set(b)
                    await ws.send_json(dict(type='ack', seq=seq))
                elif kind == 'answer' and not peer['remote']:
                    result, sdp = GstSdp.SDPMessage.new()
                    if not isinstance(data.get('sdp'), str) or \
                            GstSdp.sdp_message_parse_buffer(data['sdp'].encode(), sdp) != GstSdp.SDPResult.OK:
                        raise ValueError('Invalid SDP')
                    answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
                    await self.promise(rtc, 'set-remote-description', answer)
                    peer['remote'] = True
                    for mline, candidate in peer['ice']:
                        rtc.emit('add-ice-candidate', mline, candidate)
                    peer['ice'].clear()
                elif kind == 'ice':
                    mline, candidate = int(data['sdpMLineIndex']), data['candidate']
                    if not isinstance(candidate, str) or len(candidate) > 2048 or not 0 <= mline < 4:
                        raise ValueError('Invalid ICE candidate')
                    if peer['remote']:
                        rtc.emit('add-ice-candidate', mline, candidate)
                    elif len(peer['ice']) < 32:
                        peer['ice'].append((mline, candidate))
                elif kind == 'leave':
                    if slot is not None:
                        self.leave(slot, ws)
                    await ws.close(code=1000, message=b'Left')
                    break
                elif kind == 'ping' and isinstance(data.get('id'), int):
                    await ws.send_json(dict(type='pong', id=data['id']))
                elif kind == 'stats' and isinstance(data.get('s'), dict):
                    peer['client'] = data['s']
                    self.log_client(peer, data['s'])
        except Exception:
            log.exception('Peer failed')
        finally:
            if 'stats_task' in locals():
                stats_task.cancel()
            log.info('Peer %s (%s) gone: close code %s', request.remote,
                     f'player {slot + 1}' if slot is not None else 'spectator', ws.close_code)
            self.peers.pop(ws, None)
            await asyncio.to_thread(transport.set_state, Gst.State.NULL)
            await ws.close()
        return ws

    def count_encoders(self):
        """Encoders that actually exist, in the shared pipeline AND every viewer's
        transport, so /stats proves (not asserts) that viewers add no encoder."""
        counts = dict(video=0, audio=0)
        pipelines = [self.pipeline] + [p['pipeline'] for p in self.peers.values()]
        for pipeline in filter(None, pipelines):
            found, it = [], pipeline.iterate_recurse()
            while True:
                ok, element = it.next()
                if ok == Gst.IteratorResult.RESYNC:   # pipeline changed mid-walk: restart it
                    found, _ = [], it.resync()
                    continue
                if ok != Gst.IteratorResult.OK:
                    break
                klass = element.get_factory().get_metadata('klass') if element.get_factory() else ''
                if 'Encoder' in klass:
                    found.append('video' if 'Video' in klass else 'audio')
            for kind in found:
                counts[kind] += 1
        return counts

    async def stats(self, request):
        if request.remote != '127.0.0.1':  # peer IPs and client stats: operators only
            raise web.HTTPForbidden()
        return web.json_response(dict(
            game=self.game, encoders=self.count_encoders(), max_players=self.players,
            players=sum(1 for p in self.peers.values() if p['slot'] is not None),
            spectators=sum(1 for p in self.peers.values() if p['slot'] is None),
            slots=[None if o is None else dict(connected=o['ws'] is not None) for o in self.owners],
            video_frames=self.video_frames, video_bytes=self.video_bytes,
            uptime=time.monotonic() - self.started, error=self.error,
            emulator_running=self.emulator.poll() is None,
            capture_age_ms={m: w.summary() for m, w in self.age.items()},
            video_frame_kb=self.frame_kb.summary(), keyframes_forced=self.keyframes_forced,
            peers=[dict(slot=None if p['slot'] is None else p['slot'] + 1, addr=p['addr'],
                        server=p['server'], client=p['client']) for p in self.peers.values()]))

    async def cleanup(self, app):
        if hasattr(self, 'monitor'):
            self.monitor.cancel()
        for ws in list(self.peers):
            await ws.close()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        for pad in self.pads:
            pad.close()
        if self.x11:
            self.x11.close()
        if self.emulator and self.emulator.poll() is None:
            self.emulator.terminate()   # run-ps1.sh stops RetroArch, Xvfb and Pulse
            try:
                await asyncio.wait_for(asyncio.to_thread(self.emulator.wait), 10)
            except asyncio.TimeoutError:
                os.killpg(self.emulator.pid, signal.SIGKILL)
                await asyncio.to_thread(self.emulator.wait)
        if hasattr(self, 'emulator_log'):
            self.emulator_log.close()


def parse_capture(text):
    """'320x240' -> (320, 240). Even sizes only: the encoder takes 4:2:0 frames."""
    try:
        w, h = (int(v) for v in text.lower().split('x'))
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not WxH') from None
    if not (160 <= w <= 1280 and 120 <= h <= 960 and w % 2 == 0 and h % 2 == 0):
        raise argparse.ArgumentTypeError(f'{text!r}: need even sizes, 160x120 to 1280x960')
    return w, h


def check_bind(host, port):
    """Bind every address `host` resolves to, as asyncio's server will (SO_REUSEADDR,
    IPV6_V6ONLY), and release it again. Raises OSError if aiohttp could not bind."""
    for family, kind, proto, _, addr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                                                           flags=socket.AI_PASSIVE):
        with socket.socket(family, kind, proto) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind(addr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('game', choices=sorted(GAMES))
    parser.add_argument('--host', action='append',
                        help='bind address (repeatable; default 10.42.0.1 = party AP, and 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8198)
    parser.add_argument('--capture', type=parse_capture, default=(640, 480), metavar='WxH',
                        help='private screen size to grab and encode (default 640x480; 320x240 = '
                             'the PS1 native size, ~4x cheaper to grab and convert)')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error(f'--port {args.port} is not a TCP port')
    hosts = args.host or ['10.42.0.1', '127.0.0.1']
    # aiohttp binds only after on_startup has launched the emulator and the encoder, so an
    # unusable address (e.g. 10.42.0.1 while the party AP is down) must fail before that.
    for host in hosts:
        try:
            check_bind(host, args.port)
        except OSError as e:
            why = {errno.EADDRNOTAVAIL: 'not an address of this machine; is the party AP up?',
                   errno.EADDRINUSE: 'port already in use'}.get(e.errno, e.strerror or str(e))
            parser.error(f'cannot bind {host}:{args.port} ({why}); choose addresses with --host')
    ps1 = PS1Stream(args.game, args.capture)
    app = web.Application(client_max_size=4096)
    app.router.add_get('/', lambda request: web.FileResponse(HERE / 'index.html'))
    app.router.add_get('/ws', ps1.websocket)
    app.router.add_get('/stats', ps1.stats)
    app.on_startup.append(ps1.startup)
    app.on_cleanup.append(ps1.cleanup)
    web.run_app(app, host=hosts, port=args.port,
                access_log=None)  # /ws?token=... must never reach a log
