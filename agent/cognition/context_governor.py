"""Frame audit logging para la matriz de confusión de conversation_mode.

La selección/recorte real de contexto la hace working_memory.build_messages
(fases 2-6) y la política determinística vive en context_policy. Este módulo
sólo registra el veredicto del frame por turno a data/logs/governor.log para
muestrear y auditar la clasificación de modo (§13).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.substrate.logger import get_logger

logger = get_logger("agent.governor")

UTC = timezone.utc
_GOVERNOR_LOG_PATH = Path("data/logs/governor.log")


def log_frame_audit(user_id: str, message: str, frame: dict) -> None:
    """Anexa un registro JSONL por turno con el veredicto del frame.

    Sólo frame_audit: el presupuesto real (post-recorte) se loguea aparte en
    data/logs/dynamic.log desde build_messages."""
    try:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "user_id": user_id,
            "message": (message or "")[:200],
            "frame_audit": {
                "conversation_mode": frame.get("conversation_mode"),
                "user_emotion": frame.get("user_emotion"),
                "tool_plan_needs_tool": (frame.get("tool_plan") or {}).get("needs_tool"),
            },
        }
        _GOVERNOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _GOVERNOR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[frame_audit] write failed: {e}")
