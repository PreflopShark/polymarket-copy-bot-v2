"""Performance summary - compare our positions vs target's."""
import requests
from collections import defaultdict

proxy = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'
target = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

# Get our positions
our_positions = requests.get(f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0', timeout=10).json()

# Get our recent activity
our_activity = requests.get(f'https://data-api.polymarket.com/activity?user={proxy}&limit=500', timeout=10).json()
our_trades = [a for a in our_activity if a.get('type') == 'TRADE']

# Calculate totals
total_value = sum(float(p.get('currentValue', 0) or 0) for p in our_positions)
total_cost = sum(float(p.get('size', 0) or 0) * float(p.get('avgPrice', 0) or 0) for p in our_positions)
total_bought = sum(float(t.get('usdcSize', 0)) for t in our_trades if t.get('side') == 'BUY')
total_sold = sum(float(t.get('usdcSize', 0)) for t in our_trades if t.get('side') == 'SELL')

print("=" * 60)
print("           PERFORMANCE SUMMARY")
print("=" * 60)
print()

print("PORTFOLIO")
print("-" * 40)
print(f"  Position Value:     ${total_value:.2f}")
print(f"  Position Cost:      ${total_cost:.2f}")
print(f"  Unrealized P&L:     ${total_value - total_cost:+.2f}")
print(f"  Open Positions:     {len([p for p in our_positions if float(p.get('size', 0) or 0) > 0])}")
print()

print("TRADING ACTIVITY")
print("-" * 40)
print(f"  Total Trades:       {len(our_trades)}")
print(f"  Total Bought:       ${total_bought:.2f}")
print(f"  Total Sold:         ${total_sold:.2f}")
print(f"  Net Deployed:       ${total_bought - total_sold:.2f}")
print()

# Group positions by market
print("POSITIONS BY MARKET")
print("-" * 60)

markets = defaultdict(lambda: {'up': 0, 'down': 0, 'up_value': 0, 'down_value': 0, 'title': ''})
for p in our_positions:
    cond = p.get('conditionId', '')
    outcome = p.get('outcome', '')
    size = float(p.get('size', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    cost = size * float(p.get('avgPrice', 0) or 0)
    
    if size < 0.01:
        continue
    
    if 'Up' in outcome or 'Yes' in outcome:
        markets[cond]['up'] = cost
        markets[cond]['up_value'] = value
    else:
        markets[cond]['down'] = cost
        markets[cond]['down_value'] = value
    markets[cond]['title'] = p.get('title', '')[:45]

total_pnl = 0
for cond, m in sorted(markets.items(), key=lambda x: -(x[1]['up'] + x[1]['down'])):
    if m['up'] + m['down'] < 1:
        continue
    
    cost = m['up'] + m['down']
    value = m['up_value'] + m['down_value']
    pnl = value - cost
    total_pnl += pnl
    
    # Determine our dominant side
    side = "UP" if m['up'] > m['down'] else "DOWN" if m['down'] > m['up'] else "BALANCED"
    
    print(f"{m['title']}")
    print(f"  Cost: ${cost:.2f} (Up ${m['up']:.2f} / Down ${m['down']:.2f}) -> {side}")
    print(f"  Value: ${value:.2f} | P&L: ${pnl:+.2f}")
    print()

print("=" * 60)
print(f"TOTAL UNREALIZED P&L: ${total_pnl:+.2f}")
print("=" * 60)
