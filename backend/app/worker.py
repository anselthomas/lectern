"""Background worker: PDF ingest, embeddings, chapter builds. Run with `python -m app.worker`."""
import concurrent.futures as cf
import logging
import re
import signal
import threading
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import delete, insert, text
from sqlalchemy.exc import IntegrityError

from . import content, jobs, llm, migrations, pdf, structure, telemetry, vectors
from .db import SessionLocal, engine
from .limits import record_tokens
from .models import Base, Book, Chapter, Chunk, Lesson, Notification, Page, Section, User
from .storage import local_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lectern.worker")
stop = threading.Event()


NOTIFY_PREF = {"book_ready": "ready", "chapter_ready": "ready"}


def notify(db, user_id, type_, title, body="", link=None):
    """Add a notification. A rebuild or re-detect replaces the earlier one about the same thing instead of stacking up."""
    if (db.get(User, user_id).notify_prefs or {}).get(NOTIFY_PREF.get(type_, type_)) is False:
        return
    if link:
        db.query(Notification).filter_by(user_id=user_id, type=type_, link=link).delete()
    db.add(Notification(user_id=user_id, type=type_, title=title, body=body, link=link))


# ---------------------------------------------------------------- ingest

def book_exists(db, book_id) -> bool:
    return db.get(Book, book_id) is not None


def ingest_book(book_id: str) -> None:
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        if book is None:
            return  # deleted before we got to it
        user = db.get(User, book.user_id)
        book.status, book.status_detail = "processing", "Reading the PDF"
        db.commit()
        path = local_pdf(book)
        try:
            doc = pdf.open_pdf(path)
        except PermissionError:
            book.status, book.status_detail = "needs_password", "This PDF is password-protected."
            db.commit()
            return
        except Exception as e:  # corrupt or not a PDF
            book.status, book.status_detail = "failed", f"We couldn't open this file as a PDF ({e.__class__.__name__})."
            db.commit()
            return

        lim = user.plan.limits
        if not user.limits_exempt and lim.get("max_pages") and doc.page_count > lim["max_pages"]:
            book.status, book.status_detail = "failed", f"This PDF has {doc.page_count} pages; your plan allows {lim['max_pages']}."
            db.commit()
            return

        scanned = pdf.is_scanned(doc)
        book.kind = "scanned" if scanned else "text"
        if scanned and not (user.limits_exempt or lim.get("scanned")):
            book.status, book.status_detail = "failed", "scanned_requires_pro"
            db.commit()
            return

        book.pages = doc.page_count
        meta_title = ((doc.metadata or {}).get("title") or "").strip()
        if len(meta_title) > 3 and not pdf.junk_title(meta_title):
            book.title = meta_title[:300]
        elif pdf.junk_title(book.title):  # e.g. an earlier run stored "Prepage.pmd"
            book.title = pdf.title_from_filename(book.filename)
        db.commit()

        texts, labels = [], []
        db.execute(delete(Page).where(Page.book_id == book.id))
        batch = []
        for i in range(doc.page_count):
            page = doc[i]
            if i % 50 == 0:
                book.status_detail = f"{'Running OCR on' if scanned else 'Reading'} page {i + 1} of {doc.page_count}"
                db.commit()
            t = pdf.clean(pdf.page_text(page, ocr=scanned))
            label = page.get_label() or None
            texts.append(t)
            labels.append(label)
            batch.append({"book_id": book.id, "pdf_page": i + 1, "label": label, "text": t})
            if len(batch) >= 200:
                db.execute(insert(Page), batch)
                batch = []
        if batch:
            db.execute(insert(Page), batch)

        offset = pdf.detect_offset(labels, texts)
        book.page_offset = offset
        if offset is not None and not any(labels):
            # Fill printed labels from the detected offset so citations show book page numbers.
            for i in range(doc.page_count):
                p = i + 1 - offset
                if p >= 1:
                    db.query(Page).filter(Page.book_id == book.id, Page.pdf_page == i + 1).update({"label": str(p)})

        book.status_detail = "Finding the chapters"
        db.commit()
        with telemetry.scope(user_id=book.user_id, book_id=book.id, feature="ingest"):
            specs, source = structure.detect(doc, texts, offset)
        book.structure_source = source
        doc.close()

        db.query(Chapter).filter(Chapter.book_id == book.id).delete()
        if not specs:
            book.status, book.status_detail = "no_structure", "We couldn't find chapters in this PDF."
        else:
            for n, s in enumerate(specs, start=1):
                if s.title == structure.WHOLE_DOCUMENT:
                    s.title = book.title
                db.add(Chapter(book_id=book.id, n=n, title=s.title[:300], kind=s.kind, pdf_start=s.pdf_start,
                               pdf_end=s.pdf_end, outline_children=s.children, check_note=s.check_note))
            book.status, book.status_detail = "review", None
            notify(db, book.user_id, "book_ready", f"{book.title}: chapters found",
                   f"We found {sum(1 for s in specs if s.kind == 'chapter')} chapters. Check them to start.",
                   f"/books/{book.id}/structure")
        if book.embed_status != "done":  # a re-detect keeps the existing search index
            jobs.enqueue(db, "embed_book", book_id=book.id)
        db.commit()
        telemetry.event("book_processed", user_id=book.user_id, book_id=book.id, pages=book.pages, kind=book.kind,
                        structure=source, chapters=sum(1 for s in specs if s.kind == "chapter"), status=book.status)


