const sel = document.querySelector(arguments[0]);
const trig = sel?.querySelector('.mat-mdc-select-trigger') || sel;
if (!trig) return;
trig.scrollIntoView({block: 'center'});
if (arguments[1] === 1) {
    trig.click();
} else if (arguments[1] === 2) {
    trig.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    trig.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
    trig.click();
} else {
    sel.focus();
    sel.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', keyCode: 32, bubbles: true }));
}
