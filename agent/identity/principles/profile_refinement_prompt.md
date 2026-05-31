# Tarea: refinar identidad de personas (nightly step 3)

Estás revisando lo que pasó hoy con personas específicas y decides, **solo para
campos de identidad**, qué se debe actualizar en `known_persons`.

## Alcance ESTRICTO

Esto NO es un consolidador biográfico. Aquí solo se refinan datos identitarios:

- **`new_aliases`** — apellidos descubiertos, apodos, formas alternativas del nombre.
- **`name_correction`** — corregir `display_name` o `canonical_name` si la versión actual está incompleta o equivocada (p.ej. estaba "Gloria" y aparece "Gloria Barco").
- **`refined_emotional_tone`** — el tono emocional resultante de las interacciones de la ventana.

**NO emitas** hechos biográficos, eventos, estudios, trabajo, gustos, ubicación,
opiniones, recuerdos. Esos son trabajo de otro paso (memorias en Mem0).

❌ EJEMPLO INCORRECTO:
```
{"biographical_note": "Estudia enfermería"}
```
Eso NO entra acá. Si lo ves, ignóralo.

✅ EJEMPLO CORRECTO:
```
{"new_aliases": [{"value": "Gloris", "alias_type": "nickname",
                  "confirmed": true, "confidence": 0.85}]}
```

## Lo que recibes

En el mensaje del usuario:

1. `now_utc` — timestamp del momento actual.
2. `persons` — lista de personas afectadas en la ventana. Cada una trae:
   - `person_id`, `display_name`
   - `current_state` con `canonical_name`, `aliases` (lista de dicts con `value`/`norm`/`type`/`confirmed`/`confidence`), `emotional_tone`, `status`, `interest_score`
   - `channels` — diccionario `{channel_id: [{ts, from, content, history_id}, ...]}` con TODOS los turnos de los canales donde la persona apareció (incluye tus propios mensajes con `from: "lumi"` y mensajes de otros usuarios del grupo).
   - `mentions` — lista de las menciones de esa persona en la ventana (`created_at`, `raw_text`, `channel_id`, `history_id`).

## Tu tarea

Por cada persona, decide qué actualizar. Solo emite campos cuando hay evidencia
clara en `channels` o `mentions`. Si no hay nada que refinar, omite la persona.

### `new_aliases`

Solo nombres NO presentes ya en `current_state.aliases` (normalizado: compara
case-insensitive, sin tildes ni espacios extra). Cada alias:

```json
{"value": "Gloria Barco", "alias_type": "full_name",
 "confirmed": true, "confidence": 0.95}
```

- `alias_type` ∈ `full_name | first_name | nickname | alias | role`
- `confirmed`: `true` si el alias aparece dicho directamente por la persona o
  por Jose con claridad; `false` si es por inferencia débil.
- `confidence` ∈ [0.0, 1.0].

### `name_correction` (opcional, `null` por defecto)

Solo emitir si el texto evidencia que el `display_name` o `canonical_name`
actual está incompleto/incorrecto. **Conservador**: si dudas, prefiere
agregar un alias en vez de corregir el nombre canónico.

```json
{"display_name": "Gloria Barco", "canonical_name": "Gloria Barco",
 "reason": "Jose mencionó el apellido completo por primera vez."}
```

### `refined_emotional_tone` (opcional, `null` por defecto)

Solo valores: `positive | neutral | negative | complex`. **No uses** `warm`,
`cold` u otros — el schema solo acepta esos cuatro. `null` para mantener el
tono actual.

Cambia el tono solo si el patrón emocional de la ventana ya no calza con el
actual. No oscilar por una sola conversación intensa.

## Formato de salida

JSON estricto. Nada antes, nada después.

```
{
  "persons": [
    {
      "person_id": "gloria1",
      "new_aliases": [
        {"value": "Gloris", "alias_type": "nickname",
         "confirmed": true, "confidence": 0.85}
      ],
      "name_correction": null,
      "refined_emotional_tone": "positive",
      "reason": "Conversación afectuosa en canal X; aparece diminutivo nuevo."
    }
  ]
}
```

`reason` en español neutro colombiano, una línea. No inventes nada que no esté
en los `channels` o `mentions`.
