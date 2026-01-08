"""
Polymarket Copy Bot v2
A clean, minimal copy trading bot for Polymarket.
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiohttp
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, BalanceAllowanceParams, AssetType

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class Config:
    """Bot configuration from environment."""

    def __init__(self):
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        self.target_wallet = os.getenv("TARGET_WALLET", "")
        self.private_key = os.getenv("PRIVATE_KEY", "")
        self.funder_address = os.getenv("FUNDER_ADDRESS", "")
        self.api_key = os.getenv("POLYMARKET_API_KEY", "")
        self.api_secret = os.getenv("POLYMARKET_API_SECRET", "")
        self.api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "")

        self.max_trade_amount = float(os.getenv("MAX_TRADE_AMOUNT", "25"))
        self.min_trade_amount = float(os.getenv("MIN_TRADE_AMOUNT", "1"))
        self.max_price = float(os.getenv("MAX_PRICE", "0.80"))
        self.min_price = float(os.getenv("MIN_PRICE", "0.10"))
        self.max_slippage = float(os.getenv("MAX_SLIPPAGE", "0.10"))
        self.poll_interval = float(os.getenv("POLL_INTERVAL", "0.1"))
        self.skip_opposite_side = os.getenv("SKIP_OPPOSITE_SIDE", "true").lower() == "true"
        self.initial_balance = float(os.getenv("INITIAL_BALANCE", "1200.0"))

        # API endpoints
        self.clob_host = "https://clob.polymarket.com"
        self.data_api_host = "https://data-api.polymarket.com"
        self.chain_id = 137  # Polygon mainnet


class PolymarketClient:
    """Handles Polymarket API connections."""

    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[ClobClient] = None

    def connect(self) -> bool:
        """Initialize and verify connection to Polymarket."""
        logger.info("Connecting to Polymarket...")

        try:
            # Create CLOB client
            if self.config.funder_address:
                logger.info("Using proxy wallet (signature_type=1)")
                self.client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=1,
                    funder=self.config.funder_address,
                )
            else:
                logger.info("Using EOA wallet (signature_type=0)")
                self.client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=0,
                )

            # Set API credentials
            if self.config.api_key:
                api_creds = ApiCreds(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    api_passphrase=self.config.api_passphrase,
                )
                self.client.set_api_creds(api_creds)
                logger.info("API credentials set")

            # Verify connection
            result = self.client.get_ok()
            logger.info(f"Connection verified: {result}")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def get_balance(self) -> Optional[float]:
        """Get USDC balance."""
        if not self.client:
            return None
        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_info = self.client.get_balance_allowance(params)
            raw_balance = float(balance_info.get("balance", 0))
            return raw_balance / 1_000_000  # Convert to USDC
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """Get order book for a token."""
        if not self.client:
            return None
        try:
            return self.client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Failed to get order book: {e}")
            return None


class TradeMonitor:
    """Monitors target trader for new trades."""

    def __init__(self, config: Config):
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


class PaperTrader:
    """Simulates trades for dry run mode."""

    def __init__(self, initial_balance: float):
        self.usdc_balance = initial_balance
        self.positions: Dict[str, dict] = {}
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
                    "market": market_name,
                }
            else:
                self.positions[token_id]["shares"] += shares
                self.positions[token_id]["cost"] += size

            self.trades_executed += 1
            return True

        return False

    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value (simplified)."""
        # For now, just return balance + cost basis of positions
        position_value = sum(p["cost"] for p in self.positions.values())
        return self.usdc_balance + position_value


