# Third-party licensing, SBOM and redistribution policy

- **Status:** **APPROVED policy (owner decision 2026-10-14, AVR-73). The generator exists; the gate does not run in CI yet (Actions unavailable). Commercial distribution and public releases stay gated pending rights verification.** It is an engineering policy and not legal advice: a lawyer must review it before Avrana is sold or distributed outside the owner's own use.
- **Machine-readable part:** [`contracts/third-party.v1.json`](../../contracts/third-party.v1.json) (inventory) and [`tools/sbom.py`](../../tools/sbom.py) (check, SBOM, NOTICE).
- **Not covered:** the Games repository's own inventory (pointer list only, section 7); a legal opinion on any license; signing of releases.

## 1. Why

Avrana is private today. A commercial or public release changes what each dependency allows. This page makes the answer visible per component, so that a license is never discovered at release time. It separates five things that are easy to confuse: what **ships** in Avrana output, what the **owner installs** on their own box, what is only **built with**, what is **referenced for ideas**, and what Avrana may **not** reuse at all.

## 2. Classification

Every component has one `usage` (how it is used now) and one `redistribution` posture (what Avrana may do with it).

| `usage` | Meaning | Typical example |
|---|---|---|
| `embedded` | its bytes are inside a committed output served to the appliance or phones | Plus Jakarta Sans font, compiled Tailwind and daisyUI CSS, Lucide icons, avatars |
| `separate-process` | run as its own process; no linking or embedding | RetroArch |
| `owner-installed` | the owner installs it on their appliance; Avrana does not ship it | libretro cores, ROMs, nginx, Node runtime, Beszel |
| `build-time-only` | used to produce outputs; none of its code is in them | Playwright, `@dicebear/core` |
| `reference-only` | read for ideas; no code, assets or protocol text copied | Sunshine, Moonlight-Web, LocalSend protocol, RAUC |

| `redistribution` | Rule |
|---|---|
| `embed-ok` | may be embedded or linked and redistributed (CC0, MIT-style); the NOTICE still lists it |
| `redistribute-with-notice` | may be redistributed in binary or source if the copyright and license text travel with it (MIT, ISC, OFL-1.1 with `OFL.txt`) |
| `separate-process-only` | copyleft (GPL/LGPL family): only as a separate program, never linked into or embedded in Avrana code; shipping the binary in an image means a source offer |
| `owner-installs-do-not-bundle` | the owner installs it; Avrana does not put it in a release artifact, image or repository |
| `reference-only` | not reusable: copying code, assets or specification text is not allowed. A repository with **no license file grants no rights** and stays reference-only |
| `avoid-commercial-distribution` | the license forbids commercial use or bundling: never in a commercial offering; sets `commercial_blocker` |
| `not-distributed` | build-time; nothing to redistribute |

Owner-installed and shipped are distinguishable by `usage` and by `shipped_in` (`appliance-web`, `phones`, `appliance-system`, `none`). `appliance-system` components are installed on the box by the owner or a documented installer and are never in the repository's committed outputs.

`license_verification` says how a license claim was established: `file-read` (a license file or package metadata in this tree or an installed package was read), `repo-doc` (recorded in a repository document such as [the open-source substrate research](../research/AVRANA-OPEN-SOURCE-SUBSTRATE.md), not re-read from upstream) or `unverified` (the license is recorded as `NOASSERTION`). An unverified component must be resolved before anything is redistributed.

## 3. License-review gate for a new production dependency

A change that adds anything that ships (a committed vendored asset, a runtime npm or Python dependency, a pinned download, a system package in `deploy/appliance-inventory.json`) must in the same pull request:

1. add or update its entry in `contracts/third-party.v1.json` with a license read from the package's own license file (not from memory), the version or pin, and the source;
2. choose `usage` and `redistribution` using section 2, and set `commercial_blocker: true` for anything non-commercial, copyleft-embedded or unlicensed;
3. keep the license text beside any vendored file that requires it (as `web/party/fonts/OFL.txt` does);
4. run `python tools/sbom.py --check`.

Default rules: permissive (MIT, BSD, ISC, Apache-2.0, OFL-1.1 fonts, CC0) is allowed with notice. GPL, LGPL, AGPL, MPL, SSPL, "non-commercial", "no derivatives", "SEE LICENSE" and unlicensed code need an owner decision recorded in the issue before merge. Copyleft code is never copied into Avrana files.

## 4. NOTICE and SBOM

