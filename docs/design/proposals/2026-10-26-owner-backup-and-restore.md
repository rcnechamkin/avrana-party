# Owner backup and restore: what the appliance keeps, and how an owner gets it back (AVR-81)

- **Status:** proposal, 2026-10-26. Nothing is implemented. No file, unit, path or tool changes with this
  document. **Owner decisions are required** (section 7) before any code is written.
- **Reads with:** `deploy/appliance-inventory.json` (every path below comes from it or from the code named),
  [SYSTEM.md](../../SYSTEM.md) "Runtime-only paths", `avrana/ops/rebuild.py` (AVR-32), `avrana/ops/install_game.py`
  (AVR-39), [ADR 0016](../../adr/0016-service-identities-and-local-trust-boundary.md) (secret ownership).
- **Why now:** the support and warranty decision packet (Linear AVR-448) found that without backup and
  restore, a faulty unit cannot be swapped without the owner losing their setup. Every exchange then becomes a
  manual rebuild.

## 1. What exists today

| Fact | Where |
|---|---|
| `rebuild restore BACKUP` undoes the file changes of **one `rebuild apply`**. It does not back up an owner's setup. | `avrana/ops/rebuild.py` (`restore`, line 1063); backups under `/var/backups/avrana-party/rebuild-<UTC>/` |
| The rebuild tool refuses to create, read, copy or remove any secret path | `rebuild.py` `SECRET_TREES`, `SECRET_FILES` (lines 111-113) |
| An installed package leaves an install record (id, version, sha256, grants) and a staged tree. **The original `.avrgame` archive is not kept on the device.** | `install_game.py` (`records_dir` `/etc/avrana-party/packages.d`, `games_root` `/opt/avrana-games`) |
| The effective catalog is derived from the web release and the records | `avrana/ops/catalog_overlay.py` (`DEFAULT_DIR` `/var/lib/avrana-party/catalog`) |
| The party itself is memory-only. Only phone identities persist (hashed tokens to device ids, 0600 JSON). | `avrana/party/core.py:62`; `identity.DeviceStore`; `party-core.json` `"devices"` |
| No owner-facing admin, export or import exists | AVR-44 (Backlog) |

## 2. Every kind of state, and what a backup does with it

| Class | What | Path (inventory / code) | In a backup? | On restore |
|---|---|---|---|---|
| **R: rebuilt from a release** | Party, Games and web releases; the games venv; template units | `/opt/avrana-party*`, `/var/www/avrana-party/web/*`, `/etc/systemd/system/avrana*` | **no** | `rebuild apply` and `ops/deploy.sh` at the unit's own version |
| **R** | Effective catalog | `/var/lib/avrana-party/catalog/` | no | regenerated (`catalog_overlay.after_change`) |
| **O: owner configuration** | Access point name, channel, regulatory country | the NetworkManager AP profile (inventory `network`, unknowns U4, U5) | **yes**, non-secret fields only | rewritten through the same nmcli path `rebuild ap-profile` prints |
| **O, secret** | Wi-Fi passphrase | `/etc/NetworkManager/system-connections/` | **only if the owner chooses, and only encrypted** (D2) | set at NetworkManager's prompt, or from the encrypted backup |
| **O** | Edits to `party-core.json` | `/etc/avrana-party/party-core.json` | yes, as a diff against the release's example | merged only for known keys; unknown keys refused and reported |
| **O** | Installed packages and their grants | `/etc/avrana-party/packages.d/<id>.json` | the **list** (id, version, sha256, grants); archives per D1 | each package re-installed through `install_game` with the same grants: the same validation, never a file copy |
| **O** | Game covers | `/srv/avrana/covers` (inventory `not_managed`, AVR-306) | yes | copied back, then the web release re-made (`ops/install-party-web.sh`) |
| **O, future** | People profiles, results history | AVR-85, AVR-71 (not built) | yes when they exist | – |
| **S: device secrets** | Game session keys | `/etc/avrana-party/game-keys/` | **never** | **regenerated on the device** (`ops/provision-party-game-key.sh`, `ops/provision-game`). They are per-device and the games receive the new ones. |
| **S** | TLS private key, ACME account, Cloudflare token | `/etc/avrana-party/tls/`, `/var/lib/avrana-party/lego/`, `/etc/avrana-party/cloudflare.env` | **never** | re-issued on the device (party-https runbook), or the unit runs Limited Mode until then (ADR 0012) |
| **S** | Operator SSH and GitHub keys | inventory `operator-access` | never | provisioned again by the owner |
| **E: ephemeral** | Phone identities | `/var/lib/avrana-party-core/devices.json` | **no** by default (D4) | phones join again as new devices; the party is memory-only anyway |
| **E** | DHCP leases, journal, telemetry, nginx logs | SYSTEM.md runtime-only paths | never | – |
| **C: owner-supplied content** | ROMs and BIOS | `/srv/avrana/…` | **no** by default (D3) | the owner copies them back, as today |

