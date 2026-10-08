# Texas Hold'em calculator and Pokerist analyzer

A Python calculation engine for a future poker AI. It counts and streams every
legal combination and calculates showdown win, tie, loss, and split-pot equity
at pre-flop, flop, turn, and river. Supports 1–9 opponents, fully or partially
known opponent cards, and dead cards.

Python 3.10+. The calculator has no runtime dependencies. The optional native
Pokerist analyzer uses NumPy and reads a locally running Linux/Steam Proton client.

## Open the visual dashboard

```bash
cd /home/jeremias/texasholdembot
.venv/bin/python -m pip install -e '.[native]'
.venv/bin/poker-dashboard
```

This starts a local website at **http://127.0.0.1:8765** and opens it in your
browser. Keep the terminal running; Ctrl+C stops it. The dashboard shows the
live table, occupied/open seats, dealer and acting player, stacks and bets,
community cards, your hole cards, pot components, and observed round updates.

When you have an active personal hand, it automatically displays win/tie/loss
probabilities, split-pot equity, confidence bounds, possible deal counts, and
all nine final hand-category probabilities. Exact results and estimates are
labeled separately. Spectator mode shows an explicit empty personal hand.
The **What if** tab calculates a separately entered hand while the live table
remains visible. Scenario results are labeled and never alter game state.

Pause/resume updates, expand player details, and export the current observation
as JSON. The layout works on desktop and mobile. The server reconnects if the
game closes or you switch tables; it can start before Pokerist is running.

```bash
# Choose another port; start without opening the browser.
.venv/bin/poker-dashboard --port 8766 --no-browser

# Increase the sample count for live estimates (up to 50,000).
.venv/bin/poker-dashboard --simulations 25000

# Module entry point, also available without installing the command.
.venv/bin/python -m texasholdem.dashboard
```

The web interface uses local HTML/CSS/JavaScript and Python's standard library;
no frontend build, hosted account, or external asset service is needed. See
[dashboard architecture](docs/dashboard.md) for the API and validation commands.

## Read the live Pokerist table

Start Pokerist and enter a table as a player or spectator, then run:

```bash
cd /home/jeremias/texasholdembot
.venv/bin/python -m pip install -e '.[native]'

# Current table, players, stacks, bets, acting seat, dealer, pot, and board.
.venv/bin/poker-analyze

# Stream JSON Lines for the future AI; Ctrl+C stops the reader.
.venv/bin/poker-analyze --watch --interval 0.5

# Discover the current pointers and include the game window's location.
.venv/bin/poker-analyze --inspect --window

# Calculate equity automatically when seated with an active personal hand.
.venv/bin/poker-analyze --equity --seed 42

# Save 100 observations.
.venv/bin/poker-analyze --watch --samples 100 --output artifacts/table.jsonl
```

Without the installed command, use
`.venv/bin/python -m texasholdem.interfaces.analyzer_cli` with the same options.
Use `--pid` or `--table-id` when the client has multiple matching processes/tables.

The analyzer reads the game's IL2CPP table model through `/proc/PID/mem`, opened
read-only. It locates the live table owner and discovers game field offsets from
the installed metadata and runtime reflection records. Addresses are rediscovered
on each launch. It does not send actions to the game.

**Spectators have no personal cards.** Spectator observations contain
`hero_id: null` and `hero_cards: []`. The private-card path is implemented for a
seated player, but the current live validation was performed as a spectator.
`--equity` returns an explicit reason when a personal hand is unavailable.

This reader was verified on the local Steam/Proton Pokerist client using Unity
6000.0.75f1 and IL2CPP metadata version 31, in its 2D table view. The 3D owner is
also recognized but has not been tested live. Other client builds may require
runtime-layout changes. See [native reader details](docs/native_reader.md) for
field meanings, snapshot consistency, limitations, and the discovered pointer chain.

## Run immediately

From the project directory, without installing:

```bash
cd /home/jeremias/texasholdembot
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c" --seed 42
```

Cards use rank then suit: `As Kh Td 2c` (spades, hearts, diamonds, clubs).
`10d`, lowercase ranks, and comma-separated cards are also accepted.

To install the command in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/poker-calc --hero "As Ah" --board "Ks 7d 2c 9h" --json
```

## Calculate at any street

```bash
# Pre-flop: automatic mode estimates equity against two unknown opponents.
PYTHONPATH=src python3 -m texasholdem --hero "As Kh" --opponents 2 --seed 42

# Flop: exact percentages of every final hero hand category.
PYTHONPATH=src python3 -m texasholdem --hero "Ah Kh" --board "Qh 2h 9c" --distribution-only

# Turn: exhaustively evaluate every board and unknown opponent holding.
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c 9h" --mode exact

