# Finding: product differentiation, weaknesses and what to prove first (2026-09-24)

A deliberately blunt review from a future buyer's perspective (and first the owner's, since V1.0
is for the owner): *why use this instead of a Switch, Jackbox, AirConsole, Steam Remote Play, a
retro handheld, Kahoot or a deck of cards?* Competitor and travel-policy facts come from web
sources noted at the end and were **not** individually verified with each airline or cruise line.

## Bottom line

Only one thing is both **working** and **different** today: phones join a local Wi-Fi network with
**no TV and no app** — and, by design, no internet (not yet tested with the upstream actually cut;
see `2026-09-24-party-network-and-offline-mode.md`). Everything that would make someone choose Avrana over a Switch
or Jackbox — a fun no-TV native game, Personal Viewports, one party carried across games — is
unbuilt or unmeasured. And the hardware is the weakest link: the Pi can't yet stay reliably
powered even from a wall supply (see `CLAUDE-HANDOFF.md`, power).

## Competitors

| Competitor | Does better | Where Avrana could win | What that win needs |
|---|---|---|---|
| Switch / Switch 2 | polish, first-party games, real buttons, battery, tabletop mode | no controllers to buy or share; players sitting apart | native touch games that feel good; a measured latency budget |
| Jackbox | writing quality, laughing together at one screen, big library | offline and no TV (Jackbox needs internet and a shared screen) | a player-generated-content game that stays funny without a shared screen |
| AirConsole | large catalogue, polished pairing | offline, no big screen (AirConsole needs both) | don't compete on count; win where it can't run |
| Steam Remote Play Together | a real PC library | no PC, no internet | nothing worth chasing |
| Retro handhelds | cheap, battery, screen, stronger SoC than a Pi 4 | multiplayer where each player has their own screen | Personal Viewports on a split-screen title |
| Kahoot | quiz authoring, hundreds of players | offline, hidden information | probably nothing (AP capacity, below) |
| A deck of cards | $3, no boot, no battery, no radio | players physically apart; server-enforced hidden hands | power-on to first game < 3 min, reliable on battery |

## Real differentiators

- **Offline + no TV + no app, simultaneously.** True by design (offline untested on real phones); no listed competitor does all three.
- **A private, server-masked screen per player.** BLUFF already proves the masking discipline.
- **Players who are physically apart** (plane rows, across a room) — the one setting where cards
  and Switch tabletop mode both fail.
- **Personal Viewports** — genuinely new, but **untested**: neither current PS1 title is
  split-screen (Bomberman is one arena, Worms is hot-seat), and nobody has checked that a 160×120
  native-pixel quadrant is readable on a phone.
- **One party across games** — valuable only if switching games is actually painful; unmeasured.

## Weak or fake differentiators

- **Profiles, achievements, rivalries, cosmetics, cross-game teams.** Nobody buys a party box for a
  badge; emulated games can't report results, so cross-game scoring covers native games only.
- **"28 games."** A count, not quality; retired upstream code; assume a handful are worth replaying
  until the owner ranks them.
- **Open game installation.** No ecosystem exists; a device guests join that runs arbitrary GitHub
  code is a liability until the trust model exists. A principle, not a selling point.
- **Distributed phone display.** A gimmick (already parked as experimental).
- **Emulation as the headline.** Buyers must supply their own content; legal exposure and friction
  make it a poor crowdfunding headline. Keep it as a power-user feature.
- **"60 fps."** Encoded frame rate is not latency. Action games over Wi-Fi in a crowded bar or
  plane is the weakest claim the project could make until it is measured.
- **Worms** is hot-seat on one pad; phones add nothing to it.

## Where Avrana loses today

- **Power.** Recurring under-voltage on a wall supply *(2026-09-24 evening: resolved for the tested
  workloads by removing the USB Wi-Fi adapter — `2026-09-24-no-usb-power-baseline.md`)*. Battery operation (needed for most target
  settings) is untested and likely harder.
