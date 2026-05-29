"""Context Governor — Fase 1 (Shadow Mode).

Capa 100% determinística que DECIDE cuánto contexto entraría al prompt de Lumi
por turno: política por modo (§8), presupuestos (§7) y overlays deterministas
(jose_floor §9.1, group_overlay §9.2).

EN FASE 1 NO CAMBIA EL OUTPUT. select() + overlays sólo producen un
SelectedContext que se loguea a data/logs/governor.log para medir tokens reales
y construir la matriz de confusión de conversation_mode. La integración real en
build_messages llega en fases posteriores.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.substrate.logger import get_logger
from agent.cognition.working_memory import format_turns_grouped
from agent.cognition.context_pack import ContextPack
from agent.cognition.context_policy import (
    MODE_POLICY, _DEFAULT_MODE, MIN_RAW_TURNS, TARGET_MAX_TOKENS, est_tokens,
    select_cross_session, select_diary, memory_queries_from_frame,
    entity_names_from_context,
)

logger = get_logger("agent.governor")

UTC = timezone.utc
_GOVERNOR_LOG_PATH = Path("data/logs/governor.log")

# La tabla MODE_POLICY, los límites de turnos, el presupuesto (TARGET_MAX_TOKENS)
# y est_tokens viven en context_policy (fuente de verdad compartida con
# build_messages para evitar ciclos de importación).

# Escalas ordenadas para clamps de perillas. La capsule usa low/medium/high; el
# plan habla de "normal" → equivale a "medium".
_WARMTH_SCALE = ["low", "medium", "high"]
_LENGTH_SCALE = ["short", "medium", "long"]


@dataclass
class SelectedContext:
    mode: str
    style_capsule: dict
    raw_turns_cap: int = 0           # límite de la política para el modo
    raw_turns_available: int = 0     # turnos que existían en la sesión
    raw_turns_selected: int = 0      # = min(cap, available) tras recorte por presupuesto
    raw_turns_budget_trimmed: int = 0  # cuántos quitó el recorte por presupuesto (no por disponibilidad)
    diary_selected: int = 0
    cross_session_selected: int = 0
    memories_selected: int = 0
    lumi_tastes_selected: int = 0
    budget: dict = field(default_factory=dict)
    jose_floor_applied: bool = False
    group_overlay_applied: bool = False
    presence_upgrade: bool = False
    strip_private_jose_memories: bool = False
    # should_respond se deja en True siempre: la supresión de turno en grupos
    # queda EXCLUIDA en esta fase — los grupos ya se gobiernan por su propia
    # máquina de estados aparte.
    should_respond: bool = True
    notes: list = field(default_factory=list)


def _clamp_min(value: str, floor: str, scale: list[str]) -> str:
    try:
        return value if scale.index(value) >= scale.index(floor) else floor
    except ValueError:
        return floor


def _clamp_max(value: str, ceil: str, scale: list[str]) -> str:
    try:
        return value if scale.index(value) <= scale.index(ceil) else ceil
    except ValueError:
        return ceil


def _render_turns(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        speaker = "Lumi" if t.get("role") == "assistant" else (t.get("user_id") or "user")
        lines.append(f"{speaker}: {t.get('content') or ''}")
    return "\n".join(lines)


def _select_diary(pack: ContextPack, rule: str) -> list:
    """Delega en la selección determinística compartida de context_policy,
    usando las queries del memory_plan + nombres de entidad como señal."""
    return select_diary(
        pack.diary_entries or [],
        rule,
        memory_queries_from_frame(pack.frame),
        entity_names_from_context(pack.entities_context),
        pack.frame.get("user_emotion") or {},
    )


def _select_cross_session(pack: ContextPack, rule: str) -> list:
    """Delega en la selección determinística compartida de context_policy."""
    return select_cross_session(
        pack.cross_session_turns or [], rule, pack.message, bool(pack.entities_context)
    )


def select(pack: ContextPack) -> SelectedContext:
    """Aplica política por modo + presupuestos. Determinístico, sin LLM."""
    mode = pack.frame.get("conversation_mode") or _DEFAULT_MODE
    policy = MODE_POLICY.get(mode, MODE_POLICY[_DEFAULT_MODE])

    sel = SelectedContext(mode=mode, style_capsule=dict(pack.style_capsule or {}))

    # --- Turnos crudos de la sesión actual: últimos N ---
    # raw_turns_selected aquí refleja sólo la DISPONIBILIDAD (min(cap, existentes)).
    # El recorte por presupuesto, si ocurre, se contabiliza aparte más abajo.
    n_turns = policy["raw_turns"]
    selected_turns = pack.current_session_turns[-n_turns:] if n_turns else []
    sel.raw_turns_cap = n_turns
    sel.raw_turns_available = len(pack.current_session_turns)
    sel.raw_turns_selected = len(selected_turns)

    # --- Memorias: cap total tras fusión (sin desglose en shadow) ---
    mem_limit = policy["global_mem"] + policy["entity_mem"] + policy["rel_mem"]
    selected_memories = pack.memories[:mem_limit]
    sel.memories_selected = len(selected_memories)

    # --- Diario ---
    selected_diary = _select_diary(pack, policy["diary"])
    sel.diary_selected = len(selected_diary)

    # --- Cross-session ---
    selected_cross = _select_cross_session(pack, policy["cross_session"])
    sel.cross_session_selected = len(selected_cross)

    # --- Tastes de Lumi (TODO: siempre vacío en esta fase) ---
    use_tastes = policy["lumi_tastes"] != "skip"
    selected_tastes = pack.lumi_tastes if use_tastes else []
    sel.lumi_tastes_selected = len(selected_tastes)

    # --- Presupuesto por bloque (tokens estimados) ---
    memories_text = (
        "[Memoria relevante]\n" + "\n".join("- " + m for m in selected_memories)
        if selected_memories else ""
    )
    diary_text = "\n\n".join(e.get("summary") or "" for e in selected_diary)
    cross_text = format_turns_grouped(selected_cross, current_session_id=None, now=datetime.now(UTC)) if selected_cross else ""
    turns_text = _render_turns(selected_turns)

    budget = {
        "cached_prefix": est_tokens(pack.cached_prefix),
        "identity_pulse": est_tokens(pack.identity_pulse_text),
        "state": est_tokens(pack.state_text),
        "profile": est_tokens(pack.profile_text),
        "entities": est_tokens(pack.entities_text),
        "memories": est_tokens(memories_text),
        "lumi_tastes": 0,  # vacío en Fase 1
        "diary": est_tokens(diary_text),
        "frame": est_tokens(pack.frame_block_text),
        "style_capsule": est_tokens(pack.style_capsule_text),
        "operational": est_tokens(pack.operational_text),
        "current_session_turns": est_tokens(turns_text),
        "cross_session": est_tokens(cross_text),
    }
    budget["total_input_tokens_estimated"] = sum(budget.values())

    # --- Recorte por prioridad (§7) si excede el presupuesto objetivo ---
    # Nunca se recorta: cached_prefix, identity_pulse, frame, style_capsule,
    # mensaje actual. Orden: cross_session → diary → memorias → lumi_tastes →
    # turnos crudos (hasta el mínimo del modo) → profile_relevant.
    trim_order = ["cross_session", "diary", "memories", "lumi_tastes", "current_session_turns"]
    for block in trim_order:
        if budget["total_input_tokens_estimated"] <= TARGET_MAX_TOKENS:
            break
        if block == "current_session_turns":
            # Recortar turnos hasta el piso mínimo. Cuenta SOLO lo quitado por
            # presupuesto (distinto de tener pocos turnos por disponibilidad).
            trimmed_here = 0
            while sel.raw_turns_selected > MIN_RAW_TURNS and budget["total_input_tokens_estimated"] > TARGET_MAX_TOKENS:
                selected_turns = selected_turns[1:]
                sel.raw_turns_selected = len(selected_turns)
                trimmed_here += 1
                budget["current_session_turns"] = est_tokens(_render_turns(selected_turns))
                budget["total_input_tokens_estimated"] = sum(v for k, v in budget.items() if k != "total_input_tokens_estimated")
            if trimmed_here:
                sel.raw_turns_budget_trimmed = trimmed_here
                sel.notes.append(f"budget_trimmed:current_session_turns:{trimmed_here}")
        elif budget.get(block, 0) > 0:
            budget["total_input_tokens_estimated"] -= budget[block]
            budget[block] = 0
            if block == "diary":
                sel.diary_selected = 0
            elif block == "cross_session":
                sel.cross_session_selected = 0
            elif block == "memories":
                sel.memories_selected = 0
            elif block == "lumi_tastes":
                sel.lumi_tastes_selected = 0
            sel.notes.append(f"trimmed:{block}")

    sel.budget = budget
    return sel


def apply_jose_floor(selected: SelectedContext, frame: dict, speaker_id: str) -> SelectedContext:
    """Protege el núcleo relacional con Jose (§9.1). Determinístico."""
    if speaker_id != "jose":
        return selected

    # 1. Piso de calidez: nunca por debajo de 'medium' (= 'normal') hacia Jose.
    selected.style_capsule["warmth"] = _clamp_min(
        selected.style_capsule.get("warmth", "medium"), "medium", _WARMTH_SCALE
    )

    # 2. Re-clasificación de presencia emocional: si el modo salió operativo pero
    #    la emoción del usuario es intensa y negativa, marcar presencia emocional
    #    (acknowledge-first). En shadow sólo se marca el flag.
    ue = frame.get("user_emotion") or {}
    operativo = selected.mode in {"casual_chat", "technical_debug", "tool_request"}
    if operativo and float(ue.get("intensity") or 0.0) >= 0.6 and float(ue.get("valence") or 0.0) <= -0.3:
        selected.presence_upgrade = True
        selected.notes.append("jose_floor:presence_upgrade")

    selected.jose_floor_applied = True
    return selected


def apply_group_overlay(selected: SelectedContext, metadata: dict) -> SelectedContext:
    """Contrae la expresión en canal grupal (§9.2). Determinístico.

    NOTA: la regla de silencio (should_respond=False) queda EXCLUIDA — los grupos
    ya se gobiernan por su propia máquina de estados aparte."""
    if metadata.get("channel_type") != "group":
        return selected

    # 1. Expresión contraída.
    selected.style_capsule["warmth"] = _clamp_max(
        selected.style_capsule.get("warmth", "medium"), "medium", _WARMTH_SCALE
    )
    selected.style_capsule["length"] = _clamp_max(
        selected.style_capsule.get("length", "medium"), "medium", _LENGTH_SCALE
    )

    # 2. Privacidad: no exponer memorias privadas de Jose ni el plano íntimo.
    selected.strip_private_jose_memories = True
    selected.lumi_tastes_selected = 0

    selected.group_overlay_applied = True
    return selected


def log_governor_shadow(pack: ContextPack, selected: SelectedContext, frame: dict) -> None:
    """Anexa un registro JSONL por turno a data/logs/governor.log (§13).

    Archivo dedicado (no dynamic.log) para facilitar el muestreo y la matriz de
    confusión de conversation_mode."""
    try:
        policy = MODE_POLICY.get(selected.mode, MODE_POLICY[_DEFAULT_MODE])
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "user_id": pack.user_id,
            "message": pack.message[:200],
            "context_budget": selected.budget,
            "context_selection": {
                "conversation_mode": selected.mode,
                "raw_turns_cap": selected.raw_turns_cap,
                "raw_turns_available": selected.raw_turns_available,
                "raw_turns_selected": selected.raw_turns_selected,
                "raw_turns_budget_trimmed": selected.raw_turns_budget_trimmed,
                "diary_entries_selected": selected.diary_selected,
                "cross_session_fragments_selected": selected.cross_session_selected,
                "memories_selected": selected.memories_selected,
                "global_mem_limit": policy["global_mem"],
                "entity_mem_limit": policy["entity_mem"],
                "relationship_mem_limit": policy["rel_mem"],
                "lumi_tastes_selected": selected.lumi_tastes_selected,
                "jose_floor_applied": selected.jose_floor_applied,
                "group_overlay_applied": selected.group_overlay_applied,
                "presence_upgrade": selected.presence_upgrade,
                "trailing_nudge": False,
                "notes": selected.notes,
            },
            "frame_audit": {
                "conversation_mode": frame.get("conversation_mode"),
                "user_emotion": frame.get("user_emotion"),
                "tool_plan_needs_tool": (frame.get("tool_plan") or {}).get("needs_tool"),
            },
        }
        _GOVERNOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _GOVERNOR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[governor_log] write failed: {e}")
