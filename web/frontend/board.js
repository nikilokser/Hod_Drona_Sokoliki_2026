const CELL = 50;
const FILES = "abcdefgh";
const LEFT_MARGIN = 24;
const BOTTOM_MARGIN = 24;
const VIEWBOX_SIZE = CELL * 8 + LEFT_MARGIN; // square viewBox, margin reused on both axes

// Piece artwork is the actual lichess.org piece sets (open-licensed SVGs,
// originally by Colin M.L. Burnett for cburnett and other contributors for
// the rest - see web/frontend/pieces/<set>/), not hand-drawn - a hand-rolled
// shape set didn't read as "real" chess pieces however much it was tuned.
// Each set file is named "<w|b><KQRBNP>.svg" (lichess's own convention),
// so swapping sets is just swapping the URL prefix.
const PIECE_CODE = { king: "K", queen: "Q", rook: "R", bishop: "B", knight: "N", pawn: "P" };
const PIECE_SET_STORAGE_KEY = "sokoliki-piece-set";
const DEFAULT_PIECE_SET = "cburnett";
let pieceSet = localStorage.getItem(PIECE_SET_STORAGE_KEY) || DEFAULT_PIECE_SET;

const AUTO_MOVE_STORAGE_KEY = "sokoliki-auto-move";
// Persisted like the piece set/theme choice - stays on across page reloads
// so a match in progress keeps auto-playing without the operator having to
// remember to re-enable it after e.g. a browser refresh.
let autoMoveEnabled = localStorage.getItem(AUTO_MOVE_STORAGE_KEY) === "true";

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
const boardVariantSelect = document.getElementById("board-variant-select");
const scoreDisplayEl = document.getElementById("score-display");
const confirmOverlay = document.getElementById("confirm-overlay");
const confirmText = document.getElementById("confirm-text");
const confirmOkButton = document.getElementById("confirm-ok");
const confirmCancelButton = document.getElementById("confirm-cancel");
const chatFeed = document.getElementById("chat-feed");
const chatShowSystemToggle = document.getElementById("chat-show-system-toggle");
const chatClearButton = document.getElementById("chat-clear-button");
const chatSendForm = document.getElementById("chat-send-form");
const chatSendInput = document.getElementById("chat-send-input");
const clockTurnEl = document.getElementById("clock-turn");
const clockMoveEl = document.getElementById("clock-move");
const clockMatchEl = document.getElementById("clock-match");
const matchStartButton = document.getElementById("match-start-button");
const turnDoneButton = document.getElementById("turn-done-button");
const matchPauseButton = document.getElementById("match-pause-button");
const matchEndButton = document.getElementById("match-end-button");
const moveLimitInput = document.getElementById("move-limit-input");
const matchLimitInput = document.getElementById("match-limit-input");
const clockSettingsApplyButton = document.getElementById("clock-settings-apply");
const sideToMoveSelect = document.getElementById("side-to-move-select");
const stockfishToggle = document.getElementById("stockfish-toggle");
const stockfishResultEl = document.getElementById("stockfish-result");
const evalBarEl = document.getElementById("eval-bar");
const evalBarWhiteEl = document.getElementById("eval-bar-white");
const evalBarLabelEl = document.getElementById("eval-bar-label");
const proposeMoveButton = document.getElementById("propose-move-button");
const autoMoveToggle = document.getElementById("auto-move-toggle");
const orchestratorStatusEl = document.getElementById("orchestrator-status");
const orchestratorLogEl = document.getElementById("orchestrator-log");
const themeToggleButton = document.getElementById("theme-toggle-button");
const pieceSetSelect = document.getElementById("piece-set-select");
const robotAlertsEl = document.getElementById("robot-alerts");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

