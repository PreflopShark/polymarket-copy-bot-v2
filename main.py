"""
Polymarket Copy Bot v2
A clean slate for building a copy trading bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def main():
    """Main entry point for the copy bot."""
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    target_wallet = os.getenv("TARGET_WALLET", "")

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"=" * 50)
    print(f"Polymarket Copy Bot v2")
    print(f"Mode: {mode}")
    print(f"Target: {target_wallet[:10]}..." if target_wallet else "Target: Not set")
    print(f"=" * 50)

    if not target_wallet:
        print("ERROR: TARGET_WALLET not set in .env")
        return

    # TODO: Implement copy trading logic
    print("Bot initialized. Ready for development.")


if __name__ == "__main__":
    main()
