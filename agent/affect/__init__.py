"""
Lumi's emotional state and mood evaluation.

Submodules:
  mood.py       — CRUD, deltas, morning_reset, emotional_honesty_mode
  evaluation.py — idle_decay, LLM contextual evaluation, prompts
"""
from agent.affect.mood import (
    init_state_table,
    get_state,
    state_to_text,
    apply_deltas,
    morning_reset,
    check_emotional_honesty_mode,
    write_state,
    touch_last_interaction,
    FIELD_RANGES,
    DEFAULT_STATE,
)
from agent.affect.evaluation import (
    idle_decay,
    evaluate_mood,
    MOOD_EVAL_PROMPT,
)

__all__ = [
    "init_state_table",
    "get_state",
    "state_to_text",
    "apply_deltas",
    "morning_reset",
    "check_emotional_honesty_mode",
    "write_state",
    "touch_last_interaction",
    "FIELD_RANGES",
    "DEFAULT_STATE",
    "idle_decay",
    "evaluate_mood",
    "MOOD_EVAL_PROMPT",
]
