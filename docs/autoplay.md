# Autonomous Pokerist play

Run `poker-dashboard --autoplay`, or click Start autoplay in the local dashboard.
Pokerist must be running on Linux/Steam Proton with X11, and you must be seated
in Texas Hold'em. Start can precede the game; the controller waits for discovery.
The current adapter was tested against Unity 6000.0.75f1 / IL2CPP metadata v31,
using the windowed 2D layout. Other client versions, native Windows, Wayland,
and the 3D UI require adapter validation.

## Strategy and modules

`agents/strategy.py` routes the default hybrid policy.
`agents/policy.py` rollout remains available with settings `strategy="rollout"`;
`strategy="hybrid"` is the default: CFR+ on heads-up rivers, range rollout
elsewhere. `strategy="search"` opts into experimental multi-street search outside
the heads-up river solver. The larger search has not cleared the performance gate. The dashboard lets you choose either before
starting a session or through Apply settings during play.

- `search/river.py`: alternating vector-form CFR+, positive cumulative regrets,
  linear strategy averaging, separate regrets for every board-legal holding,
  mixed action selection, and exact best responses inside the restricted tree.
- `search/ranges.py`: board-specific public action likelihoods, draw features,
  smoothed opponent profiles, a uniform uncertainty component, exact river
  blocker arithmetic, and whole-deal rejection sampling of joint holdings.
- `search/betting.py`: public no-limit continuation state; clockwise action,
  street transitions, big-blind option, full raises and short all-ins.
- `search/rollout.py`: preflop/flop/turn and multiway search through subsequent
  betting streets, including counter-raises. Candidate actions share sampled
  deals and rollout features. Paired differences reduce comparison variance.
- `agents/opponents.py`: observed action events (including hero actions), the
  board/price when each action happened, public statistics, and chip ledger.
- `agents/pots.py`: main/side pots, split payouts and uncalled chips.
- `agents/objectives.py`: chip utility and simulation-uncertainty preferences.
- `agents/sizing.py`: one shared native action menu, scaled to pot and stacks.
- `agents/benchmark.py`: offline convergence and paired arena evaluations.
- `agents/controller.py`: execution, cancellation, limits and acknowledgments.

### Playing objectives and automatic bet sizes

`objective="profit"` is the default: maximize estimated expected chips. Rollouts
rank candidates by mean chip return. On heads-up rivers, CFR+ supplies the
opponent's average strategy and continuation values; the bot selects the action
with the largest conditional chip value. This greedy root response can be more
exploitable than sampling the mixed strategy. Neither estimated ranges nor the
assumed opponent strategy are guaranteed to match actual opponents.

`objective="balanced"` samples CFR+'s average mixed strategy on heads-up rivers.
Elsewhere it subtracts one simulation standard error from estimated chip EV.

`objective="conservative"` uses terminal utility
`u(x) = x - min(x, 0)^2 / (2 * max(1, current_stack))` and subtracts two standard
errors of that utility. A possible loss consumes more utility at a short stack.
Hybrid uses this risk-adjusted rollout on every street; experimental search
applies the same utility to full continuation outcomes. It does not reinterpret
the constant-sum CFR+ gap as a risk-averse solution.

The shared bet menu includes the smallest and largest eligible native amounts,
pot fractions, and (for profit/conservative) preflop blind-based sizes and bets
scaled to the largest contestable opponent stack. Profit considers overbets;
conservative considers smaller fractions. All-in is a candidate, not an
instruction. Every size is snapped to the client's available steps and checked
against the actual stack, native bounds and any optional user cap. This is a
discrete sizing abstraction, not a search of every integer chip amount.

These objectives change chip utility and action selection; they do not convert
Pokerist chips into cash or guarantee winnings. No outside account balance,
rake, tournament ICM or cash-bankroll model is available.

### Heads-up river

When exactly two players remain and contributions are known, the solver uses
all 1,081 combinations compatible with the five board cards for each player's
public range. The hero's actual cards select the final strategy row; they are
not revealed to the opponent's strategy. Terminal values remove incompatible
card pairs exactly. Folded contributions remain in pot accounting.

The root uses native legal buttons and selectable amounts. Later nodes use
half-pot, pot and all-in sizes, with at most two further raises on this street.
The hero's chip-per-move limit also restricts continuation actions. These limits
change the game being solved; a low cap can be strategically exploitable.
With the balanced objective, the selected action is sampled from the average
strategy. Profit selects the largest conditional action EV. UI percentages are
**action frequencies**, not showdown win probabilities; profit selection is
deterministic. `solver_probability` retains the solver's underlying mixture.

`nash_conv_chips` is the sum of both players' unilateral best-response gains
against the average profile, calculated exactly for the supplied ranges and
restricted river tree. It is not an estimate of full-game exploitability, a
confidence interval, a profit promise, or a safe-resolving guarantee. No blueprint
counterfactual values are available, so this is not safe continual resolving.
Profit decisions use method `river-cfr+-ev` and rename this diagnostic to
`solver_nash_conv_chips`, displayed as Solver baseline gap: it describes the
mixed baseline, **not** the greedy root response actually selected.

