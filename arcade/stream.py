#!/usr/bin/env python3
"""One emulator, one hardware video encode, per-phone WebRTC transports."""
import asyncio
import collections
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
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

MAX_PLAYERS = 2  # P1 verified on a real phone over 5 GHz; raise beyond 2 only after a 2-phone test.
# Must match contracts/games/arcade-gauntlet2.json "input" and index.html's data-key buttons (tested).
LAYOUT = ControllerLayout(buttons=('fire', 'magic', 'coin', 'start'), directions='dpad')
ROM = '/srv/avrana/roms/arcade/gaunt2.zip'
PRESENTATION = ProviderInfo(
    id='shared-webrtc', kind='presentation', offers=('presentation.shared_stream',),
    implementation='one v4l2h264enc encode fanned out per phone through GStreamer webrtcbin')
EMULATOR_LOG = ROOT / 'runtime/emulator.log'
EMULATOR_LOG_MAX = 20 * 1024 * 1024  # emulator.log.1 keeps the previous 20 MB; total stays under ~45 MB.
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


def ap_addresses():
    """Addresses of the Avrana Party access point interface (wlan1)."""
    found = set()
    try:
        for line in subprocess.run(['ip', '-o', 'addr', 'show', 'dev', 'wlan1'], capture_output=True,
                                   text=True, timeout=2).stdout.splitlines():
            found.add(line.split()[3].split('/')[0])
    except Exception:
        pass
    return found


class Stream:
    info = PRESENTATION

    def __init__(self):
        self.pipeline = None
        self.input = UInputGamepadProvider()
        self.runtime = RetroArchRuntime(config=ROOT / 'retroarch.cfg',
                                        core=ROOT / 'cores/mame2010_libretro.so', content=ROM)
        self.pads = []
        self.peers = {}
        self.reserved = set()
        self.video_frames = 0
        self.video_bytes = 0
        self.started = time.monotonic()
        self.error = None
        self.emulator = None
        self.serial = 0
        self.age = dict(video=Window(), audio=Window())
        self.frame_kb = Window()
        self.client_log = None
        self.last_keyframe = 0.0
        self.keyframes_forced = 0

    async def startup(self, app):
        self.loop = asyncio.get_running_loop()
        self.pads = [self.input.open(slot, LAYOUT) for slot in range(MAX_PLAYERS)]
        await asyncio.sleep(0.5)  # Allow udev to expose the controllers before SDL scans.
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
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Could not start capture pipeline')
        self.monitor = asyncio.create_task(self.watch())

    async def cap_emulator_log(self):
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(rotate_emulator_log)
            except OSError:
                log.exception('emulator log rotation failed')

    def distribute(self, sink, media):
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
            if self.error:
                for ws in list(self.peers):
                    await ws.close(code=1011, message=b'Stream stopped')
                return

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
        used = self.reserved
        slot = next((s for s in range(MAX_PLAYERS) if s not in used), None)
        if slot is None:
            raise web.HTTPConflict(text='Player slot in use. Close the other controller first.')
        self.reserved.add(slot)
        ws = web.WebSocketResponse(max_msg_size=65536, heartbeat=5)
        try:
            await ws.prepare(request)
        except BaseException:
            self.reserved.discard(slot)
            raise
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
        try:
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
                raise RuntimeError('Media caps did not reach WebRTC')
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
            self.pads[slot].update([])
            self.peers.pop(ws, None)
            self.reserved.discard(slot)
            await asyncio.to_thread(transport.set_state, Gst.State.NULL)
            await ws.close()
        return ws

    def log_client(self, peer, values):
        path = ROOT / 'runtime/client-stats.jsonl'
        if path.exists() and path.stat().st_size > 20_000_000:
            return
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
                    (ROOT / f'runtime/webrtc-stats-sample{ticks}.txt').write_text(reply.to_string())
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
        return web.json_response(dict(players=len(self.peers), max_players=MAX_PLAYERS,
            video_encoders=1, video_frames=self.video_frames, video_bytes=self.video_bytes,
            uptime=time.monotonic() - self.started, error=self.error,
            emulator_running=self.runtime.running(),
            capture_age_ms={m: w.summary() for m, w in self.age.items()},
            video_frame_kb=self.frame_kb.summary(), keyframes_forced=self.keyframes_forced,
            providers=dict(runtime=self.runtime.status(),
                           input=dict(self.input.info.describe(), controllers=len(self.pads)),
                           presentation=self.status()),
            peers=[dict(slot=p['slot'] + 1, addr=p['addr'], server=p['server'], client=p['client'])
                   for p in self.peers.values()]))

    async def cleanup(self, app):
        if hasattr(self, 'monitor'):
            self.monitor.cancel()
        if hasattr(self, 'log_cap'):
            self.log_cap.cancel()
        for ws in list(self.peers):
            await ws.close()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        for pad in self.pads:
            pad.update([])
            pad.device.close()
        await asyncio.to_thread(self.runtime.stop, 5)
        if hasattr(self, 'emulator_log'):
            self.emulator_log.close()


if __name__ == '__main__':
    stream = Stream()
    app = web.Application(client_max_size=65536)
    app.router.add_get('/', lambda request: web.FileResponse(ROOT / 'index.html'))
    app.router.add_get('/ws', stream.websocket)
    app.router.add_get('/stats', stream.stats)
    app.on_startup.append(stream.startup)
    app.on_cleanup.append(stream.cleanup)
    web.run_app(app, host='127.0.0.1', port=8097)
