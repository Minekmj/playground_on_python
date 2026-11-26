const prevCount = arguments[0];
const done = arguments[arguments.length - 1];

const getModelTurns = () => {
    const turns = Array.from(document.querySelectorAll('ms-chat-session ms-chat-turn'));
    const newTurns = turns.slice(prevCount);
    let lastUserIdx = -1;
    newTurns.forEach((t, i) => {
        if (t.querySelector('[data-turn-role="User"]')) lastUserIdx = i;
    });
    return newTurns
        .slice(lastUserIdx + 1)
        .filter(t => t.querySelector('[data-turn-role="Model"]'));
};

const collectTurnImages = (modelTurns) => {
    const imgs = [];
    for (const turn of modelTurns) {
        for (const img of turn.querySelectorAll('ms-image-chunk img.loaded-image, img.markdown-image')) {
            if (!img.closest('ms-thought-chunk') && img.complete && img.naturalWidth > 0 && img.src) {
                imgs.push(img);
            }
        }
    }
    return imgs;
};

const imageToDataUrl = async (img) => {
    const src = img.src;
    if (src.startsWith('data:')) return src;

    try {
        const resp = await fetch(src);
        const blob = await resp.blob();
        return await new Promise((resolve, reject) => {
            const fr = new FileReader();
            fr.onload = () => resolve(String(fr.result || ''));
            fr.onerror = reject;
            fr.readAsDataURL(blob);
        });
    } catch (e) {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        canvas.getContext('2d').drawImage(img, 0, 0);
        return canvas.toDataURL('image/png');
    }
};

(async () => {
    try {
        const imgs = collectTurnImages(getModelTurns());
        const out = [];
        for (const img of imgs) {
            const dataUrl = await imageToDataUrl(img);
            if (dataUrl) {
                out.push({
                    data_url: dataUrl,
                    width: img.naturalWidth,
                    height: img.naturalHeight,
                });
            }
        }
        done(out);
    } catch (err) {
        done([]);
    }
})();
