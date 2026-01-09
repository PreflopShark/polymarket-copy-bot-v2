"""Analyze target trader's activity to find non-short-term markets."""

import requests
from collections import defaultdict

TARGET = "0x63ce342161250d705dc0b16df89036c8e5f9ba9a"

def main():
    # Fetch recent trades
    url = f"https://data-api.polymarket.com/activity?user={TARGET}&limit=500"
    resp = requests.get(url)
    trades = resp.json()

    # Group by market title
    markets = defaultdict(lambda: {"count": 0, "volume": 0, "trades": []})

    for trade in trades:
        title = trade.get("title", "Unknown")
        usdc = trade.get("usdcSize", 0)
        markets[title]["count"] += 1
        markets[title]["volume"] += usdc
        markets[title]["trades"].append(trade)

    # Filter out short-term crypto markets
    short_term_keywords = [
        "Up or Down - January",
        "Up or Down - February",
        "Up or Down - March",
        "Up or Down - December",
        "PM ET", "AM ET",
        "updown-15m",
        "updown-5m",
    ]

    print("=" * 80)
    print("TARGET TRADER ANALYSIS: 0x8dxd (Blushing-Fine)")
    print("=" * 80)

    print("\n\n### SHORT-TERM CRYPTO MARKETS (probably not copyable) ###\n")
    short_term_total = 0
    for title, data in sorted(markets.items(), key=lambda x: -x[1]["volume"]):
        is_short = any(kw in title for kw in short_term_keywords)
        if is_short:
            short_term_total += data["volume"]
            print(f"  {title[:60]:<60} | {data['count']:>3} trades | ${data['volume']:>8.2f}")
    print(f"\n  TOTAL SHORT-TERM: ${short_term_total:.2f}")

    print("\n\n### LONGER-TERM MARKETS (potentially copyable) ###\n")
    long_term_total = 0
    for title, data in sorted(markets.items(), key=lambda x: -x[1]["volume"]):
        is_short = any(kw in title for kw in short_term_keywords)
        if not is_short:
            long_term_total += data["volume"]
            # Show recent trade details
            recent = data["trades"][0]
            side = recent.get("side", "?")
            price = recent.get("price", 0)
            outcome = recent.get("outcome", "?")
            print(f"  {title[:55]:<55} | {data['count']:>3} trades | ${data['volume']:>8.2f} | Last: {side} {outcome} @${price:.2f}")

    print(f"\n  TOTAL LONGER-TERM: ${long_term_total:.2f}")

    print(f"\n\n### SUMMARY ###")
    print(f"Short-term crypto gambling: ${short_term_total:.2f} ({100*short_term_total/(short_term_total+long_term_total):.1f}%)")
    print(f"Longer-term markets:        ${long_term_total:.2f} ({100*long_term_total/(short_term_total+long_term_total):.1f}%)")

if __name__ == "__main__":
    main()
