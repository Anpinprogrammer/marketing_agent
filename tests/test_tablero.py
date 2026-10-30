from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tablero import guia
from tablero.admin import PLAN
from tablero.app import crear_app
from tablero.auth import hash_codigo
from tablero.config import Config
from tablero.db import Miembro, cargar_plan, crear_motor, fabrica_sesiones
from tablero.github import ErrorGitHub, RepoGitHub, nombre_seguro


class GuiaFalsa:
    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.llamadas: list[dict[str, Any]] = []
        self.stop_reason = stop_reason

    def create(self, **kwargs: Any) -> Any:
        self.llamadas.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text="Empieza por B07.")],
        )


class RepoFalso:
    def __init__(self, falla: bool = False) -> None:
        self.subidas: list[tuple[str, str, bytes]] = []
        self.falla = falla

    def subir_evidencia(
        self, tarea_id: str, titulo: str, detalle: str, nombre: str, contenido: bytes, resumen: str
    ) -> tuple[str, str]:
        if self.falla:
            raise ErrorGitHub("GitHub respondió 403")
        self.subidas.append((tarea_id, nombre, contenido))
        return "https://github.com/x/y/pull/9", f"evidencias/{tarea_id}/{nombre}"


def _config(tmp_path: Path, github: bool = True) -> Config:
    return Config(
        url_base_datos=f"sqlite:///{tmp_path / 'tablero.db'}",
        directorio_archivos=tmp_path / "archivos",
        max_bytes_archivo=1024,
        github_token="token" if github else None,
        github_repo="dueno/repo",
        github_rama_base="main",
        modelo_guia="claude-opus-5-5",
        esfuerzo_guia="low",
        zona_horaria="America/Bogota",
    )


def _preparar(tmp_path: Path) -> dict[str, str]:
    fabrica = fabrica_sesiones(crear_motor(f"sqlite:///{tmp_path / 'tablero.db'}"))
    with fabrica() as s:
        cargar_plan(s, PLAN)
        s.add(Miembro(nombre="Andrés", persona="andres", token_hash=hash_codigo("cod-andres")))
        s.add(Miembro(nombre="Laura", persona="mercadeo", token_hash=hash_codigo("cod-laura")))
        s.commit()
    return {"andres": "Bearer cod-andres", "laura": "Bearer cod-laura"}


@pytest.fixture
def entorno(tmp_path: Path) -> tuple[TestClient, dict[str, str], GuiaFalsa, RepoFalso]:
    codigos = _preparar(tmp_path)
    falsa, repo = GuiaFalsa(), RepoFalso()
    app = crear_app(_config(tmp_path), mensajes_api=falsa, repo=repo)  # type: ignore[arg-type]
    return TestClient(app), codigos, falsa, repo


