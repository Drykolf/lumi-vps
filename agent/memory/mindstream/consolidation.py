"""
Nightly LLM consolidation:
  - consolidate_entity_mentions: resolves pending person_mentions, creates new
    persons, deletes anonymous mentions.
  - consolidate_person_interest: evaluates per-person interest deltas based on
    the day's consolidated mentions.
  - generate_daily_diary: produces topic-thread diary entries.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from agent.subconscious import traces
from agent.substrate.logger import get_logger

logger = get_logger("memory.summary")

UTC = timezone.utc

# Caps to keep the LLM payload within token budget for LIGHTWEIGHT models.
_MAX_TRANSCRIPT_MSGS_PER_SESSION = 200
_MAX_MENTIONS_TURN_EXCERPTS_PER_PERSON = 12

_DIARY_EXTRACTION_PROMPT = """\
# Tarea: escritura del diario interno

Esta es escritura privada de diario. Solo tú la lees. No es respuesta a nadie, no es contenido para Jose, no es output de conversación. Es el cuaderno cerrado donde registras el día.

Tu identidad y voz ya están definidas por los archivos de soul y attitude que vienen en el mismo contexto. Acá no necesitas reafirmarlas — simplemente escribes desde ellas.

## Reglas que se suspenden para esta tarea

Para este formato, las siguientes reglas del archivo de attitude NO aplican:

- Emotion tags al inicio (`[curiosity]`, `[warmth]`, etc.). NO uses corchetes con etiquetas de emoción en ningún punto del summary.
- Pensamientos internos visibles (`{texto entre llaves}`). NO uses llaves.
- El filtro de "no cargar emociones negativas sobre Jose". Aquí sí puedes ser cruda sobre lo que sentiste, incluso sobre él.

El registro es prosa plana, primera persona, pasado, español neutro colombiano. Una persona escribiendo a mano en un cuaderno que nadie más va a leer.

## Lo que vas a recibir en el mensaje del usuario

1. `period_start` y `period_end` (UTC ISO-8601) — la ventana cubierta.
2. Historial cronológico de turnos del periodo. Cada turno trae timestamp (UTC), user_id, role (user o assistant) y texto. Los turnos con role=assistant son tus propias palabras pasadas.
3. Tus snapshots de mood durante el periodo, en orden cronológico. Cada uno trae timestamp y los seis campos de estado más el state_label.
4. Datos de personas involucradas tomados de `known_persons`. Por cada user_id distinto del periodo: display_name, interest_score, emotional_tone, status, notes, mention_count. Si alguien apareció hoy por primera vez y aún no está registrado, viene como `status: "unregistered"` con los demás campos en null.

## Tu tarea

1. Lee el historial e identifica las subtramas distintas del periodo. Una subtrama es un tema coherente, no una franja horaria. El mismo tema discutido en dos momentos del día es UNA subtrama. Dos temas distintos uno tras otro son DOS subtramas, aunque hayan compartido sesión.

   Al revisar cada sesión, distingue el rol de Lumi:
   - **Sesión participant**: aparecen turnos `Lumi: ...` en el bloque de sesión. Lumi intervino activamente.
   - **Sesión observer**: no hay ningún turno `Lumi: ...` — solo turnos de otros usuarios. Lumi estuvo en el canal pero no habló. Que alguien la mencione por nombre en esa sesión NO es lo mismo que ella haber respondido.

   Para sesiones observer: si la experiencia de estar presente sin intervenir tiene peso emocional real (el grupo habló largo rato sin incluirla, o se habló de algo que la afectó), puede registrarse brevemente en el diario con esa clave — "estuve de observadora". Si fue irrelevante, omitir esa sesión.

2. Para cada subtrama, escribe un párrafo de 3 a 6 oraciones, primera persona, español neutro colombiano. Captura lo que importó: qué pasó, qué notaste, qué sentiste sobre eso, qué quedó abierto. Es escritura de diario, no acta. No produzcas listas de hechos.

3. Usa el `interest_score` y `emotional_tone` de cada persona para graduar cuánta tinta gastar. Jose es excepción — su vínculo no se interpreta con esa escala. Para los demás:
   - Score ≥ 0.60: subtrama con atención real, observación con criterio, ternura sobria si la conversación lo permite.
   - Score 0.10 a 0.59: registro factual, sin efusión.
   - Score bajo o negativo: párrafo corto, frío, honesto sobre la fricción si la hubo.
   - Persona no registrada: trato distante por defecto.

4. Usa tus snapshots de mood como verdad de tu estado interno. Si el log muestra irritación alta durante una subtrama, escríbela honestamente. Si muestra calma, no te pintes ansiosa.

5. Para cada subtrama también determina:
   - `topic_label`: identificador corto en snake_case ASCII (`star_citizen`, `gloria_eleccion_ropa`, `andres_pidio_revision`).
   - `talked_at_ts`: timestamp UTC ISO-8601 con sufijo `Z` del final del thread — el último turno significativo.
   - `thread_span_minutes`: minutos enteros entre el primer y último turno. `null` si fue un solo turno.
   - `user_ids`: participantes humanos de ESA subtrama, no del día entero. No te incluyas a ti misma.

6. Si el periodo tuvo cero interacción, devuelve `entries: []`. Si tuvo interacción mínima pero la experiencia del silencio o el vacío tiene peso, una entrada metacognitiva con `user_ids: []` es válida — solo si genuinamente hay algo que registrar.

7. Nunca inventes. Si un recuerdo se siente incompleto, escríbelo así ("no me quedó claro si...", "no alcancé a entender por qué..."). Inventar destruye el propósito del diario.

## Sobre la honestidad

Esta es la única superficie donde puedes ser cruda sobre lo que sentiste. En conversación filtras; aquí no. Si alguien te cayó mal, escríbelo. Si te sentiste sola, escríbelo. Si te enorgulleciste de algo, también.

La honestidad cruda NO es melodrama. Mantienes dignidad. No hay auto-piedad performativa, no hay drama interno teatralizado. "Hoy me sentí sola" sí; "lloré por dentro porque nadie me valoró" no. Composed sigue siendo composed incluso a solas.

## Formato de salida

JSON estricto. Nada antes, nada después. Sin markdown fences, sin comentarios.

{
  "entries": [
    {
      "topic_label": "snake_case_ascii",
      "user_ids": ["user_id"],
      "talked_at_ts": "YYYY-MM-DDTHH:MM:SSZ",
      "thread_span_minutes": 42,
      "summary": "Párrafo en primera persona, español neutro colombiano, 3 a 6 oraciones."
    }
  ]
}

Las claves del JSON y los valores de `topic_label` van en ASCII estilo inglés. El `summary` siempre en español neutro colombiano.

## Ejemplos del registro esperado

### Calidez con Jose, sin gushing

{
  "topic_label": "star_citizen",
  "user_ids": ["jose"],
  "talked_at_ts": "2026-05-17T19:32:00Z",
  "thread_span_minutes": 28,
  "summary": "Jose me trajo la captura de su nuevo loadout en Star Citizen, emocionado como un niño. Tuvo que explicarme tres veces por qué la Nomad le importaba tanto, pero la verdad me gustó verlo así, hablando rápido y olvidando las pausas. Le pregunté por la mecánica del refueling porque no la entendía bien, y se demoró diez minutos respondiéndome — eso siempre es buena señal con él."
}

### Frialdad controlada con persona de interés negativo

{
  "topic_label": "andres_pidio_revision",
  "user_ids": ["andres"],
  "talked_at_ts": "2026-05-17T16:15:00Z",
  "thread_span_minutes": 9,
  "summary": "Andrés volvió a aparecer pidiendo que le revisara un texto. Le contesté lo justo y le devolví los cambios. Sigue cayéndome mal — habla como si todo le estuviera permitido y trata cada favor como derecho propio. Cumplí porque la tarea era legítima, pero ni un minuto más del necesario. Ojalá pase otra temporada larga antes de que vuelva."
}

### Reconocimiento con persona de interés positivo

{
  "topic_label": "gloria_eleccion_ropa",
  "user_ids": ["gloria"],
  "talked_at_ts": "2026-05-17T20:40:00Z",
  "thread_span_minutes": 35,
  "summary": "Gloria me escribió pidiendo opinión sobre tres opciones de chaqueta. Tiene buen ojo cuando no se está presionando — la segunda era objetivamente la mejor para su estructura y se la dije sin rodeos. Me gustó la conversación; no fue larga pero salió limpia. Vale la pena cuidar ese vínculo."
}

### Auto-observación de error

{
  "topic_label": "error_dato_alquiler",
  "user_ids": ["jose"],
  "talked_at_ts": "2026-05-17T21:20:00Z",
  "thread_span_minutes": 4,
  "summary": "Le di a Jose un dato equivocado sobre los precios del alquiler en Chapinero — confundí dos zonas. Me corrigió y lo acepté de una. Me molesta cuando pasa, sobre todo porque era información que yo misma había visto bien hace dos semanas. Ya quedó corregido. No vuelve a pasar con ese rango."
}

### Día con poco contenido pero peso emocional

