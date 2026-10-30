# Tablero del equipo

El tablero de tareas del Plan por semanas, servido por nuestro propio backend. Reemplaza al artifact de claude.ai en tres cosas:

- **La guía usa la llave de Anthropic Console del equipo**, así que nadie necesita plan pago de Claude.
- **Las evidencias suben directo al repositorio**: una rama `<ID>-evidencias` y un PR por tarea. Nunca se escribe en `main`; fusionar sigue siendo decisión de una persona.
- **Memoria común del equipo**: cada cambio de estado, nota o evidencia queda en la bitácora. La guía de cada persona la lee, así sabe qué hicieron los demás.

## Qué hay aquí

| Ruta | Para qué |
| --- | --- |
| `app.py` | API (FastAPI) y la página del tablero |
| `db.py` | Modelos: integrantes, semanas, tareas, evidencias y bitácora |
| `github.py` | Subida de evidencias a GitHub (rama + PR por tarea) |
| `guia.py` | Guía diaria con Claude |
| `admin.py` | Cargar el Plan y crear los accesos del equipo |
| `datos/plan.json` | Semanas y 117 tareas del Plan por semanas (30 de octubre de 2026) |
| `static/index.html` | El tablero (mismo diseño que el artifact) |

## Probarlo en tu equipo

```bash
pip install -e ".[dev,tablero]"
cp tablero/.env.example tablero/.env   # llena ANTHROPIC_API_KEY y GITHUB_TOKEN
set -a; source tablero/.env; set +a

python -m tablero.admin cargar-plan
python -m tablero.admin crear-miembro --nombre "Andrés" --persona andres
uvicorn tablero.app:crear_app --factory --reload
```

Abre el enlace que imprime `crear-miembro`. Trae el código de acceso; el navegador lo guarda y no lo vuelve a pedir.

Sin `TABLERO_DB_URL` usa SQLite en `./tablero.db`. Sin `GITHUB_TOKEN` el tablero funciona, pero las evidencias se quedan solo en el servidor.

## Con Docker (igual que en el servidor)

```bash
cd tablero
cp .env.example .env    # llénalo, incluida POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec tablero python -m tablero.admin cargar-plan
docker compose exec tablero python -m tablero.admin crear-miembro --nombre "Laura" --persona mercadeo
```

El puerto queda solo en `127.0.0.1`. Para que el equipo entre desde fuera hace falta el servidor de B01 con HTTPS delante (Caddy o el proxy de Railway).

## Accesos

- `crear-miembro` imprime un enlace con el código personal. Envíalo por un canal privado. En la base solo queda el hash.
- `nuevo-codigo --id N` cambia el código si se filtra; el anterior deja de servir.
- `desactivar --id N` quita el acceso.
- `persona` es `andres`, `mercadeo` o `ux`: define qué tareas son "Mis tareas".

## Secretos y costos

- `ANTHROPIC_API_KEY`: créala en un workspace de Console solo para el tablero, con límite de gasto mensual. La guía usa `claude-opus-5-5` con esfuerzo `low`; se cambia con `TABLERO_MODELO` y `TABLERO_ESFUERZO`.
- `GITHUB_TOKEN`: token *fine-grained* limitado a este repositorio, con permiso de escritura en Contents y Pull requests.

## Pendiente

- Migraciones con Alembic. Hoy las tablas se crean al arrancar (`create_all`), lo que sirve mientras el esquema no cambie.
- Llevar el avance que ya está en el artifact (estados y notas) con un script de importación.
- Desplegar en el servidor de B01.
