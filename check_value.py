import requests

# Get positions
url = "https://data-api.polymarket.com/positions?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750&sizeThreshold=0.01"
positions = requests.get(url).json()

# Sum values
total_positions = sum(float(p.get('currentValue', 0)) for p in positions)

# Get cash balance from value endpoint
value_url = "https://data-api.polymarket.com/value?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750"
value_data = requests.get(value_url).json()
total_value = float(value_data[0]['value']) if value_data else 0

cash = total_value - total_positions

print(f"Open Positions Value: ${total_positions:.2f}")
print(f"Cash Balance: ${cash:.2f}")
print(f"Total Portfolio: ${total_value:.2f}")
