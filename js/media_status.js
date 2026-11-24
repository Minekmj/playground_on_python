const chunks = document.querySelectorAll('ms-prompt-box .multi-media-row > *, ms-prompt-box ms-image-chunk, ms-prompt-box ms-file-chunk, ms-prompt-box ms-video-chunk');
const loading = document.querySelectorAll('ms-prompt-box .loading-icon, ms-prompt-box .spinner-container, ms-prompt-box mat-spinner, ms-prompt-box mat-progress-spinner');
const uploading = Array.from(loading).some(el => el.offsetParent !== null || el.getClientRects().length > 0);
return { count: chunks.length, uploading: uploading };
