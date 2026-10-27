# Owner game management: install, sources, update and rollback (AVR-60)

- **Status:** proposal, 2026-10-26. Nothing is implemented. **Owner decisions required** (section 8).
- **There is no owner page yet.** No owner route or Admin PIN session exists in code today. Every flow below is the design for that future surface (AVR-44), or a future owner app acting as its remote control. Until then, `install_game` over SSH is the only path.
- **Reads with:**
  - `avrana/ops/install_game.py` and [AVRGAME-PACKAGE.md](../AVRGAME-PACKAGE.md) (install, remove, list, verify; all or nothing; no upgrade yet);
  - signing, update and rollback mechanics: AVR-58, draft #230;
  - permissions and trust presentation: AVR-62, draft #239;
  - dependencies: AVR-77, draft #235;
  - backup and restore: AVR-81, draft #227;
  - health and storage facts: AVR-74, draft #243.

This document is the **experience** layer. It decides no new mechanism. Where a mechanism is needed, it points to the proposal that defines it.

## 1. What exists today

| Need | Today | Source |
|---|---|---|
| Install a local `.avrgame` | `install_game install <file>`, root, over SSH. Validated, staged, provisioned, all or nothing, unwound on failure. | `install_game.py` |
| Remove | `install_game remove <id> [--keep-state]`, refused while that game is in the live session | same |
| See what is installed | `install_game list [--json]`, `verify <id>` | same |
| Update, pin, rollback | not implemented: an installed id is refused ("remove it first") | same, module doc |
| Sources, publishers, provenance | the install record keeps `sha256`, version and claims; no signatures yet | AVR-58 |
| What a guest sees | installed games appear in the Library through the catalog overlay | `catalog_overlay.py` |

## 2. Principles

1. **One authority.** Every channel goes through the same appliance-side installer: a USB stick, a phone upload, a community source, a future paid catalog, or an owner app. A phone or app never holds a parallel package store or runtime (owner decision 2026-10-06).
2. **A console library, not a package manager.** The owner sees games, not packages. Words like versions, keys and sources appear one tap deeper, never on the first screen.
3. **Nothing half-done is ever visible.** A game appears in the Library only after its install, update or rollback has fully committed. The installer's ledger already guarantees this for install, and update and rollback reuse it (section 5).
4. **Guests never see management.** No guest screen shows sources, updates or errors. A game being updated is simply not offered until it is ready, with "Updating" on its Library card for the owner only.
5. **Offline sideload is first-class.** Installing from a file is the primary path, not a fallback. Sources are optional.

## 3. One game, one card: states

Each installed or available game has one card on the owner's Games screen, in exactly one state:

| State | Meaning | Primary action |
|---|---|---|
| **Available** | known from a source or a file the owner opened; not installed | Install |
| **Installing / Updating / Rolling back** | the installer holds the lock | none; shows the progress step |
| **Ready** | installed, verified, offline-ready (every file and dependency is on the box) | Play (opens Party Home) |
| **Update available** | Ready, and a newer accepted version is known | Update |
| **Held** | the owner pinned this version; updates are not offered | Release hold |
| **Needs attention** | `verify` failed, a dependency is missing, the publisher key was revoked (AVR-58 §8), or a runtime is missing | the specific fix, with a plain reason |
| **Not playable here** | it needs something this box lacks (a runtime, a capability) | an explanation only |

Card details, one tap deeper:
- installed size and saved-data size, shown separately;
- version, and the date it was installed or updated;
- source and publisher, with the AVR-58 trust line ("Signed by …", "Unsigned: you chose to install it");
- permissions as the AVR-62 groups;
- player count and fit;
- "browser" today; "app-ready" later, when AVR-45 and AVR-135 define it;
- last played: a count and date from local results (AVR-71), never per guest.

## 4. Install

