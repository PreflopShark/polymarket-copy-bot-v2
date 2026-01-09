"""
Sports Resolution Friction Bot - MVP

RULES:
1. Only sports markets (Team A vs Team B)
2. Only trade when game_status == FINAL
3. Only BUY winners
4. Price must be <= 0.97
"""
import asyncio
import logging
import signal
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List
from dataclasses import dataclass, field

from resolution_bot import config
from resolution_bot.sports_oracle import SportsOracle

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@dataclass
class Position:
    market_id: str
    market_title: str
    token_id: str
    outcome: str
    shares: float
    entry_price: float
    entry_time: datetime
    
    @property
    def cost(self) -> float:
        return self.shares * self.entry_price
    
    @property
    def expected_profit(self) -> float:
        return self.shares * (1.0 - self.entry_price)


@dataclass 
class BotStats:
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    markets_checked: int = 0
    games_final: int = 0
    price_ok: int = 0
    trades_executed: int = 0
    total_invested: float = 0.0
    positions: List[Position] = field(default_factory=list)
    traded_markets: set = field(default_factory=set)


class SportsResolutionBot:
    GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        self.oracle = SportsOracle()
        self.stats = BotStats()
        self.running = False
    
    async def fetch_markets(self) -> List[Dict[str, Any]]:
        """Fetch sports markets from Polymarket"""
        markets = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.GAMMA_API}/markets",
                    params={"active": "true", "closed": "false", "limit": 100},
                    timeout=10.0
                )
                if resp.status_code == 200:
                    all_markets = resp.json()
                    for m in all_markets:
                        if self.oracle.is_sports_market(m):
                            markets.append(m)
                    logger.info(f"Found {len(markets)} sports markets (of {len(all_markets)} total)")
        except Exception as e:
            logger.error(f"Fetch error: {e}")
        return markets
    
    async def check_and_trade(self, market: Dict[str, Any]) -> bool:
        """Check market and trade if conditions met"""
        market_id = market.get("condition_id", market.get("conditionId", ""))
        
        if market_id in self.stats.traded_markets:
            return False
        
        result = await self.oracle.check_market(market)
        if not result:
            return False
        
        self.stats.markets_checked += 1
        
        # RULE: game_status == FINAL
        if not result.game_final:
            logger.debug(f"Not final: {result.reasoning}")
            return False
        
        self.stats.games_final += 1
        
        if not result.winner or not result.winner_price:
            logger.debug(f"No winner/price: {result.reasoning}")
            return False
        
        # RULE: Price <= 0.97
        if result.winner_price > config.MAX_PRICE:
            logger.info(f"Price too high: {result.winner} @ ${result.winner_price:.4f} > ${config.MAX_PRICE}")
            return False
        
        self.stats.price_ok += 1
        
        # Calculate trade
        profit_margin = 1.0 - result.winner_price
        position_cost = config.MAX_POSITION_SIZE
        shares = position_cost / result.winner_price
        expected_profit = shares * profit_margin
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🏆 GAME FINAL - BUY WINNER")
        logger.info("=" * 60)
        logger.info(f"Market: {result.market_title}")
        logger.info(f"Winner: {result.winner}")
        logger.info(f"Price: ${result.winner_price:.4f}")
        logger.info(f"Margin: {profit_margin * 100:.1f}%")
        logger.info(f"Buy: {shares:.2f} shares for ${position_cost:.2f}")
        logger.info(f"Expected profit: +${expected_profit:.2f}")
        logger.info("=" * 60)
        
        if config.DRY_RUN:
            logger.info("[PAPER] Trade simulated")
            self.stats.positions.append(Position(
                market_id=market_id,
                market_title=result.market_title,
                token_id=result.winner_token_id or "",
                outcome=result.winner,
                shares=shares,
                entry_price=result.winner_price,
                entry_time=datetime.now(timezone.utc),
            ))
            self.stats.traded_markets.add(market_id)
            self.stats.trades_executed += 1
            self.stats.total_invested += position_cost
            return True
        
        logger.warning("Live trading not implemented")
        return False
    
    def print_status(self):
        runtime = (datetime.now(timezone.utc) - self.stats.start_time).total_seconds() / 60
        logger.info("")
        logger.info("=" * 50)
        logger.info("📊 STATUS")
        logger.info(f"Runtime: {runtime:.1f} min")
        logger.info(f"Markets checked: {self.stats.markets_checked}")
        logger.info(f"Games FINAL: {self.stats.games_final}")
        logger.info(f"Price <= $0.97: {self.stats.price_ok}")
        logger.info(f"Trades: {self.stats.trades_executed}")
        logger.info(f"Invested: ${self.stats.total_invested:.2f}")
        if self.stats.positions:
            profit = sum(p.expected_profit for p in self.stats.positions)
            logger.info(f"Expected profit: +${profit:.2f}")
        logger.info("=" * 50)
    
    async def run(self):
        logger.info("=" * 60)
        logger.info("Sports Resolution Bot - MVP")
        logger.info("=" * 60)
        logger.info("")
        logger.info("RULES:")
        logger.info("  1. Sports markets only (Team A vs Team B)")
        logger.info("  2. game_status == FINAL")
        logger.info("  3. BUY winner")
        logger.info(f"  4. Price <= ${config.MAX_PRICE:.2f}")
        logger.info("")
        
        if config.DRY_RUN:
            logger.info("[PAPER TRADING MODE]")
        
        logger.info(f"Max position: ${config.MAX_POSITION_SIZE}")
        logger.info(f"Poll interval: {config.POLL_INTERVAL}s")
        logger.info("")
        logger.info("Scanning for finished games...")
        logger.info("")
        
        self.running = True
        iteration = 0
        
        while self.running:
            try:
                markets = await self.fetch_markets()
                
                for m in markets:
                    await self.check_and_trade(m)
                
                iteration += 1
                if iteration % 6 == 0:
                    self.print_status()
                
                await asyncio.sleep(config.POLL_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)
        
        self.print_status()
        logger.info("Stopped")
    
    def stop(self):
        self.running = False


async def main():
    bot = SportsResolutionBot()
    signal.signal(signal.SIGINT, lambda s, f: bot.stop())
    signal.signal(signal.SIGTERM, lambda s, f: bot.stop())
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
