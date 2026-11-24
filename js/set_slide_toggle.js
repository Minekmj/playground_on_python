const label = arguments[0];
const want = arguments[1];
const btn = document.querySelector(`ms-run-settings button[role="switch"][aria-label="${label}"]`)
    || Array.from(document.querySelectorAll('ms-run-settings button[role="switch"]')).find(
        b => (b.getAttribute('aria-label') || '').toLowerCase().includes(label.toLowerCase())
    );
if (!btn) return 'missing';
if (btn.disabled || btn.classList.contains('mdc-switch--disabled')) return 'disabled';
const checked = btn.getAttribute('aria-checked') === 'true';
if (checked === want) return 'already';
btn.scrollIntoView({block: 'center'});
btn.click();
return 'toggled';
