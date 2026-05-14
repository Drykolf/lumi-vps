"""
Session summary generator — LLM-powered session summaries every 5 turns.
Stores in traces.db: session_summaries table.
"""
import json
from datetime import datetime, timezone
from agent.subconscious import traces
from agent.memory.episodic import get_session_turns, mark_summarized
from agent.memory.mindstream.session import get_session_users
from agent.substrate.logger import get_logger

logger = get_logger("memory.summary")

UTC = timezone.utc

_SUMMARY_PROMPT = """Eres Lumi. Resume esta sesion en 2-3 oraciones, en espanol, primera persona.
Participantes: {participants}.
Enfocate en: temas tratados, decisiones tomadas, estado emocional general.
No incluyas hechos atomicos (ya extraidos aparte).

Conversacion:
{transcript}"""


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
    turns = get_session_turns(session_id)
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
