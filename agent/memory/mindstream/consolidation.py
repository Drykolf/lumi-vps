"""
Daily diary consolidation — LLM-powered diary entries per topic-thread, nightly.
Replaces the previous session_summaries approach.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from agent.subconscious import traces
from agent.substrate.logger import get_logger

logger = get_logger("memory.summary")

UTC = timezone.utc

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
    for rel in ("compact_soul.md", "attitude.md"):
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
    turn_lines = []
    for r in history_rows:
        role_label = "assistant" if r[2] == "assistant" else "user"
        turn_lines.append(f"[{r[5]}] {role_label} ({r[1]}): {r[3]}")
    turns_text = "\n".join(turn_lines)

    mood_lines = []
    for m in mood_rows:
        mood_lines.append(
            f"[{m[0]}] valence={m[1]:.2f} energy={m[2]:.2f} irritation={m[3]:.2f} "
            f"focus={m[4]:.2f} presence_need={m[5]:.2f} label={m[6]} "
            f"honesty_mode={bool(m[7])}"
        )
    moods_text = "\n".join(mood_lines) if mood_lines else "(no mood snapshots)"

    user_msg = (
        f"Period: {period_start.isoformat()} to {period_end.isoformat()}\n\n"
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
        model_group=ModelGroup.LIGHTWEIGHT,
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


