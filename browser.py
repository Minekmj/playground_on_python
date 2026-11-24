from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from typing import List, Optional, Set
import urllib.request

from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.options import Options

from .js_loader import load_js
from .logger import PlayGroundLogger
from .storage import ProfileStorage


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def find_chrome_executable() -> Optional[str]:
    system = platform.system()
    candidates: List[str] = []
    if system == "Windows":
        for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_key)
            if base:
                candidates.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
                candidates.append(str(Path(base) / "Chromium" / "Application" / "chrome.exe"))
    elif system == "Darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return None


def _kill_pid_tree(pid: int) -> None:
    if not pid or pid <= 0:
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def kill_chrome_using_profile(profile_dir: Path) -> None:
    target = str(profile_dir.resolve())
    system = platform.system()
    try:
        if system == "Windows":
            escaped = target.replace("'", "''")
            ps_cmd = (
                f"$t = '{escaped}'; "
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='chromedriver.exe'\" | "
                "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($t, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
                "ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null }"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        else:
            subprocess.run(
                ["pkill", "-9", "-f", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
    except Exception:
        pass


class BrowserManager:
    def __init__(self, storage: ProfileStorage, logger: PlayGroundLogger) -> None:
        self.storage = storage
        self.logger = logger
        self.chrome_proc: Optional[subprocess.Popen] = None
        self._tracked_pids: Set[int] = set()

    def build_options(
        self,
        headless: bool = False,
        debugger_address: Optional[str] = None,
        extra_safe: bool = False,
    ) -> Options:
        options = Options()
        options.page_load_strategy = "eager"
        if debugger_address:
            options.add_experimental_option("debuggerAddress", debugger_address)
            return options

        options.add_argument(f"--user-data-dir={self.storage.profile_dir.resolve()}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-background-mode")
        options.add_argument("--mute-audio")
        options.add_argument("--window-size=1440,960")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        if extra_safe:
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
        return options

    def _create_driver(self, headless: bool, extra_safe: bool = False) -> webdriver.Chrome:
        options = self.build_options(headless=headless, extra_safe=extra_safe)
        driver = webdriver.Chrome(options=options)
        try:
            svc = getattr(driver, "service", None)
            proc = getattr(svc, "process", None) if svc else None
            if proc and proc.pid:
                self._tracked_pids.add(int(proc.pid))
        except Exception:
            pass
        try:
            driver.set_window_size(1440, 960)
        except Exception:
            pass
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
            )
            if headless:
                ua = driver.execute_script("return navigator.userAgent || '';") or ""
                if "HeadlessChrome/" in ua:
                    driver.execute_cdp_cmd(
                        "Network.setUserAgentOverride",
                        {"userAgent": ua.replace("HeadlessChrome/", "Chrome/")},
                    )
        except Exception:
            pass
        return driver

    def start_selenium(self, headless: bool = True) -> webdriver.Chrome:
        self.storage.acquire_profile_lock()
        try:
            self.logger.debug("브라우저", f"Chrome 시작 ({'Headless' if headless else 'GUI'})")
            if self.storage.cleanup_locks():
                kill_chrome_using_profile(self.storage.profile_dir)
                time.sleep(0.3)
                self.storage.cleanup_locks()

            try:
                return self._create_driver(headless=headless, extra_safe=False)
            except SessionNotCreatedException:
                self.logger.emit("브라우저", "이전 Chrome 점유 감지 -> 강제 정리 후 재시도")
                kill_chrome_using_profile(self.storage.profile_dir)
                time.sleep(0.4)
                self.storage.cleanup_locks()
                try:
                    return self._create_driver(headless=headless, extra_safe=True)
                except SessionNotCreatedException:
                    self.logger.emit("브라우저", "프로필 손상 의심 -> 런타임 프로필 초기화 후 재시도")
                    self.storage.wipe_runtime_profile()
                    return self._create_driver(headless=headless, extra_safe=True)
        except Exception:
            self.storage.release_profile_lock()
            raise

    def launch_native_chrome(self, target_url: str) -> Optional[int]:
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            return None
        self.storage.acquire_profile_lock()
        try:
            if self.storage.cleanup_locks():
                kill_chrome_using_profile(self.storage.profile_dir)
                time.sleep(0.3)
                self.storage.cleanup_locks()
            port = find_free_port()
            self.logger.emit("로그인", "구글 로그인 창 실행 (브라우저에서 로그인을 완료해 주세요)")
            cmd = [
                chrome_exe,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self.storage.profile_dir.resolve()}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-mode",
                "--window-size=1440,960",
                target_url,
            ]
            self.chrome_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if self.chrome_proc.pid:
                self._tracked_pids.add(int(self.chrome_proc.pid))
            return port
        except Exception:
            self.storage.release_profile_lock()
            raise

    def wait_for_studio_tab_and_attach(self, port: int, wait_timeout: int) -> webdriver.Chrome:
        deadline = time.monotonic() + max(30, wait_timeout)
        last_log = 0.0
        while time.monotonic() < deadline:
            if self.chrome_proc is not None and self.chrome_proc.poll() is not None:
                raise RuntimeError("로그인 완료 전에 브라우저 창이 닫혔습니다.")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2.0) as resp:
                    tabs = json.loads(resp.read().decode("utf-8"))
                on_studio = any(
                    isinstance(t, dict)
                    and t.get("type") == "page"
                    and "aistudio.google.com" in str(t.get("url", "")) and "accounts.google.com" not in str(t.get("url", ""))
                    for t in tabs
                )
                if on_studio:
                    self.logger.debug("로그인", "AI Studio 탭 감지 -> Selenium 연결")
                    options = self.build_options(debugger_address=f"127.0.0.1:{port}")
                    driver = webdriver.Chrome(options=options)
                    try:
                        svc = getattr(driver, "service", None)
                        proc = getattr(svc, "process", None) if svc else None
                        if proc and proc.pid:
                            self._tracked_pids.add(int(proc.pid))
                    except Exception:
                        pass
                    return driver
            except Exception:
                pass
            now = time.monotonic()
            if now - last_log >= 15.0:
                self.logger.emit("로그인", "로그인 및 AI Studio 진입 대기 중...")
                last_log = now
            time.sleep(0.5)
        raise TimeoutError("구글 로그인 및 AI Studio 접속 대기 시간이 초과되었습니다.")

    def shutdown(self, driver: Optional[webdriver.Chrome]) -> None:
        pids = set(self._tracked_pids)
        if driver is not None:
            try:
                svc = getattr(driver, "service", None)
                proc = getattr(svc, "process", None) if svc else None
                if proc and proc.pid:
                    pids.add(int(proc.pid))
            except Exception:
                pass
            if self.chrome_proc is not None:
                try:
                    driver.execute_cdp_cmd("Browser.close", {})
                except Exception:
                    pass
            try:
                driver.quit()
            except Exception:
                pass
        if self.chrome_proc is not None:
            if self.chrome_proc.pid:
                pids.add(int(self.chrome_proc.pid))
            try:
                if self.chrome_proc.poll() is None:
                    self.chrome_proc.wait(timeout=4)
            except Exception:
                try:
                    if self.chrome_proc.poll() is None:
                        self.chrome_proc.terminate()
                        self.chrome_proc.wait(timeout=2)
                except Exception:
                    pass
            self.chrome_proc = None

        for pid in pids:
            _kill_pid_tree(pid)
        self._tracked_pids.clear()
        kill_chrome_using_profile(self.storage.profile_dir)
        self.storage.cleanup_locks()
        self.storage.release_profile_lock()

    def js_click_selector(self, driver: webdriver.Chrome, selector: str, label: str = "") -> bool:
        clicked = bool(driver.execute_script(load_js("click_selector.js"), selector))
        if clicked and label:
            self.logger.debug("JS", label)
        return clicked

    def set_input_value(self, driver: webdriver.Chrome, element, value: str) -> None:
        driver.execute_script(load_js("set_input_value.js"), element, value)