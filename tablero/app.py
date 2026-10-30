"""API del tablero del equipo y la página que la usa.

Uso local:
    uvicorn tablero.app:crear_app --factory --reload
"""

# Sin "from __future__ import annotations": FastAPI necesita resolver los alias locales BD y Yo.
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, cast
from zoneinfo import ZoneInfo

import anthropic
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tablero import config as configuracion
from tablero import guia
from tablero.auth import hash_codigo
from tablero.db import (
    ESTADOS,
    Bitacora,
    Evidencia,
    Miembro,
    Semana,
    Tarea,
    ahora,
    crear_motor,
    fabrica_sesiones,
)
from tablero.github import ErrorGitHub, RepoGitHub, nombre_seguro

ESTATICOS = Path(__file__).resolve().parent / "static"
NOMBRES_ESTADO = {
    "pendiente": "Por hacer",
    "en_curso": "En curso",
    "revision": "En revisión",
    "hecha": "Hecha",
}


class CambioTarea(BaseModel):
    estado: str | None = None
    nota: str | None = None


class TurnoGuia(BaseModel):
    role: str
    content: str


class PreguntaGuia(BaseModel):
    mensajes: list[TurnoGuia]


def semana_dict(s: Semana) -> dict[str, Any]:
    return {
        "id": s.id,
        "orden": s.orden,
        "corto": s.corto,
        "nombre": s.nombre,
        "inicio": s.inicio,
        "fin": s.fin,
        "nota": s.nota,
        "incremento": s.incremento,
        "criterios": s.criterios,
    }


def tarea_dict(t: Tarea) -> dict[str, Any]:
    return {
        "id": t.id,
        "titulo": t.titulo,
        "detalle": t.detalle,
        "frente": t.frente,
        "cuando": t.cuando,
        "semana": t.semana,
        "rol": t.rol,
        "apoyo": t.apoyo,
        "persona": t.persona,
        "estado": t.estado,
        "nota": t.nota,
        "actualizadoPor": t.actualizado_por,
        "actualizadoEn": t.actualizado_en.isoformat() if t.actualizado_en else None,
    }


def evidencia_dict(e: Evidencia) -> dict[str, Any]:
    return {
        "id": e.id,
        "tarea": e.tarea,
        "nombre": e.nombre,
        "tipo": e.tipo,
        "bytes": e.bytes,
        "por": e.subida_por,
        "fecha": e.fecha.isoformat(),
        "repo": e.repo,
        "prUrl": e.pr_url,
        "rutaRepo": e.ruta_repo,
        "error": e.error,
    }


