"""
MCP Bridge Server — seccion 7.5 del manual.
WebSocket persistente VPS <-> PC local.
Fase 3: acepta conexiones y registra por user_id.
Fase 4+: ejecuta tool calls remotos en el PC de Jose.
"""
import json
import uuid
import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("bridge")

# user_id -> WebSocket activo
_connections: dict[str, WebSocket] = {}
# request_id -> Future (para awaitar respuestas de tool calls)
_pending: dict[str, asyncio.Future] = {}


async def on_connect(ws: WebSocket, user_id: str):
    await ws.accept()
    _connections[user_id] = ws
    logger.info(f"Bridge conectado: {user_id}")
    try:
        async for raw in ws.iter_text():
            msg = json.loads(raw)
            if msg.get("type") in ("tool_result", "tool_error"):
                fut = _pending.pop(msg["request_id"], None)
                if fut and not fut.done():
                    result = msg.get("result") or {"error": msg.get("error")}
                    fut.set_result(result)
    except WebSocketDisconnect:
        _connections.pop(user_id, None)
        logger.info(f"Bridge desconectado: {user_id}")


async def call_remote(user_id: str, tool_name: str, args: dict, timeout: int = 30):
    ws = _connections.get(user_id)
    if not ws:
        return {"error": "bridge_not_connected"}

    request_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _pending[request_id] = fut

    try:
        await ws.send_text(json.dumps({
            "type": "tool_call",
            "request_id": request_id,
            "tool": tool_name,
            "args": args,
        }))
    except Exception:
        _connections.pop(user_id, None)
        _pending.pop(request_id, None)
        return {"error": "bridge_not_connected"}

    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(request_id, None)
        return {"error": "bridge_timeout"}

async def _heartbeat_loop(interval: int = 60):
    """Ping a todas las conexiones activas. Limpia las muertas."""
    while True:
        await asyncio.sleep(interval)
        dead = []
        for user_id, ws in list(_connections.items()):
            try:
                await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                dead.append(user_id)
                logger.info(f"Bridge heartbeat: conexion muerta detectada — {user_id}")
        for user_id in dead:
            _connections.pop(user_id, None)


async def start_heartbeat():
    asyncio.ensure_future(_heartbeat_loop())
    
def is_connected(user_id: str) -> bool:
    return user_id in _connections


def connected_users() -> list[str]:
    return list(_connections.keys())