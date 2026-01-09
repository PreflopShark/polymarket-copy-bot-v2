"""
Bot lifecycle manager - handles start/stop and event broadcasting.

Provides WebSocket broadcasting and bot lifecycle management.
"""

import asyncio
import logging
from enum import Enum
from typing import Optional, Set, Dict, Any
from datetime import datetime

from fastapi import WebSocket

from .config import BotConfig, get_config
from .core.events import EventBus, EventType, Event, get_event_bus
from .services.copy_bot import CopyBot
from .services.polymarket_client import PolymarketClient
from .services.trade_monitor import TargetTradeMonitor
from .services.paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class BotState(str, Enum):
    """Bot lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class WebSocketManager:
    """Manages WebSocket connections for real-time broadcasting."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self._connections:
            logger.debug(f"No WS connections to broadcast to (msg type: {message.get('type')})")
            return

        logger.debug(f"Broadcasting to {len(self._connections)} clients: {message.get('type')}")
        disconnected = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"WS send error: {e}")
                disconnected.add(ws)

        for ws in disconnected:
            self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        """Get number of active connections."""
        return len(self._connections)


class BotManager:
    """
    Manages bot lifecycle and provides real-time event broadcasting.

    Bridges the EventBus to WebSocket clients and handles bot start/stop.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._state = BotState.STOPPED
        self._event_bus = event_bus or get_event_bus()
        self._ws_manager = WebSocketManager()

        self._bot: Optional[CopyBot] = None
        self._task: Optional[asyncio.Task] = None
        self._session_summary: Optional[Dict[str, Any]] = None

        # Log buffer for new connections
        self._log_buffer: list = []
        self._max_log_buffer = 200

        # Subscribe to all events for WebSocket broadcasting
        self._event_bus.subscribe_all(self._handle_event)
        logger.info(f"BotManager initialized with EventBus id={id(self._event_bus)}")

    @property
    def state(self) -> BotState:
        """Get current bot state."""
        return self._state

    @property
    def connection_manager(self) -> WebSocketManager:
        """Get WebSocket manager for connection handling."""
        return self._ws_manager

    @property
    def session_summary(self) -> Optional[Dict[str, Any]]:
        """Get last session summary."""
        return self._session_summary

    async def _handle_event(self, event: Event) -> None:
        """Handle events from the EventBus and broadcast to WebSocket clients."""
        # Log trade events at INFO level for visibility
        if event.type in (EventType.TRADE_DETECTED, EventType.TRADE_COPIED, EventType.TRADE_SKIPPED):
            logger.info(f"Event: {event.type.value} -> {self._ws_manager.connection_count} clients")

        # Convert event to WebSocket message format
        message = self._event_to_message(event)

        # Buffer log messages
        if event.type == EventType.LOG:
            self._log_buffer.append(message)
            if len(self._log_buffer) > self._max_log_buffer:
                self._log_buffer.pop(0)

        # Update state based on lifecycle events
        if event.type == EventType.BOT_STARTING:
            self._state = BotState.STARTING
        elif event.type == EventType.BOT_STARTED:
            self._state = BotState.RUNNING
        elif event.type == EventType.BOT_STOPPING:
            self._state = BotState.STOPPING
        elif event.type == EventType.BOT_STOPPED:
            self._state = BotState.STOPPED

        # Broadcast to WebSocket clients
        await self._ws_manager.broadcast(message)

    def _event_to_message(self, event: Event) -> Dict[str, Any]:
        """Convert an Event to WebSocket message format."""
        # Map event types to message types for backwards compatibility
        type_map = {
            EventType.LOG: "log",
            EventType.BOT_STARTING: "state",
            EventType.BOT_STARTED: "state",
            EventType.BOT_STOPPING: "state",
            EventType.BOT_STOPPED: "state",
            EventType.STATUS_UPDATE: "status",
            EventType.TRADE_DETECTED: "trade",
            EventType.TRADE_COPIED: "trade",
            EventType.TRADE_SKIPPED: "trade",
            EventType.TRADE_FAILED: "trade",
            EventType.BALANCE_UPDATE: "balance",
        }

        msg_type = type_map.get(event.type, event.type.value)

        message = {
            "type": msg_type,
            "timestamp": event.timestamp.isoformat(),
            **event.data,
        }

        # Add state for lifecycle events
        if event.type in (EventType.BOT_STARTING, EventType.BOT_STARTED,
                          EventType.BOT_STOPPING, EventType.BOT_STOPPED):
            message["state"] = self._state.value

        return message

    def _create_bot(self, config: BotConfig) -> CopyBot:
        """Create a new CopyBot instance with dependencies."""
        # Create trading client
        trading_client = PolymarketClient(config)

        # Create trade monitor
        trade_monitor = TargetTradeMonitor(config)

        # Create executor (paper trader for dry run mode)
        executor = None
        if config.dry_run:
            executor = PaperTrader(
                initial_balance=config.initial_balance,
                simulate_real_market=config.simulate_real_market,
            )

        logger.info(f"Creating CopyBot with EventBus id={id(self._event_bus)}")
        return CopyBot(
            config=config,
            event_bus=self._event_bus,
            trading_client=trading_client,
            trade_monitor=trade_monitor,
            trade_executor=executor,
        )

    async def start(self) -> Dict[str, Any]:
        """Start the bot."""
        if self._state != BotState.STOPPED:
            return {"success": False, "error": f"Bot is {self._state.value}"}

        self._state = BotState.STARTING
        await self._ws_manager.broadcast({
            "type": "state",
            "state": self._state.value,
        })

        try:
            config = get_config()

            if not config.target_wallet:
                self._state = BotState.STOPPED
                return {"success": False, "error": "No target wallet configured"}

            # Clear previous session data
            self._log_buffer.clear()
            self._session_summary = None

            # Create and start bot
            self._bot = self._create_bot(config)
            self._task = asyncio.create_task(self._run_bot())

            return {"success": True, "message": "Bot starting"}

        except Exception as e:
            logger.exception("Failed to start bot")
            self._state = BotState.STOPPED
            await self._ws_manager.broadcast({
                "type": "state",
                "state": self._state.value,
                "error": str(e),
            })
            return {"success": False, "error": str(e)}

    async def _run_bot(self) -> None:
        """Run the bot and handle completion."""
        try:
            self._session_summary = await self._bot.run()
        except Exception as e:
            logger.exception("Bot crashed")
            self._session_summary = {
                "error": str(e),
                "end_time": datetime.now().isoformat(),
            }
        finally:
            self._state = BotState.STOPPED
            await self._ws_manager.broadcast({
                "type": "state",
                "state": self._state.value,
            })
            await self._ws_manager.broadcast({
                "type": "session_complete",
                "summary": self._session_summary,
            })

    async def stop(self) -> Dict[str, Any]:
        """Stop the bot gracefully."""
        if self._state != BotState.RUNNING:
            return {"success": False, "error": f"Bot is not running (state: {self._state.value})"}

        self._state = BotState.STOPPING
        await self._ws_manager.broadcast({
            "type": "state",
            "state": self._state.value,
        })

        # Signal bot to stop
        if self._bot:
            self._bot.request_stop()

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
            "summary": self._session_summary,
        }

    async def kill(self) -> Dict[str, Any]:
        """Force kill the bot immediately without graceful shutdown."""
        if self._state not in (BotState.RUNNING, BotState.STARTING, BotState.STOPPING):
            return {"success": False, "error": f"Bot is not running (state: {self._state.value})"}

        logger.warning("Force killing bot")

        # Cancel the task immediately
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._state = BotState.STOPPED
        self._bot = None
        self._task = None

        await self._ws_manager.broadcast({
            "type": "state",
            "state": self._state.value,
        })

        return {"success": True, "message": "Bot force killed"}

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        result = {
            "state": self._state.value,
            "stats": None,
            "paper": None,
        }

        if self._bot and self._state == BotState.RUNNING:
            status = self._bot.get_status()
            result["stats"] = status.get("stats")
            result["paper"] = status.get("paper")
            result["start_time"] = status.get("start_time")
            result["runtime_seconds"] = status.get("runtime_seconds")
            result["skip_reasons"] = status.get("skip_reasons")

        return result

    def get_portfolio(self) -> Dict[str, Any]:
        """Get current portfolio state."""
        if not self._bot or not self._bot.executor:
            config = get_config()
            return {
                "usdc_balance": config.initial_balance,
                "portfolio_value": config.initial_balance,
                "pnl": 0,
                "pnl_percentage": 0,
                "positions": [],
            }

        stats = self._bot.executor.get_stats()
        return {
            "usdc_balance": stats.get("usdc_balance", 0),
            "portfolio_value": stats.get("portfolio_value", 0),
            "pnl": stats.get("pnl", 0),
            "pnl_percentage": stats.get("pnl_percentage", 0),
            "positions": stats.get("positions", []),
        }

    def get_recent_trades(self, limit: int = 50) -> list:
        """Get recent trades."""
        if self._bot:
            return self._bot.get_recent_trades(limit)
        return []

    def get_session_summary(self) -> Optional[Dict[str, Any]]:
        """Get last session summary."""
        return self._session_summary

    def get_log_buffer(self) -> list:
        """Get buffered logs for new connections."""
        return self._log_buffer.copy()


# Global bot manager instance
_bot_manager: Optional[BotManager] = None


def get_bot_manager() -> BotManager:
    """Get the global bot manager instance."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = BotManager()
    return _bot_manager
