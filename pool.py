from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import queue
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union
from .api import PlayGround
from .config import PlayGroundConfig

class PlayGroundPool:
    """여러 Chrome 워커를 띄워 병렬 요청을 처리하는 클라이언트 풀."""

    def __init__(
        self,
        count: int=2,
        base_profile: str='default',
        profiles: Optional[Sequence[str]]=None,
        base_dir: Optional[Union[str, Path]]=None,
        headless: bool=True,
        backup: bool=True,
        auto_login: bool=True,
        refresh_clone: bool=False,
        encrypt: bool=True,
        key_path: Optional[Union[str, Path]]=None,
        wipe_runtime_profile: bool=False,
        timeout: Optional[int]=None,
        verbose: Union[bool, str]=True,
        log_cb: Optional[Callable[[str], None]]=None,
        default_config: Optional[PlayGroundConfig]=None,
    ) -> None:
        """워커 풀 초기화.

        count: base_profile을 복제해 띄울 워커 수 (profiles 미지정 시)
        base_profile: 복제 원본 프로필명
        profiles: 서로 다른 개별 프로필명 리스트 (지정 시 count 무시)
        headless, backup, auto_login, refresh_clone, encrypt, default_config: 각 워커 PlayGround에 전달
        """
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
                self.clients.append(PlayGround(base_dir=base_dir, profile_name=str(pname), encrypt=self.encrypt, key_path=self.key_path, wipe_runtime_profile=self.wipe_runtime_profile, timeout=timeout, verbose=verbose, log_cb=log_cb, default_config=default_config))
        else:
            n = max(1, int(count))
            for idx in range(n):
                self.clients.append(PlayGround(base_dir=base_dir, profile_name=f'{base_profile}_worker_{idx + 1}', clone_from=base_profile, refresh_clone=refresh_clone, encrypt=self.encrypt, key_path=self.key_path, wipe_runtime_profile=self.wipe_runtime_profile, timeout=timeout, verbose=verbose, log_cb=log_cb, default_config=default_config))

    def __enter__(self) -> 'PlayGroundPool':
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def start(self, parallel: bool=True, new_chat: bool=True) -> 'PlayGroundPool':
        """풀 내 모든 워커 브라우저 연결 (parallel=True면 동시 연결) 후 self 반환."""
        if self._started:
            return self
        if self.auto_login and (not self.profiles):
            master = PlayGround(base_dir=self.base_dir, profile_name=self.base_profile, encrypt=self.encrypt, key_path=self.key_path, wipe_runtime_profile=self.wipe_runtime_profile, timeout=self.timeout, verbose=self.verbose, log_cb=self.log_cb)
            if not master.storage.has_any_saved_session():
                master.setting(first=True, backup=self.backup)
        def _connect_one(client: PlayGround) -> PlayGround:
            return client.connect(backup=self.backup, headless=self.headless, auto_login=self.auto_login if self.profiles else False, new_chat=new_chat)
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
    def acquire(self, timeout: Optional[float]=None) -> Iterator[PlayGround]:
        """유휴 워커 1개를 대여하고 블록 종료 시 자동 반납."""
        if not self._started:
            self.start()
        client = self._idle.get(timeout=timeout)
        try:
            yield client
        finally:
            self._idle.put(client)

    def list_models(
        self,
        kind: Optional[str]=None,
        paid: Optional[bool]=None,
        category: Optional[str]=None,
        refresh: bool=False,
    ) -> List[Dict[str, Any]]:
        """유휴 워커 1개를 사용해 모델 목록(list[dict]) 조회."""
        with self.acquire() as client:
            return client.list_models(kind=kind, paid=paid, category=category, refresh=refresh)

    def send(self, text: str, **kwargs: Any) -> Union[str, Dict[str, Any]]:
        """유휴 워커 1개로 PlayGround.send() 실행."""
        with self.acquire() as client:
            return client.send(text, **kwargs)

    def generate_image(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        """유휴 워커 1개로 PlayGround.generate_image() 실행."""
        with self.acquire() as client:
            return client.generate_image(prompt, **kwargs)

    def send_batch(
        self,
        tasks: Sequence[Union[str, Dict[str, Any]]],
        default_kwargs: Optional[Dict[str, Any]]=None,
    ) -> List[Union[str, Dict[str, Any]]]:
        """여러 작업을 워커 수만큼 병렬 실행해 입력 순서대로 결과 리스트 반환.

        tasks: 프롬프트 str 또는 send() 인자 dict 리스트 (dict에는 'text' 키 필수)
        default_kwargs: 모든 작업에 공통 적용할 send() 기본 인자
        """
        if not self._started:
            self.start()
        if not tasks:
            return []
        base_kw = dict(default_kwargs or {})
        def _run_one(item: Union[str, Dict[str, Any]]) -> Union[str, Dict[str, Any]]:
            if isinstance(item, str):
                return self.send(item, **base_kw)
            kw = {**base_kw, **item}
            prompt_text = kw.pop('text')
            return self.send(prompt_text, **kw)
        with ThreadPoolExecutor(max_workers=len(self.clients)) as ex:
            return list(ex.map(_run_one, tasks))

    def close(self) -> None:
        """풀의 모든 워커 브라우저 종료."""
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass
        self._started = False
