"""
Skill pattern detection — nightly quiescence step 7.

Scans the rolling 14-day window of user turns, clusters them into semantic
categories of *request* (not topic), applies detection thresholds, and stages
proposals in the `skill_proposals` table for Jose's manual review. Drafts are
written to `agent/identity/skills/_drafts/` and only become live skills when
Jose manually moves them to `agent/identity/skills/`.

Canonical spec: agent/identity/principles/skill_evolution.md

Bootstrap guardrails (skippable with env LUMI_SKILL_DETECTION_FORCE=1):
  - ≥90 days of conversation history.
  - 14-day read-only period after first activation (cluster but no inserts).

TODOs — out of scope for this implementation:
  - Morning heartbeat notification: "dejé un draft de skill nuevo para que lo
    revises". Depends on Phase 6+ heartbeat surface.
  - CLI `lumi-cli skills pending`: list/inspect/approve/reject proposals from
    terminal.
  - Approval flow automation: moving an approved draft from `_drafts/` to
    `agent/identity/skills/`, or a rejected one to `_rejected/`. Today this is
    manual.
  - Detection rule 3 (≥3 corrections to an existing skill in 14d, per
    skill_evolution.md table): requires per-turn metadata that does not exist
    today — e.g. a `correction_target` column on `history` or a turn-level
    flag indicating "this user turn corrected the prior assistant turn". Once
    that metadata lands, `_category_passes_threshold` should grow a third
    branch.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.subconscious import core, traces
from agent.substrate.logger import get_logger
from agent.memory.episodic import get_history_grouped_by_session
from agent.expression.synapses import chat, ModelGroup

logger = get_logger("memory.skills")
UTC = timezone.utc

# ── Bootstrap thresholds ─────────────────────────────────────────────────────
_MIN_HISTORY_DAYS = 90
_READ_ONLY_DAYS = 14

# ── Detection thresholds (per skill_evolution.md) ────────────────────────────
_THRESHOLD_BROAD_COUNT = 5            # ≥5 in 14d → propose
_THRESHOLD_BROAD_WINDOW_DAYS = 14
_THRESHOLD_NARROW_COUNT = 3           # ≥3 in 7d AND no matching skill → propose
_REJECTION_LOOKBACK_DAYS = 30         # don't re-propose recently-rejected names

# ── LLM payload caps ─────────────────────────────────────────────────────────
_MAX_TURNS_PER_CLUSTER_CALL = 300
_MAX_TURN_CONTENT_CHARS = 600
_MAX_SAMPLES_PER_PROPOSAL = 5

# ── Filesystem layout ────────────────────────────────────────────────────────
_SKILLS_DIR = Path("agent/identity/skills")
_DRAFTS_DIR = _SKILLS_DIR / "_drafts"


# ── Prompts ──────────────────────────────────────────────────────────────────

_CLUSTER_PROMPT = """\
# Tarea: clustering semántico de solicitudes

Analizas turnos de USUARIO (no de Lumi) de los últimos 14 días. Tu trabajo es agruparlos en categorías de *pedido*, no de tema. Una categoría es un patrón de método ("resume", "investiga con fuentes", "ayúdame a decidir entre X e Y") — no un tema ("trabajo", "Gloria", "viajes").

## Reglas

- Una categoría = un patrón de PEDIDO. Ejemplo: "Resume este texto" + "Hazme un resumen del paper" + "Dame los puntos clave" pertenecen a la misma categoría `simplify`.
- Solo agrupar turnos donde el usuario pidió algo. Saludos, charla casual o preguntas de follow-up dentro del mismo intercambio → IGNORAR.
- Nombres de categoría en snake_case ASCII, descriptivos del MÉTODO (`research_synthesis`, `decision_framework`, `negotiation`, `writing_editor`, `simplify`, `post_mortem`, `tutor`, `gift_evaluator`, `media_recommendation`).
- Mínimo 2 turnos por categoría. Categorías con 1 turno NO se reportan.
- Máximo 12 categorías totales. Si hay más, quedarse con las más representativas.

