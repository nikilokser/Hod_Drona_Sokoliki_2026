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

let currentState = null;
let latestRobots = [];
let gatewayOk = false;
let drag = null; // {square, group, pointerId, offsetX, offsetY}

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
}

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
