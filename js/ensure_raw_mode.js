const want = arguments[0] !== false;

const directSwitch = document.querySelector('ms-run-settings button[role="switch"][aria-label*="raw" i]')
    || Array.from(document.querySelectorAll('ms-run-settings button[role="switch"]')).find(
        b => (b.getAttribute('aria-label') || '').toLowerCase().includes('raw mode')
    );

if (directSwitch) {
    if (directSwitch.disabled || directSwitch.classList.contains('mdc-switch--disabled')) {
        return { status: 'disabled' };
    }
    const checked = directSwitch.getAttribute('aria-checked') === 'true';
    if (checked === want) return { status: 'already', method: 'switch' };
    directSwitch.scrollIntoView({ block: 'center' });
    directSwitch.click();
    return { status: 'toggled', method: 'switch' };
}

const findMenuItems = () => Array.from(
    document.querySelectorAll(
        '.cdk-overlay-container [role="menuitem"], '
        + '.cdk-overlay-container [role="menuitemcheckbox"], '
        + '.mat-mdc-menu-panel button.mat-mdc-menu-item'
    )
).filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
});

const findRawModeItem = () => findMenuItems().find(el => {
    const txt = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
    return txt.includes('raw mode') || txt.includes('원본 모드');
});

let menuItem = findRawModeItem();
let openedMenu = false;

if (!menuItem) {
    const moreBtnCandidates = Array.from(document.querySelectorAll(
        'ms-toolbar button[aria-label*="more" i], '
        + 'ms-header-actions button[aria-label*="more" i], '
        + 'header button[aria-label*="more" i], '
        + 'button[aria-label="More options"], '
        + 'button[aria-label="More actions"]'
    )).filter(b => !b.closest('ms-chat-turn') && !b.closest('ms-run-settings'));

    const iconFallback = moreBtnCandidates.length > 0
        ? moreBtnCandidates
        : Array.from(document.querySelectorAll('button')).filter(b => {
            if (b.closest('ms-chat-turn') || b.closest('ms-run-settings')) return false;
            const r = b.getBoundingClientRect();
            if (r.width === 0 || r.height === 0 || r.top > 140) return false;
            const icon = (b.querySelector('.material-symbols-outlined, .google-symbols')?.textContent || '').trim();
            return icon === 'more_vert';
        });

    if (iconFallback.length === 0) {
        return { status: 'missing_button' };
    }
    iconFallback[0].click();
    openedMenu = true;
    menuItem = findRawModeItem();
}

if (!menuItem) {
    return { status: openedMenu ? 'opened_wait' : 'missing_item' };
}

const isItemChecked = (el) => {
    if (el.getAttribute('aria-checked') === 'true') return true;
    const sw = el.querySelector('[role="switch"], input[type="checkbox"]');
    if (sw && (sw.checked || sw.getAttribute('aria-checked') === 'true')) return true;
    if (el.querySelector('.mdc-switch--checked, .mat-mdc-slide-toggle-checked')) return true;
    const icons = Array.from(el.querySelectorAll('.material-symbols-outlined, .google-symbols'))
        .map(i => (i.textContent || '').trim().toLowerCase());
    return icons.some(t => t === 'check' || t === 'check_box' || t === 'toggle_on');
};

const currentlyOn = isItemChecked(menuItem);
if (currentlyOn === want) {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    return { status: 'already', method: 'menu' };
}

menuItem.click();
return { status: 'toggled', method: 'menu' };
