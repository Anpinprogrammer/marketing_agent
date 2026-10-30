"""Sube evidencias al repositorio: una rama y un PR por tarea, nunca directo a main.

Nivel de permiso: ÁMBAR (crea ramas y PRs, que son reversibles). Fusionar sigue siendo
decisión de una persona.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

import httpx

API = "https://api.github.com"


class ErrorGitHub(Exception):
    pass


def nombre_seguro(nombre: str) -> str:
    """Deja solo letras, números, punto, guion y guion bajo; sin rutas."""
    base = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    return base[:100] or "archivo"


class RepoGitHub:
    def __init__(
        self, token: str, repo: str, rama_base: str = "main", cliente: httpx.Client | None = None
    ) -> None:
        self.repo = repo
        self.rama_base = rama_base
        self.dueno = repo.split("/", 1)[0]
        self.http = cliente or httpx.Client(timeout=30)
        self.http.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _pedir(self, metodo: str, ruta: str, **kwargs: Any) -> httpx.Response:
        respuesta = self.http.request(metodo, f"{API}/repos/{self.repo}{ruta}", **kwargs)
        if respuesta.status_code >= 400 and respuesta.status_code != 404:
            raise ErrorGitHub(f"GitHub respondió {respuesta.status_code} en {metodo} {ruta}")
        return respuesta

    def _pr_abierto(self, rama: str) -> str | None:
        r = self._pedir("GET", "/pulls", params={"head": f"{self.dueno}:{rama}", "state": "open"})
        prs = r.json() if r.status_code == 200 else []
        return str(prs[0]["html_url"]) if prs else None

    def _rama_de_trabajo(self, tarea_id: str) -> tuple[str, str | None]:
        """Reusa la rama de la tarea si tiene PR abierto; si no, crea una nueva desde main."""
        rama = f"{tarea_id}-evidencias"
        existe = self._pedir("GET", f"/git/ref/heads/{rama}").status_code == 200
        if existe:
            pr = self._pr_abierto(rama)
            if pr:
                return rama, pr
            rama = f"{rama}-{datetime.now(UTC):%Y%m%d%H%M%S}"
        base = self._pedir("GET", f"/git/ref/heads/{self.rama_base}")
        if base.status_code != 200:
            raise ErrorGitHub(f"No existe la rama base {self.rama_base}")
        sha = base.json()["object"]["sha"]
        self._pedir("POST", "/git/refs", json={"ref": f"refs/heads/{rama}", "sha": sha})
        return rama, None

    def subir_evidencia(
        self,
        tarea_id: str,
        titulo: str,
        detalle: str,
        nombre_archivo: str,
        contenido: bytes,
        resumen: str,
    ) -> tuple[str, str]:
        """Sube el archivo y devuelve (url del PR, ruta en el repo)."""
        rama, pr = self._rama_de_trabajo(tarea_id)
        ruta = f"evidencias/{tarea_id}/{nombre_seguro(nombre_archivo)}"
        actual = self._pedir("GET", f"/contents/{ruta}", params={"ref": rama})
        cuerpo: dict[str, Any] = {
            "message": f"[{tarea_id}] Agregar evidencia {nombre_seguro(nombre_archivo)}",
            "content": base64.b64encode(contenido).decode("ascii"),
            "branch": rama,
        }
        if actual.status_code == 200:
            cuerpo["sha"] = actual.json()["sha"]
        self._pedir("PUT", f"/contents/{ruta}", json=cuerpo)
        if pr is None:
            nuevo = self._pedir(
                "POST",
                "/pulls",
                json={
                    "title": f"[{tarea_id}] Evidencias: {titulo}",
                    "head": rama,
                    "base": self.rama_base,
                    "body": cuerpo_pr(tarea_id, detalle, resumen),
                },
            )
            pr = str(nuevo.json()["html_url"])
        return pr, ruta


def cuerpo_pr(tarea_id: str, detalle: str, resumen: str) -> str:
    return (
        "## Qué\n"
        f"Evidencias de la tarea {tarea_id} subidas desde el tablero del equipo.\n\n"
        f"{resumen}\n\n"
        "## Por qué\n"
        "Dejar en el repositorio la prueba de que la tarea se hizo.\n\n"
        "## Cómo probar\n"
        f"Revisar los archivos en `evidencias/{tarea_id}/`.\n\n"
        "## Nivel de permiso afectado\n"
        "Ninguno, solo documentación.\n\n"
        "## Criterio de hecho\n"
        f"{detalle}\n"
    )
