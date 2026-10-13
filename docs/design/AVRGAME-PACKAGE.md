# `.avrgame` package format (EXPERIMENTAL)

- **Status:** **EXPERIMENTAL (2026-10-10). Implemented as a library and CLI; not a specification, not frozen, not an SDK.** The format string is `avrana.avrgame/experimental.1`. Every name, field and limit here may change. It supersedes nothing and no ADR depends on it.
- **Implements:** the subset of AVR-37 that current evidence supports, and a minimal, validated install and remove of an experimental package (a bounded slice of AVR-39: `avrana.ops.install_game`, [install-game runbook](../runbooks/install-game.md)). Not run on the appliance.
- **Evidence input:** [AVRGAME-EXPERIMENTAL-DRAFT](../research/AVRGAME-EXPERIMENTAL-DRAFT.md) (research; history, not edited here).
- **Code:** `avrana/avrgame/` (format; `installed.py` the install records; `node.py` the rules of a Node package, `node_pin.py` the pinned Node build), `avrana/ops/install_game.py`, `avrana/ops/node_runtime.py`, `tools/build_avrgame_tools.py` (the developer tools export, AVR-59); tests `tests/unit/test_avrgame_package.py`, `tests/unit/test_install_game.py`, `tests/unit/test_node_game_runtime.py`, `tests/unit/test_avrgame_tools_export.py`; real-systemd proofs `experiments/native-game/package-proof.sh` (a Python package) and `node-package-proof.sh` (a Node package).

**Freeze gates, all unmet.** (1) Checkers integration: met for drafting only. (2) Written review of the AVR-27 four-human BLUFF evidence against this text and owner acceptance: not met. (3) Spades boundary validation (ADR 0014 decision 12): not met. Until the owner freezes it, nothing may call `.avrgame` v0, stable or frozen.

## What a package is

A package is one ZIP file (`*.avrgame`) holding a **native** game: its authoritative server process (runtime: python | node) and a portable browser client bundle. The appliance validates it, and an installer (later lane) stages it, maps it to a grant and provisions it through the same path first-party native games use. Browser-only guest play is unchanged: phones need no app, account or store.

**Valid is not trusted.** A package is untrusted input even when it validates. Validation reads bytes and checks data; it never executes, imports or evaluates anything from the package, and there are no install hooks or scripts. What a valid package may do is decided by the appliance (grant, tier, sandbox, ADR 0016), never by the package. A package may **request**; it can never **grant**.

## Archive

