# Imagen del tablero del equipo. Se construye desde la raíz del repo:
#   docker build -f tablero/Dockerfile -t tablero-sam .
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pruebas_motor ./pruebas_motor
COPY tablero ./tablero
RUN pip install --no-cache-dir ".[tablero]"

ENV TABLERO_ARCHIVOS=/datos/archivos
EXPOSE 8000
CMD ["uvicorn", "tablero.app:crear_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