- **Capacity.** The Pi 4's *onboard* Broadcom Wi-Fi reportedly caps AP mode at ~7 clients
  (home-assistant/operating-system#3502). *(Since 2026-09-24 the party AP **is** the onboard radio — the USB adapter was
  removed — so this limit now applies; reported ~8 on the standard firmware, `docs/runbooks/network.md`.)*
  **Measure the real client ceiling** before promising a 10-person bar party.
- **Latency.** Not formally measured (the ~26 ms jitter buffer was 2 phones at home).
- **Content.** One person cannot out-write Jackbox. The real moat is a content pipeline.
- **Hardware cost vs a laptop hotspot.** The Pi earns its place only as an *appliance*: battery,
  QR display, fast boot, reliability after power loss.
- **Travel policy** (unverified per operator):
  - *Planes:* "no hotspot" rules mostly target cellular hotspots, and Switch local wireless is
    commonly used, so a Wi-Fi-only AP is probably tolerated. **Power is the harder blocker:** seat
    USB rarely supplies 5.1 V / 3 A, and several airlines (e.g. Lufthansa Group, Emirates,
    Singapore, Cathay, Korean, Qantas) now ban using power banks in flight. A bare board wired to a
    battery will also draw attention — an enclosure matters.
  - *Cruise ships:* Carnival (Sept 2024) and Royal Caribbean ban travel routers; an Avrana is
    functionally one and could be confiscated at embarkation.
  - *Hotels/airports:* probably fine.
  - *Radio regulation:* the AP uses channel 149, which isn't legal everywhere; the regulatory
    domain must follow the country.
- **Guests lose the internet** while on the party network (see `docs/design/ONBOARDING.md`).
- **Noise.** Sound cues fail in loud bars; six unsynchronized phones playing audio is worse.

## What to prove first (for the owner's V1.0)

1. **BLUFF on real phones, one evening** (already ROADMAP N2): 3–6 people including an Android
   phone, plus one manual switch to a LAN Games title and back. Measure power-on → first deal
   (target < 3 min), % of phones joining unaided (QR vs typed address), seats lost to sleep/reload,
   seconds and confusion per manual game switch, "one more game?" requests, fun 1–5. Play one round
   with players in different rooms to stand in for plane rows. **The game-switch number decides
   whether "party follows host" is worth building first** (build it if a switch costs > 60 s or
   loses a player).
2. **Personal Viewports, 2 then 4 players, after the power fix:** latency with a 240 fps phone
   camera (crop vs full), readability 1–5, crop vs full-frame preference, stream stability with 4
   phones. Kill it if cropped play rates worse than everyone watching the full frame.
3. **A content-light native no-TV game** (drawing-telephone or hidden-role voting, where players
   generate the content): laughs at the reveal without a shared screen, sessions per party, whether
   people look at each other or only at their phones. (Gartic Phone/skribbl.io do this free but need
   internet — this tests whether *offline + private* is enough.)

## Roadmap implications

- **Deprioritize** until a party night has been measured: profiles/PINs beyond the admin PIN,
  achievements, cosmetics, rivalries, cross-game teams, whispers/team chat, moderation presets,
  packaging/trust for open installation, distributed display, emulated result adapters, Worms.
  F1–F8 stay gated on the N2 playtest.
- **Missing, and a buyer would care:** power first (stable on the wall, then a battery that holds
  5.1 V / 3 A, with measured runtime); boot-to-joinable time (target < 45 s); surviving power loss
  (SD protection; does the party survive a reboot?); network capacity (client ceiling, airtime per
  streaming phone); onboarding (QR card, `party.local` on Android); noisy-venue UX (visual and
  haptic cues, big targets, glanceable state); phone battery drain per hour of 60 fps streaming; a
  content pipeline after BLUFF; a travel compliance sheet; an enclosure and cooling that survive a
  bag.

## Sources

Jackbox needs internet (Steam forum) · AirConsole needs internet (Hypertext, 2016) · Pi 4 AP client
limit: github.com/home-assistant/operating-system/issues/3502 · airline power-bank rules
(AirlineRatings) · cruise router bans (Royal Caribbean Blog, CruiseRadio) · hotspots on planes
(Traveling Light). All as of 2026-09; verify before relying on any single claim.
