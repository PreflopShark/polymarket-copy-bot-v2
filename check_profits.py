"""Calculate profits from recent trades."""
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

address = os.getenv("FUNDER_ADDRESS")
print(f"Checking profits for: {address}")
print(f"Time: Last 2 hours")
print()

# Get activity
r = requests.get(f"https://data-api.polymarket.com/activity?user={address}&limit=100")
data = r.json()

# Filter to last 2 hours
cutoff = datetime.now() - timedelta(hours=2)
recent = []
for t in data:
    ts = t.get('timestamp', 0)
    trade_time = datetime.fromtimestamp(ts)
    if trade_time >= cutoff:
        recent.append(t)

print(f"Found {len(recent)} activities in last 2 hours")
print()

# Separate by type
trades = [t for t in recent if t.get('type') == 'TRADE']
redeems = [t for t in recent if t.get('type') == 'REDEEM']

# Calculate trade costs (buys are negative, sells are positive)
total_spent = 0
total_received = 0
positions = {}

for t in trades:
    side = t.get('side', '')
    amount = float(t.get('usdcSize', 0))
    title = t.get('title', '')[:40]
    outcome = t.get('outcome', '')
    price = float(t.get('price', 0))
    shares = float(t.get('size', 0))
    
    key = f"{t.get('conditionId')}_{t.get('outcomeIndex')}"
    
    if side == 'BUY':
        total_spent += amount
        if key not in positions:
            positions[key] = {'title': title, 'outcome': outcome, 'shares': 0, 'cost': 0, 'current_price': price}
        positions[key]['shares'] += shares
        positions[key]['cost'] += amount
    elif side == 'SELL':
        total_received += amount
        if key in positions:
            positions[key]['shares'] -= shares

# Calculate redeems (wins)
total_redeemed = sum(float(t.get('usdcSize', 0)) for t in redeems)

print("=" * 60)
print("SUMMARY - Last 2 Hours")
print("=" * 60)
print(f"Total spent on buys:     ${total_spent:.2f}")
print(f"Total from sells:        ${total_received:.2f}")
print(f"Total redeemed (wins):   ${total_redeemed:.2f}")
print()
print(f"Realized P&L:            ${(total_received + total_redeemed - total_spent):+.2f}")
print("=" * 60)
print()

# Show recent trades
print("Recent Trades:")
print("-" * 60)
for t in trades[:15]:
    side = t.get('side', '')
    amount = float(t.get('usdcSize', 0))
    title = t.get('title', '')[:35]
    outcome = t.get('outcome', '')
    price = float(t.get('price', 0))
    ts = datetime.fromtimestamp(t.get('timestamp', 0)).strftime('%H:%M:%S')
    print(f"{ts} | {side:4} | ${amount:>7.2f} | {outcome:4} @ {price:.0%} | {title}")

if redeems:
    print()
    print("Redemptions (Wins):")
    print("-" * 60)
    for t in redeems:
        amount = float(t.get('usdcSize', 0))
        title = t.get('title', '')[:40]
        ts = datetime.fromtimestamp(t.get('timestamp', 0)).strftime('%H:%M:%S')
        print(f"{ts} | REDEEM | ${amount:>7.2f} | {title}")
