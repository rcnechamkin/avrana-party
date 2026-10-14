# Generated files: change the source, then regenerate

**Do not hand-edit generated outputs.** Paths below are repository-relative. The same mapping
is machine-readable in [manifest.json](manifest.json); it describes provenance, not product state.
Use the committed npm lockfile (`npm ci`). UI generation runs on a development machine, never the Pi.

| Generated output | Authoritative source | Regenerate | Freshness check |
|---|---|---|---|
| `web/party/styles.css` | `web/src/party.css`, its explicit `@source` HTML/JS, locked Tailwind/daisyUI | `npm run build:css` | `npm run check:ui` |
| `web/party/lib/icons.js` | `tools/build-icons.mjs`, locked `lucide-static` | `npm run build:icons` | `node tools/build-icons.mjs --check` |
| `web/party/avatars/*.svg`, `web/party/lib/avatars.js` | `tools/build-avatars.mjs`, locked DiceBear | `npm run build:avatars` | `node tools/build-avatars.mjs --check` |
| `web/party/art/*.svg` | `contracts/artwork.json`, `assets/vendor/`, `tools/build-art.mjs` | `npm run build:art` | `node tools/build-art.mjs --check` |
| `web/party/catalog.json` | `contracts/` game/appliance/vocabulary/artwork and imported LAN catalog, `avrana/contracts/` | `python3 -m avrana.contracts.catalog` | same command with `--check` |
| `contracts/catalogs/lan-games.json` | Games registry/exporter in the separate Games repo | In Games: `python ops/export_avrana_catalog.py --out ../avrana-party/contracts/catalogs/lan-games.json` | In Games: `python ops/export_avrana_catalog.py --check ../avrana-party/contracts/catalogs/lan-games.json` |
| `assets/vendor/lan-games-art/*.svg` | Games `web/gameart.js`, `provider/catalog.json`, exporter | In Games: `node ops/export_game_art.mjs ../avrana-party/assets/vendor/lan-games-art` | same command with `--check` |

Confirm the exporter CLI in the selected Games revision before refreshing an imported snapshot.
One generated artifact is not in the repository: the appliance-local effective catalog
`/var/lib/avrana-party/catalog/catalog.json` (experimental, [AVRGAME-PACKAGE](design/AVRGAME-PACKAGE.md)), written by
`python3 -m avrana.ops.catalog_overlay refresh` from the release's `catalog.json` and the install records.
See [asset provenance](../assets/vendor/README.md), [provider design](design/LAN-GAMES-PROVIDER.md)
and [cross-repo testing](TESTING.md#lan-games-provider-cross-repository-tests).
The public offline lane validates the committed snapshots and downstream outputs, but cannot
prove freshness against a private Games checkout it does not have. No credentials are added to CI.

`npm run build:ui` regenerates all UI outputs. `npm run check:repo` composes `check:ui` and catalog
freshness without changing source. `.gitattributes` marks outputs as generated and vendor assets
as vendored for GitHub; existing byte/line-ending rules remain unchanged.

`web/party/` also contains hand-authored HTML/JS, including `sw.js`; only the listed paths are
generated. `python3 -m avrana.web.build --out <temporary-directory>` copies the shell, stamps
the service worker and creates `version.json` for a release. That output, test reports, dependency
caches, installer backups and runtime data are not committed source. A local build is not a deploy.

## Derived Graphify context

[Graphify](GRAPHIFY.md) lists source scopes and exact commands. `graphify-public/`, `graphify-out/`
and `.graphify-context/` are ignored derived products; Linear exports are private and never uploaded.
Optional `context/graphify/semantic-graph.json` and `semantic-receipt.json` are generated together
by interactive host-agent extraction plus `accept-semantic`; never hand-edit them.
`check-semantic` flags stale docs, while `status` verifies AST hashes and Linear TTL where applicable.
No Graphify product is authoritative. These optional/ignored outputs are not required by the
manifest's product-build provenance mappings; their metadata is checked by the shared toolkit.
