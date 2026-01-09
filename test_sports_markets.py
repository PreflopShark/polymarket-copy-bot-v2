"""Quick test to see what sports markets exist"""
import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        # Try searching for specific matchup markets
        resp = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "limit": 200},
            timeout=10.0
        )
        
        markets = resp.json()
        print(f"Total markets: {len(markets)}")
        print()
        
        # Look specifically for "vs" markets
        vs_markets = []
        for m in markets:
            title = m.get("question", m.get("title", "")).lower()
            if " vs " in title or " vs. " in title:
                vs_markets.append({
                    "title": m.get("question", m.get("title", "")),
                    "slug": m.get("slug", ""),
                })
        
        print(f"Markets with 'vs': {len(vs_markets)}")
        print("=" * 60)
        for vm in vs_markets[:30]:
            print(f"Title: {vm['title']}")
            print(f"Slug: {vm['slug']}")
            print("-" * 40)
        
        # Also try tags endpoint or events
        print("\n\nChecking for 'NFL' tag markets...")
        resp2 = await client.get(
            "https://gamma-api.polymarket.com/events",
            params={"active": "true", "closed": "false", "limit": 50, "tag": "nfl"},
            timeout=10.0
        )
        if resp2.status_code == 200:
            events = resp2.json()
            print(f"NFL Events: {len(events)}")
            for e in events[:10]:
                print(f" - {e.get('title', e.get('slug', 'unknown'))}")

asyncio.run(main())
