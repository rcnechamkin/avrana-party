# Field-session diagnostics

Status: **implemented, NOT RUN on the Pi** (2026-10-21, AVR-697). Unit-tested, and demonstrated against
the dev server on the laptop ([demo](../findings/field-session/2026-10-21-demo-package.txt)).

During a friend test, the operator records what they saw, the appliance's health and the relevant logs.
Afterwards, one bounded package holds all of it with private data removed. You hand that package to
whoever investigates.

**Off by default.** Nothing is recorded until `start` and nothing after `stop`. There is no service,
timer or endpoint. Party Core and its telemetry are unchanged. It records no per-member data: the
status document only carries counts.

## On the night (Pi, the operator's SSH session, no sudo)

```bash
cd /opt/avrana-party/current        # or the checkout, until a deployment carries this tool
F="python3 -m avrana.ops.fieldsession"
$F start --label "four phones bluff"                    # records the Party/Games revisions now
$F mark "all four phones on Party Home" --outcome pass --step A-03
$F mark "phone C stuck on the lobby after reload" --outcome fail --step A-12
$F snapshot                                             # health now (also: --attach-preflight preflight.json)
$F stop                                                 # final snapshot, journal and power excerpts, timeline
$F export --out ~/                                      # ~/avrana-field-<id>.tar.gz, validated first
```

- **Marks:** never type names. Call phones A, B, C, D. Outcomes are `note`, `pass`, `fail`,
  `blocked` and `observed`. `--step` takes the runbook step id.
- **Snapshots:** take one right after each failure you mark. The timeline then shows the service
  states that changed and the status reasons that appeared or cleared.
- **The preflight:** `python3 -m avrana.ops.preflight --json > pf.json`, then
  `$F snapshot --attach-preflight pf.json` (AVR-696). The preflight result goes into the timeline.
- **Guest names:** to prove none slipped into the package, put them in a file, one per line, and pass
  `export --forbid-terms names.txt`. The file is read, never stored.

`$F status` says whether a session is recording. `$F timeline` prints the session as one ordered page.
`$F validate PACKAGE` re-checks any package. It prints rule ids and counts, never the content.

## After the fact: a support bundle (no session needed)

When something went wrong and nobody ran `start`, one command collects the same package for the last
hours (AVR-74, PROTOTYPE; the proposal's decisions are open):

```bash
python3 -m avrana.ops.fieldsession bundle --out ~/ --hours 6            # at most 24; also --attach-preflight, --forbid-terms
```

It takes one snapshot now, then the journal and power lines from `--hours` ago until now, through the
same writer, bounds, redaction and validator. The package is `avrana-field-<id>-support-<N>h.tar.gz`,
and its `session.json` says `"kind": "support"` with the window. It is refused while a session is
recording (stop and export that one), and nothing is written if validation fails. Nothing is sent
anywhere: hand the file over yourself.

## What a package holds

| Member | Content | Source |
|---|---|---|
| `session.json` | id, label, start/stop, limits, the Party/Games/web/contract revisions at start and stop, collector SHA | `/party/api/status` |
| `events.jsonl` | start, marks (scrubbed, at most 200 characters each), snapshots, stop | the operator |
| `snapshots/NNN.json` | the status document, Pi health state, optional preflight summary | `/party/api/status`, `/run/avrana/pi-health.json` |
| `journal.jsonl` | `at`, `priority`, `unit` and `message` for Avrana units and kernel warnings inside the window, at most 1500 lines; warnings are kept first | `journalctl` |
| `throttle.jsonl` | power and temperature records inside the window | `/var/log/avrana/pi-throttle.jsonl` |
| `timeline.md` | every event in order, with service transitions, journal warnings and errors, and revisions | built from the above |
| `manifest.json` | sha256 and size of every member, the redaction rules version | built at export |

The same session always exports to the same bytes: members are sorted, timestamps fixed and
ownership zeroed.

## What never leaves the appliance

The rules live in `avrana/ops/redact.py` (`avrana.redaction/v2`). Every string is scrubbed before
it is written. The export runs the validator, and a package with any hit is not written.

- **Credentials and keys:**
  - PEM blocks;
  - 32 or more hex characters outside a revision field (game keys are 64);
  - device tokens, caught by shape;
  - `Authorization`, bearer and basic tokens;
  - `password=` / `token=` / `ticket=` values.
- **Membership cookies:** `__Host-avrana_device`, `avrana_device`, `avrana_limited`, and every
  `Cookie:` or `Set-Cookie:` line.
- **Per-member and per-device identifiers:** `member-…` and `device-…`. `devices.json` is never read.
- **Device records:**
  - IPv4 addresses other than `127.0.0.1` and `10.42.0.1`;
  - IPv6 addresses;
  - MAC addresses;
  - e-mail addresses;
  - all NetworkManager and dnsmasq logs, which are not collected.
- **Raw chat and player data:**
  - every journal line that mentions chat is dropped whole;
  - quoted text is removed, because names land in logs as quoted strings;
  - fields named like `name`, `nickname`, `text`, `peer`, `user_agent` or `device_id` are replaced.
- **Wi-Fi and other secrets in assignments:** `psk=`, `passphrase=`, `pwd=` and `pin=` values.
- **Fields:** camelCase names (`playerName`, `deviceId`) are read like snake_case. JSON keys are
  scrubbed like values. Count fields such as `members` keep only numbers.
- **Digests:** a 40-character commit is kept only at revision paths, and a 64-character sha256 only at
  `nginx_site.sha256` and the manifest's `files.<name>.sha256`. A game key under any other name is
  redacted.

A package someone hands you is refused by `validate` when:
- a member's name is outside the package's own directory or unknown;
- a member appears twice;
- a member is not a regular file;
- the manifest is malformed or does not list every member.

The automated suite is `python -m unittest discover -s tests/unit -p test_fieldsession.py`. For every
planted kind of secret, it checks two things:
- scrubbing removes it;
- the validator catches it when it was not scrubbed.

It also covers:
- a fuzz run of random secrets in random text;
- a 20,000-token check that a bare device token is caught by its shape alone;
- the poisoned journal fixture (`tests/fixtures/field-session/poisoned-journal.json`);
- tampering, unexpected members and the size limits.

## Bounds

- A session directory refuses new data at `--max-bytes` (default 1.5 MiB). `stop` then trims the journal and power records to the budget left, so a stopped session always fits one package (2 MiB).
- A session expires after `--max-hours` (default 12). After that, marks and snapshots are refused.
- Journal lines are cut at 300 characters each. A package over 2 MiB is not exported.
- Sessions live under `~/avrana-field-sessions` (mode 0700) or `$AVRANA_FIELD_SESSIONS`. Delete a
  session directory when you no longer need it.

## Not verified

- **Not run on the Pi.** Confirm on the first real run that the operator can read the journal. If
  not, `stop` records the journalctl error and the package says so: add the operator to
  `systemd-journal`, which is an owner decision.
- Phones are not observed. What a phone showed is only what the operator marks.
- The journal is volatile until AVR-29 is installed. Export before any reboot.
