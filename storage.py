from __future__ import annotations

import os
import base64
import json
import platform
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .crypto import ProfileCrypto, build_zip_bytes, extract_zip_bytes
from .logger import PlayGroundLogger


AI_STUDIO_BASE_URL = 'https://aistudio.google.com'
AI_STUDIO_NEW_CHAT_URL = f'{AI_STUDIO_BASE_URL}/prompts/new_chat'

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_PROFILE_LOCKS: Dict[str, threading.RLock] = {}

_IGNORED_PROFILE_DIRS = {
    'Cache', 'Code Cache', 'GPUCache', 'DawnGraphiteCache', 'DawnWebGPUCache',
    'GrShaderCache', 'ShaderCache', 'Crashpad', 'BrowserMetrics', 'Safe Browsing',
    'OptimizationHints', 'component_crx_cache', 'extensions_crx_cache',
    'OnDeviceHeadSuggestModel', 'hyphen-data', 'Subresource Filter', 'WidevineCdm',
    'ZxcvbnData', 'FileTypePolicies', 'MEIPreload', 'SafetyTips', 'SSLErrorAssistant',
    'Crowd Deny', 'CertificateRevocation', 'PKIMetadata', 'FirstPartySetsPreloaded',
    'OriginTrials', 'Webstore Downloads', 'CacheStorage',
}

_ESSENTIAL_PROFILE_REL_PATHS = (
    'Local State',
    'Default/Cookies',
    'Default/Network',
    'Default/Local Storage',
    'Default/Session Storage',
    'Default/IndexedDB',
    'Default/Preferences',
    'Default/Secure Preferences',
    'Default/Web Data',
    'Default/Login Data',
)

_CHROME_LOCK_NAMES = (
    'SingletonLock',
    'SingletonCookie',
    'SingletonSocket',
    'lockfile',
    'DevToolsActivePort',
)


# --- OS 파일 잠금 헬퍼 ---

def _lock_file_handle(fp) -> None:
    if platform.system() == 'Windows':
        import msvcrt
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_handle(fp) -> None:
    if platform.system() == 'Windows':
        import msvcrt
        msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


# --- 단일 JSON 프로필 저장소 ---

