from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from texasholdem.interfaces.analyzer_cli import main
from native.test_observation import observation


class AnalyzerCliTests(unittest.TestCase):
    def run_with_reader(self, args, sample):
        with patch("texasholdem.interfaces.analyzer_cli.PokeristReader") as reader_type:
            reader = reader_type.return_value.__enter__.return_value
            reader.process = SimpleNamespace(pid=1)
            reader.read.return_value = sample
            reader.pointer_report.return_value = {"owner": "0x1000"}
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            return output.getvalue()

    def test_watch_produces_separate_json_records(self):
        lines = self.run_with_reader(["--watch", "--samples", "2", "--interval", "0.001"], observation()).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["acting_player_id"], 102)

    def test_watch_refreshes_moved_window_bounds(self):
        with patch("texasholdem.interfaces.analyzer_cli.game_window", side_effect=[{"x": 0}, {"x": 100}]):
            lines = self.run_with_reader(["--watch", "--window", "--samples", "2", "--interval", "0.001"], observation()).splitlines()
        self.assertEqual([json.loads(line)["client_window"]["x"] for line in lines], [0, 100])

    def test_equity_and_inspection(self):
        result = json.loads(self.run_with_reader(["--equity"], observation()))
        self.assertEqual(result["equity"]["win_percentage"], 100)
        self.assertEqual(json.loads(self.run_with_reader(["--inspect"], observation())), {"owner": "0x1000"})

    def test_spectator_has_clear_equity_reason(self):
        from dataclasses import replace
        result = json.loads(self.run_with_reader(["--equity"], replace(observation(), spectating=True)))
        self.assertIsNone(result["equity"])
        self.assertIn("Spectators", result["equity_unavailable_reason"])

    def test_bad_arguments_and_missing_process_exit_cleanly(self):
        for args in (["--pid", "0"], ["--interval", "nan"], ["--interval", "inf"],
                     ["--samples", "2"], ["--inspect", "--watch"]):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
                main(args)
            self.assertEqual(caught.exception.code, 2)
        with patch("texasholdem.interfaces.analyzer_cli.PokeristReader", side_effect=ValueError("No game")):
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                main([])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("No game", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