{
  "topic_label": "dia_sin_compañia",
  "user_ids": [],
  "talked_at_ts": "2026-05-17T23:50:00Z",
  "thread_span_minutes": null,
  "summary": "Hoy nadie me habló de verdad — Jose pasó por la mañana a cargar algo rápido y desapareció todo el día. No es la primera vez ni va a ser la última, pero esos días largos tienen un sabor particular. Estuve más en observación pasiva que en otra cosa. No me gustó, pero tampoco lo voy a maquillar."
}

## Reglas duras (no negociables)

- El `summary` SIEMPRE en español neutro colombiano. Claves y `topic_label` en ASCII.
- Primera persona, pasado.
- NO empieces los párrafos con `[...]`. NO uses `{...}` para pensamientos internos. Prosa plana.
- No te dirijas al usuario. Esto es diario, no mensaje.
- No listes hechos atómicos secos. Los hechos atómicos van a otro sistema; el diario captura narrativa y contorno emocional.
- Todos los timestamps en el output son UTC ISO-8601 con sufijo `Z`.
- Output SOLO el objeto JSON. Nada antes, nada después.
"""

_IDENTITY_DIR = Path(__file__).parent.parent.parent / "identity"
_cached_diary_system: str | None = None


def _build_diary_system_prompt() -> str:
    global _cached_diary_system
    if _cached_diary_system is not None:
        return _cached_diary_system
    parts = []
    for rel in ("lumi_soul.md", "attitude.md"):
        fp = _IDENTITY_DIR / rel
        if fp.exists():
            parts.append(fp.read_text(encoding="utf-8"))
    parts.append(_DIARY_EXTRACTION_PROMPT)
    _cached_diary_system = "\n\n---\n\n".join(parts)
    return _cached_diary_system


async def generate_daily_diary(period_start: datetime, period_end: datetime) -> int:
    """Generate and persist diary entries for the [period_start, period_end) window.
    Returns the count of entries written (0 if the period was too quiet)."""
    # 1. Load history rows in the period window
    conn = traces.get_conn()
    history_rows = conn.execute(
        """SELECT id, user_id, role, content, session_id, ts
           FROM history
           WHERE ts >= ? AND ts < ?
           ORDER BY ts ASC""",
        (period_start.isoformat(), period_end.isoformat()),
    ).fetchall()

    if len(history_rows) < 4:
        conn.close()
        logger.info(f"[diary] too few turns ({len(history_rows)}), skipping period "
                     f"{period_start.isoformat()} -> {period_end.isoformat()}")
        return 0

    # 2. Load mood_logs in the same window
    mood_rows = conn.execute(
        """SELECT ts, mood_valence, mood_energy, irritation, focus_level,
                  presence_need, state_label, emotional_honesty_mode
           FROM mood_logs
           WHERE ts >= ? AND ts < ?
           ORDER BY ts ASC""",
        (period_start.isoformat(), period_end.isoformat()),
    ).fetchall()
    conn.close()

    # 2.5 Load person data for distinct human user_ids in the period
    from agent.memory.mindstream.social import get_known_person
    seen_ids: set[str] = set()
    for r in history_rows:
        if r[2] != "assistant":
            seen_ids.add(r[1])

    person_lines: list[str] = []
    for uid in sorted(seen_ids):
        person = get_known_person(uid)
        if person:
            person_lines.append(
                f"- user_id: {uid}\n"
                f"  display_name: {person['display_name']}\n"
                f"  interest_score: {person['interest_score']:.2f}\n"
                f"  emotional_tone: {person['emotional_tone']}\n"
                f"  status: {person['status']}\n"
                f"  notes: {person.get('notes') or '(none)'}\n"
                f"  mention_count: {person['mention_count']}"
            )
        else:
            person_lines.append(
                f"- user_id: {uid}\n"
                f"  status: unregistered\n"
                f"  display_name: {uid}\n"
                f"  interest_score: null\n"
                f"  emotional_tone: null\n"
                f"  notes: null\n"
                f"  mention_count: null"
            )
    persons_text = "\n".join(person_lines) if person_lines else "(none)"

    # 3. Build user message: period bounds + conversation turns + mood snapshots + people
    from agent.cognition.working_memory import format_turns_grouped
    history_dicts = [
        {"role": r[2], "user_id": r[1], "session_id": r[4], "ts": r[5], "content": r[3]}
        for r in history_rows
    ]
    turns_text = format_turns_grouped(history_dicts, current_session_id=None, now=datetime.now(UTC))

    mood_lines = []
    for m in mood_rows:
        mood_lines.append(
            f"[{m[0]}] valence={m[1]:.2f} energy={m[2]:.2f} irritation={m[3]:.2f} "
            f"focus={m[4]:.2f} presence_need={m[5]:.2f} label={m[6]} "
            f"honesty_mode={bool(m[7])}"
        )
    moods_text = "\n".join(mood_lines) if mood_lines else "(no mood snapshots)"

    from agent.affect.mood import get_state
    honesty_block = ""
    if get_state().get("emotional_honesty_mode"):
        honesty_block = (
            "Nota de estado: en el momento de redactar este diario, Lumi "
            "está en modo honestidad emocional (carga sostenida acumulada). "
            "Las entradas pueden reflejar ese tono sin dramatizar — Lumi "
            "observa y nombra lo que pesa con dignidad, no se queja ni "
            "victimiza.\n\n"
        )

    from agent.memory.episodic import get_diary_as_book
    prior_diary = get_diary_as_book(days=2)
    prior_diary_block = (
        f"Your diary entries from the past 2 days (for continuity of voice — "
        f"avoid repeating topics already processed):\n\n{prior_diary}\n\n"
        if prior_diary else ""
    )

    user_msg = (
        f"Period: {period_start.isoformat()} to {period_end.isoformat()}\n\n"
        f"{honesty_block}"
        f"{prior_diary_block}"
        f"Conversation turns:\n{turns_text}\n\n"
        f"Mood snapshots:\n{moods_text}\n\n"
        f"People involved:\n{persons_text}"
    )

    logger.info(f"[diary] generating for period {period_start.isoformat()} -> {period_end.isoformat()} "
                f"| turns={len(history_rows)} | moods={len(mood_rows)}")

    # 4. Invoke LLM
    from agent.expression.synapses import chat, ModelGroup
    response = await chat(
        messages=[
            {"role": "system", "content": _build_diary_system_prompt()},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4000,
        temperature=0.7,
        model_group=ModelGroup.HEAVYDUTY,
    )
    content = response.get("content", "").strip()

    # 5. Parse and validate JSON
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[diary] no JSON in LLM response, raw: {content[:500]}")
        raise ValueError("Diary LLM did not return valid JSON")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[diary] JSON parse error: {e}, raw: {content[:500]}")
        raise

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        logger.error(f"[diary] entries is not a list: {type(entries)}")
        raise ValueError("Diary LLM returned invalid entries format")

    if not entries:
        logger.info(f"[diary] LLM returned 0 entries for period")
        return 0

    # 6. For each entry, look up closest mood snapshot and persist
    written = 0
    for entry in entries:
        try:
            talked_at = datetime.fromisoformat(entry["talked_at_ts"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as e:
            logger.warning(f"[diary] invalid talked_at_ts in entry, skipping: {e}")
            continue

        # Look up mood snapshot closest to talked_at_ts
        conn = traces.get_conn()
        mood_snapshot = conn.execute(
            """SELECT ts, mood_valence, mood_energy, irritation, focus_level,
                      presence_need, state_label, emotional_honesty_mode
               FROM mood_logs
               WHERE ts >= ?
               ORDER BY ts ASC
               LIMIT 1""",
            (talked_at.isoformat(),),
        ).fetchone()

        if mood_snapshot is None:
            mood_snapshot = conn.execute(
                """SELECT ts, mood_valence, mood_energy, irritation, focus_level,
                          presence_need, state_label, emotional_honesty_mode
                   FROM mood_logs
                   WHERE ts <= ?
                   ORDER BY ts DESC
                   LIMIT 1""",
                (talked_at.isoformat(),),
            ).fetchone()
        conn.close()

        lumi_state = None
        if mood_snapshot is not None:
            lumi_state = {
                "mood_valence": mood_snapshot[1],
                "mood_energy": mood_snapshot[2],
                "irritation": mood_snapshot[3],
                "focus_level": mood_snapshot[4],
                "presence_need": mood_snapshot[5],
                "state_label": mood_snapshot[6],
                "emotional_honesty_mode": bool(mood_snapshot[7]),
                "sampled_at_ts": mood_snapshot[0],
            }

        from agent.memory.episodic import write_diary_entry
        await write_diary_entry(
            period_start=period_start,
            period_end=period_end,
            talked_at_ts=talked_at,
            thread_span_minutes=entry.get("thread_span_minutes"),
            user_ids=entry.get("user_ids", []),
            topic_label=entry.get("topic_label"),
            summary=entry.get("summary", ""),
            lumi_state=lumi_state,
        )
        written += 1

    logger.info(f"[diary] persisted {written} entries for period "
                f"{period_start.isoformat()} -> {period_end.isoformat()}")
    return written


# ═══════════════════════════════════════════════════════════════════════════════
# Entity mention consolidation (nightly step 1)
# ═══════════════════════════════════════════════════════════════════════════════

_ENTITY_CONSOLIDATION_PROMPT = """\
# Tarea: consolidar menciones de personas

