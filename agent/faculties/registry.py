"""
Tool registry — local and remote tool schemas.
Extracted from cognition/intention.py per separation of concerns:
  cognition/intention → intent (decides what tool is needed)
  faculties/registry  → registration (knows what tools exist)
  faculties/dispatcher → execution (runs the tools)
"""
from agent.faculties.base import BaseTool

_local_tools: dict[str, callable] = {}
_remote_tools: dict[str, dict] = {}


def register_tool(tool: BaseTool):
    _local_tools[tool.name] = tool.run
    _remote_tools[tool.name] = tool.schema()


def register_remote(name: str, schema: dict):
    _remote_tools[name] = schema


def all_schemas() -> list[dict]:
    return list(_remote_tools.values())
