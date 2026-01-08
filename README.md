# Polymarket Copy Bot v2

A trading bot that copies trades from successful Polymarket traders.

## Setup

1. Clone this repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python main.py`

## Configuration

| Setting | Description |
|---------|-------------|
| `DRY_RUN` | Set to `true` for paper trading, `false` for live |
| `TARGET_WALLET` | Wallet address of the trader to copy |
| `MAX_TRADE_AMOUNT` | Maximum USD per trade |
| `MAX_SLIPPAGE` | Maximum acceptable slippage (0.10 = 10%) |
| `SKIP_OPPOSITE_SIDE` | Only trade one side per market |

## License

MIT
