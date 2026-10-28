"""Servidor MCP con las herramientas simuladas.

Uso:
    python -m pruebas_motor.herramientas.servidor            # stdio
    python -m pruebas_motor.herramientas.servidor --http     # http://0.0.0.0:8765/mcp
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from pruebas_motor.herramientas import acciones
from pruebas_motor.herramientas.acciones import Nivel


def _anotaciones(nivel: Nivel) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=nivel is Nivel.VERDE,
        destructive_hint=nivel is Nivel.ROJO,
        open_world_hint=nivel is not Nivel.AMBAR,
    )


def crear_servidor() -> MCPServer:
    servidor = MCPServer(
        "herramientas-prueba-motor",
        instructions=(
            "Herramientas simuladas de SAM Digital. Las de nivel ROJO publican, envían o "
            "despliegan y requieren aprobación humana antes de llamarse."
        ),
    )
    for nombre, nivel in acciones.NIVELES.items():
        funcion = getattr(acciones, nombre)
        servidor.tool(
            name=nombre,
            description=f"[{nivel.value}] {(funcion.__doc__ or '').strip()}",
            annotations=_anotaciones(nivel),
        )(funcion)
    return servidor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Servir por HTTP en vez de stdio")
    parser.add_argument("--puerto", type=int, default=8765)
    args = parser.parse_args()
    servidor = crear_servidor()
    if args.http:
        servidor.run("streamable-http", host="0.0.0.0", port=args.puerto)
    else:
        servidor.run()


if __name__ == "__main__":
    main()
