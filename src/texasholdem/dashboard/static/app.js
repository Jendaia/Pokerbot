"use strict";

const $ = (id) => document.getElementById(id);
const suits = {c: "♣", d: "♦", h: "♥", s: "♠"};
const handNames = ["High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush"];
const ui = {payload: null, bot: null, botBusy: false, botRequestRevision: 0, botSettingsLoaded: false, raiseToken: null, paused: false, mode: "live", scenario: null, calculating: false, scenarioRevision: 0, analysisSignature: null, eventSignature: null};
const money = (value) => value == null ? "—" : new Intl.NumberFormat(undefined, {maximumFractionDigits: Number.isInteger(value) ? 0 : 2}).format(value);
const percentage = (value) => `${Number(value).toFixed(1)}%`;
const bigCount = (value) => {
  if (value == null) return "—";
  if (value >= 1e12) return Number(value).toExponential(2);
  return money(value);
};
const clock = (value) => new Date(value).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function card(code, empty = false) {
  const known = typeof code === "string" && /^[2-9TJQKA][cdhs]$/.test(code);
  const element = node("div", `playing-card ${known ? ("dh".includes(code[1]) ? "red" : "") : empty ? "empty" : "back"}`);
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", known ? code : empty ? "Undealt card" : "Unknown card");
  if (known) {
    const corner = node("span", "card-corner", code[0] === "T" ? "10" : code[0]);
    corner.append(node("small", "", suits[code[1]]));
    element.append(corner, node("span", "card-suit", suits[code[1]]));
  }
  return element;
}

function showCards(container, cards, slots) {
  const elements = Array.from({length: Math.max(cards.length, slots)}, (_, index) => card(cards[index]?.code ?? cards[index], index >= cards.length));
  container.replaceChildren(...elements);
}

function badge(id, text, tone = "muted") {
  $(id).textContent = text;
  $(id).className = `badge ${tone}`;
}

function setConnection(status, message) {
  const paused = ui.paused;
  $("connection-text").textContent = paused ? "Paused" : status === "live" ? "Live connection" : status === "connecting" ? "Connecting" : "Reconnecting";
  $("connection-pill").className = `connection-pill ${status === "live" && !paused ? "live" : ""}`;
  $("connection-notice").hidden = status === "live" && !paused;
  $("connection-notice").textContent = paused ? "Updates are paused. You’re viewing the last captured round." : message;
}

function playerStatus(player, observation) {
  if (player.sitting_out) return "Sitting out";
  if (player.folded) return "Folded";
  if (observation.acting_player_id === player.id) return "To act";
  if (player.playing && player.cards_count > 0 && player.stack === 0) return "All-in";
  return player.playing && player.cards_count > 0 ? "In the hand" : "Waiting";
}

function renderSeats(observation) {
  const seats = observation?.seats || [];
  const players = observation?.players || [];
  const hero = players.find((player) => player.id === observation.hero_id);
  const heroIndex = seats.indexOf(hero?.seat);
  const startAngle = heroIndex >= 0 ? 90 - heroIndex * 360 / seats.length : -126;
  const probe = node("div", "seat");
  probe.style.visibility = "hidden";
  $("seats-layer").append(probe);
  const radiusX = Math.max(0, Math.min(40, 50 - (probe.offsetWidth / 2 + 8) / Math.max(1, $("poker-stage").clientWidth) * 100));
  probe.remove();
  const elements = seats.map((seatNumber, index) => {
    const player = players.find((value) => value.seat === seatNumber);
    const angle = (startAngle + index * 360 / seats.length) * Math.PI / 180;
    const element = node("div", "seat");
    element.style.left = `${50 + radiusX * Math.cos(angle)}%`;
    element.style.top = `${50 + 38 * Math.sin(angle)}%`;
    if (!player) {
      element.classList.add("empty");
      element.textContent = `Seat ${seatNumber} · Open`;
      return element;
    }
    element.classList.toggle("acting", observation.acting_player_id === player.id);
    element.classList.toggle("hero", player.is_hero);
    element.classList.toggle("folded", player.folded || player.sitting_out);
    element.title = `${player.name || "Player"} · seat ${seatNumber} · ${playerStatus(player, observation)} · player ${player.id}`;
    element.append(node("span", "seat-number", `${seatNumber}${player.is_hero ? " · YOU" : ""}`));
    const top = node("div", "seat-top");
    top.append(node("span", "seat-name", player.name || "Player"));
    if (observation.dealer_seat === seatNumber) top.append(node("span", "seat-marker", "D"));
    element.append(top, node("div", "seat-stack", money(player.stack)));
    const bottom = node("div", "seat-bottom");
    bottom.append(node("span", "", playerStatus(player, observation)));
    if (player.bet) bottom.append(node("span", "", `· Bet ${money(player.bet)}`));
    element.append(bottom);
    return element;
  });
  $("seats-layer").replaceChildren(...elements);

  $("player-rows").replaceChildren(...players.map((player) => {
    const row = node("tr");
    const name = node("td", "", `${player.name || "Player"}${player.is_hero ? " · You" : ""}`);
    name.append(node("small", "", `Seat ${player.seat} · ID ${player.id}`));
    row.append(name, node("td", "", money(player.stack)), node("td", "", money(player.bet)), node("td", "", playerStatus(player, observation)));
    return row;
  }));
}

