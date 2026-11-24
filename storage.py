from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Union

from playground_on_python.crypto import ProfileCrypto
from playground_on_python.logger import PlayGroundLogger

AI_STUDIO_BASE_URL = "https://aistudio.google.com"
AI_STUDIO_NEW_CHAT_URL = f"{AI_STUDIO_BASE_URL}/prompts/new_chat"

_IGNORED_PROFILE_DIRS = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GrShaderCache",
    "ShaderCache",
    "Crashpad",
    "BrowserMetrics",
    "Safe Browsing",
    "OptimizationHints",
    "component_crx_cache",
    "extensions_crx_cache",
    "OnDeviceHeadSuggestModel",
    "hyphen-data",
    "Subresource Filter",
    "WidevineCdm",
    "ZxcvbnData",
    "FileTypePolicies",
    "MEIPreload",
    "SafetyTips",
    "SSLErrorAssistant",
    "Crowd Deny",
    "CertificateRevocation",
    "PKIMetadata",
    "FirstPartySetsPreloaded",
    "OriginTrials",
    "Webstore Downloads",
    "CacheStorage",
}

_ESSENTIAL_PROFILE_REL_PATHS = (
    "Local State",
    "Default/Cookies",
    "Default/Network",
    "Default/Local Storage",
    "Default/Session Storage",
    "Default/IndexedDB",
    "Default/Preferences",
    "Default/Secure Preferences",
    "Default/Web Data",
    "Default/Login Data",
)


