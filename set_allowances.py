"""
One-time script to set CLOB trading allowances on Polymarket.
This grants the exchange contracts permission to trade with your USDC.

Requires: POL (MATIC) for gas fees on Polygon.
"""

import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# Polygon RPC
RPC_URL = "https://polygon-rpc.com"

# Token contracts
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"   # Conditional Tokens

# Exchange contracts to approve
EXCHANGES = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # CTF Exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg Risk CTF Exchange
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg Risk Adapter
]

# ERC-20 approve ABI
ERC20_ABI = [
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# ERC-1155 setApprovalForAll ABI
ERC1155_ABI = [
    {
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

MAX_UINT256 = 2**256 - 1


def main():
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY not set in .env")

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise ConnectionError("Failed to connect to Polygon RPC")

    account = w3.eth.account.from_key(private_key)
    address = account.address
    print(f"Setting allowances for: {address}")

    # Check POL balance for gas
    balance = w3.eth.get_balance(address)
    print(f"POL balance: {w3.from_wei(balance, 'ether'):.4f} POL")
    if balance < w3.to_wei(0.01, 'ether'):
        print("WARNING: Low POL balance. You need POL for gas fees!")
        return

    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI)

    nonce = w3.eth.get_transaction_count(address)

    for exchange in EXCHANGES:
        exchange_checksum = Web3.to_checksum_address(exchange)
        print(f"\nApproving exchange: {exchange[:10]}...")

        # Approve USDC
        print("  Approving USDC...")
        tx = usdc.functions.approve(exchange_checksum, MAX_UINT256).build_transaction({
            'from': address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': w3.to_wei(50, 'gwei'),
            'chainId': 137
        })
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  USDC tx: {tx_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(tx_hash)
        nonce += 1

        # Approve Conditional Tokens
        print("  Approving Conditional Tokens...")
        tx = ctf.functions.setApprovalForAll(exchange_checksum, True).build_transaction({
            'from': address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': w3.to_wei(50, 'gwei'),
            'chainId': 137
        })
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  CTF tx: {tx_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(tx_hash)
        nonce += 1

    print("\n" + "="*50)
    print("SUCCESS! All allowances set.")
    print("You can now run the copy trading bot.")
    print("="*50)


if __name__ == "__main__":
    main()
