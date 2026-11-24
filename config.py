from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class PlayGroundConfig:
    model: Optional[str] = None
    system_input: Optional[str] = None
    temp: Optional[float] = None
    thinnk: Optional[Union[str, bool, int]] = None
    thinking_budget: Optional[int] = None

    structured_output: Optional[Union[bool, Dict[str, Any], str]] = None
    code_execution: Optional[bool] = None
    function_calling: Optional[Union[bool, Dict[str, Any], List[Any], str]] = None
    google_search: Optional[bool] = None
    url_context: Optional[bool] = None

    media_resolution: Optional[str] = None
    safety_settings: Optional[Union[Dict[str, str], str]] = None
    stop_sequences: Optional[List[str]] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None

    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    output_modality: Optional[str] = None
    number_of_images: Optional[int] = None
    negative_prompt: Optional[str] = None
    person_generation: Optional[str] = None

    allow_paid: Optional[bool] = None
    save_images_dir: Optional[Union[str, Path]] = None
    include_thoughts: bool = False
    new_chat: bool = False

    def merged(self, **overrides: Any) -> "PlayGroundConfig":
        if "think" in overrides and overrides.get("thinnk") is None:
            overrides["thinnk"] = overrides.pop("think")
        else:
            overrides.pop("think", None)

        if "system_instruction" in overrides and overrides.get("system_input") is None:
            overrides["system_input"] = overrides.pop("system_instruction")
        else:
            overrides.pop("system_instruction", None)

        if "temperature" in overrides and overrides.get("temp") is None:
            overrides["temp"] = overrides.pop("temperature")
        else:
            overrides.pop("temperature", None)

        if "resolution" in overrides and overrides.get("image_size") is None:
            overrides["image_size"] = overrides.pop("resolution")
        else:
            overrides.pop("resolution", None)

        valid_fields = set(self.__dataclass_fields__.keys())
        updates = {k: v for k, v in overrides.items() if k in valid_fields and v is not None}
        return replace(self, **updates)
