const CELL = 50;
const FILES = "abcdefgh";
const LEFT_MARGIN = 24;
const BOTTOM_MARGIN = 24;
const VIEWBOX_SIZE = CELL * 8 + LEFT_MARGIN; // square viewBox, margin reused on both axes

const GLYPHS = {
  white: { king: "♔", queen: "♕", rook: "♖", bishop: "♗", knight: "♘", pawn: "♙" },
  black: { king: "♚", queen: "♛", rook: "♜", bishop: "♝", knight: "♞", pawn: "♟" },
};

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

const MOVE_LIMIT_SEC = 5 * 60;
const MATCH_LIMIT_SEC = 2 * 60 * 60;

let currentState = null;
let latestRobots = [];
let gatewayOk = false;
let drag = null; // {square, group, pointerId, offsetX, offsetY}
let lastAnalysis = null; // {from, to, score} - redrawn as an arrow after every render()

function squareToXY(square) {
  const file = FILES.indexOf(square[0]);
  const rank = parseInt(square[1], 10);
  return { x: file * CELL, y: (8 - rank) * CELL };
}

function xyToSquare(x, y) {
  let file = Math.floor(x / CELL);
  let rankFromTop = Math.floor(y / CELL);
  file = Math.max(0, Math.min(7, file));
  rankFromTop = Math.max(0, Math.min(7, rankFromTop));
  const rank = 8 - rankFromTop;
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
  modeSelect.value = state.mode;
  colorSelect.value = state.our_color;

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

  for (const [square, piece] of Object.entries(state.board)) {
    svg.appendChild(renderPiece(square, piece, state));
  }

  renderBindingsPanel(state);
  renderChatFeed(state);
  renderClockPanel(state);
  renderAnalysisPanel(state);
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

  drawAnalysisArrow();
}

function drawAnalysisArrow() {
  const existing = svg.querySelectorAll(".analysis-arrow, .analysis-arrow-head");
  existing.forEach((el) => el.remove());

  if (!lastAnalysis) return;

  const from = squareToXY(lastAnalysis.from);
  const to = squareToXY(lastAnalysis.to);
  const x1 = LEFT_MARGIN + from.x + CELL / 2;
  const y1 = from.y + CELL / 2;
  const x2 = LEFT_MARGIN + to.x + CELL / 2;
  const y2 = to.y + CELL / 2;

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", x1);
  line.setAttribute("y1", y1);
  line.setAttribute("x2", x2);
  line.setAttribute("y2", y2);
  line.setAttribute("class", "analysis-arrow");
  svg.appendChild(line);

  const angle = Math.atan2(y2 - y1, x2 - x1);
  const headLength = 10;
  const headWidth = 7;
  const tipX = x2 - Math.cos(angle) * (CELL / 2 - 6);
  const tipY = y2 - Math.sin(angle) * (CELL / 2 - 6);
  const baseX = tipX - headLength * Math.cos(angle);
  const baseY = tipY - headLength * Math.sin(angle);
  const p1 = `${tipX},${tipY}`;
  const p2 = `${baseX + headWidth * Math.sin(angle)},${baseY - headWidth * Math.cos(angle)}`;
  const p3 = `${baseX - headWidth * Math.sin(angle)},${baseY + headWidth * Math.cos(angle)}`;

  const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  head.setAttribute("points", `${p1} ${p2} ${p3}`);
  head.setAttribute("class", "analysis-arrow-head");
  svg.appendChild(head);
}

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

function renderChatFeed(state) {
  chatFeed.innerHTML = "";
  const events = state.chat_events || [];

  for (const event of events) {
    const bubble = document.createElement("div");
    bubble.className = `chat-event ${event.direction || "system"}`;

    if (event.direction === "system") {
      bubble.textContent = `${formatEventTime(event.timestamp)} · ${event.text || event.event_type}`;
    } else {
      const meta = document.createElement("span");
      meta.className = "chat-event-meta";
      const who = event.robot_id || event.sender || "";
      meta.textContent = `${formatEventTime(event.timestamp)} · ${who}`;
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
  for (let rankFromTop = 0; rankFromTop < 8; rankFromTop++) {
    const rank = 8 - rankFromTop;
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", LEFT_MARGIN / 2);
    label.setAttribute("y", rankFromTop * CELL + CELL / 2);
    label.setAttribute("class", "board-label");
    label.textContent = rank;
    svg.appendChild(label);
  }

  for (let file = 0; file < 8; file++) {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", LEFT_MARGIN + file * CELL + CELL / 2);
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
  const draggable = state.mode !== "view";
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

  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("x", cx);
  text.setAttribute("y", cy);
  text.setAttribute(
    "class",
    `piece-glyph ${piece.color === "white" ? "white-piece" : "black-piece"}`
  );
  text.textContent = GLYPHS[piece.color][piece.piece];
  group.appendChild(text);

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
