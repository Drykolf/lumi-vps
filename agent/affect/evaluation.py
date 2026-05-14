"""
Mood evaluation orchestrator — idle decay and LLM contextual evaluation.
Implements mood_policy.md evaluation guidelines.
"""
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from agent.affect.mood import FIELD_RANGES
from agent.substrate.logger import get_logger

logger = get_logger("affect.evaluation")

_IDENTITY_DIR = Path(__file__).parent.parent / "identity"
_cached_system_prefix: str | None = None


def _get_system_prefix() -> str:
    """Lazy-load compact_soul.md + mood_policy.md, cache once per process."""
    global _cached_system_prefix
    if _cached_system_prefix is not None:
        return _cached_system_prefix
    parts = []
    for rel in ("compact_soul.md", "principles/mood_policy.md"):
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
    "mood_valence": -0.01,
    "mood_energy": -0.01,
    "irritation": -0.03,
    "focus_level": -0.005,
    "presence_need": 0.02,
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

    return new_state


# ──────────────────────────────────────────────────────────────────────────────
# LLM evaluation prompt
# ──────────────────────────────────────────────────────────────────────────────

MOOD_EVAL_PROMPT = (
    """You are evaluating Lumi’s internal mood state using the provided compact_soul, mood_policy, current mood state, recent context, and involved people.

Follow the mood_policy as the source of truth.

Return only valid JSON matching the schema below.

Do not generate Lumi’s user-facing response.
Do not use emotion tags.
Do not generate inner thoughts.
Do not update memory, profile, relationship data, or interest_score.
Use current_mood_state as the anchor.
Mood changes should be gradual unless the context contains a clearly strong event.
Jose has the strongest influence on Lumi’s mood.
Unknown third parties usually affect irritation more than mood_valence.
If deterministic idle decay was already applied, do not apply silence decay again.
If context is insufficient, make the smallest reasonable update.

Return these fields only:
{
  "mood_valence": number,
  "mood_energy": number,
  "irritation": number,
  "focus_level": number,
  "presence_need": number,
  "state_label": string,
  "state_sentence": string,
  "emotional_honesty_mode": boolean,
  "last_interaction_at": string | null,
  "last_meaningful_interaction_at": string | null,
  "reasoning_summary": string
}

Rules:
- mood_valence must be between -1.0 and 1.0.
- mood_energy, irritation, focus_level, and presence_need must be between 0.0 and 1.0.
- Use decimals with at most 3 digits.
- state_sentence must be one natural Spanish sentence.
- reasoning_summary must be 1–3 short Spanish sentences.
- Do not include last_day_reset.
- Do not include last_updated.
- Do not include extra keys.
- Do not wrap the JSON in markdown.""")


# ──────────────────────────────────────────────────────────────────────────────
# Context builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_eval_context(
    messages: list[dict],
    current_state: dict,
    involved_people: dict | None = None,
) -> tuple[str, str]:
    """
    Build (system_prompt, user_message) for the LLM mood evaluation call.

    System = compact_soul.md + mood_policy.md + MOOD_EVAL_PROMPT
    User   = timestamp + mood state + involved people + transcript
    """
    system_prompt = _get_system_prefix() + "\n\n---\n\n" + MOOD_EVAL_PROMPT

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    for m in messages:
        name = "Lumi" if m.get("role") == "assistant" else (m.get("user_id") or m.get("role", "desconocido"))
        lines.append(f"{name}: {m.get('content', '')}")
    transcript = "\n".join(lines)

    involved_block = "# TODO" if not involved_people else json.dumps(involved_people, ensure_ascii=False)

    user_msg = (
        f"Current timestamp: {now}\n\n"
        "Current mood state:\n"
        f"{json.dumps(current_state, ensure_ascii=False, indent=2)}\n\n"
        f"#Involved people:\n#{involved_block}\n\n"
        "Recent context:\n"
        f"{transcript}"
    )

    return system_prompt, user_msg


# ──────────────────────────────────────────────────────────────────────────────
# LLM mood evaluation
# ──────────────────────────────────────────────────────────────────────────────

# Fields the LLM is allowed to override in the state dict
_MOOD_FIELD_SET = {
    "mood_valence", "mood_energy", "irritation",
    "focus_level", "presence_need", "state_label",
    "state_sentence", "emotional_honesty_mode",
    "last_interaction_at", "last_meaningful_interaction_at",
}


async def evaluate_mood(
    messages: list[dict],
    current_state: dict,
    involved_people: dict | None = None,
) -> tuple[dict, str]:
    """
    Call lightweight LLM with thinking=True to evaluate mood changes.

    Returns (new_state_dict, reasoning_summary).
    Does NOT save — caller decides whether to persist.
    Falls back to idle_decay on LLM failure.
    """
    from agent.expression.synapses import chat, ModelGroup

    system_prompt, user_msg = _build_eval_context(messages, current_state, involved_people)

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            thinking=True,
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
            elif field == "emotional_honesty_mode":
                new_state[field] = bool(data[field])
            elif field in ("last_interaction_at", "last_meaningful_interaction_at"):
                val = data[field]
                new_state[field] = str(val) if val else None

        reasoning_summary = str(data.get("reasoning_summary", ""))
        return new_state, reasoning_summary

    except Exception as e:
        logger.warning(f"[mood_eval] LLM call failed: {e}, falling back to idle decay")
        return idle_decay(current_state, 60), f"Error LLM: {e}"
