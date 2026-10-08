# Texas Hold'em calculator, Pokerist dashboard, and autonomous bot

A Python calculation engine for a future poker AI. It counts and streams every
legal combination and calculates showdown win, tie, loss, and split-pot equity
at pre-flop, flop, turn, and river. Supports 1–9 opponents, fully or partially
known opponent cards, and dead cards.

Python 3.10+. The calculator has no runtime dependencies. The optional native
Pokerist analyzer uses NumPy and reads a locally running Linux/Steam Proton client.
The bot adds a range-weighted decision policy and ordinary X11 mouse input.

## Open the visual dashboard

```bash
git clone https://github.com/Jendaia/Pokerbot.git
cd Pokerbot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/poker-dashboard
```

For an existing checkout, run the installation command from its root directory.
`requirements.txt` installs the project and its NumPy dependency, including all
three commands. Live Pokerist reading requires Linux with the Steam/Proton client.

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

## Autonomous play and game controls

Enter a Pokerist Texas Hold'em table and take a seat. In **Your copilot**, click
**Start autoplay**. The default hybrid strategy solves heads-up rivers with
CFR+ and uses range rollout on other streets. The default **Maximize chip EV**
objective chooses the highest estimated chip return. Bets adapt to pot size,
available chips, opponents' effective stacks, and native legal amounts. An experimental
multi-street search option simulates later betting and counter-raises. It submits its selected fold/check/call/raise through the game.
**Stop** cancels pending planning and future clicks. Manual Fold, Check, Call,
and Raise controls pause autoplay and apply only to the displayed live turn.
Open Raise to read the game's minimum, maximum, and available bet steps; the
entered amount is **additional chips**, not the total street wager.

```bash
# Enable autoplay as soon as the dashboard connects to a seated player.
.venv/bin/poker-dashboard --autoplay --objective profit
```

The default has **no per-move, loss, or hand limit**: autoplay can use the whole
table stack and continues across hands. Leave each optional limit blank, or
enter a cap. Choose **Balanced** for mixed river strategies, or **Preserve stack**
to penalize large potential losses relative to your remaining chips. **Apply
settings** changes the objective or limits during the session without resetting
its results or restarting a stopped bot. Planning defaults to two seconds and
3,000 samples/iterations per decision. A table
change or lost live connection stops the session. Seat/buy-in and rebuy remain
under your control. Decisions and confirmed actions are saved locally to
`exports/autoplay/YYYY-MM-DD.jsonl` and shown in the dashboard.

Input requires the Linux Steam/Proton client running on X11, `xwininfo`, `xprop`,
`libX11`, and `libXtst`. On Ubuntu/Debian, the system packages are:

```bash
sudo apt install x11-utils libx11-6 libxtst6
```

The dashboard shows action frequencies, expected chip values, range equity,
and a convergence diagnostic for the restricted river solver. With the profit
objective, the solver's mixed-profile gap is labeled **Solver baseline gap**;
it does not measure the selected greedy policy. Chip EV is an estimate, not
guaranteed earnings. Range rollout and experimental multi-street search remain
selectable for comparison. Installation needs no trained-model
download, GPU, or API key; `requirements.txt` includes the solver dependency.

Playing strength is experimental. This is not a trained Pluribus/ReBeL model
or a proven state-of-the-art player. Ranges and continuation responses are
estimated, and the river solver restricts bet sizes and raise depth. See
[research and evaluation](docs/strategy_research.md) and [bot design](docs/autoplay.md).

Run offline checks without connecting to Pokerist:

```bash
.venv/bin/poker-benchmark river --iterations 400 --output artifacts/river.json
.venv/bin/poker-benchmark arena --players 6 --hands 120 --output artifacts/arena.json
```

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

After installation, start Pokerist and enter a table as a player or spectator,
then run these commands from the repository directory:

```bash
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
`hero_id: null` and `hero_cards: []`. Personal-card extraction has also been
verified live while seated, including changing hole cards and betting streets.
`--equity` returns an explicit reason when a personal hand is unavailable.

This reader was verified on the local Steam/Proton Pokerist client using Unity
6000.0.75f1 and IL2CPP metadata version 31, in its 2D table view. The 3D owner is
also recognized but has not been tested live. Other client builds may require
runtime-layout changes. See [native reader details](docs/native_reader.md) for
field meanings, snapshot consistency, limitations, and the discovered pointer chain.

## Run immediately

From the project directory, without installing:

```bash
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
├── agents/        # hybrid policy, history, pots, controller, offline benchmark
│   └── search/    # betting engine, ranges, CFR+ river solver, future-street rollouts
├── adapters/      # validated Pokerist actions and X11 mouse input
├── analyzers/
│   └── native/    # process, metadata, runtime, collections, table reader
├── dashboard/     # live service, analysis, local HTTP API, visual frontend
├── models/        # serializable deal and result objects
└── interfaces/    # calculator and analyzer command-line interfaces
tests/
├── core/
├── calculators/
├── agents/
├── native/
├── dashboard/
└── interfaces/
examples/          # equity by street; AI/native observation integration
scripts/           # exhaustive evaluator verification
docs/              # architecture and probability model
```

See [architecture](docs/architecture.md) and [probability model](docs/probability_model.md)
for extension points and assumptions. The betting policy is separate from game
observation and input, so a trained strategy can replace the rollout policy.

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
