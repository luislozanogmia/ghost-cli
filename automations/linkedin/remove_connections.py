"""
remove_connections.py v2 — LinkedIn connection remover via Recruiter search
===========================================================================
Standalone Playwright script. Navigates Recruiter search results, extracts
public profile URLs via the "Public profile" tooltip, opens each in a new
tab, clicks More -> Remove Connection, then advances to the next candidate.

Proven flow (all selectors verified via live testing):
  1. From Recruiter detail view, click "Public profile" button
  2. Read the /in/ slug from the tooltip popup link
  3. Open new tab -> navigate to public profile URL
  4. Click "More" button (page.evaluate, NOT locators — LinkedIn's dynamic
     elements cause timeouts with Playwright locators)
  5. Click "Remove Connection" menu item (page.evaluate)
  6. Close tab, click "Next candidate", repeat

Usage:
  python remove_connections.py --url <recruiter_search_url> [--count 10] [--dry-run] [--delay 3]

Requirements:
  - pip install playwright && playwright install chromium
  - User must be logged into LinkedIn in the persistent browser context
"""

from __future__ import annotations

import argparse
import sys
import time
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Playwright MCP's browser context — has LinkedIn auth cookies
MCP_BROWSER_CONTEXT_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent / "playwright" / "browser_context"
)

DEFAULT_DELAY = 3        # seconds between actions
ACTION_TIMEOUT = 15000   # ms for page loads and waits

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("remove_connections")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait(seconds: float):
    """Delay between actions for rate-limiting and page settling."""
    time.sleep(seconds)


def close_extra_tabs(context: BrowserContext, keep: Page):
    """Close every tab except the one we want to keep."""
    for p in context.pages:
        if p != keep:
            try:
                p.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Step 0: Navigate to search URL and click first profile
# ---------------------------------------------------------------------------

def step_handle_contract_chooser(page: Page, delay: float) -> bool:
    """If LinkedIn redirected to contract chooser, select Recruiter Lite."""
    is_chooser = page.evaluate("""() => {
        return window.location.href.includes('contract-chooser');
    }""")
    if not is_chooser:
        return True  # not on contract chooser, nothing to do

    log.info("Detected contract chooser page. Selecting Recruiter Lite...")
    selected = page.evaluate("""() => {
        // Find the card/link containing "Recruiter Lite"
        const links = document.querySelectorAll('a');
        for (const link of links) {
            if (link.textContent.includes('Recruiter Lite')) {
                link.click();
                return true;
            }
        }
        // Try buttons
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.includes('Recruiter Lite')) {
                btn.click();
                return true;
            }
        }
        // Try any clickable element
        const all = document.querySelectorAll('[role="radio"], [role="option"], [class*="contract"]');
        for (const el of all) {
            if (el.textContent.includes('Recruiter Lite') || el.textContent.includes('Lite')) {
                el.click();
                return true;
            }
        }
        return false;
    }""")

    if not selected:
        log.error("Could not find 'Recruiter Lite' on contract chooser.")
        return False

    log.info("Selected Recruiter Lite. Waiting for navigation...")
    wait(delay * 2)
    return True