# River: exact showdown against one known and one unknown opponent.
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c 9h 3s" --opponents 2 --villain "Kh Kd"

# Exclude exposed folded cards, and supply one known opponent card.
PYTHONPATH=src python3 -m texasholdem --hero "As Kh" --board "Qs Jh 2c" --villain "Ad" --dead "7c 8c" --seed 42
```

Use `--json` for machine-readable state, possibility counts, probabilities,
hand categories, and uncertainty. `--counts-only` counts the entire search space
instantly without evaluating hands. Run `--help` for all options.

Unknown opponents are modeled as uniform legal holdings. These are **showdown**
probabilities with all players remaining in the hand. Pot equity includes the
correct share of multi-way ties.

## Exact results and estimates

`--mode auto` (default) exhaustively evaluates up to 200,000 deals and uses
100,000 Monte Carlo samples for larger spaces. A heads-up river has 990 deals;
a heads-up turn has 45,540; pre-flop has 2,097,572,400.

`--mode exact` enumerates every allocation. For a larger computation, explicitly
add `--allow-large-exact` or change `--max-exact-trials`. Full pre-flop enumeration
is supported but very expensive. `--mode monte-carlo --simulations 500000 --seed 42`
selects a reproducible estimate. Sampled equity includes a conservative 95% bound.
Every result states whether it is exhaustive or sampled.

## Enumerate and export combinations

Listings stream JSON Lines with a default limit of 25. Use `--limit 0` to
export every row; full deal exports can be extremely large.

```bash
# All 46 possible rivers from this turn.
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c 9h" --list runouts --limit 0

# Current legal holdings for the first opponent.
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c" --list opponents

# Export every river allocation with winners and hero's pot share.
mkdir -p exports
PYTHONPATH=src python3 -m texasholdem --hero "As Ah" --board "Ks 7d 2c 9h 3s" --list showdowns --limit 0 > exports/river.jsonl
```

Other listings are `next-boards` (the next street) and `deals` (unlabelled complete
allocations). Opponent listing seats are one-based in the CLI, zero-based in Python.
Showdown winner seat 0 is hero; opponent seats are 1 through the opponent count.

## Python API for the future AI

```python
from texasholdem import (
    EquityCalculator, GameState, HandDistributionCalculator,
    count_complete_deals, iter_complete_deals, parse_cards,
)

state = GameState(
    hero=parse_cards("As Kh"),
    board=parse_cards("Qs Jh 2c"),
    opponents=2,
    opponent_hands=(parse_cards("Ad"), ()),
    dead_cards=parse_cards("7c 8c"),
)

result = EquityCalculator().calculate(state, simulations=100_000, seed=42)
print(result.win_percentage, result.equity_percentage)
print(result.equity_95_interval)
observation = {"state": state.as_dict(), "showdown": result.as_dict()}

# Board-only hand distribution is exhaustive on flop/turn/river in auto mode.
distribution = HandDistributionCalculator().calculate(state)
print(distribution.category_percentages())

# Count instantly, or consume the stream without storing every deal.
print(count_complete_deals(state))
first_deal = next(iter_complete_deals(state))
print(first_deal.as_dict())
```

Public helpers also include `evaluate`, `evaluate_five`, `best_five`, `showdown`,
`possible_board_runouts`, `possible_next_boards`, `possible_opponent_hands`,
`possible_hole_cards`, and `sample_deals`.

## Organized structure

```text
src/texasholdem/
├── core/          # cards, immutable game state, rankings, showdown
├── calculators/   # counting, enumeration, sampling, equity, distributions
├── analyzers/
│   └── native/    # process, metadata, runtime, collections, table reader
├── dashboard/     # live service, analysis, local HTTP API, visual frontend
├── models/        # serializable deal and result objects
└── interfaces/    # calculator and analyzer command-line interfaces
tests/
├── core/
├── calculators/
├── native/
├── dashboard/
└── interfaces/
examples/          # equity by street; AI/native observation integration
scripts/           # exhaustive evaluator verification
docs/              # architecture and probability model
```

See [architecture](docs/architecture.md) and [probability model](docs/probability_model.md)
for extension points and assumptions. An agent's betting policy, opponent ranges,
action history, and pot/stack model can be added as separate modules.

## Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/validate_evaluator.py
PYTHONPATH=src python3 examples/equity_by_street.py
PYTHONPATH=src python3 examples/ai_integration.py
```

Tests compare five-, six-, and seven-card rankings against an independent
five-card oracle; verify exhaustive multi-seat allocations against permutations;
check exact and sampled equity, exclusions, ties, draw probabilities, and CLI
exports. The validation script checks all 2,598,960 five-card hands against
category counts derived combinatorially.
