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

ENGAGED_TIME_WINDOW_S = int(os.getenv("LUMI_GROUP_ENGAGED_WINDOW_S", "300"))
ENGAGED_MESSAGE_WINDOW = int(os.getenv("LUMI_GROUP_ENGAGED_MSG_WINDOW", "5"))

LUMI_NAMES = ("lumi", "loomy", "lummy", "lumii", "lumy")

_LUMI_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in LUMI_NAMES) + r")\b",
    re.IGNORECASE,
)

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


def classify_inbound(
    group_id: str,
    msg: _GroupMsg,
    lumi_jid: str | None = None,
) -> Decision:
    """Decide qué hacer con un mensaje entrante de grupo. Muta estado."""
    state = _get(group_id)
    now = _now()

    is_reply_to_lumi = bool(
        msg.reply_to_msg_id and msg.reply_to_msg_id in state.last_lumi_msg_ids
    )
    is_mention = (
        (lumi_jid and lumi_jid in (msg.mentioned_jids or []))
        or bool(_LUMI_NAME_RE.search(msg.text or ""))
    )
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
