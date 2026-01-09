"""
Directional Copy Trading Strategy

Copies target trader's single-side trades immediately for temporal arbitrage.
The target (@0x8dxd) profits by betting on price lag between CEX and Polymarket.

This module:
1. Evaluates incoming trades against price filters
2. Returns trades for immediate execution (no pairing)
3. Tracks position for exit copying
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Price filters - avoid extreme prices to control risk
MAX_PRICE = 0.85  # Don't buy above 85% (limited upside)
MIN_PRICE = 0.15  # Don't buy below 15% (too speculative)


@dataclass
class Trade:
    """A trade to copy."""
    activity: dict
    token_id: str
    condition_id: str
    outcome_index: int
    outcome_name: str
    side: str
    price: float
    usdc_size: float
    shares: float
    timestamp: float = field(default_factory=time.time)


class DirectionalStrategy:
    """
    Directional copy trading - executes single-side trades immediately.
    
    Flow:
    1. Target buys any outcome → Check price filters → Execute if valid
    2. Target sells → Pass through for exit handling
    3. Track stats for monitoring
    """

    def __init__(self,
                 max_price: float = MAX_PRICE,
                 min_price: float = MIN_PRICE):
        self.max_price = max_price
        self.min_price = min_price

        # Stats
        self.trades_copied = 0
        self.trades_skipped = 0

        logger.info(f"Directional strategy: price range {min_price:.0%}-{max_price:.0%}")

    def evaluate(self, activity: dict) -> Optional[Trade]:
        """
        Evaluate a trade for execution.

        Returns Trade if it passes filters, None otherwise.
        """
        # Extract trade details
        condition_id = activity.get("conditionId", "")
        if not condition_id:
            logger.warning("Trade missing conditionId, skipping")
            return None

        outcome_index = activity.get("outcomeIndex", 0)
        outcome_name = activity.get("outcome", f"outcome_{outcome_index}")
        market_name = activity.get("title", "Unknown")
        token_id = activity.get("asset", "")
        price = float(activity.get("price", 0))
        usdc_size = float(activity.get("usdcSize", 0))
        shares = float(activity.get("size", 0))
        side = activity.get("side", "BUY")

        trade = Trade(
            activity=activity,
            token_id=token_id,
            condition_id=condition_id,
            outcome_index=outcome_index,
            outcome_name=outcome_name,
            side=side,
            price=price,
            usdc_size=usdc_size,
            shares=shares,
        )

        # SELL trades pass through for exit handling
        if side != "BUY":
            logger.debug(f"Passing through SELL for exit handling")
            return trade

        # Price filter: Don't buy at extreme prices
        if price > self.max_price:
            logger.warning(
                f"SKIP: {market_name[:40]} | {outcome_name} @ {price:.0%} "
                f"(above max {self.max_price:.0%})"
            )
            self.trades_skipped += 1
            return None

        if price < self.min_price:
            logger.warning(
                f"SKIP: {market_name[:40]} | {outcome_name} @ {price:.0%} "
                f"(below min {self.min_price:.0%})"
            )
            self.trades_skipped += 1
            return None

        # Passed filters - execute
        self.trades_copied += 1
        logger.info(
            f"COPY: {market_name[:40]} | {outcome_name} @ {price:.0%}"
        )
        return trade

    def get_stats(self) -> dict:
        """Get strategy statistics."""
        return {
            "trades_copied": self.trades_copied,
            "trades_skipped": self.trades_skipped,
        }

    def print_status(self):
        """Print current status."""
        stats = self.get_stats()
        logger.info("=== STRATEGY STATUS ===")
        logger.info(f"Trades copied: {stats['trades_copied']}")
        logger.info(f"Trades skipped: {stats['trades_skipped']}")


def create_strategy(
    max_price: float = MAX_PRICE,
    min_price: float = MIN_PRICE,
) -> DirectionalStrategy:
    """Factory function to create directional strategy."""
    return DirectionalStrategy(
        max_price=max_price,
        min_price=min_price,
    )
