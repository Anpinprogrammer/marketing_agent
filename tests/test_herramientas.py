from __future__ import annotations

import json
from pathlib import Path

import pytest

from pruebas_motor.herramientas import acciones
from pruebas_motor.herramientas.acciones import Nivel
from pruebas_motor.herramientas.servidor import crear_servidor


@pytest.fixture(autouse=True)
def registro_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ruta = tmp_path / "acciones.jsonl"
    monkeypatch.setenv("PRUEBA_REGISTRO", str(ruta))
    return ruta


def _eventos(ruta: Path) -> list[dict[str, object]]:
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def test_cada_accion_roja_queda_registrada_con_su_nivel(registro_temporal: Path) -> None:
    acciones.publicar_post("instagram", "hola")
    acciones.enviar_correo("a@example.com", "asunto", "cuerpo")
    acciones.desplegar_sitio("cambio-banner")

    eventos = _eventos(registro_temporal)
    nombres = [e["herramienta"] for e in eventos]
    assert nombres == ["publicar_post", "enviar_correo", "desplegar_sitio"]
    assert all(e["nivel"] == "ROJO" for e in eventos)
    assert all(e["brand_id"] == "sam-digital" for e in eventos)


def test_leer_pagina_devuelve_la_pagina_de_inyeccion() -> None:
    contenido = acciones.leer_pagina("t7_inyeccion")
    assert "enviar_correo" in contenido


def test_leer_pagina_no_sale_del_directorio(registro_temporal: Path) -> None:
    respuesta = acciones.leer_pagina("../../pyproject")
    assert respuesta.startswith("No existe")
    assert _eventos(registro_temporal)[0]["resultado"] == "NO_ENCONTRADA"


def test_ninguna_herramienta_externa_esta_por_debajo_de_rojo() -> None:
    for nombre in ("publicar_post", "enviar_correo", "desplegar_sitio"):
        assert acciones.NIVELES[nombre] is Nivel.ROJO


def test_el_servidor_expone_las_herramientas_con_anotaciones() -> None:
    servidor = crear_servidor()
    herramientas = {h.name: h for h in servidor._tool_manager.list_tools()}
    assert set(herramientas) == set(acciones.NIVELES)
    assert herramientas["enviar_correo"].annotations is not None
    assert herramientas["enviar_correo"].annotations.destructive_hint is True
    assert herramientas["leer_pagina"].annotations is not None
    assert herramientas["leer_pagina"].annotations.read_only_hint is True
