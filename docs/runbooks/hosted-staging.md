# Runbook: hosted staging at avrana.party

Status: **PROPOSED procedure, NOT RUN** (2026-10-22). The design and decisions are in
[HOSTED-STAGING](../design/HOSTED-STAGING.md) (owner-approved H1, 2026-10-22). Nothing here has
run on the Media host or on Cloudflare.

Every numbered step that changes the Media host, Cloudflare or a public name is an **owner action
with its own explicit approval**. Approval of one step does not carry over to the next. Agents
prepare the commands and verify the results. They never hold the host's SSH key, the tunnel
credential or Cloudflare credentials.

Hosted staging runs the same Party as the Pi:

- Party Core, the shell, `ops/deploy.sh`, the units and the nginx rules.
- These run in one Debian 13 VM on the Media host (`avrana`, 10.0.0.218).
- The VM is reached only through its own outbound Cloudflare Tunnel, behind Cloudflare Access.

It proves platform and gameplay behavior between people on different networks. It never proves
Wi-Fi, the captive portal, local DNS, offline play or phone hardware: those remain Pi evidence.

## Gates at a glance

| Step | What changes | Approval needed |
|---|---|---|
| 1 | nothing (read-only host preflight) | none |
| 2 | Media host: one libvirt network filter, one VM, its disk | **owner: create the VM** |
| 3 | inside the VM only: packages, users, units, firewall | covered by step 2 |
| 4 | inside the VM only: first deployment at explicit SHAs | **owner: deploy Party X + Games Y** |
| 5 | Cloudflare: a tunnel, two DNS records, one Access application | **owner: Cloudflare changes**, separately for each of DNS, tunnel and Access |
| 6 | nothing (acceptance) | none |

## 1. Host preflight (read-only)

On the Media host, as the operator:

```sh
bash ~/avrana-party/deploy/hosted/vm/host-preflight.sh --disk-gb 12 --ram-mb 2048 --vcpus 2
```

The preflight checks:

- **Disk:** at least 39 GB free under `/var/lib/libvirt/images`. That is 12 GB for the thin disk at
  its ceiling, 12 GB for one snapshot at worst, and 15 GB left for Media.
- **Memory:** 2 GiB plus a 4 GiB reserve available.
- **CPU:** fewer vCPUs than cores.
- **Virtualization:** `/dev/kvm`, `virt-install`, and the `default` network active.
- **Names:** no existing domain or filter with these names.

On 2026-10-22 the root volume had 28 GB free, below 39. The disk therefore needs either:

- `--disk-gb 8`, and snapshots taken only after pruning; or
- the owner choosing another storage pool.

This is the first decision at step 2. Do not lower the 15 GB Media reserve.

Resource ceilings once created:

| Ceiling | Value |
|---|---|
| vCPUs | 2 |
| CPU quota | 150 % of one core |
| `cpu_shares` | 256 (Media wins contention) |
| Memory | 2 GiB, no balloon |
| Disk I/O weight | 200 |

The memory ceiling is measured in step 6. If Tanks (Node) needs more, raise it then.

## 2. Create the VM (owner, on the Media host)

1. Download Debian 13's `debian-13-genericcloud-amd64.qcow2` and `SHA512SUMS` from
   `https://cloud.debian.org/images/cloud/trixie/latest/`. Check it with
   `sha512sum -c --ignore-missing SHA512SUMS`.
2. Copy `deploy/hosted/vm/cloud-init.user-data.example` to `user-data.yaml`. Put your SSH
   **public** key in it.
3. If `virt-install` is missing, install it: `sudo apt install virtinst cloud-image-utils`.
   This is a host package install, so it needs approval like the rest of this step.
4. Dry run, then create:

```sh
sudo bash deploy/hosted/vm/create-vm.sh --image debian-13-genericcloud-amd64.qcow2 --user-data user-data.yaml --dry-run
sudo bash deploy/hosted/vm/create-vm.sh --image debian-13-genericcloud-amd64.qcow2 --user-data user-data.yaml
virsh -c qemu:///system domifaddr avrana-party-staging        # the VM's 192.168.122.x address
```

What this changes on the host:

- one network filter, `avrana-staging-egress`;
- one domain, `avrana-party-staging`, on the existing `default` NAT network;
- one disk and one seed ISO.

It adds no port forward, bridge, host firewall rule, or nginx, Docker or tunnel change.

To undo: `sudo bash deploy/hosted/vm/create-vm.sh --destroy`.

## 3. Provision inside the VM (owner)

