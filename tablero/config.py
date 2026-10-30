"""Configuración del tablero, leída solo de variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    url_base_datos: str
    directorio_archivos: Path
    max_bytes_archivo: int
    github_token: str | None
    github_repo: str
    github_rama_base: str
    modelo_guia: str
    esfuerzo_guia: str
    zona_horaria: str

    @property
    def github_activo(self) -> bool:
        return bool(self.github_token)


def cargar() -> Config:
    return Config(
        url_base_datos=os.environ.get("TABLERO_DB_URL", "sqlite:///./tablero.db"),
        directorio_archivos=Path(os.environ.get("TABLERO_ARCHIVOS", "./tablero_archivos")),
        max_bytes_archivo=int(os.environ.get("TABLERO_MAX_MB", "20")) * 1024 * 1024,
        github_token=os.environ.get("GITHUB_TOKEN") or None,
        github_repo=os.environ.get("TABLERO_GITHUB_REPO", "Anpinprogrammer/marketing_agent"),
        github_rama_base=os.environ.get("TABLERO_GITHUB_RAMA_BASE", "main"),
        modelo_guia=os.environ.get("TABLERO_MODELO", "claude-opus-5-5"),
        esfuerzo_guia=os.environ.get("TABLERO_ESFUERZO", "low"),
        zona_horaria=os.environ.get("TABLERO_ZONA", "America/Bogota"),
    )
