"""
Ghost Browser — COMPILE module.

Takes a scout manifest (JSON dict) and generates a deterministic, importable
Python script that wraps a page's interactive surface as a Playwright-based
async class.

No LLM calls. Pure template-based code generation.

Usage:
    from ghost.compile import compile_script
    code = compile_script(manifest, output_path="pages/example_com.py")

CLI:
    python compile.py manifest.json [-o output.py]
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def domain_to_classname(url: str) -> str:
    """Convert a URL to a PascalCase class name derived from the domain.

    Examples:
        https://example.com       -> ExampleCom
        https://open.spotify.com  -> OpenSpotifyCom
        https://github.com/foo    -> GithubCom
    """
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc or "unknown"
    # Strip leading www.
    host = re.sub(r"^www\.", "", host)
    # Split on dots / hyphens, title-case each part
    parts = re.split(r"[.\-]+", host)
    return "".join(p.capitalize() for p in parts if p)


def _sanitize_name(raw: str) -> str:
    """Turn an arbitrary element name into a valid snake_case Python identifier."""
    # Lowercase, replace non-alnum with underscore
    s = re.sub(r"[^a-z0-9]+", "_", raw.lower().strip())
    # Collapse multiple underscores, strip leading/trailing
    s = re.sub(r"_+", "_", s).strip("_")
    # Must not start with a digit
    if s and s[0].isdigit():
        s = "el_" + s
    return s or "unnamed"


def _deduplicate_names(names: list[str]) -> list[str]:
    """Append numeric suffixes where names collide."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for n in names:
        if n in seen:
            seen[n] += 1
            result.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            result.append(n)
    return result


def _best_selector(element: dict) -> str:
    """Pick the highest-priority selector from an element dict.

    Priority: data-testid > aria-label > #id > explicit selector field > role-based.
    """
    attrs = element.get("attributes") or {}

    # 1. data-testid
    testid = attrs.get("data-testid")
    if testid:
        return f'[data-testid="{testid}"]'

    # 2. aria-label
    aria = attrs.get("aria-label")
    if aria:
        escaped = aria.replace('"', '\\"')
        return f'[aria-label="{escaped}"]'

    # 3. id
    el_id = attrs.get("id")
    if el_id:
        return f"#{el_id}"

    # 4. Explicit selector from scout
    sel = element.get("selector")
    if sel:
        return sel

    # 5. Role-based fallback
    role = element.get("role", "")
    name = element.get("name", "")
    tag = element.get("tag", "div")
    if role and name:
        escaped = name.replace('"', '\\"')
        return f'{tag}[role="{role}"][aria-label="{escaped}"]'
    if role:
        return f'{tag}[role="{role}"]'
    return tag


def _indent(code: str, level: int = 1) -> str:
    """Indent every line of *code* by *level* x 4 spaces."""
    prefix = "    " * level
    lines = code.splitlines(True)
    return "".join(prefix + l if l.strip() else l for l in lines)


# ---------------------------------------------------------------------------
# Method generators — each returns (method_name, method_code_str)
# ---------------------------------------------------------------------------

def _gen_button_method(name: str, selector: str) -> tuple[str, str]:
    method_name = f"click_{name}"
    code = (
        f"async def {method_name}(self):\n"
        f'    """Click the \'{name}\' button."""\n'
        f"    try:\n"
        f"        await self._page.click({selector!r}, timeout=5000)\n"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return None\n"
    )
    return method_name, code


def _gen_input_method(name: str, selector: str) -> tuple[str, str]:
    method_name = f"fill_{name}"
    code = (
        f"async def {method_name}(self, value: str):\n"
        f'    """Fill the \'{name}\' text input."""\n'
        f"    try:\n"
        f"        await self._page.fill({selector!r}, value, timeout=5000)\n"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return None\n"
    )
    return method_name, code


def _gen_link_method(name: str, selector: str) -> tuple[str, str]:
    method_name = f"goto_{name}"
    code = (
        f"async def {method_name}(self):\n"
        f'    """Click the \'{name}\' link and wait for navigation."""\n'
        f"    try:\n"
        f"        async with self._page.expect_navigation(timeout=10000):\n"
        f"            await self._page.click({selector!r}, timeout=5000)\n"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return None\n"
    )
    return method_name, code


