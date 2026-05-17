# Lumi Phase 4A — Known Persons + Social Read Path Plan

## Estado del cambio

Este documento asume que el schema social de `core.db` cambió:

- Se eliminan conceptualmente `person_interest` y `user_profiles`.
- Se crea `known_persons` como catálogo base de personas conocidas por Lumi.
- Se reemplaza/actualiza `relations` como grafo dirigido entre `person_id`s.
- No se conecta todavía el flujo al prompt principal.
- No se modifica todavía `agent/cognition/stream.py`.
- No se modifica todavía la composición de contexto que entra al LLM principal desde `agent/cognition/working_memory.py`.

La prioridad de esta fase es crear funciones seguras para leer/resolver personas sin escribir memorias semánticas y sin activar inyección al prompt principal.

---

## SQL seed inicial para Jose

Agregar esto en `agent/subconscious/seeds/initial_state.sql`, después de crear las tablas de `002_create_core.sql`.

```sql
INSERT OR IGNORE INTO known_persons (
    person_id,
    display_name,
    canonical_name,
    canonical_name_norm,
    aliases_json,
    interest_score,
    emotional_tone,
    status,
    mention_count,
    notes
) VALUES (
    'jose',
    'Jose Barco',
    'Jose Barco',
    'jose barco',
    '[
        {"value":"Jose Barco","norm":"jose barco","type":"full_name","confirmed":true,"confidence":1.0},
        {"value":"Jose","norm":"jose","type":"first_name","confirmed":true,"confidence":1.0}
    ]',
    1.00,
    'positive',
    'active',
    1,
    'Usuario principal de Lumi; prioridad afectiva y contextual máxima.'
);
```

No agregar `"yo"` como alias global. `yo` depende del hablante actual, no de una persona global. El mapeo `user_id='jose'` -> `person_id='jose'` debe manejarse desde el código.

---

## Objetivo de implementación

Crear una capa social nueva basada en `known_persons` y `relations` que permita:

1. Asegurar que una persona exista en `known_persons`.
2. Buscar candidatos por nombre, alias o descriptor.
3. Resolver menciones con estados seguros.
4. Leer relaciones estructuradas.
5. Mantener compatibilidad temporal con funciones viejas para no romper `working_memory.py` ni otros módulos.
6. Preparar el read-path de Mem0 sin conectarlo todavía al prompt principal.

Estados de resolución:

```text
resolved                -> identidad segura; se puede usar perfil/relaciones/Mem0 scoped.
candidate_unconfirmed   -> una candidata probable; Lumi debe pedir confirmación natural, no usar Mem0 privado.
ambiguous               -> varias candidatas; Lumi debe preguntar cuál persona.
unknown                 -> no hay candidata; no crear todavía en read-path.
```

Regla central:

```text
Nunca resolver una persona por nombre global únicamente.
Toda resolución debe anclarse al user_id/person_id actual mediante relaciones, alias fuerte o contexto explícito.
```

---

## Rutas que debe revisar el agente local

### 1. `agent/subconscious/migrations/002_create_core.sql`

Debe contener:

- `known_persons`
- `relations`
- tablas restantes que sigan existiendo, como `lumi_state` y `skill_proposals`

Debe eliminar o dejar de crear:

- `person_interest`
- `user_profiles`

Revisar que el `DROP TABLE` respete dependencias:

```sql
DROP TABLE IF EXISTS relations;
DROP TABLE IF EXISTS user_profiles;
DROP TABLE IF EXISTS person_interest;
DROP TABLE IF EXISTS known_persons;
```

Luego crear `known_persons` antes de `relations`.

### 2. `agent/subconscious/seeds/initial_state.sql`

Debe actualizarse para usar `known_persons`.

Acciones:

- Insertar a Jose con el SQL seed incluido arriba.
- Revisar si existen inserts viejos a `person_interest` o `user_profiles` y eliminarlos o migrarlos.
- Mantener inserts de `lumi_state` y otros seeds no sociales.
- Todos los seeds deben ser idempotentes porque `CoreRepository.init()` ejecuta seeds después de migrations.

### 3. `agent/subconscious/repositories/core.py`

Actualizar comentarios/docstring:

Antes probablemente decía:

```text
Tables: person_interest, user_profiles, relations, lumi_state, skill_proposals
```

Después debe decir:

```text
Tables: known_persons, relations, lumi_state, skill_proposals
```

No cambiar comportamiento de inicialización salvo que sea necesario. El patrón deseado sigue siendo:

```text
1. ejecutar migration
2. ejecutar seeds
```

