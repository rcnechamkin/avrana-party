# BLUFF listed and launchable from Party Home (2026-09-28)

Status: **LIVE** on production since 2026-09-28, and **phone-verified**: the owner saw BLUFF in Party
Home on an iPhone on the Party Wi-Fi and launched it from its tile. Issue AVR-91; avrana-party PR #20,
merged as `15f6322`.

## Symptom

On 2026-09-28 the owner tested production on an iPhone after deploying Games `c6199be` and Party
`3724b34`. BLUFF worked when opened by its direct URL, but it was **missing from Party Home**.
Diagnostics listed BLUFF's player seat as `ready`, but under "BLUFF (not installed)".

## Cause

The appliance profile (`contracts/appliances/avrana-pi4.json`) never granted `bluff`. Leaving it out
was deliberate while BLUFF was still only in the fork (`docs/findings/2026-09-26-lan-providerization.md`),
and tests asserted that it stayed hidden. That became stale when the fork went live on 2026-09-27:
- the catalog builder marked BLUFF `installed: false`;
- Party Home's `visibleGames()` hides games that are not installed;
- diagnostics still ran the capability check, which found everything BLUFF needs.

"ready" meant *this phone can play it*, not *this appliance offers it*.

## Fix

- **Grant:** one entry for `bluff`, under its own ID (not `lan-bluff`, per `docs/design/LAN-GAMES-PROVIDER.md`):
  - `entry` is `/games/bluff/`, the same as the donor launch target;
  - `tier` is `builtin`;
  - `permissions_granted` is `["party_roster"]`, the one permission BLUFF's contract declares.
- **Catalog:** regenerated. The only semantic change is BLUFF's `installed` (false → true) and
  `entry` (null → `/games/bluff/`).
- **Tile:** keeps its existing art (`art/lan-bluff.svg`) and launches `/games/bluff/?avrana=1`
  through `avrana.lan-launch/v1`.
- **Tests:** they now assert BLUFF is listed, launchable, and shown as installed in diagnostics.
  The library count is 33 (29 donor titles + BLUFF + arcade + 2 PS1).
- **Games fork:** no change. `ops/export_avrana_catalog.py --check` at `c6199be` reported this
  repository's `contracts/catalogs/lan-games.json` consistent.

## Evidence

- **TESTED (laptop, Windows):**
  - The updated tests failed before the grant and passed after it.
  - `node --test tests/offline/*.test.mjs`: 59/59 pass.
  - The contract and assimilation unit tests pass.
  - `tests/offline/assimilation.spec.ts`: 14/14 pass.
  - The owner ran the Party Home and diagnostics specs.
  - CI `offline` passed on the PR head, `5f0c05c`.
- **Deploy:**
  - The production checkout `/home/cody/avrana-party` was fast-forwarded to `15f6322` by the owner.
  - The owner ran `ops/install-party-web.sh`, creating release `20260929T030813Z-15f6322efc7d`.
  - The served `version.json` names commit `15f6322`, and the served `catalog.json` has BLUFF
    `installed: true` with entry `/games/bluff/`, read on the Pi.
  - No nginx, service or arcade change.
- **Real phone:** on an iPhone on the Party Wi-Fi, BLUFF appears in Party Home and launches from its tile.

## Limits

- **No Party session admission:** production still launches BLUFF without Party session admission.
  No Party service runs until AVR-51 deploys Party Core v0. The tile proves discovery and the
  integrated launch path, not Party sessions (tested separately in
  `docs/findings/2026-09-28-bluff-party-reconnect.md`).
- **Diagnostics wording:** the "ready (not installed)" label still applies to titles that really
  are not installed (the PS1 entries). Separating "phone can" from "appliance offers" in that
  wording belongs to the discovery-metadata work (AVR-70).
