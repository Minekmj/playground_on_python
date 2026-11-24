const box = document.querySelector('ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]');
if (!box) return false;
const accBtn = document.querySelector('ms-account-switcher button.account-switcher-button, ms-account-switcher button');
if (accBtn && accBtn.classList.contains('signed-out')) return false;
const signInBtn = document.querySelector('ms-account-switcher .signed-out, ms-account-switcher a[href*="ServiceLogin"]');
if (signInBtn) return false;
return true;
