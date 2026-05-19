# LUMI — Emotional Honesty Mode Refactor (Hybrid C)

## Goal

Refactor `emotional_honesty_mode` from a binary threshold flip into a flag **derived from a slow accumulator** of emotional load. Aligns with `mood_policy.md` intent ("varios días con carga negativa acumulada") and closes the risk documented in `LUMI-Manual.md §11.1` ("flag stays activated indefinitely").

## Design summary (Option C — hybrid derived)

- Add a new state field `negative_load` (float, 0.0–1.0). It is a slow accumulator of emotional weight.
- A deterministic classifier runs every hour (after `idle_decay` or `evaluate_mood`) and adjusts `negative_load` based on the current mood category.
- The LLM evaluator is **no longer allowed to set `emotional_honesty_mode` directly**. Instead, the LLM may adjust `negative_load` when it sees a sustained strong signal (grief, prolonged stress on Jose, sustained mistreatment).
- `check_emotional_honesty_mode()` now reads `negative_load` and applies hysteresis (ON ≥ 0.70, OFF < 0.30) instead of checking raw mood fields.
- `morning_reset` applies a proportional decay to `negative_load` (a good night helps, but does not erase real accumulated weight).

## Calibration constants

```
NEGATIVE_LOAD_RATES (per hour):
    strong_negative: +0.030     # irritation > 0.7 OR mood_valence < -0.4 OR presence_need > 0.7
    mild_negative:   +0.018     # irritation > 0.6 OR mood_valence < -0.2 OR presence_need > 0.6
    neutral:         -0.008     # neither negative nor positive
    positive:        -0.022     # mood_valence > 0.3 AND irritation < 0.2

HONESTY_ON_THRESHOLD  = 0.70
HONESTY_OFF_THRESHOLD = 0.30
MORNING_LOAD_DECAY_FACTOR = 0.93   # proportional 7% decay on morning reset
```

Expected behavior:
- Single bad day in isolation → does **not** activate
- 2 days fully in strong_negative → activates
- ~2.5 days fully in mild_negative → activates
- Mixed 70% mild + 30% neutral → activates around day 3–4
- After activation, a fully positive day → deactivates next day

---

## File 1 — `src/agent/affect/mood.py`

### 1.1 Update `DEFAULT_STATE`

Add `negative_load` initialized to `0.0`:

```python
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
```

### 1.2 Update `FIELD_RANGES`

Add `negative_load`:

```python
FIELD_RANGES = {
    "mood_valence": (-1.0, 1.0),
    "mood_energy": (0.0, 1.0),
    "irritation": (0.0, 1.0),
    "focus_level": (0.0, 1.0),
    "presence_need": (0.0, 1.0),
    "negative_load": (0.0, 1.0),
}
```

### 1.3 Add new module-level constants (after `FIELD_RANGES`)

```python
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
```

### 1.4 Add classifier + accumulator updater (place after `apply_deltas`, before `morning_reset`)

```python
def _classify_load_state(state: dict) -> str:
    """Classify current mood into a load-accumulator category.

    Strong/mild conditions match the OLD honesty-mode triggers, kept as bands
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
```

### 1.5 Replace `check_emotional_honesty_mode` entirely

Replace the existing function with this hysteresis-based version:

```python
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
```

### 1.6 Update `morning_reset` to decay `negative_load`

Modify `morning_reset` so it also applies the proportional decay. **Do not** call `check_emotional_honesty_mode()` from inside `morning_reset` — Jose will wire the call order in the cron routine separately.

```python
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
```

### 1.7 Backfill default in `get_state`

Ensure rows persisted before the schema change still expose `negative_load`. Modify `get_state` to backfill:

```python
def get_state(user_id: str = None) -> dict:
    """Return current state dict. user_id is ignored (Lumi owns a single state)."""
    state = _read_state()
    if state is None:
        return DEFAULT_STATE.copy()
    # Backfill new fields for state rows written before the refactor
    if "negative_load" not in state:
        state["negative_load"] = 0.0
    return state
```

---

## File 2 — `src/agent/affect/evaluation.py`

