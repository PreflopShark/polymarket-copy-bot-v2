"""
Trade monitoring service.

Watches target trader for new trades via Polymarket Data API.
"""

import logging
from typing import Optional, List, Dict, Any, Set

import aiohttp

from ..config import BotConfig
from ..core.interfaces import TradeMonitor as ITradeMonitor

logger = logging.getLogger(__name__)


class TargetTradeMonitor(ITradeMonitor):
    """
    Monitors a target trader for new trades.

    Uses the Polymarket Data API to poll for activity and
    filters out already-seen trades.
    """

    def __init__(self, config: BotConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._owns_session = session is None
        self._last_trade_id: Optional[str] = None
        self._seen_trades: Set[str] = set()
        self._max_seen = 1000

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the HTTP session if we own it."""
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    async def fetch_trades(self) -> List[Dict[str, Any]]:
        """Fetch recent trades from target wallet."""
        session = await self._get_session()
        url = f"{self.config.data_api_host}/activity"
        params = {
            "user": self.config.target_wallet,
            "limit": 25,
        }

        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                else:
                    logger.warning(f"Data API returned status {response.status}")
                    return []
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching trades: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []

    def filter_new_trades(self, trades: List[Dict]) -> List[Dict]:
        """
        Filter out trades we've already seen.

        Uses transaction hash as unique identifier.
        On first call, establishes baseline and returns empty list.
        """
        if not trades:
            return []

        # Sort by timestamp (newest first)
        trades = sorted(
            trades,
            key=lambda t: float(t.get("timestamp", 0)),
            reverse=True
        )

        # First fetch - establish baseline
        if self._last_trade_id is None:
            if trades:
                self._last_trade_id = trades[0].get("transactionHash")
                self._seen_trades.add(self._last_trade_id)
                market = trades[0].get("title", "unknown")[:40]
                logger.info(f"Baseline established: {market}")
            return []

        # Find new trades (those we haven't seen)
        new_trades = []
        for trade in trades:
            tx_hash = trade.get("transactionHash")
            if not tx_hash:
                continue

            # Stop at last seen trade
            if tx_hash == self._last_trade_id:
                break

            # Skip if already seen (handles out-of-order arrivals)
            if tx_hash in self._seen_trades:
                continue

            new_trades.append(trade)
            self._seen_trades.add(tx_hash)

        # Update last trade marker
        if new_trades:
            self._last_trade_id = new_trades[0].get("transactionHash")

        # Cleanup seen trades to prevent memory growth
        if len(self._seen_trades) > self._max_seen:
            # Keep only recent half
            self._seen_trades = set(list(self._seen_trades)[-self._max_seen // 2:])

        return new_trades

    def reset(self) -> None:
        """Reset monitor state for new session."""
        self._last_trade_id = None
        self._seen_trades.clear()
        logger.info("Trade monitor reset")

    @property
    def is_initialized(self) -> bool:
        """Check if monitor has established baseline."""
        return self._last_trade_id is not None
