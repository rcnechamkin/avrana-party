# Runbook: real-phone BLUFF reconnect and session end in a Party session (AVR-23, AVR-24)

Status: **PREPARED 2026-09-27, not run.** The laptop run is TESTED
(`docs/findings/2026-09-28-bluff-party-reconnect.md`); this is the owner's real-phone check that
AVR-23 still needs. It is a supervised lab run on the Pi's dev port, not a deployment: no sudo, no
nginx, dnsmasq, NetworkManager or systemd change, and the live services keep running.

What it proves: a phone that reloads, sleeps or switches apps during a BLUFF game started from a
Party session comes back to the same seat with the same two cards, by its Party cookie and a fresh
ticket, never by the browser's `wc-token`; a phone asleep when the session ends shows the end
(never a standalone seat); a rematch is joined as a new session; a watcher becomes a player at
the next launch that includes them, without a reload.

What it does not prove: the HTTPS path (`https://party.avrana.net/party/api/…`, `Secure` cookie).
That needs the Party service deployed behind an owner-approved `location /party/api/` on the 443
server, which is a separate, later step. The lab is plain HTTP on `10.42.0.1:8190`.

## 0. Before you start

- Merged or at least pushed for review: the games branch with AVR-22, AVR-23 and AVR-24 together
  (`GAMES_BRANCH` below; the integration branch was `fix/avr-22-23-24-integration`) and the
  avrana-party harness branch `fix/avr-23-party-bluff-reconnect-e2e`. Note both SHAs.
- Two phones on the "Avrana Party" Wi-Fi. Best: one iPhone (Safari) and one Android (Chrome); the
  wake-up failure this work fixed is most likely on iOS. A third browser is optional (step 6).
- Nothing else on the lab port: `ssh party 'ss -ltn | grep -E ":8190 " || echo free'`. If the old
  party-service front door runs there, stop it first (it is yours to stop; it is a lab process).
- No power measurement in progress (each SSH session is a CPU burst).

## 1. Stage the code under `~/avrana-lab/` (no sudo)

The Pi reads `avrana-party` from GitHub but not the private games repository, so the games branch
travels as a bundle (as in `games-fork-deploy.md`):

```bash
# laptop, games checkout:
git bundle create avr23-games.bundle GAMES_BRANCH && scp avr23-games.bundle party:
# Pi:
git -C ~/avrana-lab/avrana-party-games fetch ~/avr23-games.bundle GAMES_BRANCH:avr23-lab \
    && rm ~/avr23-games.bundle
git -C ~/avrana-lab/avrana-party-games worktree add ~/avrana-lab/wt/avr23-games avr23-lab
git -C ~/avrana-lab/avrana-party-docs fetch origin fix/avr-23-party-bluff-reconnect-e2e
git -C ~/avrana-lab/avrana-party-docs worktree add ~/avrana-lab/wt/avr23-party FETCH_HEAD
git -C ~/avrana-lab/wt/avr23-games log --oneline -1; git -C ~/avrana-lab/wt/avr23-party log --oneline -1
```

Check both SHAs against the ones you noted.

## 2. Start the lab (supervised; keep this SSH session open)

The existing games venv has FastAPI and uvicorn; the harness only reads it.

```bash
mkdir -p ~/avrana-lab/playtest
cd ~/avrana-lab/wt/avr23-party
/home/cody/LAN-Games/.venv/bin/python tests/provider/server.py \
    --games ~/avrana-lab/wt/avr23-games --port 8190 --party-session --bind 10.42.0.1 \
    2>&1 | tee ~/avrana-lab/playtest/avr23-$(date +%F-%H%M).log
```