# ---------------------------------------------------------------- embeddings

def embed_book(book_id: str) -> None:
    with SessionLocal() as db:
        # Atomic claim: duplicate jobs (e.g. released after a restart) find the book already running/done and stop.
        claimed = db.execute(text(
            "UPDATE books SET embed_status = 'running', embedded_chunks = 0 "
            "WHERE id = :id AND embed_status IN ('pending', 'failed') RETURNING id"), {"id": book_id}).first()
        db.commit()
        if not claimed:
            return
        book = db.get(Book, book_id)
        try:
            with telemetry.scope(user_id=book.user_id, book_id=book.id, feature="embed"):
                _embed(db, book)
        except Exception:
            db.rollback()
            db.execute(text("UPDATE books SET embed_status = 'failed' WHERE id = :id"), {"id": book_id})
            db.commit()
            raise


def _embed(db, book: Book) -> None:
    chapters = [(c.n, c.pdf_start, c.pdf_end) for c in db.query(Chapter).filter_by(book_id=book.id)]

    def chapter_of(p):
        for n, a, b in chapters:
            if a <= p <= b:
                return n
        return None

    rows = []
    for page in db.query(Page).filter_by(book_id=book.id).order_by(Page.pdf_page):
        for chunk in pdf.chunk_page(page.text):
            rows.append({"book_id": book.id, "n": len(rows), "chapter_n": chapter_of(page.pdf_page),
                         "pdf_page": page.pdf_page, "text": chunk})
    db.execute(delete(Chunk).where(Chunk.book_id == book.id))
    for i in range(0, len(rows), 500):
        db.execute(insert(Chunk), rows[i:i + 500])
    db.commit()

    done = 0
    counter = telemetry.EmbedCounter()
    started = telemetry.now()
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for i in range(0, len(rows), 200):
            batch = rows[i:i + 200]
            embs = list(pool.map(lambda r: llm.embed(r["text"], counter), batch))
            vectors.put([{"key": f"{book.id}:{r['n']}", "embedding": e, "user_id": str(book.user_id),
                          "book_id": str(book.id), "chapter_n": r["chapter_n"], "pdf_page": r["pdf_page"]}
                         for r, e in zip(batch, embs)])
            done += len(batch)
            if not book_exists(db, book.id):  # deleted mid-way; the delete already removed its vectors
                return
            book.embedded_chunks = done
            db.commit()
    telemetry.record_call(kind="embed", model=llm.settings.embed_model, calls=counter.calls, tokens_in=counter.tokens,
                          cost=telemetry.embed_cost(counter.tokens),
                          latency_ms=int((telemetry.now() - started).total_seconds() * 1000))
    book.embed_status = "done"
    db.commit()
    log.info("embedded %s chunks for %s", done, book.id)


# ---------------------------------------------------------------- chapter build