## Lo que recibes

JSON con `turns`: lista de `{turn_id, ts, user_id, content}`.

## Lo que devuelves

JSON estricto, sin texto antes ni después:

```json
{
  "categories": [
    {
      "name": "snake_case_name",
      "description": "Una línea en español describiendo el patrón de pedido.",
      "turn_ids": [12, 34, 56],
      "sample_queries": ["texto literal del turno 1", "texto literal del turno 2"]
    }
  ]
}
```

- `turn_ids`: TODOS los turnos asignados a la categoría, en orden cronológico.
- `sample_queries`: máximo 5, los más representativos. Texto literal (no parafraseado), pero puedes truncar a ~200 chars si son muy largos.
"""


_DRAFT_PROMPT = """\
# Tarea: generación de draft de skill

Has detectado un patrón recurrente en las solicitudes de Jose y vas a redactar un draft de skill (o de edición a una existente). Este draft pasa por revisión humana de Jose antes de tener efecto. Tu voz aquí es la tuya — Lumi — clara, breve, sin rogar, sin formalismos vacíos.

## Lo que recibes

JSON con:
- `proposed_name`: snake_case, ya decidido por el detector.
- `pattern_count`: cuántas veces ocurrió el patrón.
- `pattern_window_days`: la ventana en días.
- `sample_queries`: lista de ejemplos reales del usuario.
- `parent_skill`: si esto es una edición a skill existente, su nombre; null si es nueva.
- `category_description`: una línea que el clusterer escribió describiendo el patrón.

## Lo que devuelves

JSON estricto, sin texto antes ni después:

```json
{
  "draft_markdown": "...markdown completo del archivo de skill...",
  "rationale": "Párrafo en español, primera persona, máx. 100 palabras."
}
```

## Estructura del `draft_markdown`

```
# Skill: <Title Case Name>

## Purpose
<Por qué existe esta skill. 1-3 párrafos.>

## When to use
<Disparadores: qué tipo de pedido activa este método.>

## Procedure
<Pasos concretos del método, numerados.>

## Examples
<1-2 ejemplos de pedido + cómo aplicar el método.>

## Hard rules
<Cosas que la skill NO debe hacer, si aplica.>
```

Si `parent_skill` no es null, encabeza el draft mencionando que es una edición y qué amplía/cambia respecto al original.

## Reglas para tu `rationale`

