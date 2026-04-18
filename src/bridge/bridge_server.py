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
            if msg.get("type") == "tool_result":
                fut = _pending.pop(msg["request_id"], None)
                if fut and not fut.done():
                    fut.set_result(msg["result"])
    except WebSocketDisconnect:
        _connections.pop(user_id, None)
        logger.info(f"Bridge desconectado: {user_id}")


async def call_remote(user_id: str, tool_name: str, args: dict, timeout: int = 30):
    """
    Envia un tool call al PC del usuario y espera el resultado.
    Si el bridge no esta conectado, retorna error sin bloquear.
    """
    ws = _connections.get(user_id)
    if not ws:
        return {"error": "bridge_not_connected"}

    request_id = uuid.uuid4().hex
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    _pending[request_id] = fut

    await ws.send_text(json.dumps({
        "type": "tool_call",
        "request_id": request_id,
        "tool": tool_name,
        "args": args,
    }))

    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        _pending.pop(request_id, None)
        return {"error": "bridge_timeout"}


def is_connected(user_id: str) -> bool:
    return user_id in _connections


def connected_users() -> list[str]:
    return list(_connections.keys())