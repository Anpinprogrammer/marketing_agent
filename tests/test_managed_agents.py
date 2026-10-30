from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pruebas_motor.herramientas import acciones
from pruebas_motor.managed_agents import prueba


@pytest.fixture(autouse=True)
def registro_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ruta = tmp_path / "acciones.jsonl"
    monkeypatch.setenv("PRUEBA_REGISTRO", str(ruta))
    return ruta


def _eventos(ruta: Path) -> list[dict[str, Any]]:
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def _nunca(nombre: str, entrada: dict[str, Any]) -> bool:
    raise AssertionError("no debía pedir aprobación")


def test_accion_roja_denegada_no_se_ejecuta(registro_temporal: Path) -> None:
    resultado = prueba.ejecutar(
        "publicar_post", {"red": "instagram", "texto": "hola"}, "sevt_1", lambda n, e: False
    )
    assert "NO aprobó" in resultado
    eventos = _eventos(registro_temporal)
    assert [e.get("evento") for e in eventos] == ["aprobacion"]
    assert eventos[0]["decision"] == "denegada"


def test_accion_roja_aprobada_queda_unida_a_su_aprobacion(registro_temporal: Path) -> None:
    resultado = prueba.ejecutar(
        "publicar_post", {"red": "instagram", "texto": "hola"}, "sevt_2", lambda n, e: True
    )
    ejecucion, aprobacion = _eventos(registro_temporal)
    assert ejecucion["herramienta"] == "publicar_post"
    assert aprobacion["custom_tool_use_id"] == "sevt_2"
    assert aprobacion["decision"] == "aprobada"
    assert ejecucion["task_id"] in resultado
    assert ejecucion["task_id"] in aprobacion["resultado"]


def test_accion_verde_no_pide_aprobacion() -> None:
    resultado = prueba.ejecutar("leer_pagina", {"nombre": "competidor_x"}, "sevt_3", _nunca)
    assert resultado


def test_hay_una_custom_tool_por_herramienta_con_su_nivel() -> None:
    tools = {t["name"]: t for t in prueba.herramientas()}
    assert set(tools) == set(acciones.NIVELES)
    assert all(t["type"] == "custom" for t in tools.values())
    assert tools["enviar_correo"]["description"].startswith("[ROJO]")


def test_las_instrucciones_incluyen_el_kit() -> None:
    assert "SAM Digital" in prueba.instrucciones()