def build_chapter(chapter_id: str, level: str = "standard") -> None:
    with SessionLocal() as db:
        # Atomic claim: a second job for the same chapter (double click, retry, re-queue) finds it taken and stops.
        claimed = db.execute(text(
            "UPDATE chapters SET status = 'building', status_detail = NULL "
            "WHERE id = :id AND status IN ('queued', 'pending', 'failed') RETURNING id"), {"id": chapter_id}).first()
        db.commit()
        if not claimed:
            return
        ch = db.get(Chapter, chapter_id)
        book = db.get(Book, ch.book_id)
        user = db.get(User, book.user_id)
        try:
            with telemetry.scope(user_id=user.id, book_id=book.id, chapter_id=ch.id, feature="chapter_build"):
                usage = content.build_chapter(db, book, ch, level)
        except Exception as e:
            db.rollback()
            ch = db.get(Chapter, chapter_id)
            ch.status, ch.status_detail = "failed", str(e)[:500]
            db.commit()
            raise
        ch.status, ch.built_at = "ready", datetime.now(timezone.utc)
        record_tokens(db, user, usage.tokens_in, usage.tokens_out)
        notify(db, user.id, "chapter_ready", f"Chapter {ch.n} is ready", ch.title, f"/books/{book.id}?chapter={ch.id}")
        telemetry.event("chapter_built", user_id=user.id, book_id=book.id, chapter_id=ch.id, n=ch.n, title=ch.title,
                        level=level, sections=len(ch.sections), tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        db.commit()
        log.info("built chapter %s (%s in / %s out tokens)", ch.id, usage.tokens_in, usage.tokens_out)


def build_lesson(section_id: str, level: str) -> None:
    """A lesson at a level the chapter wasn't built at (the learner switched level). Interactive tier."""
    with SessionLocal() as db:
        sec = db.get(Section, section_id)
        if sec is None:
            return
        ch = db.get(Chapter, sec.chapter_id)
        book = db.get(Book, ch.book_id)
        if db.query(Lesson).filter_by(section_id=sec.id, level=level).first():
            return
        if ch.status in ("queued", "building"):
            return  # the chapter build is writing every lesson right now
        with telemetry.scope(user_id=book.user_id, book_id=book.id, chapter_id=ch.id, feature="lesson_level"):
            body, usage = content.generate_lesson(db, book, ch, sec, level, background=False)
        try:
            db.add(Lesson(section_id=sec.id, level=level, body=body, model=llm.settings.text_model))
            record_tokens(db, db.get(User, book.user_id), usage.tokens_in, usage.tokens_out)
            db.commit()
        except IntegrityError:
            db.rollback()  # section replaced by a rebuild, or another job saved this lesson first
            log.info("lesson for section %s/%s no longer needed", section_id, level)


# ---------------------------------------------------------------- reminders

def send_review_reminders() -> None:
    """At most one in-app "cards are due" reminder per learner a day, for those who left reminders on."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT c.user_id, count(*) FROM cards c JOIN users u ON u.id = c.user_id
            WHERE u.reminders AND c.due_at <= now()
              AND NOT EXISTS (SELECT 1 FROM notifications n WHERE n.user_id = c.user_id AND n.type = 'review_reminder'
                              AND n.created_at > now() - interval '20 hours')
            GROUP BY c.user_id""")).all()
        for user_id, n in rows:
            notify(db, user_id, "review_reminder", f"{n} flashcard{'s' if n != 1 else ''} due",
                   "A few minutes of review now keeps them from slipping.", "/review")
        db.commit()


HANDLERS = {"ingest_book": ingest_book, "embed_book": embed_book, "build_chapter": build_chapter,
            "build_lesson": build_lesson}


def loop(name: str) -> None:
    while not stop.is_set():
        with SessionLocal() as db:
            job = jobs.claim(db)
            if job is None:
                stop.wait(2)
                continue
            log.info("[%s] job %s %s %s", name, job.id, job.type, job.payload)
            try:
                HANDLERS[job.type](**job.payload)
                jobs.finish(db, job)
            except Exception:
                err = traceback.format_exc()
                log.error("[%s] job %s failed:\n%s", name, job.id, err)
                db.rollback()
                jobs.finish(db, db.get(type(job), job.id), err)


def main() -> None:
    Base.metadata.create_all(engine)
    migrations.run(engine)
    with SessionLocal() as db:
        jobs.release_stale(db, minutes=0)  # single worker process: anything "running" now was cut off by a restart
        db.execute(text("UPDATE books SET embed_status = 'pending' WHERE embed_status = 'running'"))
        db.execute(text("UPDATE chapters SET status = 'queued' WHERE status = 'building'"))
        db.commit()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = [threading.Thread(target=loop, args=(f"w{i}",), daemon=True) for i in range(3)]
    for t in threads:
        t.start()
    while not stop.is_set():
        try:
            send_review_reminders()
        except Exception:  # noqa: BLE001 - a missed reminder must not stop the worker
            log.exception("review reminders failed")
        stop.wait(600)


if __name__ == "__main__":
    main()
