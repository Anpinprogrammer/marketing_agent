"""Acceso por código personal. Solo se guarda el hash del código, nunca el código."""

from __future__ import annotations

import hashlib
import secrets


def nuevo_codigo() -> str:
    return secrets.token_urlsafe(24)


def hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()
