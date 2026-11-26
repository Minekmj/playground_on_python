const prevCount = arguments[0];
const includeThoughts = Boolean(arguments[1]);

const scroller = document.querySelector('ms-autoscroll-container');
if (scroller) {
    scroller.scrollTop = scroller.scrollHeight;
}

const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
        return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
};

const isRunButtonActive = (runBtns, promptEmpty) => {
    for (const btn of runBtns) {
        if (!isVisible(btn)) continue;

        const label = (
            btn.querySelector('.run-button-label')?.innerText
            || btn.innerText
            || btn.getAttribute('aria-label')
            || ''
        ).toLowerCase();
        const iconTxt = (
            btn.querySelector('.material-symbols-outlined, .google-symbols')?.textContent || ''
        ).trim().toLowerCase();
        const hasStopRect = !!btn.querySelector('svg rect');
        const isEnabledStopCandidate = (
            promptEmpty && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true'
        );

        if (
            btn.classList.contains('stoppable')
            || !!btn.querySelector('.stoppable-spinner, .stoppable-stop, mat-spinner, mat-progress-spinner')
            || label.includes('stop')
            || label.includes('중지')
            || label.includes('cancel')
            || iconTxt === 'stop'
            || iconTxt === 'stop_circle'
            || iconTxt === 'square'
            || hasStopRect
            || isEnabledStopCandidate
        ) {
            return true;
        }
    }
    return false;
};

const isIgnoredNode = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const tag = el.tagName;
    if (tag === 'BUTTON' || tag === 'STYLE' || tag === 'SCRIPT') return true;
    return (
        el.classList.contains('ignore-when-copying')
        || el.classList.contains('material-symbols-outlined')
        || el.classList.contains('google-symbols')
        || el.classList.contains('actions-container')
    );
};

const wrapInline = (inner, marker) => {
    if (!inner) return '';
    const m = inner.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!m || !m[2]) return inner;
    return m[1] + marker + m[2] + marker + m[3];
};

const serializeChildren = (el, ctx) => {
    let out = '';
    for (const child of el.childNodes) {
        out += nodeToMd(child, ctx);
    }
    return out;
};

const serializeList = (listEl, ordered, depth) => {
    const items = [];
    let num = parseInt(listEl.getAttribute('start') || '1', 10) || 1;
    const indent = '  '.repeat(depth);
    const directLis = Array.from(listEl.querySelectorAll('li')).filter(
        li => li.closest('ul, ol') === listEl
    );
    const blockTags = ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'PRE', 'MS-CODE-BLOCK', 'TABLE', 'MS-KATEX'];

    for (const child of directLis) {
        const prefix = ordered ? `${num}. ` : '- ';
        if (ordered) num += 1;

        const mainParts = [];
        const subLists = [];

        const walkLi = (node) => {
            if (!node) return;
            if (node.nodeType === 1 && (node.tagName === 'UL' || node.tagName === 'OL')) {
                subLists.push(serializeList(node, node.tagName === 'OL', depth + 1).trimEnd());
                return;
            }
            if (
                node.nodeType === 1
                && !isIgnoredNode(node)
                && !blockTags.includes(node.tagName)
                && node.querySelector
                && node.querySelector('ul, ol')
            ) {
                for (const sub of node.childNodes) {
                    walkLi(sub);
                }
                return;
            }
            const part = nodeToMd(node, { inPre: false, listDepth: depth + 1 });
            if (part) mainParts.push(part);
        };

        for (const liChild of child.childNodes) {
            walkLi(liChild);
        }

        const body = mainParts
            .join('')
            .replace(/\n{3,}/g, '\n\n')
            .trim()
            .replace(/\n/g, `\n${indent}  `);

        let line = `${indent}${prefix}${body}`;
        if (subLists.length > 0) {
            line += '\n' + subLists.map(s => s.replace(/^\n+/, '')).join('\n');
        }
        items.push(line);
    }

    return items.length > 0 ? '\n\n' + items.join('\n') + '\n\n' : '';
};

const serializeTable = (tableEl) => {
    const rows = Array.from(tableEl.querySelectorAll('tr'));
    if (rows.length === 0) return '';

    const mdRows = rows.map(tr => {
        const cells = Array.from(tr.querySelectorAll('th, td')).map(cell =>
            serializeChildren(cell, { inPre: false, listDepth: 0 })
                .replace(/\n+/g, ' ')
                .replace(/\|/g, '\\|')
                .trim()
        );
        return '| ' + cells.join(' | ') + ' |';
    });

    if (mdRows.length >= 1) {
        const colCount = Math.max(1, rows[0].querySelectorAll('th, td').length);
        const sep = '| ' + Array(colCount).fill('---').join(' | ') + ' |';
        mdRows.splice(1, 0, sep);
    }

    return '\n\n' + mdRows.join('\n') + '\n\n';
};

