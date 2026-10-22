# Proposal: game artwork and presentation standards

**Status: proposal, for owner decision.** Nothing here is built, merged or deployed. It does not change or freeze the `.avrgame` manifest contract. Linear AVR-37 (freeze), AVR-466 (bundled artwork), Party PR #178 (visualization, draft, "preserved as separate visual research"). Linear was not readable; this rests on repository text at `origin/main`, PR #143 (draft nginx `/party/pkgart/`) and PR #178.

There are two standards. They answer different questions and must not be merged.

| | 1. Platform compatibility | 2. Avrana Featured / Showcase |
|---|---|---|
| Question | Does the package work and stay safe? | Does the game look deliberate on Avrana's shelf and TV? |
| Applies to | Every package, including older ones | Games the owner chooses to feature |
| Enforced by | `check`, `comply`, the Party validator | Owner review, with an optional report |
| Can it fail a package? | Only for malformed art that is present | Never |

## What exists today (cited)

Party `origin/main`, `avrana/avrgame/artwork.py`:
- Optional block, keys `cover`, `icon`, `banner`, `screenshots` (`:24`); any other key is refused, `credit` by name (`:79-83`, owner decision D8).
- Formats WebP, PNG, JPEG, by magic bytes agreeing with the extension; SVG, AVIF, GIF, animated WebP, APNG refused (`:35-38`, `:7`). Remote URLs refused and the file must sit outside `client.root` (`:53`, `:64-67`).
- `cover` square, 256-1024 px, at most 256 KiB (`:26`, `:432-437`). `icon` square, 64-512 px, at most 64 KiB (`:27`). `banner` 16:9 within 2%, 640x360 to 1920x1080, at most 384 KiB (`:28-31`, `:439-444`). `screenshots` up to 5, each `{path, alt}`, `alt` 1-125 characters, aspect 9:16 to 16:9, long side at most 1920, at most 384 KiB (`:19-20`, `:32-33`, `:91-117`, `:446-448`).
- At most 2,097,152 pixels per image (`:17`); 2 MiB total (`:18`, `:490`). A declared file the package lacks is a problem (`:133-136`). EXIF/XMP is a pack-time warning only (`:494-497`).
- Wiring: `manifest.py:186-191`; `archive.py:208,230-239`; `build.py:166-200`.

Appliance and shell:
- `avrana/ops/catalog_overlay.py:135-209` re-reads the staged manifest, re-hashes and re-validates `cover` and `icon` only, adds `images: {cover|icon: {url,w,h}}` to the catalog row, and drops a bad image alone (the game stays listed). Banner and screenshots are validated but not served (D11).
- `web/party/lib/cover-art.js`: ladder owner cover, package cover, package icon, title art, kind icon (list rows prefer icon); a rung that fails to load falls through. The URL shape is pinned to `/party/pkgart/<id>/<16 hex>.<ext>`. Nginx location: PR #143, deploy gated, so today an appliance tile draws its kind icon.
- Fallback: `ui.js:42-46` `kindIcon` (gamepad for emulated, spade for private hands, dice otherwise), drawn with `aria-hidden` (`icons.js:9-17`) beside the visible title. Package art is decorative (`alt=""`, name as adjacent text; `AVRGAME-PACKAGE.md:115`). `tests/offline/covers.spec.ts:90,171` and `cover-art.test.mjs` assert the no-art and failed-image behaviour.
- Games kit: `avrana_gamekit/artwork.py` holds no limits by design; `check`/`comply` confirm the key is allowed and files exist, and note the images were not checked unless `--tools DIR` runs the Party validator (`artwork.py` `NOTE`; `DEVELOPING-A-GAME.md` "Artwork").
- Best Guess is the first-party example of deliberate art, but has no `artwork` block: its mark and `web/icon.svg` are hand-written SVG (`bestguess/art-src/README.md`), which the block would refuse. Its `PROVENANCE.json` records origin, author, licence and SHA-256 per file, and the same file states no generative-AI media.

## Standard 1: platform compatibility

