const CELL = 50;
const FILES = "abcdefgh";
const LEFT_MARGIN = 24;
const BOTTOM_MARGIN = 24;
const VIEWBOX_SIZE = CELL * 8 + LEFT_MARGIN; // square viewBox, margin reused on both axes

// Flat vector piece icons (no external assets/fonts - drawn as plain shapes
// in a shared 45x45 local coordinate space, scaled to fit a cell at render
// time). Deliberately simple silhouettes rather than a photorealistic
// classic set - reliable to render crisply at any board size instead of
// depending on how a given OS/browser happens to draw chess Unicode glyphs.
const PIECE_ICON_VIEWBOX = 45;

const PIECE_SHAPES = {
  pawn: [
    { tag: "rect", attrs: { x: 13, y: 36, width: 19, height: 5, rx: 2 } },
    { tag: "polygon", attrs: { points: "16,36 29,36 25,22 20,22" } },
    { tag: "ellipse", attrs: { cx: 22.5, cy: 21, rx: 5, ry: 2 } },
    { tag: "circle", attrs: { cx: 22.5, cy: 13, r: 7 } },
  ],
  rook: [
    { tag: "rect", attrs: { x: 9, y: 36, width: 27, height: 5, rx: 1 } },
    { tag: "polygon", attrs: { points: "13,36 32,36 29,17 16,17" } },
    { tag: "rect", attrs: { x: 14, y: 12, width: 17, height: 5, rx: 1 } },
    { tag: "rect", attrs: { x: 14, y: 6, width: 4, height: 6 } },
    { tag: "rect", attrs: { x: 20.5, y: 6, width: 4, height: 6 } },
    { tag: "rect", attrs: { x: 27, y: 6, width: 4, height: 6 } },
  ],
  bishop: [
    { tag: "rect", attrs: { x: 12, y: 36, width: 21, height: 5, rx: 2 } },
    { tag: "ellipse", attrs: { cx: 22.5, cy: 25, rx: 8, ry: 13 } },
    { tag: "rect", attrs: { x: 19, y: 14, width: 7, height: 5, rx: 1 } },
    { tag: "circle", attrs: { cx: 22.5, cy: 10, r: 6 } },
    { tag: "circle", attrs: { cx: 22.5, cy: 3.5, r: 2.2 } },
  ],
  knight: [
    { tag: "rect", attrs: { x: 11, y: 36, width: 23, height: 5, rx: 2 } },
    {
      tag: "path",
      attrs: {
        d: "M 13,41 L 13,30 C 13,23 16,18 21,15 L 17,13 C 15.5,12.2 15.5,10.2 17,9.5 " +
          "C 20,8 23.5,8 26,9.5 L 33,14 C 36,16 37.5,19.5 37.5,23 L 37.5,26 " +
          "C 37.5,27.2 36.5,28 35.5,27.5 L 33,26 L 33,30 C 33,31 32,31.5 31.2,30.8 " +
          "L 28,28 C 26,29.5 24,30 22,30 L 24,41 Z",
      },
    },
    { tag: "circle", attrs: { cx: 20, cy: 12.5, r: 1.1 } },
  ],
  queen: [
    { tag: "rect", attrs: { x: 10, y: 36, width: 25, height: 5, rx: 2 } },
    { tag: "ellipse", attrs: { cx: 22.5, cy: 25, rx: 9, ry: 12 } },
    { tag: "rect", attrs: { x: 17, y: 15, width: 11, height: 5, rx: 1 } },
    { tag: "polygon", attrs: { points: "14,15 31,15 29,9 16,9" } },
    { tag: "circle", attrs: { cx: 14, cy: 7, r: 2.2 } },
    { tag: "circle", attrs: { cx: 18.25, cy: 6, r: 2.2 } },
    { tag: "circle", attrs: { cx: 22.5, cy: 5.5, r: 2.2 } },
    { tag: "circle", attrs: { cx: 26.75, cy: 6, r: 2.2 } },
    { tag: "circle", attrs: { cx: 31, cy: 7, r: 2.2 } },
  ],
  king: [
    { tag: "rect", attrs: { x: 10, y: 36, width: 25, height: 5, rx: 2 } },
    { tag: "ellipse", attrs: { cx: 22.5, cy: 25, rx: 9, ry: 12 } },
    { tag: "rect", attrs: { x: 17, y: 15, width: 11, height: 5, rx: 1 } },
    { tag: "polygon", attrs: { points: "15,15 30,15 28,10 17,10" } },
    { tag: "rect", attrs: { x: 20.5, y: 1, width: 4, height: 9, rx: 1 } },
    { tag: "rect", attrs: { x: 17.5, y: 3.5, width: 10, height: 4, rx: 1 } },
  ],
};

function buildPieceIcon(pieceType, colorClass) {
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  group.setAttribute("class", `piece-icon ${colorClass}`);

  for (const shape of PIECE_SHAPES[pieceType] || []) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", shape.tag);
    for (const [key, value] of Object.entries(shape.attrs)) {
      el.setAttribute(key, value);
    }
    group.appendChild(el);
  }

  return group;
}

const ROLE_ORDER = [
  "king", "queen", "bishop_1", "bishop_2", "knight_1", "knight_2", "rook_1", "rook_2",
  "pawn_1", "pawn_2", "pawn_3", "pawn_4", "pawn_5", "pawn_6", "pawn_7", "pawn_8",
];

