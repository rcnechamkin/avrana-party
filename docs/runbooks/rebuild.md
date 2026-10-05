# Runbook: rebuild the appliance on a clean target (AVR-32)

Status: **PROPOSED procedure, NOT RUN** (2026-10-05). Written from source and from the facts
[SYSTEM](../SYSTEM.md) and [network](network.md) record; never executed on any device. The tests
rehearse it on a simulated host, which proves the procedure is ordered, idempotent and keeps
secrets out of the repository. It does not prove that a Raspberry Pi built this way plays a game.
Running any step on a device is an owner action: nothing in CI, in an agent's task or in this
document authorizes it.

Read these three limits first.

1. **The target is what source describes, not what the Pi runs today.** The unit files in the
   repositories describe dedicated service users and root-owned code under `/opt`
   ([ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md) phase 1). That layout
   has never run on the Pi: today every service runs as the operator account from the checkouts,
   and the games unit installed there is in no repository. A rebuild from source therefore
   produces the phase-1 layout. Rebuilding today's Pi exactly is not possible from source.
2. **`apply`, `restore` and `seal` change only a card that is being built, and refuse every
   other host.** A host that has an Avrana unit enabled or running, or any install path of
   today's layout (the key store, the site file, the web root, the releases, the deployment
   manifest: the inventory's `guard` lists them), and no valid marker of this tool, is refused
   with exit 2 before a package, a user, a file or a command. So is a rebuilt card after `seal`
   (the last step below). That host is a migration
   ([service-users-migration](service-users-migration.md)), which moves state and can be
   reversed. The owner's override does not change this for a host with a service enabled or
   running: it is refused too (section 3). `plan` and `verify` only read, are safe anywhere, and
   say which of the four states the host is in: clean, open, sealed, or an appliance.
3. **This is not an image.** No OS image is built, no card is written, nothing updates over the
   air. Image-based install and A/B rollback are later work (AVR-67, AVR-82).

## What is enumerated, and where

[`deploy/appliance-inventory.json`](../../deploy/appliance-inventory.json) is the list: the
packages, the service users and groups, every directory and configuration file with its owner
and mode and the repository file it comes from, the units that must be running, the things that
are in no repository (the two checkouts, the releases, the libretro core, the ROM, the lego
client, the games virtualenv), every secret with the place it lives and who provisions it, the
network profile the scripts target, the phone checks, and what the repository cannot say.
`tests/unit/test_ops_rebuild.py` fails when a unit file, an installer, the network scripts or
this runbook disagree with it.

Each package carries how it is known: `scripted` (an installer in the repository names it) or
`derived` (a script needs the command; the Debian package name is a reading that nobody has
confirmed on the device). `python3 -m avrana.ops.rebuild packages` prints the names.

```bash
python3 -m avrana.ops.rebuild check       # the inventory against the repository (any machine)
python3 -m avrana.ops.rebuild plan        # read-only: in place / this tool can do / waits for / handoff
sudo python3 -m avrana.ops.rebuild apply --target-hostname NAME   # the first apply names the machine
sudo python3 -m avrana.ops.rebuild apply  # everything whose needs are met; run again after each handoff
sudo python3 -m avrana.ops.rebuild verify # state, smoke, topology, boundary; then the phone checklist
sudo python3 -m avrana.ops.rebuild seal   # the build is accepted: apply and restore refuse from now on
python3 -m avrana.ops.rebuild unknowns    # what the owner confirms on the device
```

Run them from a tree of the commit being installed: the checkout at first, then
`/opt/avrana-party/current` once it exists (`cd` there). Under `sudo` always add
`PYTHONDONTWRITEBYTECODE=1`, as the commands below do: without it root leaves `__pycache__`
directories in the operator's checkout, which then is no longer clean for `ops/deploy.sh`, or in
a release. Option names are never abbreviated: `--a` is an error, not `--activate`. `--root DIR` works on a simulated host under `DIR` and
never touches the machine it runs on.

## Install order

Every step is one of four kinds, and the four sections below take them in turn.

