"""
Paper trading service for dry run mode.

Implements TradeExecutor interface for simulated trading.
"""

import asyncio
import random
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

    When simulate_real_market=True, adds realistic execution conditions:
    - Execution delay (100-300ms)
    - Size-based slippage (larger orders = more slippage)
    - Partial fills (5% chance, fills 60-90%)
    - Order rejection (2% chance)
    """

    def __init__(self, initial_balance: float, simulate_real_market: bool = False):
        self._initial_balance = initial_balance
        self._usdc_balance = initial_balance
        self._positions: Dict[str, Position] = {}
        self._trade_history: List[TradeRecord] = []
        self._trades_executed = 0
        self._trades_skipped = 0
        self._simulate_real_market = simulate_real_market

        # Simulation stats
        self._partial_fills = 0
        self._rejections = 0

        # Realized PnL tracking
        self._realized_pnl = 0.0
        self._resolved_positions: List[Dict[str, Any]] = []

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

        # Apply real market simulation if enabled
        if self._simulate_real_market:
            size, price, sim_result = await self._apply_market_simulation(action, size, price)
            if sim_result:
                return sim_result

        if action == "BUY":
            return self._execute_buy(trade, size, price)
        elif action == "SELL":
            return self._execute_sell(trade, size, price)

        return ExecutionResult(
            success=False,
            status="failed",
            message=f"Unknown action: {action}",
        )

    async def _apply_market_simulation(
        self, action: str, size: float, price: float
    ) -> tuple[float, float, Optional[ExecutionResult]]:
        """
        Apply realistic market conditions to the trade.

        Based on observed Polymarket behavior:
        - Execution delay: 100-300ms (order processing time)
        - Slippage: 0.5-3% based on order size (larger = more)
        - Partial fills: 5% chance, fills 60-90%
        - Rejection: 2% chance (liquidity issues)

        Returns (adjusted_size, adjusted_price, failure_result or None)
        """
        # 1. Execution delay (100-300ms like real order processing)
        delay = random.uniform(0.1, 0.3)
        await asyncio.sleep(delay)
        logger.debug(f"[SIM] Execution delay: {delay*1000:.0f}ms")

        # 2. Order rejection (2% chance - simulates low liquidity)
        if random.random() < 0.02:
            self._rejections += 1
            logger.info(f"[SIM] Order rejected (low liquidity simulation)")
            return size, price, ExecutionResult(
                success=False,
                status="rejected",
                message="Order rejected - insufficient liquidity (simulated)",
                reason="liquidity_rejection",
            )

        # 3. Slippage based on order size
        # Larger orders move the market more
        # $1-10: 0.5% avg, $10-50: 1% avg, $50+: 1.5-3% avg
        base_slippage = 0.005  # 0.5% base
        if size > 50:
            base_slippage = random.uniform(0.015, 0.03)  # 1.5-3%
        elif size > 10:
            base_slippage = random.uniform(0.008, 0.015)  # 0.8-1.5%
        else:
            base_slippage = random.uniform(0.003, 0.008)  # 0.3-0.8%

        # Apply slippage (unfavorable direction)
        if action == "BUY":
            price = price * (1 + base_slippage)  # Pay more
        else:
            price = price * (1 - base_slippage)  # Receive less

        logger.debug(f"[SIM] Applied slippage: {base_slippage:.2%}")

        # 4. Partial fills (5% chance, more likely on larger orders)
        partial_chance = 0.05 if size < 25 else 0.10
        if random.random() < partial_chance:
            fill_ratio = random.uniform(0.6, 0.9)
            original_size = size
            size = size * fill_ratio
            self._partial_fills += 1
            logger.info(f"[SIM] Partial fill: {fill_ratio:.0%} of ${original_size:.2f} = ${size:.2f}")

        return size, price, None

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

    def redeem_position(self, token_id: str, resolution_price: float) -> Optional[Dict[str, Any]]:
        """
        Redeem a resolved position and realize the PnL.

        Args:
            token_id: The token ID of the resolved position
            resolution_price: 1.0 if won (YES outcome), 0.0 if lost (NO outcome)

        Returns:
            Dict with redemption details, or None if position not found
        """
        if token_id not in self._positions:
            return None

        position = self._positions[token_id]
        payout = position.shares * resolution_price
        pnl = payout - position.cost_basis

        # Update balance with payout
        self._usdc_balance += payout

        # Track realized PnL
        self._realized_pnl += pnl

        # Record the resolved position
        resolved_record = {
            "timestamp": datetime.now().isoformat(),
            "market": position.market,
            "token_id": token_id,
            "shares": position.shares,
            "cost_basis": position.cost_basis,
            "avg_price": position.avg_price,
            "resolution_price": resolution_price,
            "payout": payout,
            "pnl": pnl,
        }
        self._resolved_positions.append(resolved_record)

        # Remove the position
        del self._positions[token_id]

        logger.info(f"Position redeemed: {position.market} | Payout: ${payout:.2f} | PnL: ${pnl:.2f}")
        return resolved_record

    @property
    def realized_pnl(self) -> float:
        """Total realized PnL from resolved positions."""
        return self._realized_pnl

    def get_resolved_positions(self) -> List[Dict[str, Any]]:
        """Get list of all resolved/redeemed positions."""
        return self._resolved_positions.copy()

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
        unrealized_pnl = self._calculate_unrealized_pnl()
        stats = {
            "initial_balance": self._initial_balance,
            "usdc_balance": self._usdc_balance,
            "portfolio_value": self._get_portfolio_value(),
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": self._realized_pnl,
            "trades_executed": self._trades_executed,
            "trades_skipped": self._trades_skipped,
            "positions_count": len(self._positions),
            "positions": self.get_positions(),
            "resolved_count": len(self._resolved_positions),
            "resolved_positions": self._resolved_positions,
            "simulate_real_market": self._simulate_real_market,
        }

        # Include simulation stats if enabled
        if self._simulate_real_market:
            stats["simulation"] = {
                "partial_fills": self._partial_fills,
                "rejections": self._rejections,
            }

        return stats

    def _get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cost basis)."""
        position_value = sum(p.cost_basis for p in self._positions.values())
        return self._usdc_balance + position_value

    def _calculate_pnl(self) -> tuple[float, float]:
        """Get total P&L (realized + unrealized)."""
        portfolio_value = self._get_portfolio_value()
        pnl = portfolio_value - self._initial_balance
        pnl_pct = (pnl / self._initial_balance) * 100 if self._initial_balance > 0 else 0
        return pnl, pnl_pct

    def _calculate_unrealized_pnl(self) -> float:
        """Get unrealized P&L from open positions only."""
        # Unrealized = current market value - cost basis of open positions
        # Since we use cost basis as value (no live price feeds), unrealized is 0
        # for now. In a real implementation, this would fetch current prices.
        # For simulation, we track this as: total_pnl - realized_pnl
        total_pnl, _ = self._calculate_pnl()
        return total_pnl - self._realized_pnl

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