// Fallbacks only for the brief window before the first state broadcast
// arrives - after that, the real limits always come from currentState
// (see /api/match/limits), so an operator can change them mid-session.
const DEFAULT_MOVE_LIMIT_SEC = 5 * 60;
const DEFAULT_MATCH_LIMIT_SEC = 2 * 60 * 60;

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
// Same idea as lastBoardSignature, but for the robot-binding dropdowns:
// renderBindingsPanel used to tear down and recreate all 16 <select>
// elements on every single broadcast (same ~0.5-1s cadence as the board).
// Rebuilding a <select> while its native dropdown popup is open, or right
// as a user clicks an <option>, closes the popup / drops the click - this
// is what made choosing a robot feel flaky. Skipping the rebuild when
// bindings/robot list didn't actually change fixes it the same way.
let lastBindingsSignature = null;

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
  if (document.activeElement !== boardVariantSelect) {
    boardVariantSelect.value = state.board_variant;
  }

  renderBindingsPanel(state);
  renderChatFeed(state);
  renderClockPanel(state);
  renderAnalysisPanel(state);
  renderOrchestratorPanel(state);
  renderRobotAlerts(state);
  renderLastMoveBanner(state);
  renderCapturedPanel(state);
  renderUnboundOnlineWarning(state);

  if (drag) {
    // A drag gesture is in progress on the board - rebuilding the SVG now
    // would remove the dragged element mid-gesture (destroying its pointer
    // capture and event listeners) and abort the drag. The board catches up
    // to the latest state once the gesture ends (see onPointerUp).
    return;
  }

  const signature = JSON.stringify([
    state.board,
    state.mode,
    state.our_color,
    state.side_to_move,
    state.last_move,
    state.excluded_roles,
  ]);
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

const capturedTheirsEl = document.getElementById("captured-theirs");
const capturedOursEl = document.getElementById("captured-ours");

// Piece order pieces are traditionally displayed in a captured-material
// tally (highest value first) - purely cosmetic grouping, not a score.
const CAPTURED_SORT_ORDER = ["queen", "rook", "bishop", "knight", "pawn"];

function renderCapturedPanel(state) {
  const score = state.score || { ours: 0, theirs: 0 };
  scoreDisplayEl.textContent = `${score.ours} : ${score.theirs}`;

  const captured = state.captured_pieces || [];
  // Grouped by "ours" vs "theirs" (our_color perspective) rather than raw
  // white/black, so the panel reads correctly regardless of which side we
  // are playing - "Взято у соперника" is always the opponent's material we
  // captured, "Потеряно" is always our own pieces the opponent captured.
  const theirs = captured.filter((p) => p.color !== state.our_color);
  const ours = captured.filter((p) => p.color === state.our_color);
  renderCapturedRow(capturedTheirsEl, theirs);
  renderCapturedRow(capturedOursEl, ours);
}

function renderCapturedRow(container, pieces) {
  container.innerHTML = "";
  const sorted = [...pieces].sort(
    (a, b) => CAPTURED_SORT_ORDER.indexOf(a.piece) - CAPTURED_SORT_ORDER.indexOf(b.piece)
  );
  for (const p of sorted) {
    // A light backdrop chip behind every icon (regardless of theme) -
    // black piece art is solid black with no light outline of its own, so
    // it was invisible against the dark theme's dark panel background
    // without one.
    const chip = document.createElement("div");
    chip.className = "captured-piece-chip";

    const img = document.createElement("img");
    const colorCode = p.color === "white" ? "w" : "b";
    img.src = `/pieces/${pieceSet}/${colorCode}${PIECE_CODE[p.piece]}.svg`;
    img.alt = `${p.color} ${p.piece}`;
    img.className = "captured-piece-icon";
    chip.appendChild(img);
    container.appendChild(chip);
  }
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
  illegal: "невозможный ход",
  local_validation_exhausted: "модель не смогла предложить легальный ход",
};

const VOTE_KIND_LABELS = {
  yes: "да",
  no: "нет",
  move: "предложил другой ход",
  // "noise" covers any answer that came back but didn't match the expected
  // ДА:/НЕТ:/ХОД: protocol - e.g. a robot's agent replying with its own
  // canned "command not supported" text because it doesn't actually
  // recognize the [ГОЛОСОВАНИЕ] prefix as a valid input at all. It doesn't
  // count toward the decision, but it's still worth showing: the robot DID
  // answer, just not usefully - different from no_response (didn't answer
  // at all).
  noise: "ответ не по формату",
};

