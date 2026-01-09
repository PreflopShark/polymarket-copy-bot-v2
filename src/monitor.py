"""Trade monitoring service - watches target trader for new activity."""

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable, List, Optional, Union

import aiohttp

from .config import Config

logger = logging.getLogger(__name__)


class TradeMonitor:
    """Monitors a target trader's activity on Polymarket."""

    def __init__(self, config: Config):
        self.config = config
        self.last_trade_id: Optional[str] = None
        self.last_trade_timestamp: Optional[datetime] = None
        self._running = False

    async def fetch_trades(self, session: aiohttp.ClientSession) -> List[dict]:
        """
        Fetch recent trades for the target trader.

        Args:
            session: aiohttp session for making requests.

        Returns:
            List of trade dictionaries from the API.
        """
        url = f"{self.config.data_api_host}/activity"
        params = {
            "user": self.config.target_trader_address,
            # High-frequency traders can place multiple trades between polls or while the
            # API is lagging. Use a slightly larger window to reduce "missed" trades.
            "limit": 25,
        }

        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                else:
                    logger.warning(f"API returned status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []

    def _get_trade_id(self, trade: dict) -> str:
        """Get unique identifier for a trade."""
        # Use transactionHash as unique ID, fallback to timestamp + asset
        return trade.get("transactionHash") or f"{trade.get('timestamp')}_{trade.get('asset')}"

    def filter_new_trades(self, trades: List[dict]) -> List[dict]:
        """
        Filter out trades we've already seen.

        Args:
            trades: List of trades from the API.

        Returns:
            List of new trades only.
        """
        if not trades:
            return []

        # Normalize ordering: API ordering is not guaranteed. Sort newest -> oldest.
        # Timestamp from the API is usually an int/float (seconds).
        def _ts(t: dict) -> float:
            try:
                return float(t.get("timestamp") or 0)
            except Exception:
                return 0.0

        trades = sorted(trades, key=_ts, reverse=True)

        # If this is our first fetch, just record the latest and don't return any
        # (avoid copying historical trades on startup)
        if self.last_trade_id is None:
            if trades:
                self.last_trade_id = self._get_trade_id(trades[0])
                self.last_trade_timestamp = trades[0].get("timestamp")
                logger.info(f"Initialized with latest trade: {trades[0].get('title', 'unknown')[:40]}")
                logger.info(f"Trade ID: {self.last_trade_id[:20]}...")
            return []

        # Find trades newer than what we've seen
        new_trades = []
        for trade in trades:
            trade_id = self._get_trade_id(trade)
            if trade_id == self.last_trade_id:
                break
            new_trades.append(trade)

        # If our marker fell out of the fetched window, we can't reliably diff.
        # In that case, treat the entire window as "new" and rely on downstream
        # de-duplication via transactionHash.
        if not new_trades and trades and self.last_trade_id is not None:
            oldest_id = self._get_trade_id(trades[-1])
            newest_id = self._get_trade_id(trades[0])
            if self.last_trade_id != newest_id and self.last_trade_id != oldest_id:
                logger.warning(
                    "Last seen trade is not in the fetched window; increasing window or poll rate may help"
                )

        # Update our marker to the newest trade
        if new_trades:
            self.last_trade_id = self._get_trade_id(new_trades[0])
            self.last_trade_timestamp = new_trades[0].get("timestamp")

        return new_trades

    async def start_monitoring(self, on_trade: Callable[[dict], Awaitable[None]]):
        """
        Start monitoring loop - polls for new trades.

        Args:
            on_trade: Callback function called for each new trade detected.
        """
        self._running = True
        consecutive_errors = 0
        max_backoff = 30  # Maximum backoff seconds
        poll_count = 0
        status_interval = 150  # Log status every ~30 seconds at 0.2s polls
        logger.info(f"Starting trade monitor for {self.config.target_trader_address}")
        logger.info(f"Poll interval: {self.config.poll_interval_seconds}s")

        async with aiohttp.ClientSession() as session:
            # Initial fetch to establish baseline
            initial_trades = await self.fetch_trades(session)
            self.filter_new_trades(initial_trades)
            logger.info("Baseline established. Watching for new trades...")

            while self._running:
                try:
                    trades = await self.fetch_trades(session)
                    new_trades = self.filter_new_trades(trades)

                    # Reset error counter on success
                    consecutive_errors = 0
                    poll_count += 1

                    # Periodic status log
                    if poll_count % status_interval == 0:
                        logger.info(f"[SCAN] Active - {poll_count} polls, watching for trades...")

                    # Process new trades (oldest first)
                    for trade in reversed(new_trades):
                        logger.info(f"New trade detected: {trade}")
                        try:
                            await on_trade(trade)
                        except Exception as e:
                            logger.error(f"Error processing trade: {e}", exc_info=True)

                    await asyncio.sleep(self.config.poll_interval_seconds)

                except asyncio.CancelledError:
                    logger.info("Monitor cancelled")
                    break
                except aiohttp.ClientError as e:
                    consecutive_errors += 1
                    backoff = min(self.config.poll_interval_seconds * (2 ** consecutive_errors), max_backoff)
                    logger.warning(f"Network error in monitor (attempt {consecutive_errors}), backing off {backoff:.1f}s: {e}")
                    await asyncio.sleep(backoff)
                except Exception as e:
                    consecutive_errors += 1
                    backoff = min(self.config.poll_interval_seconds * consecutive_errors, max_backoff)
                    logger.error(f"Monitor error (attempt {consecutive_errors}): {e}", exc_info=True)
                    await asyncio.sleep(backoff)

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        logger.info("Monitor stop requested")
