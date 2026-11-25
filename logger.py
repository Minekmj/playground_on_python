from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional, Union

class PlayGroundLogger:

    def __init__(
        self,
        client_id: str='default',
        verbose: Union[bool, str]=True,
        callback: Optional[Callable[[str], None]]=None,
    ) -> None:
        self.client_id = client_id
        self.callback = callback
        if isinstance(verbose, str):
            v = verbose.strip().lower()
            if v in ('off', 'false', '0', 'none', 'quiet'):
                self.level = 0
            elif v in ('debug', 'all', 'trace'):
                self.level = 2
            else:
                self.level = 1
        else:
            self.level = 1 if verbose else 0

    def _write(self, stage: str, message: str) -> None:
        now = datetime.now().strftime('%H:%M:%S')
        line = f'[{now}][{self.client_id}][{stage}] {message}'
        if self.level >= 1:
            print(line, flush=True)
        if self.callback is not None:
            try:
                self.callback(line)
            except Exception:
                pass

    def emit(self, stage: str, message: str) -> None:
        if self.level >= 1:
            self._write(stage, message)

    def debug(self, stage: str, message: str) -> None:
        if self.level >= 2:
            self._write(stage, message)

    def attempt(self, stage: str, idx: int, total: int, message: str) -> None:
        if idx >= 2 or self.level >= 2:
            self._write(stage, f'재시도 {idx}/{total} - {message}')
