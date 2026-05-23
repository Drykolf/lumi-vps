from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Query, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal
import os
import httpx
import json
from dotenv import load_dotenv
from agent.cognition.stream import run, run_stream
from agent.perception.websocket import on_connect, connected_users, start_heartbeat
from agent.memory import get_user_information, set_user_information
from agent.memory.mindstream.social import (
    add_identifier,
    ensure_known_person,
    get_identifier,
    get_known_person,
)
from agent.substrate.logger import get_logger, configure_root
from agent.subconscious import init_databases
import agent.rhythm.heartbeat as scheduler

load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
configure_root()
logger = get_logger("main")

API_KEY = os.getenv("LUMI_API_KEY")

app = FastAPI(title="LUMI VPS", version="0.4.0", root_path="/lumi")


def verify_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


_DIRECT_CHANNELS = {"desktop", "web"}


class UnknownInboundUser(Exception):
    """Inbound whatsapp/discord identifier not mapped to a known person."""


def resolve_inbound_user_id(channel: str, raw_user_id: str) -> str:
    if channel in _DIRECT_CHANNELS:
        return raw_user_id
    row = get_identifier(channel, raw_user_id)
    if row is None:
        raise UnknownInboundUser(
            f"inbound {channel} identifier {raw_user_id!r} is not mapped to a known person"
        )
    return row["person_id"]


class ChatRequest(BaseModel):
    content: str
    user_id: str
    source: Literal["asr", "text"] = "text"
    channel: Literal["desktop", "discord", "whatsapp", "web"] = "desktop"
    session_id: str = "default"
    conversation_active: bool = True
    was_interruption: bool = False
    interrupt_context: str | None = None
    stream: bool = True


class ObserveRequest(BaseModel):
    user_id: str
    source: Literal["audio", "screen"] = "audio"
    content: str
    session_id: str = "default"

class UserProfileRequest(BaseModel):
    display_name: str
    description: str = ""
    metadata: dict = {}


class MapContactRequest(BaseModel):
    user_id: str
    platform: Literal["whatsapp", "discord"]
    identifier: str


class CreatePersonRequest(BaseModel):
    user_id: str
    display_name: str
    notes: str | None = None

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.4.0",
        "bridge_connected": connected_users(),
    }


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/v1/chat")
async def chat(req: ChatRequest, x_api_key: str = Header(...)):
    verify_key(x_api_key)

    try:
        person_id = resolve_inbound_user_id(req.channel, req.user_id)
    except UnknownInboundUser as e:
        raise HTTPException(status_code=404, detail=str(e))

    metadata = {
        "source": req.source,
        "channel": req.channel,
        "session_id": req.session_id,
        "conversation_active": req.conversation_active,
        "was_interruption": req.was_interruption,
        "interrupt_context": req.interrupt_context,
    }
    if req.stream:
        return StreamingResponse(
            run_stream(person_id, req.content, metadata),
            media_type="text/plain"
        )
    else:
        reply = await run(person_id, req.content, metadata)
        return {"reply": reply}


# ── Observe ───────────────────────────────────────────────────────────────────
# Fase 3: loguea y guarda. No responde al usuario.
# Fase 4+: extraction_agent ligero -> Mem0 (tipo passive_observation)

