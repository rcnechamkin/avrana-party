"""Party Core v0: the appliance's one authoritative party (stdlib only).

avrana.party.identity   server-issued device identity (hash-only store, the device cookie)
avrana.party.core       membership, presence, host and game-session state; pure, clock injected
avrana.party.service    the HTTP service: `/party/api/…` for phones
avrana.party.sessions   the party's side of the session protocol over HTTP
avrana.party.protocol   the session protocol itself (vendored by game repositories)
avrana.party.result     the game result envelope (vendored by game repositories)
avrana.party.registry   which games this appliance runs and how Party Core reaches each one
avrana.party.managed    a runtime that runs only while the party says so (the arcade)

Runs on the appliance as `avrana-party-core` behind nginx `/party/api/`; docs/SYSTEM.md has the
deployed revision. Design: ADR 0002/0003/0006/0011, docs/design/PARTY-LIFECYCLE.md.
"""
