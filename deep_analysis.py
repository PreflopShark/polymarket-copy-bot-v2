"""Deep analysis of target's strategy and what we're missing."""

import requests
from collections import defaultdict

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
OUR_PROXY = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'

print("="*70)
print("DEEP STRATEGY ANALYSIS")
print("="*70)

# Get target positions
url = f'https://data-api.polymarket.com/positions?user={TARGET}'
resp = requests.get(url, timeout=30)
target_positions = resp.json()

# Get our positions
url = f'https://data-api.polymarket.com/positions?user={OUR_PROXY}'
resp = requests.get(url, timeout=30)
our_positions = resp.json()

# Group target positions by market (conditionId)
target_by_market = defaultdict(list)
for p in target_positions:
    cond_id = p.get('conditionId', '')
    target_by_market[cond_id].append(p)

# Group our positions by market
our_by_market = defaultdict(list)
for p in our_positions:
    cond_id = p.get('conditionId', '')
    our_by_market[cond_id].append(p)

print("\n" + "="*70)
print("TARGET'S HEDGING STRATEGY ANALYSIS")
print("="*70)

hedged_markets = []
single_side_markets = []

for cond_id, positions in target_by_market.items():
    title = positions[0].get('title', 'Unknown')[:50]
    
    up_pos = None
    down_pos = None
    
    for p in positions:
        outcome = p.get('outcome', '')
        if 'Up' in outcome or 'Yes' in outcome:
            up_pos = p
        elif 'Down' in outcome or 'No' in outcome:
            down_pos = p
    
    if up_pos and down_pos:
        up_size = float(up_pos.get('size', 0) or 0)
        down_size = float(down_pos.get('size', 0) or 0)
        up_cost = up_size * float(up_pos.get('avgPrice', 0) or 0)
        down_cost = down_size * float(down_pos.get('avgPrice', 0) or 0)
        up_value = float(up_pos.get('currentValue', 0) or 0)
        down_value = float(down_pos.get('currentValue', 0) or 0)
        
        total_cost = up_cost + down_cost
        total_value = up_value + down_value
        net_pnl = total_value - total_cost
        
        hedged_markets.append({
            'title': title,
            'up_cost': up_cost,
            'down_cost': down_cost,
            'up_value': up_value,
            'down_value': down_value,
            'total_cost': total_cost,
            'total_value': total_value,
            'net_pnl': net_pnl,
            'up_pct': up_cost / total_cost * 100 if total_cost > 0 else 0,
        })
    else:
        pos = up_pos or down_pos
        if pos:
            size = float(pos.get('size', 0) or 0)
            cost = size * float(pos.get('avgPrice', 0) or 0)
            value = float(pos.get('currentValue', 0) or 0)
            single_side_markets.append({
                'title': title,
                'outcome': pos.get('outcome', ''),
                'cost': cost,
                'value': value,
                'pnl': value - cost,
            })

print(f"\nTarget has {len(hedged_markets)} HEDGED markets (both Up and Down)")
print(f"Target has {len(single_side_markets)} SINGLE-SIDE markets")

print("\n--- HEDGED MARKETS (Both sides) ---")
total_hedged_cost = 0
total_hedged_value = 0
for m in sorted(hedged_markets, key=lambda x: -x['net_pnl']):
    pnl_pct = (m['net_pnl'] / m['total_cost'] * 100) if m['total_cost'] > 0 else 0
    print(f"{m['title']}")
    print(f"  Up: ${m['up_cost']:.2f} ({m['up_pct']:.0f}%) -> ${m['up_value']:.2f}")
    print(f"  Down: ${m['down_cost']:.2f} ({100-m['up_pct']:.0f}%) -> ${m['down_value']:.2f}")
    print(f"  NET: Cost ${m['total_cost']:.2f} -> Value ${m['total_value']:.2f} | P&L: ${m['net_pnl']:.2f} ({pnl_pct:+.1f}%)")
    print()
    total_hedged_cost += m['total_cost']
    total_hedged_value += m['total_value']

print(f"HEDGED MARKETS TOTAL:")
print(f"  Cost: ${total_hedged_cost:.2f}")
print(f"  Value: ${total_hedged_value:.2f}")
hedged_pnl_pct = ((total_hedged_value/total_hedged_cost)-1)*100 if total_hedged_cost > 0 else 0
print(f"  P&L: ${total_hedged_value - total_hedged_cost:.2f} ({hedged_pnl_pct:+.1f}%)")

