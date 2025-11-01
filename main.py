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
import random

# Load environment variables
load_dotenv()


class PinterestDownloader:
    def __init__(self, output_folder="pinterest_images"):
        self.output_folder = output_folder
        Path(output_folder).mkdir(parents=True, exist_ok=True)
        self.downloaded_hashes = set()
        self.skipped_hashes = set()
        self.db_file = ".pinterest_db.json"
        self.load_database()

    def load_database(self):
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
        db = {
            'downloaded': list(self.downloaded_hashes),
            'skipped': list(self.skipped_hashes)
        }
        with open(self.db_file, 'w') as f:
            json.dump(db, f, indent=2)

    def get_image_hash(self, img_url):
        return hashlib.md5(img_url.encode()).hexdigest()[:12]

    def login_to_pinterest(self, page, username, password):
        try:
            print("Attempting to log in to Pinterest...")
            page.goto("https://www.pinterest.com/login/")
            page.wait_for_timeout(random.randint(1500, 2500))

            email_input = page.locator('input[id="email"]')
            if email_input.is_visible(timeout=5000):
                email_input.fill(username)
                page.wait_for_timeout(random.randint(300, 600))

                password_input = page.locator('input[id="password"]')
                password_input.fill(password)
                page.wait_for_timeout(random.randint(300, 600))

                login_button = page.locator('button[type="submit"]').first
                login_button.click()

                print("Login credentials submitted. Waiting for login to complete...")
                page.wait_for_timeout(random.randint(4000, 6000))

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

    def download_pin(self, page, pin, idx, board_url):
        current_scroll = page.evaluate("window.scrollY")
        outcome = "Failed"
        try:
            try:
                pin.scroll_into_view_if_needed()
                page.wait_for_timeout(random.randint(400, 900))
                pin.click()
            except:
                page.wait_for_timeout(random.randint(400, 900))
                pin.scroll_into_view_if_needed()
                pin.click()

            page.wait_for_timeout(random.randint(1000, 2000))

            # Check for new tabs (ads/popups) and close them
            if len(page.context.pages) > 1:
                for p in page.context.pages[1:]:
                    print(f"[Pin {idx}] Closing unexpected new tab (ad)")
                    p.close()
                page.bring_to_front()

            img = page.locator('img[src*="pinimg"]').first
            img_src = img.get_attribute('src')
            img_hash = self.get_image_hash(img_src)

            if img_hash in self.downloaded_hashes:
                outcome = "Skipped (already downloaded)"
            elif img_hash in self.skipped_hashes:
                outcome = "Skipped (too small)"
            else:
                more_button = None
                for selector in ['[aria-label="More options"]', '[data-test-id="more-options-button"]',
                                 'button:has-text("More")', '[aria-label="More actions"]']:
                    try:
                        more_button = page.locator(selector).first
                        if more_button.is_visible(timeout=1000):
                            break
                    except:
                        continue

                if not more_button:
                    outcome = "Failed (No More options button)"
                else:
                    more_button.click()
                    page.wait_for_timeout(random.randint(300, 600))  # faster

                    download_button = None
                    for selector in ['text="Download image"', 'text="Download"',
                                     '[data-test-id="download-button"]', 'div:has-text("Download image")']:
                        try:
                            download_button = page.locator(selector).first
                            if download_button.is_visible(timeout=1000):
                                break
                        except:
                            continue

                    if not download_button:
                        outcome = "Failed (No Download button)"
                    else:
                        with page.expect_download(timeout=20000) as download_info:
                            download_button.click()
                        download = download_info.value

                        temp_path = os.path.join(
                            self.output_folder, f"temp_{img_hash}")
                        download.save_as(temp_path)
                        file_size_kb = os.path.getsize(temp_path) / 1024

                        if file_size_kb < 70:
                            os.remove(temp_path)
                            self.skipped_hashes.add(img_hash)
                            self.save_database()
                            outcome = f"Skipped (too small {file_size_kb:.1f} KB)"
                        else:
                            new_filename = f"{img_hash}_{download.suggested_filename}"
                            final_path = os.path.join(
                                self.output_folder, new_filename)
                            os.rename(temp_path, final_path)
                            self.downloaded_hashes.add(img_hash)
                            self.save_database()
                            outcome = f"Downloaded ({file_size_kb:.1f} KB)"

        except Exception as e:
            outcome = f"Failed ({str(e)})"
        finally:
            try:
                page.go_back(wait_until='domcontentloaded')
                page.wait_for_timeout(random.randint(500, 900))
                page.evaluate(f"window.scrollTo(0, {current_scroll})")
                page.wait_for_timeout(random.randint(300, 700))

                # Ensure we returned to the board page
                if board_url not in page.url:
                    raise Exception(
                        f"Did not return to board page! Current URL: {page.url}")

            except Exception as e:
                print(f"[Pin {idx}] ERROR: {e}")
                raise e

        print(f"[Pin {idx}] Clicked → {outcome}")
        return outcome.startswith("Downloaded")

    def download_images_from_board(self, board_url, headless=False, username=None, password=None):
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

            if username and password:
                login_success = self.login_to_pinterest(
                    page, username, password)
                if not login_success and not headless:
                    input(
                        "\nPlease complete login manually in the browser and press Enter to continue...")
            else:
                page.goto("https://www.pinterest.com/login/")
                input(
                    "\nPlease log in to Pinterest manually and press Enter to continue...")

            page.goto(board_url, timeout=60000, wait_until='domcontentloaded')
            page.wait_for_timeout(random.randint(2000, 3000))

            print("Starting scrolling & downloading pins...")
            seen_hashes = set()
            downloaded_count = 0
            failed_count = 0
            idx = 1
            scroll_pause_time = 1.2

            while True:
                pins = page.locator('[data-test-id="pin"]').all()
                new_pin_found = False

                for pin in pins:
                    img = pin.locator('img[src*="pinimg"]').first
                    img_src = img.get_attribute('src')
                    img_hash = self.get_image_hash(img_src)
                    if img_hash not in seen_hashes:
                        new_pin_found = True
                        seen_hashes.add(img_hash)
                        success = self.download_pin(
                            page, pin, idx, board_url)
                        if success:
                            downloaded_count += 1
                        else:
                            failed_count += 1
                        idx += 1

                # Double the scroll amount
                scroll_amount = page.evaluate(
                    "window.innerHeight * 2")  # doubled scroll
                page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                page.wait_for_timeout(random.randint(
                    int(scroll_pause_time*800), int(scroll_pause_time*1200)))

                if not new_pin_found:
                    print("No new pins detected. Finished scrolling.")
                    break

            print("\n" + "="*50)
            print(f"Downloaded: {downloaded_count}")
            print(f"Failed downloads: {failed_count}")
            print(f"Total pins seen: {len(seen_hashes)}")
            print("="*50)

            if not headless:
                input("\nPress Enter to close the browser...")
            browser.close()


def main():
    print("Pinterest Board Image Downloader")
    print("="*50)

    board_url = os.getenv('PINTEREST_BOARD_URL')
    output_folder_env = os.getenv('OUTPUT_FOLDER')
    headless_env = os.getenv('HEADLESS')
    username = os.getenv('PINTEREST_USERNAME')
    password = os.getenv('PINTEREST_PASSWORD')

    if not board_url:
        board_url = input("Enter your Pinterest board URL: ").strip()
    print(f"Board URL: {board_url}")

    output_folder = output_folder_env if output_folder_env else "pinterest_images"
    print(f"Output folder: {output_folder}")

    headless = headless_env.lower() in ('true', '1', 'yes') if headless_env else False
    print(f"Headless: {headless}")

    downloader = PinterestDownloader(output_folder=output_folder)

    try:
        downloader.download_images_from_board(
            board_url, headless=headless, username=username, password=password
        )
    except KeyboardInterrupt:
        print("\nDownload interrupted by user")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
