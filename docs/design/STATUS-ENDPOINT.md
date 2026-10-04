# Status endpoint: `GET /party/api/status` (`avrana.status/v0`)

Status: **implemented on main (AVR-232)**; served by Party Core (`avrana/party/service.py` via
`avrana/ops/status.py`) under the `/party/api/` prefix nginx already forwards, so deploying the
Party Core code is enough. Whether production serves it is a [SYSTEM](../SYSTEM.md) question.

## Purpose

One request answers, for a person or an agent: *what exact Avrana build is running right now,
and is it healthy?*

```sh
curl -s https://party.avrana.net/party/api/status | python3 -m json.tool      # phone, laptop on the Party LAN
curl -s -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/status   # on the Pi
```

The Host guard applies like on every Party route; no cookie or identity is needed. The document
is cached for 5 seconds so phones cannot turn it into a `systemctl` storm.

## Shape

| Field | Content |
|---|---|
| `schema`, `generated_at`, `cached` | `avrana.status/v0`, UTC time, whether this answer came from the cache |
| `deployment` | the [deployment manifest](DEPLOYMENT-MANIFEST.md) without filesystem paths and operator login, or `null`; `manifest_error` says why when malformed |
| `party`, `games` | `{deployed_sha, checkout_sha, dirty, untracked, deployed_dirty, ref, mismatch}`: what the manifest says was deployed versus what is on disk now. `dirty` = tracked files modified now; `untracked` = count of untracked, non-ignored files; `deployed_dirty` = the deployment itself was made with `--allow-dirty` |
| `web_release` | `{build, commit}` of the installed `/party/` shell |
| `contract` | `{party_games, party_session, lan_launch, games_advertises}`: what Party implements and what the games server advertises at `/api/games` |
| `services` | each configured systemd unit: `active`, `inactive`, `failed`, `not-installed`, `unknown` or `unavailable` |
| `certificate` | `{not_after, days_left, status}` with `ok`, `expiring` (< 21 days), `expired` or `unavailable` |
| `party_core` | `{ok, uptime_s, members, session: {game, state} or null}` from inside the service |
| `games_provider` | `{ok, integration, compatible}` from loopback `:8096/api/games` |
| `arcade` | `{ok, state, players, max_players, party_managed, emulator_running, error, video_frames, sample_age_s}` from loopback `:8098/stats` |
| `summary` | `{state: ok, degraded or unknown; reasons; notes}` |

`unknown` means something could not be observed (no manifest yet, `systemctl` unavailable);
it is never reported as `ok`. `degraded` lists its reasons. `notes` carries facts that are not
problems on an undeployed checkout (a dirty development tree).

A unit that systemd does not know is `not-installed`. That degrades the summary, except for the
units named in the config's `optional_units` (default: `avrana-party-certificate.timer`, which
exists only once automatic renewal has been set up; see [party-https](../runbooks/party-https.md)):
those are listed in `notes`. An optional unit that is installed and `inactive` or `failed`
degrades like any other.

## Never included

Keys, tokens, cookies, environment variables, logs, peer or phone addresses, request data,
filesystem paths and the operator's login (those two stay in the manifest file on the Pi). The
arcade `peers` list is dropped on purpose. `tests/unit/test_ops_status.py` asserts this.

## Configuration

Optional `"status"` block in `/etc/avrana-party/party-core.json`
([example](../../deploy/party-core/party-core.example.json)): `manifest`, `party_checkout`,
`games_checkout`, `web_root`, `certificate`, `games_url`, `arcade_url`, `units`. Unknown keys are
ignored; defaults match the appliance layout in SYSTEM.

## Consumers

`python3 -m avrana.ops.smoke` fails when the summary is `degraded`; `/party/diag/` shows the
build and lets a person copy it into a field report; `tools/reconcile.py --status-url` compares
the deployed SHAs with `main`; agents read it to learn the deployed version before changing code.
