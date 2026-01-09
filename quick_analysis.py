"""Quick analysis of recent trades - compare us vs target."""
import requests
from datetime import datetime, timedelta
from collections import defaultdict

proxy = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'
target = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

# Get OUR recent activity
url = f'https://data-api.polymarket.com/activity?user={proxy}&limit=500'
our_activity = requests.get(url, timeout=30).json()

# Filter to last 2 hours
cutoff = datetime.now() - timedelta(hours=2)
our_recent = [a for a in our_activity if datetime.fromtimestamp(a.get('timestamp', 0)) >= cutoff]
our_trades = [t for t in our_recent if t.get('type') == 'TRADE' and t.get('side') == 'BUY']

# Get TARGET recent activity  
url = f'https://data-api.polymarket.com/activity?user={target}&limit=500'
target_activity = requests.get(url, timeout=30).json()
target_recent = [a for a in target_activity if datetime.fromtimestamp(a.get('timestamp', 0)) >= cutoff]
target_trades = [t for t in target_recent if t.get('type') == 'TRADE' and t.get('side') == 'BUY']

print(f'Last 2 hours: We made {len(our_trades)} buys, Target made {len(target_trades)} buys')
print()

# Compare by market
our_markets = defaultdict(lambda: {'up': 0, 'down': 0, 'title': ''})
target_markets = defaultdict(lambda: {'up': 0, 'down': 0, 'title': ''})

for t in our_trades:
    cond = t.get('conditionId', '')
    outcome = t.get('outcome', '')
    usdc = float(t.get('usdcSize', 0))
    if 'Up' in outcome:
        our_markets[cond]['up'] += usdc
    else:
        our_markets[cond]['down'] += usdc
    our_markets[cond]['title'] = t.get('title', '')[:40]

for t in target_trades:
    cond = t.get('conditionId', '')
    outcome = t.get('outcome', '')
    usdc = float(t.get('usdcSize', 0))
    if 'Up' in outcome:
        target_markets[cond]['up'] += usdc
    else:
        target_markets[cond]['down'] += usdc
    target_markets[cond]['title'] = t.get('title', '')[:40]

print('=== TARGET vs US (Last 2 Hours) ===')
print()

# Get current positions
url = f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0'
positions = requests.get(url, timeout=30).json()
pos_by_cond = defaultdict(list)
for p in positions:
    cond = p.get('conditionId', '')
    pos_by_cond[cond].append(p)

all_conds = set(our_markets.keys()) | set(target_markets.keys())
total_mismatch = 0

for cond in all_conds:
    ours = our_markets.get(cond, {'up': 0, 'down': 0, 'title': ''})
    theirs = target_markets.get(cond, {'up': 0, 'down': 0, 'title': ''})
    title = ours.get('title') or theirs.get('title', '')
    
    if ours['up'] + ours['down'] < 0.5 and theirs['up'] + theirs['down'] < 0.5:
        continue
    
    our_dominant = 'UP' if ours['up'] > ours['down'] else 'DOWN'
    target_dominant = 'UP' if theirs['up'] > theirs['down'] else 'DOWN'
    
    mismatch = 'MISMATCH!' if our_dominant != target_dominant and (ours['up'] + ours['down'] > 0.5) else ''
    if mismatch:
        total_mismatch += 1
    
    # Get position value
    pos_value = sum(float(p.get('currentValue', 0) or 0) for p in pos_by_cond.get(cond, []))
    cost = sum(float(p.get('size', 0) or 0) * float(p.get('avgPrice', 0) or 0) for p in pos_by_cond.get(cond, []))
    pnl = pos_value - cost if cost > 0 else 0
    
    print(f'{title}')
    print(f'  TARGET: Up ${theirs["up"]:.2f} / Down ${theirs["down"]:.2f} -> {target_dominant}')
    print(f'  US:     Up ${ours["up"]:.2f} / Down ${ours["down"]:.2f} -> {our_dominant} {mismatch}')
    print(f'  Position: ${pos_value:.2f} (P&L: ${pnl:+.2f})')
    print()

print('='*60)
print(f'Total mismatched markets: {total_mismatch}')

# Overall P&L
total_cost = 0
total_value = 0
for p in positions:
    size = float(p.get('size', 0) or 0)
    avg_price = float(p.get('avgPrice', 0) or 0)
    cur_price = float(p.get('curPrice', 0) or 0)
    total_cost += size * avg_price
    total_value += size * cur_price

print()
print(f'Total position cost: ${total_cost:.2f}')
print(f'Total position value: ${total_value:.2f}')
print(f'Unrealized P&L: ${total_value - total_cost:+.2f}')
