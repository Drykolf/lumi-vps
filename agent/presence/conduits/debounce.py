"""Generic debounce buffer for inbound channel messages.

Accumulates messages per session key and fires the handler after
DEBOUNCE_SECONDS of silence OR when the message cap is reached.
"""
import asyncio
from dataclasses import dataclass, field
from agent.substrate.logger import get_logger

logger = get_logger("presence.debounce")


@dataclass
class _Slot:
    messages: list = field(default_factory=list)
    task: asyncio.Task | None = None


class DebouncePolicy:
    def __init__(self, debounce_seconds: float = 5.0, max_messages: int = 10):
        self.debounce_seconds = debounce_seconds
        self.max_messages = max_messages
        self._slots: dict[str, _Slot] = {}

    def enqueue(self, key: str, msg, handler) -> None:
        """Append msg to the buffer for key and reset the debounce timer.

        handler(list[msg]) is called once after debounce_seconds of silence
        or immediately when max_messages is reached.
        """
        slot = self._slots.get(key)
        if slot is None:
            slot = _Slot()
            self._slots[key] = slot

        slot.messages.append(msg)
        pending = len(slot.messages)

        if slot.task and not slot.task.done():
            slot.task.cancel()

        delay = 0.0 if pending >= self.max_messages else self.debounce_seconds
        slot.task = asyncio.create_task(self._fire(key, slot.messages, handler, delay))
        logger.info(
            f"[debounce] enqueued key={key!r} pending={pending} delay={delay}s"
        )

    async def _fire(self, key: str, messages: list, handler, delay: float):
        if delay > 0:
            await asyncio.sleep(delay)
        self._slots.pop(key, None)
        logger.info(f"[debounce] firing key={key!r} n={len(messages)}")
        try:
            await handler(messages)
        except Exception as exc:
            logger.error(f"[debounce] handler error key={key!r}: {exc}")
