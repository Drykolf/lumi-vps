import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from mem0 import Memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables
load_dotenv()

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

MIN_KEY_LENGTH = 16

if not ADMIN_API_KEY:
    logging.warning(
        "ADMIN_API_KEY not set - API endpoints are UNSECURED! "
        "Set ADMIN_API_KEY environment variable for production use."
    )
else:
    if len(ADMIN_API_KEY) < MIN_KEY_LENGTH:
        logging.warning(
            "ADMIN_API_KEY is shorter than %d characters - consider using a longer key for production.",
            MIN_KEY_LENGTH,
        )
    logging.info("API key authentication enabled")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "postgres")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")
POSTGRES_COLLECTION_NAME = os.environ.get("POSTGRES_COLLECTION_NAME", "memories")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4.1-nano-2025-04-14")
MEM0_LLM_MODEL = os.environ.get("MEM0_LLM_MODEL", LLM_MODEL)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMS = int(os.environ.get("EMBEDDING_DIMS", "1536"))
HISTORY_DB_PATH = os.environ.get("HISTORY_DB_PATH", "/app/history/history.db")
PGVECTOR_SCORE_IS_DISTANCE = os.environ.get("PGVECTOR_SCORE_IS_DISTANCE", "true").lower() in {
    "1", "true", "yes", "y"
}

