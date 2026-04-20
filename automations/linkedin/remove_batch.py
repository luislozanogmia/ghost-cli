"""
remove_batch.py — Standalone LinkedIn connection remover (background-safe)
==========================================================================
Uses exported Playwright auth state. Runs independently, logs to file.
Can be stopped with Ctrl+C. Designed to run in bash background.

Usage:
  python remove_batch.py --url <recruiter_profile_url> --count 50 [--delay 3]
  python remove_batch.py --url <recruiter_profile_url> --count 300 --delay 4
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AUTH_STATE = str(Path(__file__).parent / "playwright_auth.json")
LOG_FILE = str(Path(__file__).parent / "remove_batch.log")
DEFAULT_DELAY = 3

# ---------------------------------------------------------------------------
# Logging — both file and console
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("remove_batch")


def wait(seconds: float):
    time.sleep(seconds)


def get_profile_name(page: Page) -> str:
    return page.evaluate("""() => {
        const h1s = document.querySelectorAll('h1');
        for (const h1 of h1s) {
            const t = h1.textContent.trim();
            if (t && !t.includes('search results') && !t.includes('Pagination') && !t.includes('Showing result')) return t;
        }
        // Fallback: try profile name selectors
        const el = document.querySelector('[data-test-profile-name], .profile-heading, .artdeco-entity-lockup__title');
        if (el) return el.textContent.trim();
        return '(unknown)';
    }""")


def dismiss_tooltip(page: Page):
    page.evaluate("""() => {
        document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Public profile') &&
                btn.getAttribute('aria-expanded') === 'true') btn.click();
        }
    }""")
    wait(1)


def get_public_url(page: Page, delay: float) -> str | None:
    """Extract public profile URL via tooltip with stale-URL protection."""
    dismiss_tooltip(page)

    # Snapshot existing /in/ links
    existing = page.evaluate("""() => {
        const urls = new Set();
        document.querySelectorAll('a[href*="/in/"]').forEach(a => urls.add(a.getAttribute('href')));
        return Array.from(urls);
    }""")

    # Click "Public profile" button
    clicked = page.evaluate("""() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Public profile')) { btn.click(); return true; }
        }
        return false;
    }""")

    if not clicked:
        return None

    wait(delay)

    # Extract NEW /in/ link
    url = page.evaluate("""(existing) => {
        const existSet = new Set(existing);
        const btn = Array.from(document.querySelectorAll('button'))
            .find(b => b.textContent.trim().includes('Public profile'));
        if (btn) {
            const popupId = btn.getAttribute('aria-controls');
            if (popupId) {
                const popup = document.getElementById(popupId);
                if (popup) {
                    const link = popup.querySelector('a[href*="/in/"]');
                    if (link) return link.getAttribute('href');
                }
            }
            const parent = btn.closest('[class*="popover"], [class*="tooltip"], [class*="dropdown"], [role="tooltip"], [role="dialog"]') || btn.parentElement;
            if (parent) {
                const link = parent.querySelector('a[href*="/in/"]');
                if (link && !existSet.has(link.getAttribute('href'))) return link.getAttribute('href');
            }
        }
        const allLinks = document.querySelectorAll('a[href*="/in/"]');
        for (const link of allLinks) {
            const href = link.getAttribute('href');
            if (href && href.includes('/in/') && !existSet.has(href)) return href;
        }
        if (allLinks.length > 0) return allLinks[allLinks.length - 1].getAttribute('href');
        return null;
    }""", existing)

    # Close tooltip
    page.keyboard.press("Escape")
    wait(0.5)

    if url and url.startswith("/"):
        url = "https://www.linkedin.com" + url

    return url


def remove_in_new_tab(context: BrowserContext, public_url: str, delay: float) -> str:
    """Open profile in new tab, click More > Remove Connection. Returns status string."""
    new_page = context.new_page()
    try:
        new_page.goto(public_url, wait_until="domcontentloaded", timeout=30000)
        wait(delay)

        # Click "More"
        more_clicked = new_page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            for (let i = 5; i < Math.min(buttons.length, 15); i++) {
                if (buttons[i].textContent.trim() === 'More') { buttons[i].click(); return true; }
            }
            for (const btn of buttons) {
                if (btn.textContent.trim() === 'More') { btn.click(); return true; }
            }
            return false;
        }""")

        if not more_clicked:
            return "FAIL:no_more_btn"

        wait(delay)

        # Click "Remove Connection" with retry
        for attempt in range(3):
            result = new_page.evaluate("""() => {
                const spans = document.querySelectorAll('span.display-flex.t-normal.flex-1');
                for (const span of spans) {
                    if (span.textContent.trim() === 'Remove Connection') { span.click(); return 'REMOVED'; }
                }
                const allSpans = document.querySelectorAll('span');
                for (const span of allSpans) {
                    if (span.textContent.trim() === 'Remove Connection') { span.click(); return 'REMOVED'; }
                }
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === 'Connect') return 'SKIP:not_connected';
                }
                return null;
            }""")
            if result:
                return result
            wait(2)

        return "FAIL:no_remove_option"

    except Exception as e:
        return f"FAIL:{str(e)[:80]}"
    finally:
        try:
            new_page.close()
        except Exception:
            pass


