# Native Pokerist table reader

The Steam game installed on this machine is a 64-bit Unity IL2CPP client running
under Proton. `PokeristReader` reads its local state without attaching a debugger,
injecting code, altering memory, or changing game actions. The supported platform
is Linux with access to the game process's `/proc/PID/maps` and `/proc/PID/mem`.
The memory file is opened with `O_RDONLY`.

## Discovery and pointers

The reader identifies `Texas Poker.exe` and obtains its installation from the
process working directory. It parses
`Texas Poker_Data/il2cpp_data/Metadata/global-metadata.dat`, resolves class-name
pointers in the mapped metadata, and validates live `FieldInfo` records against
field names and tokens in that file. It then scans for live `Poker2D` or `Poker3D`
objects and follows their inherited `Poker.<State>k__BackingField`.

Selecting an arbitrary `PokerTableState` object is unreliable: the process retains
old states. Discovery instead validates the owner, Unity native pointer, initialized
status, closing/destroyed/replay flags, `Session` type, and matching session/state
table IDs. Ambiguous live owners cause an error rather than choosing one silently.

In the observed session the owner was `0x12b2d1540`, and its state field at `+0x368`
pointed to `0x7c2b6ee0`. These addresses apply only to that running process.
`poker-analyze --inspect` reports newly discovered addresses and game field offsets.
GameAssembly-relative static offsets are not required.

Game field offsets are discovered dynamically, while the 64-bit Unity class,
field-record, string, list, and array layouts are implementation-specific. The
runtime layout was verified with Unity 6000.0.75f1 and metadata v31. The metadata
parser accepts v29/v31, but acceptance alone does not establish compatibility
with every game build. A client update may require changes to `runtime.py`.

## Observation fields

| JSON value | Client source / meaning |
| --- | --- |
| `table_id` | `PokerTableState.DeskID`, checked against `TableInfo.ID` |
| `game_id` | `TableInfo.GameUID`, the client's game identifier; not a hand counter |
| `seats` | `SeatPlaces`, global place IDs; a five-seat table used `[1,3,5,7,9]` |
| `dealer_seat` | `DealerPlace`; zero becomes `null` |
| `acting_seat` | `Current`, a global place ID; zero/no hand/result becomes `null` |
| `acting_player_id` | The player whose `Place` matches `acting_seat` |
| `players[].id/name` | `PlayerInfo.m_ID/m_Nick` |
| `players[].stack` | `PlayerInfo.DAmount`, chips at this table |
| `players[].bet` | `PokerPlayerInfo.TableAmount`, the player's current street contribution |
| `players[].folded/sitting_out/playing/cards_count` | Corresponding `PokerPlayerInfo` fields |
| `players[].has_timer` | Render model timer flag, supplementary to the state acting seat |
| `spectating/spectators` | `Session.Spectate` / `PokerTableState.Spectators` |
| `board` | `PokerTableState.Cards`, decoded from each `CardInfo.Suite/Value` |
| `hero_id` | Local `PlayerManualPoker` model's info ID; `null` when spectating |
| `hero_cards` | `PokerTableState.PrivateCards`; empty when spectating |
| `collected_pot` | `PokerTableState.TableMoney` |
| `street_bets_total` | Sum of observed players' `TableAmount` |
| `pot_total` | Derived `TableMoney + sum(TableAmount)`; both components remain available |
| `small_blind` | `SmallBlindAmount` |
| `street/stage` | Board length and game/result flags |

The combined pot treats `TableMoney` as already collected chips and `TableAmount`
as contributions still on the felt. That interpretation follows the client model
and observed round transitions; it has not been compared against a screen reading.
During chip movement or payout animations, these client amounts may be transient.
There is no side-pot allocation or payout model yet.

The separate `PlayerInfo.m_Amount` is an account balance and is not read. Account
credentials, contact information, chats, and opponents' hidden card data are not
part of the observation. This interface describes the current table, not the
complete lobby browser or every server-side table.

Card enum values are decoded by their metadata names. Standard ranks/suits receive
codes such as `As` and `Td`. Unknown, hidden, or special cards have `code: null`;
they are not assigned a guessed identity. `CardInfo.ID` is retained for diagnosis
but is not used to derive the rank/suit (it was zero for observed board cards).

`--window` reports the full game's X11 window bounds when available. It does not
locate the felt within that window or perform screenshot/OCR analysis. The state
reader works when other windows cover the game.

## Consistency and calculator integration

Lists are checked for size/version changes. Snapshots re-read the table header,
session/owner chain, player rows, and cards and retry if they change. This reduces
torn reads but cannot provide an atomic snapshot of a running game without its
cooperation. Short-lived animation/transitional states can still be observed.
An invalidated owner triggers rediscovery within the same process. Restarting the
game requires restarting the reader.

`TableObservation.to_game_state()` requires an active Texas Hold'em personal hand,
two resolved hero cards, a legal board, and active opponents. Folded opponents are
excluded. The calculator uses uniform legal unknown holdings; it does not use
hidden opponent cards, infer opponent ranges, model future folds, or account for
unequal side-pot eligibility. It rejects spectators and incomplete or duplicate
cards. Showdown/result animations cannot create a calculator state.

```python
from texasholdem.analyzers.native import PokeristReader
from texasholdem import EquityCalculator

with PokeristReader() as reader:
    observation = reader.read()
    print(observation.as_dict())
    try:
        state = observation.to_game_state()
    except ValueError as error:
        print(error)  # For example, no personal hand while spectating.
    else:
        print(EquityCalculator().calculate(state, simulations=10_000).as_dict())
```

`poker-analyze --watch` writes one JSON object per line. `--samples` limits the
number of observations. `--equity` includes a calculation or an explicit
unavailable reason; identical calculator states reuse the prior result.
Watch errors stop with an explanatory message; they do not silently emit stale
data. `Ctrl+C` closes the read-only memory handle.

## Validation

Live spectator validation captured 120 consecutive snapshots over 30 seconds,
pre-flop/flop transitions, changing stacks/bets, and acting-seat changes across
four occupied seats. A separate live snapshot resolved a complete five-card board
and a showdown pot. The local window was located at `(0,0)` with size `2560x1440`.
Validation exports are stored in ignored `artifacts/native/`.

Unit tests cover binary metadata/enums, bounded collection traversal and mutation,
read-only process memory, UTF-16 names, typed card decoding, snapshot-to-equity
validation, folded-player exclusion, and CLI JSON streaming. Personal-card
extraction has synthetic coverage; it has not been verified live while seated.
