"""Operations tooling for the deployed appliance (stdlib only; imports on any machine).

avrana.ops.manifest   the deployment manifest the Pi writes (avrana.deployment/v0)
avrana.ops.status     the machine-readable /party/api/status document (avrana.status/v0)
avrana.ops.smoke      deterministic post-deploy smoke checks
avrana.ops.boundary   the service boundary of ADR 0016, judged on a host (read-only)
avrana.ops.rebuild    a clean target against deploy/appliance-inventory.json: plan, apply, verify

ops/deploy.sh is the one deterministic deployment entry point; it is run by the owner on the Pi
and calls these modules. None of this deploys anything by itself.
"""
