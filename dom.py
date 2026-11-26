from __future__ import annotations

import base64
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import BrowserManager
from .config import PlayGroundConfig
from .js_loader import load_js
from .logger import PlayGroundLogger
from .storage import AI_STUDIO_NEW_CHAT_URL


MediaItem = Union[str, Path, Tuple[bytes, str], Any]
MediaInput = Union[MediaItem, Sequence[MediaItem]]

_KIND_ALIASES: Dict[str, str] = {
    'text': 'text', '텍스트': 'text', 'chat': 'text', 'gemini': 'text',
    'image': 'image', 'images': 'image', 'img': 'image', 'imagen': 'image',
    '이미지': 'image', '사진': 'image', '그림': 'image',
    'video': 'video', 'videos': 'video', 'veo': 'video',
    '비디오': 'video', '영상': 'video',
    'audio': 'audio', 'voice': 'audio', 'speech': 'audio',
    'live': 'audio', 'music': 'audio', '오디오': 'audio', '음성': 'audio',
    'all': 'all', '전체': 'all',
}

_MODEL_CACHE_RESET_KEYS = (
    'temp', 'think', 'thinking_budget', 'media_resolution',
    'top_p', 'seed', 'aspect_ratio', 'image_size',
    'output_modality', 'number_of_images',
)

_PROMPT_TEXTAREA_CSS = (
    'ms-prompt-box textarea[formcontrolname="promptText"], '
    'ms-prompt-box textarea[aria-label="Enter a prompt"]'
)

_MEDIA_INPUT_CSS = (
    'ms-prompt-box input[data-test-upload-file-input], '
    'ms-add-media-button input[type="file"], '
    'ms-prompt-box input[type="file"]'
)


# --- 모델 분류 / 미디어 / 데이터 URL 헬퍼 ---