@app.post("/v1/observe")
async def observe(req: ObserveRequest, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    #logger.info(req.dict())
    logger.info(f"[observe] user={req.user_id} source={req.source} len={len(req.content)}")
    # TODO Fase 4: mem0.save(user_id, req.content, type="passive_observation")
    return {"status": "ok", "user_id": req.user_id}


# ── WhatsApp webhook (Evolution API) ──────────────────────────────────────────

from agent.presence.conduits.whatsapp_adapter import (
    Skip,
    handle_inbound,
    is_authorized,
    parse_inbound,
)


@app.post("/v1/chat/whatsapp")
async def whatsapp_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        raw = await request.body()
        logger.warning(f"[whatsapp-webhook] non-json body ({e}): {raw!r}")
        return {"status": "ignored", "reason": "non-json"}

    if not is_authorized(payload):
        logger.warning("[whatsapp-webhook] invalid apikey")
        raise HTTPException(status_code=401, detail="Unauthorized")
    logger.info("[whatsapp-webhook] received payload: %s", json.dumps(payload))
    parsed = parse_inbound(payload)
    if isinstance(parsed, Skip):
        return {"status": "ignored", "reason": parsed.reason}

    logger.info(
        f"[whatsapp-webhook] inbound person_id={parsed.person_id} "
        f"instance={parsed.instance} session_id={parsed.metadata['session_id']} "
        f"is_group={parsed.is_group} text={parsed.text!r}"
    )
    return await handle_inbound(parsed)


# ── Person management ─────────────────────────────────────────────────────────
# Admin endpoints: create a known_person row, then attach platform identifiers
# so that inbound messages from those identifiers resolve in /v1/chat.

@app.post("/v1/create-person")
async def create_person(req: CreatePersonRequest, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    person = ensure_known_person(
        req.user_id,
        display_name=req.display_name,
        notes=req.notes,
    )
    logger.info(f"[create-person] person_id={req.user_id} display_name={req.display_name!r}")
    return {
        "person_id": person["person_id"],
        "display_name": person["display_name"],
        "status": person["status"],
        "notes": person.get("notes"),
    }


@app.post("/v1/map-contact")
async def map_contact(req: MapContactRequest, x_api_key: str = Header(...)):
    verify_key(x_api_key)

    person = get_known_person(req.user_id)
    if person is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"person_id={req.user_id!r} does not exist; "
                f"create it first via POST /v1/create-person"
            ),
        )

    existing = get_identifier(req.platform, req.identifier)
    if existing and existing["person_id"] != req.user_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"identifier {req.identifier!r} on {req.platform} is already mapped "
                f"to person_id={existing['person_id']!r}"
            ),
        )

    row = add_identifier(req.user_id, req.platform, req.identifier, verified=True)
    logger.info(
        f"[map-contact] person_id={req.user_id} {req.platform}={req.identifier}"
    )
    return {
        "person_id": req.user_id,
        "display_name": person["display_name"],
        "platform": row["platform"],
        "identifier": row["identifier"],
        "verified": bool(row["verified"]),
    }


# ── Bridge ────────────────────────────────────────────────────────────────────
# WebSocket persistente VPS <-> PC local.
# Autenticacion por query param ?api_key=... (headers no disponibles en WS handshake).

@app.websocket("/v1/bridge")
async def bridge(ws: WebSocket, user_id: str = Query(...), api_key: str = Query(...)):
    if api_key != API_KEY:
        await ws.close(code=4001)
        return
    await on_connect(ws, user_id)

@app.on_event("startup")
async def startup():
    init_databases()
    await start_heartbeat()
    scheduler.start()

@app.get("/v1/tools")
async def get_tools(x_api_key: str = Header(...)):
    verify_key(x_api_key)
    from agent.faculties.registry import _local_tools, _remote_tools
    connected = connected_users()
    result = {}
    for name in _local_tools:
        result[name] = {"location": "vps", "connected": True}
    for name in _remote_tools:
        if name not in result:  # no duplicar si está en ambos
            result[name] = {"location": "bridge", "connected": bool(connected)}
    return {"tools": result, "bridge_connected": connected}

# ── LLM Test ─────────────────────────────────────────────────────────────────

@app.get("/v1/testllm")
async def test_llm(x_api_key: str = Header(...)):
    verify_key(x_api_key)
    from agent.expression.synapses import test_models
    return {"results": await test_models(reasoning_effort="none")}

# ── User Profiles ─────────────────────────────────────────────────────────────
@app.get("/v1/memories/{user_id}")
async def get_memories(user_id: str, x_api_key: str = Header(None)):
    if x_api_key != os.getenv("LUMI_API_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://localhost:8100/memories?user_id={user_id}",
            headers={"X-API-Key": os.getenv("MEM0_ADMIN_API_KEY")}
        )
        return resp.json()