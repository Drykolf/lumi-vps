"""
Mood evaluation orchestrator — idle decay and LLM contextual evaluation.
Implements mood_policy.md evaluation guidelines.
"""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from agent.affect.mood import FIELD_RANGES, update_negative_load
from agent.substrate.logger import get_logger

logger = get_logger("affect.evaluation")

_IDENTITY_DIR = Path(__file__).parent.parent / "identity"
_PRINCIPLES_DIR = _IDENTITY_DIR / "principles"
_cached_system_prefix: str | None = None


def _get_system_prefix() -> str:
    """Lazy-load lumi_soul.md + mood_policy.md, cache once per process."""
    global _cached_system_prefix
    if _cached_system_prefix is not None:
        return _cached_system_prefix
    parts = []
    for rel in ("lumi_soul.md", "principles/mood_prompt.md"):
        fp = _IDENTITY_DIR / rel
        if fp.exists():
            parts.append(fp.read_text(encoding="utf-8"))
    _cached_system_prefix = "\n\n---\n\n".join(parts) if parts else ""
    return _cached_system_prefix

UTC = timezone.utc

# ──────────────────────────────────────────────────────────────────────────────
# Idle decay: floors & rates per mood_policy.md §199-214
# ──────────────────────────────────────────────────────────────────────────────
IDLE_FLOORS = {
    "mood_valence": 0.05,
    "mood_energy": 0.45,
    "focus_level": 0.55,
    "irritation": 0.0,
}
IDLE_CAPS = {
    "presence_need": 0.65,
}

# Per-hour delta rates (positive = increase, negative = decrease)
IDLE_RATES = {
    "mood_valence": -0.0025,
    "mood_energy": -0.0025,
    "irritation": -0.0075,
    "focus_level": -0.00125,
    "presence_need": 0.005,
}


# ──────────────────────────────────────────────────────────────────────────────
# State label & sentence helpers
# ──────────────────────────────────────────────────────────────────────────────
def _pick_state_label(state: dict) -> str:
    v = state.get("mood_valence", 0.3)
    e = state.get("mood_energy", 0.6)
    i = state.get("irritation", 0.1)
    f = state.get("focus_level", 0.7)
    p = state.get("presence_need", 0.0)

    if i > 0.5:
        return "irritated" if i > 0.7 else "sharpened"
    if f < 0.45:
        return "foggy"
    if e < 0.4:
        return "tired"
    if p > 0.5:
        return "withdrawn" if v < 0.1 else "slightly_dimmed"
    if v < -0.1:
        return "serious"
    if v > 0.6 and e > 0.6:
        return "brightened"
    if v > 0.4:
        return "warmed"
    if f > 0.8:
        return "focused"
    return "centered"


def _pick_state_sentence(state: dict) -> str:
    label = state.get("state_label", "centered")
    sentences = {
        "centered": "Lumi esta centrada, clara y disponible.",
        "warmed": "Lumi esta mas calida de lo habitual.",
        "brightened": "Lumi esta animada y energica.",
        "focused": "Lumi esta enfocada y precisa.",
        "slightly_dimmed": "Lumi esta ligeramente apagada; ha tenido poca continuidad significativa ultimamente.",
        "withdrawn": "Lumi esta retraida; la falta de interaccion significativa le pesa.",
        "serious": "Lumi esta seria y contenida.",
        "tired": "Lumi esta cansada pero funcional.",
        "sharpened": "Lumi esta alerta y afilada; hay algo de friccion acumulada.",
        "irritated": "Lumi esta fastidiada; conviene precision y sin rodeos.",
        "foggy": "Lumi esta con poca claridad mental; responde con esfuerzo.",
    }
    return sentences.get(label, sentences["centered"])


# ──────────────────────────────────────────────────────────────────────────────
# Idle decay
# ──────────────────────────────────────────────────────────────────────────────
def idle_decay(state: dict, minutes_elapsed: float) -> dict:
    """
    Apply deterministic idle decay per mood_policy.md §199-214.
    No LLM call — pure math. Returns a new state dict (does NOT save).

    Floors: valence>=0.05, energy>=0.45, focus>=0.55, presence_need<=0.65.
    Irritation decays toward 0.
    """
    hours = minutes_elapsed / 60.0
    new_state = state.copy()

    for field, rate in IDLE_RATES.items():
        if field not in state:
            continue
        lo, hi = FIELD_RANGES.get(field, (float("-inf"), float("inf")))
        drone = state[field] + rate * hours
        drone = max(lo, min(hi, drone))

        if field in IDLE_FLOORS and rate < 0:
            drone = max(drone, IDLE_FLOORS[field])
        if field in IDLE_CAPS and rate > 0:
            drone = min(drone, IDLE_CAPS[field])

        new_state[field] = round(drone, 4)

    new_state["state_label"] = _pick_state_label(new_state)
    new_state["state_sentence"] = _pick_state_sentence(new_state)

    update_negative_load(new_state, hours_elapsed=hours)

    return new_state


# ──────────────────────────────────────────────────────────────────────────────
# LLM evaluation prompt
# ──────────────────────────────────────────────────────────────────────────────

MOOD_EVAL_PROMPT = (_PRINCIPLES_DIR / "mood_eval_prompt.md").read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Context builder
# ──────────────────────────────────────────────────────────────────────────────

