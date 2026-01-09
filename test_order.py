"""Test order placement to diagnose signature issues"""
from dotenv import load_dotenv
import os
load_dotenv()

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
from py_clob_client.constants import POLYGON

# Create client with signature_type=1 (proxy wallet)
client = ClobClient(
    'https://clob.polymarket.com',
    key=os.getenv('PRIVATE_KEY'),
    chain_id=POLYGON,
    signature_type=1,
    funder=os.getenv('FUNDER_ADDRESS')
)

# Set credentials
creds = ApiCreds(
    api_key=os.getenv('POLYMARKET_API_KEY'),
    api_secret=os.getenv('POLYMARKET_API_SECRET'),
    api_passphrase=os.getenv('POLYMARKET_API_PASSPHRASE'),
)
client.set_api_creds(creds)

funder = os.getenv('FUNDER_ADDRESS')
print(f'Client address: {client.get_address()}')
print(f'Funder (proxy): {funder}')
print(f'Signature type: {client.builder.sig_type}')

# Skip balance check for now - just test order

# Test with a small limit order that won't fill
# Using a real token from the crypto market
token_id = '29179682863761521016082178592399193498846352652561679090411973415155380704849'
order_args = OrderArgs(
    price=0.01,  # Very low price - won't fill
    size=5.0,
    side=BUY,
    token_id=token_id,
)

try:
    signed_order = client.create_order(order_args)
    print(f'Signed order created successfully')
    print(f'Order object: {vars(signed_order.order)}')
    print(f'Signature: {signed_order.signature}')
    print(f'Order signature type: {signed_order.order.signatureType}')
    print(f'Order maker: {signed_order.order.maker}')
    print(f'Order signer: {signed_order.order.signer}')
    
    # Try posting
    resp = client.post_order(signed_order, OrderType.GTC)
    print(f'Order posted: {resp}')
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f'Error: {type(e).__name__}: {e}')
