from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


INSTANCE_ID_PROPERTY = {
    "type": "string",
    "description": (
        "Named Ghost browser instance. Omit to use the shared default instance. "
        "Use different instance IDs for independent Chrome sessions."
    ),
}


def get_ghost_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="ghost_instance_create",
            description=(
                "Create or reuse a named Ghost browser instance backed by its own "
                "independent Chrome profile. Optionally open the browser immediately "
                "and navigate to a URL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": (
                            "Optional instance name. If omitted, Ghost generates one. "
                            "Reusing the same name attaches to the same independent Chrome session."
                        ),
                    },
                    "open_browser": {
                        "type": "boolean",
                        "description": "Open the browser window immediately (default: true).",
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional URL to open immediately after creation.",
                    },
                    "cdp_url": {
                        "type": "string",
                        "description": (
                            "CDP endpoint to attach to an external browser (e.g. "
                            "\"http://localhost:9222\" for Liquid's embedded Chrome). "
                            "When set, Ghost controls the external browser instead of launching its own. "
                            "Use the special value \"live-chrome\" to attach to the user's currently open "
                            "Chrome session through its DevTools websocket, bypassing the chrome-devtools-mcp "
                            "auto-connect proxy."
                        ),
                    },
                    "playwright_session": {
                        "type": "string",
                        "description": (
                            "Attach Ghost to a managed Playwright CLI session instead of a Chrome/CDP target. "
                            "For LinkedIn, prefer the stable launcher under "
                            "browser_context/linkedin/ and the shared auth state at "
                            "browser_context/linkedin_auth.json."
                        ),
                    },
                    "reuse_only": {
                        "type": "boolean",
                        "description": (
                            "If true, fail with an error if the instance does not already exist instead "
                            "of creating a new one. Use this when you want to operate on an existing tab "
                            "rather than accidentally opening a new browser session. "
                            "Call ghost_instance_list first to see what instances are available."
                        ),
                    },
                    "headless": {
                        "type": "boolean",
                        "description": (
                            "Launch the browser in headless mode (no visible window). "
                            "Defaults to false so the user can see the browser, but set to true "
                            "when running on servers or in CI without a display."
                        ),
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_instance_list",
            description="List all known Ghost browser instances and their current page state.",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDef(
            name="ghost_instance_close",
            description=(
                "Close a named Ghost browser instance and unregister it from the local "
                "Ghost runtime. This does not delete its profile directory."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "The named instance to close.",
                    },
                },
                "required": ["instance_id"],
            },
        ),
        ToolDef(
            name="ghost_vacuum",
            description=(
                "Vacuum the current browser page into a numbered text menu. "
                "Returns ONLY interactive elements (buttons, links, inputs) "
                "grouped by page region. Optionally navigate to a URL first. "
                "Shows first N elements (default 50); use ghost_more for next page. "
                "Use this instead of reading raw page HTML/DOM."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "url": {
                        "type": "string",
                        "description": "Optional URL to navigate to before vacuuming. Omit to vacuum the current page.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max elements to show per page (default 50). Use ghost_more for next pages.",
                    },
                    "wait": {
                        "type": "string",
                        "enum": ["load", "networkidle", "none"],
                        "description": (
                            "Wait strategy after navigation: "
                            "'load' (default -- wait for DOMContentLoaded + 2s settle), "
                            "'networkidle' (wait until network is idle for 500ms -- best for SPAs), "
                            "'none' (don't wait -- use when page is already loaded)."
                        ),
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_more",
            description=(
                "Get the next page of elements from the last vacuum result. "
                "Does NOT re-vacuum the page - uses the cached element list. "
                "Element numbers stay globally consistent (element [75] is always [75])."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "offset": {
                        "type": "integer",
                        "description": "Start from this element offset. Omit to continue from where the last page ended.",
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_click",
            description=(
                "Execute an action from the Ghost menu by number. "
                "Clicks buttons/links, fills inputs, toggles checkboxes. "
                "After executing, automatically re-vacuums and returns the updated menu. "
                "Works with ANY element number, even if not shown on the current page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "choice": {
                        "type": "integer",
                        "description": "The menu number to execute (e.g., 7 to click element [7]).",
                    },
                    "value": {
                        "type": "string",
                        "description": "Text value for input/search fields. Required for textbox/searchbox elements.",
                    },
                    "wait": {
                        "type": "string",
                        "enum": ["load", "networkidle", "none"],
                        "description": (
                            "Wait strategy after clicking: "
                            "'load' (default -- wait for page settle + 1s), "
                            "'networkidle' (wait until network is idle -- best for SPAs and link clicks), "
                            "'none' (click and immediately re-vacuum)."
                        ),
                    },
                },
                "required": ["choice"],
            },
        ),
        ToolDef(
            name="ghost_status",
            description=(
                "Show current Ghost state for one instance: cached page URL, element count, "
                "browser connection status, and runtime session count."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                },
            },
        ),
        ToolDef(
            name="ghost_save_auth",
            description=(
                "Export browser auth (cookies, localStorage) from one instance to linkedin_auth.json. "
                "Call after logging into a site to persist the session across restarts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                },
            },
        ),
        ToolDef(
            name="ghost_eval",
            description=(
                "Run a JavaScript function on the current page and return the result. "
                "Use this to extract elements that the accessibility tree misses (e.g. WhatsApp chat list, "
                "LinkedIn feed items, SPAs with custom renders). "
                "Pass a JS arrow function string: '() => document.title' or "
                "'() => [...document.querySelectorAll(\"span[title]\")].map(e=>e.title).join(\"\\\\n\")'"
            ),
            input_schema={
                "type": "object",
                "required": ["script"],
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "script": {
                        "type": "string",
                        "description": "JavaScript arrow function to evaluate, e.g. '() => document.title'",
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_screenshot",
            description=(
                "Take a screenshot of the current browser page. "
                "Optionally scroll to a specific menu element first. "
                "Returns file path by default. Set inline=true to get base64 data "
                "that can be viewed directly without a separate Read call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "element": {
                        "type": "integer",
                        "description": "Menu element number to scroll to before taking screenshot. Omit for current viewport.",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture entire page (default: false, captures only visible viewport).",
                    },
                    "inline": {
                        "type": "boolean",
                        "description": (
                            "Return screenshot as base64 data URI instead of saving to disk. "
                            "Useful when you want to view the image immediately without a Read call. "
                            "Default: false (saves to disk and returns path)."
                        ),
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_extract",
            description=(
                "Smart vacuum: extract page content using a named recipe and return a clean "
                "numbered list (same format as ghost_vacuum). Recipes know specific page "
                "structures (LinkedIn, generic links, meta tags) and strip all noise. "
                "Built-in recipes: 'linkedin_search', 'linkedin_profile', 'page_links', 'page_meta'. "
                "Or pass a custom JS arrow function via 'script'. "
                "Use ghost_eval if you need raw JS output instead of formatted text."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "recipe": {
                        "type": "string",
                        "description": (
                            "Named extraction recipe. Built-in: "
                            "'linkedin_search' (numbered profile list from search results), "
                            "'linkedin_profile' (formatted profile card), "
                            "'page_links' (numbered link list), "
                            "'page_meta' (title, description, og tags as text). "
                            "Omit to use custom JS via 'script' parameter."
                        ),
                    },
                    "script": {
                        "type": "string",
                        "description": (
                            "Custom JS arrow function. Result is returned as-is (string). "
                            "Example: '() => [...document.querySelectorAll(\"h2\")].map(e => e.textContent).join(\"\\n\")'"
                        ),
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Limit number of extracted items (default: 10).",
                    },
                },
            },
        ),
        # ---------------------------------------------------------------
        # Improvement #1: ghost_read -- text extraction primitive
        # ---------------------------------------------------------------
        ToolDef(
            name="ghost_read",
            description=(
                "Extract the readable text content of the current page (like reader mode). "
                "Returns clean article text, stripping navigation, ads, and chrome. "
                "Use this to READ page content. Use ghost_vacuum to INTERACT with elements. "
                "Optionally navigate to a URL first. Optionally limit output to first N characters."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "url": {
                        "type": "string",
                        "description": "Optional URL to navigate to before reading. Omit to read the current page.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default: 8000). Set higher for long articles.",
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "Optional CSS selector to scope reading. "
                            "e.g. 'article', 'main', '.post-content'. "
                            "Omit for auto-detection (tries article > main > body)."
                        ),
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_find_text",
            description=(
                "Search the current page for a text string or regex pattern. "
                "Returns matches with surrounding context. Use this instead of "
                "ghost_vacuum when you just need to check if specific content exists on the page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "query": {
                        "type": "string",
                        "description": "Text or regex pattern to search for on the page.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matches to return (default: 5).",
                    },
                    "context_chars": {
                        "type": "integer",
                        "description": "Characters of surrounding context per match (default: 100).",
                    },
                },
                "required": ["query"],
            },
        ),
        # ---------------------------------------------------------------
        # Improvement #4: ghost_scroll -- scroll and re-vacuum for lazy content
        # ---------------------------------------------------------------
        ToolDef(
            name="ghost_scroll",
            description=(
                "Scroll the page down (or up) to load lazy content, then re-vacuum. "
                "Use this on infinite-scroll pages (LinkedIn feed, Twitter, search results) "
                "where ghost_more only paginates cached elements but doesn't load NEW content. "
                "After scrolling, returns fresh vacuum menu with newly loaded elements."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up", "bottom", "top"],
                        "description": (
                            "Scroll direction: 'down' (one viewport), 'up' (one viewport), "
                            "'bottom' (end of page), 'top' (start of page). Default: 'down'."
                        ),
                    },
                    "pixels": {
                        "type": "integer",
                        "description": "Exact pixels to scroll (overrides direction presets). Positive = down, negative = up.",
                    },
                    "wait": {
                        "type": "number",
                        "description": "Seconds to wait after scrolling for lazy content to load (default: 2.0).",
                    },
                },
            },
        ),
        # ---------------------------------------------------------------
        # Improvement #6: ghost_tab_list -- multi-tab support
        # ---------------------------------------------------------------
        ToolDef(
            name="ghost_tab_list",
            description=(
                "List all open tabs in a Ghost browser instance. "
                "Returns tab index, URL, and title for each tab. "
                "Use ghost_tab_switch to change the active tab."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                },
            },
        ),
        ToolDef(
            name="ghost_tab_open",
            description=(
                "Open a new tab in the current Ghost browser instance. "
                "Optionally navigate to a URL. The new tab becomes the active tab. "
                "Useful for comparing pages side-by-side without creating separate instances."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "url": {
                        "type": "string",
                        "description": "URL to open in the new tab. Omit for a blank tab.",
                    },
                },
            },
        ),
        ToolDef(
            name="ghost_tab_switch",
            description=(
                "Switch the active tab in a Ghost browser instance by index. "
                "Use ghost_tab_list first to see available tabs and their indices. "
                "After switching, automatically vacuums the new active tab."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "tab_index": {
                        "type": "integer",
                        "description": "Zero-based tab index to switch to (from ghost_tab_list).",
                    },
                },
                "required": ["tab_index"],
            },
        ),
        ToolDef(
            name="ghost_tab_close",
            description=(
                "Close a tab in the current Ghost browser instance by index. "
                "If the closed tab was active, switches to the previous tab. "
                "Cannot close the last remaining tab."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "tab_index": {
                        "type": "integer",
                        "description": "Zero-based tab index to close (from ghost_tab_list).",
                    },
                },
                "required": ["tab_index"],
            },
        ),
        # ---------------------------------------------------------------
        # ghost_key -- independent keyboard input
        # ---------------------------------------------------------------
        ToolDef(
            name="ghost_key",
            description=(
                "Press keyboard keys independently of any element. "
                "Use for Enter, Escape, Tab, arrow keys, shortcuts (Ctrl+A), "
                "or typing text into the currently focused element. "
                "Supports Playwright key notation: Enter, Escape, Tab, ArrowDown, "
                "ArrowUp, Backspace, Delete, Home, End, PageDown, PageUp, "
                "Control+a, Meta+c, Shift+Tab, etc."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "key": {
                        "type": "string",
                        "description": (
                            "Key or key combination to press. Examples: "
                            "'Enter', 'Escape', 'Tab', 'ArrowDown', "
                            "'Control+a', 'Meta+v', 'Shift+Tab'. "
                            "For typing text, use the 'text' parameter instead."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "Text to type into the currently focused element. "
                            "Unlike 'key', this types each character sequentially "
                            "with realistic key events. Use for filling inputs "
                            "that don't appear in the vacuum menu."
                        ),
                    },
                    "repeat": {
                        "type": "integer",
                        "description": "Number of times to repeat the key press (default: 1).",
                    },
                },
            },
        ),
        # ---------------------------------------------------------------
        # ghost_iframes -- list and switch to iframes
        # ---------------------------------------------------------------
        ToolDef(
            name="ghost_iframes",
            description=(
                "List all iframes on the current page, or switch Ghost's active "
                "context to a specific iframe by index. After switching, "
                "ghost_vacuum will extract elements from inside that iframe. "
                "Use 'index: -1' or omit index to switch back to the main frame."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "instance_id": INSTANCE_ID_PROPERTY,
                    "index": {
                        "type": "integer",
                        "description": (
                            "Zero-based iframe index to switch to. "
                            "Omit to list all iframes. Use -1 to switch back to main frame."
                        ),
                    },
                },
            },
        ),
    ]
