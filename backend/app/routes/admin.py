"""Admin dashboard API: usage, learning and cost telemetry across all users. Read-only; admins only."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import telemetry
from ..auth import admin_user
from ..db import get_db
from ..models import Book, User
from .common import parse_id

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])


def since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))


def rows(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def one(db: Session, sql: str, **params) -> dict:
    r = db.execute(text(sql), params).first()
    return dict(r._mapping) if r else {}


def money(x) -> float:
    return round(float(x or 0), 4)


@router.get("/overview")
def overview(days: int = 30, db: Session = Depends(get_db)):
    t0 = since(days)
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    users = one(db, """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE created_at >= :t0) AS new,
               count(*) FILTER (WHERE last_seen_at >= now() - interval '1 day') AS active_1d,
               count(*) FILTER (WHERE last_seen_at >= now() - interval '7 days') AS active_7d,
               count(*) FILTER (WHERE last_seen_at >= now() - interval '30 days') AS active_30d,
               count(*) FILTER (WHERE plan_id = 'pro') AS pro
        FROM users""", t0=t0)
    library = one(db, """
        SELECT (SELECT count(*) FROM books) AS books, (SELECT coalesce(sum(pages), 0) FROM books) AS pages,
               (SELECT count(*) FROM chapters WHERE status = 'ready') AS chapters_built,
               (SELECT count(*) FROM chapters WHERE kind IN ('chapter', 'appendix')) AS chapters_total,
               (SELECT count(*) FROM lessons) AS lessons, (SELECT count(*) FROM cards) AS cards""")
    activity = {r["type"]: r["n"] for r in rows(db, """
        SELECT type, count(*) AS n FROM events WHERE created_at >= :t0 GROUP BY type""", t0=t0)}
    quiz = one(db, """
        SELECT count(*) AS n, avg((props->>'score')::float) AS avg_score FROM events
        WHERE type = 'quiz_submitted' AND created_at >= :t0""", t0=t0)
    cost = one(db, """
        SELECT coalesce(sum(cost_usd), 0) AS cost, coalesce(sum(tokens_in), 0) AS tokens_in,
               coalesce(sum(tokens_out), 0) AS tokens_out, coalesce(sum(calls), 0) AS calls,
               count(*) FILTER (WHERE NOT ok) AS errors, avg(latency_ms) FILTER (WHERE kind <> 'embed') AS avg_latency_ms
        FROM llm_calls WHERE created_at >= :t0""", t0=t0)
    month_cost = one(db, "SELECT coalesce(sum(cost_usd), 0) AS c FROM llm_calls WHERE created_at >= :m", m=month_start)["c"]
    last7 = one(db, "SELECT coalesce(sum(cost_usd), 0) AS c FROM llm_calls WHERE created_at >= now() - interval '7 days'")["c"]
    by_feature = rows(db, """
        SELECT feature, sum(calls) AS calls, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
               sum(cost_usd) AS cost FROM llm_calls WHERE created_at >= :t0 GROUP BY feature ORDER BY cost DESC""", t0=t0)
    by_kind = rows(db, """
        SELECT kind, model, tier, sum(calls) AS calls, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
               sum(cost_usd) AS cost, avg(latency_ms) AS avg_latency_ms
        FROM llm_calls WHERE created_at >= :t0 GROUP BY kind, model, tier ORDER BY cost DESC""", t0=t0)
    daily = rows(db, """
        SELECT to_char(d, 'YYYY-MM-DD') AS day, coalesce(sum(c.cost_usd), 0) AS cost,
               coalesce(sum(c.tokens_in), 0) AS tokens_in, coalesce(sum(c.tokens_out), 0) AS tokens_out,
               (SELECT count(DISTINCT e.user_id) FROM events e WHERE e.created_at::date = d::date) AS active_users
        FROM generate_series(date_trunc('day', CAST(:t0 AS timestamptz)), date_trunc('day', now()), interval '1 day') d
        LEFT JOIN llm_calls c ON c.created_at::date = d::date
        GROUP BY d ORDER BY d""", t0=t0)
    failed_jobs = one(db, "SELECT count(*) AS n FROM jobs WHERE status = 'failed' AND created_at >= :t0", t0=t0)["n"]
    daily_ai = float(last7) / 7
    return {
        "days": days, "users": users, "library": library,
        "activity": {"uploads": activity.get("book_uploaded", 0), "chapters_started": activity.get("chapter_started", 0),
                     "sections_completed": activity.get("section_completed", 0), "explains": activity.get("explain_submitted", 0),
                     "quizzes": quiz.get("n", 0), "quiz_avg": round(float(quiz["avg_score"]) * 100) if quiz.get("avg_score") is not None else None,
                     "final_tests": activity.get("final_test_submitted", 0), "cards_reviewed": activity.get("card_reviewed", 0),
                     "tutor_messages": activity.get("tutor_message", 0), "voice_clips": activity.get("voice_clip", 0),
                     "signups": activity.get("signup", 0)},
        "cost": {"period": money(cost.get("cost")), "tokens_in": int(cost.get("tokens_in") or 0),
                 "tokens_out": int(cost.get("tokens_out") or 0), "calls": int(cost.get("calls") or 0),
                 "errors": int(cost.get("errors") or 0),
                 "avg_latency_ms": round(cost["avg_latency_ms"]) if cost.get("avg_latency_ms") else None,
                 "month_to_date_ai": money(month_cost), "fixed_monthly": telemetry.FIXED_MONTHLY_USD,
                 "projected_month_ai": money(daily_ai * 30),
                 "projected_month_total": money(daily_ai * 30 + telemetry.FIXED_MONTHLY_USD),
                 "per_active_user_30d": money(float(last7) / 7 * 30 / max(1, users.get("active_30d") or 1)),
                 "prices": telemetry.PRICES},
        "by_feature": [{**r, "cost": money(r["cost"])} for r in by_feature],
        "by_kind": [{**r, "cost": money(r["cost"]), "avg_latency_ms": round(r["avg_latency_ms"] or 0)} for r in by_kind],
        "daily": [{**r, "cost": money(r["cost"])} for r in daily],
        "failed_jobs": failed_jobs,
    }


@router.get("/users")
def users(days: int = 30, db: Session = Depends(get_db)):
    t0 = since(days)
    out = rows(db, """
        SELECT u.id, u.email, u.name, u.plan_id, u.is_admin, u.limits_exempt, u.created_at, u.last_seen_at,
               u.level_default, u.daily_minutes,
               (SELECT count(*) FROM books b WHERE b.user_id = u.id) AS books,
               (SELECT count(*) FROM progress p WHERE p.user_id = u.id AND p.mastered) AS chapters_mastered,
               (SELECT coalesce(sum(jsonb_array_length(p.sections_done)), 0) FROM progress p WHERE p.user_id = u.id) AS sections_done,
               (SELECT round(avg(a.score) * 100) FROM attempts a WHERE a.user_id = u.id) AS quiz_avg,
               (SELECT coalesce(sum(s.seconds), 0) / 60 FROM study_days s WHERE s.user_id = u.id) AS study_minutes,
               (SELECT count(*) FROM reviews r WHERE r.user_id = u.id) AS reviews,
               (SELECT count(*) FROM chat_messages m WHERE m.user_id = u.id AND m.role = 'user') AS tutor_messages,
               (SELECT coalesce(sum(c.tokens_in), 0) FROM llm_calls c WHERE c.user_id = u.id AND c.created_at >= :t0) AS tokens_in,
               (SELECT coalesce(sum(c.tokens_out), 0) FROM llm_calls c WHERE c.user_id = u.id AND c.created_at >= :t0) AS tokens_out,
               (SELECT coalesce(sum(c.cost_usd), 0) FROM llm_calls c WHERE c.user_id = u.id AND c.created_at >= :t0) AS cost_period,
               (SELECT coalesce(sum(c.cost_usd), 0) FROM llm_calls c WHERE c.user_id = u.id) AS cost_total
        FROM users u ORDER BY u.last_seen_at DESC NULLS LAST, u.created_at DESC""", t0=t0)
    for r in out:
        r["id"] = str(r["id"])
        r["cost_period"], r["cost_total"] = money(r["cost_period"]), money(r["cost_total"])
    return out


@router.get("/users/{user_id}")
def user_detail(user_id: str, days: int = 30, db: Session = Depends(get_db)):
    u = db.get(User, parse_id(user_id))
    if u is None:
        raise HTTPException(404, "User not found")
    t0 = since(days)
    books = []
    for b in db.query(Book).filter_by(user_id=u.id).order_by(Book.created_at):
        chapters = rows(db, """
            SELECT c.n, c.title, c.kind, c.status, c.pdf_start, c.pdf_end,
                   (SELECT count(*) FROM sections s WHERE s.chapter_id = c.id) AS sections,
                   coalesce(jsonb_array_length(p.sections_done), 0) AS sections_done, p.quiz_best, coalesce(p.mastered, false) AS mastered,
                   p.prequestion->>'rating' AS self_rating, (p.explain->>'met')::int AS explain_met, (p.explain->>'total')::int AS explain_total,
                   (SELECT coalesce(sum(cost_usd), 0) FROM llm_calls l WHERE l.chapter_id = c.id) AS cost
            FROM chapters c LEFT JOIN progress p ON p.chapter_id = c.id AND p.user_id = :u
            WHERE c.book_id = :b ORDER BY c.n""", u=u.id, b=b.id)
        books.append({"id": str(b.id), "title": b.title, "pages": b.pages, "status": b.status, "kind": b.kind,
                      "structure_source": b.structure_source, "created_at": b.created_at.isoformat(),
                      "cost": money(one(db, "SELECT coalesce(sum(cost_usd), 0) AS c FROM llm_calls WHERE book_id = :b", b=b.id)["c"]),
                      "chapters": [{**c, "cost": money(c["cost"])} for c in chapters]})
    by_feature = rows(db, """
        SELECT feature, sum(calls) AS calls, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, sum(cost_usd) AS cost
        FROM llm_calls WHERE user_id = :u AND created_at >= :t0 GROUP BY feature ORDER BY cost DESC""", u=u.id, t0=t0)
    events = rows(db, """
        SELECT e.type, e.props, e.created_at, c.title AS chapter FROM events e LEFT JOIN chapters c ON c.id = e.chapter_id
        WHERE e.user_id = :u ORDER BY e.created_at DESC LIMIT 80""", u=u.id)
    for e in events:
        e["created_at"] = e["created_at"].isoformat()
    return {"user": {"id": str(u.id), "email": u.email, "name": u.name, "plan": u.plan_id, "is_admin": u.is_admin,
                     "created_at": u.created_at.isoformat(), "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
                     "level_default": u.level_default, "daily_minutes": u.daily_minutes, "goal": u.goal},
            "books": books, "by_feature": [{**r, "cost": money(r["cost"])} for r in by_feature], "events": events}


@router.get("/books")
def books(db: Session = Depends(get_db)):
    out = rows(db, """
        SELECT b.id, b.title, b.pages, b.bytes, b.kind, b.status, b.structure_source, b.embed_status, b.embedded_chunks,
               b.created_at, u.email,
               (SELECT count(*) FROM chapters c WHERE c.book_id = b.id AND c.kind IN ('chapter', 'appendix')) AS chapters,
               (SELECT count(*) FROM chapters c WHERE c.book_id = b.id AND c.status = 'ready') AS chapters_built,
               (SELECT coalesce(sum(cost_usd), 0) FROM llm_calls l WHERE l.book_id = b.id) AS cost
        FROM books b JOIN users u ON u.id = b.user_id ORDER BY b.created_at DESC""")
    for r in out:
        r["id"], r["cost"], r["created_at"] = str(r["id"]), money(r["cost"]), r["created_at"].isoformat()
    return out


@router.get("/learning")
def learning(days: int = 30, db: Session = Depends(get_db)):
    t0 = since(days)
    top_chapters = rows(db, """
        SELECT c.title, b.title AS book, count(*) FILTER (WHERE e.type = 'section_completed') AS sections_completed,
               count(*) FILTER (WHERE e.type = 'chapter_started') AS starts,
               count(*) FILTER (WHERE e.type = 'tutor_message') AS tutor_questions,
               round(avg((e.props->>'score')::float) FILTER (WHERE e.type = 'quiz_submitted') * 100) AS quiz_avg,
               count(DISTINCT e.user_id) AS learners
        FROM events e JOIN chapters c ON c.id = e.chapter_id JOIN books b ON b.id = c.book_id
        WHERE e.created_at >= :t0 GROUP BY c.id, c.title, b.title ORDER BY learners DESC, sections_completed DESC LIMIT 25""", t0=t0)
    top_topics = rows(db, """
        SELECT e.props->>'title' AS topic, e.props->>'section' AS section, count(*) AS completions,
               count(DISTINCT e.user_id) AS learners
        FROM events e WHERE e.type = 'section_completed' AND e.created_at >= :t0
        GROUP BY 1, 2 ORDER BY completions DESC LIMIT 25""", t0=t0)
    scores = rows(db, """
        SELECT width_bucket((props->>'score')::float, 0, 1.0001, 5) AS bucket, count(*) AS n
        FROM events WHERE type IN ('quiz_submitted', 'final_test_submitted') AND created_at >= :t0 GROUP BY 1 ORDER BY 1""", t0=t0)
    funnel_steps = [("signup", "Signed up"), ("book_uploaded", "Uploaded a book"), ("chapter_started", "Started a chapter"),
                    ("section_completed", "Finished a section"), ("explain_submitted", "Explained it back"),
                    ("quiz_submitted", "Took a quiz"), ("card_reviewed", "Reviewed flashcards")]
    counts = {r["type"]: r["n"] for r in rows(db, """
        SELECT type, count(DISTINCT user_id) AS n FROM events WHERE created_at >= :t0 GROUP BY type""", t0=t0)}
    explain = one(db, """
        SELECT count(*) AS n, avg((props->>'met')::float / nullif((props->>'total')::float, 0)) AS ratio
        FROM events WHERE type = 'explain_submitted' AND created_at >= :t0""", t0=t0)
    levels = rows(db, "SELECT level_default AS level, count(*) AS users FROM users GROUP BY 1 ORDER BY 2 DESC")
    return {"top_chapters": top_chapters, "top_topics": top_topics,
            "quiz_buckets": [{"range": f"{(b['bucket'] - 1) * 20}–{b['bucket'] * 20}%", "n": b["n"]} for b in scores if b["bucket"]],
            "funnel": [{"step": label, "users": counts.get(key, 0)} for key, label in funnel_steps],
            "explain": {"n": explain.get("n", 0), "avg_points": round(float(explain["ratio"]) * 100) if explain.get("ratio") is not None else None},
            "levels": levels}


@router.get("/calls")
def calls(limit: int = 100, errors_only: bool = False, db: Session = Depends(get_db)):
    out = rows(db, f"""
        SELECT l.id, l.created_at, u.email, l.feature, l.kind, l.model, l.tier, l.calls, l.tokens_in, l.tokens_out,
               l.units, l.cost_usd, l.latency_ms, l.ok, l.error, b.title AS book, c.title AS chapter
        FROM llm_calls l LEFT JOIN users u ON u.id = l.user_id LEFT JOIN books b ON b.id = l.book_id
        LEFT JOIN chapters c ON c.id = l.chapter_id {"WHERE NOT l.ok" if errors_only else ""}
        ORDER BY l.created_at DESC LIMIT :n""", n=max(1, min(limit, 500)))
    for r in out:
        r["created_at"] = r["created_at"].isoformat()
    return out


@router.get("/system")
def system(db: Session = Depends(get_db)):
    jobs = rows(db, """
        SELECT type, status, count(*) AS n FROM jobs WHERE created_at >= now() - interval '7 days' GROUP BY 1, 2 ORDER BY 1, 2""")
    failures = rows(db, """
        SELECT id, type, attempts, left(error, 400) AS error, created_at FROM jobs WHERE status = 'failed'
        ORDER BY created_at DESC LIMIT 20""")
    stuck = rows(db, """
        SELECT 'chapter' AS what, c.title AS name, c.status FROM chapters c WHERE c.status IN ('failed', 'building')
        UNION ALL SELECT 'book', b.title, b.status FROM books b WHERE b.status IN ('failed', 'processing', 'queued')
        UNION ALL SELECT 'embedding', b.title, b.embed_status FROM books b WHERE b.embed_status IN ('failed', 'running')""")
    for f in failures:
        f["created_at"] = f["created_at"].isoformat()
    return {"jobs": jobs, "failures": failures, "attention": stuck}