const ROLE_LABELS = {
  king: "Король",
  queen: "Ферзь",
  bishop_1: "Слон (a)",
  bishop_2: "Слон (h)",
  knight_1: "Конь (a)",
  knight_2: "Конь (h)",
  rook_1: "Ладья (a)",
  rook_2: "Ладья (h)",
  pawn_1: "Пешка a",
  pawn_2: "Пешка b",
  pawn_3: "Пешка c",
  pawn_4: "Пешка d",
  pawn_5: "Пешка e",
  pawn_6: "Пешка f",
  pawn_7: "Пешка g",
  pawn_8: "Пешка h",
};

const GATEWAY_POLL_INTERVAL_MS = 5000;

const svg = document.getElementById("board");
const modeSelect = document.getElementById("mode-select");
const colorSelect = document.getElementById("color-select");
const connectionStatus = document.getElementById("connection-status");
const gatewayStatus = document.getElementById("gateway-status");
const bindingsList = document.getElementById("bindings-list");
const messageBar = document.getElementById("message-bar");
const resetButton = document.getElementById("reset-button");
const confirmOverlay = document.getElementById("confirm-overlay");
const confirmText = document.getElementById("confirm-text");
const confirmOkButton = document.getElementById("confirm-ok");
const confirmCancelButton = document.getElementById("confirm-cancel");
const chatFeed = document.getElementById("chat-feed");
const chatShowSystemToggle = document.getElementById("chat-show-system-toggle");
const chatSendForm = document.getElementById("chat-send-form");
const chatSendInput = document.getElementById("chat-send-input");
const clockTurnEl = document.getElementById("clock-turn");
const clockMoveEl = document.getElementById("clock-move");
const clockMatchEl = document.getElementById("clock-match");
const matchStartButton = document.getElementById("match-start-button");
const turnDoneButton = document.getElementById("turn-done-button");
const matchPauseButton = document.getElementById("match-pause-button");
const matchEndButton = document.getElementById("match-end-button");
const sideToMoveSelect = document.getElementById("side-to-move-select");
const stockfishToggle = document.getElementById("stockfish-toggle");
const stockfishResultEl = document.getElementById("stockfish-result");
const evalBarEl = document.getElementById("eval-bar");
const evalBarWhiteEl = document.getElementById("eval-bar-white");
const evalBarLabelEl = document.getElementById("eval-bar-label");
const proposeMoveButton = document.getElementById("propose-move-button");
const orchestratorStatusEl = document.getElementById("orchestrator-status");
const orchestratorLogEl = document.getElementById("orchestrator-log");
const themeToggleButton = document.getElementById("theme-toggle-button");
const robotAlertsEl = document.getElementById("robot-alerts");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

const MOVE_LIMIT_SEC = 5 * 60;
const MATCH_LIMIT_SEC = 2 * 60 * 60;

let currentState = null;
let latestRobots = [];
let gatewayOk = false;
let drag = null; // {square, group, pointerId, offsetX, offsetY}
let lastAnalysis = null; // {from, to, score} - redrawn as an arrow after every render()
let proposingMove = false; // local-only: true while /api/orchestrator/propose-move is in flight
// Flipped so our own side is always nearest the viewer at the bottom -
// matches where the operator physically stands next to the real field.
let boardFlipped = false;
// Signature of the last board rebuild (board + whatever affects piece
// draggability/highlighting). Continuous Stockfish analysis and the chat
// feed broadcast a fresh full state every ~0.5-1s even when the board
// itself hasn't changed - rebuilding the whole SVG board on every single
// one of those needlessly widens the window where a user's pointerdown can
// land on an empty/mid-rebuild board and silently fail to start a drag.
// Skipping the rebuild when nothing board-relevant actually changed keeps
// the DOM (and its pointer listeners) stable except on real moves.
let lastBoardSignature = null;

function squareToXY(square) {
  const file = FILES.indexOf(square[0]);
  const rank = parseInt(square[1], 10);
  const col = boardFlipped ? 7 - file : file;
  const row = boardFlipped ? rank - 1 : 8 - rank;
  return { x: col * CELL, y: row * CELL };
}

function xyToSquare(x, y) {
  let col = Math.floor(x / CELL);
  let row = Math.floor(y / CELL);
  col = Math.max(0, Math.min(7, col));
  row = Math.max(0, Math.min(7, row));
  const file = boardFlipped ? 7 - col : col;
  const rank = boardFlipped ? row + 1 : 8 - row;
  return `${FILES[file]}${rank}`;
}

function svgPoint(evt) {
  const rect = svg.getBoundingClientRect();
  const x = ((evt.clientX - rect.left) / rect.width) * VIEWBOX_SIZE - LEFT_MARGIN;
  const y = ((evt.clientY - rect.top) / rect.height) * VIEWBOX_SIZE;
  return { x, y };
}

function confirmDialog(text) {
  return new Promise((resolve) => {
    confirmText.textContent = text;
    confirmOverlay.hidden = false;

    const cleanup = (result) => {
      confirmOverlay.hidden = true;
      confirmOkButton.removeEventListener("click", onOk);
      confirmCancelButton.removeEventListener("click", onCancel);
      resolve(result);
    };
    const onOk = () => cleanup(true);
    const onCancel = () => cleanup(false);

    confirmOkButton.addEventListener("click", onOk);
    confirmCancelButton.addEventListener("click", onCancel);
  });
}