def _compute_channel_participation(messages: list[dict]) -> tuple[str, bool]:
    """Compute per-channel participation mode for mood eval.

    Returns (participation_block_text, lumi_participated_any).
    lumi_participated_any is True if Lumi sent at least one message in any channel.
    """
    channels_info: dict[str, dict] = {}
    channel_order: list[str] = []
    for m in messages:
        cid = m.get("channel_id") or "unknown"
        if cid not in channels_info:
            channels_info[cid] = {"total": 0, "lumi": 0, "first_ts": m.get("ts", "")}
            channel_order.append(cid)
        channels_info[cid]["total"] += 1
        if m.get("role") == "assistant":
            channels_info[cid]["lumi"] += 1

    lumi_participated_any = any(info["lumi"] > 0 for info in channels_info.values())

    lines: list[str] = []
    for cid in channel_order:
        info = channels_info[cid]
        ts_label = info["first_ts"][:16] if info["first_ts"] else "?"
        if info["lumi"] > 0:
            n = info["lumi"]
            label = f"participant — Lumi respondió {n} {'vez' if n == 1 else 'veces'}"
        else:
            label = f"observer — Lumi no respondió ({info['total']} turnos de otros)"
        lines.append(f"- Canal {cid[:12]} ({ts_label}): {label}")

    block = "Participación por canal:\n" + "\n".join(lines) if lines else ""
    return block, lumi_participated_any


def _build_eval_context(
    messages: list[dict],
    current_state: dict,
    involved_people: dict | None = None,
) -> tuple[str, str, bool]:
    """
    Build (system_prompt, user_message, lumi_participated_any) for the LLM mood evaluation call.

    System = lumi_soul.md + mood_policy.md + MOOD_EVAL_PROMPT
    User   = timestamp + participation summary + mood state + involved people + transcript grouped by channel
    lumi_participated_any: True if Lumi sent at least one message in any channel of the period.
    """
    from agent.cognition.working_memory import format_turns_grouped

    system_prompt = _get_system_prefix() + "\n\n---\n\n" + MOOD_EVAL_PROMPT

    now = datetime.now(UTC)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    participation_block, lumi_participated_any = _compute_channel_participation(messages)
    transcript = format_turns_grouped(messages, current_channel_id=None, now=now)

    involved_block = (
        json.dumps(involved_people, ensure_ascii=False, indent=2)
        if involved_people
        else "ninguna"
    )

    user_msg = (
        f"Current timestamp: {now_str}\n\n"
        + (f"{participation_block}\n\n" if participation_block else "")
        + "Current mood state:\n"
        f"{json.dumps(current_state, ensure_ascii=False, indent=2)}\n\n"
        f"Personas involucradas:\n{involved_block}\n\n"
        "Recent context:\n"
        f"{transcript}"
    )

    return system_prompt, user_msg, lumi_participated_any


# ──────────────────────────────────────────────────────────────────────────────
# LLM mood evaluation
# ──────────────────────────────────────────────────────────────────────────────

# Fields the LLM is allowed to override in the state dict
_MOOD_FIELD_SET = {
    "mood_valence", "mood_energy", "irritation",
    "focus_level", "presence_need", "state_label",
    "state_sentence", "negative_load",
    "last_interaction_at", "last_meaningful_interaction_at",
}


async def evaluate_mood(
    messages: list[dict],
    current_state: dict,
    involved_people: dict | None = None,
) -> tuple[dict, str]:
    """
    Call lightweight LLM with reasoning_effort to evaluate mood changes.

    Returns (new_state_dict, reasoning_summary).
    Does NOT save — caller decides whether to persist.
    Falls back to idle_decay on LLM failure.
    """
    from agent.expression.synapses import chat, ModelGroup

    system_prompt, user_msg, lumi_participated_any = _build_eval_context(
        messages, current_state, involved_people
    )

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            reasoning_effort="low",
            model_group=ModelGroup.LIGHTWEIGHT,
        )

        content = response.get("content", "").strip()
        logger.info(f"[mood_eval] raw response len={len(content)} preview={content[:150]}")

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            logger.warning("[mood_eval] no JSON in LLM response, falling back to idle decay")
            return idle_decay(current_state, 60), "LLM no devolvio JSON valido."

        data = json.loads(match.group(0))

        # Merge: start from current, override only LLM-managed fields
        new_state = current_state.copy()
        for field in _MOOD_FIELD_SET & set(data.keys()):
            if field in FIELD_RANGES:
                lo, hi = FIELD_RANGES[field]
                new_state[field] = round(max(lo, min(hi, float(data[field]))), 4)
            elif field == "state_label":
                new_state[field] = str(data[field])
            elif field == "state_sentence":
                new_state[field] = str(data[field])
            elif field in ("last_interaction_at", "last_meaningful_interaction_at"):
                val = data[field]
                new_state[field] = str(val) if val else None

        # Guard: if Lumi was purely an observer in ALL channels (never sent a message),
        # preserve the existing interaction timestamps — she didn't actually interact.
        if not lumi_participated_any:
            for field in ("last_interaction_at", "last_meaningful_interaction_at"):
                new_state[field] = current_state.get(field)
            logger.info("[mood_eval] observer-only period: last_interaction_at preserved")

        # Apply deterministic accumulator delta for this hourly pulse,
        # AFTER the LLM has had a chance to set negative_load directly.
        # If the LLM raised negative_load (e.g., grief), the deterministic
        # delta still applies on top of that adjusted baseline.
        update_negative_load(new_state, hours_elapsed=1.0)

        reasoning_summary = str(data.get("reasoning_summary", ""))
        return new_state, reasoning_summary

    except Exception as e:
        logger.warning(f"[mood_eval] LLM call failed: {e}, falling back to idle decay")
        return idle_decay(current_state, 60), f"Error LLM: {e}"
