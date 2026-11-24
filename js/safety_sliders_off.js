const dlg = document.querySelector('mat-dialog-container, .cdk-overlay-pane [role="dialog"], .cdk-overlay-popover [role="dialog"]');
if (!dlg) return;
for (const r of dlg.querySelectorAll('input[type="range"]')) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(r, r.min || '0');
    r.dispatchEvent(new Event('input', { bubbles: true }));
    r.dispatchEvent(new Event('change', { bubbles: true }));
}
