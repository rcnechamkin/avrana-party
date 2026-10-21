# A guest's Leave during a round on a game origin (assessment)

- **Status:** **DECIDED by the owner (2026-10-21, AVR-580); built in source (§7), not deployed, not checked on a phone.**
  A security assessment with one recommendation, which the owner approved. It adds no bridge capability.
- **Reads with:** [ADR 0011](../../adr/0011-party-console-model.md) (Leave is not a disconnect; a Host's
  Leave goes through succession), [ADR 0013](../../adr/0013-party-and-game-browser-origins.md) (origins),
  [the control centre](2026-10-16-control-center.md) (D3: over a game origin the layer is coverable),
  Party PR #167, `web/party/lib/layer.js` (`actions()`), `web/party/lib/bridge.js` (`onView`).

## 1. The gap

On #167's head (bc78d7c), Leave is not offered when the layer sits on a page of another origin. A guest
whose Party is in a round on a game origin (today BLUFF and EXPO, later any package) cannot leave until
the round ends. Closing the page is a disconnect, not a Leave, so their place is kept and they come back
as soon as the page opens again. The owner does not want this to be the permanent behaviour.

## 2. What must stay true

1. **Core decides.** Leave is `POST /party/api/leave`, authenticated by the device cookie. Nothing else
   changes membership.
2. **The game page gets nothing new.** No new message to or from it, and no URL from a message. Its only
   navigation stays the bridge's `navigate {to:'party'}`, which goes to Party Home.
3. **No wider Host power.** Over a game origin the Host keeps End and Party Home only (D3). This proposal
   is for guests. A Host's Leave still happens on the Party's own pages, where succession is confirmed.
4. **Accountless and device-local.** No account and no new stored identity. #167's opt-out marker stays
   as it is.

## 3. The threat

The game page owns the layer's `<iframe>` element. It can move the frame, cover it, make it transparent
or put a lure on top. This is D3's "coverable", and no browser offers a portable defence: the
IntersectionObserver v2 visibility check works only in Chromium, and the frame cannot detect that it is
covered. So **anything confirmed inside the frame can be clickjacked**.

What a guest's Leave can do to a guest: it ends their own membership. Their seat in the round stays
(`core.leave` never touches a live session) and Reconnect brings them back. It cannot affect anyone
else. The harm is low, but tricking a person into leaving their own party is still a real harm, so the
confirmation must happen where the game cannot draw.

## 4. Options

| | Mechanism | Verdict |
|---|---|---|
| A | Leave and its confirmation inside the layer frame | **Rejected.** Both taps can be clickjacked (§3). |
| B | The frame asks; the confirmation happens on Party Home, a top-level Party page | **Recommended** (§5) |
| C | Let the layer frame navigate the top window (`allow-top-navigation-by-user-activation`) to a Party leave page | **Rejected for now.** It changes the vendored mount in every package (an SDK release). It gives a Party frame top navigation inside game pages. A query-string intent can also be forged by any page; the top-level confirmation would still stop that. |
| D | A new bridge message that asks the game page to go to a Party "leave" URL | **Rejected.** It is a new bridge capability with a URL, which §2.2 forbids. |
| E | Keep it unavailable: close the page, then Leave from Party Home after the round | The status quo, and the fallback if B is declined |

## 5. Recommendation: B, a Party-origin exit request

§7 records how it was built where it differs from this first description.

1. **Ask.** The layer drawer offers a guest **Leave Party…** during a round when `crossOrigin` is true.
   It is a request only, with no confirmation in the frame. The frame posts
   `POST /party/api/leave/request`. The Party origin is required and so is the device cookie, as for
   every API call the layer makes today.
2. **Core records a request, not a Leave.** The member gets a marker for about 60 seconds. It appears
   only in their own view (`me.exit_requested`), not in other members' views. It changes no membership,
   seat or location. It is idempotent and refused for the Host (`host_must_use_party_home`), so §2.3
   holds in Core and not only in the UI.
3. **The existing navigation takes the guest out.** `bridge.js onView` already sends the game page
   `navigate {to:'party'}` when the device has `departed`. The change adds `me.exit_requested` to the
   same condition. The game page gets the message it already gets on End.