def test_sin_codigo_no_entra(entorno: Any) -> None:
    cliente, _, _, _ = entorno
    assert cliente.get("/api/tareas").status_code == 401
    assert cliente.get("/api/tareas", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_plan_cargado_con_117_tareas(entorno: Any) -> None:
    cliente, codigos, _, _ = entorno
    tareas = cliente.get("/api/tareas", headers={"Authorization": codigos["andres"]}).json()
    assert len(tareas) == 117
    titulos = {t["id"]: t["titulo"] for t in tareas}
    assert titulos["B07"] == "Cuentas Google y GitHub del agente"


def test_cargar_plan_otra_vez_conserva_el_avance(tmp_path: Path) -> None:
    _preparar(tmp_path)
    fabrica = fabrica_sesiones(crear_motor(f"sqlite:///{tmp_path / 'tablero.db'}"))
    with fabrica() as s:
        from tablero.db import Tarea

        tarea = s.get(Tarea, "C01")
        assert tarea is not None
        tarea.estado, tarea.nota = "hecha", "listo"
        s.commit()
        total, nuevas = cargar_plan(s, PLAN)
        assert (total, nuevas) == (117, 0)
        tarea = s.get(Tarea, "C01")
        assert tarea is not None and (tarea.estado, tarea.nota) == ("hecha", "listo")


def test_mover_tarea_queda_en_la_bitacora(entorno: Any) -> None:
    cliente, codigos, _, _ = entorno
    cab = {"Authorization": codigos["laura"]}
    r = cliente.patch(
        "/api/tareas/A01", json={"estado": "en_curso", "nota": "Borrador listo"}, headers=cab
    )
    assert r.status_code == 200 and r.json()["estado"] == "en_curso"
    textos = [b["texto"] for b in cliente.get("/api/bitacora", headers=cab).json()]
    assert "Movió A01 a En curso." in textos
    assert any("Borrador listo" in t for t in textos)


def test_estado_invalido(entorno: Any) -> None:
    cliente, codigos, _, _ = entorno
    r = cliente.patch(
        "/api/tareas/A01", json={"estado": "volando"}, headers={"Authorization": codigos["laura"]}
    )
    assert r.status_code == 422


def test_evidencia_sube_al_repo(entorno: Any) -> None:
    cliente, codigos, _, repo = entorno
    r = cliente.post(
        "/api/tareas/B07/evidencias",
        files={"archivos": ("Captura ñ.png", b"png", "image/png")},
        data={"subir_repo": "true"},
        headers={"Authorization": codigos["andres"]},
    )
    assert r.status_code == 200
    ev = r.json()[0]
    assert ev["repo"] == "subida" and ev["prUrl"].endswith("/pull/9")
    assert repo.subidas == [("B07", "Captura-n.png", b"png")]


def test_evidencia_solo_en_el_tablero(entorno: Any) -> None:
    cliente, codigos, _, repo = entorno
    r = cliente.post(
        "/api/tareas/B07/evidencias",
        files={"archivos": ("nota.txt", b"hola", "text/plain")},
        data={"subir_repo": "false"},
        headers={"Authorization": codigos["andres"]},
    )
    assert r.json()[0]["repo"] == "no" and repo.subidas == []
    descarga = cliente.get(
        f"/api/evidencias/{r.json()[0]['id']}/archivo", headers={"Authorization": codigos["laura"]}
    )
    assert descarga.content == b"hola"


def test_error_de_github_queda_marcado(tmp_path: Path) -> None:
    codigos = _preparar(tmp_path)
    app = crear_app(_config(tmp_path), mensajes_api=GuiaFalsa(), repo=RepoFalso(falla=True))  # type: ignore[arg-type]
    r = TestClient(app).post(
        "/api/tareas/B07/evidencias",
        files={"archivos": ("a.txt", b"x", "text/plain")},
        headers={"Authorization": codigos["andres"]},
    )
    assert r.json()[0]["repo"] == "error" and "403" in r.json()[0]["error"]


def test_archivo_muy_grande(entorno: Any) -> None:
    cliente, codigos, _, _ = entorno
    r = cliente.post(
        "/api/tareas/B07/evidencias",
        files={"archivos": ("grande.bin", b"0" * 2000, "application/octet-stream")},
        headers={"Authorization": codigos["andres"]},
    )
    assert r.status_code == 413


def test_solo_quien_subio_puede_borrar(entorno: Any) -> None:
    cliente, codigos, _, _ = entorno
    r = cliente.post(
        "/api/tareas/B07/evidencias",
        files={"archivos": ("a.txt", b"x", "text/plain")},
        data={"subir_repo": "false"},
        headers={"Authorization": codigos["andres"]},
    )
    ev = r.json()[0]["id"]
    assert (
        cliente.delete(
            f"/api/evidencias/{ev}", headers={"Authorization": codigos["laura"]}
        ).status_code
        == 403
    )
    assert (
        cliente.delete(
            f"/api/evidencias/{ev}", headers={"Authorization": codigos["andres"]}
        ).status_code
        == 200
    )


def test_guia_recibe_la_bitacora_del_equipo(entorno: Any) -> None:
    cliente, codigos, falsa, _ = entorno
    cliente.patch(
        "/api/tareas/A01", json={"estado": "hecha"}, headers={"Authorization": codigos["laura"]}
    )
    r = cliente.post(
        "/api/guia",
        json={"mensajes": [{"role": "user", "content": "¿Qué hago hoy?"}]},
        headers={"Authorization": codigos["andres"]},
    )
    assert r.json() == {"texto": "Empieza por B07."}
    llamada = falsa.llamadas[0]
    assert llamada["model"] == "claude-opus-5-5"
    assert llamada["fallbacks"] == "default"
    contexto = json.loads(llamada["system"][1]["text"].split("\n", 1)[1])
    assert contexto["persona"]["nombre"] == "Andrés"
    assert any("A01" in b["texto"] and b["quien"] == "Laura" for b in contexto["bitacoraDelEquipo"])
    assert all(t["id"][0] != "A" for t in contexto["misTareasAbiertas"])


def test_guia_rechazada() -> None:
    r = guia.preguntar(GuiaFalsa("refusal"), "m", "low", {}, [{"role": "user", "content": "x"}])
    assert r.rechazada


def test_conversacion_debe_terminar_en_pregunta() -> None:
    with pytest.raises(ValueError):
        guia.validar_conversacion([{"role": "assistant", "content": "hola"}])
    limpia = guia.validar_conversacion(
        [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}]
    )
    assert limpia == [{"role": "user", "content": "b"}]


