"""Slot/token ownership logic of stream_ps1.py with GStreamer/aiohttp stubbed out:
runs anywhere (no Pi, no load).  python3 ps1/tests/test_slots.py"""
import asyncio, sys, types
fake = types.ModuleType('stream')
class Stream:
    def __init__(self): self.pads=[]; self.peers={}; self.serial=0
fake.Stream=Stream; fake.Gst=fake.GstWebRTC=fake.GstSdp=None
fake.web=types.SimpleNamespace(); fake.log=types.SimpleNamespace(info=print, warning=print)
fake.ROOT=None; fake.ap_addresses=lambda: set(); fake.Window=object
sys.modules['stream']=fake
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stream_ps1 as m

class Pad:
    def __init__(self): self.mask=0; self.releases=0
    def set(self, b): self.mask=b
    def release_all(self): self.mask=0; self.releases+=1
class WS:
    def __init__(self, n): self.n=n; self.closed=False; self.close_code=None
    async def close(self, code=None, message=None): self.closed=True; self.close_code=code

async def main():
    s=m.PS1Stream('bomberman'); s.loop=asyncio.get_running_loop(); s.pads=[Pad() for _ in range(4)]
    m.GRACE=0.2
    a,b,c,d,e=(WS(i) for i in range(5))
    ra=[s.claim(w, None, False) for w in (a,b,c,d)]
    assert [x[0] for x in ra]==[0,1,2,3], ra
    assert s.claim(e, None, False)==(None,None), 'full -> spectator'
    assert s.claim(WS(9), ra[0][1], True)==(None,None), 'watch role never gets a slot'
    # spoof: garbage / non-ascii / other token lengths
    for bad in ['x'*20, 'é'*20, 'short', 123, None]:
        slot,_=s.claim(WS(8), bad, False); assert slot is None, bad
    # takeover by token: old socket replaced, old finally must not clear new owner's buttons
    a2=WS(10); slot,tok=s.claim(a2, ra[0][1], False); assert (slot,tok)==(0,ra[0][1])
    await asyncio.sleep(0); assert a.closed and a.close_code==4001
    s.pads[0].set(0b1); s.release(0, a); assert s.pads[0].mask==0b1, 'old socket cleared new owner'
    # disconnect -> grace -> reclaim within grace keeps slot
    s.pads[1].set(0b10); s.release(1, b); assert s.pads[1].mask==0 and s.owners[1]['ws'] is None
    b2=WS(11); assert s.claim(b2, ra[1][1], False)[0]==1
    # disconnect -> grace expiry frees slot, stale token no longer works
    s.release(2, c); await asyncio.sleep(0.3); assert s.owners[2] is None
    slot,newtok=s.claim(WS(12), ra[2][1], False); assert slot==2 and newtok!=ra[2][1], 'stale token must not get old identity'
    print('slot/token logic OK')
asyncio.run(main())
