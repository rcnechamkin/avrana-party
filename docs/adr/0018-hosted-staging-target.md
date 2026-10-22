# ADR 0018: Hosted staging is a second deployment target, not a second Party

Status: **proposed · awaiting owner approval** · Date: 2026-10-22

## Context

Remote multiplayer testing between people on different networks cannot happen on the Pi, which
is reachable only on its own Wi-Fi. The owner wants a private staging site at `https://avrana.party`
on the Avrana Media host (ThinkCentre M700). The H1 audit is in
[HOSTED-STAGING](../design/HOSTED-STAGING.md).

## Decision (proposed)

1. **One application.** The same Party Core, Party Home, SDK contracts, game packages,
   `ops/deploy.sh` and systemd units run in both targets. Differences are limited to:
   - deployment configuration (`party-core.json`, a deploy profile);
   - a hosted nginx site rendered from `avrana-party.nginx`;
   - environment-neutral client handling of an authentication redirect.

   Nothing in Core, the SDK or game logic knows which target it runs on.
2. **Isolation.** Staging runs in its own KVM virtual machine on the Media host (Debian 13, like
   the Pi), with its own outbound-only Cloudflare Tunnel. It touches no Media container, nginx
   site, tunnel or data.
3. **Two origins.** `avrana.party` is the Party origin and `games.avrana.party` the game origin,
   as ADR 0013 requires and as native games enforce.
4. **Authentication.** Staging authentication is Cloudflare Access (email allow-list, one-time
   PIN), enforced at the edge and again by `cloudflared` (Access JWT required). It stays separate
   from Party identity: Party Core never reads Access headers.
5. **What is not hosted.** The captive portal, AP, local DNS, Limited Mode, the doorway, the
   arcade and the devserver's test controls.
6. **The appliance stays authoritative.** It is still the only evidence for Wi-Fi, captive
   portal, offline and real-phone hardware behavior. Hosted results never stand in for appliance
   results, and appliance suites are not weakened.

## Consequences

- Infrastructure steps (VM, host network filter, tunnel, DNS, Access) each need explicit owner
  approval.
- Deployments stay owner-run with explicit commits. There is no deploy on push and no CI
  dependency.
