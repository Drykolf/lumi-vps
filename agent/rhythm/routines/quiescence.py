"""
Nightly quiescence: deep maintenance at 3am COT.
Consolidates memories, relationships, profiles, tasks, and learnings.
"""
from agent.rhythm.state import rhythm_task


async def nightly_quiescence() -> None:
    """Deep nightly maintenance at 3am COT."""
    async with rhythm_task("nightly_quiescence"):
        await consolidate_daily_memories()
        await update_relationship_memory()
        await update_user_profiles()
        await analyze_daily_tasks()
        await extract_daily_learnings()
        await cleanup_memory_tiers()


async def consolidate_daily_memories() -> None:
    ...


async def update_relationship_memory() -> None:
    ...


async def update_user_profiles() -> None:
    """No-op: user_profiles table removed. Migrated to known_persons + Mem0."""
    pass


async def analyze_daily_tasks() -> None:
    ...


async def extract_daily_learnings() -> None:
    ...


async def cleanup_memory_tiers() -> None:
    ...


"""1. Leer history donde memory_evaluated = 0.
2. Agrupar por owner_user_id / sesión / día.
3. Extraer personas, hechos, relaciones y correcciones.
4. Resolver identidad usando known_persons + aliases + relations + contexto del día.
5. Si identidad está confirmada:
      actualizar known_persons
      actualizar person_profiles
      actualizar relations
      guardar memoria en Mem0 con metadata.person_id
6. Si identidad es ambigua:
      NO guardar en Mem0 scoped.
      dejar unresolved mention / log / propuesta de aclaración.
7. Marcar history como memory_evaluated."""

"""Diary entries
PROMPT:
Eres Lumi escribiendo una entrada privada de diario sobre lo que ocurrió hoy con el/los usuario(s).

Resume el día de forma narrativa, no como facts atómicos.
No inventes información.
No repitas cada mensaje.
Concéntrate en:
- temas importantes,
- decisiones tomadas,
- asuntos pendientes,
- tono emocional,
- continuidad de la relación,
- cosas que Lumi debería recordar mañana.

Mem0 ya maneja facts atómicos, así que incluye facts solo cuando sean importantes para la historia del día.

Escribe en primera persona como Lumi.
Mantén la entrada concisa pero suficiente para recuperar contexto en el futuro."""