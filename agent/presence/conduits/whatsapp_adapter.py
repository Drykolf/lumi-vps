"""WhatsApp / Evolution API integration helpers."""
import os
import re
from dataclasses import dataclass, field

import httpx

from agent.memory.mindstream.social import get_identifier, add_identifier
from agent.substrate.logger import get_logger

logger = get_logger("presence.whatsapp")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")


def _lumi_jids() -> list[str]:
    """LUMI_WHATSAPP_JIDS = lista comma-separated (acepta @s.whatsapp.net y @lid)."""
    raw = os.getenv("LUMI_WHATSAPP_JIDS", "")
    return [j.strip() for j in raw.split(",") if j.strip()]

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


def _resolve_context_info(data: dict) -> dict:
    """Devuelve el contextInfo correcto. Evolution lo eleva a data.contextInfo,
    pero otros entornos Baileys lo dejan dentro de message.*. Precedencia:
      1. data.contextInfo                                   (Evolution actual)
      2. message.extendedTextMessage.contextInfo            (Baileys clásico)
      3. message.contextInfo                                (fallback)
    """
    if (ctx := data.get("contextInfo")):
        return ctx
    msg = data.get("message") or {}
    if (ctx := (msg.get("extendedTextMessage") or {}).get("contextInfo")):
        return ctx
    return msg.get("contextInfo") or {}


def extract_reply_and_mentions(data: dict) -> tuple[str | None, list[str], str | None]:
    """Extrae (reply_to_msg_id, mentioned_jids, replied_to_participant) del contextInfo.

    `replied_to_participant` es el autor del mensaje citado (en replies); útil
    para detectar replies a Lumi sin depender del cache de msg_ids enviados.
    """
    ctx = _resolve_context_info(data)
    reply_to = ctx.get("stanzaId")
    mentions = ctx.get("mentionedJid") or []
    if not isinstance(mentions, list):
        mentions = []
    replied_to_participant = ctx.get("participant")
    return reply_to, mentions, replied_to_participant


def extract_quoted_text(data: dict) -> str | None:
    """Texto del mensaje citado en un reply (None si no hay reply o no es texto)."""
    ctx = _resolve_context_info(data)
    quoted = ctx.get("quotedMessage") or {}
    return (
        quoted.get("conversation")
        or (quoted.get("extendedTextMessage") or {}).get("text")
    )


def _jid_local(jid: str) -> str:
    """573155963781:83@s.whatsapp.net → 573155963781. Mismo helper que en group_policy."""
    return jid.split("@", 1)[0].split(":", 1)[0] if jid else ""


def replace_lumi_mentions(text: str, lumi_jids: list[str]) -> str:
    """En WhatsApp el @mention en texto solo lleva el número (sin sufijo @lid ni
    @s.whatsapp.net). Reemplaza '@<numero>' por '@lumi' para cualquier jid
    configurado de Lumi."""
    if not text or not lumi_jids:
        return text
    locals_ = [_jid_local(j) for j in lumi_jids if j]
    locals_ = [l for l in locals_ if l]
    if not locals_:
        return text
    pattern = re.compile(r"@(" + "|".join(re.escape(l) for l in locals_) + r")\b")
    return pattern.sub("@lumi", text)


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


def _sync_sender_lid(data: dict, person_id: str) -> None:
    """Si el sender tiene un JID @lid (grupos), lo registra como identificador
    adicional de WhatsApp la primera vez que aparece. Solo se llama cuando
    person_id ya fue verificado via get_identifier(phone), así que el registro
    solo ocurre para personas ya conocidas."""
    key = data.get("key") or {}
    participant = key.get("participant", "")
    if not participant or not participant.endswith("@lid"):
        return
    lid = normalize_phone(participant)
    if not lid:
        return
    if get_identifier("whatsapp", lid):
        return
    try:
        add_identifier(person_id, "whatsapp", lid, verified=True, notes="lid")
        logger.info(f"[whatsapp] registered LID {lid} → person_id={person_id}")
    except Exception as e:
        logger.warning(f"[whatsapp] failed to register LID {lid}: {e}")


def replace_person_mentions(text: str, mentioned_jids: list[str]) -> str:
    """Reemplaza @<lid_o_telefono> en el texto por @<display_name> para personas
    conocidas. Usa el mismo normalize_phone que el resto del pipeline."""
    if not text or not mentioned_jids:
        return text
    resolved: dict[str, str] = {}
    for jid in mentioned_jids:
        local = normalize_phone(jid)
        if not local:
            continue
        row = get_identifier("whatsapp", local)
        if row:
            resolved[local] = row["display_name"]
    if not resolved:
        return text
    pattern = re.compile(r"@(" + "|".join(re.escape(k) for k in resolved) + r")\b")
    return pattern.sub(lambda m: f"@{resolved[m.group(1)]}", text)