function showMessage(text, kind) {
  messageBar.textContent = text;
  messageBar.className = `message-bar ${kind || ""}`;
  messageBar.hidden = false;
}

function clearMessage() {
  messageBar.hidden = true;
}

function render(state) {
  currentState = state;
  boardFlipped = state.our_color === "black";
  modeSelect.value = state.mode;
  colorSelect.value = state.our_color;

  renderBindingsPanel(state);
  renderChatFeed(state);
  renderClockPanel(state);
  renderAnalysisPanel(state);
  renderOrchestratorPanel(state);
  renderRobotAlerts(state);
  renderLastMoveBanner(state);

  if (drag) {
    // A drag gesture is in progress on the board - rebuilding the SVG now
    // would remove the dragged element mid-gesture (destroying its pointer
    // capture and event listeners) and abort the drag. The board catches up
    // to the latest state once the gesture ends (see onPointerUp).
    return;
  }

  const signature = JSON.stringify([state.board, state.mode, state.our_color, state.side_to_move, state.last_move]);
  if (signature === lastBoardSignature) {
    // Nothing that affects the board's pieces/highlighting/draggability
    // actually changed since the last rebuild (a very frequent case: every
    // Stockfish analysis tick and every chat event broadcasts the full
    // state) - skip tearing down and rebuilding the SVG to keep pointer
    // listeners stable and avoid narrowing the window for a drag to start.
    return;
  }
  lastBoardSignature = signature;

  renderBoard(state);
}

function renderBoard(state) {
  svg.innerHTML = "";

  for (let rankFromTop = 0; rankFromTop < 8; rankFromTop++) {
    for (let file = 0; file < 8; file++) {
      const isLight = (file + rankFromTop) % 2 === 0;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", LEFT_MARGIN + file * CELL);
      rect.setAttribute("y", rankFromTop * CELL);
      rect.setAttribute("width", CELL);
      rect.setAttribute("height", CELL);
      rect.setAttribute("class", `square ${isLight ? "light" : "dark"}`);
      svg.appendChild(rect);
    }
  }

  renderLabels();
  renderLastMoveHighlight(state);

  for (const [square, piece] of Object.entries(state.board)) {
    svg.appendChild(renderPiece(square, piece, state));
  }

  drawLastMoveArrow(state);
  drawAnalysisArrow();
}

function renderLastMoveHighlight(state) {
  if (!state.last_move) return;

  for (const square of [state.last_move.from, state.last_move.to]) {
    const { x, y } = squareToXY(square);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", LEFT_MARGIN + x);
    rect.setAttribute("y", y);
    rect.setAttribute("width", CELL);
    rect.setAttribute("height", CELL);
    rect.setAttribute("class", "last-move-highlight");
    svg.appendChild(rect);
  }
}

const SQUARE_LABEL_RU = { king: "Король", queen: "Ферзь", rook: "Ладья", bishop: "Слон", knight: "Конь", pawn: "Пешка" };

function renderLastMoveBanner(state) {
  const banner = document.getElementById("last-move-banner");
  const move = state.last_move;

  if (!move) {
    banner.hidden = true;
    return;
  }

  const isOurs = move.color === state.our_color;
  const pieceName = SQUARE_LABEL_RU[move.piece] || move.piece;
  banner.hidden = false;
  banner.classList.toggle("ours", isOurs);
  banner.textContent = isOurs
    ? `✓ Наш ход выполнен: ${pieceName} ${move.from} → ${move.to}`
    : `Ход соперника: ${pieceName} ${move.from} → ${move.to}`;
}

function renderAnalysisPanel(state) {
  sideToMoveSelect.value = state.side_to_move;
  stockfishToggle.checked = state.stockfish_enabled;

  const analysis = state.stockfish_enabled ? state.stockfish_analysis : null;
  lastAnalysis = analysis && analysis.ok ? analysis : null;

  if (!state.stockfish_enabled) {
    stockfishResultEl.textContent = "";
  } else if (!analysis) {
    stockfishResultEl.textContent = "Анализирую…";
  } else if (!analysis.ok) {
    stockfishResultEl.textContent = analysis.error || "Ошибка анализа";
  } else {
    const scoreText = analysis.score === null || analysis.score === undefined
      ? ""
      : ` (оценка: ${(analysis.score / 100).toFixed(2)})`;
    stockfishResultEl.textContent = `Рекомендация: ${analysis.from} → ${analysis.to}${scoreText}`;
  }

  renderEvalBar(state.stockfish_enabled ? analysis : null);

  drawAnalysisArrow();
}

function scoreToWhitePercent(scoreCp) {
  const clamped = Math.max(-1000, Math.min(1000, scoreCp));
  // Logistic-ish curve (roughly matches how eval bars elsewhere map
  // centipawns to a win/advantage share) rather than a plain linear scale,
  // so it doesn't look pointlessly maxed out from a small material edge.
  return 50 + 50 * (2 / (1 + Math.exp(-0.004 * clamped)) - 1);
}

