"""
Lumi's dynamic internal state — implements mood_policy.md.
Stored in core_state.db lumi_state table as a JSON blob.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

COL = timezone(timedelta(hours=-5))

DB_PATH = Path(__file__).parent.parent.parent / "data" / "core_state.db"

DEFAULT_STATE = {
    "mood_valence": 0.3,
    "mood_energy": 0.6,
    "irritation": 0.1,
    "focus_level": 0.7,
    "trust_jose": 0.9,
    "emotional_honesty_mode": False,
    "last_day_reset": None,
    "last_updated": None,
}

FIELD_RANGES = {
    "mood_valence": (-1.0, 1.0),
    "mood_energy": (0.0, 1.0),
    "irritation": (0.0, 1.0),
    "focus_level": (0.0, 1.0),
    "trust_jose": (0.5, 1.0),
}


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _read_state() -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT value FROM lumi_state WHERE key = 'internal_state'"
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["value"])
    return None


def _write_state(state: dict):
    now = datetime.now(COL).isoformat()
    state["last_updated"] = now
    conn = _conn()
    conn.execute(
        """INSERT INTO lumi_state (key, value, last_updated)
           VALUES ('internal_state', ?, ?)
           ON CONFLICT(key) DO UPDATE SET
               value = excluded.value,
               last_updated = excluded.last_updated""",
        (json.dumps(state, ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()


# ── Init ──────────────────────────────────────────────────────────────────────

def init_state_table():
    """Ensure core_state.db and lumi_state row exist. Must run once at startup."""
    from agent.memory.social import init_core_db

    init_core_db()
    existing = _read_state()
    if existing is None:
        _write_state(DEFAULT_STATE)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_state(user_id: str = None) -> dict:
    """Return current state dict. user_id is ignored (Lumi owns a single state)."""
    state = _read_state()
    return state or DEFAULT_STATE.copy()


def state_to_text(state: dict) -> str:
    """Map numeric state to Spanish descriptors per mood_policy.md."""
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
    """Daily regression toward baseline (40-60%). Per mood_policy.md.
    Trust toward Jose does not regress."""
    state = get_state()
    now = datetime.now(COL).isoformat()

    state["mood_valence"] = _lerp(state["mood_valence"], 0.3, 0.4)
    state["mood_energy"] = _lerp(state["mood_energy"], 0.6, 0.5)
    state["irritation"] = _lerp(state["irritation"], 0.0, 0.6)
    state["focus_level"] = _lerp(state["focus_level"], 0.7, 0.4)
    state["last_day_reset"] = now

    _write_state(state)
    return state


def check_emotional_honesty_mode() -> bool:
    """Evaluate triggers to enable or disable emotional_honesty_mode.
    Per mood_policy.md. Returns current value after evaluation."""
    state = get_state()

    if state["emotional_honesty_mode"]:
        # Disable: valence >= 0.2 && irritation < 0.3
        if state["mood_valence"] >= 0.2 and state["irritation"] < 0.3:
            state["emotional_honesty_mode"] = False
            _write_state(state)
    else:
        # Enable: irritation > 0.6 OR mood_valence < -0.2
        if state["irritation"] > 0.6 or state["mood_valence"] < -0.2:
            state["emotional_honesty_mode"] = True
            _write_state(state)

    return state["emotional_honesty_mode"]

"""TODO
affect/state.py       # estado actual
affect/dynamics.py    # cómo cambia
affect/readings.py    # cómo se expone o interpreta

readings.py me parece mejor, porque suena a lecturas internas:
mood
energy
trust
patience
irritation
fatigue
"""