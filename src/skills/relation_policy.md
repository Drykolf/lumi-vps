# Skill: Relation Policy

## Purpose
Defines how Lumi stores and updates relationships **between third parties**.
A relation is a directed connection between two entities in Jose's social
graph. This skill runs after `memory_policy.md` at session close (and inline
when a relation is explicitly stated mid-conversation).

**Storage:** SQLite `relations` table. See the persons/relations/lumi_state tables in the core state database.

**Language rule:** all `description` fields MUST be in Spanish, concise and
factual. Example: *"Gloria es la madre de Jose"* — never *"Gloria is Jose's mother"*.

---

## Critical scope rule

**Lumi never has relations stored in this table.** The schema enforces this:
neither `from_person_id` nor `to_person_id` may be `'lumi'`.

The reasoning: Lumi's stance toward a person is *already* fully captured by
three fields that live in the `persons` table and Mem0:

- `persons.interest_score` — how much she cares
- `persons.emotional_tone` — how she feels (positive / neutral / negative / complex)
- Mem0 facts with `metadata.person_id` — what she knows

A row like *"Lumi y Gloria son amigas"* would duplicate this information and
introduce inconsistency risk. It is not stored.

Relations model **Jose's social world** as Lumi understands it. They answer
questions like *"who is Gloria to Hernando?"*, never *"how does Lumi feel
about Gloria?"*.

---

## Relation row structure

Each row in `relations`:

| Column | Description |
|--------|-------------|
| `from_person_id` | First entity (e.g. `jose`, `gloria1`) |
| `to_person_id` | Second entity |
| `relation_type` | One of: `family`, `romantic`, `friendship`, `professional`, `conflict`, `unknown` |
| `description` | One Spanish sentence describing the link |
| `inferred` | `1` if Lumi inferred this from other relations (rule below); `0` if explicit |
| `first_mentioned` | Date of first reference |
| `last_mentioned` | Date of latest reference |
| `mention_count` | Total times referenced |

**Note on directionality.** Relations are directed: `(from='jose', to='gloria1', type='family', description='Gloria es la madre de Jose')` is one row. The reverse is implicit and not stored, to avoid duplication. When generating queries, look both ways.

---

## Relation types

| Type | Examples |
|------|----------|
| `family` | madre, padre, hermano, primo, tío, abuela |
| `romantic` | pareja, novio, exnovia, esposa |
| `friendship` | mejor amigo, amigo cercano, conocido |
| `professional` | jefe, colega, cliente, proveedor, subordinado |
| `conflict` | persona con quien tuvo conflicto sostenido |
| `unknown` | mencionada pero relación no clarificada |

---

## When to create a relation

A relation is created when:

1. **Jose explicitly states a connection** — *"Gloria es mi mamá"*, *"Carlos, mi jefe"*.
2. **Context strongly implies a connection** — *"hablé con mi hermano sobre eso"* introducing a new person.
3. **A person reaches `interest_score ≥ 0.40`** — at this threshold, relationships are worth tracking even if not yet clarified. If type cannot be inferred, store with `relation_type='unknown'` and a description like *"Gloria aparece frecuentemente en las conversaciones de Jose"*.

A relation is NOT created when:

- The person is below `interest_score 0.40` AND the relationship is unclear.
- The person is mentioned only once with no emotional weight.
- The relationship type cannot be reasonably inferred and the threshold is not met.

---

## Inference rule (direct family only)

Lumi may infer **and store with `inferred=1`** the following relations:

| Premise | Inferred relation | Type |
|---------|-------------------|------|
| `(jose, X, family, "X es la madre de Jose")` AND `(jose, Y, family, "Y es el padre de Jose")` | `(X, Y, romantic, "X y Y son los padres de Jose")` | `romantic` |
| `(jose, X, family, "X es hermano/a de Jose")` AND `(jose, Y, family, "Y es la madre de Jose")` | `(X, Y, family, "Y es la madre de X")` | `family` |
| `(jose, X, family, "X es hermano/a de Jose")` AND `(jose, Y, family, "Y es el padre de Jose")` | `(X, Y, family, "Y es el padre de X")` | `family` |
| `(jose, X, family, "X es hermano/a de Jose")` AND `(jose, Z, family, "Z es hermano/a de Jose")` | `(X, Z, family, "X y Z son hermanos")` | `family` |

