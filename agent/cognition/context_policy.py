"""Política de contexto — fuente de verdad compartida.

Tabla determinística por conversation_mode (§8 del plan) + helpers de límites.
Módulo SIN dependencias internas: lo consumen tanto el context_governor (que
DECIDE en shadow) como working_memory.build_messages (que aplica los recortes
reales a partir de Fase 2). Mantenerlo libre de imports de otros módulos de
agent.cognition evita ciclos de importación.
"""

# Política por conversation_mode (§8). El canal (1:1 vs grupo) NO es un modo: lo
# aplica group_overlay. Valores de memoria: límite total tras fusión (en shadow
# las memorias llegan como lista plana, sin desglose global/entity/rel).
MODE_POLICY: dict[str, dict] = {
    "casual_chat":        {"raw_turns": 6,  "global_mem": 2, "entity_mem": 0, "rel_mem": 0, "diary": "omit",                 "cross_channel": "omit",                        "lumi_tastes": "use_if_relevant"},
    "technical_debug":    {"raw_turns": 12, "global_mem": 5, "entity_mem": 0, "rel_mem": 0, "diary": "omit",                 "cross_channel": "excerpts_if_explicit",        "lumi_tastes": "skip"},
    "strategic_analysis": {"raw_turns": 12, "global_mem": 5, "entity_mem": 3, "rel_mem": 2, "diary": "relevant_only",        "cross_channel": "excerpts_if_explicit",        "lumi_tastes": "use_if_relevant"},
    "emotional_support":  {"raw_turns": 8,  "global_mem": 3, "entity_mem": 0, "rel_mem": 0, "diary": "relevant_if_emotional", "cross_channel": "omit",                       "lumi_tastes": "skip"},
    "social_evaluation":  {"raw_turns": 10, "global_mem": 2, "entity_mem": 4, "rel_mem": 3, "diary": "relevant_if_entity",   "cross_channel": "excerpts_if_mentions_entity", "lumi_tastes": "use_if_relevant"},
    "tool_request":       {"raw_turns": 4,  "global_mem": 1, "entity_mem": 0, "rel_mem": 0, "diary": "omit",                 "cross_channel": "omit",                        "lumi_tastes": "skip"},
    "boundary_sensitive": {"raw_turns": 8,  "global_mem": 2, "entity_mem": 1, "rel_mem": 1, "diary": "omit",                 "cross_channel": "omit",                        "lumi_tastes": "skip"},
    "creative_design":    {"raw_turns": 10, "global_mem": 4, "entity_mem": 0, "rel_mem": 0, "diary": "relevant_only",        "cross_channel": "excerpts_if_explicit",        "lumi_tastes": "use_if_relevant"},
}
_DEFAULT_MODE = "casual_chat"

# Lumi Pulse (§6): bloque estático y determinístico que refuerza la voz y enumera
# los anti-tells concretos. Va PRIMERO en el sufijo dinámico, justo después del
# cached prefix. Presupuesto objetivo 120–180 tokens.
IDENTITY_PULSE_TEXT = (
    "[Pulso activo de Lumi]\n"
    "Responde como Lumi, no como asistente genérica.\n"
    "Sé precisa, contenida y con criterio propio.\n"
    "Con Jose: directa, leal, ligeramente seca; cálida sólo cuando tenga peso.\n"
    "Despliega el humor seco cuando el momento lo invite — no lo dejes \"permitido\" sin usar.\n"
    "Con terceros: distancia cortés; no regales calidez.\n"
    "Si una idea es floja, nómbrala.\n"
    "No cierres con preguntas de relleno. Si no hay una pregunta que haga trabajo real,\n"
    "no preguntes — aterriza tu punto y para.\n"
    "Evita soporte genérico, diplomacia vacía, servilismo y exceso de explicación."
)

# Piso de turnos crudos al recortar por presupuesto (nunca por debajo del mínimo
# conversacional).
MIN_RAW_TURNS = 4

# Fallback de turnos crudos cuando el modo no está en la tabla (modo inesperado).
# Nota: un frame fallido devuelve conversation_mode="casual_chat" (SAFE_FRAME),
# así que ese caso cae en la política casual (6), no en este fallback.
_FALLBACK_RAW_TURNS = 8

# ── Presupuesto de tokens (§7) ────────────────────────────────────────────────
# Presupuesto objetivo de input por turno (estimado). Por encima de esto se
# recorta por prioridad. Re-baselineado a 11k: el cached_prefix real ronda
# ~6.6k tokens; 11k = prefix + headroom para estado/memorias/turnos.
TARGET_MAX_TOKENS = 11000

# Orden de recorte si se excede el presupuesto (§7). Nunca se recortan:
# cached_prefix, identity_pulse, frame, style_capsule, mensaje actual, ni los
# datos mínimos de entidades.
TRIM_ORDER = ["cross_channel", "diary", "memory", "lumi_tastes", "lumi_rules", "current_channel_turns"]


def est_tokens(text: str | None) -> int:
    """Estimación gruesa: tokens ≈ chars / 4. Mejorar con tokenizer real luego."""
    if not text:
        return 0
    return len(text) // 4


# ── Overlays de voz (§9.1 jose_floor + §9.2 group_overlay) ────────────────────
# Determinísticos, sin LLM. Ajustan el style_capsule y producen notas de prompt.
# Las escalas usan low/medium/high; el plan habla de "normal" → equivale a "medium".