class ProfileStorage:
    """프로필 상태·쿠키·히스토리·백업 아카이브를 단일 JSON 파일로 관리."""

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]],
        profile_name: str,
        logger: PlayGroundLogger,
        encrypt: bool = True,
        key_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.root_dir = Path(base_dir) if base_dir else Path(os.getcwd()).resolve() / '.pg_data'
        self.profile_name = profile_name
        self.logger = logger
        self.encrypt = bool(encrypt)
        self._lock_fp = None
        self._thread_lock_held = False
        self._bundle_cache: Optional[Dict[str, Any]] = None

        # 파일/폴더 최소화: <profile_name>.json 단일 파일 + 실행 중 임시 런타임 폴더
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.root_dir / f'{profile_name}.json'
        self.lock_file_path = self.root_dir / f'.{profile_name}.lock'
        self.profile_dir = self.root_dir / f'{profile_name}_runtime'

        self.crypto: Optional[ProfileCrypto] = None
        if self.encrypt:
            kp = Path(key_path) if key_path else self.root_dir / 'key.bmp'
            self.crypto = ProfileCrypto(kp)

    # --- 프로세스 / 스레드 잠금 ---

    def _get_thread_lock(self) -> threading.RLock:
        key = str(self.profile_dir.resolve()).lower()
        with _THREAD_LOCKS_GUARD:
            if key not in _THREAD_PROFILE_LOCKS:
                _THREAD_PROFILE_LOCKS[key] = threading.RLock()
            return _THREAD_PROFILE_LOCKS[key]

    def _open_and_lock_file(self):
        self.root_dir.mkdir(parents=True, exist_ok=True)
        fp = self.lock_file_path.open('a+b')
        try:
            fp.seek(0)
            if fp.read(1) == b'':
                fp.write(b'0')
                fp.flush()
            fp.seek(0)
            _lock_file_handle(fp)
            return fp
        except Exception:
            try:
                fp.close()
            except Exception:
                pass
            raise

    def acquire_profile_lock(self) -> None:
        tlock = self._get_thread_lock()
        if not tlock.acquire(blocking=False):
            raise RuntimeError(
                f"프로필 '{self.profile_name}'이(가) 이미 현재 프로세스에서 실행 중입니다. "
                "동시 실행이 필요하면 PlayGroundPool 또는 clone_from을 사용하세요."
            )
        self._thread_lock_held = True
        try:
            self._lock_fp = self._open_and_lock_file()
        except Exception as exc:
            self._thread_lock_held = False
            tlock.release()
            raise RuntimeError(
                f"프로필 '{self.profile_name}'이(가) 다른 파이썬 프로세스에서 사용 중입니다."
            ) from exc

    def release_profile_lock(self) -> None:
        if self._lock_fp is not None:
            try:
                self._lock_fp.seek(0)
                _unlock_file_handle(self._lock_fp)
            except Exception:
                pass
            try:
                self._lock_fp.close()
            except Exception:
                pass
            self._lock_fp = None
            try:
                self.lock_file_path.unlink(missing_ok=True)
            except OSError:
                pass

        if self._thread_lock_held:
            self._thread_lock_held = False
            try:
                self._get_thread_lock().release()
            except Exception:
                pass

    def cleanup_locks(self) -> bool:
        still_locked = False
        for lock_name in _CHROME_LOCK_NAMES:
            target = self.profile_dir / lock_name
            if target.exists() or target.is_symlink():
                try:
                    target.unlink()
                except OSError:
                    still_locked = True
        return still_locked

    # --- 단일 JSON 파일 입출력 및 암복호화 헬퍼 ---

    def _empty_bundle(self) -> Dict[str, Any]:
        return {
            'version': 1,
            'profile_name': self.profile_name,
            'encrypted': self.encrypt,
            'updated_at': '',
            'state': None,
            'cookies': None,
            'history': [],
            'profile_archive': None,
        }

    def _read_bundle(self) -> Dict[str, Any]:
        if self._bundle_cache is not None:
            return dict(self._bundle_cache)
        if not self.data_file.is_file():
            return self._empty_bundle()
        try:
            raw = json.loads(self.data_file.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                bundle = {**self._empty_bundle(), **raw}
                self._bundle_cache = bundle
                return dict(bundle)
        except Exception:
            pass
        return self._empty_bundle()

    def _write_bundle(self, bundle: Dict[str, Any]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        bundle['version'] = 1
        bundle['profile_name'] = self.profile_name
        bundle['encrypted'] = self.encrypt
        bundle['updated_at'] = datetime.now().isoformat(timespec='seconds')
        self._bundle_cache = dict(bundle)
        self.data_file.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def _encode_field(self, value: Any) -> Any:
        if self.crypto is None:
            return value
        raw_text = json.dumps(value, ensure_ascii=False)
        return base64.b64encode(self.crypto.encrypt_text(raw_text)).decode('ascii')

    def _decode_field(self, stored: Any) -> Any:
        if stored is None:
            return None
        if isinstance(stored, str) and self.crypto is not None:
            try:
                plain = self.crypto.decrypt_text(base64.b64decode(stored))
                return json.loads(plain)
            except Exception:
                return None
        return stored

    # --- 프로필 데이터 상태 확인 ---

    def has_profile_data(self) -> bool:
        return self.profile_dir.exists() and any(self.profile_dir.iterdir())

    def has_backup_data(self) -> bool:
        bundle = self._read_bundle()
        return bool(bundle.get('profile_archive') or bundle.get('cookies'))

    def has_any_saved_session(self) -> bool:
        if not self.data_file.is_file():
            return False
        bundle = self._read_bundle()
        return bool(bundle.get('profile_archive') or bundle.get('cookies') or bundle.get('state'))

    def wipe_runtime_profile(self) -> None:
        if self.profile_dir.exists():
            shutil.rmtree(self.profile_dir, ignore_errors=True)

    # --- 프로필 백업 / 복원 / 복제 ---

    def _essential_targets(self, pdir: Path) -> List[Path]:
        targets = [pdir / rel for rel in _ESSENTIAL_PROFILE_REL_PATHS if (pdir / rel).exists()]
        return targets if targets else [pdir]

    def backup_profile(self) -> None:
        if not self.has_profile_data():
            return
        targets = self._essential_targets(self.profile_dir)
        if self.crypto is not None:
            raw_bytes = self.crypto.encrypt_files_to_bytes(
                self.profile_dir, targets, ignore_names=_IGNORED_PROFILE_DIRS,
            )
        else:
            raw_bytes = build_zip_bytes(
                self.profile_dir, targets, ignore_names=_IGNORED_PROFILE_DIRS,
            )

        bundle = self._read_bundle()
        bundle['profile_archive'] = base64.b64encode(raw_bytes).decode('ascii')
        self._write_bundle(bundle)
        self.logger.emit('백업', f'프로필 데이터 저장 완료 ({self.data_file.name})')

    def restore_profile_from_backup(self) -> bool:
        bundle = self._read_bundle()
        arc_b64 = bundle.get('profile_archive')
        if not arc_b64 or not isinstance(arc_b64, str):
            return False

        try:
            raw_bytes = base64.b64decode(arc_b64)
            self.wipe_runtime_profile()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            if self.crypto is not None:
                self.crypto.decrypt_bytes_to_dir(raw_bytes, self.profile_dir)
            else:
                extract_zip_bytes(raw_bytes, self.profile_dir)
            return True
        except Exception:
            return False

    def clone_from_profile(self, source_profile: str, force: bool = False) -> None:
        if source_profile == self.profile_name:
            return
        if not force and self.has_profile_data():
            return

        src_storage = ProfileStorage(
            base_dir=self.root_dir,
            profile_name=source_profile,
            logger=self.logger,
            encrypt=self.encrypt,
            key_path=self.crypto.key_bmp_path if self.crypto else None,
        )
        if not src_storage.data_file.is_file() and not src_storage.has_profile_data():
            raise FileNotFoundError(f"복제할 원본 프로필('{source_profile}')이 없습니다.")

        if src_storage.has_profile_data() and not src_storage.has_backup_data():
            src_storage.backup_profile()

        src_bundle = src_storage._read_bundle()
        new_bundle = self._empty_bundle()
        new_bundle['profile_archive'] = src_bundle.get('profile_archive')

        src_state = src_storage.load_state(backup=True)
        if src_state:
            src_state['prompt_url'] = AI_STUDIO_NEW_CHAT_URL
            src_state['prompt_id'] = ''
            new_bundle['state'] = self._encode_field(src_state)

        src_cookies = src_storage.load_cookies(backup=True)
        if src_cookies:
            new_bundle['cookies'] = self._encode_field(src_cookies)

        self._write_bundle(new_bundle)
        self.restore_profile_from_backup()
        self.logger.emit('복제', f"'{source_profile}' -> '{self.profile_name}'")

    # --- 상태 / 쿠키 / 히스토리 (단일 JSON 내 필드) ---

    def load_state(self, backup: bool = True) -> Dict[str, Any]:
        bundle = self._read_bundle()
        data = self._decode_field(bundle.get('state'))
        return data if isinstance(data, dict) else {}

    def save_state(self, info: Dict[str, Any], backup: bool = True) -> Dict[str, Any]:
        state = {**info, 'updated_at': datetime.now().isoformat(timespec='seconds')}
        bundle = self._read_bundle()
        bundle['state'] = self._encode_field(state)
        self._write_bundle(bundle)
        return state

    def save_cookies(self, cookies: List[Dict[str, Any]], backup: bool = True) -> None:
        if not cookies:
            return
        bundle = self._read_bundle()
        bundle['cookies'] = self._encode_field(cookies)
        self._write_bundle(bundle)

    def load_cookies(self, backup: bool = True) -> List[Dict[str, Any]]:
        bundle = self._read_bundle()
        data = self._decode_field(bundle.get('cookies'))
        return data if isinstance(data, list) else []

    def append_history(
        self,
        prompt_url: str,
        prompt_text: str,
        response_text: str,
        meta: Dict[str, Any],
    ) -> None:
        try:
            record = {
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'client_id': self.profile_name,
                'prompt_url': prompt_url,
                'meta': meta,
                'prompt': prompt_text,
                'response': response_text,
            }
            bundle = self._read_bundle()
            history = bundle.get('history')
            if not isinstance(history, list):
                history = []
            history.append(self._encode_field(record))
            bundle['history'] = history
            self._write_bundle(bundle)
        except Exception:
            pass