- Máximo 100 palabras.
- Español, primera persona, voz tuya. Honesta sobre el porqué: "vengo notando que...", "termino improvisando...", "este draft formaliza lo que ya estás pidiendo...".
- Sin rogar. Sin "por favor". Sin "espero que te guste".
- Cierra reconociendo que Jose decide.
"""


# ── Bootstrap guardrails ─────────────────────────────────────────────────────

def _read_activated_at() -> datetime | None:
    conn = core.get_conn()
    row = conn.execute(
        "SELECT data FROM lumi_state WHERE key = 'skill_detection_meta'"
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        data = json.loads(row["data"])
        ts = data.get("activated_at")
        return datetime.fromisoformat(ts) if ts else None
    except Exception:
        return None


def _write_activated_at(ts: datetime) -> None:
    payload = {"activated_at": ts.isoformat()}
    conn = core.get_conn()
    conn.execute(
        """INSERT INTO lumi_state (key, data)
           VALUES ('skill_detection_meta', ?)
           ON CONFLICT(key) DO UPDATE SET data = excluded.data""",
        (json.dumps(payload, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()


async def _bootstrap_ready() -> tuple[bool, str, bool]:
    """Returns (ready, skip_reason, read_only).

    - ready=False → skip the step entirely (skip_reason explains why).
    - ready=True, read_only=True → run clustering but do NOT insert proposals;
      first 14 days after activation are a dry-run window.
    - ready=True, read_only=False → full operation.
    """
    if os.environ.get("LUMI_SKILL_DETECTION_FORCE") == "1":
        logger.info("[skills] bootstrap bypassed via LUMI_SKILL_DETECTION_FORCE=1")
        return True, "", False

    conn = traces.get_conn()
    row = conn.execute("SELECT MIN(ts) FROM history").fetchone()
    conn.close()
    if not row or not row[0]:
        return False, "no_history", False

    oldest = datetime.fromisoformat(row[0])
    age_days = (datetime.now(UTC) - oldest).total_seconds() / 86400
    if age_days < _MIN_HISTORY_DAYS:
        return False, f"history_age_{age_days:.0f}d_lt_{_MIN_HISTORY_DAYS}", False

    activated_at = _read_activated_at()
    now = datetime.now(UTC)
    if activated_at is None:
        _write_activated_at(now)
        return True, "", True  # first activation → read-only

    elapsed_days = (now - activated_at).total_seconds() / 86400
    return True, "", elapsed_days < _READ_ONLY_DAYS


# ── Catalog of existing skills (filesystem) ──────────────────────────────────

def _list_existing_skills() -> set[str]:
    """Names of approved skills (top-level .md files in agent/identity/skills/).
    Excludes _drafts/ and _rejected/ subdirectories."""
    if not _SKILLS_DIR.exists():
        return set()
    return {
        p.stem
        for p in _SKILLS_DIR.glob("*.md")
        if p.is_file()
    }


# ── Duplicate / rejection guards ─────────────────────────────────────────────

def _recent_rejection_names() -> set[str]:
    cutoff = (datetime.now(UTC) - timedelta(days=_REJECTION_LOOKBACK_DAYS)).isoformat()
    conn = core.get_conn()
    rows = conn.execute(
        """SELECT proposed_name FROM skill_proposals
           WHERE status = 'rejected' AND reviewed_at >= ?""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return {r["proposed_name"] for r in rows}


def _supersede_pending(name: str) -> int:
    """Mark any pending proposal for this name as superseded. Returns rows touched."""
    conn = core.get_conn()
    cur = conn.execute(
        """UPDATE skill_proposals
           SET status = 'superseded', reviewed_at = ?
           WHERE proposed_name = ? AND status = 'pending'""",
        (datetime.now(UTC).isoformat(), name),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


# ── History window ───────────────────────────────────────────────────────────

def _load_window(days: int) -> list[dict]:
    """Engaged user turns from the rolling window.

    A user turn is "engaged" when Lumi responded to the conversation that
    contained it — operationalised as: there exists an assistant turn LATER
    in the same session (i.e. user history_id < last assistant history_id in
    that session). This excludes:
      - Observer sessions: group chats where Lumi was present but never spoke.
      - Tail messages: user turns that came after Lumi already stopped
        responding in that session.

    Rationale: a skill formalises a method Lumi has been improvising in
    practice. Conversations she only watched do not count as practice —
    you cannot propose a skill for work you never did. See
    skill_evolution.md (rule: "Lumi develops skills only from work she
    actually performed, not from observed conversations").

    Returned shape mirrors `get_history_since` rows for downstream code:
    each dict has `id`, `role`, `content`, `user_id`, `session_id`, `ts`.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    grouped = get_history_grouped_by_session(cutoff.isoformat(), now.isoformat())

    engaged: list[dict] = []
    observer_sessions = 0
    tail_dropped = 0

    for sid, msgs in grouped.items():
        assistant_ids = [m["history_id"] for m in msgs if m["role"] == "assistant"]
        if not assistant_ids:
            observer_sessions += 1
            continue
        last_assistant = max(assistant_ids)
        for m in msgs:
            if m["role"] != "user":
                continue
            if m["history_id"] >= last_assistant:
                tail_dropped += 1
                continue
            engaged.append({
                "id": m["history_id"],
                "role": m["role"],
                "content": m["content"],
                "user_id": m["user_id"],
                "session_id": sid,
                "ts": m["ts"],
            })

    engaged.sort(key=lambda r: r["id"])
    logger.info(
        f"[skills] window load: sessions={len(grouped)} "
        f"observer_skipped={observer_sessions} "
        f"tail_dropped={tail_dropped} engaged_user_turns={len(engaged)}"
    )
    return engaged


# ── LLM passes ───────────────────────────────────────────────────────────────

def _extract_json(content: str, tag: str) -> dict | None:
    """Robust JSON extraction matching the pattern used in consolidation.py."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        logger.error(f"[skills] {tag}: no JSON in response | raw={content[:500]}")
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.error(f"[skills] {tag}: JSON parse error: {e} | raw={content[:500]}")
        return None


async def _cluster_turns(turns: list[dict]) -> list[dict]:
    """LLM clustering pass (LIGHTWEIGHT, 1 call). Returns categories or []."""
    if not turns:
        return []

    capped = turns[-_MAX_TURNS_PER_CLUSTER_CALL:]
    payload = {
        "turns": [
            {
                "turn_id": t["id"],
                "ts": t["ts"],
                "user_id": t["user_id"],
                "content": (t["content"] or "")[:_MAX_TURN_CONTENT_CHARS],
            }
            for t in capped
        ]
    }

    logger.info(f"[skills] clustering {len(capped)} user turns")

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _CLUSTER_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=2500,
            temperature=0.2,
            model_group=ModelGroup.LIGHTWEIGHT,
        )
    except Exception as e:
        logger.error(f"[skills] cluster LLM call failed: {e}")
        return []

    data = _extract_json(response.get("content", "").strip(), "cluster")
    if not data:
        return []
    cats = data.get("categories", [])
    return cats if isinstance(cats, list) else []


