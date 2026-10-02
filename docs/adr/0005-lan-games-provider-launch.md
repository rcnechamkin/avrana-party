# ADR 0005: LAN Games provider launches

Status: **implemented and merged** (Party PR #7 / Games PR #1); provider launches and fork
cutover are deployed ([2026-09-27 finding](../findings/2026-09-27-production-deploy.md)).
Status reconciled 2026-10-01; [SYSTEM](../SYSTEM.md) owns verified runtime revisions.
The decision below is the original provider boundary. ADRs 0006–0011 subsequently add Party
session/roster authority and replace fixed return chrome during Party rounds with authoritative
follow and host-owned controls. Original sprint deferrals below are historical, not the queue.
Date: 2026-09-26. Builds on ADR 0004 and merged shell assimilation PR #5.

Avrana owns identity/profile, global navigation, discovery, library and Party Chat.
LAN Games owns individual game implementations and temporary transport internals.
The standalone hub is a compatibility/development surface, not a product boundary.

Decisions:

- avrana.lan-catalog/v1 is a deterministic public descriptor exported from the
  authoritative registry, with reviewed revision/digest and cross-repo drift tests.
  IDs are lan-<slug>, except existing bluff. Routes remain outside Game Contracts;
  installation is still an appliance grant, verified against the known route.
- avrana.lan-launch/v1 is advertised in /api/games. Integrated URLs use avrana=1
 , no credentials or arbitrary return URLs. Unsupported
  donors fail visibly. Donor support should land before platform activation.
- Shared bootstrap and declared data-avrana-* surfaces gate legacy global chrome.
  A contained game room leaves space for one explicit /party/ return. Game-specific
  UI and standalone development remain supported; no iframe shell is introduced.
- wc-* keys remain shared identity compatibility. lg-* remain the one library store;
  canonical entries use avrana:<ID> and known old aliases collapse lazily. History
  means opened, not execution success. Unknown data survives.
- One /chat/ws conversation remains; games do not create competing global chat.
  Connection counts are not a canonical roster. No Party service is promoted.
- Integrated pages do not register the donor root SW. Its updated standalone worker
  bypasses Avrana/integrated clients and preserves foreign caches. /party/ scope,
  HTTPS, captive HTTP, diagnostics and runtime providers remain unchanged.

Consequences: two coordinated PRs, explicit deployment version gate and hardware
acceptance after review. Existing pre-upgrade browser SWs require update testing.
Cross-origin historical storage, legacy authorization, authoritative session state
and deeper transport extraction remain debt. Details: [LAN-GAMES-PROVIDER](../design/LAN-GAMES-PROVIDER.md).
