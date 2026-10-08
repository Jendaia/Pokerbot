from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest

from texasholdem.interfaces.cli import main
from helpers import small_state


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        output = StringIO()
        with redirect_stdout(output):
            status = main(args)
        self.assertEqual(status, 0)
        return output.getvalue()

    def test_json_equity_has_state_counts_and_probabilities(self):
        report = json.loads(self.run_cli([
            "--hero", "As Ks", "--board", "Qs Js Ts 2d 3c", "--json",
        ]))
        self.assertEqual(report["state"]["street"], "river")
        self.assertEqual(report["combinations"]["complete_deals"], 990)
        self.assertEqual(report["win_percentage"], 100)
        self.assertEqual(report["current_hand"]["category"], "Straight Flush")
        self.assertTrue(report["is_exact"])

    def test_count_preflop_without_enumerating(self):
        report = json.loads(self.run_cli(["--hero", "As Ah", "--counts-only", "--json"]))
        self.assertEqual(report["combinations"]["complete_deals"], 2_097_572_400)
        self.assertNotIn("trials", report)

    def test_known_opponent_and_dead_card_options(self):
        report = json.loads(self.run_cli([
            "--hero", "2c 3d", "--board", "As Ks Qs Js Ts", "--villain", "4c 5d",
            "--dead", "6c", "--json",
        ]))
        self.assertEqual(report["total_possible"], 1)
        self.assertEqual(report["equity_percentage"], 50)
        self.assertEqual(report["state"]["dead_cards"], ["6c"])

    def test_list_limit_and_labelled_showdowns(self):
        rows = self.run_cli(["--hero", "As Ah", "--list", "deals", "--limit", "3"]).splitlines()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(json.loads(rows[0])["board"]), 5)
        labelled = json.loads(self.run_cli([
            "--hero", "As Ks", "--board", "Qs Js Ts 2d 3c", "--list", "showdowns", "--limit", "1",
        ]))
        self.assertEqual(labelled["winner_seats"], [0])
        self.assertEqual(labelled["hero_pot_share"], 1)

    def test_export_every_combination_on_small_deck(self):
        state = small_state()
        rows = self.run_cli([
            "--hero", "As Kh", "--board", "Qs Js 2d 3c", "--opponents", "2", "--villain", "Ac",
            "--dead", " ".join(map(str, state.dead_cards)), "--list", "deals", "--limit", "0",
        ]).splitlines()
        self.assertEqual(len(rows), 180)

    def test_distribution_report(self):
        report = json.loads(self.run_cli([
            "--hero", "Ah Kh", "--board", "Qh 2h 9c 7d", "--distribution-only", "--json",
        ]))
        self.assertEqual(report["trials"], 46)
        self.assertEqual(report["hand_category_counts"]["Flush"], 9)

    def test_readable_output(self):
        text = self.run_cli(["--hero", "As Ah", "--mode", "monte-carlo", "--simulations", "20", "--seed", "7"])
        self.assertIn("Win outright:", text)
        self.assertIn("95% equity bound:", text)

    def test_bad_inputs_exit_cleanly(self):
        for args in (
            ["--hero", "As As"],
            ["--hero", "As Ah", "--limit", "-1"],
            ["--hero", "As Ah", "--list", "opponents", "--seat", "2"],
            ["--hero", "As Ah", "--mode", "exact"],
        ):
            error = StringIO()
            with self.subTest(args=args), redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                main(args)
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("error:", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