def _gen_nav_method(name: str, selector: str) -> tuple[str, str]:
    method_name = f"nav_{name}"
    code = (
        f"async def {method_name}(self):\n"
        f'    """Navigate to the \'{name}\' section."""\n'
        f"    try:\n"
        f"        async with self._page.expect_navigation(timeout=10000):\n"
        f"            await self._page.click({selector!r}, timeout=5000)\n"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return None\n"
    )
    return method_name, code


def _gen_form_method(form: dict) -> tuple[str, str]:
    """Generate a submit_<form> method that fills every field then submits."""
    form_name = _sanitize_name(form.get("name") or form.get("id") or "form")
    method_name = f"submit_{form_name}"

    fields: list[dict] = form.get("fields") or []
    fill_lines: list[str] = []
    param_names: list[str] = []

    for f in fields:
        pname = _sanitize_name(f.get("name") or f.get("label") or "field")
        selector = _best_selector(f)
        param_names.append(pname)
        fill_lines.append(
            f"        await self._page.fill({selector!r}, str(kwargs.get({pname!r}, '')), timeout=5000)"
        )

    submit_selector = _best_selector(form) if form.get("selector") or form.get("attributes") else "button[type='submit']"

    fills_str = "\n".join(fill_lines) if fill_lines else "        pass  # no fields detected"

    code = (
        f"async def {method_name}(self, **kwargs):\n"
        f'    """Fill and submit the \'{form_name}\' form.\n'
        f"\n"
        f"    Keyword args (detected fields): {', '.join(param_names) or 'none detected'}\n"
        f'    """\n'
        f"    try:\n"
        f"{fills_str}\n"
        f"        await self._page.click({submit_selector!r}, timeout=5000)\n"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return None\n"
    )
    return method_name, code


def _gen_data_region_method(region: dict) -> tuple[str, str]:
    """Generate a get_<region> method that extracts tabular / list data."""
    region_name = _sanitize_name(region.get("name") or region.get("role") or "data")
    method_name = f"get_{region_name}"
    selector = _best_selector(region)

    # If columns are declared, use them for structured extraction
    columns: list[str] = region.get("columns") or []
    item_selector = region.get("item_selector") or "tr"

    if columns:
        col_keys = ", ".join(repr(c) for c in columns)
        extract_lines = (
            f"        rows = await container.query_selector_all({item_selector!r})\n"
            f"        results = []\n"
            f"        for row in rows:\n"
            f"            cells = await row.query_selector_all(\"td, th, [role='cell']\")\n"
            f"            texts = [await c.inner_text() for c in cells]\n"
            f"            keys = [{col_keys}]\n"
            f"            entry = dict(zip(keys, texts))\n"
            f"            results.append(entry)\n"
            f"        return results\n"
        )
    else:
        extract_lines = (
            f"        items = await container.query_selector_all({item_selector!r})\n"
            f"        results = []\n"
            f"        for item in items:\n"
            f"            text = await item.inner_text()\n"
            f"            results.append({{\"text\": text.strip()}})\n"
            f"        return results\n"
        )

    code = (
        f"async def {method_name}(self) -> list[dict]:\n"
        f'    """Extract data from the \'{region_name}\' region."""\n'
        f"    try:\n"
        f"        container = await self._page.query_selector({selector!r})\n"
        f"        if not container:\n"
        f"            return []\n"
        f"{extract_lines}"
        f"    except Exception:\n"
        f"        # Selector may have changed -- re-scout the page.\n"
        f"        return []\n"
    )
    return method_name, code


# ---------------------------------------------------------------------------
# Classify elements by role
# ---------------------------------------------------------------------------

_BUTTON_ROLES = {"button", "submit", "reset", "menuitem", "switch", "tab"}
_INPUT_ROLES = {"textbox", "searchbox", "input", "textarea", "combobox", "spinbutton", "slider"}
_LINK_ROLES = {"link", "a"}

