"""WebSocket connection manager for portfolio updates."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for portfolio updates."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._connection_counter = 0

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and assign it an ID."""
        await websocket.accept()
        connection_id = f"client_{self._connection_counter}"
        self._connection_counter += 1

        self.active_connections[connection_id] = websocket
        logger.info(f"WebSocket client connected: {connection_id}")
        return connection_id

    async def disconnect(self, connection_id: str):
        """Remove a WebSocket connection."""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            logger.info(f"WebSocket client disconnected: {connection_id}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            logger.debug("No active WebSocket connections to broadcast to")
            return

        dead_connections = []
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except WebSocketDisconnect:
                logger.warning(f"WebSocket {connection_id} disconnected during broadcast")
                dead_connections.append(connection_id)
            except Exception as e:
                logger.error(f"Error broadcasting to {connection_id}: {e}")
                dead_connections.append(connection_id)

        # Clean up dead connections
        for connection_id in dead_connections:
            await self.disconnect(connection_id)

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self.active_connections)


class PortfolioBroadcaster:
    """Helper class to broadcast portfolio updates."""

    def __init__(self, manager: ConnectionManager):
        self.manager = manager

    async def broadcast_portfolio_update(
        self,
        total_value: float,
        holdings: dict,
        timestamp: datetime | None = None
    ):
        """Broadcast a portfolio update to all connected clients."""
        if timestamp is None:
            timestamp = datetime.now()

        message = {
            "type": "portfolio_update",
            "total_value": total_value,
            "holdings": holdings,
            "timestamp": timestamp.isoformat()
        }

        await self.manager.broadcast(message)
        logger.debug(f"Broadcast portfolio update: {total_value} AUD")


# Global connection manager instance
connection_manager = ConnectionManager()
portfolio_broadcaster = PortfolioBroadcaster(connection_manager)
