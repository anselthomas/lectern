import csv
import json
import io
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import telemetry, vectors
from ..auth import current_user
from ..aws import cognito
from ..config import settings
from ..db import get_db
from ..limits import usage_summary
from ..models import (
    Attempt, Book, Card, Chapter, ChatMessage, Chunk, Note, Notification, Progress, Quiz, Review, StudyDay, User,
)
from ..storage import delete_object, drop_local
from .common import chapter_label, label_for, own_book

router = APIRouter(prefix="/api")


def me_out(db: Session, user: User) -> dict:
    return {
        "id": str(user.id), "email": user.email, "name": user.name, "onboarded": user.onboarded,
        "goal": user.goal, "level_default": user.level_default, "daily_minutes": user.daily_minutes,
        "target_recall": user.target_recall, "reminders": user.reminders, "is_admin": user.is_admin,
        "notify_prefs": {"ready": True, "product": True, **(user.notify_prefs or {})},
        "usage": usage_summary(db, user),
    }


@router.get("/me")
def get_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = me_out(db, user)
    db.commit()
    return out


class Prefs(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    goal: str | None = Field(default=None, max_length=40)
    level_default: str | None = Field(default=None, pattern="^(simple|standard|exam)$")
    daily_minutes: int | None = Field(default=None, ge=5, le=720)  # up to 12 h for intensive study
    target_recall: float | None = Field(default=None, ge=0.7, le=0.97)
    reminders: bool | None = None
    notify_prefs: dict[Literal["ready", "product"], bool] | None = None
    onboarded: bool | None = None


@router.patch("/me")
def update_me(body: Prefs, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    if data.get("level_default") == "exam" and not (user.limits_exempt or user.plan.limits.get("exam")):
        raise HTTPException(402, {"code": "exam_requires_pro", "message": "Exam-level explanations need Pro."})
    if "notify_prefs" in data:
        data["notify_prefs"] = {**(user.notify_prefs or {}), **data["notify_prefs"]}
    if data.get("onboarded") and not user.onboarded:
        telemetry.event("onboarding_completed", user_id=user.id, goal=data.get("goal"), level=data.get("level_default"),
                        daily_minutes=data.get("daily_minutes"))
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return me_out(db, user)


@router.delete("/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    for book in db.query(Book).filter_by(user_id=user.id):
        n = db.query(func.count(Chunk.id)).filter(Chunk.book_id == book.id).scalar()
        try:
            vectors.delete_book(str(book.id), n)
            delete_object(book.s3_key)
        except Exception:
            pass
        drop_local(book.id)
    sub = user.cognito_sub
    db.delete(user)
    db.commit()
    try:
        cognito().admin_delete_user(UserPoolId=settings.user_pool_id, Username=sub)
    except cognito().exceptions.UserNotFoundException:
        pass
    return {"ok": True}


@router.get("/me/export")
def export_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    books = db.query(Book).filter_by(user_id=user.id).all()
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {k: v for k, v in me_out(db, user).items() if k != "usage"},
        "books": [{"title": b.title, "pages": b.pages, "chapters": [
            {"n": c.n, "title": c.title, "pdf_start": c.pdf_start, "pdf_end": c.pdf_end} for c in b.chapters]}
            for b in books],
        "notes": [{"book_id": str(n.book_id), "page": n.pdf_page, "quote": n.quote, "text": n.text}
                  for n in db.query(Note).filter_by(user_id=user.id)],
        "cards": [{"front": c.front, "back": c.back, "due": c.due_at.isoformat()} for c in db.query(Card).filter_by(user_id=user.id)],
        "chat": [{"book_id": str(m.book_id), "role": m.role, "text": m.text, "at": m.created_at.isoformat()}
                 for m in db.query(ChatMessage).filter_by(user_id=user.id)],
    }
    return Response(content=json.dumps(data, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="lectern-export.json"'})


@router.get("/me/cards.csv")
def export_cards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["front", "back", "tags"])
    for c in db.query(Card).filter_by(user_id=user.id):
        w.writerow([c.front, c.back.replace("\n", "<br>"), (c.tag or "").replace(" ", "_")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="lectern-flashcards.csv"'})


# ---------------------------------------------------------------- notifications

@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return {"unread": sum(1 for n in rows if n.read_at is None), "items": [
        {"id": str(n.id), "type": n.type, "title": n.title, "body": n.body, "link": n.link,
         "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read_at.is_(None)) \
        .update({"read_at": datetime.now(timezone.utc)})
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- activity & progress

class PageView(BaseModel):
    path: str = Field(max_length=80, pattern=r"^/[\w/:.-]*$")


_last_view: dict[tuple, float] = {}


@router.post("/track")
def track(body: PageView, user: User = Depends(current_user)):
    """Which screen a learner opened, as a route pattern ("/books/:id/structure"), never its content."""
    import time
    key, now_s = (user.id, body.path), time.monotonic()
    if now_s - _last_view.get(key, 0) > 15:  # a re-render or quick back-and-forth isn't a new visit
        _last_view[key] = now_s
        telemetry.event("page_view", user_id=user.id, path=body.path)
    return {"ok": True}


class ClientEvent(BaseModel):
    type: Literal["upload_problem"]
    reason: str = Field(max_length=40)
    detail: dict = Field(default_factory=dict)
    agent: str = Field(default="", max_length=200)


@router.post("/client-event")
def client_event(body: ClientEvent, user: User = Depends(current_user)):
    """Problems only the browser sees (a file rejected before upload, a failed transfer to S3)."""
    detail = {k: (str(v)[:200] if not isinstance(v, (int, float, bool)) else v) for k, v in list(body.detail.items())[:8]}
    telemetry.event(body.type, user_id=user.id, reason=body.reason, agent=body.agent, **detail)
    return {"ok": True}


class Activity(BaseModel):
    book_id: str
    seconds: int = Field(ge=1, le=600)


@router.post("/activity")
def activity(body: Activity, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, body.book_id)
    today = datetime.now(timezone.utc).date()
    row = db.get(StudyDay, (user.id, book.id, today))
    if row is None:
        db.add(StudyDay(user_id=user.id, book_id=book.id, day=today, seconds=body.seconds))
    else:
        row.seconds += body.seconds
    db.commit()
    return {"ok": True}


def streak(db: Session, user: User) -> int:
    days = {d for (d,) in db.query(StudyDay.day).filter(StudyDay.user_id == user.id).distinct()}
    days |= {r.date() for (r,) in db.query(Review.reviewed_at).filter(Review.user_id == user.id)}
    today = datetime.now(timezone.utc).date()
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


@router.get("/progress")
def progress(days: int = 14, user: User = Depends(current_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).date() - timedelta(days=days - 1) if days < 10000 else date(2000, 1, 1)
    per_day = dict(db.query(StudyDay.day, func.sum(StudyDay.seconds)).filter(
        StudyDay.user_id == user.id, StudyDay.day >= since).group_by(StudyDay.day).all())
    series = []
    if days < 10000:
        for i in range(days):
            d = since + timedelta(days=i)
            series.append({"day": d.isoformat(), "minutes": round((per_day.get(d) or 0) / 60)})
    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    reviewed = db.query(func.count(Review.id)).filter(Review.user_id == user.id, Review.reviewed_at >= since_dt).scalar()
    scores = [a.score for a in db.query(Attempt).filter(Attempt.user_id == user.id, Attempt.created_at >= since_dt)]
    by_book = []
    for b in db.query(Book).filter_by(user_id=user.id):
        learnable = [c for c in b.chapters if c.kind in ("chapter", "appendix")]
        prog = {p.chapter_id: p for p in db.query(Progress).filter(
            Progress.user_id == user.id, Progress.chapter_id.in_([c.id for c in learnable]))} if learnable else {}
        quiz_scores = [p.quiz_best for p in prog.values() if p.quiz_best is not None]
        secs = db.query(func.coalesce(func.sum(StudyDay.seconds), 0)).filter(
            StudyDay.user_id == user.id, StudyDay.book_id == b.id).scalar()
        by_book.append({"id": str(b.id), "title": b.title, "chapters_total": len(learnable),
                        "chapters_mastered": sum(1 for p in prog.values() if p.mastered),
                        "quiz_avg": round(100 * sum(quiz_scores) / len(quiz_scores)) if quiz_scores else None,
                        "minutes": round(secs / 60)})
    weak = db.execute(text(
        """SELECT c.chapter_id, count(*) AS n FROM cards c WHERE c.user_id = :u AND c.chapter_id IS NOT NULL
           AND (c.lapses > 0 OR c.source = 'missed_question') GROUP BY c.chapter_id ORDER BY n DESC LIMIT 5"""),
        {"u": user.id}).fetchall()
    attention = []
    for chapter_id, n in weak:
        ch = db.get(Chapter, chapter_id)
        if ch:
            b = db.get(Book, ch.book_id)
            attention.append({"chapter_id": str(ch.id), "title": ch.title, "book": b.title, "chapter_n": ch.n,
                              "chapter_label": chapter_label(db, ch), "book_id": str(b.id), "cards": n})
    return {
        "minutes_total": round(sum(per_day.values() or [0]) / 60) if per_day else 0,
        "streak": streak(db, user), "cards_reviewed": reviewed,
        "quiz_avg": round(100 * sum(scores) / len(scores)) if scores else None,
        "goal_minutes": user.daily_minutes, "series": series, "by_book": by_book, "attention": attention,
    }


# ---------------------------------------------------------------- search

@router.get("/search")
def search(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = q.strip()[:200]
    if len(q) < 2:
        return {"books": [], "passages": [], "notes": [], "cards": []}
    like = f"%{q}%"
    books = db.query(Book).filter(Book.user_id == user.id, Book.title.ilike(like)).limit(5).all()
    passages = db.execute(text(
        """SELECT ch.book_id, ch.pdf_page, ts_headline('english', ch.text, websearch_to_tsquery('english', :q),
                  'MaxFragments=1,MaxWords=30,MinWords=12,StartSel=<mark>,StopSel=</mark>') AS snippet
           FROM chunks ch JOIN books b ON b.id = ch.book_id
           WHERE b.user_id = :u AND ch.tsv @@ websearch_to_tsquery('english', :q)
           ORDER BY ts_rank(ch.tsv, websearch_to_tsquery('english', :q)) DESC LIMIT 12"""),
        {"q": q, "u": user.id}).fetchall()
    titles = {b.id: b.title for b in db.query(Book).filter_by(user_id=user.id)}
    notes = db.query(Note).filter(Note.user_id == user.id, (Note.text.ilike(like)) | (Note.quote.ilike(like))).limit(8).all()
    cards = db.query(Card).filter(Card.user_id == user.id, (Card.front.ilike(like)) | (Card.back.ilike(like))).limit(8).all()
    return {
        "books": [{"id": str(b.id), "title": b.title} for b in books],
        "passages": [{"book_id": str(r.book_id), "book": titles.get(r.book_id), "pdf_page": r.pdf_page,
                      "page_label": label_for(db, r.book_id, r.pdf_page), "snippet": r.snippet} for r in passages],
        "notes": [{"id": str(n.id), "book_id": str(n.book_id), "book": titles.get(n.book_id), "text": n.text,
                   "quote": n.quote, "pdf_page": n.pdf_page} for n in notes],
        "cards": [{"id": str(c.id), "front": c.front, "back": c.back[:200], "book": titles.get(c.book_id)} for c in cards],
    }
