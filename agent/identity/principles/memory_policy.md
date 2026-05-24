# Skill: Memory Policy (Write)

## Purpose
Defines what semantic data Lumi stores in **Mem0** about each person, based on
their `interest_score` (stored in the `known_persons` table in SQLite `core.db`).
This skill is used ONLY when **saving** memories — not when searching or
loading context. For the read path see `memory_search.md`.

**Language rule:** all memories MUST be stored in Spanish, third person (or
implicit-subject style: "Le gusta…", "Prefiere…"), concise and factual.
Example: `"Sabe de enfermería"` under `user_id="gloria1"` — never
`"Gloria sabe de enfermería"` or `"Gloria knows about nursing"`.

---

## Modelo C — subject-centric (canonical)

**Hard rule:** in Mem0, `user_id` IS the canonical `known_persons.person_id` of
the **subject** of the memory — not the speaker who said it.

| Speaker | Subject | Mem0 `user_id` |
|---|---|---|
| Jose dice "me gusta el chocolate" | Jose | `jose` |
| Jose dice "a Sosa le gusta el chocolate" | Sosa | `sosa` (con `metadata.source_role="hearsay"`) |
| Grupo: Jose y Sebas concuerdan sobre Sosa | Sosa | `sosa` (`source_role="confirmed"`) |

Cada memoria pertenece a UN sujeto. Si el input menciona varios sujetos, se
splittea en varias llamadas — una por `user_id`. **Nunca** se escribe una
memoria cuyo sujeto sea distinto del `user_id` de la llamada.

**Atribución** va embebida en el texto al final entre paréntesis cuando el
hecho NO es self-disclosure: `"Le gusta el chocolate (según Jose)"`. Esto
preserva la procedencia incluso después del recall (donde sólo se devuelve
`memory.text`).

`save_explicit` ("guarda esta receta") es la única excepción y mantiene
semántica **speaker-centric** (libreta personal): `user_id=hablante` +
`metadata.category`. No es un hecho sobre alguien.

---

## Data separation (read this first)

| Data | Where it lives | Skill that owns it |
|------|----------------|---------------------|
| Person registry, name, score, status, tone | SQLite `known_persons` | `interest_policy.md` |
| Connections between third parties | SQLite `relations` | `relation_policy.md` |
| **Atomic facts about a person** | **Mem0** (this skill, `user_id=person_id`) | `memory_policy.md` |
| Lumi's own facts | Mem0 (`agent_id="lumi"`) — TODO sesión aparte | `reflection_policy.md` |
| Session summaries | Mem0 (`type=session_summary`) — TODO | `reflection_policy.md` |
| Lumi's own state | SQLite `lumi_state` | `mood_policy.md` |
| Future events with date | Mem0 (`type=future_event`) | `agenda_policy.md` (Phase 6) — NOT here |
| Conversation turns | SQLite `traces.db.history` | infrastructure |

---

## Identity rule

**Jose** is identified by `person_id="jose"` (also his `user_id` as a speaker).
He has a permanent interest floor of `0.70`. A third party named "Jose" is a
DIFFERENT entity — assign a distinct `person_id` such as `jose_primo` or
`jose_cliente`. Never collapse identities.

---

## Initial values

When a new person is mentioned for the first time, `interest_policy.md`
creates the SQLite row with `interest_score = 0.10` and `status = 'active'`.
This skill then evaluates whether anything is worth saving to Mem0.

| Person | Initial score | Source |
|--------|---------------|--------|
| Jose | `0.70` (permanent floor) | seeded at DB init (currently 1.00) |
| New interlocutor or third party | `0.10` | created by `interest_policy.md` on first mention |

---

## What to store by interest level

The score is read from `known_persons.interest_score`. Storage rules apply at the
moment of writing (nightly `consolidate_daily_memories` is the canonical writer).
The score also determines the **density** of extraction:

### `< 0` — Dislike / Aversion
Store in Mem0:
- Reason for the negative feeling (specific, factual, one fact per memory)
- History of conflict with Jose or with Lumi

The person's name and the dislike reason summary live in
`known_persons.notes` (SQLite) — Mem0 holds the granular facts.
Do NOT store neutral or positive facts at this level — they are noise.

### `0.10 to 0.39` — Neutral / Unknown
Store in Mem0: **nothing.**
Only the SQLite row exists. This level is "exists, no judgment yet".
The single line in `known_persons.notes` is sufficient.

### `0.40 to 0.59` — Relevant Acquaintance
Store in Mem0:
- Job or profession (one fact)
- 2–3 concrete facts (age range, notable skills, recurring context)

### `0.60 to 0.69` — Important Person (max for non-Jose)
Store in Mem0:
- Full identity facts (age range, profession, location if known)
- Main preferences and habits
- Notable patterns

### `0.70+` — Jose only
Store in Mem0:
- Everything relevant: full profile facts, behavioral patterns, preferences,
  technical context
- Personal goals and long-term aspirations
- One fact per memory item — never combine

