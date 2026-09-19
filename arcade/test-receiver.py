"""Local WebRTC decoder smoke test; not a phone/Wi-Fi latency measurement."""
import asyncio
import json
import sys
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GstSdp, GstWebRTC
from aiohttp import ClientSession
Gst.init(None)


async def main():
    loop = asyncio.get_running_loop()
    pipeline = Gst.Pipeline.new('test-receiver')
    rtc = Gst.ElementFactory.make('webrtcbin', 'receiver')
    rtc.set_property('bundle-policy', GstWebRTC.WebRTCBundlePolicy.MAX_BUNDLE)
    pipeline.add(rtc)
    counts = dict(video=0, audio=0)
    sinks = []
    def incoming(_, pad):
        if pad.get_direction() != Gst.PadDirection.SRC:
            return
        caps = pad.get_current_caps() or pad.query_caps(None)
        media = caps.get_structure(0).get_string('media')
        decoder = 'rtph264depay ! h264parse ! openh264dec' if media == 'video' else 'rtpopusdepay ! opusdec'
        branch = Gst.parse_bin_from_description('queue ! ' + decoder + ' ! fakesink name=decoded sync=false signal-handoffs=true', True)
        sink = branch.get_by_name('decoded')
        def frame(*_): counts[media] += 1
        sink.connect('handoff', frame)
        pipeline.add(branch)
        pad.link(branch.get_static_pad('sink'))
        branch.sync_state_with_parent()
        sinks.append(branch)
    rtc.connect('pad-added', incoming)
    async def promise(signal, *args):
        future = loop.create_future()
        def done(p, *_):
            value = p.get_reply()
            reply = value.copy() if value is not None else None
            loop.call_soon_threadsafe(lambda: None if future.done() else future.set_result(reply))
        p = Gst.Promise.new_with_change_func(done, None, None)
        rtc.emit(signal, *args, p)
        return await asyncio.wait_for(future, 10)
    async with ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8097/ws', origin='http://127.0.0.1:8097') as ws:
            async def ice(mline, candidate):
                if not ws.closed:
                    await ws.send_json(dict(type='ice', sdpMLineIndex=mline, candidate=candidate))
            rtc.connect('on-ice-candidate', lambda _, m, c: asyncio.run_coroutine_threadsafe(ice(m,c), loop))
            pipeline.set_state(Gst.State.PLAYING)
            control_task = None
            async def controls():
                await asyncio.sleep(2)
                # A coin joins P1, then move right. Stop updates while held to
                # exercise the server's 300 ms stale-input release.
                for _ in range(4):
                    await ws.send_json(dict(type='input', buttons=['coin']))
                    await asyncio.sleep(0.05)
                await ws.send_json(dict(type='input', buttons=[]))
                await asyncio.sleep(2)
                await ws.send_json(dict(type='input', buttons=['right', 'fire']))
            pending = []
            remote = False
            try:
                async with asyncio.timeout(15):
                    async for msg in ws:
                        if msg.type.name != 'TEXT':
                            break
                        data = json.loads(msg.data)
                        print('Signal:', data['type'], flush=True)
                        if data['type'] == 'offer':
                            from pathlib import Path
                            Path('/home/cody/avrana-party/arcade/evidence/test-offer.sdp').write_text(data['sdp'])
                            _, sdp = GstSdp.SDPMessage.new()
                            GstSdp.sdp_message_parse_buffer(data['sdp'].encode(), sdp)
                            offer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdp)
                            await promise('set-remote-description', offer)
                            remote = True
                            for m,c in pending: rtc.emit('add-ice-candidate',m,c)
                            reply = await promise('create-answer', None)
                            answer = reply.get_value('answer').copy()
                            Path('/home/cody/avrana-party/arcade/evidence/test-answer.sdp').write_text(answer.sdp.as_text())
                            await promise('set-local-description', answer)
                            await ws.send_json(dict(type='answer',sdp=answer.sdp.as_text()))
                            if '--controls' in sys.argv:
                                control_task = asyncio.create_task(controls())
                        elif data['type'] == 'ice':
                            if remote: rtc.emit('add-ice-candidate',data['sdpMLineIndex'],data['candidate'])
                            else: pending.append((data['sdpMLineIndex'],data['candidate']))
            except TimeoutError:
                pass
            finally:
                if control_task:
                    control_task.cancel()
                pipeline.set_state(Gst.State.NULL)
    print(json.dumps(counts))
    assert counts['video'] > 100 and counts['audio'] > 100, 'Decoded media missing'


asyncio.run(main())
