from dataclasses import replace
import json
import unittest

from texasholdem.calculators.equity import EquityCalculator
from texasholdem.models.observation import ObservedCard, ObservedPlayer, TableObservation


def cards(text):
    return tuple(ObservedCard(0, "test", "test", code) for code in text.split())


def observation():
    return TableObservation(
        captured_at="2026-01-01T00:00:00+00:00", pid=1, table_id=22, game_id=33,
        game_type="Texas", view="Poker2D", spectating=False, spectators=0,
        seats=(1, 3, 5), dealer_seat=5, acting_seat=3,
        players=(
            ObservedPlayer(101, "Hero", 1, 1000, 25, False, False, True, 2, True),
            ObservedPlayer(102, "Opponent", 3, 900, 50, False, False, True, 2),
            ObservedPlayer(103, "Folded", 5, 700, 100, True, False, True, 2),
        ), board=cards("Qs Js Ts 2d 3c"), hero_id=101, hero_cards=cards("As Ks"),
        collected_pot=200, street_bets_total=175, small_blind=25,
        game_in_progress=True, result_in_progress=False,
    )


class ObservationTests(unittest.TestCase):
    def test_global_seat_turn_and_pot(self):
        data = json.loads(json.dumps(observation().as_dict()))
        self.assertEqual(data["acting_player_id"], 102)
        self.assertEqual(data["pot_total"], 375)
        self.assertEqual(data["player_count"], 3)
        self.assertEqual(data["street"], "river")

    def test_native_observation_to_exact_equity_excludes_folded_opponents(self):
        state = observation().to_game_state()
        self.assertEqual(state.opponents, 1)
        result = EquityCalculator().calculate(state)
        self.assertEqual(result.trials, 990)
        self.assertEqual(result.win_percentage, 100)

    def test_spectator_and_inactive_hands_cannot_make_equity(self):
        sample = observation()
        for changed in (
            replace(sample, spectating=True), replace(sample, game_type="Omaha"),
            replace(sample, game_in_progress=False), replace(sample, result_in_progress=True),
            replace(sample, hero_id=None), replace(sample, hero_cards=()),
            replace(sample, hero_cards=cards("As As")),
            replace(sample, hero_cards=(ObservedCard(0, "UNKNOWN", "UNKNOWN", None),) * 2),
            replace(sample, board=cards("Qs Js")),
            replace(sample, players=tuple(replace(p, folded=True) for p in sample.players)),
            replace(sample, players=(sample.players[0],)),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                changed.to_game_state()

    def test_no_acting_seat_and_animation_stage(self):
        sample = replace(observation(), acting_seat=None, result_in_progress=True)
        self.assertIsNone(sample.acting_player_id)
        self.assertEqual(sample.stage, "showdown")
        self.assertEqual(replace(sample, result_in_progress=False, game_in_progress=False).stage, "between-hands")