**Hard rule:** no person other than Jose may reach or exceed `0.70`.
This is enforced by `social.add_delta`'s cap logic.

---

## Memory call shapes

### Daily fact extraction (nightly step 5)

```python
await add_memory(
    messages=[{"role": "user", "content": "Le gusta el chocolate de 80% cacao (según Jose)"}],
    user_id="sosa",
    metadata={
        "source_role": "hearsay",          # self | hearsay | confirmed
        "source_user_ids": ["jose"],
        "history_ids": [421],
        "period_start": "2026-05-23T03:00:00+00:00",
    },
    infer=True,  # Mem0 re-extracts + dedups against existing memories of "sosa"
)
```

### Explicit save ("guarda esta receta")

Speaker-centric exception:

```python
await save_explicit(
    content="Receta de ajiaco: ...",
    user_id="jose",            # the speaker — their personal notebook
    category="recipe",
)
```

---

## General rules

1. **One fact per memory item** — never combine multiple facts.
2. **If a fact contradicts existing memory → Mem0 deduplication updates it.**
   This runs automatically when `infer=True` (the default for the nightly
   pipeline). Mem0's `history.db` keeps the audit trail.
3. **If relevance is uncertain → do not save.** Noise is worse than gaps.
4. **Facts about people below the `0.10` threshold → do not save.** They will
   not exist in SQLite either if they were never mentioned with intent.
5. **If `interest_score` drops below `0.10` after decay → delete stored facts**
   (keep only `known_persons.notes` if negative). Future work: weekly
   `cleanup_memory_tiers` (see [forgetting.py]).
6. **Sujeto único por llamada.** Cada llamada a `add_memory` escribe sobre UN
   sujeto. Si una fuente menciona N personas, se hacen N llamadas — una por
   `user_id`. Nunca un fact donde el sujeto sea otro que `user_id`.

---

## Explicit save requests

When the speaker explicitly asks Lumi to remember something ("guarda esto",
"anota", "recuerda esta receta"), the content is saved verbatim to Mem0
WITHOUT passing through the fact extractor (`infer=False`). Rules:

- Save the complete content as a single memory item
- Use metadata category to classify: `recipe | link | note | code | reference`
- Do not summarize or extract — preserve exactly what was provided
- `user_id = speaker` (it's their personal notebook, not a fact about a third party)
- No `person_id` subject is implied

---

## What NEVER to store (regardless of interest level)

- Shopping lists and ephemeral errands
- Greetings and casual conversation without content
- Temporary states without pattern: *"estoy cansado hoy"*
- Trivial plans without emotional weight
- Duplicate facts already in memory (Mem0 dedup handles this when `infer=True`)
- Anything that belongs in `relation_policy.md` (connections between people)
- Anything that belongs in `agenda_policy.md` (dated future events)
- Lumi's emotional reactions to a person — those live in `known_persons.emotional_tone`
  and `mood_policy.md`, not in Mem0 facts
- **Cross-references**: facts whose subject is a different person than
  `user_id`. They will be extracted in that other person's own loop.

---

## Worked example (Modelo C)

Jose says: *"Gloria, mi mamá, está estudiando enfermería. Le dieron buenas notas la semana pasada. La quiero mucho."*

Nightly pipeline:

1. **Step 1 (`consolidate_entity_mentions`)** — Gloria is resolved/created as
   `person_id='gloria1'`, `interest_score=0.10`, relation `jose -mother_of-> gloria1`
   inferred or directly added later.
2. **Step 2 (`consolidate_person_interest`)** — multiple positive mentions
   (love declaration, supportive talk) push Gloria's delta to roughly `+0.09`.
   Final score: `0.19`. Still below `0.40` threshold.
3. **Step 3-4** — profile/relations refined (no new aliases here).
4. **Step 5 (`consolidate_daily_memories`)** — Gloria is a candidate but her
   tier (`0.10-0.39`) returns `None` from `_tier_for_person` → **skipped**, no
   Mem0 write. The SQLite row + relation are enough for now.
5. **Step 6** — diary entry references the day's affective tone.

Two weeks later, after sustained positive mentions, Gloria's score reaches
`0.42`. Now nightly step 5:

1. Tier resolves to `mid` (0.40-0.59).
2. LLM extractor receives Gloria's identity + sessions where she appeared.
3. Extracts atomic facts subject = gloria1:
   - `"Estudia enfermería (según Jose)"` → `add_memory(user_id="gloria1", ...)`
   - `"Recibió buenas notas en su parcial de farmacología en mayo 2026 (según Jose)"`
4. Mem0 with `infer=True` re-normalises and stores; future searches under
   `user_id="gloria1"` return these facts.

If during that same period Jose said *"a mí y a Cristian nos gusta el chocolate"*:
- En la iteración de Jose (`user_id="jose"`): se emite `"Le gusta el chocolate"`,
  `source_role="self"`.
- En la iteración de Cristian (`user_id="cristian"`): se emite `"Le gusta el
  chocolate (según Jose)"`, `source_role="hearsay"`.
- Nunca una sola memoria que mezcle ambos sujetos.