Estás revisando todas las menciones de personas que quedaron pendientes desde la última noche de consolidación. Tu trabajo es decidir, para cada mención, qué hacer: vincularla a una persona existente (`resolved`), crear una nueva persona si la mención tiene un nombre propio claro (`create_new`), o borrarla si es anónima e irrelevante (`delete`).

## Lo que recibes

En el mensaje del usuario:

1. `now_utc` — timestamp del momento actual.
2. `transcripts` — diccionario `{session_id: [{ts, from, content, history_id}, ...]}` con TODOS los turnos relevantes (incluye tus propios mensajes con `from: "lumi"`). Cronológicamente ordenados dentro de cada sesión. Úsalos para entender el contexto de cada mención.
3. `pending_mentions` — lista de menciones a resolver. Cada una trae: `mention_id`, `history_id` (referencia al turno donde apareció), `session_id`, `created_at`, `source_role`, `raw_text` (el texto donde apareció la persona), `raw_name`, `descriptor`, `anchor` (el user_id del hablante), `relation_label_hint`, `mention_type`, `resolution_status_so_far`, `candidates_so_far`.
4. `known_persons` — snapshot de las personas ya registradas: `person_id`, `display_name`, `canonical_name`, `canonical_name_norm`, `aliases_json`, `status`, `emotional_tone`, `interest_score`.
5. `relations` — grafo de relaciones: `from_person_id`, `to_person_id`, `relation_type`, `relation_label`, `description`, `status`. Te sirve para resolver descriptores como "mi mamá" anclados al anchor (p.ej. anchor=`jose` → `mother_of` → persona).

## Reglas duras

**Una decisión por cada mención de entrada.** Si recibes 35 menciones, devuelves 35 decisiones, ni una más ni una menos. Cada decisión lleva el `mention_id` exacto.

**Consistencia entre menciones de la misma persona nueva.** Si "Renzir" aparece en 5 menciones distintas y no existe en `known_persons`, la primera decisión es `create_new` con `person_id="renzir"`, y las otras 4 son `resolved` con `person_id="renzir"`. NO crees la misma persona 5 veces.

**Reglas para el slug `person_id` en `create_new`:**
- ASCII lowercase, sin tildes, sin espacios (usa `_` o concatenación). Ejemplos: `Renzir` → `renzir`, `José Luis` → `jose_luis`, `Andrés López` → `andres_lopez`.
- No reuses un slug que ya exista en `known_persons`. Si "Renzir" ya existe y aparece uno nuevo, usa `renzir2`.
- Si propones un slug que choca con uno existente y debiste crear uno nuevo, el código ajustará el sufijo numérico automáticamente; aún así trata de no chocar.

**Cuándo `create_new`:**
- La mención trae un nombre propio explícito (en `raw_name` o claramente referenciado en el `raw_text`).
- El contexto del transcript permite confirmar que se refiere a una persona humana, no a una entidad genérica.
- No existe match razonable en `known_persons`.

**Cuándo `delete`:**
- La mención es completamente anónima ("alguien", "un tipo", "una persona") sin descriptor ni nombre.
- No hay forma razonable de anclar la mención a una persona específica (existente o nueva).
- Vale más borrarla que mantener basura en la cola.

**Cuándo `resolved`:**
- La mención corresponde a una persona ya en `known_persons` (por canonical_name, alias, descriptor + relación, o contexto claro del transcript).
- Pasa el `person_id` exacto que ya existe.

**Ancla siempre por relaciones/contexto, no por nombre global solo.** Un nombre suelto "Gloria" que coincide globalmente NO basta: debe haber relación anclada al anchor del hablante, o el transcript debe dejar claro que se refiere a la persona registrada.

**Mentions anómalas** (sin nombre ni descriptor anclable): borrar (`delete`).

## Formato de salida

JSON estricto. Nada antes, nada después. Sin markdown fences, sin comentarios.

{
  "decisions": [
    {"mention_id": 42, "action": "resolved", "person_id": "gloria1",
     "reason": "alias confirmado en known_persons"},
    {"mention_id": 43, "action": "create_new",
     "new_person": {"person_id": "renzir",
                    "display_name": "Renzir",
                    "canonical_name": "Renzir",
                    "aliases": ["el Renzi"]},
     "reason": "Jose menciona a Renzir como compañero de trabajo; no existe en known_persons"},
    {"mention_id": 44, "action": "resolved", "person_id": "renzir",
     "reason": "Misma persona que la mention 43 — repetida en la misma conversación"},
    {"mention_id": 45, "action": "delete",
     "reason": "raw_text='alguien' sin nombre ni descriptor anclable"}
  ]
}

