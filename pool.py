from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import queue
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union

from playground_on_python.api import PlayGround
from playground_on_python.config import PlayGroundConfig


class PlayGroundPool:
    def __init__(
        self,
        count: int = 2,
        base_profile: str = "default",
        profiles: Optional[Sequence[str]] = None,
        base_dir: Optional[Union[str, Path]] = None,
        headless: bool = True,
        backup: bool = True,
        auto_login: bool = True,
        refresh_clone: bool = False,
        encrypt: bool = True,
        key_path: Optional[Union[str, Path]] = None,
        wipe_runtime_profile: bool = False,
        timeout: int = 180,
        verbose: Union[bool, str] = True,
        log_cb: Optional[Callable[[str], None]] = None,
        default_config: Optional[PlayGroundConfig] = None,
    ) -> None:
        self.base_dir = base_dir
        self.base_profile = base_profile
        self.profiles = list(profiles) if profiles else None
        self.headless = bool(headless)
        self.backup = bool(backup)
        self.auto_login = bool(auto_login)
        self.encrypt = bool(encrypt)
        self.key_path = key_path
        self.wipe_runtime_profile = bool(wipe_runtime_profile)
        self.timeout = timeout
        self.verbose = verbose
        self.log_cb = log_cb
        self.default_config = default_config

        self.clients: List[PlayGround] = []
        self._idle: queue.Queue[PlayGround] = queue.Queue()
        self._started = False

        if self.profiles:
            for pname in self.profiles:
                self.clients.append(
                    PlayGround(
                        base_dir=base_dir,
                        profile_name=str(pname),
                        encrypt=self.encrypt,
                        key_path=self.key_path,
                        wipe_runtime_profile=self.wipe_runtime_profile,
                        timeout=timeout,
                        verbose=verbose,
                        log_cb=log_cb,
                        default_config=default_config,
                    )
                )
        else:
            n = max(1, int(count))
            for idx in range(n):
                self.clients.append(
                    PlayGround(
                        base_dir=base_dir,
                        profile_name=f"{base_profile}_worker_{idx + 1}",
                        clone_from=base_profile,
                        refresh_clone=refresh_clone,
                        encrypt=self.encrypt,
                        key_path=self.key_path,
                        wipe_runtime_profile=self.wipe_runtime_profile,
                        timeout=timeout,
                        verbose=verbose,
                        log_cb=log_cb,
                        default_config=default_config,
                    )
                )

    def __enter__(self) -> "PlayGroundPool":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def start(self, parallel: bool = True, new_chat: bool = True) -> "PlayGroundPool":
        if self._started:
            return self

        if self.auto_login and not self.profiles:
            master = PlayGround(
                base_dir=self.base_dir,
                profile_name=self.base_profile,
                encrypt=self.encrypt,
                key_path=self.key_path,
                wipe_runtime_profile=self.wipe_runtime_profile,
                timeout=self.timeout,
                verbose=self.verbose,
                log_cb=self.log_cb,
            )
            if not master.storage.has_any_saved_session():
                master.setting(first=True, backup=self.backup)

        def _connect_one(client: PlayGround) -> PlayGround:
            return client.connect(
                backup=self.backup,
                headless=self.headless,
                auto_login=self.auto_login if self.profiles else False,
                new_chat=new_chat,
            )

        try:
            if parallel and len(self.clients) > 1:
                with ThreadPoolExecutor(max_workers=len(self.clients)) as ex:
                    list(ex.map(_connect_one, self.clients))
            else:
                for client in self.clients:
                    _connect_one(client)
        except Exception:
            self.close()
            raise

        while not self._idle.empty():
            try:
                self._idle.get_nowait()
            except queue.Empty:
                break
        for client in self.clients:
            self._idle.put(client)

        self._started = True
        return self

    @contextmanager
    def acquire(self, timeout: Optional[float] = None) -> Iterator[PlayGround]:
        if not self._started:
            self.start()
        client = self._idle.get(timeout=timeout)
        try:
            yield client
        finally:
            self._idle.put(client)

    def list_models(
        self,
        kind: Optional[str] = None,
        paid: Optional[bool] = None,
        category: Optional[str] = None,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        with self.acquire() as client:
            return client.list_models(kind=kind, paid=paid, category=category, refresh=refresh)

    def send(self, text: str, **kwargs: Any) -> Union[str, Dict[str, Any]]:
        with self.acquire() as client:
            return client.send(text, **kwargs)

    def generate_image(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        with self.acquire() as client:
            return client.generate_image(prompt, **kwargs)

    def send_batch(
        self,
        tasks: Sequence[Union[str, Dict[str, Any]]],
        default_kwargs: Optional[Dict[str, Any]] = None,
    ) -> List[Union[str, Dict[str, Any]]]:
        if not self._started:
            self.start()
        if not tasks:
            return []

        base_kw = dict(default_kwargs or {})

        def _run_one(item: Union[str, Dict[str, Any]]) -> Union[str, Dict[str, Any]]:
            if isinstance(item, str):
                return self.send(item, **base_kw)
            kw = {**base_kw, **item}
            prompt_text = kw.pop("text")
            return self.send(prompt_text, **kw)

        with ThreadPoolExecutor(max_workers=len(self.clients)) as ex:
            return list(ex.map(_run_one, tasks))

    def close(self) -> None:
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass
        self._started = False
