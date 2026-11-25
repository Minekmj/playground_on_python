const prevCount = arguments[0];
const includeThoughts = Boolean(arguments[1]);
const scroller = document.querySelector('ms-autoscroll-container');
if (scroller) scroller.scrollTop = scroller.scrollHeight;
const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
};
const runBtns = Array.from(document.querySelectorAll('ms-run-button button'));
let btnRunning = false;
for (const btn of runBtns) {
    if (!isVisible(btn)) continue;
    const label = (
        btn.querySelector('.run-button-label')?.innerText
        || btn.innerText
        || btn.getAttribute('aria-label')
        || ''
    ).toLowerCase();
    const iconTxt = (btn.querySelector('.material-symbols-outlined, .google-symbols')?.textContent || '').trim().toLowerCase();
    if (
        btn.classList.contains('stoppable')
        || !!btn.querySelector('.stoppable-spinner, .stoppable-stop, mat-spinner, mat-progress-spinner')
        || label.includes('stop')
        || label.includes('중지')
        || iconTxt === 'stop'
        || iconTxt === 'stop_circle'
    ) {
        btnRunning = true;
        break;
    }
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
const isIgnoredNode = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const tag = el.tagName;
    if (tag === 'BUTTON' || tag === 'STYLE' || tag === 'SCRIPT') return true;
    if (el.classList.contains('ignore-when-copying')) return true;
    if (el.classList.contains('material-symbols-outlined')) return true;
    if (el.classList.contains('google-symbols')) return true;
    if (el.classList.contains('actions-container')) return true;
    return false;
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
    for (const child of listEl.children) {
        if (child.tagName !== 'LI') continue;
        const prefix = ordered ? `${num}. ` : '- ';
        if (ordered) num += 1;
        let mainParts = [];
        let subLists = [];
        for (const liChild of child.childNodes) {
            if (liChild.nodeType === 1 && (liChild.tagName === 'UL' || liChild.tagName === 'OL')) {
                subLists.push(serializeList(liChild, liChild.tagName === 'OL', depth + 1));
            } else {
                const part = nodeToMd(liChild, { inPre: false, listDepth: depth + 1 });
                if (part) mainParts.push(part);
            }
        }
        const body = mainParts.join('').replace(/\n{3,}/g, '\n\n').trim().replace(/\n/g, `\n${indent}  `);
        let line = `${indent}${prefix}${body}`;
        if (subLists.length > 0) {
            line += '\n' + subLists.join('\n');
        }
        items.push(line);
    }
    return '\n\n' + items.join('\n') + '\n\n';
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
const nodeToMd = (node, ctx = { inPre: false, listDepth: 0 }) => {
    if (!node) return '';
    if (node.nodeType === 3) {
        return node.nodeValue || '';
    }
    if (node.nodeType !== 1) return '';
    if (isIgnoredNode(node)) return '';
    const tag = node.tagName;
    if (tag === 'MS-CODE-BLOCK') {
        const lang = (node.querySelector('.title-text')?.textContent || '').trim().toLowerCase();
        const codeEl = node.querySelector('pre code, pre');
        const codeTxt = (codeEl ? codeEl.textContent : '').replace(/\n$/, '');
        const fence = codeTxt.includes('```') ? '````' : '```';
        return `\n\n${fence}${lang}\n${codeTxt}\n${fence}\n\n`;
    }
    if (node.classList.contains('very-large-text-container') || node.classList.contains('user-chunk')) {
        return node.textContent || '';
    }
    if (tag === 'MS-KATEX') {
        const tex = node.querySelector('annotation[encoding="application/x-tex"]')?.textContent?.trim();
        if (tex) {
            const isDisplay = !!node.querySelector('.katex-display');
            return isDisplay ? `\n\n$$\n${tex}\n$$\n\n` : `$${tex}$`;
        }
        return node.textContent || '';
    }
    if (tag === 'PRE') {
        const codeTxt = (node.textContent || '').replace(/\n$/, '');
        const fence = codeTxt.includes('```') ? '````' : '```';
        return `\n\n${fence}\n${codeTxt}\n${fence}\n\n`;
    }
    if (tag === 'BR') return '\n';
    if (tag === 'HR') return '\n\n---\n\n';
    if (tag === 'CODE' || node.classList.contains('inline-code')) {
        const raw = (node.textContent || '');
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
        if (src && !src.startsWith('data:')) {
            return `![${alt}](${src})`;
        }
        return '';
    }
    if (tag === 'MAT-CHECKBOX') {
        const checked = node.querySelector('input')?.checked || node.classList.contains('mat-mdc-checkbox-checked');
        return checked ? '[x] ' : '[ ] ';
    }
    if (/^H[1-6]$/.test(tag)) {
        const lvl = parseInt(tag[1], 10);
        const heading = serializeChildren(node, ctx).trim();
        return heading ? `\n\n${'#'.repeat(lvl)} ${heading}\n\n` : '';
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
const lastModelTurn = modelTurns.length > 0 ? modelTurns[modelTurns.length - 1] : null;
const hasRerunBtn = !!(
    lastModelTurn
    && Array.from(lastModelTurn.querySelectorAll(
        'button[name="rerun-button"], .actions-container button[aria-label*="Good" i], .actions-container button[aria-label*="Copy" i], ms-chat-turn-options button'
    )).some(b => isVisible(b) && !b.disabled)
);
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