function renderEvalBar(analysis) {
  if (!analysis || !analysis.ok || analysis.score === null || analysis.score === undefined) {
    evalBarEl.hidden = true;
    return;
  }

  evalBarEl.hidden = false;
  evalBarEl.classList.toggle("flipped", boardFlipped);
  const percent = scoreToWhitePercent(analysis.score);
  evalBarWhiteEl.style.height = `${percent}%`;
  evalBarLabelEl.textContent = (analysis.score / 100).toFixed(2);
}

// Shared arrow drawing for both the actual last-move arrow and the
// Stockfish-suggestion arrow - only the CSS variant (color) differs.
function appendBoardArrow(fromSquare, toSquare, variant) {
  const from = squareToXY(fromSquare);
  const to = squareToXY(toSquare);
  const x1 = LEFT_MARGIN + from.x + CELL / 2;
  const y1 = from.y + CELL / 2;
  const x2 = LEFT_MARGIN + to.x + CELL / 2;
  const y2 = to.y + CELL / 2;

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", x1);
  line.setAttribute("y1", y1);
  line.setAttribute("x2", x2);
  line.setAttribute("y2", y2);
  line.setAttribute("class", `board-arrow board-arrow--${variant}`);
  svg.appendChild(line);

  const angle = Math.atan2(y2 - y1, x2 - x1);
  const headLength = 13;
  const headWidth = 9;
  const tipX = x2 - Math.cos(angle) * (CELL / 2 - 8);
  const tipY = y2 - Math.sin(angle) * (CELL / 2 - 8);
  const baseX = tipX - headLength * Math.cos(angle);
  const baseY = tipY - headLength * Math.sin(angle);
  const p1 = `${tipX},${tipY}`;
  const p2 = `${baseX + headWidth * Math.sin(angle)},${baseY - headWidth * Math.cos(angle)}`;
  const p3 = `${baseX - headWidth * Math.sin(angle)},${baseY + headWidth * Math.cos(angle)}`;

  const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  head.setAttribute("points", `${p1} ${p2} ${p3}`);
  head.setAttribute("class", `board-arrow-head board-arrow-head--${variant}`);
  svg.appendChild(head);
}

function drawLastMoveArrow(state) {
  svg.querySelectorAll(".board-arrow--last-move, .board-arrow-head--last-move").forEach((el) => el.remove());
  if (!state.last_move) return;
  appendBoardArrow(state.last_move.from, state.last_move.to, "last-move");
}

function drawAnalysisArrow() {
  svg.querySelectorAll(".board-arrow--analysis, .board-arrow-head--analysis").forEach((el) => el.remove());
  if (!lastAnalysis) return;
  appendBoardArrow(lastAnalysis.from, lastAnalysis.to, "analysis");
}

const ORCHESTRATOR_OUTCOME_LABELS = {
  accepted: "принято",
  accepted_no_quorum: "принято (кворум недоступен)",
  vetoed: "отклонено голосованием",
  escalated_alternative: "предложена альтернатива",
  model_error: "ошибка модели",
  local_validation_exhausted: "модель не смогла предложить легальный ход",
};

function renderOrchestratorPanel(state) {
  // TEMPORARY: also allowed in "view" for debugging the orchestrator
  // end-to-end without switching modes - mirrors the same relaxation in
  // move_orchestrator.py. Narrow back to "manual" only once stable.
  const modeOk = state.mode === "manual" || state.mode === "view";
  const eligible = modeOk && state.side_to_move === state.our_color;
  proposeMoveButton.disabled = proposingMove || !eligible;
  updateOrchestratorStatusText(eligible);

  renderOrchestratorLog(state);
}

// A full round (model calls + up to 3 vote-collection timeouts) can take
// minutes; a static "Идёт согласование хода…" gives no way to tell a slow
// round from a stuck one, so this ticks a live elapsed-seconds counter -
// both from the render() path (on every broadcast) and from its own
// 1s interval so it keeps moving between broadcasts too.
let proposeStartedAt = null;
// Set only while auto-retrying after a round that ended with no move chosen
// at all (model error / model couldn't produce a legal move) - not for a
// round that picked a move but failed to execute it physically, and not for
// static ineligibility errors (wrong mode/turn), see apiProposeMove().
let proposeRetryInfo = null; // {attempt, max}

function updateOrchestratorStatusText(eligible) {
  if (proposingMove) {
    const elapsed = proposeStartedAt ? Math.round((Date.now() - proposeStartedAt) / 1000) : 0;
    const retryText = proposeRetryInfo
      ? ` — повтор ${proposeRetryInfo.attempt}/${proposeRetryInfo.max} (ход не выбран, пробуем снова)`
      : "";
    orchestratorStatusEl.textContent = `Идёт согласование хода… (${elapsed} с)${retryText}`;
  } else {
    orchestratorStatusEl.textContent = eligible
      ? ""
      : "Доступно только в режиме «Ручные ходы» или «Наблюдение» в наш ход";
  }
}

setInterval(() => {
  if (proposingMove) updateOrchestratorStatusText(true);
}, 1000);