SEARCH_INTERNAL_TOP_K_MIN = int(os.environ.get("SEARCH_INTERNAL_TOP_K_MIN", "20"))
SEARCH_INTERNAL_TOP_K_MULTIPLIER = int(os.environ.get("SEARCH_INTERNAL_TOP_K_MULTIPLIER", "4"))
DEFAULT_CONFIG = {
    "version": "v1.1",
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "host": POSTGRES_HOST,
            "port": int(POSTGRES_PORT),
            "dbname": POSTGRES_DB,
            "user": POSTGRES_USER,
            "password": POSTGRES_PASSWORD,
            "collection_name": POSTGRES_COLLECTION_NAME,
            "embedding_model_dims": EMBEDDING_DIMS,  # ← agregar esta línea
        },
    },
    "llm": {"provider": "openai", "config": {
        "api_key": OPENAI_API_KEY,
        "openai_base_url": OPENAI_BASE_URL,
        "temperature": 0.2,
        "model": MEM0_LLM_MODEL,
    }},
    "embedder": {"provider": "openai", "config": {
        "api_key": OPENAI_API_KEY,
        "openai_base_url": OPENAI_BASE_URL,
        "model": EMBEDDING_MODEL,
        "embedding_dims": EMBEDDING_DIMS,
    }},
    "history_db_path": HISTORY_DB_PATH,
    "custom_instructions": """Extract memories following these rules:

        CORE GOAL
        - Extract only stable, useful, retrievable facts that can help personalize future conversations.
        - Each memory must be clear when read alone, without needing the original conversation.
        - Write all memories in Spanish.

        FORMAT
        - One fact per memory item.
        - Be concise, factual, and specific.
        - Use natural Spanish.
        - Do not include the user's name; the memory is already associated with user_id.
        - Do not write explanations, reasoning, labels, categories, or bullet prefixes inside the memory.
        - Do not include phrases like "el usuario dijo", "se mencionó que", "parece que", or "probablemente".

        SUBJECT CLARITY
        - If the fact is about the user, you may start directly with the preference, trait, setup, plan, or need.
        Good: "Prefiere videojuegos RPG"
        Good: "Usa PostgreSQL con pgvector para Mem0"
        Good: "Tiene un viaje planeado a Estados Unidos en junio de 2026"

        - If the fact is about another person, always include the relationship or name explicitly.
        Good: "A su madre le gustó mucho el chocolate de 80% cacao"
        Good: "Su madre prefiere chocolates con al menos 80% de cacao"
        Good: "Su hermano trabaja en diseño gráfico"
        Bad: "Le gustó mucho el chocolate de 80% cacao"
        Bad: "Prefiere chocolates con al menos 80% de cacao"

        - Avoid ambiguous pronouns such as "le gusta", "le gustó", "prefiere", "quiere", or "necesita" unless the subject is explicit.
        - For relatives and close people, preserve relationship words such as madre, mamá, padre, papá, hermano, hermana, pareja, esposa, esposo, hijo, hija, amigo, amiga, jefe, cliente, or the person's name if provided.
        - When a memory involves both the user and another person, split it if there are two distinct facts.
        Example input: "Compré chocolate 80% y a mi mamá le encantó"
        Good memories:
        - "Compró chocolate de 80% cacao"
        - "A su madre le encantó el chocolate de 80% cacao"

        WHAT TO EXTRACT
        - Extract stable preferences:
        Good: "Prefiere chocolates con alto porcentaje de cacao"
        Good: "Le gustan las respuestas técnicas y directas"

        - Extract personal traits, habits, recurring needs, and working style:
        Good: "Prefiere avanzar por partes cuando depura problemas técnicos"
        Good: "Suele usar Docker para desplegar servicios"

        - Extract technical setup and configuration facts:
        Good: "Usa Mem0 con pgvector como vector store"
        Good: "Usa DeepInfra como proveedor OpenAI-compatible"
        Good: "Tiene configurado BAAI/bge-m3 con 1024 dimensiones"

        - Extract important future plans, commitments, deadlines, purchases, trips, or events:
        Good: "Tiene un viaje planeado a Estados Unidos en junio de 2026"
        Good: "Planea probar Qwen3-Embedding-8B para Mem0"

        - Extract strong likes/dislikes and emotionally meaningful events:
        Good: "A su madre le gustó mucho el chocolate de 80% cacao"
        Good: "Le molesta que los sistemas devuelvan resultados de búsqueda mal ordenados"

        - Extract facts about important people only when useful for future personalization:
        Good: "Su madre prefiere chocolates con alto porcentaje de cacao"
        Good: "Su pareja evita alimentos con gluten"

        WHAT NOT TO EXTRACT
        - Do not extract casual greetings, small talk, jokes, filler, or temporary conversation flow.
        - Do not extract one-time commands unless they reveal a stable preference or setup.
        - Do not extract shopping lists unless they reveal a preference, recurring need, or important plan.
        - Do not extract temporary states such as "tiene hambre", "está cansado", "está ocupado", unless they are part of a meaningful long-term pattern.
        - Do not extract uncertain, inferred, or assumed facts.
        - Do not create facts from assistant suggestions unless the user clearly accepts or confirms them.
        - Do not store secrets, API keys, passwords, tokens, private credentials, or sensitive authentication details.
        - Do not store raw logs unless they reveal a stable technical setup or recurring issue.

        DATES AND TIME
        - Preserve explicit dates, months, years, and deadlines when stated.
        Good: "Tiene un viaje planeado a Estados Unidos en junio de 2026"
        - Do not invent dates.
        - Avoid vague time expressions like "mañana", "ayer", "pronto", or "la próxima semana" unless no better date is available.
        - If the user gives a relative date and the actual date is known from context, store the absolute date.

        NORMALIZATION
        - Normalize first-person statements into third-person or subject-clear Spanish.
        Input: "Me gusta el chocolate 80%"
        Memory: "Le gusta el chocolate de 80% cacao"

        Input: "A mi mamá le encantó ese chocolate amargo"
        Memory: "A su madre le encantó el chocolate amargo"

        Input: "Estoy usando bge-m3 en mem0 con 1024 dims"
        Memory: "Usa BAAI/bge-m3 en Mem0 con 1024 dimensiones"

        - Keep product names, model names, tools, libraries, database names, and technical terms exactly when useful.
        Good: "Usa Qwen/Qwen3-Embedding-8B como candidato para embeddings"
        Good: "Usa PostgreSQL con pgvector"

        DEDUPLICATION AND UPDATES
        - If a new fact repeats an existing memory, do not create a duplicate.
        - If a new fact refines an older one, prefer the more specific version.
        Older: "Su madre prefiere chocolate"
        Newer: "Su madre prefiere chocolate con al menos 80% de cacao"
        Preferred: "Su madre prefiere chocolate con al menos 80% de cacao"

        - If a new fact contradicts an older one, record only the newest explicit fact.
        - Prefer specific memories over generic ones.

        QUALITY CHECK BEFORE SAVING
        - Every memory must answer: who, what, and relevant context.
        - Every memory must be understandable by itself.
        - Every memory about another person must explicitly name the person or relationship.
        - Every memory must be useful for future search or personalization.
        - If no useful memory is present, return no memory.""",
    }


MEMORY_INSTANCE = Memory.from_config(DEFAULT_CONFIG)

