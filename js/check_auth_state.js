const href = window.location.href || '';
if (href.includes('accounts.google.com') || href.includes('ServiceLogin')) {
    return 'signed_out';
}
const accBtn = document.querySelector('ms-account-switcher button.account-switcher-button');
if (accBtn) {
    if (accBtn.classList.contains('signed-out')) return 'signed_out';
    const txt = (accBtn.querySelector('.account-switcher-text')?.textContent || accBtn.getAttribute('aria-label') || '').trim();
    if (txt.includes('@')) return 'signed_in';
}
return 'loading';