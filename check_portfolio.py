"""Quick portfolio check."""
import requests

proxy = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'

# Get positions
r = requests.get(f'https://data-api.polymarket.com/positions?user={proxy}&sizeThreshold=0', timeout=10).json()

total_value = sum(float(p.get('currentValue', 0) or 0) for p in r)
total_cost = sum(float(p.get('size', 0) or 0) * float(p.get('avgPrice', 0) or 0) for p in r)

# Get cash balance from gamma API
try:
    cash_resp = requests.get(f'https://gamma-api.polymarket.com/users/{proxy}', timeout=10)
    if cash_resp.status_code == 200:
        cash = cash_resp.json()
        usdc = float(cash.get('usdcBalance', 0) or 0)
    else:
        usdc = 0
except:
    usdc = 0

print(f'USDC Cash: ${usdc:.2f}')
print(f'Positions Value: ${total_value:.2f}')
print(f'Position Cost: ${total_cost:.2f}')
print(f'Unrealized P&L: ${total_value - total_cost:+.2f}')
print(f'Total Portfolio: ${usdc + total_value:.2f}')
print(f'Open Positions: {len([p for p in r if float(p.get("size", 0) or 0) > 0])}')
