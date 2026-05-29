"""
Memory plan consumer — ejecuta las queries que el frame analyzer dejó en
`frame["memory_plan"]` contra Mem0. Reemplaza las búsquedas implícitas que
antes hacía `_build_dynamic_suffix` (global con message literal) y
`_resolve_entities` (scoped por persona con message literal).

Mem0 es subject-centric (Modelo C): user_id en Mem0 = la persona SOBRE la que
se almacena el hecho, no el hablante. Por eso:
- global_user_queries → search bajo el speaker.
- entity_scoped_queries → search bajo el person_id resuelto (fallback al
  speaker si la entidad no se resolvió).
- relationship_queries → fan-out a speaker + cada person_id resuelto que
  aparezca en `entities[]` de la query.
"""
import asyncio

from agent.memory import search_relevant
from agent.substrate.logger import get_logger

logger = get_logger("agent.memory_plan")


def _build_entity_index(entities_context: list[dict]) -> dict[str, str]:
    """Map lowercased reference labels → person_id for resolved entities only."""
    index: dict[str, str] = {}
    for ctx in entities_context or []:
        if ctx.get("status") != "resolved":
            continue
        pid = ctx.get("person_id")
        if not pid:
            continue
        for label in (
            ctx.get("display_name"),
            ctx.get("raw_name"),
            (ctx.get("mention") or {}).get("raw_text"),
            (ctx.get("mention") or {}).get("normalized_name"),
        ):
            if label:
                index[label.strip().lower()] = pid
    return index


async def resolve_memory_plan(
    speaker_user_id: str,
    plan: dict,
    entities_context: list[dict],
    per_query_limit: int = 3,
    global_limit: int = 5,
    min_score: float = 0.5,
) -> list[str]:
    """Run all queries described by frame['memory_plan'], deduped, ordered by appearance.

    Returns [] if should_search_memory is False or all lists are empty.
    No fallback to message-as-query — the frame is the authority.
    """
    if not isinstance(plan, dict) or not plan.get("should_search_memory"):
        return []

    globals_ = [q for q in (plan.get("global_user_queries") or []) if isinstance(q, str) and q.strip()]
    scoped_ = [q for q in (plan.get("entity_scoped_queries") or []) if isinstance(q, dict) and q.get("query")]
    rel_ = [q for q in (plan.get("relationship_queries") or []) if isinstance(q, dict) and q.get("query")]

    if not (globals_ or scoped_ or rel_):
        return []

    entity_index = _build_entity_index(entities_context)
    tasks: list = []

    for q in globals_:
        tasks.append(search_relevant(speaker_user_id, q, limit=global_limit, min_score=min_score))

    for q in scoped_:
        ref = (q.get("entity_ref") or "").strip().lower()
        target = entity_index.get(ref, speaker_user_id)
        tasks.append(search_relevant(target, q["query"], limit=per_query_limit, min_score=min_score))

    # TODO(lumi-as-subject): la consolidación nocturna debería empezar a escribir
    # las opiniones/observaciones de Lumi sobre personas bajo user_id="lumi"
    # (con metadata.about_person_id), como complemento semántico al
    # `interest_score` de known_persons. Cuando eso exista, "Lumi" en
    # relationship_queries.entities deja de ser un caso especial — pasa a ser
    # otro person_id buscable en el fan-out.
    for q in rel_:
        targets: list[str] = [speaker_user_id]
        seen = {speaker_user_id}
        for name in (q.get("entities") or []):
            if not isinstance(name, str):
                continue
            n = name.strip().lower()
            if n in ("lumi", "asistente", "assistant"):
                logger.info("[memory_plan] skipping 'Lumi' in relationship_query (no subject yet)")
                continue
            pid = entity_index.get(n)
            if pid and pid not in seen:
                targets.append(pid)
                seen.add(pid)
        for t in targets:
            tasks.append(search_relevant(t, q["query"], limit=per_query_limit, min_score=min_score))

    raw_results: list[list[str]] = []
    if tasks:
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for r in gathered:
            if isinstance(r, Exception):
                logger.warning(f"[memory_plan] search_relevant failed: {r}")
                continue
            raw_results.append(r or [])

    seen_mem: set[str] = set()
    out: list[str] = []
    for batch in raw_results:
        for mem in batch:
            if mem and mem not in seen_mem:
                seen_mem.add(mem)
                out.append(mem)

    logger.info(
        f"[memory_plan] global={len(globals_)} scoped={len(scoped_)} rel={len(rel_)} "
        f"→ {len(out)} hits after dedupe"
    )
    return out