- ZIP, entries stored or deflated only. `avrgame.json` at the root; everything else under relative paths. The package root becomes the server's working directory, so a Python game ships its importable packages at the root, and a Node game its entry file and any vendored `node_modules`.
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
| `server.interpreter` | the runtime, a **name** from the appliance's allowlist (`INTERPRETERS`): `python3` (mapped to `/usr/bin/python3`) or `node` (mapped to the appliance's pinned Node build, when it has one); never a path |
| `server.args` | 1-16 strings, each 1-200 printable characters, no control characters, no absolute path or `..` (a hygiene check, not a sandbox). For `python3` the only supported form is `["-m", "<dotted module>", ...]`, and the module must exist in the package as `NAME/__main__.py` or `NAME.py` (checked statically; nothing is imported or run). `-c`, a script path or other interpreter options are refused with a message saying so. For `node` the only supported form is `["<entry>.mjs", ...]`: the first argument is the entry, a file of the package (same name rules as an archive entry) ending in `.mjs`, outside any `node_modules`; `.js`, `.cjs`, an option such as `--eval` or `--require`, and a path that leaves the package are refused. The arguments after it reach the script, never Node |
| `client.root` | relative directory inside the package holding the portable browser bundle; must contain `index.html`. Informational today (the game's own server serves it) |

`publisher`, `license` and `source` are **display-only claims**; no trust derives from them. The manifest has no tier, entry path, health check, granted permission, key, socket or absolute path; those keys are refused by name (`set by the appliance`).

**Reserved, refused today:** top-level `signature`, `provenance`, `entitlement`, `publisher_key` ("reserved; not implemented in this experimental format"), so an ignored signature can never look like a checked one. No field requires a store, account, signature or entitlement.

## Runtimes

`runtime: python | node`, chosen by `server.interpreter`. Both run in the same template unit with the same sandbox, lifecycle and grant; a package never says how it is started beyond its runtime name and arguments. There is no install step for either: **no install-time script, no `pip` or `npm install`, no lifecycle script, no shell command.** What a package needs it carries as plain files.

| | python | node |
|---|---|---|
| `server.interpreter` | `python3` | `node` |
| Executable (the appliance's) | `/usr/bin/python3` | `/opt/avrana-runtimes/node-22.22.2/bin/node`, a pinned official build |
| On every appliance | yes | **optional**: installed by `ops/install-node-runtime`; a Node package on an appliance without it is refused at install, by name, before anything is written |
| `server.args` | `["-m", "<module>", ...]` | `["<entry>.mjs", ...]` |
| Dependencies | importable packages at the root | vendored under `node_modules` as plain files |

**The Node runtime (AVR-68, EXPERIMENTAL, not installed on the appliance).** One version, pinned in `avrana/avrgame/node_pin.py` with the SHA-256 of the official `linux-arm64` and `linux-x64` tarballs (from nodejs.org's `SHASUMS256.txt`). `ops/install-node-runtime install <tarball>` runs offline: the operator supplies the tarball, the tool opens it once, reads it whole, accepts those bytes only when their digest is the pin for this machine's architecture (the file at that path is never opened again, so swapping it after the check changes nothing), takes out **only `bin/node` and `LICENSE`** (no npm, npx, corepack, headers or links), and leaves `/opt/avrana-runtimes/node-<version>/` root-owned with a record of both digests (`verify` re-checks it; `remove` is refused while an installed package runs on it or while a file in the records directory cannot be read as a record, and always clears the staging directory of a killed install). It never downloads. Party Core never imports, runs or looks for Node: it knows only the path text in an install record, and Python packages are unaffected by the runtime being present or absent. Moving the pin (or the appliance's options of Node) is a code change, and it is not transparent: an install record written before the change names the old executable or options, is **refused when records are loaded**, and its game is not offered until the operator runs `install-game remove <id>` and installs the package again. The old tree stays on disk until `install-node-runtime remove --version <old>` (refused while a record still names it, and for a tree whose own record does not say this tool made it).

**What a Node package may contain.** Source only. `node_modules` is ordinary package content under the ordinary rules: regular files, no symbolic link (so a linked `pnpm` layout must be flattened), no dot entries (so no `node_modules/.bin`, `.package-lock.json`; `pack` skips them), the same limits (2000 files, 64 MiB; **not raised**: a larger dependency tree should be bundled into a few files). Compiled code is refused for a Node package: by name (`*.node` native addons, `*.so`, `*.dylib`, `*.dll`, `*.exe`) and by content (a file that begins with the ELF or Mach-O magic, whatever it is called). WebAssembly is allowed: it runs inside V8. A vendored `package.json` is inert data: its `scripts` (`preinstall`, `install`, `postinstall`) are never read, and there is no npm on the appliance to run them. **This is review hygiene, not a boundary:** code that runs can still write a file to its private `/tmp` and execute it; the unit sandbox is what confines it. The compiled-code rule is not applied to Python packages today (unchanged behavior; a `.so` extension module is not refused there).

**Sandbox: identical for both runtimes.** A Node unit's drop-in differs from a Python package's in `ExecStart=`, `WorkingDirectory=` and one line that only takes away, `UnsetEnvironment=NODE_OPTIONS NODE_PATH` (a unit test compares them): the community-tier ceilings below, `MemoryMax=256M` and `TasksMax=64` included, socket activation on file descriptor 3, the key as a credential, `RestrictAddressFamilies=AF_UNIX` and `PrivateNetwork=yes` (no egress), `DynamicUser=`. **No directive is relaxed for V8.** The JIT needs to map executable memory, which `MemoryDenyWriteExecute=` would forbid; neither the template nor the drop-in sets it (nor a `SystemCallFilter=`), for either runtime, so there was nothing to relax. `node-package-proof.sh` checks on a real systemd that V8 compiles and runs machine code inside the unit (the fixture compiles and calls a WebAssembly function at start, which has no interpreter in V8). If `MemoryDenyWriteExecute=yes` is ever added to package units, Node needs either an exemption or `--jitless` (no WebAssembly, and markedly slower: see the measurement). A realtime game needs nothing more: a WebSocket is an HTTP upgrade on the same Unix socket.

**What Node is told is the appliance's.** The command of a Node unit is `<pinned node> --max-old-space-size=192 <entry>.mjs [args]`. The option is `node_pin.OPTIONS`, put between the executable and the entry by the installer, required in exactly that form when a record is loaded, and never a package's: a manifest's first argument must be the `.mjs` entry, so it cannot name an option of Node. It caps V8's old generation under the unit's `MemoryMax=256M`, so V8 collects (and at the end fails the allocation and exits) before the cgroup acts. It is a cap on one heap, not on the process: buffers and other memory outside the V8 heap are not counted by it. A process that still outgrows `MemoryMax` is killed by the cgroup, and what happens next is the template's existing `Restart=on-failure`, the same as for any game; nothing new was added for that. `NODE_OPTIONS` and `NODE_PATH` are unset on the unit, so nothing but that command line says what Node runs or where it finds modules (a command-line option already wins over `NODE_OPTIONS`, but the variable can carry `--require` and `--import`, which the command line does not answer).

**Measured (one run, a disposable x86-64 CI runner, systemd 255; not the Pi, not arm64):** https://github.com/rcnechamkin/avrana-party/actions/runs/38433397837 (commit bcce379, job `node-package`, 119 checks). The idle fixture game (one HTTP server, one vendored module) under the real unit: **RSS 61 264 kB** (high-water 61 724 kB), **7 threads**; its cgroup: `MemoryCurrent` 16.6 MB of `MemoryMax` 256M (the RSS counts the mapped Node binary, which the cgroup does not charge to the unit in full), `TasksCurrent` **7 of 64**. V8 compiled and ran machine code in the sandbox (`jit ok`). `--jitless` beside the default, same binary outside the unit: an arithmetic loop took 1249 ms against 373 ms (about 3.3 times slower), RSS 45.8 MB against 52.4 MB (about 7 MB less), and there is no `WebAssembly`. The JIT stays on. In that run V8 reported a heap limit of 259 MiB inside the 256M unit, which is why the appliance now passes `--max-old-space-size=192`. **Not measured on Linux since:** the numbers above are from before that option. With it, the same Node version reports a heap limit of 240 MiB (a unit test asks a real `node` when one is on PATH; seen on a Windows x64 laptop only); `node-package-proof.sh` now checks the unit's effective command line, the unset variables and that limit on a real systemd, and that script has not run since the change. **Open:** 192 is a first value, not a tuned one: it needs a real game and an arm64 measurement.

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

**Run the tooling from the Party checkout, or from the experimental tools export.** `python -m avrana.avrgame` and `python -m avrana.ops.install_game` import the `avrana` package and read `contracts/` from the checkout they live in. Run them with the working directory set to the Party checkout, or set `PYTHONPATH` to it (`PYTHONPATH=/path/to/avrana-party python -m avrana.avrgame pack /path/to/game/hello_party/avrgame.build.json`). **An experimental tools export exists and is not published.** `python tools/build_avrgame_tools.py --out DIR` (outside the repository; it refuses a dirty tree unless `--allow-dirty`, and then the file name and the top directory in the zip say `-dirty`) writes `avrana-avrgame-tools-experimental.1.zip` and its `.sha256`: the validator and packer only (`avrana/avrgame/` without `installed.py`, the Game Contract validator, three generated stand-ins that hold the session protocol version, the result schema string and the bridge protocol version and nothing else, and a reduced capability-names JSON with placeholder labels; the Party-to-Games declaration file is not shipped, and comments and docstrings naming internal material are removed from the copied code, which is proven unchanged as a syntax tree), a README for an outside developer, a NOTICE, a snapshot of this note's format sections and a `MANIFEST.json` with every file's sha256 and the source commit. It is reproducible (sorted entries, fixed times, stored, LF text), is unpacked and exercised from a clean directory before it is called good, and its tool is checked to give the same packed bytes and refusals as this repository's. CI builds and verifies it, fails the job if it does not verify, and prints its sha256, but keeps no copy (no workflow artifact). **Nothing hands it to anyone**: whether and on what terms it is redistributed (the repository states no licence) and whether the protocol version strings and this format description may go to outside developers are owner decisions, not made here. It has no installer: installation stays the appliance owner's `install-game`. It is a local file (CI keeps no copy), not an SDK and not a promise.

## Install lifecycle (EXPERIMENTAL, AVR-39)

`python3 -m avrana.ops.install_game install|remove|list|verify` (wrapper `ops/install-game`; procedure and trust statement: [install-game runbook](../runbooks/install-game.md)). It calls the existing `avrana.ops.provision_game` functions for keys, registry entries, units and reloads; there is one path onto the appliance.

1. Validate the archive as untrusted input (`avrana.avrgame.read`); refuse an unsupported format or `requires`, a first-party or reserved id, an installed id (upgrade and rollback are not implemented: AVR-58, AVR-60), an id already provisioned by other means.
2. Preflight what provisioning needs (phase 1, Party Core's config naming the registry and the `packages` directory, the Party origin, a trusted games root and interpreter).
3. Stage into `/opt/avrana-games/.staging-<random>` (root, `0700`), re-hash every file, set modes (directories `0755`, files `0644`), flush, rename to `/opt/avrana-games/<id>/<version>-<sha12>`.
4. Write the **install record** `/etc/avrana-party/packages.d/<id>.json` atomically. This is the one generic overlay: Party Core and the catalog read installed games' contracts and grants from these records, in addition to `contracts/games/` and the appliance profile. `avrana/avrgame/installed.py` re-validates every record on every load (contract with the existing validator, grant with the appliance grant rules, tier `community`, entry `/games/<id>/`, working directory = the staged root, no collision with a repository game) and refuses a bad record by itself.
5. `provision_game.provision` with the repository contracts merged with the installed ones, `trusted=trusted_path`.
6. On any failure after step 3 began, unwind in reverse and report the original failure.

Record schema (`avrana.avrgame-install/experimental.1`): `id`, `version`, `sha256` (archive), `format`, `installed_at`, `root`, `files` (path, size, sha256), `contract`, `grant` (`game`, `entry`, `tier`, `permissions_granted`, `runtime`), `package` (publisher, license, source: unverified claims). Granted permissions are the contract's request intersected with the operator's `--grant` flags; the tier is always `community`.

**Catalog (AVR-337, experimental, not deployed).** Party Home reads `/party/catalog.json`, a static, generated file of the release tree that an install never rewrites; a game without a row in it has no tile and no navigation target on a phone, although Party Core offers and can launch it. An installed package therefore appears through an **effective catalog**: `avrana/ops/catalog_overlay.py` writes the release's `catalog.json` plus one row per installed package (appended in id order, after every first-party row, which stay byte-identical; a package whose id is already in the catalog is not listed) to `/var/lib/avrana-party/catalog/catalog.json` (root-owned, `0644`, atomic, deterministic), and an exact `location = /party/catalog.json` in `avrana-party.nginx` serves that file when it exists and the release's file when it does not (`try_files`; nginx only reads, same headers as `/party/`). With no package installed the overlay does not exist and the appliance serves exactly the committed catalog. `install-game install` and `remove` regenerate it; **an install whose catalog cannot be written is undone** (fail closed: no game that nobody can see), and a failed regeneration removes the overlay, so the worst case is the committed catalog with no package tile. The overlay is derived from the release, so `ops/install-party-web.sh` regenerates it whenever `current` moves (new release, rollback; the hook is an owner decision of 2026-10-10); `ops/catalog-overlay check` reports a stale one and `refresh` repairs it. A record that is refused, or a row the catalog builder rejects, drops that package only. The service worker needs no change: it fetches the catalog network-first. A package's own `web/icon.svg` is not shown (a tile draws its kind icon): `img-src 'self'` keeps a phone from loading it from the game origin. Custom package icons are deferred and the CSP is not relaxed (owner decision 2026-10-10). A package row is not trusted text: only an allowlist of the builder's keys survives (provider, status, tier, entry and installed are set by the appliance, not read from the contract; legacy slug, integration, icon, art, accent, category and the like are dropped), every string and the row are bounded (name 60, summary 400, other text 200, row 4 KB, overlay 5 MB), and a display name equal to a first-party game's name or id (after NFKC, case folding and whitespace collapse) is refused. A package whose row is refused makes the install fail and be undone; for an already installed one only that row is dropped and `catalog-overlay check` prints a warning line. Confusable letters (Cyrillic or Greek look-alikes of Latin ones) are NOT folded in that comparison: a documented residual. Three states leave a tile that cannot launch: an install record deleted by hand (the overlay still lists the game until the next refresh), provisioning drift (a unit or registry entry removed by hand), and a `remove` that failed midway (the record is deleted last, so it is still there and the best-effort regenerate keeps the row; re-run `install-game remove ID`); `install-game verify ID` and `catalog-overlay refresh` find and clear them. `avrana.ops.smoke` is deliberately not extended: it has only pass, fail and skip, its result goes into the deployment manifest, and a package problem must never fail a first-party deploy, so the stale-overlay consistency check lives in `ops/install-party-web.sh` instead (owner decision 2026-10-10): after the automatic regeneration it runs the read-only `catalog-overlay check` and prints a WARNING with the remedy (`ops/catalog-overlay refresh`); it is output only and never changes the result of a deploy, smoke, the manifest or `/party/api/status`. Alternatives not taken: a Party Core route (a new public route: owner approval) and regenerating the release catalog at deploy (rewrites a committed, CI-checked artifact per appliance). The committed catalog and `python3 -m avrana.contracts.catalog --check` are unchanged; `--packages DIR --out FILE` still builds a standalone catalog for inspection.

**What an installed package can and cannot do** (from [`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service) and ADR 0016; the unit is the only protection):

- **Can:** run arbitrary code as a throwaway `DynamicUser=` (its runtime, Python or Node, and whatever it ships); read any world-readable file on the host, including the install records (they hold no secret); connect to Party Core's internal Unix socket (`AVRANA_PARTY_SOCKET`, group `avrana-games`; authenticated by the game's own key only, so it can also flood it); keep state in its own `StateDirectory=` (`0700`, no disk quota) when `persistent_storage` is granted; receive, in every launch, the roster of the session (participant id, display name, role) and sign results for its own session.
- **Cannot:** connect to another game's socket (`/run/avrana-games/<id>.sock` is `root:avrana-front` `0660` and a package is not in `avrana-front`; `package-proof.sh` runs the connect with that identity and sees it refused, while Party Core's internal socket accepts it); open IP sockets (`RestrictAddressFamilies=AF_UNIX`); write its own code (the staged tree is root-owned and `ProtectSystem=strict` is implied by `DynamicUser=`); read other games' private state or keys (each game gets only its own key as a credential; state directories are `0700` per dynamic user); see home directories or devices (`ProtectHome`, `PrivateDevices`).
- **`party_roster` is mandatory for the experimental format (owner decision 2026-10-10; revisit before any freeze, AVR-37; not a frozen spec).** Party Core hands every game the roster whatever was granted, so the installer refuses a package that does not request `party_roster` and an install without `--grant party_roster`. What `party_roster` should cover (names, participant ids, or both) and launch-time enforcement remain open for the freeze.
- **Party Core's internal socket (`/run/avrana-party/internal.sock`, group `avrana-games`).** A package can connect, but cannot act as another game: `ended` and the host question are verified with the key of the game that owns the CURRENT session (`avrana/party/sessions.py` `ended` / `host`, `endpoints.get(session.game_id)`), by HMAC (`protocol.unseal`, `protocol.py:194`), the issuer must equal that game (`sessions.py:176`), and a shared nonce guard refuses replays (`protocol.py:402`); a package has only its own key, so another game's result or end is refused (403). Residual: it can send junk or flood the socket (denial of service, no quota), and in `ended` the replay guard is called outside `service.lock` (a narrow race, not a forgery).
- **Community-tier ceilings (AVR-336; provisional values, to be revisited with measurements on a real game and the Pi, owner decision 2026-10-10):** the package's drop-in adds `MemoryMax=256M`, `TasksMax=64`, `CPUQuota=100%`, an empty `CapabilityBoundingSet=`, `PrivateNetwork=yes` (no abstract-namespace sockets of the host; path sockets such as Party's still work), `ProtectProc=invisible`, `ProtectClock`, `ProtectHostname`, `LockPersonality`, `RestrictRealtime` and `RestrictNamespaces`. First-party units are unchanged. A ceiling that is too low kills the package's process, not the host.
- **State directory follows the grant (AVR-336).** A community unit has its `StateDirectory=` (`0700`, from the template) only when `persistent_storage` was requested and granted; otherwise the drop-in resets it (`StateDirectory=`), so the unit has no `$STATE_DIRECTORY` and no persistent directory (`package-proof.sh` checks both cases on a real systemd). `/tmp` is `PrivateTmp` (implied by `DynamicUser=`): private to the unit and discarded when it stops. No game or gamekit in use reads `$STATE_DIRECTORY` (Hello Party requests only `party_roster`).
- **NOT limited today:** `SystemCallFilter=` is **deferred** (owner decision 2026-10-10) until an arm64 run on the Pi with a real game proves a filter; no disk quota (a granted state directory, or `/tmp` while the unit runs, can fill the disk); and **granted permissions are not enforced by Party Core at launch**, so the installer fails closed instead: it refuses `--grant` of any permission the sandbox cannot provide (everything except `persistent_storage` and `party_roster`), and requires `party_roster` (above). `persistent_storage` is enforced by the unit as described.
- The hidden path options (`--games-root`, `--visible-root`, `--records-dir`, `--lock-file`, ...) exist for tests and rehearsals. They are for root only and must never be pointed at a directory a package or a non-root user can write.

**The reference id `hello` cannot be installed as a package on a tree that carries the test fixture `contracts/games/hello.json`:** the installer refuses to shadow a repository contract (the CI proof deletes that fixture from its copied tree on purpose). A developer installs their own renamed game. **Validation cannot prove a package starts.** It checks bytes, the manifest and that the `-m` module (or the Node entry file) exists in the package; the only gate is running it: the Games walkthrough's packaged-conformance step, and the real-systemd proof.

## Explicitly deferred

| Topic | Where it belongs |
|---|---|
| Signing, provenance, publisher identity | AVR-58 |
| Package repository, community source | AVR-57 |
| Presenting requested permissions to a guest or owner | AVR-62 |
| Client cache, progressive delivery, loading profile, seat-ready signal | AVR-135 |
| `client.onboarding` schema, artwork | onboarding and art issues (AVR-294) |
| Tuning the community-tier ceilings (CPU, memory), a syscall filter, a disk quota | needs measurement on a real game and a Pi run |
| The Node runtime on arm64 and on the Pi; a V8 heap setting; more than one Node version side by side | not run on arm64 (the proof is x86-64); owner decision |
| Compatibility and deprecation policy | AVR-72 |
| Owner-app hosting and transport | AVR-45, AVR-63 |
| Storefront, entitlement, licensing | AVR-143, AVR-316, AVR-73 |
| Emulated games | a separate provider, never this format |
| Update, rollback | AVR-58, AVR-60 |
| Serving a catalog that lists installed packages on the appliance | built (AVR-337, effective-catalog overlay served by an exact nginx location): owner decision 2026-10-10; the nginx deploy is the owner's |
| Enforcing permissions at launch (roster redaction); what `party_roster` covers | revisit before any freeze (AVR-37) |

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
| A validated install and remove workflow through the existing native provisioning path | **Met in code and unit tests** (scratch directories, recorded systemctl). Real systemd (disposable CI runner): `package-proof.sh`, https://github.com/rcnechamkin/avrana-party/actions/runs/38082213316 (commit 44275a1, 78 checks); never the Pi |
| Nothing half-installed after a failure | Met in unit tests at every injected failure point; kill -9 repair by `remove` tested by simulating the partial states |
| A valid package is not trusted; tier community; operator grants | Met (`--grant`, record re-validation); permissions are recorded, **not enforced at launch** by Party Core; the installer fails closed on what it cannot enforce (AVR-336) |
| Package content never imported or executed by the installer | Met by construction (only bytes are read and hashed); the game runs only in the template unit |
| Staged tree root-owned, not group/world writable, no links; trusted-path rule | Met in code; root ownership is asserted on a real host only by the proof |
| Upgrade, rollback | **Not met**, deferred (AVR-58, AVR-60) |
| Signing, provenance, publisher identity, repository, permission prompts | **Not met**, deferred (AVR-58, AVR-57, AVR-62) |
| A phone sees the installed game in Party Home on a real appliance | **Partly**: Party Core offers and launches it; the phone catalog is static and does not list it until an owner-approved catalog route exists |
| Resource ceilings | **Partly** (AVR-336): provisional community-tier ceilings are set and checked on a real systemd; to be revisited with measurements |
| Run on the Pi | **Not done** and not authorized |
