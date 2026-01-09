import requests

# Get positions
url = "https://data-api.polymarket.com/positions?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750&sizeThreshold=0.01"
positions = requests.get(url).json()

print("=== POSITIONS THAT LOST (value near $0 but had shares) ===\n")
total_lost = 0
for p in positions:
    size = float(p.get('size', 0))
    value = float(p.get('currentValue', 0))
    # If we had significant shares but value is near zero, we lost
    if size > 5 and value < 1:
        title = p.get('title', 'Unknown')[:50]
        outcome = p.get('outcome', '?')
        print(f"{title} | {outcome} | {size:.1f} shares | ${value:.2f}")
        # Estimate loss (rough - shares * avg price)
        total_lost += size * 0.5  # rough estimate

print(f"\n=== ESTIMATED LOSSES: ~${total_lost:.2f} ===")

print("\n\n=== ALL CURRENT POSITIONS ===\n")
for p in sorted(positions, key=lambda x: -float(x.get('currentValue', 0))):
    size = float(p.get('size', 0))
    value = float(p.get('currentValue', 0))
    if value > 0.01:
        title = p.get('title', 'Unknown')[:45]
        outcome = p.get('outcome', '?')
        print(f"${value:>7.2f} | {title} | {outcome}")
