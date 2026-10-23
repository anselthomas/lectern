"""Admin tasks run on the server: `python -m app.admin grant-internal EMAIL`.

Marks an existing Cognito user as the internal QA account (plan=internal, no usage limits).
The Cognito user and its password are created separately with admin credentials (see deploy/create-test-user.sh).
"""
import sys

from .aws import cognito
from .config import settings
from .db import Base, SessionLocal, engine
from .limits import seed_plans
from .models import User


def grant_internal(email: str) -> None:
    Base.metadata.create_all(engine)
    attrs = cognito().admin_get_user(UserPoolId=settings.user_pool_id, Username=email)["UserAttributes"]
    sub = next(a["Value"] for a in attrs if a["Name"] == "sub")
    with SessionLocal() as db:
        seed_plans(db)
        user = db.query(User).filter_by(cognito_sub=sub).one_or_none()
        if user is None:
            user = User(cognito_sub=sub, email=email, name="Lectern QA")
            db.add(user)
        user.plan_id, user.limits_exempt = "internal", True
        db.commit()
    print(f"{email}: plan=internal, limits_exempt=true")


def reset_user(email: str) -> None:
    """Delete a user's books (S3 file, vectors, cache) and learning history, keeping the account itself."""
    from sqlalchemy import func

    from . import vectors
    from .models import Book, Card, ChatMessage, Chunk, Notification, Note, Review, StudyDay, UsageMonthly
    from .storage import delete_object, drop_local

    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        for book in db.query(Book).filter_by(user_id=user.id):
            n = db.query(func.count(Chunk.id)).filter(Chunk.book_id == book.id).scalar()
            vectors.delete_book(str(book.id), n)
            delete_object(book.s3_key)
            drop_local(book.id)
            db.delete(book)
        for model in (Review, Card, ChatMessage, Note, Notification, StudyDay, UsageMonthly):
            db.query(model).filter(model.user_id == user.id).delete()
        user.onboarded = False
        db.commit()
    print(f"{email}: books and history removed")


def backfill_usage() -> None:
    """One-off: turn token totals recorded before per-call telemetry into one llm_calls row per user and month."""
    from datetime import datetime, timezone

    from . import telemetry
    from .models import LlmCall, UsageMonthly

    with SessionLocal() as db:
        n = 0
        for row in db.query(UsageMonthly).all():
            if not (row.tokens_in or row.tokens_out):
                continue
            if db.query(LlmCall).filter_by(user_id=row.user_id, kind="backfill").first():
                continue
            logged_in = sum(c.tokens_in for c in db.query(LlmCall).filter_by(user_id=row.user_id))
            logged_out = sum(c.tokens_out for c in db.query(LlmCall).filter_by(user_id=row.user_id))
            tin, tout = max(0, row.tokens_in - logged_in), max(0, row.tokens_out - logged_out)
            if tin or tout:
                db.add(LlmCall(user_id=row.user_id, feature="before_telemetry", kind="backfill", model="nova-2-lite (estimated)",
                               tier="standard", calls=0, tokens_in=tin, tokens_out=tout,
                               cost_usd=round(telemetry.text_cost(tin, tout), 6), ok=True,
                               created_at=datetime.strptime(row.month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)))
                n += 1
        db.commit()
    print(f"backfilled {n} user-months")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "backfill-usage":
        backfill_usage()
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "grant-internal":
        grant_internal(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "reset-user":
        reset_user(sys.argv[2])
    else:
        sys.exit("usage: python -m app.admin grant-internal|reset-user EMAIL")
