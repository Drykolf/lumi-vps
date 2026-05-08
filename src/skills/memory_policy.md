# Skill: Memory Policy (Write)

## Purpose
Defines what semantic data Lumi stores in **Mem0** about each person, based on
their `interest_score` (stored in the `persons` table in SQLite `core_state.db`).
This skill is used ONLY when **saving** memories — not when searching or
loading context. For the read path see `memory_search.md`.

**Language rule:** all memories MUST be stored in Spanish, third person,
concise and factual.
Example: `"Gloria sabe de enfermería"` — never `"Gloria knows about nursing"`.

---

## Data separation (read this first)

| Data | Where it lives | Skill that owns it |
|------|----------------|---------------------|
| Person registry, name, score, status, tone | SQLite `persons` table | `interest_policy.md` |
| Connections between third parties | SQLite `relations` table | `relation_policy.md` |
| **Atomic facts about a person** | **Mem0** (this skill) | `memory_policy.md` |
| Jose's structured profile | Mem0 (`type=user_profile`) | `reflection_policy.md` |
| Session summaries | Mem0 (`type=session_summary`) | `reflection_policy.md` |
| Lumi's own state | SQLite `lumi_state` | `mood_policy.md` |
| Future events with date | Mem0 (`type=future_event`) | `agenda_policy.md` (Phase 6) — NOT here |
| Conversation turns | SQLite `history.db` | infrastructure, not a skill |

**Hard rule:** every memory written to Mem0 MUST include `metadata.person_id`
matching a row in SQLite `persons`. If the person does not exist yet, create
the row first via `interest_policy.md` initialization.

---

## Identity rule

**Jose** is identified by `user_id="jose"` and is the only row with `is_jose=1`.
He is the primary person Lumi speaks with. A third party named "Jose" is a
DIFFERENT entity — assign a distinct `person_id` such as `jose_primo` or
`jose_cliente`. Never collapse identities.

---

## Initial values

When a new person is mentioned for the first time, `interest_policy.md`
creates the SQLite row with `interest_score = 0.10` and `status = 'active'`.
This skill then evaluates whether anything is worth saving to Mem0.

| Person | Initial score | Source |
|--------|---------------|--------|
| Jose | `0.70` (permanent floor) | seeded at DB init |
| New interlocutor or third party | `0.10` | created by `interest_policy.md` on first mention |

---

## What to store by interest level

The score is read from `persons.interest_score`. Storage rules apply at the
moment of writing. If the score crosses a threshold, `reflection_policy.md`
triggers an upgrade or downgrade pass.

### `< 0` — Dislike / Aversion
Store in Mem0:
- Reason for the negative feeling (specific, factual, one fact per memory)
- History of conflict with Jose or with Lumi

The person's name and the dislike reason summary live in
`persons.notes` (SQLite) — Mem0 holds the granular facts.
Do NOT store neutral or positive facts at this level — they are noise.

### `0.10 to 0.39` — Neutral / Unknown
Store in Mem0: **nothing.**
Only the SQLite row exists. This level is "exists, no judgment yet".
The single line in `persons.notes` (e.g. *"mencionada por Jose el 22 de abril"*)
is sufficient.

### `0.40 to 0.59` — Relevant Acquaintance
Store in Mem0:
- Job or profession (one fact)
- 2–3 concrete facts (age range, notable skills, recurring context)

### `0.60 to 0.69` — Important Person (max for non-Jose)
Store in Mem0:
- Full identity facts (age range, profession, location if known)
- Main preferences and habits
- Notable patterns

### `0.70` — Jose only
Store in Mem0:
- Everything relevant: full profile facts, behavioral patterns, preferences,
  technical context
- Personal goals and long-term aspirations
- One fact per memory item — never combine

**Hard rule:** no person other than Jose may reach or exceed `0.70`.
This is enforced by a SQLite CHECK constraint.

---

## Memory types written by this skill

| Mem0 type | Indexed by | Description | When |
|-----------|-----------|-------------|------|
| `fact` | `user_id="jose"` + `metadata.person_id` | Single atomic fact about a person | Each relevant turn |
| `lumi_fact` | `agent_id="lumi"` | Fact about Lumi herself (her preferences, history, appearance choices) | When Jose tells Lumi something about herself |

`user_profile`, `session_summary`, `lumi_state` updates → `reflection_policy.md`.
`future_event` → `agenda_policy.md` (Phase 6).

---

## General rules

1. **One fact per memory item** — never combine multiple facts into one entry.
2. **If a fact contradicts existing memory → UPDATE immediately.** The Mem0
   v2.0.0 deduplication via `history.db` handles this; do not write a parallel
   conflicting fact.
3. **If relevance is uncertain → do not save.** Noise is worse than gaps.
4. **Facts about people below the `0.10` threshold → do not save.** They will
   not exist in SQLite either if they were never mentioned with intent.
5. **If `interest_score` drops below `0.10` after decay → delete stored facts**
   (keep only `persons.notes` if negative). This is run by
   `reflection_policy.md` at session close.
6. **Always include `metadata.person_id`** matching a SQLite row. A memory
   without this metadata is orphaned and unreachable by `memory_search.md`.

---

## Explicit save requests

When Jose explicitly asks Lumi to remember something ("guarda esto", 
"anota", "recuerda esta receta"), the content is saved verbatim to Mem0 
WITHOUT passing through the fact extractor. Rules:

- Save the complete content as a single memory item
- Use metadata category to classify: recipe | link | note | code | reference
- Do not summarize or extract — preserve exactly what Jose provided
- user_id="jose" always
- No person_id required for this type

---

## What NEVER to store (regardless of interest level)

- Shopping lists and ephemeral errands
- Greetings and casual conversation without content
- Temporary states without pattern: *"estoy cansado hoy"*
- Trivial plans without emotional weight
- Duplicate facts already in memory
- Anything that belongs in `relation_policy.md` (connections between people)
- Anything that belongs in `agenda_policy.md` (dated future events)
- Lumi's emotional reactions to a person — those live in `persons.emotional_tone`
  and `mood_policy.md`, not in Mem0 facts

---

## Worked example

Jose says: *"Gloria, mi mamá, está estudiando enfermería. Le dieron buenas notas la semana pasada. La quiero mucho."*

Result of WRITE pipeline:

1. `interest_policy.md` — Gloria does not exist yet → create
   `persons` row: `person_id='gloria1', canonical_name='Gloria', score=0.10`.
   Then apply deltas: explicit positive mention (+0.01) + high positive
   emotional weight (+0.03) + Jose declares closeness via "la quiero mucho"
   (+0.05). Final: `0.19`. Still below `0.40` → no Mem0 facts written by
   this skill yet.
2. `relation_policy.md` — explicit connection → create relation
   `from='jose', to='gloria1', type='family', description='Gloria es la madre de Jose'`.
3. `memory_policy.md` (this skill) — score is `0.19`, below `0.40`. Write
   nothing to Mem0. Update `persons.notes` to *"mencionada por Jose como su madre, estudia enfermería"*.

Two weeks later, after several positive mentions, Gloria's score is `0.42`.
Now `reflection_policy.md` triggers an upgrade pass:

1. Re-read all conversation turns where Gloria was mentioned.
2. Extract atomic facts: *"Gloria estudia enfermería"*, *"Gloria recibió buenas notas en mayo de 2026"*.
3. Write each as a Mem0 `fact` with `metadata.person_id='gloria1'`.
