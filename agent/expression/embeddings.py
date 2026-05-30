"""
Embedder directo — DeepInfra (OpenAI-compatible) con BAAI/bge-m3.

El repo embebe memorias de usuarios vía Mem0 (REST), pero la capa de evolución
necesita embeddings síncronos en el turno (cosine vs tastes/rules). Este helper
llama directo al endpoint de embeddings de DeepInfra — mismo modelo que usa Mem0,
así los vectores son coherentes — con cache en proceso para no re-embeber.
"""
import hashlib
import math
import os

from openai import AsyncOpenAI

from agent.substrate.logger import get_logger

logger = get_logger("embeddings")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

_client: AsyncOpenAI | None = None
# Cache en proceso: sha256(text) -> vector. Las entradas de evolución son pocas
# y estables, así que el cache se llena rápido y casi nunca se invalida.
_cache: dict[str, list[float]] = {}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )
    return _client


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def embed(text: str) -> list[float]:
    """Devuelve el vector de `text`. Cachea por hash del texto."""
    text = (text or "").strip()
    if not text:
        return []
    k = _key(text)
    cached = _cache.get(k)
    if cached is not None:
        return cached

    response = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    vector = response.data[0].embedding
    _cache[k] = vector
    return vector


async def embed_many(texts: list[str]) -> list[list[float]]:
    """Embebe varios textos en UNA sola llamada (los que no estén en cache).

    Evita el fan-out de N llamadas secuenciales al recuperar tastes/rules: el
    catálogo entero se embebe en un request. Respeta el cache por texto.
    """
    cleaned = [(t or "").strip() for t in texts]
    keys = [_key(t) if t else None for t in cleaned]

    # Sólo pedimos los que faltan, deduplicados.
    missing: dict[str, str] = {}  # key -> text
    for k, t in zip(keys, cleaned):
        if k and k not in _cache and k not in missing:
            missing[k] = t

    if missing:
        miss_keys = list(missing.keys())
        response = await _get_client().embeddings.create(
            model=EMBEDDING_MODEL,
            input=[missing[k] for k in miss_keys],
        )
        for k, item in zip(miss_keys, response.data):
            _cache[k] = item.embedding

    return [_cache.get(k, []) if k else [] for k in keys]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores. 0.0 si alguno es vacío o nulo."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
