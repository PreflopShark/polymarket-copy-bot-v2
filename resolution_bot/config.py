"""
Configuration for Resolution Friction Farm Bot - MVP

RULES:
1. Only deadline-based markets (crypto up/down)
2. Only trade AFTER deadline passes
3. Only BUY winners (no shorts)
4. Price must be <= 0.97 (minimum 3% profit)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Wallet configuration (shared with main bot)
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS")

# =============================================================================
# MVP HARD RULES
# =============================================================================
MAX_PRICE = 0.97  # NEVER pay more than 97 cents (3% min profit)
# =============================================================================

# Position sizing
MIN_POSITION_SIZE = 1.0
MAX_POSITION_SIZE = float(os.getenv("RES_MAX_POSITION", "50"))

# Scanning
POLL_INTERVAL = int(os.getenv("RES_POLL_INTERVAL", "10"))

# Dry run mode
DRY_RUN = os.getenv("RES_DRY_RUN", "true").lower() == "true"

# Logging
LOG_LEVEL = os.getenv("RES_LOG_LEVEL", "INFO")
