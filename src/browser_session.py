"""Browser-based HTTP session using undetected-chromedriver to bypass Cloudflare."""

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import undetected_chromedriver as uc

logger = logging.getLogger(__name__)


class BrowserSession:
    """
    Manages a headless Chrome browser session that bypasses Cloudflare.
    Uses the browser to make API requests with valid cf_clearance cookies.
    """
    
    _instance: Optional['BrowserSession'] = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.driver: Optional[uc.Chrome] = None
        self.cookies: Dict[str, str] = {}
        self._initialized = False
        
    @classmethod
    def get_instance(cls) -> 'BrowserSession':
        """Get or create the singleton browser session."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def initialize(self, headless: bool = True) -> bool:
        """
        Initialize the browser and get Cloudflare clearance.
        
        Args:
            headless: Run browser in headless mode (no visible window)
            
        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True
            
        logger.info("Initializing undetected Chrome browser...")
        
        try:
            options = uc.ChromeOptions()
            if headless:
                options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            
            # Create undetected Chrome instance
            self.driver = uc.Chrome(options=options, use_subprocess=True)
            
            # Visit polymarket to get Cloudflare clearance
            logger.info("Visiting polymarket.com to get Cloudflare clearance...")
            self.driver.get("https://polymarket.com")
            
            # Wait for page to load and Cloudflare challenge to complete
            time.sleep(5)
            
            # Also visit the CLOB API domain to get clearance there
            logger.info("Visiting clob.polymarket.com for API clearance...")
            self.driver.get("https://clob.polymarket.com/")
            time.sleep(3)
            
            # Extract cookies
            self._extract_cookies()
            
            if 'cf_clearance' in self.cookies:
                logger.info("Cloudflare clearance obtained successfully!")
                self._initialized = True
                return True
            else:
                logger.warning("No cf_clearance cookie found, but continuing...")
                self._initialized = True
                return True
                
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            return False
    
    def _extract_cookies(self):
        """Extract cookies from the browser session."""
        if not self.driver:
            return
            
        all_cookies = self.driver.get_cookies()
        for cookie in all_cookies:
            self.cookies[cookie['name']] = cookie['value']
            
        logger.info(f"Extracted {len(self.cookies)} cookies")
        if 'cf_clearance' in self.cookies:
            logger.info("cf_clearance cookie found!")
    
    def get_cookie_header(self) -> str:
        """Get cookies formatted as a header string."""
        return "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
    
    def execute_request(self, method: str, url: str, headers: Dict[str, str] = None, 
                        data: Any = None) -> Dict[str, Any]:
        """
        Execute an HTTP request using the browser's JavaScript engine.
        This ensures all Cloudflare cookies and headers are sent correctly.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            headers: Additional headers to send
            data: Request body data (will be JSON serialized)
            
        Returns:
            Response data as dict
        """
        if not self._initialized:
            raise RuntimeError("Browser session not initialized")
        
        # Build the fetch options
        fetch_options = {
            "method": method,
            "credentials": "include",
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                **(headers or {})
            }
        }
        
        if data is not None:
            if isinstance(data, str):
                fetch_options["body"] = data
            else:
                fetch_options["body"] = json.dumps(data)
        
        # Execute fetch in browser context
        script = f"""
        return await (async () => {{
            try {{
                const response = await fetch({json.dumps(url)}, {json.dumps(fetch_options)});
                const status = response.status;
                const text = await response.text();
                let json_data = null;
                try {{
                    json_data = JSON.parse(text);
                }} catch (e) {{
                    // Not JSON
                }}
                return {{
                    status: status,
                    text: text,
                    json: json_data,
                    ok: response.ok
                }};
            }} catch (e) {{
                return {{
                    error: e.toString(),
                    status: 0
                }};
            }}
        }})();
        """
        
        result = self.driver.execute_script(script)
        
        if result.get('error'):
            raise Exception(f"Browser fetch error: {result['error']}")
        
        if not result.get('ok'):
            raise Exception(f"HTTP {result['status']}: {result.get('text', '')[:500]}")
        
        return result.get('json') or result.get('text')
    
    def close(self):
        """Close the browser session."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._initialized = False


def get_browser_cookies() -> Dict[str, str]:
    """Get Cloudflare cookies from a browser session."""
    session = BrowserSession.get_instance()
    if not session._initialized:
        session.initialize(headless=False)  # Show browser for first-time setup
    return session.cookies


def create_requests_session_with_browser_cookies():
    """Create a requests session with browser cookies for Cloudflare bypass."""
    import requests
    
    session = BrowserSession.get_instance()
    if not session._initialized:
        session.initialize(headless=False)
    
    req_session = requests.Session()
    for name, value in session.cookies.items():
        req_session.cookies.set(name, value)
    
    # Add browser-like headers
    req_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://polymarket.com",
        "Referer": "https://polymarket.com/",
    })
    
    return req_session