const serializeCodeBlock = (node, withLang) => {
    const lang = withLang
        ? (node.querySelector('.title-text')?.textContent || '').trim().toLowerCase()
        : '';
    const codeEl = withLang ? node.querySelector('pre code, pre') : node;
    const codeTxt = (codeEl ? codeEl.textContent : '').replace(/\n$/, '');
    const fence = codeTxt.includes('```') ? '````' : '```';
    return `\n\n${fence}${lang}\n${codeTxt}\n${fence}\n\n`;
};

const serializeInlineNode = (tag, node, ctx) => {
    if (tag === 'CODE' || node.classList.contains('inline-code')) {
        const raw = node.textContent || '';
        if (!raw) return '';
        const tick = raw.includes('`') ? '``' : '`';
        const pad = raw.includes('`') ? ' ' : '';
        return `${tick}${pad}${raw}${pad}${tick}`;
    }
    if (tag === 'STRONG' || tag === 'B') {
        return wrapInline(serializeChildren(node, ctx), '**');
    }
    if (tag === 'EM' || tag === 'I' || (tag === 'SPAN' && node.style && node.style.fontStyle === 'italic')) {
        return wrapInline(serializeChildren(node, ctx), '*');
    }
    if (tag === 'DEL' || tag === 'S') {
        return wrapInline(serializeChildren(node, ctx), '~~');
    }
    if (tag === 'A') {
        const label = serializeChildren(node, ctx).trim();
        const href = (node.getAttribute('href') || '').trim();
        if (href && !href.startsWith('javascript:') && label && label !== href) {
            return `[${label}](${href})`;
        }
        return label || href;
    }
    if (tag === 'IMG') {
        const src = (node.getAttribute('src') || '').trim();
        const alt = (node.getAttribute('alt') || '').trim();
        return (src && !src.startsWith('data:')) ? `![${alt}](${src})` : '';
    }
    return null;
};

const nodeToMd = (node, ctx = { inPre: false, listDepth: 0 }) => {
    if (!node) return '';
    if (node.nodeType === 3) return node.nodeValue || '';
    if (node.nodeType !== 1 || isIgnoredNode(node)) return '';

    const tag = node.tagName;
    if (tag === 'MS-CODE-BLOCK') return serializeCodeBlock(node, true);
    if (node.classList.contains('very-large-text-container') || node.classList.contains('user-chunk')) {
        return node.textContent || '';
    }
    if (tag === 'MS-KATEX') {
        const tex = node.querySelector('annotation[encoding="application/x-tex"]')?.textContent?.trim();
        if (tex) {
            return node.querySelector('.katex-display') ? `\n\n$$\n${tex}\n$$\n\n` : `$${tex}$`;
        }
        return node.textContent || '';
    }
    if (tag === 'PRE') return serializeCodeBlock(node, false);
    if (tag === 'BR') return '\n';
    if (tag === 'HR') return '\n\n---\n\n';

    const inlineVal = serializeInlineNode(tag, node, ctx);
    if (inlineVal !== null) return inlineVal;

    if (tag === 'MAT-CHECKBOX') {
        const checked = node.querySelector('input')?.checked || node.classList.contains('mat-mdc-checkbox-checked');
        return checked ? '[x] ' : '[ ] ';
    }
    if (/^H[1-6]$/.test(tag)) {
        const heading = serializeChildren(node, ctx).trim();
        return heading ? `\n\n${'#'.repeat(parseInt(tag[1], 10))} ${heading}\n\n` : '';
    }
    if (tag === 'P') {
        const body = serializeChildren(node, ctx).trim();
        return body ? `\n\n${body}\n\n` : '';
    }
    if (tag === 'BLOCKQUOTE') {
        const inner = serializeChildren(node, ctx).replace(/\n{3,}/g, '\n\n').trim();
        if (!inner) return '';
        const quoted = inner.split('\n').map(l => (l.trim() ? `> ${l}` : '>')).join('\n');
        return `\n\n${quoted}\n\n`;
    }
    if (tag === 'UL') return serializeList(node, false, ctx.listDepth || 0);
    if (tag === 'OL') return serializeList(node, true, ctx.listDepth || 0);
    if (tag === 'TABLE') return serializeTable(node);
    if (tag === 'DETAILS') {
        const summary = node.querySelector('summary');
        const sTxt = summary ? serializeChildren(summary, ctx).trim() : '';
        let body = '';
        for (const ch of node.childNodes) {
            if (ch !== summary) body += nodeToMd(ch, ctx);
        }
        return `\n\n${sTxt ? `**${sTxt}**\n` : ''}${body.trim()}\n\n`;
    }
    return serializeChildren(node, ctx);
};

const extractCleanMarkdown = (tc) => {
    const raw = nodeToMd(tc, { inPre: false, listDepth: 0 });
    return raw.replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
};