function renderTable(payload) {
  const observation = payload.observation;
  const metrics = payload.metrics;
  const acting = observation?.players.find((player) => player.id === observation.acting_player_id);
  $("game-type-label").textContent = !observation || observation.game_type === "Texas" ? "TEXAS HOLD’EM" : observation.game_type.toUpperCase();
  $("table-label").textContent = observation ? `TABLE ${observation.table_id}` : "WAITING FOR A TABLE";
  $("pot-value").textContent = money(observation?.pot_total);
  $("pot-detail").textContent = observation ? `${money(observation.collected_pot)} collected · ${money(observation.street_bets_total)} on the felt` : "Collected pot + street bets";
  $("players-value").textContent = observation ? `${observation.player_count}` : "—";
  $("capacity-value").textContent = observation ? `/ ${observation.seats.length} seats` : "seats";
  $("active-detail").textContent = observation ? `${metrics.active_players} in this hand · ${observation.spectators} watching` : "Waiting for players";
  $("acting-value").textContent = acting?.name || (observation ? observation.result_in_progress ? "Showdown" : "Between actions" : "—");
  $("acting-detail").textContent = acting ? `${metrics.is_hero_turn ? "Your turn" : "To act"} · Seat ${acting.seat}` : "Waiting for the next action";
  $("stack-value").textContent = observation?.spectating ? "Spectating" : money(metrics?.hero_stack);
  $("stack-value").style.fontSize = observation?.spectating ? "23px" : "";
  $("stack-detail").textContent = observation?.spectating ? "Take a seat to see your hand" : observation?.hero_id ? `Your chips · ${observation.view}` : "Not seated yet";
  badge("mode-badge", observation ? observation.result_in_progress ? "Showdown" : observation.spectating ? "Spectator view" : "Your live table" : "Waiting", observation && !observation.spectating ? "green" : "muted");
  $("blinds-label").textContent = `Small blind ${money(observation?.small_blind)}`;
  const order = ["pre-flop", "flop", "turn", "river"];
  $("street-track").querySelectorAll("[data-street]").forEach((element) => {
    element.classList.toggle("current", observation?.street === element.dataset.street && observation.game_in_progress);
    element.classList.toggle("past", !!observation && order.indexOf(element.dataset.street) < order.indexOf(observation.street));
  });
  showCards($("board-cards"), observation?.board || [], 5);
  $("board-label").textContent = observation?.result_in_progress ? "SHOWDOWN BOARD" : "COMMUNITY CARDS";
  $("table-pot").textContent = observation ? `${money(observation.pot_total)} in the pot` : "Waiting for a hand";
  showCards($("hero-cards"), observation?.hero_cards || [], 2);
  $("hero-hand-label").textContent = observation?.spectating ? "Watching this round" : observation?.hero_cards.length ? observation.hero_cards.map((value) => value.code || "?").join(" · ") : "Waiting for your cards";
  $("hero-hand-detail").textContent = observation?.spectating ? "No personal hand while spectating." : "Your cards appear automatically when dealt.";
  $("export-button").disabled = !observation;
  $("updated-at").textContent = observation ? `${ui.paused ? "Paused at" : "Updated"} ${clock(observation.captured_at)} · Pokerist ${observation.view}` : "Waiting for a live observation";
  renderSeats(observation);
}