def crear_app(
    cfg: configuracion.Config | None = None,
    mensajes_api: guia.ClienteMensajes | None = None,
    repo: RepoGitHub | None = None,
) -> FastAPI:
    cfg = cfg or configuracion.cargar()
    fabrica = fabrica_sesiones(crear_motor(cfg.url_base_datos))
    cfg.directorio_archivos.mkdir(parents=True, exist_ok=True)
    if repo is None and cfg.github_token:
        repo = RepoGitHub(cfg.github_token, cfg.github_repo, cfg.github_rama_base)

    app = FastAPI(title="Tablero SAM")

    def obtener_sesion() -> Iterator[Session]:
        with fabrica() as s:
            yield s

    BD = Annotated[Session, Depends(obtener_sesion)]

    def miembro_actual(s: BD, authorization: Annotated[str | None, Header()] = None) -> Miembro:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Falta tu código de acceso.")
        m = s.scalar(
            select(Miembro).where(
                Miembro.token_hash == hash_codigo(authorization[7:]), Miembro.activo
            )
        )
        if m is None:
            raise HTTPException(401, "El código de acceso no es válido.")
        return m

    Yo = Annotated[Miembro, Depends(miembro_actual)]

    def anotar(s: Session, m: Miembro, tipo: str, texto: str, tarea: str | None = None) -> None:
        s.add(Bitacora(miembro_id=m.id, tarea=tarea, tipo=tipo, texto=texto))

    def subir_al_repo(s: Session, m: Miembro, e: Evidencia) -> None:
        if repo is None:
            e.repo, e.error = "error", "La subida al repositorio no está configurada."
            return
        t = s.get(Tarea, e.tarea)
        assert t is not None
        contenido = (cfg.directorio_archivos / e.archivo).read_bytes()
        resumen = f"Subida por {m.nombre}. Estado en el tablero: {NOMBRES_ESTADO[t.estado]}."
        if t.nota:
            resumen += f"\n\nNota de avance: {t.nota}"
        try:
            pr, ruta = repo.subir_evidencia(t.id, t.titulo, t.detalle, e.nombre, contenido, resumen)
        except (ErrorGitHub, OSError) as error:
            e.repo, e.error = "error", str(error)[:250]
            return
        e.repo, e.pr_url, e.ruta_repo, e.error = "subida", pr, ruta, None
        anotar(s, m, "repo", f"{e.nombre} quedó en el repositorio ({pr}).", t.id)

    @app.get("/")
    def pagina() -> FileResponse:
        return FileResponse(ESTATICOS / "index.html")

    @app.get("/api/yo")
    def yo(m: Yo) -> dict[str, Any]:
        return {"id": m.id, "nombre": m.nombre, "persona": m.persona, "repo": repo is not None}

    @app.get("/api/equipo")
    def equipo(s: BD, _: Yo) -> list[dict[str, Any]]:
        miembros = s.scalars(select(Miembro).where(Miembro.activo)).all()
        return [{"id": x.id, "nombre": x.nombre, "persona": x.persona} for x in miembros]

    @app.get("/api/semanas")
    def semanas(s: BD, _: Yo) -> list[dict[str, Any]]:
        return [semana_dict(x) for x in s.scalars(select(Semana).order_by(Semana.orden))]

    @app.get("/api/tareas")
    def tareas(s: BD, _: Yo) -> list[dict[str, Any]]:
        return [tarea_dict(x) for x in s.scalars(select(Tarea).order_by(Tarea.id))]

    @app.patch("/api/tareas/{tarea_id}")
    def cambiar_tarea(tarea_id: str, cambio: CambioTarea, s: BD, m: Yo) -> dict[str, Any]:
        t = s.get(Tarea, tarea_id)
        if t is None:
            raise HTTPException(404, "No existe esa tarea.")
        if cambio.estado is not None and cambio.estado != t.estado:
            if cambio.estado not in ESTADOS:
                raise HTTPException(422, "Estado no válido.")
            t.estado = cambio.estado
            anotar(s, m, "estado", f"Movió {t.id} a {NOMBRES_ESTADO[t.estado]}.", t.id)
        if cambio.nota is not None and cambio.nota != t.nota:
            t.nota = cambio.nota[:4000]
            anotar(s, m, "nota", f"Actualizó la nota de {t.id}: {t.nota[:300]}", t.id)
        t.actualizado_por, t.actualizado_en = m.id, ahora()
        s.commit()
        return tarea_dict(t)

    @app.get("/api/evidencias")
    def evidencias(s: BD, _: Yo) -> list[dict[str, Any]]:
        return [evidencia_dict(x) for x in s.scalars(select(Evidencia).order_by(Evidencia.id))]

    @app.post("/api/tareas/{tarea_id}/evidencias")
    def adjuntar(
        tarea_id: str,
        s: BD,
        m: Yo,
        archivos: Annotated[list[UploadFile], File()],
        subir_repo: Annotated[bool, Form()] = True,
    ) -> list[dict[str, Any]]:
        t = s.get(Tarea, tarea_id)
        if t is None:
            raise HTTPException(404, "No existe esa tarea.")
        creadas = []
        for archivo in archivos:
            contenido = archivo.file.read(cfg.max_bytes_archivo + 1)
            if len(contenido) > cfg.max_bytes_archivo:
                raise HTTPException(413, f"{archivo.filename} pasa del límite de tamaño.")
            nombre = nombre_seguro(archivo.filename or "archivo")
            guardado = f"{tarea_id}/{uuid.uuid4().hex}-{nombre}"
            destino = cfg.directorio_archivos / guardado
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(contenido)
            e = Evidencia(
                tarea=tarea_id,
                nombre=nombre,
                archivo=guardado,
                tipo=archivo.content_type or "",
                bytes=len(contenido),
                subida_por=m.id,
                repo="pendiente" if subir_repo else "no",
            )
            s.add(e)
            anotar(s, m, "evidencia", f"Adjuntó {nombre} a {tarea_id}.", tarea_id)
            s.flush()
            if subir_repo:
                subir_al_repo(s, m, e)
            creadas.append(e)
        s.commit()
        return [evidencia_dict(e) for e in creadas]

    @app.post("/api/evidencias/{evidencia_id}/subir")
    def subir(evidencia_id: int, s: BD, m: Yo) -> dict[str, Any]:
        e = s.get(Evidencia, evidencia_id)
        if e is None:
            raise HTTPException(404, "No existe esa evidencia.")
        if e.repo != "subida":
            subir_al_repo(s, m, e)
            s.commit()
        return evidencia_dict(e)

    @app.get("/api/evidencias/{evidencia_id}/archivo")
    def descargar(evidencia_id: int, s: BD, _: Yo) -> FileResponse:
        e = s.get(Evidencia, evidencia_id)
        if e is None:
            raise HTTPException(404, "No existe esa evidencia.")
        return FileResponse(
            cfg.directorio_archivos / e.archivo, media_type=e.tipo or None, filename=e.nombre
        )

    @app.delete("/api/evidencias/{evidencia_id}")
    def borrar(evidencia_id: int, s: BD, m: Yo) -> dict[str, bool]:
        e = s.get(Evidencia, evidencia_id)
        if e is None:
            raise HTTPException(404, "No existe esa evidencia.")
        if e.subida_por != m.id:
            raise HTTPException(403, "Solo quien subió el archivo puede borrarlo.")
        if e.repo == "subida":
            raise HTTPException(409, "Ya está en el repositorio; se quita desde el PR.")
        (cfg.directorio_archivos / e.archivo).unlink(missing_ok=True)
        anotar(s, m, "evidencia", f"Borró {e.nombre} de {e.tarea}.", e.tarea)
        s.delete(e)
        s.commit()
        return {"borrada": True}

    @app.get("/api/bitacora")
    def bitacora(s: BD, _: Yo, limite: int = 50) -> list[dict[str, Any]]:
        filas = s.scalars(
            select(Bitacora).order_by(Bitacora.id.desc()).limit(min(limite, 200))
        ).all()
        return [
            {
                "fecha": b.fecha.isoformat(),
                "miembro": b.miembro_id,
                "tarea": b.tarea,
                "tipo": b.tipo,
                "texto": b.texto,
            }
            for b in filas
        ]

    @app.post("/api/guia")
    def preguntar_guia(pregunta: PreguntaGuia, s: BD, m: Yo) -> dict[str, str]:
        nonlocal mensajes_api
        if mensajes_api is None:
            mensajes_api = cast(guia.ClienteMensajes, anthropic.Anthropic().beta.messages)
        try:
            conversacion = guia.validar_conversacion([t.model_dump() for t in pregunta.mensajes])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        contexto = contexto_guia(s, m, datetime.now(ZoneInfo(cfg.zona_horaria)).date())
        try:
            r = guia.preguntar(
                mensajes_api, cfg.modelo_guia, cfg.esfuerzo_guia, contexto, conversacion
            )
        except anthropic.RateLimitError as error:
            raise HTTPException(429, "La guía está muy ocupada. Intenta en un minuto.") from error
        except anthropic.APIStatusError as error:
            raise HTTPException(502, "La guía no respondió. Intenta de nuevo.") from error
        except anthropic.APIConnectionError as error:
            raise HTTPException(502, "No hay conexión con la guía.") from error
        return {"texto": r.texto}

    return app


