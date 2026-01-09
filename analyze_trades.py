import requests
import json

# Get target trader's recent trades
url = "https://data-api.polymarket.com/activity?user=0x63ce342161250d705dc0b16df89036c8e5f9ba9a&limit=100"
resp = requests.get(url)
data = resp.json()

print("=" * 60)
print("TARGET TRADER ANALYSIS (Blushing-Fine)")
print("=" * 60)

# Separate by outcome
up_trades = [t for t in data if t.get('outcome') == 'Up']
down_trades = [t for t in data if t.get('outcome') == 'Down']

print(f"\nTotal trades: {len(data)}")
print(f"UP trades: {len(up_trades)}")
print(f"DOWN trades: {len(down_trades)}")

# Calculate average prices
up_prices = [float(t.get('price', 0)) for t in up_trades]
down_prices = [float(t.get('price', 0)) for t in down_trades]

if up_prices:
    print(f"\nUP avg entry: {sum(up_prices)/len(up_prices):.0%}")
if down_prices:
    print(f"DOWN avg entry: {sum(down_prices)/len(down_prices):.0%}")

# Key insight - trader's entry prices
print("\n" + "=" * 60)
print("KEY INSIGHT: Entry Prices")
print("=" * 60)

# Group by market
markets = {}
for t in data:
    market = t.get('title', 'unknown')[:50]
    outcome = t.get('outcome', 'unknown')
    price = float(t.get('price', 0))
    size = float(t.get('usdcSize', 0))

    key = f"{market} - {outcome}"
    if key not in markets:
        markets[key] = {'prices': [], 'total_size': 0}
    markets[key]['prices'].append(price)
    markets[key]['total_size'] += size

print("\nTrader's positions by market:")
for key, data in sorted(markets.items(), key=lambda x: -x[1]['total_size'])[:15]:
    avg_price = sum(data['prices']) / len(data['prices'])
    print(f"  {key}")
    print(f"    Avg Entry: {avg_price:.0%} | Total: ${data['total_size']:.2f} | Trades: {len(data['prices'])}")

# Critical analysis
print("\n" + "=" * 60)
print("THE PROBLEM")
print("=" * 60)
print("""
The trader is buying BOTH UP and DOWN on the SAME markets!

Looking at 'Bitcoin Up or Down - January 8, 7:30PM-7:45PM ET':
- They buy UP @ 66%
- They ALSO buy DOWN @ 34-41%

This is a HEDGING strategy - they're market making or hedging.
They profit from the spread, not from direction.

When we copy, we only see individual trades, not the full strategy.
We end up with BOTH sides of the hedge, which cancels out!
""")