function renderOrchestratorLog(state) {
  orchestratorLogEl.innerHTML = "";
  const rounds = state.orchestrator_log || [];

  for (const round of rounds.slice().reverse()) {
    const card = document.createElement("div");
    card.className = "orchestrator-round";

    const final = round.final_proposal;
    const execOk = round.execution && round.execution.ok;
    const title = document.createElement("div");
    title.className = "orchestrator-round-title";
    title.textContent = final
      ? `${final.from} → ${final.to} (${final.piece || ""}) — ${execOk ? "выполнено" : "ошибка исполнения"}`
      : round.in_progress
        ? "Согласование идёт… (попытки появятся ниже по мере готовности)"
        : "Ход не выбран";
    card.appendChild(title);

    for (const attempt of round.attempts || []) {
      const line = document.createElement("div");
      line.className = "orchestrator-attempt";
      const proposal = attempt.proposal;
      const proposalText = proposal && proposal.from ? `${proposal.from} → ${proposal.to}` : "";
      const outcomeText = ORCHESTRATOR_OUTCOME_LABELS[attempt.outcome] || attempt.outcome || "";
      const forcedText = attempt.forced_after_regeneration_limit ? " (без консенсуса)" : "";
      line.textContent = `${proposalText} — ${outcomeText}${forcedText}`;
      card.appendChild(line);
    }

    orchestratorLogEl.appendChild(card);
  }
}

// Static ineligibility errors (wrong mode/wrong turn) - retrying would just
// fail identically forever, so these are never auto-retried.
const PROPOSE_STATIC_ERRORS = new Set([
  "Предложение хода доступно только в режиме «Ручные ходы»",
  "Сейчас не ваш ход",
]);
const MAX_PROPOSE_AUTO_RETRIES = 3;
const PROPOSE_RETRY_DELAY_MS = 2000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiProposeMove() {
  proposingMove = true;
  proposeStartedAt = Date.now();
  proposeRetryInfo = null;
  if (currentState) renderOrchestratorPanel(currentState);

  try {
    for (let attempt = 1; attempt <= MAX_PROPOSE_AUTO_RETRIES; attempt++) {
      let body;
      try {
        const response = await fetch("/api/orchestrator/propose-move", { method: "POST" });
        body = await response.json();
      } catch (err) {
        showMessage(`Сетевая ошибка: ${err}`, "error");
        return;
      }

      if (body.ok) {
        clearMessage();
        return;
      }

      // "round" is only present once a move was actually chosen and taken to
      // execution (execute_move failed) - that's a different failure mode
      // from "no move was selected" and isn't what the user asked to retry.
      const noMoveSelected = !body.round && !PROPOSE_STATIC_ERRORS.has(body.error);
      if (!noMoveSelected || attempt === MAX_PROPOSE_AUTO_RETRIES) {
        showMessage(body.error || "Не удалось согласовать ход", "error");
        return;
      }

      proposeRetryInfo = { attempt, max: MAX_PROPOSE_AUTO_RETRIES };
      if (currentState) renderOrchestratorPanel(currentState);
      await sleep(PROPOSE_RETRY_DELAY_MS);
    }
  } finally {
    proposingMove = false;
    proposeStartedAt = null;
    proposeRetryInfo = null;
    if (currentState) renderOrchestratorPanel(currentState);
  }
}

proposeMoveButton.addEventListener("click", () => apiProposeMove());

async function apiSetSideToMove(color) {
  await fetch("/api/side-to-move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ color }),
  });
}