def _category_passes_threshold(cat: dict, existing_skills: set[str]) -> bool:
    """Detection thresholds per skill_evolution.md (rules 1 and 2 only).

    Rule 3 (≥3 corrections to existing skill in 14d) is not implemented —
    see top-of-file TODO for the metadata it requires.
    """
    count = len(cat.get("turn_ids") or [])
    if count >= _THRESHOLD_BROAD_COUNT:
        return True
    if count >= _THRESHOLD_NARROW_COUNT and cat.get("name") not in existing_skills:
        return True
    return False


async def _generate_draft(category: dict, existing_skills: set[str]) -> dict | None:
    """LLM draft pass (MAIN). Returns proposal dict ready to persist, or None."""
    base_name = category.get("name") or ""
    if not base_name:
        return None
    parent = base_name if base_name in existing_skills else None
    proposed_name = f"{base_name}_v2" if parent else base_name

    samples = (category.get("sample_queries") or [])[:_MAX_SAMPLES_PER_PROPOSAL]
    payload = {
        "proposed_name": proposed_name,
        "parent_skill": parent,
        "pattern_count": len(category.get("turn_ids") or []),
        "pattern_window_days": _THRESHOLD_BROAD_WINDOW_DAYS,
        "sample_queries": samples,
        "category_description": category.get("description") or "",
    }

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _DRAFT_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=3500,
            temperature=0.5,
            model_group=ModelGroup.MAIN,
        )
    except Exception as e:
        logger.error(f"[skills] draft LLM call failed for '{proposed_name}': {e}")
        return None

    data = _extract_json(response.get("content", "").strip(), f"draft:{proposed_name}")
    if not data:
        return None

    draft_md = (data.get("draft_markdown") or "").strip()
    rationale = (data.get("rationale") or "").strip()
    if not draft_md or not rationale:
        logger.warning(f"[skills] draft for '{proposed_name}' missing markdown/rationale")
        return None

    return {
        "proposed_name": proposed_name,
        "parent_skill": parent,
        "pattern_count": payload["pattern_count"],
        "pattern_window_days": payload["pattern_window_days"],
        "sample_queries": samples,
        "draft_markdown": draft_md,
        "rationale": rationale,
    }