1. **Artwork stays optional.** No block, an empty block, or a package older than the block passes `check`, `comply` and install. An older Party refuses a package that has the block; that is already documented as fail-closed (`AVRGAME-PACKAGE.md:65`).
2. **Generated fallbacks are the contract for no art.** Today that is a kind-icon tile plus the visible title and player range. Requirements to keep, and to add as tests if absent: the name is real text, never only in an image; the icon is `aria-hidden` and carries no meaning the text lacks; the player-range chip is text; nothing is distinguished only by colour. Open item: no test measures the tile's contrast, and the PR #178 findings note the spade misreads on non-card games and that a tile is blank while a picture loads. Both are shell work, each needing its own approval.
3. **When art is present the validator enforces exactly the limits above**, and only those. Failure is correct only for: wrong type or extension mismatch, unreadable or truncated structure, wrong aspect, out-of-range dimensions or bytes, a missing file, a path under `client.root`, a remote URL, a malformed screenshot entry (including missing `alt`), an unknown key.
4. **Alt text:** `screenshots[].alt` is the only author-supplied text. Cover and icon stay decorative.

## Standard 2: Avrana Featured / Showcase

Applied by the owner to games Avrana promotes (first-party titles first). Use only the existing fields:

- `artwork.cover` and `artwork.icon` present (square), `artwork.banner` present for the Home feature and TV (16:9); `artwork.screenshots` optional, never used as a cover.
- Cover: opaque, no title or logo text, one subject in the central 70%, quiet bottom-left quarter (the player chip sits there), readable on the dark shell. Recommended 512 px, WebP.
- Icon: one silhouette that reads at about 48 px, no text.
- Banner: 1280x720, same subject as the cover, no text, subject inside the central square so a square crop survives.
- Mobile shelf legibility: reviewed at the Library sizes (about 76 px row, 90-200 px grid, 343 px feature) on a 375 px phone, dark mode.
- Widescreen/TV: banner reviewed at 1920x1080 at TV distance; no text smaller than the game's own TV text rules.
- Provenance: one record per image (author, origin, licence, source files kept in the repo, tool used, whether generative AI was used), following Best Guess's `PROVENANCE.json`. Never box art or logos without rights.
- Review checklist: the points above plus validator clean, metadata stripped, no baked titles, fallback still sane if the image 404s.
- In mock-ups and review boards, Avrana UI text is Plus Jakarta Sans (owner preference).

Showcase status is a curation decision, not a manifest flag. A community package without it is not lesser for compliance.

## Gaps and additive options

| Gap | Existing field? | Option |
|---|---|---|
| Provenance (who, licence, source) | No: `credit` is refused (D8) | Keep it outside the manifest: a `PROVENANCE.json`-style sidecar in the repo, read only by the report. No new manifest key. |
| Accent colour for loading/no-art tile (#178) | No | Defer. Any new key inside `artwork` is refused by every deployed Party, so it breaks "an artless-compatible package works on an older Party". Only worth it after the freeze decision on additive blocks. |
| Banner/screenshots not served | Fields exist | Shell/nginx step D11; no contract change. |
| Alt for a cover | Not needed | Keep decorative. |

I propose **no manifest extension now**. If the owner wants one later, it must be optional, under `artwork`, and decided with the AVR-37 rule for additive blocks.

## Validation proposal

- **Missing art:** `check` and `comply` print a note ("no artwork declared; the library will draw a placeholder"), exit status unchanged. This replaces nothing the kit does now.
- **Present art:** with `--tools DIR`, malformed art is a failure with the validator's own sentence. Without `--tools`, keep today's note that images were not checked.
- **`--showcase` (optional, never part of default `check`/`comply`, never affects exit status):** a report listing present/absent cover, icon, banner; measured sizes against the recommended ones; whether the sidecar provenance covers every declared file and its SHA-256 matches; a reminder list of the manual items (no text, safe area, TV review). The kit continues to hold none of the numbers; the report takes them from the Party validator.

## Owner decisions

1. Approve two separate standards, with Showcase never a compliance gate?
2. Showcase scope: first-party only, or open to community submissions by request?
3. Provenance: sidecar file convention, no manifest key (recommended), or a future additive key?
4. Accent colour: defer (recommended) or pursue?
5. Is `--showcase` worth building, and in the kit or the Party tools?
6. Order of shell work: banner serving (D11), letterbox fill, loading placeholder, neutral kind icon. Each separately approved.
7. Make first-party art (BLUFF, EXPO, Checkers, Best Guess) now, outside the field-test release? Emulated titles stay with the owner's own covers.
8. Deploy gate for `/party/pkgart/` (PR #143) stays the owner's call.
