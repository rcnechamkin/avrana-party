# Source, IP and disclosure inventory (AVR-420, read-only audit)

Dated evidence, observed 2026-10-14 (UTC). Historical observation, not a policy, not a decision and
**not legal advice**. **Nothing was changed on GitHub or in any audited repository to produce it**: no
visibility, setting, history, release or artifact was touched. Sections 7 and 8 are PROPOSALS for the
owner; nothing here is accepted. Third-party licence detail belongs to AVR-73.

## 1. Scope and method

Owner `rcnechamkin`. Scanned in depth: `avrana-party` (Party), `avrana-party-games` (Games) and
`avrana-party-docs` (Docs). The other repositories were inventoried only.

| Step | Command (all read-only) |
|---|---|
| Inventory | `gh repo list rcnechamkin --limit 100 --json name,visibility,isFork,licenseInfo,createdAt,pushedAt,description` |
| Per-repo facts | `gh api repos/rcnechamkin/<r>` (private, fork, forks_count, license), `.../forks`, `gh release list -R`, `.../actions/artifacts` |
| Authors | `git shortlog -sn --all --no-merges`; `git log --all --format=%ae` grouped by domain only; `gh api .../contributors` |
| Remote refs | `git ls-remote origin` (counts by namespace); `git clone --mirror` into a scratch directory to include `refs/pull/*` |
| Licences | `git ls-tree` for LICENSE/NOTICE/OFL files; `git log --all -- <path>`; Games read from `origin/main` (the local checkout is on a stale branch) |
| Secret scan | A small Python filter over `git log --all -p -U0 --text`, added lines only: `BEGIN .*PRIVATE KEY`, `gh[pousr]_`, `github_pat_`, `AKIA[0-9A-Z]{16}`, `xox[bpas]-`, `sk-[A-Za-z0-9_-]{20,}`, `lin_api_`, and `password/secret/token/api_key` assignments with a non-placeholder literal. Matches were classified by file; values were never printed into this document |
| Artifact scan | `git log --all --diff-filter=A --name-only` filtered for key, certificate, archive, ROM, disc-image, bundle, database, `.env`, `.avrgame` and PDF extensions; `git rev-list --objects --all` for blobs over 1 MB, on both the local clone and the mirror |

Limits: GitHub does not expose visibility history, so "was ever public" is stated from the issue, not
verified. A pattern scan is not proof of absence. The Docs repository was scanned from a local clone
(4 commits behind `origin/main` at the time; fetched, not merged). Git history is not mined for
copyright headers: only 9 tracked Party files carry any copyright or SPDX text (fonts, icons, notices).

## 2. Repository visibility and licence matrix

All counts at 2026-10-14. Forks of each repository: 0. Releases: none, in every repository listed.

