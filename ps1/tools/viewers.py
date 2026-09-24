#!/usr/bin/env python3
"""Simulated phones for the PS1 shared stream (Playwright Chromium, one isolated
browser context per phone, so each has its own localStorage token and its own
WebSocket, exactly like separate devices). Players tap the page's real on-screen
buttons with pointer events, so input takes the same path as a phone.

  viewers.py URL --players N --watchers M --seconds S [--moves FILE] [--out FILE]
--moves: JSON list of [t_seconds, player(1-based), button, hold_ms]; button is one
of up/down/left/right/cross/circle/square/triangle/l1/r1/l2/r2/start/select.
"""
import argparse, asyncio, json, time
from playwright.async_api import async_playwright

BITS = {n: i for i, n in enumerate('up down left right cross circle square triangle l1 r1 l2 r2 start select'.split())}

async def phone(browser, url, watch, idx, results, stop):
    ctx = await browser.new_context(viewport={'width': 900, 'height': 900})
    page = await ctx.new_page()
    rec = results.setdefault(idx, dict(role=None, slot=None, samples=[], errors=[]))
    rec['page'] = page
    page.on('pageerror', lambda e: rec['errors'].append(str(e)))
    await page.goto(url)
    await page.click('#watch' if watch else '#connect')
    await page.wait_for_function('document.querySelector("video").readyState >= 2', timeout=20000)
    rec['role'] = await page.text_content('#role')
    rec['connected_at'] = time.time()
    while not stop.is_set():
        await asyncio.sleep(1)
        txt = await page.text_content('#metrics')
        if txt and txt.startswith('{'):
            rec['samples'].append(json.loads(txt))
    return ctx

async def press(page, button, hold_ms):
    box = await page.locator(f'[data-bit="{BITS[button]}"]').bounding_box()
    await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    await page.mouse.down()
    await asyncio.sleep(hold_ms / 1000)
    await page.mouse.up()

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('url'); ap.add_argument('--players', type=int, default=1)
    ap.add_argument('--watchers', type=int, default=0); ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--moves'); ap.add_argument('--out')
    ap.add_argument('--control', help='append lines "P button ms" (P=1..4, or several joined by +), "shot NAME" or "quit" while running')
    a = ap.parse_args()
    results, stop = {}, asyncio.Event()
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        pages = {}
        tasks = []
        for i in range(a.players + a.watchers):   # connect in order -> deterministic slots
            ctx_task = asyncio.create_task(phone(browser, a.url, i >= a.players, i, results, stop))
            tasks.append(ctx_task)
            for _ in range(100):
                if results.get(i, {}).get('role'):
                    break
                await asyncio.sleep(0.2)
            print(f'phone {i}: {results.get(i, {}).get("role")}', flush=True)
        t0 = time.time()
        if a.moves:
            moves = json.load(open(a.moves))
            # pages by slot number
            await asyncio.sleep(1)
            async def run(m):
                t, player, button, hold = m
                await asyncio.sleep(max(0, t0 + t - time.time()))
                pg = next((r['page'] for r in results.values() if r['role'] == f'Player {player}'), None)
                if pg:
                    await press(pg, button, hold)
            await asyncio.gather(*(run(m) for m in moves))
        if a.control:
            open(a.control, 'w').close()
            done = 0
            by_slot = lambda n: next((r['page'] for r in results.values() if r['role'] == f'Player {n}'), None)
            while time.time() < t0 + a.seconds:
                lines = open(a.control).read().splitlines()
                for line in lines[done:]:
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0] == 'sleep':
                        await asyncio.sleep(int(parts[1]) / 1000 if len(parts) > 1 else 1)
                    elif parts[0] == 'debug':
                        for i, r in results.items():
                            info = await r['page'].evaluate('''() => ({hidden: document.querySelector("#controls").hidden,
                                status: document.querySelector("#status").textContent, role: document.querySelector("#role").textContent})''')
                            print('debug', i, info, flush=True)
                    elif parts[0] == 'quit':
                        a.seconds = 0
                    elif parts[0] == 'shot':
                        # Screenshot a viewer's decoded <video>: proves what the stream shows.
                        viewer = results[max(results)]['page']
                        await viewer.locator('video').screenshot(path=parts[1])
                        print('shot', parts[1], flush=True)
                    else:
                        # "1+2+3 up 400": simultaneous presses from several phones
                        try:
                            await asyncio.gather(*(press(by_slot(int(n)), parts[1], int(parts[2]))
                                                   for n in parts[0].split('+')))
                        except Exception as e:
                            print('bad control line', line, e, flush=True)
                done = len(lines)
                await asyncio.sleep(0.1)
        await asyncio.sleep(max(0, t0 + a.seconds - time.time()))
        stop.set()
        await asyncio.sleep(1.5)
        summary = {}
        for i, r in results.items():
            vs = [s.get('video') or {} for s in r['samples'][2:]]
            fps = [v.get('fps') for v in vs if v.get('fps')]
            kbps = [v.get('kbps') for v in vs if v.get('kbps') is not None]
            jb = [v.get('jitterBufMs') for v in vs if v.get('jitterBufMs') is not None]
            ack = [s['ackRtt']['p50'] for s in r['samples'] if s.get('ackRtt', {}).get('p50') is not None]
            summary[i] = dict(role=r['role'], n=len(vs), fps_avg=round(sum(fps)/len(fps), 1) if fps else None,
                              kbps_avg=round(sum(kbps)/len(kbps)) if kbps else None,
                              jitter_ms_avg=round(sum(jb)/len(jb), 1) if jb else None,
                              lost=sum(v.get('pktLostD') or 0 for v in vs),
                              dropped=sum(v.get('dropped') or 0 for v in vs),
                              freezes=(vs[-1].get('freezes') if vs else None),
                              ack_rtt_p50=sorted(ack)[len(ack)//2] if ack else None,
                              errors=r['errors'][:3])
        print(json.dumps(summary, indent=1))
        if a.out:
            json.dump(dict(summary=summary, raw={i: r['samples'] for i, r in results.items()}), open(a.out, 'w'))
        await browser.close()

asyncio.run(main())
