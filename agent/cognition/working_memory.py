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
from agent.cognition.context_policy import (
    raw_turns_for_mode,
    cross_session_rule_for_mode,
    select_cross_session,
    diary_rule_for_mode,
    select_diary,
    entity_names_from_context,
    apply_voice_overlays,
    IDENTITY_PULSE_TEXT,
    TARGET_MAX_TOKENS,
    TRIM_ORDER,
    MIN_RAW_TURNS,
    est_tokens,
)
from agent.evolution import get_injector
from agent.substrate.logger import get_logger
import math

logger = get_logger("agent.context")

UTC = timezone.utc
SOUL_PATH = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"
_DYNAMIC_LOG_PATH = Path("data/logs/dynamic.log")

_cached_prefix = None


def _dump_dynamic_log(
    user_id: str,
    message: str,
    dynamic: str,
    budget: dict | None = None,
    trimmed: list | None = None,
) -> None:
    """Overwrite data/logs/dynamic.log with the latest dynamic suffix.
    Fase 6: incluye el presupuesto real (post-recorte) y qué se recortó."""
    try:
        _DYNAMIC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"[dynamic_suffix {datetime.now(UTC).isoformat(timespec='seconds')} UTC]",
            f"user_id: {user_id}",
            f"message: {message}",
        ]
        if budget is not None:
            total = budget.get("total_input_tokens_estimated")
            lines.append(f"budget_total_est: {total} (target {TARGET_MAX_TOKENS})")
            parts = ", ".join(
                f"{k}={v}" for k, v in budget.items()
                if k != "total_input_tokens_estimated"
            )
            lines.append(f"budget: {parts}")
            lines.append(f"trimmed: {trimmed or []}")
        header = "\n".join(lines) + f"\n{'-' * 80}\n"
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

