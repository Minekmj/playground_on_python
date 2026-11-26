const catLabel = arguments[0];

const parseBadgesAndPaid = (row) => {
    const badges = [];
    let isPaid = false;

    for (const b of row.querySelectorAll('ms-badge')) {
        const bt = (b.innerText || '').trim();
        if (bt) badges.push(bt);
        const bLow = bt.toLowerCase();
        if (b.classList.contains('paid') || ['paid', '유료', 'paid tier', 'billing'].includes(bLow)) {
            isPaid = true;
        }
    }

    const detailsTxt = Array.from(row.querySelectorAll('.model-details li, .agent-pricing-row'))
        .map(el => (el.innerText || '').trim())
        .join(' | ')
        .toLowerCase();

    if (
        detailsTxt.includes('paid only')
        || detailsTxt.includes('paid tier only')
        || detailsTxt.includes('requires billing')
        || detailsTxt.includes('not available on free')
        || detailsTxt.includes('유료 등급')
        || detailsTxt.includes('결제 필요')
    ) {
        isPaid = true;
    }

    return { badges, isPaid };
};

const resolveModelId = (title, subtitle) => {
    const candidates = (subtitle + ' ' + title).match(/[a-z0-9][a-z0-9._-]*-(?:[a-z0-9._-]+)+/gi) || [];
    if (candidates.length > 0) return candidates[0].toLowerCase();
    return title.toLowerCase().replace(/\s+/g, '-');
};

const out = [];
for (const row of document.querySelectorAll('ms-model-carousel-row')) {
    const r = row.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;

    const title = (row.querySelector('.model-title-text')?.innerText || '').trim();
    const subtitle = (row.querySelector('.model-subtitle')?.innerText || '').trim();
    if (!title && !subtitle) continue;

    const { badges, isPaid } = parseBadgesAndPaid(row);
    out.push({
        id: resolveModelId(title, subtitle),
        name: title,
        subtitle,
        badges,
        is_paid: isPaid,
        category_tab: catLabel,
        icon: (row.querySelector('.model-icon')?.innerText || '').trim(),
        selected: row.classList.contains('selected'),
        disabled: row.classList.contains('disabled'),
    });
}

return out;
