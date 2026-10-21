# A guest's Leave during a round on a game origin (assessment)

- **Status:** **PROPOSED (2026-10-20, AVR-580). Nothing built.** A security assessment with one
  recommendation for the owner. It changes no contract and adds no bridge capability.
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

## 6. Decisions for the owner

1. Approve B as the direction: an ADR 0011 amendment and a separate change after #167.
2. Approve the marker's lifetime (60 s is suggested) and its wording on the sheet.
3. Decide whether #167 merges first with E, as now, and B follows as its own PR. This is recommended,
   because B depends on #167's Leave and Reconnect.