1. **Choose a game.** Three equal ways: a file (from a USB stick, or uploaded from the owner's phone to the appliance), a source listing, or a link from the owner app. Each one hands the appliance an archive. The appliance validates it, and nothing runs yet.
2. **Review.** One screen in this order:
   - name, art and player count;
   - who made it and how we know (AVR-58);
   - what it can do (AVR-62 groups, with plain risks);
   - size, and whether there is room (AVR-74 storage);
   - dependencies, if any (AVR-77, which bundles them, so normally nothing).

   An unsigned package needs a deliberate confirmation each time (AVR-58 D1).
3. **Install.** The ledger runs. On any failure the screen says what failed in one sentence and confirms that "nothing was changed"; the unwind already guarantees that. A crash mid-install (power loss) leaves the card in **Needs attention** with one action, "Clean up", which is `remove <id>`.
4. **Ready.** The card says Ready, and the game appears in guests' Library.

## 5. Update, hold and rollback

The mechanics are AVR-58 §5 (keep one previous version and its state snapshot; refuse a downgrade to bytes never installed here). The experience:

- **Update one or all.**
  - "Update all" queues the games one at a time. Each is its own all-or-nothing transaction, so one failure never blocks or breaks the others.
  - Updates never start while that game is being played. Queued games wait, and the card says "Waiting for the current round".
- **Before an update**, the screen shows only what changed and matters:
  - new permissions, which require the owner's confirmation (AVR-62);
  - a new publisher key, which requires confirmation (AVR-58 §8);
  - a size change.

  Release notes are optional text from the package, shown as the publisher's words.
- **Hold** pins the current version. Holding is per game and survives restarts and backups (AVR-81).
- **Rollback** is a single action on the card for 30 days after an update (D3), while the previous version is still kept. It restores the previous version **and** its saved data from before the update, and says so: "Progress made since the update will be lost."
- **Failed update:** the old version stays in place and playable. The card shows **Update failed** with the reason and a Retry button. A failed update never removes a working game.

## 6. Remove and storage

- **Remove asks one question:** "Keep saved games?" (`--keep-state`), defaulting to keep. Deleting saved data is a second, explicit choice, never bundled with removal.
- **Low storage** (AVR-74 `storage.*` at WARN or FAIL) opens a "Free up space" list, largest first:
  - kept previous versions, which are always safe to delete; doing so ends rollback for that game;
  - downloaded update files not yet installed;
  - removed games' kept saved data;
  - finally, games the owner chooses to remove.
- An install or update that would leave less than the preflight's minimum free space is refused before it starts, never halfway through.

## 7. Sources (advanced)

- A **source** is a signed listing (AVR-58 §7): a community repository, a paid catalog, or a courier on a USB stick.
- **Adding one** shows who signs it and asks the owner to confirm its key once.
- **Removing one** never removes installed games. Their cards then show "source removed; updates by file only".
- A future **paid catalog** is just another source, from the appliance's point of view. Purchase and entitlement live in that catalog's own flow and are out of scope here. The appliance installs only what validates, whatever the channel (AVR-143).
- Sources live on the Settings screen, not the Games screen, so an owner who only sideloads never meets them.

## 8. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Default for "Keep saved games?" on remove (the CLI default today is delete: `--keep-state` is opt-in) | keep; delete | **keep** in the owner page; the CLI default can stay as it is |
| D2 | "Update all" | offered; one at a time only | **offered**, executed one game at a time |
| D3 | How long rollback is offered | until the next update; 30 days; forever | **30 days or until the next update**, whichever comes first; the kept version can be freed sooner from "Free up space" |
| D4 | Automatic updates | never; opt-in per source | **never** in the prototype; an owner always presses Update |
| D5 | Show "Updating" to guests? | never; a neutral "not available right now" | **never**: the game is simply not in the Library until it is ready |
| D6 | Phone upload of a `.avrgame` to the appliance | yes, from the owner page; USB and SSH only | **yes**, from the owner page once owner authentication exists |

## 9. Exit criteria

| Criterion | Section |
|---|---|
| Normal install understandable without a terminal | 4 (once the owner page exists; SSH until then) |
| Failure never leaves a half-installed catalog | 2.3, 4.3, 5 (each step is one ledger transaction) |
| The owner sees where a game came from | 3 (source and publisher on the card), 4.2 |
| Explicit rollback and recovery | 5 |
| Offline sideload first-class | 2.5, 4.1 |
| Source management does not complicate guest play | 2.4, 7 |
| Storage and library expectations | 3, 6 |
| Companion app as remote control only | 2.1 |

## 10. Order of work (not done here)

1. `install_game update <file>` and `rollback <id>` on the existing ledger, after AVR-58 P1 (the kept previous version).
2. A `list --json` that carries the card states of section 3 (one reader, which the owner page and app both use).
3. The owner page's Games screen, after AVR-44's owner session.
4. Sources, after AVR-58 §7.
