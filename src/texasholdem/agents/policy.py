from __future__ import annotations

from bisect import bisect_right
from itertools import combinations
from math import sqrt
import random
import time

from ..analyzers.native.controls import ControlFrame
from ..core.cards import Card, full_deck
from ..core.hand_evaluator import _evaluate_unchecked
from .models import Action, BotSettings, Decision
from .objectives import LABELS, score, utility
from .opponents import HandTracker
from .pots import pot_payout
from .sizing import native_actions


def preflop_strength(hand: tuple[Card, Card]) -> float:
    high, low = sorted((c.rank for c in hand), reverse=True)
    if high == low:
        return .53 + .032 * (high - 2)
    gap = high - low
    score = .20 + .025 * (high - 2) + .016 * (low - 2)
    score += .055 if hand[0].suit == hand[1].suit else 0
    score += .055 if gap == 1 else .025 if gap == 2 else -.015 * min(4, gap - 2)
    score += .04 if high == 14 else 0
    return max(.05, min(.9, score))


class RolloutPolicy:
    """Range-weighted, common-random-number action-value search.

    This is a bounded compute baseline, not a trained equilibrium strategy.
    Future streets check down; responses to a bet are a public-history model.
    The native input adapter independently enforces action legality.
    """

    name = "Range-weighted rollout v1"

    def decide(self, frame: ControlFrame, tracker: HandTracker, settings: BotSettings, cancelled=lambda: False,
               *, seed: int | None = None) -> Decision:
        started = time.monotonic()
        observation = frame.observation
        state = observation.to_game_state()
        if observation.acting_player_id != observation.hero_id or not frame.legal:
            raise ValueError("The hero does not have a legal turn")
        hero = next(p for p in observation.players if p.id == observation.hero_id)
        opponents = [p for p in observation.players if p.id != hero.id and p.playing and not p.folded and p.cards_count]
        highest = max(p.bet for p in observation.players)
        call = min(hero.stack, max(0, highest - hero.bet))
        pot_odds = call / max(1, observation.pot_total + call)
        passive = Action("check") if "check" in frame.legal else Action("fold")
        candidates = native_actions(frame, tracker, settings)
        deck = tuple(c for c in full_deck() if c not in (*state.hero, *state.board))
        hands = tuple(combinations(deck, 2))
        if state.board:
            ranks = [_evaluate_unchecked((*hand, *state.board)) for hand in hands]
            sorted_ranks = sorted(ranks)
            strengths = [bisect_right(sorted_ranks, rank) / len(hands) for rank in ranks]
        else:
            strengths = [preflop_strength(hand) for hand in hands]
        weights = [[tracker.range_weight(p.id, value, observation.street) for value in strengths] for p in opponents]
        cumulative = []
        for row in weights:
            total, values = 0., []
            for weight in row:
                total += weight
                values.append(total)
            cumulative.append(values)
        rng = random.Random(seed)
        sums, squares = [0.] * len(candidates), [0.] * len(candidates)
        utility_sums, utility_squares = [0.] * len(candidates), [0.] * len(candidates)
        wealth = hero.stack
        contributions = tracker.contributions(observation)
        equity, count = 0., 0
        deadline = started + settings.think_seconds
        for count in range(1, settings.samples + 1):
            if count % 32 == 1 and (cancelled() or time.monotonic() > deadline):
                count -= 1
                break
            used, sampled, current_strengths = set(), [], []
            for row in cumulative:
                for _ in range(256):
                    index = bisect_right(row, rng.random() * row[-1])
                    hand = hands[index]
                    if not used.intersection(hand):
                        break
                else:
                    # Conditional weighted sampling with card removal, without
                    # falling back to uniform or reusing a blocked card.
                    valid = [i for i, hand in enumerate(hands) if not used.intersection(hand)]
                    native_weights = [row[i] - (row[i - 1] if i else 0) for i in valid]
                    index = rng.choices(valid, weights=native_weights, k=1)[0]
                    hand = hands[index]
                used.update(hand)
                sampled.append(hand)
                current_strengths.append(strengths[index])
            remaining = [c for c in deck if c not in used]
            board = (*state.board, *rng.sample(remaining, 5 - len(state.board)))
            hero_rank = _evaluate_unchecked((*state.hero, *board))
            opp_ranks = [_evaluate_unchecked((*hand, *board)) for hand in sampled]
            best = max([hero_rank, *opp_ranks])
            equity += (1 / (1 + opp_ranks.count(best))) if hero_rank == best else 0
            draws = [rng.random() for _ in opponents]
            for index, candidate in enumerate(candidates):
                if candidate.kind == "fold":
                    value = 0.
                else:
                    cost = call if candidate.kind == "call" else candidate.amount if candidate.kind == "raise" else 0
                    target = hero.bet + cost
                    wagers, live = dict(contributions), {hero.id: hero_rank}
                    wagers[hero.id] = wagers.get(hero.id, 0) + cost
                    for p, rank, strength, draw in zip(opponents, opp_ranks, current_strengths, draws):
                        price = min(p.stack, max(0, target - p.bet))
                        odds = price / max(1, observation.pot_total + cost + price)
                        probability = tracker.call_probability(p.id, strength, odds, observation.street)
                        # Players already matched or all-in remain eligible.
                        if price == 0 or draw <= probability:
                            wagers[p.id] = wagers.get(p.id, 0) + price
                            live[p.id] = rank
                    value = pot_payout(wagers, live, hero.id) - cost
                    if candidate.kind == "raise" and len(state.board) < 5:
                        # Reserve value for omitted counter-raises and imperfect
                        # equity realization, especially out of position/multiway.
                        value -= min(cost * .06, observation.small_blind * (1 + len(opponents) * .25))
                sums[index] += value
                squares[index] += value * value
                adjusted = utility(value, wealth, settings.objective)
                utility_sums[index] += adjusted
                utility_squares[index] += adjusted * adjusted
        if cancelled():
            raise ValueError("Decision was cancelled")
        if count == 0:
            return Decision(passive, "No compute budget remains; use the available check/fold", 0, pot_odds, 0,
                            time.monotonic() - started, ())
        estimates = []
        for action, total, squared, u_total, u_squared in zip(candidates, sums, squares, utility_sums, utility_squares):
            mean = total / count
            error = sqrt(max(0, squared / count - mean * mean) / max(1, count - 1))
            u_mean = u_total / count
            u_error = sqrt(max(0, u_squared / count - u_mean * u_mean) / max(1, count - 1))
            estimates.append({"action": action.kind, "amount": action.amount, "ev_chips": mean,
                              "standard_error": error, "utility_chips": u_mean,
                              "score": score(u_mean, u_error, settings.objective)})
        best_index = max(range(len(candidates)), key=lambda i: estimates[i]["score"])
        selected = candidates[best_index]
        if not tracker.ledger_complete:
            reason = "Waiting for a complete hand ledger; check or fold until the next hand"
        else:
            reason = (f"{LABELS[settings.objective]} · {selected.kind.title()} has the best estimated objective value · "
                      f"range equity {equity / count:.1%} · call price {pot_odds:.1%}")
        return Decision(selected, reason, equity / count, pot_odds, count, time.monotonic() - started, tuple(estimates),
                        diagnostics={"objective": settings.objective, "stack_chips": hero.stack,
                                     "limitations": "Estimated opponent responses and check-down runouts; chip EV is not guaranteed profit"})
