# Party chat on real phones: owner checklist

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance or on a phone** (2026-10-16).
For the AVR-54 branch (Party-owned messaging). Desktop Chromium results do not count here.

**Setup.** The Pi running the AVR-54 build (deployed only with the owner's approval), the WAN
cable out, the Party Wi-Fi only. At least one iPhone (Safari) and one Android phone (Chrome),
ideally four phones. Record the phone, OS and browser version for each row.

| # | Do | Expect | iPhone | Android |
|---|---|---|---|---|
| 1 | Two phones join. A opens the Party control, then Chat, and sends "hello" | B's Party control shows **1**; B opens Chat and sees "hello" under A's Party name; the count clears | | |
| 2 | A sends six messages fast, then a seventh | The seventh says "Slow down a little"; the words stay in the box | | |
| 3 | The keyboard: tap the message box on each phone | The box and Send stay above the keyboard; nothing moves sideways; the last message is visible | | |
| 4 | Largest system text (iOS Larger Text, Android font size max) | Names and messages wrap; the composer and Close are reachable | | |
| 5 | VoiceOver / TalkBack: open the drawer, go to Chat, have the other phone send a line | The new line is read once, politely; focus stays where it was; closing returns to the Party control | | |
| 6 | Lock phone B for two minutes while A sends three lines; unlock B | B shows all three once, in order; the count says 3 | | |
| 7 | Turn B's Wi-Fi off for a minute while A sends; turn it on | "Reconnecting…", then the missed lines once each; no doubles | | |
| 8 | Reload Party Home on B | The room is still there; lines read before the reload are not counted again | | |
| 9 | Host starts BLUFF, plays a round, returns to Party Home | Chat history is intact; "BLUFF started" and "BLUFF ended" appear as the Party's own small lines | | |
| 10 | During the BLUFF briefing open the Party control | People only, no chat (rule 3.2 unchanged) | | |
| 11 | Names in another script and emoji (e.g. "Zoë", "李", "👨‍👩‍👧") | Shown intact; an emoji is not cut | | |
| 12 | If Limited Mode is enabled: a Limited phone joins | Its notice mentions the chat; Full phones' Chat says it is not private | | |
| 13 | Restart Party Core (owner, with care: it forgets everyone) | Phones rejoin; the old chat is gone; nothing old reappears as new | | |

Record: date, Party and Games SHAs, the phones, any row that failed and what it showed. Do not
mark AVR-54's phone criteria done from this sheet until every row has a result from a real phone.
