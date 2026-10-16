#!/usr/bin/env python3
"""Four-player journey over the REAL Party service and the REAL BLUFF game server (Tier 2).

Evidence level: simulation on one machine. Real: avrana.party.service (Party Core, HTTP routes, the
launch/end GameLink, tickets), the Games repository's server.py and core/net.py over uvicorn, and
four real WebSocket clients speaking the party-session protocol. Not real: phones, Wi-Fi, a browser,
nginx/TLS, systemd, the Pi, wall-clock presence (a controllable clock drives Party timers). A PASS
here never closes a physical gate (AVR-10/12/27); it shows the protocol journey works.

    python tools/acceptance/four_player_journey.py --games PATH_TO_GAMES_CHECKOUT [--out DIR]

Run it with an interpreter that has the Games requirements (fastapi, uvicorn, websockets).
Scenarios (each on a fresh stack): J1 join/launch/private views/play to the end/go home/play again,
J2 a dropped phone returns to its seat and hand, J3 the Host's phone vanishes mid-round, J4 every
phone vanishes (TABLE_ABANDON) and the next arrival starts a new round, J5 the Host ends a live
round and a stale ticket is refused. Writes journey-<stamp>.json and .md under --out.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

PARTY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PARTY_ROOT))

NAMES = ["Ada", "Ben", "Cleo", "Dev"]


def _git(root, *args):
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:
        return "unknown"


class Evidence:
    """Ordered PASS/FAIL checks with timings, written as JSON and Markdown."""

    def __init__(self, meta):
        self.meta, self.rows, self.metrics = meta, [], {}
        self.scenario = ""

    def begin(self, name):
        self.scenario = name

    def check(self, label, ok, detail=""):
        self.rows.append({"scenario": self.scenario, "check": label,
                          "status": "PASS" if ok else "FAIL", "detail": str(detail)})
        print(("PASS  " if ok else "FAIL  ") + f"[{self.scenario}] {label}" + (f"  ({detail})" if detail else ""))
        return ok

    def metric(self, name, value):
        self.metrics.setdefault(name, []).append(value)

    def failed(self):
        return [r for r in self.rows if r["status"] == "FAIL"]

    def write(self, out):
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (out / f"journey-{stamp}.json").write_text(
            json.dumps({"meta": self.meta, "results": self.rows, "metrics": self.summary()}, indent=2))
        lines = ["# Four-player journey (Tier 2: real Party service + real BLUFF server, no phones)", "",
                 *[f"- {k}: `{v}`" for k, v in self.meta.items()], "",
                 "| Scenario | Check | Result | Detail |", "|---|---|---|---|"]
        lines += [f"| {r['scenario']} | {r['check']} | {r['status']} | {r['detail']} |" for r in self.rows]
        lines += ["", "## Measured", "", *[f"- {k}: {v}" for k, v in self.summary().items()]]
        (out / f"journey-{stamp}.md").write_text("\n".join(lines) + "\n")
        return out / f"journey-{stamp}.md"

    def summary(self):
        out = {}
        for k, v in self.metrics.items():
            v = sorted(v)
            out[k] = {"n": len(v), "p50_ms": round(statistics.median(v), 1),
                      "p95_ms": round(v[min(len(v) - 1, int(len(v) * 0.95))], 1), "max_ms": round(v[-1], 1)}
        return out


class Client:
    """One phone: a real WebSocket to the game, holding the last state it was sent."""

    def __init__(self, name, device, stack):
        self.name, self.device, self.stack = name, device, stack
        self.ws, self.state, self.pid, self.seen, self.ended_msg = None, None, None, [], None

    def connect(self):
        from websockets.sync.client import connect
        self.ws = connect("ws://127.0.0.1:%d/games/bluff/ws" % self.stack.game_port, open_timeout=5)
        self.ws.send(json.dumps({"t": "hello", "ticket": self.stack.ticket(self)}))
        return self

    def send(self, **msg):
        self.ws.send(json.dumps(msg))

    def pump(self, timeout=0.05):
        """Read whatever is waiting; remember the newest state. False once the socket closed."""
        if self.ws is None:
            return False
        try:
            while True:
                m = json.loads(self.ws.recv(timeout=timeout))
                timeout = 0.001
                self.seen.append(m)
                if m.get("type") == "welcome":
                    self.pid = m.get("pid")
                elif m.get("type") == "state" and m.get("game"):
                    self.state = m["game"]
                elif m.get("kind") == "party_ended":
                    self.ended_msg = m
        except TimeoutError:
            return True
        except Exception:
            return False

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


class Stack:
    """The real party service + the real Games server on loopback ephemeral ports."""

    def __init__(self, games_root, key_mod, clock):
        sys.path.insert(0, str(games_root))
        os.chdir(games_root)
        import uvicorn
        from avrana.party import identity, service, sessions
        from core import party_protocol, party_session
        from core import session as base_session
        from core.net import GameBinding
        from games.bluff import game as bluff
        import server
        self.party_protocol, self.sessions = party_protocol, sessions
        base_session.COUNTDOWN_SECONDS, base_session.GAME_END_SECONDS = 0.1, 0.5
        self.key = party_protocol.new_key()
        self.tmp = tempfile.TemporaryDirectory()
        store = identity.DeviceStore(os.path.join(self.tmp.name, "devices.json"))
        self.svc = service.PartyService(store, service.load_games({"bluff": {"max_players": 6}}), clock=clock)
        cfg = service.Config({"127.0.0.1"}, {"http://127.0.0.1"}, secure_cookie=False)
        self.party = service.make_server(self.svc, cfg, port=0)
        threading.Thread(target=self.party.serve_forever, daemon=True).start()
        party_url = "http://127.0.0.1:%d" % self.party.server_address[1]
        self.binding = server.bindings["bluff"]
        self.binding.party = party_protocol.GameSide(self.key, "bluff")
        self.binding.party_url = party_session.party_url(party_url)
        fresh = GameBinding("bluff", bluff.BluffSession(rng=random.Random(7)))
        for name, value in vars(fresh).items():
            if name not in ("party", "party_url"):
                setattr(self.binding, name, value)
        self.game = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
        threading.Thread(target=self.game.run, daemon=True).start()
        deadline = time.time() + 10
        while not self.game.started and time.time() < deadline:
            time.sleep(0.02)
        if not self.game.started:
            raise RuntimeError("the games server did not start")
        self.game_port = self.game.servers[0].sockets[0].getsockname()[1]
        endpoints = {"bluff": sessions.GameEndpoint("bluff", "http://127.0.0.1:%d/games/bluff" % self.game_port, self.key)}
        self.svc.link = sessions.HttpGameLink(endpoints, timeout=5)
        extra, internal = sessions.routes(self.svc, endpoints)
        self.party.RequestHandlerClass.extra_routes = extra
        self.party.RequestHandlerClass.internal_routes = internal
        self.clients = []

    def join(self, name):
        _, device = self.svc.store.issue()
        self.svc.call("join", device, name)
        c = Client(name, device, self)
        self.clients.append(c)
        return c

    def version(self):
        return self.svc.core.party.version

    def session(self):
        return self.svc.core.party.session

    def ticket(self, c):
        with self.svc.lock:
            s, p = self.svc.core.participant_for(c.device)
            host = p.member_id == self.svc.core.party.host_id     # as the party's ticket route does
        return self.party_protocol.mint_ticket(self.key, "bluff", s.id, p.id, p.role, host=host)

    def follow(self, *clients):
        """What a phone's open page does continuously: a party request, so the Party sees it here."""
        for c in clients:
            self.svc.view(c.device)

    def pump_all(self):
        for c in self.clients:
            c.pump()

    def stop(self):
        for c in self.clients:
            c.close()
        self.game.should_exit = True
        self.party.shutdown()
        self.party.server_close()
        self.tmp.cleanup()


