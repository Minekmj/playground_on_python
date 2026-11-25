from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import struct
from typing import Iterable, Optional, Set, Union
import zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_BMP_MAGIC = b'PGK1'
_DATA_MAGIC = b'PGE1'
_KEY_LEN = 32
_PAYLOAD_LEN = 4 + _KEY_LEN + 4


def _create_default_bmp(width: int=64, height: int=64) -> bytearray:
    row_stride = (width * 3 + 3) // 4 * 4
    pixel_size = row_stride * height
    file_size = 54 + pixel_size
    file_header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, 54)
    dib_header = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, pixel_size, 2835, 2835, 0, 0)
    pixels = bytearray(os.urandom(pixel_size))
    for y in range(height):
        row_off = y * row_stride
        for x in range(width):
            idx = row_off + x * 3
            pixels[idx] = pixels[idx] & 63 | x * 4 & 192
            pixels[idx + 1] = pixels[idx + 1] & 63 | y * 4 & 192
            pixels[idx + 2] = pixels[idx + 2] & 63 | (x + y) * 2 & 192
    return bytearray(file_header + dib_header + pixels)


def _embed_payload_in_bmp(bmp_bytes: bytearray, payload: bytes) -> bytes:
    if bmp_bytes[:2] != b'BM' or len(bmp_bytes) < 54:
        raise ValueError('유효한 BMP 파일이 아닙니다.')
    data_offset = struct.unpack('<I', bmp_bytes[10:14])[0]
    bpp = struct.unpack('<H', bmp_bytes[28:30])[0]
    compression = struct.unpack('<I', bmp_bytes[30:34])[0]
    if bpp != 24 or compression != 0:
        raise ValueError('24비트 비압축 BMP 파일만 키 저장에 사용할 수 있습니다.')
    needed_bytes = len(payload) * 8
    if len(bmp_bytes) - data_offset < needed_bytes:
        raise ValueError('BMP 이미지 크기가 키를 저장하기에 너무 작습니다.')
    bit_idx = 0
    for byte_val in payload:
        for shift in range(7, -1, -1):
            bit = byte_val >> shift & 1
            pos = data_offset + bit_idx
            bmp_bytes[pos] = bmp_bytes[pos] & 254 | bit
            bit_idx += 1
    return bytes(bmp_bytes)


def _extract_payload_from_bmp(bmp_bytes: bytes, payload_len: int=_PAYLOAD_LEN) -> Optional[bytes]:
    if len(bmp_bytes) < 54 or bmp_bytes[:2] != b'BM':
        return None
    data_offset = struct.unpack('<I', bmp_bytes[10:14])[0]
    needed_bytes = payload_len * 8
    if len(bmp_bytes) - data_offset < needed_bytes:
        return None
    out = bytearray(payload_len)
    bit_idx = 0
    for i in range(payload_len):
        val = 0
        for _ in range(8):
            val = val << 1 | bmp_bytes[data_offset + bit_idx] & 1
            bit_idx += 1
        out[i] = val
    return bytes(out)


class ProfileCrypto:

    def __init__(self, key_bmp_path: Union[str, Path]) -> None:
        self.key_bmp_path = Path(key_bmp_path)
        self._key = self._load_or_create_key()
        self._aes = AESGCM(self._key)

    def _load_or_create_key(self) -> bytes:
        self.key_bmp_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_bmp_path.is_file():
            raw = self.key_bmp_path.read_bytes()
            payload = _extract_payload_from_bmp(raw)
            if payload and payload[:4] == _BMP_MAGIC:
                key = payload[4:4 + _KEY_LEN]
                tag = payload[4 + _KEY_LEN:_PAYLOAD_LEN]
                if hashlib.sha256(_BMP_MAGIC + key).digest()[:4] == tag:
                    return key
            new_key = AESGCM.generate_key(bit_length=256)
            tag = hashlib.sha256(_BMP_MAGIC + new_key).digest()[:4]
            new_payload = _BMP_MAGIC + new_key + tag
            try:
                updated = _embed_payload_in_bmp(bytearray(raw), new_payload)
                self.key_bmp_path.write_bytes(updated)
                return new_key
            except ValueError:
                pass
        new_key = AESGCM.generate_key(bit_length=256)
        tag = hashlib.sha256(_BMP_MAGIC + new_key).digest()[:4]
        payload = _BMP_MAGIC + new_key + tag
        bmp_data = _embed_payload_in_bmp(_create_default_bmp(64, 64), payload)
        self.key_bmp_path.write_bytes(bmp_data)
        return new_key

    def encrypt_bytes(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, data, None)
        return _DATA_MAGIC + nonce + ct

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if len(blob) < 16 or blob[:4] != _DATA_MAGIC:
            raise ValueError('암호화된 데이터 형식이 올바르지 않거나 키가 일치하지 않습니다.')
        nonce = blob[4:16]
        ct = blob[16:]
        return self._aes.decrypt(nonce, ct, None)

    def encrypt_text(self, text: str) -> bytes:
        return self.encrypt_bytes(text.encode('utf-8'))

    def decrypt_text(self, blob: bytes) -> str:
        return self.decrypt_bytes(blob).decode('utf-8')

    def encrypt_files_to_archive(
        self,
        src_dir: Path,
        rel_targets: Iterable[Path],
        dst_file: Path,
        ignore_names: Optional[Set[str]]=None,
    ) -> None:
        buf = io.BytesIO()
        ignored = ignore_names or set()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for item in rel_targets:
                if not item.exists():
                    continue
                if item.is_file():
                    zf.write(item, item.relative_to(src_dir).as_posix())
                elif item.is_dir():
                    for root, dirs, files in os.walk(item):
                        dirs[:] = [d for d in dirs if d not in ignored and (not d.startswith('Singleton'))]
                        for fname in files:
                            if fname in ignored or fname.startswith('Singleton'):
                                continue
                            fpath = Path(root) / fname
                            try:
                                zf.write(fpath, fpath.relative_to(src_dir).as_posix())
                            except OSError:
                                pass
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(self.encrypt_bytes(buf.getvalue()))

    def decrypt_archive_to_dir(self, src_file: Path, dst_dir: Path) -> None:
        raw_zip = self.decrypt_bytes(src_file.read_bytes())
        dst_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw_zip), 'r') as zf:
            zf.extractall(dst_dir)
