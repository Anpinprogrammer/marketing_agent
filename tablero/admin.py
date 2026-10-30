"""Tareas de administración del tablero.

Uso (desde la raíz del repo, con las mismas variables de entorno del servidor):
    python -m tablero.admin cargar-plan
    python -m tablero.admin crear-miembro --nombre "Andrés" --persona andres
    python -m tablero.admin nuevo-codigo --id 1
    python -m tablero.admin desactivar --id 3
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tablero import config
from tablero.auth import hash_codigo, nuevo_codigo
from tablero.db import PERSONAS, Miembro, cargar_plan, crear_motor, fabrica_sesiones

PLAN = Path(__file__).resolve().parent / "datos" / "plan.json"


def _enlace(codigo: str) -> str:
    base = os.environ.get("TABLERO_URL_PUBLICA", "http://localhost:8000")
    return f"{base}/#acceso={codigo}"


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tablero.admin")
    sub = parser.add_subparsers(dest="accion", required=True)
    sub.add_parser("cargar-plan", help="Carga o actualiza semanas y tareas del Plan")
    crear = sub.add_parser("crear-miembro", help="Crea un integrante y muestra su código")
    crear.add_argument("--nombre", required=True)
    crear.add_argument("--persona", required=True, choices=PERSONAS)
    for nombre in ("nuevo-codigo", "desactivar"):
        sub.add_parser(nombre).add_argument("--id", type=int, required=True)
    args = parser.parse_args(argumentos)

    fabrica = fabrica_sesiones(crear_motor(config.cargar().url_base_datos))
    with fabrica() as s:
        if args.accion == "cargar-plan":
            total, nuevas = cargar_plan(s, PLAN)
            print(f"Plan cargado: {total} tareas ({nuevas} nuevas).")
            return
        if args.accion == "crear-miembro":
            codigo = nuevo_codigo()
            m = Miembro(
                nombre=args.nombre[:40], persona=args.persona, token_hash=hash_codigo(codigo)
            )
            s.add(m)
            s.commit()
            print(f"Integrante {m.id} creado. Envíale este enlace por un canal privado:")
            print(_enlace(codigo))
            return
        miembro = s.get(Miembro, args.id)
        if miembro is None:
            raise SystemExit(f"No existe el integrante {args.id}.")
        if args.accion == "desactivar":
            miembro.activo = False
            s.commit()
            print(f"{miembro.nombre} ya no puede entrar.")
            return
        codigo = nuevo_codigo()
        miembro.token_hash = hash_codigo(codigo)
        s.commit()
        print(f"Nuevo enlace de {miembro.nombre} (el anterior deja de servir):")
        print(_enlace(codigo))


if __name__ == "__main__":
    main()
