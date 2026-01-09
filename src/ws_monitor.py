"""WebSocket-based trade monitoring service.

This module provides real-time trade detection using Polymarket's WebSocket API.
It can be used as an alternative to the polling-based monitor.py.

Strategy: Subscribe to Target's Active Markets
1. Fetch target trader's current positions via REST API
2. Subscribe to WebSocket channels for those specific markets
3. When we see trade activity in those markets, immediately check target's activity
4. Periodically refresh subscriptions as target enters/exits markets
5. Fall back to polling if WebSocket unavailable
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, List, Optional, Set

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .config import Config

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class WSConfig:
    """WebSocket-specific configuration."""
    # WebSocket endpoints
    clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    # Connection settings
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    reconnect_multiplier: float = 2.0

    # Monitoring settings
    max_markets_to_watch: int = 50
    position_refresh_interval: float = 60.0  # Refresh target positions every 60s
    instant_check_cooldown: float = 0.1  # Min time between instant checks (100ms)


@dataclass
class MarketSubscription:
    """Tracks a subscribed market."""
    token_id: str
    condition_id: str
    title: str
    outcome: str
    subscribed_at: float = field(default_factory=time.time)
    last_activity: float = 0.0


class WebSocketMonitor:
    """
    Real-time trade monitor using Polymarket WebSocket.

    Subscribes to the target trader's active markets for instant trade detection.
    When activity occurs in a subscribed market, immediately checks if target traded.
    """

    def __init__(self, config: Config, ws_config: Optional[WSConfig] = None):
        self.config = config
        self.ws_config = ws_config or WSConfig()

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_delay = self.ws_config.reconnect_delay

        # Trade tracking
        self.last_trade_id: Optional[str] = None
        self.last_trade_timestamp: Optional[int] = None
        self._seen_trade_ids: Set[str] = set()
        self._max_seen_ids = 1000

        # Market subscriptions (token_id -> MarketSubscription)
        self._subscriptions: Dict[str, MarketSubscription] = {}
        self._target_positions: List[dict] = []
        self._last_position_refresh = 0.0

        # Activity tracking
        self._last_instant_check = 0.0
        self._pending_check = False
        self._triggered_by_ws = False  # Track if check was triggered by WS

        # Callbacks
        self._on_trade: Optional[Callable[[dict], Awaitable[None]]] = None

        # HTTP session
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Stats
        self._ws_triggers = 0
        self._poll_triggers = 0
        self._trades_detected = 0

    async def _fetch_target_positions(self) -> List[dict]:
        """
        Fetch the target trader's current positions.

        Returns:
            List of position dictionaries with token IDs and market info
        """
        if not self._http_session:
            return []

        url = f"{self.config.data_api_host}/positions"
        params = {
            "user": self.config.target_trader_address,
            "sizeThreshold": 0.01,  # Only positions with meaningful size
        }

        try:
            async with self._http_session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    positions = await response.json()
                    if isinstance(positions, list):
                        logger.info(f"Target has {len(positions)} active positions")
                        return positions
                else:
                    logger.warning(f"Positions API returned status {response.status}")
        except Exception as e:
            logger.error(f"Error fetching target positions: {e}")

        return []

    async def _fetch_active_markets(self) -> List[dict]:
        """
        Fetch active crypto markets (BTC, ETH, SOL up/down).

        These are the high-frequency markets the target likely trades.
        """
        if not self._http_session:
            return []

        markets = []

        # Fetch active markets from gamma API
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "closed": "false",
            "active": "true",
            "limit": 50,
        }

        try:
            async with self._http_session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    all_markets = await response.json()
                    # Filter for crypto up/down markets
                    for m in all_markets:
                        question = m.get("question", "").lower()
                        if any(crypto in question for crypto in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]):
                            if "up or down" in question:
                                markets.append(m)
        except Exception as e:
            logger.debug(f"Error fetching active markets: {e}")

        return markets

    async def _update_subscriptions(self):
        """
        Update WebSocket subscriptions based on target's positions and active markets.
        """
        if self.state != ConnectionState.CONNECTED:
            return

        # Get target's current positions
        positions = await self._fetch_target_positions()
        self._target_positions = positions

        # Also get active crypto markets (target likely to trade these)
        active_markets = await self._fetch_active_markets()

        # Build set of token IDs to subscribe to
        tokens_to_subscribe: Dict[str, MarketSubscription] = {}

        # Add tokens from target's positions
        for pos in positions[:self.ws_config.max_markets_to_watch // 2]:
            asset = pos.get("asset")
            if asset:
                tokens_to_subscribe[asset] = MarketSubscription(
                    token_id=asset,
                    condition_id=pos.get("conditionId", ""),
                    title=pos.get("title", "")[:40],
                    outcome=pos.get("outcome", ""),
                )

        # Add tokens from active crypto markets
        for market in active_markets[:self.ws_config.max_markets_to_watch // 2]:
            tokens = market.get("clobTokenIds", [])
            for token in tokens:
                if token and token not in tokens_to_subscribe:
                    tokens_to_subscribe[token] = MarketSubscription(
                        token_id=token,
                        condition_id=market.get("conditionId", ""),
                        title=market.get("question", "")[:40],
                        outcome="",
                    )

        # Unsubscribe from markets we no longer need
        current_tokens = set(self._subscriptions.keys())
        new_tokens = set(tokens_to_subscribe.keys())

        to_unsubscribe = current_tokens - new_tokens
        to_subscribe = new_tokens - current_tokens

        for token_id in to_unsubscribe:
            await self._unsubscribe_market(token_id)

        for token_id in to_subscribe:
            sub = tokens_to_subscribe[token_id]
            if await self._subscribe_market(token_id):
                self._subscriptions[token_id] = sub

        if to_subscribe or to_unsubscribe:
            logger.info(f"Subscriptions updated: +{len(to_subscribe)} -{len(to_unsubscribe)} = {len(self._subscriptions)} markets")

        self._last_position_refresh = time.time()

    async def _connect(self) -> bool:
        """Establish WebSocket connection."""
        if self.state == ConnectionState.CONNECTED:
            return True

        self.state = ConnectionState.CONNECTING
        logger.info(f"Connecting to WebSocket: {self.ws_config.clob_ws_url}")

        try:
            self._ws = await websockets.connect(
                self.ws_config.clob_ws_url,
                ping_interval=self.ws_config.ping_interval,
                ping_timeout=self.ws_config.ping_timeout,
            )
            self.state = ConnectionState.CONNECTED
            self._reconnect_delay = self.ws_config.reconnect_delay
            logger.info("WebSocket connected successfully")
            return True

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.state = ConnectionState.DISCONNECTED
            return False

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        self.state = ConnectionState.RECONNECTING

        while self._running and self.state != ConnectionState.CONNECTED:
            logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
            await asyncio.sleep(self._reconnect_delay)

            if await self._connect():
                await self._update_subscriptions()
                break

            self._reconnect_delay = min(
                self._reconnect_delay * self.ws_config.reconnect_multiplier,
                self.ws_config.max_reconnect_delay
            )

    async def _subscribe_market(self, token_id: str) -> bool:
        """Subscribe to a market's WebSocket channel."""
        if not self._ws or self.state != ConnectionState.CONNECTED:
            return False

        try:
            subscribe_msg = {
                "type": "subscribe",
                "channel": "market",
                "markets": [token_id],
            }
            await self._ws.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to market: {token_id[:16]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            return False

    async def _unsubscribe_market(self, token_id: str) -> bool:
        """Unsubscribe from a market's WebSocket channel."""
        if not self._ws or self.state != ConnectionState.CONNECTED:
            return False

        try:
            unsubscribe_msg = {
                "type": "unsubscribe",
                "channel": "market",
                "markets": [token_id],
            }
            await self._ws.send(json.dumps(unsubscribe_msg))
            self._subscriptions.pop(token_id, None)
            return True

        except Exception as e:
            logger.error(f"Failed to unsubscribe: {e}")
            return False

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "last_trade_price":
                # Trade happened in a market we're watching!
                asset_id = data.get("asset_id", "")
                if asset_id in self._subscriptions:
                    self._subscriptions[asset_id].last_activity = time.time()
                    await self._trigger_instant_check()

            elif msg_type == "price_change":
                # Price moved - might indicate incoming trade
                asset_id = data.get("asset_id", "")
                if asset_id in self._subscriptions:
                    await self._trigger_instant_check()

            elif msg_type == "book":
                # Order book update - less urgent but could be relevant
                pass

            elif msg_type == "error":
                logger.error(f"WebSocket error: {data.get('message', data)}")

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _trigger_instant_check(self):
        """
        Trigger an instant check of target's activity.
        Rate-limited to prevent API spam.
        """
        now = time.time()
        if now - self._last_instant_check < self.ws_config.instant_check_cooldown:
            return

        self._last_instant_check = now
        self._pending_check = True
        self._triggered_by_ws = True
        self._ws_triggers += 1

    async def _check_target_activity(self) -> List[dict]:
        """Check target trader's recent activity via REST API."""
        if not self._http_session:
            return []

        url = f"{self.config.data_api_host}/activity"
        params = {
            "user": self.config.target_trader_address,
            "limit": 5,
        }

        try:
            async with self._http_session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    trades = await response.json()
                    return self._filter_new_trades(trades if isinstance(trades, list) else [])
        except Exception as e:
            logger.error(f"Error checking target activity: {e}")

        return []

    def _get_trade_id(self, trade: dict) -> str:
        """Get unique identifier for a trade."""
        return trade.get("transactionHash") or f"{trade.get('timestamp')}_{trade.get('asset')}"

    def _filter_new_trades(self, trades: List[dict]) -> List[dict]:
        """Filter out trades we've already seen."""
        if not trades:
            return []

        # First run - establish baseline
        if self.last_trade_id is None:
            if trades:
                self.last_trade_id = self._get_trade_id(trades[0])
                self.last_trade_timestamp = trades[0].get("timestamp")
                self._seen_trade_ids.add(self.last_trade_id)
                logger.info(f"Baseline: {trades[0].get('title', 'unknown')[:40]}")
            return []

        new_trades = []
        for trade in trades:
            trade_id = self._get_trade_id(trade)

            if trade_id in self._seen_trade_ids:
                continue

            if trade_id == self.last_trade_id:
                break

            new_trades.append(trade)
            self._seen_trade_ids.add(trade_id)

            # Limit memory
            if len(self._seen_trade_ids) > self._max_seen_ids:
                oldest = list(self._seen_trade_ids)[:self._max_seen_ids // 2]
                self._seen_trade_ids = set(list(self._seen_trade_ids)[self._max_seen_ids // 2:])

        if new_trades:
            self.last_trade_id = self._get_trade_id(new_trades[0])
            self.last_trade_timestamp = new_trades[0].get("timestamp")
            self._trades_detected += len(new_trades)

        return new_trades

    async def _message_loop(self):
        """Main loop for receiving WebSocket messages."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=self.ws_config.ping_interval + 5
                )
                await self._handle_message(message)

            except asyncio.TimeoutError:
                pass  # Normal timeout, connection still alive

            except ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                self.state = ConnectionState.DISCONNECTED
                if self._running:
                    await self._reconnect()
                break

            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
                self.state = ConnectionState.DISCONNECTED
                if self._running:
                    await self._reconnect()
                break

    async def _activity_check_loop(self):
        """
        Loop that processes pending activity checks.
        Triggered by WebSocket events or polling fallback.
        """
        while self._running:
            try:
                if self._pending_check:
                    self._pending_check = False
                    trigger_type = "WS" if self._triggered_by_ws else "poll"
                    self._triggered_by_ws = False

                    new_trades = await self._check_target_activity()

                    for trade in reversed(new_trades):
                        logger.info(f"Trade detected ({trigger_type}): {trade.get('title', '')[:30]}")
                        if self._on_trade:
                            try:
                                await self._on_trade(trade)
                            except Exception as e:
                                logger.error(f"Error processing trade: {e}")

                await asyncio.sleep(0.02)  # 20ms loop

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Activity loop error: {e}")
                await asyncio.sleep(1.0)

    async def _polling_loop(self):
        """
        Polling loop - runs continuously as backup.
        Also refreshes subscriptions periodically.
        """
        poll_interval = self.config.poll_interval_seconds

        while self._running:
            try:
                now = time.time()

                # Refresh subscriptions periodically
                if now - self._last_position_refresh > self.ws_config.position_refresh_interval:
                    if self.state == ConnectionState.CONNECTED:
                        await self._update_subscriptions()

                # Polling fallback - always poll but less frequently when WS is working
                if self.state == ConnectionState.CONNECTED:
                    # WS connected - poll less frequently as backup
                    await asyncio.sleep(poll_interval * 2)
                else:
                    # WS not connected - aggressive polling
                    self._pending_check = True
                    self._poll_triggers += 1
                    await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling loop error: {e}")
                await asyncio.sleep(1.0)

    async def start_monitoring(self, on_trade: Callable[[dict], Awaitable[None]]):
        """Start the WebSocket monitor."""
        self._running = True
        self._on_trade = on_trade

        logger.info(f"Starting WebSocket monitor for {self.config.target_trader_address}")
        logger.info("Strategy: Subscribe to target's active markets")

        self._http_session = aiohttp.ClientSession()

        try:
            # Establish baseline
            initial_trades = await self._check_target_activity()
            self._filter_new_trades(initial_trades)
            logger.info("Baseline established")

            # Connect and subscribe
            if await self._connect():
                await self._update_subscriptions()
                logger.info(f"Watching {len(self._subscriptions)} markets via WebSocket")

                # Run all loops concurrently
                await asyncio.gather(
                    self._message_loop(),
                    self._activity_check_loop(),
                    self._polling_loop(),
                )
            else:
                logger.warning("WebSocket unavailable, using polling only")
                await asyncio.gather(
                    self._activity_check_loop(),
                    self._polling_loop(),
                )

        except asyncio.CancelledError:
            logger.info("Monitor cancelled")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the monitor and clean up."""
        self._running = False
        logger.info("Stopping WebSocket monitor...")

        # Log stats
        logger.info(f"Stats: {self._ws_triggers} WS triggers, {self._poll_triggers} poll triggers, {self._trades_detected} trades")

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http_session:
            await self._http_session.close()
            self._http_session = None

        self.state = ConnectionState.DISCONNECTED
        logger.info("WebSocket monitor stopped")

    def get_status(self) -> dict:
        """Get current monitor status."""
        return {
            "state": self.state.value,
            "subscribed_markets": len(self._subscriptions),
            "target_positions": len(self._target_positions),
            "ws_triggers": self._ws_triggers,
            "poll_triggers": self._poll_triggers,
            "trades_detected": self._trades_detected,
        }


# Standalone test
async def test_ws_monitor():
    """Test the WebSocket monitor."""
    from .config import load_config

    config = load_config()
    monitor = WebSocketMonitor(config)

    async def on_trade(trade: dict):
        print(f"\n{'='*60}")
        print(f"TRADE: {trade.get('title', 'unknown')[:40]}")
        print(f"Side: {trade.get('side')} | ${trade.get('usdcSize', 0):.2f}")
        print(f"{'='*60}\n")

    try:
        await monitor.start_monitoring(on_trade)
    except KeyboardInterrupt:
        pass
    finally:
        await monitor.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(test_ws_monitor())