# Roles that represent interactive elements worth generating methods for.
_INTERACTIVE_ROLES = _BUTTON_ROLES | _INPUT_ROLES | _LINK_ROLES | {
    "checkbox", "radio", "option", "listbox", "menu",
}

# Roles that are purely structural / layout — never generate methods.
_SKIP_ROLES = {
    "rootwebarea", "generic", "group", "region", "main", "banner",
    "contentinfo", "complementary", "article", "section", "paragraph",
    "heading", "text", "statictext", "img", "image", "figure",
    "separator", "presentation", "none", "document", "dialog",
    "status", "alert", "log", "timer", "progressbar",
    "rowgroup", "row", "cell", "columnheader", "rowheader",
    "table", "grid", "treegrid",
    "layouttable", "layouttablerow", "layouttablecell",
    "list", "listitem", "directory",
    "toolbar", "navigation",
}


def _classify_element(el: dict) -> str:
    """Return one of: button, input, link, unknown."""
    role = (el.get("role") or "").lower()
    tag = (el.get("tag") or "").lower()

    if role in _BUTTON_ROLES or tag == "button":
        return "button"
    if role in _INPUT_ROLES or tag in ("input", "textarea"):
        input_type = (el.get("attributes") or {}).get("type", "text").lower()
        if input_type in ("text", "search", "email", "password", "url", "tel", "number", ""):
            return "input"
        return "button"  # checkbox, radio, etc. treated as clickable
    if role in _LINK_ROLES or tag == "a":
        return "link"
    return "unknown"


# ---------------------------------------------------------------------------
# Main compiler
# ---------------------------------------------------------------------------

