import requests
from collections import defaultdict

# Get all trades
activity_url = 'https://data-api.polymarket.com/activity?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750&limit=1000'
activity = requests.get(activity_url).json()

trades = [a for a in activity if a.get('type') == 'TRADE']
redeems = [a for a in activity if a.get('type') == 'REDEEM']

# Group trades by market
market_trades = defaultdict(lambda: {'spent': 0, 'redeemed': 0, 'trades': []})

for t in trades:
    title = t.get('title', 'Unknown')
    usdc = float(t.get('usdcSize', 0))
    market_trades[title]['spent'] += usdc
    market_trades[title]['trades'].append(t)

for r in redeems:
    title = r.get('title', 'Unknown')
    usdc = float(r.get('usdcSize', 0))
    market_trades[title]['redeemed'] += usdc

# Get current positions
pos_url = 'https://data-api.polymarket.com/positions?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750&sizeThreshold=0'
positions = requests.get(pos_url).json()

for p in positions:
    title = p.get('title', 'Unknown')
    current = float(p.get('currentValue', 0))
    market_trades[title]['current_value'] = market_trades[title].get('current_value', 0) + current

print('=== COMPLETE MARKET-BY-MARKET P&L ===')
print('P&L = (Redeemed winnings) + (Current position value) - (Spent on trades)')
print('=' * 95)

results = []
for market, data in market_trades.items():
    spent = data['spent']
    redeemed = data['redeemed']
    current = data.get('current_value', 0)
    pnl = redeemed + current - spent
    results.append((market[:50], spent, redeemed, current, pnl))

# Sort by P&L (worst first)
for market, spent, redeemed, current, pnl in sorted(results, key=lambda x: x[4]):
    status = 'OPEN' if current > 1 else 'CLOSED'
    print(f'{pnl:>+8.2f} | Spent:${spent:>7.2f} | Won:${redeemed:>7.2f} | Pos:${current:>7.2f} | {status:>6} | {market}')

print('=' * 95)
total_spent = sum(r[1] for r in results)
total_redeemed = sum(r[2] for r in results)
total_current = sum(r[3] for r in results)
total_pnl = sum(r[4] for r in results)
print(f'{total_pnl:>+8.2f} | Spent:${total_spent:>7.2f} | Won:${total_redeemed:>7.2f} | Pos:${total_current:>7.2f} |        | TOTAL')

print(f'\n=== SUMMARY ===')
print(f'Total spent on trades: ${total_spent:.2f}')
print(f'Total redeemed (wins): ${total_redeemed:.2f}')
print(f'Current positions:     ${total_current:.2f}')
print(f'Net P&L:               ${total_pnl:+.2f}')
