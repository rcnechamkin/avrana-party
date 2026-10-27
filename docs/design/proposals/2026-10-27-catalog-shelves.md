# Catalog shelves: Featured, Classics, Lab, Hidden (AVR-155)

- **Status:** proposal with a mechanism, 2026-10-27. The mechanism (`contracts/shelves.json` → catalog `shelves` → `visibleGames`) is in this draft PR, with `contracts/shelves.json` **empty**: nothing changes on Home or in the Library until the owner places titles. **The dispositions in section 3 are recommendations: owner decisions required** (section 5). Nothing is deployed.
- **Reads with:** [ADR 0014](../../adr/0014-native-games-isolated-lan-games-retired.md) (the LAN Games donor library is retired from the catalog); `avrana/contracts/catalog.py`; `avrana/ops/catalog_overlay.py` (installed `.avrgame` rows); `web/party/lib/catalog-view.js` and `web/party/lib/library.js` (`homeShelves`, `arrange`).

## 1. What happens today (origin/main)

- The release catalog lists **6** titles: BLUFF, Checkers, EXPO and Gauntlet II (installed), and Bomberman Party Edition and Worms Armageddon (PS1, `experimental`, not installed, shown as "Experimental · Not installed on this Party box").
- Rows are sorted installed first, then by name. Installed `.avrgame` packages (Best Guess, Tanks, Courting, Coup once installed) are appended **after every first-party row** by the overlay, by design (a package never moves a first-party row).
- Home's lead is the last title played on this phone, otherwise **the first installed title that suits the Party**. On a fresh phone that is always BLUFF (alphabetical first). The four Private Demo candidates can never lead, and they sit at the end of the Library.
- The 31 LAN Games donor titles are in `contracts/catalogs/lan-games.json` only as display text for BLUFF and EXPO; none is offered (ADR 0014).

Installed was, in effect, Featured, and in the wrong order.

## 2. The mechanism (in this PR)

- `contracts/shelves.json` (`avrana.shelves/v0`): `{game id: featured | classics | lab | hidden}`, owner-edited, committed empty, validated by `catalog.load_shelves` (id shape, shelf word, schema). An id may name a package-only game: it is a **placement, not a grant**.
- `python3 -m avrana.contracts.catalog` copies it to the catalog's top-level `shelves`. No row is added, removed, moved or edited (tested: the catalog built with shelves, minus `shelves`, equals the plain build). The overlay rewrites the release document with its keys intact, so package rows are placed by the **owner's** file. A package cannot place itself.
- `visibleGames` (the one list Home, the Library, the Limited notice and troubles use) puts **featured** first, then titles with no placement, then **classics**, then **lab**, keeping catalog order within each shelf. It leaves **hidden** out. Home's lead and rail follow, because `homeShelves` takes the first installed title that suits the Party from that list.
- A hidden title keeps its contract, grant, install and code. It is only not listed. An unknown shelf word is no placement. A featured title that is not installed is still not listed.
- No visual change: Classics and Lab are quieter by position only. A heading or tag per shelf is a follow-up once the owner settles the tiers (section 5, D4).

## 3. Game-by-game audit and recommended disposition

Product bar (from the issue): would the tile make Avrana look intentional, does Avrana improve the game, is it a complete game, is it acceptable in screenshots, would it be missed, and is the licensing and maintenance burden proportionate? **Entering a shelf accepts nothing.** Each Featured title still needs its own implementation, visual, Party-flow, real-phone, offline and legal evidence (AVR-764).

| Title (id) | Where it comes from | Recommended | Why |
|---|---|---|---|
| Best Guess (`bestguess`) | Games package | **Featured** | Cooperative 3–7 word game, made for phones; art cleared, sound off (Games #85/#86). |
| Courting (`courting`) | Games package (draft games#101) | **Featured** | Private Demo candidate; Linux spec, review and phones not yet run. |
| Tanks (`colyseus-tanks`) | Games package | **Featured** | The Colyseus Three.js port (AVR-511), **not** the LAN Games artillery `lan-tanks`; real-phone session still open. |
| Coup (`coup`) | avrana-coup package | **Featured** | Owner's test-hardware permission only. The rights letter is gated separately, so Featured here is not permission to distribute. |
| EXPO (`expo`) | first party | **Lab** (or Featured as the optional fifth) | The issue makes it optional; a substantial demonstration, but not required to carry the shelf. |
| BLUFF (`bluff`) | first party | **Lab** | Prototype (working title); valid platform and regression consumer, not a showcase tile. |
| Checkers (`checkers`) | first party (native) | **Classics** | Familiar, complete, phone-only; library depth without carrying the identity. |
| Gauntlet II (`arcade-gauntlet2`) | arcade | **Lab** | TV-heavy emulation; ROM provenance is the owner's to confirm before it shows anywhere public. |
| Bomberman Party Edition (`ps1-bomberman`) | PS1, not installed | **Hidden** | Commercial disc image; an "Experimental" tile still advertises a game Avrana cannot ship. |
| Worms Armageddon (`ps1-worms`) | PS1, not installed | **Hidden** | Same as Bomberman. |
| 31 LAN Games donor titles (`lan-*`) | retired donor snapshot | **Hidden, already** (ADR 0014) | Not in the catalog. If any returns, the issue's candidates are Wordclash (Featured-worthy), Chess, Spades, Hearts and Euchre (Classics); Bingo and Charades stay hidden. |

## 4. Evidence

- `PYTHONPATH=. python tests/unit/test_catalog_shelves.py`: 5 OK (schema, words, ids, package ids allowed, build changes nothing else, committed catalog in step with `--check`).
- `test_assimilation`, `test_catalog_overlay` (direct run): OK; the overlay's 10 POSIX-only skips are unchanged.
- `node --test tests/offline/*.test.mjs`: 342 pass. The new module test covers order, hidden, a placement granting nothing, unknown words and inherited keys, and no shelves meaning the catalog order.
- `tests/offline/shelves.spec.ts` (Chromium, both phone projects): 6 pass. It serves the real catalog with the recommended-style shelves added: the Library lists featured first and leaves hidden out (search too), Home leads with the featured title on a fresh phone, and no shelves means the catalog order. Against main's `catalog-view.js` 2 of its 3 tests fail.
- Offline `library`, `home`, `assimilation`, `covers`, `a11y`, `coherence`, `shell` and `limited` specs: 130 pass. The committed catalog is byte-for-byte main's.
- **Not run:** the rest of the offline and party suites, an installed-package overlay on the Pi or the hosted VM, and real phones.

## 5. Owner decisions

| # | Decision | Recommendation |
|---|---|---|
| D1 | Confirm or change each disposition in section 3 (fill `contracts/shelves.json`, run `python3 -m avrana.contracts.catalog`; the Library/Home specs that list the six titles in catalog order then need the new order) | As recommended |
| D2 | EXPO: Lab, or Featured as the optional fifth? | Lab until its Private Demo evidence is in |
| D3 | Hide the PS1 titles now, or keep the honest "Not installed" tiles? | Hide |
| D4 | Should Classics and Lab get their own heading or tag on the Library, or is order enough for Private Demo v0? | Order only for v0; headings with the Friend Ready catalog |
| D5 | Should a hidden title be launchable from a direct link by the owner (for regression play)? | Yes. Today nothing stops it, and this PR changes no launch path |
