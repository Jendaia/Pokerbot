# Autonomous Pokerist play

Run `poker-dashboard --autoplay`, or click Start autoplay in the local dashboard.
Pokerist must be running on Linux/Steam Proton with X11, and you must be seated
in Texas Hold'em. Start can precede the game; the controller waits for discovery.
The current adapter was tested against Unity 6000.0.75f1 / IL2CPP metadata v31,
using the windowed 2D layout. Other client versions, native Windows, Wayland,
and the 3D UI require adapter validation.

## Modules

`agents/models.py` defines settings, actions, decisions, and the turn identity.
`agents/opponents.py` maintains smoothed public-action statistics, range
likelihoods, and a per-hand chip ledger. `agents/pots.py` distributes main and
side pots, tied payouts, and uncalled excess chips. `agents/policy.py` implements
bounded action-value rollouts. `agents/controller.py` owns the decision/input
worker, cancellation, limits, action acknowledgment, and local audit records.

`analyzers/native/controls.py` resolves live control models and their UI layout.
`adapters/pokerist.py` prepares, dismisses, selects, and confirms game controls.
`adapters/x11.py` sends ordinary XTest mouse events to a process-verified Pokerist
window and accounts for Proton borders and viewport scaling.

The calculator and read-only CLI still work without input libraries. NumPy is
the only Python dependency for native gameplay. `x11-utils`, `libx11-6`, and
`libxtst6` are system dependencies for the input adapter.

## Decision model

For each turn, the policy samples opponent holdings with card removal and range
weights derived from observed calls/raises. Preflop uses a rank/pair/suitedness/
connectivity prior; postflop uses made-hand percentiles among legal holdings.
Future boards are drawn uniformly from the remaining cards. These holdings are
hypotheses; hidden opponent cards are never read.

Candidate moves share sampled deals and response random numbers to reduce the
variance of comparisons. A smoothed opponent model estimates whether a player
will match a bet at a given price. Each candidate subtracts the hero's additional
cost from a simulated payout, with folded contributions and all-in caps included.
The ranking uses estimated chip EV minus one simulation standard error; raises
also reserve value for omitted counter-raises/equity realization before the river.
Fold has zero incremental EV, and checking costs no chips. Native minimum,
roughly one-third/two-thirds/pot sizes, and a capped all-in are considered where
available. Chip-per-action limits restrict voluntary calls and raises.

Simulations check down future streets. They do not solve equilibrium, search
complete future betting trees, model rake, use ICM, or learn a neural policy.
Weighted holdings are sampled sequentially with collision rejection; this is
an approximate multi-opponent range model, not a calibrated joint posterior.
Made-hand percentile likelihoods also underestimate some drawing hands. Sample
standard errors describe simulation noise, not opponent-model uncertainty.

Joining in the middle of a hand leaves past contributions uncertain. The policy
uses only check/fold until it observes a complete preflop chip ledger. The ledger
handles final calls moving immediately into the next street's collected pot;
unexplained discrepancies make the hand incomplete. The displayed general
calculator percentages remain uniform-opponent showdown odds; they are separate
from the policy's range equity and action-value estimates.

## Input and session behavior

The controller distinguishes instant actions from preselected check/fold/call
toggles. It verifies the game window's Steam class and process ID, brings it into
focus, and re-reads the turn before each click. The turn identity includes the
table, client hand counter, hero and board cards, actor, and every observed stack,
wager, and folded status. Changed decisions are discarded.

Raise opens the native panel without betting. The reader gets the current bounds
and available steps; +/- or All-in selects an amount, which is re-read before
confirming. Pokerist disables Call while that panel is open; a call first
dismisses it and verifies that the native Call button is enabled again. Non-native
amounts are rejected without confirmation. Selection has a time/step bound.

Only one betting action can await acknowledgment. Calls/raises require the
corresponding stack/wager change, folds require a folded state, and checks require
the actor to advance. A round/result transition also completes acknowledgment.
A six-second timeout stops autoplay rather than replaying the input. Stop
invalidates pending decisions and queued actions; a mouse event already sent
cannot be undone. Native snapshots are consistency-checked, not atomic.

Defaults: 3,000 samples, two seconds of planning, 1,000 additional chips per
move, a 2,000-chip session loss limit, and 100 observed hands. The loss check uses
the remaining stack plus known committed chips and is applied at preflop.
Partial initial-hand contributions can make that baseline approximate. Table
changes and lost connections stop the session. No seat purchase/rebuy or chip
store flow is automated. Manual moves pause autoplay and bypass its spending
limits because their amount is chosen directly by the operator.

Audit records are local JSON Lines in `exports/autoplay/`, containing the
public table observation, hero/board, candidates, selected action, and input
result. Submission and acknowledgment/failure are separate events with matching
action and session IDs, so interrupted sessions still retain sent actions.
They are ignored by Git. Public opponent statistics are session-local; no
persistent trained checkpoint or account credentials are stored.

## Research and performance claims

Strong multiplayer poker research combines self-play with a learned blueprint
and search, as described in the primary [Pluribus paper](https://noambrown.github.io/papers/19-Science-Superhuman.pdf).
[ReBeL](https://arxiv.org/abs/2007.13544) combines reinforcement learning and
search with theoretical results for two-player zero-sum games and demonstrated
heads-up poker performance. This project implements neither trained system.
It provides a replaceable `decide(frame, tracker, settings, cancelled)` policy
interface and an execution/data layer for future learning and evaluation.

There is no measured win rate, exploitability result, or state-of-the-art claim.
Correct arithmetic and successful GUI actions do not demonstrate playing
strength. A serious evaluation needs reproducible opponent pools, seat-balanced
matches, enough hands for confidence intervals, and comparison with strong
policies under the same stacks, blinds, rules, and compute budgets.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/validate_dashboard.py
.venv/bin/python scripts/validate_bot_dashboard.py
```

Unit checks cover main/side pots, tied and uncalled chips, known river outcomes,
action caps, incomplete histories, street transitions, stale turns, Stop during
planning/native reads, duplicate-action prevention, call acknowledgment, native
UI wrapper traversal, visibility, deferred toggles, and viewport scaling.
The browser checks exercise bot controls against intercepted fixture responses,
so they never submit test moves to a live game. Live integration is assessed
separately from the bot's native acknowledged-action log.