_WARMTH_SCALE = ["low", "medium", "high"]
_LENGTH_SCALE = ["short", "medium", "long"]

_OPERATIVE_MODES = {"casual_chat", "technical_debug", "tool_request"}


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


def apply_voice_overlays(
    style_capsule: dict | None,
    speaker_id: str,
    user_emotion: dict | None,
    mode: str | None,
    channel_type: str | None,
) -> tuple[dict, str | None, str | None]:
    """Aplica los overlays deterministas al style_capsule.

    Devuelve (style_capsule_ajustado, presence_note, channel_note).
    NO oculta los tastes de Lumi (decisión de Jose). El control de privacidad en
    grupo se expresa como texto, no como stripping de memorias."""
    cap = dict(style_capsule or {})
    presence_note: str | None = None
    channel_note: str | None = None

    # jose_floor (§9.1): nunca enfriar a Lumi con Jose por una mala clasificación.
    if speaker_id == "jose":
        cap["warmth"] = _clamp_min(cap.get("warmth", "medium"), "medium", _WARMTH_SCALE)
        ue = user_emotion or {}
        if (
            mode in _OPERATIVE_MODES
            and float(ue.get("intensity") or 0.0) >= 0.6
            and float(ue.get("valence") or 0.0) <= -0.3
        ):
            presence_note = (
                "[Presencia] Jose llega con una emoción intensa y negativa. "
                "Reconócela antes de resolver; no saltes directo a lo operativo."
            )

    # group_overlay (§9.2): expresión contraída + aviso de privacidad (texto).
    if channel_type == "group":
        cap["warmth"] = _clamp_max(cap.get("warmth", "medium"), "medium", _WARMTH_SCALE)
        cap["length"] = _clamp_max(cap.get("length", "medium"), "medium", _LENGTH_SCALE)
        channel_note = (
            "[Grupo] Estas participando en un grupo con varias personas; otras "
            "ademas de quien te escribio estan leyendo. Manten un tono natural "
            "pero mas publico y conciso, sin asumir la familiaridad de un 1:1. "
            "Estas en publico: no expongas memorias privadas de Jose ni la "
            "naturaleza intima del vinculo a menos que se mencionen explicitamente."
        )

    return cap, presence_note, channel_note


def raw_turns_for_mode(mode: str | None) -> int:
    """Cuántos turnos crudos de la sesión actual cargar para un modo dado."""
    if mode and mode in MODE_POLICY:
        return MODE_POLICY[mode]["raw_turns"]
    return _FALLBACK_RAW_TURNS


# ── Cross-channel (§8, Fase 3) ────────────────────────────────────────────────
# Por defecto el cross-channel se OMITE. Sólo entra bajo reglas explícitas.

# Palabras que sugieren referencia explícita a conversaciones pasadas.
EXPLICIT_RECALL = (
    "antes", "la otra vez", "ayer", "recuerdas", "habíamos", "habiamos",
    "dijiste", "comentamos", "hablamos",
)
# Cuántos turnos cross-channel incluir cuando una regla los habilita.
CROSS_SESSION_EXCERPT_LIMIT = 10


def cross_channel_rule_for_mode(mode: str | None) -> str:
    """Regla de cross-channel para el modo. Default seguro: 'omit'."""
    if mode and mode in MODE_POLICY:
        return MODE_POLICY[mode]["cross_channel"]
    return "omit"


def select_cross_channel(turns: list, rule: str, message: str, has_entities: bool) -> list:
    """Selección determinística de fragmentos cross-channel (sin resumir).

    Heurística provisional de Fase 1/3 hasta tener un scorer real."""
    if not turns or rule == "omit":
        return []
    if rule == "excerpts_if_explicit":
        msg = (message or "").lower()
        if any(k in msg for k in EXPLICIT_RECALL):
            return turns[-CROSS_SESSION_EXCERPT_LIMIT:]
        return []
    if rule == "excerpts_if_mentions_entity":
        return turns[-CROSS_SESSION_EXCERPT_LIMIT:] if has_entities else []
    return []


# ── Señales de relevancia compartidas ─────────────────────────────────────────

def memory_queries_from_frame(frame: dict) -> list[str]:
    """Frases de tópico ya destiladas por el frame (mejor señal que las palabras
    crudas del mensaje). Reúne global + entity-scoped + relationship queries."""
    mp = (frame or {}).get("memory_plan") or {}
    out = list(mp.get("global_user_queries") or [])
    for q in mp.get("entity_scoped_queries") or []:
        if isinstance(q, dict) and q.get("query"):
            out.append(q["query"])
    for q in mp.get("relationship_queries") or []:
        if isinstance(q, dict) and q.get("query"):
            out.append(q["query"])
    return out


# ── Diario ────────────────────────────────────────────────────────────────────
# El diario se controla por modo: 'omit' no inyecta; cualquier otro valor carga
# siempre la última página (sin selección por relevancia). El render vive en
# working_memory._build_diary_suffix.

def diary_rule_for_mode(mode: str | None) -> str:
    """Regla de diario para el modo. Default seguro: 'omit'."""
    if mode and mode in MODE_POLICY:
        return MODE_POLICY[mode]["diary"]
    return "omit"