4. **Party Home confirms.** While the marker is set, `destination()` keeps this device on Party Home
   instead of forwarding it to the round. Party Home is top-level, its CSP is `frame-ancestors 'none'`
   (`avrana-party.nginx`, the dev server's `SHELL_HEADERS`), and the game cannot draw over it. It shows
   #167's Leave sheet with the same wording and consequence. **Leave** calls the existing `/leave`, and
   the device goes to Reconnect? as on #167. **Stay** clears the marker
   (`DELETE /party/api/leave/request`) and following resumes. If nobody answers, the marker expires and
   following resumes.

### What this costs

- **Core:** one member-scoped marker with an expiry, one endpoint, one field in the member's own view, and
  one branch in `destination()`. A small amendment to ADR 0011, together with #167's amendment.
- **Party web:** one drawer action for guests over game origins, one condition in `bridge.js`, and Party
  Home showing the existing sheet when the marker is set.
- **Games and the SDK:** nothing. Packages already load the bridge and follow `navigate`.

### Residual risks

| Risk | Effect | Accepted because |
|---|---|---|
| A lure makes a guest tap **Leave Party…** | The guest is taken to Party Home and offered Leave or Stay. Nothing has changed, and Stay or 60 s returns them to the round. | It is an interruption only. A hostile page can already interrupt its own players. |
| A game page ignores `navigate` | The guest stays on the game page with the marker set. The marker expires. | A page that ignores `navigate` also ignores End. The SDK conformance gap (AVR-681) is where that is fixed. |
| Another Party tab on the same device | That tab sees the marker and also shows the sheet. | It is the same device and the same person, as with #167's opt-out. |
| A Host taps it | It is not offered to a Host, and Core refuses it. | §2.3 |

### Tests it needs before review

- Provider (cross-origin): a guest's request takes their page to Party Home with the sheet. Stay returns
  them to the round, Leave shows Reconnect?, and the round goes on for everyone else.
- The Host is not offered the action, and Core refuses a Host's request.
- The marker expires. Other members' views never show it.
- A request with no cookie, or from a game origin, is refused.
- Physical: iPhone Safari and an installed PWA, plus Android, as part of #167's acceptance checklist.

## 6. Decisions for the owner (taken 2026-10-21)

The owner approved B, #167 merged first, and B is built as its own PR. The wording and the lifetime are
in §7 for review.

1. Approve B as the direction: an ADR 0011 amendment and a separate change after #167.
2. Approve the marker's lifetime (60 s is suggested) and its wording on the sheet.
3. Decide whether #167 merges first with E, as now, and B follows as its own PR. This is recommended,
   because B depends on #167's Leave and Reconnect.

## 7. As built (2026-10-21)

- **Core** (`avrana/party/core.py`): `request_exit` and `stay`.
  - The request has an id (`exit_id`) and a time (`exit_until`, `EXIT_INTENT` = 60 s).
  - It is refused for the Host (`host_uses_party_home`, 403), outside a round or its results
    (`not_in_round`), for a device that left (`left_party`) and for a stranger (`not_member`).
  - A repeat keeps the id and renews the time.
  - Stay, Leave and Reconnect close it. It never touches membership, seats, roles or the location.
- **Service:** `POST /party/api/leave/request` and `POST /party/api/leave/stay`.
  - They have the same guards as every Party API post: the Party origin (game origins are never POST
    origins), JSON, `Sec-Fetch-Site`, and the device cookie.
- **View:** `me.exit = {id, live}` on this device's own view only. It is not in `members` and not in the
  bridge's `publicView`, so no game page learns of it.
- **One navigation decision:** `destination()` returns Party Home while `me.exit.live`. The shell, the
  follower and the bridge all use it, so the bridge's existing `navigate {to:'party'}` moves the game
  page.
- **Drawer** (`layer.js` `exitOffered`, `layer-app.js`): **Leave Party…** for a guest over another origin
  during a round or its results.
  - It asks once, with no confirmation in the frame.
  - It says "You will confirm on Party Home. Nothing changes until you do."
- **Party Home** (`app.js` `exitOpen`): it shows #167's Leave sheet with a line saying the person asked
  from the game and that their place in the round is kept until they choose, and with **Stay in
  Party**.
  - **Focus goes to Stay**, the choice that changes nothing.
  - **Stay, the close button and Escape all mean Stay.**
  - **Expiry never closes an open sheet.** The sheet belongs to its request id and stays until that id
    is closed (Stay here or in another tab, Leave, Reconnect). The 60 s only limits how long pages are
    moved: after it, a reload or a game page stays where it is.
  - **Offline at Stay**, the sheet stays and says it could not reach the Party.
- **Tests:**
  - `tests/unit/test_party_guest_exit.py` (Core and HTTP: refusals, origins, cookies, expiry, repeats,
    tabs, succession);
  - `tests/offline/guest-exit.test.mjs` (drawer rule, `destination()`, client, bridge: one existing
    `navigate`, no new word);
  - `tests/provider/game-origin-layer.spec.ts` (real Party, real BLUFF on the game origin: Leave, Stay,
    Escape and close, Host refusal, the game page cannot ask, two tabs, offline, expiry with the sheet
    open).
- **Not done:** real phones (iPhone Safari and an installed PWA, Android Chrome), Limited Mode (no game
  origins there, so the drawer never offers it), VoiceOver and TalkBack on the sheet, and a real Pi
  restart or Wi-Fi drop during the question.
