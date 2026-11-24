const sel = document.querySelector(arguments[0]);
if (!sel) return null;
return {
    disabled: sel.getAttribute('aria-disabled') === 'true',
    text: (sel.innerText || '').trim()
};