| # | Kind | Step |
|---|---|---|
| 1 | owner | Write the OS to the card, create the operator account, give it your SSH key, connect `eth0`; install `git`, `sudo` and Python 3.11 or newer; install NetworkManager and let it run the network, at a console |
| 2 | owner | Clone the Party checkout at the reviewed commit; carry the Games bundle, clone it, detach at the reviewed commit |
| 3 | automated | `check`, `plan`, then `apply --target-hostname NAME`: the marker, packages, service users, directories, the configuration that waits for nothing |
| 4 | automated | `ops/deploy.sh --skip-smoke` builds both code releases and the manifest; `ops/install-party-web.sh` builds the web release |
| 5 | owner | Place what is in no repository: the games virtualenv, the libretro core, the ROM, the lego client |
| 6 | secret | Generate the three game keys; issue and install the certificate |
| 7 | owner | Create the access point profile and type its passphrase |
| 8 | automated | `apply --activate`: unit files, drop-ins, the nginx site; then the reload commands of everything in place, step 3's included (journal, `uinput`, udev, systemd, nginx), then enable and start |
| 9 | automated | `verify`; then `ops/deploy.sh` once more with the same commits, so the manifest records a smoke result |
| 10 | hardware | The phone checklist, on real phones over the party Wi-Fi |
| 11 | owner | Optional pieces (telemetry, automatic renewal), then update SYSTEM and write a dated finding |
| 12 | owner | `seal`: the build is over; from now on this card is an appliance and `apply` and `restore` refuse it |

## 1. Automated, reproducible steps

These are scripts. Each can be run twice; the second run changes nothing.

**Step 3.** From the Party checkout:

```bash
cd /home/cody/avrana-party
python3 -m avrana.ops.rebuild check && python3 -m avrana.ops.rebuild plan
sudo PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild apply --target-hostname <the name you read on the card>
```

Type the name; do not let the shell compute it. Passing the output of `hostname` there is always
true and checks nothing: the argument exists so that a terminal which is on another machine
than you think (a laptop, the wrong SSH session) refuses. Give the new card a hostname of its
own in step 1 and type that. On any Linux machine that shows no sign of an appliance, `apply` as
root would otherwise install all of this. A name that is not the machine's own is refused;
`apply` then prints the hostname, OS release and architecture it is about to change and records
them in the marker, and a marker counts only on the machine whose name it records.

**The hostname does not protect the Pi that hosts parties.** A fresh card and today's Pi
may share a hostname (U6): the records call the Pi both `party` and `RaspberryPi`, the image
default. What protects the live Pi is that it has the units and install paths of an appliance
and no marker; the name only catches the wrong terminal.

The first thing the first `apply` does, on a host with none of the signs above, is write
`/var/lib/avrana-rebuild/marker.json` (root-owned: the UTC time, the Party commit, the machine).
While that file is a valid, unsealed marker, every later `apply` and `restore` goes on, including
after the units have been started, when the host looks exactly like an appliance; later runs
need no `--target-hostname`. Something else at that path (a directory, a link, a file that is
not a marker) opens nothing. So `apply` comes before `ops/deploy.sh` (step 4), which creates
paths the guard treats as an installed appliance. The marker stops working at step 12.

**What step 3 does to a running machine, so do it at a console or knowing this.** Installing
the `nginx` package starts nginx at once, on port 80, serving Debian's default page until step 8
replaces the site. `apply` does **not** install the `network-manager` package and never enables
or starts NetworkManager: on an image whose network is run by something else, NetworkManager
arriving can take over `eth0` in the middle of an SSH session, and which image this is is not
recorded (U1). That is why it is in step 1, yours, at a console. Until it is installed `plan`
lists it as a handoff and the captive DNS drop-in waits for it. `apply` runs no `nmcli`.

`apply` installs the missing packages with `apt-get install --no-install-recommends`, creates
the groups `avrana-front` and `avrana-games` and the users `avrana-party`, `avrana-arcade` and
`avrana-lan-games` (system users, no shell, no home; the same commands as
`ops/migrate-service-users.sh`), creates the directories and installs the files in the table
below whose needs are already met: the journal caps, the `uinput` module and udev rule, the
captive DNS drop-in, the certificate helper scripts and `/etc/avrana-party/party-core.json`.
That last file is installed from the example only when it is absent; an existing one is never
replaced, because the owner may have edited it. Everything else waits and says what for.

