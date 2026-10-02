# Deployment assets and operator tools

These files are reviewed source, not proof of installation. [SYSTEM](../docs/SYSTEM.md) owns
verified deployed revisions. Procedures in [runbooks](../docs/runbooks/) require a separate
owner deployment instruction; do not run installers as development or CI checks.

| Source | Purpose / companion |
|---|---|
| [Root nginx site](../avrana-party.nginx) | Must stay byte-identical to [arcade/nginx-site](../arcade/nginx-site); CI enforces this |
| [Root captive DNS configuration](../avrana-captive.conf) | NetworkManager dnsmasq drop-in; [network runbook](../docs/runbooks/network.md) |
| [Portal installer](../install-portal.py), [DNS installer](../install-captive-dns.py) | Legacy owner-run installers; DNS installer can bounce the AP; use the relevant runbook |
| [party-core/](party-core/) | Service/config templates and nginx location snippet |
| [arcade/](arcade/), [journald/](journald/) | Party-session drop-in and log bounds |
| [ops/](../ops/) | HTTPS/certificate provisioning, config checks and web release/rollback tools |
| [telemetry/](../telemetry/), [arcade/](../arcade/) | Component-specific units/installers |

The root configuration/installer paths are intentionally retained. Existing installers,
operations tools and historical deployment commands consume them; moving them only to reduce
root file count would change that operational interface. Do not consolidate the two nginx
copies or change their line endings. Source equality does not establish live-site equality.
