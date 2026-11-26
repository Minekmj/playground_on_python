from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


_FIELD_ALIASES: Tuple[Tuple[str, str], ...] = (
    ('think', 'thinnk'),
    ('system_instruction', 'system_input'),
    ('temperature', 'temp'),
    ('resolution', 'image_size'),
)


class PlayGroundOptions:
    """PlayGround / PlayGroundConfig에 전달할 고정 옵션 상수 모음.

    예:
        PlayGroundOptions.Thinking.HIGH
        PlayGroundOptions.AspectRatio.RATIO_16_9
        PlayGroundOptions.ImageSize.K2
    """

    class Thinking:
        MINIMAL = 'Minimal'
        LOW = 'Low'
        MEDIUM = 'Medium'
        HIGH = 'High'
        EXTRAHIGH = 'Extra High'
        ON = True
        OFF = False

    class MediaResolution:
        DEFAULT = 'Default'
        LOW = 'Low'
        MEDIUM = 'Medium'
        HIGH = 'High'

    class AspectRatio:
        SQUARE = '1:1'
        RATIO_1_1 = '1:1'
        RATIO_16_9 = '16:9'
        RATIO_9_16 = '9:16'
        RATIO_4_3 = '4:3'
        RATIO_3_4 = '3:4'
        RATIO_3_2 = '3:2'
        RATIO_2_3 = '2:3'
        RATIO_4_5 = '4:5'
        RATIO_5_4 = '5:4'
        RATIO_21_9 = '21:9'

    class ImageSize:
        K0_5 = '0.5K'
        K1 = '1K'
        K2 = '2K'
        K4 = '4K'

    class OutputModality:
        TEXT = 'Text'
        IMAGE = 'Image'
        IMAGE_AND_TEXT = 'Image and text'
        AUDIO = 'Audio'

    class PersonGeneration:
        ALLOW_ALL = 'Allow all'
        ALLOW_ADULT = 'Allow adult'
        DONT_ALLOW = "Don't allow"

    class Safety:
        OFF = 'off'
        NONE = 'none'
        BLOCK_NONE = 'block_none'
        DISABLE = 'disable'

    class ModelKind:
        ALL = 'all'
        TEXT = 'text'
        IMAGE = 'image'
        VIDEO = 'video'
        AUDIO = 'audio'

    class LoginMode:
        AUTO = 'auto'
        FORCE_NEW = True
        EXISTING = False

    class Verbose:
        OFF = False
        BASIC = True
        DEBUG = 'debug'


@dataclass
class PlayGroundConfig:
    """PlayGround / PlayGroundPool 호출 시 공통으로 넘기는 모델·생성 옵션 객체.

    텍스트 옵션: model, system_input, temp, thinnk, thinking_budget, top_p, seed, max_output_tokens, stop_sequences
    도구/안전: google_search, url_context, code_execution, structured_output, function_calling, media_resolution, safety_settings
    이미지 옵션: aspect_ratio, image_size, output_modality, number_of_images, negative_prompt, person_generation, save_images_dir
    동작 제어: allow_paid, include_thoughts, new_chat, raw_mode
    """

    # --- 텍스트 및 추론 옵션 ---
    model: Optional[str] = None
    system_input: Optional[str] = None
    temp: Optional[float] = None
    thinnk: Optional[Union[str, bool, int]] = None
    thinking_budget: Optional[int] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[List[str]] = None

    # --- 도구 및 안전 설정 ---
    structured_output: Optional[Union[bool, Dict[str, Any], str]] = None
    code_execution: Optional[bool] = None
    function_calling: Optional[Union[bool, Dict[str, Any], List[Any], str]] = None
    google_search: Optional[bool] = None
    url_context: Optional[bool] = None
    media_resolution: Optional[str] = None
    safety_settings: Optional[Union[Dict[str, str], str]] = None

    # --- 이미지 생성 옵션 ---
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    output_modality: Optional[str] = None
    number_of_images: Optional[int] = None
    negative_prompt: Optional[str] = None
    person_generation: Optional[str] = None
    save_images_dir: Optional[Union[str, Path]] = None

    # --- 동작 제어 ---
    allow_paid: Optional[bool] = None
    include_thoughts: bool = False
    new_chat: bool = False
    raw_mode: bool = True

    def merged(self, **overrides: Any) -> 'PlayGroundConfig':
        """별칭(think, temperature 등)을 정규화하고 None이 아닌 값만 덮어쓴 새 PlayGroundConfig 반환."""
        normalized = _normalize_aliases(overrides)
        valid_fields = set(self.__dataclass_fields__.keys())
        updates = {
            k: v for k, v in normalized.items()
            if k in valid_fields and v is not None
        }
        return replace(self, **updates)


def _normalize_aliases(overrides: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(overrides)
    for alias, target in _FIELD_ALIASES:
        if alias in data:
            alias_val = data.pop(alias)
            if data.get(target) is None:
                data[target] = alias_val
    return data