def build_metadata(remote_jid: str) -> dict:
    """Construye el metadata que recibe run()."""
    return {
        "source": "text",
        "platform": "whatsapp",
        "channel_id": remote_jid,
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
    replied_to_participant: str | None = None
    quoted_text: str | None = None
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

    text = replace_lumi_mentions(text, _lumi_jids())

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

    _sync_sender_lid(data, row["person_id"])

    reply_to, mentions, replied_to_participant = extract_reply_and_mentions(data)
    text = replace_person_mentions(text, mentions)
    quoted_text = extract_quoted_text(data)
    return InboundMessage(
        person_id=row["person_id"],
        text=text,
        instance=payload.get("instance"),
        remote_jid=remote_jid,
        metadata=build_metadata(remote_jid),
        msg_id=(data.get("key") or {}).get("id"),
        reply_to_msg_id=reply_to,
        mentioned_jids=mentions,
        replied_to_participant=replied_to_participant,
        quoted_text=quoted_text,
        is_group=remote_jid.endswith("@g.us"),
        push_name=data.get("pushName"),
    )


# ── Orquestación: dispatch entre 1:1 y grupo ──────────────────────────────────

from agent.cognition.stream import run, observe_turn
from agent.memory import save_turn, get_recent_channel_log
from agent.presence.conduits import group_policy
from agent.presence.conduits.debounce import DebouncePolicy

_debounce = DebouncePolicy(debounce_seconds=5.0, max_messages=10)


# ── Flush handlers (llamados por el debounce tras la ventana de silencio) ──────

async def _flush_direct(messages: list) -> None:
    parsed = messages[-1]
    parsed.metadata["channel_type"] = "direct"
    # Concatenar todos los mensajes de la ventana como un solo turno
    text = "\n".join(m.text for m in messages)
    reply = await run(parsed.person_id, text, parsed.metadata)
    try:
        await send_text(parsed.instance, parsed.remote_jid, reply)
    except Exception as e:
        logger.error(f"[flush_direct] sendText failed: {e}")


async def _flush_group(messages: list) -> None:
    # Guardar todos los mensajes anteriores al ultimo en el historial individualmente
    for m in messages[:-1]:
        save_turn(m.person_id, "user", m.text, channel_id=m.metadata["channel_id"])

    parsed = messages[-1]
    parsed.metadata["channel_type"] = "group"
    llm_text = parsed.text
    if parsed.quoted_text:
        llm_text = (
            f"{parsed.text}\n"
            f"(el usuario esta respondiendo directamente a un mensaje anterior: "
            f"{parsed.quoted_text})"
        )
    reply = await run(parsed.person_id, llm_text, parsed.metadata)
    try:
        sent_id = await send_text(parsed.instance, parsed.remote_jid, reply)
    except Exception as e:
        logger.error(f"[flush_group] sendText failed: {e}")
        return
    group_policy.register_lumi_response(
        parsed.remote_jid, sent_id, user_msg_text=parsed.text
    )


# ── Handlers de entrada ───────────────────────────────────────────────────────

async def _handle_group(parsed: InboundMessage) -> dict:
    import asyncio
    decision = group_policy.classify_inbound(
        parsed.remote_jid, parsed, lumi_jids=_lumi_jids()
    )

    if decision == "observe":
        asyncio.create_task(
            observe_turn(parsed.person_id, parsed.text, parsed.metadata["channel_id"])
        )
        return {"status": "observed", "person_id": parsed.person_id}

    if decision == "confirm_close":
        recent = get_recent_channel_log(parsed.metadata["channel_id"], limit=4)
        is_close, short_reply = await group_policy.confirm_closing(parsed.text, recent)
        if is_close:
            save_turn(
                parsed.person_id, "user", parsed.text,
                channel_id=parsed.metadata["channel_id"],
            )
            try:
                sent_id = await send_text(
                    parsed.instance, parsed.remote_jid, short_reply
                )
            except Exception as e:
                logger.error(f"sendText (close) failed: {e}")
                sent_id = None
            save_turn(
                parsed.person_id, "assistant", short_reply,
                channel_id=parsed.metadata["channel_id"],
            )
            group_policy.close_window(parsed.remote_jid)
            return {"status": "closed", "person_id": parsed.person_id, "msg_id": sent_id}
        group_policy.reopen_window(parsed.remote_jid)
        # fallthrough → engage_main con debounce

    # engage_main (o reabierto tras KEEP): encolar y responder tras ventana de silencio
    cid = parsed.metadata["channel_id"]
    _debounce.enqueue(cid, parsed, _flush_group)
    return {"status": "queued", "person_id": parsed.person_id}


async def _handle_direct(parsed: InboundMessage) -> dict:
    cid = parsed.metadata["channel_id"]
    _debounce.enqueue(cid, parsed, _flush_direct)
    return {"status": "queued", "person_id": parsed.person_id}


async def handle_inbound(parsed: InboundMessage) -> dict:
    if parsed.is_group:
        return await _handle_group(parsed)
    return await _handle_direct(parsed)
