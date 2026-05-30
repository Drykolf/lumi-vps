"""
Turn frame analyzer — fusiona entity check + tool routing + (futuro) memory plan
+ style capsule en una sola llamada LIGHTWEIGHT.

Devuelve un JSON estructurado describiendo el turno entrante. No responde al
usuario. Fases 1-3: cycle() sólo consume `entities` y `tool_plan`. El resto del
schema se emite y loguea para preparar fases 4-6 (memory_plan, style_capsule,
rules/tastes) sin rediseñar el prompt después.
"""
import json
import re
from copy import deepcopy
from pathlib import Path

from agent.expression.synapses import chat, ModelGroup
from agent.faculties.registry import all_schemas
from agent.memory import get_recent_session_log, get_known_person
from agent.substrate.logger import get_logger

logger = get_logger("agent.frame")

_PRINCIPLES_DIR = Path(__file__).parent.parent / "identity" / "principles"
_TURN_FRAME_PROMPT_TEMPLATE = (_PRINCIPLES_DIR / "turn_frame_prompt.md").read_text(encoding="utf-8")


SAFE_FRAME: dict = {
    "schema_version": "1.0",
    "conversation_mode": "casual_chat",
    "entities": [],
    "user_emotion": {
        "primary": "neutral",
        "intensity": 0.0,
        "valence": 0.0,
        "needs_acknowledgment": False,
        "is_venting": False,
        "confidence": 0.0,
    },
    "tool_plan": {
        "needs_tool": False,
        "tool_name": None,
        "args": None,
        "confidence": 0.0,
        "reason": "",
    },
    "memory_plan": {
        "should_search_memory": True,
        "global_user_queries": [],
        "entity_scoped_queries": [],
        "relationship_queries": [],
    },
    "rule_candidates": [],
    "taste_candidates": [],
    "style_capsule": {
        "response_goal": "Responder normalmente al usuario con la personalidad base de Lumi.",
        "tone": "neutral",
        "length": "short",
        "directness": "high",
        "warmth": "low",
        "pushback": "light_if_needed",
        "humor": "dry_possible",
        "memory_usage": "use_if_relevant",
        "avoid": ["sonar como asistente genérica"],
        "special_instruction": "",
    },
}


def _safe_frame(reason: str) -> dict:
    frame = deepcopy(SAFE_FRAME)
    frame["tool_plan"]["reason"] = f"fallback: {reason}"
    return frame


def _merge_defaults(value, default):
    """Fill missing sub-keys of dict-typed defaults; coerce wrong types back to default."""
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return deepcopy(default)
        out = {}
        for k, v_default in default.items():
            out[k] = _merge_defaults(value.get(k, v_default), v_default)
        return out
    return value


def validate_turn_frame(raw) -> dict:
    """Normalize a parsed JSON dict against SAFE_FRAME defaults.
    Always returns a frame with all top-level keys present and well-typed."""
    if not isinstance(raw, dict):
        return _safe_frame("not a dict")

    frame = {}
    for key, default in SAFE_FRAME.items():
        frame[key] = _merge_defaults(raw.get(key, default), default)

    if not isinstance(frame["entities"], list):
        frame["entities"] = []
    if not isinstance(frame["rule_candidates"], list):
        frame["rule_candidates"] = []
    if not isinstance(frame["taste_candidates"], list):
        frame["taste_candidates"] = []
    if not isinstance(frame["memory_plan"].get("should_search_memory"), bool):
        frame["memory_plan"]["should_search_memory"] = True
    for key in ("global_user_queries", "entity_scoped_queries", "relationship_queries"):
        if not isinstance(frame["memory_plan"][key], list):
            frame["memory_plan"][key] = []

    plan = frame["tool_plan"]
    if not isinstance(plan["needs_tool"], bool):
        plan["needs_tool"] = False
    if plan["needs_tool"]:
        valid_names = {s["function"]["name"] for s in all_schemas()}
        if plan["tool_name"] not in valid_names:
            logger.warning(f"[frame] tool_name {plan['tool_name']!r} not in registry; dropping")
            plan["needs_tool"] = False
            plan["tool_name"] = None
            plan["args"] = None
        elif not isinstance(plan["args"], dict):
            logger.warning(f"[frame] args not a dict for tool {plan['tool_name']!r}; dropping")
            plan["needs_tool"] = False
            plan["args"] = None
    else:
        plan["tool_name"] = None
        plan["args"] = None

    return frame


