"""
Tool dispatcher — executes local and remote tools.
Extracted from cognition/intention.py per separation of concerns.
"""
import json as _json
import logging
from agent.perception import websocket
from agent.faculties.registry import _local_tools, _remote_tools

logger = logging.getLogger("tools")


async def execute(tool_calls: list, user_id: str) -> list[dict]:
    results = []
    for call in tool_calls:
        name = call.get("function", {}).get("name")
        raw_args = call.get("function", {}).get("arguments", {})
        args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        logger.info(f"tool={name} args={args}")
        if name in _local_tools:
            try:
                result = await _local_tools[name](**args)
            except Exception as e:
                result = {"error": str(e)}
        elif name in _remote_tools:
            result = await websocket.call_remote(user_id, name, args)
        else:
            result = {"error": f"tool '{name}' no registrada"}

        logger.info(f"tool={name} user={user_id} result={result}")
        results.append({"tool": name, "result": result})

    return results