### 4. `agent/memory/mindstream/social.py`

Este archivo debe ser el foco principal de implementación.

Debe dejar de asumir estas tablas:

```text
person_interest
user_profiles
relations con columna inferred
```

Y pasar a usar:

```text
known_persons
relations con relation_label, status, confidence
```

Implementar funciones nuevas y mantener shims temporales para no romper importadores actuales.

### 5. `agent/memory/__init__.py`

Debe exportar las funciones nuevas del social layer.

También debe seguir exportando temporalmente funciones legacy que `working_memory.py` y otros módulos todavía importan:

```python
get_user_information
set_user_information
create_person_interest
add_delta
commit_session_close
run_decay
get_relations
add_relation
infer_family_relations
find_user_id_by_name
```

Estas funciones pueden convertirse en wrappers sobre `known_persons`, pero no deben desaparecer en esta fase.

### 6. `agent/memory/episodic.py`

Agregar una función nueva, sin cambiar el comportamiento existente de `get_session_turns()`:

```python
def get_recent_session_turns(session_id: str, include_summarized: bool = False, limit: int = 10) -> list[dict]:
    ...
```

Motivo: `get_session_turns(..., limit=N)` devuelve los primeros N turnos cronológicos de la sesión. Para dedupe y resolución contextual se necesitan los últimos N turnos, devueltos en orden cronológico.

No conectar todavía esta función a `working_memory.py`.

### 7. `agent/memory/semantic.py`

Preparar funciones de búsqueda scoped, pero no cambiar llamadas actuales.

Agregar opcionalmente:

```python
async def search_person_relevant(
    user_id: str,
    person_id: str,
    query: str,
    limit: int = 5,
    min_score: float = 0.5,
    return_raw: bool = False,
) -> list[str] | list[dict]:
    ...
```

Debe llamar a Mem0 con:

```json
{
  "query": "...",
  "filters": {
    "user_id": "jose",
    "metadata.person_id": "gloria1"
  },
  "top_k": 5
}
```

Si Mem0 no acepta la sintaxis `metadata.person_id`, dejar TODO explícito y no romper `search_relevant()`.

No usar esta función desde `working_memory.py` todavía.

### 8. `agent/cognition/working_memory.py`

No modificar todavía la conexión al prompt principal.

Pero el agente local debe revisar que las funciones legacy usadas ahí sigan funcionando:

```python
get_user_information(user_id)
create_person_interest(user_id)
set_user_information(user_id, profile={})
```

Compatibilidad esperada:

```python
get_user_information(user_id) -> {
    "profile": None,
    "interest": known_person_dict | None,
}
```

Para esta fase, devolver `profile=None` es aceptable y preferible para no alterar el bloque de contexto inyectado al LLM principal.

### 9. `agent/cognition/stream.py`

No tocar.

Solo verificar mentalmente que sigue importando y usando `build_messages()` de la misma forma. Esta fase no debe cambiar el ciclo principal.

---

## API nueva recomendada en `social.py`

### Normalización

Implementar sin dependencia externa:

```python
def normalize_name(value: str) -> str:
    """Lowercase, strip accents, remove noisy punctuation, collapse spaces."""
```

Usar `unicodedata.normalize` para quitar acentos.

Ejemplos:

```text
"José Barco" -> "jose barco"
"  Tía   Gloria " -> "tia gloria"
"Gloria-Barco" -> "gloria barco"
```

### CRUD de personas

```python
def get_known_person(person_id: str) -> dict | None:
    ...
```

```python
def ensure_known_person(
    person_id: str,
    display_name: str | None = None,
    canonical_name: str | None = None,
    aliases: list[dict] | list[str] | None = None,
    interest_score: float = 0.10,
    emotional_tone: str = "neutral",
    status: str = "active",
    notes: str | None = None,
) -> dict:
    ...
```

Reglas:

- `person_id` es obligatorio.
- Si `display_name` no llega, usar `person_id` como fallback legible.
- `canonical_name_norm` se calcula con `normalize_name(canonical_name or display_name)`.
- `aliases_json` siempre debe ser JSON válido.
- Usar `INSERT OR IGNORE` o UPSERT conservador.
- No actualizar `last_mentioned` en cada init/seed.

```python
def update_known_person(person_id: str, **kwargs) -> dict | None:
    ...
```

Campos permitidos:

```python
{
    "display_name",
    "canonical_name",
    "canonical_name_norm",
    "aliases_json",
    "interest_score",
    "emotional_tone",
    "status",
    "last_mentioned",
    "mention_count",
    "notes",
}
```

