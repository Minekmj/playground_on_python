const label = arguments[0].toLowerCase();
const headers = document.querySelectorAll('ms-run-settings .settings-group-header');
for (const h of headers) {
    const btn = h.querySelector('button');
    const btnLabel = (btn?.getAttribute('aria-label') || '').toLowerCase();
    const title = (h.querySelector('.group-title')?.innerText || '').toLowerCase();
    if (btnLabel.includes(label) || title.includes(label)) {
        if (!h.classList.contains('expanded')) {
            (btn || h).click();
            return false;
        }
        return true;
    }
}
return true;
