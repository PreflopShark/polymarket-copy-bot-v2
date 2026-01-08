"""Paper trading service for dry run mode."""

import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class PaperTrader:
    """Simulates trades for dry run mode."""

    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.usdc_balance = initial_balance
        self.positions: Dict[str, dict] = {}
        self.trade_history: List[dict] = []
        self.trades_executed = 0
        self.trades_skipped = 0

    def execute_trade(self, token_id: str, market_name: str, side: str,
                      size: float, price: float) -> bool:
        """Simulate a trade execution."""
        if side == "BUY":
            if size > self.usdc_balance:
                logger.warning(f"Insufficient balance: need ${size:.2f}, have ${self.usdc_balance:.2f}")
                return False

            shares = size / price
            self.usdc_balance -= size

            if token_id not in self.positions:
                self.positions[token_id] = {
                    "shares": shares,
                    "cost": size,
                    "avg_price": price,
                    "market": market_name,
                }
            else:
                pos = self.positions[token_id]
                total_cost = pos["cost"] + size
                total_shares = pos["shares"] + shares
                pos["shares"] = total_shares
                pos["cost"] = total_cost
                pos["avg_price"] = total_cost / total_shares

            # Record trade
            self.trade_history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "BUY",
                "token_id": token_id,
                "market": market_name,
                "shares": shares,
                "price": price,
                "size": size,
            })

            self.trades_executed += 1
            return True

        elif side == "SELL":
            if token_id not in self.positions:
                logger.warning(f"No position to sell: {market_name}")
                return False

            pos = self.positions[token_id]
            shares_to_sell = min(size / price, pos["shares"])
            proceeds = shares_to_sell * price

            pos["shares"] -= shares_to_sell
            pos["cost"] -= shares_to_sell * pos["avg_price"]

            if pos["shares"] <= 0:
                del self.positions[token_id]

            self.usdc_balance += proceeds

            # Record trade
            self.trade_history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "SELL",
                "token_id": token_id,
                "market": market_name,
                "shares": shares_to_sell,
                "price": price,
                "size": proceeds,
            })

            self.trades_executed += 1
            return True

        return False

    def record_skipped(self):
        """Record a skipped trade."""
        self.trades_skipped += 1

    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cost basis)."""
        position_value = sum(p["cost"] for p in self.positions.values())
        return self.usdc_balance + position_value

    def get_pnl(self) -> tuple[float, float]:
        """Get P&L (absolute and percentage)."""
        portfolio_value = self.get_portfolio_value()
        pnl = portfolio_value - self.initial_balance
        pnl_pct = (pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        return pnl, pnl_pct

    def get_positions_list(self) -> List[dict]:
        """Get positions as a list for API response."""
        return [
            {
                "token_id": tid,
                "market": pos["market"],
                "shares": pos["shares"],
                "cost_basis": pos["cost"],
                "avg_price": pos["avg_price"],
            }
            for tid, pos in self.positions.items()
        ]

    def get_summary(self) -> dict:
        """Get paper trading summary."""
        pnl, pnl_pct = self.get_pnl()
        return {
            "initial_balance": self.initial_balance,
            "usdc_balance": self.usdc_balance,
            "portfolio_value": self.get_portfolio_value(),
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "trades_executed": self.trades_executed,
            "trades_skipped": self.trades_skipped,
            "positions_count": len(self.positions),
            "positions": self.get_positions_list(),
        }

    def reset(self):
        """Reset paper trader to initial state."""
        self.usdc_balance = self.initial_balance
        self.positions.clear()
        self.trade_history.clear()
        self.trades_executed = 0
        self.trades_skipped = 0
