const box = document.querySelector('ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]');
const accBtn = document.querySelector('ms-account-switcher button.account-switcher-button');
if (!box || !accBtn) return false;
if (accBtn.classList.contains('signed-out')) return false;
const txt = (accBtn.querySelector('.account-switcher-text')?.innerText || accBtn.getAttribute('aria-label') || '').trim();
return txt.includes('@');
