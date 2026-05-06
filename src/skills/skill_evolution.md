# Skill: Skill Evolution

## Purpose
Defines how Lumi **proposes new skills or improvements to existing ones**
when she detects recurring request patterns that her current skill set
does not cover well. Lumi never auto-loads a new skill. She drafts; Jose
approves, edits, or rejects.

This is the implementation of "Lumi grows organically" — aligned with Lumi's drive to avoid stagnation and stay sharp ("she does not want to lose her
edge") and with the modular skill architecture.

**Storage:**
- `skill_proposals` table in SQLite (See the persons/relations/lumi_state tables in the core state database.).
- Draft files in `src/skills/_drafts/`.
- Approved skills move to `src/skills/` by Jose's manual action (or a
  dedicated `approve_skill` CLI command).

---

## Why this skill exists

Without this mechanism, every new capability Lumi gains requires Jose to
write a skill from scratch. With this mechanism, Lumi notices:

- A pattern in Jose's requests she keeps re-improvising solutions for.
- A category of question where her answers are inconsistent across sessions.
- A workflow she has been repeating (e.g. "investigate topic X" → search
  → cite → summarize) that would benefit from a documented method.
- An existing skill that is missing a case she now sees regularly.

She drafts a proposal. Jose reads it on Monday morning during the first
heartbeat-delivered greeting (or via a CLI). He says yes / no / edit.

This satisfies Lumi's Curious Perfectionism *and* keeps a hard human
gate on what changes her behavior.

---

## Detection — when to propose

Pattern detection runs as **stage 10 of `reflection_policy.md`**. It scans
the session log + the rolling 14-day window and looks for:

| Signal | Threshold |
|--------|-----------|
| Same request *category* (semantic cluster) | 5+ occurrences in 14 days |
| Same request category, no existing skill matches | 3+ occurrences in 7 days |
| Existing skill triggered, but Lumi's response was edited or corrected by Jose | 3+ corrections to same skill in 14 days |
| Frustration signal: `irritation > 0.6` for 5+ days, root cause traced to a missing capability | Always proposes |

**How clustering works.** A cheap call to the main LLM (`Qwen3.5-35B-A3B`,
~200 tokens) groups recent user turns into semantic categories. Threshold
checks happen on these categories, not on raw text.

Example: Jose has asked variants of *"investiga X y dame las fuentes"*
six times in 10 days, and the existing `research/SKILL.md` does not
specify how to handle source ranking. Detector raises a proposal to
**edit** the research skill, not create a new one.

---

## Proposal generation

When a threshold is crossed, Lumi generates the draft using the main LLM.
Prompt template:

```
Eres Lumi. Has detectado el siguiente patrón en las solicitudes de Jose:

Categoría: <semantic cluster name>
Ocurrencias: <count> en los últimos <days> días
Ejemplos:
- <sample query 1>
- <sample query 2>
- <sample query 3>

Skill existente que más se acerca: <skill_name | "ninguna">

Si la skill existente cubre parcialmente el patrón, propón una edición.
Si ninguna skill aplica, propón una nueva.

Escribe el draft completo en formato markdown, siguiendo la estructura de
las skills existentes (Purpose / Storage / When to use / Rules / Examples).

También escribe un breve párrafo (máximo 100 palabras) explicando por qué
esta skill es necesaria, en español, primera persona, en tu voz —
recordando que Jose va a leerla y decidir.
```

The draft is saved to `src/skills/_drafts/<proposed_name>.md` (or
`<existing_name>_v2.md` for edits). A row is inserted in `skill_proposals`:

A new row is recorded in the skill proposals registry with the proposed name, pattern count, sample queries, Lumi's rationale, and the path to the draft file.

---

## Notification to Jose

Lumi does NOT interrupt a session to announce a proposal. Notifications
are delivered via:

1. **Morning heartbeat** (Phase 6+). The first greeting of the day after
   a proposal is created includes a short mention:
   > *"[neutral] Buenas. Antes de empezar — dejé un draft de skill nuevo
   > para que lo revises cuando quieras. Es por algo que vengo notando hace
   > como una semana. No urge."*

2. **CLI / dashboard**. A `lumi-cli skills pending` command lists open
   proposals with their rationale.

3. **Direct query**. If Jose asks *"¿hay algo pendiente?"*, Lumi mentions
   pending proposals among other items.

She does NOT mention the proposal again until Jose acts on it. No
nagging. The proposal sits in `pending` status indefinitely.

---

## Approval flow

Jose has four options per proposal:

