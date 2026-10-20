# Join card and real-phone onboarding check (AVR-76)

Status: **PROPOSED owner-run procedure, NOT RUN on a phone or on the appliance** (2026-10-19). The
card generator and its tests run offline on a laptop; whether real phones read a printed card and
reach Party Home is unproven until the checklist below is done. Nothing here changes the Pi, the
access point, captive probes, DNS or nginx.

## Make the card (laptop, offline)

Write the card to a **local folder that no cloud service syncs** and that is not inside any Git
repository. Not Desktop or Documents (OneDrive and iCloud often sync them), and not OneDrive,
iCloud Drive, Dropbox or Google Drive. Type the password at the hidden prompt, which keeps it out
of shell history. Git must be installed: the tool refuses a password card if it cannot check for
a working tree.

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Avrana\join-cards" | Out-Null
node tools/join-card/join-card.mjs --ssid "Avrana Party" --out "$env:LOCALAPPDATA\Avrana\join-cards\avrana-join-card.html"
```

```bash
mkdir -p ~/.local/share/avrana/join-cards    # macOS: ~/Library/Application\ Support/Avrana/join-cards
node tools/join-card/join-card.mjs --ssid "Avrana Party" --out ~/.local/share/avrana/join-cards/avrana-join-card.html
```

Delete the file after printing, or keep it only in that folder.

Without a terminal (a script), set `AVRANA_WIFI_PASSWORD` in the environment instead. Open the file in
a browser and print it (A6 landscape, or any size with each QR code at least 3 cm wide). The tool:

- writes **QR 1**, the standard `WIFI:T:WPA;S:…;P:…;;` string, and **QR 2**, the Party link
  `https://party.avrana.net/party/`. QR 2 never carries a query or fragment, so no token, device id
  or name can be put in it; the tool refuses any other host, a game origin, or plain HTTP to the
  Full Mode name.
- prints the network name, password and typed address under the codes, and the fixes for the known
  failures (no-internet prompt, VPN/Private DNS, mobile data, captive mini-browser, Chrome's Local
  Network prompt on iPhone).
- refuses to write a card with the password inside any Git working tree (or if git cannot run), and
  never prints the password.
  The card itself contains it: keep it with the box, do not commit, post or photograph it.
- **Password changed?** Generate and print a new card (the same `--out` path is replaced); the card
  shows the date it was printed.
- QR 1 uses `T:WPA`, right for WPA2-Personal and WPA2/WPA3 transition, not a WPA3-only access point.

`--party-only` makes a card with only QR 2 and no password (for a screen, a chat, or a second card).
QR 2's target is decided (owner, 2026-10-19, AVR-76): `https://party.avrana.net/party/` is the
canonical destination. `http://10.42.0.1` is the documented recovery fallback, printed on the card;
`--party-url http://10.42.0.1/` makes a recovery card that targets it. It resolves under every DNS
condition but adds a tap, and today it only links on to Full Mode.

## Real-phone check

Run with the Pi's upstream disconnected (truly offline), after an approved deploy, with the printed
card. Phones: at least one iPhone (Safari) and one Android (Chrome); ideally also a Samsung and an
Android 10/11. Start each phone **not** joined to the Party Wi-Fi ("Forget this network" first).
Record per phone: model, OS version, browser, mobile data on/off, VPN/Private DNS state, Party commit
(`/party/version.json`). Use a stopwatch from the first scan. Write PASS / FAIL / NOT RUN and what
the phone actually showed.

| # | Do | Expect / record |
|---|---|---|
| 1 | Scan QR 1 with the Camera (Android: Camera, else Wi-Fi settings › QR icon) | Join prompt names the network; one tap joins; no password typed |
| 2 | Watch for a system prompt | iPhone: none expected. Android: "no internet" notice; record the exact wording and whether "Stay connected" was needed |
| 3 | If a captive mini-browser or sign-in sheet opens | Record it. Close it; do not play inside it |
| 4 | Scan QR 2 with the Camera | Opens in the default browser (record which) at Party Home; no certificate warning; time to Party Home |
| 5 | Mobile data **on**, repeat 1–4 with a forgotten network | Does QR 2 still load, or does traffic leave over mobile data? |
| 6 | VPN on, then Android Private DNS set to a hostname, then iCloud Private Relay on | Expected failure: the name does not resolve. Does the card's fallback (`10.42.0.1`, then *Open Avrana Party*) get the guest in? |
| 7 | Type the printed address by hand instead of scanning | Same Party Home, same profile (not a second person) |
| 8 | Close the browser, lock the phone 2 minutes, reopen the tab | Party Home resumes the same person, no rejoin |
| 9 | Walk out of range and back | Phone rejoins the Party Wi-Fi on its own; page recovers |
| 10 | Chrome on iPhone (not Safari) | Local Network prompt shown? Party loads after "Allow"? Record "Don't allow" behavior |
| 11 | Lab only, a throwaway card for a test network whose password is all digits (e.g. `12345678`) | QR 1 still joins on both phones; some parsers mishandle digit-only or hex-looking passwords |
| 12 | First-timer with no help, card only | Seconds from first scan to Party Home; number of questions asked |

Real-device acceptance is pending under AVR-11 and AVR-295; record per-device results there, with
dates. A FAIL is a
finding, not a reason to change the access point, probes or DNS without the owner.
