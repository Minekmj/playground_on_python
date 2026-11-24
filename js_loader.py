from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_JS_DIR = Path(__file__).resolve().parent / "js"


@lru_cache(maxsize=None)
def load_js(filename: str) -> str:
    path = _JS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"JS 파일을 찾을 수 없습니다: {path}")
    return path.read_text(encoding="utf-8")
