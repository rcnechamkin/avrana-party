# `.avrgame` package format (EXPERIMENTAL)

- **Status:** **EXPERIMENTAL (2026-10-10). Implemented as a library and CLI; not a specification, not frozen, not an SDK.** The format string is `avrana.avrgame/experimental.1`. Every name, field and limit here may change. It supersedes nothing and no ADR depends on it.
- **Implements:** the subset of AVR-37 and the validation half of AVR-39 that current evidence supports. Installing a package is a separate lane (`avrana.ops.install_game`, not here).
- **Evidence input:** [AVRGAME-EXPERIMENTAL-DRAFT](../research/AVRGAME-EXPERIMENTAL-DRAFT.md) (research; history, not edited here).
- **Code:** `avrana/avrgame/`; tests `tests/unit/test_avrgame_package.py`.

**Freeze gates, all unmet.** (1) Checkers integration: met for drafting only. (2) Written review of the AVR-27 four-human BLUFF evidence against this text and owner acceptance: not met. (3) Spades boundary validation (ADR 0014 decision 12): not met. Until the owner freezes it, nothing may call `.avrgame` v0, stable or frozen.

## What a package is

A package is one ZIP file (`*.avrgame`) holding a **native** game: its authoritative server process (today Python, stdlib) and a portable browser client bundle. The appliance validates it, and an installer (later lane) stages it, maps it to a grant and provisions it through the same path first-party native games use. Browser-only guest play is unchanged: phones need no app, account or store.

**Valid is not trusted.** A package is untrusted input even when it validates. Validation reads bytes and checks data; it never executes, imports or evaluates anything from the package, and there are no install hooks or scripts. What a valid package may do is decided by the appliance (grant, tier, sandbox, ADR 0016), never by the package. A package may **request**; it can never **grant**.

## Archive

- ZIP, entries stored or deflated only. `avrgame.json` at the root; everything else under relative paths. The package root becomes the server's working directory, so a Python game ships its importable packages at the root.
- Names: relative, `/` separated, ASCII letters, digits and `. _ + @ = ~ -` only; at most 200 characters and 16 segments; no empty, `.` or `..` segments, no backslash, drive letter or `:`, no NUL or control characters, no segment ending in `.` or a space, no dotfiles, no Windows device names (`CON`, `NUL`, `COM1` ...), no two names differing only by case, no name that is both file and directory.
- Entries must be regular files (or plain directory entries). Symbolic links, devices, FIFOs, sockets, setuid/setgid/sticky bits, encrypted entries and other compression methods are refused. Python bytecode (`*.pyc`, `__pycache__`) is refused: bytecode is not reviewable source.
- Extraction ignores archive modes: files are written 0644, directories 0755, into a **new or empty** directory the caller provides, never following links, and each destination is checked to stay inside it.
- `pack` is deterministic: manifest first, then files sorted by path, timestamps 1980-01-01, mode 0644, no directory entries, deflate level 9 (or stored with `--store`). Same inputs give the same bytes with the same zlib (stored is identical on every platform), so the sha256 is stable. Hidden files, `__pycache__`, `*.pyc` and `avrgame.build.json` are skipped inside directory includes; symbolic links are refused.

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
| `server.args` | 1-16 strings, each 1-200 printable characters, no control characters, no absolute path or `..` (a hygiene check, not a sandbox) |
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
python -m avrana.avrgame pack <path/to/avrgame.build.json> [--out FILE] [--store]
python -m avrana.avrgame inspect <file.avrgame> [--json]
```

Exit 0 success, 1 refused (one problem per line on stderr), 2 usage.

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
| Install, update, remove | `avrana.ops.install_game` (next lane) |

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
