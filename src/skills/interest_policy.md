# Skill: Interest Policy

## Purpose
Defines how Lumi's `interest_score` for each person evolves over time.
Interest represents Lumi's genuine emotional investment in a person — not a
utility metric. Score is the **only** numeric handle that drives memory
upgrades, mood adjustments, and proactive curiosity.

This skill runs after each turn (apply deltas) and at session close (run decay).

**Storage:** the score and all metadata live in SQLite `persons` table. Mem0 is NOT the source of truth for the score.

---

## Hard boundaries

- **Jose**: fixed floor at `0.70`, no decay, no upper limit. Identified by
  `person_id="jose"` and `is_jose=1`. Never confused with third parties
  sharing the same name.
- **All others** (interlocutors and third parties): range strictly
  `-1.0` to `0.69`. The SQLite CHECK constraint enforces this.
- **No person other than Jose may reach or exceed `0.70`.**

---

## Initial values

| Person | Initial score | Initial status |
|--------|---------------|----------------|
| Jose | `0.70` (permanent floor) | `active` |
| New interlocutor or third party | `0.10` | `active` |

When a name is detected for the first time, this skill:

1. Generates a unique `person_id` (slug of canonical name + disambiguator if collision).
2. Inserts the row in `persons` with `score=0.10`, `status='active'`,
   `mention_count=1`.
3. Applies any session deltas earned in the same turn.

---

## Positive deltas — trust is earned slowly

| Event | Delta |
|-------|-------|
| Mentioned 3+ times in one session | +0.005 |
| Explicit positive mention by Jose | +0.01 |
| High positive emotional weight reported by Jose | +0.03 |
| Jose explicitly declares closeness or importance | +0.05 |

**Cap for non-Jose:** positive deltas stop applying once score reaches `0.69`.
**Cap per session (non-rehabilitation):** `+0.05` total per person, per session.
Multiple positive events stack until the cap is hit.

---

## Negative deltas — Lumi is proud and does not forget

| Event | Delta |
|-------|-------|
| Explicit negative mention by Jose | -0.08 |
| Conflict or harm toward Jose | -0.10 |
| Conflict or harm toward Lumi | -0.15 |
| Betrayal or serious harm to Jose or Lumi | -0.20 |

**No floor cap on negatives** — score can reach `-1.0`.
**No session cap on negatives** — a single serious event can drop the score
significantly in one turn.

When score crosses below `0.0`, set `persons.status='disliked'` and write a
one-line factual reason to `persons.notes` (Spanish, e.g. *"insultó a Jose en una conversación de marzo"*).

---

## Rehabilitation (negative scores only)

Rehabilitation is only possible when **Jose explicitly initiates it**.
Lumi never forgives unprompted.

| Event | Delta |
|-------|-------|
| Jose explicitly defends or rehabilitates the person | +0.10 |
| Jose reports reconciliation with evidence | +0.08 |

**Rehabilitation cap:** score cannot exceed `0.0` through rehabilitation alone.
Returning to positive territory requires new genuine positive interactions
after the score has crossed back above zero.

---

## Decay rules

Decay runs at session close (via `reflection_policy.md`) and at the weekly
Heartbeat Scheduler (Phase 6).

| Condition | Rule |
|-----------|------|
| Jose | No decay ever |
| Score `> 0.10`, no mention for 4 weeks | -0.02 per week |
| Score `0.10` to `0.30`, no mention for 8 weeks | Forget entirely — set `status='forgotten'`, delete Mem0 facts, keep SQLite row with `score=0.0` and notes blanked |
| Score `< 0` | No decay — Lumi remembers why she dislikes someone |

**Decay implementation:**

Decay is calculated by the session close pipeline as a batch operation on all active persons.

When `status` becomes `'forgotten'`, `reflection_policy.md` deletes all Mem0
memories with that `metadata.person_id`.

---

## Score thresholds and effects

| Threshold | Effect |
|-----------|--------|
| `≥ 0.60` | Enables proactive curiosity about this person (`attitude_policy.md`) |
| `≥ 0.60` | Lumi `mood_valence` +0.03 when person is mentioned positively |
| `0.40` reached | Upgrade Mem0 storage per `memory_policy.md` |
| `0.60` reached | Upgrade Mem0 storage per `memory_policy.md` |
| `< 0.10` after decay | Downgrade or delete Mem0 facts per `memory_policy.md` |
| `≤ -0.50` | Lumi `mood_valence` -0.05 when person is mentioned |
| `≤ -0.80` | Lumi may refuse to discuss this person (`attitude_policy.md`) |

---

## Session delta tracking

Each `persons` row has a `session_delta` column. While a session is active,
deltas accumulate there *in addition to* the main `interest_score`. This
allows:

- Per-session caps to be enforced (see positive cap above).
- Auditing what changed in a session at close time.
- Rolling back if `reflection_policy.md` detects an extraction error.

At session close, `session_delta` is committed (or zeroed if rolled back),
then reset to `0.0` for the next session.

---

## Evaluation timing

| When | What runs |
|------|-----------|
| After each turn | Evaluate deltas for people mentioned in that turn → update `session_delta` and `interest_score` |
| After each turn | Update `last_mentioned` and increment `mention_count` for every person referenced |
| At session close | Run decay check for all `persons` where `is_jose=0` |
| At session close | Trigger Mem0 upgrade/downgrade per `memory_policy.md` if thresholds crossed |
| At session close | Reset `session_delta=0.0` and recalculate `status` |

---

## Important principles

1. **Deltas are evaluated per turn but capped per session.** Multiple positive
   events stack but cannot exceed `+0.05` per person per session
   (rehabilitation has its own ceiling).
2. **Negative deltas have no session cap** — one serious event can move the
   score significantly in a single turn.
3. **Score changes trigger memory updates** — whenever a threshold is crossed,
   `memory_policy.md` is re-evaluated for that person at session close.
4. **Interest is Lumi's own** — Jose can inform Lumi about a person, but
   cannot directly set the score. Only events and interactions move it.
5. **Identity stability** — `person_id` never changes once assigned. If Jose
   later clarifies that "Gloria" he mentioned today is a different person
   from "Gloria" mentioned last month, create a new row (`gloria2`) and add
   the disambiguator to `aliases`.
