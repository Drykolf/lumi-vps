from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal
import os
import logging
import json
from dotenv import load_dotenv
from src.agent.loop import run,run_stream
from src.bridge.bridge_server import on_connect, connected_users, start_heartbeat

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

API_KEY = os.getenv("LUMI_API_KEY")

app = FastAPI(title="LUMI VPS", version="0.4.0", root_path="/lumi")


def verify_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


class ChatRequest(BaseModel):
    content: str
    user_id: str
    source: Literal["asr", "text"] = "text"
    channel: Literal["desktop", "discord", "whatsapp", "web"] = "desktop"
    session_id: str = "default"
    conversation_active: bool = True
    was_interruption: bool = False
    interrupt_context: str | None = None


class ObserveRequest(BaseModel):
    user_id: str
    source: Literal["audio", "screen"] = "audio"
    content: str
    session_id: str = "default"


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
    metadata = {
        "source": req.source,
        "channel": req.channel,
        "session_id": req.session_id,
        "conversation_active": req.conversation_active,
        "was_interruption": req.was_interruption,
        "interrupt_context": req.interrupt_context,
    }
    return StreamingResponse(
        run_stream(req.user_id, req.content, metadata),
        media_type="text/plain"
    )


# ── Observe ───────────────────────────────────────────────────────────────────
# Fase 3: loguea y guarda. No responde al usuario.
# Fase 4+: extraction_agent ligero -> Mem0 (tipo passive_observation)

@app.post("/v1/observe")
async def observe(req: ObserveRequest, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    logger.info(f"[observe] user={req.user_id} source={req.source} len={len(req.content)}")
    # TODO Fase 4: mem0.save(user_id, req.content, type="passive_observation")
    return {"status": "ok", "user_id": req.user_id}


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
    await start_heartbeat()

@app.get("/v1/tools")
async def get_tools(x_api_key: str = Header(...)):
    verify_key(x_api_key)
    from src.agent import tools
    connected = connected_users()
    result = {}
    for name in tools._local_tools:
        result[name] = {"location": "vps", "connected": True}
    for name in tools._remote_tools:
        if name not in result:  # no duplicar si está en ambos
            result[name] = {"location": "bridge", "connected": bool(connected)}
    return {"tools": result, "bridge_connected": connected}