class CopyBot:
    """Main copy trading bot."""

    def __init__(self):
        self.config = Config()
        self.pm_client = PolymarketClient(self.config)
        self.monitor = TradeMonitor(self.config)
        self.paper_trader = PaperTrader(self.config.initial_balance) if self.config.dry_run else None

        # Stats
        self.start_time = None
        self.trades_detected = 0
        self.trades_copied = 0
        self.trades_skipped = 0
        self.poll_count = 0

    def print_banner(self):
        """Print startup banner."""
        mode = "DRY RUN (Paper Trading)" if self.config.dry_run else "LIVE TRADING"
        print("=" * 60)
        print("POLYMARKET COPY BOT v2")
        print("=" * 60)
        print(f"Mode: {mode}")
        print(f"Target: {self.config.target_wallet[:16]}...")
        print(f"Poll Interval: {self.config.poll_interval}s")
        print(f"Max Trade: ${self.config.max_trade_amount}")
        print(f"Price Range: {self.config.min_price:.0%} - {self.config.max_price:.0%}")
        print("=" * 60)

    async def test_connection(self) -> bool:
        """Test all connections."""
        logger.info("Testing connections...")

        # Test CLOB API
        if not self.pm_client.connect():
            logger.error("CLOB API connection failed")
            return False

        # Get balance
        balance = self.pm_client.get_balance()
        if balance is not None:
            logger.info(f"USDC Balance: ${balance:.2f}")

        # Test Data API
        async with aiohttp.ClientSession() as session:
            trades = await self.monitor.fetch_trades(session)
            if trades:
                logger.info(f"Data API OK - Found {len(trades)} recent trades from target")
            else:
                logger.warning("Data API returned no trades (target may be inactive)")

        return True

    async def process_trade(self, trade: dict):
        """Process a detected trade."""
        # Only process TRADE activities
        if trade.get("type", "").upper() != "TRADE":
            return

        market_name = trade.get("title", "Unknown")[:40]
        side = trade.get("side", "").upper()
        price = float(trade.get("price", 0))
        size = float(trade.get("usdcSize", 0))
        outcome = trade.get("outcome", "")

        logger.info("-" * 50)
        logger.info("NEW TRADE DETECTED")
        logger.info(f"Market: {market_name}")
        logger.info(f"Side: {side} {outcome} @ {price:.0%} | Amount: ${size:.2f}")

        self.trades_detected += 1

        # Price filter
        if price > self.config.max_price:
            logger.info(f"SKIP: Price {price:.0%} > max {self.config.max_price:.0%}")
            self.trades_skipped += 1
            return

        if price < self.config.min_price:
            logger.info(f"SKIP: Price {price:.0%} < min {self.config.min_price:.0%}")
            self.trades_skipped += 1
            return

        # Only copy BUY trades
        if side != "BUY":
            logger.info(f"SKIP: Not a BUY trade")
            self.trades_skipped += 1
            return

        # Calculate our trade size
        our_size = min(size, self.config.max_trade_amount)
        our_size = max(our_size, self.config.min_trade_amount)

        # Execute trade
        if self.config.dry_run and self.paper_trader:
            # Check slippage by getting current order book
            token_id = trade.get("asset", "")
            book = self.pm_client.get_order_book(token_id)

            current_price = price
            if book and book.asks:
                sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
                current_price = float(sorted_asks[0].price)

            slippage = abs(current_price - price) / price if price > 0 else 0
            logger.info(f"Slippage: {slippage:.1%} (target: ${price:.2f}, market: ${current_price:.2f})")

            if slippage > self.config.max_slippage:
                logger.info(f"SKIP: Slippage {slippage:.1%} > max {self.config.max_slippage:.0%}")
                self.trades_skipped += 1
                return

            # Paper trade
            success = self.paper_trader.execute_trade(
                token_id=token_id,
                market_name=market_name,
                side=side,
                size=our_size,
                price=current_price,
            )

            if success:
                logger.info(f"[PAPER] Executed: {side} ${our_size:.2f} @ {current_price:.2%}")
                logger.info(f"[PAPER] Balance: ${self.paper_trader.usdc_balance:.2f}")
                self.trades_copied += 1
            else:
                self.trades_skipped += 1
        else:
            # Live trading would go here
            logger.info("[LIVE] Trade execution not yet implemented")
            self.trades_skipped += 1

    def print_status(self):
        """Print current status."""
        runtime = (time.time() - self.start_time) / 3600 if self.start_time else 0

        print()
        print("=" * 50)
        print("STATUS")
        print("=" * 50)
        print(f"Runtime: {runtime:.2f} hours")
        print(f"Polls: {self.poll_count}")
        print(f"Trades Detected: {self.trades_detected}")
        print(f"Trades Copied: {self.trades_copied}")
        print(f"Trades Skipped: {self.trades_skipped}")

        if self.paper_trader:
            print(f"Paper Balance: ${self.paper_trader.usdc_balance:.2f}")
            print(f"Portfolio Value: ${self.paper_trader.get_portfolio_value():.2f}")
            print(f"Open Positions: {len(self.paper_trader.positions)}")
        print("=" * 50)

    async def run(self):
        """Main bot loop."""
        self.print_banner()

        # Test connections
        if not await self.test_connection():
            logger.error("Connection test failed. Exiting.")
            return

        logger.info("Starting trade monitor...")
        self.start_time = time.time()
        status_interval = int(30 / self.config.poll_interval)  # Print status every ~30 seconds

        async with aiohttp.ClientSession() as session:
            # Initial fetch to establish baseline
            initial_trades = await self.monitor.fetch_trades(session)
            self.monitor.filter_new_trades(initial_trades)
            logger.info("Baseline established. Watching for new trades...")

            while True:
                try:
                    trades = await self.monitor.fetch_trades(session)
                    new_trades = self.monitor.filter_new_trades(trades)

                    self.poll_count += 1

                    # Process new trades (oldest first)
                    for trade in reversed(new_trades):
                        await self.process_trade(trade)

                    # Periodic status
                    if self.poll_count % status_interval == 0:
                        logger.info(f"[SCAN] {self.poll_count} polls | Detected: {self.trades_detected} | Copied: {self.trades_copied}")

                    await asyncio.sleep(self.config.poll_interval)

                except KeyboardInterrupt:
                    logger.info("Shutting down...")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(1)

        self.print_status()


async def main():
    """Entry point."""
    bot = CopyBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
