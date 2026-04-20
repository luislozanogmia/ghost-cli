"""
SCOUT — Page intelligence via headless Chrome.

Launches Playwright, navigates to a URL, captures the full accessibility tree
(via CDP Accessibility.getFullAXTree) and DOM attributes, then merges both
into a single structured manifest for downstream agentic consumption.

Usage:
    from ghost.scout import scout, save_manifest
    manifest = scout("https://example.com")
    save_manifest(manifest, "example_manifest.json")

CLI:
    python scout.py https://example.com
    python scout.py https://example.com --wait 5 --output manifest.json
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERACTIVE_ROLES = {
    "button", "link", "textbox", "checkbox", "radio", "combobox",
    "listbox", "menuitem", "menu", "menubar", "option", "searchbox",
    "slider", "spinbutton", "switch", "tab", "tablist", "tree",
    "treeitem", "gridcell", "row", "columnheader", "rowheader",
    "dialog", "alertdialog",
}

DOM_ATTRIBUTES_TO_CAPTURE = [
    "id", "class", "href", "src", "type", "placeholder", "name",
    "value", "action", "method", "role", "tabindex", "title", "alt",
    "data-testid", "data-test-id", "data-cy",
    "aria-label", "aria-labelledby", "aria-describedby",
    "aria-expanded", "aria-checked", "aria-selected", "aria-disabled",
    "aria-hidden", "aria-haspopup", "aria-controls",
]


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

def _get_ax_tree(cdp_session) -> list[dict]:
    """Fetch the full accessibility tree via CDP."""
    result = cdp_session.send("Accessibility.getFullAXTree")
    return result.get("nodes", [])


def _get_dom_nodes(cdp_session, selector: str = "*") -> dict[int, dict]:
    """
    Query DOM for all elements matching selector.
    Returns mapping of backendNodeId -> {tag, attributes}.
    """
    doc = cdp_session.send("DOM.getDocument", {"depth": 0})
    root_id = doc["root"]["nodeId"]

    result = cdp_session.send("DOM.querySelectorAll", {
        "nodeId": root_id,
        "selector": selector,
    })
    node_ids = result.get("nodeIds", [])

    dom_map = {}
    for nid in node_ids:
        if nid == 0:
            continue
        try:
            desc = cdp_session.send("DOM.describeNode", {"nodeId": nid})
            node = desc.get("node", {})
            backend_id = node.get("backendNodeId")
            if backend_id is None:
                continue

            # Parse flat attribute list [key, val, key, val, ...] into dict
            raw_attrs = node.get("attributes", [])
            attrs = {}
            for i in range(0, len(raw_attrs) - 1, 2):
                key = raw_attrs[i]
                val = raw_attrs[i + 1]
                if key in DOM_ATTRIBUTES_TO_CAPTURE or key.startswith("data-") or key.startswith("aria-"):
                    attrs[key] = val

            dom_map[backend_id] = {
                "tag": node.get("nodeName", "").lower(),
                "attributes": attrs,
            }
        except Exception:
            # Node may have been removed between query and describe
            continue

    return dom_map


def _get_box_model(cdp_session, backend_node_id: int) -> Optional[dict]:
    """Get bounding box for a node via CDP. Returns None on failure."""
    try:
        result = cdp_session.send("DOM.getBoxModel", {
            "backendNodeId": backend_node_id,
        })
        content = result.get("model", {}).get("content", [])
        if len(content) >= 8:
            x1, y1 = content[0], content[1]
            x2, y2 = content[4], content[5]
            return {
                "x": x1,
                "y": y1,
                "width": round(x2 - x1, 1),
                "height": round(y2 - y1, 1),
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# A11y tree parsing
# ---------------------------------------------------------------------------

def _extract_ax_properties(node: dict) -> dict:
    """Extract role, name, description, state from an AX tree node."""
    role_obj = node.get("role", {})
    role = role_obj.get("value", "") if isinstance(role_obj, dict) else str(role_obj)

    name_obj = node.get("name", {})
    name = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj)

    desc_obj = node.get("description", {})
    description = desc_obj.get("value", "") if isinstance(desc_obj, dict) else str(desc_obj)

    # Collect boolean state properties
    states = {}
    for prop in node.get("properties", []):
        prop_name = prop.get("name", "")
        prop_value = prop.get("value", {})
        val = prop_value.get("value") if isinstance(prop_value, dict) else prop_value
        if prop_name in ("focused", "disabled", "expanded", "selected", "checked",
                         "pressed", "required", "readonly", "hidden", "modal"):
            states[prop_name] = val

    return {
        "role": role,
        "name": name,
        "description": description,
        "state": states,
        "backend_node_id": node.get("backendDOMNodeId"),
    }


# ---------------------------------------------------------------------------
# Selector generation
# ---------------------------------------------------------------------------

def _build_selector(role: str, name: str, tag: str, attrs: dict) -> str:
    """
    Build the best CSS selector for targeting this element.
    Priority: data-testid > aria-label > id > role-based.
    """
    # data-testid variants
    for attr_key in ("data-testid", "data-test-id", "data-cy"):
        if attr_key in attrs and attrs[attr_key]:
            return f'[{attr_key}="{attrs[attr_key]}"]'

    # aria-label
    aria_label = attrs.get("aria-label", "")
    if aria_label:
        return f'[aria-label="{aria_label}"]'

    # id
    elem_id = attrs.get("id", "")
    if elem_id:
        return f"#{elem_id}"

    # role + name combination
    dom_role = attrs.get("role", role)
    if dom_role and name:
        return f'[role="{dom_role}"][aria-label="{name}"]'
    if dom_role:
        return f'[role="{dom_role}"]'

    # Fallback to tag
    if tag:
        return tag

    return "*"


# ---------------------------------------------------------------------------
# Structure detection (forms, navigation, data regions)
# ---------------------------------------------------------------------------

def _detect_forms(elements: list[dict]) -> list[dict]:
    """Detect form structures from element list."""
    forms = []
    form_fields = []

    for el in elements:
        tag = el.get("tag", "")
        role = el.get("role", "")
        attrs = el.get("attributes", {})

        if role in ("textbox", "searchbox", "combobox", "listbox",
                     "checkbox", "radio", "spinbutton", "slider", "switch"):
            form_fields.append({
                "role": role,
                "name": el.get("name", ""),
                "type": attrs.get("type", ""),
                "placeholder": attrs.get("placeholder", ""),
                "selector": el.get("selector", ""),
            })

    if form_fields:
        forms.append({
            "fields": form_fields,
            "field_count": len(form_fields),
        })

    return forms


def _detect_navigation(elements: list[dict]) -> list[dict]:
    """Detect navigation elements with links."""
    nav_links = []
    for el in elements:
        if el.get("role") == "link":
            href = el.get("attributes", {}).get("href", "")
            nav_links.append({
                "text": el.get("name", ""),
                "href": href,
                "selector": el.get("selector", ""),
            })

    return nav_links


def _detect_data_regions(elements: list[dict]) -> list[dict]:
    """Detect areas that look like data tables or structured lists."""
    regions = []
    table_roles = {"grid", "table", "treegrid", "row", "gridcell",
                   "columnheader", "rowheader"}

    table_elements = [e for e in elements if e.get("role") in table_roles]
    if table_elements:
        regions.append({
            "type": "table",
            "element_count": len(table_elements),
            "headers": [e.get("name", "") for e in table_elements
                        if e.get("role") in ("columnheader", "rowheader")],
        })

    list_roles = {"list", "listitem", "tree", "treeitem"}
    list_elements = [e for e in elements if e.get("role") in list_roles]
    if list_elements:
        regions.append({
            "type": "list",
            "element_count": len(list_elements),
        })

    return regions


# ---------------------------------------------------------------------------
# Main scout function
# ---------------------------------------------------------------------------

def scout(
    url: str,
    wait_seconds: float = 3.0,
    browser_context_dir: str = None,
) -> dict:
    """
    Navigate to a URL with headless Chrome and capture a unified manifest
    combining the accessibility tree and DOM attributes.

    Args:
        url: Target URL to scout.
        wait_seconds: Seconds to wait after page load for dynamic content.
        browser_context_dir: Optional path to saved browser context for auth persistence.

    Returns:
        Structured manifest dict with elements, forms, navigation, data_regions.
    """
    manifest = {
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tree_hash": "",
        "page_title": "",
        "elements": [],
        "forms": [],
        "navigation": [],
        "data_regions": [],
        "error": None,
    }

    with sync_playwright() as pw:
        # Launch browser
        browser = pw.chromium.launch(headless=True)

        try:
            # Create context (with or without saved state)
            context_kwargs: dict[str, Any] = {}
            if browser_context_dir:
                context_kwargs["storage_state"] = browser_context_dir

            context: BrowserContext = browser.new_context(**context_kwargs)
            page: Page = context.new_page()

            # Navigate
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as nav_err:
                manifest["error"] = f"Navigation failed: {nav_err}"
                return manifest

            # Wait for page to settle
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            # Get page title
            manifest["page_title"] = page.title()

            # Open CDP session on the page
            cdp = context.new_cdp_session(page)

            # Enable required CDP domains
            cdp.send("DOM.enable")
            cdp.send("Accessibility.enable")

            # Fetch accessibility tree
            ax_nodes = _get_ax_tree(cdp)

            # Fetch DOM attributes for interactive elements
            interactive_selector = (
                "a, button, input, select, textarea, "
                "[role], [data-testid], [data-test-id], [data-cy], "
                "[tabindex], [aria-label], [onclick], "
                "details, summary, dialog, form, nav, table, "
                "ul, ol, dl, th, td"
            )
            dom_map = _get_dom_nodes(cdp, interactive_selector)

            # Merge a11y nodes with DOM data
            elements = []
            for ax_node in ax_nodes:
                ax_info = _extract_ax_properties(ax_node)
                role = ax_info["role"]

                # Skip non-interactive / structural noise
                if role in ("none", "generic", "StaticText", "InlineTextBox",
                            "paragraph", "group", "document", "WebArea",
                            "rootWebArea", ""):
                    continue

                backend_id = ax_info.get("backend_node_id")

                # Get DOM info if available
                dom_info = dom_map.get(backend_id, {})
                tag = dom_info.get("tag", "")
                attrs = dom_info.get("attributes", {})

                # Build selector
                selector = _build_selector(role, ax_info["name"], tag, attrs)

                # Get bounding box
                bounds = None
                if backend_id:
                    bounds = _get_box_model(cdp, backend_id)

                element = {
                    "role": role,
                    "name": ax_info["name"],
                    "description": ax_info["description"],
                    "state": ax_info["state"],
                    "selector": selector,
                    "tag": tag,
                    "attributes": attrs,
                    "bounds": bounds,
                }
                elements.append(element)

            manifest["elements"] = elements

            # Detect structural patterns
            manifest["forms"] = _detect_forms(elements)
            manifest["navigation"] = _detect_navigation(elements)
            manifest["data_regions"] = _detect_data_regions(elements)

            # Compute tree hash for staleness detection
            tree_bytes = json.dumps(elements, sort_keys=True).encode("utf-8")
            manifest["tree_hash"] = hashlib.sha256(tree_bytes).hexdigest()

            # Cleanup CDP
            cdp.detach()
            context.close()

        except Exception as ex:
            manifest["error"] = f"Scout error: {ex}"
        finally:
            browser.close()

    return manifest


# ---------------------------------------------------------------------------
# I/O helper
# ---------------------------------------------------------------------------

def save_manifest(manifest: dict, output_path: str) -> None:
    """Write the manifest dict to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SCOUT — Page intelligence via headless Chrome")
    parser.add_argument("url", help="URL to scout")
    parser.add_argument("--wait", type=float, default=3.0, help="Seconds to wait after page load (default: 3)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Save manifest to JSON file")
    parser.add_argument("--context-dir", type=str, default=None, help="Path to saved browser context for auth")
    args = parser.parse_args()

    result = scout(args.url, wait_seconds=args.wait, browser_context_dir=args.context_dir)

    if args.output:
        save_manifest(result, args.output)
        print(f"Manifest saved to {args.output}")
        print(f"  Elements: {len(result['elements'])}")
        print(f"  Hash: {result['tree_hash'][:16]}...")
        if result.get("error"):
            print(f"  Error: {result['error']}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