| Repository | Visibility now | Licence file | Public before? | Actions artifacts | Notes |
|---|---|---|---|---|---|
| avrana-party | Private | none (all rights reserved by default) | yes (issue) | 50 | created 2026-09-19 |
| avrana-party-games | Private | MIT, `Copyright (c) 2026 BEACNpool` (upstream's, unchanged) | yes (issue) | 25 | created 2026-09-26; a **fork of third-party LAN Games**, but GitHub reports it as a detached copy (`isFork: false`) |
| avrana-party-docs | **Public** | none | yes | 0 | created 2026-10-09; no licence means all rights reserved, viewable but not reusable |
| avrana | Private | none | unknown | 0 | created 2025-06-12 |
| avrana-game | Private | none | unknown (issue says now private) | 0 | created 2026-09-29; "independent of Avrana Party" |
| avranawebportal | Private | Apache-2.0 | unknown (issue says now private) | 0 | created 2026-08-20 |
| OpenCE | **Public** | CC0-1.0 (inherited) | n/a | 0 | **fork** of a third-party Halo port; see section 8 |
| agent-watch, AI-workflow | Public | none | n/a | 0 | not audited |
| Kern-Ecosystem, UniFi-Migration-Strategy, Wireless-Migration-Strategy, Fortinet-Lab-Suite, Network-Ops-Lab-Suite | Private | none | not Avrana | 0 | not audited |

GitHub Actions artifacts (Party and Games, none expired): Party holds `package-browser-results`,
`graphify-architecture-*` and `reconcile-report-*`; Games holds `graphify-architecture-*`. While a
repository is public, artifacts of public repositories are downloadable by any signed-in GitHub user, so
anything inside them should be treated as disclosed. Their contents were **not downloaded or inspected**
(see section 9).

Remote refs: Party has 111 branches and 136 `refs/pull/*`; Games has 70 branches and 72 `refs/pull/*`.
`refs/pull/*` of a repository that was public may have been fetched by third parties and persists even
after a branch is deleted.

## 3. Contributors and rights

| Repository | Commits (non-merge) | Distinct author names | Non-owner humans | AI / bots |
|---|---|---|---|---|
| avrana-party | 576 | 4 | none found | `Claude` 28; one author named "Avrana Experiment" (1 commit) |
| avrana-party-games | 310 | 5 | **yes: `BEACNpool`, 43 commits** (49 in `--all` including branches), GitHub's contributors list also shows `BEACNLabs` (12), possibly the same party | `Claude` 5; "Avrana Experiment" 2 |
| avrana-party-docs | 17 | 3 | none found | `Claude` 13 |

Owner names appear under three spellings (`rcnechamkin`, `Robert Cody Nechamkin`, one local-domain
identity), counted as one person. Author-email domains were checked only by domain: Party 735 gmail,
30 anthropic.com, 1 local; Docs 13 anthropic.com, 9 gmail.

Findings:

1. **Games' first commit (2026-07-17, "Initial release: LAN Games") is by BEACNpool**, who also wrote the
   LICENSE. Everything from that snapshot is third-party code under MIT (`NOTICE.md` says so). The
   BEACNpool commits are the upstream history carried over (single-tenant `core/`, `web/`, `games/`,
   `tests/`) and include one 21.6 MB marketing video (`2026-07-17_LAN-GAMES_explainer_web.mp4`) that
   is still in the tree. Whether BEACNpool is one person or a team, and whether the author identity maps to
   the licence holder, is not established here.
2. The `NOTICE.md` also carries two further obligations: a CC BY 4.0 tank model by Firewarden3D and MIT
   code by Endel Dreyer and Maksims Mihejevs (Colyseus Tanks demo). Neither has been checked against
   upstream by this audit.
3. AI-assisted authorship: ownership of AI-generated output is jurisdiction-dependent and is a legal question
   (section 9). Anthropic's terms were not reviewed here.
4. Docs and Party have no non-owner human authors, but there is no contributor licence agreement, no
   DCO and no recorded external contributions policy in either repository.

## 4. Third-party and vendored material (pointers; AVR-73 has the detail)

| Where | What | Licence per local file | Bundled? |
|---|---|---|---|
| Party `assets/vendor/kenney-board-game-icons/` | Kenney Board Game Icons 1.1 | Kenney licence text present (`License.txt`) | yes |
| Party `assets/vendor/lan-games-art/` | 30 SVG game icons from LAN Games | MIT (upstream); attribution in `docs/references/LAN-GAMES-NOTICE.md`. The notice states that no donor asset is bundled, which conflicts with this directory; re-check | yes |
| Party `web/party/fonts/`, `docs/design/.../fonts/` | Geist variable font | OFL file present in `web/party/fonts` | yes |
| Party `arcade/` | RetroArch config, MAME 2010 libretro core named (not tracked), ROM path git-ignored (`arcade/roms/*`, `*.zip`) | core and ROM terms are not in the repo | binaries and ROMs not tracked |
| Party `tools/avrgame-tools/NOTICE.md.in` | Template for a **public SDK export**; states it is a factual statement, not a licence grant | none granted | export only, nothing published |
| Games `web/fonts/`, `games/wordclash/web/fonts/` | Sora and JetBrains Mono | OFL texts beside each copy | yes |
| Games `games/bluff/art/kenney/` | Kenney art | `License.txt` | yes |
| Games `colyseus-tanks/upstream/` | Colyseus Realtime Tanks Demo, Pixel Tank model | MIT; CC BY 4.0 | yes (also `pixelTank.fbx`) |
| Games `checkers/` | Rules adapted from LAN Games' engine | MIT, attributed | yes |
| Games runtime deps | python-chess (GPL-3.0-or-later) | installed from PyPI, not bundled; **an obligation if Games ever ships a combined distribution** | no |
| Docs | none vendored (a favicon and CSS only) | n/a | n/a |

No `.zip`, `.chd`, `.iso`, `.cue`, console ROM, `.avrgame`, `.pem`, `.key`, `.p12`, `.env` or `.sqlite`
file was ever added in the three repositories (checked on `--all`, and on the GitHub mirror for
Party and Games).

## 5. Hazard scan results

| Class | Result |
|---|---|
| Private keys, `ghp_`, `github_pat_`, `AKIA`, `xox`, `sk-`, `lin_api_` | **No real hit** in Party, Games or Docs. One literal `-----BEGIN PRIVATE KEY-----` appears in two commits of Party's `tests/unit/test_avrgame_tools_export.py`: it is a forbidden-string list used to assert the SDK export contains no key. A fixture |
| `password/secret/token/api_key =` literals | About 25 Party and 45 Games files match, almost all code that handles a token (variable names, function arguments, test setup). Spot-checked: signed `aps0.` session tickets in `contracts/vectors/party-session.v0.json` and `tests/vectors/party-session.v0.json` use fixed timestamps (year 2033) and repeated-digit ids, so they are test vectors; a README example Wi-Fi block uses a placeholder value ("hunter2"); `deploy/appliance-inventory.json` only lists `secret:` requirement names. No literal credential was found |
| Network details in public Docs | Docs mentions no private IP address; one file mentions SSID in prose. Party's private `docs/findings/` do record the appliance management address and topology, now private only |
| Binary / large blobs | Party: largest blob 1.4 MB (a power-measurement `.jsonl`). Games: the 21.6 MB upstream video |
| Commercial content | Games has **no** commercial artwork on any remote ref. A **local-only** git ref (`refs/codex/turn-diffs/checkpoints/...`, a Codex agent working-tree snapshot) in the local Games clone contains a 26.5 MB `avr23-games.bundle` and the "The Crew II" publisher box images, rules PDF and 3D box render (about 9 MB), none of which exist on GitHub (`git ls-remote` shows only `refs/heads/*` and `refs/pull/*`; the mirror contains none of it). It was **not removed**; the owner should decide whether to delete that local ref. Party's clone has one local codex ref too, with no flagged content |
| Actions artifacts | Listed only; not downloaded. See section 9 |
| Real secret / signing key / token | **none found by this scan** |

## 6. Component classification

Classes: **A** public spec, SDK or example; **B** deliberate open source; **C** proprietary platform
candidate; **D** commercial or licensed content; **E** third-party obligation; **S** secret (none).

| Component | Repository | Class | Basis |
|---|---|---|---|
| Docs site (explanations of architecture and decisions) | Docs | A (presentation only) | public today, no licence |
| Contracts and vectors (`contracts/`, `contracts/vectors`) | Party | A candidate | spec-like; Games already mirrors them |
| `.avrgame` package format and tools (`avrana/avrgame`, `tools/avrgame-tools`) | Party | A candidate | experimental, export template exists, not frozen |
| `avrana_gamekit`, `hello_party`, conformance harness | Games | A candidate | SDK and example intent |
| Party Core, identity, sessions, navigation, ops, deploy, provider glue | Party | C | the platform; no licence granted |
| Party web shell and UX design | Party | C | owner's design; design fonts are E |
| Native games (BLUFF, EXPO, Checkers port, Diplomacy etc.) | Games | C (own code), E where derived | MIT inherited for all Games files, unless re-licensed per file |
| LAN Games derived code, catalog, icons, video | Games and Party | B / E | upstream MIT; must keep BEACNpool notice |
| Colyseus Tanks, Pixel Tank model | Games | E | MIT + CC BY 4.0 attribution |
| Kenney icons and art, Sora, JetBrains Mono, Geist | both | E | attribution or OFL terms |
| RetroArch / MAME cores, ROMs, PS1 titles | Party (config only) | D | not tracked; third-party and commercial terms; ROMs git-ignored |
| "The Crew II" assets | local-only ref | D | publisher content; not on GitHub |
| Operational facts (IP, topology, Linear details, Pi evidence) | Party | C (private) | not for public repos |
| Stand-alone `avrana`, `avrana-game`, `avranawebportal` | other | not audited | separate repos |

## 7. Proposed public-versus-proprietary boundary (PROPOSAL; owner decides)

1. **Keep private by default**: Party, Games, and the three stand-alone repositories. Publish nothing
   by repository visibility; publish by deliberate **export** (the AVR-68/SDK export is the model).
2. **Public candidates, each needing an explicit licence and a clean-room check**: the contract and
   vector schemas, the `.avrgame` format document, gamekit and `hello_party` example, and the Docs
   site. Pick one licence for the specification (for example a permissive code licence for SDK code and
   a separate text licence for documents), decided by the owner.
3. **Games needs a licence decision before any export**: its tree is MIT by inheritance. Owner-written
   code can be offered under other terms only if per-file ownership is recorded; the safest path is to
   keep the MIT notice and publish only new, owner-written examples.
4. **Never export**: operational data, deploy scripts with host details, Pi evidence, internal issue
   references, ROMs and cores, commercial board-game material, anything carrying a third-party licence
   not yet reviewed under AVR-73.
5. **Docs**: add a licence file (or an explicit all-rights-reserved notice) so the public repository is
   not ambiguous.
6. **Disclosure rule**: anything that was in a public repository is treated as disclosed for ever;
   privacy changes and history rewrites do not reverse this. Only secrets would justify rotation.

## 8. Open questions for the owner and counsel (checklist)

- [ ] Does BEACNpool consent to (or is any further action needed for) publishing a derivative under
      MIT? The MIT notice already permits it; confirm no separate agreement or trademark use exists.
- [ ] Is BEACNpool the same person as BEACNLabs, and is that identity the copyright holder?
- [ ] Does Party's `assets/vendor/lan-games-art` need an updated notice, since the notice says no
      donor asset is bundled?
- [ ] Which licence should Party, Docs and any exported SDK carry? Is "all rights reserved" intended?
- [ ] AI-generated code: who owns it and how is it recorded? Is a contributor policy needed?
- [ ] Who owns the trademark and name "Avrana" (domain `avrana.net` appears in Party docs)?
- [ ] Games' MIT notice credits "Avrana Party Games" as a copyright holder; is that name the owner or a
      separate legal entity?
- [ ] Colyseus Tanks: confirm Pixel Tank model attribution (CC BY 4.0) against its Sketchfab page
      before any public release.
- [ ] Public repository `OpenCE` (fork of a Halo: Combat Evolved port) and Games branch
      `exp/opence-avrana-poc` ("experimental opence Avrana Party PoC"): is this repository intended to be
      public, and does the project use game-derived assets? Game assets of a commercial title are
      copyrighted and are not covered by the repository's CC0 label. The audit looked only at metadata.
- [ ] Decide whether to delete the local-only `refs/codex/...` snapshot in the Games clone (not done here).
- [ ] Review Actions artifacts of Party and Games (may include graphs of internal architecture);
      decide on deletion/expiry.
- [ ] Which of `avrana`, `avrana-game`, `avranawebportal` was ever public, and does it hold secrets?

## 9. Follow-up tasks (proposed)

1. Owner: answer section 8; accept or change section 7.
2. AVR-73: third-party licence review (Kenney, Geist, Sora, JetBrains Mono, Colyseus Tanks, Firewarden3D
   model, python-chess, MAME cores); fix the LAN-Games-art notice contradiction.
3. Add LICENSE or an explicit notice to Docs; add a short `docs/` licence/disclosure policy in Party
   once the owner has decided.
4. Download and inspect the Actions artifacts (by a person with read access) and expire them if needed.
5. Scan the three stand-alone repositories and `agent-watch` / `AI-workflow` / `OpenCE` for secrets
   and licence status; not in this audit's scope.
6. Add a CI secret-scan and a "no licensed content" check to the export tool before any SDK release.
7. Write down contributor policy (DCO or none) before accepting external contributions.

## 10. Follow-up 2026-10-14

Same guardrails as above: read-only toward GitHub, no values of any match written down. Mirror clones
(`git clone --mirror`) of the three stand-alone repositories were made in a scratch directory, scanned
with the section 1 patterns over all refs and added lines, then deleted. Nothing was changed on GitHub.

### 10.1 Remaining repositories

| | `avrana` | `avrana-game` | `avranawebportal` |
|---|---|---|---|
| Visibility / created | Private, 2025-06-12 | Private, 2026-09-29 | Private, 2026-08-20 |
| Refs scanned | 10 branches, 18 PR refs, 78 commits | 1 branch, 2 commits | 1 branch, 5 commits |
| Licence file history | none at the root; `services/avrana-audible-connector/companion/LICENSES/README.md` (instructions only) | none | `LICENSE` (Apache-2.0) |
| Distinct human authors | 1 (owner) | 1 (owner) | 1 (owner, two spellings) |
| Bots | `Claude` 3 commits | none | none |
| Vendored third-party dirs | none (no `vendor`, `node_modules`, `dist`) | none | none |
| Largest blob | under 0.5 MB | under 0.5 MB | under 0.5 MB |
| ROM, disc image, key, certificate, database, archive, `.avrgame` ever added | none | none | none |
| `.env` files | thirteen `.env.example` files only (no real `.env`) | none | none |

Pattern hits, all classified as **fixtures or code, not secrets**. `avrana` is the only repository with
hits (5 file/commit pairs; `avrana-game` and `avranawebportal`: 0):

| Path (all in `avrana`) | Pattern | Verdict |
|---|---|---|
| `scripts/review_git_content.py` | `github_pat_` | a detection regex inside a review script; fixture |
| `deploy/homepage/config/services.yaml` | password assignment | a templated placeholder (contains a template expression, not a literal); fixture |
| `services/avrana-home/tests/test_jellyfin_adapter.py` | key assignment | test constant; fixture |
| `services/avrana-home/tests/test_mutations.py` | `SECRET =` | test constant (27 characters, self-describing); fixture |
| `services/avrana-imax-verify/tests/test_server.py` | webhook user and password | short test strings assigned to the module under test; fixture |

No private key header, `ghp_`/`gho_`/`github_pat_` token, `AKIA` id, `xox` token, `sk-` key or `lin_api_`
token was found in any of the three. Licence observations:

- `avrana` has no root licence (all rights reserved by default). Its audible connector README says the
  companion image redistributes unmodified `rmcrackan/libation` layers (GPL-3.0) and that the GPL text
  `Libation-GPL-3.0.txt` must be fetched and committed before the image is distributed. That file is not
  in the tree. This is an obligation, not a secret; it matters only if that image is distributed.
- `avranawebportal` is Apache-2.0 with a single human author; `avrana-game` has no licence file.
- "Was ever public" remains unknown for all three (GitHub does not expose visibility history).

**PRIVATE ESCALATION: none.**

### 10.2 GitHub Actions artifacts (metadata only, nothing downloaded)

`gh api repos/rcnechamkin/<repo>/actions/artifacts --paginate`. Observed 2026-10-14. All 75 are unexpired.
The repository retention setting reads 90 days (maximum allowed 400), but the earliest expiry observed is
2026-10-14 and the latest 2026-12-04 (Party) and 2026-10-20 (Games), so the workflows set shorter retention.

| Repository | Artifact name | Count | Total size | Could it hold secrets or runtime state? |
|---|---|---|---|---|
| Party | `graphify-architecture-<run>` | 39 | 15.0 MB | low: code-structure graph of the repository; may expose internal architecture and file names, no runtime data |
| Party | `package-browser-results` | 8 | 6.0 MB | **highest of the set**: a Playwright results bundle. Traces, videos and screenshots can embed request headers, cookies and `localStorage` of the tested page. The test target is a locally started app with fixed test identities, so a real credential is unlikely, but the contents should be inspected once by the owner |
| Party | `avrgame-tools-export` | 2 | 69 KB | low: the SDK export bundle; by design contains no operational data |
| Party | `reconcile-report-<run>` | 1 | 4 KB | low: a text report of repository/Linear reconciliation; may name internal issues |
| Games | `graphify-architecture-<run>` | 25 | 14.3 MB | low: same as Party's graphify output |

While a repository is private, only users with read access can download artifacts. Both repositories were
public earlier; artifacts created while public would have been downloadable by any signed-in GitHub
user, but all observed artifacts were created from 2026-10-05 on and visibility during that window
is not established here. Nothing was deleted or expired. Proposal for the owner: shorten retention for
`package-browser-results`, and inspect one before deciding whether it needs expiring.

### 10.3 LAN Games artwork notice (fixed in this change)

`docs/references/LAN-GAMES-NOTICE.md` said no donor image or runtime asset is bundled, while
`assets/vendor/lan-games-art/` holds 30 donor SVG scenes. Provenance from the repositories:

- The SVGs are exported by `ops/export_game_art.mjs` (Games, added by the owner 2026-09-28) from
  `web/gameart.js`. That file was written by BEACNpool (LAN Games, 2026-07-26, two commits).
- The only later change to it is the owner's `ff0c9b0` (2026-09-28), which adds the BLUFF scene:
  12 added lines, 0 removed. So 29 of the 30 scenes are unmodified upstream drawings and `bluff.svg` is
  Avrana-authored.
- Licence: LAN Games `LICENSE` (MIT, `Copyright (c) 2026 BEACNpool`), carried by the Games fork and
  reproduced in the notice.

Changes: the notice now states that artwork is bundled and how many are upstream, keeps the copyright line
and full MIT text in the same file; `assets/vendor/README.md` no longer calls the artwork "first-party";
`contracts/third-party.v1.json` entry `lan-games-art` is renamed and its note and licence source corrected
(licence stays MIT, `redistribution` unchanged). `python tools/sbom.py --check` passes. Section 4 and 8 above
are left as written (dated observations); this section supersedes the contradiction they record. Not
done: the Colyseus Tanks and Kenney items in section 9 task 2 remain AVR-73's.
