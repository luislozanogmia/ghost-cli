"""
Ghost Extractors -- pre-built JS extraction recipes for common page patterns.

Each recipe is a JS function string that returns JSON-serializable data.
Recipes are designed to be context-efficient: they extract ONLY the structured
data needed, filtering out DOM noise before it reaches the LLM.
"""

RECIPES: dict[str, str] = {
    "linkedin_search": r"""
(() => {
    const results = [];
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
        const snippet = (snippetEl ? snippetEl.innerText : '').replace(/\s+/g, ' ').trim();
        results.push({ url, name, title, location, snippet });
    });
    // Fallback: if no cards found, try generic profile link extraction
    if (results.length === 0) {
        document.querySelectorAll('a[href*="/in/"]').forEach(a => {
            const url = a.href.split('?')[0];
            if (seen.has(url)) return;
            seen.add(url);
            const container = a.closest('li, div[class*="result"]');
            const context = container
                ? container.innerText.replace(/\s+/g, ' ').slice(0, 200)
                : a.innerText.slice(0, 100);
            results.push({ url, name: a.innerText.trim(), title: '', location: '', snippet: context.trim() });
        });
    }
    return results.slice(0, MAX_ITEMS);
})()
""",

    "linkedin_profile": r"""
(() => {
    const get = sel => {
        const el = document.querySelector(sel);
        return el ? el.innerText.trim() : '';
    };
    const name = get('h1') || get('.text-heading-xlarge');
    const headline = get('.text-body-medium.break-words') || get('.pv-top-card--list li');
    const location = get('.text-body-small.inline.t-black--light.break-words');
    const about = get('#about ~ div .inline-show-more-text') || get('section.pv-about-section p');
    const experiences = [];
    document.querySelectorAll('#experience ~ div ul > li, section[id*="experience"] li').forEach(li => {
        const role = (li.querySelector('.t-bold span') || li.querySelector('.pv-entity__summary-info h3') || {}).innerText || '';
        const company = (li.querySelector('.t-normal span') || li.querySelector('.pv-entity__secondary-title') || {}).innerText || '';
        const dates = (li.querySelector('.pvs-entity__caption-wrapper') || li.querySelector('.pv-entity__date-range span:nth-child(2)') || {}).innerText || '';
        if (role || company) experiences.push({ role: role.trim(), company: company.trim(), dates: dates.trim() });
    });
    const education = [];
    document.querySelectorAll('#education ~ div ul > li, section[id*="education"] li').forEach(li => {
        const school = (li.querySelector('.t-bold span') || li.querySelector('.pv-entity__school-name') || {}).innerText || '';
        const degree = (li.querySelector('.t-normal span') || {}).innerText || '';
        if (school) education.push({ school: school.trim(), degree: degree.trim() });
    });
    return { name, headline, location, about: about.slice(0, 500), experiences: experiences.slice(0, 5), education: education.slice(0, 3) };
})()
""",

    "page_links": r"""
(() => {
    const seen = new Set();
    return [...document.querySelectorAll('a[href]')]
        .filter(a => {
            const href = a.href;
            if (!href || href.startsWith('javascript:') || seen.has(href)) return false;
            seen.add(href);
            return true;
        })
        .slice(0, MAX_ITEMS)
        .map(a => ({
            text: a.innerText.replace(/\s+/g, ' ').trim().slice(0, 100),
            href: a.href,
        }));
})()
""",

    "page_meta": r"""
(() => {
    const get = sel => {
        const el = document.querySelector(sel);
        return el ? (el.content || el.innerText || '').trim() : '';
    };
    return {
        title: document.title,
        url: location.href,
        description: get('meta[name="description"]') || get('meta[property="og:description"]'),
        og_title: get('meta[property="og:title"]'),
        og_image: get('meta[property="og:image"]'),
        canonical: get('link[rel="canonical"]'),
        h1: (document.querySelector('h1') || {}).innerText || '',
    };
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
