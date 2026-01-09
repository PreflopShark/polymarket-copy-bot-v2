"""Auto-redeem resolved winning positions on Polymarket."""

import logging
import os
import requests
from typing import List, Dict, Optional
from web3 import Web3
from eth_account import Account

logger = logging.getLogger(__name__)

# Polymarket Conditional Tokens Framework (CTF) contract on Polygon
# This is where positions are held and redeemed
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Simplified ABI for redeemPositions on CTF
CTF_ABI = [
    {
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Parent collection ID (bytes32 zero for root)
PARENT_COLLECTION_ID = bytes(32)


class PositionRedeemer:
    """Handles automatic redemption of resolved positions."""
    
    def __init__(self, private_key: str, funder_address: str):
        self.private_key = private_key
        self.funder_address = funder_address.lower()
        
        # Connect to Polygon
        self.w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        self.account = Account.from_key(private_key)
        
        # CTF Contract instance
        self.ctf = self.w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=CTF_ABI
        )
        
        logger.info(f"Redeemer initialized for {self.funder_address[:10]}...")
    
    def get_redeemable_positions(self) -> List[Dict]:
        """Fetch positions that can be redeemed."""
        try:
            url = f"https://data-api.polymarket.com/positions?user={self.funder_address}&sizeThreshold=0.01"
            response = requests.get(url, timeout=10)
            positions = response.json()
            
            redeemable = []
            for p in positions:
                cur_price = float(p.get('curPrice', 0.5))
                # Position is resolved if price is 0 or 1
                is_winner = cur_price >= 0.99
                is_resolved = cur_price <= 0.01 or cur_price >= 0.99
                
                if is_resolved and is_winner:
                    redeemable.append({
                        'conditionId': p.get('conditionId'),
                        'asset': p.get('asset'),
                        'size': float(p.get('size', 0)),
                        'title': p.get('title', 'Unknown'),
                        'outcome': p.get('outcome', '?'),
                        'value': float(p.get('size', 0)) * 1.0,  # $1 per share
                        'outcomeIndex': p.get('outcomeIndex', 0),
                        'mergeable': p.get('mergeable', False),
                    })
            
            return redeemable
            
        except Exception as e:
            logger.error(f"Error fetching redeemable positions: {e}")
            return []
    
    def redeem_position(self, position: Dict) -> bool:
        """Redeem a single resolved position via CTF contract."""
        try:
            condition_id = position['conditionId']
            outcome_index = position.get('outcomeIndex', 0)
            size = position['size']
            title = position['title'][:30]

            # Convert condition_id to bytes32
            if condition_id.startswith('0x'):
                condition_bytes = bytes.fromhex(condition_id[2:])
            else:
                condition_bytes = bytes.fromhex(condition_id)

            # Index sets - redeem both outcomes (1 for Yes/Up, 2 for No/Down)
            # The CTF will pay out based on the resolution
            index_sets = [1, 2]

            # First, estimate gas to check if tx will succeed (prevents wasting MATIC)
            try:
                estimated_gas = self.ctf.functions.redeemPositions(
                    Web3.to_checksum_address(USDC_ADDRESS),
                    PARENT_COLLECTION_ID,
                    condition_bytes,
                    index_sets
                ).estimate_gas({'from': self.account.address})
            except Exception as e:
                # If estimateGas fails, the tx would revert - skip it
                logger.debug(f"Skipping {title}: not redeemable yet (gas estimate failed)")
                return False

            logger.info(f"Redeeming: {title}... | {position['outcome']} | {size:.1f} shares = ${position['value']:.2f}")

            # Build transaction with estimated gas + buffer
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            gas_price = self.w3.eth.gas_price

            txn = self.ctf.functions.redeemPositions(
                Web3.to_checksum_address(USDC_ADDRESS),  # collateral token
                PARENT_COLLECTION_ID,  # parent collection (zero for root)
                condition_bytes,  # condition ID
                index_sets  # which outcomes to redeem
            ).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gas': int(estimated_gas * 1.2),  # 20% buffer
                'gasPrice': int(gas_price * 1.2),
                'chainId': 137,
            })

            # Sign and send
            signed_txn = self.w3.eth.account.sign_transaction(txn, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)

            logger.info(f"Redeem tx sent: {tx_hash.hex()[:20]}...")

            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt['status'] == 1:
                logger.info(f"[OK] Redeemed ${position['value']:.2f} from {title}")
                return True
            else:
                logger.error(f"[FAIL] Redeem tx failed for {title}")
                return False

        except Exception as e:
            logger.error(f"Error redeeming position: {e}")
            return False
    
    def redeem_all(self) -> Dict:
        """Check for redeemable positions and log them.

        NOTE: Auto-redemption from proxy wallets requires Polymarket's relayer.
        Positions must be redeemed manually via polymarket.com or with Builder API access.
        This method now just reports what's available to redeem.
        """
        redeemable = self.get_redeemable_positions()

        if not redeemable:
            logger.debug("No positions to redeem")
            return {'redeemed': 0, 'total_value': 0}

        total_value = sum(p['value'] for p in redeemable)
        logger.info(f"[REDEEM] {len(redeemable)} positions ready to redeem (${total_value:.2f})")
        logger.info("   Redeem manually at polymarket.com (proxy wallet requires relayer)")

        # Log each position
        for p in redeemable[:5]:  # Show first 5
            logger.info(f"   - {p['title'][:35]}... | {p['outcome']} | ${p['value']:.2f}")
        if len(redeemable) > 5:
            logger.info(f"   ... and {len(redeemable) - 5} more")

        return {
            'redeemed': 0,  # Can't auto-redeem from proxy wallet
            'total_value': total_value,
            'pending_count': len(redeemable)
        }


def create_redeemer() -> Optional[PositionRedeemer]:
    """Create a redeemer from environment variables."""
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS")
    
    if not private_key or not funder_address:
        logger.warning("Missing PRIVATE_KEY or FUNDER_ADDRESS for redeemer")
        return None
    
    return PositionRedeemer(private_key, funder_address)


if __name__ == "__main__":
    # Test redemption
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv()
    
    redeemer = create_redeemer()
    if redeemer:
        positions = redeemer.get_redeemable_positions()
        print(f"\nFound {len(positions)} redeemable positions:")
        for p in positions:
            print(f"  {p['title'][:40]}... | {p['outcome']} | ${p['value']:.2f}")
