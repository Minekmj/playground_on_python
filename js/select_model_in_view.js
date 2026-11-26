const target = arguments[0];

const search = document.querySelector('ms-model-selector input, ms-sliding-right-panel input');
if (search) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(search, target);
    search.dispatchEvent(new Event('input', { bubbles: true }));
    search.dispatchEvent(new Event('change', { bubbles: true }));
}

const findBestRow = () => {
    let best = null;
    for (const row of document.querySelectorAll('ms-model-carousel-row')) {
        const title = (row.querySelector('.model-title-text')?.innerText || '').trim().toLowerCase();
        const sub = (row.querySelector('.model-subtitle')?.innerText || '').trim().toLowerCase();
        const full = (row.innerText || '').trim().toLowerCase();

        if (title === target || sub === target || full.split(/\n/).includes(target)) {
            return row;
        }
        if (!best && (title.includes(target) || sub.includes(target) || full.includes(target))) {
            best = row;
        }
    }
    return best;
};

const best = findBestRow();
if (!best) return null;

const isPaid = Array.from(best.querySelectorAll('ms-badge')).some(
    b => b.classList.contains('paid') || ['paid', '유료'].includes((b.innerText || '').trim().toLowerCase())
);
const btn = best.querySelector('button.content-button') || best;
btn.scrollIntoView({ block: 'center' });
btn.click();

return {
    name: (best.querySelector('.model-title-text')?.innerText || '').trim(),
    is_paid: isPaid,
};
