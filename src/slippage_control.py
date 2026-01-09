"""
Slippage Control Layer for Polymarket Copy Trading Bot.

This module provides slippage minimization strategies:
1. Max slippage threshold - reject trades with excessive slippage
2. Price improvement - wait for better prices within a time window
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SlippageConfig:
    """Configuration for slippage control."""

    # Maximum allowed slippage in absolute cents (e.g., 0.03 = 3 cents)
    max_slippage_absolute: float = 0.03  # 3 cents default

    # Legacy percentage mode (disabled by default, absolute takes precedence)
    max_slippage_percent: float = 0.04  # 4% default (not used if absolute > 0)
    use_absolute_slippage: bool = True  # Use absolute instead of percentage

    # Skip trades near market resolution (price > threshold means outcome likely known)
    skip_near_resolution_threshold: float = 0.91  # Skip if price > 91%

    # Price improvement settings
    enable_price_improvement: bool = True
    price_improvement_wait_ms: int = 500  # Wait up to 500ms for better price
    price_check_interval_ms: int = 100  # Check price every 100ms


class SlippageController:
    """
    Controls and minimizes slippage for copy trades.

    Usage:
        controller = SlippageController(config)

        # Check if trade should proceed
        should_trade, adjusted_price, reason = controller.evaluate_trade(
            target_price=0.50,
            market_price=0.55,
            side="BUY"
        )
    """

    def __init__(self, config: Optional[SlippageConfig] = None):
        self.config = config or SlippageConfig()
        self.trade_history = []  # Track slippage for analytics

    def calculate_slippage(
        self,
        target_price: float,
        execution_price: float,
        side: str
    ) -> Tuple[float, float]:
        """
        Calculate slippage both as percentage and absolute.

        Args:
            target_price: Price the target trader got
            execution_price: Price we would execute at
            side: BUY or SELL

        Returns:
            Tuple of (slippage_percent, slippage_absolute)
            - slippage_percent: as a decimal (0.05 = 5% slippage)
            - slippage_absolute: in dollars (0.03 = 3 cents)
        """
        if target_price <= 0:
            return 0.0, 0.0

        if side == "BUY":
            # For buys, slippage is positive if we pay more
            slippage_absolute = execution_price - target_price
            slippage_percent = slippage_absolute / target_price
        else:
            # For sells, slippage is positive if we receive less
            slippage_absolute = target_price - execution_price
            slippage_percent = slippage_absolute / target_price

        return slippage_percent, slippage_absolute

    def is_near_resolution(self, price: float, side: str) -> bool:
        """
        Check if market is near resolution (outcome likely known).

        Args:
            price: Current market price
            side: BUY or SELL

        Returns:
            True if market appears to be resolving
        """
        threshold = self.config.skip_near_resolution_threshold

        # If buying and price is very high, outcome likely "Yes"
        # If buying and price is very low, outcome likely "No"
        if price >= threshold or price <= (1 - threshold):
            return True

        return False

    def evaluate_trade(
        self,
        target_price: float,
        market_price: float,
        side: str,
        market_name: str = ""
    ) -> Tuple[bool, float, str]:
        """
        Evaluate whether a trade should proceed given slippage.

        Args:
            target_price: Price the target trader executed at
            market_price: Current best price in order book
            side: BUY or SELL
            market_name: Name of the market for logging

        Returns:
            Tuple of (should_proceed, adjusted_price, reason)
        """
        slippage_pct, slippage_abs = self.calculate_slippage(target_price, market_price, side)
        slippage_pct_display = slippage_pct * 100
        slippage_cents = slippage_abs * 100  # Convert to cents for display

        # Log slippage (show both absolute and percentage)
        logger.info(
            f"Slippage analysis: {market_name[:30]} | "
            f"Target: ${target_price:.4f} | Market: ${market_price:.4f} | "
            f"Slippage: {slippage_cents:+.1f}c ({slippage_pct_display:+.1f}%)"
        )

        # Check if near resolution
        if self.is_near_resolution(market_price, side):
            reason = f"Market near resolution (price={market_price:.2f})"
            logger.warning(f"SKIP: {reason}")
            return False, market_price, reason

        # Check slippage threshold (use absolute if configured, else percentage)
        if self.config.use_absolute_slippage:
            # Absolute slippage check (in dollars, e.g., 0.03 = 3 cents)
            if slippage_abs > self.config.max_slippage_absolute:
                reason = f"Slippage {slippage_cents:.1f}c exceeds max {self.config.max_slippage_absolute * 100:.0f}c"
                logger.warning(f"SKIP: {reason}")
                return False, market_price, reason
        else:
            # Legacy percentage check
            if slippage_pct > self.config.max_slippage_percent:
                reason = f"Slippage {slippage_pct_display:.1f}% exceeds max {self.config.max_slippage_percent * 100:.1f}%"
                logger.warning(f"SKIP: {reason}")
                return False, market_price, reason

        # Trade is acceptable
        self._record_trade(target_price, market_price, slippage_pct, side)

        return True, market_price, f"Slippage acceptable: {slippage_cents:+.1f}c ({slippage_pct_display:+.1f}%)"

    def _record_trade(
        self,
        target_price: float,
        execution_price: float,
        slippage: float,
        side: str
    ):
        """Record trade for slippage analytics."""
        self.trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "target_price": target_price,
            "execution_price": execution_price,
            "slippage": slippage,
            "side": side,
        })

        # Keep last 100 trades
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]

    def get_slippage_stats(self) -> dict:
        """
        Get slippage statistics from trade history.

        Returns:
            Dict with slippage statistics
        """
        if not self.trade_history:
            return {
                "total_trades": 0,
                "avg_slippage": 0,
                "max_slippage": 0,
                "min_slippage": 0,
                "trades_skipped": 0,
            }

        slippages = [t["slippage"] for t in self.trade_history]

        return {
            "total_trades": len(self.trade_history),
            "avg_slippage": sum(slippages) / len(slippages),
            "max_slippage": max(slippages),
            "min_slippage": min(slippages),
            "avg_slippage_pct": f"{(sum(slippages) / len(slippages)) * 100:.2f}%",
            "max_slippage_pct": f"{max(slippages) * 100:.2f}%",
        }

    def print_stats(self):
        """Print slippage statistics to logger."""
        stats = self.get_slippage_stats()

        logger.info("=" * 50)
        logger.info("SLIPPAGE STATISTICS")
        logger.info("=" * 50)
        logger.info(f"Total trades analyzed: {stats['total_trades']}")
        logger.info(f"Average slippage: {stats.get('avg_slippage_pct', 'N/A')}")
        logger.info(f"Max slippage: {stats.get('max_slippage_pct', 'N/A')}")
        logger.info("=" * 50)


def create_slippage_controller(
    max_slippage_pct: float = 10.0,
    max_slippage_cents: float = 3.0,
    use_absolute: bool = True,
    skip_near_resolution: bool = True,
    enable_price_improvement: bool = True,
) -> SlippageController:
    """
    Factory function to create a configured SlippageController.

    Args:
        max_slippage_pct: Maximum allowed slippage in percent (default 10%)
        max_slippage_cents: Maximum allowed slippage in cents (default 3 cents)
        use_absolute: Use absolute (cents) instead of percentage (default True)
        skip_near_resolution: Skip trades on markets near resolution
        enable_price_improvement: Wait briefly for better prices

    Returns:
        Configured SlippageController instance
    """
    config = SlippageConfig(
        max_slippage_percent=max_slippage_pct / 100,
        max_slippage_absolute=max_slippage_cents / 100,  # Convert cents to dollars
        use_absolute_slippage=use_absolute,
        skip_near_resolution_threshold=0.90 if skip_near_resolution else 1.0,
        enable_price_improvement=enable_price_improvement,
    )

    return SlippageController(config)


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Create controller with 10% max slippage
    controller = create_slippage_controller(max_slippage_pct=10.0)

    # Test cases
    test_cases = [
        # (target_price, market_price, side, market_name)
        (0.50, 0.52, "BUY", "BTC Up - Normal slippage"),
        (0.50, 0.60, "BUY", "BTC Up - High slippage"),
        (0.50, 0.99, "BUY", "BTC Up - Near resolution"),
        (0.60, 0.58, "SELL", "ETH Down - Sell slippage"),
        (0.45, 0.46, "BUY", "SOL Up - Low slippage"),
    ]

    print("\n" + "=" * 60)
    print("SLIPPAGE CONTROL TEST")
    print("=" * 60 + "\n")

    for target, market, side, name in test_cases:
        should_trade, price, reason = controller.evaluate_trade(
            target_price=target,
            market_price=market,
            side=side,
            market_name=name
        )

        status = "✅ PROCEED" if should_trade else "❌ SKIP"
        print(f"{status}: {name}")
        print(f"   Reason: {reason}\n")

    # Print stats
    controller.print_stats()
