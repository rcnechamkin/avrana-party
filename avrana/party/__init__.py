"""Party Core v0: the appliance's one authoritative party (stdlib only).

avrana.party.identity   server-issued device identity (hash-only store, the `/party/` cookie)
avrana.party.core       membership, presence, host and game-session state; pure, clock injected
avrana.party.service    the HTTP service: `/party/api/…` for phones

Status: PROPOSED production shape on a review branch; not deployed. Design: ADR 0002/0003,
docs/design/PARTY-LIFECYCLE.md. Reference evidence (not merged): branch experiment/party-service
and the lifecycle model on experiment/party-sim.
"""
