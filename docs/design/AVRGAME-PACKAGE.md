# `.avrgame` package format (EXPERIMENTAL)

- **Status:** **EXPERIMENTAL (2026-10-10). Implemented as a library and CLI; not a specification, not frozen, not an SDK.** The format string is `avrana.avrgame/experimental.1`. Every name, field and limit here may change. It supersedes nothing and no ADR depends on it.
- **Implements:** the subset of AVR-37 that current evidence supports, and a minimal, validated install and remove of an experimental package (a bounded slice of AVR-39: `avrana.ops.install_game`, [install-game runbook](../runbooks/install-game.md)). Not run on the appliance.
- **Evidence input:** [AVRGAME-EXPERIMENTAL-DRAFT](../research/AVRGAME-EXPERIMENTAL-DRAFT.md) (research; history, not edited here).
- **Code:** `avrana/avrgame/` (format; `installed.py` the install records), `avrana/ops/install_game.py`; tests `tests/unit/test_avrgame_package.py`, `tests/unit/test_install_game.py`; real-systemd proof `experiments/native-game/package-proof.sh`.

**Freeze gates, all unmet.** (1) Checkers integration: met for drafting only. (2) Written review of the AVR-27 four-human BLUFF evidence against this text and owner acceptance: not met. (3) Spades boundary validation (ADR 0014 decision 12): not met. Until the owner freezes it, nothing may call `.avrgame` v0, stable or frozen.

## What a package is

A package is one ZIP file (`*.avrgame`) holding a **native** game: its authoritative server process (today Python, stdlib) and a portable browser client bundle. The appliance validates it, and an installer (later lane) stages it, maps it to a grant and provisions it through the same path first-party native games use. Browser-only guest play is unchanged: phones need no app, account or store.

**Valid is not trusted.** A package is untrusted input even when it validates. Validation reads bytes and checks data; it never executes, imports or evaluates anything from the package, and there are no install hooks or scripts. What a valid package may do is decided by the appliance (grant, tier, sandbox, ADR 0016), never by the package. A package may **request**; it can never **grant**.

## Archive

- ZIP, entries stored or deflated only. `avrgame.json` at the root; everything else under relative paths. The package root becomes the server's working directory, so a Python game ships its importable packages at the root.
- Names: relative, `/` separated, ASCII letters, digits and `. _ + @ = ~ -` only; at most 200 characters and 16 segments; no empty, `.` or `..` segments, no backslash, drive letter or `:`, no NUL or control characters, no segment ending in `.` or a space, no dotfiles, no Windows device names (`CON`, `NUL`, `COM1` ...), no two names differing only by case, no name that is both file and directory.
- Key material is refused, not skipped, by the packer and by the validator: any file named `*.key`, `*.pem`, `*.p12`, `*.pfx`, `id_rsa*`, `*.env` or `.env` ("key material must never be in a package").
- Entries must be regular files (or plain directory entries). Symbolic links, devices, FIFOs, sockets, setuid/setgid/sticky bits, encrypted entries and other compression methods are refused. Python bytecode (`*.pyc`, `__pycache__`) is refused: bytecode is not reviewable source.
- Extraction ignores archive modes: files are written 0644, directories 0755, into a **new or empty** directory the caller provides, never following links, and each destination is checked to stay inside it.
- `pack` is deterministic: manifest first, then files sorted by path, timestamps 1980-01-01, mode 0644, no directory entries, and entries **stored** (no compression) by default, so the same inputs give the same bytes, and the same archive sha256, on every machine and zlib build (`--deflate` opts into level-9 deflate, which is smaller but only reproducible with the same zlib). Hidden files, `__pycache__`, `*.pyc` and `avrgame.build.json` are skipped inside directory includes; symbolic links are refused.

### Limits (experimental values)

| Limit | Value |
|---|---|
| Entries (files) | 2000 |
| One file, unpacked | 16 MiB |
| All files, unpacked | 64 MiB |
| Archive file | 64 MiB |
| `avrgame.json` | 256 KiB |
| Name length / depth | 200 characters / 16 segments |