It then prints the commands that load what it installed (restart the journal, load `uinput`,
reload udev). They can wait for step 8: `apply --activate` runs the reload commands of
everything that is in place, every time, whichever run installed it. A line about the access
point going down and up applies only once the profile exists (step 7), and is never run by the
tool.

A step that fails stops the run. `apply` reports only what really changed, names the failure,
exits 1, and can simply be run again once the cause is fixed.

**Step 4.** The releases and the web shell come from the scripts that already own them:

```bash
sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA> --skip-smoke
sudo bash /home/cody/avrana-party/ops/install-party-web.sh /home/cody/avrana-party
```

With both checkouts already at the named commits `ops/deploy.sh` stops and starts nothing,
builds `/opt/avrana-party/current` and `/opt/avrana-party-games/current` and writes the
[deployment manifest](../design/DEPLOYMENT-MANIFEST.md). It builds no web release in that case,
which is why the second command is there. This reading of `ops/deploy.sh` on a host with no
services is from its source; it has not been run that way.

**Step 8.** After the handoffs of sections 2 and 3:

```bash
cd /opt/avrana-party/current
sudo PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild plan
sudo PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild apply --activate
```

Now the unit files and drop-ins have their users, releases and keys, and the nginx site has its
certificate. `apply` installs them, links the site into `sites-enabled`, removes Debian's
`default` site (it claims the same `default_server`), and with `--activate` runs, in this
order, `systemctl daemon-reload`, the journal restart, `modprobe uinput`, the two `udevadm`
lines, `nginx -t`, the nginx reload, and `systemctl enable --now` for each unit whose needs are
met (providers before Party Core; never NetworkManager). Those seven reload commands are fixed
in the code: the inventory cannot add one. If one fails nothing after it runs; see "Rollback
and recovery".

**Every `apply --activate` restarts `systemd-journald` and reloads nginx even when nothing changed,**
and re-runs the other reload commands, with no check for a party in progress (`ops/deploy.sh`
refuses while a session is live; this does not). That is acceptable only on a card under build,
before `seal`; it is one more reason to seal, after which `apply` refuses.

**Step 9.**

```bash
sudo PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild verify
sudo bash /home/cody/avrana-party/ops/deploy.sh --party <PARTY_SHA> --games <GAMES_SHA>
```

The second line changes nothing and records `smoke: passed` or `failed` in the manifest, which
is what `/party/api/status` reports ([deploy](deploy.md)).

## 2. Secret and certificate provisioning

Nothing in this section is in a repository, a backup of this procedure, a log or a chat. `plan`
lists each one that is missing with the command below; `verify` checks that each exists with the
listed owner and mode and never opens one.

| Secret | Lives at | Provisioned by |
|---|---|---|
| `game-key-bluff` | `/etc/avrana-party/game-keys/bluff.key` `avrana-party:avrana-party` `0600` | `sudo bash /home/cody/avrana-party/ops/provision-party-game-key.sh bluff` |
| `game-key-expo` | `/etc/avrana-party/game-keys/expo.key` `avrana-party:avrana-party` `0600` | the same script, `expo` |
| `game-key-arcade-gauntlet2` | `/etc/avrana-party/game-keys/arcade-gauntlet2.key` `avrana-party:avrana-party` `0600` | the same script, `arcade-gauntlet2` |
| `tls-certificate` | `/etc/avrana-party/tls/current/fullchain.pem` `root:root` `0644`<br>`/etc/avrana-party/tls/current/privkey.pem` `root:root` `0600` | issued on the device, then `install-party-certificate.sh` (below) |
| `cloudflare-token` (optional) | `/etc/avrana-party/cloudflare.env` `root:root` `0600` | the owner writes it on the device |
| `wifi-passphrase` | NetworkManager's own store, `/etc/NetworkManager/system-connections/` | the owner types it (section 3) |
| `operator-access` | the operator account's SSH configuration | the owner |

**Game keys.** Each is 32 random bytes generated on the device by the script, which never prints
one and refuses to overwrite. They are new keys: nothing is carried over from another device,
and nothing needs to be, because both ends of each key are on this device. The script needs the
user `avrana-party`, which step 3 created.

