const directSels = arguments[0];
const keywords = arguments[1];
const val = arguments[2];

const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;

const applyInput = (inp) => {
    if (!inp || inp.disabled) return false;
    inp.scrollIntoView({ block: 'center' });
    setter.call(inp, val);
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    inp.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
};

for (const sel of directSels) {
    if (applyInput(document.querySelector(sel))) return true;
}

for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
    const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
    if (!keywords.some(k => title.includes(k))) continue;
    const inp = item.querySelector('input[type="number"], input[type="text"], input');
    if (applyInput(inp)) return true;
}

return false;
