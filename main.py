"""
Pinterest Board Image Downloader (Playwright)
Downloads images from a Pinterest board using the built-in download button
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
import os
import hashlib
from pathlib import Path


class PinterestDownloader:
    def __init__(self, output_folder="pinterest_images"):
        self.output_folder = output_folder
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        self.downloaded_hashes = set()
        self.load_existing_hashes()

    def load_existing_hashes(self):
        """Load hashes of existing files to avoid re-downloading"""
        for filename in os.listdir(self.output_folder):
            if filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                # Extract hash from filename if it exists
                hash_part = filename.split(
                    '_')[0] if '_' in filename else filename.split('.')[0]
                self.downloaded_hashes.add(hash_part)
        print(f"Found {len(self.downloaded_hashes)} existing images")

    def get_image_hash(self, img_url):
        """Generate a hash for the image URL"""
        return hashlib.md5(img_url.encode()).hexdigest()[:12]

    def scroll_to_load_all_pins(self, page):
        """Scroll through the page to load all pins"""
        print("Loading all pins from board...")

        previous_height = 0
        scroll_pause_time = 2
        max_scrolls = 50  # Prevent infinite scrolling
        scrolls = 0
        no_change_count = 0

        while scrolls < max_scrolls:
            try:
                # Get current pins count
                pins = page.locator('[data-test-id="pin"]').all()
                current_count = len(pins)
                print(f"Loaded {current_count} pins...")

                # Scroll down
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(scroll_pause_time * 1000)

                # Get new height
                new_height = page.evaluate("document.body.scrollHeight")

                # Get new pins count after scroll
                pins_after = page.locator('[data-test-id="pin"]').all()
                new_count = len(pins_after)

                # If no new pins loaded and height hasn't changed, increment counter
                if new_count == current_count and new_height == previous_height:
                    no_change_count += 1
                    if no_change_count >= 3:
                        break
                else:
                    no_change_count = 0

                previous_height = new_height
                scrolls += 1
            except Exception as e:
                print(f"Error during scrolling: {e}")
                break

        # Get final count
        try:
            final_pins = page.locator('[data-test-id="pin"]').all()
            print(f"Finished loading. Found {len(final_pins)} total pins")
            return final_pins
        except Exception as e:
            print(f"Error getting final pin count: {e}")
            return []

    def download_images_from_board(self, board_url, headless=False):
        """Download all images from a Pinterest board"""
        with sync_playwright() as p:
            # Launch browser
            browser = p.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                accept_downloads=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            # Navigate to Pinterest and login
            print("Opening Pinterest login page...")
            page.goto("https://www.pinterest.com/login/")

            input(
                "\nPlease log in to Pinterest in the browser window and press Enter to continue...")

            # Navigate to board
            print(f"\nOpening board: {board_url}")
            try:
                page.goto(board_url, timeout=60000,
                          wait_until='domcontentloaded')
                page.wait_for_timeout(3000)

                # Check if we're actually on the board page
                if "pinterest.com" not in page.url:
                    print(f"Warning: Redirected to {page.url}")
                    input(
                        "Please navigate to your board manually and press Enter to continue...")

                # Wait for pins to appear
                page.wait_for_selector('[data-test-id="pin"]', timeout=10000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"Error loading board: {e}")
                print("Current URL:", page.url)
                input(
                    "Please navigate to your board manually in the browser and press Enter to continue...")

            # Load all pins
            pins = self.scroll_to_load_all_pins(page)
            total_pins = len(pins)

            downloaded = 0
            skipped = 0
            failed = 0

            # Process each pin
            for idx in range(total_pins):
                try:
                    # Re-query pins each iteration to avoid stale elements
                    current_pins = page.locator('[data-test-id="pin"]').all()
                    if idx >= len(current_pins):
                        print(f"[{idx+1}/{total_pins}] Pin no longer available")
                        failed += 1
                        continue

                    pin = current_pins[idx]

                    # Scroll pin into view
                    pin.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)

                    # Click the pin to open closeup view
                    pin.click()
                    page.wait_for_timeout(2000)

                    try:
                        # Wait for the image to load in closeup view
                        page.wait_for_selector(
                            'img[src*="pinimg"]', timeout=5000)

                        # Get image source to check if already downloaded
                        img = page.locator('img[src*="pinimg"]').first
                        img_src = img.get_attribute('src')
                        img_hash = self.get_image_hash(img_src)

                        # Check if already downloaded
                        if img_hash in self.downloaded_hashes:
                            print(
                                f"[{idx+1}/{total_pins}] Skipping - already downloaded")
                            skipped += 1
                        else:
                            # Look for "More actions" button - try multiple selectors
                            more_button = None
                            selectors = [
                                '[aria-label="More options"]',
                                '[data-test-id="more-options-button"]',
                                'button:has-text("More")',
                                '[aria-label="More actions"]'
                            ]

                            for selector in selectors:
                                try:
                                    more_button = page.locator(selector).first
                                    if more_button.is_visible(timeout=1000):
                                        break
                                except:
                                    continue

                            if not more_button:
                                print(
                                    f"[{idx+1}/{total_pins}] Failed - couldn't find More options button")
                                failed += 1
                            else:
                                # Click more options
                                more_button.click()
                                page.wait_for_timeout(1000)

                                # Look for download option - try multiple text variations
                                download_button = None
                                download_texts = [
                                    'text="Download image"',
                                    'text="Download"',
                                    '[data-test-id="download-button"]',
                                    'div:has-text("Download image")',
                                ]

                                for selector in download_texts:
                                    try:
                                        download_button = page.locator(
                                            selector).first
                                        if download_button.is_visible(timeout=1000):
                                            break
                                    except:
                                        continue

                                if not download_button:
                                    print(
                                        f"[{idx+1}/{total_pins}] Failed - couldn't find Download button")
                                    failed += 1
                                else:
                                    # Click download and handle the download
                                    with page.expect_download(timeout=30000) as download_info:
                                        download_button.click()

                                    download = download_info.value

                                    # Save with hash prefix
                                    original_name = download.suggested_filename
                                    ext = Path(original_name).suffix
                                    new_filename = f"{img_hash}_{original_name}"
                                    download_path = os.path.join(
                                        self.output_folder, new_filename)

                                    download.save_as(download_path)
                                    self.downloaded_hashes.add(img_hash)

                                    print(
                                        f"[{idx+1}/{total_pins}] Downloaded: {new_filename}")
                                    downloaded += 1
                                    page.wait_for_timeout(1000)

                    except PlaywrightTimeout:
                        print(
                            f"[{idx+1}/{total_pins}] Failed - timeout waiting for elements")
                        failed += 1
                    except Exception as e:
                        print(f"[{idx+1}/{total_pins}] Failed - {str(e)}")
                        failed += 1

                    # Close the pin closeup view
                    try:
                        # Try multiple ways to close
                        close_selectors = [
                            '[aria-label="Close"]',
                            '[data-test-id="closeup-close-button"]',
                            'button:has-text("Close")'
                        ]

                        closed = False
                        for selector in close_selectors:
                            try:
                                close_button = page.locator(selector).first
                                if close_button.is_visible(timeout=1000):
                                    close_button.click()
                                    closed = True
                                    break
                            except:
                                continue

                        if not closed:
                            # Fallback to Escape key
                            page.keyboard.press('Escape')

                        page.wait_for_timeout(1000)
                    except:
                        # Try Escape as last resort
                        page.keyboard.press('Escape')
                        page.wait_for_timeout(1000)

                except Exception as e:
                    print(
                        f"[{idx+1}/{total_pins}] Error processing pin: {str(e)}")
                    failed += 1

                    # Try to close any open dialogs
                    try:
                        page.keyboard.press('Escape')
                        page.wait_for_timeout(500)
                    except:
                        pass

            print("\n" + "="*50)
            print(f"Download complete!")
            print(f"Downloaded: {downloaded}")
            print(f"Skipped (already exists): {skipped}")
            print(f"Failed: {failed}")
            print(f"Total pins: {total_pins}")
            print("="*50)

            input("\nPress Enter to close the browser...")
            browser.close()


def main():
    print("Pinterest Board Image Downloader")
    print("="*50)

    # Configuration
    BOARD_URL = input("Enter your Pinterest board URL: ").strip()
    OUTPUT_FOLDER = input(
        "Enter output folder name (default: pinterest_images): ").strip() or "pinterest_images"
    HEADLESS = input(
        "Run in headless mode? (y/n, default: n): ").strip().lower() == 'y'

    downloader = PinterestDownloader(output_folder=OUTPUT_FOLDER)

    try:
        downloader.download_images_from_board(BOARD_URL, headless=HEADLESS)
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")


if __name__ == "__main__":
    main()
