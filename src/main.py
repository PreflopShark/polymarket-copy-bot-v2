"""Main entry point for Polymarket Copy Trading Bot."""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime

from .config import load_config
from .auth import create_clob_client, verify_client, initialize_browser_session
from .monitor import TradeMonitor
from .ws_monitor import WebSocketMonitor
from .executor import TradeExecutor
from .paper_trader import PaperTrader
from .redeemer import create_redeemer
from .session_logger import init_session_logger, get_session_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)

logger = logging.getLogger(__name__)


class CopyTradingBot:
    """Main bot orchestrator."""

    def __init__(self):
        self.config = None
        self.client = None
        self.monitor = None
        self.executor = None
        self.paper_trader = None
        self.redeemer = None
        self.session_logger = None
        self._shutdown_event = asyncio.Event()
        self._status_task = None
        self._redeem_task = None
        # When Cloudflare blocks order placement, pause order submissions for a while.
        self._trade_cooldown_until: float = 0.0

    async def initialize(self):
        """Initialize all bot components."""
        logger.info("=" * 60)
        logger.info("Polymarket Copy Trading Bot")
        logger.info("=" * 60)

        # Load configuration
        logger.info("Loading configuration...")
        self.config = load_config()

        # Initialize session logger
        self.session_logger = init_session_logger(self.config)

        # Display mode
        if self.config.dry_run:
            logger.info("")
            logger.info("*" * 60)
            logger.info("*  DRY RUN MODE - No real trades will be executed  *")
            logger.info("*" * 60)
            logger.info("")
            logger.info(f"Paper trading balance: ${self.config.initial_paper_balance:.2f}")
            self.paper_trader = PaperTrader(self.config.initial_paper_balance)
        else:
            logger.info("")
            logger.info("!" * 60)
            logger.info("!  LIVE MODE - Real trades will be executed!  !")
            logger.info("!" * 60)
            logger.info("")

        logger.info(f"Target trader: {self.config.target_trader_address}")
        logger.info(f"Copy ratio: {self.config.copy_ratio} ({self.config.copy_ratio * 100}%)")
        logger.info(f"Per-asset ratios: BTC={self.config.btc_copy_ratio*100:.0f}%, ETH={self.config.eth_copy_ratio*100:.0f}%, SOL={self.config.sol_copy_ratio*100:.0f}%")
        logger.info(f"Trade limits: ${self.config.min_trade_amount} - ${self.config.max_trade_amount}")
        logger.info(f"Poll interval: {self.config.poll_interval_seconds}s")
        if self.config.use_websocket:
            logger.info("Monitor mode: WebSocket (experimental)")
        else:
            logger.info("Monitor mode: Polling")

        if self.config.enable_browser_bypass:
            logger.info(
                "Cloudflare bypass: starting silent browser session "
                f"(headless={self.config.browser_headless})"
            )
            try:
                ok = initialize_browser_session(headless=self.config.browser_headless)
                if ok:
                    logger.info("Cloudflare bypass: browser cookies ready")
                else:
                    logger.warning(
                        "Cloudflare bypass: browser init failed; will fall back to CF_BM_COOKIE if provided"
                    )
            except Exception as e:
                logger.warning(
                    f"Cloudflare bypass: browser init errored ({type(e).__name__}); "
                    "will fall back to CF_BM_COOKIE if provided"
                )
        else:
            logger.info("Cloudflare bypass: using CF_BM_COOKIE from .env (if set)")

        # Create authenticated client (needed for order book data even in dry run)
        logger.info("")
        logger.info("Authenticating with Polymarket...")
        try:
            self.client = create_clob_client(self.config)
            if verify_client(self.client):
                logger.info("API connection verified")
            else:
                logger.warning("API verification failed - continuing anyway for monitoring")
        except Exception as e:
            logger.warning(f"Could not create CLOB client: {e}")
            logger.info("Continuing in monitor-only mode (no order book data)")
            self.client = None

        # Initialize components - choose monitor type based on config
        if self.config.use_websocket:
            self.monitor = WebSocketMonitor(self.config)
        else:
            self.monitor = TradeMonitor(self.config)
        self.executor = TradeExecutor(self.client, self.config, self.paper_trader)
        
        # Auto-redeemer for resolved positions
        if not self.config.dry_run and self.config.enable_auto_redeem:
            self.redeemer = create_redeemer()
            if self.redeemer:
                logger.info("Auto-redeem enabled for resolved positions")
        elif not self.config.dry_run and not self.config.enable_auto_redeem:
            logger.info("Auto-redeem disabled (ENABLE_AUTO_REDEEM=false)")

        logger.info("")
        logger.info("Bot initialized successfully")

    async def on_trade_detected(self, activity: dict):
        """
        Callback when a new trade is detected.

        Args:
            activity: The activity data from the monitor.
        """
        # Handle different activity types
        activity_type = activity.get("type", "").upper()
        
        # Handle REDEEM events - resolve our paper positions
        if activity_type == "REDEEM":
            if self.paper_trader:
                condition_id = activity.get("conditionId", "")
                market_name = activity.get("title", "")
                usdc_redeemed = activity.get("usdcSize", 0)
                
                if usdc_redeemed > 0:
                    logger.info("")
                    logger.info("=" * 50)
                    logger.info("🏆 TARGET REDEEMED WINNING POSITION")
                    logger.info(f"Market: {market_name[:50]}")
                    logger.info(f"Amount: ${usdc_redeemed:.2f}")
                    logger.info("=" * 50)
                    
                    # Redeem our matching positions
                    redeemed = self.paper_trader.redeem_position(
                        condition_id=condition_id,
                        market_name=market_name,
                        usdc_redeemed=usdc_redeemed
                    )
                    
                    if redeemed > 0:
                        logger.info(f"Our redemption: ${redeemed:.2f}")
                    
                    self.paper_trader.print_status()
                    logger.info("")
            return
        
        if activity_type != "TRADE":
            return  # Silently skip TRANSFER, etc.

        # Signal filter: only copy trades above threshold
        trade_amount = float(activity.get('usdcSize', 0))
        min_target = self.config.min_target_trade
        if min_target > 0 and trade_amount < min_target:
            logger.debug(f"Skipping small trade ${trade_amount:.2f} < ${min_target:.2f} threshold")
            return

        logger.info("")
        logger.info("-" * 50)
        logger.info("NEW TRADE DETECTED FROM TARGET")
        logger.info(f"Market: {activity.get('title', 'unknown')[:50]}")
        logger.info(f"Side: {activity.get('side')} | Amount: ${activity.get('usdcSize', 0):.2f}")
        logger.info("-" * 50)

        now = time.time()
        if now < self._trade_cooldown_until:
            remaining = int(self._trade_cooldown_until - now)
            logger.warning(f"Trade execution paused due to Cloudflare block (cooldown {remaining}s remaining)")
            return

        result = await self.executor.copy_trade(activity)

        if result:
            # Check if trade was actually executed vs skipped
            status = result.get("status", "")
            if status == "skipped":
                reason = result.get("reason", "unknown")
                logger.warning(f"Trade SKIPPED: {reason}")
            elif status == "cancelled":
                logger.warning(f"Trade cancelled: {result.get('reason', 'stale order')}")
            elif status == "blocked":
                # Back off to avoid repeated 403s and potential IP/session hard blocks.
                cooldown_seconds = 15 * 60
                self._trade_cooldown_until = time.time() + cooldown_seconds
                logger.error(
                    "Order placement is being blocked by Cloudflare (HTTP 403). "
                    f"Pausing new order submissions for {cooldown_seconds}s. "
                    "Reconnect VPN / refresh cookies, then restart or wait for cooldown."
                )
            elif status == "contrarian_trade":
                original_side = result.get("original_side", "BUY")
                logger.info(f"[CONTRARIAN] Faded {original_side} -> took OPPOSITE side!")
            elif status in ("matched", "paper_trade", "dry_run") or result.get("success"):
                logger.info("Trade copied successfully!")
            else:
                logger.info(f"Trade result: {status or 'submitted'}")
        else:
            logger.debug("Trade not copied (filtered out)")

        # Print paper trading status after each trade
        if self.paper_trader:
            self.paper_trader.print_status()

        logger.info("-" * 50)
        logger.info("")

    async def periodic_status(self):
        """Print status periodically."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(300)  # Every 5 minutes
            if self.paper_trader:
                logger.info("")
                self.paper_trader.print_status()

    async def periodic_redeem(self):
        """Check for and redeem resolved positions periodically."""
        # Wait a bit before first check
        await asyncio.sleep(60)
        
        while not self._shutdown_event.is_set():
            try:
                if self.redeemer:
                    logger.info("Checking for redeemable positions...")
                    result = self.redeemer.redeem_all()
                    if result['redeemed'] > 0:
                        logger.info(f"💰 Auto-redeemed ${result['total_value']:.2f}")
            except Exception as e:
                logger.error(f"Error in auto-redeem: {e}")
            
            # Check every 2 minutes
            await asyncio.sleep(120)

    async def run(self):
        """Run the bot main loop."""
        await self.initialize()

        logger.info("")
        logger.info("Starting trade monitoring...")
        logger.info(f"Watching: {self.config.target_trader_address}")
        logger.info("Press Ctrl+C to stop")
        logger.info("")

        # Start periodic status updates in dry run mode
        if self.config.dry_run and self.paper_trader:
            self._status_task = asyncio.create_task(self.periodic_status())
        
        # Start auto-redeem in live mode
        if not self.config.dry_run and self.config.enable_auto_redeem and self.redeemer:
            self._redeem_task = asyncio.create_task(self.periodic_redeem())

        try:
            await self.monitor.start_monitoring(self.on_trade_detected)
        except asyncio.CancelledError:
            logger.info("Bot shutting down...")
        finally:
            if self._status_task:
                self._status_task.cancel()
            if self._redeem_task:
                self._redeem_task.cancel()

            # Save paper trading results
            if self.paper_trader:
                self.paper_trader.print_status()
                filename = f"paper_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                self.paper_trader.save_to_file(filename)

    def shutdown(self):
        """Initiate graceful shutdown."""
        logger.info("Shutdown requested...")

        # Log session summary before stopping (wrap in try/except for safety)
        try:
            if self.session_logger:
                self.session_logger.log_session_end(self.client)
        except Exception as e:
            logger.error(f"Error logging session end: {e}")

        if self.monitor:
            # WebSocketMonitor.stop() is async, TradeMonitor.stop() is sync
            if isinstance(self.monitor, WebSocketMonitor):
                # Try to create task if event loop is running, otherwise just set running flag
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.monitor.stop())
                except RuntimeError:
                    # No running event loop - just set the internal flag
                    self.monitor._running = False
            else:
                self.monitor.stop()
        self._shutdown_event.set()


def main():
    """Main entry point."""
    bot = CopyTradingBot()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        bot.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    # SIGTERM is not available on Windows
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    # Setup global exception handler for uncaught async exceptions
    def handle_exception(loop, context):
        msg = context.get("exception", context["message"])
        logger.error(f"Unhandled async exception: {msg}")
        # Don't shutdown on every exception, just log it

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(handle_exception)
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        try:
            loop.close()
        except Exception:
            pass

    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