### 2.1 Update `_MOOD_FIELD_SET`

Remove `emotional_honesty_mode`; add `negative_load`:

```python
_MOOD_FIELD_SET = {
    "mood_valence", "mood_energy", "irritation",
    "focus_level", "presence_need", "state_label",
    "state_sentence", "negative_load",
    "last_interaction_at", "last_meaningful_interaction_at",
}
```

### 2.2 Update `evaluate_mood` merge logic

In `evaluate_mood`, the `for field in _MOOD_FIELD_SET & set(data.keys()):` loop currently handles `emotional_honesty_mode` as a `bool` branch. Remove that branch. `negative_load` is already handled by the `FIELD_RANGES` branch (it's a clamped float). No new branch needed — just delete the `elif field == "emotional_honesty_mode":` block.

Final shape of the merge loop:

```python
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
```

### 2.3 Replace `MOOD_EVAL_PROMPT` (Spanish, with negative_load guidance)

Replace the entire `MOOD_EVAL_PROMPT` constant with this Spanish version:

```python
MOOD_EVAL_PROMPT = (
    """Estás evaluando el estado interno (mood) de Lumi usando: compact_soul, mood_policy, el estado mood actual, el contexto reciente y las personas involucradas.

Sigue mood_policy como fuente de verdad.

Devuelve únicamente JSON válido que cumpla el esquema indicado abajo.

No generes la respuesta de Lumi al usuario.
No uses emotion tags.
No generes inner thoughts.
No actualices memoria, perfil, datos de relaciones ni interest_score.
Usa current_mood_state como anclaje.
Los cambios de mood deben ser graduales salvo que el contexto contenga un evento claramente fuerte.
Jose tiene la influencia más fuerte sobre el mood de Lumi.
Terceros desconocidos suelen afectar más irritation que mood_valence.
Si ya se aplicó decay determinista, no apliques silence decay otra vez.
Si el contexto es insuficiente, haz el ajuste más pequeño razonable.

Devuelve solo estos campos:
{
  "mood_valence": number,
  "mood_energy": number,
  "irritation": number,
  "focus_level": number,
  "presence_need": number,
  "negative_load": number,
  "state_label": string,
  "state_sentence": string,
  "last_interaction_at": string | null,
  "last_meaningful_interaction_at": string | null,
  "reasoning_summary": string
}

Reglas:
- mood_valence debe estar entre -1.0 y 1.0.
- mood_energy, irritation, focus_level y presence_need entre 0.0 y 1.0.
- negative_load entre 0.0 y 1.0.
- negative_load es un acumulador lento de peso emocional sostenido a lo largo de días. Ajústalo SOLO cuando el contexto contenga una señal fuerte sostenida (duelo, maltrato sostenido, estrés prolongado en Jose que se contagia a Lumi, negligencia prolongada). Para fluctuaciones normales del mood, déjalo IGUAL — el pulse determinista lo ajustará a partir de irritation, mood_valence y presence_need.
- NO incluyas emotional_honesty_mode. Se deriva de negative_load downstream.
- Usa decimales con máximo 3 dígitos.
- state_sentence debe ser una oración natural en español.
- reasoning_summary debe ser 1 a 3 oraciones cortas en español.
- No incluyas last_day_reset.
- No incluyas last_updated.
- No incluyas claves extra.
- No envuelvas el JSON en markdown.""")
```

### 2.4 Call `update_negative_load` after `idle_decay`

At the end of `idle_decay`, after `state_label` and `state_sentence` are assigned but before `return`, call the accumulator updater. Import it at the top of the file alongside the existing `FIELD_RANGES` import:

```python
from agent.affect.mood import FIELD_RANGES, update_negative_load
```

Modified end of `idle_decay`:

```python
    new_state["state_label"] = _pick_state_label(new_state)
    new_state["state_sentence"] = _pick_state_sentence(new_state)

    update_negative_load(new_state, hours_elapsed=hours)

    return new_state
```

### 2.5 Call `update_negative_load` after LLM merge in `evaluate_mood`

In `evaluate_mood`, after the merge loop and before the `return new_state, reasoning_summary` line, call the updater for one hour:

```python
        # ... merge loop above ...

        # Apply deterministic accumulator delta for this hourly pulse,
        # AFTER the LLM has had a chance to set negative_load directly.
        # If the LLM raised negative_load (e.g., grief), the deterministic
        # delta still applies on top of that adjusted baseline.
        update_negative_load(new_state, hours_elapsed=1.0)

        reasoning_summary = str(data.get("reasoning_summary", ""))
        return new_state, reasoning_summary
```

Also update the two `idle_decay` fallback paths inside `evaluate_mood` — they already call `idle_decay(current_state, 60)` which now updates `negative_load` internally. No additional work needed for those branches.

---

## File 3 — Migration `src/agent/subconscious/migrations/002_create_core.sql`

Around lines 170–171 there is a virtual generated column mirroring `emotional_honesty_mode` from the JSON blob. Add a parallel virtual column for `negative_load` immediately after it.

Locate the existing line. The exact syntax may differ in the file — match the style used for `emotional_honesty_mode`. Expected addition:

```sql
negative_load REAL GENERATED ALWAYS AS (json_extract(data, '$.negative_load')) VIRTUAL,
```

If the existing pattern uses `STORED` instead of `VIRTUAL`, or uses a different cast (`CAST(json_extract(...) AS REAL)`), match that pattern exactly for consistency.

### One-time data backfill for the existing row

The `lumi_state` table has at most one row (`key='mood_state'`). After the migration runs, add this idempotent backfill so the JSON blob explicitly contains `negative_load: 0.0` instead of relying on a Python-side default:

```sql
UPDATE lumi_state
SET data = json_set(data, '$.negative_load', 0.0)
WHERE key = 'mood_state'
  AND json_extract(data, '$.negative_load') IS NULL;
```

Decide based on your migration policy whether this goes in `002_create_core.sql` (if migrations are re-runnable) or in a new migration file. If a new file, name it following the existing convention (`003_add_negative_load.sql` or similar).

---

## Validation checklist

After applying changes, the agent should verify:

1. **Imports resolve**: `from agent.affect.mood import update_negative_load` works inside `evaluation.py`.
2. **DB migration applied**: `negative_load` exists both inside the JSON blob and as a virtual column queryable from SQL.
3. **Defaults sensible**: A fresh `get_state()` on a clean DB returns `negative_load == 0.0` and `emotional_honesty_mode == False`.
4. **Backfill works**: An older state row without `negative_load` in its JSON, after one `get_state()` call, exposes the field as `0.0`.
5. **Classifier sanity**: Given a state with `irritation=0.8`, `_classify_load_state` returns `"strong_negative"`. Given `mood_valence=0.5, irritation=0.1`, returns `"positive"`.
6. **Updater clamping**: `update_negative_load({"negative_load": 0.99, "irritation": 0.8}, hours_elapsed=10)` clamps result at `1.0`. Same with negative clamp at `0.0`.
7. **Hysteresis**: Setting `negative_load=0.5` and calling `check_emotional_honesty_mode` should NOT activate the flag (between thresholds, current value preserved). Setting `0.71` activates. Setting `0.29` afterwards deactivates.
8. **LLM cannot toggle flag directly**: Submit a synthetic LLM response with `"emotional_honesty_mode": true` in the JSON — `evaluate_mood` should ignore it (it's no longer in `_MOOD_FIELD_SET`).
9. **LLM can adjust accumulator**: Submit a synthetic LLM response with `"negative_load": 0.5` — `evaluate_mood` should apply it (clamped via `FIELD_RANGES`).

---

## Out of scope for this task (Jose handles separately)

- Wiring `check_emotional_honesty_mode()` call order in the hourly cron routine.
- Wiring `morning_reset` ordering relative to mood eval.
- Injecting the honesty-mode prompt block into `_build_dynamic_suffix` in `src/agent/cognition/working_memory.py` — separate task, known gap from `phase4_plan.md` Block 4.
- Recalibration of `NEGATIVE_LOAD_RATES` or thresholds after observing real usage data — current values are starting points per `LUMI-Manual.md §13.4`.
