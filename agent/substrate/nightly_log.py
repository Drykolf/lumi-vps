"""Human-readable persistent log for the last nightly_quiescence run.

Writes to `data/logs/nightly_quiescence.log` (overwrites each run). The
orchestrator instantiates `NightlyLog`, calls `section()` per completed
stage and `error()` when one raises. Flushing is incremental — every call
rewrites the file with what's been accumulated so far, so partial logs
survive crashes.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

UTC = timezone.utc
COL = timezone(timedelta(hours=-5))

_LOG_PATH = Path("data/logs/nightly_quiescence.log")


class NightlyLog:
    def __init__(self, label: str = "nightly_quiescence"):
        now_utc = datetime.now(UTC)
        now_col = now_utc.astimezone(COL)
        header = (
            f"[{label} {now_col.strftime('%d %b %Y %I:%M%p').lstrip('0')} COL"
            f" / {now_utc.isoformat(timespec='seconds')} UTC]"
        )
        self._lines: list[str] = [header, ""]
        self._flush()

    def section(self, title: str, **fields: Any) -> None:
        """Append a stage section with key/value pairs."""
        self._lines.append(f"## {title}")
        for k, v in fields.items():
            self._lines.append(f"  {k}: {_format_value(v)}")
        self._lines.append("")
        self._flush()

    def error(self, title: str, exc: BaseException) -> None:
        """Record that a stage raised, with exception class + message."""
        self._lines.append(f"## {title}")
        self._lines.append(f"  ERROR: {type(exc).__name__}: {exc}")
        self._lines.append("")
        self._flush()

    def note(self, text: str) -> None:
        """Free-form line for transitions or closing markers."""
        self._lines.append(text)
        self._flush()

    def _flush(self) -> None:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOG_PATH.write_text("\n".join(self._lines) + "\n", encoding="utf-8")


def _format_value(v: Any) -> str:
    """Pretty-print metric values for the log file."""
    if isinstance(v, set):
        items = sorted(v)
        if len(items) > 20:
            return f"[{', '.join(items[:20])}, ... +{len(items)-20} more]"
        return f"[{', '.join(items)}]" if items else "[]"
    if isinstance(v, (list, tuple)):
        if len(v) > 20:
            head = ", ".join(str(x) for x in v[:20])
            return f"[{head}, ... +{len(v)-20} more]"
        return f"[{', '.join(str(x) for x in v)}]"
    return str(v)
