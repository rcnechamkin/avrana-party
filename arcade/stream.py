#!/usr/bin/env python3
"""One emulator, one hardware video encode, per-phone WebRTC transports.

Two ways to run (AVR-134, ADR 0009):
  * always-on (no Party session key configured): the emulator and the encode start with the
    process and run until it stops, as before;
  * Party-managed ($AVRANA_PARTY_KEYS holds arcade-gauntlet2.key and $AVRANA_PARTY_URL is set;
    deploy/arcade/avrana-party-session.conf): the page, the controllers and /stats are always up,
    but RetroArch and the capture/encode run only between the Party's signed `launch` and `end`
    (avrana.party.managed), served on 127.0.0.1:CONTROL_PORT, which nginx never forwards.
"""
import asyncio
import collections
import json
import logging
import os
import signal
from pathlib import Path
import subprocess
import sys
import threading
import time

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GstVideo, GstWebRTC, GstSdp
from aiohttp import web

Gst.init(None)
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))  # the repository root: avrana/ platform package
from avrana.providers.base import ProviderInfo  # noqa: E402
from avrana.providers.controller import ControllerLayout  # noqa: E402
from avrana.providers.retroarch import RetroArchRuntime  # noqa: E402
from avrana.providers.uinput_gamepad import UInputGamepadProvider  # noqa: E402
from avrana.party import managed as party_managed  # noqa: E402
from avrana.party import protocol  # noqa: E402

MAX_PLAYERS = 2  # P1 verified on a real phone over 5 GHz; raise beyond 2 only after a 2-phone test.
SEAT_GRACE_S = 60  # docs/design/PARTY-LIFECYCLE.md provisional SEAT_GRACE
# Must match contracts/games/arcade-gauntlet2.json "input" and index.html's data-key buttons (tested).
LAYOUT = ControllerLayout(buttons=('fire', 'magic', 'coin', 'start'), directions='dpad')
ROM = '/srv/avrana/roms/arcade/gaunt2.zip'
PRESENTATION = ProviderInfo(
    id='shared-webrtc', kind='presentation', offers=('presentation.shared_stream',),
    implementation='one v4l2h264enc encode fanned out per phone through GStreamer webrtcbin')
EXIT_FATAL = 1  # non-zero: avranaparty-arcade.service restarts on failure (Restart=on-failure)
# ximagesrc runs at a fixed 60 fps (use-damage=false), so encoded video never pauses while the
# arcade is healthy, even on a still screen. No video for this long means the capture/encode
# pipeline has wedged without a bus ERROR (seen 2026-09-28: v4l2h264enc stopped returning frames,
# the process stayed "active" and every phone failed with "Media caps did not reach WebRTC").
VIDEO_STALL_S = 10
EXIT_BACKSTOP_S = 20  # a fatal exit that has not finished cleanup by then is forced
PARTY_GAME = 'arcade-gauntlet2'  # the Party Core game id (contracts/games/arcade-gauntlet2.json)
CONTROL_PORT = int(os.environ.get('AVRANA_ARCADE_CONTROL_PORT', '8098'))  # loopback only
IDLE_TEXT = 'Gauntlet II is not running. The Party Host starts it from Party Home.'
# Everything the arcade writes: the unit's runtime directory, or ./runtime for a hand-run prototype.
RUNTIME = Path(os.environ.get('AVRANA_ARCADE_RUNTIME') or ROOT / 'runtime')
# The libretro core is built on the host, not kept in Git; the unit points at its installed copy.
CORE = Path(os.environ.get('AVRANA_ARCADE_CORE') or ROOT / 'cores/mame2010_libretro.so')
EMULATOR_LOG = RUNTIME / 'emulator.log'
EMULATOR_LOG_MAX = 20 * 1024 * 1024  # emulator.log.1 keeps the previous 20 MB; total stays under ~45 MB.
# Per-second phone stats (analyze-latency.py). Past the cap it rotates to .1, so the newest
# records are kept and the pair stays under ~2x the cap (AVR-30).
CLIENT_LOG = RUNTIME / 'client-stats.jsonl'
CLIENT_LOG_MAX = 20 * 1024 * 1024
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('avrana-arcade')


