const prevCount = arguments[0];
const done = arguments[arguments.length - 1];
(async () => {
    try {
        const turns = Array.from(document.querySelectorAll('ms-chat-session ms-chat-turn'));
        const newTurns = turns.slice(prevCount);
        let lastUserIdx = -1;
        newTurns.forEach((t, i) => {
            if (t.querySelector('[data-turn-role="User"]')) lastUserIdx = i;
        });
        const modelTurns = newTurns
            .slice(lastUserIdx + 1)
            .filter(t => t.querySelector('[data-turn-role="Model"]'));
        const imgs = [];
        for (const turn of modelTurns) {
            for (const img of turn.querySelectorAll('ms-image-chunk img.loaded-image, img.markdown-image')) {
                if (!img.closest('ms-thought-chunk') && img.complete && img.naturalWidth > 0 && img.src) {
                    imgs.push(img);
                }
            }
        }
        const out = [];
        for (const img of imgs) {
            let dataUrl = '';
            const src = img.src;
            if (src.startsWith('data:')) {
                dataUrl = src;
            } else {
                try {
                    const resp = await fetch(src);
                    const blob = await resp.blob();
                    dataUrl = await new Promise((resolve, reject) => {
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
                    dataUrl = canvas.toDataURL('image/png');
                }
            }
            if (dataUrl) {
                out.push({
                    data_url: dataUrl,
                    width: img.naturalWidth,
                    height: img.naturalHeight
                });
            }
        }
        done(out);
    } catch (err) {
        done([]);
    }
})();