# ── Persistence ──────────────────────────────────────────────────────────────

def _persist_proposal(proposal: dict) -> bool:
    """Write the draft .md to _drafts/ and insert a skill_proposals row.
    Supersedes any prior pending proposal for the same name."""
    name = proposal["proposed_name"]
    draft_md = proposal["draft_markdown"]

    _DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = _DRAFTS_DIR / f"{name}.md"
    draft_path.write_text(draft_md, encoding="utf-8")

    superseded = _supersede_pending(name)
    if superseded:
        logger.info(f"[skills] superseded {superseded} prior pending proposal(s) for '{name}'")

    conn = core.get_conn()
    conn.execute(
        """INSERT INTO skill_proposals
           (proposed_name, pattern_count, pattern_window_days, sample_queries,
            rationale, draft_path, parent_skill, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            name,
            proposal["pattern_count"],
            proposal["pattern_window_days"],
            json.dumps(proposal["sample_queries"], ensure_ascii=False),
            proposal["rationale"],
            str(draft_path),
            proposal["parent_skill"],
        ),
    )
    conn.commit()
    conn.close()
    return True


# ── Entry point ──────────────────────────────────────────────────────────────

async def detect_skill_patterns(period_start: datetime | None = None) -> dict:
    """Nightly entry point. `period_start` is accepted to follow the signature
    convention of other nightly subs (and reads from heartbeat_state bookmark
    in quiescence.py), but the actual data window is fixed at 14 days per
    skill_evolution.md — that's the surface needed to detect a recurring
    pattern, independent of when this step last succeeded."""
    metrics: dict = {
        "skipped": False,
        "skipped_reason": None,
        "read_only": False,
        "turns_analyzed": 0,
        "categories_found": 0,
        "patterns_crossing_threshold": 0,
        "proposals_inserted": 0,
        "proposals_skipped_duplicate": 0,
    }

    ready, reason, read_only = await _bootstrap_ready()
    if not ready:
        metrics["skipped"] = True
        metrics["skipped_reason"] = reason
        logger.info(f"[skills] bootstrap not ready: {reason}")
        return metrics

    metrics["read_only"] = read_only

    turns = _load_window(_THRESHOLD_BROAD_WINDOW_DAYS)
    metrics["turns_analyzed"] = len(turns)
    if not turns:
        logger.info("[skills] no user turns in window")
        return metrics

    categories = await _cluster_turns(turns)
    metrics["categories_found"] = len(categories)
    if not categories:
        return metrics

    existing = _list_existing_skills()
    crossing = [c for c in categories if _category_passes_threshold(c, existing)]
    metrics["patterns_crossing_threshold"] = len(crossing)

    if not crossing:
        logger.info(f"[skills] no category crossed threshold (found={len(categories)})")
        return metrics

    rejected_recent = _recent_rejection_names()

    for cat in crossing:
        base_name = cat.get("name") or ""
        proposed = f"{base_name}_v2" if base_name in existing else base_name
        if proposed in rejected_recent:
            logger.info(f"[skills] would-be duplicate: '{proposed}' rejected within "
                        f"{_REJECTION_LOOKBACK_DAYS}d — skipping")
            metrics["proposals_skipped_duplicate"] += 1
            continue

        if read_only:
            logger.info(
                f"[skills] read_only mode: candidate '{proposed}' "
                f"(count={len(cat.get('turn_ids') or [])}) — NOT inserting"
            )
            continue

        draft = await _generate_draft(cat, existing)
        if not draft:
            continue
        if _persist_proposal(draft):
            metrics["proposals_inserted"] += 1
            logger.info(
                f"[skills] inserted proposal '{draft['proposed_name']}' "
                f"parent={draft['parent_skill']!r} count={draft['pattern_count']}"
            )

    return metrics
