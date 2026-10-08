from __future__ import annotations

import argparse
import webbrowser

from ..dashboard.server import DashboardServer
from ..dashboard.service import DashboardService
from .analyzer_cli import positive_integer, positive_interval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a local live Pokerist dashboard.")
    parser.add_argument("--port", type=positive_integer, default=8765, help="local port (default: 8765)")
    parser.add_argument("--pid", type=positive_integer, help="select a Pokerist process")
    parser.add_argument("--table-id", type=positive_integer, help="select a table")
    parser.add_argument("--interval", type=positive_interval, default=0.5, help="refresh interval in seconds")
    parser.add_argument("--simulations", type=positive_integer, default=10_000, help="live equity sample count (1000–50000)")
    parser.add_argument("--no-browser", action="store_true", help="start the server without opening a browser")
    parser.add_argument("--autoplay", action="store_true", help="enable the bot when the dashboard starts")
    args = parser.parse_args(argv)
    if args.port > 65535:
        parser.error("--port must be between 1 and 65535")
    service = None
    try:
        service = DashboardService(pid=args.pid, table_id=args.table_id,
                                   interval=args.interval, simulations=args.simulations)
        with DashboardServer(args.port, service) as server:
            service.start()
            if args.autoplay:
                service.bot.start()
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"Poker dashboard: {url}\nCtrl+C stops the dashboard.", flush=True)
            if not args.no_browser:
                webbrowser.open(url, new=2)
            server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as error:
        parser.exit(2, f"poker-dashboard: {error}\n")
    finally:
        if service is not None:
            service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
