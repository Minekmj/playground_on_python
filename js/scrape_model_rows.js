const catLabel = arguments[0];
const out = [];
for (const row of document.querySelectorAll('ms-model-carousel-row')) {
    const r = row.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const title = (row.querySelector('.model-title-text')?.innerText || '').trim();
    const subtitle = (row.querySelector('.model-subtitle')?.innerText || '').trim();
    if (!title && !subtitle) continue;

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
        .join(' | ');
    const dLow = detailsTxt.toLowerCase();
    if (
        dLow.includes('paid only')
        || dLow.includes('paid tier only')
        || dLow.includes('requires billing')
        || dLow.includes('not available on free')
        || dLow.includes('유료 등급')
        || dLow.includes('결제 필요')
    ) {
        isPaid = true;
    }

    const icon = (row.querySelector('.model-icon')?.innerText || '').trim();
    const selected = row.classList.contains('selected');

    let modelId = '';
    const candidates = (subtitle + ' ' + title).match(/[a-z0-9][a-z0-9._-]*-(?:[a-z0-9._-]+)+/gi) || [];
    if (candidates.length > 0) {
        modelId = candidates[0].toLowerCase();
    } else {
        modelId = title.toLowerCase().replace(/\s+/g, '-');
    }

    out.push({
        id: modelId,
        name: title,
        subtitle: subtitle,
        badges: badges,
        is_paid: isPaid,
        category_tab: catLabel,
        icon: icon,
        selected: selected,
        disabled: row.classList.contains('disabled')
    });
}
return out;
