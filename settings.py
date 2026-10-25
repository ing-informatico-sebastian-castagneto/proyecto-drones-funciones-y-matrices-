"""Carga y valida la configuración compartida de la aplicación."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ServerSettings(_ConfigModel):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    reload: bool


class UploadSettings(_ConfigModel):
    max_bytes: int = Field(ge=1)
    max_image_pixels: int = Field(ge=1)
    max_image_dimension: int = Field(ge=1)
    content_types: list[
        Annotated[str, Field(pattern=r"^image/(png|jpeg|webp)$")]
    ] = Field(min_length=1)


class ProcessingSettings(_ConfigModel):
    min_zoom: float = Field(gt=0)
    max_zoom: float = Field(gt=0)
    zoom_step: float = Field(gt=0)
    default_zoom: float = Field(gt=0)
    min_gamma: float = Field(gt=0)
    max_gamma: float = Field(gt=0)
    gamma_step: float = Field(gt=0)
    default_gamma: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> ProcessingSettings:
        if not self.min_zoom < self.max_zoom:
            raise ValueError("min_zoom debe ser menor que max_zoom.")
        if not self.min_zoom <= self.default_zoom <= self.max_zoom:
            raise ValueError("default_zoom debe estar dentro del rango de zoom.")
        if not self.min_gamma < self.max_gamma:
            raise ValueError("min_gamma debe ser menor que max_gamma.")
        if not self.min_gamma <= self.default_gamma <= self.max_gamma:
            raise ValueError("default_gamma debe estar dentro del rango de gamma.")
        return self


class LiveViewSettings(_ConfigModel):
    enabled: bool
    source: Literal["synthetic"]
    interval_ms: int = Field(ge=500, le=60000)


class AssistantSettings(_ConfigModel):
    mode: Literal["local"]
    count: Literal[2]
    max_source_chars: int = Field(ge=100, le=500000)


class AppSettings(_ConfigModel):
    server: ServerSettings
    upload: UploadSettings
    processing: ProcessingSettings
    live_view: LiveViewSettings
    assistants: AssistantSettings


def load_settings(path: Path = CONFIG_PATH) -> AppSettings:
    """Lee el JSON de configuración y reporta claramente cualquier error."""
    try:
        raw_config = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"No se pudo leer la configuración en {path}.") from error

    try:
        config_data = json.loads(raw_config)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"La configuración en {path} no contiene un JSON válido."
        ) from error

    try:
        return AppSettings.model_validate(config_data)
    except ValidationError as error:
        raise RuntimeError(
            f"La configuración en {path} no cumple el formato esperado: {error}"
        ) from error


settings = load_settings()
