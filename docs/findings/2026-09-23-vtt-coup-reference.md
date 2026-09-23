# VirtualTabletop's "Diplomacy" is a Coup-style game: mechanical reference (2026-09-23)

**Source:** `ArnoldSmith86/virtualtabletop` (GPL-3.0) at `f02df19d`,
`library/games/Diplomacy/`. Despite the folder name, it's a Coup-style bluffing game: its
metadata points to Coup (BGG 131357, designer Rikki Tahta).

**Purpose:** a *reference point* for designing the first Avrana-native bluffing game. It's
not a spec, and none of its assets or text are reused.

## What the VTT files actually encode

**Only components and a table layout. There are no rules, automation or enforcement.**
The single routine is a "↺" reset (recall all cards, flip them face down, shuffle). The card
art is icons from game-icons.net (CC BY) with glyphs such as `+`, `&` and `→`, and there's no
rules text. Players do everything by hand and out loud.

| Variant | Players | Character deck |
|---|---|---|
| `0.json` | 2–6 | 3 each of Duke, Assassin, Captain, Contessa, "Embassador" (sic) |
| `1.json` "Inquisitor expansion" | 2–6 | the Ambassador is replaced by 3 Inquisitors |
| `2.json` | 7–8 | 4 of each |
| `3.json` | 9–10 | 5 of each |

The table has, per seat, two "Lives" slots and two "Treasury" slots. There's a central deck
and a discard area, and a coin supply of 24 crown-coins plus 5 gold coins. Two hand holders
use `childrenPerOwner`, so each player sees only their own cards.

## The Coup-style mechanics the table assumes (standard play)

1. **Setup:** each player has 2 face-down character cards (their *influence*) and starting
   coins. The rest of the deck is the draw pile.
2. **Private:** the identity of your own face-down cards.
3. **Public:** each player's coins, how many face-down cards they have left, revealed
   (lost) cards, every claim made, and whose turn it is.
4. **Turn:** the active player takes exactly one action. The others may challenge a claim
   or block. Play passes clockwise.
5. **Actions anyone can take:**
   - Income: +1 coin; can't be blocked or challenged.
   - Foreign aid: +2 coins; can be blocked.
   - Coup: pay 7 coins, target loses a card. It can't be stopped, and it's **mandatory at
     10 or more coins**.
6. **Character actions, all bluffable** (claim the card whether or not you hold it):
   - Tax (Duke): take 3 coins; the Duke also blocks Foreign aid.
   - Assassinate (Assassin): pay 3 coins, target loses a card.
   - Steal (Captain): take 2 coins from a player; the Captain also blocks stealing.
   - Exchange (Ambassador): draw 2, return 2; the Ambassador also blocks stealing.
   - The Contessa has no action; she blocks assassination.
   - The Inquisitor (variant): swap 1 card with the deck, or look at another player's card
     and optionally force them to swap it; also blocks stealing.
7. **Challenge:** anyone may challenge a claim.
   - If the claimer **holds** the card, they reveal it, shuffle it back and draw a
     replacement, and the challenger loses a card.
   - If they **don't**, the claimer loses a card and the action fails. An assassin's
     3 coins are still spent.
8. **Block:** the target (or anyone, against Foreign aid) claims a blocking character. A
   block is itself a claim and can be challenged the same way. If the block stands, the
   action fails.
9. **Losing influence:** the loser *chooses* which card to reveal face-up. It's permanently
   out.
10. **Currency:** a shared supply. Costs are Coup 7 and Assassinate 3; income is +1, +2 or
    +3; stealing moves 2 coins between players.
11. **End:** a player with no face-down cards left is eliminated. The last player standing
    wins.

## Implications for the Avrana version

- The VTT game shows the *components*. The Avrana server must own the entire rules state
  machine: claims, response windows, challenges, blocks and influence loss.
- The "respond or pass" windows are the hard UX problem on phones. They need clear
  prompts, and they must never stall the game.
- Hidden information is exactly each player's own cards, plus the cards drawn during an
  exchange. Everything else is public.
