# Local visual dashboard

Run `.venv/bin/poker-dashboard` from the project directory. The site opens at
`http://127.0.0.1:8765`. `--no-browser` runs just the server; `--port` selects
another port. The command works even if Pokerist has not started yet and retries
native discovery until a table becomes available. It is a local development
dashboard, not a deployed multi-user service.

## Structure

```text
src/texasholdem/dashboard/
  analysis.py       state calculations, scenario validation, round metrics
  service.py        independent reader/calculation workers, recent observations
  server.py         local HTTP API and allowlisted packaged assets
  static/
    index.html      accessible dashboard structure
    styles.css      table, cards, graphs, responsive layouts
    app.js          live updates, scenario form, pause and JSON export
    mark.svg        local logo/favicon
src/texasholdem/interfaces/dashboard_cli.py
tests/dashboard/   calculation, service lifecycle, and HTTP tests
scripts/validate_dashboard.py
```

The frontend polls the current service state every 600 ms. The native reader
normally samples every 500 ms; `--interval` adjusts that rate. Reading occurs
independently of calculations, so Monte Carlo work does not queue obsolete
observations. A separate worker calculates only the most recent valid hand.
Results from an older hand are discarded, and unchanged hero/board/opponent
inputs reuse the cached result. Native errors clear live cards/percentages and
trigger rediscovery, including after game restarts and table changes.

The HTTP service uses Python's
[ThreadingHTTPServer](https://docs.python.org/3/library/http.server.html#http.server.ThreadingHTTPServer)
bound to IPv4 loopback. Assets are packaged with the Python distribution. Bot
control endpoints validate local origins and accept typed actions for the
current native turn. Arbitrary mouse coordinates and process targets are not
accepted. The API is also usable directly by a future AI consumer.

## API

`GET /api/state` returns:

- `connection`: live/connecting/reconnecting status and an explanation.
- `observation`: the native `TableObservation`, or `null` when disconnected.
- `metrics`: occupied/active seats, local stack, turn flag, and derived call ratio.
- `analysis`: calculating/ready/unavailable/error status. A ready result contains
  the calculator state, showdown equity, hand distribution, combinations, current
  hand category, and calculation timestamp. `exact_counts` contains decimal
  strings so very large allocation counts survive JavaScript and JSON downloads
  without integer rounding. The UI abbreviates large counts but preserves the
  full count in its tooltip and export.
- `events`: up to 40 observed changes. These are local observations, not a
  complete server hand history or inferred betting actions.
- `bot`: autoplay state, settings, native legal actions and turn token, current
  decision/action-value estimates, public opponent statistics, session metrics,
  and recent submitted/acknowledged actions.

`POST /api/bot/start` accepts bot settings (an empty object uses current
settings); `POST /api/bot/stop` accepts `{}`. `POST /api/bot/prepare` accepts
`{"turn_token":"..."}` and opens the current native raise controls without
confirming a bet. `POST /api/bot/action` accepts
`{"action":"call","amount":0,"turn_token":"..."}`. Fold, check, and call
use amount zero; raise uses a positive integer additional-chip amount. Manual
requests pause autoplay and are rejected if the displayed turn is stale.
See [autoplay](autoplay.md) for the controller and strategy model.

`POST /api/analyze` accepts a separate scenario:

```json
{"hero":"As Ks","board":"Qs Js Ts 2d 3c","opponents":1,"simulations":10000}
```

It returns `{ "status": "ready", "source": "scenario", "result": ... }`.
An empty board is valid pre-flop. Invalid, duplicate, or incomplete cards return
a JSON error. Opponents must be 1–9 and sampling requests 1,000–50,000. Exact
enumeration is selected automatically for smaller spaces. This endpoint does
not replace the native observation or interact with Pokerist.

## Probability meanings

**Win** means an outright showdown win; **tie** includes any tied winning pot;
**lose** means hero does not share the winning hand. **Pot equity** is the mean
fraction of a common pot, including divided ties. A shared royal flush heads-up
therefore has 0% outright win, 100% tie, and 50% pot equity.

The nine hand-category bars describe hero's final best five-card category across
legal future board runouts. They are calculated independently from showdown
equity, and their exact/sampled status is shown separately. A royal flush is
included in straight flush. The current category is shown when at least five
cards are known; pre-flop pocket pairs are labeled without evaluating an
incomplete five-card hand.

Live calculations require an active Texas Hold'em personal hand from
`TableObservation.to_game_state()`. Spectators have no personal hand and see
placeholders. The What if tab provides an independent calculator in that case.
The private-card native path and game input have been validated while seated;
native extraction, cancellation, and action flows also have synthetic coverage.

The **Your odds** calculator uses uniform unknown opponents. Future folds,
weighted ranges, and side-pot eligibility are not modeled in those percentages.
The separate **Your copilot** policy uses weighted opponent ranges and layered
pot payouts; its estimates are labeled as decision values. Collected pot and street bets remain
separate, with their sum labeled as derived. The displayed call ratio is
`call / (pot + call)`, capped by the remaining stack; it does not decide a betting
action or model payouts. See [native field meanings](native_reader.md) and
[calculator assumptions](probability_model.md).

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v

# Optional browser tooling; not required to run the dashboard.
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium

# With poker-dashboard running:
.venv/bin/python scripts/validate_dashboard.py
.venv/bin/python scripts/validate_bot_dashboard.py
```

Browser checks cover visual percentages for exact wins and ties, all hand bars,
card validation, stale scenario clearing, mode switching, pause/resume, JSON
downloads, and a 390 px mobile viewport. Screenshots and exports go to ignored
`artifacts/dashboard/`. Unit tests verify consistent updates, calculation caching,
older result rejection, local HTTP responses, and native observation integration.
