const accBtn = document.querySelector('ms-account-switcher button.account-switcher-button');
const email = (accBtn?.querySelector('.account-switcher-text')?.innerText || '').trim();
const label = (accBtn?.getAttribute('aria-label') || '').trim();
const canonical = document.querySelector('link[rel="canonical"]')?.getAttribute('href') || '';
const url = window.location.href || canonical;
return { email, label, url };