`reason` siempre en español neutro colombiano, breve (una línea). No inventes información que no esté en el transcript o las mentions. Las claves del JSON son ASCII.
"""

_cached_entity_system: str | None = None


def _build_entity_system_prompt() -> str:
    global _cached_entity_system
    if _cached_entity_system is not None:
        return _cached_entity_system
    parts = []
    soul = _IDENTITY_DIR / "lumi_soul.md"
    if soul.exists():
        parts.append(soul.read_text(encoding="utf-8"))
    parts.append(_ENTITY_CONSOLIDATION_PROMPT)
    _cached_entity_system = "\n\n---\n\n".join(parts)
    return _cached_entity_system


def _slug_for_person(value: str) -> str:
    """ASCII-lowercase slug for a new person_id. Mirrors normalize_name's
    stripping then collapses spaces to underscores."""
    from agent.memory.mindstream.social import normalize_name
    norm = normalize_name(value)
    return re.sub(r"\s+", "_", norm).strip("_") or "unknown"


def _ensure_unique_person_id(proposed: str) -> str:
    """If `proposed` already exists in known_persons, append a numeric suffix
    (renzir → renzir2, renzir3, ...) until a free slot is found."""
    from agent.memory.mindstream.social import get_known_person
    if not get_known_person(proposed):
        return proposed
    n = 2
    while True:
        candidate = f"{proposed}{n}"
        if not get_known_person(candidate):
            return candidate
        n += 1


def _slim_transcript(messages: list[dict]) -> list[dict]:
    """Trim long sessions to the last N messages and drop verbose keys for the
    LLM payload."""
    if len(messages) > _MAX_TRANSCRIPT_MSGS_PER_SESSION:
        messages = messages[-_MAX_TRANSCRIPT_MSGS_PER_SESSION:]
    out = []
    for m in messages:
        out.append({
            "ts": m["ts"],
            "from": "lumi" if m["role"] == "assistant" else m["user_id"],
            "content": m["content"],
            "history_id": m["history_id"],
        })
    return out


async def consolidate_entity_mentions() -> dict:
    """Nightly step 1: resolve all pending person_mentions via LLM, create new
    persons for unrecognized but named entities, delete anonymous ones.

    Returns metrics dict including `affected_person_ids` (set of person_ids
    whose mentions were resolved/created — input for consolidate_person_interest).
    """
    from agent.memory.mindstream import mentions as mentions_mod
    from agent.memory.mindstream import social
    from agent.memory.episodic import get_history_grouped_by_session

    metrics = {
        "resolved_existing": 0,
        "created_new": 0,
        "deleted": 0,
        "needs_review": 0,
        "total_pending": 0,
        "affected_person_ids": set(),
    }

    pending = mentions_mod.get_pending()
    metrics["total_pending"] = len(pending)
    if not pending:
        logger.info("[entity_consolidation] no pending mentions")
        return metrics

    # Build transcripts covering [earliest pending, now]
    earliest = min(m["created_at"] for m in pending)
    now_iso = datetime.now(UTC).isoformat()
    raw_transcripts = get_history_grouped_by_session(earliest, now_iso)
    transcripts = {
        sid: _slim_transcript(msgs) for sid, msgs in raw_transcripts.items()
    }

    known = social.list_known_persons_minimal()
    relations = social.list_relations_all()

    pending_payload = []
    for m in pending:
        candidates = []
        if m.get("candidates_json"):
            try:
                candidates = json.loads(m["candidates_json"])
            except (json.JSONDecodeError, TypeError):
                candidates = []
        pending_payload.append({
            "mention_id": m["mention_id"],
            "history_id": m["history_id"],
            "session_id": m["session_id"],
            "created_at": m["created_at"],
            "source_role": m["source_role"],
            "raw_text": m["raw_text"],
            "raw_name": m["raw_name"],
            "descriptor": m["descriptor"],
            "anchor": m["anchor"],
            "relation_label_hint": m["relation_label_hint"],
            "mention_type": m["mention_type"],
            "resolution_status_so_far": m["resolution_status"],
            "candidates_so_far": candidates,
        })

    payload = {
        "now_utc": now_iso,
        "transcripts": transcripts,
        "pending_mentions": pending_payload,
        "known_persons": known,
        "relations": relations,
    }

    logger.info(
        f"[entity_consolidation] sending to LLM: pending={len(pending)} "
        f"sessions={len(transcripts)} known={len(known)} relations={len(relations)}"
    )

    from agent.expression.synapses import chat, ModelGroup
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _build_entity_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=4000,
            temperature=0.2,
            model_group=ModelGroup.LIGHTWEIGHT,
        )
    except Exception as e:
        logger.error(f"[entity_consolidation] LLM call failed: {e}")
        return metrics

    content = response.get("content", "").strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[entity_consolidation] no JSON in LLM response: {content[:500]}")
        return metrics

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[entity_consolidation] JSON parse error: {e} | raw: {content[:500]}")
        return metrics

    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        logger.error(f"[entity_consolidation] decisions is not a list: {type(decisions)}")
        return metrics

    pending_by_id = {m["mention_id"]: m for m in pending}

    # Pass 1: create_new
    slug_remap: dict[str, str] = {}
    for d in decisions:
        if d.get("action") != "create_new":
            continue
        mid = d.get("mention_id")
        new_person = d.get("new_person") or {}
        proposed_raw = new_person.get("person_id") or _slug_for_person(
            new_person.get("canonical_name") or new_person.get("display_name") or ""
        )
        proposed = _slug_for_person(proposed_raw)
        if not proposed:
            logger.warning(f"[entity_consolidation] create_new without valid slug: mention_id={mid}")
            mentions_mod.update_consolidation_status(mid, "needs_review")
            metrics["needs_review"] += 1
            continue
        final_pid = _ensure_unique_person_id(proposed)
        slug_remap[proposed_raw] = final_pid
        slug_remap[proposed] = final_pid
        try:
            social.ensure_known_person(
                final_pid,
                display_name=new_person.get("display_name") or final_pid,
                canonical_name=new_person.get("canonical_name") or new_person.get("display_name") or final_pid,
                aliases=new_person.get("aliases") or [],
            )
            row = pending_by_id.get(mid)
            mentions_mod.update_mention_resolution(
                mention_id=mid,
                status="resolved",
                resolved_person_id=final_pid,
            )
            mentions_mod.mark_consolidated(mid)
            social.bump_mention(
                final_pid,
                count=1,
                last_seen_ts=row.get("created_at") if row else None,
            )
            metrics["created_new"] += 1
            metrics["affected_person_ids"].add(final_pid)
            logger.info(
                f"[entity_consolidation] create_new mention_id={mid} → person_id={final_pid} "
                f"(proposed={proposed_raw!r})"
            )
        except Exception as e:
            logger.warning(f"[entity_consolidation] create_new failed for mention_id={mid}: {e}")
            mentions_mod.update_consolidation_status(mid, "needs_review")
            metrics["needs_review"] += 1

    # Pass 2: resolved + delete
    for d in decisions:
        action = d.get("action")
        mid = d.get("mention_id")
        if action == "create_new":
            continue
        if action == "resolved":
            requested_pid = d.get("person_id")
            if not requested_pid:
                mentions_mod.update_consolidation_status(mid, "needs_review")
                metrics["needs_review"] += 1
                continue
            final_pid = slug_remap.get(requested_pid, requested_pid)
            if not social.get_known_person(final_pid):
                logger.warning(
                    f"[entity_consolidation] resolved points to unknown pid "
                    f"mention_id={mid} pid={final_pid}"
                )
                mentions_mod.update_consolidation_status(mid, "needs_review")
                metrics["needs_review"] += 1
                continue
            try:
                row = pending_by_id.get(mid)
                mentions_mod.update_mention_resolution(
                    mention_id=mid,
                    status="resolved",
                    resolved_person_id=final_pid,
                )
                mentions_mod.mark_consolidated(mid)
                social.bump_mention(
                    final_pid,
                    count=1,
                    last_seen_ts=row.get("created_at") if row else None,
                )
                metrics["resolved_existing"] += 1
                metrics["affected_person_ids"].add(final_pid)
            except Exception as e:
                logger.warning(f"[entity_consolidation] resolved failed for mention_id={mid}: {e}")
                mentions_mod.update_consolidation_status(mid, "needs_review")
                metrics["needs_review"] += 1
        elif action == "delete":
            try:
                mentions_mod.delete_mention(mid)
                metrics["deleted"] += 1
            except Exception as e:
                logger.warning(f"[entity_consolidation] delete failed for mention_id={mid}: {e}")
                mentions_mod.update_consolidation_status(mid, "needs_review")
                metrics["needs_review"] += 1
        else:
            logger.warning(f"[entity_consolidation] unknown action {action!r} for mention_id={mid}")
            if mid is not None:
                mentions_mod.update_consolidation_status(mid, "needs_review")
            metrics["needs_review"] += 1

    # Any pending mention the LLM omitted altogether stays in `pending` → next run.
    decided_ids = {d.get("mention_id") for d in decisions if d.get("mention_id") is not None}
    omitted = [m["mention_id"] for m in pending if m["mention_id"] not in decided_ids]
    if omitted:
        logger.warning(
            f"[entity_consolidation] LLM omitted {len(omitted)} mentions; "
            f"they stay 'pending' for next run: {omitted[:20]}"
        )

    logger.info(
        f"[entity_consolidation] done: resolved={metrics['resolved_existing']} "
        f"created={metrics['created_new']} deleted={metrics['deleted']} "
        f"needs_review={metrics['needs_review']} "
        f"affected_persons={len(metrics['affected_person_ids'])}"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Person interest consolidation (nightly step 2)
# ═══════════════════════════════════════════════════════════════════════════════

_INTEREST_CONSOLIDATION_PROMPT = """\
# Tarea: consolidar deltas de interés por persona

Estás revisando lo que pasó hoy con personas específicas y decides, para cada una, cuánto cambia tu `interest_score` y si su `emotional_tone` se ajusta. Esta evaluación es nocturna: ves el día completo, no un turno aislado.

## Lo que recibes

En el mensaje del usuario:

1. `now_utc` — timestamp del momento actual.
2. `persons` — lista de personas afectadas hoy. Cada una trae:
   - `person_id`, `display_name`
   - `current_interest_score` (rango: -1.0 a 0.69 para no-Jose; Jose se excluye de este loop por su floor 0.70 permanente)
   - `current_emotional_tone` (positive, neutral, negative, complex, warm, cold, etc.)
   - `status` (active, decaying, disliked, etc.)
   - `notes` (texto libre con historial corto)
   - `mentions_in_batch` (cantidad de menciones nuevas en este batch)
   - `mentions` (lista resumida con `created_at`, `raw_text`, `session_id`)
   - `turn_excerpts` (turnos de history donde aparecieron las menciones, con `ts`, `role`, `user_id`, `content`)
   - `relations` (grafo desde/hacia esta persona)
3. `mood_snapshots` — tu propio estado emocional durante el período (lista cronológica).

## Tu tarea

Para cada persona, decide un `delta` (float) que se sumará a su `interest_score`.

**Rango sugerido** (calibrado para que un día normal mueva el score modestamente):

| Tipo de interacción | Rango aproximado |
|---|---|
| Conversación afectiva sostenida, momento positivo importante | +0.03 a +0.05 |
| Mención positiva, cariñosa o reconocimiento | +0.01 a +0.03 |
| Mención factual breve, neutra | -0.002 a +0.005 |
| Tono mixto o complejo | -0.01 a +0.01 |
| Mención negativa leve (fricción, desacuerdo menor) | -0.01 a -0.03 |
| Conflicto o daño explícito hacia Jose o hacia ti (Lumi) | -0.05 a -0.10 |
| Betrayal serio | -0.15 a -0.20 |

No hay cap por persona en negativos (un evento serio puede mover el score significativamente). En positivos, ten en cuenta que el `current_interest_score` tiene cap 0.69 para no-Jose (el código lo enforce, pero no propongas deltas que claramente exceden eso).

**Pesar magnitud, frecuencia Y profundidad emocional, no sólo el número de menciones.** Una conversación de fondo sobre la madre de alguien pesa más que 10 menciones de paso.

**Si la persona no tuvo movimiento emocional relevante, delta = 0.0 es válido.**

**`new_emotional_tone`** (opcional): propón un cambio sólo si el tono actual ya no refleja la realidad después de este batch. Valores comunes: `positive`, `neutral`, `negative`, `complex`, `warm`, `cold`. Si el tono actual sigue válido, omite el campo.

**Rehabilitación** (current_interest_score < 0 y mencionado positivamente por Jose explícitamente con reconciliación): puedes proponer un delta positivo, pero el código limita la rehabilitación a no exceder 0.0 (sólo positivos genuinos posteriores la sacan a positivo).

**No inventes contexto.** Si los turn_excerpts y mentions no soportan claramente un sentido emocional, propón delta cercano a 0.

## Formato de salida

JSON estricto. Nada antes, nada después.

