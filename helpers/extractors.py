"""
Ghost Extractors -- pre-built JS extraction recipes for common page patterns.

Each recipe is a JS function that returns a FORMATTED STRING, not JSON.
Output follows the same numbered-menu pattern as ghost_vacuum so the LLM
gets a consistent interface: read the list, pick a number or URL, act.

ghost_eval remains the escape hatch for raw JS when you need structured data.
"""

RECIPES: dict[str, str] = {
    "linkedin_search": r"""
(() => {
    const profiles = [];
    const cards = document.querySelectorAll(
        'li.reusable-search__result-container, div[data-chameleon-result-urn], div.entity-result'
    );
    const seen = new Set();
    cards.forEach(card => {
        const link = card.querySelector('a[href*="/in/"]');
        if (!link) return;
        const url = link.href.split('?')[0];
        if (seen.has(url)) return;
        seen.add(url);
        const nameEl = card.querySelector('span[dir="ltr"] > span[aria-hidden="true"]')
            || card.querySelector('.entity-result__title-text a span')
            || link;
        const name = (nameEl ? nameEl.innerText : '').trim();
        const subtitleEl = card.querySelector('.entity-result__primary-subtitle')
            || card.querySelector('.reusable-search-simple-insight__text');
        const title = (subtitleEl ? subtitleEl.innerText : '').trim();
        const locationEl = card.querySelector('.entity-result__secondary-subtitle');
        const location = (locationEl ? locationEl.innerText : '').trim();
        const snippetEl = card.querySelector('.entity-result__summary');
        const snippet = (snippetEl ? snippetEl.innerText : '').replace(/\s+/g, ' ').trim().slice(0, 120);
        profiles.push({ url, name, title, location, snippet });
    });
    // Fallback: generic profile link scan
    if (profiles.length === 0) {
        document.querySelectorAll('a[href*="/in/"]').forEach(a => {
            const url = a.href.split('?')[0];
            if (seen.has(url)) return;
            seen.add(url);
            const container = a.closest('li, div[class*="result"]');
            const context = container
                ? container.innerText.replace(/\s+/g, ' ').slice(0, 150)
                : a.innerText.slice(0, 80);
            profiles.push({ url, name: a.innerText.trim(), title: '', location: '', snippet: context.trim() });
        });
    }
    const items = profiles.slice(0, MAX_ITEMS);
    if (items.length === 0) return '(no profiles found on this page)';
    const lines = items.map((p, i) => {
        let line = `  [${i+1}] ${p.name}`;
        if (p.title) line += ` -- ${p.title}`;
        line += `\n       ${p.url}`;
        if (p.location) line += ` | ${p.location}`;
        if (p.snippet) line += `\n       ${p.snippet}`;
        return line;
    });
    return `=== LinkedIn Search: ${items.length} profiles ===\nURL: ${location.href}\n\n` + lines.join('\n\n') + '\n';
})()
""",

    "linkedin_profile": r"""
(() => {
    const get = sel => {
        const el = document.querySelector(sel);
        return el ? el.innerText.trim() : '';
    };
    const name = get('h1') || get('.text-heading-xlarge') || '(unknown)';
    const headline = get('.text-body-medium.break-words') || get('.pv-top-card--list li');
    const loc = get('.text-body-small.inline.t-black--light.break-words');
    const about = (get('#about ~ div .inline-show-more-text') || get('section.pv-about-section p')).slice(0, 400);
    const url = location.href.split('?')[0];

    let out = `=== ${name} ===\n${url}\n`;
    if (headline) out += `${headline}\n`;
    if (loc) out += `${loc}\n`;
    out += '\n';
    if (about) out += `${about}\n\n`;

    // Experience
    const exps = [];
    document.querySelectorAll('#experience ~ div ul > li, section[id*="experience"] li').forEach(li => {
        const role = (li.querySelector('.t-bold span') || li.querySelector('.pv-entity__summary-info h3') || {}).innerText || '';
        const company = (li.querySelector('.t-normal span') || li.querySelector('.pv-entity__secondary-title') || {}).innerText || '';
        const dates = (li.querySelector('.pvs-entity__caption-wrapper') || li.querySelector('.pv-entity__date-range span:nth-child(2)') || {}).innerText || '';
        if (role || company) exps.push({ role: role.trim(), company: company.trim(), dates: dates.trim() });
    });
    if (exps.length > 0) {
        out += 'Experience:\n';
        exps.slice(0, 5).forEach((e, i) => {
            out += `  [${i+1}] ${e.role}`;
            if (e.company) out += ` -- ${e.company}`;
            if (e.dates) out += ` (${e.dates})`;
            out += '\n';
        });
        out += '\n';
    }

    // Education
    const edu = [];
    document.querySelectorAll('#education ~ div ul > li, section[id*="education"] li').forEach(li => {
        const school = (li.querySelector('.t-bold span') || li.querySelector('.pv-entity__school-name') || {}).innerText || '';
        const degree = (li.querySelector('.t-normal span') || {}).innerText || '';
        if (school) edu.push({ school: school.trim(), degree: degree.trim() });
    });
    if (edu.length > 0) {
        out += 'Education:\n';
        edu.slice(0, 3).forEach((e, i) => {
            out += `  [${i+1}] ${e.school}`;
            if (e.degree) out += ` -- ${e.degree}`;
            out += '\n';
        });
    }
    return out;
})()
""",

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
