import requests

proxy = '0x9c76847744942b41d3bBDcFE5A3B98AE67a95750'

# Get all trades
url = f'https://data-api.polymarket.com/activity?user={proxy}&limit=500'
activity = requests.get(url, timeout=10).json()
trades = [a for a in activity if a.get('type') == 'TRADE']

# Get current positions for unrealized P&L
url = f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0'
positions = requests.get(url, timeout=10).json()

# Create position lookup by asset (token ID)
pos_by_asset = {}
for p in positions:
    asset = p.get('asset', '')
    if asset:
        pos_by_asset[asset] = p

# Define buckets
buckets = {
    '$50+': {'min': 50, 'max': float('inf'), 'trades': 0, 'invested': 0, 'pnl': 0},
    '$25-$50': {'min': 25, 'max': 50, 'trades': 0, 'invested': 0, 'pnl': 0},
    '$10-$25': {'min': 10, 'max': 25, 'trades': 0, 'invested': 0, 'pnl': 0},
    '$5-$10': {'min': 5, 'max': 10, 'trades': 0, 'invested': 0, 'pnl': 0},
    '$2-$5': {'min': 2, 'max': 5, 'trades': 0, 'invested': 0, 'pnl': 0},
    '<$2': {'min': 0, 'max': 2, 'trades': 0, 'invested': 0, 'pnl': 0},
}

for t in trades:
    size = float(t.get('usdcSize', 0) or 0)
    shares = float(t.get('size', 0) or 0)
    outcome = t.get('outcome', '')
    outcome_index = t.get('outcomeIndex')
    asset = t.get('asset', '')

    # Calculate P&L for this trade
    pnl = 0

    if outcome and outcome_index is not None:
        # Resolved market
        bought_side = 'Up' if outcome_index == 0 else 'Down'
        if bought_side == outcome:
            pnl = shares - size  # Won: payout is shares, cost is size
        else:
            pnl = -size  # Lost: lost the cost
    elif asset in pos_by_asset:
        # Open position - calculate unrealized P&L
        pos = pos_by_asset[asset]
        cur_price = float(pos.get('curPrice', 0) or 0)
        current_value = shares * cur_price
        pnl = current_value - size

    # Find bucket
    for name, bucket in buckets.items():
        if bucket['min'] <= size < bucket['max']:
            bucket['trades'] += 1
            bucket['invested'] += size
            bucket['pnl'] += pnl
            break

print('=' * 75)
print('OUR BOT PERFORMANCE BY BET SIZE (Realized + Unrealized)')
print('=' * 75)
print(f'{"Bucket":<12} {"Trades":<8} {"Invested":<12} {"P&L":<12} {"ROI":<10}')
print('-' * 75)

total_trades = 0
total_invested = 0
total_pnl = 0

for name, b in buckets.items():
    if b['trades'] == 0:
        continue
    roi = (b['pnl'] / b['invested'] * 100) if b['invested'] > 0 else 0
    print(f'{name:<12} {b["trades"]:<8} ${b["invested"]:<11.2f} ${b["pnl"]:>+10.2f} {roi:>+8.1f}%')
    total_trades += b['trades']
    total_invested += b['invested']
    total_pnl += b['pnl']

print('-' * 75)
total_roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
print(f'{"TOTAL":<12} {total_trades:<8} ${total_invested:<11.2f} ${total_pnl:>+10.2f} {total_roi:>+8.1f}%')
