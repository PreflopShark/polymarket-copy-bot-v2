"""Analyze trade history - ACTUAL P&L."""
import requests
import os
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()
address = os.getenv('FUNDER_ADDRESS')

print(f"Analyzing trades for: {address}")
print()

# Get current positions value
r_pos = requests.get(f'https://data-api.polymarket.com/positions?user={address}&sizeThreshold=0.01')
positions = r_pos.json()
portfolio_value = sum(float(p.get('size', 0)) * float(p.get('curPrice', 0)) for p in positions)

# Get all activity
r = requests.get(f'https://data-api.polymarket.com/activity?user={address}&limit=1000')
data = r.json()

# Separate by type
trades = [t for t in data if t.get('type') == 'TRADE']
redeems = [t for t in data if t.get('type') == 'REDEEM']

# Calculate totals
total_spent = sum(float(t.get('usdcSize', 0)) for t in trades if t.get('side') == 'BUY')
total_sold = sum(float(t.get('usdcSize', 0)) for t in trades if t.get('side') == 'SELL')
total_redeemed = sum(float(t.get('usdcSize', 0)) for t in redeems)

print('='*70)
print('ACTUAL P&L CALCULATION')
print('='*70)
print(f'Total spent on buys:     ${total_spent:.2f}')
print(f'Total from sells:        ${total_sold:.2f}')
print(f'Total redeemed (wins):   ${total_redeemed:.2f}')
print(f'Current portfolio value: ${portfolio_value:.2f}')
print()
net_cash = total_sold + total_redeemed - total_spent
total_value = net_cash + portfolio_value
print(f'Net cash flow:           ${net_cash:+.2f}')
print(f'+ Open positions:        ${portfolio_value:.2f}')
print('='*70)
print(f'ACTUAL P&L:              ${total_value:+.2f}')
print('='*70)

# Group by market to find losers
markets = defaultdict(lambda: {'buys': 0, 'sells': 0, 'redeems': 0, 'trades': []})

for t in trades:
    key = t.get('conditionId', '')
    title = t.get('title', '')[:50]
    markets[key]['title'] = title
    side = t.get('side', '')
    amount = float(t.get('usdcSize', 0))
    if side == 'BUY':
        markets[key]['buys'] += amount
    else:
        markets[key]['sells'] += amount
    markets[key]['trades'].append(t)

for t in redeems:
    key = t.get('conditionId', '')
    amount = float(t.get('usdcSize', 0))
    markets[key]['redeems'] += amount

# Calculate P&L per market
results = []
for key, m in markets.items():
    pnl = m['sells'] + m['redeems'] - m['buys']
    results.append({
        'title': m.get('title', 'Unknown'),
        'buys': m['buys'],
        'sells': m['sells'],
        'redeems': m['redeems'],
        'pnl': pnl,
        'trades': m['trades']
    })

# Sort by P&L (worst first)
results.sort(key=lambda x: x['pnl'])

print('BIGGEST LOSERS:')
print('-'*70)
for r in results[:15]:
    if r['pnl'] < -0.01:
        print(f"${r['pnl']:+8.2f} | Buy: ${r['buys']:>7.2f} | Redeem: ${r['redeems']:>7.2f} | {r['title']}")

print()
print('BIGGEST WINNERS:')
print('-'*70)
for r in sorted(results, key=lambda x: -x['pnl'])[:10]:
    if r['pnl'] > 0.01:
        print(f"${r['pnl']:+8.2f} | Buy: ${r['buys']:>7.2f} | Redeem: ${r['redeems']:>7.2f} | {r['title']}")

# Check for unredeemed positions (open positions)
print()
print('='*70)
print('OPEN POSITIONS (not yet resolved):')
print('-'*70)
open_positions = [r for r in results if r['redeems'] == 0 and r['sells'] == 0 and r['buys'] > 0]
total_open = 0
for r in sorted(open_positions, key=lambda x: -x['buys'])[:15]:
    print(f"${r['buys']:>8.2f} invested | {r['title']}")
    total_open += r['buys']
print(f"\nTotal in open positions: ${total_open:.2f}")

# Analyze loss patterns
print()
print('='*70)
print('LOSS ANALYSIS:')
print('-'*70)
losers = [r for r in results if r['pnl'] < -0.01]
total_loss = sum(r['pnl'] for r in losers)
print(f"Number of losing markets: {len(losers)}")
print(f"Total losses: ${total_loss:.2f}")

# Check if losses are from markets that resolved against us
print()
print("Markets where we bought but got $0 back (wrong prediction):")
wrong_predictions = [r for r in results if r['buys'] > 0 and r['redeems'] == 0 and r['sells'] == 0]
# Actually check for markets with some redeems but less than buys - partial loss
partial_losses = [r for r in results if r['redeems'] > 0 and r['redeems'] < r['buys'] * 0.5]
print(f"Partial losses (redeemed < 50% of investment): {len(partial_losses)}")
for r in partial_losses[:5]:
    loss_pct = (1 - r['redeems']/r['buys']) * 100 if r['buys'] > 0 else 0
    print(f"  ${r['pnl']:+.2f} | Bought ${r['buys']:.2f}, got back ${r['redeems']:.2f} ({loss_pct:.0f}% loss) | {r['title'][:40]}")
