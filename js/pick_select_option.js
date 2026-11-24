const cands = arguments[0];
const sels = [
    'div.mat-mdc-select-panel mat-option',
    '.cdk-overlay-popover mat-option',
    '.cdk-overlay-container mat-option',
    'mat-option.mat-mdc-option',
    '[role="listbox"] [role="option"]'
];
let opts = [];
for (const s of sels) {
    const found = Array.from(document.querySelectorAll(s)).filter(o => o.offsetParent !== null || o.getClientRects().length > 0);
    if (found.length > 0) { opts = found; break; }
}
for (const cand of cands) {
    for (const opt of opts) {
        const raw = (opt.innerText || '').trim().toLowerCase();
        const first = (raw.split(/\n/)[0] || '').trim();
        if (first === cand || first.startsWith(cand) || raw.includes(cand)) {
            opt.click();
            return (opt.innerText || '').trim().split(/\n/)[0];
        }
    }
}
return null;
