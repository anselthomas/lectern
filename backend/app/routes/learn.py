import concurrent.futures as cf
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import content, jobs, llm, srs, telemetry, vectors
from ..auth import current_user
from ..db import get_db
from ..limits import check_feature, check_tutor, record_tokens
from ..models import (
    Attempt, Book, Card, Chapter, ChatMessage, Chunk, Job, Lesson, Page, Progress, Quiz, Review, Section, User,
)
from .common import label_for, own_book, own_chapter, own_section, parse_id, progress_row

router = APIRouter(prefix="/api")
LEVELS = ("simple", "standard", "exam")


def queue_build(db: Session, ch: Chapter, level: str) -> None:
    if ch.status in ("pending", "failed"):
        ch.status, ch.status_detail = "queued", None
        jobs.enqueue(db, "build_chapter", chapter_id=ch.id, level=level)


def next_chapter(book: Book, ch: Chapter) -> Chapter | None:
    return next((c for c in book.chapters if c.n > ch.n and c.kind in ("chapter", "appendix")), None)


# ---------------------------------------------------------------- chapter map

@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch, book = own_chapter(db, user, chapter_id)
    queue_build(db, ch, user.level_default)
    nxt = next_chapter(book, ch)
    if ch.status == "ready" and nxt:
        queue_build(db, nxt, user.level_default)  # pre-build so the next chapter is ready when they get there
    p = db.get(Progress, (user.id, ch.id))
    done = set(p.sections_done if p else [])
    quiz = db.query(Quiz).filter_by(chapter_id=ch.id, kind="chapter").first()
    due_cards = (db.query(Card).filter(Card.user_id == user.id, Card.chapter_id == ch.id,
                                       Card.due_at <= datetime.now(timezone.utc)).count())
    db.commit()
    sections = [{"id": str(s.id), "n": s.n, "title": s.title, "summary": s.summary,
                 "pages_label": f"{label_for(db, book.id, s.pdf_start)}–{label_for(db, book.id, s.pdf_end)}",
                 "done": str(s.id) in done} for s in ch.sections]
    resume = next((s for s in sections if not s["done"]), None)
    return {
        "id": str(ch.id), "n": ch.n, "title": ch.title, "kind": ch.kind, "status": ch.status,
        "status_detail": ch.status_detail, "book": {"id": str(book.id), "title": book.title},
        "pages_label": f"{label_for(db, book.id, ch.pdf_start)}–{label_for(db, book.id, ch.pdf_end)}",
        "map": ch.map, "sections": sections, "resume": resume,
        "progress": {"prequestion": p.prequestion if p else None, "explain": p.explain if p else None,
                     "quiz_best": p.quiz_best if p else None, "mastered": bool(p and p.mastered),
                     "sections_done": len(done)},
        "quiz": {"id": str(quiz.id), "count": len(quiz.questions)} if quiz else None,
        "due_cards": due_cards,
        "next_chapter": {"id": str(nxt.id), "n": nxt.n, "title": nxt.title, "status": nxt.status} if nxt else None,
    }


