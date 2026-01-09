"""Test script to place a single trade on Polymarket."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.constants import POLYGON

# Market details
TOKEN_ID = "30247838524016950285983728899628085099194631313141244143555651362630420449270"  # Celonis IPO Yes
SIDE = "BUY"
TARGET_USDC = 1.0  # $1 trade

def main():
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS")

    if not private_key or not funder_address:
        print("Missing PRIVATE_KEY or FUNDER_ADDRESS in .env")
        return

    print("Initializing client...")
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=POLYGON,
        funder=funder_address,
        signature_type=1,  # POLY_GNOSIS_SAFE
    )

    # Derive API credentials
    print("Deriving API credentials...")
    client.set_api_creds(client.derive_api_key())

    # Get order book to find best ask
    print(f"\nGetting order book for token {TOKEN_ID[:20]}...")
    book = client.get_order_book(TOKEN_ID)

    if not book.asks:
        print("No asks in order book!")
        return

    # Sort asks by price ascending to get the lowest ask
    sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
    best_ask = float(sorted_asks[0].price)
    print(f"Best ask price: ${best_ask:.4f}")

    # Calculate shares
    shares = TARGET_USDC / best_ask
    if shares < 5:
        print(f"Shares {shares:.2f} below minimum 5, adjusting to 5")
        shares = 5

    actual_cost = shares * best_ask
    print(f"Order: {shares:.2f} shares @ ${best_ask:.4f} = ${actual_cost:.2f}")

    # Create order
    print("\nCreating order...")
    order_args = OrderArgs(
        token_id=TOKEN_ID,
        price=best_ask,
        size=shares,
        side=SIDE,
    )

    signed_order = client.create_order(order_args)

    # Submit order
    print("Submitting order...")
    try:
        response = client.post_order(signed_order, OrderType.FOK)
        print(f"\nOrder response: {response}")
    except Exception as e:
        print(f"FOK failed: {e}")
        print("Trying GTC order...")
        response = client.post_order(signed_order, OrderType.GTC)
        print(f"\nGTC Order response: {response}")

if __name__ == "__main__":
    main()