const hasActiveStatusText = (root, selector, pattern) => {
    for (const el of root.querySelectorAll(selector)) {
        if (!isVisible(el)) continue;
        if (el.closest('ms-text-chunk') && !el.closest('ms-thought-chunk')) continue;
        const t = (el.textContent || '').trim();
        if (t.length > 0 && t.length <= 80 && pattern.test(t)) {
            return true;
        }
    }
    return false;
};

const promptTa = document.querySelector(
    'ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]'
);
const promptEmpty = !promptTa || !(promptTa.value || '').trim();
const runBtns = Array.from(document.querySelectorAll('ms-run-button button'));
const btnRunning = isRunButtonActive(runBtns, promptEmpty);

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
let thoughtLength = 0;
const errors = [];
const thoughtChunks = [];
const chunks = [];

const turnStatusSel = (
    'ms-thought-chunk > div, ms-thought-chunk span, ms-thought-chunk p, '
    + '.thinking-header, .thought-header, .turn-status, .status-text, '
    + '[class*="thinking"], [class*="status"]'
);
const turnIndicatorSel = (
    'loading-indicator, mat-progress-bar, mat-progress-spinner, mat-spinner, '
    + '[role="progressbar"], .thinking-progress-icon.in-progress, '
    + 'ms-code-block .container.generating, ms-image-chunk .spinner-container, '
    + '.generating, .streaming, .in-progress'
);
const turnStatusRe = /^(still\s+(thinking|working|generating|reasoning)|thinking\.{2,3}|generating\.{2,3}|생각\s*중|생성\s*중)/i;

for (const turn of modelTurns) {
    if (turn.querySelector(turnIndicatorSel)) {
        activeIndicator = true;
    }
    if (!activeIndicator && hasActiveStatusText(turn, turnStatusSel, turnStatusRe)) {
        activeIndicator = true;
    }

    for (const thEl of turn.querySelectorAll('ms-thought-chunk')) {
        thoughtLength += (thEl.innerText || thEl.textContent || '').trim().length;
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
            const t = extractCleanMarkdown(th);
            if (t) thoughtChunks.push(t);
        }
    }

    const textChunks = Array.from(turn.querySelectorAll('ms-text-chunk')).filter(
        el => !el.closest('ms-thought-chunk')
    );
    for (const tc of textChunks) {
        const text = extractCleanMarkdown(tc);
        if (text) chunks.push(text);
    }
}

if (!activeIndicator) {
    const globalSel = (
        'ms-chat-session [class*="status"], ms-chat-session [class*="thinking"], '
        + 'ms-chat-session [class*="progress"], ms-autoscroll-container [class*="loading"]'
    );
    const globalRe = /^(still\s+(thinking|working|generating|reasoning)|생각\s*중|생성\s*중)/i;
    activeIndicator = hasActiveStatusText(document, globalSel, globalRe);
}

const lastModelTurn = modelTurns.length > 0 ? modelTurns[modelTurns.length - 1] : null;
const hasRerunBtn = !!(
    lastModelTurn
    && Array.from(lastModelTurn.querySelectorAll('button[name="rerun-button"]'))
        .some(b => isVisible(b) && !b.disabled)
);

const bodyText = chunks.join('\n\n').trim();
const thoughtText = thoughtChunks.join('\n\n').trim();
const finalText = (includeThoughts && thoughtText)
    ? (`[Thoughts]\n${thoughtText}\n\n[Answer]\n${bodyText}`).trim()
    : bodyText;

const debugRunBtns = runBtns.map(b => ({
    vis: isVisible(b),
    dis: !!b.disabled,
    ariaDis: b.getAttribute('aria-disabled'),
    ariaLbl: b.getAttribute('aria-label') || '',
    cls: b.className || '',
    txt: (b.innerText || '').trim().slice(0, 40),
}));

const debugTurnBtns = lastModelTurn
    ? Array.from(lastModelTurn.querySelectorAll('button'))
        .filter(b => isVisible(b))
        .slice(0, 12)
        .map(b => ({
            name: b.getAttribute('name') || '',
            ariaLbl: b.getAttribute('aria-label') || '',
            dis: !!b.disabled,
            txt: (b.innerText || '').trim().slice(0, 30),
        }))
    : [];

return {
    totalTurns: turns.length,
    hasUserTurn,
    hasModelTurn: modelTurns.length > 0,
    isGenerating: btnRunning || activeIndicator,
    btnRunning,
    activeIndicator,
    hasRerunBtn,
    errors,
    text: finalText,
    bodyLength: bodyText.length,
    thoughtLength,
    imageCount,
    debug: {
        promptEmpty,
        runBtns: debugRunBtns,
        turnBtns: debugTurnBtns,
        runHost: (document.querySelector('ms-run-button')?.outerHTML || '').slice(0, 300),
    },
};