def click_next(page: Page, delay: float) -> bool:
    """Click Next candidate. Returns True if successful."""
    page.bring_to_front()
    wait(1)

    result = page.evaluate("""() => {
        const links = document.querySelectorAll('a');
        for (const l of links) {
            const t = l.textContent.trim();
            if (t === 'Next candidate' || t === 'Next') { l.click(); return 'link'; }
        }
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const t = btn.textContent.trim();
            if (t === 'Next candidate' || t === 'Next') { btn.click(); return 'button'; }
        }
        const ariaNext = document.querySelector('[aria-label="Next candidate"], [aria-label="Next"]');
        if (ariaNext) { ariaNext.click(); return 'aria'; }
        return null;
    }""")

    if result:
        wait(delay)
        return True

    log.warning("  Next button not found. Trying keyboard shortcut...")
    # Fallback: try right arrow key
    page.keyboard.press("ArrowRight")
    wait(delay)

    # Check if page changed
    return True  # optimistic — we'll catch failures on the next iteration


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Background LinkedIn connection remover")
    parser.add_argument("--url", type=str, required=True, help="Recruiter profile detail URL")
    parser.add_argument("--count", type=int, default=50, help="Number of profiles to process")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between actions (seconds)")
    args = parser.parse_args()

    # Single-instance lock — prevent two copies from fighting over profiles
    lock_path = Path(__file__).parent / "remove_batch.lock"
    if lock_path.exists():
        old_pid = lock_path.read_text().strip()
        # Check if that PID is still alive
        import subprocess
        result = subprocess.run(["tasklist", "/FI", f"PID eq {old_pid}"], capture_output=True, text=True)
        if old_pid in result.stdout:
            log.error(f"Another instance is running (PID {old_pid}). Kill it first or delete {lock_path}")
            sys.exit(1)
        else:
            log.info(f"Stale lock from PID {old_pid} — removing.")
    lock_path.write_text(str(os.getpid()))

    auth_path = Path(AUTH_STATE)
    if not auth_path.exists():
        log.error(f"Auth file not found: {auth_path}")
        log.error("Run: playwright MCP browser_run_code to export storageState first")
        lock_path.unlink(missing_ok=True)
        sys.exit(1)

    log.info(f"Starting: count={args.count}, delay={args.delay}s")
    log.info(f"Auth: {auth_path}")
    log.info(f"Log: {LOG_FILE}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(auth_path),
            no_viewport=True,  # Don't force window size — let the OS handle it
        )
        page = context.new_page()

        log.info(f"Navigating to: {args.url[:120]}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        wait(args.delay)

        # Check we're on a profile detail page
        actual_url = page.evaluate("() => window.location.href")
        log.info(f"Landed on: {actual_url[:120]}")

        if "/talent/search/profile/" not in actual_url:
            log.error("Not on Recruiter profile detail view. Check auth or URL.")
            browser.close()
            sys.exit(1)

        removed = 0
        skipped = 0
        failed = 0

        try:
            for i in range(1, args.count + 1):
                name = get_profile_name(page)
                log.info(f"[{i}/{args.count}] {name}")

                public_url = get_public_url(page, args.delay)
                if not public_url:
                    log.warning(f"  SKIP: no public URL")
                    skipped += 1
                    if i < args.count:
                        click_next(page, args.delay)
                    continue

                log.info(f"  URL: {public_url}")
                result = remove_in_new_tab(context, public_url, args.delay)

                if result == "REMOVED":
                    log.info(f"  REMOVED")
                    removed += 1
                elif result.startswith("SKIP"):
                    log.info(f"  {result}")
                    skipped += 1
                else:
                    log.warning(f"  {result}")
                    failed += 1

                # Back to recruiter page — verify we're on the right tab
                page.bring_to_front()
                wait(1)
                current_url = page.evaluate("() => window.location.href")
                if "/talent/search" not in current_url:
                    log.warning(f"  Tab drifted to: {current_url[:80]}. Navigating back...")
                    page.go_back()
                    wait(args.delay)

                if i < args.count:
                    if not click_next(page, args.delay):
                        log.error("  Cannot advance. Stopping.")
                        break

                # Recovery cycle every 8 profiles: Esc → hard refresh → wait → select first → wait
                if i % 8 == 0 and i < args.count:
                    log.info(f"  --- Recovery cycle at {i} ---")
                    page.keyboard.press("Escape")
                    wait(1)
                    page.keyboard.press("Control+Shift+r")
                    wait(5)
                    # Click first profile in search results to re-enter detail view
                    page.evaluate("""() => {
                        const links = document.querySelectorAll('a[href*="/talent/profile/"]');
                        if (links.length > 0) links[0].click();
                    }""")
                    wait(5)
                    log.info(f"  --- Recovery done, continuing ---")

                # Progress summary every 25
                if i % 25 == 0:
                    log.info(f"  --- Progress: {removed} removed | {skipped} skipped | {failed} failed | {i}/{args.count} ---")

        except KeyboardInterrupt:
            log.info("\nInterrupted by user.")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
        finally:
            log.info("")
            log.info(f"{'='*60}")
            log.info(f"DONE: {removed} removed | {skipped} skipped | {failed} failed | {removed+skipped+failed}/{args.count}")
            log.info(f"{'='*60}")
            browser.close()
            lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