class ProfileStorage:
    def __init__(
        self,
        base_dir: Optional[Union[str, Path]],
        profile_name: str,
        logger: PlayGroundLogger,
        encrypt: bool = True,
        key_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.root_dir = Path(base_dir) if base_dir else (Path(__file__).resolve().parent / ".pg_data")
        self.profile_name = profile_name
        self.base_dir = self.root_dir / profile_name
        self.profile_dir = self.base_dir / "profile"
        self.backup_dir = self.base_dir / "backup"

        self.state_enc_file = self.base_dir / "state.enc"
        self.backup_state_enc_file = self.backup_dir / "state.enc"
        self.cookies_enc_file = self.base_dir / "cookies.enc"
        self.backup_cookies_enc_file = self.backup_dir / "cookies.enc"
        self.history_enc_file = self.backup_dir / "history_backup.enc"
        self.backup_profile_enc_file = self.backup_dir / "profile_data.enc"

        self.state_plain_file = self.base_dir / "state.json"
        self.backup_state_plain_file = self.backup_dir / "state.json"
        self.cookies_plain_file = self.base_dir / "cookies.json"
        self.backup_cookies_plain_file = self.backup_dir / "cookies.json"
        self.history_plain_file = self.backup_dir / "history_backup.jsonl"
        self.backup_profile_plain_dir = self.backup_dir / "profile_snapshot"

        self.logger = logger
        self.encrypt = bool(encrypt)
        self.crypto: Optional[ProfileCrypto] = None
        if self.encrypt:
            kp = Path(key_path) if key_path else (self.root_dir / "key.bmp")
            self.crypto = ProfileCrypto(kp)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_locks(self) -> bool:
        still_locked = False
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile", "DevToolsActivePort"):
            target = self.profile_dir / lock_name
            if target.exists() or target.is_symlink():
                try:
                    target.unlink()
                except OSError:
                    still_locked = True
        return still_locked

    def has_profile_data(self) -> bool:
        return self.profile_dir.exists() and any(self.profile_dir.iterdir())

    def has_backup_data(self) -> bool:
        return (
            self.backup_profile_enc_file.is_file()
            or self.backup_cookies_enc_file.is_file()
            or (self.backup_profile_plain_dir.exists() and any(self.backup_profile_plain_dir.iterdir()))
            or self.backup_cookies_plain_file.is_file()
        )

    def has_any_saved_session(self) -> bool:
        return (
            self.has_profile_data()
            or self.has_backup_data()
            or self.cookies_enc_file.is_file()
            or self.cookies_plain_file.is_file()
        )

    def wipe_runtime_profile(self) -> None:
        if self.profile_dir.exists():
            shutil.rmtree(self.profile_dir, ignore_errors=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def _essential_targets(self, pdir: Path) -> List[Path]:
        targets = [pdir / rel for rel in _ESSENTIAL_PROFILE_REL_PATHS if (pdir / rel).exists()]
        return targets if targets else [pdir]

    def _copy_essential_tree(self, src: Path, dst: Path) -> None:
        if not src.exists():
            return
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)

        def _ignore(_cur_dir: str, names: List[str]) -> List[str]:
            return [
                name for name in names
                if name in _IGNORED_PROFILE_DIRS or name.startswith("Singleton") or name == "lockfile"
            ]

        for target in self._essential_targets(src):
            rel = target.relative_to(src)
            dest_item = dst / rel
            dest_item.parent.mkdir(parents=True, exist_ok=True)
            try:
                if target.is_dir():
                    shutil.copytree(target, dest_item, ignore=_ignore, dirs_exist_ok=True)
                else:
                    shutil.copy2(target, dest_item)
            except OSError:
                pass

    def backup_profile(self) -> None:
        if not self.has_profile_data():
            return
        if self.crypto is not None:
            targets = self._essential_targets(self.profile_dir)
            self.crypto.encrypt_files_to_archive(
                self.profile_dir,
                targets,
                self.backup_profile_enc_file,
                ignore_names=_IGNORED_PROFILE_DIRS,
            )
            if self.backup_profile_plain_dir.exists():
                shutil.rmtree(self.backup_profile_plain_dir, ignore_errors=True)
        else:
            self._copy_essential_tree(self.profile_dir, self.backup_profile_plain_dir)
        self.logger.emit("백업", "프로필 데이터 백업 완료")

    def restore_profile_from_backup(self) -> bool:
        if self.crypto is not None and self.backup_profile_enc_file.is_file():
            self.wipe_runtime_profile()
            self.crypto.decrypt_archive_to_dir(self.backup_profile_enc_file, self.profile_dir)
            return True
        if self.backup_profile_plain_dir.exists() and any(self.backup_profile_plain_dir.iterdir()):
            self._copy_essential_tree(self.backup_profile_plain_dir, self.profile_dir)
            return True
        return False

    def clone_from_profile(self, source_profile: str, force: bool = False) -> None:
        if source_profile == self.profile_name:
            return
        if not force and self.has_profile_data():
            return

        src_base = self.root_dir / source_profile
        src_enc = src_base / "backup" / "profile_data.enc"
        src_plain = src_base / "backup" / "profile_snapshot"
        src_live = src_base / "profile"

        if self.crypto is not None and src_enc.is_file():
            self.wipe_runtime_profile()
            self.crypto.decrypt_archive_to_dir(src_enc, self.profile_dir)
            shutil.copy2(src_enc, self.backup_profile_enc_file)
        elif src_plain.exists() and any(src_plain.iterdir()):
            self._copy_essential_tree(src_plain, self.profile_dir)
            if self.crypto is not None:
                self.backup_profile()
        elif src_live.exists() and any(src_live.iterdir()):
            self._copy_essential_tree(src_live, self.profile_dir)
            if self.crypto is not None:
                self.backup_profile()
        else:
            raise FileNotFoundError(f"복제할 원본 프로필('{source_profile}')이 없습니다.")

        src_storage = ProfileStorage(
            base_dir=self.root_dir,
            profile_name=source_profile,
            logger=self.logger,
            encrypt=self.encrypt,
            key_path=self.crypto.key_bmp_path if self.crypto else None,
        )
        src_state = src_storage.load_state(backup=True)
        if src_state:
            src_state["prompt_url"] = AI_STUDIO_NEW_CHAT_URL
            src_state["prompt_id"] = ""
            self.save_state(src_state, backup=True)
        src_cookies = src_storage.load_cookies(backup=True)
        if src_cookies:
            self.save_cookies(src_cookies, backup=True)

        self.logger.emit("복제", f"'{source_profile}' -> '{self.profile_name}'")

    def _read_json_encrypted_or_plain(self, enc_path: Path, plain_path: Path) -> Any:
        if self.crypto is not None and enc_path.is_file():
            try:
                return json.loads(self.crypto.decrypt_text(enc_path.read_bytes()))
            except Exception:
                pass
        if plain_path.is_file():
            try:
                return json.loads(plain_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def _write_json_encrypted_or_plain(self, data: Any, enc_path: Path, plain_path: Path) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        if self.crypto is not None:
            enc_path.parent.mkdir(parents=True, exist_ok=True)
            enc_path.write_bytes(self.crypto.encrypt_text(raw))
            if plain_path.is_file():
                try:
                    plain_path.unlink()
                except OSError:
                    pass
        else:
            plain_path.parent.mkdir(parents=True, exist_ok=True)
            plain_path.write_text(raw, encoding="utf-8")

    def load_state(self, backup: bool) -> Dict[str, Any]:
        pairs = (
            [(self.backup_state_enc_file, self.backup_state_plain_file), (self.state_enc_file, self.state_plain_file)]
            if backup
            else [(self.state_enc_file, self.state_plain_file), (self.backup_state_enc_file, self.backup_state_plain_file)]
        )
        for enc_p, plain_p in pairs:
            data = self._read_json_encrypted_or_plain(enc_p, plain_p)
            if isinstance(data, dict):
                return data
        return {}

    def save_state(self, info: Dict[str, Any], backup: bool) -> Dict[str, Any]:
        state = {
            **info,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_json_encrypted_or_plain(state, self.state_enc_file, self.state_plain_file)
        if backup:
            self._write_json_encrypted_or_plain(state, self.backup_state_enc_file, self.backup_state_plain_file)
        return state

    def save_cookies(self, cookies: List[Dict[str, Any]], backup: bool) -> None:
        if not cookies:
            return
        self._write_json_encrypted_or_plain(cookies, self.cookies_enc_file, self.cookies_plain_file)
        if backup:
            self._write_json_encrypted_or_plain(cookies, self.backup_cookies_enc_file, self.backup_cookies_plain_file)

    def load_cookies(self, backup: bool) -> List[Dict[str, Any]]:
        pairs = (
            [(self.backup_cookies_enc_file, self.backup_cookies_plain_file), (self.cookies_enc_file, self.cookies_plain_file)]
            if backup
            else [(self.cookies_enc_file, self.cookies_plain_file), (self.backup_cookies_enc_file, self.backup_cookies_plain_file)]
        )
        for enc_p, plain_p in pairs:
            data = self._read_json_encrypted_or_plain(enc_p, plain_p)
            if isinstance(data, list):
                return data
        return []

    def append_history(self, prompt_url: str, prompt_text: str, response_text: str, meta: Dict[str, Any]) -> None:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "client_id": self.profile_name,
                "prompt_url": prompt_url,
                "meta": meta,
                "prompt": prompt_text,
                "response": response_text,
            }
            line = json.dumps(record, ensure_ascii=False)
            if self.crypto is not None:
                token = base64.b64encode(self.crypto.encrypt_text(line)).decode("ascii")
                with self.history_enc_file.open("a", encoding="utf-8") as fp:
                    fp.write(token + "\n")
            else:
                with self.history_plain_file.open("a", encoding="utf-8") as fp:
                    fp.write(line + "\n")
        except Exception:
            pass