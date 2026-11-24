const href = window.location.href || '';
if (href.includes('accounts.google.com') || href.includes('ServiceLogin')) {
    return 'signed_out';
}
const accBtn = document.querySelector('ms-account-switcher button.account-switcher-button, ms-account-switcher button');
if (accBtn) {
    if (accBtn.classList.contains('signed-out')) return 'signed_out';
    const txt = (
        accBtn.querySelector('.account-switcher-text')?.textContent
        || accBtn.getAttribute('aria-label')
        || accBtn.innerText
        || ''
    ).trim();
    if (txt.includes('@')) return 'signed_in';
}
const emailEl = document.querySelector('ms-account-switcher [aria-label*="@"], ms-account-switcher [title*="@"], ms-account-switcher img[alt*="@"]');
if (emailEl) return 'signed_in';
const signInBtn = document.querySelector('ms-account-switcher .signed-out, ms-account-switcher a[href*="ServiceLogin"]');
if (signInBtn) return 'signed_out';
const promptBox = document.querySelector('ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]');
if (promptBox) {
    return 'signed_in';
}
return 'loading';
