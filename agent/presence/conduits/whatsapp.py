"""WhatsApp / Evolution API integration helpers."""
import os
import re
from dataclasses import dataclass, field

import httpx

from agent.memory.mindstream.social import get_identifier
from agent.substrate.logger import get_logger

logger = get_logger("presence.whatsapp")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")

_EMOTION_TAG = re.compile(r"\[[^\]]*\]")
_INNER_THOUGHT = re.compile(r"\{[^}]*\}")


# ── Outbound ──────────────────────────────────────────────────────────────────

def format_for_whatsapp(text: str) -> str:
    """Remueve emotion tags [..] e inner thoughts {..} antes de enviar."""
    text = _EMOTION_TAG.sub("", text)
    text = _INNER_THOUGHT.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def send_text(instance: str, jid: str, text: str) -> str | None:
    """POST /message/sendText/{instance}. jid puede ser persona o grupo.

    Retorna el msg_id (key.id) del mensaje enviado, o None si no se envió
    o si la respuesta no lo contiene.
    """
    api_key = os.getenv("EVOLUTION_API_KEY") or ""
    body = format_for_whatsapp(text)
    if not body:
        logger.info(f"[whatsapp] skipping empty send to jid={jid}")
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{EVOLUTION_API_URL}/message/sendText/{instance}",
            json={"number": jid, "text": body},
            headers={"apikey": api_key},
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            return None
        return ((data.get("key") or {}).get("id"))


# ── Inbound: validadores y extractores ────────────────────────────────────────

def is_authorized(payload: dict) -> bool:
    """True si la apikey de la instancia coincide (o si la env var no esta seteada)."""
    expected = os.getenv("EVOLUTION_INSTANCE_API_KEY")
    return not expected or payload.get("apikey") == expected


def check_event(payload: dict) -> str | None:
    """None si el evento es procesable; reason en otro caso."""
    event = payload.get("event")
    return None if event == "messages.upsert" else f"event={event}"


def is_from_me(data: dict) -> bool:
    return bool((data.get("key") or {}).get("fromMe"))


def extract_remote_jid(data: dict) -> str | None:
    return (data.get("key") or {}).get("remoteJid")


def extract_text(data: dict) -> str | None:
    """conversation o extendedTextMessage.text; None para no-texto."""
    msg = data.get("message") or {}
    return (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
    )


def extract_reply_and_mentions(data: dict) -> tuple[str | None, list[str]]:
    """Extrae (reply_to_msg_id, mentioned_jids) de extendedTextMessage.contextInfo."""
    msg = data.get("message") or {}
    ctx = (msg.get("extendedTextMessage") or {}).get("contextInfo") or {}
    reply_to = ctx.get("stanzaId")
    mentions = ctx.get("mentionedJid") or []
    if not isinstance(mentions, list):
        mentions = []
    return reply_to, mentions


def extract_sender_jid(data: dict, remote_jid: str) -> str | None:
    """En 1:1 el sender es remote_jid. En grupo, participantAlt (preferido) o participant."""
    if remote_jid.endswith("@g.us"):
        key = data.get("key") or {}
        return key.get("participantAlt") or key.get("participant")
    return remote_jid


def normalize_phone(jid: str) -> str:
    """573155963781:83@s.whatsapp.net -> 573155963781."""
    return jid.split("@", 1)[0].split(":", 1)[0]


def is_phone_jid(jid: str) -> bool:
    return jid.endswith("@s.whatsapp.net")


def build_metadata(remote_jid: str) -> dict:
    """Construye el metadata que recibe run()."""
    return {
        "source": "text",
        "channel": "whatsapp",
        "session_id": remote_jid,
        "conversation_active": True,
        "was_interruption": False,
        "interrupt_context": None,
    }


# ── Acopladora ────────────────────────────────────────────────────────────────

@dataclass
class InboundMessage:
    person_id: str
    text: str
    instance: str
    remote_jid: str
    metadata: dict
    msg_id: str | None = None
    reply_to_msg_id: str | None = None
    mentioned_jids: list[str] = field(default_factory=list)
    is_group: bool = False
    push_name: str | None = None


@dataclass
class Skip:
    reason: str


def parse_inbound(payload: dict) -> InboundMessage | Skip:
    """Encadena los validadores y extractores. No valida auth (eso es is_authorized)."""
    if (r := check_event(payload)) is not None:
        return Skip(r)

    data = payload.get("data") or {}
    if is_from_me(data):
        return Skip("fromMe")

    remote_jid = extract_remote_jid(data)
    if not remote_jid:
        return Skip("no remoteJid")

    text = extract_text(data)
    if not text:
        return Skip(f"non-text messageType={data.get('messageType')}")

    sender_jid = extract_sender_jid(data, remote_jid)
    if not sender_jid:
        return Skip("group message without participant")
    if not is_phone_jid(sender_jid):
        return Skip(f"non-phone sender jid: {sender_jid}")

    phone = normalize_phone(sender_jid)
    row = get_identifier("whatsapp", phone)
    if row is None:
        logger.warning(
            f"unknown contact phone={phone} remoteJid={remote_jid} "
            f"pushName={data.get('pushName')!r}"
        )
        return Skip("unknown contact")

    reply_to, mentions = extract_reply_and_mentions(data)
    return InboundMessage(
        person_id=row["person_id"],
        text=text,
        instance=payload.get("instance"),
        remote_jid=remote_jid,
        metadata=build_metadata(remote_jid),
        msg_id=(data.get("key") or {}).get("id"),
        reply_to_msg_id=reply_to,
        mentioned_jids=mentions,
        is_group=remote_jid.endswith("@g.us"),
        push_name=data.get("pushName"),
    )
