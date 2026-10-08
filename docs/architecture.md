# Calculation engine and future AI integration

The library is the primary interface. The CLI only parses input and formats
results, so a future agent can call the same engine without launching a process.

```text
src/texasholdem/
  core/             Card, GameState, hand ranking, showdown resolution
  calculators/      counting, enumeration, sampling, equity, hand distributions
  analyzers/native/ local Pokerist process/metadata/runtime and table extraction
  dashboard/        observation service, analysis, HTTP API, visual frontend
  models/           serializable Deal, EquityResult, HandDistributionResult
  interfaces/       CLI input and reporting
  __init__.py       supported public imports
  __main__.py       python -m texasholdem
tests/
  core/             rules, kickers, state validation, independent ranking oracle
  calculators/      allocation coverage, exact equity, uniform sampling, draws
  interfaces/       JSON reports, exports, CLI errors
  native/           native layouts, bounded reads, observation extraction
  dashboard/        visual analysis, worker consistency, local HTTP API
examples/           per-street calculation and AI observation construction
scripts/            exhaustive full-deck evaluator validation
docs/               architecture and probability assumptions
```

The local [visual dashboard](dashboard.md) uses the same calculation engine.
Its reader and calculation workers are separate, and the web API exposes the
current observation independently of whether a personal hand is available.

`GameState` copies its inputs into tuples and checks all known cards together.
Hero, board, known opponent cards, and dead cards must be mutually disjoint.
Opponent seats accept zero, one, or two known cards. Missing seats are unknown.

`iter_complete_deals` streams allocations. Each opponent seat is distinct and
cards within a hand are unordered. Exact equity visits every allocation and
reuses hand ranks within the current board. Monte Carlo draws all missing cards
without replacement, then assigns them to the board and seats. Neither engine
stores the complete outcome space.

The evaluator counts ranks and suits directly for five through seven cards.
The public evaluator validates its input; the calculation loop uses the same
ranking implementation after `GameState` validation. The `best_five` helper
returns one winning five-card subset when a UI needs to display it.

## Connecting an agent

See `examples/ai_integration.py` for a JSON-compatible observation. Use numeric
properties directly for model features; retain `mode`, `trials`, and the confidence
bounds so an agent can distinguish estimates from exhaustive calculations.
Seed simulations for reproducible experiments. Independent seeds are appropriate
when measuring variability across repeated experiments.

Unknown opponents currently have uniform legal holdings, rather than inferred
ranges. A betting agent also needs action history, position, legal actions,
pot and stack sizes, contribution and side-pot handling, and an opponent model.
Those belong in additional game/agent modules; showdown equity alone does not
choose a profitable betting action. Ranges would require weighted allocations
and weighted sampling conditioned on card removal.