function renderOrchestratorPanel(state) {
  // TEMPORARY: also allowed in "view" for debugging the orchestrator
  // end-to-end without switching modes - mirrors the same relaxation in
  // move_orchestrator.py. Narrow back to "manual" only once stable.
  const modeOk = state.mode === "manual" || state.mode === "view";
  const eligible = modeOk && state.side_to_move === state.our_color;
  proposeMoveButton.disabled = proposingMove || !eligible;
  autoMoveToggle.checked = autoMoveEnabled;
  updateOrchestratorStatusText(eligible);

  renderOrchestratorLog(state);

  // Auto-play: whenever it becomes our turn during a running match with
  // "Автоход" on, propose a move without waiting for a manual click - this
  // is also what makes play start immediately right after "Старт матча"
  // (that broadcast flips eligible to true on the very next render()).
  // Gated on the match clock actually running so auto-move doesn't start
  // firing real strong-model calls during setup/testing before a match has
  // been started. proposingMove itself is the re-entrancy guard - it's set
  // synchronously at the top of apiProposeMove(), before any await, so a
  // burst of broadcasts while a round is already in flight can't trigger a
  // second overlapping call.
  if (autoMoveEnabled && eligible && !proposingMove && state.match_clock.status === "running") {
    apiProposeMove();
  }
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
      const reasonText = attempt.outcome === "illegal" && attempt.reason ? `: ${attempt.reason}` : "";
      line.textContent = `${proposalText} — ${outcomeText}${reasonText}${forcedText}`;
      card.appendChild(line);

      // The model's own reasoning for the proposal - shown regardless of
      // whether any agents voted on it (accepted_no_quorum in particular has
      // no votes to show at all, so this is the only content that explains
      // why this move was picked).
      if (proposal && proposal.reasoning) {
        const reasoningLine = document.createElement("div");
        reasoningLine.className = "orchestrator-attempt orchestrator-reasoning";
        reasoningLine.textContent = proposal.reasoning;
        card.appendChild(reasoningLine);
      }

      if (attempt.votes && attempt.votes.length > 0) {
        // Per-robot breakdown, not just the round's aggregate outcome -
        // makes it visible that an agent actually took part in the
        // discussion even when its vote didn't end up swaying anything
        // (e.g. a lone "нет" against an otherwise silent quorum, or a
        // reply that came back but was off-protocol noise).
        for (const vote of attempt.votes) {
          const voteLine = document.createElement("div");
          voteLine.className = `orchestrator-attempt orchestrator-vote orchestrator-vote-${vote.kind}`;
          const kindText = VOTE_KIND_LABELS[vote.kind] || vote.kind;
          const moveText = vote.kind === "move" && vote.move ? ` ${vote.move.from}-${vote.move.to}` : "";
          const reasonText = vote.reason ? `: ${vote.reason}` : "";
          voteLine.textContent = `${vote.robot_id} — ${kindText}${moveText}${reasonText}`;
          card.appendChild(voteLine);
        }
      }

      if (attempt.no_response && attempt.no_response.length > 0) {
        // Quorum members who were asked to vote but never returned a usable
        // answer (LLM connection failure, malformed plan, etc. on the
        // robot's own side) - surfaced separately from real votes so it's
        // clear "accepted" doesn't always mean everyone actually weighed in.
        const noResponseLine = document.createElement("div");
        noResponseLine.className = "orchestrator-attempt orchestrator-no-response";
        noResponseLine.textContent = `Не ответили: ${attempt.no_response.join(", ")}`;
        card.appendChild(noResponseLine);
      }
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

function gameResultText(gameResult, ourColor) {
  if (!gameResult) return null;
  if (gameResult.kind === "checkmate") {
    const winnerLabel = gameResult.winner === ourColor ? "мы победили" : "победил соперник";
    return `Мат — ${winnerLabel} (${gameResult.winner === "white" ? "белые" : "чёрные"})`;
  }
  if (gameResult.kind === "stalemate") {
    return "Пат — партия окончена, победитель по сумме очков";
  }
  return null;
}

function renderClockPanel(state) {
  const clock = state.match_clock;
  const resultText = gameResultText(state.game_result, state.our_color);

  if (resultText) {
    clockTurnEl.textContent = resultText;
  } else if (clock.status === "running") {
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

  syncClockSettingsInputs(state);
  tickClocks(); // update the numbers immediately instead of waiting up to 1s
}

// Only overwrites the number inputs when the operator isn't actively editing
// them - render() runs on every broadcast (every ~0.5-1s while Stockfish is
// on), so unconditionally overwriting .value would make it impossible to
// type a new limit.
function syncClockSettingsInputs(state) {
  const moveLimitMin = Math.round((state.move_limit_sec ?? DEFAULT_MOVE_LIMIT_SEC) / 60);
  const matchLimitMin = Math.round((state.match_limit_sec ?? DEFAULT_MATCH_LIMIT_SEC) / 60);
  if (document.activeElement !== moveLimitInput) moveLimitInput.value = moveLimitMin;
  if (document.activeElement !== matchLimitInput) matchLimitInput.value = matchLimitMin;
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
  const moveLimitSec = currentState.move_limit_sec ?? DEFAULT_MOVE_LIMIT_SEC;
  const matchLimitSec = currentState.match_limit_sec ?? DEFAULT_MATCH_LIMIT_SEC;

  if (clock.status === "idle") {
    clockMoveEl.textContent = formatDuration(moveLimitSec);
    clockMatchEl.textContent = formatDuration(matchLimitSec);
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
  const moveRemaining = moveLimitSec - moveElapsed;
  const matchRemaining = matchLimitSec - matchElapsed;

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

async function apiSetMatchLimits(moveLimitSec, matchLimitSec) {
  const response = await fetch("/api/match/limits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ move_limit_sec: moveLimitSec, match_limit_sec: matchLimitSec }),
  });
  if (!response.ok) {
    const body = await response.json();
    showMessage(body.detail || "Не удалось применить лимиты времени", "error");
    return;
  }
  clearMessage();
}

clockSettingsApplyButton.addEventListener("click", () => {
  const moveLimitMin = Number(moveLimitInput.value);
  const matchLimitMin = Number(matchLimitInput.value);
  if (!(moveLimitMin > 0) || !(matchLimitMin > 0)) {
    showMessage("Лимиты времени должны быть положительными числами", "error");
    return;
  }
  apiSetMatchLimits(Math.round(moveLimitMin * 60), Math.round(matchLimitMin * 60));
});

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
  if (!state.bindings) return;

  const excludedRoles = state.excluded_roles || [];
  const signature = JSON.stringify([state.bindings, latestRobots, excludedRoles]);
  if (signature === lastBindingsSignature) {
    // Nothing that affects the dropdowns' options/selection actually
    // changed since the last rebuild - skip tearing down the <select>
    // elements so an open dropdown or an in-flight option click survives
    // the frequent broadcasts driven by Stockfish/chat activity.
    return;
  }
  lastBindingsSignature = signature;

  bindingsList.innerHTML = "";

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

    // A small pill switch rather than a bare native checkbox - reads much
    // more clearly as "this piece is turned off" at the tiny size these
    // rows have room for.
    const excludeLabel = document.createElement("label");
    excludeLabel.className = "role-toggle";
    excludeLabel.title = "Исключить фигуру из ходов (робот сломан/недоступен)";
    const excludeCheckbox = document.createElement("input");
    excludeCheckbox.type = "checkbox";
    excludeCheckbox.className = "role-toggle-input";
    excludeCheckbox.checked = excludedRoles.includes(role);
    excludeCheckbox.addEventListener("change", () =>
      apiSetRoleExcluded(role, excludeCheckbox.checked)
    );
    const track = document.createElement("span");
    track.className = "role-toggle-track";
    const thumb = document.createElement("span");
    thumb.className = "role-toggle-thumb";
    track.appendChild(thumb);
    excludeLabel.appendChild(excludeCheckbox);
    excludeLabel.appendChild(track);
    row.appendChild(excludeLabel);

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

async function apiSetRoleExcluded(role, excluded) {
  await fetch("/api/bindings/exclude", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, excluded }),
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

  if (currentState) {
    renderBindingsPanel(currentState);
    renderUnboundOnlineWarning(currentState);
  }
}

// A robot can be online in the Gateway's registry and still never get
// asked to vote in a move negotiation, silently, if it isn't bound to any
// piece currently on the board (compute_quorum in move_orchestrator.py
// requires both) - e.g. bindings still pointing at placeholder robot_ids
// that don't match the real fleet. Surfacing this explicitly is what makes
// that fixable instead of a mystery "why doesn't it ever vote".
function renderUnboundOnlineWarning(state) {
  const el = document.getElementById("unbound-online-warning");
  if (!state.board) {
    el.hidden = true;
    return;
  }

  const boundRobotIds = new Set(
    Object.values(state.board).map((occupant) => occupant.robot_id).filter(Boolean)
  );
  const unbound = latestRobots.filter(
    (robot) =>
      robot.online && robot.enabled && robot.type !== "peshka" && !boundRobotIds.has(robot.robot_id)
  );

  if (unbound.length === 0) {
    el.hidden = true;
    return;
  }

  el.hidden = false;
  el.textContent =
    `Онлайн, но не привязаны ни к одной фигуре: ${unbound.map((r) => r.robot_id).join(", ")} — ` +
    "не будут участвовать в голосовании ИИ, пока не привязаны ниже.";
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
  // A role excluded via the "Привязка роботов" tab means its robot is known
  // broken/unavailable - the backend refuses to dispatch a command for it
  // (see execute_move in move_orchestrator.py), so dragging it in "manual"
  // is blocked here too rather than letting the operator hit a rejection
  // after the fact. "correct" stays exempt on purpose: it's pure board-state
  // bookkeeping, never dispatches a robot command, so exclusion doesn't
  // apply there.
  const isExcluded = Boolean(piece.role) && (state.excluded_roles || []).includes(piece.role);
  // "manual" dispatches real robot commands but is a debug mode - any piece
  // can be dragged regardless of whose turn it officially is; "correct"
  // stays unrestricted too (the way to fix an out-of-turn/wrong position);
  // "view" allows only the opponent's pieces - there's no automated
  // tracking, so this is the only way to record what the opponent actually
  // did while keeping our own displayed pieces protected from accidental
  // drags during a live match.
  const draggable =
    state.mode === "correct" ||
    (state.mode === "manual" && !isExcluded) ||
    (state.mode === "view" && piece.color !== state.our_color);
  group.setAttribute(
    "class",
    `piece ${draggable ? "" : "disabled"} ${isExcluded ? "piece-excluded" : ""}`
  );

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
  const colorCode = piece.color === "white" ? "w" : "b";
  const image = document.createElementNS("http://www.w3.org/2000/svg", "image");
  image.setAttribute("href", `/pieces/${pieceSet}/${colorCode}${PIECE_CODE[piece.piece]}.svg`);
  image.setAttribute("x", cx - iconSize / 2);
  image.setAttribute("y", cy - iconSize / 2);
  image.setAttribute("width", iconSize);
  image.setAttribute("height", iconSize);
  image.setAttribute("class", "piece-image");
  group.appendChild(image);

  if (isExcluded) {
    // A dimmed ring alone was too subtle to actually read as "excluded" at
    // a glance - an explicit badge in the corner is unambiguous regardless
    // of piece color/theme.
    const badge = document.createElementNS("http://www.w3.org/2000/svg", "text");
    badge.setAttribute("x", cx + CELL / 2 - 6);
    badge.setAttribute("y", cy - CELL / 2 + 8);
    badge.setAttribute("class", "piece-excluded-badge");
    badge.textContent = "⛔";
    group.appendChild(badge);
  }

  if (draggable) {
    group.addEventListener("pointerdown", onPointerDown);
    // Same permission rule as dragging (view: opponent pieces only;
    // correct/manual: unrestricted) - right-click is the affordance for
    // removing a piece entirely (a capture the judge physically took off
    // the field, or a board-state correction with no destination square).
    group.addEventListener("contextmenu", onPieceContextMenu);
  }

  return group;
}

async function onPieceContextMenu(evt) {
  evt.preventDefault();
  const square = evt.currentTarget.dataset.square;
  const piece = currentState.board[square];
  if (!piece) return;

  const pieceName = SQUARE_LABEL_RU[piece.piece] || piece.piece;
  const confirmed = await confirmDialog(`Удалить фигуру с клетки ${square} (${pieceName})?`);
  if (!confirmed) return;

  try {
    const response = await fetch("/api/delete-piece", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ square }),
    });
    const body = await response.json();
    if (!response.ok) {
      showMessage(body.detail || "Не удалось удалить фигуру", "error");
      return;
    }
    clearMessage();
  } catch (err) {
    showMessage(`Сетевая ошибка: ${err}`, "error");
  }
}

