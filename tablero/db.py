"""Modelos y sesión de base de datos (PostgreSQL en producción, SQLite en local y pruebas)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

PERSONAS = ("andres", "mercadeo", "ux")
ESTADOS = ("pendiente", "en_curso", "revision", "hecha")
ESTADOS_REPO = ("no", "pendiente", "subida", "error")


def ahora() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Miembro(Base):
    __tablename__ = "miembros"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40))
    persona: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    activo: Mapped[bool] = mapped_column(default=True)
    creado: Mapped[datetime] = mapped_column(default=ahora)


class Semana(Base):
    __tablename__ = "semanas"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    orden: Mapped[int]
    corto: Mapped[str] = mapped_column(String(40))
    nombre: Mapped[str] = mapped_column(String(120))
    inicio: Mapped[str | None] = mapped_column(String(10))
    fin: Mapped[str | None] = mapped_column(String(10))
    nota: Mapped[str | None] = mapped_column(String(80))
    incremento: Mapped[str] = mapped_column(Text, default="")
    criterios: Mapped[list[str]] = mapped_column(JSON, default=list)


class Tarea(Base):
    __tablename__ = "tareas"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    titulo: Mapped[str] = mapped_column(String(160))
    detalle: Mapped[str] = mapped_column(Text)
    frente: Mapped[str] = mapped_column(String(80))
    cuando: Mapped[str] = mapped_column(String(80))
    semana: Mapped[str] = mapped_column(ForeignKey("semanas.id"))
    rol: Mapped[str] = mapped_column(String(8))
    apoyo: Mapped[str] = mapped_column(String(40), default="")
    persona: Mapped[str] = mapped_column(String(20))
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")
    nota: Mapped[str] = mapped_column(Text, default="")
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("miembros.id"))
    actualizado_en: Mapped[datetime | None]


class Evidencia(Base):
    __tablename__ = "evidencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    tarea: Mapped[str] = mapped_column(ForeignKey("tareas.id"))
    nombre: Mapped[str] = mapped_column(String(120))
    archivo: Mapped[str] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(100), default="")
    bytes: Mapped[int]
    subida_por: Mapped[int] = mapped_column(ForeignKey("miembros.id"))
    fecha: Mapped[datetime] = mapped_column(default=ahora)
    repo: Mapped[str] = mapped_column(String(12), default="no")
    pr_url: Mapped[str | None] = mapped_column(String(255))
    ruta_repo: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String(255))


class Bitacora(Base):
    """Memoria común del equipo: cada cambio de tarea, evidencia o resumen de la guía."""

    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(default=ahora)
    miembro_id: Mapped[int | None] = mapped_column(ForeignKey("miembros.id"))
    tarea: Mapped[str | None] = mapped_column(String(8))
    tipo: Mapped[str] = mapped_column(String(20))
    texto: Mapped[str] = mapped_column(Text)


def crear_motor(url: str) -> Engine:
    argumentos: dict[str, Any] = {}
    if url.startswith("sqlite"):
        argumentos["connect_args"] = {"check_same_thread": False}
    motor = create_engine(url, **argumentos)
    Base.metadata.create_all(motor)
    return motor


def fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(motor, expire_on_commit=False)


def sesion(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    with fabrica() as s:
        yield s


def cargar_plan(s: Session, ruta: Path) -> tuple[int, int]:
    """Carga semanas y tareas del Plan sin tocar el estado, la nota ni las evidencias existentes."""
    plan = json.loads(ruta.read_text(encoding="utf-8"))
    for datos in plan["semanas"]:
        s.merge(Semana(**datos))
    s.flush()
    nuevas = 0
    for datos in plan["tareas"]:
        tarea = s.get(Tarea, datos["id"])
        if tarea is None:
            s.add(Tarea(**datos))
            nuevas += 1
        else:
            for campo, valor in datos.items():
                setattr(tarea, campo, valor)
    s.commit()
    total = len(s.scalars(select(Tarea.id)).all())
    return total, nuevas
