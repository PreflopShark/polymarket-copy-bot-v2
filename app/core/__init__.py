"""Core module - interfaces, events, and base classes."""

from .events import EventBus, Event, EventType, get_event_bus
from .interfaces import (
    TradingClient,
    TradeMonitor,
    TradeExecutor,
    TradeInfo,
    OrderBookInfo,
    ExecutionResult,
)
from .exceptions import BotError, ConfigError, ConnectionError, ExecutionError

__all__ = [
    # Events
    "EventBus",
    "Event",
    "EventType",
    "get_event_bus",
    # Interfaces
    "TradingClient",
    "TradeMonitor",
    "TradeExecutor",
    # Data classes
    "TradeInfo",
    "OrderBookInfo",
    "ExecutionResult",
    # Exceptions
    "BotError",
    "ConfigError",
    "ConnectionError",
    "ExecutionError",
]