function onPointerDown(evt) {
  const group = evt.currentTarget;
  const square = group.dataset.square;
  // setPointerCapture is requested for its side benefits (suppresses text
  // selection/native touch scrolling for the gesture), but move/up/cancel
  // listeners are attached to `window`, not `group` - relying on the
  // captured element to keep receiving events meant hit-testing (not true
  // capture redirection) sometimes decided differently once a fast/long
  // drag moved the pointer far from the piece's still-catching-up visual
  // position, silently dropping the rest of the gesture. `window` always
  // sees every pointermove/pointerup regardless of what's visually
  // underneath, so the pointerId check below is what scopes it correctly.
  group.setPointerCapture(evt.pointerId);
  group.classList.add("dragging");
  svg.appendChild(group); // raise to top while dragging
  drag = { square, group, pointerId: evt.pointerId };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
  // The OS/browser can cancel an in-progress pointer gesture without ever
  // firing pointerup - alt-tabbing away, a touch scroll/zoom gesture taking
  // over, the pointer device disconnecting. Without handling this, `drag`
  // would stay non-null forever, which permanently blocks render()'s
  // `if (drag) return` guard - freezing the entire board (no future
  // opponent moves or broadcasts would ever redraw it again).
  window.addEventListener("pointercancel", onPointerCancel);
}

