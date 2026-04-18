import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.agent.memory import get_history, search_relevant
from src.state.internal_state import get_state, state_to_text
COL = timezone(timedelta(hours=-5))
CARD_PATH = Path(__file__).parent.parent / "personality" / "lumi_card.json"

_cached_prefix = None


def _render_card(card: dict) -> str:
    data = card["data"]

    sections = []

    # [1] Runtime directives primero — máxima prioridad
    if data.get("system_prompt"):
        sections.append("# LUMI — Directives (HIGHEST PRIORITY)\n\n" + data["system_prompt"])

    # [2] Identidad completa
    sections.append("# LUMI — Identity\n\n" + data["description"])

    # [3] Personalidad condensada
    sections.append("## Personality\n\n" + data["personality"])

    # [4] Escenario operativo
    sections.append("## Context\n\n" + data["scenario"])

    # [5] Ejemplos — convertir sintaxis SillyTavern a texto plano
    if data.get("mes_example"):
        examples = (data["mes_example"]
            .replace("{{user}}", "Jose")
            .replace("{{char}}", "Lumi")
            .replace("<START>", "---"))
        sections.append("## Dialogue Examples\n\n" + examples)

    return "\n\n---\n\n".join(sections)

def _build_cached_prefix() -> str:
    if not CARD_PATH.exists():
        return "Eres Lumi, asistente personal de Jose Barco. Responde en español colombiano neutro. Emotion tag obligatorio al inicio: [neutral], [happy], [sad], [thinking], [surprised], [playful]."
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    return _render_card(card)


def get_cached_prefix() -> str:
    global _cached_prefix
    if _cached_prefix is None:
        _cached_prefix = _build_cached_prefix()
    return _cached_prefix


def _build_dynamic_suffix(user_id: str, message: str, metadata: dict) -> str:
    state = get_state(user_id)
    relevant_memories = search_relevant(user_id, message)
    now = datetime.now(COL).strftime("%d/%m/%Y %H:%M COT")

    parts = ["[Estado interno] " + state_to_text(state)]

    if relevant_memories:
        parts.append("[Memorias relevantes]\n" + "\n".join("- " + m for m in relevant_memories))

    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    parts.append("[Contexto] Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now)

    return "\n\n".join(parts)


def build_messages(user_id: str, message: str, metadata: dict) -> list[dict]:
    cached = get_cached_prefix()
    dynamic = _build_dynamic_suffix(user_id, message, metadata)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    history = get_history(user_id, limit=10)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    return messages