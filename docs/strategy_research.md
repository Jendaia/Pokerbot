# Poker strategy research and evaluation — 0.6.0

Research checked 8 October 2026. This release adds a working, local river solver
and a measured strategy-development path. It does **not** establish SOTA playing
strength. No freely downloadable, validated superhuman multiplayer checkpoint
compatible with the current 2–9 seat Pokerist integration was established by
this search. Having public game state and hole cards supplies an observation
interface; it does not supply a trained strategy or complete betting history.

## Primary sources and implementation choice

| System | Evidence and availability | Decision for this project |
| --- | --- | --- |
| [Pluribus, Brown & Sandholm (2019)](https://noambrown.github.io/papers/19-Science-Superhuman.pdf) | Demonstrated professional-level six-player no-limit play using a self-play blueprint and real-time search. The paper explicitly withholds its source code. | Architectural reference; no original model or code was integrated. A repository using its name is not the original agent. |
| [ReBeL, Brown et al. (2020)](https://arxiv.org/abs/2007.13544) | Combines learning and search; demonstrated heads-up poker. The [official release](https://github.com/facebookresearch/rebel) contains Liar's Dice, not its poker agent. | No drop-in poker checkpoint. We implement a narrower range-versus-range river solve without a learned value network. |
| [DecisionHoldem](https://github.com/AI-Decision/DecisionHoldem) | Published heads-up agent with blueprint/search code and separately hosted binary data. Repository is AGPL-3.0 and describes a 48-core, 512-GB development workstation. | Heads-up format and deployment do not match a lightweight 2–9 player dependency. Did not bundle its code, compiled libraries or model files. |
| [NoRegrets](https://github.com/conorarmstrong/noregrets/tree/757f7692738069522195d2b486eec60a8b010c0c) | MIT Rust implementation for 2–6 players. Source at the inspected commit is public; trained artifacts are commercially licensed. Its [own measurements](https://github.com/conorarmstrong/noregrets/blob/757f7692738069522195d2b486eec60a8b010c0c/BASELINES.md) include search regressions and losses against Slumbot. | Reviewed the source and evaluation methodology. No source dependency, pretrained artifact or unverified binary is installed. Larger search must pass comparison tests before becoming the default. |

The implemented solver follows [CFR+ (Tammelin, 2014)](https://arxiv.org/abs/1407.5042):
alternating updates, regret matching with a zero floor, and weighted average
strategies. Counterfactual values and best responses consider every legal river
holding with exact card removal. The numerical code uses NumPy, already included
in `requirements.txt`; it requires no GPU, training download, or paid API.

The implementation is intentionally narrower than those research systems:
heads-up rivers only, estimated public ranges, restricted bet menus and raise
depth, no blueprint safety values. Solving that subgame does not solve the full
game. Its reported gap must never be advertised as full-game exploitability.
See [the strategy specification](autoplay.md) for the precise assumptions.

## Default selection

`hybrid` uses CFR+ on heads-up rivers and the original range rollout elsewhere.
`rollout` retains the original policy for comparisons. `search` opts into the
new multi-street simulator outside heads-up rivers. It includes later bets,
counter-raises, board-conditioned ranges and public-information response models.

The larger search was not promoted: its arena results did not establish a gain.
More elaborate simulation against a wrong opponent model can make play worse.
The default's new river algorithm has verified subgame convergence; its overall
playing-strength improvement is **unproven**. There is no claim that this release
beats Pluribus, ReBeL, Slumbot, professional players, or the previous bot overall.

## Reproduce the measurements

```bash
python -m pip install -r requirements.txt
poker-benchmark river --iterations 400 --output artifacts/river.json
poker-benchmark arena --players 3 --hands 120 --seeds 11,29,47 --output artifacts/hybrid-3p.json
poker-benchmark arena --players 6 --hands 60 --seeds 11,29,47 --output artifacts/hybrid-6p.json
poker-benchmark arena --players 3 --hands 60 --seeds 11,29,47 --strategy search --output artifacts/search-3p.json
```

These commands are offline: they neither connect to Pokerist nor send input.
The [recorded results](benchmarks/0.6.0.json) and [paired outcomes](benchmarks/0.6.0-arena.csv)
include seeds, package versions and the agent-source digest. Arena version 2 assigns a
full button orbit to each opponent style, avoiding a position/style confound.
Deals are reproducible; wall-clock compute limits can change the number of
completed samples/iterations and thus exact decisions across machines.

The river diagnostic uses eight positions: four board textures, each with and
without a bet to call. Each starts with asymmetric fixed ranges and solves for
400 iterations. Exact best-response gaps fell from **350–402 chips to
0.14–0.46 chips**, with constant-sum accounting correct to floating-point
precision. Those results concern only the restricted test trees and ranges.

The arena uses 100-BB stacks, rotating buttons, the same shuffled deals in each
policy pair, and fixed station/tight/aggressive opponents. Both policies get
200 samples/iterations and a 0.2-second decision ceiling. Profiles start fresh
each hand; this is a cold-start comparison, not a test of long-term adaptation.
There is no rake. Raw paired means and standard errors are stored in the JSON.

| Candidate | Players | Paired hands | Difference from original, BB/hand | Standard error |
| --- | ---: | ---: | ---: | ---: |
| Default hybrid | 3 | 360 | +0.182 | 0.461 |
| Default hybrid | 6 | 180 | −0.907 | 0.643 |
| Experimental multi-street search | 3 | 180 | −5.860 | 4.268 |

Positive means the candidate scored higher; the standard error is **not** a
95% interval. The differences do not establish an overall improvement.

These short matches are diagnostic, with substantial uncertainty and weak
scripted opponents. They are not a validated ranking. Extending this into a
strong multiplayer agent still requires a compatible trained blueprint or
learned continuation model, broader external opponents, longer seat-balanced
matches, and evaluation on realistic stacks and observed action histories.

## Correctness checks

The tests compare the blocker sweep against independent enumeration, verify
mixed-strategy convergence on a small known-range game, conserve chips through
random legal 2/3/6/9-player continuations, and check short all-in reopening,
unequal stacks, folded dead money, and uncalled refunds. Existing controller
tests cover cancellation, stale turns, duplicate suppression and acknowledgments.
Browser tests use intercepted control APIs, so test clicks never play a live hand.
