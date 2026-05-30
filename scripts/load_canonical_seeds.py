"""
Carga de canonical seeds → JSONs runtime de la capa de evolución (Fase A).

Lee los seeds fuente (formato `entries[]`), les añade la metadata fija que el
pipeline espera (immutable, confidence=0.95, etc.) y los escribe como dict-EASE
(clave estable por id) en agent/identity/evolution/{lumi_tastes,lumi_rules}.json.

Idempotente: re-ejecutar regenera los JSON desde los seeds sin duplicar. NO toca
entries evolutivas (los seeds son immutable y se reescriben byte a byte; el
pipeline nocturno escribe entries con id distinto vía patches RFC-6902).

Uso:
    uv run python scripts/load_canonical_seeds.py
"""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARCH_DIR = REPO / ".architecture"
EVOLUTION_DIR = REPO / "agent" / "identity" / "evolution"
SEEDS_DIR = EVOLUTION_DIR / "seeds"

NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _common_meta(seed_text: str) -> dict:
    return {
        "confidence": 0.95,
        "evidence_count": 999,
        "unique_sessions": 999,
        "first_seen": NOW,
        "last_reinforced": NOW,
        "valid_from": NOW,
        "valid_to": None,
        "invalid_at": None,
        "source": "canonical_seed",
        "origin_pathway": "seed",
        "immutable": True,
        "decay_resistant": True,
        "promoted_by_patch": None,
    }


def build_tastes(entries: list[dict]) -> dict:
    out = {}
    for i, e in enumerate(entries, start=1):
        tid = f"taste_seed_{i:04d}"
        out[tid] = {
            "id": tid,
            "category": e["category"],
            "content": e["content"],
            "valence": e.get("valence"),
            **_common_meta(e["content"]),
            "inspired_by": e.get("inspired_by"),
            "embedding_hash": _sha256(e["content"]),
        }
    return out


def build_rules(entries: list[dict]) -> dict:
    out = {}
    for i, e in enumerate(entries, start=1):
        rid = f"rule_seed_{i:04d}"
        meta = _common_meta(e["trigger_pattern"])
        meta["success_count"] = 999
        meta["failure_count"] = 0
        out[rid] = {
            "id": rid,
            "category": e["category"],
            "trigger_pattern": e["trigger_pattern"],
            "heuristic": e["heuristic"],
            "expected_outcome": e.get("expected_outcome", ""),
            **meta,
            "inspired_by": e.get("inspired_by"),
            "trigger_embedding_hash": _sha256(e["trigger_pattern"]),
        }
    return out


def main() -> None:
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)

    plan = [
        ("tastes", "tastes", build_tastes),
        ("rules", "rules", build_rules),
    ]

    for name, container_key, builder in plan:
        src = ARCH_DIR / f"{name}_seed.json"
        # Conserva una copia canónica del seed fuente dentro del módulo.
        seed_copy = SEEDS_DIR / f"{name}_seed.json"
        shutil.copyfile(src, seed_copy)

        data = json.loads(src.read_text())
        entries = data["entries"]
        built = builder(entries)

        doc = {
            "schema_version": "1.0",
            "last_modified": NOW,
            container_key: built,
        }
        out_path = EVOLUTION_DIR / f"lumi_{name}.json"
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
        print(f"{name}: {len(built)} entries -> {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