Sizes are enforced against the bytes actually read while streaming, not only the declared headers, so a compression bomb is stopped by what it really expands to.

## Manifest `avrgame.json`

Strict JSON (duplicate keys, NaN, a BOM or an unknown key anywhere in the envelope is an error). All validation problems are collected, not just the first.

| Field | Rule |
|---|---|
| `format` | exactly `avrana.avrgame/experimental.1`; anything else is refused (compatibility fails closed) and the message names what is supported |
| `game` | a complete `avrana.game/v0` Game Contract, checked by the existing validator unchanged; the **one** source of game facts, `game.id` is the package id. Must be `kind: native` with `runtime.type: external`, `start: service`. Emulated, LAN module and arcade games are not packageable: emulation is a separate provider. `game.package` is refused (use the block below) |
| `package.version` | `^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]{1,32})?$` |
| `package.publisher`, `license` | required, 1-80 printable characters |
| `package.source` | optional, 1-200 printable characters |
| `requires.session`, `.bridge`, `.result` | all three required; each must equal what this Party implements (read from `avrana/party/protocol.py`, `avrana/party/result.py` and `contracts/party-games.v0.json`). Unknown key or value is refused |
| `server.interpreter` | a **name** from the appliance's allowlist (`INTERPRETERS`, today `python3` mapped to `/usr/bin/python3`); never a path |
| `server.args` | 1-16 strings, each 1-200 printable characters, no control characters, no absolute path or `..` (a hygiene check, not a sandbox). For `python3` the only supported form is `["-m", "<dotted module>", ...]`, and the module must exist in the package as `NAME/__main__.py` or `NAME.py` (checked statically; nothing is imported or run). `-c`, a script path or other interpreter options are refused with a message saying so |
| `client.root` | relative directory inside the package holding the portable browser bundle; must contain `index.html`. Informational today (the game's own server serves it) |

`publisher`, `license` and `source` are **display-only claims**; no trust derives from them. The manifest has no tier, entry path, health check, granted permission, key, socket or absolute path; those keys are refused by name (`set by the appliance`).

**Reserved, refused today:** top-level `signature`, `provenance`, `entitlement`, `publisher_key` ("reserved; not implemented in this experimental format"), so an ignored signature can never look like a checked one. No field requires a store, account, signature or entitlement.

## Build recipe (developer convenience)

`avrgame.build.json` beside the manifest; not in the archive and not part of the package contract:
`{"recipe": "avrana.avrgame-build/experimental.1", "manifest": "avrgame.json", "root": "..", "include": [...]}`. `manifest` and `root` are relative to the recipe file (defaults `avrgame.json` and `.`); `include` entries are relative to `root` and may not escape it; directories are recursive. Unknown keys are refused.

## API and CLI

`avrana.avrgame`: `FORMAT`, `INTERPRETERS`, `Refused(problems)`, `validate_manifest(obj)`, `read(path)` / `inspect(path)`, `extract(path, dest)`, `pack(source_root, manifest_path, includes, out_path)`, `pack_recipe(recipe_path, out_path=None)`, `validate_recipe(recipe_path)`, `scan(bytes)`, and the `Package` / `PackageFile` dataclasses (module docstring has the signatures).

```
python -m avrana.avrgame validate <file.avrgame | directory-with-recipe>
python -m avrana.avrgame pack <path/to/avrgame.build.json> [--out FILE] [--deflate]
python -m avrana.avrgame inspect <file.avrgame> [--json]
python -m avrana.avrgame extract <file.avrgame> <dest>      # validate, then unpack into a new or empty directory
```

Exit 0 success, 1 refused (one problem per line on stderr), 2 usage.

**Known limitation: run the tooling from the Party checkout.** `python -m avrana.avrgame` and `python -m avrana.ops.install_game` import the `avrana` package and read `contracts/` from the checkout they live in. Run them with the working directory set to the Party checkout, or set `PYTHONPATH` to it (`PYTHONPATH=/path/to/avrana-party python -m avrana.avrgame pack /path/to/game/hello_party/avrgame.build.json`). There is no installable distribution of this tooling yet.

## Install lifecycle (EXPERIMENTAL, AVR-39)

`python3 -m avrana.ops.install_game install|remove|list|verify` (wrapper `ops/install-game`; procedure and trust statement: [install-game runbook](../runbooks/install-game.md)). It calls the existing `avrana.ops.provision_game` functions for keys, registry entries, units and reloads; there is one path onto the appliance.

1. Validate the archive as untrusted input (`avrana.avrgame.read`); refuse an unsupported format or `requires`, a first-party or reserved id, an installed id (upgrade and rollback are not implemented: AVR-58, AVR-60), an id already provisioned by other means.
2. Preflight what provisioning needs (phase 1, Party Core's config naming the registry and the `packages` directory, the Party origin, a trusted games root and interpreter).
3. Stage into `/opt/avrana-games/.staging-<random>` (root, `0700`), re-hash every file, set modes (directories `0755`, files `0644`), flush, rename to `/opt/avrana-games/<id>/<version>-<sha12>`.
4. Write the **install record** `/etc/avrana-party/packages.d/<id>.json` atomically. This is the one generic overlay: Party Core and the catalog read installed games' contracts and grants from these records, in addition to `contracts/games/` and the appliance profile. `avrana/avrgame/installed.py` re-validates every record on every load (contract with the existing validator, grant with the appliance grant rules, tier `community`, entry `/games/<id>/`, working directory = the staged root, no collision with a repository game) and refuses a bad record by itself.
5. `provision_game.provision` with the repository contracts merged with the installed ones, `trusted=trusted_path`.
6. On any failure after step 3 began, unwind in reverse and report the original failure.

Record schema (`avrana.avrgame-install/experimental.1`): `id`, `version`, `sha256` (archive), `format`, `installed_at`, `root`, `files` (path, size, sha256), `contract`, `grant` (`game`, `entry`, `tier`, `permissions_granted`, `runtime`), `package` (publisher, license, source: unverified claims). Granted permissions are the contract's request intersected with the operator's `--grant` flags; the tier is always `community`.

**Catalog.** Party Home reads a static, generated `web/party/catalog.json`; a game without an installed catalog row has no tile and no navigation target on a phone, although Party Core offers and can launch it. `python3 -m avrana.contracts.catalog --packages DIR --out FILE` builds a catalog that includes installed packages (the committed catalog and `--check` are unchanged without `--packages`). The installer does not rewrite the release tree's catalog. Whether the appliance serves a regenerated catalog (a writable web overlay, a Party Core route, or a deploy step) touches deploy, nginx and routes: **an owner decision, not made here.**

**What an installed package can and cannot do** (from [`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service) and ADR 0016; the unit is the only protection):

- **Can:** run arbitrary code as a throwaway `DynamicUser=` (its Python and whatever it ships); read any world-readable file on the host, including the other install records; connect to the Unix sockets it can reach: other games' sockets (it has the `avrana-games` supplementary group) and Party Core's internal socket (`AVRANA_PARTY_SOCKET`, which is authenticated by the game's own key only); keep state in its own `StateDirectory=` (`0700`); use CPU, memory and processes without limit.
- **Cannot:** open IP sockets (`RestrictAddressFamilies=AF_UNIX`); write its own code (the staged tree is root-owned and `ProtectSystem=strict` is implied by `DynamicUser=`); read other games' private state or keys (each game gets only its own key as a credential; state directories are `0700` per dynamic user); see home directories or devices (`ProtectHome`, `PrivateDevices`).
- **NOT limited today:** no `CapabilityBoundingSet=` and no `SystemCallFilter=` beyond what `DynamicUser=` implies; no `MemoryMax=`, `TasksMax=` or `CPUQuota=`. Granted permissions are recorded and shown but **not enforced** by Party Core at launch.
- The hidden path options (`--games-root`, `--visible-root`, `--records-dir`, `--lock-file`, ...) exist for tests and rehearsals. They are for root only and must never be pointed at a directory a package or a non-root user can write.

**The reference id `hello` cannot be installed as a package on a tree that carries the test fixture `contracts/games/hello.json`:** the installer refuses to shadow a repository contract (the CI proof deletes that fixture from its copied tree on purpose). A developer installs their own renamed game. **Validation cannot prove a package starts.** It checks bytes, the manifest and that the `-m` module exists in the package; the only gate is running it: the Games walkthrough's packaged-conformance step, and the real-systemd proof.

## Explicitly deferred

| Topic | Where it belongs |
|---|---|
| Signing, provenance, publisher identity | AVR-58 |
| Package repository, community source | AVR-57 |
| Presenting requested permissions to a guest or owner | AVR-62 |
| Client cache, progressive delivery, loading profile, seat-ready signal | AVR-135 |
| `client.onboarding` schema, artwork | onboarding and art issues (AVR-294) |
| Resource ceilings (CPU, memory) | needs measurement on a real game |
| Compatibility and deprecation policy | AVR-72 |
| Owner-app hosting and transport | AVR-45, AVR-63 |
| Storefront, entitlement, licensing | AVR-143, AVR-316, AVR-73 |
| Emulated games | a separate provider, never this format |
| Update, rollback | AVR-58, AVR-60 |
| Serving a catalog that lists installed packages on the appliance | owner decision (deploy / nginx / routes) |
| CPU and memory ceilings for a package game | needs a measured real game |

## AVR-37 acceptance, as implemented

| Criterion | Where met, or why not |
|---|---|
| Manifest names the package, version and compatibility | `format`, `package.version`, `requires`; unknown versions refused |
| Strict validation, unknown keys and duplicate keys refused | `manifest.py`, `strictjson`; tests `ManifestTests` |
| One source of game facts | embedded `avrana.game/v0` contract, validated unchanged |
| A package requests, never grants | appliance-owned names refused in envelope and contract; no tier or grant fields |
| Compatibility fails closed | `format` and `requires` checks |
| Safe, bounded archive handling of untrusted input | `archive.py`; `HostileArchiveTests` |
| Offline validator and CLI, no root, no network | `python -m avrana.avrgame validate` |
| Deterministic, reproducible build | `pack`, recipe; determinism tests |
| Portable browser client only, no native phone code | `client.root` must be a directory with `index.html`; nothing else is allowed |
| No store, account or signature required | no such field exists; four names reserved and refused |
| Signing and provenance | **not met**, deferred to AVR-58 |
| Permissions presentation, client cache, onboarding schema, resource ceilings, deprecation policy | **not met**, deferred as listed above |
| Freeze (stable name) | **not met**; owner act after the gates above |

## AVR-39 acceptance (the bounded slice implemented here), honestly

| Criterion | Status |
|---|---|
| A validated install and remove workflow through the existing native provisioning path | **Met in code and unit tests** (scratch directories, recorded systemctl). Real systemd (disposable CI runner): `package-proof.sh`, <RUN-LINK>; never the Pi |
| Nothing half-installed after a failure | Met in unit tests at every injected failure point; kill -9 repair by `remove` tested by simulating the partial states |
| A valid package is not trusted; tier community; operator grants | Met (`--grant`, record re-validation); permissions are recorded, **not enforced at launch** by Party Core |
| Package content never imported or executed by the installer | Met by construction (only bytes are read and hashed); the game runs only in the template unit |
| Staged tree root-owned, not group/world writable, no links; trusted-path rule | Met in code; root ownership is asserted on a real host only by the proof |
| Upgrade, rollback | **Not met**, deferred (AVR-58, AVR-60) |
| Signing, provenance, publisher identity, repository, permission prompts | **Not met**, deferred (AVR-58, AVR-57, AVR-62) |
| A phone sees the installed game in Party Home on a real appliance | **Partly**: Party Core offers and launches it; the phone catalog is static and does not list it until an owner-approved catalog route exists |
| Resource ceilings | **Not met** (needs measurement) |
| Run on the Pi | **Not done** and not authorized |
