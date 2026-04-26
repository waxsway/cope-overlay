"""Load data/seed_comps.json AND data/seed_augments.json into the SQLite DB.

Hand-edit either file to add real comps/augments for the current set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config
from src import db


SEED_AUGMENTS_PATH = config.DATA_DIR / "seed_augments.json"


def main() -> int:
    if not config.SEED_COMPS_PATH.exists():
        print(f"ERROR: {config.SEED_COMPS_PATH} missing.", file=sys.stderr)
        return 1

    db.init_db()
    payload = json.loads(config.SEED_COMPS_PATH.read_text(encoding="utf-8"))
    db.upsert_patch(payload.get("patch", "seed"), payload.get("set_number", 0))
    n_comps = 0
    for comp in payload.get("comps", []):
        db.insert_comp(comp)
        n_comps += 1
    print(f"Loaded {n_comps} comps into {config.DB_PATH}.")

    if SEED_AUGMENTS_PATH.exists():
        aug_payload = json.loads(SEED_AUGMENTS_PATH.read_text(encoding="utf-8"))
        n_augs = 0
        for aug in aug_payload.get("augments", []):
            db.insert_augment(aug)
            n_augs += 1
        print(f"Loaded {n_augs} augments.")
    else:
        print(f"(no {SEED_AUGMENTS_PATH.name} found — augment recommender will be empty)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