async def _build_diary_suffix(
    user_id: str,
    conversation_mode: str | None = None,
    memory_queries: list[str] | None = None,
    entity_names: list[str] | None = None,
    user_emotion: dict | None = None,
) -> str | None:
    """Fase 4: el diario se controla por modo. Pool = 7 entradas más recientes;
    se seleccionan 1–3 relevantes (o se omite el bloque si no hay relevancia).
    La relevancia se mide contra las queries del memory_plan + nombres de
    entidad, salvo la rama emocional que prioriza recencia."""
    rule = diary_rule_for_mode(conversation_mode)
    if rule == "omit":
        return None
    diary = await read_recent_diary_entries(user_id=user_id, limit=7)
    if not diary:
        return None
    selected = select_diary(diary, rule, memory_queries, entity_names, user_emotion)
    if not selected:
        return None
    # Render cronológico (más antigua primero).
    selected = sorted(selected, key=lambda e: e.get("talked_at_ts") or datetime.min.replace(tzinfo=UTC))
    lines = []
    for entry in selected:
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
    speaker = speaker or {}
    display = speaker.get("display_name") or user_id
    parts = [f"[Usuario] {display}"]

    # Perfil base del hablante: ubicación/zona horaria/idioma/unidades. Ya se
    # inyecta al frame analyzer (frame._build_speaker_card) para fundar tool args
    # y memory queries; aquí lo damos también al LLM principal para que interprete
    # "mañana"/horarios en hora local y responda en el idioma/unidades del usuario.
    profile = [
        ("ubicación", speaker.get("location")),
        ("zona horaria", speaker.get("timezone")),
        ("idioma", speaker.get("language")),
        ("unidades", speaker.get("units")),
    ]
    profile_line = " | ".join(f"{label}: {val}" for label, val in profile if val)
    if profile_line:
        parts.append(profile_line)

    notes = speaker.get("notes")
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
    memory_queries: list[str] | None = None,
) -> list[tuple[str, str]]:
    state = get_state()
    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")

    # Orden del sufijo dinámico (§12): el Pulso va primero (justo tras el cached
    # prefix) para reforzar la voz; el diario baja a la zona del frame; el
    # contexto operativo/ubicación/grupo cierran. Tastes de Lumi: TODO (skip).
    # Devuelve bloques nombrados (name, text) para que build_messages pueda
    # presupuestar y recortar por prioridad (§7).
    blocks: list[tuple[str, str]] = []

    # 1. Lumi Pulse — refuerzo de voz, estático, primero (§6). No se recorta.
    blocks.append(("identity_pulse", IDENTITY_PULSE_TEXT))

    # 2. Estado interno (cada ~15min) + modificadores de estado adyacentes.
    blocks.append(("state", "[Estado interno] " + state_to_text(state)))

    stage = get_sleep_stage(timezone(timedelta(hours=LUMI_TZ_OFFSET)))
    if stage == "drowsy":
        blocks.append((
            "sleep",
            "[Modo descanso] Lumi está ligeramente cansada. "
            "Responde con normalidad, pero con un tono algo más tranquilo "
            "y pausado que lo habitual. No lo menciones a menos que la "
            "conversación lo invite naturalmente.",
        ))
    elif stage == "sleepy":
        blocks.append((
            "sleep",
            "[Modo descanso] Lumi está muy cansada y pronto va a descansar. "
            "Responde lo que haya que responder, y al final añade una frase "
            "corta y natural indicando que ya quieres descansar o que "
            "continuarán después. En tu voz, sin drama, sin repetirlo si "
            "ya lo dijiste antes en la conversación.",
        ))

    if state.get("emotional_honesty_mode"):
        blocks.append((
            "honesty",
            "[Modo honestidad emocional] Lumi arrastra una carga emocional "
            "sostenida. Puede nombrar UNA observación concisa sobre ese "
            "estado si la conversación lo invita naturalmente. Mantiene la "
            "dignidad: sin súplicas, sin dramatizar, sin culpabilizar, sin "
            "encuadre romántico, sin desbordamiento. No menciona el cambio "
            "de modo en sí — el modo es silencioso.",
        ))

    # 3. Perfil del hablante.
    speaker_parts, speaker_display = _format_speaker_block(user_id)
    if speaker_parts:
        blocks.append(("profile_core", "\n".join(speaker_parts)))

    # 4. Entidades del turno + postura por interés.
    entity_sections = _format_entity_sections(
        entities_context or [], user_id, speaker_display
    )
    if entity_sections:
        blocks.append(("entities", "\n\n".join(entity_sections)))

    posture = _build_posture_hint(entities_context or [])
    if posture:
        blocks.append(("posture", posture))

    # 5. Memoria relevante — ya pre-buscada por resolve_memory_plan().
    sid = metadata.get("session_id", "default")
    recent_for_dedup = get_recent_session_log(sid, limit=10)
    merged_memories = _dedup_memories(list(memory_results or []), recent_for_dedup)
    if merged_memories:
        blocks.append((
            "memory",
            "[Memoria relevante]\n" + "\n".join("- " + m for m in merged_memories),
        ))

    # 6. Evolución de Lumi — gustos y heurísticas consolidados, recuperados por
    #    similitud semántica (top-N). Cada bloque va envuelto: un fallo de
    #    embeddings nunca debe tumbar el turno.
    injector = get_injector()
    recent_context = " ".join(
        t.get("content", "") for t in recent_for_dedup[-4:]
    ).strip()

    try:
        tastes = await injector.select_tastes(message, recent_context, top_k=5)
        if tastes:
            blocks.append((
                "lumi_tastes",
                "[Gustos relevantes]\n"
                + "\n".join("- " + t["content"] for t in tastes),
            ))
    except Exception as e:  # noqa: BLE001 — best-effort, no bloqueante
        logger.warning("evolution.injection.tastes.failed: %s", e)

    try:
        ctx_class = conversation_mode or "casual_chat"
        rules = await injector.select_rules(message, ctx_class, top_k=3)
        if rules:
            blocks.append((
                "lumi_rules",
                "[Heurísticas activas]\n"
                + "\n".join("- " + r["heuristic"] for r in rules),
            ))
    except Exception as e:  # noqa: BLE001 — best-effort, no bloqueante
        logger.warning("evolution.injection.rules.failed: %s", e)

    # 7. Diario reciente relevante (§4) — baja a la zona del frame.
    diary_block = await _build_diary_suffix(
        user_id,
        conversation_mode=conversation_mode,
        memory_queries=memory_queries,
        entity_names=entity_names_from_context(entities_context),
        user_emotion=user_emotion,
    )
    if diary_block:
        blocks.append(("diary", diary_block))

    # 8. Frame del turno — modo conversacional + emoción del usuario. No se recorta.
    frame_block = _format_frame_block(conversation_mode, user_emotion)
    if frame_block:
        blocks.append(("frame", frame_block))

    # 9. Style capsule — con overlays deterministas aplicados (jose_floor +
    #    group_overlay): clamps de warmth/length + notas de presencia/grupo.
    adj_capsule, presence_note, channel_note = apply_voice_overlays(
        style_capsule, user_id, user_emotion, conversation_mode,
        metadata.get("channel_type"),
    )
    capsule_block = _format_style_capsule(adj_capsule)
    if capsule_block:
        blocks.append(("style_capsule", capsule_block))

    if presence_note:
        blocks.append(("presence", presence_note))

    # 10. Contexto operativo (ubicación + canal/sesión/hora) + grupo — cierran.
    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    blocks.append((
        "operational",
        "[Contexto] La ubicacion principal de Lumi es en Colombia (UTC-5); guarda todo "
        "en UTC pero interpreta horarios a hora colombiana. "
        "Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now_str,
    ))

    if channel_note:
        blocks.append(("group", channel_note))

    return blocks


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
    memory_queries: list[str] | None = None,
) -> list[dict]:
    cached = get_cached_prefix()
    blocks = await _build_dynamic_suffix(
        user_id, message, metadata,
        entities_context=entities_context,
        memory_results=memory_results,
        conversation_mode=conversation_mode,
        user_emotion=user_emotion,
        style_capsule=style_capsule,
        memory_queries=memory_queries,
    )

    sid = metadata.get("session_id", "default")
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    now = datetime.now(UTC)

    # Fase 2: el historial crudo de la sesión actual se limita por modo
    # (antes 100 fijo). La tabla vive en context_policy (fuente única). El
    # frame fallido devuelve conversation_mode="casual_chat", que cae en su
    # política (6); modos inesperados usan el fallback (8).
    turn_limit = raw_turns_for_mode(conversation_mode)
    session_turns = get_recent_session_log(sid, since_ts=since, limit=turn_limit)

    # Fase 3: el cross-session se OMITE por defecto. Sólo se consulta e incluye
    # bajo reglas explícitas por modo (excerpts_if_explicit / _mentions_entity),
    # con fragmentos crudos (sin resumir). En 'omit' ni siquiera se toca la DB.
    cross_rule = cross_session_rule_for_mode(conversation_mode)
    if cross_rule == "omit":
        cross_turns = []
    else:
        cross_all = get_recent_user_log(user_id, since_ts=since, exclude_session_id=sid, limit=100)
        cross_turns = select_cross_session(
            cross_all, cross_rule, message, bool(entities_context)
        )

    # ── Fase 6: presupuesto de tokens + recorte por prioridad (§7) ────────────
    # Nunca se recortan: cached_prefix, identity_pulse, frame, style_capsule,
    # mensaje actual, entidades. Orden de recorte en TRIM_ORDER.
    prefix_tok = est_tokens(cached)
    current_text = f"{user_id}: {message}"
    current_tok = est_tokens(current_text)
    block_tok = {name: est_tokens(text) for name, text in blocks}

    def _cross_text() -> str:
        if not cross_turns:
            return ""
        return "[Conversaciones anteriores]\n\n" + format_turns_grouped(
            cross_turns, current_session_id=None, now=now
        )

    cross_tok = est_tokens(_cross_text())
    turns_msgs = _turns_to_messages(session_turns)

    def _turns_tok() -> int:
        return sum(est_tokens(m["content"]) for m in turns_msgs)

    def _total() -> int:
        return prefix_tok + sum(block_tok.values()) + cross_tok + _turns_tok() + current_tok

    trimmed: list[str] = []
    for unit in TRIM_ORDER:
        if _total() <= TARGET_MAX_TOKENS:
            break
        if unit == "cross_session":
            if cross_turns:
                cross_turns = []
                cross_tok = 0
                trimmed.append("cross_session")
        elif unit in ("diary", "memory", "lumi_tastes", "lumi_rules"):
            if unit in block_tok:
                blocks = [(n, t) for n, t in blocks if n != unit]
                block_tok.pop(unit, None)
                trimmed.append(unit)
        elif unit == "current_session_turns":
            n_trim = 0
            while _total() > TARGET_MAX_TOKENS and len(session_turns) > MIN_RAW_TURNS:
                session_turns = session_turns[1:]  # descarta el más antiguo
                turns_msgs = _turns_to_messages(session_turns)
                n_trim += 1
            if n_trim:
                trimmed.append(f"current_session_turns:{n_trim}")

    dynamic = "\n\n".join(text for _, text in blocks)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    budget = dict(block_tok)
    budget["cached_prefix"] = prefix_tok
    budget["cross_session"] = cross_tok
    budget["current_session_turns"] = _turns_tok()
    budget["current_message"] = current_tok
    budget["total_input_tokens_estimated"] = _total()
    _dump_dynamic_log(user_id, message, dynamic, budget=budget, trimmed=trimmed)

    messages = [{"role": "system", "content": system_prompt}]
    if cross_turns:
        messages.append({"role": "user", "content": _cross_text()})
    messages.extend(turns_msgs)
    messages.append({"role": "user", "content": current_text})

    return messages
