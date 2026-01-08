"""Event system for decoupled communication between components."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Event types for the bot."""
    # Lifecycle events
    BOT_STARTING = "bot.starting"
    BOT_STARTED = "bot.started"
    BOT_STOPPING = "bot.stopping"
    BOT_STOPPED = "bot.stopped"
    BOT_ERROR = "bot.error"

    # Trade events
    TRADE_DETECTED = "trade.detected"
    TRADE_EVALUATING = "trade.evaluating"
    TRADE_COPIED = "trade.copied"
    TRADE_SKIPPED = "trade.skipped"
    TRADE_FAILED = "trade.failed"

    # Status events
    STATUS_UPDATE = "status.update"
    BALANCE_UPDATE = "balance.update"
    POSITION_UPDATE = "position.update"

    # Log events
    LOG = "log"


@dataclass
class Event:
    """Event object passed through the event bus."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert event to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


class EventBus:
    """
    Async event bus for decoupled component communication.

    Allows components to publish events without knowing who subscribes,
    and subscribers to receive events without knowing who publishes.
    """

    def __init__(self):
        self._subscribers: Dict[EventType, Set[Callable]] = {}
        self._global_subscribers: Set[Callable] = set()
        self._event_history: List[Event] = []
        self._max_history = 500

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()
        self._subscribers[event_type].add(callback)

    def subscribe_all(self, callback: Callable) -> None:
        """Subscribe to all events."""
        self._global_subscribers.add(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """Unsubscribe from a specific event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].discard(callback)

    def unsubscribe_all(self, callback: Callable) -> None:
        """Unsubscribe from all events."""
        self._global_subscribers.discard(callback)
        for subscribers in self._subscribers.values():
            subscribers.discard(callback)

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Get all relevant callbacks
        callbacks = set(self._global_subscribers)
        if event.type in self._subscribers:
            callbacks.update(self._subscribers[event.type])

        # Call all callbacks
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")

    async def emit(self, event_type: EventType, **data) -> None:
        """Convenience method to emit an event."""
        event = Event(type=event_type, data=data)
        await self.publish(event)

    def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        """Get event history, optionally filtered by type."""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