def rotate_emulator_log():
    """Copy-truncate. Safe because the emulator holds the log open with O_APPEND."""
    if EMULATOR_LOG.stat().st_size > EMULATOR_LOG_MAX:
        with EMULATOR_LOG.open('rb') as src:
            src.seek(-EMULATOR_LOG_MAX, os.SEEK_END)
            tail = src.read()
        EMULATOR_LOG.with_name('emulator.log.1').write_bytes(tail)
        os.truncate(EMULATOR_LOG, 0)


class Window:
    """Bounded rolling samples with cheap percentile summaries."""
    def __init__(self, size=600):
        self.values = collections.deque(maxlen=size)

    def add(self, value):
        self.values.append(value)

    def summary(self):
        data = sorted(self.values)
        if not data:
            return None
        pick = lambda q: round(data[min(len(data) - 1, int(q * len(data)))], 2)
        return dict(n=len(data), p50=pick(0.5), p95=pick(0.95), max=round(data[-1], 2))


def plain(value):
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return getattr(value, 'value_nick', None) or str(value)


def flatten_stats(reply):
    """webrtcbin stats: a Gst.Structure whose fields are Gst.Structure stat objects."""
    out = {}
    for i in range(reply.n_fields()):
        name = reply.nth_field_name(i)
        item = reply.get_value(name)
        if isinstance(item, Gst.Structure):
            out[name] = {item.nth_field_name(j): plain(item.get_value(item.nth_field_name(j)))
                         for j in range(item.n_fields())}
    return out


PARTY_ADDRESS = '10.42.0.1'


def ap_addresses():
    """Addresses of the Avrana Party access point interface: whichever interface holds the party
    address (wlan1 with the old USB adapter; the internal wlan0 since 2026-09-24). Used only to
    label a peer's network path in /stats."""
    found = set()
    try:
        lines = subprocess.run(['ip', '-o', 'addr', 'show'], capture_output=True,
                               text=True, timeout=2).stdout.splitlines()
        ifaces = {line.split()[1] for line in lines if f' {PARTY_ADDRESS}/' in line}
        for line in lines:
            parts = line.split()
            if len(parts) > 3 and parts[1] in ifaces:
                found.add(parts[3].split('/')[0])
    except Exception:
        pass
    return found


