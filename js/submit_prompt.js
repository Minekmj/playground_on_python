const btn = document.querySelector('ms-run-button button');
const ta = document.querySelector('ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]');
if (arguments[0] <= 2 && btn) {
    btn.scrollIntoView({block: 'center'});
    btn.click();
} else if (ta) {
    ta.focus();
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, ctrlKey: true, bubbles: true }));
}
