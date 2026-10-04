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
| [games/](games/) | Source copies of the nginx rules for `/games/`, committed verbatim in both site files and not deployed by any script. `nginx-native-games.location` (HTTPS block only; native games are never served over plain HTTP): control paths refused, every slug routed to its own Unix socket, anything else refused; names no title and is the file a later `games.avrana.net` block includes (ADR 0016 §4, AVR-259). `nginx-legacy-lan-games.location` (both blocks): BLUFF and EXPO routed by name to the retiring LAN Games runtime; goes with AVR-228. `nginx-games-plain-http.location` (port 80 only): every other path under `/games/` refused. The site file and the web build of the same commit are one deployment unit: the catalog no longer offers the LAN Games titles this routing no longer serves |
| [arcade/](arcade/), [journald/](journald/) | Party-session drop-in and log bounds |
| [ops/](../ops/) | HTTPS/certificate provisioning, config checks and web release/rollback tools |
| [telemetry/](../telemetry/), [arcade/](../arcade/) | Component-specific units/installers |

The root configuration/installer paths are intentionally retained. Existing installers,
operations tools and historical deployment commands consume them; moving them only to reduce
root file count would change that operational interface. Do not consolidate the two nginx
copies or change their line endings. Source equality does not establish live-site equality.
