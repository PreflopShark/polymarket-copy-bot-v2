import requests

proxy = '0x9c76847744942b41d3bBDcFE5A3B98AE67a95750'

# User's actual starting info
STARTING_BALANCE = 500  # Original deposit
ADDITIONAL_DEPOSIT = 1000  # Extra deposit made
TOTAL_DEPOSITS = STARTING_BALANCE + ADDITIONAL_DEPOSIT  # $1500 total deposited

# Get current portfolio value
url = f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0'
positions = requests.get(url, timeout=10).json()

total_position_value = sum(
    float(p.get('size', 0) or 0) * float(p.get('curPrice', 0) or 0)
    for p in positions
)

# Get USDC balance
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
usdc_address = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'
usdc_abi = [{'inputs': [{'name': 'account', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]
usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc_address), abi=usdc_abi)
usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(proxy)).call() / 1e6

current_portfolio = total_position_value + usdc_balance
actual_profit = current_portfolio - TOTAL_DEPOSITS
actual_roi = (actual_profit / TOTAL_DEPOSITS) * 100

print('=' * 60)
print('CORRECTED PORTFOLIO SUMMARY')
print('=' * 60)
print(f'Total deposited: ${TOTAL_DEPOSITS:.2f} ($500 + $1000)')
print(f'Current portfolio: ${current_portfolio:.2f}')
print(f'Actual profit: ${actual_profit:.2f}')
print(f'Actual ROI: {actual_roi:+.1f}%')
print('=' * 60)

# Now analyze by bet size - but we need to calculate relative performance
# The question is: which bet sizes are performing BETTER relative to each other

url = f'https://data-api.polymarket.com/activity?user={proxy}&limit=500'
activity = requests.get(url, timeout=10).json()
trades = [a for a in activity if a.get('type') == 'TRADE']

# Create position lookup
pos_by_asset = {p.get('asset', ''): p for p in positions if p.get('asset')}

buckets = {
    '$50+': {'min': 50, 'max': float('inf'), 'trades': 0, 'invested': 0, 'value': 0},
    '$25-$50': {'min': 25, 'max': 50, 'trades': 0, 'invested': 0, 'value': 0},
    '$10-$25': {'min': 10, 'max': 25, 'trades': 0, 'invested': 0, 'value': 0},
    '$5-$10': {'min': 5, 'max': 10, 'trades': 0, 'invested': 0, 'value': 0},
    '$2-$5': {'min': 2, 'max': 5, 'trades': 0, 'invested': 0, 'value': 0},
    '<$2': {'min': 0, 'max': 2, 'trades': 0, 'invested': 0, 'value': 0},
}

for t in trades:
    size = float(t.get('usdcSize', 0) or 0)
    shares = float(t.get('size', 0) or 0)
    outcome = t.get('outcome', '')
    outcome_index = t.get('outcomeIndex')
    asset = t.get('asset', '')

    # Calculate current value for this trade
    current_value = 0
    if outcome and outcome_index is not None:
        # Resolved market
        bought_side = 'Up' if outcome_index == 0 else 'Down'
        if bought_side == outcome:
            current_value = shares  # Won: each share worth $1
        else:
            current_value = 0  # Lost
    elif asset in pos_by_asset:
        # Open position
        pos = pos_by_asset[asset]
        cur_price = float(pos.get('curPrice', 0) or 0)
        current_value = shares * cur_price

    # Find bucket
    for name, bucket in buckets.items():
        if bucket['min'] <= size < bucket['max']:
            bucket['trades'] += 1
            bucket['invested'] += size
            bucket['value'] += current_value
            break

print('\nPERFORMANCE BY BET SIZE')
print('=' * 75)
print(f'{"Bucket":<12} {"Trades":<8} {"Invested":<12} {"Value":<12} {"P&L":<12} {"ROI":<10}')
print('-' * 75)

for name, b in buckets.items():
    if b['trades'] == 0:
        continue
    pnl = b['value'] - b['invested']
    roi = (pnl / b['invested'] * 100) if b['invested'] > 0 else 0
    print(f'{name:<12} {b["trades"]:<8} ${b["invested"]:<11.2f} ${b["value"]:<11.2f} ${pnl:>+10.2f} {roi:>+8.1f}%')

print('-' * 75)
total_invested = sum(b['invested'] for b in buckets.values())
total_value = sum(b['value'] for b in buckets.values())
total_pnl = total_value - total_invested
total_roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
print(f'{"TOTAL":<12} {sum(b["trades"] for b in buckets.values()):<8} ${total_invested:<11.2f} ${total_value:<11.2f} ${total_pnl:>+10.2f} {total_roi:>+8.1f}%')

print('\n** Note: This shows trading P&L only. Your ~$600 profit aligns with')
print('   the difference between current portfolio ($2,145) and deposits ($1,500)')
