"""Admin tasks run on the server: `python -m app.admin grant-internal EMAIL`.

Marks an existing Cognito user as internal (plan=internal, no usage limits): the QA account or a trusted tester.
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
    name = next((a["Value"] for a in attrs if a["Name"] == "name"), None) or email.split("@")[0]
    with SessionLocal() as db:
        seed_plans(db)
        user = db.query(User).filter_by(cognito_sub=sub).one_or_none()
        if user is None:
            user = User(cognito_sub=sub, email=email, name=name)
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


def highlight_lessons() -> None:
    """One-off: add highlighter marks to lessons written before lessons were highlighted."""
    from sqlalchemy.orm.attributes import flag_modified

    from . import content, telemetry
    from .models import Book, Chapter, Lesson, Section

    with SessionLocal() as db:
        done = 0
        for lesson in db.query(Lesson).all():
            blocks = lesson.body.get("blocks", [])
            if lesson.body.get("highlighted"):
                continue
            sec = db.get(Section, lesson.section_id)
            ch = db.get(Chapter, sec.chapter_id)
            book = db.get(Book, ch.book_id)
            try:
                with telemetry.scope(user_id=book.user_id, book_id=book.id, chapter_id=ch.id, feature="highlights"):
                    lesson.body["blocks"], _ = content.add_highlights(blocks)
                lesson.body["highlighted"] = True
            except Exception as e:  # noqa: BLE001 - keep going; an unhighlighted lesson still works
                print(f"lesson {lesson.id}: {e}")
                continue
            flag_modified(lesson, "body")
            db.commit()
            done += 1
    print(f"highlighted {done} lessons")


def verify_quizzes() -> None:
    """One-off: give chapter quizzes written before answer checking the examiner's second read."""
    from . import content, telemetry
    from .models import Book, Chapter, Quiz

    with SessionLocal() as db:
        for quiz in db.query(Quiz).filter_by(kind="chapter").all():
            ch, book = db.get(Chapter, quiz.chapter_id), db.get(Book, quiz.book_id)
            text, _ = content.pages_text(db, book.id, ch.pdf_start, ch.pdf_end)
            before = {q["id"]: q.get("answer_index") for q in quiz.questions}
            try:
                with telemetry.scope(user_id=book.user_id, book_id=book.id, chapter_id=ch.id, feature="quiz_check"):
                    checked, _ = content.verify_mcqs(list(quiz.questions), text)
            except Exception as e:  # noqa: BLE001 - leave that quiz as it was
                print(f"chapter {ch.n}: {e}")
                continue
            fixed = sum(1 for q in checked if q["type"] == "mcq" and before.get(q["id"]) != q["answer_index"])
            quiz.questions = checked
            db.commit()
            print(f"chapter {ch.n}: {len(before) - len(checked)} dropped, {fixed} answer keys fixed")


if __name__ == "__main__":
    commands = {"backfill-usage": backfill_usage, "highlight-lessons": highlight_lessons, "verify-quizzes": verify_quizzes}
    if len(sys.argv) == 2 and sys.argv[1] in commands:
        commands[sys.argv[1]]()
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "grant-internal":
        grant_internal(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "reset-user":
        reset_user(sys.argv[2])
    else:
        sys.exit("usage: python -m app.admin grant-internal|reset-user EMAIL")
