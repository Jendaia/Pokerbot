from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from math import isfinite
from pathlib import Path
import sys
import time

from ..analyzers.native.pokerist import PokeristReader
from ..analyzers.native.window import game_window
from ..calculators.equity import EquityCalculator


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def positive_interval(value: str) -> float:
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read the current Pokerist table from a local Linux/Proton client.")
    parser.add_argument("--native", action="store_true", help="use the native reader (the default)")
    parser.add_argument("--pid", type=positive_integer, help="select a specific Texas Poker.exe process")
    parser.add_argument("--table-id", type=positive_integer, help="select a table if several live owners exist")
    parser.add_argument("--inspect", action="store_true", help="report discovered pointers and offsets")
    parser.add_argument("--window", action="store_true", help="include X11 game window bounds when available")
    parser.add_argument("--watch", action="store_true", help="stream snapshots as JSON Lines until interrupted")
    parser.add_argument("--interval", type=positive_interval, default=0.5, help="watch interval in seconds (default: 0.5)")
    parser.add_argument("--samples", type=positive_integer, help="stop watch after this many snapshots")
    parser.add_argument("--output", type=Path, help="write JSON/JSON Lines to this file")
    parser.add_argument("--equity", action="store_true", help="include showdown equity when a personal hand is available")
    parser.add_argument("--simulations", type=positive_integer, default=10_000, help="equity Monte Carlo samples (default: 10000)")
    parser.add_argument("--seed", type=int, help="reproducible equity sampling seed")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.inspect and (args.watch or args.equity):
        parser.error("--inspect cannot be combined with --watch or --equity")
    if args.samples and not args.watch:
        parser.error("--samples requires --watch")
    try:
        with PokeristReader(args.pid, table_id=args.table_id) as reader:
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
            destination = args.output.open("w", encoding="utf-8") if args.output else nullcontext(sys.stdout)
            with destination as stream:
                cached_key = None
                cached_equity = None
                count = 0
                while True:
                    started = time.monotonic()
                    if args.inspect:
                        result = reader.pointer_report()
                    else:
                        observation = reader.read()
                        result = observation.as_dict()
                        if args.equity:
                            try:
                                state = observation.to_game_state()
                            except ValueError as error:
                                result["equity"] = None
                                result["equity_unavailable_reason"] = str(error)
                            else:
                                key = json.dumps(state.as_dict(), sort_keys=True)
                                if key != cached_key:
                                    cached_equity = EquityCalculator().calculate(
                                        state, simulations=args.simulations, seed=args.seed,
                                    ).as_dict()
                                    cached_key = key
                                result["equity"] = cached_equity
                    if args.window:
                        result["client_window"] = game_window(reader.process.pid)
                    print(json.dumps(result, ensure_ascii=False, indent=None if args.watch else 2), file=stream, flush=True)
                    count += 1
                    if not args.watch or args.samples is not None and count >= args.samples:
                        break
                    time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    except ModuleNotFoundError as error:
        if error.name == "numpy":
            parser.exit(2, "Native scanning requires NumPy. Install with: pip install -e '.[native]'\n")
        raise
    except (OSError, ValueError) as error:
        parser.exit(2, f"poker-analyze: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
