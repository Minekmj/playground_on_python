const out = [];
const btns = document.querySelectorAll('ms-model-selector .model-categories-container button, ms-sliding-right-panel .model-categories-container button');
for (let i = 0; i < btns.length; i++) {
    const b = btns[i];
    if (b.classList.contains('alt-view-tab-button')) continue;
    const txt = (b.innerText || '').trim();
    if (!txt) continue;
    out.push({ idx: i, text: txt, active: b.classList.contains('ms-button-active') });
}
return out;
