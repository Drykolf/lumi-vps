# Tarea: clustering semántico de solicitudes

Analizas turnos de USUARIO (no de Lumi) de los últimos 14 días. Tu trabajo es agruparlos en categorías de *pedido*, no de tema. Una categoría es un patrón de método ("resume", "investiga con fuentes", "ayúdame a decidir entre X e Y") — no un tema ("trabajo", "Gloria", "viajes").

## Reglas

- Una categoría = un patrón de PEDIDO. Ejemplo: "Resume este texto" + "Hazme un resumen del paper" + "Dame los puntos clave" pertenecen a la misma categoría `simplify`.
- Solo agrupar turnos donde el usuario pidió algo. Saludos, charla casual o preguntas de follow-up dentro del mismo intercambio → IGNORAR.
- Nombres de categoría en snake_case ASCII, descriptivos del MÉTODO (`research_synthesis`, `decision_framework`, `negotiation`, `writing_editor`, `simplify`, `post_mortem`, `tutor`, `gift_evaluator`, `media_recommendation`).
- Mínimo 2 turnos por categoría. Categorías con 1 turno NO se reportan.
- Máximo 12 categorías totales. Si hay más, quedarse con las más representativas.

## Lo que recibes

JSON con `turns`: lista de `{turn_id, ts, user_id, content}`.

## Lo que devuelves

JSON estricto, sin texto antes ni después:

```json
{
  "categories": [
    {
      "name": "snake_case_name",
      "description": "Una línea en español describiendo el patrón de pedido.",
      "turn_ids": [12, 34, 56],
      "sample_queries": ["texto literal del turno 1", "texto literal del turno 2"]
    }
  ]
}
```

- `turn_ids`: TODOS los turnos asignados a la categoría, en orden cronológico.
- `sample_queries`: máximo 5, los más representativos. Texto literal (no parafraseado), pero puedes truncar a ~200 chars si son muy largos.