def wait_for(stack, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        stack.pump_all()
        if pred():
            return True
        time.sleep(0.01)
    return False


def seat_up(stack, ev, names=NAMES):
    clients = [stack.join(n) for n in names]
    host = clients[0]
    t0 = time.perf_counter()
    s = stack.svc.launch(host.device, "bluff", stack.version())
    ev.check("host launches BLUFF for the party", s.state == "active", getattr(s, "detail", s.state))
    for c in clients:
        c.connect()
    ok = wait_for(stack, lambda: all(c.pid for c in clients))
    ev.check("all four phones get a welcome with a seat", ok, f"{(time.perf_counter() - t0) * 1000:.0f} ms")
    ev.metric("launch_to_all_welcomed_ms", (time.perf_counter() - t0) * 1000)
    for c in clients:
        c.send(t="ready", ready=True)
    time.sleep(0.2)
    host.send(t="start")
    ok = wait_for(stack, lambda: stack.binding.session.phase == "playing" and all(c.state for c in clients))
    ev.check("round starts; every phone has a table state", ok)
    return clients, s


def private_views_ok(clients):
    """Each phone sees only its own cards; the public seat list never carries another's hand."""
    for c in clients:
        me = (c.state or {}).get("me") or {}
        if len(me.get("cards", [])) != 2:
            return False
        for seat in c.state["seats"]:
            if "cards" in seat:
                return False
        others = {x.pid for x in clients if x is not c}
        if me.get("pid") in others:
            return False
    return True


def play_until(stack, clients, ev, done, drop=(), limit=600):
    """Drive turns like four people would: income to 7, then coup; the loser gives up a card."""
    sent = 0
    sent_at = {}
    while not done() and sent < limit:
        stack.pump_all()
        moved = False
        for c in clients:
            if c in drop or not c.state or not c.state.get("me"):
                continue
            me, pend = c.state["me"], c.state["pending"]
            step = pend["step"]
            if me.get("prompt") and me["prompt"]["kind"] == "lose":
                c.send(t="lose", card=0, step=step)
            elif me.get("actions"):
                acts = {a["action"]: a for a in me["actions"]}
                if "coup" in acts and (c.state["seats"][[s["pid"] for s in c.state["seats"]].index(me["pid"])]["coins"] >= 7):
                    a = acts["coup"]
                    c.send(t="act", action="coup", target=a["targets"][0], step=step)
                else:
                    c.send(t="act", action="income", step=step)
            else:
                continue
            if sent_at.get(c.name) != step:
                sent_at[c.name] = step
                sent += 1
                t0 = time.perf_counter()
                end = time.time() + 5
                while time.time() < end:
                    stack.pump_all()
                    if any(x.state and x.state["pending"]["step"] != step for x in clients if x not in drop):
                        ev.metric("action_to_new_state_ms", (time.perf_counter() - t0) * 1000)
                        break
                moved = True
        if not moved:
            time.sleep(0.01)
    return sent


def finish(stack, clients, ev, label, drop=()):
    s = stack.session()
    sent = play_until(stack, clients, ev, lambda: s.state == "ended", drop=drop)
    ok = wait_for(stack, lambda: s.state == "ended", 15)
    ev.check(f"{label}: BLUFF played to a winner and Party recorded the end", ok and s.outcome == "completed",
             f"{sent} moves, outcome={s.outcome}")
    return s


def j1(games, ev, clock):
    ev.begin("J1 four phones, full game, play again")
    st = Stack(games, None, clock)
    try:
        clients, s = seat_up(st, ev)
        ev.check("private hands: each phone sees only its own two cards", private_views_ok(clients))
        ev.check("the spectator-omniscient view is not sent to players",
                 all(not c.state.get("omniscient") for c in clients))
        s = finish(st, clients, ev, "round 1")
        ev.check("result accepted by Party Core (structured standings, 4 entries)",
                 s.result_refused is None and s.result and len(s.result["standings"]) == 4,
                 getattr(s, "result_refused", None))
        ev.check("Party is on the results screen", st.svc.core.location()["at"] == "results")
        host = clients[0]
        st.svc.go_home(host.device, st.version())
        ev.check("Host sends everyone home; Party has no active game", st.svc.core.view(host.device)["state"] == "lobby")
        ok = wait_for(st, lambda: st.binding.party_room_sid is None)
        ev.check("the game released its room (no residual occupied room)", ok)
        for c in clients:
            c.close()
        t0 = time.perf_counter()
        s2 = st.svc.launch(host.device, "bluff", st.version())
        ev.check("play again: a new session, different id", s2.state == "active" and s2.id != s.id)
        for c in clients:
            c.state, c.pid, c.seen = None, None, []
            c.connect()
        clients2 = clients
        for c in clients2:
            c.send(t="ready", ready=True)
        time.sleep(0.2)
        host.send(t="start")
        ok = wait_for(st, lambda: st.binding.session.phase == "playing" and all(c.state for c in clients2))
        ev.check("round 2 starts for all four with fresh hands", ok and private_views_ok(clients2),
                 f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        finish(st, clients2, ev, "round 2")
    finally:
        st.stop()


def j2(games, ev, clock):
    ev.begin("J2 reconnect to the same seat")
    st = Stack(games, None, clock)
    try:
        clients, s = seat_up(st, ev)
        victim = clients[2]
        hand, pid = list(victim.state["me"]["cards"]), victim.pid
        victim.close()
        ok = wait_for(st, lambda: any(x["pid"] == pid and x["presence"] != "here"
                                      for x in clients[0].state["seats"]))
        ev.check("others see the dropped phone as not here (seat held)", ok)
        t0 = time.perf_counter()
        victim.state, victim.pid = None, None
        victim.connect()
        ok = wait_for(st, lambda: victim.state is not None and victim.pid == pid)
        ev.check("fresh ticket returns the same seat", ok, f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        ev.metric("reconnect_to_state_ms", (time.perf_counter() - t0) * 1000)
        ev.check("same private hand after reconnect", victim.state and victim.state["me"]["cards"] == hand)
        finish(st, clients, ev, "after reconnect")
    finally:
        st.stop()


def j3(games, ev, clock, advance):
    ev.begin("J3 Host's phone vanishes mid-round")
    st = Stack(games, None, clock)
    try:
        from avrana.party import core as pcore
        clients, s = seat_up(st, ev)
        host = clients[0]
        host.close()
        st.follow(*clients[1:])
        advance(pcore.LIVE_WINDOW + pcore.HOST_GRACE + 5)
        st.follow(*clients[1:])
        st.svc.tick()
        ev.check("the round is still active (Host away does not end it)", s.state == "active")
        host_now = st.svc.core.party.host_id
        hm = [m for m in st.svc.core.party.members.values() if m.name == "Ada"][0]
        ev.check("RECORD: Host unchanged while away mid-round", host_now == hm.id, f"host={host_now}")
        done = finish(st, clients, ev, "remaining three finish", drop=(host,))
        ev.check("RECORD: the vanished Host's seat is forfeited or autopiloted, game still completes", done.state == "ended")
        st.follow(*clients[1:])
        advance(pcore.LIVE_WINDOW + pcore.HOST_GRACE + 5)
        st.follow(*clients[1:])
        st.svc.tick()
        new_host = st.svc.core.party.host_id
        ev.check("after the round, Host succession moves to a present player", new_host is not None and new_host != hm.id,
                 f"new host={new_host}")
    finally:
        st.stop()


def j4(games, ev, clock, advance):
    ev.begin("J4 every phone vanishes (abandoned table)")
    st = Stack(games, None, clock)
    try:
        from avrana.party import core as pcore
        clients, s = seat_up(st, ev)
        for c in clients:
            c.close()
        advance(pcore.LIVE_WINDOW + 60)
        st.svc.tick()
        ev.check("before the bound the round is still active", s.state == "active")
        advance(pcore.TABLE_ABANDON + 5)
        st.svc.tick()
        ev.check("after the bound the round ends as abandoned", s.state == "ended" and s.outcome == "abandoned",
                 f"{s.state}/{s.outcome}")
        ok = wait_for(st, lambda: st.binding.party.sid is None and st.binding.party_room_sid is None, 8)
        ev.check("the game was told to end and holds no room", ok)
        ev.check("Party location is home", st.svc.core.location()["at"] == "home", st.svc.core.location()["at"])
        arriver = st.join("Eve")
        advance(1)
        st.svc.view(arriver.device)
        host_id = st.svc.core.party.host_id
        s2 = st.svc.launch(arriver.device, "bluff", st.version())
        ev.check("the next arrival can start a new round without a developer", s2.state == "active" and s2.id != s.id,
                 f"host before={host_id}")
    finally:
        st.stop()


def j5(games, ev, clock):
    ev.begin("J5 Host ends a live round; stale ticket refused")
    st = Stack(games, None, clock)
    try:
        clients, s = seat_up(st, ev)
        old_ticket = st.ticket(clients[1])
        st.svc.end(clients[0].device, st.version())
        ev.check("Host's End confirmed by the game", s.state == "ended" and s.outcome == "ended_by_host"
                 and s.game_confirmed_end is True)
        ok = wait_for(st, lambda: all(c.ended_msg for c in clients[1:]))
        ev.check("every phone is told the party ended", ok)
        from websockets.sync.client import connect
        ws = connect("ws://127.0.0.1:%d/games/bluff/ws" % st.game_port, open_timeout=5)
        ws.send(json.dumps({"t": "hello", "ticket": old_ticket}))
        got_welcome, end = False, time.time() + 2
        while time.time() < end:
            try:
                m = json.loads(ws.recv(timeout=0.3))
                got_welcome |= m.get("type") == "welcome"
            except Exception:
                break
        ev.check("the old session's ticket is refused", not got_welcome)
        ws.close()
        s2 = st.svc.launch(clients[0].device, "bluff", st.version())
        ev.check("a new round can start straight away", s2.state == "active")
    finally:
        st.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", default=os.environ.get("AVRANA_GAMES_REPO"), help="Games repository checkout")
    ap.add_argument("--out", default=str(PARTY_ROOT / "test-results" / "acceptance"))
    ap.add_argument("--only", help="comma list of J1..J5")
    args = ap.parse_args(argv)
    if not args.games or not (Path(args.games) / "server.py").exists():
        print("need --games (or AVRANA_GAMES_REPO) pointing at an avrana-party-games checkout", file=sys.stderr)
        return 2
    games = Path(args.games).resolve()
    import logging
    logging.disable(logging.WARNING)             # the games server logs every event; evidence is the table
    offset = [0.0]
    clock = lambda: time.monotonic() + offset[0]

    def advance(seconds):
        offset[0] += seconds

    meta = {"party_sha": _git(PARTY_ROOT, "rev-parse", "HEAD"), "games_sha": _git(games, "rev-parse", "HEAD"),
            "python": sys.version.split()[0], "platform": sys.platform,
            "evidence_level": "Tier 2 simulation: real Party service + real BLUFF server + 4 real WebSockets",
            "when_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ev = Evidence(meta)
    scenarios = {"J1": lambda: j1(games, ev, clock), "J2": lambda: j2(games, ev, clock),
                 "J3": lambda: j3(games, ev, clock, advance), "J4": lambda: j4(games, ev, clock, advance),
                 "J5": lambda: j5(games, ev, clock)}
    for name, fn in scenarios.items():
        if args.only and name not in args.only.split(","):
            continue
        try:
            fn()
        except Exception as exc:
            ev.check("scenario ran to the end", False, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
    path = ev.write(Path(args.out))
    print(f"\nwrote {path}; {len(ev.rows) - len(ev.failed())} pass, {len(ev.failed())} fail")
    return 1 if ev.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
