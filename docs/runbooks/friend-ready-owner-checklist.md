# Owner checklist: four phones, offline, one night (about 60 minutes)

Short form of [friend-ready-acceptance](friend-ready-acceptance.md) and
[physical-check-avr-475-476](physical-check-avr-475-476.md). Evidence so far and the reasoning:
[the 2026-10-15 matrix](../findings/2026-10-15-friend-ready-acceptance-matrix.md). Nothing here is
done by an agent; tick each box yourself and write PASS / FAIL / SKIPPED beside it.

## Before the night (needs your yes, one time)

- [ ] **Deploy Party `main` (Games stays `bd7e01d`)** with `ops/deploy.sh` and the explicit 40-character
      Party SHA, dry run first ([deploy](deploy.md)). This is the only way the abandoned-table and
      Host-escape fixes reach the Pi. Afterwards `https://party.avrana.net/party/api/status` shows
      `summary: ok` and the new Party SHA. *Write the SHA here:* ______________
- [ ] Have: the Pi with its power supply, **four phones** (at least one iPhone with Safari and one
      Android with Chrome), a laptop on the home network for the status page, a timer, a pen.
- [ ] On every phone: turn mobile data **off** and forget any VPN. Note model and OS version.

## The night

| # | Do this | Pass if | Issue if it fails |
|---|---|---|---|
| 1 | Unplug the Ethernet cable, then power the Pi off and on. Start the timer | The Party Wi-Fi appears within about 2 minutes, with no keyboard or screen | AVR-10 |
| 2 | On phone A, join the Party Wi-Fi. Open the camera/QR or the browser as printed on the join card | The Party page opens in the normal browser; no password typed besides Wi-Fi; no app | AVR-76 |
| 3 | Phones B, C, D do the same, all four connected at once | All four show Party Home and their name; nothing says "no internet" in a way that blocks you | AVR-12 |
| 4 | Phone A (the Host) opens BLUFF and starts it. Others tap ready | All four land on the table; each sees only their own cards | AVR-27 |
| 5 | Play BLUFF to the end **without help**. Note anything anyone asks you | A winner is shown; you were not needed | AVR-27 |
| 6 | Mid-game: lock one non-Host phone for 20 seconds, then unlock | It returns to its own seat and cards | AVR-27 |
| 7 | After the game: Host taps to go home, then starts BLUFF again | A fresh round starts for all four | AVR-27 |
| 8 | (Optional) Mid-game on the Host: browser Back, then "Bring everyone back", then Keep playing | The Host reaches the Party's menu and the round continues | AVR-476 |
| 9 | (Optional) Close the game on all four phones and wait 7 minutes | The Party shows the game ended ("Everyone left the game"); the next person to open it can start a game | AVR-475 |
| 10 | Afterwards: `https://party.avrana.net/party/api/status` from the laptop on Ethernet | `summary: ok`; no throttling or under-voltage noted | AVR-10 |

## Write down, even if everything passes

- Date, the Party SHA from the status page, each phone's model, OS and browser.
- Time from power-on to the Party page opening on phone A: ______ s
- Any moment a player was confused, or asked what to do: ______________________
- Any moment you touched the Pi or a laptop during steps 2 to 9 (that counts as developer
  intervention): ______________________

## If something is red

Stop. Do not restart services. Photograph the phone screen, copy the status page, and put both on
the issue in the last column. [service-recovery](service-recovery.md) has the recovery steps if the
party must go on.

## GO / NO-GO

Rows 1 to 7 PASS on at least one iPhone and one Android phone: **GO** for friends. Any of 1 to 7 FAIL:
**NO-GO**; file it and send the notes.
