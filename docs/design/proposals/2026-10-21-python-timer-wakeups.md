# Proposal: bounded timers for Python kit games (AVR-679)

- **Status:** PROPOSAL, for owner review. Nothing is built. Direction 3 of the [Hearts closure](../../findings/2026-10-20-sdk-clean-room-hearts.md): a review first, "no speculative runtime rewrite".
- **Paths** are Games `origin/main` unless they start with `avrana/` or `docs/`.
- **Evidence:** Hearts r1 G-09 and r2 G06: no autopilot, no turn clock, bots must act inside the request that made them due, and a sleeping phone stalls the table until the Host ends it (`experiments/avr-676-hearts/r2/records/DECISIONS.md` D6, `GAPS.md` G06; r1 `records/DECISIONS.md` D-04, D-05). The guide's answer today is "use Node".

## 1. How a Python kit game runs, and why nothing can wake it

- The server is threaded: `class _Server(http.server.ThreadingHTTPServer)` with `daemon_threads = True` (`avrana_gamekit/runtime.py:154-156`). One request, one thread.
- All game state is guarded by one `threading.Condition()` (`avrana_gamekit/app.py:165`), whose default lock is reentrant. Actions run under it (`app.py:345-352`).
- A long poll blocks in `cond.wait_for(... session.v > since ...)` for at most 25 s (`app.py:61,330-331`). It wakes only when a request thread calls `notify_all`: after an action (`app.py:358`), a launch or end (`app.py:243-247`), or shutdown (`app.py:414-418`).
- So **no code runs unless a request arrives**. The only recurring hook is `service_actions`, about every 0.5 s on the server's main thread, outside the lock, used for the idle stop (`runtime.py:158-161`). It is the wrong tool (section 8).
- The kit README states the consequence: "no timer for absent players" (`avrana_gamekit/README.md:33`); stale timer text elsewhere is listed in `docs/findings/2026-10-20-sdk-readiness-audit.md:44`.
- Bestguess (a Python kit game) has no timer (nothing in `bestguess/session.py` or `server.py`).

## 2. How others do it

- **Node kit.** The game gets `changed()` in `newSession(roster, { changed })` (`avrana_gamekit/js/game-app.mjs:19,32-35,309`). The game owns its `setTimeout`s and calls `changed()` when a timer changes something; the kit concludes a finished session and wakes the polls (`game-app.mjs:477-484`). Single-threaded, so no lock; `shutdown()` is where a game clears its timers (`js/game-runtime.mjs:25`). An uncaught error abandons the session (`game-app.mjs:516-520`).
- **Legacy LAN games.** One `(deadline, gen)` pair per session (`core/session.py:11,127-129`); one asyncio task, replaced on every push (`core/net.py:131-143`); a stale `gen` is ignored (`net.py:156-157`, `session.py:415`); the delay is measured on the monotonic clock because a wall-clock step once fired deadlines early (`session.py:232-240`, `net.py:146-148`, AVR-221); a raising `tick` bumps `gen` and retries in 2 s so it cannot hot-loop (`net.py:161-168`).

Keep the Node shape (a handle given to the game) with the legacy lessons: monotonic, stale-safe, no hot loop.

## 3. API

`new_session(roster)` gains an optional second parameter, as in the options proposal (one-argument games keep working):

```python
def new_session(roster, timers):
    ...
class Session:
    def on_timer(self, name): ...      # called under the kit's lock
# in a session or an action:
timers.after(15.0, "pass_turn")        # seconds from now; same name re-arms (replaces)
timers.cancel("pass_turn")
timers.now()                           # time.monotonic(), for computing deadlines
```

`after` takes a relative delay, so a game never mixes clocks. The browser never sees a monotonic value: a view carries "seconds left as of `v`".

## 4. Scheduler and locking

- **One scheduler thread per process, not per session.** A process hosts one session at a time (`app.py:167,251`). Entries are `(due, seq, name, session)` in a heap; the daemon thread starts on the first `after`.
- It waits on the **same** `app.cond` with `timeout = next_due - clock()`, so scheduling from inside an action wakes it, and it never holds a second lock (no ordering to get wrong).
- When due, it calls `session.on_timer(name)` **under `app.cond`**: timers and actions are serialized exactly like two actions. The callback must not block or use the network.
- After the callback the kit runs the same tail as `_act`: conclude if `session.over`, then `notify_all` (`app.py:356-358`). That tail becomes one method `_changed(session)`, the twin of Node's `changed()`: the only edit to existing code.

## 5. Cancellation

All of a session's timers are dropped by `_forget` (`app.py:243-247`), which every launch, replacement, end and decline already goes through (`app.py:251,271`), and when `session.over` is concluded. A fire also checks `entry.session is app.session` (the pattern at `app.py:334`), so a timer that raced a relaunch does nothing. `close()` and the idle stop stop the thread (`app.py:402-418`). Pending timers are not activity for the idle stop.

## 6. Errors

A raising `on_timer` is caught, logged by exception type only (the kit's logs carry no names or tokens), and **not** re-armed. The session continues; the next action or a game-side re-arm proceeds. The legacy retry in 2 s (`net.py:161-168`) is rejected: a bug repeated forever is worse than once. Owner decision: abandon the session after the first or third failure, as Node does for uncaught errors.

## 7. Bounds

At most 16 pending timers; names `[a-z][a-z0-9_]{0,31}`; delay 0.25 s to 6 h (the minimum stops a self-re-arming callback from spinning); re-arming a name replaces it and does not count twice. A breach raises `TimerRefused(ValueError)` to the game. Precision is "about a second".

## 8. What not to do

No asyncio rewrite or change to `ThreadingHTTPServer`; no thread per session or timer; no `service_actions` (0.5 s steps, wrong thread, outside the lock); no wall clock; no persistence (a restart loses the session anyway); no cron; no autopilot or bot library; no change to the protocol or the Party. Kit modules ship inside a package (`avrana_gamekit/README.md:53`), so there is no Party compatibility question.

## 9. Node parity

Node needs no scheduler. For one meaning across languages, add the same `timers.after / cancel / now` and bounds as a thin layer over `setTimeout`, cleared at session end and followed by `changed()`. Optional.

## 10. Testing

- `Scheduler(clock, thread=False)` with a `FakeClock.advance(s)` that runs due entries synchronously. `GameApp` already takes `clock` and `sleep` (`app.py:144-146`), and a game's `make_app(**options)` forwards them (`runtime.py:118-121,279`).
- **Unit tests:** fires at, not before, the due time; order; replace; cancel; caps; minimum; stale-session no-op; late burst limit; raising callback keeps serving; `_changed` still concludes and reports (`app.py:356-361`).
- **Integration (real clock, short delays):** a parked long poll returns within about a second of a timer that bumps `v`; relaunch and end cancel; `close()` joins the thread.
- **Conformance:** the runner starts the game as a process (`avrana_gamekit/devparty.py:317`), so a fake clock cannot reach it. Add `Fixture.timer_cases`, run **in process** with the fake clock only for games that declare it: arm, advance, assert the `view` and `v`; end and relaunch leave nothing behind; a raising callback does not break the next request. Games without timers are untouched.

## 11. Owner decisions

1. Relative `after` (recommended) versus absolute `at`.
2. Handle passed to `new_session` (recommended) versus a method on the session.
3. Raising callback: log and drop (recommended) or abandon the session.
4. Bounds: 16 timers, 0.25 s to 6 h.
5. Node parity layer: yes or no.
6. In-process fixture path for conformance (recommended).
