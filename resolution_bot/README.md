# Resolution Friction Farm Bot

## Strategy Overview

This bot exploits the **resolution friction** in prediction markets - the time delay between when an event outcome becomes known and when the market officially settles.

### The Opportunity

When a market's outcome becomes effectively certain:
1. **Sports**: Game ends, final score known
2. **Crypto prices**: Time window closes, price determined
3. **Events**: News breaks, outcome confirmed

But official Polymarket resolution may take minutes to hours. During this window:
- Winning shares trade at 95-99 cents (not $1)
- Sellers accept discount for immediate liquidity
- Market makers still offer spreads

### Profit Mechanism

```
Buy winning shares @ $0.98
Wait for resolution
Receive $1.00 per share
Profit = $0.02/share (2% ROI, annualized can be massive)
```

### Risk Factors

1. **Oracle error**: We determine wrong outcome
2. **Resolution disputes**: Market contested
3. **Timing risk**: Long wait for settlement
4. **Execution risk**: Can't buy at target price

## Architecture

```
resolution_bot/
├── config.py       # Configuration and parameters
├── oracle.py       # Multi-source resolution oracle
├── main.py         # Main bot logic
└── README.md       # This file
```

### Oracle System

The `EffectivelyResolvedOracle` aggregates multiple data sources:

1. **CryptoPriceOracle**: Binance, CoinGecko for BTC/ETH/SOL prices
2. **SportsOracle**: ESPN API for game results
3. **NewsOracle**: Market consensus as fallback

Each oracle returns:
- `ResolutionState`: UNKNOWN, LIKELY, EFFECTIVELY_RESOLVED, OFFICIALLY_RESOLVED
- `winning_outcome`: Which outcome won
- `confidence`: 0.0 to 1.0
- `reasoning`: Why we believe this

## Configuration

Set in `.env`:

```env
# Strategy parameters
RES_MIN_PROFIT_BPS=50      # Minimum 0.5% profit
RES_MAX_PRICE=0.995        # Max 99.5 cents per share
RES_MIN_PRICE=0.90         # Avoid weird markets
RES_MAX_POSITION=100       # Max $100 per position

# Oracle settings
RES_POLL_INTERVAL=30       # Check every 30s
RES_CONFIDENCE=0.95        # 95% confidence required

# Mode
RES_DRY_RUN=true          # Paper trading mode
```

## Usage

```bash
# From project root
python -m resolution_bot.main
```

## Extending the Oracle

To add a new data source:

```python
class MyOracle(BaseOracle):
    def can_handle(self, market: Dict) -> bool:
        # Return True if this oracle handles this market type
        return "my_keyword" in market.get("title", "").lower()
    
    async def check_resolution(self, market: Dict) -> Optional[OracleResult]:
        # Check external data source
        # Return OracleResult with resolution state
        pass
```

Then add to `EffectivelyResolvedOracle.oracles` list.

## Future Improvements

1. **More data sources**: Add Reuters, AP, official sports APIs
2. **Historical analysis**: Track resolution timing patterns
3. **Position management**: Auto-exit on disputes
4. **Multi-market**: Batch orders across opportunities
5. **MEV protection**: Private mempool submission