**Certificate.** The private key and the ACME account are created on the device and stay there
([party-https](party-https.md), "Trust and key custody"). Issue `party.avrana.net` with lego's
DNS-01 challenge into `/var/lib/avrana-party/lego` (the manual DNS mode needs someone with
access to the `avrana.net` zone to add one TXT record). **No repository records the lego command
line that was used** (U13): [party-https](party-https.md) describes the issuance in prose, and
the only scripted lego call is the renewal, which needs the Cloudflare token. Work it out from
`lego --help` and write it into a finding. Then:

```bash
sudo /usr/local/libexec/avrana-party/install-party-certificate.sh \
  /var/lib/avrana-party/lego/certificates/party.avrana.net.crt \
  /var/lib/avrana-party/lego/certificates/party.avrana.net.key
```

Do not copy the key from the old device, and do not use `ops/deploy-party-https.sh`: it was the
one-time deployment of 2026-09-25 and reads a lab directory that exists only on that Pi.

**Automatic renewal (optional).** With the token file in place, `apply` installs
`avrana-party-certificate.service` and `.timer`; enable the timer only after one manual run of
the service succeeded. Without the token neither file is installed, `verify` reports them as
skipped, and renewal is manual: the certificate check fails below 21 days.

## 3. Owner-only production actions

These need a person at the device, a decision, or something only the owner holds.

**Step 1: the OS.** SYSTEM records a Raspberry Pi 4 running Debian 13 as user `cody`. Which
image, and what was changed in the boot configuration, is not recorded (U1, U3 below). Python
3.11 or newer and `sudo` must be there before step 3.

**Step 2: the checkouts.** The Party repository is cloned to `/home/cody/avrana-party` with the
device's own GitHub key. That key does not read the private Games repository, so the Games code
travels as a bundle ([games-fork-deploy](games-fork-deploy.md), section 1) to
`/home/cody/avrana-party-games`. Check both out detached at the reviewed commits.

**Step 5: what is in no repository.**

| Artifact | Lives at | How |
|---|---|---|
| `games-venv` | `/opt/avrana-party-games/venv/bin/python` | `sudo python3 -m venv /opt/avrana-party-games/venv`, then its `pip install -r /opt/avrana-party-games/current/requirements.txt`; needs the internet over `eth0`; root-owned |
| `arcade-core` | `/opt/avrana-arcade/cores/mame2010_libretro.so` | your copy of the core, root-owned `0644`; `verify` compares its sha256 with `arcade/evidence/selected-core.json` and warns when they differ (U8) |
| `arcade-rom` | `/srv/avrana/roms/arcade/gaunt2.zip` | your own Gauntlet II set, readable by `avrana-arcade`; never downloaded, never committed |
| `lego` | `/usr/local/bin/lego` | the lego ACME client, root-owned `0755` (U7) |
| `party-checkout`, `games-checkout` | `/home/cody/avrana-party/.git`, `/home/cody/avrana-party-games/.git` | step 2 |
| `party-release`, `games-release`, `web-release` | `/opt/avrana-party/current/avrana/ops/smoke.py`, `/opt/avrana-party-games/current/server.py`, `/var/www/avrana-party/web/current/version.json` | step 4 |

**Step 7: the access point.** No script creates the NetworkManager profile, and none should:
it holds the passphrase. `python3 -m avrana.ops.rebuild ap-profile` prints the `nmcli` command
for the profile every script here targets ("Avrana Party Internal" on `wlan0`, 5 GHz channel
149, WPA2, `10.42.0.1/24` shared), without the passphrase, and the `nmcli --ask` line that makes
NetworkManager prompt for it. Run both at the device or over `eth0`, never over the party Wi-Fi.
Set the regulatory country first (U4). The fields are the ones [network](network.md) recorded on
2026-09-24; that record is not a full export of the profile (U5), and the printed command has
never been run. The profile is created with autoconnect on and no passphrase in it: whether the
passphrase typed at `--ask` is stored for the next boot is not known (U5). Check with a reboot
before section 4; if the access point does not come back, set the passphrase with `nmtui`. The captive DNS drop-in was installed in step 3, before the profile first comes
up; if you change that file later, the profile has to go down and up, which drops every phone.
Then apply "Boot determinism" from the network runbook if you want the access point to win at
every boot.

