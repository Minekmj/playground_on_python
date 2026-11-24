from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union

from selenium import webdriver
from selenium.common.exceptions import TimeoutException

from playground_on_python.browser import BrowserManager
from playground_on_python.config import PlayGroundConfig
from playground_on_python.dom import AIStudioDOM, MediaInput
from playground_on_python.logger import PlayGroundLogger
from playground_on_python.storage import AI_STUDIO_BASE_URL, AI_STUDIO_NEW_CHAT_URL, ProfileStorage


class PlayGround:
    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        profile_name: str = "default",
        clone_from: Optional[str] = None,
        refresh_clone: bool = False,
        encrypt: bool = True,
        key_path: Optional[Union[str, Path]] = None,
        wipe_runtime_profile: bool = False,
        timeout: int = 180,
        verbose: Union[bool, str] = True,
        log_cb: Optional[Callable[[str], None]] = None,
        default_config: Optional[PlayGroundConfig] = None,
    ) -> None:
        self.profile_name = profile_name
        self.clone_from = clone_from
        self.refresh_clone = bool(refresh_clone)
        self.encrypt = bool(encrypt)
        self.wipe_runtime_profile = bool(wipe_runtime_profile)
        self.timeout = max(30, int(timeout))
        self.default_config = default_config or PlayGroundConfig()

        self.logger = PlayGroundLogger(client_id=profile_name, verbose=verbose, callback=log_cb)
        self.storage = ProfileStorage(
            base_dir=base_dir,
            profile_name=profile_name,
            logger=self.logger,
            encrypt=self.encrypt,
            key_path=key_path,
        )
        self.browser = BrowserManager(storage=self.storage, logger=self.logger)
        self.dom = AIStudioDOM(browser=self.browser, logger=self.logger)

        self.driver: Optional[webdriver.Chrome] = None
        self._backup_enabled = False
        self._state: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def __enter__(self) -> "PlayGround":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def configure(self, config: Optional[PlayGroundConfig] = None, **kwargs: Any) -> "PlayGround":
        base = config if config is not None else self.default_config
        self.default_config = base.merged(**kwargs)
        return self

    def _save_session(self, driver: webdriver.Chrome, backup: bool) -> Dict[str, Any]:
        info = self.dom.extract_account_info(driver)
        state = self.storage.save_state(info, backup=backup)
        self._state = state
        try:
            cookies = driver.get_cookies()
            self.storage.save_cookies(cookies, backup=backup)
        except Exception:
            pass
        return state

    def _restore_cookies(self, driver: webdriver.Chrome, backup: bool) -> bool:
        cookies = self.storage.load_cookies(backup=backup)
        if not cookies:
            return False
        driver.get(AI_STUDIO_BASE_URL)
        time.sleep(0.5)
        restored = 0
        for cookie in cookies:
            c = dict(cookie)
            c.pop("sameSite", None)
            if "expiry" in c and c["expiry"] is not None:
                try:
                    c["expiry"] = int(c["expiry"])
                except Exception:
                    c.pop("expiry", None)
            try:
                driver.add_cookie(c)
                restored += 1
            except Exception:
                pass
        return restored > 0

    def is_logged_in(self, backup: bool = True, timeout: int = 30) -> bool:
        with self._lock:
            if self.driver is not None:
                return self.dom.is_logged_in_and_ready(self.driver)
            if backup and not self.storage.has_profile_data():
                self.storage.restore_profile_from_backup()
            if not self.storage.has_any_saved_session():
                return False

            driver = self.browser.start_selenium(headless=True)
            try:
                driver.get(AI_STUDIO_NEW_CHAT_URL)
                self.dom.wait_prompt_box_ready(driver, timeout=timeout)
                time.sleep(0.25)
                if self.dom.is_logged_in_and_ready(driver):
                    return True
                if backup and self._restore_cookies(driver, backup=True):
                    driver.get(AI_STUDIO_NEW_CHAT_URL)
                    self.dom.wait_prompt_box_ready(driver, timeout=timeout)
                    time.sleep(0.25)
                    return self.dom.is_logged_in_and_ready(driver)
                return False
            except Exception:
                return False
            finally:
                self.browser.shutdown(driver)

    def setting(
        self,
        first: Union[bool, str] = "auto",
        backup: bool = True,
        url: Optional[str] = None,
        wait_timeout: int = 300,
        keep_open: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            self.close()
            if isinstance(first, str):
                mode = first.strip().lower()
                if mode == "auto":
                    if self.storage.has_any_saved_session():
                        self.logger.emit("설정", "기존 세션 확인 중 (auto)...")
                        if backup and not self.storage.has_profile_data():
                            self.storage.restore_profile_from_backup()
                        saved = self.storage.load_state(backup=backup)
                        target = url or saved.get("prompt_url") or AI_STUDIO_NEW_CHAT_URL
                        probe = self.browser.start_selenium(headless=True)
                        try:
                            probe.get(target)
                            self.dom.wait_prompt_box_ready(probe, timeout=40)
                            time.sleep(0.25)
                            if not self.dom.is_logged_in_and_ready(probe) and backup:
                                if self._restore_cookies(probe, backup=True):
                                    probe.get(target)
                                    self.dom.wait_prompt_box_ready(probe, timeout=40)
                                    time.sleep(0.25)
                            if self.dom.is_logged_in_and_ready(probe):
                                state = self._save_session(probe, backup=backup)
                                self.logger.emit("설정", f"자동 확인 완료 ({state.get('account_email')})")
                                if keep_open:
                                    self.driver = probe
                                else:
                                    self.browser.shutdown(probe)
                                    if backup:
                                        time.sleep(0.4)
                                        self.storage.backup_profile()
                                    if self.wipe_runtime_profile:
                                        self.storage.wipe_runtime_profile()
                                return state
                        except Exception:
                            pass
                        self.browser.shutdown(probe)
                    self.logger.emit("설정", "세션 없음/만료 -> 로그인 창 열기")
                    first_bool = True
                else:
                    first_bool = mode in ("true", "1", "yes")
            else:
                first_bool = bool(first)

            saved = self.storage.load_state(backup=backup)
            target_url = url or (AI_STUDIO_NEW_CHAT_URL if first_bool else saved.get("prompt_url") or AI_STUDIO_NEW_CHAT_URL)

            driver: Optional[webdriver.Chrome] = None
            try:
                if first_bool:
                    port = self.browser.launch_native_chrome(target_url)
                    if port is not None:
                        driver = self.browser.wait_for_studio_tab_and_attach(port, wait_timeout)
                    else:
                        driver = self.browser.start_selenium(headless=False)
                        driver.get(target_url)

                    deadline = time.monotonic() + max(30, wait_timeout)
                    while time.monotonic() < deadline:
                        if self.dom.is_logged_in_and_ready(driver):
                            break
                        time.sleep(0.5)
                    if not self.dom.is_logged_in_and_ready(driver):
                        raise TimeoutException("구글 로그인 및 AI Studio 플레이그라운드 진입 시간 초과")
                else:
                    if backup and not self.storage.has_profile_data():
                        self.storage.restore_profile_from_backup()
                    driver = self.browser.start_selenium(headless=False)
                    driver.get(target_url)
                    deadline = time.monotonic() + max(30, wait_timeout)
                    while time.monotonic() < deadline:
                        if self.dom.is_logged_in_and_ready(driver):
                            break
                        time.sleep(0.5)
                    if not self.dom.is_logged_in_and_ready(driver):
                        raise TimeoutException("로그인 상태 확인 실패. setting(first=True, backup=True)를 실행해 주세요.")

                state = self._save_session(driver, backup=backup)
                self.logger.emit("설정", f"로그인 저장 완료 ({state.get('account_email')})")
                if keep_open:
                    self.driver = driver
                else:
                    self.browser.shutdown(driver)
                    driver = None
                    if backup:
                        time.sleep(0.5)
                        self.storage.backup_profile()
                    if self.wipe_runtime_profile:
                        self.storage.wipe_runtime_profile()
                return state
            except Exception:
                if driver is not None and not keep_open:
                    self.browser.shutdown(driver)
                raise

    def connect(
        self,
        backup: bool = True,
        headless: bool = True,
        auto_login: bool = True,
        prompt_url: Optional[str] = None,
        new_chat: bool = False,
        timeout: int = 60,
    ) -> "PlayGround":
        with self._lock:
            self.close()
            self._backup_enabled = bool(backup)

            if self.clone_from:
                self.storage.clone_from_profile(self.clone_from, force=self.refresh_clone)

            if backup and not self.storage.has_profile_data():
                self.storage.restore_profile_from_backup()

            if not self.storage.has_any_saved_session():
                if auto_login:
                    self.logger.emit("연결", "저장된 세션 없음 -> 자동 로그인 실행")
                    self.setting(first=True, backup=backup)
                else:
                    raise RuntimeError("저장된 로그인 세션이 없습니다. setting(first=True, backup=True)를 실행하세요.")

            saved = self.storage.load_state(backup=backup)
            self._state = saved

            if prompt_url:
                target_url = prompt_url
            elif new_chat or self.clone_from:
                target_url = AI_STUDIO_NEW_CHAT_URL
            elif backup and saved.get("prompt_url"):
                target_url = str(saved["prompt_url"])
            else:
                target_url = AI_STUDIO_NEW_CHAT_URL

            driver = self.browser.start_selenium(headless=headless)
            try:
                driver.get(target_url)
                self.dom.wait_prompt_box_ready(driver, timeout=timeout)
                time.sleep(0.25)

                if not self.dom.is_logged_in_and_ready(driver):
                    if backup and self._restore_cookies(driver, backup=True):
                        driver.get(target_url)
                        self.dom.wait_prompt_box_ready(driver, timeout=timeout)
                        time.sleep(0.25)

                if not self.dom.is_logged_in_and_ready(driver):
                    if auto_login:
                        self.logger.emit("연결", "세션 만료 -> 자동 재로그인 실행")
                        self.browser.shutdown(driver)
                        driver = None
                        self.setting(first=True, backup=backup)
                        return self.connect(
                            backup=backup,
                            headless=headless,
                            auto_login=False,
                            prompt_url=prompt_url,
                            new_chat=new_chat,
                            timeout=timeout,
                        )
                    raise RuntimeError("구글 계정이 로그인되어 있지 않습니다. setting(first=True, backup=True)를 실행해 주세요.")

                self.driver = driver
                state = self._save_session(driver, backup=backup)
                self.logger.emit("연결", f"연결 완료 ({state.get('account_email')})")
                return self
            except Exception:
                if driver is not None:
                    self.browser.shutdown(driver)
                raise

    def list_models(
        self,
        kind: Optional[str] = None,
        paid: Optional[bool] = None,
        category: Optional[str] = None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            driver = self._require_driver()
            return self.dom.list_models(driver, kind=kind, paid=paid, category=category, refresh=refresh)

    def new_chat(self) -> None:
        with self._lock:
            driver = self._require_driver()
            self.dom.click_new_chat(driver)

    def close(self) -> None:
        with self._lock:
            was_open = self.driver is not None
            self.browser.shutdown(self.driver)
            self.driver = None
            self.dom.reset_cache()
            if was_open and self._backup_enabled:
                self.storage.backup_profile()
            if was_open and self.wipe_runtime_profile:
                self.storage.wipe_runtime_profile()

    def _require_driver(self) -> webdriver.Chrome:
        if self.driver is None:
            raise RuntimeError("브라우저가 연결되어 있지 않습니다. 먼저 connect(backup=True)를 호출하세요.")
        return self.driver

    def send(
        self,
        text: str,
        system_input: Optional[str] = None,
        model: Optional[str] = None,
        temp: Optional[float] = None,
        thinnk: Optional[Union[str, bool, int]] = None,
        *,
        media: Optional[MediaInput] = None,
        config: Optional[PlayGroundConfig] = None,
        google_search: Optional[bool] = None,
        url_context: Optional[bool] = None,
        code_execution: Optional[bool] = None,
        structured_output: Optional[Union[bool, Dict[str, Any], str]] = None,
        function_calling: Optional[Union[bool, Dict[str, Any], List[Any], str]] = None,
        media_resolution: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
        safety_settings: Optional[Union[Dict[str, str], str]] = None,
        top_p: Optional[float] = None,
        seed: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        output_modality: Optional[str] = None,
        number_of_images: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        person_generation: Optional[str] = None,
        allow_paid: Optional[bool] = None,
        save_images_dir: Optional[Union[str, Path]] = None,
        include_thoughts: Optional[bool] = None,
        new_chat: Optional[bool] = None,
        timeout: Optional[int] = None,
        media_timeout: int = 60,
        return_dict: bool = False,
        **kwargs: Any,
    ) -> Union[str, Dict[str, Any]]:
        base_cfg = config if config is not None else self.default_config
        effective_cfg = base_cfg.merged(
            model=model,
            system_input=system_input,
            temp=temp,
            thinnk=thinnk,
            thinking_budget=thinking_budget,
            google_search=google_search,
            url_context=url_context,
            code_execution=code_execution,
            structured_output=structured_output,
            function_calling=function_calling,
            media_resolution=media_resolution,
            max_output_tokens=max_output_tokens,
            stop_sequences=stop_sequences,
            safety_settings=safety_settings,
            top_p=top_p,
            seed=seed,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            output_modality=output_modality,
            number_of_images=number_of_images,
            negative_prompt=negative_prompt,
            person_generation=person_generation,
            allow_paid=allow_paid,
            save_images_dir=save_images_dir,
            include_thoughts=include_thoughts,
            new_chat=new_chat,
            **kwargs,
        )

        with self._lock:
            driver = self._require_driver()
            wait_sec = self.timeout if timeout is None else max(15, int(timeout))

            if effective_cfg.new_chat:
                self.dom.click_new_chat(driver)

            self.dom.apply_config(driver, effective_cfg)

            if media is not None:
                self.dom.attach_media(driver, media, timeout=media_timeout)

            prev_count = self.dom.submit_prompt(driver, text)
            res = self.dom.wait_for_response(
                driver,
                prev_count=prev_count,
                timeout=wait_sec,
                include_thoughts=effective_cfg.include_thoughts,
            )

            images: List[Dict[str, Any]] = []
            if res["image_count"] > 0 and (return_dict or effective_cfg.save_images_dir is not None):
                images = self.dom.extract_generated_images(
                    driver,
                    prev_count=prev_count,
                    save_dir=effective_cfg.save_images_dir,
                )

            reply_text = str(res["text"] or "")

            if self._backup_enabled:
                self._save_session(driver, backup=True)
                self.storage.append_history(
                    prompt_url=driver.current_url or "",
                    prompt_text=text,
                    response_text=reply_text,
                    meta={k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(effective_cfg).items() if v is not None},
                )

            if return_dict:
                return {
                    "text": reply_text,
                    "images": images,
                    "paths": [img["path"] for img in images if img.get("path") is not None],
                }
            return reply_text

    def generate_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        *,
        aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        output_modality: Optional[str] = None,
        number_of_images: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        person_generation: Optional[str] = None,
        media: Optional[MediaInput] = None,
        save_to: Optional[Union[str, Path]] = None,
        allow_paid: Optional[bool] = None,
        new_chat: bool = True,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.send(
            text=prompt,
            model=model,
            media=media,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            output_modality=output_modality,
            number_of_images=number_of_images,
            negative_prompt=negative_prompt,
            person_generation=person_generation,
            allow_paid=allow_paid,
            save_images_dir=save_to,
            new_chat=new_chat,
            timeout=timeout,
            return_dict=True,
            **kwargs,
        )
