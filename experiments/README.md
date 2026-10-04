# Experiments and preserved prototypes

Current source lives on GitHub main. [The branch inventory](../docs/branches.json) records
intentionally divergent research/history branches; they are not deployment candidates or
current assignments. No experiment becomes accepted architecture without a reviewed decision.

[Archived Diplomacy](archive/diplomacy/README.md) is abandoned and retained only as evidence.
Do not continue it. Its validation script is not part of the offline test suite.
[service-trust/proof.sh](service-trust/proof.sh) is the non-production systemd proof behind
[ADR 0016](../docs/adr/0016-service-identities-and-local-trust-boundary.md); it runs in CI or on a
disposable Linux machine, never on the Pi.
See [AGENTS](../AGENTS.md) and [Linear](https://linear.app/avranakern) before starting work.
