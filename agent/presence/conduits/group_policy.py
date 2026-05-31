"""Group participation policy — decisión por mensaje.

Lumi siempre observa los grupos, pero sólo responde cuando se le habla
explícitamente en ese mensaje concreto: una @mención directa o un reply/quote a
un mensaje suyo. No hay modo "engaged" pegajoso ni maquinaria de cierre: cada
mensaje se evalúa de forma independiente.

Agnóstico de plataforma; hoy sólo lo usa el webhook de WhatsApp. El único estado
en memoria del proceso es el registro de los IDs de los últimos mensajes de Lumi
por grupo (para detectar replies a ella). Si el server reinicia se pierde, lo que
sólo afecta la detección de replies por msg_id hasta que Lumi vuelva a hablar.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal, Protocol

from agent.substrate.logger import get_logger

logger = get_logger("presence.group_policy")

Decision = Literal["observe", "engage_main"]

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
    last_lumi_msg_ids: deque[str] = field(default_factory=lambda: deque(maxlen=_LUMI_MSG_ID_CAP))


_states: dict[str, GroupState] = {}


def _get(group_id: str) -> GroupState:
    state = _states.get(group_id)
    if state is None:
        state = GroupState()
        _states[group_id] = state
    return state


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
    """Decide qué hacer con un mensaje entrante de grupo.

    Responde ("engage_main") sólo si el mensaje interpela a Lumi: @mención o
    reply/quote a un mensaje suyo. En cualquier otro caso, observa.

    lumi_jids: lista de jids propios de Lumi en la plataforma (puede incluir
    formas @s.whatsapp.net y @lid). La comparación es por parte local del jid.
    """
    state = _get(group_id)

    lumi_locals = {_jid_local(j) for j in (lumi_jids or []) if j}
    is_reply_to_lumi = bool(
        (msg.reply_to_msg_id and msg.reply_to_msg_id in state.last_lumi_msg_ids)
        or (msg.replied_to_participant
            and _jid_local(msg.replied_to_participant) in lumi_locals)
    )
    is_mention = _is_lumi_mentioned(msg.mentioned_jids or [], lumi_jids or [])
    addressed = is_reply_to_lumi or is_mention

    if addressed:
        logger.info(f"[group_policy] {group_id} addressed ({'reply' if is_reply_to_lumi else 'mention'}) → engage_main")
        return "engage_main"
    return "observe"


def register_lumi_response(group_id: str, msg_id: str | None) -> None:
    """Llamar después de cada respuesta de Lumi: registra el msg_id para poder
    detectar replies a ella en mensajes posteriores."""
    if msg_id:
        _get(group_id).last_lumi_msg_ids.append(msg_id)


def reset_all() -> None:
    """Test helper."""
    _states.clear()
