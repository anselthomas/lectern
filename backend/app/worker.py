"""Background worker: PDF ingest, embeddings, chapter builds. Run with `python -m app.worker`."""
import concurrent.futures as cf
import logging
import re
import signal
import threading
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import delete, insert

from . import content, jobs, llm, pdf, vectors
from .db import SessionLocal, engine
from .limits import record_tokens
from .models import Base, Book, Chapter, Chunk, Lesson, Notification, Page, Section, User
from .storage import local_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lectern.worker")
stop = threading.Event()


def notify(db, user_id, type_, title, body="", link=None):
    db.add(Notification(user_id=user_id, type=type_, title=title, body=body, link=link))


# ---------------------------------------------------------------- ingest

CONTENTS_SCHEMA = {"type": "object", "required": ["chapters"], "properties": {"chapters": {
    "type": "array", "items": {"type": "object", "required": ["title", "printed_page"], "properties": {
        "title": {"type": "string"}, "printed_page": {"type": "integer"}}}}}}


def chapters_from_contents(texts: list[str], labels: list[str | None], offset: int | None) -> list[pdf.ChapterSpec]:
    """No bookmarks: ask the model to read the contents pages, then map printed pages to PDF pages."""
    front = "\n".join(f'<page n="{i + 1}">\n{t[:4000]}\n</page>' for i, t in enumerate(texts[:25]))
    data, _ = llm.call_json(
        system="You read a book's table of contents and list its top-level chapters.",
        prompt="List the top-level chapters (and appendices) from the contents page below with the printed page "
               "number where each starts. If there is no contents page, return an empty list.\n\n" + front,
        schema=CONTENTS_SCHEMA, tool_name="contents", max_tokens=2500, temperature=0)
    entries = [e for e in data.get("chapters", []) if e.get("printed_page")]
    if len(entries) < 2:
        return []
    n = len(texts)
    starts = []
    for e in entries:
        p = None
        if offset is not None:
            p = int(e["printed_page"]) + offset
        else:
            # Find the page whose first lines contain the title, after the contents pages.
            key = re.sub(r"\W+", " ", e["title"]).strip().lower()[:40]
            for i in range(10, n):
                head = re.sub(r"\W+", " ", " ".join(texts[i].splitlines()[:6])).lower()
                if key and key in head:
                    p = i + 1
                    break
        if p and 1 <= p <= n:
            starts.append((p, e["title"]))
    starts = sorted({p: t for p, t in starts}.items())
    specs = []
    for j, (p, title) in enumerate(starts):
        end = starts[j + 1][0] - 1 if j + 1 < len(starts) else n
        specs.append(pdf.ChapterSpec(title=title, pdf_start=p, pdf_end=max(p, end), kind=pdf.kind_for(title)))
    return specs


def ingest_book(book_id: str) -> None:
    with SessionLocal() as db:
        book = db.get(Book, book_id)
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
        meta_title = (doc.metadata or {}).get("title") or ""
        if meta_title.strip() and len(meta_title) > 3 and not meta_title.lower().endswith(".pdf"):
            book.title = meta_title.strip()[:300]
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

        specs = pdf.chapters_from_outline(doc)
        book.structure_source = "bookmarks" if specs else None
        if not specs:
            book.status_detail = "Reading the contents page"
            db.commit()
            specs = chapters_from_contents(texts, labels, offset)
            book.structure_source = "contents" if specs else None
        doc.close()

        db.query(Chapter).filter(Chapter.book_id == book.id).delete()
        if not specs:
            book.status, book.status_detail = "no_structure", "We couldn't find chapters in this PDF."
        else:
            for n, s in enumerate(specs, start=1):
                db.add(Chapter(book_id=book.id, n=n, title=s.title[:300], kind=s.kind, pdf_start=s.pdf_start,
                               pdf_end=s.pdf_end, outline_children=s.children, check_note=s.check_note))
            book.status, book.status_detail = "review", None
            notify(db, book.user_id, "book_ready", f"{book.title}: chapters found",
                   f"We found {sum(1 for s in specs if s.kind == 'chapter')} chapters. Check them to start.",
                   f"/books/{book.id}/structure")
        jobs.enqueue(db, "embed_book", book_id=book.id)
        db.commit()


# ---------------------------------------------------------------- embeddings

def embed_book(book_id: str) -> None:
    with SessionLocal() as db:
        book = db.get(Book, book_id)
        book.embed_status, book.embedded_chunks = "running", 0
        db.commit()
        chapters = [(c.n, c.pdf_start, c.pdf_end) for c in db.query(Chapter).filter_by(book_id=book.id)]

        def chapter_of(p):
            for n, a, b in chapters:
                if a <= p <= b:
                    return n
            return None

        rows = []
        for page in db.query(Page).filter_by(book_id=book.id).order_by(Page.pdf_page):
            for text in pdf.chunk_page(page.text):
                rows.append({"book_id": book.id, "n": len(rows), "chapter_n": chapter_of(page.pdf_page),
                             "pdf_page": page.pdf_page, "text": text})
        db.execute(delete(Chunk).where(Chunk.book_id == book.id))
        for i in range(0, len(rows), 500):
            db.execute(insert(Chunk), rows[i:i + 500])
        db.commit()

        done = 0
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for i in range(0, len(rows), 200):
                batch = rows[i:i + 200]
                embs = list(pool.map(lambda r: llm.embed(r["text"]), batch))
                vectors.put([{"key": f"{book.id}:{r['n']}", "embedding": e, "user_id": str(book.user_id),
                              "book_id": str(book.id), "chapter_n": r["chapter_n"], "pdf_page": r["pdf_page"]}
                             for r, e in zip(batch, embs)])
                done += len(batch)
                book.embedded_chunks = done
                db.commit()
        book.embed_status = "done"
        db.commit()
        log.info("embedded %s chunks for %s", done, book.id)


# ---------------------------------------------------------------- chapter build

def build_chapter(chapter_id: str, level: str = "standard") -> None:
    with SessionLocal() as db:
        ch = db.get(Chapter, chapter_id)
        book = db.get(Book, ch.book_id)
        user = db.get(User, book.user_id)
        ch.status, ch.status_detail = "building", None
        db.commit()
        try:
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
        db.commit()
        log.info("built chapter %s (%s in / %s out tokens)", ch.id, usage.tokens_in, usage.tokens_out)


def build_lesson(section_id: str, level: str) -> None:
    """A lesson at a level the chapter wasn't built at (the learner switched level). Interactive tier."""
    with SessionLocal() as db:
        sec = db.get(Section, section_id)
        ch = db.get(Chapter, sec.chapter_id)
        book = db.get(Book, ch.book_id)
        if db.query(Lesson).filter_by(section_id=sec.id, level=level).first():
            return
        body, usage = content.generate_lesson(db, book, ch, sec, level, background=False)
        db.add(Lesson(section_id=sec.id, level=level, body=body, model=llm.settings.text_model))
        record_tokens(db, db.get(User, book.user_id), usage.tokens_in, usage.tokens_out)
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
    with SessionLocal() as db:
        jobs.release_stale(db)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = [threading.Thread(target=loop, args=(f"w{i}",), daemon=True) for i in range(3)]
    for t in threads:
        t.start()
    while not stop.is_set():
        time.sleep(1)


if __name__ == "__main__":
    main()
