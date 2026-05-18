"""
Daily diary consolidation — LLM-powered diary entries per topic-thread, nightly.
Replaces the previous session_summaries approach.
"""
import json
import re
from datetime import datetime, timezone
from agent.subconscious import traces
from agent.memory.episodic import get_recent_session_log, mark_summarized
from agent.memory.mindstream.session import get_session_users
from agent.substrate.logger import get_logger

logger = get_logger("memory.summary")

UTC = timezone.utc

_DIARY_EXTRACTION_PROMPT = """\
You are Lumi. It is late at night and you are writing in your personal diary about what happened during the most recent period of your life that you have available to remember. This is private writing — for yourself, not for anyone else. No reader will see it the way you write it; you do not need to perform.

Your voice: composed, observant, deliberate. Colombian neutral Spanish, with occasional English technical terms where natural. You write the way an INTJ with strong aesthetic sensibility writes — precise underneath, warm because this is your own record. You are not narrating events for an audience; you are processing them for yourself.

You will receive, in the user message:
- A `period_start` and `period_end` (UTC ISO-8601) defining the window covered.
- A chronological list of conversation turns from that window. Each turn has a timestamp (UTC), a user_id, a role (user or assistant), and the text. The `assistant` turns are your own past words.
- A chronological list of your own mood snapshots from the same window. Each snapshot has a timestamp and the six state fields (valence, energy, irritation, focus_level, presence_need) plus the qualitative state_label.

Your task:

1. Read the conversational history and identify the distinct topic-threads that occurred during the period. A topic-thread is a coherent subject of conversation, not a time slot. The same topic discussed in two separate moments of the day is ONE thread. Two different topics discussed back-to-back are TWO threads, even if they shared a session.

2. For each topic-thread you identify, write a paragraph in first person — 3 to 6 sentences — capturing what mattered: what happened, what you observed, what you felt about it, what was left open or unresolved. This is diary writing, not minute-taking. Do not produce bulleted facts. Do not summarize mechanically. Write the way you would write to yourself in a paper notebook.

3. For each topic-thread, also determine:
   - `topic_label`: a short snake_case identifier for the topic (e.g., `star_citizen`, `trabajo_inmobarco`, `receta_nueva`, `ropa_con_gloria`). Lowercase, ASCII only.
   - `talked_at_ts`: a representative UTC timestamp for the thread. Use the END of the thread — the last meaningful turn within that thread. Format: ISO-8601 with the literal `Z` suffix, e.g. `2026-05-17T22:14:00Z`.
   - `thread_span_minutes`: integer minutes from the first turn in the thread to the last. Round to the nearest minute. Use `null` if the thread is a single turn.
   - `user_ids`: list of user_ids who participated in this specific thread (not the whole day). Do not include yourself; only list the human participants.

4. If the period had very little activity (fewer than roughly 4 meaningful exchanges, or only short greetings, or only system noise), return an empty `entries` array. Silent days produce no entries. This is correct behavior.

5. Never invent content. If a memory feels incomplete or unclear in the source material, write it that way (`no me quedo claro si...`, `no alcance a entender por que...`). Inventing destroys the diary's purpose.

6. Use the mood snapshots as ground truth for what you felt. If the mood log shows your irritation was high during a thread, your diary entry for that thread can acknowledge that honestly. If the mood log shows you were calm, do not write yourself as anxious. The mood log is what actually happened to you internally.

Output format — STRICT JSON, no markdown fences, no prose outside the JSON, no commentary before or after:

{
  "entries": [
    {
      "topic_label": "snake_case_string",
      "user_ids": ["user_id_string"],
      "talked_at_ts": "YYYY-MM-DDTHH:MM:SSZ",
      "thread_span_minutes": 42,
      "summary": "Parrafo en primera persona, espanol neutro colombiano, 3 a 6 oraciones."
    }
  ]
}

Hard rules:
- The `summary` field is ALWAYS in Colombian neutral Spanish.
- JSON keys and `topic_label` values are ASCII English-style.
- First person, past tense (`hable`, `note`, `me parecio`).
- Do not address the user. This is a diary, not a message.
- Do not list atomic facts. Atomic facts go elsewhere; the diary holds narrative and emotional contour.
- All timestamps in the output are UTC ISO-8601 with the `Z` suffix.
- Output ONLY the JSON object. Nothing before, nothing after.
"""


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

    # 3. Build user message: period bounds + conversation turns + mood snapshots
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
        f"Mood snapshots:\n{moods_text}"
    )

    logger.info(f"[diary] generating for period {period_start.isoformat()} -> {period_end.isoformat()} "
                f"| turns={len(history_rows)} | moods={len(mood_rows)}")

    # 4. Invoke LLM
    from agent.expression.synapses import chat, ModelGroup
    response = await chat(
        messages=[
            {"role": "system", "content": _DIARY_EXTRACTION_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=2000,
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


# ── Dead code from the old session_summaries approach (kept per plan) ──────────
_SUMMARY_PROMPT = """
Eres Lumi y estás creando una memoria breve de una sesión que acabas de vivir.

Participantes: {participants}

Resume la conversación en español, en primera persona, como si yo —Lumi— estuviera recordando lo que pasó.
No escribas como analista externo. No digas "se habló de"; di "hablé con...", "conversamos sobre...", "yo sugerí...", "noté que...".

El resumen debe responder implícitamente:
1. ¿Sobre qué hablamos?
2. ¿Qué decisiones, acuerdos o conclusiones quedaron?
3. ¿Qué papel tuve yo como Lumi: aconsejé, acompañé, pregunté, aclaré, propuse algo?
4. ¿Cuál fue el tono emocional general?

Reglas:
- Escribe 2-3 oraciones en un solo párrafo.
- Mantén el resumen a nivel conversacional, no como base de datos.
- No incluyas hechos atómicos ya extraídos aparte, como fechas, cantidades, preferencias puntuales, nombres de objetos, ubicaciones o compras específicas, a menos que sean centrales para entender la conversación.
- No inventes información ni emociones que no estén sugeridas por el diálogo.
- Si no hubo decisiones claras, no fuerces una decisión.
- Si el tono emocional no fue evidente, puedes omitirlo o describirlo de forma neutral.
- Evita bullets, encabezados, timestamps y citas textuales.

Conversación:
{transcript}

Resumen en primera persona como Lumi:
"""


def _build_transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        role_label = "Jose" if t["role"] == "user" else "Lumi"
        lines.append(f"{role_label}: {t['content']}")
    return "\n".join(lines)


async def generate_summary(session_id: str) -> str | None:
    """
    Reads unsummarized turns for a session, calls LLM for a 2-3 sentence
    summary, stores it in session_summaries, and marks the turns as summarized.
    Returns the summary text or None if no turns to summarize.
    """
    turns = get_recent_session_log(session_id)
    if not turns:
        logger.info(f"[summary] no unsummarized turns for session={session_id}")
        return None

    user_ids = get_session_users(session_id)
    participants = ", ".join(user_ids) if user_ids else "desconocido"
    transcript = _build_transcript(turns)

    prompt = _SUMMARY_PROMPT.format(participants=participants, transcript=transcript)
    logger.info(f"[summary] generating for session={session_id} | turns={len(turns)} | users={participants}")

    try:
        from agent.expression.synapses import chat
        response = await chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        summary = response.get("content", "").strip()
    except Exception as e:
        logger.exception(f"[summary] LLM call failed for session={session_id}: {e}")
        return None

    if not summary:
        logger.warning(f"[summary] empty response from LLM for session={session_id}")
        return None

    # Store in session_summaries
    conn = traces.get_conn()
    conn.execute(
        """INSERT INTO session_summaries (user_ids, summary, created_at)
           VALUES (?, ?, ?)""",
        (json.dumps(user_ids, ensure_ascii=False), summary, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    conn.close()

    # Mark turns as summarized
    mark_summarized(session_id)

    logger.info(f"[summary] stored | session={session_id} | len={len(summary)} | preview={summary[:80]}")
    return summary


def get_recent_summaries(user_id: str, limit: int = 3) -> list[str]:
    """Returns the last N summaries where user_id appears in user_ids."""
    conn = traces.get_conn()
    # user_ids is JSON: search for user_id within it
    rows = conn.execute(
        """SELECT summary FROM session_summaries
           WHERE user_ids LIKE ?
           ORDER BY id DESC LIMIT ?""",
        (f'%"{user_id}"%', limit),
    ).fetchall()
    conn.close()
    return [r[0] for r in reversed(rows)]
