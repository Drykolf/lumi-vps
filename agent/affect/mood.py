"""
Lumi's dynamic internal state — implements mood_policy.md.
Stored in core.db lumi_state table as a JSON blob.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from agent.subconscious import core

UTC = timezone.utc

LUMI_SLEEP_HOUR = int(os.getenv("LUMI_SLEEP_HOUR", "3"))
LUMI_TZ_OFFSET = int(os.getenv("LUMI_TIMEZONE", "-5"))

DEFAULT_STATE = {
    "mood_valence": 0.3,
    "mood_energy": 0.6,
    "irritation": 0.1,
    "focus_level": 0.7,
    "presence_need": 0.0,
    "negative_load": 0.0,
    "state_label": "centered",
    "state_sentence": "Lumi está centrada, clara y disponible.",
    "emotional_honesty_mode": False,
    "last_interaction_at": None,
    "last_meaningful_interaction_at": None,
    "last_day_reset": None,
    "last_updated": None,
}

FIELD_RANGES = {
    "mood_valence": (-1.0, 1.0),
    "mood_energy": (0.0, 1.0),
    "irritation": (0.0, 1.0),
    "focus_level": (0.0, 1.0),
    "presence_need": (0.0, 1.0),
    "negative_load": (0.0, 1.0),
}

# ── Emotional honesty mode (derived from negative_load) ──────────────────────

NEGATIVE_LOAD_RATES = {
    "strong_negative": +0.030,   # per hour
    "mild_negative":   +0.018,
    "neutral":         -0.008,
    "positive":        -0.022,
}

HONESTY_ON_THRESHOLD = 0.70
HONESTY_OFF_THRESHOLD = 0.30
MORNING_LOAD_DECAY_FACTOR = 0.93


def _read_state() -> dict | None:
    conn = core.get_conn()
    row = conn.execute(
        "SELECT data FROM lumi_state WHERE key = 'mood_state'"
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None


def _write_state(state: dict):
    now = datetime.now(UTC).isoformat()
    state["last_updated"] = now
    conn = core.get_conn()
    conn.execute(
        """INSERT INTO lumi_state (key, data)
           VALUES ('mood_state', ?)
           ON CONFLICT(key) DO UPDATE SET
               data = excluded.data""",
        (json.dumps(state, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()


write_state = _write_state


def _in_range(val: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= val < end
    return val >= start or val < end


def get_sleep_stage(tz=None, sleep_hour=None) -> str:
    if tz is None:
        tz = timezone(timedelta(hours=LUMI_TZ_OFFSET))
    if sleep_hour is None:
        sleep_hour = LUMI_SLEEP_HOUR

    now = datetime.now(tz)
    current = now.hour * 60 + now.minute
    sh = sleep_hour * 60

    sleeping_start = (sh - 30) % 1440
    sleeping_end   = (sh + 30) % 1440
    sleepy_start   = (sh - 60) % 1440
    sleepy_end     = (sh - 30) % 1440
    drowsy_start   = (sh - 120) % 1440
    drowsy_end     = (sh - 60) % 1440

    if _in_range(current, sleeping_start, sleeping_end):
        return "sleeping"
    if _in_range(current, sleepy_start, sleepy_end):
        return "sleepy"
    if _in_range(current, drowsy_start, drowsy_end):
        return "drowsy"
    return "awake"


# ── Init ──────────────────────────────────────────────────────────────────────

def init_state_table():
    """Ensure core.db and lumi_state row exist. Must run once at startup."""
    existing = _read_state()
    if existing is None:
        _write_state(DEFAULT_STATE)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_state(user_id: str = None) -> dict:
    """Return current state dict. user_id is ignored (Lumi owns a single state)."""
    state = _read_state()
    if state is None:
        return DEFAULT_STATE.copy()
    if "negative_load" not in state:
        state["negative_load"] = 0.0
    return state


def state_to_text(state: dict) -> str:
    """Return mood description for prompt injection per mood_policy.md §440-456.
    Prefers state_sentence from JSON, falls back to numeric descriptor build."""
    sentence = state.get("state_sentence")
    if sentence:
        base = sentence
    else:
        valence = state.get("mood_valence", 0.3)
        energy = state.get("mood_energy", 0.6)
        irritation = state.get("irritation", 0.1)

        valence_desc = (
            "algo seria" if valence < 0.0
            else "neutra" if valence < 0.3
            else "de buen humor" if valence < 0.7
            else "muy animada"
        )
        energy_desc = (
            "cansada" if energy < 0.3
            else "normal" if energy < 0.6
            else "con energia"
        )
        irrit_desc = (
            "" if irritation < 0.3
            else ", con algo de fastidio acumulado" if irritation < 0.6
            else ", bastante fastidiada"
        )
        base = f"Estado interno actual de Lumi: {valence_desc}, {energy_desc}{irrit_desc}."

    stage = get_sleep_stage()
    if stage == "drowsy":
        base += "\nLumi empieza a sentirse cansada."
    elif stage == "sleepy":
        base += "\nLumi está cansada y quiere descansar."

    return base


# ── Write (deltas) ───────────────────────────────────────────────────────────

def _lerp(current: float, target: float, t: float) -> float:
    return current + (target - current) * t


def apply_deltas(**deltas: float) -> dict:
    """Apply mood deltas from a single turn or session event.
    Each delta value in the range [-0.20, +0.20]. Per-field cumulative cap
    of 0.30 magnitude per session is enforced by the caller."""
    state = get_state()

    for field, delta in deltas.items():
        if field in FIELD_RANGES and isinstance(delta, (int, float)):
            lo, hi = FIELD_RANGES[field]
            state[field] = max(lo, min(hi, state[field] + delta))

    _write_state(state)
    from agent.memory.episodic import add_mood_log
    add_mood_log(state, trigger_source="event")
    return state


def touch_last_interaction(meaningful: bool = False):
    state = get_state()
    now = datetime.now(UTC).isoformat()
    state["last_interaction_at"] = now
    if meaningful:
        state["last_meaningful_interaction_at"] = now
    _write_state(state)


def _classify_load_state(state: dict) -> str:
    """Classify current mood into a load-accumulator category.

    Strong/mild conditions match the old honesty-mode thresholds, kept as bands
    so the deterministic classifier remains a faithful interpretation of
    mood_policy thresholds — just averaged over time rather than instantaneous.
    """
    v = state.get("mood_valence", 0.3)
    i = state.get("irritation", 0.1)
    p = state.get("presence_need", 0.0)

    if i > 0.7 or v < -0.4 or p > 0.7:
        return "strong_negative"
    if i > 0.6 or v < -0.2 or p > 0.6:
        return "mild_negative"
    if v > 0.3 and i < 0.2:
        return "positive"
    return "neutral"


def update_negative_load(state: dict, hours_elapsed: float = 1.0) -> dict:
    """Apply the per-hour delta to negative_load based on the current category.

    Mutates and returns the passed-in state dict. Does NOT persist. The caller
    is expected to invoke this after idle_decay() or evaluate_mood() each pulse,
    then write the state once.
    """
    category = _classify_load_state(state)
    delta = NEGATIVE_LOAD_RATES[category] * hours_elapsed
    current = state.get("negative_load", 0.0)
    state["negative_load"] = round(max(0.0, min(1.0, current + delta)), 4)
    return state


def morning_reset():
    """Daily regression toward baseline per mood_policy.md §329-352.
    Constants: irritation 60%→0.0, energy 50%→0.6, valence 40%→0.3,
    focus 40%→0.7, presence_need 35%→0.0.
    Also applies proportional decay to negative_load (7%)."""
    state = get_state()
    now = datetime.now(UTC).isoformat()

    state["irritation"] = _lerp(state["irritation"], 0.0, 0.6)
    state["mood_energy"] = _lerp(state["mood_energy"], 0.6, 0.5)
    state["mood_valence"] = _lerp(state["mood_valence"], 0.3, 0.4)
    state["focus_level"] = _lerp(state["focus_level"], 0.7, 0.4)
    state["presence_need"] = _lerp(state["presence_need"], 0.0, 0.35)
    state["negative_load"] = round(
        state.get("negative_load", 0.0) * MORNING_LOAD_DECAY_FACTOR, 4
    )
    state["last_day_reset"] = now

    _write_state(state)
    from agent.memory.episodic import add_mood_log
    add_mood_log(state, trigger_source="morning_regression")
    return state


def check_emotional_honesty_mode() -> bool:
    """Derive emotional_honesty_mode from negative_load with hysteresis.

    Activates when negative_load >= HONESTY_ON_THRESHOLD (0.70).
    Deactivates when negative_load < HONESTY_OFF_THRESHOLD (0.30).
    Between those bounds, the previous state is preserved.

    Per mood_policy.md: the flag reflects SUSTAINED emotional load across
    days, not instantaneous mood. The LLM evaluator may influence this
    indirectly by adjusting negative_load when it observes strong sustained
    context.

    Returns the current value of the flag after evaluation.
    """
    state = get_state()
    load = state.get("negative_load", 0.0)
    was_active = state["emotional_honesty_mode"]

    if was_active and load < HONESTY_OFF_THRESHOLD:
        state["emotional_honesty_mode"] = False
        _write_state(state)
        from agent.memory.episodic import add_mood_log
        add_mood_log(
            state,
            trigger_source="event",
            note=f"emotional_honesty_mode disabled (load={load:.3f})",
        )
    elif not was_active and load >= HONESTY_ON_THRESHOLD:
        state["emotional_honesty_mode"] = True
        _write_state(state)
        from agent.memory.episodic import add_mood_log
        add_mood_log(
            state,
            trigger_source="event",
            note=f"emotional_honesty_mode enabled (load={load:.3f})",
        )

    return state["emotional_honesty_mode"]