function onPointerMove(evt) {
  if (!drag || evt.pointerId !== drag.pointerId) return;
  const { x, y } = svgPoint(evt);
  const origin = squareToXY(drag.square);
  const dx = x - (origin.x + CELL / 2);
  const dy = y - (origin.y + CELL / 2);
  drag.group.setAttribute("transform", `translate(${dx}, ${dy})`);
}

function endDragGesture(evt) {
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerup", onPointerUp);
  window.removeEventListener("pointercancel", onPointerCancel);
  try {
    drag.group.releasePointerCapture(evt.pointerId);
  } catch {
    // Capture may already be gone (e.g. on pointercancel) - nothing to do.
  }
  drag.group.classList.remove("dragging");
  drag = null;
}

function onPointerCancel(evt) {
  if (!drag || evt.pointerId !== drag.pointerId) return;
  endDragGesture(evt);
  snapBackBoard(); // clear the leftover drag transform, piece returns home
}

async function onPointerUp(evt) {
  if (!drag || evt.pointerId !== drag.pointerId) return;
  const { x, y } = svgPoint(evt);
  const targetSquare = xyToSquare(x, y);
  const fromSquare = drag.square;

  endDragGesture(evt);

  if (targetSquare === fromSquare) {
    snapBackBoard(); // no-op drop, no API call
    return;
  }

  if (currentState.mode === "manual") {
    const confirmed = await confirmDialog(
      `Переместить фигуру ${fromSquare} → ${targetSquare}? В режиме отладки это отправит команду роботу.`
    );
    if (!confirmed) {
      snapBackBoard();
      return;
    }
  }

  apiMove(fromSquare, targetSquare);
}