const categoryElements = new Map();
for (const name of handNames) {
  const row = node("div", "category-row");
  const top = node("div", "category-top");
  const value = node("strong", "", "—");
  top.append(node("span", "", name), value);
  const rail = node("div", "category-rail");
  const fill = node("span", "category-fill");
  fill.style.width = "0%";
  rail.append(fill);
  row.append(top, rail);
  categoryElements.set(name, {row, value, fill});
  $("hand-categories").append(row);
}

function renderCategories(distribution) {
  const percentages = distribution?.hand_categories;
  const largest = percentages ? Math.max(...Object.values(percentages)) : 0;
  categoryElements.forEach(({row, value, fill}, name) => {
    const probability = percentages?.[name];
    value.textContent = probability == null ? "—" : probability > 0 && probability < 0.1 ? "<0.1%" : percentage(probability);
    fill.style.width = `${probability || 0}%`;
    row.classList.toggle("most-likely", probability > 0 && probability === largest);
  });
  $("distribution-method").textContent = distribution ? `${distribution.is_exact ? "Exact" : "Estimated"} · ${money(distribution.trials)} board runouts ${distribution.is_exact ? "evaluated" : "sampled"}` : "Waiting for a personal hand";
  badge("distribution-source", ui.mode === "scenario" ? "What-if scenario" : "Live hand", ui.mode === "scenario" ? "gold" : "muted");
  $("distribution-description").textContent = ui.mode === "scenario" ? "Final hand probabilities for your entered scenario, independent of the live table." : "Final five-card hand probabilities, across legal future board runouts.";
}

function renderResult(result) {
  const equity = result.equity;
  $("equity-value").textContent = percentage(equity.equity_percentage);
  $("equity-ring").style.background = `conic-gradient(var(--green) ${equity.equity_percentage}%, #2b3d31 0)`;
  $("current-hand").textContent = result.current_hand.category;
  $("equity-explanation").textContent = `Against ${result.state.opponents} ${result.state.opponents === 1 ? "opponent" : "opponents"}. Includes your share of tied pots.`;
  for (const outcome of ["win", "tie", "loss"]) {
    $(outcome === "loss" ? "loss-value" : `${outcome}-value`).textContent = percentage(equity[`${outcome}_percentage`]);
    $(`${outcome}-bar`).style.width = `${equity[`${outcome}_percentage`]}%`;
  }
  $("method-label").textContent = equity.is_exact ? "Exact showdown probabilities" : "Monte Carlo estimate";
  $("trial-value").textContent = `${money(equity.trials)} ${equity.is_exact ? "deals" : "samples"}`;
  $("confidence-label").textContent = equity.is_exact ? "Every legal complete deal evaluated." : `95% equity bound: ${percentage(equity.equity_95_interval[0])}–${percentage(equity.equity_95_interval[1])}`;
  const deals = result.exact_counts?.complete_deals || result.combinations.complete_deals;
  $("deals-value").textContent = bigCount(deals);
  $("deals-value").title = String(deals);
  $("runouts-value").textContent = money(result.combinations.board_runouts);
  $("scenario-card-preview").hidden = ui.mode !== "scenario";
  if (ui.mode === "scenario") {
    const elements = result.state.hero.map((code) => card(code));
    if (result.state.board.length) elements.push(node("span", "preview-divider"), ...result.state.board.map((code) => card(code)));
    $("scenario-card-preview").replaceChildren(...elements);
  }
  renderCategories(result.distribution);
}