It listens on `127.0.0.1:8190` (the Party's launch reaches the games server only over loopback)
and `10.42.0.1:8190` (the Party Wi-Fi only; not eth0). The throwaway session key lives in a
temporary directory that is deleted when the harness stops. The console shows one `EVENT` line per
join, rejoin and disconnect, with the in-game `pid` (never a ticket or cookie).

## 3. Join and launch

On each phone open `http://10.42.0.1:8190/__harness__/party-lab` (a bare test page; the Party shell
has no Join button yet).

1. Phone A: type a name, tap **Join**. It shows `me: <name> (host)`.
2. Phone B: type another name, tap **Join**. Both pages list both members.
3. Phone A: tap **Launch BLUFF (host)**. Both pages show `game: bluff active, you are a player`.
4. Both: tap **Open BLUFF**, then **I'M READY**; phone A taps **START GAME**.
5. Write down each phone's two cards and seat order. The log shows `join` for `p1` and `p2`.

Fail right here if a phone shows the table without its own cards: it was admitted as a watcher.

## 4. The reconnect checks (phone A first, then repeat on phone B)

Do them in this order; after each one, check the pass conditions before moving on.

| # | Action on the phone | Pass |
|---|---|---|
| R1 | Reload the BLUFF tab (pull down / reload button) | Same seat, same two cards, same name; the log shows `disconnect` then `rejoin` with the same `pid` |
| R2 | Lock the screen for about 15 s (under BLUFF's 30 s `AWAY_GRACE`), unlock, back to the tab | Within about 5 s the RECONNECTING banner goes away; same seat and cards. Phone B shows A as reconnecting during the sleep and back after |
| R3 | Switch to another app for about 20 s, come back | As R2 |
| R4 | Turn Wi-Fi off for about 10 s, then on (stay on the tab) | As R2; never a spectator view |
| R5 | Close the browser tab, then open `http://10.42.0.1:8190/games/bluff/?avrana=1` again | As R1 (a new page, same Party cookie) |

The game timers keep running: if it becomes your turn during a check, play it, and note that the
cards then change by play, not by the reconnect.

Then the session-end checks (both phones on the BLUFF tab; phone A is the host):

| # | Action | Pass |
|---|---|---|
| E1 | Lock phone B. On phone A open the lab page and tap **End game (host)**. Wait 10 s, unlock B | B shows "This game is over." beside Back to Party; no table, no hand; no `join` or `rejoin` for B in the log |
| E2 | Phone A: **Launch BLUFF (host)**, then back to the BLUFF tab | Within about 10 s B's page joins the new game by itself (lobby, its own name, no reload); both ready and start a fresh table |
| E3 | A third phone joins on the lab page while a game runs and opens BLUFF | It watches (card backs only). Phone A: End, then Launch. Within about 10 s the third phone is a player in the new game, no reload |

## 5. Optional: beyond the grace

Lock phone A for about 45 s. Expected (BLUFF's rules, unchanged): phone B shows A as `away`, and
autopilot may answer a prompt for A (it passes, allows, or gives up the first card). On unlock, A
is still in the same seat; any change to A's cards must match a line in the game log.

## 6. Optional: someone who did not join

On a third browser that never joined, open `http://10.42.0.1:8190/games/bluff/?avrana=1`. Pass: it
shows the table as a watcher, with card backs only and no hand of its own.

## 7. Stop and clean up

1. Ctrl-C the harness. `ss -ltn | grep -E ":8190 " || echo free` must say `free`.
2. Keep the log in `~/avrana-lab/playtest/` (runtime data, never committed).
3. Optional: `git -C ~/avrana-lab/avrana-party-games worktree remove ~/avrana-lab/wt/avr23-games`
   and the same for `~/avrana-lab/wt/avr23-party`.

## 8. Record the result

Add a dated file under `docs/findings/` with: both SHAs; each phone's model, OS and browser
version; R1 to R5 pass or fail per phone (plus 5 and 6 if run); whether the banner showed and how
long the return took; and the `EVENT` lines for the checks. AVR-23's real-phone criterion is met
when R1 and R2 pass on at least one real phone; both phones on all of R1 to R5 and E1 to E2 is
the goal (E3 needs a third phone). Any
failure: keep the log, note the step, and do not retry past it.