print("\n" + "="*70)
print("COMPARISON: WHAT WE'RE DOING VS TARGET")
print("="*70)

# Check our positions
our_hedged = 0
our_single = 0
for cond_id, positions in our_by_market.items():
    if len(positions) > 1:
        our_hedged += 1
    else:
        our_single += 1

print(f"\nOUR STRATEGY:")
print(f"  Hedged markets: {our_hedged}")
print(f"  Single-side markets: {our_single}")

print(f"\nTARGET'S STRATEGY:")
print(f"  Hedged markets: {len(hedged_markets)}")
print(f"  Single-side markets: {len(single_side_markets)}")

# Key insight: Check if we're betting same side as target's LARGER position
print("\n" + "="*70)
print("SIDE ALIGNMENT ANALYSIS")
print("="*70)

aligned = 0
misaligned = 0
not_copied = 0

for cond_id, target_pos_list in target_by_market.items():
    # Find target's dominant side
    target_up = None
    target_down = None
    for p in target_pos_list:
        outcome = p.get('outcome', '')
        if 'Up' in outcome or 'Yes' in outcome:
            target_up = p
        else:
            target_down = p
    
    # Calculate which side is larger
    up_cost = float(target_up.get('size', 0) or 0) * float(target_up.get('avgPrice', 0) or 0) if target_up else 0
    down_cost = float(target_down.get('size', 0) or 0) * float(target_down.get('avgPrice', 0) or 0) if target_down else 0
    
    target_dominant = 'Up' if up_cost >= down_cost else 'Down'
    
    # Check what we have
    our_pos = our_by_market.get(cond_id)
    if not our_pos:
        not_copied += 1
        continue
    
    our_outcomes = [p.get('outcome', '') for p in our_pos]
    our_has_up = any('Up' in o or 'Yes' in o for o in our_outcomes)
    our_has_down = any('Down' in o or 'No' in o for o in our_outcomes)
    
    if (target_dominant == 'Up' and our_has_up) or (target_dominant == 'Down' and our_has_down):
        aligned += 1
    else:
        misaligned += 1
        title = target_pos_list[0].get('title', '')[:40]
        print(f"MISALIGNED: {title}")
        print(f"  Target dominant: {target_dominant} (Up: ${up_cost:.2f}, Down: ${down_cost:.2f})")
        print(f"  We have: {'Up' if our_has_up else ''} {'Down' if our_has_down else ''}")

print(f"\n--- SUMMARY ---")
print(f"Aligned with target's dominant side: {aligned}")
print(f"Misaligned (opposite of dominant): {misaligned}")
print(f"Markets not copied: {not_copied}")

# Now the key question: What's the P&L of markets we're aligned vs misaligned?
print("\n" + "="*70)
print("THE REAL PROBLEM: WE'RE ONLY COPYING ONE SIDE")
print("="*70)

print("""
TARGET'S STRATEGY:
- Buys BOTH Up AND Down on most markets
- Profits when one side wins big (100%) minus the losing side (0%)
- Net positive because they size according to their prediction

OUR STRATEGY:
- Only copies the FIRST trade we see
- If target buys Up first, then Down, we only get Up
- We miss the hedge that protects against losses

RECOMMENDATION:
1. When target buys one side, wait to see if they also buy the other
2. Copy BOTH sides with similar ratios
3. This captures their "predicted direction" sizing advantage
""")

# Calculate what target's P&L would be if they only had one side
print("\n--- SIMULATION: If target only had single side (like us) ---")
for m in sorted(hedged_markets, key=lambda x: -abs(x['net_pnl']))[:5]:
    # If they only had Up
    up_only_pnl = m['up_value'] - m['up_cost']
    # If they only had Down  
    down_only_pnl = m['down_value'] - m['down_cost']
    # Their actual
    actual_pnl = m['net_pnl']
    
    print(f"{m['title']}")
    print(f"  Up-only P&L: ${up_only_pnl:.2f}")
    print(f"  Down-only P&L: ${down_only_pnl:.2f}")
    print(f"  Hedged P&L: ${actual_pnl:.2f}")
    print()
