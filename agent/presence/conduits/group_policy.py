"""Group participation policy — máquina de estados OBSERVING/ENGAGED por grupo.

Agnóstico de plataforma; hoy sólo lo usa el webhook de WhatsApp. Estado en
memoria del proceso: si el server reinicia todos los grupos vuelven a
OBSERVING (fail-safe que prefiere silencio).
"""
from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal, Protocol

from agent.substrate.logger import get_logger

logger = get_logger("presence.group_policy")

Decision = Literal["observe", "engage_main", "confirm_close"]

ENGAGED_TIME_WINDOW_S = int(os.getenv("LUMI_GROUP_ENGAGED_WINDOW_S", "30"))
ENGAGED_MESSAGE_WINDOW = int(os.getenv("LUMI_GROUP_ENGAGED_MSG_WINDOW", "5"))

CLOSING_PATTERNS = re.compile(
    r"\b(gracias|listo|chao|ok|ya|bye)\b.{0,15}\blum[iy]+\b"
    r"|\blum[iy]+\b.{0,15}\b(gracias|chao|bye)\b",
    re.IGNORECASE,
)

_LUMI_MSG_ID_CAP = 20


class _GroupMsg(Protocol):
    """Shape mínima que el policy necesita de un mensaje de grupo."""
    text: str
    msg_id: str
    reply_to_msg_id: str | None
    mentioned_jids: list[str]
    replied_to_participant: str | None


@dataclass
class GroupState:
    mode: Literal["observing", "engaged"] = "observing"
    engaged_since: datetime | None = None
    last_engaged_activity: datetime | None = None
    messages_since_interpellation: int = 0
    last_lumi_msg_ids: deque[str] = field(default_factory=lambda: deque(maxlen=_LUMI_MSG_ID_CAP))
    pending_close: bool = False


_states: dict[str, GroupState] = {}


def _get(group_id: str) -> GroupState:
    state = _states.get(group_id)
    if state is None:
        state = GroupState()
        _states[group_id] = state
    return state


def _now() -> datetime:
    return datetime.now(UTC)


def _jid_local(jid: str) -> str:
    """Devuelve la parte local del jid (antes de '@' y antes de ':'). WhatsApp usa
    el mismo numero/lid con sufijos distintos (@s.whatsapp.net, @lid)."""
    return jid.split("@", 1)[0].split(":", 1)[0] if jid else ""


def _is_lumi_mentioned(mentioned_jids: list[str], lumi_jids: list[str]) -> bool:
    if not lumi_jids or not mentioned_jids:
        return False
    lumi_locals = {_jid_local(j) for j in lumi_jids if j}
    return any(_jid_local(j) in lumi_locals for j in mentioned_jids)


def classify_inbound(
    group_id: str,
    msg: _GroupMsg,
    lumi_jids: list[str] | None = None,
) -> Decision:
    """Decide qué hacer con un mensaje entrante de grupo. Muta estado.

    lumi_jids: lista de jids propios de Lumi en la plataforma (puede incluir
    formas @s.whatsapp.net y @lid). La comparación es por parte local del jid.
    """
    state = _get(group_id)
    now = _now()

    lumi_locals = {_jid_local(j) for j in (lumi_jids or []) if j}
    is_reply_to_lumi = bool(
        (msg.reply_to_msg_id and msg.reply_to_msg_id in state.last_lumi_msg_ids)
        or (msg.replied_to_participant
            and _jid_local(msg.replied_to_participant) in lumi_locals)
    )
    is_mention = _is_lumi_mentioned(msg.mentioned_jids or [], lumi_jids or [])
    addressed = is_reply_to_lumi or is_mention

    if state.mode == "observing":
        if addressed:
            state.mode = "engaged"
            state.engaged_since = now
            state.last_engaged_activity = now
            state.messages_since_interpellation = 0
            state.pending_close = False
            logger.info(f"[group_policy] {group_id} OBSERVING → ENGAGED ({'reply' if is_reply_to_lumi else 'mention'})")
            return "engage_main"
        return "observe"

    # mode == engaged
    if state.pending_close:
        logger.info(f"[group_policy] {group_id} pending_close → confirm via LLM")
        return "confirm_close"

    if addressed:
        state.last_engaged_activity = now
        state.messages_since_interpellation = 0
        return "engage_main"

    # mensaje ambiguo dentro de ventana
    elapsed = (now - (state.last_engaged_activity or now)).total_seconds()
    if elapsed > ENGAGED_TIME_WINDOW_S or state.messages_since_interpellation >= ENGAGED_MESSAGE_WINDOW:
        state.pending_close = True
        logger.info(
            f"[group_policy] {group_id} window exhausted "
            f"(elapsed={elapsed:.0f}s, msgs={state.messages_since_interpellation}) "
            f"→ confirm_close"
        )
        return "confirm_close"

    state.messages_since_interpellation += 1
    return "engage_main"


