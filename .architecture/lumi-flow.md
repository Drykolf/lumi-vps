# Lumi — Flujo completo (estado actual)

## Flujo por turno (POST /v1/chat)

```
POST /v1/chat
  → resolve_inbound_user_id()     # mapea identifier de canal → person_id
  → cycle()
      → get_sleep_stage()          # si duerme → "[tired] Zzz..." y corta
      → attention.classify()       # keyword router: chat / long_task / explicit_save
      → _entities_check()          # LLM LIGHTWEIGHT (~500 tokens): extrae menciones de personas
      → _resolve_entities()        # cruza menciones contra known_persons en core.db
      → build_messages()           # construye el prompt completo (ver abajo)
      → intention.decide_tool()    # LLM LIGHTWEIGHT: ¿necesita tool?
      → [tool execution si aplica]
      → chat_stream() MAIN LLM     # genera respuesta (stream)
      → _finalize_turn()           # guarda ambos turnos + menciones
```

---

## Construcción del prompt (`build_messages`)

El sistema prompt tiene dos partes que se concatenan con `---`:

### Prefijo cacheado (estático, cargado una vez en memoria)

- `agent/identity/lumi_soul.md` — personalidad base
- `agent/identity/attitude.md` — actitud y directivas

### Sufijo dinámico (construido en cada turno, en este orden)

| # | Bloque | Origen | Volatilidad |
|---|--------|--------|-------------|
| 1 | `[Ubicacion]` Colombia/UTC | hardcoded | nunca cambia |
| 2 | `[Modo descanso]` | `get_sleep_stage()` basado en hora COL | estable por horas |
| 3 | `[Entradas del diario]` | tabla `diary` en traces.db (últimas 7) | se actualiza a las 3am |
| 4 | `[Estado interno]` | `lumi_state` en core.db | actualizado cada hora |
| 5 | `[Modo honestidad emocional]` | `negative_load >= 0.70` en lumi_state | por turno si aplica |
| 6 | `[Usuario]` display_name + notas | `known_persons` en core.db | por usuario |
| 7 | `[Personas mencionadas]` / `[Sin perfil]` etc. | entidades resueltas en este turno | por turno |
| 7b | `[Postura]` | interest_score de personas mencionadas | por turno |
| 8 | `[Memoria relevante]` | `search_relevant()` Mem0 por user_id + query, + Mem0 del sujeto | por turno |
| 9 | `[Contexto]` canal + sesión + hora UTC | metadata del request | por turno |

### Historial de conversación inyectado

Después del system prompt, la lista de mensajes se construye así:

1. **Cross-turns** (`[Conversaciones anteriores]`): turnos del mismo `user_id` en otras sesiones, últimas 24h, máx 100 — agrupados por sesión con headers como `--- Sesión 1 (hace 3h) ---`
2. **Session turns**: turnos de la sesión actual, últimas 24h, máx 100 — en formato OpenAI alternante user/assistant
3. **Mensaje actual**: `{user_id}: {message}`

---

## Guardado al final del turno (`_finalize_turn`)

Ocurre síncronamente después de que el LLM termina de responder:

- `save_turn(user_id, "user", message, sid)` → tabla `history` en traces.db
- `save_turn(user_id, "assistant", reply_text, sid)` → tabla `history` en traces.db
- `touch_last_interaction()` → actualiza `last_interaction_at` en `lumi_state`
- Por cada entidad detectada: `add_mention()` → tabla `person_mentions` en core.db, con `resolution_status` y `candidates_json`

**No se guarda nada en Mem0 en tiempo real** — eso ocurre nocturnamente en la quiescencia.

---

## Schedulers (APScheduler, zona COL/UTC-5)

| Job | Cuándo | Qué hace |
|-----|--------|----------|
| `mood_state_tick` | Cada hora (minuto 0) | Si hubo mensajes: LLM evalúa mood con personas involucradas. Si idle ≥ umbral: aplica `idle_decay`. Escribe `lumi_state` + `mood_logs`. |
| `daily_morning` | 7am COL | Regresión parcial de valence/energy/irritation hacia baseline. |
| `nightly_quiescence` | 3am COL | 7 pasos en cadena (ver abajo). |
| `weekly_decay` | Lunes 4am COL | Decay de interest scores de `known_persons`. |

> `rhythm_tick` (tick de 15 min) está desactivado — comentado en heartbeat.py.

---

## Quiescencia nocturna (3am COL, 7 pasos)

Cada paso usa `heartbeat_state.last_success_at` como bookmark: si un paso falla, el próximo día recupera automáticamente el período perdido extendiendo la ventana.

| Paso | Función | Qué hace |
|------|---------|----------|
| 1 | `consolidate_entity_mentions` | Resuelve `person_mentions` con status `pending`; puede crear nuevos `known_persons` o eliminar anónimos. |
| 2 | `consolidate_person_interest` | LLM evalúa deltas de interés por persona y los aplica a `known_persons.interest_score`. |
| 3 | `update_profiles` | Corrige aliases, nombres, `emotional_tone` de personas. |
| 4 | `update_relations` | Detecta relaciones nuevas + inferencia de familia por reglas. |
| 5 | `consolidate_daily_memories` | Extrae hechos atómicos por persona → **Mem0** (Modelo C: `user_id` = `person_id` del sujeto). |
| 6 | `extract_daily_learnings` | Genera entradas del diario en tabla `diary` de traces.db. |
| 7 | `analyze_daily_tasks` | Stub — pendiente de implementar. |

---

## Las tres capas de memoria

| Capa | Backend | Cuándo se escribe | Cuándo se lee |
|------|---------|-------------------|---------------|
| **Episódica** (historial de turnos) | `traces.db` → tabla `history` | Cada turno (`_finalize_turn`) | Cada turno (`build_messages`) |
| **Semántica** (hechos atómicos) | Mem0 + pgvector (port 8100) | Nocturnamente (paso 5) + `explicit_save` inmediato | Cada turno (`search_relevant`) |
| **Social / estado** (personas, mood, menciones) | `core.db` → `known_persons`, `lumi_state`, `person_mentions` | Turno (menciones), hora (mood), noche (perfiles/relaciones) | Cada turno (sufijo dinámico) |