def step_navigate_and_enter_detail(page: Page, url: str, delay: float) -> bool:
    """Navigate to the Recruiter search URL and click the first profile."""
    log.info(f"Navigating to: {url[:120]}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # Wait for SPA redirects to settle (LinkedIn redirects to contract chooser etc.)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass  # timeout is OK, page might never fully idle
    wait(delay)

    # Debug: log where we actually landed
    actual_url = page.evaluate("() => window.location.href")
    log.info(f"Landed on: {actual_url[:150]}")

    # Handle contract chooser redirect
    if not step_handle_contract_chooser(page, delay):
        return False

    # If URL already points to a profile detail view, skip clicking first profile
    is_detail = page.evaluate("""() => {
        return window.location.href.includes('/talent/search/profile/');
    }""")
    if is_detail:
        log.info("Already on profile detail view.")
        return True

    # Click the first profile link in the search results list
    log.info("Clicking first profile in search results...")
    clicked = page.evaluate("""() => {
        const links = document.querySelectorAll('a[href*="/talent/profile/"]');
        if (links.length === 0) return false;
        links[0].click();
        return true;
    }""")

    if not clicked:
        log.error("No profile links found on the search results page.")
        return False

    log.info("Entered profile detail view.")
    wait(delay)
    return True


# ---------------------------------------------------------------------------
# Step 1: Extract public profile URL from Recruiter detail view
# ---------------------------------------------------------------------------

def step_get_public_url(page: Page, delay: float) -> str | None:
    """
    Click "Public profile" button, read the /in/ slug from the tooltip,
    then close the tooltip. Returns the full public profile URL or None.

    v3 fix: dismiss stale tooltips first, then scope link search to the
    freshly-opened tooltip container (not the whole page). This prevents
    LinkedIn's SPA from serving cached /in/ URLs from previous profiles.
    """
    # --- Phase 0: Dismiss any stale tooltip left from previous iteration ---
    page.evaluate("""() => {
        // Press Escape to close any open popover/tooltip
        document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        // Also try toggling the button off if it's aria-expanded
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Public profile') &&
                btn.getAttribute('aria-expanded') === 'true') {
                btn.click();
            }
        }
    }""")
    wait(1)

    # --- Phase 1: Snapshot existing /in/ links BEFORE opening tooltip ---
    existing_urls = page.evaluate("""() => {
        const urls = new Set();
        document.querySelectorAll('a[href*="/in/"]').forEach(a => {
            urls.add(a.getAttribute('href'));
        });
        return Array.from(urls);
    }""")

    # --- Phase 2: Click "Public profile" button ---
    clicked = page.evaluate("""() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Public profile')) {
                btn.click();
                return true;
            }
        }
        return false;
    }""")

    if not clicked:
        log.error("  Could not find 'Public profile' button.")
        return None

    log.info("  Clicked 'Public profile' button.")
    wait(delay)

    # --- Phase 3: Find the NEW /in/ link (not in the pre-existing set) ---
    url = page.evaluate("""(existingUrls) => {
        const existing = new Set(existingUrls);
        // Strategy A: Look inside aria-expanded tooltip container
        const btn = Array.from(document.querySelectorAll('button'))
            .find(b => b.textContent.trim().includes('Public profile'));
        if (btn) {
            // Check aria-controls for the popup ID
            const popupId = btn.getAttribute('aria-controls');
            if (popupId) {
                const popup = document.getElementById(popupId);
                if (popup) {
                    const link = popup.querySelector('a[href*="/in/"]');
                    if (link) return link.getAttribute('href');
                }
            }
            // Check next sibling / parent for a popup container
            const parent = btn.closest('[class*="popover"], [class*="tooltip"], [class*="dropdown"], [role="tooltip"], [role="dialog"]')
                || btn.parentElement;
            if (parent) {
                const link = parent.querySelector('a[href*="/in/"]');
                if (link && !existing.has(link.getAttribute('href'))) {
                    return link.getAttribute('href');
                }
            }
        }
        // Strategy B: Find any /in/ link that is NEW (wasn't there before the click)
        const allLinks = document.querySelectorAll('a[href*="/in/"]');
        for (const link of allLinks) {
            const href = link.getAttribute('href');
            if (href && href.includes('/in/') && !existing.has(href)) {
                return href;
            }
        }
        // Strategy C: Last resort — get the LAST /in/ link (most recently added to DOM)
        if (allLinks.length > 0) {
            return allLinks[allLinks.length - 1].getAttribute('href');
        }
        return null;
    }""", existing_urls)

    if not url:
        log.error("  Could not find /in/ link in tooltip popup.")
        # Close tooltip before returning
        page.keyboard.press("Escape")
        wait(0.5)
        return None

    # Normalize: ensure it's a full URL
    if url.startswith("/"):
        url = "https://www.linkedin.com" + url
    elif not url.startswith("http"):
        url = "https://www.linkedin.com/in/" + url

    log.info(f"  Extracted public URL: {url}")

    # --- Phase 4: Close the tooltip cleanly ---
    page.keyboard.press("Escape")
    wait(0.5)
    # Double-check: if still expanded, click button to toggle off
    page.evaluate("""() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.trim().includes('Public profile') &&
                btn.getAttribute('aria-expanded') === 'true') {
                btn.click();
            }
        }
    }""")
    wait(0.5)

    return url


# ---------------------------------------------------------------------------
# Step 2: Get profile name from Recruiter detail view
# ---------------------------------------------------------------------------

def get_profile_name(page: Page) -> str:
    """Extract the profile name from the Recruiter detail page header."""
    name = page.evaluate("""() => {
        // Try h1 first (most common in Recruiter detail)
        const h1 = document.querySelector('h1');
        if (h1 && h1.textContent.trim()) return h1.textContent.trim();
        // Try profile name heading
        const heading = document.querySelector('[data-test-profile-name], .profile-heading');
        if (heading && heading.textContent.trim()) return heading.textContent.trim();
        return null;
    }""")
    return name or "(unknown)"


# ---------------------------------------------------------------------------
# Step 3: Open public profile in new tab and remove connection
# ---------------------------------------------------------------------------

def step_remove_in_new_tab(
    context: BrowserContext,
    main_page: Page,
    public_url: str,
    dry_run: bool,
    delay: float,
) -> bool:
    """
    Open public_url in a new tab, click More -> Remove Connection, close tab.
    Uses page.evaluate() for all button clicks (proven reliable vs locators).
    Returns True if removal succeeded (or dry-run skipped).
    """
    new_page = context.new_page()
    try:
        log.info(f"  Opening new tab: {public_url}")
        new_page.goto(public_url, wait_until="domcontentloaded", timeout=30000)
        wait(delay)

        # --- Click "More" button ---
        # The correct "More" button is the one in the profile action bar,
        # typically the 7th-11th button on the page. We find the first button
        # whose trimmed text is exactly "More" among buttons after index 5.
        more_clicked = new_page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            for (let i = 5; i < Math.min(buttons.length, 15); i++) {
                const text = buttons[i].textContent.trim();
                if (text === 'More') {
                    buttons[i].click();
                    return true;
                }
            }
            // Fallback: find any button with exact text "More"
            for (const btn of buttons) {
                if (btn.textContent.trim() === 'More') {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if not more_clicked:
            log.error("  Could not find 'More' button on public profile.")
            return False

        log.info("  Clicked 'More' button.")
        wait(delay)

        # --- Click "Remove Connection" (with retry for dropdown render) ---
        if dry_run:
            log.info("  [DRY RUN] Would click 'Remove Connection' -- skipping.")
            return True

        remove_clicked = False
        for attempt in range(3):
            remove_clicked = new_page.evaluate("""() => {
                // Primary: LinkedIn uses span.display-flex.t-normal.flex-1 for dropdown items
                const spans = document.querySelectorAll('span.display-flex.t-normal.flex-1');
                for (const span of spans) {
                    if (span.textContent.trim() === 'Remove Connection') {
                        span.click();
                        return 'removed';
                    }
                }
                // Fallback: any span with exact text
                const allSpans = document.querySelectorAll('span');
                for (const span of allSpans) {
                    if (span.textContent.trim() === 'Remove Connection') {
                        span.click();
                        return 'removed';
                    }
                }
                // Check if already not connected (Connect button visible = not a connection)
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === 'Connect') {
                        return 'not_connected';
                    }
                }
                return null;
            }""")
            if remove_clicked:
                break
            log.info(f"  Retry {attempt + 1}/3: dropdown may still be rendering...")
            wait(2)

        if remove_clicked == "not_connected":
            log.info("  Already not connected (Connect button visible). Skipping.")
            return True  # not an error, just already disconnected

        if not remove_clicked:
            log.error("  Could not find 'Remove Connection' menu item after 3 attempts.")
            return False

        log.info("  Clicked 'Remove Connection'. (No confirmation dialog expected.)")
        wait(delay)
        return True

    except Exception as e:
        log.error(f"  Error in new tab: {e}")
        return False

    finally:
        try:
            new_page.close()
            log.info("  Closed public profile tab.")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Step 4: Navigate to next candidate
# ---------------------------------------------------------------------------

def step_next_candidate(page: Page, delay: float) -> bool:
    """Click 'Next candidate' link on the Recruiter detail view."""
    # Bring page to front and wait for it to be ready
    try:
        page.bring_to_front()
    except Exception:
        pass
    wait(2)

    clicked = page.evaluate("""() => {
        // Try links — match "Next candidate" or just "Next"
        const links = document.querySelectorAll('a');
        for (const link of links) {
            const t = link.textContent.trim();
            if (t === 'Next candidate' || t === 'Next') {
                link.click();
                return 'link';
            }
        }
        // Try buttons
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const t = btn.textContent.trim();
            if (t === 'Next candidate' || t === 'Next') {
                btn.click();
                return 'button';
            }
        }
        // Try aria-label
        const ariaNext = document.querySelector('[aria-label="Next candidate"], [aria-label="Next"]');
        if (ariaNext) {
            ariaNext.click();
            return 'aria';
        }
        // Debug: report current URL and any navigation-related links
        const navLinks = [];
        for (const link of links) {
            const t = link.textContent.trim();
            if (t.includes('candidate') || t.includes('Next') || t.includes('Previous') || t.includes('Back'))
                navLinks.push(t.substring(0, 50));
        }
        return JSON.stringify({url: window.location.href.substring(0, 80), navLinks});
    }""")

    if clicked in ('link', 'button', 'aria'):
        log.info(f"  Clicked 'Next candidate' ({clicked}).")
        wait(delay)
        return True

    log.error(f"  Could not find 'Next candidate'. Debug: {clicked}")
    return False

    log.info("  Clicked 'Next candidate'.")
    wait(delay)
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def remove_connections_loop(
    page: Page,
    context: BrowserContext,
    count: int,
    dry_run: bool,
    delay: float,
):
    """
    Main loop. Assumes we're on a Recruiter detail view (first profile).
    For each profile: extract public URL, open in new tab, remove connection,
    close tab, click Next candidate.
    """
    removed = 0
    skipped = 0

    log.info(f"Starting removal loop: count={count}, dry_run={dry_run}, delay={delay}s")
    log.info(f"Current page: {page.url[:120]}")

    for i in range(1, count + 1):
        name = get_profile_name(page)
        log.info("")
        log.info(f"{'='*60}")
        log.info(f"Profile {i}/{count}: {name}")
        log.info(f"{'='*60}")

        # Step 1: Get public profile URL
        public_url = step_get_public_url(page, delay)
        if not public_url:
            log.warning(f"  SKIP: Could not extract public URL for {name}")
            skipped += 1
            close_extra_tabs(context, page)
            if i < count and not step_next_candidate(page, delay):
                log.error("  Cannot advance to next candidate. Stopping.")
                break
            continue

        # Step 2: Open new tab, remove connection, close tab
        success = step_remove_in_new_tab(context, page, public_url, dry_run, delay)
        close_extra_tabs(context, page)
        wait(1)  # let Recruiter tab regain focus

        if success:
            if dry_run:
                log.info(f"  [DRY RUN] Would have removed: {name}")
            else:
                log.info(f"  REMOVED: {name}")
                removed += 1
        else:
            log.warning(f"  FAILED to remove: {name}")
            skipped += 1

        # Step 3: Next candidate (skip on last iteration)
        if i < count:
            if not step_next_candidate(page, delay):
                log.error("  Cannot advance to next candidate. Stopping.")
                break

    # Summary
    log.info("")
    log.info(f"{'='*60}")
    log.info(f"DONE -- Removed: {removed} | Skipped: {skipped} | Attempted: {removed + skipped}/{count}")
    if dry_run:
        log.info("(Dry run -- no connections were actually removed)")
    log.info(f"{'='*60}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Remove LinkedIn connections from Recruiter search results. "
                    "Uses Playwright with a persistent browser context."
    )
    parser.add_argument(
        "--url", type=str, default="",
        help="LinkedIn Recruiter search results URL (the list view page)"
    )
    parser.add_argument(
        "--count", type=int, default=10,
        help="Number of connections to remove (default: 10)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk through the flow but skip the actual 'Remove Connection' click"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Seconds to wait between actions (default: {DEFAULT_DELAY})"
    )
    parser.add_argument(
        "--context-dir", type=str, default=MCP_BROWSER_CONTEXT_DIR,
        help=f"Path to Playwright persistent browser context (default: {MCP_BROWSER_CONTEXT_DIR})"
    )
    parser.add_argument(
        "--login", action="store_true",
        help="Open browser for manual login. Auth is saved to context-dir for future runs."
    )
    args = parser.parse_args()

    context_dir = Path(args.context_dir)

    if not args.login and not args.url:
        parser.error("--url is required (unless using --login)")

    log.info(f"Browser context: {context_dir}")
    log.info(f"Target count: {args.count} | Dry run: {args.dry_run} | Delay: {args.delay}s")

    with sync_playwright() as pw:
        browser = None
        connected_via_cdp = False

        # --- Login mode: open browser, wait for user to log in, then exit ---
        if args.login:
            log.info("LOGIN MODE: Opening browser for manual login...")
            log.info(f"Context dir: {context_dir}")
            ctx = pw.chromium.launch_persistent_context(
                str(context_dir),
                headless=False,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                viewport={"width": 1400, "height": 900},
                timeout=30000,
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
            log.info("Please log in to LinkedIn in the browser window.")
            log.info("Waiting up to 120s for login (auto-detects redirect from /login)...")
            for _ in range(120):
                current = page.evaluate("() => window.location.href")
                if "/login" not in current and "/uas/" not in current and "/checkpoint/" not in current:
                    log.info(f"Login detected! Redirected to: {current[:100]}")
                    break
                time.sleep(1)
            else:
                log.warning("Timeout waiting for login. Saving context anyway.")
            wait(2)  # let cookies settle
            log.info("Auth saved. You can now run the script without --login.")
            ctx.close()
            sys.exit(0)

        # --- Strategy 1: Connect to existing Chrome via CDP ---
        # If Playwright MCP (or another tool) already has Chrome running,
        # DevToolsActivePort contains the CDP port. Connect to it.
        dta_path = context_dir / "DevToolsActivePort"
        if dta_path.exists():
            try:
                port = int(dta_path.read_text().strip().split("\n")[0])
                log.info(f"Found running Chrome on CDP port {port}. Connecting...")
                browser = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                context = browser.contexts[0]
                connected_via_cdp = True
                log.info("Connected to existing Chrome via CDP.")
            except Exception as e:
                log.warning(f"CDP connection failed ({e}). Will launch own browser.")
                browser = None

        # --- Strategy 2: Launch own browser from same context dir ---
        if not connected_via_cdp:
            log.info("Launching own Chrome instance...")
            context = pw.chromium.launch_persistent_context(
                str(context_dir),
                headless=False,
                channel="chrome",  # use system Chrome, same as Playwright MCP
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                viewport={"width": 1400, "height": 900},
                timeout=30000,
            )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            # Navigate to search URL and click first profile to enter detail view
            if not step_navigate_and_enter_detail(page, args.url, args.delay):
                log.error("Could not enter Recruiter profile detail view. Exiting.")
                if connected_via_cdp:
                    browser.close()  # disconnect only, Chrome stays alive
                else:
                    context.close()
                sys.exit(1)

            # Run the removal loop
            remove_connections_loop(page, context, args.count, args.dry_run, args.delay)

        except KeyboardInterrupt:
            log.info("\nInterrupted by user. Closing browser.")
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            raise
        finally:
            if connected_via_cdp:
                browser.close()  # disconnect, Chrome stays alive for MCP
                log.info("Disconnected from Chrome (browser stays open).")
            else:
                context.close()
                log.info("Browser closed.")


if __name__ == "__main__":
    main()
