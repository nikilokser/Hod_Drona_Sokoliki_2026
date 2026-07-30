from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, initial_state: dict) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        await websocket.send_json(initial_state)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, state: dict) -> None:
        stale: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(state)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)
