from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import tempfile
import time
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

_KIND_ALIASES = {
    "text": "text", "텍스트": "text", "chat": "text", "gemini": "text",
    "image": "image", "images": "image", "img": "image", "imagen": "image",
    "이미지": "image", "사진": "image", "그림": "image",
    "video": "video", "videos": "video", "veo": "video", "비디오": "video", "영상": "video",
    "audio": "audio", "voice": "audio", "speech": "audio", "live": "audio",
    "music": "audio", "오디오": "audio", "음성": "audio",
    "all": "all", "전체": "all",
}


def _normalize_kind(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    return _KIND_ALIASES.get(kind.strip().lower(), kind.strip().lower())


def _infer_model_kind(name: str, model_id: str, subtitle: str, categories: List[str], icon: str) -> str:
    blob = " ".join([name, model_id, subtitle, *categories]).lower()
    ic = (icon or "").strip().lower()
    if any(w in blob for w in ("imagen", "image", "banana", "gempix", "photo", "이미지", "그림")) or ic in ("image", "photo", "palette", "brush"):
        return "image"
    if any(w in blob for w in ("veo", "video", "영상", "비디오")) or ic in ("videocam", "movie", "video_library"):
        return "video"
    if any(w in blob for w in ("tts", "audio", "speech", "lyria", "music", "live", "오디오", "음성")) or ic in ("mic", "graphic_eq", "music_note", "volume_up"):
        return "audio"
    return "text"


class AIStudioDOM:
    def __init__(self, browser: BrowserManager, logger: PlayGroundLogger) -> None:
        self.browser = browser
        self.logger = logger
        self._cache: Dict[str, Any] = {}
        self._models_cache: Optional[List[Dict[str, Any]]] = None

    def reset_cache(self) -> None:
        self._cache.clear()

    def get_auth_state(self, driver: webdriver.Chrome) -> str:
        try:
            url = driver.current_url or ""
            if "accounts.google.com" in url or "ServiceLogin" in url:
                return "signed_out"
            if "aistudio.google.com" not in url:
                return "loading"
            return str(driver.execute_script(load_js("check_auth_state.js")) or "loading")
        except Exception:
            return "loading"

    def wait_auth_state(self, driver: webdriver.Chrome, timeout: float = 6.0) -> str:
        deadline = time.monotonic() + timeout
        last_state = "loading"
        while time.monotonic() < deadline:
            last_state = self.get_auth_state(driver)
            if last_state in ("signed_in", "signed_out"):
                return last_state
            time.sleep(0.15)
        return last_state

    def is_logged_in_and_ready(self, driver: webdriver.Chrome) -> bool:
        return self.get_auth_state(driver) == "signed_in"

    def extract_account_info(self, driver: webdriver.Chrome) -> Dict[str, str]:
        info = driver.execute_script(load_js("extract_account_info.js")) or {}
        url = str(info.get("url") or AI_STUDIO_NEW_CHAT_URL)
        prompt_id = ""
        if "/prompts/" in url:
            tail = url.split("/prompts/", 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
            if tail and tail != "new_chat":
                prompt_id = tail
        return {
            "account_email": str(info.get("email") or ""),
            "account_label": str(info.get("label") or ""),
            "prompt_url": url,
            "prompt_id": prompt_id,
        }

    def wait_prompt_box_ready(self, driver: webdriver.Chrome, timeout: int) -> None:
        def _ready_or_signed_out(drv: webdriver.Chrome):
            try:
                url = drv.current_url or ""
                if "accounts.google.com" in url or "ServiceLogin" in url:
                    return True
            except Exception:
                pass
            if self.get_auth_state(drv) == "signed_out":
                return True
            els = drv.find_elements(
                By.CSS_SELECTOR,
                'ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]'
            )
            return els[0] if els else False

        WebDriverWait(driver, max(15, int(timeout)), poll_frequency=0.1).until(_ready_or_signed_out)

    def wait_no_overlay_backdrop(self, driver: webdriver.Chrome, timeout: float = 1.5) -> None:
        script = load_js("has_overlay_backdrop.js")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not driver.execute_script(script):
                return
            time.sleep(0.05)

    def ensure_run_settings_open(self, driver: webdriver.Chrome) -> None:
        try:
            if driver.get_window_size().get("width", 0) < 1100:
                driver.set_window_size(1440, 960)
        except Exception:
            pass

        if driver.execute_script(load_js("ensure_run_settings.js")):
            return

        for sel in (
            'button[aria-label*="run settings" i]',
            'button[aria-label*="Tune" i]',
            'ms-right-side-panel .toggles-container button',
            'ms-right-side-panel button',
        ):
            if self.browser.js_click_selector(driver, sel, label="Run settings 열기"):
                time.sleep(0.12)
                return

    def _ensure_group_expanded(self, driver: webdriver.Chrome, aria_label: str) -> None:
        if not driver.execute_script(load_js("ensure_group_expanded.js"), aria_label):
            time.sleep(0.1)

    def _is_sliding_panel_open(self, driver: webdriver.Chrome) -> bool:
        return bool(
            driver.execute_script(
                """
                const els = document.querySelectorAll('ms-model-carousel-row, ms-sliding-right-panel .panel-header, ms-system-instructions textarea');
                return Array.from(els).some(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
                });
                """
            )
        )

    def close_open_panels(self, driver: webdriver.Chrome) -> None:
        selectors = [
            "ms-sliding-right-panel .panel-header .back-button",
            "ms-sliding-right-panel .panel-header button",
            ".cdk-overlay-container ms-sliding-right-panel button",
            ".cdk-overlay-popover ms-sliding-right-panel button",
            ".toolbar-system-instructions .close-button",
            'ms-system-instructions button[aria-label*="Close" i]',
        ]
        for _ in range(2):
            if not self._is_sliding_panel_open(driver):
                break
            clicked = False
            for sel in selectors:
                if self.browser.js_click_selector(driver, sel, label="패널 닫기"):
                    clicked = True
                    break
            if not clicked:
                driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and self._is_sliding_panel_open(driver):
                time.sleep(0.05)
        self.wait_no_overlay_backdrop(driver, timeout=1.0)

    def _close_dialog_if_open(self, driver: webdriver.Chrome) -> None:
        driver.execute_script(load_js("close_dialog.js"))
        self.wait_no_overlay_backdrop(driver, timeout=1.0)

    def _find_visible_select_options(self, driver: webdriver.Chrome):
        selectors = [
            "div.mat-mdc-select-panel mat-option",
            ".cdk-overlay-popover mat-option",
            ".cdk-overlay-container mat-option",
            "mat-option.mat-mdc-option",
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

    def _select_mat_dropdown(self, driver: webdriver.Chrome, select_css: str, candidates: List[str], stage: str) -> Optional[str]:
        self.wait_no_overlay_backdrop(driver)
        info = driver.execute_script(load_js("get_select_info.js"), select_css)
        if info is None or info["disabled"]:
            return None

        cur_val = info["text"].lower()
        if any(cur_val == c or cur_val.startswith(c) for c in candidates):
            return info["text"]

        open_js = load_js("open_select_dropdown.js")
        options = []
        for attempt_idx in range(1, 4):
            self.logger.attempt(stage, attempt_idx, 3, "드롭다운 열기")
            driver.execute_script(open_js, select_css, attempt_idx)
            try:
                options = WebDriverWait(driver, 2.0, poll_frequency=0.05).until(self._find_visible_select_options)
                if options:
                    break
            except TimeoutException:
                continue

        if not options:
            raise TimeoutException(f"{stage} 드롭다운 옵션을 열지 못했습니다.")

        chosen = driver.execute_script(load_js("pick_select_option.js"), candidates)
        if chosen:
            self.wait_no_overlay_backdrop(driver, timeout=1.0)
            self.logger.emit(stage, f"-> {chosen}")
            return chosen
        driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));")
        return None

    def _set_slide_toggle(self, driver: webdriver.Chrome, aria_label: str, want: bool, stage: str) -> bool:
        self._ensure_group_expanded(driver, "tools")
        res = driver.execute_script(load_js("set_slide_toggle.js"), aria_label, bool(want))
        if res in ("missing", "disabled"):
            return False
        if res == "toggled":
            self.logger.emit(stage, f"{aria_label} -> {want}")
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
        applied = bool(driver.execute_script(load_js("set_number_input.js"), direct_selectors, title_keywords, val_str))
        if applied:
            self.logger.emit(stage, f"-> {val_str}")
        return applied

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
            self.browser.js_click_selector(driver, "ms-model-selector button.model-selector-card")
            try:
                WebDriverWait(driver, 15, poll_frequency=0.05).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "ms-model-carousel-row")) > 0
                )

                chips = driver.execute_script(load_js("list_model_chips.js")) or []
                scrape_js = load_js("scrape_model_rows.js")
                merged: Dict[str, Dict[str, Any]] = {}
                all_chip = next((c for c in chips if c["text"].lower() in ("all", "전체")), None)

                def _absorb(rows: List[Dict[str, Any]]) -> None:
                    for row in rows:
                        key = (row["id"] or row["name"]).lower()
                        cat_tab = row.pop("category_tab", "")
                        if key not in merged:
                            row["categories"] = [cat_tab] if cat_tab else []
                            row["kind"] = _infer_model_kind(row["name"], row["id"], row["subtitle"], row["categories"], row.pop("icon", ""))
                            merged[key] = row
                        else:
                            row.pop("icon", None)
                            if cat_tab and cat_tab not in merged[key]["categories"]:
                                merged[key]["categories"].append(cat_tab)
                            merged[key]["is_paid"] = merged[key]["is_paid"] or row["is_paid"]

                if all_chip is not None:
                    if not all_chip["active"]:
                        driver.execute_script(
                            "document.querySelectorAll('.model-categories-container button')[arguments[0]]?.click();",
                            all_chip["idx"],
                        )
                        time.sleep(0.15)
                    _absorb(driver.execute_script(scrape_js, all_chip["text"]) or [])
                elif chips:
                    for c in chips[:10]:
                        driver.execute_script(
                            "document.querySelectorAll('.model-categories-container button')[arguments[0]]?.click();",
                            c["idx"],
                        )
                        time.sleep(0.12)
                        _absorb(driver.execute_script(scrape_js, c["text"]) or [])
                else:
                    _absorb(driver.execute_script(scrape_js, "") or [])

                self._models_cache = list(merged.values())
                self.logger.emit("모델 목록", f"총 {len(self._models_cache)}개 조회")
            finally:
                self.close_open_panels(driver)

        results = list(self._models_cache)
        norm_kind = _normalize_kind(kind)
        if norm_kind and norm_kind != "all":
            results = [m for m in results if m.get("kind") == norm_kind]
        if category:
            cat_l = category.strip().lower()
            if cat_l not in ("all", "전체"):
                results = [
                    m for m in results
                    if any(cat_l in c.lower() for c in m.get("categories", [])) or cat_l == m.get("kind")
                ]
        if paid is not None:
            results = [m for m in results if bool(m.get("is_paid")) is bool(paid)]
        return results

    def apply_model(self, driver: webdriver.Chrome, model: str, allow_paid: Optional[bool] = None) -> None:
        target = model.strip()
        if not target:
            return
        target_norm = target.lower().removeprefix("models/")
        if self._cache.get("model") == target_norm:
            return

        if allow_paid is False and self._models_cache is not None:
            matched = next((m for m in self._models_cache if target_norm in (m["id"].lower(), m["name"].lower())), None)
            if matched and matched.get("is_paid"):
                raise PermissionError(f"유료(Paid) 모델 사용이 차단되었습니다: {matched['name']} ({matched['id']})")

        self.close_open_panels(driver)
        cur = driver.execute_script(load_js("get_model_card_info.js"))
        if cur and target_norm in (cur.get("title"), cur.get("id")):
            if allow_paid is False and self._models_cache is None:
                models = self.list_models(driver)
                matched = next((m for m in models if target_norm in (m["id"].lower(), m["name"].lower())), None)
                if matched and matched.get("is_paid"):
                    raise PermissionError(f"유료(Paid) 모델 사용이 차단되었습니다: {matched['name']} ({matched['id']})")
            self._cache["model"] = target_norm
            return

        self.browser.js_click_selector(driver, "ms-model-selector button.model-selector-card")
        try:
            WebDriverWait(driver, 15, poll_frequency=0.05).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, "ms-model-carousel-row")) > 0
            )
            driver.execute_script(
                """
                for (const b of document.querySelectorAll('.model-categories-container button')) {
                    const t = (b.innerText || '').trim().toLowerCase();
                    if ((t === 'all' || t === '전체') && !b.classList.contains('ms-button-active')) { b.click(); break; }
                }
                """
            )
            time.sleep(0.1)

            select_js = load_js("select_model_in_view.js")
            selected = driver.execute_script(select_js, target_norm)
            if not selected:
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
                        break

            if not selected:
                raise ValueError(f"모델을 찾을 수 없습니다: {model}")

            if allow_paid is False and selected.get("is_paid"):
                raise PermissionError(f"유료(Paid) 모델 사용이 차단되었습니다: {selected.get('name') or model}")

            time.sleep(0.15)
            self._cache["model"] = target_norm
            for k in (
                "temp", "think", "thinking_budget", "media_resolution",
                "top_p", "seed", "aspect_ratio", "image_size", "output_modality", "number_of_images",
            ):
                self._cache.pop(k, None)
            self.logger.emit("모델", f"-> {selected.get('name') or model}")
        finally:
            self.close_open_panels(driver)

    def _find_system_instructions_editor(self, driver: webdriver.Chrome):
        selectors = [
            "ms-system-instructions-panel ms-sliding-right-panel textarea",
            "ms-system-instructions textarea",
            ".cdk-overlay-container ms-system-instructions textarea",
            ".cdk-overlay-popover ms-system-instructions textarea",
            ".cdk-overlay-container ms-sliding-right-panel textarea",
            ".cdk-overlay-popover ms-sliding-right-panel textarea",
            "ms-sliding-right-panel textarea",
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
        if self._cache.get("system_input") == system_input:
            return

        self.wait_no_overlay_backdrop(driver)
        editor = self._find_system_instructions_editor(driver)
        if editor is None:
            for attempt_idx in range(1, 4):
                self.logger.attempt("시스템 프롬프트", attempt_idx, 3, "입력창 열기")
                self.browser.js_click_selector(
                    driver,
                    "ms-system-instructions-panel button[data-test-system-instructions-card], ms-system-instructions-panel button.system-instructions-card",
                )
                try:
                    editor = WebDriverWait(driver, 2.5, poll_frequency=0.05).until(self._find_system_instructions_editor)
                    if editor is not None:
                        break
                except TimeoutException:
                    continue

        if editor is None:
            raise TimeoutException("System instructions 입력창(textarea)을 찾지 못했습니다.")

        self.browser.set_input_value(driver, editor, system_input)
        self.close_open_panels(driver)
        self._cache["system_input"] = system_input
        self.logger.emit("시스템 프롬프트", f"적용 ({len(system_input)}자)")

    def apply_thinking(self, driver: webdriver.Chrome, think_val: Union[str, bool, int]) -> None:
        think_key = repr(think_val).lower()
        if self._cache.get("think") == think_key:
            return

        if isinstance(think_val, bool):
            candidates = ["high", "medium"] if think_val else ["minimal", "low", "off"]
        elif isinstance(think_val, int):
            if think_val <= 0:
                candidates = ["minimal", "low"]
            elif think_val < 4096:
                candidates = ["low", "medium"]
            elif think_val < 16384:
                candidates = ["medium", "high"]
            else:
                candidates = ["high"]
        else:
            norm = str(think_val).strip().lower()
            if norm in ("false", "off", "none", "0", "disable"):
                candidates = ["minimal", "low"]
            elif norm in ("true", "on", "1", "enable"):
                candidates = ["high", "medium"]
            else:
                candidates = [norm]

        chosen = self._select_mat_dropdown(
            driver,
            'ms-thinking-level-setting mat-select[aria-label="Thinking Level"], ms-thinking-level-setting mat-select',
            candidates,
            stage="Thinking",
        )
        if chosen is not None:
            self._cache["think"] = think_key
            return

        if isinstance(think_val, bool):
            toggled = driver.execute_script(
                """
                const want = arguments[0];
                const btn = document.querySelector('ms-run-settings mat-slide-toggle button[aria-label*="Think" i]');
                if (!btn) return false;
                if ((btn.getAttribute('aria-checked') === 'true') !== want) btn.click();
                return true;
                """,
                think_val,
            )
            if toggled:
                self._cache["think"] = think_key
                self.logger.emit("Thinking", f"-> {think_val}")

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
        clicked = bool(driver.execute_script(load_js("apply_gallery_or_select.js"), gallery_selectors, title_keywords, target))
        if clicked:
            self.logger.emit(stage, f"-> {value}")
            time.sleep(0.08)
            return True

        for sel in select_selectors:
            res = self._select_mat_dropdown(driver, sel, [target], stage=stage)
            if res is not None:
                return True

        mat_sel_found = driver.execute_script(
            """
            const keywords = arguments[0];
            for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
                const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
                if (!keywords.some(k => title.includes(k))) continue;
                const sel = item.querySelector('mat-select');
                if (sel) { sel.setAttribute('data-pg-tmp-sel', '1'); return true; }
            }
            return false;
            """,
            title_keywords,
        )
        if mat_sel_found:
            try:
                return self._select_mat_dropdown(driver, 'mat-select[data-pg-tmp-sel="1"]', [target], stage=stage) is not None
            finally:
                driver.execute_script("document.querySelectorAll('[data-pg-tmp-sel]').forEach(e => e.removeAttribute('data-pg-tmp-sel'));")
        return False

    def apply_config(self, driver: webdriver.Chrome, cfg: PlayGroundConfig) -> None:
        has_any = any(
            v is not None
            for v in (
                cfg.model, cfg.system_input, cfg.temp, cfg.thinnk, cfg.thinking_budget,
                cfg.structured_output, cfg.code_execution, cfg.function_calling,
                cfg.google_search, cfg.url_context, cfg.media_resolution, cfg.safety_settings,
                cfg.stop_sequences, cfg.max_output_tokens, cfg.top_p, cfg.seed,
                cfg.aspect_ratio, cfg.image_size, cfg.output_modality,
                cfg.number_of_images, cfg.negative_prompt, cfg.person_generation,
            )
        )
        if not has_any:
            return

        self.ensure_run_settings_open(driver)

        if cfg.model is not None:
            self.apply_model(driver, str(cfg.model), allow_paid=cfg.allow_paid)
        if cfg.system_input is not None:
            self.apply_system_input(driver, str(cfg.system_input))
        if cfg.thinnk is not None:
            self.apply_thinking(driver, cfg.thinnk)
        if cfg.thinking_budget is not None and self._cache.get("thinking_budget") != int(cfg.thinking_budget):
            self._ensure_group_expanded(driver, "advanced settings")
            if self._set_named_number_input(
                driver,
                ['ms-thinking-budget-setting input[type="number"]', 'ms-run-settings input[aria-label*="budget" i]'],
                ["thinking budget", "budget"],
                str(int(cfg.thinking_budget)),
                stage="Thinking Budget",
            ):
                self._cache["thinking_budget"] = int(cfg.thinking_budget)

        if cfg.output_modality is not None and self._cache.get("output_modality") != cfg.output_modality.lower():
            if self._apply_gallery_or_select(
                driver,
                [".output-modality-gallery", "ms-run-settings .output-modality-gallery"],
                ['ms-run-settings mat-select[aria-label*="modality" i]'],
                ["output modality", "modality", "출력 형식"],
                cfg.output_modality,
                stage="Output Modality",
            ):
                self._cache["output_modality"] = cfg.output_modality.lower()

        if cfg.aspect_ratio is not None and self._cache.get("aspect_ratio") != cfg.aspect_ratio.lower():
            if self._apply_gallery_or_select(
                driver,
                [".aspect-ratio-gallery", "ms-run-settings .aspect-ratio-gallery"],
                ['ms-run-settings mat-select[aria-label*="aspect" i]'],
                ["aspect ratio", "화면 비율", "비율"],
                cfg.aspect_ratio,
                stage="Aspect Ratio",
            ):
                self._cache["aspect_ratio"] = cfg.aspect_ratio.lower()

        if cfg.image_size is not None and self._cache.get("image_size") != cfg.image_size.lower():
            if self._apply_gallery_or_select(
                driver,
                ["ms-run-settings .image-size-gallery"],
                ['ms-run-settings mat-select[aria-label*="resolution" i]', 'ms-run-settings mat-select[aria-label*="image size" i]'],
                ["image size", "resolution", "이미지 크기", "해상도"],
                cfg.image_size,
                stage="Image Size",
            ):
                self._cache["image_size"] = cfg.image_size.lower()

        if cfg.number_of_images is not None and self._cache.get("number_of_images") != int(cfg.number_of_images):
            if self._set_named_number_input(
                driver,
                ['ms-run-settings input[aria-label*="number of images" i]'],
                ["number of images", "이미지 수"],
                str(int(cfg.number_of_images)),
                stage="Number of Images",
            ):
                self._cache["number_of_images"] = int(cfg.number_of_images)

        if cfg.person_generation is not None and self._cache.get("person_generation") != cfg.person_generation.lower():
            if self._apply_gallery_or_select(
                driver,
                [],
                ['ms-run-settings mat-select[aria-label*="person" i]'],
                ["person generation", "인물 생성"],
                cfg.person_generation,
                stage="Person Generation",
            ):
                self._cache["person_generation"] = cfg.person_generation.lower()

        if cfg.negative_prompt is not None and self._cache.get("negative_prompt") != cfg.negative_prompt:
            neg_el = driver.execute_script(
                """
                for (const item of document.querySelectorAll('ms-run-settings .settings-item')) {
                    const title = (item.querySelector('.item-description-title, h3')?.innerText || '').toLowerCase();
                    if (title.includes('negative')) return item.querySelector('textarea, input');
                }
                return document.querySelector('ms-run-settings textarea[aria-label*="negative" i], ms-run-settings input[aria-label*="negative" i]');
                """
            )
            if neg_el:
                self.browser.set_input_value(driver, neg_el, cfg.negative_prompt)
                self._cache["negative_prompt"] = cfg.negative_prompt

        if cfg.google_search is not None and self._cache.get("google_search") != bool(cfg.google_search):
            if self._set_slide_toggle(driver, "Grounding with Google Search", bool(cfg.google_search), stage="도구"):
                self._cache["google_search"] = bool(cfg.google_search)
        if cfg.url_context is not None and self._cache.get("url_context") != bool(cfg.url_context):
            if self._set_slide_toggle(driver, "Browse the url context", bool(cfg.url_context), stage="도구"):
                self._cache["url_context"] = bool(cfg.url_context)
        if cfg.code_execution is not None and self._cache.get("code_execution") != bool(cfg.code_execution):
            if self._set_slide_toggle(driver, "Code execution", bool(cfg.code_execution), stage="도구"):
                self._cache["code_execution"] = bool(cfg.code_execution)

        if cfg.structured_output is not None and self._cache.get("structured_output") != cfg.structured_output:
            want_so = bool(cfg.structured_output) if isinstance(cfg.structured_output, bool) else True
            if self._set_slide_toggle(driver, "Structured outputs", want_so, stage="도구"):
                if not isinstance(cfg.structured_output, bool):
                    schema_str = (
                        cfg.structured_output
                        if isinstance(cfg.structured_output, str)
                        else json.dumps(cfg.structured_output, ensure_ascii=False, indent=2)
                    )
                    if self.browser.js_click_selector(driver, 'button[data-test-id="editJsonSchemaButton"], button[aria-label="Edit JSON schema"]'):
                        time.sleep(0.15)
                        ed = driver.execute_script("return document.querySelector('mat-dialog-container textarea, .cdk-overlay-pane textarea, .cdk-overlay-popover textarea');")
                        if ed:
                            self.browser.set_input_value(driver, ed, schema_str)
                            self._close_dialog_if_open(driver)
                self._cache["structured_output"] = cfg.structured_output

        if cfg.function_calling is not None and self._cache.get("function_calling") != cfg.function_calling:
            want_fc = bool(cfg.function_calling) if isinstance(cfg.function_calling, bool) else True
            if self._set_slide_toggle(driver, "Function calling", want_fc, stage="도구"):
                if not isinstance(cfg.function_calling, bool):
                    fn_str = (
                        cfg.function_calling
                        if isinstance(cfg.function_calling, str)
                        else json.dumps(cfg.function_calling, ensure_ascii=False, indent=2)
                    )
                    if self.browser.js_click_selector(driver, 'button[aria-label="Edit function declarations"]'):
                        time.sleep(0.15)
                        ed = driver.execute_script("return document.querySelector('mat-dialog-container textarea, .cdk-overlay-pane textarea, .cdk-overlay-popover textarea');")
                        if ed:
                            self.browser.set_input_value(driver, ed, fn_str)
                            self._close_dialog_if_open(driver)
                self._cache["function_calling"] = cfg.function_calling

        need_adv = any(
            v is not None
            for v in (
                cfg.temp, cfg.media_resolution, cfg.safety_settings,
                cfg.stop_sequences, cfg.max_output_tokens, cfg.top_p, cfg.seed,
            )
        )
        if need_adv:
            self._ensure_group_expanded(driver, "advanced settings")

        if cfg.temp is not None and self._cache.get("temp") != float(cfg.temp):
            if self._set_named_number_input(
                driver,
                ['ms-run-settings input[aria-label*="Temperature" i]', 'ms-run-settings input[name*="temperature" i]', 'ms-temperature-setting input[type="number"]'],
                ["temperature"],
                f"{float(cfg.temp):g}",
                stage="Temperature",
            ):
                self._cache["temp"] = float(cfg.temp)

        if cfg.media_resolution is not None and self._cache.get("media_resolution") != cfg.media_resolution.lower():
            res = self._select_mat_dropdown(
                driver,
                '[data-test-id="mediaResolution"] mat-select, mat-select[aria-label="Media resolution"]',
                [cfg.media_resolution.strip().lower()],
                stage="Media resolution",
            )
            if res is not None:
                self._cache["media_resolution"] = cfg.media_resolution.lower()

        if cfg.max_output_tokens is not None and self._cache.get("max_output_tokens") != int(cfg.max_output_tokens):
            if self._set_named_number_input(
                driver,
                ['ms-run-settings input[name="maxOutputTokens"]', 'ms-run-settings input[aria-label="Maximum output tokens"]'],
                ["output length", "max output", "maximum output"],
                str(int(cfg.max_output_tokens)),
                stage="Output length",
            ):
                self._cache["max_output_tokens"] = int(cfg.max_output_tokens)

        if cfg.top_p is not None and self._cache.get("top_p") != float(cfg.top_p):
            if self._set_named_number_input(
                driver,
                ['ms-run-settings input[aria-label*="Top P" i]', 'ms-run-settings input[name*="topP" i]'],
                ["top p", "top-p"],
                f"{float(cfg.top_p):g}",
                stage="Top P",
            ):
                self._cache["top_p"] = float(cfg.top_p)

        if cfg.seed is not None and self._cache.get("seed") != int(cfg.seed):
            if self._set_named_number_input(
                driver,
                ['ms-run-settings input[aria-label*="Seed" i]', 'ms-run-settings input[name*="seed" i]'],
                ["seed"],
                str(int(cfg.seed)),
                stage="Seed",
            ):
                self._cache["seed"] = int(cfg.seed)

        if cfg.stop_sequences is not None and self._cache.get("stop_sequences") != tuple(cfg.stop_sequences):
            self._apply_stop_sequences(driver, cfg.stop_sequences)
            self._cache["stop_sequences"] = tuple(cfg.stop_sequences)

        if cfg.safety_settings is not None and self._cache.get("safety_settings") != repr(cfg.safety_settings):
            self._apply_safety_settings(driver, cfg.safety_settings)
            self._cache["safety_settings"] = repr(cfg.safety_settings)

    def _apply_stop_sequences(self, driver: webdriver.Chrome, stops: List[str]) -> None:
        driver.execute_script(
            "document.querySelectorAll('ms-stop-sequence-input .remove-button, ms-stop-sequence-input button[matChipRemove]').forEach(b => b.click());"
        )
        inputs = driver.find_elements(By.CSS_SELECTOR, 'ms-stop-sequence-input input#chip-input, ms-stop-sequence-input input[aria-label="Add stop sequence"]')
        if not inputs:
            return
        inp = inputs[0]
        for s in stops:
            if not s:
                continue
            self.browser.set_input_value(driver, inp, str(s))
            inp.send_keys(Keys.ENTER)
        self.logger.emit("Stop sequences", f"-> {stops}")

    def _apply_safety_settings(self, driver: webdriver.Chrome, safety: Union[Dict[str, str], str]) -> None:
        if not self.browser.js_click_selector(driver, 'ms-run-settings button[aria-label="Edit safety settings"]'):
            return
        time.sleep(0.15)
        if isinstance(safety, str) and safety.strip().lower() in ("off", "none", "block_none", "disable"):
            driver.execute_script(load_js("safety_sliders_off.js"))
            self.logger.emit("Safety settings", "-> off")
        self._close_dialog_if_open(driver)

    def _materialize_media(self, media: MediaInput) -> Tuple[List[str], Optional[Path]]:
        items: List[MediaItem] = list(media) if isinstance(media, (list, tuple)) and not (
            len(media) == 2 and isinstance(media[0], (bytes, bytearray)) and isinstance(media[1], str)
        ) else [media]

        temp_dir: Optional[Path] = None
        paths: List[str] = []

        for idx, item in enumerate(items):
            if isinstance(item, (str, Path)):
                p = Path(item).expanduser().resolve()
                if not p.is_file():
                    raise FileNotFoundError(f"미디어 파일을 찾을 수 없습니다: {p}")
                paths.append(str(p))
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], (bytes, bytearray)):
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix="pg_media_"))
                dest = temp_dir / (Path(str(item[1])).name or f"media_{idx}.bin")
                dest.write_bytes(bytes(item[0]))
                paths.append(str(dest.resolve()))
            elif hasattr(item, "save") and hasattr(item, "size"):
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix="pg_media_"))
                dest = temp_dir / f"image_{idx}.png"
                item.save(dest, format="PNG")
                paths.append(str(dest.resolve()))
            else:
                raise TypeError(f"지원하지 않는 미디어 형식입니다: {type(item).__name__}")

        return paths, temp_dir

    def attach_media(self, driver: webdriver.Chrome, media: MediaInput, timeout: int = 60) -> None:
        paths, temp_dir = self._materialize_media(media)
        if not paths:
            return

        self.logger.emit("미디어", f"{len(paths)}개 첨부")
        status_js = load_js("media_status.js")
        try:
            before_count = int((driver.execute_script(status_js) or {}).get("count", 0))
            file_input = WebDriverWait(driver, 15, poll_frequency=0.05).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        'ms-prompt-box input[data-test-upload-file-input], ms-add-media-button input[type="file"], ms-prompt-box input[type="file"]',
                    )
                )
            )
            file_input.send_keys("\n".join(paths))

            deadline = time.monotonic() + max(15, int(timeout))
            while time.monotonic() < deadline:
                status = driver.execute_script(status_js) or {"count": 0, "uploading": False}
                if status["count"] >= before_count + len(paths) and not status["uploading"]:
                    time.sleep(0.1)
                    return
                time.sleep(0.12)

            raise TimeoutException(f"미디어 업로드 대기 시간({timeout}초)을 초과했습니다.")
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def get_response_state(self, driver: webdriver.Chrome, prev_count: int, include_thoughts: bool = False) -> Dict[str, Any]:
        return driver.execute_script(load_js("response_state.js"), prev_count, include_thoughts) or {
            "totalTurns": prev_count,
            "hasUserTurn": False,
            "hasModelTurn": False,
            "isGenerating": False,
            "hasRerunBtn": False,
            "errors": [],
            "text": "",
            "bodyLength": 0,
            "imageCount": 0,
        }

    def extract_generated_images(
        self,
        driver: webdriver.Chrome,
        prev_count: int,
        save_dir: Optional[Union[str, Path]] = None,
    ) -> List[Dict[str, Any]]:
        raw_items = driver.execute_async_script(load_js("extract_images.js"), prev_count) or []

        dest_dir = Path(save_dir) if save_dir else None
        if dest_dir is not None:
            dest_dir.mkdir(parents=True, exist_ok=True)

        results: List[Dict[str, Any]] = []
        stamp = int(time.time() * 1000)
        for idx, item in enumerate(raw_items):
            data_url = str(item.get("data_url") or "")
            if "," not in data_url:
                continue
            header, b64 = data_url.split(",", 1)
            mime_type = "image/png"
            if ";" in header and ":" in header:
                mime_type = header.split(":", 1)[1].split(";", 1)[0].strip() or "image/png"
            ext = {"image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(mime_type, "png")
            img_bytes = base64.b64decode(b64)
            saved_path: Optional[Path] = None
            if dest_dir is not None:
                saved_path = dest_dir / f"gen_{stamp}_{idx + 1}.{ext}"
                saved_path.write_bytes(img_bytes)
            results.append(
                {
                    "bytes": img_bytes,
                    "mime_type": mime_type,
                    "width": int(item.get("width") or 0),
                    "height": int(item.get("height") or 0),
                    "path": saved_path,
                }
            )
        return results

    def submit_prompt(self, driver: webdriver.Chrome, text: str) -> int:
        self.logger.emit("전송", f"{len(text)}자")
        prev_count = int(
            driver.execute_script("return document.querySelectorAll('ms-chat-session ms-chat-turn').length;") or 0
        )

        textarea = WebDriverWait(driver, 20, poll_frequency=0.05).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'ms-prompt-box textarea[formcontrolname="promptText"], ms-prompt-box textarea[aria-label="Enter a prompt"]')
            )
        )
        self.browser.set_input_value(driver, textarea, text)

        WebDriverWait(driver, 15, poll_frequency=0.05).until(
            lambda d: d.execute_script(
                "const btn = document.querySelector('ms-run-button button'); return btn && btn.getAttribute('aria-disabled') !== 'true';"
            )
        )

        submit_js = load_js("submit_prompt.js")
        for attempt_idx in range(1, 4):
            self.logger.attempt("전송", attempt_idx, 3, "Run 실행")
            driver.execute_script(submit_js, attempt_idx)

            confirm_deadline = time.monotonic() + 2.0
            while time.monotonic() < confirm_deadline:
                state = self.get_response_state(driver, prev_count)
                if state["totalTurns"] > prev_count or state["isGenerating"] or state["errors"]:
                    return prev_count
                time.sleep(0.05)

        raise TimeoutException("프롬프트 전송 후 AI Studio 턴 생성이 시작되지 않았습니다.")

    def wait_for_response(
        self,
        driver: webdriver.Chrome,
        prev_count: int,
        timeout: int,
        include_thoughts: bool = False,
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        saw_running = False
        last_sig = ("", 0)
        stable_ticks = 0
        empty_idle_ticks = 0

        while time.monotonic() < deadline:
            state = self.get_response_state(driver, prev_count, include_thoughts=include_thoughts)

            if state["errors"]:
                err = " | ".join(state["errors"])
                self.logger.emit("오류", err)
                raise RuntimeError(f"AI Studio 오류: {err}")

            generating = bool(state["isGenerating"])
            cur_text = str(state["text"] or "")
            body_len = int(state.get("bodyLength", 0))
            image_count = int(state.get("imageCount", 0))
            has_model_turn = bool(state["hasModelTurn"])
            has_rerun = bool(state.get("hasRerunBtn"))

            if generating:
                saw_running = True

            cur_sig = (cur_text, image_count)
            if not generating and has_model_turn:
                if body_len > 0 or image_count > 0:
                    empty_idle_ticks = 0
                    if cur_sig == last_sig:
                        stable_ticks += 1
                    else:
                        stable_ticks = 0
                    needed = 1 if has_rerun else 2
                    if stable_ticks >= needed:
                        self.logger.emit("완료", f"{len(cur_text)}자, 이미지 {image_count}개")
                        return {"text": cur_text, "image_count": image_count}
                else:
                    stable_ticks = 0
                    if saw_running:
                        empty_idle_ticks += 1
                        if empty_idle_ticks >= 40:
                            return {"text": cur_text, "image_count": image_count}
            else:
                stable_ticks = 0
                empty_idle_ticks = 0

            last_sig = cur_sig
            time.sleep(0.15)

        raise TimeoutException(f"AI Studio 응답 대기 시간({timeout}초)을 초과했습니다.")

    def click_new_chat(self, driver: webdriver.Chrome) -> None:
        if not self.browser.js_click_selector(driver, 'button[data-test-clear="outside"], a[href="/prompts/new_chat"]'):
            driver.get(AI_STUDIO_NEW_CHAT_URL)
        self.wait_prompt_box_ready(driver, timeout=30)
        self.reset_cache()
        time.sleep(0.15)