# Proposal: declarative game options chosen by the Host (AVR-678)

- **Status:** PROPOSAL, for owner review. Nothing is built; the launch protocol is not changed by this document.
- **Reads with:** [ADR 0006](../../adr/0006-party-session-protocol.md), [ADR 0010](../../adr/0010-party-pregame.md), [ADR 0011](../../adr/0011-party-console-model.md), [Hearts findings](../../findings/2026-10-20-sdk-clean-room-hearts.md) (direction 2).
- **Evidence:** Hearts r1 G-11 and r2 G05: the donor offered a target of 50 or 100, bot difficulty and a turn clock; the Party game could offer none (Games `experiments/avr-676-hearts/r2/records/GAPS.md` G05, `DECISIONS.md` D7).

## 1. Today

- A launch carries a roster and nothing else: `launch_message` writes `roster` and a `nonce` (`avrana/party/protocol.py:359-370`), and the game's check accepts only `{participant, name, role}` entries (Games `core/party_protocol.py:490-497`).
- The Python kit hands a game only that roster: `PartySide.launch` returns it (Games `avrana_gamekit/party.py:74-77`), and `new_session(roster)` is the game's one entry (`avrana_gamekit/app.py:249-253`). The Node kit is the same (`js/game-app.mjs:304-311`).
- The Party's setup scene collects one thing, Play or Watch (`avrana/party/core.py:616-633`; routes `service.py:23-25`).
- The validator for the `net.avrana.party` extension allows exactly one key, `pregame` (`avrana/contracts/party_config.py:31,50-53`).

## 2. Where to declare: `extensions."net.avrana.party".options`

The Game Contract v0 is frozen: "a new field needs a new schema version. Extensions go in `extensions`" (`contracts/README.md:29`). `pregame` already took that route for the same reason (`contracts/README.md:88`). The `.avrgame` manifest embeds the contract unchanged and validates it with the contract validator (`avrana/avrgame/manifest.py:109-123`), so a package gets options without a manifest change, and the manifest's appliance-owned keys stay untouched. A new manifest key would split a game's facts across two places. A later contract version may promote `options` to a field, as it should `pregame`.

## 3. Declaration

```json
"net.avrana.party": { "pregame": true, "options": {
  "version": 1,
  "items": [
    {"id": "target", "type": "enum", "label": "Play to", "values": [
        {"value": "50", "label": "50 points"}, {"value": "100", "label": "100 points"}], "default": "50"},
    {"id": "bots", "type": "bool", "label": "Fill empty seats with bots", "default": true},
    {"id": "hands", "type": "int", "label": "Hands", "min": 1, "max": 20, "step": 1, "default": 4}]}}
```

- **Types:** `enum` (2 to 8 string values), `bool`, `int` (min, max, step; at most 1,000 steps). No free text, floats or lists: a Party-validated value should be enumerable, and text would carry names and links onto the screen.
- **Bounds:** at most 8 items; `id` matches the game-id pattern's lowercase form (`[a-z][a-z0-9_]{0,23}`); label 1 to 40 printable characters; every default must itself validate; an option may not depend on another (v1 has no conditions).
- **Requires pregame.** Options need the Host's setup scene, so `options` with `pregame` false is a validation error.
- **Accessibility:** `label` is the only visible name and is the control's accessible name. An optional `help` (at most 120 characters) becomes its description. Display strings are data, never markup.
- **Validation by the Party:** a new key in `EXTENSION_KEYS` plus a checker in `party_config.py`, run wherever the contract is (the catalog build, the package install check). A failure is a normal contract refusal naming the item.

## 4. How values travel

**Recommendation: one new optional field `options` in the signed `launch` payload, protocol version unchanged.**

- Precedent: `jti`, `host` and `result` were added inside `avrana.party-session/v0` (`protocol.py:79-97`, ADR 0006 amendments). The field sits inside the MAC like the roster. A verifier that predates it ignores it, so an old game still launches; it simply plays its defaults.
- The value is `{"v": 1, "values": {"target": "100", "bots": true, "hands": 4}}`, always complete (the Party fills defaults), at most 512 bytes, sealed under the existing 8,192-byte cap (`protocol.py:114`).
- A separate message was rejected: it adds a second replay-guarded exchange and a window where a session has no options yet.
- **Compatibility, three cases.** (a) Old game, new Party: the declaration is not used, so the game declares nothing, and nothing is sent. (b) New game, old Party: the old Party's extension check rejects the unknown key `options` (`party_config.py:50-51`), so the game is refused at validation with a named reason, not run with surprising defaults. That is correct fail-closed behaviour, but the message should say "needs a newer Party". (c) A kit that ignores the field: the game plays defaults, which must equal its declared ones (checked in section 8).
-

## 5. The setup scene

The Host sees the options in the Party's setup scene (ADR 0011 decision 4), under the roster and above Start. They are Party Home design-system controls (select, switch, stepper), labelled by `label`. Followers see the values read-only. Only the Host edits: `POST /party/api/session/options {values, if_version}`, refused outside setup with the same boundary as `round_on`. Party Core validates against the declaration and keeps `session.options`; values change only before Start, and Start freezes them into the launch.

## 6. Play again and switch

- **Play again** opens a new setup (`web/party/lib/party-follow.js:112`). Proposal: the new setup is **prefilled with the previous round's values**, shown as editable; Start is still the Host's. Choices of Play or Watch are not carried over (ADR 0010), but a rules choice the Host already made is not a role.
- **Switch or Choose another game:** options belong to a game; they are dropped. Returning to the first game later starts from its defaults.

## 7. SDK

- **Python:** `new_session(roster, options)`, where `options` is a read-only mapping of every declared id, already validated by the Party and re-validated by the kit against the game's own copy of the declaration. One-argument games keep working (the kit inspects the signature once).
- **Node:** `newSession(roster, { changed, options })`; same rules.
- The game re-checks type and range and raises `Declined(sentence)` for a value it cannot honour: the Party validated the shape; only the game knows its rules.

## 8. Conformance

`Fixture` gains `options_cases`. The runner derives the cases from the declaration: every enum value; both bool values; an int's min, max and one interior step; the defaults; the launch with the field absent (must behave as the defaults); and refusals: an unknown id, a wrong type, an out-of-range int and a value not in the enum must each be declined with a sentence. Cases are capped (say 64).

## 9. Not in scope

Conditional options, free text, per-player options, mid-round changes, and any protocol or Party implementation.

## 10. Owner decisions

1. Declare in `extensions."net.avrana.party".options` (recommended) versus waiting for a contract v1 field.
2. Types limited to enum, bool and bounded int (recommended); allow or forbid a short text.
3. Additive `options` in the signed launch, version unchanged (recommended) versus a protocol v1.
4. Play again prefills the last values (recommended) or resets to defaults.
5. Followers see the values read-only (recommended).
6. Old Party plus an options-declaring game: refuse at validation (recommended).
