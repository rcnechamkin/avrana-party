# PS1 title profiles: first-party provider data (AVR-309)

Status: **data and checks only; nothing here launches an emulator** (2026-10-07).

On `main` there is still no PS1 service, unit, nginx route, appliance grant, Party Core key or phone
page, and the catalog lists both titles as experimental and not installed. What exists is the source
half: two title profiles, a strict loader, deterministic RetroArch configuration, a check of the
owner's content and an XTest keyboard input provider, proven by fixture tests that use a few
synthetic bytes. The owner steps that remain are in the [runbook](../docs/runbooks/ps1-titles.md);
the decisions for the launch work are on Linear AVR-310.

## Where it came from

The profiles are the donor branch's, recovered, not merged. Donor: branch
`experiment/ps1-title-profiles`, commit `4b8fa60afecb4868be0816f4b908b752bc33296d`, 329 commits behind
`main` (and 25 ahead of it) when this was done; a retained research branch is evidence, never a merge
queue ([inventory](../docs/branches.json)). Each data file was copied byte for byte with
`git show 4b8fa60:<path>`, and `sha256sum` gives the same value on both sides:

| File here | Donor path | sha256 |
|---|---|---|
| `titles/bomberman.json` | `ps1/titles/bomberman.json` | `6eb9a5493ab5f5f90698db42a7aec4ee9bc3b188af1b82d5f1336add038e6281` |
| `titles/worms.json` | `ps1/titles/worms.json` | `5fea1597b29fe9010d2769b8b12d90709c9b9873b8fbf73d17dde571ea3c98e5` |
| `evidence/selected-core.json` | `ps1/evidence/selected-core.json` | `57921bedcf7ee9f9c117b8b384f867eeecc7dd163cf3b109421608c006ddc175` |
| `retroarch.cfg` | `ps1/retroarch.cfg` | `8ccbd8c9a92ec946c0a155c9ad79a9700b72c853f92e76014818acf4c8a4bb33` |
| `mode-xvfb.cfg` | `ps1/mode-xvfb.cfg` | `ec60bcd8a7b676631639dbccec9dafca242c689ccce63c5820485d7534dd8200` |

The code is a port, not a copy: the loader and the generators are the donor's `ps1/profiles.py`; the
X11, `XTestPad`, `BANKS` and `MIN_HOLD` pieces are the donor's `ps1/stream_ps1.py`. The golden files in
`tests/fixtures/ps1/golden/` are the donor's `ps1/tests/golden/` files, also byte for byte (a test
checks their hashes), kept LF in every checkout by `.gitattributes`.

The evidence behind the data is the donor's own, and it is history, not instruction:
[the Bomberman party slice](../docs/findings/2026-09-24-ps1-bomberman-party-slice.md) and
[the latency finding](../docs/findings/2026-09-24-ps1-latency.md) (both 2026-09-24), and the 2026-09-23
shared-stream finding, `docs/findings/2026-09-23-ps1-shared-stream.md`, which exists only on the
retained branch `ps1-emulation` and is not on `main`. The multitap allowlist rests on that last one:
`"port 2"` gives five human players, `"port 1"` makes the game ignore all input, `"disabled"` leaves
only players 1 and 2, and Worms is hot-seat on port 1.

## What is here

| Path | What it is |
|---|---|
| `titles/<id>.json` | the title profile: data from an allowlist, never raw RetroArch configuration |
| `evidence/selected-core.json` | the pinned core build; the content check compares the core's SHA-256 with its `so_sha256` |
| `retroarch.cfg` | the donor's base RetroArch configuration (see "Debt") |
| `mode-xvfb.cfg` | headless mode: a private Xvfb, X keyboard input, a key bank per player, joypads pinned to an index that never exists, hotkeys gated behind `scroll_lock` |
| `../avrana/providers/ps1.py` | loader, generators, content check, `XTestKeysProvider` and the command line |
| `../tests/unit/test_ps1_profiles.py`, `../tests/unit/test_ps1_provider.py`, `../tests/fixtures/ps1/golden/` | the tests and the goldens |

## One source of truth

The Game Contract owns a title's serial, stream slots and multitap setting: the `net.avrana.ps1`
extension of `contracts/games/ps1-<id>.json`, which the catalog build already validates. The profile
keeps what the contract has no field for (`cue`, `retroarch_users`) and, because the donor format and
the generators need them, repeats those three. `load_checked(id)` loads the profile strictly, loads the
contract, and refuses any difference with a `ContractMismatchError` that names every field that
differs; service code loads profiles that way. The contract writes the multitap as `multitap_port: 2`
or `multitap: "disabled"` and the profile in RetroArch's words, `"port 2"` and `"disabled"`; the check
maps one to the other. `load()` alone reads the profile without the contract.

## Use (a library and one command, not a launcher)