async function apiSetStockfishEnabled(enabled) {
  await fetch("/api/stockfish/enable", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

sideToMoveSelect.addEventListener("change", () => apiSetSideToMove(sideToMoveSelect.value));

stockfishToggle.addEventListener("change", async () => {
  if (stockfishToggle.checked) {
    const confirmed = await confirmDialog(
      "Регламент запрещает использование шахматных движков для выбора хода во время зачётного матча. " +
      "Включить подсказку Stockfish только для анализа/тренировки?"
    );
    if (!confirmed) {
      stockfishToggle.checked = false;
      return;
    }
  }
  apiSetStockfishEnabled(stockfishToggle.checked);
});

const CLOCK_STATUS_LABELS = {
  idle: "Матч не начат",
  paused: "Матч на паузе",
  finished: "Матч завершён",
};

function renderClockPanel(state) {
  const clock = state.match_clock;

  if (clock.status === "running") {
    const whoLabel = clock.active_color === state.our_color ? "наш ход" : "ход соперника";
    const colorLabel = clock.active_color === "white" ? "Белые" : "Чёрные";
    clockTurnEl.textContent = `Ход: ${colorLabel} (${whoLabel})`;
  } else {
    clockTurnEl.textContent = CLOCK_STATUS_LABELS[clock.status];
  }

  const canPauseOrResume = clock.status === "running" || clock.status === "paused";
  turnDoneButton.disabled = clock.status !== "running";
  matchPauseButton.disabled = !canPauseOrResume;
  matchPauseButton.textContent = clock.status === "paused" ? "Продолжить" : "Пауза";
  matchEndButton.disabled = !canPauseOrResume;

  tickClocks(); // update the numbers immediately instead of waiting up to 1s
}

function formatDuration(totalSeconds) {
  const negative = totalSeconds < 0;
  const abs = Math.abs(Math.trunc(totalSeconds));
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const seconds = abs % 60;
  const pad = (n) => String(n).padStart(2, "0");
  const body = hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
  return negative ? `-${body}` : body;
}

function tickClocks() {
  if (!currentState) return;
  const clock = currentState.match_clock;

  if (clock.status === "idle") {
    clockMoveEl.textContent = formatDuration(MOVE_LIMIT_SEC);
    clockMatchEl.textContent = formatDuration(MATCH_LIMIT_SEC);
    clockMoveEl.classList.remove("overtime");
    clockMatchEl.classList.remove("overtime");
    return;
  }

  // Paused/finished: freeze the display at the moment it stopped instead
  // of the live clock, using the same "reference - started_at" math.
  const referenceNow = clock.status === "running"
    ? Date.now()
    : new Date(clock.frozen_at).getTime();

  const moveElapsed = (referenceNow - new Date(clock.move_started_at).getTime()) / 1000;
  const matchElapsed = (referenceNow - new Date(clock.match_started_at).getTime()) / 1000;
  const moveRemaining = MOVE_LIMIT_SEC - moveElapsed;
  const matchRemaining = MATCH_LIMIT_SEC - matchElapsed;

  clockMoveEl.textContent = formatDuration(moveRemaining);
  clockMatchEl.textContent = formatDuration(matchRemaining);
  clockMoveEl.classList.toggle("overtime", moveRemaining < 0);
  clockMatchEl.classList.toggle("overtime", matchRemaining < 0);
}

async function apiStartMatch() {
  await fetch("/api/match/start", { method: "POST" });
}

async function apiTurnDone() {
  const response = await fetch("/api/match/turn-done", { method: "POST" });
  if (!response.ok) {
    const body = await response.json();
    showMessage(body.detail || "Не удалось переключить ход", "error");
  }
}

async function apiPauseMatch() {
  const response = await fetch("/api/match/pause", { method: "POST" });
  if (!response.ok) {
    const body = await response.json();
    showMessage(body.detail || "Не удалось поставить матч на паузу", "error");
  }
}

async function apiResumeMatch() {
  const response = await fetch("/api/match/resume", { method: "POST" });
  if (!response.ok) {
    const body = await response.json();
    showMessage(body.detail || "Не удалось возобновить матч", "error");
  }
}

async function apiEndMatch() {
  const response = await fetch("/api/match/end", { method: "POST" });
  if (!response.ok) {
    const body = await response.json();
    showMessage(body.detail || "Не удалось завершить матч", "error");
  }
}

matchStartButton.addEventListener("click", async () => {
  if (currentState && currentState.match_clock.status !== "idle") {
    const confirmed = await confirmDialog(
      "Начать матч заново? Текущие часы хода и матча будут сброшены."
    );
    if (!confirmed) return;
  }
  apiStartMatch();
});

turnDoneButton.addEventListener("click", () => apiTurnDone());

matchPauseButton.addEventListener("click", () => {
  if (currentState && currentState.match_clock.status === "paused") {
    apiResumeMatch();
  } else {
    apiPauseMatch();
  }
});

matchEndButton.addEventListener("click", async () => {
  const confirmed = await confirmDialog(
    "Досрочно завершить матч? Часы остановятся; чтобы начать заново, потребуется нажать «Старт матча»."
  );
  if (confirmed) apiEndMatch();
});

setInterval(tickClocks, 1000);

// Gateway sends event_type "command"/"answer" for actual negotiation/move
// text, and "status"/"availability"/"error"/"system" for chatter that isn't
// part of the discussion itself (typing-indicator-style progress pings,
// online/offline flapping, connection errors). Hidden by default - the
// checkbox in the panel header switches to showing everything.
const CHAT_DISCUSSION_EVENT_TYPES = new Set(["command", "answer"]);
let chatShowSystemEvents = false; // local-only UI filter, not persisted

// Stable per-agent color, so the same robot_id/sender always gets the same
// color across renders regardless of join order - hashed rather than
// assigned by first-appearance so it doesn't shift as new agents join mid-match.
const AGENT_COLOR_PALETTE = [
  "#5b8dee", "#c26ce0", "#3ab6a0", "#e0637a",
  "#4fb8d0", "#8f8fe0", "#d97a3f", "#6fb0e8",
];

function colorForAgent(identity) {
  let hash = 0;
  for (let i = 0; i < identity.length; i++) {
    hash = (hash * 31 + identity.charCodeAt(i)) | 0;
  }
  return AGENT_COLOR_PALETTE[Math.abs(hash) % AGENT_COLOR_PALETTE.length];
}

function renderChatFeed(state) {
  chatFeed.innerHTML = "";
  const events = state.chat_events || [];
  const visibleEvents = chatShowSystemEvents
    ? events
    : events.filter((event) => CHAT_DISCUSSION_EVENT_TYPES.has(event.event_type));

  for (const event of visibleEvents) {
    const bubble = document.createElement("div");
    bubble.className = `chat-event ${event.direction || "system"}`;

    if (event.direction === "system") {
      bubble.textContent = `${formatEventTime(event.timestamp)} · ${event.text || event.event_type}`;
    } else {
      const who = event.robot_id || event.sender || "";
      const agentColor = who ? colorForAgent(who) : null;
      if (agentColor) bubble.style.borderLeft = `3px solid ${agentColor}`;

      const meta = document.createElement("span");
      meta.className = "chat-event-meta";
      meta.appendChild(document.createTextNode(`${formatEventTime(event.timestamp)} · `));
      const agentNameEl = document.createElement("span");
      agentNameEl.className = "chat-event-agent";
      agentNameEl.textContent = who;
      if (agentColor) agentNameEl.style.color = agentColor;
      meta.appendChild(agentNameEl);
      bubble.appendChild(meta);
      bubble.appendChild(document.createTextNode(event.text || ""));
    }

    chatFeed.appendChild(bubble);
  }

  chatFeed.scrollTop = chatFeed.scrollHeight;
}

function formatEventTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ru-RU", { hour12: false });
}

function renderRobotAlerts(state) {
  robotAlertsEl.innerHTML = "";
  const alerts = state.robot_alerts || [];

  for (const alert of alerts) {
    const row = document.createElement("div");
    row.className = "robot-alert";

    const text = document.createElement("span");
    text.textContent = alert.text;
    row.appendChild(text);

    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "robot-alert-dismiss";
    dismiss.setAttribute("aria-label", "Скрыть предупреждение");
    dismiss.textContent = "✕";
    dismiss.addEventListener("click", () => apiDismissRobotAlert(alert.id));
    row.appendChild(dismiss);

    robotAlertsEl.appendChild(row);
  }
}

async function apiDismissRobotAlert(alertId) {
  await fetch(`/api/robot-alerts/${alertId}/dismiss`, { method: "POST" });
}

function renderBindingsPanel(state) {
  bindingsList.innerHTML = "";
  if (!state.bindings) return;

  for (const role of ROLE_ORDER) {
    const currentRobotId = state.bindings[role];

    const row = document.createElement("div");
    row.className = "binding-row";

    const label = document.createElement("span");
    label.className = "binding-label";
    label.textContent = ROLE_LABELS[role];
    row.appendChild(label);

    const select = document.createElement("select");
    const seen = new Set();
    const addOption = (robotId, online) => {
      if (seen.has(robotId)) return;
      seen.add(robotId);
      const option = document.createElement("option");
      option.value = robotId;
      option.textContent = online === undefined ? robotId : `${robotId} ${online ? "🟢" : "⚪"}`;
      if (robotId === currentRobotId) option.selected = true;
      select.appendChild(option);
    };

    if (currentRobotId) addOption(currentRobotId, undefined);
    for (const robot of latestRobots) {
      addOption(robot.robot_id, robot.online);
    }

    select.addEventListener("change", () => apiSetBinding(role, select.value));
    row.appendChild(select);
    bindingsList.appendChild(row);
  }
}

async function apiSetBinding(role, robotId) {
  await fetch("/api/bindings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, robot_id: robotId }),
  });
}