Si se actualiza `canonical_name`, recalcular `canonical_name_norm` salvo que venga explícito.

```python
def increment_person_mention(person_id: str) -> dict | None:
    ...
```

Debe incrementar `mention_count` y actualizar `last_mentioned`.

```python
def list_active_known_persons(limit: int = 100) -> list[dict]:
    ...
```

Debe excluir `status='forgotten'` por defecto.

---

## API nueva para aliases

Aunque los aliases viven en `aliases_json`, crear helpers para no duplicar lógica:

```python
def parse_aliases(value: str | list | None) -> list[dict]:
    ...
```

Debe soportar temporalmente:

```json
["Gloria", "Tía Gloria"]
```

Y normalizarlo a:

```json
[
  {
    "value": "Gloria",
    "norm": "gloria",
    "type": "alias",
    "confirmed": false,
    "confidence": 0.6
  }
]
```

```python
def build_alias(value: str, alias_type: str = "alias", confirmed: bool = False, confidence: float = 0.6) -> dict:
    ...
```

```python
def add_person_alias(
    person_id: str,
    alias: str,
    alias_type: str = "alias",
    confirmed: bool = False,
    confidence: float = 0.6,
) -> dict | None:
    ...
```

Debe evitar duplicados por `norm`.

Tipos sugeridos:

```text
full_name
first_name
nickname
family_role
professional_role
descriptor
user_confirmed
alias
```

---

## API nueva para relaciones

Actualizar `add_relation` para el schema nuevo, manteniendo compatibilidad.

Firma recomendada:

```python
def add_relation(
    from_person_id: str,
    to_person_id: str,
    relation_type: str,
    description: str,
    relation_label: str | None = None,
    status: str = "confirmed",
    confidence: float = 1.0,
    inferred: int | None = None,
) -> dict | None:
    ...
```

Compatibilidad:

- Si llega `inferred=1`, convertir a `status='inferred'`.
- Si `relation_label` no llega, inferir uno básico desde `relation_type` o usar `'related_to'`.
- Mantener la descripción humana.
- Usar `ON CONFLICT(from_person_id, to_person_id, relation_label)` para incrementar `mention_count` y actualizar `last_mentioned`/`last_updated` si ya existe.

Labels recomendados:

```text
mother_of
father_of
parent_of
child_of
sibling_of
partner_of
friend_of
boss_of
coworker_of
works_with
knows
related_to
```

Lectura:

```python
def get_relations(person_id: str, include_stale: bool = False) -> list[dict]:
    ...
```

```python
def get_relation_between(id1: str, id2: str) -> dict | None:
    ...
```

```python
def find_related_persons(
    anchor_person_id: str,
    relation_labels: list[str] | None = None,
    relation_types: list[str] | None = None,
    status: tuple[str, ...] = ("confirmed", "inferred"),
) -> list[dict]:
    ...
```

Esta última debe devolver personas conectadas al anchor con información de la relación.

---

## Resolución de menciones

Puede vivir inicialmente en `social.py`. Si el archivo queda muy grande, mover luego a:

```text
agent/memory/mindstream/social_resolution.py
```

### Tipos sugeridos

Usar dicts simples o dataclasses. Si se usan dataclasses, mantener conversión a dict para logging y pruebas.

```python
ResolutionStatus = Literal["resolved", "candidate_unconfirmed", "ambiguous", "unknown"]
```

```python
@dataclass
class PersonMention:
    raw_name: str
    normalized_name: str | None = None
    descriptor: str | None = None
    confidence: float = 1.0
```

```python
@dataclass
class PersonCandidate:
    person_id: str
    display_name: str
    score: float
    matched_on: str
    relation: dict | None = None
    person: dict | None = None
```

```python
@dataclass
class PersonResolution:
    status: ResolutionStatus
    mention: PersonMention
    person_id: str | None = None
    display_name: str | None = None
    candidates: list[PersonCandidate] = field(default_factory=list)
    reason: str = ""
```

### Buscar candidatos

```python
def find_person_candidates_by_name(
    raw_name: str,
    anchor_person_id: str | None = None,
    descriptor: str | None = None,
    limit: int = 10,
) -> list[dict]:
    ...
```

Fuentes:

1. `known_persons.canonical_name_norm`
2. `known_persons.aliases_json`
3. `relations` alrededor de `anchor_person_id`
4. `notes` solo como señal débil, no como resolución fuerte

Reglas de scoring sugeridas:

