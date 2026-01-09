"""
Auto-redeem winning positions on Polymarket using screen automation.

This script interacts with your existing Chrome window - no need to close it.
It finds and clicks the Claim/Redeem button on screen.

Requirements:
- pip install pyautogui pillow pygetwindow
- Chrome window open with Polymarket portfolio page

Usage:
    python auto_redeem_screen.py
"""

import time
import logging
import pyautogui
import pygetwindow as gw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Safety: pyautogui will raise exception if mouse goes to corner
pyautogui.FAILSAFE = True

# How often to check (seconds)
CHECK_INTERVAL = 30


def find_chrome_window():
    """Find and focus the Chrome window with Polymarket."""
    windows = gw.getWindowsWithTitle('Chrome')

    for win in windows:
        if 'polymarket' in win.title.lower() or 'portfolio' in win.title.lower():
            logger.info(f"Found Polymarket window: {win.title[:50]}")
            win.activate()
            time.sleep(0.5)
            return win

    # If no polymarket-specific window, just use first Chrome
    if windows:
        logger.info(f"Using Chrome window: {windows[0].title[:50]}")
        windows[0].activate()
        time.sleep(0.5)
        return windows[0]

    return None


def find_button_by_image(button_images):
    """Try to find a button on screen using image matching."""
    for img in button_images:
        try:
            location = pyautogui.locateOnScreen(img, confidence=0.8)
            if location:
                return pyautogui.center(location)
        except Exception as e:
            logger.debug(f"Image search failed for {img}: {e}")
    return None


def find_button_by_color():
    """
    Look for the Polymarket claim button by its distinctive color.
    Polymarket uses a purple/blue button for claims.
    """
    import pyautogui
    from PIL import ImageGrab

    # Take screenshot
    screenshot = ImageGrab.grab()
    pixels = screenshot.load()
    width, height = screenshot.size

    # Polymarket claim button is teal with white text
    target_colors = [
        (0, 128, 128),    # Teal
        (32, 178, 170),   # Light sea green
        (0, 150, 136),    # Teal variant
        (38, 166, 154),   # Teal 400
        (0, 172, 193),    # Cyan teal
        (0, 188, 212),    # Cyan
        (77, 182, 172),   # Teal light
        (0, 137, 123),    # Teal dark
    ]

    def color_distance(c1, c2):
        return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5

    # Scan for button-like regions (look in right portion of screen where buttons usually are)
    candidates = []

    for y in range(100, height - 100, 5):
        for x in range(width // 3, width - 50, 5):
            try:
                pixel = pixels[x, y][:3]
                for target in target_colors:
                    if color_distance(pixel, target) < 50:
                        candidates.append((x, y))
                        break
            except:
                continue

    if candidates:
        # Find center of the cluster
        avg_x = sum(c[0] for c in candidates) // len(candidates)
        avg_y = sum(c[1] for c in candidates) // len(candidates)
        logger.info(f"Found potential button area at ({avg_x}, {avg_y})")
        return (avg_x, avg_y)

    return None


def find_text_on_screen(text_to_find):
    """
    Use OCR to find text on screen.
    Requires: pip install pytesseract
    And Tesseract OCR installed.
    """
    try:
        import pytesseract
        from PIL import ImageGrab

        screenshot = ImageGrab.grab()

        # Get all text and positions
        data = pytesseract.image_to_data(screenshot, output_type=pytesseract.Output.DICT)

        for i, text in enumerate(data['text']):
            if text_to_find.lower() in text.lower():
                x = data['left'][i] + data['width'][i] // 2
                y = data['top'][i] + data['height'][i] // 2
                logger.info(f"Found '{text}' at ({x}, {y})")
                return (x, y)

    except ImportError:
        logger.debug("pytesseract not available")
    except Exception as e:
        logger.debug(f"OCR failed: {e}")

    return None


def click_claim_button():
    """Try multiple methods to find and click the claim button."""

    # Method 1: Try OCR to find "Claim" or "Redeem" text
    for text in ['Claim', 'Redeem', 'CLAIM', 'REDEEM']:
        pos = find_text_on_screen(text)
        if pos:
            logger.info(f"Found '{text}' button via OCR")
            pyautogui.click(pos[0], pos[1])
            return True

    # Method 2: Try color detection for purple button
    pos = find_button_by_color()
    if pos:
        logger.info("Found button via color detection - clicking")
        pyautogui.click(pos[0], pos[1])
        return True

    logger.info("No claim button found on screen")
    return False


def handle_confirmation():
    """Look for and click any confirmation dialog."""
    time.sleep(2)

    for text in ['Confirm', 'Yes', 'OK', 'Submit']:
        pos = find_text_on_screen(text)
        if pos:
            logger.info(f"Clicking confirmation: {text}")
            pyautogui.click(pos[0], pos[1])
            time.sleep(3)
            return True

    return False


def main():
    """Main loop."""
    logger.info("=" * 50)
    logger.info("Polymarket Screen Auto-Redeem")
    logger.info("=" * 50)
    logger.info("This script will click Claim/Redeem buttons on your screen")
    logger.info("Move mouse to top-left corner to STOP (failsafe)")
    logger.info(f"Checking every {CHECK_INTERVAL} seconds")
    logger.info("")

    # Check for required packages
    try:
        from PIL import ImageGrab
    except ImportError:
        logger.error("Please install Pillow: pip install pillow")
        return

    # Give user time to position window
    logger.info("Starting in 3 seconds... make sure Polymarket is visible!")
    time.sleep(3)

    while True:
        try:
            # Find and focus Chrome
            win = find_chrome_window()
            if not win:
                logger.warning("No Chrome window found!")
                time.sleep(CHECK_INTERVAL)
                continue

            time.sleep(1)

            # Try to click claim button
            if click_claim_button():
                logger.info("Clicked a button!")
                handle_confirmation()

        except pyautogui.FailSafeException:
            logger.info("Failsafe triggered - stopping")
            break
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception as e:
            logger.error(f"Error: {e}")

        logger.info(f"Next check in {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