@router.post("/chapters/{chapter_id}/build")
def rebuild(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch, _ = own_chapter(db, user, chapter_id)
    if ch.status in ("queued", "building"):
        return {"status": ch.status}
    ch.status = "failed" if ch.status == "ready" else ch.status
    queue_build(db, ch, user.level_default)
    db.commit()
    return {"status": ch.status}


class PreQ(BaseModel):
    rating: str = Field(pattern="^(new|some|confident)$")
    answer: str = Field(default="", max_length=2000)


@router.post("/chapters/{chapter_id}/prequestion")
def prequestion(chapter_id: str, body: PreQ, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch, _ = own_chapter(db, user, chapter_id)
    if ch.status != "ready":
        raise HTTPException(409, "Chapter is still being prepared")
    with telemetry.scope(user_id=user.id, book_id=ch.book_id, chapter_id=ch.id, feature="prequestion"):
        data, usage = content.prequestion_plan(ch, body.rating, body.answer, user.level_default)
    telemetry.event("chapter_started", user_id=user.id, book_id=ch.book_id, chapter_id=ch.id, rating=body.rating,
                    suggested_level=data.get("level"))
    if data.get("level") == "exam" and not (user.limits_exempt or user.plan.limits.get("exam")):
        data["level"] = "standard"
    p = progress_row(db, user, ch)
    p.prequestion = {"rating": body.rating, "answer": body.answer, **data}
    record_tokens(db, user, usage.tokens_in, usage.tokens_out)
    db.commit()
    return p.prequestion


# ---------------------------------------------------------------- lessons

def lesson_out(db: Session, book_id, body: dict) -> dict:
    labels = body.get("labels", {})

    def lab(p):
        return labels.get(str(p)) or label_for(db, book_id, p) if p else None
    return {
        "minutes": body.get("minutes"),
        "blocks": [{**b, "page_label": lab(b.get("page"))} for b in content.highlight_blocks(body.get("blocks", []))],
        "quick_checks": [{**q, "page_label": lab(q.get("page"))} for q in body.get("quick_checks", [])],
    }


def lesson_job_pending(db: Session, section_id, level) -> bool:
    return db.query(Job).filter(Job.type == "build_lesson", Job.status.in_(("pending", "running")),
                                Job.payload["section_id"].astext == str(section_id),
                                Job.payload["level"].astext == level).count() > 0


@router.get("/sections/{section_id}")
def get_section(section_id: str, level: str | None = None, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    sec, ch, book = own_section(db, user, section_id)
    level = level or user.level_default
    if level not in LEVELS:
        raise HTTPException(400, "Unknown level")
    if level == "exam":
        check_feature(user, "exam")
    lesson = db.query(Lesson).filter_by(section_id=sec.id, level=level).first()
    status = "ready"
    if lesson is None:
        status = "building"
        # While the chapter itself is building, its lessons are on the way; don't queue duplicates.
        if ch.status not in ("queued", "building") and not lesson_job_pending(db, sec.id, level):
            jobs.enqueue(db, "build_lesson", section_id=sec.id, level=level)
            db.commit()
    p = db.get(Progress, (user.id, ch.id))
    done = set(p.sections_done if p else [])
    secs = list(ch.sections)
    i = next(k for k, s in enumerate(secs) if s.id == sec.id)
    return {
        "id": str(sec.id), "n": sec.n, "title": sec.title, "level": level, "status": status,
        "pages_label": f"{label_for(db, book.id, sec.pdf_start)}–{label_for(db, book.id, sec.pdf_end)}",
        "pdf_start": sec.pdf_start, "pdf_end": sec.pdf_end,
        "book": {"id": str(book.id), "title": book.title},
        "chapter": {"id": str(ch.id), "n": ch.n, "title": ch.title,
                    "sections": [{"id": str(s.id), "n": s.n, "title": s.title, "done": str(s.id) in done} for s in secs]},
        "prev": {"id": str(secs[i - 1].id), "n": secs[i - 1].n, "title": secs[i - 1].title} if i > 0 else None,
        "next": {"id": str(secs[i + 1].id), "n": secs[i + 1].n, "title": secs[i + 1].title} if i + 1 < len(secs) else None,
        "done": str(sec.id) in done,
        "lesson": lesson_out(db, book.id, lesson.body) if lesson else None,
    }


@router.post("/sections/{section_id}/complete")
def complete_section(section_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sec, ch, book = own_section(db, user, section_id)
    p = progress_row(db, user, ch)
    if str(sec.id) not in p.sections_done:
        p.sections_done = [*p.sections_done, str(sec.id)]
        # Key terms from this section become flashcards.
        lesson = (db.query(Lesson).filter_by(section_id=sec.id, level=user.level_default).first()
                  or db.query(Lesson).filter_by(section_id=sec.id).first())
        existing = {c.front for c in db.query(Card).filter_by(user_id=user.id, chapter_id=ch.id)}
        for b in (lesson.body.get("blocks", []) if lesson else []):
            if b.get("type") == "key_term" and b.get("term") and b["term"] not in existing:
                db.add(Card(user_id=user.id, book_id=book.id, chapter_id=ch.id, front=b["term"], back=content.HIGHLIGHT.sub(r"\1", b["text"]),
                            pdf_page=b.get("page"), tag=f"{ch.n}.{sec.n} {sec.title}"[:80], source="key_term",
                            fsrs=srs.new_state()))
    db.commit()
    telemetry.event("section_completed", user_id=user.id, book_id=book.id, chapter_id=ch.id, section=f"{ch.n}.{sec.n}",
                    title=sec.title)
    return {"sections_done": len(p.sections_done), "sections_total": len(ch.sections)}


# ---------------------------------------------------------------- explain it back

class Explain(BaseModel):
    text: str = Field(min_length=10, max_length=3000)


@router.post("/chapters/{chapter_id}/explain")
def explain_back(chapter_id: str, body: Explain, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch, book = own_chapter(db, user, chapter_id)
    if ch.status != "ready":
        raise HTTPException(409, "Chapter is still being prepared")
    with telemetry.scope(user_id=user.id, book_id=book.id, chapter_id=ch.id, feature="explain"):
        data, usage = content.grade_explanation(db, ch, body.text)
    telemetry.event("explain_submitted", user_id=user.id, book_id=book.id, chapter_id=ch.id, met=data.get("met"),
                    total=data.get("total"), verdict=data.get("verdict"), words=len(body.text.split()))
    data["page_label"] = label_for(db, book.id, data.get("page"))
    p = progress_row(db, user, ch)
    p.explain = {"text": body.text, **data}
    record_tokens(db, user, usage.tokens_in, usage.tokens_out)
    db.commit()
    return {**data, "prompt": (ch.map or {}).get("explain", {}).get("prompt")}


# ---------------------------------------------------------------- quizzes

def public_question(q: dict) -> dict:
    return {k: v for k, v in q.items() if k not in ("answer_index", "model_answer", "explanation")}


def own_quiz(db: Session, user: User, quiz_id: str) -> tuple[Quiz, Book]:
    quiz = db.get(Quiz, parse_id(quiz_id))
    if quiz is None:
        raise HTTPException(404, "Quiz not found")
    book = own_book(db, user, str(quiz.book_id))
    if quiz.kind == "final" and quiz.user_id != user.id:
        raise HTTPException(404, "Quiz not found")
    return quiz, book


@router.get("/chapters/{chapter_id}/quiz")
def get_quiz(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch, book = own_chapter(db, user, chapter_id)
    quiz = db.query(Quiz).filter_by(chapter_id=ch.id, kind="chapter").first()
    if quiz is None:
        raise HTTPException(409, "The quiz is still being prepared")
    titles = {s.n: s.title for s in ch.sections}
    return {"id": str(quiz.id), "chapter": {"id": str(ch.id), "n": ch.n, "title": ch.title},
            "book": {"id": str(book.id), "title": book.title},
            "questions": [{**public_question(q), "section_title": titles.get(q.get("section_n"))} for q in quiz.questions]}


def grade_one(q: dict, answer) -> tuple[dict, llm.Usage]:
    if q["type"] == "mcq":
        try:
            correct = int(answer) == int(q["answer_index"])
        except (TypeError, ValueError):
            correct = False
        right = q["options"][q["answer_index"]]
        return {"correct": correct, "feedback": q["explanation"],
                "correct_answer": right}, llm.Usage()
    if not answer or not str(answer).strip():
        return {"correct": False, "feedback": "No answer given.", "correct_answer": q["model_answer"]}, llm.Usage()
    data, usage = content.grade_short_answer(q["question"], q["model_answer"], str(answer)[:2000])
    return {"correct": bool(data["correct"]), "feedback": data["feedback"], "correct_answer": q["model_answer"]}, usage


class Check(BaseModel):
    question_id: str
    answer: str | int | None = None


@router.post("/quizzes/{quiz_id}/check")
def check_answer(quiz_id: str, body: Check, user: User = Depends(current_user), db: Session = Depends(get_db)):
    quiz, book = own_quiz(db, user, quiz_id)
    q = next((q for q in quiz.questions if q["id"] == body.question_id), None)
    if q is None:
        raise HTTPException(404, "Question not found")
    with telemetry.scope(user_id=user.id, book_id=book.id, chapter_id=quiz.chapter_id, feature="quiz_grading"):
        result, usage = grade_one(q, body.answer)
    record_tokens(db, user, usage.tokens_in, usage.tokens_out)
    db.commit()
    return {**result, "explanation": q["explanation"], "page": q.get("page"),
            "page_label": label_for(db, book.id, q.get("page"))}


class Submit(BaseModel):
    answers: dict[str, str | int | None]


@router.post("/quizzes/{quiz_id}/submit")
def submit_quiz(quiz_id: str, body: Submit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    quiz, book = own_quiz(db, user, quiz_id)
    scope = dict(user_id=user.id, book_id=book.id, chapter_id=quiz.chapter_id, feature="quiz_grading")

    def grade_in_scope(q):
        with telemetry.scope(**scope):
            return grade_one(q, body.answers.get(q["id"]))
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        graded = list(pool.map(grade_in_scope, quiz.questions))
    results, usage = [], llm.Usage()
    for q, (r, u) in zip(quiz.questions, graded):
        usage.add(u)
        results.append({"id": q["id"], "correct": r["correct"], "feedback": r["feedback"],
                        "correct_answer": q["options"][q["answer_index"]] if q["type"] == "mcq" else q.get("model_answer"),
                        "explanation": q.get("explanation"),
                        "section_n": q.get("section_n"), "chapter_n": q.get("chapter_n"), "page": q.get("page"),
                        "page_label": label_for(db, book.id, q.get("page")) if q.get("page") else None})
    score = sum(r["correct"] for r in results) / max(1, len(results))
    db.add(Attempt(user_id=user.id, quiz_id=quiz.id, answers=[body.answers], results=results, score=score))
    record_tokens(db, user, usage.tokens_in, usage.tokens_out)

    # Missed questions become flashcards due tomorrow-ish (FSRS decides).
    chapters = {c.n: c for c in book.chapters}
    new_cards = 0
    for q, r in zip(quiz.questions, results):
        if r["correct"]:
            continue
        ch = db.get(Chapter, quiz.chapter_id) if quiz.chapter_id else chapters.get(q.get("chapter_n"))
        if db.query(Card).filter_by(user_id=user.id, book_id=book.id, front=q["question"]).first():
            continue
        back = q["options"][q["answer_index"]] if q["type"] == "mcq" else q["model_answer"]
        db.add(Card(user_id=user.id, book_id=book.id, chapter_id=ch.id if ch else None, front=q["question"],
                    back=f"{back}\n\n{q['explanation']}", pdf_page=q.get("page"), source="missed_question",
                    tag=(f"Ch. {ch.n}" if ch else None), fsrs=srs.new_state()))
        new_cards += 1

    out = {"score": score, "correct": sum(r["correct"] for r in results), "total": len(results),
           "results": results, "new_cards": new_cards}
    if quiz.kind == "chapter":
        ch = db.get(Chapter, quiz.chapter_id)
        p = progress_row(db, user, ch)
        p.quiz_best = max(score, p.quiz_best or 0)
        p.mastered = p.mastered or score >= 0.7
        titles = {s.n: s.title for s in ch.sections}
        groups = {}
        for r in results:
            g = groups.setdefault(r["section_n"], {"section_n": r["section_n"], "title": titles.get(r["section_n"], ""),
                                                   "correct": 0, "total": 0})
            g["total"] += 1
            g["correct"] += r["correct"]
        out.update(mastered=p.mastered, by_section=sorted(groups.values(), key=lambda g: g["section_n"] or 0))
        nxt = next_chapter(book, ch)
        out["next_chapter"] = {"id": str(nxt.id), "n": nxt.n, "title": nxt.title} if nxt else None
    else:
        groups = {}
        for r in results:
            g = groups.setdefault(r["chapter_n"], {"chapter_n": r["chapter_n"], "title": chapters[r["chapter_n"]].title
                                                   if r["chapter_n"] in chapters else "", "correct": 0, "total": 0})
            g["total"] += 1
            g["correct"] += r["correct"]
        out.update(passed=score >= 0.75, by_chapter=sorted(groups.values(), key=lambda g: g["chapter_n"] or 0))
    db.commit()
    telemetry.event("quiz_submitted" if quiz.kind == "chapter" else "final_test_submitted", user_id=user.id,
                    book_id=book.id, chapter_id=quiz.chapter_id, score=round(score, 3), correct=out["correct"],
                    total=out["total"], new_cards=new_cards)
    return out


@router.get("/books/{book_id}/final")
def final_status(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    learnable = [c for c in book.chapters if c.kind in ("chapter", "appendix")]
    done = [c for c in learnable if (p := db.get(Progress, (user.id, c.id))) and p.mastered]
    built = [c for c in learnable if c.status == "ready"]
    eligible = len(done) == len(learnable) or (user.limits_exempt and built)
    attempts = (db.query(Attempt).join(Quiz, Quiz.id == Attempt.quiz_id)
                .filter(Quiz.book_id == book.id, Quiz.kind == "final", Attempt.user_id == user.id)
                .order_by(Attempt.created_at.desc()).all())
    return {"eligible": bool(eligible), "chapters_done": len(done), "chapters_total": len(learnable),
            "requires_pro": not (user.limits_exempt or user.plan.limits.get("final_test")),
            "best": max((a.score for a in attempts), default=None), "attempts": len(attempts),
            "note": None if len(done) == len(learnable) else
            "Internal test account: final test unlocked early using the chapters built so far." if eligible else None}


@router.post("/books/{book_id}/final/start")
def final_start(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    check_feature(user, "final_test")
    status = final_status(book_id, user, db)
    if not status["eligible"]:
        raise HTTPException(409, "Finish every chapter to unlock the final test")
    pools = []
    for c in book.chapters:
        quiz = db.query(Quiz).filter_by(chapter_id=c.id, kind="chapter").first()
        if quiz:
            p = db.get(Progress, (user.id, c.id))
            pools.append((c, quiz.questions, p.quiz_best if p else None))
    questions = content.final_test_questions(pools)
    if not questions:
        raise HTTPException(409, "No chapter quizzes yet")
    quiz = Quiz(book_id=book.id, kind="final", user_id=user.id, questions=questions)
    db.add(quiz)
    db.commit()
    return {"id": str(quiz.id), "minutes": max(10, round(len(questions) * 1.5)), "pass_mark": 0.75,
            "questions": [public_question(q) for q in questions]}


# ---------------------------------------------------------------- tutor

class Ask(BaseModel):
    book_id: str
    chapter_id: str | None = None
    section_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    level: str | None = None


def retrieve(db: Session, user: User, book: Book, question: str, chapter: Chapter | None, k: int = 6):
    scores: dict[int, float] = {}
    try:
        hits = vectors.query(llm.embed(question), user_id=str(user.id), book_id=str(book.id), top_k=12)
        for rank, h in enumerate(hits):
            n = int(h["key"].split(":")[1])
            scores[n] = scores.get(n, 0) + 1 / (60 + rank)
    except Exception:
        pass  # embeddings may still be running; full-text search still works
    # OR the question's stemmed terms: a natural question ("what does the book say about X") rarely has
    # every word on one page. ts_rank still favours chunks that match more of them.
    fts = db.execute(text(
        "WITH q AS (SELECT to_tsquery('english', replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')) AS t) "
        "SELECT n FROM chunks, q WHERE book_id = :b AND q.t IS NOT NULL AND tsv @@ q.t "
        "ORDER BY ts_rank_cd(tsv, q.t) DESC LIMIT 12"),
        {"b": book.id, "q": question}).fetchall()
    for rank, (n,) in enumerate(fts):
        scores[n] = scores.get(n, 0) + 1 / (60 + rank)
    if not scores:
        return []
    rows = {c.n: c for c in db.query(Chunk).filter(Chunk.book_id == book.id, Chunk.n.in_(list(scores)))}
    if chapter:
        for n, c in rows.items():
            if chapter.pdf_start <= c.pdf_page <= chapter.pdf_end:
                scores[n] += 0.004
    best = sorted(rows, key=lambda n: -scores[n])[:k]
    return [{"pdf_page": rows[n].pdf_page, "label": label_for(db, book.id, rows[n].pdf_page), "text": rows[n].text}
            for n in sorted(best, key=lambda n: rows[n].pdf_page)]


@router.post("/tutor")
def ask_tutor(body: Ask, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, body.book_id)
    chapter = own_chapter(db, user, body.chapter_id)[0] if body.chapter_id else None
    section = own_section(db, user, body.section_id)[0] if body.section_id else None
    if section and (not chapter or section.chapter_id != chapter.id):
        chapter = db.get(Chapter, section.chapter_id)
    usage_row = check_tutor(db, user)
    level = body.level if body.level in LEVELS else user.level_default
    history = [{"role": m.role, "text": m.text} for m in
               db.query(ChatMessage).filter_by(user_id=user.id, book_id=book.id)
               .order_by(ChatMessage.id.desc()).limit(6)][::-1]
    with telemetry.scope(user_id=user.id, book_id=book.id, chapter_id=chapter.id if chapter else None, feature="tutor"):
        data, usage = _tutor_reply(db, user, book, chapter, section, history, body.message, level)
    citations = [{"pdf_page": p, "label": label_for(db, book.id, p)} for p in data.get("citations", [])]
    quiz = data.get("quiz")
    if quiz:
        quiz["page_label"] = label_for(db, book.id, quiz.get("page"))
    # History keeps the quiz question as text so the next turn has the context.
    stored = data["answer"] + (f"\n\nQuiz: {quiz['question']} Options: " + " / ".join(quiz["options"]) if quiz else "")
    db.add(ChatMessage(user_id=user.id, book_id=book.id, role="user", text=body.message))
    db.add(ChatMessage(user_id=user.id, book_id=book.id, role="assistant", text=stored, citations=citations))
    telemetry.event("tutor_message", user_id=user.id, book_id=book.id, chapter_id=chapter.id if chapter else None,
                    in_book=data.get("in_book", True), quiz=bool(quiz), chars=len(body.message),
                    citations=len(citations))
    usage_row.tutor_messages += 1
    record_tokens(db, user, usage.tokens_in, usage.tokens_out)
    db.commit()
    return {"answer": data["answer"], "citations": citations, "in_book": data.get("in_book", True),
            "follow_ups": data.get("follow_ups", []), "quiz": quiz}


def _tutor_reply(db: Session, user: User, book: Book, chapter: Chapter | None, section: Section | None,
                 history: list[dict], message: str, level: str) -> tuple[dict, llm.Usage]:
    excerpts = retrieve(db, user, book, message, chapter)
    if section:
        # "This section" questions need the open section in view, whatever the search returned.
        have = {e["pdf_page"] for e in excerpts}
        own = (db.query(Chunk).filter(Chunk.book_id == book.id, Chunk.pdf_page >= section.pdf_start,
                                      Chunk.pdf_page <= section.pdf_end).order_by(Chunk.n).limit(4).all())
        excerpts = sorted(excerpts + [{"pdf_page": c.pdf_page, "label": label_for(db, book.id, c.pdf_page), "text": c.text}
                                      for c in own if c.pdf_page not in have], key=lambda e: e["pdf_page"])
    if not excerpts:
        data = {"answer": "I couldn't find anything about that in this book yet. If the book was just uploaded, "
                          "search is still being prepared — try again in a minute.", "citations": [], "in_book": False}
        usage = llm.Usage()
    else:
        where = None
        if section:
            where = (f"section {chapter.n}.{section.n} \"{section.title}\" (pages n={section.pdf_start}..{section.pdf_end}) "
                     f"of chapter {chapter.n} \"{chapter.title}\"")
        elif chapter:
            where = f"chapter {chapter.n} \"{chapter.title}\""
        data, usage = content.tutor_answer(book, excerpts, history, message, where, level)
    return data, usage


@router.get("/tutor/{book_id}/history")
def tutor_history(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    msgs = (db.query(ChatMessage).filter_by(user_id=user.id, book_id=book.id)
            .order_by(ChatMessage.id.desc()).limit(30).all())[::-1]
    return [{"role": m.role, "text": m.text, "citations": m.citations} for m in msgs]


# ---------------------------------------------------------------- flashcard review

@router.get("/review/due")
def review_due(book_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Card).filter(Card.user_id == user.id, Card.due_at <= datetime.now(timezone.utc))
    if book_id:
        q = q.filter(Card.book_id == own_book(db, user, book_id).id)
    cards = q.order_by(Card.due_at).limit(50).all()
    titles = {b.id: b.title for b in db.query(Book).filter(Book.user_id == user.id)}
    total_cards = db.query(Card).filter(Card.user_id == user.id).count()
    return {"total_cards": total_cards, "cards": [{
        "id": str(c.id), "front": c.front, "back": c.back, "tag": c.tag, "source": c.source,
        "book": {"id": str(c.book_id), "title": titles.get(c.book_id)},
        "page": c.pdf_page, "page_label": label_for(db, c.book_id, c.pdf_page),
        "intervals": srs.previews(c.fsrs, user.target_recall)} for c in cards]}


class Rate(BaseModel):
    rating: int = Field(ge=1, le=4)


@router.post("/review/{card_id}")
def review_card(card_id: str, body: Rate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    card = db.get(Card, parse_id(card_id))
    if card is None or card.user_id != user.id:
        raise HTTPException(404, "Card not found")
    card.fsrs, card.due_at = srs.review(card.fsrs, body.rating, user.target_recall)
    card.reps += 1
    card.lapses += 1 if body.rating == 1 else 0
    db.add(Review(card_id=card.id, user_id=user.id, rating=body.rating))
    db.commit()
    telemetry.event("card_reviewed", user_id=user.id, book_id=card.book_id, chapter_id=card.chapter_id,
                    rating=body.rating, source=card.source)
    return {"due_at": card.due_at.isoformat()}