```python
from avrana.providers import ps1
from avrana.providers.controller import ControllerLayout

profile = ps1.load_checked('bomberman')    # strict, and equal to its Game Contract
ps1.core_options(profile)                  # the core-options file, as text (LF, UTF-8)
ps1.retroarch_config(profile)              # the per-title RetroArch override, as text
ps1.check_content(profile).to_dict()       # the owner's content: see below

# After the private Xvfb is up (its display name, and the cookie file the launcher wrote).
# Each seat presses only the keys of its own bank.
contract = ps1.load_contract('bomberman')
provider = ps1.XTestKeysProvider(':99', xauthority=cookie_file)
pad = provider.open(0, ControllerLayout.from_contract(contract['input']))
pad.set_state(['left', 'cross'])           # a full snapshot of what is held
pad.neutralize()                           # every key of the seat up, now
provider.close()                           # every seat released, then the connection closed
```

```
python3 -m avrana.providers.ps1 check bomberman [--content DIR] [--core FILE]
```

The command prints one line per check and exits 0 only when everything passes. It changes nothing.

What the loader refuses, each with a named error (`ProfileError` and these subclasses): a duplicate
JSON key (`DuplicateKeyError`); a key outside the allowlist, which is how a raw RetroArch setting such
as `network_cmd_enable` or `savefile_directory` is kept out (`UnknownKeysError`); a content path that
is absolute, uses `..`, has a drive letter or a control character (`ContentPathError`), or leaves the
content root once links are resolved; `stream_slots` above `retroarch_users`
(`SlotsExceedUsersError`); a multitap setting other than `"disabled"` or `"port 2"`, the two values
verified on hardware (`MultitapError`); any difference from the Game Contract
(`ContractMismatchError`). It also refuses a wrong type, a missing key, an unsupported `version`, an
`id` that does not match the file name, text fields that are not one printable line (the name and
serial reach a comment line of the generated file, so a line break there would smuggle in a setting),
and a profile larger than 16 KiB.

## The owner's content (never in git)

ROMs, BIOS images, cores, saves and states are the owner's and never enter this repository; a test
checks that this directory and the fixtures hold only small text files. The content check is told
where the owner's files are and defaults to nowhere.
Two names, **provisional until AVR-310 decides the locations and their names**:

| Name | Holds |
|---|---|
| `AVRANA_PS1_CONTENT` | the content root: the BIOS image, and the disc folders laid out as each profile's `cue` path says |
| `AVRANA_PS1_CORE` | the pinned core, `pcsx_rearmed_libretro.so` |

`install_to` in `evidence/selected-core.json` (`$AVRANA_PS1_HOME/cores/`, with a default under a home
directory) is where the donor kept its core: evidence of that run, not a default here. Nothing reads it,
and the core path is only ever `AVRANA_PS1_CORE` or `--core`.

An argument beats the environment; neither falls back to a default path. The check reports that: the
cue sheet is there; every file a `FILE` line of the cue names is there (a name that is absolute or
climbs out of the disc folder is refused, not probed); the BIOS (`SCPH1001.BIN`, the name the donor's
runs used, matched exactly because the Pi's filesystem is case-sensitive: `scph1001.bin` is refused and
the report names it) is exactly 524288 bytes; and the core's SHA-256 equals `so_sha256` in
`evidence/selected-core.json`. It opens the cue sheet and the core; the disc images and the BIOS are
only looked at (that they exist, and how big the BIOS is). Each of the fifteen failures has its own
code and sentence (the [runbook](../docs/runbooks/ps1-titles.md) lists them), and a report names files
relative to the content root, never an absolute path of the owner's machine. A check never raises for
a problem with the content, only for a profile that is invalid.

## What is proven, and what is not

**Proven here (Tier 1, `python3 -m unittest discover -s tests/unit -p "test_ps1_*.py"`):** the
loader's refusals and the contract cross-check; the generated core options are byte-identical to the
donor's golden files for both titles (`pcsx_rearmed_multitap = "port 2"` and `input_max_users = "5"`
for Bomberman, `"disabled"` and `"1"` for Worms), and so are the settings of the generated RetroArch
override; the content check on temporary directories; the XTest provider's hold, release and
neutralize behaviour against a fake X11 and a fake clock; and that its four key banks equal the
donor's and are bound to the same player and button in `mode-xvfb.cfg`.

**Evidence from the donor, not re-run here** (the dated findings above). On the Pi, 2026-09-23: Worms
booted on the real BIOS and played a two-team match, hot-seat on port 1 (the second key bank did
nothing); Bomberman's multitap on port 2 gave five human players, each moving alone with its own key
bank. Both were driven by the key banks directly, with no stream and no phone. 2026-09-24: Bomberman
streamed to four simulated phones (Playwright Chromium over eth0) and took input from four independent
slots in a real match. With the arcade running the emulator was CPU-bound: about 21 frames per second
(35 percent speed) at 640x480 and 40 to 44 at 320x240, both with five viewers.

**Not proven**, and not to be read into this directory:

- **Real iPhones.** One real-iPhone playtest on the party Wi-Fi (2026-09-24 night) had a median input
  round trip of 6 ms but stalls of up to 2.2 seconds, in about 16 percent of seconds. The finding names
  the AP radio's power save as the prime suspect and an A/B test as the next step; this repository has
  no record that it ran. No multi-phone real-iPhone play, and nothing recorded on Safari decode, touch,
  or sleep and wake.
- **Audio.** The runs showed that sound is produced (a level on a private sink). Nobody has recorded
  listening to it on a phone, and on the real-phone run the phone's audio jitter buffer reached 1.27
  seconds at the 95th percentile (276 ms median).
- **The arcade stopped.** Stopping it is the finding's expected fix for the CPU limit, stated there as
  not verified; no run with it stopped is recorded.
- **Worms in the Party flow.** Worms has only been driven by key banks, with no stream, no phone and no
  Party Home.
- **Five players.** The multitap gives five human players with key banks, but a seat needs a key bank
  and there are four: the fifth pad has no phone slot.
- **A TV.** `mode-kms.cfg` (HDMI) was untested in the donor and is not carried over.
- **Streamed sessions longer than ten minutes** (the supervised runs were 5 to 10).
- **The XTest code against a real X server.** `XTestKeysProvider` and the ctypes wrapper `X11` are
  tested against a fake X11 and fake libraries; the donor ran the same calls on the Pi, this repository
  has not.
- **Anything about launching:** there is no launcher, so there is nothing to have proven.

## Differences from the donor, and debt

- **The generated RetroArch override's comment header.** The donor's golden `.cfg` files keep the
  hand-written comment lines of the pre-profile files, which the donor's generator never produced (its
  own test compared the settings only); the generator writes `# <name> <serial> — generated from
  ps1/titles/<id>.json; do not edit` instead. This port keeps the generator's header and compares the
  settings byte for byte; the header is pinned in a test. Reproducing the hand-written text would mean
  storing it in the profile.
- **A stricter loader** than the donor's (refusals the donor did not have: line breaks in text fields, a
  boolean or float `version`, non-finite numbers, a malformed serial, oversize files). The two committed
  profiles pass unchanged.
- **`retroarch.cfg` is the donor's template**, with `@PS1_HOME@` placeholders and its own directories,
  not the `avrana.providers.retroarch.write_config` convention (a committed configuration with no paths,
  the writable directories appended under the service's runtime directory). Nothing here substitutes the
  placeholder; reconciling the two belongs to the service work (AVR-310). `avrana/providers/retroarch.py`
  was not touched.
- **Not carried over:** the launcher scripts, the stream server and phone page, `mode-kms.cfg`, the
  donor's tools and its command line (`list`, `cue`, `write`, `slots`); `check` replaces it.
- **Worms' Game Contract declares no buttons** (hot-seat, one slot), so a layout built from it opens the
  d-pad only. The button set and the hot-seat semantics are owner decisions on AVR-310.
- **`xtest-keys` has no adapter in the appliance profile** (`"adapter": null`). Naming
  `avrana.providers.ps1:XTestKeysProvider` there is a contract change, left for the follow-up.
- **An XTest seat needs its display**, so it is opened after the private Xvfb is up, the other way round
  from the order `base.py` describes for uinput. The provider is not thread-safe: use it from the one
  thread that owns the seats.
- **The donor's comments cite donor files.** `retroarch.cfg` (its first lines) and `mode-xvfb.cfg` (its
  comment on the key banks), and a note in `titles/bomberman.json`, name `run-ps1.sh`, `stream_ps1.py` and
  `tools/xkeys.py`, which were `ps1/run-ps1.sh`, `ps1/stream_ps1.py` and `ps1/tools/xkeys.py` on the
  donor branch and are not in this repository. The text is the donor's, kept byte for byte; it describes
  the donor's launcher, not anything here.
- **A release timer is not re-armed earlier.** A key's release can come up to 40 ms after its minimum
  hold has ended, never before it: a release that has to wait rides the one timer its seat already has
  pending, and that timer is not moved to an earlier time (only on the event-loop path; with no loop the
  controller sleeps exactly as long as the hold needs).
- Opposing directions are not cancelled (both keys go down), as in the donor, and an X server that dies
  takes its client process with it (Xlib's default I/O error handler): the supervisor has to restart
  the service.

## Related

[Runbook: what remains for the owner](../docs/runbooks/ps1-titles.md) ·
the Game Contracts [`ps1-bomberman`](../contracts/games/ps1-bomberman.json) and
[`ps1-worms`](../contracts/games/ps1-worms.json) ·
[open game installation](../docs/design/GAME-INSTALLATION.md) (a profile is data, never executable) ·
the experiment-only [Bomberman phone test](../docs/runbooks/ps1-bomberman-party-test.md) ·
Linear AVR-309 (this recovery), AVR-310 (the launch decisions), AVR-142 (safe emulated title profiles),
AVR-137 (input bindings).