async function refreshRobots() {
  try {
    const response = await fetch("/api/robots");
    const body = await response.json();
    gatewayOk = Boolean(body.ok);
    latestRobots = body.ok ? body.robots : [];
  } catch (err) {
    gatewayOk = false;
    latestRobots = [];
  }

  gatewayStatus.textContent = gatewayOk ? "Gateway: подключён" : "Gateway: недоступен";
  gatewayStatus.classList.toggle("disconnected", !gatewayOk);

  if (currentState) renderBindingsPanel(currentState);
}

function renderLabels() {
  for (let row = 0; row < 8; row++) {
    const rank = boardFlipped ? row + 1 : 8 - row;
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", LEFT_MARGIN / 2);
    label.setAttribute("y", row * CELL + CELL / 2);
    label.setAttribute("class", "board-label");
    label.textContent = rank;
    svg.appendChild(label);
  }

  for (let col = 0; col < 8; col++) {
    const file = boardFlipped ? 7 - col : col;
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", LEFT_MARGIN + col * CELL + CELL / 2);
    label.setAttribute("y", CELL * 8 + BOTTOM_MARGIN / 2);
    label.setAttribute("class", "board-label");
    label.textContent = FILES[file];
    svg.appendChild(label);
  }
}

function renderPiece(square, piece, state) {
  const { x, y } = squareToXY(square);
  const cx = LEFT_MARGIN + x + CELL / 2;
  const cy = y + CELL / 2;

  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  group.dataset.square = square;
  // "manual" dispatches real robot commands, so it only allows dragging the
  // side whose turn it currently is; "correct" stays unrestricted (the way
  // to fix an out-of-turn/wrong position); "view" allows only the opponent's
  // pieces - there's no automated tracking, so this is the only way to
  // record what the opponent actually did while keeping our own displayed
  // pieces protected from accidental drags during a live match.
  const draggable =
    state.mode === "correct" ||
    (state.mode === "manual" && piece.color === state.side_to_move) ||
    (state.mode === "view" && piece.color !== state.our_color);
  group.setAttribute("class", `piece ${draggable ? "" : "disabled"}`);

  const isOurs = piece.color === state.our_color;
  if (isOurs) {
    const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    ring.setAttribute("cx", cx);
    ring.setAttribute("cy", cy);
    ring.setAttribute("r", CELL / 2 - 4);
    ring.setAttribute("class", "ours-ring");
    group.appendChild(ring);
  }

  const iconSize = CELL - 10; // small margin inside the cell
  const iconScale = iconSize / PIECE_ICON_VIEWBOX;
  const iconOrigin = PIECE_ICON_VIEWBOX / 2 * iconScale;
  const icon = buildPieceIcon(piece.piece, piece.color === "white" ? "white-piece" : "black-piece");
  icon.setAttribute("transform", `translate(${cx - iconOrigin}, ${cy - iconOrigin}) scale(${iconScale})`);
  group.appendChild(icon);

  if (draggable) {
    group.addEventListener("pointerdown", onPointerDown);
  }

  return group;
}

