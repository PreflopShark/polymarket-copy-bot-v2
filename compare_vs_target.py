"""Compare our performance vs the target trader."""
import requests
from collections import defaultdict
from datetime import datetime, timedelta

proxy = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'
target = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

print("=" * 70)
print("         US vs TARGET TRADER COMPARISON")
print("=" * 70)
print()

# Get both positions
our_positions = requests.get(f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0', timeout=10).json()
target_positions = requests.get(f'https://data-api.polymarket.com/positions?user={target}&sizeThreshold=0', timeout=10).json()

# Get recent activity (last 6 hours)
our_activity = requests.get(f'https://data-api.polymarket.com/activity?user={proxy}&limit=1000', timeout=10).json()
target_activity = requests.get(f'https://data-api.polymarket.com/activity?user={target}&limit=1000', timeout=10).json()

cutoff = datetime.now() - timedelta(hours=6)

our_recent = [a for a in our_activity if datetime.fromtimestamp(a.get('timestamp', 0)) >= cutoff]
target_recent = [a for a in target_activity if datetime.fromtimestamp(a.get('timestamp', 0)) >= cutoff]

our_trades = [t for t in our_recent if t.get('type') == 'TRADE']
target_trades = [t for t in target_recent if t.get('type') == 'TRADE']

# Calculate trading volume
our_buy_volume = sum(float(t.get('usdcSize', 0)) for t in our_trades if t.get('side') == 'BUY')
target_buy_volume = sum(float(t.get('usdcSize', 0)) for t in target_trades if t.get('side') == 'BUY')

print("TRADING VOLUME (Last 6 Hours)")
print("-" * 50)
print(f"  Target bought:     ${target_buy_volume:,.2f}")
print(f"  We bought:         ${our_buy_volume:,.2f}")
print(f"  Copy ratio:        {our_buy_volume/target_buy_volume*100:.1f}%" if target_buy_volume > 0 else "")
print()

# Group positions by condition ID for comparison
our_by_cond = defaultdict(lambda: {'up': 0, 'down': 0, 'up_val': 0, 'down_val': 0, 'title': ''})
target_by_cond = defaultdict(lambda: {'up': 0, 'down': 0, 'up_val': 0, 'down_val': 0, 'title': ''})

for p in our_positions:
    cond = p.get('conditionId', '')
    outcome = p.get('outcome', '')
    size = float(p.get('size', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    cost = size * float(p.get('avgPrice', 0) or 0)
    
    if 'Up' in outcome or 'Yes' in outcome:
        our_by_cond[cond]['up'] = cost
        our_by_cond[cond]['up_val'] = value
    else:
        our_by_cond[cond]['down'] = cost
        our_by_cond[cond]['down_val'] = value
    our_by_cond[cond]['title'] = p.get('title', '')[:40]

for p in target_positions:
    cond = p.get('conditionId', '')
    outcome = p.get('outcome', '')
    size = float(p.get('size', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    cost = size * float(p.get('avgPrice', 0) or 0)
    
    if 'Up' in outcome or 'Yes' in outcome:
        target_by_cond[cond]['up'] = cost
        target_by_cond[cond]['up_val'] = value
    else:
        target_by_cond[cond]['down'] = cost
        target_by_cond[cond]['down_val'] = value
    target_by_cond[cond]['title'] = p.get('title', '')[:40]

# Find markets we both traded
shared_markets = set(our_by_cond.keys()) & set(target_by_cond.keys())

print("SHARED MARKETS COMPARISON")
print("-" * 70)

our_total_pnl = 0
target_total_pnl = 0
our_total_cost = 0
target_total_cost = 0

for cond in shared_markets:
    ours = our_by_cond[cond]
    theirs = target_by_cond[cond]
    
    our_cost = ours['up'] + ours['down']
    our_value = ours['up_val'] + ours['down_val']
    our_pnl = our_value - our_cost
    
    target_cost = theirs['up'] + theirs['down']
    target_value = theirs['up_val'] + theirs['down_val']
    target_pnl = target_value - target_cost
    
    if our_cost < 1 and target_cost < 1:
        continue
    
    our_total_pnl += our_pnl
    target_total_pnl += target_pnl
    our_total_cost += our_cost
    target_total_cost += target_cost
    
    # Determine sides
    our_side = "UP" if ours['up'] > ours['down'] else "DOWN"
    target_side = "UP" if theirs['up'] > theirs['down'] else "DOWN"
    match = "✓" if our_side == target_side else "✗ MISMATCH"
    
    target_pnl_pct = (target_pnl / target_cost * 100) if target_cost > 0 else 0
    our_pnl_pct = (our_pnl / our_cost * 100) if our_cost > 0 else 0
    
    print(f"{ours['title'] or theirs['title']}")
    print(f"  TARGET: ${target_cost:>7.2f} -> ${target_value:>7.2f} | P&L: ${target_pnl:>+7.2f} ({target_pnl_pct:>+5.1f}%) [{target_side}]")
    print(f"  US:     ${our_cost:>7.2f} -> ${our_value:>7.2f} | P&L: ${our_pnl:>+7.2f} ({our_pnl_pct:>+5.1f}%) [{our_side}] {match}")
    print()

print("=" * 70)
print("SUMMARY")
print("-" * 50)

target_pnl_pct = (target_total_pnl / target_total_cost * 100) if target_total_cost > 0 else 0
our_pnl_pct = (our_total_pnl / our_total_cost * 100) if our_total_cost > 0 else 0

print(f"  TARGET Total P&L:  ${target_total_pnl:>+10.2f} ({target_pnl_pct:>+5.1f}%)")
print(f"  OUR Total P&L:     ${our_total_pnl:>+10.2f} ({our_pnl_pct:>+5.1f}%)")
print()
print(f"  Difference:        ${our_total_pnl - target_total_pnl:>+10.2f}")
print()

if target_total_pnl > 0 and our_total_pnl < 0:
    print("  ⚠️  Target is UP but we are DOWN - strategy mismatch!")
elif target_total_pnl < 0 and our_total_pnl < 0:
    print("  📉 Both are down - market moved against positions")
elif target_total_pnl > 0 and our_total_pnl > 0:
    print("  📈 Both are up - strategy working!")
    
print("=" * 70)