class PartySeats:
    """Session-local ownership keyed only by GameSide's secret game token. Never log it."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.session = None
        self.seats = {}

    def reset(self, session=None):
        self.session = session
        self.seats.clear()

    def claim(self, side, ticket, ws):
        token, role = side.admit(ticket)
        if self.session != side.sid:
            self.reset(side.sid)
        if role != 'player':
            raise protocol.Invalid('spectator')
        now = self.clock()
        self.seats = {t: s for t, s in self.seats.items()
                      if s['ws'] is not None or s['until'] > now}
        seat = self.seats.get(token)
        if seat is None:
            used = {s['slot'] for s in self.seats.values()}
            slot = next((s for s in range(MAX_PLAYERS) if s not in used), None)
            if slot is None:
                raise protocol.Invalid('full')
            seat = self.seats[token] = dict(slot=slot, ws=None, until=None)
        old = seat['ws']
        seat.update(ws=ws, until=None)
        return seat['slot'], old

    def owns(self, side, slot, ws):
        return self.session == side.sid and side.sid is not None and any(
            s['slot'] == slot and s['ws'] is ws for s in self.seats.values())

    def disconnect(self, slot, ws, *, leave=False):
        for token, seat in list(self.seats.items()):
            if seat['slot'] == slot and seat['ws'] is ws:
                if leave:
                    del self.seats[token]
                else:
                    seat.update(ws=None, until=self.clock() + SEAT_GRACE_S)
                return True
        return False


class Stream:
    info = PRESENTATION

    def __init__(self):
        self.pipeline = None
        self.input = UInputGamepadProvider()
        self.runtime = RetroArchRuntime(config=ROOT / 'retroarch.cfg',
                                        core=CORE, content=ROM)
        self.pads = []
        self.peers = {}
        self.reserved = set()
        self.party_seats = PartySeats()
        self.video_frames = 0
        self.video_bytes = 0
        self.started = time.monotonic()
        self.error = None
        self.fatal = False  # set only by watch() on an unrecoverable emulator/pipeline failure
        self.emulator = None
        self.serial = 0
        self.age = dict(video=Window(), audio=Window())
        self.frame_kb = Window()
        self.client_log = None
        self.last_keyframe = 0.0
        self.keyframes_forced = 0
        self.last_sample = {}  # media -> time.monotonic() of the newest encoded sample
        self.video_since = None  # when the capture pipeline was started (the stall grace period)
        self.managed = None  # party_managed.ManagedRuntime when the Party starts and stops the runtime
        self.party_url = None
        self.control = None  # the loopback control site's runner (Party-managed only)

    async def startup(self, app):
        self.loop = asyncio.get_running_loop()
        self.pads = [self.input.open(slot, LAYOUT) for slot in range(MAX_PLAYERS)]
        await asyncio.sleep(0.5)  # Allow udev to expose the controllers before SDL scans.
        party = party_managed.configure(os.environ, PARTY_GAME)
        if party is None:
            await self.start_runtime()  # always-on, as before AVR-134
            return
        side, self.party_url = party
        self.managed = party_managed.ManagedRuntime(side, self.start_runtime, self.stop_runtime,
                                                    report=self.report_ended)
        await self.start_control()
        log.info('Party-managed: idle until the Party launches %s', PARTY_GAME)

    async def start_control(self):
        """The session protocol's launch/end routes on 127.0.0.1:CONTROL_PORT only."""
        control = web.Application(client_max_size=party_managed.MAX_BODY)
        for action, path in (('launch', party_managed.LAUNCH_PATH), ('end', party_managed.END_PATH)):
            control.router.add_post(path, lambda request, action=action: self.control_request(request, action))
        self.control = web.AppRunner(control, access_log=None)
        await self.control.setup()
        await web.TCPSite(self.control, '127.0.0.1', CONTROL_PORT).start()

    async def control_request(self, request, action):
        raw = await request.read()  # the whole body; aiohttp answers 413 past client_max_size
        status, body = await party_managed.handle(self.managed, action, request.remote,
                                                  request.headers, raw)
        return web.json_response(body, status=status)

    async def report_ended(self, message):
        status = await asyncio.to_thread(party_managed.post_ended, self.party_url, message)
        return status == 200

    def runtime_state(self):
        if self.managed is not None:
            return self.managed.state
        return 'running' if self.pipeline is not None else 'idle'

    async def start_runtime(self):
        """RetroArch, then the shared capture/encode, then the watchdog. On failure the caller
        stops what did start (Party-managed: ManagedRuntime; always-on: the process exits)."""
        self.party_seats.reset(self.managed.session if self.managed is not None else None)
        self.error = None
        self.last_sample = {}
        # Truncate at start as before, but O_APPEND so rotate_emulator_log() can truncate in place.
        self.emulator_log = os.fdopen(os.open(
            EMULATOR_LOG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, 0o664), 'w')
        self.emulator = self.runtime.start(stdout=self.emulator_log)
        await asyncio.sleep(2)
        if not self.runtime.running():
            raise RuntimeError('Emulator exited; see runtime/emulator.log')
        self.log_cap = asyncio.create_task(self.cap_emulator_log())
        self.pipeline = Gst.parse_launch(
            'ximagesrc use-damage=false show-pointer=false ! '
            'video/x-raw,framerate=60/1 ! videoconvert ! video/x-raw,format=I420 ! '
            'v4l2h264enc name=video_encoder extra-controls="controls,video_bitrate=2500000,'
            'h264_i_frame_period=60,repeat_sequence_header=1" ! '
            'video/x-h264,profile=constrained-baseline,level=(string)3.1 ! '
            'h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! '
            'appsink name=video_out emit-signals=true sync=false max-buffers=2 drop=true '
            f'pulsesrc server={os.environ["PULSE_SERVER"]} device=avrana_arcade.monitor ! '
            'audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! '
            'opusenc bitrate=64000 frame-size=10 ! '
            'appsink name=audio_out emit-signals=true sync=false max-buffers=4 drop=true')
        for media in ('video', 'audio'):
            self.pipeline.get_by_name(media + '_out').connect('new-sample', self.distribute, media)
        self.video_since = time.monotonic()
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Could not start capture pipeline')
        self.monitor = asyncio.create_task(self.watch())

    async def stop_runtime(self, reason='Stream stopped'):
        """The reverse of start_runtime(), safe to call twice and after a partial start: phones
        are told, the watchdog stops, the capture/encode stops, then RetroArch. The controllers
        stay (they are cheap and SDL keeps its devices across runs)."""
        self.party_seats.reset()
        monitor, self.monitor = getattr(self, 'monitor', None), None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
        log_cap, self.log_cap = getattr(self, 'log_cap', None), None
        if log_cap is not None:
            log_cap.cancel()
        for ws in list(self.peers):
            await ws.close(code=1001, message=reason.encode()[:120])
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        for pad in self.pads:
            pad.update([])
        await asyncio.to_thread(self.runtime.stop, 5)
        emulator_log, self.emulator_log = getattr(self, 'emulator_log', None), None
        if emulator_log is not None:
            emulator_log.close()
        self.video_since = None

    async def cap_emulator_log(self):
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(rotate_emulator_log)
            except OSError:
                log.exception('emulator log rotation failed')

    def distribute(self, sink, media):
        self.last_sample[media] = time.monotonic()
        sample = sink.emit('pull-sample')
        buffer = sample.get_buffer()
        if buffer.pts != Gst.CLOCK_TIME_NONE:
            now = self.pipeline.get_clock().get_time() - self.pipeline.get_base_time()
            # pulsesrc (a GstAudioBaseSrc) timestamps audio from its sample-position
            # ringbuffer clock and ignores do-timestamp; the pipeline runs on the
            # system clock. When the audio thread stalls, the sample clock falls
            # permanently behind wall-clock, so buffer.pts lags and capture_age
            # ratchets up per session (13->313->1003->2800ms measured). The Pulse
            # monitor latency stays ~0, so the samples are FRESH — only the PTS is
            # mislabelled. Re-stamp audio to the running clock so peers get
            # correctly-timed audio and the lag cannot accumulate. Video (ximagesrc)
            # is already clock-stamped and is left untouched.
            if media == 'audio' and now >= 0:
                buffer = buffer.copy()  # writable copy (shares memory); safe to re-stamp
                buffer.pts = now
                buffer.dts = Gst.CLOCK_TIME_NONE
            self.age[media].add((now - buffer.pts) / 1e6)
        if media == 'video':
            self.video_frames += 1
            self.video_bytes += buffer.get_size()
            self.frame_kb.add(buffer.get_size() / 1024)
        # Nonblocking appsrc queues isolate a stalled viewer from the encoder.
        for peer in list(self.peers.values()):
            source = peer['sources'].get(media)
            if source is not None:
                if media not in peer['caps_set']:
                    source.set_property('caps', sample.get_caps())
                    peer['caps_set'].add(media)
                source.emit('push-buffer', buffer)
        return Gst.FlowReturn.OK

    def on_upstream_event(self, pad, info):
        event = info.get_event()
        if GstVideo.video_event_is_force_key_unit(event):
            self.loop.call_soon_threadsafe(self.request_keyframe, 'pli')
        return Gst.PadProbeReturn.OK

    def request_keyframe(self, reason):
        """Force the shared encoder to emit an IDR now.

        The per-peer transports are separate pipelines fed via appsink/appsrc, so a
        phone's PLI (packet-loss recovery) or a fresh join produces an upstream
        force-key-unit event that dies at its appsrc. Bridge it to the one real
        encoder. Debounced so a burst of PLIs cannot storm the encoder.
        """
        now = time.monotonic()
        if now - self.last_keyframe < 0.2:
            return
        self.last_keyframe = now
        self.keyframes_forced += 1
        encoder = self.pipeline.get_by_name('video_encoder')
        if encoder is not None:
            event = GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0)
            encoder.get_static_pad('src').send_event(event)
            log.info('Forced keyframe (%s)', reason)

    def video_age(self):
        """Seconds since the newest encoded video frame (or since the pipeline started, before
        the first one); None before startup."""
        since = self.last_sample.get('video', self.video_since)
        return None if since is None else time.monotonic() - since

    def video_stalled(self):
        age = self.video_age()
        return age is not None and age > VIDEO_STALL_S

    def status(self):
        """PresentationProvider diagnostics: one shared encode, one transport per viewer."""
        return dict(self.info.describe(), viewers=len(self.peers), encoders=1)

    async def watch(self):
        while True:
            await asyncio.sleep(0.1)
            for pad in self.pads:
                if pad.state and time.monotonic() - pad.updated > 0.3:
                    pad.update([])
            msg = self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if msg:
                err, debug = msg.parse_error()
                self.error = str(err)
                log.error('Pipeline error: %s %s', err, debug)
            if not self.runtime.running():
                self.error = 'Emulator exited'
            if not self.error and self.video_stalled():
                # Alive but silent: the service looks "active" and /stats looked healthy, yet no
                # phone can get a picture. Treat it like a pipeline error so systemd restarts it.
                self.error = 'Video capture stalled'
                log.error('No encoded video for %.1f s', self.video_age())
            if self.error:
                for ws in list(self.peers):
                    await ws.close(code=1011, message=b'Stream stopped')
                # Fatal: nothing can stream any more. Shut down through aiohttp's normal path (so
                # cleanup() releases pads, stops RetroArch and the pipeline) and exit non-zero, so
                # systemd's Restart=on-failure brings the arcade back.
                log.error('Fatal: %s; exiting for a restart', self.error)
                self.fatal = True
                if self.managed is not None:
                    # Party-managed: the party must not keep showing a game that is gone. The
                    # restarted process comes back idle until the host starts it again.
                    await self.managed.abandon()
                self.request_exit()
                return

    def request_exit(self):
        """Ask web.run_app to stop gracefully (it handles SIGTERM by running on_cleanup)."""
        # Backstop: if cleanup itself hangs on a wedged encoder, still exit non-zero so systemd
        # restarts the arcade instead of leaving a silent process behind.
        backstop = threading.Timer(EXIT_BACKSTOP_S, os._exit, (EXIT_FATAL,))
        backstop.daemon = True
        backstop.start()
        os.kill(os.getpid(), signal.SIGTERM)

    async def promise(self, element, signal, *args):
        future = self.loop.create_future()
        def done(promise, *_):
            value = promise.get_reply()
            reply = value.copy() if value is not None else None
            def resolve():
                if not future.done():
                    if reply is not None and reply.has_field('error'):
                        future.set_exception(RuntimeError(str(reply.get_value('error'))))
                    else:
                        future.set_result(reply)
            self.loop.call_soon_threadsafe(resolve)
        promise = Gst.Promise.new_with_change_func(done, None, None)
        element.emit(signal, *args, promise)
        return await asyncio.wait_for(future, 10)

    async def websocket(self, request):
        if request.headers.get('Origin') not in ('http://' + request.host, 'https://' + request.host):
            raise web.HTTPForbidden()
        if self.error:
            raise web.HTTPServiceUnavailable(text='Stream unavailable')
        if self.pipeline is None:  # Party-managed and not started: nothing to stream, nothing spent
            raise web.HTTPServiceUnavailable(text=IDLE_TEXT)
        slot = None
        if self.managed is None:
            slot = next((s for s in range(MAX_PLAYERS) if s not in self.reserved), None)
            if slot is None:
                raise web.HTTPConflict(text='Player slot in use. Close the other controller first.')
            self.reserved.add(slot)
        ws = web.WebSocketResponse(max_msg_size=65536, heartbeat=5)
        try:
            await ws.prepare(request)
            if self.managed is not None:
                try:
                    hello = await ws.receive_json(timeout=5)
                    if not isinstance(hello, dict) or hello.get('type') != 'hello':
                        raise protocol.Invalid('hello')
                    if self.managed.state != party_managed.RUNNING or self.pipeline is None:
                        raise protocol.Invalid('session')
                    slot, old = self.party_seats.claim(self.managed.side, hello.get('ticket'), ws)
                except (protocol.Invalid, ValueError, TypeError, asyncio.TimeoutError) as e:
                    reason = str(e) if isinstance(e, protocol.Invalid) else 'hello'
                    await ws.send_json(dict(type='error', reason=reason))
                    await ws.close()
                    return ws
                self.pads[slot].update([])
                if old is not None and old is not ws:
                    if not old.closed:
                        try:
                            await old.send_json(dict(type='error', reason='replaced'))
                        except (ConnectionError, RuntimeError):
                            pass  # a disappearing old socket must not undo the new binding
                    await old.close(code=1000, message=b'Controller opened in another connection')
                if not self.party_seats.owns(self.managed.side, slot, ws):
                    await ws.close()
                    return ws
        except BaseException:
            if self.managed is None:
                self.reserved.discard(slot)
            elif slot is not None:
                self.party_seats.disconnect(slot, ws)
            raise
        transport = None
        try:
            self.serial += 1
            rtc = Gst.ElementFactory.make('webrtcbin', f'peer_{self.serial}')
            rtc.set_property('bundle-policy', GstWebRTC.WebRTCBundlePolicy.MAX_BUNDLE)
            peer = dict(slot=slot, rtc=rtc, sources={}, remote=False, ice=[], sinks=[], caps_set=set(),
                        addr=request.remote, client={}, server={}, ack=Window(120))
            transport = Gst.Pipeline.new(f'transport_{self.serial}')
            peer['pipeline'] = transport
            self.peers[ws] = peer
            async def send_ice(mline, candidate):
                if not ws.closed:
                    await ws.send_json(dict(type='ice', candidate=candidate, sdpMLineIndex=mline))
            rtc.connect('on-ice-candidate', lambda _, mline, candidate:
                        asyncio.run_coroutine_threadsafe(send_ice(mline, candidate), self.loop))
            transport.add(rtc)
            wanted = [('video', 'h264parse ! rtph264pay config-interval=-1 aggregate-mode=zero-latency', 96),
                      ('audio', 'rtpopuspay', 97)]
            if request.query.get('audio') == '0':  # A/B: remove audio transport entirely
                wanted = wanted[:1]
            for media, pay, pt in wanted:
                branch = Gst.parse_bin_from_description(
                    f'appsrc name=source is-live=true format=time block=false max-buffers=4 '
                    f'leaky-type=downstream ! {pay} pt={pt}', True)
                transport.add(branch)
                sink = rtc.request_pad_simple('sink_%u')
                peer['sinks'].append(sink)
                branch_src = branch.get_static_pad('src')
                if media == 'video':
                    # webrtcbin turns the phone's PLI into an upstream force-key-unit
                    # event; it would otherwise stop at this appsrc. Relay to the encoder.
                    branch_src.add_probe(Gst.PadProbeType.EVENT_UPSTREAM, self.on_upstream_event)
                if branch_src.link(sink) != Gst.PadLinkReturn.OK:
                    raise RuntimeError('Could not link WebRTC')
                sink.get_property('transceiver').set_property('direction', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY)
                peer['sources'][media] = branch.get_by_name('source')
            transport.use_clock(self.pipeline.get_clock())
            transport.set_start_time(Gst.CLOCK_TIME_NONE)
            transport.set_base_time(self.pipeline.get_base_time())
            transport.set_state(Gst.State.PLAYING)
            self.request_keyframe('join')  # Don't make the new phone wait for the periodic IDR.
            # H.264 parser needs an IDR/SPS before advertising its RTP caps.
            for attempt in range(40):
                if all(sink.get_current_caps() for sink in peer['sinks']):
                    break
                await asyncio.sleep(0.1)
            else:
                missing = [media for (media, _, _), sink in zip(wanted, peer['sinks'])
                           if not sink.get_current_caps()]
                # Tell the phone why, so it does not blame its Wi-Fi.
                await ws.send_json(dict(type='error', reason='no-media', media=missing))
                raise RuntimeError('Media caps did not reach WebRTC: ' + ', '.join(missing))
            await ws.send_json(dict(type='player', slot=slot + 1))
            log.info('Creating offer for player %s', slot + 1)
            reply = await self.promise(rtc, 'create-offer', None)
            offer = reply.get_value('offer').copy()
            await self.promise(rtc, 'set-local-description', offer)
            await ws.send_json(dict(type='offer', sdp=offer.sdp.as_text()))
            log.info('Offer sent for player %s', slot + 1)
            stats_task = asyncio.create_task(self.peer_stats(peer, ws))
            async for message in ws:
                if message.type != web.WSMsgType.TEXT:
                    break
                data = json.loads(message.data)
                kind = data.get('type')
                if self.managed is not None and not self.party_seats.owns(self.managed.side, slot, ws):
                    break  # replaced socket or ended/switched session cannot input or release
                if kind == 'leave':
                    if self.managed is not None:
                        self.party_seats.disconnect(slot, ws, leave=True)
                    self.pads[slot].update([])
                    break
                if kind == 'answer' and not peer['remote']:
                    result, sdp = GstSdp.SDPMessage.new()
                    if GstSdp.sdp_message_parse_buffer(data['sdp'].encode(), sdp) != GstSdp.SDPResult.OK:
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
                elif kind == 'input' and peer['remote']:
                    self.pads[slot].update(data.get('buttons'))
                    if isinstance(data.get('seq'), int):
                        await ws.send_json(dict(type='ack', seq=data['seq']))
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
            if self.managed is None or self.party_seats.disconnect(slot, ws):
                self.pads[slot].update([])
            self.peers.pop(ws, None)
            if self.managed is None:
                self.reserved.discard(slot)
            if transport is not None:
                await asyncio.to_thread(transport.set_state, Gst.State.NULL)
            await ws.close()
        return ws

    def log_client(self, peer, values):
        path = CLIENT_LOG
        if path.exists() and path.stat().st_size > CLIENT_LOG_MAX:
            path.replace(path.with_name(path.name + '.1'))
        record = dict(t=round(time.time(), 2), addr=peer['addr'], path=peer['server'].get('path'),
                      client=values, server=peer['server'])
        with path.open('a') as f:
            f.write(json.dumps(record) + '\n')

    async def peer_stats(self, peer, ws):
        """Once a second, pull sender-side WebRTC stats: ICE path, RTCP RTT/jitter/loss."""
        ticks = 0
        while not ws.closed:
            await asyncio.sleep(1)
            ticks += 1
            try:
                reply = await self.promise(peer['rtc'], 'get-stats', None)
                if reply is None:
                    continue
                if ticks in (1, 8):
                    (RUNTIME / f'webrtc-stats-sample{ticks}.txt').write_text(reply.to_string())
                peer['server'] = self.summarize(flatten_stats(reply), peer)
                if 'path' in peer['server'] and not peer.get('path_sent') and not ws.closed:
                    peer['path_sent'] = True
                    await ws.send_json(dict(type='path', network=peer['server']['path']))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Stats failed')

    def summarize(self, stats, peer):
        # Classify by entry-name prefix: the live 'type' field is a GLib enum,
        # not the string nick that .to_string() prints, so it is unreliable as a key.
        out = {'queue': {m: int(src.get_property('current-level-buffers'))
                         for m, src in peer['sources'].items()}}
        pick = lambda prefix: [v for k, v in stats.items() if k.startswith(prefix)]
        transport = next(iter(pick('transport-stats')), {})
        pair = stats.get(transport.get('selected-candidate-pair-id'))
        if pair is None:  # fall back to any candidate pair carrying both endpoints
            pair = next((v for v in pick('ice-candidate-pair') if v.get('local-candidate-id')), None)
        if pair:
            local = stats.get(pair.get('local-candidate-id'), {})
            remote = stats.get(pair.get('remote-candidate-id'), {})
            address = str(local.get('address') or '')
            out['ice'] = dict(local=address, local_type=str(local.get('candidate-type')),
                              remote=str(remote.get('address')), remote_type=str(remote.get('candidate-type')),
                              protocol=str(local.get('protocol')))
            out['path'] = 'avrana' if address in ap_addresses() else 'other'
        for entry in pick('rtp-outbound'):
            out['tx_' + str(entry.get('kind'))] = dict(
                packets=entry.get('packets-sent'), bytes=entry.get('bytes-sent'),
                nack=entry.get('nack-count'), pli=entry.get('pli-count'), fir=entry.get('fir-count'))
        # RTCP receiver reports: the real round-trip and loss seen from the phone.
        for entry in pick('rtp-remote-inbound'):
            out['rr_' + str(entry.get('kind'))] = dict(
                rtt=entry.get('round-trip-time'), jitter=entry.get('jitter'),
                lost=entry.get('packets-lost'), fraction=entry.get('fraction-lost'))
        return out

    async def stats(self, request):
        now = time.monotonic()
        return web.json_response(dict(players=len(self.peers), max_players=MAX_PLAYERS,
            video_encoders=1, video_frames=self.video_frames, video_bytes=self.video_bytes,
            uptime=now - self.started, error=self.error,
            # Seconds since each medium's newest encoded sample: large values mean no phone can
            # get a picture (video) or sound (audio), whatever emulator_running says.
            sample_age_s={m: round(now - t, 1) for m, t in self.last_sample.items()},
            emulator_running=self.runtime.running(),
            # 'idle' | 'starting' | 'running' | 'stopping'; party_managed: the Party starts it.
            state=self.runtime_state(), party_managed=self.managed is not None,
            capture_age_ms={m: w.summary() for m, w in self.age.items()},
            video_frame_kb=self.frame_kb.summary(), keyframes_forced=self.keyframes_forced,
            providers=dict(runtime=self.runtime.status(),
                           input=dict(self.input.info.describe(), controllers=len(self.pads)),
                           presentation=self.status()),
            peers=[dict(slot=p['slot'] + 1, addr=p['addr'], server=p['server'], client=p['client'])
                   for p in self.peers.values()]))

    async def cleanup(self, app):
        if self.control is not None:
            await self.control.cleanup()
        await self.stop_runtime()
        for pad in self.pads:
            pad.device.close()


if __name__ == '__main__':
    stream = Stream()
    app = web.Application(client_max_size=65536)
    app.router.add_get('/', lambda request: web.FileResponse(ROOT / 'index.html'))
    app.router.add_get('/ws', stream.websocket)
    app.router.add_get('/stats', stream.stats)
    app.on_startup.append(stream.startup)
    app.on_cleanup.append(stream.cleanup)
    web.run_app(app, host='127.0.0.1', port=8097)
    sys.exit(EXIT_FATAL if stream.fatal else 0)