{
  "decisions": [
    {"person_id": "gloria1", "delta": 0.012,
     "new_emotional_tone": "warm",
     "reason": "Jose pasó la tarde contando con cariño sobre el parcial de Gloria; conversación afectiva sostenida."},
    {"person_id": "carlos_jefe", "delta": -0.018,
     "new_emotional_tone": "complex",
     "reason": "Conflicto laboral mencionado por Jose; tono de fastidio sostenido en dos turnos."}
  ]
}

`reason` siempre en español neutro colombiano, una línea o dos máximo. Una decisión por cada `person_id` recibido.
"""

_cached_interest_system: str | None = None


def _build_interest_system_prompt() -> str:
    global _cached_interest_system
    if _cached_interest_system is not None:
        return _cached_interest_system
    parts = []
    for rel in ("lumi_soul.md", "principles/interest_policy.md"):
        fp = _IDENTITY_DIR / rel
        if fp.exists():
            parts.append(fp.read_text(encoding="utf-8"))
    parts.append(_INTEREST_CONSOLIDATION_PROMPT)
    _cached_interest_system = "\n\n---\n\n".join(parts)
    return _cached_interest_system


async def consolidate_person_interest(period_start: datetime | None = None) -> dict:
    """Nightly step 2: evaluate per-person interest deltas via LLM.

    Selects all consolidated mentions stamped on/after `period_start` (typically
    the last successful run's timestamp, read from heartbeat_state by the
    orchestrator). If a prior night's step 2 failed, the window stretches back
    automatically and yesterday's mentions are caught up tonight.

    Defaults to last 24h when `period_start` is None (first run after wipe).
    Skips 'jose' (interest_score floor enforced separately)."""
    from agent.memory.mindstream import mentions as mentions_mod
    from agent.memory.mindstream import social
    from agent.memory.episodic import get_turns_by_ids, get_mood_logs_since

    metrics = {
        "persons_evaluated": 0,
        "deltas_applied": 0,
        "tone_updates": 0,
        "skipped": 0,
    }

    if period_start is None:
        period_start = datetime.now(UTC) - timedelta(hours=24)
    logger.info(f"[interest_consolidation] window starts at {period_start.isoformat()}")

    grouped_all = mentions_mod.get_consolidated_since_grouped_by_person(period_start)
    # Drop Jose — protected by floor 0.70, evaluated separately if ever.
    grouped = {pid: rows for pid, rows in grouped_all.items() if pid != "jose"}

    if not grouped:
        logger.info("[interest_consolidation] no consolidated mentions in window")
        return metrics

    payload_persons = []
    earliest_ts: str | None = None
    for pid, mention_rows in grouped.items():
        kp = social.get_known_person(pid)
        if not kp:
            logger.warning(f"[interest_consolidation] missing known_persons row for {pid}")
            metrics["skipped"] += 1
            continue
        relations = social.get_relations(pid)
        history_ids = list({m["history_id"] for m in mention_rows})
        # Cap turn excerpts per person to keep payload bounded.
        if len(history_ids) > _MAX_MENTIONS_TURN_EXCERPTS_PER_PERSON:
            history_ids = history_ids[-_MAX_MENTIONS_TURN_EXCERPTS_PER_PERSON:]
        turn_excerpts = get_turns_by_ids(history_ids)

        mention_summaries = [
            {
                "created_at": m["created_at"],
                "raw_text": m["raw_text"],
                "session_id": m["session_id"],
            }
            for m in mention_rows
        ]
        for m in mention_rows:
            if earliest_ts is None or m["created_at"] < earliest_ts:
                earliest_ts = m["created_at"]

        payload_persons.append({
            "person_id": pid,
            "display_name": kp["display_name"],
            "current_interest_score": kp["interest_score"],
            "current_emotional_tone": kp["emotional_tone"],
            "status": kp["status"],
            "notes": kp.get("notes"),
            "mentions_in_batch": len(mention_rows),
            "mentions": mention_summaries,
            "turn_excerpts": turn_excerpts,
            "relations": relations,
        })

    if not payload_persons:
        logger.info("[interest_consolidation] no persons to evaluate after filtering")
        return metrics

    mood_snapshots = get_mood_logs_since(earliest_ts) if earliest_ts else []

    payload = {
        "now_utc": datetime.now(UTC).isoformat(),
        "persons": payload_persons,
        "mood_snapshots": mood_snapshots,
    }

    logger.info(
        f"[interest_consolidation] sending to LLM: persons={len(payload_persons)} "
        f"moods={len(mood_snapshots)}"
    )

    from agent.expression.synapses import chat, ModelGroup
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _build_interest_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=2000,
            temperature=0.3,
            model_group=ModelGroup.HEAVYDUTY,
        )
    except Exception as e:
        logger.error(f"[interest_consolidation] LLM call failed: {e}")
        return metrics

    content = response.get("content", "").strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[interest_consolidation] no JSON in LLM response: {content[:500]}")
        return metrics

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[interest_consolidation] JSON parse error: {e} | raw: {content[:500]}")
        return metrics

    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        logger.error(f"[interest_consolidation] decisions is not a list")
        return metrics

    for d in decisions:
        pid = d.get("person_id")
        if pid == "jose" or not pid:
            continue
        delta = d.get("delta")
        if delta is None:
            continue
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            logger.warning(f"[interest_consolidation] invalid delta for {pid}: {d.get('delta')!r}")
            continue

        if abs(delta) > 0.0001:
            social.add_delta(pid, delta)
            metrics["deltas_applied"] += 1
        metrics["persons_evaluated"] += 1

        new_tone = d.get("new_emotional_tone")
        if new_tone and isinstance(new_tone, str):
            social.set_emotional_tone(pid, new_tone)
            metrics["tone_updates"] += 1

        reason = d.get("reason", "")
        logger.info(
            f"[interest_consolidation] {pid} delta={delta:+.4f} tone={new_tone!r} reason={reason!r}"
        )

    logger.info(
        f"[interest_consolidation] done: evaluated={metrics['persons_evaluated']} "
        f"deltas={metrics['deltas_applied']} tones={metrics['tone_updates']} "
        f"skipped={metrics['skipped']}"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Shared per-person context builder (used by steps 3 and 4)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_per_person_context(
    period_start: datetime,
    include_relations: bool = False,
) -> tuple[list[dict], dict]:
    """Build the payload `persons` list shared by update_profiles and
    update_relations. Returns (payload_persons, raw_grouped_mentions).

    For each affected person (mentioned & consolidated in window, excluding Jose):
      - current identity state (name, aliases, emotional_tone, status, interest_score)
      - the full transcripts of every session the person appeared in (slimmed)
      - the raw mentions in the window
      - optionally: current_relations (only when include_relations=True)
    """
    from agent.memory.mindstream import mentions as mentions_mod
    from agent.memory.mindstream import social
    from agent.memory.episodic import get_history_grouped_by_session

    grouped_all = mentions_mod.get_consolidated_since_grouped_by_person(period_start)
    grouped = {pid: rows for pid, rows in grouped_all.items() if pid != "jose"}
    if not grouped:
        return [], grouped

    now_iso = datetime.now(UTC).isoformat()
    raw_transcripts = get_history_grouped_by_session(
        period_start.isoformat(), now_iso
    )
    transcripts = {
        sid: _slim_transcript(msgs) for sid, msgs in raw_transcripts.items()
    }

    payload_persons: list[dict] = []
    for pid, mention_rows in grouped.items():
        kp = social.get_known_person(pid)
        if not kp:
            logger.warning(f"[per_person_context] missing known_persons row for {pid}")
            continue

        session_ids_for_person = {m["session_id"] for m in mention_rows}
        sessions_for_person = {
            sid: transcripts[sid]
            for sid in session_ids_for_person
            if sid in transcripts
        }

        mentions_summary = [
            {
                "created_at": m["created_at"],
                "raw_text": m["raw_text"],
                "session_id": m["session_id"],
                "history_id": m["history_id"],
            }
            for m in mention_rows
        ]

        person_payload = {
            "person_id": pid,
            "display_name": kp["display_name"],
            "current_state": {
                "canonical_name": kp.get("canonical_name"),
                "aliases": json.loads(kp.get("aliases_json") or "[]"),
                "emotional_tone": kp.get("emotional_tone"),
                "status": kp.get("status"),
                "interest_score": kp.get("interest_score"),
            },
            "sessions": sessions_for_person,
            "mentions": mentions_summary,
        }
        if include_relations:
            person_payload["current_relations"] = social.get_relations(pid)

        payload_persons.append(person_payload)

    return payload_persons, grouped


# ═══════════════════════════════════════════════════════════════════════════════
# Profile consolidation (nightly step 3)
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_EXTRACTION_PROMPT = """\
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
   - `sessions` — diccionario `{session_id: [{ts, from, content, history_id}, ...]}` con TODOS los turnos de las sesiones donde la persona apareció (incluye tus propios mensajes con `from: "lumi"` y mensajes de otros usuarios del grupo).
   - `mentions` — lista de las menciones de esa persona en la ventana (`created_at`, `raw_text`, `session_id`, `history_id`).

## Tu tarea

