"""
Paper trading service for dry run mode.

Implements TradeExecutor interface for simulated trading.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

from ..core.interfaces import TradeExecutor, TradeInfo, ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents a position in a market."""
    token_id: str
    market: str
    shares: float
    cost_basis: float
    avg_price: float

    @property
    def is_empty(self) -> bool:
        return self.shares <= 0


@dataclass
class TradeRecord:
    """Record of an executed trade."""
    timestamp: datetime
    trade_type: str  # BUY or SELL
    token_id: str
    market: str
    shares: float
    price: float
    size: float


class PaperTrader(TradeExecutor):
    """
    Simulates trades for dry run mode.

    Implements the TradeExecutor interface for paper trading.
    Tracks positions, balance, and P&L.
    """

    def __init__(self, initial_balance: float):
        self._initial_balance = initial_balance
        self._usdc_balance = initial_balance
        self._positions: Dict[str, Position] = {}
        self._trade_history: List[TradeRecord] = []
        self._trades_executed = 0
        self._trades_skipped = 0

    @property
    def balance(self) -> float:
        """Current USDC balance."""
        return self._usdc_balance

    @property
    def initial_balance(self) -> float:
        """Starting balance."""
        return self._initial_balance

    async def evaluate(self, trade: TradeInfo) -> Optional[Dict[str, Any]]:
        """
        Evaluate whether to copy a trade.

        For paper trading, we evaluate based on balance.
        Returns decision dict if should execute, None otherwise.
        """
        if trade.side == "BUY":
            if trade.size > self._usdc_balance:
                return None  # Insufficient balance
            return {
                "action": "BUY",
                "size": trade.size,
                "price": trade.price,
                "reason": "Paper trade - sufficient balance",
            }
        elif trade.side == "SELL":
            if trade.token_id not in self._positions:
                return None  # No position to sell
            pos = self._positions[trade.token_id]
            if pos.shares <= 0:
                return None
            return {
                "action": "SELL",
                "size": min(trade.size, pos.shares * trade.price),
                "price": trade.price,
                "reason": "Paper trade - have position",
            }
        return None

    async def execute(self, trade: TradeInfo, decision: Dict) -> ExecutionResult:
        """Execute the trade based on decision."""
        action = decision.get("action", trade.side)
        size = decision.get("size", trade.size)
        price = decision.get("price", trade.price)

        if action == "BUY":
            return self._execute_buy(trade, size, price)
        elif action == "SELL":
            return self._execute_sell(trade, size, price)

        return ExecutionResult(
            success=False,
            status="failed",
            message=f"Unknown action: {action}",
        )

    def _execute_buy(self, trade: TradeInfo, size: float, price: float) -> ExecutionResult:
        """Execute a buy order."""
        if size > self._usdc_balance:
            return ExecutionResult(
                success=False,
                status="skipped",
                message=f"Insufficient balance: need ${size:.2f}, have ${self._usdc_balance:.2f}",
                reason="insufficient_balance",
            )

        shares = size / price
        self._usdc_balance -= size

        if trade.token_id not in self._positions:
            self._positions[trade.token_id] = Position(
                token_id=trade.token_id,
                market=trade.market_name,
                shares=shares,
                cost_basis=size,
                avg_price=price,
            )
        else:
            pos = self._positions[trade.token_id]
            total_cost = pos.cost_basis + size
            total_shares = pos.shares + shares
            pos.shares = total_shares
            pos.cost_basis = total_cost
            pos.avg_price = total_cost / total_shares

        self._record_trade("BUY", trade, shares, price, size)
        self._trades_executed += 1

        return ExecutionResult(
            success=True,
            status="paper_trade",
            message=f"Paper BUY: {shares:.4f} shares @ {price:.0%}",
            price=price,
            size=size,
            shares=shares,
        )

    def _execute_sell(self, trade: TradeInfo, size: float, price: float) -> ExecutionResult:
        """Execute a sell order."""
        if trade.token_id not in self._positions:
            return ExecutionResult(
                success=False,
                status="skipped",
                message=f"No position to sell: {trade.market_name}",
                reason="no_position",
            )

        pos = self._positions[trade.token_id]
        shares_to_sell = min(size / price, pos.shares)
        proceeds = shares_to_sell * price

        pos.shares -= shares_to_sell
        pos.cost_basis -= shares_to_sell * pos.avg_price

        if pos.is_empty:
            del self._positions[trade.token_id]

        self._usdc_balance += proceeds
        self._record_trade("SELL", trade, shares_to_sell, price, proceeds)
        self._trades_executed += 1

        return ExecutionResult(
            success=True,
            status="paper_trade",
            message=f"Paper SELL: {shares_to_sell:.4f} shares @ {price:.0%}",
            price=price,
            size=proceeds,
            shares=shares_to_sell,
        )

    def _record_trade(self, trade_type: str, trade: TradeInfo, shares: float,
                      price: float, size: float) -> None:
        """Record a trade in history."""
        self._trade_history.append(TradeRecord(
            timestamp=datetime.now(),
            trade_type=trade_type,
            token_id=trade.token_id,
            market=trade.market_name,
            shares=shares,
            price=price,
            size=size,
        ))

    def record_skipped(self) -> None:
        """Record a skipped trade."""
        self._trades_skipped += 1

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions as list."""
        return [
            {
                "token_id": pos.token_id,
                "market": pos.market,
                "shares": pos.shares,
                "cost_basis": pos.cost_basis,
                "avg_price": pos.avg_price,
            }
            for pos in self._positions.values()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        pnl, pnl_pct = self._calculate_pnl()
        return {
            "initial_balance": self._initial_balance,
            "usdc_balance": self._usdc_balance,
            "portfolio_value": self._get_portfolio_value(),
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "trades_executed": self._trades_executed,
            "trades_skipped": self._trades_skipped,
            "positions_count": len(self._positions),
            "positions": self.get_positions(),
        }

    def _get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cost basis)."""
        position_value = sum(p.cost_basis for p in self._positions.values())
        return self._usdc_balance + position_value

    def _calculate_pnl(self) -> tuple[float, float]:
        """Get P&L (absolute and percentage)."""
        portfolio_value = self._get_portfolio_value()
        pnl = portfolio_value - self._initial_balance
        pnl_pct = (pnl / self._initial_balance) * 100 if self._initial_balance > 0 else 0
        return pnl, pnl_pct

    def get_trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get trade history."""
        return [
            {
                "timestamp": t.timestamp.isoformat(),
                "type": t.trade_type,
                "token_id": t.token_id,
                "market": t.market,
                "shares": t.shares,
                "price": t.price,
                "size": t.size,
            }
            for t in self._trade_history[-limit:]
        ]

    def reset(self) -> None:
        """Reset paper trader to initial state."""
        self._usdc_balance = self._initial_balance
        self._positions.clear()
        self._trade_history.clear()
        self._trades_executed = 0
        self._trades_skipped = 0
        logger.info("Paper trader reset")