**Overriding the guard.** `--owner-confirms-not-the-live-appliance` exists for one situation: a
card that has never hosted a party, on which `apply` refuses because install paths exist but the
marker does not. That happens when the marker was lost, or when `ops/deploy.sh` ran before the
first `apply`. What it can do: let `apply` or `restore`, each with `--target-hostname`, go on
there; `apply` writes the marker and records in it that it was overridden and what it saw. What
it cannot do: it is refused, like any other run, whenever one of the Avrana units
(`avrana-party-core`, `avranaparty-games`, `avranaparty-arcade`, the certificate timer) is
running, starting, failed-but-enabled, enabled or linked, or when `systemctl` gives no answer
about one, sealed or not. And it never changes the owner or mode of a key store that holds keys
and belongs to another user: `plan` shows that directory as a handoff ("owner decides"), because
re-owning it takes the keys away from whoever runs the services that read them. A host with services is a live appliance and no flag makes
this tool change it. It cannot be abbreviated, is never typed by an agent, and is never the
answer to a refusal that was not understood: read what `apply` printed first.

**Step 11.** Optional and independent of play: `telemetry/install-pi-throttle-check.sh`,
`telemetry/install-beszel-agent.sh` (and the hub's "Add System"), the renewal timer. Then update
[SYSTEM](../SYSTEM.md) from what `verify` and `/party/api/status` report and write a dated
finding; this runbook's status line changes only then.

**Step 12: seal.** When section 4 has passed and the card is going to host parties:

```bash
cd /opt/avrana-party/current && sudo PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild seal
```

It records the UTC time in the marker. From then on `apply` and `restore` refuse this card
exactly as they refuse today's Pi, so a later mistake cannot re-own a key store or replace a
site under running services. `plan` and `verify` keep working and say "SEALED". Later changes
are deployments ([deploy](deploy.md)) or a new rebuild on another card. Do not skip it: an
unsealed appliance is an unguarded one.

## 4. Real-hardware verification still required

`verify` prints these after its own checks. No script can answer them, and a pass from `verify`
is not a pass here.

- **ap**: a phone that has forgotten the network joins "Avrana Party" with the passphrase and
  gets an address in `10.42.0.10`–`254`; an iPhone shows no captive popup.
- **dns**: on that phone `https://party.avrana.net/party/` opens with no certificate warning.
- **party**: two phones Join; the first is the Party Host; a reload keeps each phone's identity.
- **games**: the Host starts BLUFF, then EXPO: the other phone follows, both play, the Host ends
  the game and both return to Party Home.
- **arcade**: the Host starts Gauntlet II: video and sound arrive, two phones control two
  heroes, End returns everyone home. The arcade unit's hardening has never met RetroArch, Xvfb,
  PulseAudio and `uinput` on any host; read `journalctl -u avranaparty-arcade` first if it fails.
- **health**: after a power cycle with `eth0` unplugged, the access point, DNS and every service
  come back by themselves and the checks above still pass.
- **nginx**: `http://10.42.0.1/` on a phone shows the link to the Party and never redirects.

Record model and OS version of each phone and the result in a dated finding.

## File locations and ownership

What `apply` creates and installs. "Waits for" is what must exist first; `plan` shows the same.

| Path | Owner:group mode | From | Waits for |
|---|---|---|---|
| `/etc/avrana-party/` | `root:root` `0755` | created | — |
| `/etc/avrana-party/game-keys/` | `avrana-party:avrana-party` `0700` | created | the user |
| `/var/lib/avrana-party/` | `root:root` `0711` | created | — |
| `/var/lib/avrana-party/lego/` | `root:root` `0700` | created | — |
| `/var/backups/avrana-party/` | `root:root` `0750` | created | — |
| `/usr/local/libexec/avrana-party/` | `root:root` `0755` | created | — |
| `/opt/avrana-arcade/cores/` | `root:root` `0755` | created | — |
| `/etc/systemd/journald.conf.d/avrana.conf` | `root:root` `0644` | `deploy/journald/avrana-journald.conf` | — |
| `/etc/modules-load.d/avrana-uinput.conf` | `root:root` `0644` | `arcade/avrana-uinput.conf` | — |
| `/etc/udev/rules.d/70-avrana-uinput.rules` | `root:root` `0644` | `arcade/70-avrana-uinput.rules` | — |
| `/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf` | `root:root` `0644` | `avrana-captive.conf` | the NetworkManager package |
| `/etc/avrana-party/party-core.json` | `root:root` `0644` | `deploy/party-core/party-core.example.json`, only if absent | — |
| `/usr/local/libexec/avrana-party/install-party-certificate.sh` | `root:root` `0755` | `ops/install-party-certificate.sh` | — |
| `/usr/local/libexec/avrana-party/renew-party-certificate.sh` | `root:root` `0755` | `ops/renew-party-certificate.sh` | — |
| `/usr/local/libexec/avrana-party/check-party-config.sh` | `root:root` `0755` | `ops/check-party-config.sh` | — |
| `/etc/systemd/system/avrana-party-certificate.service` | `root:root` `0644` | `ops/avrana-party-certificate.service` | the Cloudflare token (optional) |
| `/etc/systemd/system/avrana-party-certificate.timer` | `root:root` `0644` | `ops/avrana-party-certificate.timer` | the Cloudflare token (optional) |
| `/etc/systemd/system/avrana-party-core.service` | `root:root` `0644` | `deploy/party-core/avrana-party-core.service` | the user, the Party release |
| `/etc/systemd/system/avranaparty-arcade.service` | `root:root` `0644` | `arcade/avranaparty-arcade.service` | the user, the Party release |
| `/etc/systemd/system/avranaparty-arcade.service.d/avrana-party-session.conf` | `root:root` `0644` | `deploy/arcade/avrana-party-session.conf` | the arcade's key |
| `/etc/systemd/system/avranaparty-games.service` | `root:root` `0644` | Games `deploy/avranaparty-games.service` | the user, the Games release |
| `/etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf` | `root:root` `0644` | Games `deploy/avrana-party-session.conf` | the Games release, the BLUFF and EXPO keys |
| `/etc/nginx/sites-available/avrana-party` | `root:root` `0644` | `avrana-party.nginx` | the nginx package, the certificate |
| `/etc/nginx/sites-enabled/avrana-party` | link | to the site file | the site file |

Not created by `apply`: the state directories `/var/lib/avrana-party-core`,
`/var/lib/avrana-arcade` and `/var/lib/avrana-lan-games` (systemd makes each when its unit first
starts), the certificate and web release trees (their install scripts), the code releases and
the manifest (`ops/deploy.sh`), telemetry (its installers) and every NetworkManager connection.

## Verification checklist

`verify` reports every check as pass, fail, warn or skip under an area, and exits 1 on any fail.
A skip is never a pass; an area in which no live check passed is named at the end.

| Area | What `verify` checks on the device | Tool it reuses |
|---|---|---|
| Party | unit file, config, keys present with owner and mode, `avrana-party-core` enabled and active, `/party/` and `/party/api/state` over HTTPS, `party-core.json` against the Game Contracts | inventory, `avrana.ops.smoke`, `avrana.contracts.party_config` |
| Games | unit file and drop-in, the virtualenv, `avranaparty-games` active, `/health` and `/api/games` on loopback | inventory, `avrana.ops.smoke` |
| Arcade | unit file and drop-in, core (and its sha256), ROM, `/stats`, and `/dev/uinput` present with group `input` mode `0660` (the module and the udev rule took effect; without it no phone can control a hero) | inventory, `avrana.ops.smoke`, a stat |
| nginx | site file equals the repository's, enabled, no `default` site, the Apple probe on port 80, the root page | inventory, `avrana.ops.smoke`, `tools/avrana-topology-check` |
| AP | `wlan0` is the internal radio in AP mode on the named profile, holds only `10.42.0.1/24`, upstream is `eth0`, one AP profile autoconnects | `tools/avrana-topology-check` |
| DHCP and DNS | dnsmasq listens only on `10.42.0.1`, the DHCP range, the captive drop-in equals the repository's, every captive name and `party.avrana.net` answer `10.42.0.1` | `tools/avrana-topology-check`, `avrana.ops.smoke` |
| TLS | certificate and key present with owner and mode, days left | inventory, `avrana.ops.smoke` |
| Health | every unit active, `/party/api/status`, the service boundary of ADR 0016 phase 1 | `avrana.ops.smoke`, `avrana.ops.boundary` |

Run it as root: the certificate, the key store and other users' sockets are invisible otherwise.
Not during a power measurement.

## Rollback and recovery

**The old card is the rollback.** Build on a second card and leave the working one untouched
until section 4 passes on the new one. Putting the old card back restores the appliance exactly;
nothing in this procedure writes to it.

| What went wrong | What to do |
|---|---|
| `apply` or `restore` says "refused, nothing was changed" | Believe it: nothing was changed. On the Pi that hosts parties this is the right answer; use [service-users-migration](service-users-migration.md). On a half-built target (marker lost, or `ops/deploy.sh` run before the first `apply`) see "Overriding the guard" in section 3 |
| `apply` installed a file you want back (before `seal`) | `sudo python3 -m avrana.ops.rebuild restore /var/backups/avrana-party/rebuild-<UTC>` puts back every file, link and removed path of that run (the directory is printed by `apply`), newest first; then `sudo systemctl daemon-reload` and `sudo nginx -t && sudo systemctl reload nginx`. Users, groups, packages and directories stay: they grant nothing. **Restoring a step-8 backup removes the unit files that run installed**, so `restore` refuses while any of those units is running and prints the `sudo systemctl stop …` line to run first. It checks the whole journal before touching anything: a path the inventory does not manage, a secret path, or a copy outside the backup refuses the whole restore |
| `apply` stopped with `FAILED` | Nothing after the failed step was attempted and only the lines marked `changed` happened. Fix the cause (a missing group, a path in the way, no network for `apt-get`) and run `apply` again |
| Something is wrong after `seal` | `restore` and `apply` refuse a sealed card. Use `ops/deploy.sh` for code, the old card for everything else |
| `nginx -t` failed in `apply --activate` | nginx keeps serving its previous configuration: nothing was reloaded. Read the error, then `restore` as above or fix and run `apply --activate` again |
| A unit does not start | `journalctl -u <unit> -n 50`. A unit whose `LoadCredential=` key is missing does not start: `plan` shows the missing key. `sudo systemctl disable --now <unit>` takes it out without touching the others |
| The access point does not come up | Manage the device over `eth0`. `nmcli connection up "Avrana Party Internal"`; `tools/avrana-topology-check`; [network](network.md). Never change the profile over the party Wi-Fi |
| The certificate install failed | `install-party-certificate.sh` restores the previous link itself. With no certificate at all the Party's nginx site stays uninstalled: it waits for one |
| A game key was lost or exposed | Remove the key file, run the provision script again, restart Party Core and that game's service ([party-core-deploy](party-core-deploy.md)) |
| The deployed commits are wrong | `ops/deploy.sh` with the earlier commits ([deploy](deploy.md)) |
| The rebuilt device fails section 4 | Put the old card back; write a finding; the rebuild is not accepted |

**What a rebuild does not carry over.** Device identities (`/var/lib/avrana-party-core`), the
games runtime's avatars and chat media, the arcade's saves and high scores, telemetry and
journals start empty: phones Join again as new devices. Copying any of those from the old device
is the owner's choice and is not scripted; none of it ever goes into Git.

## Unknown: the owner must confirm on the device

The repository cannot answer these, so nothing above guesses them. Each is a read-only command
on the working Pi; the answers belong in SYSTEM or a dated finding, and the `derived` entries of
the inventory are corrected from them.

| | Question | Confirm with |
|---|---|---|
| U1 | Which OS image, release and kernel the Pi is installed from (Raspberry Pi OS or plain Debian 13, 64-bit, Lite or desktop) | `cat /etc/os-release; uname -a` |
| U2 | Which packages were installed by hand beyond the inventory, and whether the `derived` package names match (RetroArch in particular: package or local build) | `apt-mark showmanual; command -v retroarch` |
| U3 | Boot configuration the H.264 encoder and RetroArch rely on | `cat /boot/firmware/config.txt` |
| U4 | The Wi-Fi regulatory country and the active brcmfmac firmware alternative | `iw reg get; update-alternatives --display cyfmac43455-sdio.bin` |
| U5 | The access point profile's remaining settings (PMF, ciphers), the `eth0` profile, and whether a passphrase typed at `nmcli --ask` is stored so the access point comes up at the next boot | `nmcli connection show "Avrana Party Internal"` (without `-s` it prints no secret) |
| U6 | The system hostname and how `party.local` is published | `hostnamectl; grep -n host-name /etc/avahi/avahi-daemon.conf` |
| U7 | The lego version and where its binary came from | `/usr/local/bin/lego --version` |
| U8 | Whether the core on the Pi is the binary `arcade/evidence/selected-core.json` records, and where a rebuild gets it | `sha256sum /home/cody/avrana-party/arcade/cores/mame2010_libretro.so` |
| U9 | The installed games unit and its virtualenv, and whether a fresh virtualenv runs the fork | `systemctl cat avranaparty-games` |
| U10 | How the clock is kept with no internet (a Pi 4 has no RTC) well enough for certificate validation | `timedatectl` |
| U11 | sudoers, polkit and sshd for the operator account; whether a default nginx site was removed by hand | `ls -l /etc/nginx/sites-enabled/` |
| U12 | Whether the phase-1 layout runs on the Pi at all | the first supervised rebuild or migration, then `verify` |
| U13 | The exact lego command line that issues `party.avrana.net` by DNS-01 | `lego --help`; the shell history of the 2026-09-25 issuance, if kept |

## Real-host code that has never executed anywhere

The tests run on a simulated host and, so far, only on Windows. The first supervised run on a
spare card is therefore also the first execution of all of this; watch each of these do what it
says, and treat a surprise as a finding.

| Never executed | What it does on a real host |
|---|---|
| `Host.exists`, `Host.kind`, `Host.meta`, `link_target`, `entries` | `stat`, `readlink` and `listdir` on real paths, including root-only ones |
| `has_package`, `has_group`, `user_groups` (for a user that exists) | `dpkg-query`, the group and password databases |
| `Host.unit`, `unit_sign`, `systemctl_show`, `_query` against a real systemd | `systemctl show`, `is-enabled`, `is-active`; the tests feed the parser text, they never ask systemd |
| `_own`, `_parents`, and the `chmod`/`chown` in `install` and `mkdir` | ownership and modes; a missing user or group ends the run with exit 1 |
| real `symlink`, `remove`, `run` | the `sites-enabled` link, removing Debian's default site, and every command: `apt-get`, `groupadd`, `useradd`, `usermod`, the seven reload commands, `systemctl enable --now` |
| `hostname`, `identity` | `socket.gethostname()` and `/etc/os-release`, which `--target-hostname` and the marker rely on |
| `live_checks`, all of it | the smoke set, `tools/avrana-topology-check`, the service boundary, the `party-core.json` check and the `/dev/uinput` check, as called from `verify` |
| the marker written, `seal` and `restore` on a real filesystem | atomic replace under `/var/lib/avrana-rebuild` and `/var/backups/avrana-party` |
| the Linux-only test (`test_a_real_host_is_read_but_never_changed_without_root`) | it has been read, never run; Linux CI will be its first execution |

## Tests

`python3 -m unittest discover -s tests/unit -p test_ops_rebuild.py` (any platform, no device):
the inventory agrees with the unit files, installers, network scripts and this runbook; a
simulated clean host reaches the expected state in the order above; `plan` changes nothing; a
second `apply` changes nothing; no secret is created, read or copied; `restore` puts replaced
files back, checks its journal first and never works under a running service; a simulated live
appliance and a sealed card are refused by `apply` and `restore` with no change and no command,
override included, while `plan` and `verify` still read them; no option can be abbreviated; a
failed step stops the run; no secret path can be written, removed or copied whatever the
inventory says; a running service's unit file is not replaced. No test changes the machine it
runs on. Tier 1 evidence about the procedure.
Everything in section 4, and every `derived` entry, stays unproven until a device is built.
