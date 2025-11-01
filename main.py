"""
Pinterest Board Image Downloader (Playwright) with .env support
Downloads images from a Pinterest board using the built-in download button
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
import os
import hashlib
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class PinterestDownloader:
    def __init__(self, output_folder="pinterest_images"):
        self.output_folder = output_folder
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        self.downloaded_hashes = set()
        self.skipped_hashes = set()
        self.db_file = os.path.join(output_folder, ".pinterest_db.json")
        self.load_database()

    def load_database(self):
        """Load hashes of existing and skipped files"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r') as f:
                    db = json.load(f)
                    self.downloaded_hashes = set(db.get('downloaded', []))
                    self.skipped_hashes = set(db.get('skipped', []))
            except:
                pass

        for filename in os.listdir(self.output_folder):
            if filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                hash_part = filename.split(
                    '_')[0] if '_' in filename else filename.split('.')[0]
                self.downloaded_hashes.add(hash_part)

        print(f"Found {len(self.downloaded_hashes)} existing images")
        print(f"Found {len(self.skipped_hashes)} skipped images (too small)")

    def save_database(self):
        """Save the database of downloaded and skipped hashes"""
        db = {
            'downloaded': list(self.downloaded_hashes),
            'skipped': list(self.skipped_hashes)
        }
        with open(self.db_file, 'w') as f:
            json.dump(db, f, indent=2)

    def get_image_hash(self, img_url):
        """Generate a hash for the image URL"""
        return hashlib.md5(img_url.encode()).hexdigest()[:12]

    def scroll_to_load_all_pins(self, page):
        """Scroll through the page to load all pins"""
        print("Loading all pins from board...")

        scroll_pause_time = 3
        max_scrolls = 100
        scrolls = 0
        consecutive_no_change = 0
        last_count = 0

        while scrolls < max_scrolls and consecutive_no_change < 5:
            try:
                pins = page.locator('[data-test-id="pin"]').all()
                current_count = len(pins)

                if current_count != last_count:
                    print(f"Loaded {current_count} pins...")
                    consecutive_no_change = 0
                else:
                    consecutive_no_change += 1

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(scroll_pause_time * 1000)
                page.evaluate("window.scrollBy(0, 500)")
                page.wait_for_timeout(1000)

                last_count = current_count
                scrolls += 1

            except Exception as e:
                print(f"Error during scrolling: {e}")
                break

        try:
            final_pins = page.locator('[data-test-id="pin"]').all()
            final_count = len(final_pins)
            print(f"Finished loading. Found {final_count} total pins")

            if final_count < 50:
                print(
                    f"⚠️  Warning: Only found {final_count} pins. This seems low.")
                print("The page might not have loaded fully. Waiting longer...")
                page.wait_for_timeout(5000)
                final_pins = page.locator('[data-test-id="pin"]').all()
                print(f"After waiting: {len(final_pins)} pins")

            return final_pins
        except Exception as e:
            print(f"Error getting final pin count: {e}")
            return []

    def login_to_pinterest(self, page, username, password):
        """Attempt to login to Pinterest with credentials"""
        try:
            print("Attempting to log in to Pinterest...")
            page.goto("https://www.pinterest.com/login/")
            page.wait_for_timeout(2000)

            # Fill email
            email_input = page.locator('input[id="email"]')
            if email_input.is_visible(timeout=5000):
                email_input.fill(username)
                page.wait_for_timeout(500)

                # Fill password
                password_input = page.locator('input[id="password"]')
                password_input.fill(password)
                page.wait_for_timeout(500)

                # Click login button
                login_button = page.locator('button[type="submit"]').first
                login_button.click()

                print("Login credentials submitted. Waiting for login to complete...")
                page.wait_for_timeout(5000)

                # Check if login was successful
                if "pinterest.com/login" not in page.url:
                    print("✓ Login successful!")
                    return True
                else:
                    print("⚠ Login may have failed or requires verification")
                    return False
            else:
                print("Could not find login form")
                return False

        except Exception as e:
            print(f"Error during automated login: {e}")
            return False

    def download_images_from_board(self, board_url, headless=False, username=None, password=None):
        """Download all images from a Pinterest board"""
        with sync_playwright() as p:
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

            # Login
            if username and password:
                login_success = self.login_to_pinterest(
                    page, username, password)
                if not login_success and not headless:
                    input(
                        "\nPlease complete login manually in the browser and press Enter to continue...")
            else:
                print("Opening Pinterest login page...")
                page.goto("https://www.pinterest.com/login/")
                input(
                    "\nPlease log in to Pinterest in the browser window and press Enter to continue...")

            # Navigate to board
            print(f"\nOpening board: {board_url}")
            try:
                page.goto(board_url, timeout=60000,
                          wait_until='domcontentloaded')
                page.wait_for_timeout(5000)

                if "pinterest.com" not in page.url:
                    print(f"Warning: Redirected to {page.url}")
                    if not headless:
                        input(
                            "Please navigate to your board manually and press Enter to continue...")

                page.wait_for_selector('[data-test-id="pin"]', timeout=10000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Error loading board: {e}")
                print("Current URL:", page.url)
                if not headless:
                    input(
                        "Please navigate to your board manually in the browser and press Enter to continue...")

            # Load all pins
            pins = self.scroll_to_load_all_pins(page)
            total_pins = len(pins)

            if total_pins == 0:
                print(
                    "ERROR: No pins found! Make sure you're on the correct board page.")
                if not headless:
                    input("Press Enter to close...")
                browser.close()
                return

            downloaded = 0
            skipped = 0
            skipped_small = 0
            failed = 0

            board_page_url = page.url

            # Process each pin
            for idx in range(total_pins):
                try:
                    if board_page_url not in page.url:
                        print(
                            f"[{idx+1}/{total_pins}] Navigating back to board...")
                        page.goto(board_page_url)
                        page.wait_for_timeout(2000)
                        page.wait_for_selector(
                            '[data-test-id="pin"]', timeout=10000)

                    current_pins = page.locator('[data-test-id="pin"]').all()
                    if idx >= len(current_pins):
                        print(
                            f"[{idx+1}/{total_pins}] Pin index out of range, re-querying...")
                        page.wait_for_timeout(2000)
                        current_pins = page.locator(
                            '[data-test-id="pin"]').all()

                        if idx >= len(current_pins):
                            print(
                                f"[{idx+1}/{total_pins}] Pin no longer available")
                            failed += 1
                            continue

                    pin = current_pins[idx]
                    pin.scroll_into_view_if_needed()
                    page.wait_for_timeout(800)
                    pin.click()
                    page.wait_for_timeout(3000)

                    try:
                        page.wait_for_selector(
                            'img[src*="pinimg"]', timeout=8000)
                        img = page.locator('img[src*="pinimg"]').first
                        img_src = img.get_attribute('src')
                        img_hash = self.get_image_hash(img_src)

                        if img_hash in self.downloaded_hashes:
                            print(
                                f"[{idx+1}/{total_pins}] Skipping - already downloaded")
                            skipped += 1
                        elif img_hash in self.skipped_hashes:
                            print(
                                f"[{idx+1}/{total_pins}] Skipping - previously marked as too small")
                            skipped_small += 1
                        else:
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
                                    if more_button.is_visible(timeout=2000):
                                        break
                                except:
                                    continue

                            if not more_button:
                                print(
                                    f"[{idx+1}/{total_pins}] Failed - couldn't find More options button")
                                failed += 1
                            else:
                                more_button.click()
                                page.wait_for_timeout(1500)

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
                                        if download_button.is_visible(timeout=2000):
                                            break
                                    except:
                                        continue

                                if not download_button:
                                    print(
                                        f"[{idx+1}/{total_pins}] Failed - couldn't find Download button")
                                    failed += 1
                                else:
                                    with page.expect_download(timeout=30000) as download_info:
                                        download_button.click()

                                    download = download_info.value
                                    temp_path = os.path.join(
                                        self.output_folder, f"temp_{img_hash}")
                                    download.save_as(temp_path)

                                    file_size = os.path.getsize(temp_path)
                                    file_size_kb = file_size / 1024

                                    if file_size_kb < 70:
                                        os.remove(temp_path)
                                        self.skipped_hashes.add(img_hash)
                                        self.save_database()
                                        print(
                                            f"[{idx+1}/{total_pins}] Skipped - too small ({file_size_kb:.1f} KB)")
                                        skipped_small += 1
                                    else:
                                        original_name = download.suggested_filename
                                        new_filename = f"{img_hash}_{original_name}"
                                        final_path = os.path.join(
                                            self.output_folder, new_filename)
                                        os.rename(temp_path, final_path)

                                        self.downloaded_hashes.add(img_hash)
                                        self.save_database()

                                        print(
                                            f"[{idx+1}/{total_pins}] Downloaded: {new_filename} ({file_size_kb:.1f} KB)")
                                        downloaded += 1

                                    page.wait_for_timeout(1000)

                    except PlaywrightTimeout:
                        print(
                            f"[{idx+1}/{total_pins}] Failed - timeout waiting for elements")
                        failed += 1
                    except Exception as e:
                        print(f"[{idx+1}/{total_pins}] Failed - {str(e)}")
                        failed += 1

                    try:
                        page.go_back(wait_until='domcontentloaded')
                        page.wait_for_timeout(2000)
                        page.wait_for_selector(
                            '[data-test-id="pin"]', timeout=8000)
                    except Exception as e:
                        print(f"Warning: Error going back - {e}")
                        try:
                            page.goto(board_page_url)
                            page.wait_for_timeout(2000)
                        except:
                            pass

                except Exception as e:
                    print(
                        f"[{idx+1}/{total_pins}] Error processing pin: {str(e)}")
                    failed += 1

                    try:
                        if board_page_url not in page.url:
                            page.goto(board_page_url)
                            page.wait_for_timeout(2000)
                    except:
                        pass

            print("\n" + "="*50)
            print(f"Download complete!")
            print(f"Downloaded: {downloaded}")
            print(f"Skipped (already exists): {skipped}")
            print(f"Skipped (too small < 70KB): {skipped_small}")
            print(f"Failed: {failed}")
            print(f"Total pins processed: {total_pins}")
            print("="*50)

            if not headless:
                input("\nPress Enter to close the browser...")
            browser.close()


def main():
    print("Pinterest Board Image Downloader")
    print("="*50)

    # Get configuration from .env
    board_url = os.getenv('PINTEREST_BOARD_URL')
    output_folder_env = os.getenv('OUTPUT_FOLDER')
    headless_env = os.getenv('HEADLESS')
    username = os.getenv('PINTEREST_USERNAME')
    password = os.getenv('PINTEREST_PASSWORD')

    # ----------------------------
    # Board URL
    # ----------------------------
    if not board_url:
        board_url = input("Enter your Pinterest board URL: ").strip()
    else:
        print(f"Board URL: {board_url}")

    # ----------------------------
    # Output folder
    # ----------------------------
    if output_folder_env:
        output_folder = output_folder_env
    else:
        user_input = input(
            "Enter output folder name (default: pinterest_images): ").strip()
        output_folder = user_input if user_input else "pinterest_images"
    print(f"Output folder: {output_folder}")

    # ----------------------------
    # Headless mode
    # ----------------------------
    if headless_env is not None:
        headless = headless_env.lower() in ('true', '1', 'yes')
    else:
        user_input = input(
            "Run in headless mode? (y/n, default: n): ").strip().lower()
        headless = True if user_input == 'y' else False
    print(f"Headless mode: {headless}")

    # ----------------------------
    # Credentials notice
    # ----------------------------
    if not username or not password:
        print("\nNote: No credentials in .env file. Manual login will be required.")
    else:
        print("\nNote: Credentials found in .env file. Will attempt automatic login.")

    # ----------------------------
    # Start download
    # ----------------------------
    downloader = PinterestDownloader(output_folder=output_folder)

    try:
        downloader.download_images_from_board(
            board_url, headless=headless, username=username, password=password)
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