The rule this table follows: **a backup holds what only the owner chose, never what the device can make again,
and never a credential that would work anywhere other than this unit.** The single exception is the Wi-Fi
passphrase, and it is opt-in and encrypted.

## 3. The backup file (proposal)

- One file, `avrana-backup-<hostname>-<UTC>.avrbak`: a tar archive containing `manifest.json` and the files.
- `manifest.json`:
  - `schema` (`avrana.backup/v1`), the unit's Party, Games and web versions, the UTC time;
  - for each entry: its class, its logical name (never an absolute path chosen by the archive), size and SHA-256;
  - the package list.
  - It contains **no** participant ids, display names, device tokens or IP addresses.
- When the passphrase is included, the whole file is encrypted with an owner passphrase (scrypt or age style; the
  choice is left to implementation review). Without it, the file holds nothing secret but is still private
  (covers, network name).
- Where it goes:
  - downloaded by the owner from the owner page (AVR-44) over the Party's HTTPS origin, never over plain HTTP;
  - or written to a USB stick the owner plugs in.
  - **Never uploaded anywhere by the appliance.**

## 4. Restore (proposal)

1. **Precondition:** a unit reflashed or rebuilt to the same Party version or a newer one (AVR-32). Restore
   onto a newer version is allowed; onto an older version it is refused.
2. **Treat the file as untrusted input:**
   - check the manifest against the schema;
   - check every entry's hash;
   - refuse any entry whose logical name is not in the allow-list of section 2;
   - refuse links, absolute paths and `..`;
   - cap sizes (the kit's and `install_game`'s existing rules are the model).
3. **Dry run first:** print what would change, like `rebuild plan` and `install_game --dry-run`.
4. **Apply, in order:**
   - network profile (non-secret fields, then the passphrase if present);
   - `party-core.json` known keys;
   - covers;
   - each package through `install_game` with its recorded grants;
   - catalog regeneration;
   - key provisioning for each game;
   - certificate re-issue, or Limited Mode.
5. **Verify:** `rebuild verify` (state, smoke, topology, boundary) and `install_game list --json` against the
   manifest. The result is written next to the backup, and nothing is reported as done unless verify passed.
6. **A failed restore leaves the unit as it was before step 4.** That is the same promise `install_game` already
   keeps for a failed install, and `install_rehearsal.py` already proves it.

## 5. Security and privacy

- No key that can sign a game ticket or prove the unit's HTTPS identity is ever in a backup. A stolen backup
  cannot impersonate the unit or a game.
- An unencrypted backup reveals the network name, covers and the list of installed games. It reveals nothing
  about guests.
- Restore is a privileged owner action:
  - it is gated like install (AVR-44's owner credential, not the Party Host);
  - a guest can never start it;
  - the Host's game powers do not include it.
- The archive parser is an attack surface. It must be fuzzed and run with the same no-follow, no-traversal file
  rules `install_game` uses.

## 6. What this does not cover

- Moving a party between units while it is live (AVR-21 continuity).
- A disk image of the whole card. That is a different, larger tool, and it would copy secrets.
- Publisher entitlements or licensed games (AVR-316).
- Signed provenance of the backup (it could follow AVR-58 and AVR-82 later).

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | The device does not keep `.avrgame` archives. How does restore get them back? | a) back up the list only, and the owner supplies the archives; b) keep each installed archive on the device at install time (an `install_game` change, plus disk space) and include it in the backup; c) re-download (needs a source; AVR-57) | **b** for built-in and owner-installed packages: a restore that needs files the owner no longer has is not a restore |
| D2 | Include the Wi-Fi passphrase? | never; opt-in and encrypted; always and encrypted | **opt-in, encrypted** |
| D3 | Include ROMs and BIOS? | never; opt-in | **never**: owner content, size, and rights (AVR-434) |
| D4 | Keep phone identities across a restore? | no; opt-in | **no**: phones simply join again |
| D5 | Where backups go | download; USB; both | **both**, no cloud |
| D6 | Automatic backups on the device before an update? | yes (to `/var/backups`); no | **yes**, keeping the newest 3, so a failed update can be rolled back (AVR-82) |

## 8. Tests to write with the implementation

- Round trip: back up a rehearsal root with two packages, covers and a network name; restore onto a fresh root;
  `install_game list --json` and the catalog are equal. Same scratch-root method as `tools/install_rehearsal.py`.
- No secret ever: generate keys and a certificate on the source root, back up, and assert that no secret path's
  bytes appear anywhere in the archive.
- Untrusted archive: traversal, a link, a wrong hash, an unknown class, an oversize entry and a schema from the
  future are each refused with nothing changed.
- Downgrade refused; upgrade allowed.
- A failure injected in the middle of step 4 leaves the root byte-identical to before.

## 9. Unknowns this depends on

- U5: the full AP profile fields. A backup must know which ones are owner choices.
- AVR-44: the owner credential and the owner page.
- AVR-85 and AVR-71: future owner data.
- The sizes of real covers and packages (a USB stick versus a phone download).
