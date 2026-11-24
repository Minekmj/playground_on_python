const directSels = arguments[0];
const keywords = arguments[1];
const val = arguments[2];
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
for (const sel of directSels) {
    const inp = document.querySelector(sel);
    if (inp && !inp.disabled) {
        inp.scrollIntoView({block: 'center'});
        setter.call(inp, val);
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        inp.dispatchEvent(new Event('blur', { bubbles: true }));
        return true;
    }
}
const items = document.querySelectorAll('ms-run-settings .settings-item');
for (const item of items) {
    const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
    if (!keywords.some(k => title.includes(k))) continue;
    const inp = item.querySelector('input[type="number"], input[type="text"], input');
    if (!inp || inp.disabled) continue;
    inp.scrollIntoView({block: 'center'});
    setter.call(inp, val);
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    inp.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
}
return false;
