"""
Lumi's dynamic internal state — implements mood_policy.md.
Stored in core.db lumi_state table as a JSON blob.
"""
import json
from datetime import datetime, timezone
from agent.subconscious import core

UTC = timezone.utc

DEFAULT_STATE = {
    "mood_valence": 0.3,
    "mood_energy": 0.6,
    "irritation": 0.1,
    "focus_level": 0.7,
    "presence_need": 0.0,
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
}


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
    return state or DEFAULT_STATE.copy()


def state_to_text(state: dict) -> str:
    """Return mood description for prompt injection per mood_policy.md §440-456.
    Prefers state_sentence from JSON, falls back to numeric descriptor build."""
    sentence = state.get("state_sentence")
    if sentence:
        return sentence

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
    return f"Estado interno actual de Lumi: {valence_desc}, {energy_desc}{irrit_desc}."


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
    return state


def morning_reset():
    """Daily regression toward baseline per mood_policy.md §329-352.
    Constants: irritation 60%→0.0, energy 50%→0.6, valence 40%→0.3,
    focus 40%→0.7, presence_need 35%→0.0."""
    state = get_state()
    now = datetime.now(UTC).isoformat()

    state["irritation"] = _lerp(state["irritation"], 0.0, 0.6)
    state["mood_energy"] = _lerp(state["mood_energy"], 0.6, 0.5)
    state["mood_valence"] = _lerp(state["mood_valence"], 0.3, 0.4)
    state["focus_level"] = _lerp(state["focus_level"], 0.7, 0.4)
    state["presence_need"] = _lerp(state["presence_need"], 0.0, 0.35)
    state["last_day_reset"] = now

    _write_state(state)
    return state


def check_emotional_honesty_mode() -> bool:
    """Evaluate triggers to enable or disable emotional_honesty_mode.
    Per mood_policy.md §355-380. Returns current value after evaluation."""
    state = get_state()

    if state["emotional_honesty_mode"]:
        # Disable: valence >= 0.2 AND irritation < 0.3 AND presence_need < 0.4
        if (state["mood_valence"] >= 0.2
                and state["irritation"] < 0.3
                and state["presence_need"] < 0.4):
            state["emotional_honesty_mode"] = False
            _write_state(state)
    else:
        # Enable: irritation > 0.6 OR mood_valence < -0.2 OR presence_need > 0.6
        if (state["irritation"] > 0.6
                or state["mood_valence"] < -0.2
                or state["presence_need"] > 0.6):
            state["emotional_honesty_mode"] = True
            _write_state(state)

    return state["emotional_honesty_mode"]
