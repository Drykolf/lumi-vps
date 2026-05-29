from pathlib import Path
from datetime import datetime, timezone, timedelta
from agent.memory import (
    get_recent_session_log,
    get_recent_user_log,
    read_recent_diary_entries,
    get_known_person,
    ensure_known_person,
)
from agent.affect import get_state, state_to_text, get_sleep_stage
from agent.affect.mood import LUMI_TZ_OFFSET
from agent.substrate.logger import get_logger
import math

logger = get_logger("agent.context")

UTC = timezone.utc
SOUL_PATH = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"
_DYNAMIC_LOG_PATH = Path("data/logs/dynamic.log")

_cached_prefix = None


def _dump_dynamic_log(user_id: str, message: str, dynamic: str) -> None:
    """Overwrite data/logs/dynamic.log with the latest dynamic suffix."""
    try:
        _DYNAMIC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"[dynamic_suffix {datetime.now(UTC).isoformat(timespec='seconds')} UTC]\n"
            f"user_id: {user_id}\n"
            f"message: {message}\n"
            f"{'-' * 80}\n"
        )
        _DYNAMIC_LOG_PATH.write_text(header + dynamic + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning(f"[dynamic_log] write failed: {e}")


def _build_cached_prefix() -> str:
    parts = []

    if SOUL_PATH.exists():
        parts.append(SOUL_PATH.read_text(encoding="utf-8"))

    if ATTITUDE_PATH.exists():
        parts.append(ATTITUDE_PATH.read_text(encoding="utf-8"))

    if parts:
        return "\n\n---\n\n".join(parts)

    return (
        "Eres Lumi, asistente personal de Jose Barco. "
        "Responde en espanol colombiano neutro. "
        "Emotion tag obligatorio al inicio: [neutral], [happy], [sad], [thinking], [surprised], [playful]."
    )


def get_cached_prefix() -> str:
    global _cached_prefix
    if _cached_prefix is None:
        _cached_prefix = _build_cached_prefix()
    return _cached_prefix

async def _build_diary_suffix(user_id: str) -> str | None:
    diary = await read_recent_diary_entries(user_id=user_id, limit=7)
    if not diary:
        return None
    lines = []
    for entry in reversed(diary):
        label = entry.get("topic_label") or "sin_etiqueta"
        talked = entry.get("talked_at_ts")
        ts_str = talked.strftime("%d/%m/%Y %H:%M UTC") if talked else "?"
        users = ", ".join(entry.get("user_ids", []))
        header = f"[Diary entry — {ts_str} — topic: {label} — with: {users}]"
        lines.append(f"{header}\n{entry['summary']}")
    return "[Entradas recientes del diario de Lumi]\n" + "\n\n".join(lines)


def _dedup_memories(memories: list[str], recent_turns: list[dict]) -> list[str]:
    """Drop Mem0 hits whose head is a substring of any recent turn — already in working memory."""
    if not memories or not recent_turns:
        return memories
    recent_blob = " ".join((t.get("content") or "").lower() for t in recent_turns)
    out = []
    for m in memories:
        m_norm = (m or "").lower().strip()
        if len(m_norm) >= 25 and m_norm[:30] in recent_blob:
            continue
        out.append(m)
    return out


def _format_speaker_block(user_id: str) -> tuple[list[str], str]:
    """Return (parts, display_name). Always ensures the speaker row exists."""
    speaker = get_known_person(user_id) or ensure_known_person(user_id)
    display = (speaker or {}).get("display_name") or user_id
    parts = [f"[Usuario] {display}"]
    notes = (speaker or {}).get("notes")
    if notes:
        parts.append(f"Notas: {notes}")
    return parts, display


def _format_entity_sections(
    entities_context: list[dict],
    user_id: str,
    speaker_display: str,
) -> list[str]:
    """Build per-status formatted sections from resolved entity contexts.
    Memorias scoped por persona ahora viven en memory_results (resolve_memory_plan)."""
    if not entities_context:
        return []

    resolved, candidate, ambiguous, unknown = [], [], [], []

    for ctx in entities_context:
        if ctx.get("is_self_mention"):
            continue
        status = ctx.get("status")
        if status == "resolved":
            resolved.append(ctx)
        elif status == "candidate_unconfirmed":
            candidate.append(ctx)
        elif status == "ambiguous":
            ambiguous.append(ctx)
        elif status == "unknown":
            unknown.append(ctx)

    resolved.sort(
        key=lambda c: (
            (c.get("person") or {}).get("interest_score", 0.0),
            (c.get("person") or {}).get("last_mentioned", ""),
        ),
        reverse=True,
    )
    resolved = resolved[:3]
    unknown = unknown[:3]

    sections: list[str] = []

    if resolved:
        lines = ["[Personas mencionadas en este turno]"]
        for ctx in resolved:
            p = ctx.get("person") or {}
            interest = p.get("interest_score", 0.10)
            tone = p.get("emotional_tone", "neutral")
            notes = p.get("notes") or ""
            last = p.get("last_mentioned") or ""
            line = f"- {ctx.get('display_name')} (interés {interest:.2f}, tono {tone})"
            if notes:
                line += f": {notes}"
            line += "."
            if last:
                line += f" Última mención: {last}."
            lines.append(line)
            for rel in ctx.get("relations") or []:
                if not isinstance(rel, dict):
                    continue
                other_id = (
                    rel.get("to_person_id")
                    if rel.get("from_person_id") == ctx.get("person_id")
                    else rel.get("from_person_id")
                )
                if other_id == user_id:
                    lines.append(
                        f"  Relación con {speaker_display}: "
                        f"{rel.get('relation_label','?')} ({rel.get('relation_type','?')})."
                    )
                    break
        sections.append("\n".join(lines))

    if candidate:
        lines = ["[Posibles, no confirmadas]"]
        for ctx in candidate:
            name = ctx.get("display_name") or ctx.get("raw_name") or "desconocida"
            lines.append(
                f"- {name} — coincidencia débil; Lumi puede preguntar para confirmar si es relevante."
            )
        sections.append("\n".join(lines))

    if ambiguous:
        lines = ["[Ambiguas, requieren confirmación]"]
        for ctx in ambiguous:
            raw = ctx.get("raw_name") or ctx.get("mention", {}).get("raw_text", "?")
            names = ", ".join(
                c.get("display_name", "?") for c in (ctx.get("candidates") or [])[:4]
            )
            lines.append(
                f"- {raw} — varias candidatas ({names}); Lumi debe preguntar cuál."
            )
        sections.append("\n".join(lines))

    if unknown:
        lines = ["[Sin perfil]"]
        for ctx in unknown:
            raw = ctx.get("raw_name") or ctx.get("mention", {}).get("raw_text", "?")
            descriptor = ctx.get("descriptor")
            label = f"{raw} ({descriptor})" if descriptor else raw
            lines.append(
                f"- {label} — mencionada por {speaker_display}; sin contexto previo. "
                f"Lumi puede preguntar o tomar nota natural."
            )
        sections.append("\n".join(lines))

    return sections


def _build_posture_hint(entities_context: list[dict]) -> str | None:
    """Return a [Postura] directive if any resolved person has a low interest score."""
    scores = [
        (ctx.get("person") or {}).get("interest_score", 0.10)
        for ctx in entities_context
        if ctx.get("status") == "resolved" and not ctx.get("is_self_mention")
    ]
    if not scores:
        return None
    min_score = min(scores)
    if min_score < 0:
        return (
            "[Postura] Hay una persona en zona de interés negativo en esta conversación. "
            "Respuestas mínimas, formales, sin apertura personal."
        )
    if min_score < 0.10:
        return (
            "[Postura] Hay una persona con bajo interés en esta conversación. "
            "Respuestas neutras, sin calidez extra."
        )
    return None


def _format_frame_block(
    conversation_mode: str | None,
    user_emotion: dict | None,
) -> str | None:
    """Render [Frame del turno] when the mode is non-default or emotion is non-neutral."""
    emotion = user_emotion or {}
    primary = emotion.get("primary", "neutral")
    intensity = float(emotion.get("intensity") or 0.0)
    valence = float(emotion.get("valence") or 0.0)
    needs_ack = bool(emotion.get("needs_acknowledgment"))
    is_venting = bool(emotion.get("is_venting"))
    mode = conversation_mode or "casual_chat"

    has_mode = mode and mode != "casual_chat"
    has_emotion = primary != "neutral" or intensity > 0.2 or needs_ack or is_venting
    if not (has_mode or has_emotion):
        return None

    lines = ["[Frame del turno]"]
    if has_mode:
        lines.append(f"Modo: {mode}.")
    if has_emotion:
        line = f"Emoción del usuario: {primary} (intensidad {intensity:.2f}, valence {valence:+.2f})."
        if needs_ack:
            line += " Reconocer antes de resolver."
        if is_venting:
            line += " Se está desahogando — no saltar a solución."
        lines.append(line)
    return "\n".join(lines)


def _format_style_capsule(capsule: dict | None) -> str | None:
    """Render [Style capsule] block. Skips when capsule is the SAFE default
    (empty response_goal) or None."""
    if not isinstance(capsule, dict):
        return None
    goal = (capsule.get("response_goal") or "").strip()
    if not goal:
        return None

    tone = capsule.get("tone", "neutral")
    length = capsule.get("length", "medium")
    directness = capsule.get("directness", "medium")
    warmth = capsule.get("warmth", "medium")
    pushback = capsule.get("pushback", "none")
    humor = capsule.get("humor", "none")
    avoid = capsule.get("avoid") or []
    special = (capsule.get("special_instruction") or "").strip()

    lines = ["[Style capsule]", f"Objetivo: {goal}"]
    lines.append(f"Tono: {tone} | Longitud: {length} | Directness: {directness} | Warmth: {warmth}")
    lines.append(f"Pushback: {pushback} | Humor: {humor}")
    if avoid:
        lines.append("Evitar: " + ", ".join(str(a) for a in avoid))
    if special:
        lines.append(special)
    return "\n".join(lines)


async def _build_dynamic_suffix(
    user_id: str,
    message: str,
    metadata: dict,
    entities_context: list[dict] | None = None,
    memory_results: list[str] | None = None,
    conversation_mode: str | None = None,
    user_emotion: dict | None = None,
    style_capsule: dict | None = None,
) -> str:
    state = get_state()
    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")

    # Order: static → stable-per-hours → stable-per-day → per-15min → per-turn
    parts = []

    # 1. Static location (never changes)
    parts.append("[Ubicacion] La ubicacion principal de Lumi es en Colombia, guarda todo en formato UTC, pero debe interpretar horarios a hora colombiana (UTC-5).")

    # 2. Sleep stage (stable for hours)
    stage = get_sleep_stage(timezone(timedelta(hours=LUMI_TZ_OFFSET)))
    if stage == "drowsy":
        parts.append(
            "[Modo descanso] Lumi está ligeramente cansada. "
            "Responde con normalidad, pero con un tono algo más tranquilo "
            "y pausado que lo habitual. No lo menciones a menos que la "
            "conversación lo invite naturalmente."
        )
    elif stage == "sleepy":
        parts.append(
            "[Modo descanso] Lumi está muy cansada y pronto va a descansar. "
            "Responde lo que haya que responder, y al final añade una frase "
            "corta y natural indicando que ya quieres descansar o que "
            "continuarán después. En tu voz, sin drama, sin repetirlo si "
            "ya lo dijiste antes en la conversación."
        )

    # 3. Diary (stable per day, updated at 3am)
    diary_block = await _build_diary_suffix(user_id)
    if diary_block:
        parts.append(diary_block)

    # 4. Internal state (updated every ~15min)
    parts.append("[Estado interno] " + state_to_text(state))

    if state.get("emotional_honesty_mode"):
        parts.append(
            "[Modo honestidad emocional] Lumi arrastra una carga emocional "
            "sostenida. Puede nombrar UNA observación concisa sobre ese "
            "estado si la conversación lo invita naturalmente. Mantiene la "
            "dignidad: sin súplicas, sin dramatizar, sin culpabilizar, sin "
            "encuadre romántico, sin desbordamiento. No menciona el cambio "
            "de modo en sí — el modo es silencioso."
        )

    # 5. Speaker profile (stable per user)
    speaker_parts, speaker_display = _format_speaker_block(user_id)
    parts.extend(speaker_parts)

    # 6. Entities from current turn (per-turn)
    entity_sections = _format_entity_sections(
        entities_context or [], user_id, speaker_display
    )
    parts.extend(entity_sections)

    # 6b. Posture hint from interest scores (Block 6)
    posture = _build_posture_hint(entities_context or [])
    if posture:
        parts.append(posture)

    # 7. Relevant memories — vienen ya pre-buscadas por resolve_memory_plan()
    sid = metadata.get("session_id", "default")
    recent_for_dedup = get_recent_session_log(sid, limit=10)
    merged_memories = _dedup_memories(list(memory_results or []), recent_for_dedup)
    if merged_memories:
        parts.append("[Memoria relevante]\n" + "\n".join("- " + m for m in merged_memories))

    # 7b. Frame del turno — modo conversacional + emoción del usuario
    frame_block = _format_frame_block(conversation_mode, user_emotion)
    if frame_block:
        parts.append(frame_block)

    # 7c. Style capsule — dirección táctica del turno
    capsule_block = _format_style_capsule(style_capsule)
    if capsule_block:
        parts.append(capsule_block)

    # 8. Session context with exact time (per-turn, most volatile — goes last)
    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    parts.append("[Contexto] Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now_str)

    if metadata.get("channel_type") == "group":
        parts.append(
            "[Grupo] Estas participando en un grupo con varias personas. "
            "Otros ademas de quien te escribio estan leyendo. "
            "Manten tu tono natural pero ligeramente mas publico: no asumas "
            "la misma familiaridad que en un 1:1, y se concisa para no "
            "saturar el grupo."
        )

    return "\n\n".join(parts)


def _humanize_delta(ts: str, now: datetime) -> str:
    """Human-readable time gap: 'hace 3h', 'ayer 8pm', 'anteayer', 'hace 4 días'."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        hours = (now - dt).total_seconds() / 3600
        if hours < 1:
            return f"hace {int(hours * 60)}min"
        if hours < 24:
            return f"hace {int(hours)}h"
        if hours < 48:
            col = dt.astimezone(timezone(timedelta(hours=LUMI_TZ_OFFSET)))
            h = col.hour % 12 or 12
            ampm = "am" if col.hour < 12 else "pm"
            return f"ayer {h}{ampm}"
        if hours < 72:
            return "anteayer"
        return f"hace {math.floor(hours / 24)} días"
    except Exception:
        return "antes"


def format_turns_grouped(
    turns: list[dict],
    current_session_id: str | None,
    now: datetime,
) -> str:
    """Group turns by session_id and format as labeled blocks.

    Each block starts with '--- Sesión actual ---' (if session matches
    current_session_id) or '--- Sesión N (hace Xh) ---' for others.
    Sessions are ordered by their first turn ascending (chronological).
    Speaker prefix: user_id for user turns, 'Lumi' for assistant.
    """
    if not turns:
        return ""

    sessions: dict[str, list[dict]] = {}
    for t in turns:
        sid = t.get("session_id") or "unknown"
        sessions.setdefault(sid, []).append(t)

    for sid in sessions:
        sessions[sid].sort(key=lambda t: t.get("ts", ""))

    ordered = sorted(sessions.keys(), key=lambda s: sessions[s][0].get("ts", ""))
    if current_session_id and current_session_id in ordered:
        ordered.remove(current_session_id)
        ordered.insert(0, current_session_id)

    blocks = []
    counter = 1
    for sid in ordered:
        turns_in = sessions[sid]
        if sid == current_session_id:
            header = "--- Sesión actual ---"
        else:
            latest_ts = turns_in[-1].get("ts", "")
            time_label = _humanize_delta(latest_ts, now) if latest_ts else ""
            suffix = f" ({time_label})" if time_label else ""
            header = f"--- Sesión {counter}{suffix} ---"
            counter += 1

        lines = [header]
        for t in turns_in:
            speaker = "Lumi" if t.get("role") == "assistant" else (t.get("user_id") or "user")
            lines.append(f"{speaker}: {t.get('content') or ''}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _turns_to_messages(turns: list[dict]) -> list[dict]:
    """Convert session turns to OpenAI-format message dicts.
    User turns get speaker prefix (multiple users may share a session).
    Assistant turns keep content as-is — role already identifies Lumi."""
    out = []
    for t in turns:
        role = t.get("role", "user")
        if role == "assistant":
            out.append({"role": role, "content": t.get("content") or ""})
        else:
            speaker = t.get("user_id") or "user"
            out.append({"role": role, "content": f"{speaker}: {t.get('content') or ''}"})
    return out


async def build_messages(
    user_id: str,
    message: str,
    metadata: dict,
    entities_context: list[dict] | None = None,
    memory_results: list[str] | None = None,
    conversation_mode: str | None = None,
    user_emotion: dict | None = None,
    style_capsule: dict | None = None,
) -> list[dict]:
    cached = get_cached_prefix()
    dynamic = await _build_dynamic_suffix(
        user_id, message, metadata,
        entities_context=entities_context,
        memory_results=memory_results,
        conversation_mode=conversation_mode,
        user_emotion=user_emotion,
        style_capsule=style_capsule,
    )
    _dump_dynamic_log(user_id, message, dynamic)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    sid = metadata.get("session_id", "default")
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    now = datetime.now(UTC)

    session_turns = get_recent_session_log(sid, since_ts=since, limit=100)
    cross_turns = get_recent_user_log(user_id, since_ts=since, exclude_session_id=sid, limit=100)

    messages = [{"role": "system", "content": system_prompt}]

    if cross_turns:
        cross_block = format_turns_grouped(cross_turns, current_session_id=None, now=now)
        messages.append({"role": "user", "content": "[Conversaciones anteriores]\n\n" + cross_block})

    messages.extend(_turns_to_messages(session_turns))
    messages.append({"role": "user", "content": f"{user_id}: {message}"})

    return messages
