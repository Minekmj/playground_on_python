const bds = document.querySelectorAll('.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop');
return Array.from(bds).some(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
});