def test_nombre_seguro() -> None:
    assert nombre_seguro("../../etc/passwd") == "passwd"
    assert nombre_seguro("Informe final (v2).pdf") == "Informe-final-v2-.pdf"
    assert nombre_seguro("...") == "archivo"


def _github_falso(ramas: set[str], prs: dict[str, str]) -> tuple[httpx.Client, list[str]]:
    registro: list[str] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path.removeprefix("/repos/dueno/repo")
        registro.append(f"{peticion.method} {ruta}")
        if ruta.startswith("/git/ref/heads/"):
            rama = ruta.removeprefix("/git/ref/heads/")
            if rama in ramas:
                return httpx.Response(200, json={"object": {"sha": "abc"}})
            return httpx.Response(404)
        if ruta == "/git/refs":
            ramas.add(json.loads(peticion.content)["ref"].removeprefix("refs/heads/"))
            return httpx.Response(201, json={})
        if ruta == "/pulls" and peticion.method == "GET":
            rama = peticion.url.params["head"].split(":", 1)[1]
            return httpx.Response(200, json=[{"html_url": prs[rama]}] if rama in prs else [])
        if ruta == "/pulls":
            return httpx.Response(201, json={"html_url": "https://github.com/dueno/repo/pull/1"})
        if ruta.startswith("/contents/") and peticion.method == "GET":
            return httpx.Response(404)
        if ruta.startswith("/contents/"):
            cuerpo = json.loads(peticion.content)
            assert base64.b64decode(cuerpo["content"]) == b"datos"
            return httpx.Response(201, json={})
        return httpx.Response(500)

    return httpx.Client(transport=httpx.MockTransport(responder)), registro


def test_github_crea_rama_y_pr() -> None:
    cliente, registro = _github_falso({"main"}, {})
    repo = RepoGitHub("t", "dueno/repo", cliente=cliente)
    pr, ruta = repo.subir_evidencia("B07", "Cuentas", "detalle", "cap.png", b"datos", "r")
    assert pr.endswith("/pull/1") and ruta == "evidencias/B07/cap.png"
    assert "POST /git/refs" in registro and "POST /pulls" in registro


def test_github_reusa_pr_abierto() -> None:
    cliente, registro = _github_falso(
        {"main", "B07-evidencias"}, {"B07-evidencias": "https://pr/5"}
    )
    repo = RepoGitHub("t", "dueno/repo", cliente=cliente)
    pr, _ = repo.subir_evidencia("B07", "Cuentas", "detalle", "cap.png", b"datos", "r")
    assert pr == "https://pr/5"
    assert "POST /git/refs" not in registro and "POST /pulls" not in registro


def test_github_rama_vieja_sin_pr_usa_rama_nueva() -> None:
    ramas = {"main", "B07-evidencias"}
    cliente, _ = _github_falso(ramas, {})
    RepoGitHub("t", "dueno/repo", cliente=cliente).subir_evidencia(
        "B07", "Cuentas", "detalle", "cap.png", b"datos", "r"
    )
    assert any(r.startswith("B07-evidencias-") for r in ramas)