- `python tools/sbom.py --out <dir>` writes `avrana-party.cdx.json` (CycloneDX 1.5) and `NOTICE.txt`. Output is deterministic (no clock; set `SOURCE_DATE_EPOCH` to stamp it), and nothing is written when the check fails.
- `NOTICE.txt` has these sections: shipped in Avrana output (with license text where the file is in the tree), owner-installed, build-time only, reference only, commercial blockers, unverified licenses.
- **Expectation (proposed):** a release candidate carries the SBOM and NOTICE as release artifacts next to the deployment manifest (`docs/design/DEPLOYMENT-MANIFEST.md`), generated from the exact release commit with `node_modules` installed from `package-lock.json`. Until the Pi serves it, the NOTICE is also what an About screen would link to. Neither is wired into CI or the deploy yet: hosted Actions are blocked, so a follow-up adds the step.
- The SBOM lists every `package-lock.json` package (devDependencies with scope `excluded`) and every inventory component except reference-only ones. Owner-installed components have scope `optional`.

## 5. What `--check` enforces

Fails when: the inventory breaks its schema or has a component without a license; a directory under `assets/vendor/` or `web/party/fonts` is not claimed by any component; a production npm dependency, a third-party Python import in a shipped tree (`avrana`, `arcade`, `ps1`, `portal`, `ops`, `telemetry`, `deploy`, root scripts) or a package in `deploy/appliance-inventory.json` is missing; a declared path no longer exists. It warns about unverified licenses, commercial blockers and the undecided first-party license. It cannot see a font copied outside those directories, an image, or a download made by a shell script; those still rely on the gate in section 3.

## 6. Known commercial blockers

| Component | Why | Today's posture | Resolution options |
|---|---|---|---|
| MAME 2010 libretro core | non-commercial license (repo-doc) | owner-installed, never committed | different core, license, or no commercial emulation offer |
| FinalBurn Neo core | non-commercial license (repo-doc) | owner-installed, never committed | same |
| ROMs and PS1 BIOS | Avrana has no license to them | owner-supplied | never pre-load; owner brings their own |
| LocalSend protocol | the protocol repository has no LICENSE file (repo-doc) | reference-only | write our own protocol text; ask upstream for a license |
| Avrana's own license | decided 2026-10-14: all rights reserved (`LICENSE`, `package.json` UNLICENSED); deliberately published SDK components get a permissive license when published | resolved for the repository | pick the exact permissive license per SDK component at its first publication, after ownership and third-party checks |
| python-chess (Games repo) | GPL-3.0-or-later, runtime dependency of chess games | installed from PyPI, not bundled | replace it, or run chess as a separate process; Games follow-up |

Copyleft items that are **not** blockers while Avrana keeps the process boundary: RetroArch (GPL-3.0) and PCSX-ReARMed (GPL-2.0) run as a separate process and are owner-installed; an image that includes them would need a source offer. Moonlight-Web, Sunshine, InputPlumber (GPL-3.0) and openNDS (GPL-2.0) are reference-only; Selkies (MPL-2.0, but its published wheels are GPL) is a candidate only; RAUC (LGPL-2.1) is a reference candidate that would be acceptable as a separate process.

## 7. Games repository

Games is a separate repository with its own runtime dependencies and bundled assets. `games_repo_pointer` in the inventory lists what its `NOTICE.md` and `requirements.txt` on `origin/main` record (FastAPI, Uvicorn, websockets, Pillow, python-chess, Sora and JetBrains Mono fonts, colyseus-tanks upstream). Follow-up: give Games an inventory in this schema and run the same check there; verify the bundled tank textures and `games/bluff/art/kenney`.

## 8. Not yet verified

Licenses recorded as `NOASSERTION` (14 components at the time of writing, run `--check` for the live list): the Debian packages (nginx, NetworkManager, Avahi, Python, system tools, FFmpeg, PulseAudio, Xvfb, MAME, aiohttp, evdev, PyGObject), the Node.js tarball, the Beszel agent, Playwright and its siblings, and owner-supplied content. Debian copyright files and the Node tarball `LICENSE` were not available in this repository and were not read. The `repo-doc` claims were read from the 2026-09-26 research document, not re-checked upstream.

## 9. Owner decisions (2026-10-14)

1. The classification vocabulary (section 2) and the new-dependency gate (section 3) are approved.
2. Proprietary Party Core code is all rights reserved where legally permissible (`LICENSE`). Deliberately published SDK components use a permissive license, subject to ownership and third-party obligations; the exact license is chosen per component at publication.
3. Commercial distribution and public releases stay gated pending rights verification; the blockers in section 6 stand until then.
4. Running `tools/sbom.py --check` in CI waits for GitHub Actions to be available (no spending changes).