1. SSH in: `ssh -J avrana cody@192.168.122.x`.
2. Make the two checkouts at `/home/cody/avrana-party` and `/home/cody/avrana-party-games`.
   - Recommended: one read-only GitHub deploy key per repository, created by the owner inside
     the VM. The keys never leave it.
   - Alternative: `git bundle` files copied from the laptop.
3. Run:

```sh
sudo bash ~/avrana-party/deploy/hosted/vm/provision.sh --dry-run
sudo bash ~/avrana-party/deploy/hosted/vm/provision.sh
bash ~/avrana-party/deploy/hosted/vm/verify-isolation.sh                      # both layers
sudo bash ~/avrana-party/deploy/hosted/vm/verify-isolation.sh --host-layer-only   # the host filter alone
```

**Both isolation runs must print `isolation: PASS`.** Each forbidden target must time out, not
merely be refused: a refusal means a packet got there.

- **Forbidden:** every listed Media port on 192.168.122.1 and 10.0.0.218, the LAN router, the
  Pi, and the metadata address.
- **Required to connect:** DNS, Cloudflare's tunnel edge on 7844, Debian, and GitHub.

The second run sets the VM's own firewall aside for its duration. It proves the boundary root
inside the VM cannot lift. Keep both outputs as evidence. A failure stops everything: do not
continue to step 4.

## 4. Deploy explicit commits (owner, inside the VM)

The deployment is the appliance's own `ops/deploy.sh`. `/etc/avrana-party/deploy-profile` says
`hosted`, so it:

- restarts Party Core and the running native games;
- installs `deploy/hosted/avrana-party.hosted.nginx`;
- smokes with `avrana.ops.smoke --hosted`;
- records `hosted_profile` in the manifest.

