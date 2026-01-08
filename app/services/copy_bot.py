"""
Copy bot service - main trading logic with event-driven architecture.

Uses EventBus for decoupled communication with UI components.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from ..config import BotConfig
from ..core.events import EventBus, EventType
from ..core.interfaces import (
    TradingClient,
    TradeMonitor,
    TradeExecutor,
    TradeInfo,
)

logger = logging.getLogger(__name__)


class SkipReason(str, Enum):
    """Reasons for skipping a trade."""
    PRICE_HIGH = "price_high"
    PRICE_LOW = "price_low"
    NOT_BUY = "not_buy"
    SLIPPAGE = "slippage"
    EXECUTION_FAILED = "execution_failed"
    INSUFFICIENT_BALANCE = "insufficient_balance"


@dataclass
class BotStats:
    """Bot statistics."""
    trades_detected: int = 0
    trades_copied: int = 0
    trades_skipped: int = 0
    poll_count: int = 0
    skip_reasons: Dict[str, int] = field(default_factory=dict)

    def record_skip(self, reason: SkipReason) -> None:
        """Record a skip with reason."""
        self.trades_skipped += 1
        self.skip_reasons[reason.value] = self.skip_reasons.get(reason.value, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trades_detected": self.trades_detected,
            "trades_copied": self.trades_copied,
            "trades_skipped": self.trades_skipped,
            "poll_count": self.poll_count,
        }


class CopyBot:
    """
    Main copy trading bot with event-driven architecture.

    Uses dependency injection for trading client, monitor, and executor.
    Emits events through EventBus for UI updates.
    """

    def __init__(
        self,
        config: BotConfig,
        event_bus: EventBus,
        trading_client: TradingClient,
        trade_monitor: TradeMonitor,
        trade_executor: Optional[TradeExecutor] = None,
    ):
        self._config = config
        self._event_bus = event_bus
        self._client = trading_client
        self._monitor = trade_monitor
        self._executor = trade_executor

        # State
        self._start_time: Optional[datetime] = None
        self._stop_requested = False
        self._stats = BotStats()

        # Recent trades for history
        self._recent_trades: List[Dict[str, Any]] = []
        self._max_recent_trades = 100

    @property
    def is_running(self) -> bool:
        """Check if bot is running."""
        return self._start_time is not None and not self._stop_requested

    @property
    def stats(self) -> BotStats:
        """Get current statistics."""
        return self._stats

    @property
    def executor(self) -> Optional[TradeExecutor]:
        """Get the trade executor."""
        return self._executor

    def request_stop(self) -> None:
        """Request graceful stop."""
        self._stop_requested = True

    async def _emit(self, event_type: EventType, **data) -> None:
        """Emit an event through the event bus."""
        await self._event_bus.emit(event_type, **data)

    async def _log(self, level: str, message: str) -> None:
        """Emit a log event."""
        await self._emit(EventType.LOG, level=level, message=message)

    def _add_recent_trade(self, trade_type: str, data: Dict[str, Any]) -> None:
        """Add trade to recent history."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "type": trade_type,
            **data,
        }
        self._recent_trades.insert(0, record)
        if len(self._recent_trades) > self._max_recent_trades:
            self._recent_trades.pop()

    async def connect(self) -> bool:
        """Initialize connections."""
        return self._client.connect()

    async def _evaluate_trade(self, trade: TradeInfo) -> Optional[Dict[str, Any]]:
        """
        Evaluate whether to copy a trade based on filters.

        Returns decision dict if should execute, None if should skip.
        """
        # Price filter - max
        if trade.price > self._config.max_price:
            return {
                "skip": True,
                "reason": SkipReason.PRICE_HIGH,
                "message": f"Price {trade.price:.0%} > max {self._config.max_price:.0%}",
            }

        # Price filter - min
        if trade.price < self._config.min_price:
            return {
                "skip": True,
                "reason": SkipReason.PRICE_LOW,
                "message": f"Price {trade.price:.0%} < min {self._config.min_price:.0%}",
            }

        # Only copy BUY trades
        if trade.side != "BUY":
            return {
                "skip": True,
                "reason": SkipReason.NOT_BUY,
                "message": "Not a BUY trade",
            }

        # Calculate our trade size
        our_size = min(trade.size, self._config.max_trade_amount)
        our_size = max(our_size, self._config.min_trade_amount)

        # Check slippage
        book = self._client.get_order_book(trade.token_id)
        current_price = trade.price

        if book and book.best_ask is not None:
            current_price = book.best_ask

        slippage = abs(current_price - trade.price) / trade.price if trade.price > 0 else 0

        if slippage > self._config.max_slippage:
            return {
                "skip": True,
                "reason": SkipReason.SLIPPAGE,
                "message": f"Slippage {slippage:.1%} > max {self._config.max_slippage:.0%}",
                "slippage": slippage,
            }

        return {
            "skip": False,
            "size": our_size,
            "price": current_price,
            "slippage": slippage,
        }

    async def process_trade(self, raw_trade: Dict[str, Any]) -> None:
        """Process a detected trade."""
        # Only process TRADE activities
        if raw_trade.get("type", "").upper() != "TRADE":
            return

        trade = TradeInfo.from_activity(raw_trade)
        self._stats.trades_detected += 1

        await self._log("INFO", f"Trade detected: {trade.side} {trade.outcome} @ {trade.price:.0%} | ${trade.size:.2f}")
        await self._emit(
            EventType.TRADE_DETECTED,
            market=trade.market_name,
            side=trade.side,
            outcome=trade.outcome,
            price=trade.price,
            size=trade.size,
        )

        # Evaluate the trade
        decision = await self._evaluate_trade(trade)

        if decision is None or decision.get("skip"):
            reason = decision.get("reason", SkipReason.EXECUTION_FAILED) if decision else SkipReason.EXECUTION_FAILED
            message = decision.get("message", "Unknown reason") if decision else "No decision"

            await self._log("INFO", f"SKIP: {message}")
            await self._emit(
                EventType.TRADE_SKIPPED,
                market=trade.market_name,
                side=trade.side,
                price=trade.price,
                size=trade.size,
                reason=message,
            )

            self._stats.record_skip(reason)
            self._add_recent_trade("skipped", {
                "market": trade.market_name,
                "side": trade.side,
                "price": trade.price,
                "size": trade.size,
                "reason": message,
            })

            if self._executor:
                from .paper_trader import PaperTrader
                if isinstance(self._executor, PaperTrader):
                    self._executor.record_skipped()
            return

        # Execute the trade
        if self._executor and self._config.dry_run:
            our_size = decision.get("size", trade.size)
            current_price = decision.get("price", trade.price)
            slippage = decision.get("slippage", 0)

            # Create modified trade with our size/price
            exec_trade = TradeInfo(
                token_id=trade.token_id,
                market_name=trade.market_name,
                side=trade.side,
                outcome=trade.outcome,
                price=current_price,
                size=our_size,
                tx_hash=trade.tx_hash,
                timestamp=trade.timestamp,
            )

            result = await self._executor.execute(exec_trade, decision)

            if result.success:
                await self._log("INFO", f"[PAPER] Executed: {trade.side} ${our_size:.2f} @ {current_price:.0%}")

                from .paper_trader import PaperTrader
                if isinstance(self._executor, PaperTrader):
                    await self._log("INFO", f"[PAPER] Balance: ${self._executor.balance:.2f}")

                await self._emit(
                    EventType.TRADE_COPIED,
                    market=trade.market_name,
                    side=trade.side,
                    outcome=trade.outcome,
                    price=current_price,
                    size=our_size,
                    slippage=slippage,
                )

                self._stats.trades_copied += 1
                self._add_recent_trade("copied", {
                    "market": trade.market_name,
                    "side": trade.side,
                    "outcome": trade.outcome,
                    "price": current_price,
                    "size": our_size,
                    "slippage": slippage,
                })
            else:
                await self._emit(
                    EventType.TRADE_FAILED,
                    market=trade.market_name,
                    side=trade.side,
                    price=trade.price,
                    size=trade.size,
                    reason=result.message,
                )

                self._stats.record_skip(SkipReason.EXECUTION_FAILED)
                self._add_recent_trade("skipped", {
                    "market": trade.market_name,
                    "side": trade.side,
                    "price": trade.price,
                    "size": trade.size,
                    "reason": result.message,
                })

        # Emit status update
        await self._emit(EventType.STATUS_UPDATE, **self.get_status())

    async def run(self) -> Dict[str, Any]:
        """Main bot loop. Returns session summary on completion."""
        self._start_time = datetime.now()
        self._stop_requested = False
        self._stats = BotStats()

        await self._emit(EventType.BOT_STARTING)
        await self._log("INFO", "Connecting to Polymarket...")

        if not await self.connect():
            await self._log("ERROR", "Failed to connect to Polymarket")
            await self._emit(EventType.BOT_ERROR, error="Connection failed")
            return self.get_session_summary()

        # Get initial balance
        balance = self._client.get_balance()
        if balance is not None:
            await self._log("INFO", f"USDC Balance: ${balance:.2f}")
            await self._emit(EventType.BALANCE_UPDATE, balance=balance)

        await self._log("INFO", "Starting trade monitor...")
        await self._emit(EventType.BOT_STARTED, start_time=self._start_time.isoformat())
        await self._emit(EventType.STATUS_UPDATE, **self.get_status())

        # Initial fetch to establish baseline
        initial_trades = await self._monitor.fetch_trades()
        self._monitor.filter_new_trades(initial_trades)
        await self._log("INFO", "Baseline established. Watching for new trades...")

        status_interval = int(30 / self._config.poll_interval)

        while not self._stop_requested:
            try:
                trades = await self._monitor.fetch_trades()
                new_trades = self._monitor.filter_new_trades(trades)

                self._stats.poll_count += 1

                # Process new trades (oldest first)
                for trade in reversed(new_trades):
                    if self._stop_requested:
                        break
                    await self.process_trade(trade)

                # Periodic status
                if self._stats.poll_count % status_interval == 0:
                    await self._log(
                        "INFO",
                        f"[SCAN] {self._stats.poll_count} polls | "
                        f"Detected: {self._stats.trades_detected} | "
                        f"Copied: {self._stats.trades_copied} | "
                        f"Skipped: {self._stats.trades_skipped}"
                    )
                    await self._emit(EventType.STATUS_UPDATE, **self.get_status())

                await asyncio.sleep(self._config.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await self._log("ERROR", f"Error in main loop: {e}")
                await asyncio.sleep(1)

        await self._log("INFO", "Bot stopped.")
        await self._emit(EventType.BOT_STOPPED)
        return self.get_session_summary()

    def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        runtime = 0
        if self._start_time:
            runtime = (datetime.now() - self._start_time).total_seconds()

        result = {
            "running": self.is_running,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "runtime_seconds": runtime,
            "stats": self._stats.to_dict(),
            "skip_reasons": self._stats.skip_reasons,
        }

        # Add executor stats if available
        if self._executor:
            result["paper"] = self._executor.get_stats()

        return result

    def get_session_summary(self) -> Dict[str, Any]:
        """Generate session summary."""
        runtime = 0
        if self._start_time:
            runtime = (datetime.now() - self._start_time).total_seconds()

        summary = {
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "end_time": datetime.now().isoformat(),
            "runtime_seconds": runtime,
            "runtime_formatted": f"{runtime / 3600:.2f} hours",
            "mode": "dry_run" if self._config.dry_run else "live",
            "target_wallet": self._config.target_wallet,
            "stats": self._stats.to_dict(),
            "skip_reasons": self._stats.skip_reasons,
        }

        if self._executor:
            summary["paper"] = self._executor.get_stats()

        return summary

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent trades."""
        return self._recent_trades[:limit]
