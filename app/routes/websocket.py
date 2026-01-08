"""WebSocket handler for real-time updates."""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..bot_manager import get_bot_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    manager = get_bot_manager()

    await manager.connection_manager.connect(websocket)

    try:
        # Send current state on connect
        await websocket.send_json({
            "type": "state",
            "state": manager.state.value
        })

        # Send current status if bot is running
        status = manager.get_status()
        if status.get("stats"):
            await websocket.send_json({
                "type": "status",
                **status
            })

        # Send buffered logs
        for log in manager.get_log_buffer():
            await websocket.send_json(log)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages (ping/pong or commands)
                data = await websocket.receive_text()
                logger.debug(f"WebSocket received: {data}")
            except WebSocketDisconnect:
                break

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.connection_manager.disconnect(websocket)