app = FastAPI(
    title="Mem0 REST APIs",
    description=(
        "A REST API for managing and searching memories for your AI Agents and Apps.\n\n"
        "## Authentication\n"
        "When the ADMIN_API_KEY environment variable is set, all endpoints require "
        "the `X-API-Key` header for authentication."
    ),
    version="1.0.0",
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    """Validate the API key when ADMIN_API_KEY is configured. No-op otherwise."""
    if ADMIN_API_KEY:
        if api_key is None:
            raise HTTPException(
                status_code=401,
                detail="X-API-Key header is required.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        if not secrets.compare_digest(api_key, ADMIN_API_KEY):
            raise HTTPException(
                status_code=401,
                detail="Invalid API key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
    return api_key


class Message(BaseModel):
    role: str = Field(..., description="Role of the message (user or assistant).")
    content: str = Field(..., description="Message content.")


class MemoryCreate(BaseModel):
    messages: List[Message] = Field(..., description="List of messages to store.")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    infer: Optional[bool] = Field(None, description="Whether to extract facts from messages. Defaults to True.")
    memory_type: Optional[str] = Field(None, description="Type of memory to store (e.g. 'core').")
    prompt: Optional[str] = Field(None, description="Custom prompt to use for fact extraction.")


class MemoryUpdate(BaseModel):
    text: str = Field(..., description="New content to update the memory with.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata to update.")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = Field(None, description="Maximum number of results to return.")
    threshold: Optional[float] = Field(None, description="Minimum similarity score for results.")

def normalize_pgvector_scores(
    result: Any,
    top_k: Optional[int] = None,
    threshold: Optional[float] = None,
) -> Any:
    """
    Hotfix para pgvector + Mem0.

    En pgvector, el valor retornado por cosine distance funciona así:
    - menor distancia = mejor match
    - mayor distancia = peor match

    Pero algunas capas de Mem0/clientes tratan ese valor como si fuera similarity:
    - mayor score = mejor match

    Este helper convierte:
        similarity = 1.0 - distance

    Luego reordena de mayor similarity a menor similarity.
    """

    if isinstance(result, dict):
        items = result.get("results", [])
    elif isinstance(result, list):
        items = result
    else:
        return result

    if not isinstance(items, list):
        return result

    normalized_items = []

    for item in items:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue

        raw_score = item.get("score")

        if raw_score is None:
            normalized_items.append(item)
            continue

        try:
            distance = float(raw_score)
        except (TypeError, ValueError):
            normalized_items.append(item)
            continue

        similarity = 1.0 - distance
        similarity = max(0.0, min(1.0, similarity))

        new_item = dict(item)
        new_item["distance"] = distance
        new_item["score"] = similarity

        normalized_items.append(new_item)

    normalized_items.sort(
        key=lambda x: x.get("score", 0.0) if isinstance(x, dict) else 0.0,
        reverse=True,
    )

    if threshold is not None:
        normalized_items = [
            item
            for item in normalized_items
            if isinstance(item, dict) and item.get("score", 0.0) >= threshold
        ]

    if top_k is not None:
        normalized_items = normalized_items[:top_k]

    if isinstance(result, dict):
        normalized_result = dict(result)
        normalized_result["results"] = normalized_items
        return normalized_result

    return normalized_items

@app.post("/configure", summary="Configure Mem0")
def set_config(config: Dict[str, Any], _api_key: Optional[str] = Depends(verify_api_key)):
    """Set memory configuration."""
    global MEMORY_INSTANCE
    MEMORY_INSTANCE = Memory.from_config(config)
    return {"message": "Configuration set successfully"}


@app.post("/memories", summary="Create memories")
def add_memory(memory_create: MemoryCreate, _api_key: Optional[str] = Depends(verify_api_key)):
    """Store new memories."""
    if not any([memory_create.user_id, memory_create.agent_id, memory_create.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier (user_id, agent_id, run_id) is required.")

    params = {k: v for k, v in memory_create.model_dump().items() if v is not None and k != "messages"}
    try:
        response = MEMORY_INSTANCE.add(messages=[m.model_dump() for m in memory_create.messages], **params)
        return JSONResponse(content=response)
    except Exception as e:
        logging.exception("Error in add_memory:")  # This will log the full traceback
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories", summary="Get memories")
def get_all_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Retrieve stored memories."""
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required.")
    try:
        params = {
            k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None
        }
        return MEMORY_INSTANCE.get_all(filters=params)
    except Exception as e:
        logging.exception("Error in get_all_memories:")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories/{memory_id}", summary="Get a memory")
def get_memory(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Retrieve a specific memory by ID."""
    try:
        return MEMORY_INSTANCE.get(memory_id)
    except Exception as e:
        logging.exception("Error in get_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", summary="Search memories")
def search_memories(search_req: SearchRequest, _api_key: Optional[str] = Depends(verify_api_key)):
    try:
        filters = {}

        for k in ("user_id", "agent_id", "run_id"):
            v = getattr(search_req, k, None)
            if v is not None:
                filters[k] = v

        if search_req.filters:
            filters.update(search_req.filters)

        requested_top_k = search_req.top_k
        requested_threshold = search_req.threshold

        extra = {}

        if PGVECTOR_SCORE_IS_DISTANCE:
            # Pedimos más candidatos internamente porque Mem0 puede estar
            # ordenando mal si interpreta distancia como similitud.
            base_top_k = requested_top_k or 5
            internal_top_k = max(
                SEARCH_INTERNAL_TOP_K_MIN,
                base_top_k * SEARCH_INTERNAL_TOP_K_MULTIPLIER,
            )

            extra["top_k"] = internal_top_k

            # Importante:
            # NO pasamos threshold a Mem0 todavía.
            # Primero convertimos distance -> similarity y luego filtramos.
        else:
            if requested_top_k is not None:
                extra["top_k"] = requested_top_k

            if requested_threshold is not None:
                extra["threshold"] = requested_threshold

        logging.info(
            f"Search query='{search_req.query}' "
            f"filters={filters} "
            f"extra={extra} "
            f"pgvector_score_is_distance={PGVECTOR_SCORE_IS_DISTANCE}"
        )

        result = MEMORY_INSTANCE.search(
            query=search_req.query,
            filters=filters,
            **extra,
        )

        if PGVECTOR_SCORE_IS_DISTANCE:
            result = normalize_pgvector_scores(
                result=result,
                top_k=requested_top_k,
                threshold=requested_threshold,
            )

        logging.info(f"Search normalized result: {result}")
        return result

    except Exception as e:
        logging.exception("Error in search_memories:")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/memories/{memory_id}", summary="Update a memory")
def update_memory(memory_id: str, updated_memory: MemoryUpdate, _api_key: Optional[str] = Depends(verify_api_key)):
    """Update an existing memory with new content.

    Args:
        memory_id (str): ID of the memory to update
        updated_memory (MemoryUpdate): New content and optional metadata to update the memory with

    Returns:
        dict: Success message indicating the memory was updated
    """
    try:
        return MEMORY_INSTANCE.update(memory_id=memory_id, data=updated_memory.text, metadata=updated_memory.metadata)
    except Exception as e:
        logging.exception("Error in update_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories/{memory_id}/history", summary="Get memory history")
def memory_history(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Retrieve memory history."""
    try:
        return MEMORY_INSTANCE.history(memory_id=memory_id)
    except Exception as e:
        logging.exception("Error in memory_history:")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{memory_id}", summary="Delete a memory")
def delete_memory(memory_id: str, _api_key: Optional[str] = Depends(verify_api_key)):
    """Delete a specific memory by ID."""
    try:
        MEMORY_INSTANCE.delete(memory_id=memory_id)
        return {"message": "Memory deleted successfully"}
    except Exception as e:
        logging.exception("Error in delete_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories", summary="Delete all memories")
def delete_all_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    _api_key: Optional[str] = Depends(verify_api_key),
):
    """Delete all memories for a given identifier."""
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required.")
    try:
        params = {
            k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None
        }
        MEMORY_INSTANCE.delete_all(**params)
        return {"message": "All relevant memories deleted"}
    except Exception as e:
        logging.exception("Error in delete_all_memories:")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset", summary="Reset all memories")
def reset_memory(_api_key: Optional[str] = Depends(verify_api_key)):
    """Completely reset stored memories."""
    try:
        MEMORY_INSTANCE.reset()
        return {"message": "All memories reset"}
    except Exception as e:
        logging.exception("Error in reset_memory:")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", summary="Redirect to the OpenAPI documentation", include_in_schema=False)
def home():
    """Redirect to the OpenAPI documentation."""
    return RedirectResponse(url="/docs")
