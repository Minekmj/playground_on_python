const prevCount = arguments[0];
const includeThoughts = Boolean(arguments[1]);
const scroller = document.querySelector('ms-autoscroll-container');
if (scroller) scroller.scrollTop = scroller.scrollHeight;

const runBtn = document.querySelector('ms-run-button button');
let btnRunning = false;
if (runBtn) {
    const label = (runBtn.querySelector('.run-button-label')?.innerText || runBtn.getAttribute('aria-label') || '').toLowerCase();
    btnRunning = runBtn.classList.contains('stoppable')
        || !!runBtn.querySelector('.stoppable-spinner, .stoppable-stop')
        || label.includes('stop')
        || label.includes('중지');
}

const turns = Array.from(document.querySelectorAll('ms-chat-session ms-chat-turn'));
const newTurns = turns.slice(prevCount);

let lastUserIdx = -1;
newTurns.forEach((t, i) => {
    if (t.querySelector('[data-turn-role="User"]')) lastUserIdx = i;
});

const hasUserTurn = lastUserIdx >= 0;
const modelTurns = newTurns
    .slice(lastUserIdx + 1)
    .filter(t => t.querySelector('[data-turn-role="Model"]'));

let activeIndicator = false;
let imageCount = 0;
const errors = [];
const thoughtChunks = [];
const chunks = [];

const extractCleanText = (tc) => {
    const clone = tc.cloneNode(true);
    clone.querySelectorAll('.ignore-when-copying').forEach(n => n.remove());
    const codeBlocks = Array.from(clone.querySelectorAll('ms-code-block'));
    for (const cb of codeBlocks) {
        const lang = (cb.querySelector('.title-text')?.textContent || '').trim().toLowerCase();
        const codeEl = cb.querySelector('pre code, pre');
        const codeTxt = codeEl ? codeEl.textContent : '';
        const pre = document.createElement('pre');
        pre.textContent = "\n```" + lang + "\n" + codeTxt.replace(/\n$/, '') + "\n```\n";
        cb.replaceWith(pre);
    }
    clone.querySelectorAll('.material-symbols-outlined, .google-symbols, button').forEach(n => n.remove());
    return (clone.innerText || clone.textContent || '').trim();
};

for (const turn of modelTurns) {
    if (turn.querySelector('loading-indicator, .thinking-progress-icon.in-progress, ms-code-block .container.generating, ms-image-chunk .spinner-container')) {
        activeIndicator = true;
    }
    const errEl = turn.querySelector('.model-error');
    if (errEl) {
        const msg = (errEl.innerText || '').trim();
        if (msg) errors.push(msg);
    }

    for (const img of turn.querySelectorAll('ms-image-chunk img.loaded-image, img.markdown-image')) {
        if (!img.closest('ms-thought-chunk') && img.complete && img.naturalWidth > 0 && img.src) {
            imageCount += 1;
        }
    }

    if (includeThoughts) {
        for (const th of turn.querySelectorAll('ms-thought-chunk ms-text-chunk')) {
            const t = extractCleanText(th);
            if (t) thoughtChunks.push(t);
        }
    }

    const textChunks = Array.from(turn.querySelectorAll('ms-text-chunk')).filter(
        el => !el.closest('ms-thought-chunk')
    );
    for (const tc of textChunks) {
        const text = extractCleanText(tc);
        if (text) chunks.push(text);
    }
}

const lastModelTurn = modelTurns.length > 0 ? modelTurns[modelTurns.length - 1] : null;
const hasRerunBtn = !!(lastModelTurn && lastModelTurn.querySelector('button[name="rerun-button"]'));

const bodyText = chunks.join('\n\n').trim();
const thoughtText = thoughtChunks.join('\n\n').trim();
const finalText = (includeThoughts && thoughtText)
    ? ("[Thoughts]\n" + thoughtText + "\n\n[Answer]\n" + bodyText).trim()
    : bodyText;

return {
    totalTurns: turns.length,
    hasUserTurn: hasUserTurn,
    hasModelTurn: modelTurns.length > 0,
    isGenerating: btnRunning || activeIndicator,
    hasRerunBtn: hasRerunBtn,
    errors: errors,
    text: finalText,
    bodyLength: bodyText.length,
    imageCount: imageCount
};
