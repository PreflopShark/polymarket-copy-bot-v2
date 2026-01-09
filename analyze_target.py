"""Analyze target trader performance."""
import requests

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

url = f'https://data-api.polymarket.com/positions?user={TARGET}&sizeThreshold=0'
resp = requests.get(url, timeout=30)
positions = resp.json()

print('=== TARGET TRADER ANALYSIS ===')
print()

total_cost = 0
total_value = 0
resolved_pnl = 0
open_pnl = 0

resolved = []
active = []

for p in positions:
    title = p.get('title', '')[:40]
    size = float(p.get('size', 0) or 0)
    avg_price = float(p.get('avgPrice', 0) or 0)
    cur_price = float(p.get('curPrice', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    cost = size * avg_price
    pnl = value - cost

    if size < 1:
        continue

    total_cost += cost
    total_value += value

    # Check if resolved (price near 0 or 1)
    if cur_price > 0.98 or cur_price < 0.02:
        resolved_pnl += pnl
        resolved.append((title, cost, value, pnl))
    else:
        open_pnl += pnl
        active.append((title, cost, value, pnl, cur_price))

print('=== RESOLVED POSITIONS ===')
for title, cost, value, pnl in sorted(resolved, key=lambda x: x[3], reverse=True)[:10]:
    status = 'WIN' if pnl > 0 else 'LOSS'
    print(f'{status}: {title} | Cost ${cost:.0f} -> ${value:.0f} = ${pnl:+.0f}')

print()
print('=== ACTIVE POSITIONS ===')
for title, cost, value, pnl, price in sorted(active, key=lambda x: x[3], reverse=True)[:10]:
    print(f'{title} @ {price:.0%}')
    print(f'  Cost ${cost:.0f} | Value ${value:.0f} | PnL ${pnl:+.0f}')

print()
print('=== SUMMARY ===')
print(f'Total Cost: ${total_cost:,.0f}')
print(f'Total Value: ${total_value:,.0f}')
print(f'Resolved PnL: ${resolved_pnl:+,.0f}')
print(f'Open (unrealized): ${open_pnl:+,.0f}')
roi = (total_value/total_cost-1)*100 if total_cost > 0 else 0
print(f'Total PnL: ${total_value - total_cost:+,.0f} ({roi:+.1f}%)')
