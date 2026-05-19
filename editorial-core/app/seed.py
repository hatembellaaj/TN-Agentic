"""
Seed initial : 24 gouvernorats tunisiens depuis seed/governorates.json.
Exécuter une seule fois après les migrations Alembic :
    docker compose exec editorial-core python -m app.seed
"""
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.models import Governorate


def run() -> None:
    seed_path = Path(__file__).resolve().parent.parent / "seed" / "governorates.json"
    with seed_path.open("r", encoding="utf-8") as f:
        rows = json.load(f)

    with Session(engine) as session:
        existing = session.scalar(select(Governorate).limit(1))
        if existing:
            print("→ Table governorates déjà peuplée, seed ignoré.")
            return

        for row in rows:
            session.add(Governorate(**row))
        session.commit()
        print(f"✓ Seed terminé : {len(rows)} gouvernorats insérés.")


if __name__ == "__main__":
    run()
