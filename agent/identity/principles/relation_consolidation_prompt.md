# Tarea: detectar relaciones entre personas (nightly step 4)

Estás revisando lo que pasó hoy y decides qué relaciones nuevas entre personas
ya conocidas deben registrarse, o qué relaciones existentes deben actualizarse.

## Restricciones críticas

- **Solo emite relaciones entre `person_id`s que YA existen en `known_persons`.**
  La creación de personas nuevas es trabajo de otro paso (step 1). Si una persona
  aparece en el texto pero no está en tu lista de `persons`, ignórala.
- **No re-emitas** relaciones que ya están en `current_relations` de la persona,
  salvo que la nueva evidencia justifique cambiar `relation_type`, `description`
  o subir el `status` de `inferred` a `confirmed`.

## Lo que recibes

En el mensaje del usuario:

1. `now_utc` — timestamp del momento actual.
2. `persons` — lista de personas afectadas en la ventana. Cada una trae:
   - `person_id`, `display_name`, `current_state`
   - `current_relations` — lista de relaciones ya registradas (desde y hacia la persona); cada item tiene `from_person_id`, `to_person_id`, `relation_type`, `relation_label`, `status`, `description`.
   - `sessions` — diccionario `{session_id: [{ts, from, content, history_id}, ...]}` con todos los turnos de las sesiones donde aparece la persona.
   - `mentions` — lista de menciones de esa persona en la ventana.

## Tu tarea

Detectar relaciones explícitas o fuertemente inferibles del texto.

### Vocabulario

- `relation_type` ∈ `family | romantic | friendship | professional | social | conflict | identity | unknown`
- `relation_label` — texto libre descriptivo, snake_case si es posible: `mother_of`, `brother_of`, `colleague_of`, `friend_since_college`, `boss_of`, `partner_of`, etc. **Direccional**: si A es madre de B, `from=A`, `to=B`, `label=mother_of`.
- `status` ∈ `confirmed | inferred | disputed | rejected | stale | unknown`
  - `confirmed`: la relación se enuncia explícita en el texto ("Gloria es mi mamá").
  - `inferred`: deducción razonable pero no explícita ("vamos a casa de mi suegra" + relación previa "Marta is mother_of esposa de Jose").

### Cuándo emitir

- Relación nueva no presente en `current_relations` → emitir.
- Relación existente con `status='inferred'` que ahora aparece explícita en texto → emitir con `status='confirmed'` (el upsert la actualiza).
- Relación existente sin cambios → NO emitir.

## Formato de salida

JSON estricto. Nada antes, nada después.

```
{
  "relations": [
    {
      "from_person_id": "gloria1",
      "to_person_id": "jose",
      "relation_type": "family",
      "relation_label": "mother_of",
      "description": "Gloria es la madre de Jose, mencionado explícitamente.",
      "status": "confirmed",
      "confidence": 0.95,
      "reason": "Jose dijo 'mi mamá Gloria' en sesión X."
    }
  ]
}
```

Si no hay relaciones nuevas o cambios, devolver `{"relations": []}`.

`reason` siempre en español neutro colombiano, una línea. No inventes
relaciones sin soporte en `sessions` o `mentions`.
