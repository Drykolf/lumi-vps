"""Context Pack — Fase 1 (Shadow Mode).

Reúne en una estructura los candidatos de contexto disponibles para un turno.
NO decide nada: la política de selección/recorte vive en context_governor.py.

Reusa los helpers de render existentes en working_memory.py para que el
presupuesto de tokens estimado en shadow coincida con lo que realmente se
inyectaría. No añade ninguna llamada LLM: el frame ya viene resuelto y las
memorias ya vienen pre-buscadas por resolve_memory_plan().
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from agent.affect import get_state, state_to_text
from agent.memory import (
    get_recent_session_log,
    get_recent_user_log,
    read_recent_diary_entries,
)
from agent.cognition.context_policy import (
    memory_queries_from_frame,
    entity_names_from_context,
    IDENTITY_PULSE_TEXT,
)
from agent.cognition.working_memory import (
    get_cached_prefix,
    _build_diary_suffix,
    _format_speaker_block,
    _format_entity_sections,
    _dedup_memories,
    _format_frame_block,
    _format_style_capsule,
)

UTC = timezone.utc

# IDENTITY_PULSE_TEXT vive ahora en context_policy (fuente compartida); se importa
# arriba para mantener el campo del pack y evitar ciclos con working_memory.


def resolve_lumi_tastes(frame: dict, message: str) -> list:
    """Opiniones/gustos propios de Lumi por relevancia de tópico.

    # TODO Fase posterior: el subject 'lumi' aún no existe como concepto en
    # semantic.py (Mem0 es subject-centric por user_id del sujeto del hecho).
    # Por ahora siempre devuelve [] — el bloque se omite sin error.
    """
    return []


@dataclass
class ContextPack:
    frame: dict
    user_id: str
    message: str
    metadata: dict

    cached_prefix: str = ""
    identity_pulse_text: str = ""

    state_text: str = ""
    profile_text: str = ""
    operational_text: str = ""
    entities_text: str = ""
    entities_context: list = field(default_factory=list)

    memories: list = field(default_factory=list)
    lumi_tastes: list = field(default_factory=list)

    diary_entries: list = field(default_factory=list)
    diary_text: str | None = None

    frame_block_text: str | None = None
    style_capsule: dict = field(default_factory=dict)
    style_capsule_text: str | None = None

    current_session_turns: list = field(default_factory=list)
    cross_session_turns: list = field(default_factory=list)


async def build_context_pack(
    frame: dict,
    user_id: str,
    message: str,
    metadata: dict,
    entities_context: list[dict] | None = None,
    memory_results: list[str] | None = None,
) -> ContextPack:
    """Reúne todos los candidatos del turno. No decide; no llama al LLM.

    Re-lee turnos/diario de la DB (duplica lecturas de build_messages — aceptable
    en shadow; se unificará en Fase 2)."""
    entities_context = entities_context or []
    sid = metadata.get("session_id", "default")
    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")

    state = get_state()
    state_text = "[Estado interno] " + state_to_text(state)

    speaker_parts, speaker_display = _format_speaker_block(user_id)
    profile_text = "\n".join(speaker_parts)

    entity_sections = _format_entity_sections(entities_context, user_id, speaker_display)
    entities_text = "\n\n".join(entity_sections)

    recent_for_dedup = get_recent_session_log(sid, limit=10)
    memories = _dedup_memories(list(memory_results or []), recent_for_dedup)

    diary_entries = await read_recent_diary_entries(user_id=user_id, limit=7)
    diary_text = await _build_diary_suffix(
        user_id,
        conversation_mode=frame.get("conversation_mode"),
        memory_queries=memory_queries_from_frame(frame),
        entity_names=entity_names_from_context(entities_context),
        user_emotion=frame.get("user_emotion"),
    )

    frame_block_text = _format_frame_block(
        frame.get("conversation_mode"), frame.get("user_emotion")
    )
    style_capsule = frame.get("style_capsule") or {}
    style_capsule_text = _format_style_capsule(style_capsule)

    channel = metadata.get("channel", "desktop")
    operational_text = (
        "[Contexto] La ubicacion principal de Lumi es en Colombia (UTC-5); guarda todo "
        "en UTC pero interpreta horarios a hora colombiana. "
        "Canal: " + channel + " | Sesion: " + sid + " | Hora: " + now_str
    )

    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    current_session_turns = get_recent_session_log(sid, since_ts=since, limit=100)
    cross_session_turns = get_recent_user_log(
        user_id, since_ts=since, exclude_session_id=sid, limit=100
    )

    return ContextPack(
        frame=frame,
        user_id=user_id,
        message=message,
        metadata=metadata,
        cached_prefix=get_cached_prefix(),
        identity_pulse_text=IDENTITY_PULSE_TEXT,
        state_text=state_text,
        profile_text=profile_text,
        operational_text=operational_text,
        entities_text=entities_text,
        entities_context=entities_context,
        memories=memories,
        lumi_tastes=resolve_lumi_tastes(frame, message),
        diary_entries=diary_entries,
        diary_text=diary_text,
        frame_block_text=frame_block_text,
        style_capsule=style_capsule,
        style_capsule_text=style_capsule_text,
        current_session_turns=current_session_turns,
        cross_session_turns=cross_session_turns,
    )
