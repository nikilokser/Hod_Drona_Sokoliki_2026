const CELL = 50;
const FILES = "abcdefgh";

const GLYPHS = {
  white: { king: "♔", queen: "♕", rook: "♖", bishop: "♗", knight: "♘", pawn: "♙" },
  black: { king: "♚", queen: "♛", rook: "♜", bishop: "♝", knight: "♞", pawn: "♟" },
};

const svg = document.getElementById("board");
const modeSelect = document.getElementById("mode-select");
const colorSelect = document.getElementById("color-select");
const connectionStatus = document.getElementById("connection-status");
const messageBar = document.getElementById("message-bar");

let currentState = null;
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
  const x = ((evt.clientX - rect.left) / rect.width) * 400;
  const y = ((evt.clientY - rect.top) / rect.height) * 400;
  return { x, y };
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
      rect.setAttribute("x", file * CELL);
      rect.setAttribute("y", rankFromTop * CELL);
      rect.setAttribute("width", CELL);
      rect.setAttribute("height", CELL);
      rect.setAttribute("class", `square ${isLight ? "light" : "dark"}`);
      svg.appendChild(rect);
    }
  }

  for (const [square, piece] of Object.entries(state.board)) {
    svg.appendChild(renderPiece(square, piece, state));
  }
}

function renderPiece(square, piece, state) {
  const { x, y } = squareToXY(square);
  const cx = x + CELL / 2;
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

function onPointerUp(evt) {
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

modeSelect.addEventListener("change", () => apiSetMode(modeSelect.value));
colorSelect.addEventListener("change", () => apiSetColor(colorSelect.value));

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
