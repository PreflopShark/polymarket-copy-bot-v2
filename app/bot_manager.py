"""Bot lifecycle manager - handles start/stop and event broadcasting."""

import asyncio
import logging
from enum import Enum
from typing import Optional, Set, Dict, Any
from datetime import datetime

from fastapi import WebSocket

from .config import BotConfig, get_config
from .services.copy_bot import CopyBot

logger = logging.getLogger(__name__)


class BotState(str, Enum):
    """Bot lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class ConnectionManager:
    """Manages WebSocket connections for broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)


class BotManager:
    """Manages bot lifecycle and provides event hooks."""

    def __init__(self):
        self.state = BotState.STOPPED
        self.bot: Optional[CopyBot] = None
        self._task: Optional[asyncio.Task] = None
        self.session_summary: Optional[dict] = None
        self.connection_manager = ConnectionManager()

        # Log buffer for new connections
        self.log_buffer: list = []
        self.max_log_buffer = 200

    async def _on_log(self, event: dict):
        """Handle log events from bot."""
        # Buffer for new connections
        self.log_buffer.append(event)
        if len(self.log_buffer) > self.max_log_buffer:
            self.log_buffer.pop(0)

        # Broadcast to clients
        await self.connection_manager.broadcast(event)

    async def _on_trade(self, event: dict):
        """Handle trade events from bot."""
        await self.connection_manager.broadcast({
            "type": "trade",
            **event
        })

    async def _on_status(self, status: dict):
        """Handle status updates from bot."""
        await self.connection_manager.broadcast({
            "type": "status",
            **status
        })

    async def start(self) -> dict:
        """Start the bot."""
        if self.state != BotState.STOPPED:
            return {"success": False, "error": f"Bot is {self.state.value}"}

        self.state = BotState.STARTING
        await self.connection_manager.broadcast({
            "type": "state",
            "state": self.state.value
        })

        try:
            config = get_config()

            if not config.target_wallet:
                self.state = BotState.STOPPED
                return {"success": False, "error": "No target wallet configured"}

            # Create bot with event callbacks
            self.bot = CopyBot(config)
            self.bot.set_callbacks(
                on_log=self._on_log,
                on_trade=self._on_trade,
                on_status=self._on_status,
            )

            # Clear previous session data
            self.log_buffer.clear()
            self.session_summary = None

            # Start bot in background task
            self._task = asyncio.create_task(self._run_bot())

            self.state = BotState.RUNNING
            await self.connection_manager.broadcast({
                "type": "state",
                "state": self.state.value
            })

            return {"success": True, "message": "Bot started"}

        except Exception as e:
            logger.exception("Failed to start bot")
            self.state = BotState.STOPPED
            await self.connection_manager.broadcast({
                "type": "state",
                "state": self.state.value
            })
            return {"success": False, "error": str(e)}

    async def _run_bot(self):
        """Run the bot and handle completion."""
        try:
            self.session_summary = await self.bot.run()
        except Exception as e:
            logger.exception("Bot crashed")
            self.session_summary = {
                "error": str(e),
                "end_time": datetime.now().isoformat(),
            }
        finally:
            self.state = BotState.STOPPED
            await self.connection_manager.broadcast({
                "type": "state",
                "state": self.state.value
            })
            await self.connection_manager.broadcast({
                "type": "session_complete",
                "summary": self.session_summary
            })

    async def stop(self) -> dict:
        """Stop the bot gracefully."""
        if self.state != BotState.RUNNING:
            return {"success": False, "error": f"Bot is not running (state: {self.state.value})"}

        self.state = BotState.STOPPING
        await self.connection_manager.broadcast({
            "type": "state",
            "state": self.state.value
        })

        # Signal bot to stop
        if self.bot:
            self.bot.request_stop()

        # Wait for task to complete (with timeout)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Bot stop timeout, cancelling task")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        return {
            "success": True,
            "message": "Bot stopped",
            "summary": self.session_summary
        }

    def get_status(self) -> dict:
        """Get current bot status."""
        result = {
            "state": self.state.value,
            "stats": None,
            "paper": None,
        }

        if self.bot and self.state == BotState.RUNNING:
            status = self.bot.get_status()
            result["stats"] = status.get("stats")
            result["paper"] = status.get("paper")
            result["start_time"] = status.get("start_time")
            result["runtime_seconds"] = status.get("runtime_seconds")
            result["skip_reasons"] = status.get("skip_reasons")

        return result

    def get_portfolio(self) -> dict:
        """Get current portfolio state."""
        if not self.bot or not self.bot.paper_trader:
            config = get_config()
            return {
                "usdc_balance": config.initial_balance,
                "portfolio_value": config.initial_balance,
                "pnl": 0,
                "pnl_percentage": 0,
                "positions": [],
            }

        pt = self.bot.paper_trader
        pnl, pnl_pct = pt.get_pnl()
        return {
            "usdc_balance": pt.usdc_balance,
            "portfolio_value": pt.get_portfolio_value(),
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "positions": pt.get_positions_list(),
        }

    def get_recent_trades(self, limit: int = 50) -> list:
        """Get recent trades."""
        if self.bot:
            return self.bot.get_recent_trades(limit)
        return []

    def get_session_summary(self) -> Optional[dict]:
        """Get last session summary."""
        return self.session_summary


# Global bot manager instance
_bot_manager: Optional[BotManager] = None


def get_bot_manager() -> BotManager:
    """Get the global bot manager instance."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = BotManager()
    return _bot_manager
