"""Live Gemini smoke script for the 4 headline demo questions.

Skips cleanly when GEMINI_API_KEY is not configured. Run from backend/:
    .\\.venv\\Scripts\\python.exe smoke_advisor.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.advisor.agent import ask_advisor, rate_limiter
from app.advisor.llm import has_configured_gemini_key
from app.db import SessionLocal
from app.models import User
from app.seed import GROCERY_DEMO_EMAIL, seed_grocery_demo

DEMO_QUESTIONS = [
    "Why could I run out of cash next week?",
    "Can I afford a 15,000 purchase?",
    "How much cash is tied up in slow stock and overdue dues?",
    "Should I take a loan?",
]


def main() -> None:
    if not has_configured_gemini_key():
        print("SKIP: GEMINI_API_KEY is not configured in .env; skipping live Gemini smoke test.")
        return

    rate_limiter.reset()
    with SessionLocal() as db:
        info = seed_grocery_demo(db)
        db.commit()
        user = db.query(User).filter(User.email == GROCERY_DEMO_EMAIL).one()
        results = []
        for q in DEMO_QUESTIONS:
            res = ask_advisor(
                db=db,
                business_id=user.business.id,  # type: ignore[union-attr]
                user_id=user.id,
                question=q,
                enforce_rate_limit=False,
            )
            results.append({"question": q, "response": res.model_dump(mode="json")})

    out_path = BACKEND_DIR / "smoke_advisor_output.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved {len(results)} live responses for {info['business_name']} to {out_path}")


if __name__ == "__main__":
    main()
