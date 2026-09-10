"""
Ghost Extractors -- pre-built JS extraction recipes for common page patterns.

Each recipe is a JS function that returns a FORMATTED STRING, not JSON.
Output follows the same numbered-menu pattern as ghost_vacuum so the LLM
gets a consistent interface: read the list, pick a number or URL, act.

ghost_eval remains the escape hatch for raw JS when you need structured data.
"""

RECIPES: dict[str, str] = {
    "page_links": r"""
(() => {
    const seen = new Set();
    const links = [...document.querySelectorAll('a[href]')]
        .filter(a => {
            const href = a.href;
            if (!href || href.startsWith('javascript:') || seen.has(href)) return false;
            seen.add(href);
            return true;
        })
        .slice(0, MAX_ITEMS)
        .map(a => ({
            text: a.innerText.replace(/\s+/g, ' ').trim().slice(0, 80),
            href: a.href,
        }));
    if (links.length === 0) return '(no links found)';
    const lines = links.map((l, i) =>
        `  [${i+1}] ${l.text || '(no text)'}` + `\n       ${l.href}`
    );
    return `=== Links: ${links.length} found ===\nURL: ${location.href}\n\n` + lines.join('\n') + '\n';
})()
""",

    "page_meta": r"""
(() => {
    const get = sel => {
        const el = document.querySelector(sel);
        return el ? (el.content || el.innerText || '').trim() : '';
    };
    const title = document.title || '(none)';
    const desc = get('meta[name="description"]') || get('meta[property="og:description"]') || '(none)';
    const ogTitle = get('meta[property="og:title"]');
    const ogImage = get('meta[property="og:image"]');
    const canonical = get('link[rel="canonical"]');
    const h1 = (document.querySelector('h1') || {}).innerText || '(none)';

    let out = `=== Page Meta ===\n`;
    out += `URL: ${location.href}\n`;
    out += `Title: ${title}\n`;
    out += `H1: ${h1}\n`;
    out += `Description: ${desc}\n`;
    if (ogTitle) out += `OG Title: ${ogTitle}\n`;
    if (ogImage) out += `OG Image: ${ogImage}\n`;
    if (canonical) out += `Canonical: ${canonical}\n`;
    return out;
})()
""",
}


def get_recipe(name: str, max_items: int = 10) -> str:
    """Get a JS extraction recipe by name, with MAX_ITEMS substituted."""
    if name not in RECIPES:
        available = ", ".join(sorted(RECIPES.keys()))
        raise ValueError(f"Unknown recipe '{name}'. Available: {available}")
    return RECIPES[name].replace("MAX_ITEMS", str(max_items))


def list_recipes() -> list[str]:
    """List available recipe names."""
    return sorted(RECIPES.keys())
