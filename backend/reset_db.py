"""Drop and recreate all CashPilot database tables in the configured database."""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401 - register ORM models on Base.metadata
from app.db import Base, engine


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    reset_database()
    print("Database reset complete: all tables dropped and recreated.")
