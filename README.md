# marketing_agent

Agente de IA de SAM Digital, operado desde Telegram, que usa el kit de marca, recuerda lo aprendido con revisión humana y nunca actúa hacia afuera sin aprobación.

El plan y los criterios de cada semana están en el documento "Plan por semanas".

## Contenido actual

- `pruebas_motor/`: kit para la prueba de 2 días del motor (tareas C01 y C02).

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy pruebas_motor && pytest
```