### Experimental multi-street search (`strategy="search"`)

The default continues using the original check-down rollout outside heads-up
rivers. The following describes the opt-in experimental continuation engine.

Unknown hands are drawn from the product of estimated ranges, conditioned on
card removal by rejecting the entire conflicting deal. The simulator plays out
future streets, checks, bets, calls, folds and counter-raises. Each simulated
actor sees only its own holding and the currently exposed board. Its cheap
uniform-opponent equity feature samples independent runouts; it never peeks at
the episode's actual future board or another player's sampled private cards.

Continuation play is a heuristic model, tested under three nearby population
strength assumptions. Actions use paired value differences against the passive
choice using the chosen objective's utility and uncertainty margin.
`model_spread_chips` shows sensitivity to
those assumptions; it does not bound model error. Fewer than 24 completed deals
uses check/fold. No neural policy, trained blueprint, equilibrium claim, rake or
ICM model is involved. Full nonlinear joint beliefs from poker self-play are
not available.

### History and incomplete observations

Polling does not recover a complete server hand history. The tracker infers
unambiguous actions, includes final calls/checks at street transitions, and
records the board at the time, so a river improvement cannot explain an earlier
flop raise. Hero actions also condition the hero's public range. Missed actions
remain a source of range error. Likelihoods are deliberately softened instead
of excluding every hand that looks unlikely under a heuristic.

Attaching after chips enter the collected pot leaves the contribution ledger
incomplete. The policy checks/folds until the next complete hand. Unexplained
ledger discrepancies also disable spending for that hand. The dashboard's
separate general calculator still uses uniform opponents and showdown odds.

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
If the raise panel disappears mid-selection, the unconfirmed decision is
cancelled and the next live turn is re-evaluated; missing UI values are never
compared to chip amounts or confirmed.

Only one betting action can await acknowledgment. Calls/raises require the
corresponding stack/wager change, folds require a folded state, and checks require
the actor to advance. A round/result transition also completes acknowledgment.
A six-second timeout stops autoplay rather than replaying the input. Stop
invalidates pending decisions and queued actions; a mouse event already sent
cannot be undone. Native snapshots are consistency-checked, not atomic.

Defaults: profit objective, 3,000 samples, two seconds of planning, **no per-move,
session-loss or hand-count cap**. Each optional cap is represented as JSON `null`
or a blank dashboard field; positive integers enable it. The actual stack and
native table rules always bound an action. The optional loss check uses
the remaining stack plus known committed chips and is applied at preflop.
Partial initial-hand contributions can make that baseline approximate. Table
changes and lost connections stop the session. No seat purchase/rebuy or chip
store flow is automated. Manual moves pause autoplay and bypass its spending
limits because their amount is chosen directly by the operator.

`POST /api/bot/settings` updates settings during a session with a matching
`expected_generation`, cancels planning under the old settings, and preserves
the session ID, baseline, hands, actions and history. It never enables a stopped
bot and rejects changes while a betting action awaits confirmation. The UI's
Apply settings button uses this endpoint. `--objective profit|balanced|conservative`
selects the initial CLI objective; `--autoplay` enables continuous play on launch.

Audit records are local JSON Lines in `exports/autoplay/`, containing the
public table observation, inferred public action history, hero/board, candidates,
solver diagnostics, selected action, and input result. Submission and acknowledgment/failure are separate events with matching
action and session IDs, so interrupted sessions still retain sent actions.
They are ignored by Git. Public opponent statistics are session-local; no
persistent trained checkpoint or account credentials are stored.

## Research and performance claims

See [the research assessment and reproducible measurements](strategy_research.md).
The recorded v0.6.0 arena results predate the v0.7.0 objective and sizing changes
and do not validate the new default. `poker-benchmark arena --objective profit`
compares the current hybrid and rollout using the same objective. Its v3 output
records that objective explicitly; short smoke runs verify operation, not strength.
The upgrade implements specific research algorithms and their diagnostics;
it does not bundle the original Pluribus, ReBeL, or third-party trained models.
The `decide(frame, tracker, settings, cancelled)` interface remains replaceable.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/validate_dashboard.py
.venv/bin/python scripts/validate_bot_dashboard.py
```

Unit checks additionally compare blocker sweeps to independent enumeration, verify
river best-response convergence and constant-sum payoffs, exercise random betting
continuations at 2/3/6/9 seats, and check board-conditioned history. They cover main/side pots, tied and uncalled chips, known river outcomes,
action caps, incomplete histories, street transitions, stale turns, Stop during
planning/native reads, duplicate-action prevention, call acknowledgment, native
UI wrapper traversal, visibility, deferred toggles, and viewport scaling.
The browser checks exercise bot controls against intercepted fixture responses,
so they never submit test moves to a live game. Live integration is assessed
separately from the bot's native acknowledged-action log.
