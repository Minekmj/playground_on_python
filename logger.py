from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Union


def _parse_verbose_level(verbose: Union[bool, str]) -> int:
    if isinstance(verbose, str):
        v = verbose.strip().lower()
        if v in ('off', 'false', '0', 'none', 'quiet'):
            return 0
        if v in ('debug', 'all', 'trace'):
            return 2
        return 1
    return 1 if verbose else 0


class PlayGroundLogger:
    """단계별 콘솔 로그 및 선택적 콜백 출력기."""

    def __init__(
        self,
        client_id: str = 'default',
        verbose: Union[bool, str] = True,
        callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.client_id = client_id
        self.callback = callback
        self.level = _parse_verbose_level(verbose)

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
