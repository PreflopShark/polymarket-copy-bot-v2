"""Copy bot service - main trading logic with event hooks."""

import asyncio
import logging
import time
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime

import aiohttp

from ..config import BotConfig
from .polymarket_client import PolymarketClient
from .trade_monitor import TradeMonitor
from .paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class CopyBot:
    """Main copy trading bot with event hooks for web UI."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.pm_client = PolymarketClient(config)
        self.monitor = TradeMonitor(config)
        self.paper_trader = PaperTrader(config.initial_balance) if config.dry_run else None

        # State
        self.start_time: Optional[datetime] = None
        self.trades_detected = 0
        self.trades_copied = 0
        self.trades_skipped = 0
        self.poll_count = 0
        self._stop_requested = False

        # Skip reason tracking
        self.skip_reasons: Dict[str, int] = {}

        # Recent trades for UI
        self.recent_trades: List[dict] = []
        self.max_recent_trades = 100

        # Event callbacks
        self._on_log: Optional[Callable] = None
        self._on_trade: Optional[Callable] = None
        self._on_status: Optional[Callable] = None

    def set_callbacks(self,
                      on_log: Optional[Callable] = None,
                      on_trade: Optional[Callable] = None,
                      on_status: Optional[Callable] = None):
        """Set event callbacks for real-time updates."""
        self._on_log = on_log
        self._on_trade = on_trade
        self._on_status = on_status

    async def _emit_log(self, level: str, message: str):
        """Emit log event."""
        if self._on_log:
            await self._on_log({
                "type": "log",
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            })

    async def _emit_trade(self, trade_type: str, data: dict):
        """Emit trade event."""
        # Add to recent trades
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "type": trade_type,
            **data
        }
        self.recent_trades.insert(0, trade_record)
        if len(self.recent_trades) > self.max_recent_trades:
            self.recent_trades.pop()

        if self._on_trade:
            await self._on_trade(trade_record)

    async def _emit_status(self):
        """Emit status update."""
        if self._on_status:
            await self._on_status(self.get_status())

    def request_stop(self):
        """Request graceful stop."""
        self._stop_requested = True

    def get_status(self) -> dict:
        """Get current bot status."""
        runtime = 0
        if self.start_time:
            runtime = (datetime.now() - self.start_time).total_seconds()

        result = {
            "running": not self._stop_requested and self.start_time is not None,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "runtime_seconds": runtime,
            "stats": {
                "trades_detected": self.trades_detected,
                "trades_copied": self.trades_copied,
                "trades_skipped": self.trades_skipped,
                "poll_count": self.poll_count,
            },
            "skip_reasons": self.skip_reasons,
        }

        # Add paper trading stats
        if self.paper_trader:
            result["paper"] = self.paper_trader.get_summary()

        return result

    async def connect(self) -> bool:
        """Initialize connections."""
        return self.pm_client.connect()

    async def process_trade(self, trade: dict):
        """Process a detected trade."""
        # Only process TRADE activities
        if trade.get("type", "").upper() != "TRADE":
            return

        market_name = trade.get("title", "Unknown")[:50]
        side = trade.get("side", "").upper()
        price = float(trade.get("price", 0))
        size = float(trade.get("usdcSize", 0))
        outcome = trade.get("outcome", "")
        token_id = trade.get("asset", "")

        self.trades_detected += 1

        await self._emit_log("INFO", f"Trade detected: {side} {outcome} @ {price:.0%} | ${size:.2f}")
        await self._emit_trade("detected", {
            "market": market_name,
            "side": side,
            "outcome": outcome,
            "price": price,
            "size": size,
        })

        # Price filter - max
        if price > self.config.max_price:
            reason = f"Price {price:.0%} > max {self.config.max_price:.0%}"
            await self._emit_log("INFO", f"SKIP: {reason}")
            await self._emit_trade("skipped", {
                "market": market_name,
                "side": side,
                "price": price,
                "size": size,
                "reason": reason,
            })
            self.trades_skipped += 1
            self.skip_reasons["price_high"] = self.skip_reasons.get("price_high", 0) + 1
            if self.paper_trader:
                self.paper_trader.record_skipped()
            return

        # Price filter - min
        if price < self.config.min_price:
            reason = f"Price {price:.0%} < min {self.config.min_price:.0%}"
            await self._emit_log("INFO", f"SKIP: {reason}")
            await self._emit_trade("skipped", {
                "market": market_name,
                "side": side,
                "price": price,
                "size": size,
                "reason": reason,
            })
            self.trades_skipped += 1
            self.skip_reasons["price_low"] = self.skip_reasons.get("price_low", 0) + 1
            if self.paper_trader:
                self.paper_trader.record_skipped()
            return

        # Only copy BUY trades
        if side != "BUY":
            reason = "Not a BUY trade"
            await self._emit_log("INFO", f"SKIP: {reason}")
            await self._emit_trade("skipped", {
                "market": market_name,
                "side": side,
                "price": price,
                "size": size,
                "reason": reason,
            })
            self.trades_skipped += 1
            self.skip_reasons["not_buy"] = self.skip_reasons.get("not_buy", 0) + 1
            if self.paper_trader:
                self.paper_trader.record_skipped()
            return

        # Calculate our trade size
        our_size = min(size, self.config.max_trade_amount)
        our_size = max(our_size, self.config.min_trade_amount)

        # Execute trade (dry run mode)
        if self.config.dry_run and self.paper_trader:
            # Check slippage
            book = self.pm_client.get_order_book(token_id)
            current_price = price

            if book and book.asks:
                sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
                current_price = float(sorted_asks[0].price)

            slippage = abs(current_price - price) / price if price > 0 else 0

            if slippage > self.config.max_slippage:
                reason = f"Slippage {slippage:.1%} > max {self.config.max_slippage:.0%}"
                await self._emit_log("WARN", f"SKIP: {reason}")
                await self._emit_trade("skipped", {
                    "market": market_name,
                    "side": side,
                    "price": price,
                    "size": size,
                    "slippage": slippage,
                    "reason": reason,
                })
                self.trades_skipped += 1
                self.skip_reasons["slippage"] = self.skip_reasons.get("slippage", 0) + 1
                self.paper_trader.record_skipped()
                return

            # Execute paper trade
            success = self.paper_trader.execute_trade(
                token_id=token_id,
                market_name=market_name,
                side=side,
                size=our_size,
                price=current_price,
            )

            if success:
                await self._emit_log("INFO", f"[PAPER] Executed: {side} ${our_size:.2f} @ {current_price:.0%}")
                await self._emit_log("INFO", f"[PAPER] Balance: ${self.paper_trader.usdc_balance:.2f}")
                await self._emit_trade("copied", {
                    "market": market_name,
                    "side": side,
                    "outcome": outcome,
                    "price": current_price,
                    "size": our_size,
                    "slippage": slippage,
                })
                self.trades_copied += 1
            else:
                await self._emit_trade("skipped", {
                    "market": market_name,
                    "side": side,
                    "price": price,
                    "size": size,
                    "reason": "Execution failed",
                })
                self.trades_skipped += 1
                self.skip_reasons["execution_failed"] = self.skip_reasons.get("execution_failed", 0) + 1

        await self._emit_status()

    async def run(self) -> dict:
        """Main bot loop. Returns session summary on completion."""
        self.start_time = datetime.now()
        self._stop_requested = False

        await self._emit_log("INFO", "Connecting to Polymarket...")

        if not await self.connect():
            await self._emit_log("ERROR", "Failed to connect to Polymarket")
            return self.get_session_summary()

        # Get initial balance
        balance = self.pm_client.get_balance()
        if balance is not None:
            await self._emit_log("INFO", f"USDC Balance: ${balance:.2f}")

        await self._emit_log("INFO", "Starting trade monitor...")
        await self._emit_status()

        async with aiohttp.ClientSession() as session:
            # Initial fetch to establish baseline
            initial_trades = await self.monitor.fetch_trades(session)
            self.monitor.filter_new_trades(initial_trades)
            await self._emit_log("INFO", "Baseline established. Watching for new trades...")

            status_interval = int(30 / self.config.poll_interval)

            while not self._stop_requested:
                try:
                    trades = await self.monitor.fetch_trades(session)
                    new_trades = self.monitor.filter_new_trades(trades)

                    self.poll_count += 1

                    # Process new trades (oldest first)
                    for trade in reversed(new_trades):
                        if self._stop_requested:
                            break
                        await self.process_trade(trade)

                    # Periodic status
                    if self.poll_count % status_interval == 0:
                        await self._emit_log("INFO",
                            f"[SCAN] {self.poll_count} polls | "
                            f"Detected: {self.trades_detected} | "
                            f"Copied: {self.trades_copied} | "
                            f"Skipped: {self.trades_skipped}"
                        )
                        await self._emit_status()

                    await asyncio.sleep(self.config.poll_interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    await self._emit_log("ERROR", f"Error in main loop: {e}")
                    await asyncio.sleep(1)

        await self._emit_log("INFO", "Bot stopped.")
        return self.get_session_summary()

    def get_session_summary(self) -> dict:
        """Generate session summary."""
        runtime = 0
        if self.start_time:
            runtime = (datetime.now() - self.start_time).total_seconds()

        summary = {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": datetime.now().isoformat(),
            "runtime_seconds": runtime,
            "runtime_formatted": f"{runtime / 3600:.2f} hours",
            "mode": "dry_run" if self.config.dry_run else "live",
            "target_wallet": self.config.target_wallet,
            "stats": {
                "trades_detected": self.trades_detected,
                "trades_copied": self.trades_copied,
                "trades_skipped": self.trades_skipped,
                "poll_count": self.poll_count,
            },
            "skip_reasons": self.skip_reasons,
        }

        if self.paper_trader:
            summary["paper"] = self.paper_trader.get_summary()

        return summary

    def get_recent_trades(self, limit: int = 50) -> List[dict]:
        """Get recent trades."""
        return self.recent_trades[:limit]