function renderAnalysis(force = false) {
  const analysis = ui.mode === "scenario" ? ui.calculating ? {status: "calculating"} : ui.scenario || {status: "unavailable"} : ui.payload?.analysis || {status: "unavailable"};
  const signature = `${ui.mode}:${analysis.status}:${analysis.key || ""}:${analysis.result?.calculated_at || ""}:${analysis.reason || ""}`;
  if (signature !== ui.analysisSignature || force) {
    ui.analysisSignature = signature;
    const ready = analysis.status === "ready" && !!analysis.result;
    $("analysis-results").hidden = !ready;
    $("analysis-message").hidden = ready;
    $("try-scenario-button").hidden = ui.mode === "scenario";
    if (ready) {
      badge("analysis-badge", ui.mode === "scenario" ? "Scenario" : analysis.result.equity.is_exact ? "Exact" : "Estimate", ui.mode === "scenario" ? "gold" : "green");
      renderResult(analysis.result);
    } else {
      const spectator = ui.payload?.observation?.spectating;
      const calculating = analysis.status === "calculating";
      badge("analysis-badge", calculating ? "Calculating…" : ui.mode === "scenario" ? "Scenario" : spectator ? "No personal hand" : "Waiting", ui.mode === "scenario" ? "gold" : "muted");
      $("analysis-message-title").textContent = calculating ? "Finding your probabilities" : ui.mode === "scenario" ? "A hand worth exploring" : spectator ? "A view from the rail" : "Waiting for your hand";
      $("analysis-message-copy").textContent = calculating ? "Evaluating legal cards and showdown outcomes. Your table keeps updating." : ui.mode === "scenario" ? "Enter two hole cards, your board, and an opponent count. Use T for ten and c, d, h, s for suits." : spectator ? "You’re spectating, so there’s no personal hand to calculate. Take a seat, or try a hand in What if." : analysis.reason || "Your live probabilities will appear when you’re dealt a hand.";
      renderCategories(null);
    }
  }
  const metrics = ui.payload?.metrics;
  const showCall = ui.mode === "live" && analysis.status === "ready" && metrics?.to_call != null;
  $("call-detail").hidden = !showCall;
  if (showCall) {
    $("call-value").textContent = money(metrics.to_call);
    $("pot-odds-value").textContent = metrics.call_pot_odds_percentage == null ? "—" : percentage(metrics.call_pot_odds_percentage);
  }
}

function renderEvents(events) {
  const signature = events.map((value) => value.id).join(",");
  if (signature === ui.eventSignature) return;
  ui.eventSignature = signature;
  if (!events.length) {
    $("activity-list").replaceChildren(node("p", "activity-empty", "The action will appear here as the table changes."));
    return;
  }
  $("activity-list").replaceChildren(...events.map((event) => {
    const element = node("div", "activity-event");
    element.append(node("span", `event-marker ${event.kind}`), node("span", "event-copy", event.message), node("span", "event-time", clock(event.at)));
    return element;
  }));
}

function selectMode(mode) {
  ui.mode = mode;
  $("live-tab").setAttribute("aria-selected", String(mode === "live"));
  $("scenario-tab").setAttribute("aria-selected", String(mode === "scenario"));
  $("scenario-form").hidden = mode !== "scenario";
  renderAnalysis(true);
  if (mode === "scenario") $("scenario-hero").focus();
}

$("live-tab").addEventListener("click", () => selectMode("live"));
$("scenario-tab").addEventListener("click", () => selectMode("scenario"));
$("try-scenario-button").addEventListener("click", () => selectMode("scenario"));
$("pause-button").addEventListener("click", () => {
  ui.paused = !ui.paused;
  $("pause-button").querySelector("span").textContent = ui.paused ? "Resume updates" : "Pause updates";
  $("pause-button").querySelector("use").setAttribute("href", ui.paused ? "#i-play" : "#i-pause");
  setConnection(ui.payload?.connection.status || "connecting", ui.payload?.connection.message || "Connecting…");
  if (ui.payload) renderTable(ui.payload);
  if (ui.bot) renderBot(ui.bot);
});

