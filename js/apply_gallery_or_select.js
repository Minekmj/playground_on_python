const gallerySels = arguments[0];
const keywords = arguments[1];
const target = arguments[2];

const tryGallery = (root) => {
    if (!root) return false;

    const btns = Array.from(root.querySelectorAll('button, [role="button"], .toggle-button'));
    let best = null;
    for (const b of btns) {
        const txt = (b.innerText || b.getAttribute('aria-label') || '').trim().toLowerCase();
        if (!txt) continue;
        if (txt === target) {
            best = b;
            break;
        }
        if (!best && txt.includes(target)) {
            best = b;
        }
    }

    if (!best) return false;
    best.scrollIntoView({ block: 'center' });
    best.click();
    return true;
};

for (const sel of gallerySels) {
    const g = document.querySelector(sel);
    if (g && tryGallery(g)) return true;
}

for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
    const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
    if (keywords.some(k => title.includes(k)) && tryGallery(item)) {
        return true;
    }
}

return false;
