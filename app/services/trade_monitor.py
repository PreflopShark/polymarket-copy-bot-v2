"""Trade monitoring service - watches target trader for new trades."""

import logging
from typing import Optional, List

import aiohttp

from ..config import BotConfig

logger = logging.getLogger(__name__)


class TradeMonitor:
    """Monitors target trader for new trades."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.last_trade_id: Optional[str] = None
        self.data_api = config.data_api_host

    async def fetch_trades(self, session: aiohttp.ClientSession) -> List[dict]:
        """Fetch recent trades from target."""
        url = f"{self.data_api}/activity"
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
                    logger.warning(f"API returned status {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []

    def filter_new_trades(self, trades: List[dict]) -> List[dict]:
        """Filter out trades we've already seen."""
        if not trades:
            return []

        # Sort by timestamp (newest first)
        trades = sorted(trades, key=lambda t: float(t.get("timestamp", 0)), reverse=True)

        # First fetch - just record latest
        if self.last_trade_id is None:
            if trades:
                self.last_trade_id = trades[0].get("transactionHash")
                logger.info(f"Baseline trade: {trades[0].get('title', 'unknown')[:40]}")
            return []

        # Find new trades
        new_trades = []
        for trade in trades:
            trade_id = trade.get("transactionHash")
            if trade_id == self.last_trade_id:
                break
            new_trades.append(trade)

        # Update marker
        if new_trades:
            self.last_trade_id = new_trades[0].get("transactionHash")

        return new_trades

    def reset(self):
        """Reset the monitor state."""
        self.last_trade_id = None
