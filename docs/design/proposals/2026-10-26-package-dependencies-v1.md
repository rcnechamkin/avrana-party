# Package dependencies for `.avrgame` v1: self-contained packages, platform runtimes only (AVR-77)

- **Status:** proposal, 2026-10-26. Nothing is implemented, and nothing changes: this writes down the rule
  the format and installer already follow and proposes keeping it for v1. **Owner decisions are required**
  (section 6).
- **Reads with:** [GAME-INSTALLATION.md](../GAME-INSTALLATION.md) ("Dependencies"),
  [AVRGAME-PACKAGE.md](../AVRGAME-PACKAGE.md) ("Runtimes", `server.interpreter`),
  [APPLIANCE-CONTENT-DELIVERY.md](../APPLIANCE-CONTENT-DELIVERY.md) (content packs), `avrana/avrgame/manifest.py`
  (`INTERPRETERS`, `OPTIONAL_RUNTIMES`), `avrana/avrgame/node_pin.py`.

## 1. What is true today

| Fact | Source |
|---|---|
| No package manager runs at install time: no pip, npm or build step on the Pi | GAME-INSTALLATION.md "Dependencies"; the installer only reads and hashes bytes (AVR-39) |
| A game may use the standard library, a platform-pinned runtime, vendored pure-Python or pure-JS code, or a static aarch64 binary | same |
| `server.interpreter` is a **name** from the appliance's allowlist: `python3` (the OS Python) or `node` (the appliance's pinned Node build, optional). Never a path. A package that names a missing optional runtime is refused. | `manifest.py` `INTERPRETERS`, `OPTIONAL_RUNTIMES` |
| Node's version and tarball SHA-256 are pinned by the appliance, and a package cannot choose them | `node_pin.py` |
| The kit, the session protocol, the result code and the bridge are **vendored into each package** (Courting's archive holds `avrana_gamekit/`, `core/party_protocol.py`, `web/avrana-party-bridge.js`) | e.g. `inspect courting-0.1.0.avrgame` |
| A content pack ships **inside** its game's package (parts addressed by SHA-256) | games#81 (draft), APPLIANCE-CONTENT-DELIVERY.md |
| Each installed package is staged in its own tree, `/opt/avrana-games/<id>/<version>-<sha12>`, and nothing is shared between packages | AVRGAME-PACKAGE.md "Install lifecycle" |

In short: **there are no inter-package dependencies today, by construction.**

## 2. Proposal: keep it that way for v1

**P1. Dependencies between packages are prohibited in v1.** A package must contain everything it runs or serves,
except the runtime it names in `server.interpreter`. There is no `depends` field, and adding one is refused like
any other unknown key (strict JSON).

**P2. The platform provides runtimes, and nothing else.**
- The only shared things are the runtimes in `INTERPRETERS` and the Party's own protocol endpoints.
- A runtime is versioned and pinned by the appliance.
- A package can only say which one, and only through `requires` (protocol versions) and, later, `platform` (AVR-58
  §9, for example `{"node": "22"}`). That later field is checked, never resolved.

**P3. Vendoring is the supported way to share code.**
- The kit and the vendored Party files are copied in at build time by the kit's build. That is deterministic, and
  the package's own SHA-256 covers them.
- Two packages may carry different kit versions side by side without conflict.
- The cost is size: about 200 KB of kit per package, small next to content.

**P4. Content packs belong to their game.** A pack is part of the package that declares it (games#81). A pack
shared by several games is a v2 question (section 5), not a v1 feature.

**P5. Global installs.** Only the owner or the appliance installs anything global (a runtime, through
`install-node-runtime`). A package never causes a global install, and a package's removal never touches one.

## 3. How this meets each AVR-77 exit criterion

| Exit criterion | Answer in v1 |
|---|---|
| Dependency model explicit, or prohibited | **prohibited** between packages (P1); runtimes by name only (P2) |
| Resolution deterministic, fails closed | nothing to resolve. A missing runtime or unsupported `requires` refuses the install (exists today). |
| Offline bundle and import strategy | a package **is** the bundle (P3, P4); offline install already works (AVR-39) |
| Rollback and removal preserve other packages | each package has its own staged tree; removing or rolling back one cannot touch another (P1, P5; AVR-58 §5 for rollback) |
| Shared dependency ownership and update | only runtimes are shared. The appliance owns them, and a runtime update follows the AVR-72 window: an installed package outside it is shown as needing an update and is not launched. |

## 4. Consequences

- **Security:** one community game cannot replace another's dependency, because none are shared (an AVR-77
  constraint met by construction).
- **Updates:** a kit security fix reaches a game only when that game is re-packed and re-installed. The AVR-72
  deprecation warnings (on install and in `comply`) are how an old vendored kit becomes visible. `comply` already
  checks the vendored files against the kit's declaration.
- **Size:** each package carries its own copy of the kit and bridge. That is acceptable at today's sizes.

## 5. What would justify dependencies later (v2, not now)

- Several large games sharing one content pack (for example, a shared asset library) where duplication costs real
  SD-card space. The model would then be a content-only package, addressed by SHA-256, read-only, with no code,
  reference-counted by the installer.
- A shared runtime beyond Python and Node (for example a WASM runtime on the server), added to `INTERPRETERS` by the
  platform, never by a package.

In both cases: no resolver on the Pi, exact SHA-256 references only (no version ranges), and a removal that refuses
while another package still references the item.

## 6. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Prohibit inter-package dependencies in v1? | yes; allow content-only shared packs now | **yes** |
| D2 | Keep vendoring the kit into every package? | yes; ship the kit as a platform runtime | **yes for v1**: it keeps kit versions independent of Party releases, and it is what exists |
| D3 | Revisit when? | first shared-content request; never | **at the first real request for shared content**, with the v2 rules of section 5 |

## 7. Tests (none needed for v1 beyond what exists)

The rule is already enforced:
- unknown manifest keys are refused (`ManifestTests`);
- a missing runtime is refused (`OPTIONAL_RUNTIMES`);
- staging is per package (`install_rehearsal.py`).

If D1 is accepted, one test could assert that `depends`, `dependencies` and `requires.packages` are refused with a
message pointing to this note.
