"""Polymarket API authentication using py-clob-client."""

import logging
import os
from typing import Optional

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

from .config import Config
from .browser_session import BrowserSession

logger = logging.getLogger(__name__)

# Global browser session for Cloudflare bypass
_browser_session: Optional[BrowserSession] = None
_requests_session: Optional[requests.Session] = None

# Browser-like headers to bypass Cloudflare
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class AuthenticationError(Exception):
    """Raised when authentication fails - sanitized to prevent key leaks."""
    pass


def initialize_browser_session(headless: bool = False) -> bool:
    """
    Initialize the browser session for Cloudflare bypass.
    
    Args:
        headless: Whether to run browser in headless mode
        
    Returns:
        True if successful
    """
    global _browser_session, _requests_session
    
    _browser_session = BrowserSession.get_instance()
    success = _browser_session.initialize(headless=headless)
    
    if success:
        # Create a requests session with the browser's cookies
        _requests_session = requests.Session()
        for name, value in _browser_session.cookies.items():
            _requests_session.cookies.set(name, value, domain='.polymarket.com')
        _requests_session.headers.update(BROWSER_HEADERS)
        
    return success


def patch_client_with_cf_cookie():
    """Patch the HTTP client with Cloudflare cookie from .env."""
    import py_clob_client.http_helpers.helpers as http_helpers
    import httpx
    
    cf_bm_cookie = os.getenv("CF_BM_COOKIE", "")
    
    if not cf_bm_cookie:
        logger.warning("No CF_BM_COOKIE in .env - Cloudflare may block requests")
        return
    
    # Create httpx client with the CF cookie and browser headers
    cookie_jar = httpx.Cookies()
    cookie_jar.set("__cf_bm", cf_bm_cookie, domain="clob.polymarket.com")
    
    new_client = httpx.Client(
        http2=True,
        cookies=cookie_jar,
        headers=BROWSER_HEADERS,
        timeout=30.0
    )
    http_helpers._http_client = new_client
    
    logger.info("Patched HTTP client with Cloudflare cookie from .env")


def patch_client_headers(client: ClobClient):
    """Patch the client's HTTP session with browser cookies to bypass Cloudflare."""
    global _browser_session, _requests_session
    import py_clob_client.http_helpers.helpers as http_helpers
    
    if _browser_session is None:
        logger.warning("No browser session - trying CF cookie from .env")
        patch_client_with_cf_cookie()
        return
    
    # Get cookies from browser
    cookies = _browser_session.cookies
    
    # Create httpx client with cookies
    import httpx
    cookie_jar = httpx.Cookies()
    for name, value in cookies.items():
        cookie_jar.set(name, value, domain="clob.polymarket.com")
    
    # Replace the module's http client with one that has our cookies and headers
    new_client = httpx.Client(
        http2=True,
        cookies=cookie_jar,
        headers=BROWSER_HEADERS,
        timeout=30.0
    )
    http_helpers._http_client = new_client
    
    logger.info("Patched HTTP helpers with browser session for Cloudflare bypass")


def create_clob_client(config: Config) -> ClobClient:
    """
    Create and authenticate a CLOB client.

    Args:
        config: Bot configuration containing private key and API settings.

    Returns:
        Authenticated ClobClient ready for trading.

    Raises:
        AuthenticationError: If authentication fails (sanitized, no key in message).
    """
    logger.info("Initializing CLOB client...")

    try:
        # Create client with private key
        # signature_type=0 is for EOA wallets (MetaMask, etc.)
        # signature_type=1 is for browser/Magic wallet proxies
        # If FUNDER_ADDRESS is set, always use type 1 (proxy wallet)
        # This is needed because Polymarket accounts created via browser use proxy wallets
        from eth_account import Account
        key_address = Account.from_key(config.private_key).address.lower()
        funder_lower = config.funder_address.lower() if config.funder_address else ""

        # Always use signature_type=1 if funder is set (proxy wallet setup)
        if config.funder_address:
            logger.info("Using signature_type=1 (proxy wallet)")
            client = ClobClient(
                host=config.clob_host,
                chain_id=config.chain_id,
                key=config.private_key,
                signature_type=1,
                funder=config.funder_address,
            )
        else:
            logger.info("Using signature_type=0 (EOA wallet)")
            client = ClobClient(
                host=config.clob_host,
                chain_id=config.chain_id,
                key=config.private_key,
                signature_type=0,
            )
    except Exception:
        # Sanitize - don't include original exception which may contain key
        raise AuthenticationError("Failed to initialize client - check private key format")

    # Set API credentials - use Builder API key if provided, otherwise derive from private key
    if config.has_builder_api_credentials():
        logger.info("Using Builder API credentials from environment")
        api_creds = ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
        )
        client.set_api_creds(api_creds)
        logger.info("Builder API credentials set successfully")
    else:
        # Derive API credentials from the private key
        # This creates L2 auth credentials (API key, secret, passphrase)
        logger.info("Deriving API credentials from private key...")
        try:
            api_creds = client.derive_api_key()
            client.set_api_creds(api_creds)
            logger.info("API credentials derived successfully")
        except Exception as e:
            # Log sanitized error - don't include full exception details
            error_type = type(e).__name__
            logger.error(f"Failed to derive API credentials: {error_type}")
            raise AuthenticationError(f"API credential derivation failed: {error_type}")

    # Patch with browser headers to bypass Cloudflare
    patch_client_headers(client)

    return client


def verify_client(client: ClobClient) -> bool:
    """
    Verify the client is properly authenticated by checking server connectivity.

    Args:
        client: The CLOB client to verify.

    Returns:
        True if client is working, False otherwise.
    """
    try:
        # Simple health check - get server time
        result = client.get_ok()
        logger.info(f"Client verification successful: {result}")
        return True
    except Exception as e:
        logger.error(f"Client verification failed: {e}")
        return False
