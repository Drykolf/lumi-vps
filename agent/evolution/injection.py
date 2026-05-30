"""
Selección por similitud de tastes/rules consolidados (manual §C.3).

En cada turno, working_memory pide top-N gustos y heurísticas relevantes; aquí se
embebe el contexto del turno y se hace cosine contra el `content`/`trigger_pattern`
de cada entry. Los seeds (immutable) reciben un pequeño boost para que pesen más
que entries evolutivas equiparables.

Los JSON se recargan solo si cambió su mtime; los embeddings de cada entry se
cachean en proceso por id.
"""
import json
from pathlib import Path

from agent.expression.embeddings import cosine_similarity, embed, embed_many
from agent.substrate.logger import get_logger

logger = get_logger("evolution.injection")

EVOLUTION_DIR = Path(__file__).resolve().parent.parent / "identity" / "evolution"

_IMMUTABLE_BOOST = 1.15
# Umbrales de similitud (cosine bge-m3). Las rules son disparadores específicos:
# es preferible inyectar cero a inyectar heurísticas no relacionadas (ver Q2).
_TASTE_SIM_FLOOR = 0.45
_RULE_SIM_FLOOR = 0.55


class EvolutionInjector:
    def __init__(self):
        self._caches: dict[str, dict] = {}
        self._mtimes: dict[str, float] = {}
        # kind -> {entry_id: vector}. Se llena de un solo batch por kind.
        self._embedding_caches: dict[str, dict[str, list[float]]] = {}

    def _load(self, kind: str) -> dict:
        path = EVOLUTION_DIR / f"lumi_{kind}.json"
        if not path.exists():
            return {}
        mtime = path.stat().st_mtime
        if self._mtimes.get(kind) != mtime:
            self._caches[kind] = json.loads(path.read_text())
            self._mtimes[kind] = mtime
            self._embedding_caches[kind] = {}  # invalida embeddings al cambiar el archivo
        return self._caches.get(kind, {})

    async def _warm_embeddings(
        self, kind: str, entries: dict, text_field: str
    ) -> dict[str, list[float]]:
        """Garantiza el vector de cada entry, embebido en UN solo request batch."""
        cache = self._embedding_caches.setdefault(kind, {})
        pending = [(eid, e[text_field]) for eid, e in entries.items() if eid not in cache]
        if pending:
            vectors = await embed_many([t for _, t in pending])
            for (eid, _), vec in zip(pending, vectors):
                cache[eid] = vec
        return cache

    async def select_tastes(
        self, message: str, recent_context: str, top_k: int = 5, min_confidence: float = 0.6
    ) -> list[dict]:
        data = self._load("tastes").get("tastes", {})
        if not data:
            return []
        eligible = {
            tid: t for tid, t in data.items()
            if not t.get("invalid_at") and t.get("confidence", 0) >= min_confidence
        }
        cache = await self._warm_embeddings("tastes", eligible, "content")
        # La query se rige por el MENSAJE actual. Incluir recent_context lo diluía:
        # un historial saturado de un tema (p.ej. "cielo") secuestraba la selección
        # y dejaba afuera gustos que el turno menciona explícitamente (p.ej. "café").
        # recent_context se usa solo como desempate ligero (anáfora/continuidad).
        msg_embedding = await embed(message)
        ctx_embedding = (
            await embed(f"{message} {recent_context}".strip())
            if recent_context.strip()
            else msg_embedding
        )
        scored: list[tuple[float, dict]] = []
        for tid, taste in eligible.items():
            vec = cache.get(tid, [])
            sim = max(
                cosine_similarity(msg_embedding, vec),
                0.85 * cosine_similarity(ctx_embedding, vec),
            )
            if taste.get("immutable"):
                sim *= _IMMUTABLE_BOOST
            if sim > _TASTE_SIM_FLOOR:
                scored.append((sim, taste))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:top_k]]

    async def select_rules(
        self, message: str, context_classification: str, top_k: int = 3, min_confidence: float = 0.7
    ) -> list[dict]:
        data = self._load("rules").get("rules", {})
        if not data:
            return []
        eligible = {
            rid: r for rid, r in data.items()
            if not r.get("invalid_at") and r.get("confidence", 0) >= min_confidence
        }
        cache = await self._warm_embeddings("rules", eligible, "trigger_pattern")
        context_embedding = await embed(f"{context_classification} {message}".strip())
        scored: list[tuple[float, dict]] = []
        for rid, rule in eligible.items():
            sim = cosine_similarity(context_embedding, cache.get(rid, []))
            # Penaliza reglas con bajo success rate (los seeds arrancan en ~1.0).
            success = rule.get("success_count", 0)
            failure = rule.get("failure_count", 0)
            success_rate = success / max(1, success + failure)
            sim *= 0.5 + 0.5 * success_rate
            if rule.get("immutable"):
                sim *= _IMMUTABLE_BOOST
            if sim > _RULE_SIM_FLOOR:
                scored.append((sim, rule))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]


_injector: EvolutionInjector | None = None


def get_injector() -> EvolutionInjector:
    global _injector
    if _injector is None:
        _injector = EvolutionInjector()
    return _injector
