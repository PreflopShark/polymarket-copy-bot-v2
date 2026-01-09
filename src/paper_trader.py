"""Paper trading tracker for dry-run mode."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    """A simulated position in a market."""

    token_id: str
    market_name: str
    side: str  # BUY or SELL
    size: float  # Number of shares
    entry_price: float
    entry_time: datetime
    usdc_spent: float


@dataclass
class PaperTrade:
    """Record of a simulated trade."""

    timestamp: datetime
    token_id: str
    market_name: str
    side: str
    size: float
    price: float
    usdc_amount: float
    original_trade_amount: float  # What the target trader traded
    copy_ratio: float


class PaperTrader:
    """Tracks simulated positions and P&L for dry-run testing."""

    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.usdc_balance = initial_balance
        self.positions: Dict[str, PaperPosition] = {}  # token_id -> position
        self.trade_history: List[PaperTrade] = []
        self.start_time = datetime.now()

        # Statistics
        self.trades_detected = 0
        self.trades_copied = 0
        self.trades_skipped = 0

    def record_skipped_trade(self):
        """Record a detected trade that was skipped before simulation (e.g., slippage cap)."""
        self.trades_detected += 1
        self.trades_skipped += 1

    def simulate_trade(
        self,
        token_id: str,
        market_name: str,
        side: str,
        size: float,
        price: float,
        original_amount: float,
        copy_ratio: float,
    ) -> Optional[PaperTrade]:
        """
        Simulate executing a trade.

        Args:
            token_id: The market token ID.
            market_name: Human-readable market name.
            side: BUY or SELL.
            size: USDC amount to trade.
            price: Current price per share.
            original_amount: What the target trader traded.
            copy_ratio: The copy ratio used.

        Returns:
            PaperTrade record if successful, None if insufficient balance.
        """
        self.trades_detected += 1

        # Calculate shares from USDC amount
        shares = size / price if price > 0 else 0

        if side == "BUY":
            if size > self.usdc_balance:
                logger.warning(
                    f"Insufficient paper balance: need ${size:.2f}, have ${self.usdc_balance:.2f}"
                )
                self.trades_skipped += 1
                return None

            # Deduct USDC
            self.usdc_balance -= size

            # Add or update position
            if token_id in self.positions:
                pos = self.positions[token_id]
                # Average in
                total_shares = pos.size + shares
                avg_price = (
                    (pos.entry_price * pos.size + price * shares) / total_shares
                    if total_shares > 0
                    else price
                )
                pos.size = total_shares
                pos.entry_price = avg_price
                pos.usdc_spent += size
            else:
                self.positions[token_id] = PaperPosition(
                    token_id=token_id,
                    market_name=market_name,
                    side="LONG",
                    size=shares,
                    entry_price=price,
                    entry_time=datetime.now(),
                    usdc_spent=size,
                )

        elif side == "SELL":
            if token_id not in self.positions:
                logger.warning(f"No position to sell for {token_id}")
                self.trades_skipped += 1
                return None

            pos = self.positions[token_id]
            shares_to_sell = min(shares, pos.size)

            # Add USDC from sale
            usdc_received = shares_to_sell * price
            self.usdc_balance += usdc_received

            # Update position
            pos.size -= shares_to_sell
            if pos.size <= 0.0001:  # Effectively zero
                del self.positions[token_id]

        # Record trade
        trade = PaperTrade(
            timestamp=datetime.now(),
            token_id=token_id,
            market_name=market_name,
            side=side,
            size=size,
            price=price,
            usdc_amount=size,
            original_trade_amount=original_amount,
            copy_ratio=copy_ratio,
        )
        self.trade_history.append(trade)
        self.trades_copied += 1

        return trade

    def get_portfolio_value(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        """
        Calculate total portfolio value.

        Args:
            current_prices: Dict of token_id -> current price. If None, uses entry prices.

        Returns:
            Total value in USDC.
        """
        positions_value = 0.0
        for token_id, pos in self.positions.items():
            price = (
                current_prices.get(token_id, pos.entry_price)
                if current_prices
                else pos.entry_price
            )
            positions_value += pos.size * price

        return self.usdc_balance + positions_value

    def get_pnl(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        """Get current P&L."""
        return self.get_portfolio_value(current_prices) - self.initial_balance

    def redeem_position(self, condition_id: str, market_name: str, winning_token_id: Optional[str] = None, usdc_redeemed: float = 0) -> float:
        """
        Redeem a resolved position (market settled).
        
        When the target trader redeems, we find matching positions by market name
        and resolve them - winners pay $1/share, losers pay $0.
        
        Args:
            condition_id: The market condition ID
            market_name: Market name to match positions
            winning_token_id: The token that won (if known)
            usdc_redeemed: Amount target redeemed (to estimate if we won)
            
        Returns:
            USDC gained from redemption
        """
        # Find positions matching this market
        market_name_short = market_name[:30].lower() if market_name else ""
        
        positions_to_redeem = []
        for token_id, pos in list(self.positions.items()):
            pos_name_short = pos.market_name[:30].lower() if pos.market_name else ""
            if market_name_short and market_name_short in pos_name_short:
                positions_to_redeem.append((token_id, pos))
            elif pos_name_short and pos_name_short in market_name_short:
                positions_to_redeem.append((token_id, pos))
        
        if not positions_to_redeem:
            return 0.0
        
        total_redeemed = 0.0
        
        for token_id, pos in positions_to_redeem:
            # Determine if this position won
            # If target redeemed > 0 for this token, they won
            is_winner = False
            if winning_token_id and token_id == winning_token_id:
                is_winner = True
            elif usdc_redeemed > 0:
                # Target got money back - assume they won
                # We need to figure out if OUR position won
                # For now, assume if target redeems significant amount, we won too
                # (since we're copying their exact positions)
                is_winner = True
            
            if is_winner:
                # Winner: shares * $1.00
                payout = pos.size * 1.0
                profit = payout - pos.usdc_spent
                total_redeemed += payout
                logger.info(f"🎉 WON: {pos.market_name[:40]}")
                logger.info(f"   Payout: ${payout:.2f} | Cost: ${pos.usdc_spent:.2f} | Profit: ${profit:+.2f}")
            else:
                # Loser: $0
                loss = pos.usdc_spent
                logger.info(f"❌ LOST: {pos.market_name[:40]}")
                logger.info(f"   Loss: -${loss:.2f}")
            
            # Remove position
            del self.positions[token_id]
        
        # Add winnings to balance
        self.usdc_balance += total_redeemed
        
        return total_redeemed

    def get_summary(self) -> dict:
        """Get summary statistics."""
        runtime = datetime.now() - self.start_time
        hours = runtime.total_seconds() / 3600

        return {
            "runtime_hours": round(hours, 2),
            "initial_balance": self.initial_balance,
            "current_usdc": round(self.usdc_balance, 2),
            "portfolio_value": round(self.get_portfolio_value(), 2),
            "pnl": round(self.get_pnl(), 2),
            "pnl_percent": round((self.get_pnl() / self.initial_balance) * 100, 2) if self.initial_balance > 0 else 0.0,
            "trades_detected": self.trades_detected,
            "trades_copied": self.trades_copied,
            "trades_skipped": self.trades_skipped,
            "open_positions": len(self.positions),
        }

    def print_status(self):
        """Print current status to logger."""
        summary = self.get_summary()
        logger.info("=" * 50)
        logger.info("PAPER TRADING STATUS")
        logger.info("=" * 50)
        logger.info(f"Runtime: {summary['runtime_hours']} hours")
        logger.info(f"USDC Balance: ${summary['current_usdc']:.2f}")
        logger.info(f"Portfolio Value: ${summary['portfolio_value']:.2f}")
        logger.info(f"P&L: ${summary['pnl']:.2f} ({summary['pnl_percent']:.2f}%)")
        logger.info(f"Trades Detected: {summary['trades_detected']}")
        logger.info(f"Trades Copied: {summary['trades_copied']}")
        logger.info(f"Trades Skipped: {summary['trades_skipped']}")
        logger.info(f"Open Positions: {summary['open_positions']}")

        if self.positions:
            logger.info("-" * 50)
            logger.info("OPEN POSITIONS:")
            for token_id, pos in self.positions.items():
                logger.info(
                    f"  {pos.market_name[:30]}: {pos.size:.4f} shares @ ${pos.entry_price:.4f}"
                )
        logger.info("=" * 50)

    def save_to_file(self, filepath: str):
        """Save trade history and status to JSON file."""
        data = {
            "summary": self.get_summary(),
            "positions": [
                {
                    "token_id": p.token_id,
                    "market_name": p.market_name,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "entry_time": p.entry_time.isoformat(),
                    "usdc_spent": p.usdc_spent,
                }
                for p in self.positions.values()
            ],
            "trades": [
                {
                    "timestamp": t.timestamp.isoformat(),
                    "token_id": t.token_id,
                    "market_name": t.market_name,
                    "side": t.side,
                    "size": t.size,
                    "price": t.price,
                    "usdc_amount": t.usdc_amount,
                    "original_trade_amount": t.original_trade_amount,
                }
                for t in self.trade_history
            ],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Paper trading data saved to {filepath}")