def _normalize_kind(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    norm = kind.strip().lower()
    return _KIND_ALIASES.get(norm, norm)


def _infer_model_kind(
    name: str,
    model_id: str,
    subtitle: str,
    categories: List[str],
    icon: str,
) -> str:
    blob = ' '.join([name, model_id, subtitle, *categories]).lower()
    ic = (icon or '').strip().lower()

    if (
        any(w in blob for w in ('imagen', 'image', 'banana', 'gempix', 'photo', '이미지', '그림'))
        or ic in ('image', 'photo', 'palette', 'brush')
    ):
        return 'image'
    if (
        any(w in blob for w in ('veo', 'video', '영상', '비디오'))
        or ic in ('videocam', 'movie', 'video_library')
    ):
        return 'video'
    if (
        any(w in blob for w in ('tts', 'audio', 'speech', 'lyria', 'music', 'live', '오디오', '음성'))
        or ic in ('mic', 'graphic_eq', 'music_note', 'volume_up')
    ):
        return 'audio'
    return 'text'


def _normalize_media_items(media: MediaInput) -> List[MediaItem]:
    is_bytes_pair = (
        isinstance(media, tuple)
        and len(media) == 2
        and isinstance(media[0], (bytes, bytearray))
        and isinstance(media[1], str)
    )
    if isinstance(media, (list, tuple)) and not is_bytes_pair:
        return list(media)
    return [media]


def _parse_data_url_image(
    item: Dict[str, Any],
    idx: int,
    stamp: int,
    dest_dir: Optional[Path],
) -> Optional[Dict[str, Any]]:
    data_url = str(item.get('data_url') or '')
    if ',' not in data_url:
        return None

    header, b64 = data_url.split(',', 1)
    mime_type = 'image/png'
    if ';' in header and ':' in header:
        mime_type = header.split(':', 1)[1].split(';', 1)[0].strip() or 'image/png'

    ext = {'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif'}.get(mime_type, 'png')
    img_bytes = base64.b64decode(b64)

    saved_path: Optional[Path] = None
    if dest_dir is not None:
        saved_path = dest_dir / f'gen_{stamp}_{idx + 1}.{ext}'
        saved_path.write_bytes(img_bytes)

    return {
        'bytes': img_bytes,
        'mime_type': mime_type,
        'width': int(item.get('width') or 0),
        'height': int(item.get('height') or 0),
        'path': saved_path,
    }


def _resolve_thinking_candidates(think_val: Union[str, bool, int]) -> List[str]:
    if isinstance(think_val, bool):
        return ['high', 'medium'] if think_val else ['minimal', 'low', 'off']
    if isinstance(think_val, int):
        if think_val <= 0:
            return ['minimal', 'low']
        if think_val < 4096:
            return ['low', 'medium']
        if think_val < 16384:
            return ['medium', 'high']
        return ['high']

    norm = str(think_val).strip().lower()
    if norm in ('false', 'off', 'none', '0', 'disable'):
        return ['minimal', 'low']
    if norm in ('true', 'on', '1', 'enable'):
        return ['high', 'medium']
    return [norm]


# --- AI Studio DOM 제어 클래스 ---

class AIStudioDOM:
    """Google AI Studio 웹 UI의 인증, 설정, 미디어, 프롬프트 및 응답을 제어."""

    def __init__(self, browser: BrowserManager, logger: PlayGroundLogger) -> None:
        self.browser = browser
        self.logger = logger
        self._cache: Dict[str, Any] = {}
        self._models_cache: Optional[List[Dict[str, Any]]] = None

    def reset_cache(self) -> None:
        self._cache.clear()

    # --- 인증 및 기본 대기 ---

    def get_auth_state(self, driver: webdriver.Chrome) -> str:
        try:
            url = driver.current_url or ''
            if 'accounts.google.com' in url or 'ServiceLogin' in url:
                return 'signed_out'
            if 'aistudio.google.com' not in url:
                return 'loading'
            return str(driver.execute_script(load_js('check_auth_state.js')) or 'loading')
        except Exception:
            return 'loading'

    def wait_auth_state(self, driver: webdriver.Chrome, timeout: float = 6.0) -> str:
        deadline = time.monotonic() + timeout
        last_state = 'loading'
        while time.monotonic() < deadline:
            last_state = self.get_auth_state(driver)
            if last_state in ('signed_in', 'signed_out'):
                return last_state
            time.sleep(0.15)
        return last_state

    def is_logged_in_and_ready(self, driver: webdriver.Chrome) -> bool:
        return self.get_auth_state(driver) == 'signed_in'

    def extract_account_info(self, driver: webdriver.Chrome) -> Dict[str, str]:
        info = driver.execute_script(load_js('extract_account_info.js')) or {}
        url = str(info.get('url') or AI_STUDIO_NEW_CHAT_URL)
        prompt_id = ''
        if '/prompts/' in url:
            tail = url.split('/prompts/', 1)[1].split('?', 1)[0].split('#', 1)[0].strip('/')
            if tail and tail != 'new_chat':
                prompt_id = tail
        return {
            'account_email': str(info.get('email') or ''),
            'account_label': str(info.get('label') or ''),
            'prompt_url': url,
            'prompt_id': prompt_id,
        }

    def wait_prompt_box_ready(self, driver: webdriver.Chrome, timeout: int) -> None:
        def _ready_or_signed_out(drv: webdriver.Chrome):
            try:
                url = drv.current_url or ''
                if 'accounts.google.com' in url or 'ServiceLogin' in url:
                    return True
            except Exception:
                pass
            if self.get_auth_state(drv) == 'signed_out':
                return True
            els = drv.find_elements(By.CSS_SELECTOR, _PROMPT_TEXTAREA_CSS)
            return els[0] if els else False

        WebDriverWait(driver, max(15, int(timeout)), poll_frequency=0.1).until(_ready_or_signed_out)

    def wait_no_overlay_backdrop(self, driver: webdriver.Chrome, timeout: float = 1.5) -> None:
        script = load_js('has_overlay_backdrop.js')
        deadline = None if (timeout is None or timeout <= 0) else (time.monotonic() + timeout)
        while deadline is None or time.monotonic() < deadline:
            if not driver.execute_script(script):
                return
            time.sleep(0.05)

    # --- 패널 / 드롭다운 / 토글 UI 조작 ---

    def ensure_run_settings_open(self, driver: webdriver.Chrome) -> None:
        try:
            if driver.get_window_size().get('width', 0) < 1100:
                driver.set_window_size(1440, 960)
        except Exception:
            pass
        if driver.execute_script(load_js('ensure_run_settings.js')):
            return

        selectors = (
            'button[aria-label*="run settings" i]',
            'button[aria-label*="Tune" i]',
            'ms-right-side-panel .toggles-container button',
            'ms-right-side-panel button',
        )
        for sel in selectors:
            if self.browser.js_click_selector(driver, sel, label='Run settings 열기'):
                time.sleep(0.12)
                return

    def _ensure_group_expanded(self, driver: webdriver.Chrome, aria_label: str) -> None:
        if not driver.execute_script(load_js('ensure_group_expanded.js'), aria_label):
            time.sleep(0.1)

    def _is_sliding_panel_open(self, driver: webdriver.Chrome) -> bool:
        js = """
            const els = document.querySelectorAll(
                'ms-model-carousel-row, ms-sliding-right-panel .panel-header, ms-system-instructions textarea'
            );
            return Array.from(els).some(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
            });
        """
        return bool(driver.execute_script(js))

    def close_open_panels(self, driver: webdriver.Chrome) -> None:
        selectors = [
            'ms-sliding-right-panel .panel-header .back-button',
            'ms-sliding-right-panel .panel-header button',
            '.cdk-overlay-container ms-sliding-right-panel button',
            '.cdk-overlay-popover ms-sliding-right-panel button',
            '.toolbar-system-instructions .close-button',
            'ms-system-instructions button[aria-label*="Close" i]',
        ]
        for _ in range(2):
            if not self._is_sliding_panel_open(driver):
                break
            clicked = any(
                self.browser.js_click_selector(driver, sel, label='패널 닫기')
                for sel in selectors
            )
            if not clicked:
                self._send_escape_key(driver)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and self._is_sliding_panel_open(driver):
                time.sleep(0.05)

        self.wait_no_overlay_backdrop(driver, timeout=1.0)

    def _send_escape_key(self, driver: webdriver.Chrome) -> None:
        driver.execute_script(
            "document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));"
        )

    def _close_dialog_if_open(self, driver: webdriver.Chrome) -> None:
        driver.execute_script(load_js('close_dialog.js'))
        self.wait_no_overlay_backdrop(driver, timeout=1.0)

    def _find_visible_select_options(self, driver: webdriver.Chrome):
        selectors = [
            'div.mat-mdc-select-panel mat-option',
            '.cdk-overlay-popover mat-option',
            '.cdk-overlay-container mat-option',
            'mat-option.mat-mdc-option',
            '[role="listbox"] [role="option"]',
        ]
        for sel in selectors:
            opts = []
            for opt in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if opt.is_displayed():
                        opts.append(opt)
                except StaleElementReferenceException:
                    continue
            if opts:
                return opts
        return []

    def _select_mat_dropdown(
        self,
        driver: webdriver.Chrome,
        select_css: str,
        candidates: List[str],
        stage: str,
    ) -> Optional[str]:
        self.wait_no_overlay_backdrop(driver)
        info = driver.execute_script(load_js('get_select_info.js'), select_css)
        if info is None or info['disabled']:
            return None

        cur_val = info['text'].lower()
        if any(cur_val == c or cur_val.startswith(c) for c in candidates):
            return info['text']

        open_js = load_js('open_select_dropdown.js')
        options = []
        for attempt_idx in range(1, 4):
            self.logger.attempt(stage, attempt_idx, 3, '드롭다운 열기')
            driver.execute_script(open_js, select_css, attempt_idx)
            try:
                options = WebDriverWait(driver, 2.0, poll_frequency=0.05).until(
                    self._find_visible_select_options
                )
                if options:
                    break
            except TimeoutException:
                continue

        if not options:
            raise TimeoutException(f'{stage} 드롭다운 옵션을 열지 못했습니다.')

        chosen = driver.execute_script(load_js('pick_select_option.js'), candidates)
        if chosen:
            self.wait_no_overlay_backdrop(driver, timeout=1.0)
            self.logger.emit(stage, f'-> {chosen}')
            return chosen

        self._send_escape_key(driver)
        return None

    def _set_slide_toggle(
        self,
        driver: webdriver.Chrome,
        aria_label: str,
        want: bool,
        stage: str,
    ) -> bool:
        self._ensure_group_expanded(driver, 'tools')
        res = driver.execute_script(load_js('set_slide_toggle.js'), aria_label, bool(want))
        if res in ('missing', 'disabled'):
            return False
        if res == 'toggled':
            self.logger.emit(stage, f'{aria_label} -> {want}')
            time.sleep(0.08)
        return True

    def _set_named_number_input(
        self,
        driver: webdriver.Chrome,
        direct_selectors: List[str],
        title_keywords: List[str],
        val_str: str,
        stage: str,
    ) -> bool:
        applied = bool(
            driver.execute_script(
                load_js('set_number_input.js'),
                direct_selectors,
                title_keywords,
                val_str,
            )
        )
        if applied:
            self.logger.emit(stage, f'-> {val_str}')
        return applied

    def _apply_gallery_or_select(
        self,
        driver: webdriver.Chrome,
        gallery_selectors: List[str],
        select_selectors: List[str],
        title_keywords: List[str],
        value: str,
        stage: str,
    ) -> bool:
        target = value.strip().lower()
        clicked = bool(
            driver.execute_script(
                load_js('apply_gallery_or_select.js'),
                gallery_selectors,
                title_keywords,
                target,
            )
        )
        if clicked:
            self.logger.emit(stage, f'-> {value}')
            time.sleep(0.08)
            return True

        for sel in select_selectors:
            if self._select_mat_dropdown(driver, sel, [target], stage=stage) is not None:
                return True

        return self._select_dropdown_by_item_title(driver, title_keywords, target, stage)

    def _select_dropdown_by_item_title(
        self,
        driver: webdriver.Chrome,
        title_keywords: List[str],
        target: str,
        stage: str,
    ) -> bool:
        js = """
            const keywords = arguments[0];
            for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
                const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
                if (!keywords.some(k => title.includes(k))) continue;
                const sel = item.querySelector('mat-select');
                if (sel) { sel.setAttribute('data-pg-tmp-sel', '1'); return true; }
            }
            return false;
        """
        if not driver.execute_script(js, title_keywords):
            return False
        try:
            return (
                self._select_mat_dropdown(driver, 'mat-select[data-pg-tmp-sel="1"]', [target], stage=stage)
                is not None
            )
        finally:
            driver.execute_script(
                "document.querySelectorAll('[data-pg-tmp-sel]').forEach(e => e.removeAttribute('data-pg-tmp-sel'));"
            )

    # --- 모델 조회 및 선택 ---

    def _open_model_selector(self, driver: webdriver.Chrome) -> None:
        self.browser.js_click_selector(driver, 'ms-model-selector button.model-selector-card')
        WebDriverWait(driver, 15, poll_frequency=0.05).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, 'ms-model-carousel-row')) > 0
        )

    def _absorb_model_rows(self, merged: Dict[str, Dict[str, Any]], rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            key = (row['id'] or row['name']).lower()
            cat_tab = row.pop('category_tab', '')
            if key not in merged:
                row['categories'] = [cat_tab] if cat_tab else []
                row['kind'] = _infer_model_kind(
                    row['name'],
                    row['id'],
                    row['subtitle'],
                    row['categories'],
                    row.pop('icon', ''),
                )
                merged[key] = row
            else:
                row.pop('icon', None)
                if cat_tab and cat_tab not in merged[key]['categories']:
                    merged[key]['categories'].append(cat_tab)
                merged[key]['is_paid'] = merged[key]['is_paid'] or row['is_paid']

    def _scrape_model_tabs(self, driver: webdriver.Chrome) -> List[Dict[str, Any]]:
        chips = driver.execute_script(load_js('list_model_chips.js')) or []
        scrape_js = load_js('scrape_model_rows.js')
        merged: Dict[str, Dict[str, Any]] = {}
        all_chip = next((c for c in chips if c['text'].lower() in ('all', '전체')), None)

        if all_chip is not None:
            if not all_chip['active']:
                driver.execute_script(
                    "document.querySelectorAll('.model-categories-container button')[arguments[0]]?.click();",
                    all_chip['idx'],
                )
                time.sleep(0.15)
            self._absorb_model_rows(merged, driver.execute_script(scrape_js, all_chip['text']) or [])
        elif chips:
            for c in chips[:10]:
                driver.execute_script(
                    "document.querySelectorAll('.model-categories-container button')[arguments[0]]?.click();",
                    c['idx'],
                )
                time.sleep(0.12)
                self._absorb_model_rows(merged, driver.execute_script(scrape_js, c['text']) or [])
        else:
            self._absorb_model_rows(merged, driver.execute_script(scrape_js, '') or [])

        return list(merged.values())

    def _filter_models(
        self,
        models: List[Dict[str, Any]],
        kind: Optional[str],
        paid: Optional[bool],
        category: Optional[str],
    ) -> List[Dict[str, Any]]:
        results = list(models)
        norm_kind = _normalize_kind(kind)
        if norm_kind and norm_kind != 'all':
            results = [m for m in results if m.get('kind') == norm_kind]

        if category:
            cat_l = category.strip().lower()
            if cat_l not in ('all', '전체'):
                results = [
                    m for m in results
                    if any(cat_l in c.lower() for c in m.get('categories', []))
                    or cat_l == m.get('kind')
                ]

        if paid is not None:
            results = [m for m in results if bool(m.get('is_paid')) is bool(paid)]
        return results

    def list_models(
        self,
        driver: webdriver.Chrome,
        kind: Optional[str] = None,
        paid: Optional[bool] = None,
        category: Optional[str] = None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        if self._models_cache is None or refresh:
            self.ensure_run_settings_open(driver)
            self.close_open_panels(driver)
            self._open_model_selector(driver)
            try:
                self._models_cache = self._scrape_model_tabs(driver)
                self.logger.emit('모델 목록', f'총 {len(self._models_cache)}개 조회')
            finally:
                self.close_open_panels(driver)

        return self._filter_models(self._models_cache, kind=kind, paid=paid, category=category)

    def _find_cached_model(self, models: List[Dict[str, Any]], target_norm: str) -> Optional[Dict[str, Any]]:
        return next(
            (m for m in models if target_norm in (m['id'].lower(), m['name'].lower())),
            None,
        )

    def _ensure_paid_allowed(self, allow_paid: Optional[bool], matched: Optional[Dict[str, Any]], fallback: str) -> None:
        if allow_paid is False and matched and matched.get('is_paid'):
            name = matched.get('name') or fallback
            mid = matched.get('id')
            detail = f'{name} ({mid})' if mid else name
            raise PermissionError(f'유료(Paid) 모델 사용이 차단되었습니다: {detail}')

    def _select_model_across_tabs(self, driver: webdriver.Chrome, target_norm: str) -> Optional[Dict[str, Any]]:
        activate_all_js = """
            for (const b of document.querySelectorAll('.model-categories-container button')) {
                const t = (b.innerText || '').trim().toLowerCase();
                if ((t === 'all' || t === '전체') && !b.classList.contains('ms-button-active')) {
                    b.click();
                    break;
                }
            }
        """
        driver.execute_script(activate_all_js)
        time.sleep(0.1)

        select_js = load_js('select_model_in_view.js')
        selected = driver.execute_script(select_js, target_norm)
        if selected:
            return selected

        tab_count = int(
            driver.execute_script(
                "return document.querySelectorAll('.model-categories-container button:not(.alt-view-tab-button)').length;"
            )
            or 0
        )
        for idx in range(min(tab_count, 10)):
            driver.execute_script(
                "document.querySelectorAll('.model-categories-container button:not(.alt-view-tab-button)')[arguments[0]]?.click();",
                idx,
            )
            time.sleep(0.12)
            selected = driver.execute_script(select_js, target_norm)
            if selected:
                return selected
        return None

    def apply_model(self, driver: webdriver.Chrome, model: str, allow_paid: Optional[bool] = None) -> None:
        target = model.strip()
        if not target:
            return
        target_norm = target.lower().removeprefix('models/')
        if self._cache.get('model') == target_norm:
            return

        if allow_paid is False and self._models_cache is not None:
            self._ensure_paid_allowed(allow_paid, self._find_cached_model(self._models_cache, target_norm), model)

        self.close_open_panels(driver)
        cur = driver.execute_script(load_js('get_model_card_info.js'))
        if cur and target_norm in (cur.get('title'), cur.get('id')):
            if allow_paid is False and self._models_cache is None:
                models = self.list_models(driver)
                self._ensure_paid_allowed(allow_paid, self._find_cached_model(models, target_norm), model)
            self._cache['model'] = target_norm
            return

        self._open_model_selector(driver)
        try:
            selected = self._select_model_across_tabs(driver, target_norm)
            if not selected:
                raise ValueError(f'모델을 찾을 수 없습니다: {model}')
            self._ensure_paid_allowed(allow_paid, selected, model)

            time.sleep(0.15)
            self._cache['model'] = target_norm
            for k in _MODEL_CACHE_RESET_KEYS:
                self._cache.pop(k, None)
            self.logger.emit('모델', f"-> {selected.get('name') or model}")
        finally:
            self.close_open_panels(driver)

    # --- 시스템 프롬프트 & Thinking 설정 ---

    def _find_system_instructions_editor(self, driver: webdriver.Chrome):
        selectors = [
            'ms-system-instructions-panel ms-sliding-right-panel textarea',
            'ms-system-instructions textarea',
            '.cdk-overlay-container ms-system-instructions textarea',
            '.cdk-overlay-popover ms-system-instructions textarea',
            '.cdk-overlay-container ms-sliding-right-panel textarea',
            '.cdk-overlay-popover ms-sliding-right-panel textarea',
            'ms-sliding-right-panel textarea',
            'textarea[aria-label*="system" i]',
            'textarea[placeholder*="system" i]',
            'textarea[placeholder*="instructions" i]',
            'ms-system-instructions [contenteditable="true"]',
        ]
        for sel in selectors:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if el.is_displayed():
                        return el
                except StaleElementReferenceException:
                    continue
        return None

    def apply_system_input(self, driver: webdriver.Chrome, system_input: str) -> None:
        if self._cache.get('system_input') == system_input:
            return
        self.wait_no_overlay_backdrop(driver)

        editor = self._find_system_instructions_editor(driver)
        if editor is None:
            card_css = (
                'ms-system-instructions-panel button[data-test-system-instructions-card], '
                'ms-system-instructions-panel button.system-instructions-card'
            )
            for attempt_idx in range(1, 4):
                self.logger.attempt('시스템 프롬프트', attempt_idx, 3, '입력창 열기')
                self.browser.js_click_selector(driver, card_css)
                try:
                    editor = WebDriverWait(driver, 2.5, poll_frequency=0.05).until(
                        self._find_system_instructions_editor
                    )
                    if editor is not None:
                        break
                except TimeoutException:
                    continue

        if editor is None:
            raise TimeoutException('System instructions 입력창(textarea)을 찾지 못했습니다.')

        self.browser.set_input_value(driver, editor, system_input)
        self.close_open_panels(driver)
        self._cache['system_input'] = system_input
        self.logger.emit('시스템 프롬프트', f'적용 ({len(system_input)}자)')

    def apply_raw_mode(self, driver: webdriver.Chrome, enabled: bool = True) -> None:
        want = bool(enabled)
        if self._cache.get('raw_mode') == want:
            return
        for _ in range(2):
            res = driver.execute_script(load_js('ensure_raw_mode.js'), want) or {}
            status = res.get('status')
            if status in ('already', 'toggled'):
                self._cache['raw_mode'] = want
                if status == 'toggled':
                    self.logger.emit('Raw Mode', f"-> {'ON' if want else 'OFF'}")
                    time.sleep(0.08)
                return
            if status == 'opened_wait':
                time.sleep(0.15)
                continue
            break

    def apply_thinking(self, driver: webdriver.Chrome, think_val: Union[str, bool, int]) -> None:
        think_key = repr(think_val).lower()
        if self._cache.get('think') == think_key:
            return

        candidates = _resolve_thinking_candidates(think_val)
        chosen = self._select_mat_dropdown(
            driver,
            'ms-thinking-level-setting mat-select[aria-label="Thinking Level"], ms-thinking-level-setting mat-select',
            candidates,
            stage='Thinking',
        )
        if chosen is not None:
            self._cache['think'] = think_key
            return

        if isinstance(think_val, bool):
            toggle_js = """
                const want = arguments[0];
                const btn = document.querySelector('ms-run-settings mat-slide-toggle button[aria-label*="Think" i]');
                if (!btn) return false;
                if ((btn.getAttribute('aria-checked') === 'true') !== want) btn.click();
                return true;
            """
            if driver.execute_script(toggle_js, think_val):
                self._cache['think'] = think_key
                self.logger.emit('Thinking', f'-> {think_val}')

    # --- Run Settings 개별 옵션 적용 헬퍼 ---

    def _apply_cached_number(
        self,
        driver: webdriver.Chrome,
        cache_key: str,
        raw_val: Any,
        *,
        is_float: bool,
        selectors: List[str],
        keywords: List[str],
        stage: str,
    ) -> None:
        if raw_val is None:
            return
        parsed = float(raw_val) if is_float else int(raw_val)
        if self._cache.get(cache_key) == parsed:
            return
        val_str = f'{parsed:g}' if is_float else str(parsed)
        if self._set_named_number_input(driver, selectors, keywords, val_str, stage=stage):
            self._cache[cache_key] = parsed

    def _apply_cached_gallery(
        self,
        driver: webdriver.Chrome,
        cache_key: str,
        raw_val: Optional[str],
        *,
        gallery_sels: List[str],
        select_sels: List[str],
        keywords: List[str],
        stage: str,
    ) -> None:
        if raw_val is None:
            return
        norm = raw_val.lower()
        if self._cache.get(cache_key) == norm:
            return
        if self._apply_gallery_or_select(driver, gallery_sels, select_sels, keywords, raw_val, stage=stage):
            self._cache[cache_key] = norm

    def _apply_cached_toggle(
        self,
        driver: webdriver.Chrome,
        cache_key: str,
        raw_val: Optional[bool],
        aria_label: str,
    ) -> None:
        if raw_val is None:
            return
        want = bool(raw_val)
        if self._cache.get(cache_key) == want:
            return
        if self._set_slide_toggle(driver, aria_label, want, stage='도구'):
            self._cache[cache_key] = want

    def _apply_tool_with_editor(
        self,
        driver: webdriver.Chrome,
        cache_key: str,
        raw_val: Any,
        toggle_label: str,
        edit_btn_selector: str,
    ) -> None:
        if raw_val is None or self._cache.get(cache_key) == raw_val:
            return
        want = bool(raw_val) if isinstance(raw_val, bool) else True
        if not self._set_slide_toggle(driver, toggle_label, want, stage='도구'):
            return

        if not isinstance(raw_val, bool):
            payload = raw_val if isinstance(raw_val, str) else json.dumps(raw_val, ensure_ascii=False, indent=2)
            if self.browser.js_click_selector(driver, edit_btn_selector):
                time.sleep(0.15)
                ed = driver.execute_script(
                    "return document.querySelector('mat-dialog-container textarea, .cdk-overlay-pane textarea, .cdk-overlay-popover textarea');"
                )
                if ed:
                    self.browser.set_input_value(driver, ed, payload)
                    self._close_dialog_if_open(driver)

        self._cache[cache_key] = raw_val

    def _apply_negative_prompt(self, driver: webdriver.Chrome, negative_prompt: Optional[str]) -> None:
        if negative_prompt is None or self._cache.get('negative_prompt') == negative_prompt:
            return
        js = """
            for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
                const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
                if (title.includes('negative')) return item.querySelector('textarea, input');
            }
            return document.querySelector('ms-run-settings textarea[aria-label*="negative" i], ms-run-settings input[aria-label*="negative" i]');
        """
        neg_el = driver.execute_script(js)
        if neg_el:
            self.browser.set_input_value(driver, neg_el, negative_prompt)
            self._cache['negative_prompt'] = negative_prompt

    def _apply_image_settings(self, driver: webdriver.Chrome, cfg: PlayGroundConfig) -> None:
        self._apply_cached_gallery(
            driver, 'output_modality', cfg.output_modality,
            gallery_sels=['.output-modality-gallery', 'ms-run-settings .output-modality-gallery'],
            select_sels=['ms-run-settings mat-select[aria-label*="modality" i]'],
            keywords=['output modality', 'modality', '출력 형식'],
            stage='Output Modality',
        )
        self._apply_cached_gallery(
            driver, 'aspect_ratio', cfg.aspect_ratio,
            gallery_sels=['.aspect-ratio-gallery', 'ms-run-settings .aspect-ratio-gallery'],
            select_sels=['ms-run-settings mat-select[aria-label*="aspect" i]'],
            keywords=['aspect ratio', '화면 비율', '비율'],
            stage='Aspect Ratio',
        )
        self._apply_cached_gallery(
            driver, 'image_size', cfg.image_size,
            gallery_sels=['ms-run-settings .image-size-gallery'],
            select_sels=['ms-run-settings mat-select[aria-label*="resolution" i]', 'ms-run-settings mat-select[aria-label*="image size" i]'],
            keywords=['image size', 'resolution', '이미지 크기', '해상도'],
            stage='Image Size',
        )
        self._apply_cached_number(
            driver, 'number_of_images', cfg.number_of_images,
            is_float=False,
            selectors=['ms-run-settings input[aria-label*="number of images" i]'],
            keywords=['number of images', '이미지 수'],
            stage='Number of Images',
        )
        self._apply_cached_gallery(
            driver, 'person_generation', cfg.person_generation,
            gallery_sels=[],
            select_sels=['ms-run-settings mat-select[aria-label*="person" i]'],
            keywords=['person generation', '인물 생성'],
            stage='Person Generation',
        )
        self._apply_negative_prompt(driver, cfg.negative_prompt)

    def _apply_tool_settings(self, driver: webdriver.Chrome, cfg: PlayGroundConfig) -> None:
        self._apply_cached_toggle(driver, 'google_search', cfg.google_search, 'Grounding with Google Search')
        self._apply_cached_toggle(driver, 'url_context', cfg.url_context, 'Browse the url context')
        self._apply_cached_toggle(driver, 'code_execution', cfg.code_execution, 'Code execution')
        self._apply_tool_with_editor(
            driver, 'structured_output', cfg.structured_output,
            'Structured outputs',
            'button[data-test-id="editJsonSchemaButton"], button[aria-label="Edit JSON schema"]',
        )
        self._apply_tool_with_editor(
            driver, 'function_calling', cfg.function_calling,
            'Function calling',
            'button[aria-label="Edit function declarations"]',
        )

    def _apply_advanced_settings(self, driver: webdriver.Chrome, cfg: PlayGroundConfig) -> None:
        need_adv = any(
            v is not None for v in (
                cfg.temp, cfg.media_resolution, cfg.safety_settings,
                cfg.stop_sequences, cfg.max_output_tokens, cfg.top_p, cfg.seed,
            )
        )
        if not need_adv:
            return
        self._ensure_group_expanded(driver, 'advanced settings')

        self._apply_cached_number(
            driver, 'temp', cfg.temp,
            is_float=True,
            selectors=[
                'ms-run-settings input[aria-label*="Temperature" i]',
                'ms-run-settings input[name*="temperature" i]',
                'ms-temperature-setting input[type="number"]',
            ],
            keywords=['temperature'],
            stage='Temperature',
        )
        if cfg.media_resolution is not None and self._cache.get('media_resolution') != cfg.media_resolution.lower():
            res = self._select_mat_dropdown(
                driver,
                '[data-test-id="mediaResolution"] mat-select, mat-select[aria-label="Media resolution"]',
                [cfg.media_resolution.strip().lower()],
                stage='Media resolution',
            )
            if res is not None:
                self._cache['media_resolution'] = cfg.media_resolution.lower()

        self._apply_cached_number(
            driver, 'max_output_tokens', cfg.max_output_tokens,
            is_float=False,
            selectors=[
                'ms-run-settings input[name="maxOutputTokens"]',
                'ms-run-settings input[aria-label="Maximum output tokens"]',
            ],
            keywords=['output length', 'max output', 'maximum output'],
            stage='Output length',
        )
        self._apply_cached_number(
            driver, 'top_p', cfg.top_p,
            is_float=True,
            selectors=['ms-run-settings input[aria-label*="Top P" i]', 'ms-run-settings input[name*="topP" i]'],
            keywords=['top p', 'top-p'],
            stage='Top P',
        )
        self._apply_cached_number(
            driver, 'seed', cfg.seed,
            is_float=False,
            selectors=['ms-run-settings input[aria-label*="Seed" i]', 'ms-run-settings input[name*="seed" i]'],
            keywords=['seed'],
            stage='Seed',
        )

        if cfg.stop_sequences is not None and self._cache.get('stop_sequences') != tuple(cfg.stop_sequences):
            self._apply_stop_sequences(driver, cfg.stop_sequences)
            self._cache['stop_sequences'] = tuple(cfg.stop_sequences)

        if cfg.safety_settings is not None and self._cache.get('safety_settings') != repr(cfg.safety_settings):
            self._apply_safety_settings(driver, cfg.safety_settings)
            self._cache['safety_settings'] = repr(cfg.safety_settings)

    def apply_config(self, driver: webdriver.Chrome, cfg: PlayGroundConfig) -> None:
        fields_to_check = (
            cfg.model, cfg.system_input, cfg.temp, cfg.thinnk, cfg.thinking_budget,
            cfg.structured_output, cfg.code_execution, cfg.function_calling,
            cfg.google_search, cfg.url_context, cfg.media_resolution,
            cfg.safety_settings, cfg.stop_sequences, cfg.max_output_tokens,
            cfg.top_p, cfg.seed, cfg.aspect_ratio, cfg.image_size,
            cfg.output_modality, cfg.number_of_images, cfg.negative_prompt,
            cfg.person_generation,
        )
        if cfg.raw_mode is not None:
            self.apply_raw_mode(driver, enabled=bool(cfg.raw_mode))

        if not any(v is not None for v in fields_to_check):
            return

        self.ensure_run_settings_open(driver)

        if cfg.model is not None:
            self.apply_model(driver, str(cfg.model), allow_paid=cfg.allow_paid)
        if cfg.system_input is not None:
            self.apply_system_input(driver, str(cfg.system_input))
        if cfg.thinnk is not None:
            self.apply_thinking(driver, cfg.thinnk)

        if cfg.thinking_budget is not None and self._cache.get('thinking_budget') != int(cfg.thinking_budget):
            self._ensure_group_expanded(driver, 'advanced settings')
            self._apply_cached_number(
                driver, 'thinking_budget', cfg.thinking_budget,
                is_float=False,
                selectors=['ms-thinking-budget-setting input[type="number"]', 'ms-run-settings input[aria-label*="budget" i]'],
                keywords=['thinking budget', 'budget'],
                stage='Thinking Budget',
            )

        self._apply_image_settings(driver, cfg)
        self._apply_tool_settings(driver, cfg)
        self._apply_advanced_settings(driver, cfg)

    def _apply_stop_sequences(self, driver: webdriver.Chrome, stops: List[str]) -> None:
        driver.execute_script(
            "document.querySelectorAll('ms-stop-sequence-input .remove-button, ms-stop-sequence-input button[matChipRemove]').forEach(b => b.click());"
        )
        inputs = driver.find_elements(
            By.CSS_SELECTOR,
            'ms-stop-sequence-input input#chip-input, ms-stop-sequence-input input[aria-label="Add stop sequence"]',
        )
        if not inputs:
            return
        inp = inputs[0]
        for s in stops:
            if not s:
                continue
            self.browser.set_input_value(driver, inp, str(s))
            inp.send_keys(Keys.ENTER)
        self.logger.emit('Stop sequences', f'-> {stops}')

    def _apply_safety_settings(
        self,
        driver: webdriver.Chrome,
        safety: Union[Dict[str, str], str],
    ) -> None:
        if not self.browser.js_click_selector(driver, 'ms-run-settings button[aria-label="Edit safety settings"]'):
            return
        time.sleep(0.15)
        if isinstance(safety, str) and safety.strip().lower() in ('off', 'none', 'block_none', 'disable'):
            driver.execute_script(load_js('safety_sliders_off.js'))
            self.logger.emit('Safety settings', '-> off')
        self._close_dialog_if_open(driver)

    # --- 미디어 첨부 및 이미지 추출 ---

    def _materialize_media(self, media: MediaInput) -> Tuple[List[str], Optional[Path]]:
        items = _normalize_media_items(media)
        temp_dir: Optional[Path] = None
        paths: List[str] = []

        for idx, item in enumerate(items):
            if isinstance(item, (str, Path)):
                p = Path(item).expanduser().resolve()
                if not p.is_file():
                    raise FileNotFoundError(f'미디어 파일을 찾을 수 없습니다: {p}')
                paths.append(str(p))
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], (bytes, bytearray)):
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix='pg_media_'))
                dest = temp_dir / (Path(str(item[1])).name or f'media_{idx}.bin')
                dest.write_bytes(bytes(item[0]))
                paths.append(str(dest.resolve()))
            elif hasattr(item, 'save') and hasattr(item, 'size'):
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix='pg_media_'))
                dest = temp_dir / f'image_{idx}.png'
                item.save(dest, format='PNG')
                paths.append(str(dest.resolve()))
            else:
                raise TypeError(f'지원하지 않는 미디어 형식입니다: {type(item).__name__}')

        return paths, temp_dir

    def attach_media(self, driver: webdriver.Chrome, media: MediaInput, timeout: int = 60) -> None:
        paths, temp_dir = self._materialize_media(media)
        if not paths:
            return
        self.logger.emit('미디어', f'{len(paths)}개 첨부')
        status_js = load_js('media_status.js')

        try:
            before_count = int((driver.execute_script(status_js) or {}).get('count', 0))
            file_input = WebDriverWait(driver, 15, poll_frequency=0.05).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, _MEDIA_INPUT_CSS))
            )
            file_input.send_keys('\n'.join(paths))

            deadline = time.monotonic() + max(15, int(timeout))
            while time.monotonic() < deadline:
                status = driver.execute_script(status_js) or {'count': 0, 'uploading': False}
                if status['count'] >= before_count + len(paths) and not status['uploading']:
                    time.sleep(0.1)
                    return
                time.sleep(0.12)

            raise TimeoutException(f'미디어 업로드 대기 시간({timeout}초)을 초과했습니다.')
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def extract_generated_images(
        self,
        driver: webdriver.Chrome,
        prev_count: int,
        save_dir: Optional[Union[str, Path]] = None,
    ) -> List[Dict[str, Any]]:
        raw_items = driver.execute_async_script(load_js('extract_images.js'), prev_count) or []
        dest_dir = Path(save_dir) if save_dir else None
        if dest_dir is not None:
            dest_dir.mkdir(parents=True, exist_ok=True)

        stamp = int(time.time() * 1000)
        results: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_items):
            parsed = _parse_data_url_image(item, idx, stamp, dest_dir)
            if parsed is not None:
                results.append(parsed)
        return results

    # --- 프롬프트 전송 및 응답 대기 ---

    def get_response_state(
        self,
        driver: webdriver.Chrome,
        prev_count: int,
        include_thoughts: bool = False,
    ) -> Dict[str, Any]:
        default_state = {
            'totalTurns': prev_count,
            'hasUserTurn': False,
            'hasModelTurn': False,
            'isGenerating': False,
            'hasRerunBtn': False,
            'errors': [],
            'text': '',
            'bodyLength': 0,
            'thoughtLength': 0,
            'imageCount': 0,
        }
        return driver.execute_script(load_js('response_state.js'), prev_count, include_thoughts) or default_state

    def submit_prompt(self, driver: webdriver.Chrome, text: str) -> int:
        self.logger.emit('전송', f'{len(text)}자')
        prev_count = int(
            driver.execute_script("return document.querySelectorAll('ms-chat-session ms-chat-turn').length;")
            or 0
        )
        textarea = WebDriverWait(driver, 20, poll_frequency=0.05).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, _PROMPT_TEXTAREA_CSS))
        )
        self.browser.set_input_value(driver, textarea, text)

        WebDriverWait(driver, 15, poll_frequency=0.05).until(
            lambda d: d.execute_script(
                "const btn = document.querySelector('ms-run-button button'); "
                "return btn && btn.getAttribute('aria-disabled') !== 'true';"
            )
        )

        submit_js = load_js('submit_prompt.js')
        for attempt_idx in range(1, 4):
            self.logger.attempt('전송', attempt_idx, 3, 'Run 실행')
            driver.execute_script(submit_js, attempt_idx)
            confirm_deadline = time.monotonic() + 2.0
            while time.monotonic() < confirm_deadline:
                state = self.get_response_state(driver, prev_count)
                if state['totalTurns'] > prev_count or state['isGenerating'] or state['errors']:
                    return prev_count
                time.sleep(0.05)

        raise TimeoutException('프롬프트 전송 후 AI Studio 턴 생성이 시작되지 않았습니다.')

    def _log_response_debug(
        self,
        tick_idx: int,
        state: Dict[str, Any],
        stable_ticks: int,
        last_flags: Optional[Tuple[bool, ...]],
    ) -> Optional[Tuple[bool, ...]]:
        body_len = int(state.get('bodyLength', 0))
        thought_len = int(state.get('thoughtLength', 0))
        flags = (
            bool(state['isGenerating']),
            bool(state.get('btnRunning')),
            bool(state.get('activeIndicator')),
            bool(state['hasModelTurn']),
            bool(state.get('hasRerunBtn')),
            body_len > 0,
            thought_len > 0,
        )
        if flags != last_flags or tick_idx % 20 == 0:
            dbg = state.get('debug') or {}
            self.logger.debug(
                '응답대기',
                f'tick={tick_idx} gen={flags[0]}(btn={flags[1]},ind={flags[2]}) '
                f'model={flags[3]} rerun={flags[4]} body={body_len} thought={thought_len} '
                f'img={int(state.get("imageCount", 0))} stable={stable_ticks} '
                f'promptEmpty={dbg.get("promptEmpty")} runBtns={dbg.get("runBtns")} turnBtns={dbg.get("turnBtns")}',
            )
            return flags
        return last_flags

    def wait_for_response(
        self,
        driver: webdriver.Chrome,
        prev_count: int,
        timeout: Optional[int] = None,
        include_thoughts: bool = False,
    ) -> Dict[str, Any]:
        deadline = None if (timeout is None or timeout <= 0) else (time.monotonic() + timeout)
        saw_running = False
        last_sig = ('', 0, 0)
        stable_ticks = 0
        empty_idle_ticks = 0
        tick_idx = 0
        last_dbg_flags = None

        while deadline is None or time.monotonic() < deadline:
            tick_idx += 1
            state = self.get_response_state(driver, prev_count, include_thoughts=include_thoughts)
            if state['errors']:
                err = ' | '.join(state['errors'])
                self.logger.emit('오류', err)
                raise RuntimeError(f'AI Studio 오류: {err}')

            last_dbg_flags = self._log_response_debug(tick_idx, state, stable_ticks, last_dbg_flags)
            generating = bool(state['isGenerating'])
            if generating:
                saw_running = True

            cur_text = str(state['text'] or '')
            body_len = int(state.get('bodyLength', 0))
            thought_len = int(state.get('thoughtLength', 0))
            image_count = int(state.get('imageCount', 0))
            cur_sig = (cur_text, image_count, thought_len)

            if not generating and state['hasModelTurn']:
                if body_len > 0 or image_count > 0:
                    empty_idle_ticks = 0
                    stable_ticks = stable_ticks + 1 if cur_sig == last_sig else 0
                    needed = 6 if state.get('hasRerunBtn') else 20
                    if stable_ticks >= needed:
                        dbg = state.get('debug') or {}
                        self.logger.debug(
                            '응답완료판정',
                            f'tick={tick_idx} needed={needed} rerun={bool(state.get("hasRerunBtn"))} '
                            f'body={body_len} thought={thought_len} runHost={dbg.get("runHost")}',
                        )
                        self.logger.emit('완료', f'{len(cur_text)}자, 이미지 {image_count}개')
                        return {'text': cur_text, 'image_count': image_count}
                else:
                    stable_ticks = 0
                    if cur_sig != last_sig:
                        empty_idle_ticks = 0
                    elif saw_running:
                        empty_idle_ticks += 1
                        if empty_idle_ticks >= 80:
                            return {'text': cur_text, 'image_count': image_count}
            else:
                stable_ticks = 0
                empty_idle_ticks = 0

            last_sig = cur_sig
            time.sleep(0.15)

        raise TimeoutException(f'AI Studio 응답 대기 시간({timeout}초)을 초과했습니다.')

    def click_new_chat(self, driver: webdriver.Chrome) -> None:
        if not self.browser.js_click_selector(driver, 'button[data-test-clear="outside"], a[href="/prompts/new_chat"]'):
            driver.get(AI_STUDIO_NEW_CHAT_URL)
        self.wait_prompt_box_ready(driver, timeout=30)
        self.reset_cache()
        time.sleep(0.15)
