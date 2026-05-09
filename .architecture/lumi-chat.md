Arquitectura completa propuesta:
src/skills/
│
├── — ESCRITURA (cuándo y qué guardar) ──────────────────
├── memory_policy.md       ← qué datos guardar por persona según interest_score
├── interest_policy.md     ← cómo varía el interest_score
├── relation_policy.md     ← cómo guardar relaciones entre personas
│
├── — LECTURA (cuándo y qué cargar) ─────────────────────
├── memory_search.md       ← qué buscar, cuándo, y qué inyectar al contexto
│
├── — COMPORTAMIENTO (cómo actuar con lo que cargó) ─────
├── attitude_policy.md     ← honesty rule, cómo expresar interés/desagrado
├── mood_policy.md         ← cómo interest y eventos afectan el mood
│
└── — REFLEXIÓN (al cierre de sesión) ───────────────────
    └── reflection_policy.md  ← session_summary, user_profile, lumi_state update

Pipeline completo:
TURNO ENTRANTE
    ↓
[memory_search.md] → decide qué buscar y qué inyectar al contexto
[attitude_policy.md] → guía cómo Lumi usa lo que encontró
    ↓
RESPUESTA DE LUMI
    ↓
CIERRE DE TURNO
    ↓
[interest_policy.md] → recalcula interest_scores
[memory_policy.md] → guarda datos de personas según nuevo score
[relation_policy.md] → actualiza relaciones
[mood_policy.md] → ajusta mood de Lumi

CIERRE DE SESIÓN (+5 turnos)
    ↓
[reflection_policy.md] → session_summary + user_profile + lumi_state