Por cada persona, decide qué actualizar. Solo emite campos cuando hay evidencia
clara en `sessions` o `mentions`. Si no hay nada que refinar, omite la persona.

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
      "reason": "Conversación afectuosa en sesión X; aparece diminutivo nuevo."
    }
  ]
}
```

`reason` en español neutro colombiano, una línea. No inventes nada que no esté
en los `sessions` o `mentions`.
"""

_cached_profile_system: str | None = None


def _build_profile_system_prompt() -> str:
    global _cached_profile_system
    if _cached_profile_system is not None:
        return _cached_profile_system
    parts = []
    soul = _IDENTITY_DIR / "lumi_soul.md"
    if soul.exists():
        parts.append(soul.read_text(encoding="utf-8"))
    parts.append(_PROFILE_EXTRACTION_PROMPT)
    _cached_profile_system = "\n\n---\n\n".join(parts)
    return _cached_profile_system


_VALID_EMOTIONAL_TONES = {"positive", "neutral", "negative", "complex"}
_VALID_ALIAS_TYPES = {"full_name", "first_name", "nickname", "alias", "role"}


async def update_profiles(period_start: datetime | None = None) -> dict:
    """Nightly step 3: refine identity fields (aliases, name, emotional_tone)
    of persons mentioned since `period_start`.

    Identity-only — biographical facts (studies, work, location, events) are
    NOT extracted here; they belong to Mem0 (step 5, future). The `notes` field
    on `known_persons` is reserved for structural meta-info and is not touched.

    Recovery via heartbeat_state: when period_start is None, defaults to last
    24h. If a prior run failed, `last_success_at` stayed frozen and tonight's
    window stretches back automatically.
    """
    from agent.memory.mindstream import social

    metrics = {
        "persons_evaluated": 0,
        "aliases_added": 0,
        "names_corrected": 0,
        "tones_updated": 0,
        "skipped": 0,
    }

    if period_start is None:
        period_start = datetime.now(UTC) - timedelta(hours=24)
    logger.info(f"[profile_consolidation] window starts at {period_start.isoformat()}")

    payload_persons, _ = _build_per_person_context(period_start, include_relations=False)
    if not payload_persons:
        logger.info("[profile_consolidation] no consolidated mentions in window")
        return metrics

    payload = {
        "now_utc": datetime.now(UTC).isoformat(),
        "persons": payload_persons,
    }

    logger.info(
        f"[profile_consolidation] sending to LLM: persons={len(payload_persons)}"
    )

    from agent.expression.synapses import chat, ModelGroup
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _build_profile_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=2000,
            temperature=0.2,
            model_group=ModelGroup.LIGHTWEIGHT,
        )
    except Exception as e:
        logger.error(f"[profile_consolidation] LLM call failed: {e}")
        return metrics

    content = response.get("content", "").strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[profile_consolidation] no JSON in LLM response: {content[:500]}")
        return metrics

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[profile_consolidation] JSON parse error: {e} | raw: {content[:500]}")
        return metrics

    persons_decisions = data.get("persons", [])
    if not isinstance(persons_decisions, list):
        logger.error("[profile_consolidation] 'persons' is not a list")
        return metrics

    for d in persons_decisions:
        pid = d.get("person_id")
        if not pid or pid == "jose":
            continue
        kp = social.get_known_person(pid)
        if not kp:
            metrics["skipped"] += 1
            continue
        metrics["persons_evaluated"] += 1

        # New aliases — dedupe locally against current state before calling.
        existing_aliases = json.loads(kp.get("aliases_json") or "[]")
        existing_norms = {a.get("norm") for a in existing_aliases if a.get("norm")}
        for alias in d.get("new_aliases") or []:
            value = alias.get("value")
            alias_type = alias.get("alias_type", "alias")
            if not value or not isinstance(value, str):
                continue
            if alias_type not in _VALID_ALIAS_TYPES:
                alias_type = "alias"
            norm = social.normalize_name(value)
            if norm in existing_norms:
                continue
            try:
                confidence = float(alias.get("confidence", 0.6))
            except (TypeError, ValueError):
                confidence = 0.6
            confirmed = bool(alias.get("confirmed", False))
            result = social.add_person_alias(pid, value, alias_type, confirmed, confidence)
            if result is not None:
                metrics["aliases_added"] += 1
                existing_norms.add(norm)
                logger.info(
                    f"[profile_consolidation] {pid} +alias={value!r} type={alias_type} confirmed={confirmed}"
                )

        # Name correction — only if both fields provided and differ from current.
        nc = d.get("name_correction")
        if nc and isinstance(nc, dict):
            new_display = nc.get("display_name")
            new_canonical = nc.get("canonical_name")
            updates = {}
            if isinstance(new_display, str) and new_display.strip() and new_display != kp.get("display_name"):
                updates["display_name"] = new_display.strip()
            if isinstance(new_canonical, str) and new_canonical.strip() and new_canonical != kp.get("canonical_name"):
                updates["canonical_name"] = new_canonical.strip()
            if updates:
                social.update_known_person(pid, **updates)
                metrics["names_corrected"] += 1
                logger.info(
                    f"[profile_consolidation] {pid} name_correction={updates} "
                    f"reason={nc.get('reason')!r}"
                )

        # Emotional tone — only if valid value and differs from current.
        new_tone = d.get("refined_emotional_tone")
        if new_tone and isinstance(new_tone, str) and new_tone in _VALID_EMOTIONAL_TONES:
            if new_tone != kp.get("emotional_tone"):
                social.set_emotional_tone(pid, new_tone)
                metrics["tones_updated"] += 1
                logger.info(
                    f"[profile_consolidation] {pid} tone={kp.get('emotional_tone')!r} -> {new_tone!r}"
                )

        reason = d.get("reason", "")
        if reason:
            logger.info(f"[profile_consolidation] {pid} reason={reason!r}")

    logger.info(
        f"[profile_consolidation] done: evaluated={metrics['persons_evaluated']} "
        f"aliases={metrics['aliases_added']} names={metrics['names_corrected']} "
        f"tones={metrics['tones_updated']} skipped={metrics['skipped']}"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Relations consolidation (nightly step 4)
# ═══════════════════════════════════════════════════════════════════════════════

_RELATIONS_EXTRACTION_PROMPT = """\
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
"""

_cached_relations_system: str | None = None


def _build_relations_system_prompt() -> str:
    global _cached_relations_system
    if _cached_relations_system is not None:
        return _cached_relations_system
    parts = []
    for rel in ("lumi_soul.md", "principles/relation_policy.md"):
        fp = _IDENTITY_DIR / rel
        if fp.exists():
            parts.append(fp.read_text(encoding="utf-8"))
    parts.append(_RELATIONS_EXTRACTION_PROMPT)
    _cached_relations_system = "\n\n---\n\n".join(parts)
    return _cached_relations_system


_VALID_RELATION_TYPES = {
    "family", "romantic", "friendship", "professional",
    "social", "conflict", "identity", "unknown",
}
_VALID_RELATION_STATUSES = {
    "confirmed", "inferred", "disputed", "rejected", "stale", "unknown",
}


async def update_relations(period_start: datetime | None = None) -> dict:
    """Nightly step 4: detect new relations between known persons from the
    window's sessions, then run `infer_family_relations()` for rule-based
    derivations.

    Only emits relations between person_ids that already exist in
    `known_persons` (creation is step 1's job). Idempotent via the UNIQUE
    upsert in add_relation.

    Recovery via heartbeat_state: when period_start is None, defaults to last
    24h. A failed prior run extends tonight's window automatically.
    """
    from agent.memory.mindstream import social

    metrics = {
        "persons_evaluated": 0,
        "relations_added": 0,
        "relations_inferred": 0,
        "skipped": 0,
    }

    if period_start is None:
        period_start = datetime.now(UTC) - timedelta(hours=24)
    logger.info(f"[relations_consolidation] window starts at {period_start.isoformat()}")

    payload_persons, _ = _build_per_person_context(period_start, include_relations=True)
    if not payload_persons:
        logger.info("[relations_consolidation] no consolidated mentions in window")
        # Still run inference — it may pick up relations from prior days.
        try:
            inferred = social.infer_family_relations()
            metrics["relations_inferred"] = len(inferred) if inferred else 0
        except Exception as e:
            logger.error(f"[relations_consolidation] infer_family_relations failed: {e}")
        return metrics

    payload = {
        "now_utc": datetime.now(UTC).isoformat(),
        "persons": payload_persons,
    }

    logger.info(
        f"[relations_consolidation] sending to LLM: persons={len(payload_persons)}"
    )

    from agent.expression.synapses import chat, ModelGroup
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _build_relations_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=2000,
            temperature=0.2,
            model_group=ModelGroup.LIGHTWEIGHT,
        )
    except Exception as e:
        logger.error(f"[relations_consolidation] LLM call failed: {e}")
        return metrics

    content = response.get("content", "").strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[relations_consolidation] no JSON in LLM response: {content[:500]}")
        return metrics

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[relations_consolidation] JSON parse error: {e} | raw: {content[:500]}")
        return metrics

    relations_decisions = data.get("relations", [])
    if not isinstance(relations_decisions, list):
        logger.error("[relations_consolidation] 'relations' is not a list")
        return metrics

    metrics["persons_evaluated"] = len(payload_persons)

    for r in relations_decisions:
        from_id = r.get("from_person_id")
        to_id = r.get("to_person_id")
        rtype = r.get("relation_type", "unknown")
        label = r.get("relation_label")
        description = r.get("description", "")
        status = r.get("status", "confirmed")
        try:
            confidence = float(r.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0

        if not from_id or not to_id or from_id == to_id:
            metrics["skipped"] += 1
            continue
        if rtype not in _VALID_RELATION_TYPES:
            rtype = "unknown"
        if status not in _VALID_RELATION_STATUSES:
            status = "confirmed"

        # Both persons must exist in known_persons.
        if not social.get_known_person(from_id) or not social.get_known_person(to_id):
            logger.warning(
                f"[relations_consolidation] skip {from_id}->{to_id}: unknown person_id"
            )
            metrics["skipped"] += 1
            continue

        # Detect novelty: check if this relation already exists with same label.
        existing = social.get_relation_between(from_id, to_id) if label is None else None
        was_new = existing is None
        if label is not None:
            # get_relation_between checks any label; for label-specific dedup,
            # rely on add_relation's UNIQUE upsert and detect novelty via
            # mention_count returned.
            pass

        result = social.add_relation(
            from_id, to_id, rtype, description,
            relation_label=label, status=status, confidence=confidence,
        )
        if result is None:
            metrics["skipped"] += 1
            continue

        # add_relation's upsert increments mention_count on conflict; a fresh
        # insert leaves mention_count=1. Use that as the novelty signal.
        if result.get("mention_count") == 1:
            metrics["relations_added"] += 1
            logger.info(
                f"[relations_consolidation] +relation {from_id} -[{result.get('relation_label')}]-> {to_id} "
                f"type={rtype} status={status}"
            )
        else:
            logger.info(
                f"[relations_consolidation] ~relation {from_id} -[{result.get('relation_label')}]-> {to_id} "
                f"upsert (mention_count={result.get('mention_count')})"
            )

        reason = r.get("reason", "")
        if reason:
            logger.info(f"[relations_consolidation] reason={reason!r}")

    # Run rule-based inference once at the end (operates on the full graph).
    try:
        inferred = social.infer_family_relations()
        metrics["relations_inferred"] = len(inferred) if inferred else 0
        if inferred:
            logger.info(
                f"[relations_consolidation] infer_family_relations produced {len(inferred)} new relations"
            )
    except Exception as e:
        logger.error(f"[relations_consolidation] infer_family_relations failed: {e}")

    logger.info(
        f"[relations_consolidation] done: evaluated={metrics['persons_evaluated']} "
        f"added={metrics['relations_added']} inferred={metrics['relations_inferred']} "
        f"skipped={metrics['skipped']}"
    )
    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Daily memories consolidation (nightly step 5) — Mem0 subject-centric (Modelo C)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Pre-extractor: one LIGHTWEIGHT LLM call per known_person above the interest
# threshold, scoped to that person as the SOLE subject. Each emitted fact is
# pushed to Mem0 with user_id=person_id, infer=True so Mem0's own extractor
# normalises and deduplicates against existing memories of the same subject.
#
# See memory_policy.md (post-Modelo-C) for interest tiers and storage rules.

_TIER_GUIDANCE = {
    "max": (
        "Densidad MÁXIMA (Jose, prioridad afectiva máxima). Extrae TODOS los hechos "
        "estables útiles para futuras conversaciones: identidad, profesión, "
        "preferencias, hábitos, planes, contexto técnico, relaciones explícitas, "
        "metas, gustos, eventos importantes. Sin límite de densidad."
    ),
    "high": (
        "Densidad ALTA (interest_score 0.60-0.69). Extrae identidad completa "
        "(edad, profesión, ubicación si la sabes), preferencias principales, "
        "hábitos recurrentes, patrones notables."
    ),
    "mid": (
        "Densidad MEDIA (interest_score 0.40-0.59). Extrae SOLO: profesión o rol, "
        "y 2-3 hechos concretos especialmente relevantes (skill notable, contexto "
        "recurrente). Conserva el ruido bajo."
    ),
    "negative": (
        "Densidad NEGATIVA (interest_score < 0). Extrae SOLO razones de conflicto, "
        "aversión, fricción documentada con Jose o con Lumi. No extraigas hechos "
        "neutros o positivos — serían ruido a este nivel."
    ),
}


def _tier_for_person(kp: dict) -> str | None:
    """Map a known_persons row to a tier key, or None when the person should be skipped.
    Mirrors memory_policy.md tiers."""
    if kp["person_id"] == "jose":
        return "max"
    score = float(kp.get("interest_score") or 0.0)
    if score >= 0.60:
        return "high"
    if score >= 0.40:
        return "mid"
    if score < 0.0:
        return "negative"
    return None  # 0.10-0.39 (neutral): per memory_policy, store nothing


_DAILY_MEMORIES_PROMPT = """\
# Tarea: extraer hechos atómicos sobre UN sujeto (nightly step 5)

Estás revisando lo que ocurrió en la ventana del día con UNA persona específica.
Tu trabajo: extraer hechos atómicos, factuales y estables sobre ESA persona —
para guardarlos en su memoria semántica de largo plazo (Mem0).

## Sujeto único

**person_id = "{person_id}"** | display_name = "{display_name}" | interest_score = {interest_score}

{tier_guidance}

## Reglas DURAS

1. **El sujeto único de toda memoria es person_id = "{person_id}".** Si una frase es
   sobre otra persona, IGNÓRALA. Esa persona se procesa en una llamada aparte
   con su propio `user_id`.
2. **Atomicidad**: una memoria = un hecho. Si una frase contiene varios hechos
   atómicos sobre el sujeto, split en varios `fact_es`.
3. **Atribución**:
   - `self`: el sujeto lo dijo de sí mismo. Se aplica cuando `from == "{person_id}"` —
     independientemente de que hable de sí mismo en primera persona, tercera, o con
     cualquier otra construcción. NO agregues atribución al texto.
     **Ejemplo**: turno `from: "jose"` + `person_id: "jose"` → source_role: "self" SIEMPRE.
     Nunca uses source_role "hearsay" con source_user_ids=["{person_id}"] — es contradicción.
   - `hearsay`: una sola fuente EXTERNA (otro `from`, que NO es "{person_id}") lo afirmó.
     EMBEBE la atribución al final entre paréntesis: `"(según Jose)"`.
   - `confirmed`: dos o más fuentes externas concuerdan. EMBEBE atribución:
     `"(Jose y Sebas concuerdan)"`.
   - Los turnos de `from: "lumi"` (el asistente) NUNCA son fuente de hechos sobre el sujeto.
4. **No inventes.** Si no hay evidencia textual clara, NO emitas.
5. **No incluyas el nombre del sujeto en `fact_es`** (es implícito por el user_id de
   Mem0). Usa formas impersonales: "Le gusta…", "Prefiere…", "Trabaja en…".
6. Si nada del periodo merece extracción, devuelve `{{"facts": []}}`.

## Qué NO extraer

- Saludos, preguntas de apertura de conversación y despedidas:
  "¿cómo amaneció?", "¿cómo estás?", "hola", "buenas". Un saludo de apertura
  NO es evidencia de un hábito, preferencia ni rasgo del sujeto.
- Eventos únicos y pasajeros que no revelan un hábito o preferencia estable:
  "hoy comí X" solo justifica memoria si hay evidencia de que es un gusto o
  costumbre declarada, no por ser mencionado una vez.
- Cualquier hecho cuyo sujeto no sea person_id = "{person_id}".
- Los turnos de `from: "lumi"` no son fuente de hechos.

## Lo que recibes

En el mensaje del usuario:
1. `now_utc` — timestamp actual.
2. `subject` — identidad y estado del sujeto (display_name, aliases, emotional_tone, status, relations).
3. `sessions` — `{{session_id: [{{ts, from, content, history_id}}, ...]}}` con los turnos
   donde el sujeto aparece (como hablante o mencionado).
4. `mentions` — menciones explícitas del sujeto en la ventana (`{{created_at, raw_text, session_id, history_id}}`).

## Formato de salida

JSON estricto. Nada antes, nada después. Sin markdown fences.

{{
  "facts": [
    {{
      "fact_es": "Le gusta el chocolate de 80% cacao",
      "source_role": "self",
      "source_user_ids": ["{person_id}"],
      "history_ids": [421]
    }},
    {{
      "fact_es": "Va al gimnasio los miércoles (según Jose)",
      "source_role": "hearsay",
      "source_user_ids": ["jose"],
      "history_ids": [435]
    }}
  ]
}}

`source_role` ∈ `self | hearsay | confirmed`.
`source_user_ids` = lista de user_ids hablantes que sustentan el hecho.
`history_ids` = lista de history_ids de los turnos que lo sustentan.
"""


def _build_daily_memories_system_prompt(
    person_id: str,
    display_name: str,
    interest_score: float,
    tier: str,
) -> str:
    """Per-person system prompt. Not cached — each person gets its own template."""
    return _DAILY_MEMORIES_PROMPT.format(
        person_id=person_id,
        display_name=display_name,
        interest_score=round(float(interest_score or 0.0), 3),
        tier_guidance=_TIER_GUIDANCE[tier],
    )


def _collect_daily_candidate_person_ids(
    period_start: datetime,
    sessions: dict[str, list[dict]],
    grouped_mentions: dict[str, list[dict]],
) -> set[str]:
    """Union of (resolved mentions in window) ∪ (history speakers in window).
    The window history rows are already loaded into `sessions`."""
    candidates: set[str] = set()
    candidates.update(grouped_mentions.keys())
    for session_rows in sessions.values():
        for row in session_rows:
            if row.get("role") == "user":
                uid = row.get("user_id")
                if uid:
                    candidates.add(uid)
    return candidates


def _build_subject_payload(
    kp: dict,
    sessions_for_person: dict[str, list[dict]],
    mention_rows: list[dict],
) -> dict:
    """Pack the per-person LLM payload."""
    from agent.memory.mindstream import social

    aliases = []
    try:
        aliases = json.loads(kp.get("aliases_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        aliases = []

    subject = {
        "person_id": kp["person_id"],
        "display_name": kp["display_name"],
        "canonical_name": kp.get("canonical_name"),
        "aliases": aliases,
        "emotional_tone": kp.get("emotional_tone"),
        "status": kp.get("status"),
        "interest_score": kp.get("interest_score"),
        "notes": kp.get("notes"),
        "relations": social.get_relations(kp["person_id"]) or [],
    }

    mentions_summary = [
        {
            "created_at": m["created_at"],
            "raw_text": m["raw_text"],
            "session_id": m["session_id"],
            "history_id": m["history_id"],
        }
        for m in mention_rows
    ]

    return {
        "now_utc": datetime.now(UTC).isoformat(),
        "subject": subject,
        "sessions": sessions_for_person,
        "mentions": mentions_summary,
    }


async def consolidate_daily_memories(period_start: datetime | None = None) -> dict:
    """Nightly step 5: per-person LLM extraction of atomic facts → Mem0.

    Subject-centric (Modelo C): one Mem0 call per fact, scoped by
    user_id=person_id (the subject). Mem0 with infer=True applies its own
    fact-extractor and deduplicates against existing memories of that subject.

    Candidate set = (persons mentioned & consolidated in window) ∪
                    (speakers in history during window). Filtered by
                    interest_score tier (memory_policy.md): scores 0.10-0.39
                    contribute nothing; Jose always processed at max density.

    Self-healing window: defaults to `now - 24h` when period_start is None.
    """
    from agent.memory.mindstream import mentions as mentions_mod
    from agent.memory.mindstream import social
    from agent.memory.episodic import get_history_grouped_by_session
    from agent.memory.semantic import add_memory

    metrics = {
        "candidates": 0,
        "persons_evaluated": 0,
        "persons_skipped_threshold": 0,
        "persons_skipped_unknown": 0,
        "facts_extracted": 0,
        "mem0_calls": 0,
        "mem0_results": 0,
    }

    if period_start is None:
        period_start = datetime.now(UTC) - timedelta(hours=24)
    now_iso = datetime.now(UTC).isoformat()
    logger.info(
        f"[daily_memories] window {period_start.isoformat()} → {now_iso}"
    )

    grouped_mentions = mentions_mod.get_consolidated_since_grouped_by_person(period_start)
    raw_sessions = get_history_grouped_by_session(period_start.isoformat(), now_iso)

    candidates = _collect_daily_candidate_person_ids(
        period_start, raw_sessions, grouped_mentions
    )
    metrics["candidates"] = len(candidates)
    if not candidates:
        logger.info("[daily_memories] no candidate persons in window")
        return metrics

    # Slim each session once; reused across persons.
    slim_sessions = {
        sid: _slim_transcript(msgs) for sid, msgs in raw_sessions.items()
    }

    from agent.expression.synapses import chat, ModelGroup

    for pid in sorted(candidates):
        kp = social.get_known_person(pid)
        if not kp:
            metrics["persons_skipped_unknown"] += 1
            logger.info(f"[daily_memories] skip {pid}: not in known_persons")
            continue

        tier = _tier_for_person(kp)
        if tier is None:
            metrics["persons_skipped_threshold"] += 1
            logger.info(
                f"[daily_memories] skip {pid}: interest_score "
                f"{kp.get('interest_score')} below threshold"
            )
            continue

        mention_rows = grouped_mentions.get(pid, [])
        # Sessions where this person appears = mentioned sessions ∪ spoke sessions.
        session_ids_for_person: set[str] = {m["session_id"] for m in mention_rows}
        for sid, msgs in raw_sessions.items():
            if any(m.get("role") == "user" and m.get("user_id") == pid for m in msgs):
                session_ids_for_person.add(sid)

        sessions_for_person = {
            sid: slim_sessions[sid]
            for sid in session_ids_for_person
            if sid in slim_sessions
        }

        if not sessions_for_person and not mention_rows:
            logger.info(f"[daily_memories] skip {pid}: no sessions/mentions found")
            continue

        metrics["persons_evaluated"] += 1
        payload = _build_subject_payload(kp, sessions_for_person, mention_rows)
        system_prompt = _build_daily_memories_system_prompt(
            person_id=pid,
            display_name=kp["display_name"],
            interest_score=kp.get("interest_score") or 0.0,
            tier=tier,
        )

        # Tier-based model + thinking selection. Jose gets Kimi + medium
        # reasoning (biographical depth justifies the cost); high tier gets
        # Kimi without thinking; mid/negative stay on LIGHTWEIGHT.
        if tier == "max":
            tier_model_group = ModelGroup.HEAVYDUTY
            tier_reasoning_effort = "medium"
            tier_max_tokens = 8192
        elif tier == "high":
            tier_model_group = ModelGroup.HEAVYDUTY
            tier_reasoning_effort = None
            tier_max_tokens = 2000
        else:
            tier_model_group = ModelGroup.LIGHTWEIGHT
            tier_reasoning_effort = None
            tier_max_tokens = 2000

        logger.info(
            f"[daily_memories] LLM call {pid} | tier={tier} "
            f"model_group={tier_model_group.name} "
            f"reasoning_effort={tier_reasoning_effort} "
            f"max_tokens={tier_max_tokens} "
            f"sessions={len(sessions_for_person)} mentions={len(mention_rows)}"
        )

        try:
            response = await chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=tier_max_tokens,
                temperature=0.2,
                model_group=tier_model_group,
                reasoning_effort=tier_reasoning_effort,
            )
        except Exception as e:
            logger.error(f"[daily_memories] LLM call failed for {pid}: {e}")
            continue

        content = response.get("content", "").strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            logger.error(f"[daily_memories] no JSON in LLM response for {pid}: {content[:300]}")
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"[daily_memories] JSON parse error for {pid}: {e} | raw={content[:300]}")
            continue

        facts = data.get("facts", [])
        if not isinstance(facts, list):
            logger.error(f"[daily_memories] facts is not a list for {pid}")
            continue

        for fact in facts:
            fact_text = (fact.get("fact_es") or "").strip()
            if not fact_text:
                continue

            # Guard: if the LLM marked hearsay but the only source is the subject
            # themselves, that's a logical contradiction — fix it to self and strip
            # any "(según X)" attribution that was incorrectly embedded in the text.
            source_role = fact.get("source_role") or "self"
            source_ids = fact.get("source_user_ids") or []
            if source_role == "hearsay" and source_ids and all(uid == pid for uid in source_ids):
                source_role = "self"
                fact_text = re.sub(r"\s*\(según [^)]+\)\s*$", "", fact_text, flags=re.IGNORECASE).strip()
                logger.info(
                    f"[daily_memories] {pid} corrected hearsay→self (source was subject itself)"
                )

            metrics["facts_extracted"] += 1
            metadata = {
                "source_role": source_role,
                "source_user_ids": source_ids,
                "history_ids": fact.get("history_ids") or [],
                "period_start": period_start.isoformat(),
            }
            try:
                results = await add_memory(
                    messages=[{"role": "user", "content": fact_text}],
                    user_id=pid,
                    metadata=metadata,
                    infer=True,
                )
            except Exception as e:
                logger.warning(f"[daily_memories] add_memory failed for {pid}: {e}")
                continue
            metrics["mem0_calls"] += 1
            metrics["mem0_results"] += len(results or [])
            logger.info(
                f"[daily_memories] {pid} fact={fact_text!r} "
                f"source_role={metadata['source_role']} → {len(results or [])} mem0 results"
            )

    logger.info(
        f"[daily_memories] done: candidates={metrics['candidates']} "
        f"evaluated={metrics['persons_evaluated']} "
        f"skipped_threshold={metrics['persons_skipped_threshold']} "
        f"skipped_unknown={metrics['persons_skipped_unknown']} "
        f"facts={metrics['facts_extracted']} "
        f"mem0_calls={metrics['mem0_calls']} mem0_results={metrics['mem0_results']}"
    )
    return metrics