def compile_script(manifest: dict, output_path: str | None = None, compact: bool = True) -> str:
    """Generate a Playwright-based async page class from a scout manifest.

    Parameters
    ----------
    manifest : dict
        The scout manifest (see module docstring for schema).
    output_path : str, optional
        If provided, write the generated code to this file path.
    compact : bool
        If True (default), only generate methods for interactive elements
        (buttons, links, inputs, etc.). Skips structural/layout roles.

    Returns
    -------
    str
        The generated Python source code.
    """
    url: str = manifest.get("url", "https://unknown.example.com")
    classname = domain_to_classname(url)
    timestamp = manifest.get("timestamp", datetime.now(timezone.utc).isoformat())
    tree_hash = manifest.get("tree_hash", "unknown")
    page_title = manifest.get("page_title", "")
    elements: list[dict] = manifest.get("elements") or []
    forms: list[dict] = manifest.get("forms") or []
    navigation: list[dict] = manifest.get("navigation") or []
    data_regions: list[dict] = manifest.get("data_regions") or []

    # ----- Collect methods -----
    method_blocks: list[str] = []
    method_names_raw: list[str] = []

    # Elements — classify and generate
    skipped = 0
    for el in elements:
        role_lower = (el.get("role") or "").lower()

        # In compact mode, skip non-interactive roles
        if compact:
            if role_lower in _SKIP_ROLES:
                skipped += 1
                continue
            # Also skip elements with no name (unnamed structural nodes)
            if not el.get("name"):
                skipped += 1
                continue

        kind = _classify_element(el)
        name_raw = _sanitize_name(el.get("name") or el.get("role") or el.get("tag") or "element")
        selector = _best_selector(el)

        if kind == "button":
            mname, code = _gen_button_method(name_raw, selector)
        elif kind == "input":
            mname, code = _gen_input_method(name_raw, selector)
        elif kind == "link":
            mname, code = _gen_link_method(name_raw, selector)
        else:
            if compact:
                # In compact mode, skip truly unknown elements
                skipped += 1
                continue
            mname, code = _gen_button_method(name_raw, selector)

        method_names_raw.append(mname)
        method_blocks.append(code)

    # Navigation items
    for nav in navigation:
        name_raw = _sanitize_name(nav.get("name") or nav.get("label") or "section")
        selector = _best_selector(nav)
        mname, code = _gen_nav_method(name_raw, selector)
        method_names_raw.append(mname)
        method_blocks.append(code)

    # Forms
    for form in forms:
        mname, code = _gen_form_method(form)
        method_names_raw.append(mname)
        method_blocks.append(code)

    # Data regions
    for region in data_regions:
        mname, code = _gen_data_region_method(region)
        method_names_raw.append(mname)
        method_blocks.append(code)

    # Deduplicate method names and update code blocks
    deduped = _deduplicate_names(method_names_raw)
    for i, (original, deduped_name) in enumerate(zip(method_names_raw, deduped)):
        if original != deduped_name:
            method_blocks[i] = method_blocks[i].replace(
                f"async def {original}(", f"async def {deduped_name}(", 1
            )

    # ----- Meta dict -----
    meta = {
        "version": "1.0",
        "timestamp": timestamp,
        "url": url,
        "tree_hash": tree_hash,
        "selector_count": len(elements) + len(navigation),
        "element_count": len(elements) + len(forms) + len(navigation) + len(data_regions),
    }
    # Indent the JSON so it aligns inside the class body (8-space base indent)
    meta_json = json.dumps(meta, indent=4)
    meta_indented = _indent(meta_json, level=1).lstrip()  # first line stays at class attr level

    # ----- Build source line by line -----
    L = []  # noqa: E741
    L.append('"""')
    L.append("Ghost Browser -- auto-generated page class.")
    L.append("")
    L.append(f"Page : {page_title or url}")
    L.append(f"URL  : {url}")
    L.append(f"Class: {classname}")
    L.append("")
    L.append(f"Generated: {timestamp}")
    L.append(f"Tree hash: {tree_hash}")
    L.append("")
    L.append("DO NOT EDIT -- regenerate with ghost.compile.compile_script().")
    L.append('"""')
    L.append("")
    L.append("from __future__ import annotations")
    L.append("")
    L.append("")
    L.append(f"class {classname}:")
    L.append(f'    """Playwright async wrapper for {url}"""')
    L.append("")
    L.append(f"    __ghost_meta__: dict = {meta_indented}")
    L.append("")
    L.append("    def __init__(self, browser_context):")
    L.append("        self._ctx = browser_context")
    L.append("        self._page = None")
    L.append("")
    L.append("    async def open(self):")
    L.append('        """Create a new page and navigate to the target URL."""')
    L.append("        self._page = await self._ctx.new_page()")
    L.append(f"        await self._page.goto({url!r}, wait_until='domcontentloaded', timeout=30000)")
    L.append("        return self")
    L.append("")
    L.append("    async def close(self):")
    L.append('        """Close the page (not the context)."""')
    L.append("        if self._page:")
    L.append("            await self._page.close()")
    L.append("            self._page = None")
    L.append("")
    L.append("    async def __aenter__(self):")
    L.append("        await self.open()")
    L.append("        return self")
    L.append("")
    L.append("    async def __aexit__(self, exc_type, exc_val, exc_tb):")
    L.append("        await self.close()")
    L.append("        return False")
    L.append("")
    L.append("    @property")
    L.append("    def page(self):")
    L.append('        """Direct access to the underlying Playwright page for advanced use."""')
    L.append("        return self._page")

    # ----- Append generated methods -----
    for block in method_blocks:
        L.append("")
        # Each block is at indent=0; add 4-space indent to put inside class
        for line in block.splitlines():
            if line.strip():
                L.append("    " + line)
            else:
                L.append("")

    L.append("")

    # Clean up trailing whitespace and join
    source = "\n".join(line.rstrip() for line in L) + "\n"

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(source, encoding="utf-8")

    return source


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Ghost Compile — generate a Playwright page class from a scout manifest."
    )
    parser.add_argument("manifest", help="Path to a scout manifest JSON file.")
    parser.add_argument("-o", "--output", default=None, help="Output .py file path. Prints to stdout if omitted.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    code = compile_script(manifest, output_path=args.output)

    if args.output:
        print(f"Wrote generated class to {args.output}")
    else:
        print(code)


if __name__ == "__main__":
    main()