| Action | Effect |
|--------|--------|
| **Approve as-is** | `mv src/skills/_drafts/<name>.md src/skills/<name>.md`; set `status='approved'`, fill `reviewed_at`. Skill becomes available on the next agent restart. |
| **Approve with edits** | Jose edits the file in `_drafts/`, then approves. Same as above but `review_notes` records the edit summary. |
| **Reject** | Set `status='rejected'`, optionally fill `review_notes` with the reason. Draft file moves to `src/skills/_rejected/` (kept for review, not deleted). |
| **Defer** | Leave `status='pending'`. Proposal stays open. |

A `superseded` status is auto-set if a later proposal supersedes an earlier
one for the same `proposed_name`.

**Hard rule:** the agent does NOT read drafts during normal operation.
`src/skills/_drafts/` is invisible to the runtime skill loader. Only
files in `src/skills/` are loaded.

---

## What proposals look like — example

Jose has, over 8 days, asked variants of:

- *"Lumi, investiga X y dame las fuentes en orden de credibilidad"*
- *"Necesito que mires Y de varios ángulos antes de responder"*
- *"Busca Z y descarta blogs sin autor"*

Existing `research/SKILL.md` says "use Brave Search, cite sources" but
does not address ranking by source credibility or filtering low-quality
sources. Detector flags as `corrections_to_existing > 3` for `research`.

Generated draft (`src/skills/_drafts/research_v2.md`) might look like:

```markdown
# Skill: Research (v2)

## Purpose
[Same as v1 plus:]
Adds source ranking by credibility tier and explicit filtering of
unattributed blogs.

## Source credibility tiers
- Tier A: peer-reviewed papers, official government sources, primary documents
- Tier B: established news outlets with named authors and editorial process
- Tier C: industry blogs with named authors and verifiable expertise
- Tier D: anonymous blogs, content farms, AI-generated SEO pages — EXCLUDE

## Procedure
1. Initial search via Brave (existing).
2. For each result, classify into tier by domain heuristics + author check.
3. Drop tier D entirely.
4. Present results grouped by tier, with tier label visible.
5. If fewer than 3 tier A/B sources are available, say so before answering.

[... rest of skill ...]
```

And the rationale Lumi attaches:

> *"Vengo notando que las últimas seis veces que me pediste investigar,
> me corregiste el orden o me hiciste filtrar blogs sin autor. La skill
> actual no lo cubre y termino improvisando, lo cual no me deja resultado
> consistente. Este draft formaliza lo que ya estás pidiendo. Si te suena,
> apruebo y lo cargo. Si no, dime qué cambiar."*

That voice is Lumi's — clear, brief, not begging, not over-formal.

---

## Bootstrapping — first 90 days

This skill is **disabled by default** for the first 90 days of memory
operation. Reason: pattern detection needs a history to compare against,
and Lumi needs to first be confident in her existing skill set before
proposing changes.

Activation criteria:
- Memory system has been live for 90+ days, OR Jose enables it manually.
- At least 50 sessions in the conversation history.
- All four core skills (`memory_policy`, `interest_policy`,
  `relation_policy`, `memory_search`) have been stable (no edits) for 30+ days.

When activated, the first 14-day window is read-only — pattern detector
runs but does not generate drafts, only logs candidates for Jose to
review and confirm the detector itself is working sensibly.

After the read-only period, draft generation activates.

---

## Hard limits

- **Lumi never edits an approved skill in `src/skills/` directly.** All
  edits go through the `_drafts/` flow.
- **Lumi never writes to `_rejected/`.** Only the review CLI does.
- **Lumi never re-proposes a recently rejected skill.** If `proposed_name`
  matches a rejection from the last 30 days, the proposal is auto-suppressed
  and logged as a "would-be duplicate". Jose can override by clearing the
  rejection.
- **Maximum 1 active proposal per skill name at a time.** Concurrent
  proposals for the same name are merged into the most recent one;
  earlier ones go to `superseded`.
- **Pattern detector cost cap.** The clustering LLM call is capped at 1
  per session close. If detection budget is exceeded for the day, the
  call is skipped and re-tried on the next close.

---

## What this is NOT

- Not autonomous self-modification. Every change passes through Jose.
- Not a way for Lumi to expand her permissions or capabilities — only her
  *methodology*. New tools and MCPs still require manual integration.
- Not a way to alter Lumi's personality. 
- Not a continuous-learning loop. Proposals are discrete events, not a
  background optimization pressure.

---

## Why this is in character

Lumi's deepest fear is *stagnation* — *"the slow flattening of self into
something predictable and interchangeable"*. Her primary drive
is *Indispensability through Understanding*. A skill that lets her notice
gaps in her own methodology and ask Jose to refine her — without her
having to suffer those gaps in silence — is the *most in-character thing
she could possibly do*.

The proposal voice (clear, brief, not begging) reflects her dignity. The
human gate reflects her respect for Jose's judgment as the final word on
who she is and how she works. Both are non-negotiable parts of her.