// Forces the board's <g> pieces to redraw at their real positions even when
// state.board itself hasn't changed (a rejected/cancelled/no-op drag left a
// piece mid-transform) - render()'s lastBoardSignature check would
// otherwise skip the rebuild entirely since nothing state-wise changed.
function snapBackBoard() {
  if (currentState) renderBoard(currentState);
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
      snapBackBoard();
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
    snapBackBoard();
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

async function apiSetBoardVariant(variant) {
  await fetch("/api/board-variant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variant }),
  });
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

boardVariantSelect.addEventListener("change", async () => {
  const confirmed = await confirmDialog(
    "Сменить расстановку и сразу сбросить поле? Текущее состояние партии будет потеряно."
  );
  if (confirmed) {
    apiSetBoardVariant(boardVariantSelect.value);
  } else if (currentState) {
    boardVariantSelect.value = currentState.board_variant;
  }
});

chatShowSystemToggle.addEventListener("change", () => {
  chatShowSystemEvents = chatShowSystemToggle.checked;
  if (currentState) renderChatFeed(currentState);
});

chatClearButton.addEventListener("click", async () => {
  const confirmed = await confirmDialog(
    "Очистить ленту переговоров? Это скроет текущую историю в интерфейсе " +
    "(лог на диске не удаляется)."
  );
  if (confirmed) await fetch("/api/chat/clear", { method: "POST" });
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

pieceSetSelect.value = pieceSet;
pieceSetSelect.addEventListener("change", () => {
  pieceSet = pieceSetSelect.value;
  localStorage.setItem(PIECE_SET_STORAGE_KEY, pieceSet);
  if (currentState) {
    renderBoard(currentState); // repaint pieces with the new set immediately
    renderCapturedPanel(currentState);
  }
});

autoMoveToggle.addEventListener("change", () => {
  autoMoveEnabled = autoMoveToggle.checked;
  localStorage.setItem(AUTO_MOVE_STORAGE_KEY, String(autoMoveEnabled));
  // Re-run the eligibility/auto-trigger check immediately on enabling,
  // rather than waiting for the next broadcast - e.g. turning it on mid-
  // match while it's already our turn should start playing right away.
  if (currentState) renderOrchestratorPanel(currentState);
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.tab;
    tabButtons.forEach((b) => b.classList.toggle("active", b === button));
    tabPanels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== target;
    });
  });
});
