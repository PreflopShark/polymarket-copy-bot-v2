"""
Auto-redeem winning positions on Polymarket via browser automation.

This script opens Chrome, navigates to your Polymarket portfolio,
and clicks redeem on all winning positions periodically.

Requirements:
- Chrome browser installed
- Already logged into Polymarket in Chrome (uses existing profile)

Usage:
    python auto_redeem_browser.py
"""

import time
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# How often to check for redeemable positions (seconds)
CHECK_INTERVAL = 120  # 2 minutes

# Your Polymarket portfolio URL
PORTFOLIO_URL = "https://polymarket.com/portfolio"


def create_browser(use_existing_profile=False):
    """Create undetected Chrome browser.

    Args:
        use_existing_profile: If True, uses your Chrome profile (Chrome must be closed).
                             If False, opens fresh browser (you'll need to connect wallet).
    """
    logger.info("Starting Chrome browser...")

    options = uc.ChromeOptions()

    if use_existing_profile:
        # Use your default Chrome profile (keeps you logged in)
        # NOTE: Chrome must be completely closed for this to work!
        options.add_argument("--user-data-dir=C:/Users/Jack/AppData/Local/Google/Chrome/User Data")
        options.add_argument("--profile-directory=Default")
        logger.info("Using existing Chrome profile (make sure Chrome is closed!)")
    else:
        logger.info("Using fresh browser session - you'll need to connect your wallet")

    driver = uc.Chrome(options=options, use_subprocess=True)
    driver.set_window_size(1200, 900)

    return driver


def find_and_click_redeem_buttons(driver):
    """Find all redeem buttons and click them."""
    redeemed_count = 0

    try:
        # Wait for page to load
        time.sleep(3)

        # Look for redeem buttons - Polymarket uses various button styles
        # Common patterns: "Redeem", "Claim", buttons with redeem-related text
        redeem_selectors = [
            "//button[contains(text(), 'Redeem')]",
            "//button[contains(text(), 'redeem')]",
            "//button[contains(text(), 'Claim')]",
            "//button[contains(@class, 'redeem')]",
            "//div[contains(@class, 'redeem')]//button",
            "//span[contains(text(), 'Redeem')]/ancestor::button",
        ]

        for selector in redeem_selectors:
            try:
                buttons = driver.find_elements(By.XPATH, selector)
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        try:
                            # Scroll into view
                            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                            time.sleep(0.5)

                            btn_text = btn.text[:30] if btn.text else "Redeem"
                            logger.info(f"Clicking: {btn_text}")
                            btn.click()
                            redeemed_count += 1

                            # Wait for transaction to process
                            time.sleep(3)

                            # Handle any confirmation dialogs
                            try:
                                confirm_btn = WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Confirm')]"))
                                )
                                confirm_btn.click()
                                logger.info("Confirmed transaction")
                                time.sleep(5)  # Wait for tx
                            except TimeoutException:
                                pass  # No confirmation needed

                        except Exception as e:
                            logger.debug(f"Could not click button: {e}")

            except NoSuchElementException:
                continue

    except Exception as e:
        logger.error(f"Error finding redeem buttons: {e}")

    return redeemed_count


def check_for_winning_positions(driver):
    """Navigate to portfolio and look for positions to redeem."""
    logger.info("Checking for redeemable positions...")

    try:
        # Go to portfolio
        driver.get(PORTFOLIO_URL)

        # Wait for page load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)  # Extra wait for dynamic content

        # Check if logged in
        if "connect" in driver.page_source.lower() and "wallet" in driver.page_source.lower():
            logger.warning("Not logged in - please log in manually in the browser window")
            return 0

        # Find and click redeem buttons
        redeemed = find_and_click_redeem_buttons(driver)

        if redeemed > 0:
            logger.info(f"Redeemed {redeemed} positions!")
        else:
            logger.info("No positions to redeem right now")

        return redeemed

    except Exception as e:
        logger.error(f"Error checking portfolio: {e}")
        return 0


def main():
    """Main loop - periodically check and redeem positions."""
    import sys

    logger.info("=" * 50)
    logger.info("Polymarket Auto-Redeem Browser Script")
    logger.info("=" * 50)
    logger.info(f"Will check every {CHECK_INTERVAL} seconds")
    logger.info("Press Ctrl+C to stop")
    logger.info("")

    # Check for --profile flag
    use_profile = "--profile" in sys.argv
    if use_profile:
        logger.info("Using existing Chrome profile mode")
        logger.info("IMPORTANT: Close all Chrome windows first!")
        input("Press Enter when Chrome is closed...")

    driver = None

    try:
        driver = create_browser(use_existing_profile=use_profile)
        logger.info("Browser started. If not logged in, please log in now.")

        # Initial check
        time.sleep(5)  # Give time for manual login if needed

        while True:
            try:
                check_for_winning_positions(driver)
            except Exception as e:
                logger.error(f"Error in check cycle: {e}")
                # Try to recover
                try:
                    driver.get(PORTFOLIO_URL)
                except:
                    pass

            logger.info(f"Next check in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        if driver:
            logger.info("Closing browser...")
            driver.quit()


if __name__ == "__main__":
    main()
