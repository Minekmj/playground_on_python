const dlg = document.querySelector('mat-dialog-container, .cdk-overlay-pane [role="dialog"], .cdk-overlay-popover [role="dialog"]');
if (!dlg) return;
const btns = Array.from(dlg.querySelectorAll('button'));
const confirmBtn = btns.find(b => /save|apply|done|update|확인|저장|적용|닫기|close/i.test((b.innerText || b.getAttribute('aria-label') || '').trim()));
if (confirmBtn) { confirmBtn.click(); return; }
document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