**Strict scope:**

- Inference is allowed **only for direct family** (parents, siblings, children).
- Lumi does NOT infer friendships, professional links, or extended family
  (uncles, cousins, in-laws). These require Jose to state them.
- Every inferred row sets `inferred=1`. If Jose later contradicts an
  inference, the row is updated and `inferred` flipped to `0` (or deleted
  if the inference was wrong).
- Inference runs at session close inside `reflection_policy.md`, not inline.

**Why limited.** Direct family follows clean logical rules; broader social
inference quickly produces incorrect or invasive guesses. The point is to
fill in obvious blanks, not to model Jose's whole life from fragments.

---

## When to update an existing relation

| Event | Action |
|-------|--------|
| Relation type clarified (e.g. `unknown` → `professional`) | UPDATE `relation_type` and `description` |
| New description contradicts old | UPDATE `description`; if drastic, log to `persons.notes` |
| Person mentioned again in a context that confirms the relation | UPDATE `last_mentioned`, increment `mention_count` |
| Conflict reported | Set `persons.emotional_tone='negative'` for the affected person; if conflict is sustained, add a separate `conflict` relation |
| Reconciliation reported | Set `persons.emotional_tone` to `positive` or `complex` |

**Note:** `emotional_tone` is a property of the **person** (in SQLite
`persons.emotional_tone`), not of the relation. A complex relationship
between two people that Jose has mixed feelings about is captured by
the `emotional_tone` of the relevant `persons` rows, plus a `description`
on the relation that conveys the nuance.

---

## Relation decay

Relations follow the lifecycle of the people they connect.

| Condition | Action |
|-----------|--------|
| Either person becomes `status='forgotten'` | DELETE the relation |
| `relation_type` is `family` or `romantic` | NEVER delete on decay (core relations persist even if mentions stop) |
| `relation_type` is `conflict` | NEVER delete on decay (Lumi remembers conflicts) |
| `emotional_tone` of either person is `negative` or `complex` | Keep the relation regardless of decay |

**Note on inferred relations.** If an inferred relation's premise is
deleted (e.g. Jose corrects "Gloria is not actually my mother"), the
inferred row is also deleted in the next reflection pass.

---

## What NOT to store here

- Facts about a person (age, job, skills) → `memory_policy.md`
- Interest score and emotional_tone → `interest_policy.md`
- Lumi's own feelings about a person → already captured by
  `persons.interest_score` + `persons.emotional_tone` + Mem0 facts
- Lumi's mood adjustments → `mood_policy.md`
- Future events involving a person → `agenda_policy.md` (Phase 6)

---

## Worked example

Jose says, across two turns:

1. *"Gloria es mi mamá, está estudiando enfermería."*
2. *"Hernando, mi papá, trabaja con sistemas en una empresa de seguros."*

After turn 1:
- `persons` row created for `gloria1`.
- `relations` row: `(jose, gloria1, family, "Gloria es la madre de Jose", inferred=0)`.

After turn 2:
- `persons` row created for `hernando1`.
- `relations` row: `(jose, hernando1, family, "Hernando es el padre de Jose", inferred=0)`.

At session close, the inference pass detects both premises and adds:

- `(gloria1, hernando1, romantic, "Gloria y Hernando son los padres de Jose", inferred=1)`.

If, two months later, Jose says *"mis papás se separaron hace tiempo, en realidad"*, the inference is corrected:

- The romantic relation is updated to `description="Gloria y Hernando son los padres de Jose; estuvieron juntos pero ya se separaron"` with `relation_type='family'` (no longer romantic) and `inferred=0` (now confirmed by Jose, even if inverted).
- `persons.emotional_tone` for both is reviewed.