def contexto_guia(s: Session, m: Miembro, hoy: Any) -> dict[str, Any]:
    semanas = [semana_dict(x) for x in s.scalars(select(Semana).order_by(Semana.orden))]
    actual = guia.semana_actual(semanas, hoy)
    nombres = {x.id: x.nombre for x in s.scalars(select(Miembro))}
    todas = s.scalars(select(Tarea).order_by(Tarea.id)).all()
    mias = [t for t in todas if t.persona == m.persona and t.estado != "hecha"]
    resumen: dict[str, dict[str, int]] = {}
    for t in todas:
        clave = f"{t.persona}/{t.semana}"
        resumen.setdefault(clave, {}).setdefault(t.estado, 0)
        resumen[clave][t.estado] += 1
    recientes = s.scalars(select(Bitacora).order_by(Bitacora.id.desc()).limit(40)).all()
    return {
        "hoy": hoy.isoformat(),
        "persona": {"nombre": m.nombre, "rol": m.persona},
        "semanaActual": actual,
        "semanas": [
            {"id": x["id"], "nombre": x["nombre"], "inicio": x["inicio"], "fin": x["fin"]}
            for x in semanas
        ],
        "misTareasAbiertas": [
            {
                "id": t.id,
                "titulo": t.titulo,
                "detalle": t.detalle,
                "semana": t.semana,
                "estado": t.estado,
                "apoyo": t.apoyo,
                "nota": t.nota[:300],
            }
            for t in mias[:80]
        ],
        "avanceDelEquipo": resumen,
        "bitacoraDelEquipo": [
            {
                "fecha": b.fecha.isoformat(timespec="minutes"),
                "quien": nombres.get(b.miembro_id or 0, "sistema"),
                "texto": b.texto[:300],
            }
            for b in reversed(recientes)
        ],
    }