function onPointerDown(evt) {
  const group = evt.currentTarget;
  const square = group.dataset.square;
  group.setPointerCapture(evt.pointerId);
  group.classList.add("dragging");
  svg.appendChild(group); // raise to top while dragging
  drag = { square, group, pointerId: evt.pointerId };
  group.addEventListener("pointermove", onPointerMove);
  group.addEventListener("pointerup", onPointerUp);
}

function onPointerMove(evt) {
  if (!drag || evt.pointerId !== drag.pointerId) return;
  const { x, y } = svgPoint(evt);
  const origin = squareToXY(drag.square);
  const dx = x - (origin.x + CELL / 2);
  const dy = y - (origin.y + CELL / 2);
  drag.group.setAttribute("transform", `translate(${dx}, ${dy})`);
}

async function onPointerUp(evt) {
  if (!drag || evt.pointerId !== drag.pointerId) return;
  const { x, y } = svgPoint(evt);
  const targetSquare = xyToSquare(x, y);
  const fromSquare = drag.square;

  drag.group.removeEventListener("pointermove", onPointerMove);
  drag.group.removeEventListener("pointerup", onPointerUp);
  drag.group.releasePointerCapture(evt.pointerId);
  drag.group.classList.remove("dragging");
  drag = null;

  if (targetSquare === fromSquare) {
    render(currentState); // snap back, no API call for a no-op drop
    return;
  }

  if (currentState.mode === "manual") {
    const confirmed = await confirmDialog(
      `Переместить фигуру ${fromSquare} → ${targetSquare}? В режиме отладки это отправит команду роботу.`
    );
    if (!confirmed) {
      render(currentState); // snap back
      return;
    }
  }

  apiMove(fromSquare, targetSquare);
}

async function apiMove(from, to) {
  try {
    const response = await fetch("/api/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from, to }),
    });
    const body = await response.json();
    if (!response.ok) {
      showMessage(body.detail || "Ход отклонён", "error");
      render(currentState); // snap back
      return;
    }
    const gatewayResult = body.result && body.result.gateway_result;
    if (gatewayResult) {
      if (gatewayResult.ok) {
        showMessage(`Команда отправлена роботу (${from} → ${to})`, "info");
      } else {
        showMessage(`Ошибка связи с роботом: ${gatewayResult.error}`, "error");
      }
    } else {
      clearMessage();
    }
  } catch (err) {
    showMessage(`Сетевая ошибка: ${err}`, "error");
    render(currentState);
  }
}

async function apiSetMode(mode) {
  await fetch("/api/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

async function apiSetColor(color) {
  await fetch("/api/our-color", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ color }),
  });
}

async function apiResetBoard() {
  await fetch("/api/reset", { method: "POST" });
}

async function apiSendChatMessage(text) {
  const response = await fetch("/api/chat/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return response.json();
}

modeSelect.addEventListener("change", () => apiSetMode(modeSelect.value));
colorSelect.addEventListener("change", () => apiSetColor(colorSelect.value));
resetButton.addEventListener("click", async () => {
  const confirmed = await confirmDialog(
    "Сбросить поле в стартовую позицию? Текущее состояние партии на доске будет потеряно."
  );
  if (confirmed) apiResetBoard();
});

chatShowSystemToggle.addEventListener("change", () => {
  chatShowSystemEvents = chatShowSystemToggle.checked;
  if (currentState) renderChatFeed(currentState);
});

chatSendForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  const text = chatSendInput.value.trim();
  if (!text) return;

  const result = await apiSendChatMessage(text);
  if (result.ok) {
    chatSendInput.value = "";
  } else {
    showMessage(`Не удалось отправить сообщение: ${result.error}`, "error");
  }
});

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

  ws.onopen = () => {
    connectionStatus.textContent = "подключено";
    connectionStatus.classList.remove("disconnected");
  };
  ws.onmessage = (evt) => {
    render(JSON.parse(evt.data));
  };
  ws.onclose = () => {
    connectionStatus.textContent = "нет соединения — переподключение…";
    connectionStatus.classList.add("disconnected");
    setTimeout(connectWebSocket, 1500);
  };
  ws.onerror = () => ws.close();
}

connectWebSocket();
refreshRobots();
setInterval(refreshRobots, GATEWAY_POLL_INTERVAL_MS);

const THEME_STORAGE_KEY = "sokoliki-theme";

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeToggleButton.textContent = theme === "light" ? "🌙" : "☀️";
  localStorage.setItem(THEME_STORAGE_KEY, theme);
}

function initTheme() {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  const preferredLight = window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(stored || (preferredLight ? "light" : "dark"));
}

themeToggleButton.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "light" ? "dark" : "light");
});

initTheme();

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.tab;
    tabButtons.forEach((b) => b.classList.toggle("active", b === button));
    tabPanels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== target;
    });
  });
});