def _build_speaker_card(user_id: str) -> str:
    """Render a compact one-line profile card for the speaker from known_persons.
    Used to ground tool args (e.g. add location to a weather query) and memory
    queries. Marked as a non-entity-source section. Returns "" if no profile or
    no usable fields. Best-effort: DB errors never block the frame."""
    try:
        person = get_known_person(user_id)
    except Exception as e:
        logger.warning(f"[frame] speaker card fetch failed: {e}")
        return ""
    if not person:
        return ""

    display = person.get("display_name") or user_id
    head = f"{user_id} ({display})" if display != user_id else user_id

    fields = [
        ("ubicación", person.get("location")),
        ("zona horaria", person.get("timezone")),
        ("idioma", person.get("language")),
        ("unidades", person.get("units")),
    ]
    parts = [f"{label}: {val}" for label, val in fields if val]
    if not parts:
        return ""

    return (
        "[PERFIL DEL HABLANTE — contexto base del usuario; NO extraigas entidades de aquí]\n"
        + head + " | " + " | ".join(parts)
    )


def _build_transcript(sid: str, message: str, user_id: str) -> str:
    """Build the transcript with prior turns clearly separated from the current
    message. Entity extraction must run ONLY on the current message; prior turns
    are context for tool/memory disambiguation only (see turn_frame_prompt.md)."""
    out = ""
    card = _build_speaker_card(user_id)
    if card:
        out += card + "\n\n"
    turns = get_recent_session_log(sid, limit=4)
    out += "[CONTEXTO RECIENTE — solo para desambiguar referencias; NO extraigas entidades de aquí]\n"
    if turns:
        for t in turns:
            speaker = "Lumi" if t["role"] == "assistant" else (t.get("user_id") or user_id)
            out += f"{speaker}: {t['content']}\n"
    else:
        out += "(sin turnos previos)\n"
    out += "\n[MENSAJE ACTUAL — extrae entidades SOLO de esta sección]\n"
    out += f"{user_id}: {message}"
    return out


def _build_tools_text() -> str:
    schemas = all_schemas()
    if not schemas:
        return "  (ninguna disponible)"
    lines = []
    for s in schemas:
        name = s["function"]["name"]
        desc = s["function"].get("description", name)
        lines.append(f"  '{name}': {desc}")
    return "\n".join(lines)


def _parse_json_lenient(content: str):
    """Try strict JSON first, then fall back to greedy {...} extraction."""
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def turn_frame_check(
    user_id: str,
    message: str,
    sid: str,
    metadata: dict | None = None,
    prompt_cache_key: str | None = None,
) -> dict:
    """Single LIGHTWEIGHT call: returns the structured frame for this turn.
    On any error, returns SAFE_FRAME so cycle() can continue without tool."""
    tools_text = _build_tools_text()
    system_prompt = (
        _TURN_FRAME_PROMPT_TEMPLATE
        .replace("{tools_text}", tools_text)
        .replace("{rules_index}", "  (sin reglas activas — TODO)")
        .replace("{tastes_index}", "  (sin tastes activos — TODO)")
    )

    transcript = _build_transcript(sid, message, user_id)

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=900,
            temperature=0.1,
            reasoning_effort="none",
            model_group=ModelGroup.LIGHTWEIGHT,
            prompt_cache_key=prompt_cache_key,
        )
    except Exception as e:
        logger.warning(f"[frame] LLM call failed: {e}")
        return _safe_frame(f"llm error: {e}")

    content = response.get("content", "") if isinstance(response, dict) else ""
    raw = _parse_json_lenient(content)
    if raw is None:
        logger.warning(f"[frame] JSON parse failed; content head: {content[:200]!r}")
        return _safe_frame("json parse failed")

    frame = validate_turn_frame(raw)

    plan = frame["tool_plan"]
    emo = frame["user_emotion"]
    style = frame["style_capsule"]
    logger.info(
        f"[frame] mode={frame['conversation_mode']} "
        f"entities={len(frame['entities'])} "
        f"tool={plan['needs_tool']}:{plan['tool_name']} "
        f"emotion={emo['primary']}({emo['intensity']:.2f}) "
        f"goal={style['response_goal'][:60]!r}"
    )
    return frame
