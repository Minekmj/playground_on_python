const card = document.querySelector('ms-model-selector button.model-selector-card');
if (!card) return null;
return {
    title: (card.querySelector('.title')?.innerText || '').trim().toLowerCase(),
    id: (card.querySelector('[data-test-id="model-name"]')?.innerText || '').trim().toLowerCase().replace(/^models\//, '')
};