def register_lumi_response(group_id: str, msg_id: str | None, user_msg_text: str = "") -> None:
    """Llamar después de cada respuesta de Lumi (LLM principal).

    Actualiza msg_ids para detección de replies, refresca timer, y evalúa
    si el último mensaje del usuario disparó un cierre determinista por regex.
    """
    state = _get(group_id)
    if msg_id:
        state.last_lumi_msg_ids.append(msg_id)
    state.last_engaged_activity = _now()
    state.messages_since_interpellation = 0
    if user_msg_text and CLOSING_PATTERNS.search(user_msg_text):
        state.pending_close = True
        logger.info(f"[group_policy] {group_id} closing regex matched → pending_close")


def close_window(group_id: str) -> None:
    state = _get(group_id)
    state.mode = "observing"
    state.engaged_since = None
    state.last_engaged_activity = None
    state.messages_since_interpellation = 0
    state.pending_close = False
    logger.info(f"[group_policy] {group_id} ENGAGED → OBSERVING (closed)")


def reopen_window(group_id: str) -> None:
    """Cancela pending_close cuando el LLM confirma que no era cierre real."""
    state = _get(group_id)
    state.pending_close = False
    state.last_engaged_activity = _now()
    state.messages_since_interpellation = 0
    logger.info(f"[group_policy] {group_id} pending_close cancelled → still ENGAGED")


def get_mode(group_id: str) -> str:
    return _get(group_id).mode


def reset_all() -> None:
    """Test helper."""
    _states.clear()


# ── Mini-LLM de confirmación de cierre ────────────────────────────────────────
# Cuando el determinista marca pending_close, esta función decide si el siguiente
# mensaje es un cierre real (responde corto + CLOSE) o sigue la conversación
# (KEEP → re-rutear al LLM principal).

from agent.expression.synapses import chat, ModelGroup

_CLOSE_TOKEN = re.compile(r"\[\s*CLOSE\s*\]", re.IGNORECASE)

_CLOSING_SYSTEM_PROMPT = (
    "Eres Lumi en un chat grupal. Acabas de tener una conversación con "
    "alguien y ahora llega un mensaje nuevo. Decide si ese mensaje cierra la "
    "conversación contigo o no.\n\n"
    "REGLAS:\n"
    "- Si es un cierre claro (agradecimiento, despedida, confirmación final "
    "tipo 'gracias Lumi', 'listo Lumi', 'chao Lumi', 'ok perfecto Lumi'), "
    "responde con 1 a 5 palabras naturales y termina tu respuesta con el "
    "token literal [CLOSE].\n"
    "- Si el mensaje continúa el tema, hace una nueva pregunta, o introduce "
    "algo relacionado, responde SÓLO con el token literal [KEEP] (sin nada "
    "más).\n"
    "- Si tienes dudas, prefiere [KEEP].\n\n"
    "Ejemplos:\n"
    "Mensaje: 'gracias Lumi' → 'con gusto [CLOSE]'\n"
    "Mensaje: 'listo Lumi, y qué tal el otro juego?' → '[KEEP]'\n"
    "Mensaje: 'ok Lumi perfecto' → 'cuando quieras [CLOSE]'\n"
)


async def confirm_closing(
    user_msg: str,
    recent_history: list[dict] | None = None,
) -> tuple[bool, str | None]:
    """Retorna (is_close, short_reply).

    is_close=True → short_reply tiene la respuesta breve a enviar al grupo.
    is_close=False → el caller debe re-enrutar al LLM principal.
    """
    context_lines = []
    for turn in (recent_history or [])[-4:]:
        role = "Lumi" if turn["role"] == "assistant" else "Usuario"
        context_lines.append(f"{role}: {turn['content']}")
    context_block = "\n".join(context_lines)

    user_content = (
        (f"Contexto reciente:\n{context_block}\n\n" if context_block else "")
        + f"Mensaje nuevo: {user_msg}"
    )

    messages = [
        {"role": "system", "content": _CLOSING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = await chat(
            messages=messages,
            model_group=ModelGroup.LIGHTWEIGHT,
            max_tokens=40,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning(f"[confirm_closing] LLM call failed ({e}); defaulting to KEEP")
        return False, None

    content = (resp.get("content") or "").strip()
    logger.info(f"[confirm_closing] raw_response={content!r}")

    if _CLOSE_TOKEN.search(content):
        short_reply = _CLOSE_TOKEN.sub("", content).strip() or "con gusto"
        return True, short_reply

    return False, None
