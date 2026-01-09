"""Trade execution service - copies trades on Polymarket."""

import asyncio
import concurrent.futures
import logging
import math
import time
from typing import Optional, Dict, Any
from collections import OrderedDict

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, AssetType

from .config import Config
from .paper_trader import PaperTrader
from .slippage_control import create_slippage_controller
from .hedging import create_hedging_controller
from .strategy import create_strategy, Trade
from .market_classifier import classify_market, CryptoAsset
from .session_logger import get_session_logger

# Side constants
BUY = "BUY"
SELL = "SELL"

logger = logging.getLogger(__name__)


def _is_cloudflare_block_error(err: Exception) -> bool:
    """Heuristic detection of Cloudflare blocks returned as HTML with 403s."""
    msg = str(err).lower()
    if "status_code=403" in msg or "403 forbidden" in msg:
        if "cloudflare" in msg or "enable cookies" in msg or "been blocked" in msg:
            return True
    return False


def truncate_name(name: str, max_len: int = 40) -> str:
    """Truncate market name to max length for display."""
    if not name:
        return ""
    return name[:max_len] if len(name) > max_len else name


class TradeExecutor:
    """Executes copy trades on Polymarket."""

    def __init__(self, client: Optional[ClobClient], config: Config, paper_trader: Optional[PaperTrader] = None):
        self.client = client
        self.config = config
        self.paper_trader = paper_trader

        # Position tracking: token_id -> {side, total_size, avg_price, market_name}
        self.positions: Dict[str, dict] = {}

        # Duplicate detection: OrderedDict to maintain insertion order for proper FIFO eviction
        self.processed_trades: OrderedDict = OrderedDict()

        # Balance tracking with caching for latency optimization
        self._cached_balance: Optional[float] = None
        self._balance_cache_time: float = 0
        self._balance_cache_ttl: float = 5.0  # Cache balance for 5 seconds
        self._balance_warning_threshold = 50.0  # Warn when below $50

        # Slippage control - use percentage-based, no skip for near-resolution
        self.slippage_controller = create_slippage_controller(
            max_slippage_pct=config.max_slippage_percent,
            max_slippage_cents=10.0,  # Not used when use_absolute=False
            use_absolute=False,
            skip_near_resolution=False,  # Target bets on near-resolution markets
            enable_price_improvement=True,
        )
        logger.info(f"Slippage control enabled: max {config.max_slippage_percent}%")

        # Hedging controller - tracks positions to maintain balance like target
        # In DRY_RUN we optionally simulate full-size copying, so hedge math must match.
        hedging_copy_ratio = 1.0 if config.dry_run else config.copy_ratio
        self.hedging_controller = create_hedging_controller(
            max_imbalance_pct=config.max_hedge_imbalance_percent,
            copy_ratio=hedging_copy_ratio,
            target_address=config.target_trader_address,
        )
        logger.info(f"Hedging control enabled: max imbalance {config.max_hedge_imbalance_percent}%")

        # Directional copy trading strategy
        self.strategy = create_strategy(
            max_price=config.max_price,
            min_price=config.min_price,
        )

    def is_duplicate_trade(self, activity: dict) -> bool:
        """Check if we've already processed this trade."""
        tx_hash = activity.get("transactionHash")
        if not tx_hash:
            return False

        if tx_hash in self.processed_trades:
            logger.debug(f"Skipping duplicate trade: {tx_hash[:16]}...")
            return True

        return False

    def mark_trade_processed(self, activity: dict):
        """Mark a trade as processed to avoid duplicates."""
        tx_hash = activity.get("transactionHash")
        if tx_hash:
            self.processed_trades[tx_hash] = True  # Value doesn't matter, using dict for ordered keys
            # Keep size manageable - remove oldest entries (FIFO order preserved)
            while len(self.processed_trades) > 1000:
                self.processed_trades.popitem(last=False)  # Remove oldest (first inserted)

    def update_position(self, token_id: str, side: str, size: float, price: float, market_name: str,
                         condition_id: str = "", outcome_index: int = 0):
        """
        Update position tracking after a successful trade.
        FIX #3: Now syncs ALL position trackers (executor, paper_trader, hedging)

        Args:
            token_id: The token/market ID.
            side: BUY or SELL.
            size: USDC amount of the trade.
            price: Price per share.
            market_name: Human-readable market name.
            condition_id: Market condition ID for hedging controller.
            outcome_index: Outcome index (0 or 1) for hedging controller.
        """
        shares = size / price if price > 0 else 0

        # UPDATE 1: Executor's position tracker
        if side == BUY:
            if token_id not in self.positions:
                self.positions[token_id] = {
                    "side": side,
                    "shares": shares,
                    "cost_basis": size,
                    "market_name": market_name,
                }
            else:
                pos = self.positions[token_id]
                pos["shares"] += shares
                pos["cost_basis"] += size
        else:
            # SELL - only process if we have a position
            if token_id in self.positions:
                pos = self.positions[token_id]
                pos["shares"] -= shares
                pos["cost_basis"] = max(0, pos["cost_basis"] - size)

                # Remove position if closed (use pop for safe deletion)
                if pos["shares"] <= 0:
                    self.positions.pop(token_id, None)
                    logger.info(f"Position closed: {truncate_name(market_name, self.config.market_name_max_len)}")

        # UPDATE 2: Hedging controller's position tracker
        if condition_id:
            self.hedging_controller.update_our_position(
                condition_id=condition_id,
                market_name=market_name,
                outcome_index=outcome_index,
                shares=shares,
                cost=size,
                side=side
            )

        logger.debug(f"Position synced across all trackers: {truncate_name(market_name, self.config.market_name_max_len)} {side} {shares:.2f} shares")

    def get_positions_summary(self) -> str:
        """Get a summary of current positions."""
        if not self.positions:
            return "No open positions"

        lines = ["Open Positions:"]
        for token_id, pos in self.positions.items():
            lines.append(
                f"  {truncate_name(pos['market_name'], self.config.market_name_max_len)}: {pos['shares']:.2f} shares, "
                f"${pos['cost_basis']:.2f} invested"
            )
        return "\n".join(lines)

    def calculate_trade_size(self, original_amount: float, market_name: str = "") -> Optional[float]:
        """
        Calculate the trade size based on per-asset ratios and limits.

        Per-asset scaling for 15-minute crypto markets:
        - BTC markets: Use btc_copy_ratio
        - ETH markets: Use eth_copy_ratio
        - SOL markets: Use sol_copy_ratio
        - Other markets: Fall back to conviction scaling

        Args:
            original_amount: The original trade amount from target trader.
            market_name: Market title for asset classification.

        Returns:
            Calculated trade size, or None if outside limits.
        """
        # DRY RUN: Copy at 100% size (no scaling down) so paper trading reflects
        # the target's notional more realistically.
        if self.config.dry_run:
            return float(original_amount)

        # If we don't have a market name/title (e.g., unit tests or degraded API data),
        # fall back to the configured baseline copy ratio.
        if not market_name:
            copy_ratio = self.config.copy_ratio
            logger.info(f"No market title: ${original_amount:.2f} -> {copy_ratio*100:.0f}% copy ratio")
        else:
            # Classify market and get appropriate copy ratio
            asset = classify_market(market_name)

            if asset != CryptoAsset.UNKNOWN:
                # Per-asset ratio for known crypto markets
                copy_ratio = self.config.get_copy_ratio_for_asset(asset.value)
                logger.info(f"{asset.value} market: ${original_amount:.2f} -> {copy_ratio*100:.0f}% copy ratio")
            else:
                # Fall back to conviction scaling for other markets
                if original_amount < self.config.high_conviction_threshold:
                    copy_ratio = self.config.high_conviction_ratio
                    logger.info(f"SMALL BET (high ROI): ${original_amount:.2f} -> {copy_ratio*100:.0f}% copy ratio")
                else:
                    copy_ratio = self.config.low_conviction_ratio
                    logger.info(f"Large bet (lower ROI): ${original_amount:.2f} -> {copy_ratio*100:.0f}% copy ratio")

        scaled_amount = original_amount * copy_ratio

        # Apply min/max constraints (skip min if set to 0)
        if self.config.min_trade_amount > 0 and scaled_amount < self.config.min_trade_amount:
            logger.info(
                f"Scaled amount ${scaled_amount:.2f} below minimum "
                f"${self.config.min_trade_amount:.2f}, using minimum"
            )
            scaled_amount = self.config.min_trade_amount

        if scaled_amount > self.config.max_trade_amount:
            logger.info(
                f"Scaled amount ${scaled_amount:.2f} above maximum "
                f"${self.config.max_trade_amount:.2f}, capping"
            )
            scaled_amount = self.config.max_trade_amount

        return scaled_amount

    def parse_trade_activity(self, activity: dict) -> Optional[dict]:
        """
        Parse activity data to extract trade details.

        Args:
            activity: Raw activity data from the API.

        Returns:
            Parsed trade info or None if not a trade.
        """
        # Activity types: TRADE, TRANSFER, etc.
        activity_type = activity.get("type", "").upper()

        if activity_type != "TRADE":
            logger.debug(f"Skipping non-trade activity: {activity_type}")
            return None

        # Extract relevant fields from actual API response format
        # API returns: asset (token ID string), side, usdcSize, price, title
        token_id = activity.get("asset")  # This is the token ID string directly
        side = activity.get("side", "").upper()
        amount = activity.get("usdcSize") or activity.get("size")
        price = activity.get("price")

        # Get market name from title field
        market_name = activity.get("title") or f"Market {str(token_id)[:8]}..."

        if not all([token_id, side, amount]):
            logger.warning(f"Missing required trade fields in: {activity}")
            return None

        # Normalize side
        if side in ["BUY", "B"]:
            side = BUY
        elif side in ["SELL", "S"]:
            side = SELL
        else:
            logger.warning(f"Unknown trade side: {side}")
            return None

        return {
            "token_id": str(token_id),
            "side": side,
            "amount": float(amount),
            "price": float(price) if price else None,
            "market_name": market_name,
            "raw": activity,
        }

    async def copy_trade(self, activity: dict) -> Optional[dict]:
        """
        Copy a detected trade from target.

        Args:
            activity: Activity data from the monitor.

        Returns:
            Order response if successful, None otherwise.
        """
        # Early filter: Only process TRADE activities (skip REDEEM, TRANSFER, etc.)
        activity_type = activity.get("type", "").upper()
        if activity_type != "TRADE":
            return None

        # Duplicate detection - skip if already processed
        if self.is_duplicate_trade(activity):
            return None

        # Mark as processed immediately to prevent duplicates
        self.mark_trade_processed(activity)

        # Evaluate trade with strategy filters
        trade = self.strategy.evaluate(activity)

        if trade is None:
            # Trade didn't pass filters (price too high/low)
            return {"status": "skipped", "reason": "price_filter"}

        # Execute the trade
        return await self._execute_trade(trade)

    async def _execute_trade(self, trade: Trade) -> Optional[Dict[str, Any]]:
        """
        Execute a single trade.

        Args:
            trade: Trade object from strategy.

        Returns:
            Order response if successful, None otherwise.
        """
        market_name = truncate_name(trade.activity.get("title", "Unknown"), self.config.market_name_max_len)
        price = trade.price
        side = trade.side
        size = float(trade.activity.get("usdcSize", 0))

        logger.info(f"EXECUTING: {side} {market_name} @ {price:.0%}")

        result = await self._execute_single_trade(trade.activity)
        session = get_session_logger()

        if not result:
            if session:
                session.increment_failed()
            return {
                "status": "failed",
                "success": False,
                "result": None,
                "market": market_name,
                "price": price,
            }

        inner_status = result.get("status")
        if inner_status == "blocked":
            if session:
                session.increment_failed()
            return {
                "status": "blocked",
                "success": False,
                "reason": result.get("reason", "cloudflare_block"),
                "result": result,
                "market": market_name,
                "price": price,
            }
        if inner_status in ("skipped", "cancelled"):
            if session:
                session.increment_skipped()
            return {
                "status": inner_status,
                "success": False,
                "reason": result.get("reason"),
                "result": result,
                "market": market_name,
                "price": price,
            }

        success = inner_status in ("matched", "success", "paper_trade", "dry_run") or bool(result.get("success"))

        if session:
            if success:
                # Track executed trade with volume (use our scaled size, not original)
                scaled_size = self.calculate_trade_size(size, trade.activity.get("title", ""))
                session.increment_executed(volume=scaled_size or 0)
            else:
                session.increment_failed()

        return {
            "status": "executed" if success else "failed",
            "success": success,
            "result": result,
            "market": market_name,
            "price": price,
        }

    async def _execute_single_trade(self, activity: dict) -> Optional[dict]:
        """
        Execute a single trade.

        Args:
            activity: Activity data from the monitor.

        Returns:
            Order response if successful, None otherwise.
        """
        # Parse the activity into trade details
        trade = self.parse_trade_activity(activity)
        if not trade:
            return None

        # Update target's position in hedging controller
        condition_id = activity.get("conditionId", "")
        outcome_index = activity.get("outcomeIndex", 0)
        target_shares = activity.get("size", 0)
        self.hedging_controller.update_target_position(
            condition_id=condition_id,
            outcome_index=outcome_index,
            shares=target_shares,
            side=trade["side"]
        )

        # DOMINANT SIDE CHECK: Only copy trades on target's dominant side
        # This prevents copying minority-side trades (e.g., if target is 70% DOWN, skip UP trades)
        if trade["side"] == BUY:
            is_dominant, dominance_reason = self.hedging_controller.is_target_dominant_side(
                condition_id=condition_id,
                outcome_index=outcome_index,
                min_dominance=0.55  # Only copy if target has 55%+ on this side
            )
            if not is_dominant:
                logger.info(f"DOMINANT SKIP: {dominance_reason}")
                return {"status": "skipped", "reason": "minority_side"}
            else:
                logger.debug(f"Dominant check: {dominance_reason}")

        # SKIP OPPOSITE SIDE: Don't bet on opposite side of markets we already hold
        if self.config.skip_opposite_side and trade["side"] == BUY:
            our_pos = self.hedging_controller.our_positions.get(condition_id)
            if our_pos and our_pos.total_shares > 0:
                # Check if this trade is for the OPPOSITE outcome
                if outcome_index == 0 and our_pos.outcome_1_shares > 0:
                    logger.info(f"SKIP OPPOSITE: Already hold {our_pos.outcome_1_shares:.1f} shares of opposite side")
                    return {"status": "skipped", "reason": "opposite_side_held"}
                elif outcome_index == 1 and our_pos.outcome_0_shares > 0:
                    logger.info(f"SKIP OPPOSITE: Already hold {our_pos.outcome_0_shares:.1f} shares of opposite side")
                    return {"status": "skipped", "reason": "opposite_side_held"}

        # Hedging check - skip trades that would make us too imbalanced vs target
        should_copy, hedge_reason = self.hedging_controller.should_copy_trade(
            condition_id=condition_id,
            outcome_index=outcome_index,
            shares=target_shares,
            side=trade["side"]
        )
        if not should_copy:
            logger.info(f"HEDGE SKIP: {hedge_reason}")
            return {"status": "skipped", "reason": f"hedging_{hedge_reason}"}
        else:
            logger.debug(f"Hedge check passed: {hedge_reason}")

        # Calculate our trade size (using per-asset ratios for crypto markets)
        size = self.calculate_trade_size(trade["amount"], trade["market_name"])
        if size is None:
            return None

        # Apply target's sizing weight - if they put 70% on one side, we weight it more
        if trade["side"] == BUY:
            sizing_weight = self.hedging_controller.get_target_sizing_weight(condition_id, outcome_index)
            if sizing_weight != 1.0:
                original_size = size
                size = size * sizing_weight
                # Still respect max trade amount
                if size > self.config.max_trade_amount:
                    size = self.config.max_trade_amount
                logger.info(f"TARGET SIZING: Weight {sizing_weight:.2f}x -> ${original_size:.2f} -> ${size:.2f}")

        # EXIT COPYING: For SELL orders, check if we have a position to sell
        if trade["side"] == SELL:
            token_id = trade["token_id"]
            if token_id not in self.positions:
                logger.debug(f"Skipping SELL - no position held in {truncate_name(trade['market_name'], self.config.market_name_max_len)}")
                return {"status": "skipped", "reason": "no_position_to_sell"}

            # Sell proportionally to what we hold (not more than we have)
            our_position = self.positions[token_id]
            our_shares = our_position["shares"]

            # Calculate how many shares to sell based on copy ratio
            price = trade["price"] if trade["price"] else 0.5
            target_sell_shares = (trade["amount"] / price) if price > 0 else 0

            # Scale by copy ratio and cap at our position
            effective_copy_ratio = 1.0 if self.config.dry_run else self.config.copy_ratio
            shares_to_sell = min(target_sell_shares * effective_copy_ratio, our_shares)

            if shares_to_sell <= 0:
                logger.info("No shares to sell")
                return None

            # Convert shares back to USDC size
            size = shares_to_sell * price
            logger.info(f"EXIT COPY: Selling {shares_to_sell:.2f} shares (we hold {our_shares:.2f})")

        logger.info(
            f"Copying trade: {trade['side']} ${size:.2f} USDC "
            f"(original: ${trade['amount']:.2f} USDC) "
            f"market: {truncate_name(trade['market_name'], self.config.market_name_max_len)}"
        )

        # Get price
        price = trade["price"]
        if price is None:
            price = 0.5  # Default price if not available
            logger.warning(f"No price in activity, using default: {price}")

        # DRY RUN MODE - Paper trading
        if self.config.dry_run:
            logger.info("[DRY RUN] Simulating trade execution...")

            # In DRY_RUN, make execution realistic:
            # - fetch the current top-of-book price
            # - skip trades if slippage exceeds the configured cap
            # - simulate the fill at the current book price (not the target's)
            target_price = price
            execution_price = price
            book_price: Optional[float] = None

            if self.client:
                try:
                    book = self.client.get_order_book(trade["token_id"])
                    if trade["side"] == BUY and book.asks:
                        sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
                        book_price = float(sorted_asks[0].price)
                    elif trade["side"] == SELL and book.bids:
                        sorted_bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True)
                        book_price = float(sorted_bids[0].price)
                    else:
                        logger.warning("[DRY RUN] No liquidity in order book; cannot simulate realistic slippage")
                except Exception as e:
                    logger.warning(f"[DRY RUN] Failed to fetch order book for slippage simulation: {e}")

            if book_price is not None:
                should_proceed, adjusted_price, reason = self.slippage_controller.evaluate_trade(
                    target_price=target_price,
                    market_price=book_price,
                    side=trade["side"],
                    market_name=trade["market_name"],
                )

                # Calculate slippage percentage for contrarian logic
                slippage_pct = abs(book_price - target_price) / target_price * 100 if target_price > 0 else 0

                if not should_proceed:
                    # CONTRARIAN MODE: If slippage is high, take the OPPOSITE side
                    if self.config.contrarian_mode and slippage_pct >= self.config.contrarian_min_slippage:
                        # Flip the trade - bet against the target's direction
                        opposite_side = SELL if trade["side"] == BUY else BUY
                        # The opposite token price is roughly 1 - book_price (binary market)
                        opposite_price = 1.0 - book_price

                        logger.info(f"[CONTRARIAN] Slippage {slippage_pct:.1f}% >= {self.config.contrarian_min_slippage}% threshold")
                        logger.info(f"[CONTRARIAN] FADING target: {trade['side']} -> {opposite_side} @ ${opposite_price:.4f}")

                        # For contrarian, we need the opposite token_id
                        # We'll use the activity data to get the condition and flip outcome
                        condition_id = activity.get("conditionId", "")
                        outcome_index = activity.get("outcomeIndex", 0)
                        opposite_outcome = 1 - outcome_index

                        if self.paper_trader:
                            # Simulate the contrarian trade
                            paper_trade = self.paper_trader.simulate_trade(
                                token_id=f"{trade['token_id']}_FADE",  # Mark as fade trade
                                market_name=f"[FADE] {trade['market_name']}",
                                side=BUY,  # We always BUY the opposite outcome
                                size=size,
                                price=opposite_price,
                                original_amount=trade["amount"],
                                copy_ratio=1.0,
                            )
                            if paper_trade:
                                logger.info(f"[CONTRARIAN] Paper trade: BUY opposite @ ${opposite_price:.4f}")
                                logger.info(f"[DRY RUN] Paper balance: ${self.paper_trader.usdc_balance:.2f}")
                                return {"status": "contrarian_trade", "trade": paper_trade, "original_side": trade["side"]}

                        return {"status": "contrarian_skipped", "reason": "no_paper_trader"}

                    if self.paper_trader:
                        self.paper_trader.record_skipped_trade()
                    return {"status": "skipped", "reason": reason, "target_price": target_price, "book_price": book_price}

                execution_price = adjusted_price
            else:
                logger.info("[DRY RUN] Order book unavailable; using target price (slippage not simulated)")

            if self.paper_trader:
                paper_trade = self.paper_trader.simulate_trade(
                    token_id=trade["token_id"],
                    market_name=trade["market_name"],
                    side=trade["side"],
                    size=size,
                    price=execution_price,
                    original_amount=trade["amount"],
                    copy_ratio=1.0,
                )

                if paper_trade:
                    # Update executor.positions for SELL logic to work in dry-run
                    self.update_position(
                        token_id=trade["token_id"],
                        side=trade["side"],
                        size=size,
                        price=execution_price,
                        market_name=trade["market_name"],
                        condition_id=activity.get("conditionId", ""),
                        outcome_index=activity.get("outcomeIndex", 0),
                    )
                    logger.info(
                        f"[DRY RUN] Paper trade executed: {trade['side']} ${size:.2f} @ {execution_price:.4f} (target {target_price:.4f})"
                    )
                    logger.info(
                        f"[DRY RUN] Paper balance: ${self.paper_trader.usdc_balance:.2f}"
                    )
                    return {"status": "paper_trade", "trade": paper_trade}
                else:
                    logger.warning("[DRY RUN] Paper trade failed (see above)")
                    return None
            else:
                # No paper trader, just log what would happen
                logger.info(
                    f"[DRY RUN] Would execute: {trade['side']} ${size:.2f} @ {execution_price:.4f} (target {target_price:.4f})"
                )
                return {"status": "dry_run", "would_execute": trade}

        # LIVE MODE - Real trading
        if not self.client:
            logger.error("No CLOB client available for live trading")
            return None

        try:
            # LATENCY OPT #0: Pre-warm the library's cache for this token
            # These values are fetched anyway during order creation - do them in parallel with order book
            token_id = trade["token_id"]
            
            def prewarm_cache():
                """Fetch tick_size, neg_risk, fee_rate to warm cache."""
                try:
                    self.client.get_tick_size(token_id)
                    self.client.get_neg_risk(token_id)
                    self.client.get_fee_rate_bps(token_id)
                except Exception:
                    pass  # Cache warming is best-effort
            
            # Start cache warming in background thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool_executor:
                cache_future = pool_executor.submit(prewarm_cache)

                # LATENCY OPT #1: Fetch order book while cache is warming
                try:
                    book = self.client.get_order_book(token_id)
                except Exception as e:
                    logger.error(f"Failed to get order book: {e}")
                    return None

                # Wait for cache warming to complete (should be done by now)
                try:
                    cache_future.result(timeout=2.0)
                except (concurrent.futures.TimeoutError, Exception):
                    pass  # Cache warming is best-effort, don't fail the trade

            # Extract market price from order book
            if trade["side"] == BUY and book.asks:
                # For BUY, use best ask price (lowest price sellers are asking)
                sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
                market_price = float(sorted_asks[0].price)
                logger.info(f"Market BUY: using best ask price ${market_price:.4f}")
            elif trade["side"] == SELL and book.bids:
                # For SELL, use best bid price (highest price buyers are offering)
                sorted_bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True)
                market_price = float(sorted_bids[0].price)
                logger.info(f"Market SELL: using best bid price ${market_price:.4f}")
            else:
                logger.warning("No liquidity in order book")
                return None

            # Use market price if original price was missing
            if price is None or price == 0.5:
                price = market_price

            # PRICE LIMIT STRATEGY: Use target's price as our limit price
            # Instead of skipping trades with high slippage, we place limit orders at target's price
            # This ensures we never pay more than target, but still participate in the trade
            target_price = trade["price"] if trade["price"] else price

            # Determine execution price: use target price as limit (with buffer for slippage)
            # For fast-moving 15-min markets, target moves prices significantly - use 10% buffer
            slippage_buffer = self.config.max_slippage_percent / 100  # Use configured slippage as buffer
            if trade["side"] == BUY:
                # For BUY: willing to pay up to target price + slippage buffer
                # If market is cheaper, we get a better price; if more expensive, use our max limit
                max_price = round(target_price * (1 + slippage_buffer), 2)
                execution_price = min(market_price, max_price)
                if market_price > max_price:
                    logger.info(f"LIMIT ORDER: Market ${market_price:.2f} > max ${max_price:.2f} (target ${target_price:.2f} + {slippage_buffer*100:.0f}%)")
                else:
                    logger.info(f"MARKET BETTER: Market ${market_price:.2f} <= limit ${max_price:.2f}, executing at market")
            else:
                # For SELL: willing to sell at target price - slippage buffer
                min_price = round(target_price * (1 - slippage_buffer), 2)
                execution_price = max(market_price, min_price)
                if market_price < min_price:
                    logger.info(f"LIMIT ORDER: Market ${market_price:.2f} < min ${min_price:.2f} (target ${target_price:.2f} - {slippage_buffer*100:.0f}%)")
                else:
                    logger.info(f"MARKET BETTER: Market ${market_price:.2f} >= limit ${min_price:.2f}, executing at market")

            # Log slippage for monitoring (but don't skip)
            slippage_pct = abs(market_price - target_price) / target_price * 100 if target_price > 0 else 0
            logger.info(f"Slippage: {slippage_pct:.1f}% (target ${target_price:.2f} vs market ${market_price:.2f})")

            # Calculate shares at execution price
            shares = size / execution_price
            if shares < 5:
                logger.warning(f"Share count {shares:.2f} below minimum 5, adjusting to 5")
                shares = 5.0
                size = shares * execution_price

            # FIX #4: Round to proper decimal precision for FOK orders
            # API requires: price = 2 decimals max, taker (shares) = 2 decimals max for clean math, maker (size) = 2 decimals max
            execution_price = round(execution_price, 2)

            # Round shares DOWN to 2 decimals, then calculate size
            # Use math.ceil for minimum share count to ensure we hit $1 minimum
            shares = math.floor(shares * 100) / 100  # Round DOWN to 2 decimals
            size = round(shares * execution_price, 2)

            # Ensure minimum order notional.
            # Polymarket enforces a $1.00 minimum, and float/rounding inside the client/server
            # can occasionally turn a displayed "$1.00" into "$0.9999". Use a small buffer.
            min_notional = 1.01
            if size < min_notional:
                min_shares_needed = math.ceil(min_notional / execution_price * 100) / 100
                shares = max(shares, min_shares_needed)
                size = round(shares * execution_price, 2)
                # Double-check we're above $1.00 even after rounding.
                if size < 1.0:
                    shares = round(shares + 0.01, 2)
                    size = round(shares * execution_price, 2)

            logger.info(f"Order details: {shares:.2f} shares @ ${execution_price:.2f} = ${size:.2f} USDC")

            # LATENCY OPT #2: Single balance check (cached) for hedge reserve
            # This replaces two separate balance fetches that were adding 200-400ms latency
            if trade["side"] == BUY:
                balance = self.get_balance()  # Uses cache if available
                required_for_hedge = size * 2
                if balance is not None and balance < required_for_hedge:
                    logger.warning(f"HEDGE RESERVE: Need ${required_for_hedge:.2f} for balanced position, only have ${balance:.2f}")
                    return {"status": "skipped", "reason": f"insufficient_for_hedge_${required_for_hedge:.2f}_have_${balance:.2f}"}

            # Create the order at execution price (target's price or better)
            order_args = OrderArgs(
                token_id=trade["token_id"],
                price=execution_price,
                size=shares,  # size is in SHARES, not USDC
                side=trade["side"],
            )

            # Create and sign the order
            signed_order = self.client.create_order(order_args)

            # Submit as GTC (Good Till Cancel) since we're using limit price
            # This allows the order to wait for the price to come to us
            filled_shares = 0
            fill_price = execution_price
            
            try:
                response = self.client.post_order(signed_order, OrderType.FOK)
                logger.info(f"FOK order executed: {response}")
                if response.get("status") == "matched":
                    filled_shares = float(response.get("takingAmount", shares))
                    fill_price = float(response.get("price", execution_price))
            except Exception as fok_error:
                logger.warning(f"FOK order failed ({fok_error}), trying GTC with timeout")

                # Create a NEW signed order for GTC to avoid "Duplicated" error
                gtc_signed_order = self.client.create_order(order_args)
                response = self.client.post_order(gtc_signed_order, OrderType.GTC)
                order_id = response.get("orderID")

                if order_id and response.get("status") == "live":
                    # Order is live but not filled - wait and cancel if stale
                    logger.info(f"GTC order live, waiting {self.config.stale_order_timeout}s for fill...")
                    await asyncio.sleep(self.config.stale_order_timeout)

                    # FIX #1: Check for partial fills BEFORE canceling
                    try:
                        # Try to get order status to check for partial fills
                        order_status = self.client.get_order(order_id)
                        if order_status:
                            filled_shares = float(order_status.get("filledSize", 0))
                            if filled_shares > 0:
                                logger.info(f"PARTIAL FILL detected: {filled_shares:.4f} shares filled before cancel")
                    except Exception as status_err:
                        logger.debug(f"Could not check order status: {status_err}")

                    # Check if order is still open and cancel it
                    try:
                        cancel_response = self.client.cancel(order_id)
                        logger.info(f"Cancelled stale order {order_id[:16]}...: {cancel_response}")
                        
                        # FIX #1: If partial fill occurred, update position for what DID fill
                        if filled_shares > 0:
                            partial_size = filled_shares * fill_price
                            logger.warning(f"Updating position for PARTIAL FILL: {filled_shares:.4f} shares (${partial_size:.2f})")
                            self.update_position(
                                token_id=trade["token_id"],
                                side=trade["side"],
                                size=partial_size,
                                price=fill_price,
                                market_name=trade["market_name"],
                                condition_id=activity.get("conditionId", ""),
                                outcome_index=activity.get("outcomeIndex", 0),
                            )
                            self.invalidate_balance_cache()  # Balance changed on partial fill
                            return {
                                "status": "partial_fill",
                                "order_id": order_id,
                                "filled_shares": filled_shares,
                                "requested_shares": shares,
                                "fill_ratio": filled_shares / shares,
                            }
                        
                        # No fill at all
                        return {"status": "cancelled", "reason": "stale", "order_id": order_id}
                    except Exception as cancel_err:
                        # Order may have filled while we were waiting
                        logger.info(f"Cancel failed (order may have filled): {cancel_err}")
                        # Assume it filled if we can't cancel
                        filled_shares = shares

            logger.info(f"Order submitted successfully: {response}")

            # Only update position if order was filled (matched status)
            if response.get("status") == "matched" or response.get("success"):
                # FIX #3: Use unified update_position with all trackers synced
                actual_shares = float(response.get("takingAmount", shares))
                actual_size = actual_shares * fill_price

                self.update_position(
                    token_id=trade["token_id"],
                    side=trade["side"],
                    size=actual_size,
                    price=fill_price,
                    market_name=trade["market_name"],
                    condition_id=activity.get("conditionId", ""),
                    outcome_index=activity.get("outcomeIndex", 0),
                )

                # LATENCY OPT #3: Invalidate balance cache after trade execution
                # Balance changed, so next hedge check needs fresh data
                self.invalidate_balance_cache()

            return response

        except Exception as e:
            # Cloudflare sometimes returns an HTML block page with a 403.
            # Treat this as a specific failure mode so callers can back off.
            if _is_cloudflare_block_error(e):
                logger.error("Cloudflare block detected (HTTP 403). Backing off trade execution.")
                return {"status": "blocked", "reason": "cloudflare_403"}

            logger.error(f"Failed to execute trade: {e}")
            return None

    def get_balance(self, force_refresh: bool = False) -> Optional[float]:
        """
        Get current USDC balance with caching for latency optimization.

        Args:
            force_refresh: If True, bypass cache and fetch fresh balance.

        Returns:
            USDC balance or None if unavailable.
        """
        if self.config.dry_run and self.paper_trader:
            return self.paper_trader.usdc_balance

        if not self.client:
            return None

        # Check cache (unless force refresh requested)
        now = time.time()
        if not force_refresh and self._cached_balance is not None:
            cache_age = now - self._balance_cache_time
            if cache_age < self._balance_cache_ttl:
                logger.debug(f"Using cached balance: ${self._cached_balance:.2f} (age: {cache_age:.1f}s)")
                return self._cached_balance

        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_info = self.client.get_balance_allowance(params)
            # Balance is in USDC smallest units (6 decimals)
            raw_balance = float(balance_info.get("balance", 0))
            balance = raw_balance / 1_000_000  # Convert to USDC

            # Update cache
            self._cached_balance = balance
            self._balance_cache_time = now

            return balance
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None

    def invalidate_balance_cache(self):
        """Invalidate balance cache after a trade execution."""
        self._cached_balance = None
        self._balance_cache_time = 0
