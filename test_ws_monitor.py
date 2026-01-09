"""Test script for WebSocket monitor module.

Run this to test the WebSocket monitor independently without affecting the main bot.
Usage: python test_ws_monitor.py
"""

import asyncio
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


async def main():
    """Test the WebSocket monitor."""
    from src.config import load_config
    from src.ws_monitor import WebSocketMonitor, HybridMonitor

    logger.info("=" * 60)
    logger.info("WebSocket Monitor Test")
    logger.info("=" * 60)

    config = load_config()
    logger.info(f"Target trader: {config.target_trader_address}")

    # Track stats
    trade_count = 0
    start_time = asyncio.get_event_loop().time()

    async def on_trade(trade: dict):
        nonlocal trade_count
        trade_count += 1

        print(f"\n{'=' * 60}")
        print(f"TRADE #{trade_count} DETECTED!")
        print(f"Market: {trade.get('title', 'unknown')[:50]}")
        print(f"Type: {trade.get('type', 'unknown')}")
        print(f"Side: {trade.get('side')} | Amount: ${trade.get('usdcSize', 0):.2f}")
        print(f"Price: {trade.get('price', 0):.2%}")
        print(f"Outcome: {trade.get('outcome', 'unknown')}")
        print(f"TX: {trade.get('transactionHash', 'unknown')[:20]}...")
        print(f"{'=' * 60}\n")

    # Choose which monitor to test
    use_hybrid = "--hybrid" in sys.argv

    if use_hybrid:
        logger.info("Using HybridMonitor (WebSocket + polling fallback)")
        monitor = HybridMonitor(config, use_websocket=True)
    else:
        logger.info("Using WebSocketMonitor directly")
        monitor = WebSocketMonitor(config)

    logger.info("Press Ctrl+C to stop\n")

    try:
        await monitor.start_monitoring(on_trade)
    except KeyboardInterrupt:
        logger.info("\nStopping test...")
    finally:
        if hasattr(monitor, 'stop'):
            if asyncio.iscoroutinefunction(monitor.stop):
                await monitor.stop()
            else:
                monitor.stop()

        elapsed = asyncio.get_event_loop().time() - start_time
        logger.info(f"\nTest complete. Detected {trade_count} trades in {elapsed:.1f}s")

        if hasattr(monitor, 'get_status'):
            status = monitor.get_status()
            logger.info(f"Final status: {status}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