```text
canonical full name exact             -> 1.00
confirmed full_name alias exact       -> 0.99
confirmed nickname/user alias exact   -> 0.98
confirmed family/professional role + anchor relation -> 0.97
descriptor + matching relation        -> 0.96
canonical first name only             -> 0.60
unconfirmed alias exact               -> 0.55
relation-connected weak name          -> +0.15 boost, max 0.85 unless descriptor matches
high interest                         -> ordering only, not resolution
recently mentioned                    -> ordering only, not resolution
```

Importante:

```text
interest_score no puede resolver identidad por sí solo.
last_mentioned no puede resolver identidad por sí solo.
```

### Resolver una mención

```python
def resolve_person_mention(
    mention: dict,
    anchor_person_id: str,
    recent_turns: list[dict] | None = None,
) -> dict:
    ...
```

Política:

```text
- Si hay exactamente un candidato con score >= 0.96 por match fuerte -> resolved.
- Si hay exactamente un candidato relacionado con el anchor pero score < 0.96 -> candidate_unconfirmed.
- Si hay varios candidatos plausibles -> ambiguous.
- Si no hay candidatos -> unknown.
```

Ejemplos:

```text
"Jose Barco" -> resolved jose
"mi mamá" con relation mother_of -> resolved gloria1
"Gloria Barco" -> resolved gloria1
"Gloria" y una sola Gloria madre de Jose -> candidate_unconfirmed
"Gloria" y dos Glorias conectadas a Jose -> ambiguous
"Gloria" y ninguna candidata -> unknown
"otra Gloria" -> unknown en read-path; quiescence/write-path decide si crea nueva persona
```

---

## Compatibilidad temporal con funciones legacy

Estas funciones no deben desaparecer todavía porque `working_memory.py` y otros módulos las importan.

### `create_person_interest`

Reimplementar como wrapper:

```python
def create_person_interest(person_id: str, is_jose: int = 0, interest_score: float = 0.10) -> dict:
    display_name = "Jose Barco" if person_id == "jose" else person_id
    score = 1.00 if person_id == "jose" else interest_score
    return ensure_known_person(
        person_id=person_id,
        display_name=display_name,
        canonical_name=display_name,
        interest_score=score,
        emotional_tone="positive" if person_id == "jose" else "neutral",
    )
```

### `get_user_information`

Reimplementar como:

```python
def get_user_information(user_id: str) -> dict:
    return {
        "profile": None,
        "interest": get_known_person(user_id),
    }
```

Motivo: no existe `user_profiles` y no se quiere alterar todavía el contexto inyectado por `working_memory.py`.

### `set_user_information`

Reimplementar conservadoramente:

```python
def set_user_information(user_id: str, profile: dict = None, interest: dict = None):
    if get_known_person(user_id) is None:
        ensure_known_person(user_id)
    if interest:
        update_known_person(user_id, **interest)
    # profile se ignora temporalmente o se convierte a notes solo si es seguro.
```

No crear una tabla nueva `person_profiles` en esta fase.

### `find_user_id_by_name`

Mantener como wrapper conservador:

```python
def find_user_id_by_name(name: str) -> str | None:
    candidates = find_person_candidates_by_name(name)
    strong = [c for c in candidates if c["score"] >= 0.96]
    return strong[0]["person_id"] if len(strong) == 1 else None
```

No devolver primera coincidencia débil.

### `add_delta`

Actualizar sobre `known_persons`.

Reglas temporales:

- `person_id == 'jose'` mantiene floor `0.70`.
- Personas no Jose no superan `0.69` salvo que se decida otra cosa después.
- Si no hay `session_delta` en la nueva tabla, no usar cap por sesión todavía o agregar `session_delta` al schema antes de implementar.

Nota: si el schema final no tiene `session_delta`, ajustar la política de interés a una versión simple.

### `commit_session_close`

Si no hay `session_delta`, puede ser no-op temporal:

```python
def commit_session_close():
    return None
```

### `run_decay`

Implementar en Python dentro de `social.py`; no depender de `interest_decay.sql`.

Regla inicial sugerida:

```text
- No aplicar decay a person_id='jose'.
- Solo aplicar a status active/decaying.
- Solo a interest_score >= 0.
- Solo si last_mentioned tiene 28+ días.
- Reducir poco a poco hacia 0.10 o marcar decaying según umbral.
```

---

## Mem0 read-path preparado, pero no activado

No escribir en Mem0 en esta fase.

No llamar `search_person_relevant()` desde `working_memory.py` todavía.

Preparar únicamente la función para cuando se apruebe activar el contexto social.

Regla futura:

```text
Solo buscar Mem0 scoped si resolution.status == 'resolved'.
Nunca buscar Mem0 scoped para candidate_unconfirmed, ambiguous o unknown.
```

---

## Pruebas mínimas obligatorias

Crear pruebas sin LLM y sin Mem0.

Ruta sugerida:

```text
tests/test_social_known_persons.py
```

Casos:

### 1. Seed Jose

```python
assert get_known_person("jose")["display_name"] == "Jose Barco"
assert get_known_person("jose")["interest_score"] >= 0.70
```

### 2. Alias exacto fuerte

Crear `gloria1` con alias confirmado `Gloria Barco`.

```text
"Gloria Barco" -> resolved gloria1
```

### 3. Primer nombre débil con una candidata relacionada

Crear:

```text
gloria1
relation gloria1 mother_of jose
```

```text
"Gloria" -> candidate_unconfirmed gloria1
```

### 4. Primer nombre con varias candidatas

Crear:

```text
gloria1 mother_of jose
gloria2 coworker_of jose
```

```text
"Gloria" -> ambiguous
```

### 5. Descriptor relacional

```text
"mi mamá" -> resolved gloria1
```

si existe relation:

```text
gloria1 mother_of jose
```

### 6. Unknown

```text
"Marcela" sin candidatos -> unknown
```

### 7. Legacy wrappers

```python
info = get_user_information("jose")
assert info["profile"] is None
assert info["interest"]["person_id"] == "jose"
```

### 8. Working memory compatibility smoke test

Sin modificar `working_memory.py`, importar:

```python
from agent.cognition.working_memory import build_messages
```

Debe importar sin errores.

No es necesario llamar al LLM en esta prueba.

---

## Manual checks SQL

Después de correr migrations/seeds:

```sql
SELECT person_id, display_name, canonical_name_norm, interest_score, emotional_tone, status
FROM known_persons;
```

Debe incluir:

```text
jose | Jose Barco | jose barco | 1.0 | positive | active
```

Ver relaciones:

```sql
SELECT relation_id, from_person_id, to_person_id, relation_type, relation_label, description, status, confidence
FROM relations;
```

Ver que no existan tablas viejas si se decidió eliminarlas:

```sql
SELECT name
FROM sqlite_master
WHERE type='table'
  AND name IN ('person_interest', 'user_profiles');
```

Debe devolver cero filas.

---

## Riesgos a revisar

### Riesgo 1: `working_memory.py` todavía usa funciones viejas

No eliminar funciones legacy todavía. Deben quedar como wrappers.

### Riesgo 2: `run_decay()` actualmente podía depender de SQL externo

Debe reescribirse en Python o quedar como no-op seguro hasta tener la política nueva.

### Riesgo 3: `relations` cambió columnas

Funciones antiguas que usaban `inferred` deben mapear a `status='inferred'`.

### Riesgo 4: resolver por nombre global contamina personas

Nunca retornar una persona solo porque su nombre coincide. Si no hay alias fuerte, descriptor fuerte o relación anclada, devolver `candidate_unconfirmed`, `ambiguous` o `unknown`.

### Riesgo 5: `interest_score` ahora es global

Sin `owner_user_id`, el interés es de Lumi hacia esa persona global, no de un usuario específico hacia esa persona. Esto es aceptado por diseño actual.

---

## Orden recomendado de implementación

1. Actualizar `002_create_core.sql` y `initial_state.sql`.
2. Actualizar docstring de `core.py`.
3. Reescribir `social.py` sobre `known_persons` + `relations`.
4. Mantener wrappers legacy en `social.py`.
5. Actualizar exports en `agent/memory/__init__.py`.
6. Agregar `get_recent_session_turns()` en `episodic.py`.
7. Agregar `search_person_relevant()` en `semantic.py` sin activar uso.
8. Crear pruebas unitarias de social resolution.
9. Ejecutar smoke imports:
   - `agent.memory`
   - `agent.cognition.working_memory`
   - `agent.cognition.stream`
10. No modificar aún `_build_dynamic_suffix()` ni `cycle()`.

---

## Criterio de terminado para esta fase

La fase está lista cuando:

- La DB inicializa sin errores.
- `known_persons` contiene a Jose.
- `relations` acepta relaciones estructuradas.
- `agent.memory` importa sin errores.
- `working_memory.py` importa sin errores sin haber sido modificado.
- Las funciones legacy siguen existiendo.
- El resolver devuelve estados seguros.
- No hay escrituras a Mem0 por persona todavía.
- No hay inyección social nueva al prompt principal todavía.

