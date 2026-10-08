from __future__ import annotations

from datetime import datetime, timezone
import time

from ..calculators.combinations import combination_counts
from ..calculators.equity import EquityCalculator
from ..calculators.hand_distribution import HandDistributionCalculator
from ..core.cards import parse_cards
from ..core.game_state import GameState
from ..core.hand_evaluator import best_five, category_name, evaluate
from ..models.observation import TableObservation


def analyze_state(state: GameState, *, simulations: int = 10_000, seed: int | None = None) -> dict:
    started = time.monotonic()
    equity = EquityCalculator().calculate(state, simulations=simulations, seed=seed)
    distribution = HandDistributionCalculator().calculate(state, simulations=simulations, seed=seed)
    known = state.hero + state.board
    current = {"category": "Pocket pair" if state.hero[0].rank == state.hero[1].rank else "Pre-flop",
               "best_five": []}
    if len(known) >= 5:
        current = {"category": category_name(evaluate(known)), "best_five": list(map(str, best_five(known)))}
    counts = combination_counts(state)
    # Large allocation counts exceed JavaScript's exact integer range. Retain
    # decimal strings as well so browser exports preserve the complete count.
    exact_counts = {name: [str(item) for item in value] if isinstance(value, list) else str(value)
                    for name, value in counts.items()}
    return {
        "state": state.as_dict(), "equity": equity.as_dict(),
        "distribution": distribution.as_dict(), "combinations": counts, "exact_counts": exact_counts,
        "current_hand": current, "calculated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def scenario_state(payload: dict) -> tuple[GameState, int]:
    if not isinstance(payload, dict):
        raise ValueError("Enter a hand, a board, and the number of opponents")
    hero, board = payload.get("hero", ""), payload.get("board", "")
    if not isinstance(hero, str) or not isinstance(board, str) or len(hero) > 100 or len(board) > 100:
        raise ValueError("Cards must use text such as As Kh or Qs Jh 2c")
    opponents = payload.get("opponents", 1)
    simulations = payload.get("simulations", 10_000)
    if type(simulations) is not int or not 1_000 <= simulations <= 50_000:
        raise ValueError("Choose between 1,000 and 50,000 samples")
    return GameState(hero=parse_cards(hero), board=parse_cards(board), opponents=opponents), simulations


def round_metrics(observation: TableObservation) -> dict:
    active = [player for player in observation.players if player.playing and not player.folded and player.cards_count > 0]
    hero = next((player for player in observation.players if player.id == observation.hero_id), None)
    to_call = None
    if hero is not None and hero in active and not observation.spectating and observation.game_in_progress and not observation.result_in_progress:
        to_call = min(hero.stack, max(0.0, max((player.bet for player in observation.players), default=0) - hero.bet))
    denominator = observation.pot_total + (to_call or 0)
    return {
        "active_players": len(active), "occupied_seats": len(observation.players),
        "seat_capacity": len(observation.seats), "to_call": to_call,
        "call_pot_odds_percentage": 100 * to_call / denominator if to_call is not None and denominator else None,
        "hero_stack": hero.stack if hero else None,
        "is_hero_turn": hero is not None and hero.id == observation.acting_player_id,
    }