$("export-button").addEventListener("click", () => {
  if (!ui.payload?.observation) return;
  const exportData = {...ui.payload, displayed_analysis_source: ui.mode, scenario: ui.mode === "scenario" ? ui.scenario : null};
  const url = URL.createObjectURL(new Blob([JSON.stringify(exportData, null, 2)], {type: "application/json"}));
  const anchor = node("a");
  anchor.href = url;
  anchor.download = `poker-table-${ui.payload.observation.table_id}-${Date.now()}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function clearScenario() {
  ui.scenarioRevision += 1;
  ui.scenario = null;
  $("scenario-error").hidden = true;
  renderAnalysis(true);
}

$("scenario-form").addEventListener("input", clearScenario);

$("example-button").addEventListener("click", () => {
  $("scenario-hero").value = "As Ks";
  $("scenario-board").value = "Qs Js Ts 2d 3c";
  $("scenario-opponents").value = "1";
  clearScenario();
});

$("scenario-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (ui.calculating) return;
  ui.calculating = true;
  const revision = ui.scenarioRevision;
  ui.scenario = null;
  $("calculate-button").disabled = true;
  $("scenario-error").hidden = true;
  renderAnalysis(true);
  try {
    const response = await fetch("/api/analyze", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({hero: $("scenario-hero").value, board: $("scenario-board").value, opponents: Number($("scenario-opponents").value), simulations: 10000})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not calculate this hand");
    if (revision === ui.scenarioRevision) ui.scenario = result;
  } catch (error) {
    $("scenario-error").textContent = error.message;
    $("scenario-error").hidden = false;
  } finally {
    ui.calculating = false;
    $("calculate-button").disabled = false;
    renderAnalysis(true);
  }
});

async function poll() {
  try {
    {
      const response = await fetch("/api/state", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error("Dashboard unavailable");
      const payload = await response.json();
      renderBot(payload.bot);
      if (ui.paused) return;
      ui.payload = payload;
      setConnection(payload.connection.status, payload.connection.message);
      renderTable(payload);
      renderAnalysis();
      renderEvents(payload.events || []);
    }
  } catch (error) {
    document.querySelectorAll("[data-poker-action]").forEach((button) => button.disabled = true);
    setConnection("reconnecting", "The dashboard connection was interrupted. Displayed values are from the last update. Reconnecting…");
  } finally {
    setTimeout(poll, 600);
  }
}

function renderBot(bot) {
  if (!bot) return;
  ui.bot = bot;
  badge("bot-badge", bot.enabled ? "Autoplay active" : "Stopped", bot.enabled ? "green" : "muted");
  $("bot-start").disabled = bot.enabled || ui.botBusy;
  $("bot-stop").disabled = false;
  $("bot-message").textContent = bot.message;
  const methodNames = {"river-cfr+": "River CFR+ · mixed strategy", "multi-street-rollout": "Multi-street search · experimental", "rollout-v1": "Original range rollout", "ledger-guard": "Waiting for hand history"};
  $("bot-strategy").textContent = (methodNames[bot.decision?.method] || bot.strategy).toUpperCase();
  $("bot-reason").textContent = bot.decision?.reason || "Choose autoplay or take an action yourself when it’s your turn.";
  const decision = bot.decision;
  const diagnostic = decision?.diagnostics || {};
  $("bot-search-detail").textContent = !decision ? "" : [
    `Range equity ${(decision.equity * 100).toFixed(1)}%`,
    `Call price ${(decision.pot_odds * 100).toFixed(1)}%`,
    `${decision.elapsed_seconds.toFixed(2)}s`,
    diagnostic.nash_conv_chips == null ? "" : `Restricted river gap: ${money(diagnostic.nash_conv_chips.toFixed(2))} chips`,
    diagnostic.model_spread_chips == null ? "" : `Opponent-model spread: ${money(Math.round(diagnostic.model_spread_chips))} chips`,
  ].filter(Boolean).join(" · ");
  $("bot-search-detail").title = diagnostic.limitations || "";
  $("bot-hands").textContent = bot.session.hands;
  $("bot-action-count").textContent = bot.session.actions;
  $("bot-net").textContent = bot.session.net_chips == null ? "—" : `${bot.session.net_chips > 0 ? "+" : ""}${money(bot.session.net_chips)}`;
  $("bot-candidates").replaceChildren(...(bot.decision?.candidates || []).map((candidate) => {
    const mix = candidate.probability == null ? "" : ` · ${(candidate.probability * 100).toFixed(1)}%`;
    const item = node("span", "candidate", `${candidate.action}${candidate.amount ? ` ${money(candidate.amount)}` : ""}${mix} · EV ${money(Math.round(candidate.ev_chips))}`);
    item.style.setProperty("--mix", `${Math.min(100, Math.max(0, (candidate.probability || 0) * 100))}%`);
    item.classList.toggle("selected", candidate.action === bot.decision.action.kind && candidate.amount === bot.decision.action.amount);
    item.title = candidate.standard_error == null ? "Action frequency and value against the solver’s average strategy; restricted river tree and estimated ranges" : `Simulation standard error: ${money(candidate.standard_error)} chips; does not include model error`;
    return item;
  }));
  const controls = bot.controls;
  const blocked = ui.paused || ui.botBusy || ["thinking", "acting", "waiting_ack"].includes(bot.status);
  document.querySelectorAll("[data-poker-action]").forEach((button) => {
    button.disabled = blocked || !controls?.legal_actions.includes(button.dataset.pokerAction);
    if (button.dataset.pokerAction === "raise") button.textContent = controls?.raise_open ? "Confirm raise" : "Open raise";
    if (button.dataset.pokerAction === "call") button.textContent = controls?.buttons.find((b) => b.action === "call")?.title || "Call";
  });
  $("bot-raise-amount").disabled = blocked || !controls?.raise_open;
  if (controls?.raise_open) {
    $("bot-raise-amount").required = true;
    $("bot-raise-amount").min = controls.raise_min;
    $("bot-raise-amount").max = controls.raise_max;
    $("bot-raise-limits").textContent = `${money(controls.raise_min)}–${money(controls.raise_max)} additional chips`;
    $("bot-raise-steps").replaceChildren(...(controls.raise_steps || []).map((value) => {
      const option = node("option"); option.value = value; return option;
    }));
    if (ui.raiseToken !== controls.turn_token) $("bot-raise-amount").value = controls.raise_value;
    ui.raiseToken = controls.turn_token;
  } else {
    $("bot-raise-limits").textContent = ui.paused ? "Resume updates for manual moves" : controls?.legal_actions.length ? "Only legal moves are enabled" : "Waiting for your turn";
    ui.raiseToken = null;
  }
  if (!ui.botSettingsLoaded) {
    const settings = bot.settings;
    $("bot-max-action").value = settings.max_action_chips;
    $("bot-loss-limit").value = settings.stop_loss_chips;
    $("bot-hand-limit").value = settings.max_hands;
    $("bot-think-time").value = settings.think_seconds;
    $("bot-samples").value = settings.samples;
    $("bot-policy").value = settings.strategy || "hybrid";
    ui.botSettingsLoaded = true;
  }
  $("bot-history").replaceChildren(...bot.history.map((entry) => {
    const row = node("div", "bot-history-row");
    row.append(node("span", "", `${entry.action.kind.toUpperCase()}${entry.action.amount ? ` ${money(entry.action.amount)}` : ""}`),
      node("span", "small-text", `${entry.hero_cards.join(" ")} · ${entry.board.join(" ") || "Pre-flop"}`),
      node("span", "small-text", entry.acknowledged ? `Confirmed · ${clock(entry.at)}` : entry.error || "Awaiting confirmation"));
    return row;
  }));
}

async function botRequest(path, body) {
  const revision = ++ui.botRequestRevision;
  ui.botBusy = true;
  $("bot-error").hidden = true;
  if (ui.bot) renderBot(ui.bot);
  try {
    const response = await fetch(`/api/bot/${path}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal: AbortSignal.timeout(5000)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The bot request failed");
    if (revision === ui.botRequestRevision) ui.bot = result.bot;
  } catch (error) {
    if (revision === ui.botRequestRevision) {
      $("bot-error").textContent = error.message;
      $("bot-error").hidden = false;
    }
  } finally {
    if (revision === ui.botRequestRevision) {
      ui.botBusy = false;
      if (ui.bot) renderBot(ui.bot);
    }
  }
}

$("bot-start").addEventListener("click", () => {
  if (!$("bot-settings-form").reportValidity()) return;
  botRequest("start", {expected_generation: ui.bot?.generation, strategy: $("bot-policy").value, max_action_chips: Number($("bot-max-action").value), stop_loss_chips: Number($("bot-loss-limit").value), max_hands: Number($("bot-hand-limit").value), think_seconds: Number($("bot-think-time").value), samples: Number($("bot-samples").value)});
});
$("bot-stop").addEventListener("click", () => botRequest("stop", {}));
document.querySelectorAll("[data-poker-action]").forEach((button) => button.addEventListener("click", () => {
  const controls = ui.bot?.controls;
  if (!controls) return;
  const action = button.dataset.pokerAction;
  if (action === "raise" && !controls.raise_open) return botRequest("prepare", {turn_token: controls.turn_token});
  if (action === "raise" && !$("bot-raise-amount").reportValidity()) return;
  botRequest("action", {action, amount: action === "raise" ? Number($("bot-raise-amount").value) : 0, turn_token: controls.turn_token});
}));

showCards($("board-cards"), [], 5);
showCards($("hero-cards"), [], 2);
renderAnalysis();
poll();
