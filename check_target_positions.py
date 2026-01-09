"""Check target's current positions."""

import requests

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

# Get their CURRENT positions (not trade history)
url = f'https://data-api.polymarket.com/positions?user={TARGET}'
print('Fetching target current positions...')
resp = requests.get(url, timeout=30)
positions = resp.json()

print(f'Target has {len(positions)} active positions')
print()

total_value = 0
total_cost = 0
total_pnl = 0

for p in sorted(positions, key=lambda x: -float(x.get('currentValue', 0) or 0))[:30]:
    title = p.get('title', 'Unknown')[:50]
    outcome = p.get('outcome', '?')
    size = float(p.get('size', 0) or 0)
    avg_price = float(p.get('avgPrice', 0) or 0)
    cur_price = float(p.get('curPrice', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    
    cost = size * avg_price
    pnl = value - cost
    pnl_pct = (pnl / cost * 100) if cost > 0 else 0
    
    total_value += value
    total_cost += cost
    total_pnl += pnl
    
    if size > 0:
        print(f'{title}')
        print(f'  {outcome}: {size:.1f} @ {avg_price:.1%} -> {cur_price:.1%}')
        print(f'  Value: ${value:.2f} | PnL: ${pnl:.2f} ({pnl_pct:+.1f}%)')
        print()

print('='*70)
print('TOTAL PORTFOLIO:')
print(f'  Current Value: ${total_value:.2f}')
print(f'  Cost Basis: ${total_cost:.2f}')
pnl_pct_total = (total_pnl/total_cost*100) if total_cost > 0 else 0
print(f'  Unrealized P&L: ${total_pnl:.2f} ({pnl_pct_total:+.1f}%)')