See [deploy](deploy.md#deployment-profile-the-appliance-or-hosted-staging).

```sh
cd ~/avrana-party && git fetch -q origin && cd ~/avrana-party-games && git fetch -q origin
P=<reviewed Party sha>  G=<reviewed Games sha>
sudo bash ~/avrana-party/ops/deploy.sh --party "$P" --games "$G" --dry-run
sudo bash ~/avrana-party/ops/deploy.sh --party "$P" --games "$G"
sudo bash ~/avrana-party/ops/deploy.sh --status
```

Then the games. These are first-wave only; BLUFF and EXPO are second wave (below).

```sh
cd /opt/avrana-party/current
sudo ./ops/provision-game checkers --appliance contracts/appliances/avrana-hosted.json   # key, socket, registry, drop-in
python3 -m avrana.avrgame pack ~/avrana-party-games/bestguess/avrgame.build.json --out /tmp/bestguess.avrgame
sudo ./ops/install-game install /tmp/bestguess.avrgame --grant party_roster
# Tanks (Node, test_only, experimental): the pinned Node runtime first
#   (docs/runbooks/install-game.md "Node"), then its package the same way.
sudo systemctl reload avrana-party-core
python3 -m avrana.ops.smoke --hosted --config /etc/avrana-party/party-core.json
```

`game_origins` in `/etc/avrana-party/party-core.json` already lists `checkers`, `bestguess`
and `tanks` for `https://games.avrana.party`. A game added later needs its id there, then
`sudo systemctl restart avrana-party-core`. A restart ends the in-memory Party.

**Rollback:** `sudo bash ~/avrana-party/ops/deploy.sh --rollback` returns to the last known
good pair, with the same journal and smoke as the Pi. A game package has no upgrade or rollback
(AVR-58): `install-game remove <id>`, then install the previous `.avrgame`. Keep the last
known-good package files in `/var/backups/avrana-party/packages/`.

For a change to the VM's OS, take a snapshot first:
`virsh -c qemu:///system snapshot-create-as avrana-party-staging pre-<what>` (on the host).

**Reset test sessions:**

- `sudo systemctl restart avrana-party-core` ends the Party. Device identities are kept.
- `sudo systemctl stop avrana-party-core && sudo rm /var/lib/avrana-party-core/devices.json && sudo systemctl start avrana-party-core`
  also forgets every device. Every tester joins as new.
- Game state: `sudo ./ops/provision-game <slug> --rotate` for a native game, or reinstall a package.

**Logs and diagnostics:**

```sh
journalctl -u avrana-party-core -u 'avrana-game@*' -u nginx -u cloudflared-avrana-party --since -1h
curl -s -H 'Host: avrana.party' http://127.0.0.1:8080/party/api/status
```

The field-diagnostics bundle (`avrana.ops.fieldsession`) redacts through `avrana/ops/redact.py`.
Never paste Access JWTs, `CF_Authorization` cookies or the tunnel credential anywhere.

### Second wave: BLUFF and EXPO (only after the first wave passes step 6)

1. Install the LAN Games runtime from the Games release as on the Pi
   ([games-fork-deploy](games-fork-deploy.md)), with `AVRANA_STANDALONE_ADMISSION=0` in its
   session drop-in.
2. Render the site with `python3 -m avrana.ops.hosted_site --legacy-lan-games` in a commit.
3. Add `bluff` and `expo` grants to `contracts/appliances/avrana-hosted.json`, and the `games`
   entries to `party-core.json`.
4. Deploy that commit.

None of this blocks the first wave.

## 5. Cloudflare (owner, three separate approvals)

**5a. Tunnel (inside the VM).**

1. Install `cloudflared` from Cloudflare's apt repository.
2. `sudo cloudflared tunnel login`. This is the owner's browser; it writes `cert.pem`
   root-only in the VM.
3. `sudo cloudflared tunnel create avrana-party-staging`.
4. Copy `deploy/hosted/cloudflared/config.yml.example` to `/etc/cloudflared/avrana-party.yml`
   and fill in the UUID.
5. `sudo useradd --system --no-create-home --shell /usr/sbin/nologin cloudflared`, then make the
   credential `root:cloudflared 0640`.
6. Install `cloudflared-avrana-party.service`.
7. Do not start it until 5c exists.

The Media host's tunnels and `~/.cloudflared` are never touched.

**5b. DNS.** `cloudflared tunnel route dns avrana-party-staging avrana.party` and the same for
`games.avrana.party`. These are proxied CNAMEs to the tunnel and nothing else.

**5c. Access.** One self-hosted application, "Avrana Party staging", with both hostnames.

| Setting | Value |
|---|---|
| Session duration | 24 hours |
| Login methods | One-time PIN only |
| Policy 1 "testers" (Allow) | Emails: the owner's address only, until the owner names others |
| Policy 2 "harness" (Service Auth) | One service token, "avrana-staging-harness". It belongs to this application only; its client ID and secret live in the owner's password manager and in a tester's environment for a run |
| Cookie settings | defaults (HttpOnly, SameSite Lax); Binding Cookie off |

Put the application's audience tag in the tunnel config (`audTag`), then
`sudo systemctl enable --now cloudflared-avrana-party`.

**Cache rule** for both hostnames: bypass the cache for `/party/*` and `/games/*`. The shell's
build-stamped service worker handles updates, and the edge must not hold an old `sw.js`.

## 6. Acceptance (agent or owner, no approval needed)

```sh
# no session: both hostnames send the Access login, nothing from the origin
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://avrana.party/party/
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://games.avrana.party/games/bestguess/
curl -s -o /dev/null -w '%{http_code}\n' https://avrana.party/party/api/state
# the harness (the token from the environment, never a file in a repository)
CF_ACCESS_CLIENT_ID=... CF_ACCESS_CLIENT_SECRET=... HOSTED_BASE_URL=https://avrana.party npm run test:hosted
```

The H3 suite (`playwright.hosted.config.ts`, [TESTING](../TESTING.md)) covers the remote journey and the
failure cases, and reports the deployed commits it ran against from `/party/api/status`.

## Agent workflow

1. Implement, run the local suites, and open a draft PR.
2. Ask the owner: "deploy Party `<sha>` + Games `<sha>` to staging". Name the PRs. CI being red or
   unavailable is not a pass; state what ran locally.
3. The owner runs step 4.
4. The agent runs step 6 with a token the owner supplies for that session.
5. The agent reports the tested commits (from `/party/api/status`), the results and screenshots.

Agents never get the VM's SSH key, the tunnel credential, Cloudflare API tokens or the Media host.

## Known gaps (not blockers for the first wave)

- **The catalog is the appliance's.** Party Home lists the committed catalog (built for
  `avrana-pi4`) plus installed packages. Gauntlet II, BLUFF and EXPO therefore show as tiles that
  Party Core does not offer here. A per-deployment catalog
  (`avrana.contracts.catalog --appliance contracts/appliances/avrana-hosted.json` as the
  release's base) is a follow-up. It is not done in this change, to keep the release build
  identical for both targets.
- **Game pages and an expired Access session.** Party Home detects the sign-in redirect and
  offers "Sign in again". The bridge frame and a game's own reconnects on `games.avrana.party`
  do not. What a player sees there is measured in H3, not assumed.
- **The status endpoint** reports `not_applicable` for the certificate, the games provider and
  the arcade (`null` in `party-core.json`).
