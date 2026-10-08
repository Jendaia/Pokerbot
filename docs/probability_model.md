# What the probabilities mean

The board contains 0, 3, 4, or 5 cards: pre-flop, flop, turn, and river. Every
calculation asks what happens at the completed five-card-board showdown given
only the information supplied at that street. Opponents stay in the hand.

## Exact possibility counts

Let `N` be 52 minus all known cards, including exposed opponent and dead cards,
and `m = 5 - len(board)`. The number of board runouts is `C(N, m)`.
After selecting a runout, each labelled opponent seat needs `k_i` unknown cards,
where `k_i` is 0, 1, or 2. The complete-deal count is:

```text
C(N, m) * C(N-m, k_1) * C(N-m-k_1, k_2) * ...
```

For one unknown opponent and no dead cards:

| Street | Board runouts | Complete deals |
| --- | ---: | ---: |
| Pre-flop | 2,118,760 | 2,097,572,400 |
| Flop | 1,081 | 1,070,190 |
| Turn | 46 | 45,540 |
| River | 1 | 990 |

Runouts are unordered sets of future community cards. From a flop, exchanging
the future turn and river gives the same final showdown and is counted once.
`possible_next_boards` exposes the next street when reveal order matters to a
consumer. Unknown burn cards are marginalized. Exposed unavailable cards should
be included in `dead_cards`.

Single-seat holding counts are marginal counts at the current street. Multiplying
them directly is incorrect because holdings cannot share cards. Complete-deal
enumeration enforces those exclusions between seats and future board cards.

## Win probability and equity

- **Win**: hero is the sole best hand.
- **Tie**: hero shares the best hand with at least one opponent.
- **Loss**: at least one opponent has a stronger hand.
- **Equity**: average fraction of an equally funded pot awarded to hero.

A two-way tie contributes `1/2` to equity; a three-way tie contributes `1/3`.
Consequently `win + tie / 2` is only valid for heads-up play. Suits never break
ties. The best five cards may use zero, one, or two hole cards.

Hero's hand-category percentages describe the final best five-card hand, not
the current hand and not necessarily a winning hand. A distribution calculation
can enumerate board runouts alone because every runout has the same number of
legal opponent completions under the uniform model.

## Exact and Monte Carlo modes

Exact mode enumerates every legal allocation with equal weight. Auto mode uses
exact enumeration at or below the configurable trial limit (default 200,000),
otherwise independent Monte Carlo trials. Trial counts and mode are always
reported. Explicit large exact calculations require `allow_large_exact=True`
or `--allow-large-exact`; this permits full enumeration even pre-flop, although
billions of deals can take substantial time.

Monte Carlo samples complete allocations uniformly. Cards are drawn without
replacement within a trial; successive trials are independent and may repeat
a deal. The seed makes a run repeatable under the same implementation.

The equity and outright-win 95% bounds use Hoeffding's inequality for independent
values in `[0,1]`: `epsilon = sqrt(log(2/0.05) / (2 * trials))`. These conservative
bounds are clipped to `[0,100]` after conversion to percentages. Each interval
is an individual 95% bound under the model, rather than a joint guarantee.
The estimated standard error uses the sample variance of actual fractional pot
shares. One sampled trial has no estimated standard error (`null` in JSON).
Exact results have zero-width bounds and standard error zero; normal floating
point rounding still applies when summing fractional multi-way pot shares.

The probabilities depend on the supplied information and the uniform opponent
model. They do not predict folds, betting behavior, unequal contributions,
side pots, rake, or profit after a bet.
