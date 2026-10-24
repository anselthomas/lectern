import os
import tempfile
import threading
from datetime import datetime, timezone

import fitz
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import jobs, pdf, telemetry, vectors
from ..auth import current_user
from ..aws import s3
from ..config import settings
from ..db import get_db
from ..limits import check_new_book, usage_row
from ..models import Book, Chapter, Chunk, Note, Page, Progress, Section, User
from ..storage import delete_object, drop_local, local_pdf, presign_put
from .common import chapter_label, chapter_label_n, label_for, own_book, parse_id

router = APIRouter(prefix="/api")
_doc_lock = threading.Lock()


def chapter_summary(db: Session, user: User, ch: Chapter) -> dict:
    p = db.get(Progress, (user.id, ch.id))
    total = len(ch.sections)
    done = len(p.sections_done) if p else 0
    if p and p.mastered:
        state = "mastered"
    elif done or (p and p.prequestion):
        state = "in_progress"
    else:
        state = "not_started"
    return {
        "id": str(ch.id), "n": ch.n, "label": chapter_label(db, ch), "title": ch.title, "kind": ch.kind,
        "pdf_start": ch.pdf_start, "pdf_end": ch.pdf_end,
        "pages_label": f"{label_for(db, ch.book_id, ch.pdf_start)}–{label_for(db, ch.book_id, ch.pdf_end)}",
        "status": ch.status, "status_detail": ch.status_detail, "check_note": ch.check_note,
        "sections_total": total, "sections_done": done, "state": state,
        "quiz_best": p.quiz_best if p else None,
    }


def book_summary(db: Session, user: User, book: Book, with_chapters: bool = False) -> dict:
    chapters = [c for c in book.chapters]
    learnable = [c for c in chapters if c.kind in ("chapter", "appendix")]
    mastered = sum(1 for c in learnable if (p := db.get(Progress, (user.id, c.id))) and p.mastered)
    sec_total = sec_done = 0
    current = None
    for c in learnable:
        p = db.get(Progress, (user.id, c.id))
        sec_total += max(1, len(c.sections))
        sec_done += len(p.sections_done) if p else 0
        if current is None and not (p and p.mastered):
            current = c
    out = {
        "id": str(book.id), "title": book.title, "filename": book.filename, "pages": book.pages,
        "bytes": book.bytes, "kind": book.kind, "status": book.status, "status_detail": book.status_detail,
        "structure_source": book.structure_source, "page_offset": book.page_offset,
        "embed_status": book.embed_status, "embedded_chunks": book.embedded_chunks, "confirmed": book.confirmed,
        "chapters_total": len(learnable), "chapters_mastered": mastered,
        "progress": round(100 * (sec_done / sec_total), 1) if sec_total else 0,
        "current_chapter": {"id": str(current.id), "n": current.n, "title": current.title} if current else None,
        "created_at": book.created_at.isoformat(),
        "last_opened_at": book.last_opened_at.isoformat() if book.last_opened_at else None,
    }
    if with_chapters:
        out["chapters"] = [chapter_summary(db, user, c) for c in chapters]
    return out


@router.get("/books")
def list_books(user: User = Depends(current_user), db: Session = Depends(get_db)):
    books = (db.query(Book).filter(Book.user_id == user.id)
             .order_by(func.coalesce(Book.last_opened_at, Book.created_at).desc()).all())
    return [book_summary(db, user, b) for b in books]


class NewBook(BaseModel):
    filename: str = Field(max_length=300)
    size: int = Field(gt=0)


@router.post("/books")
def create_book(body: NewBook, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(400, {"code": "not_pdf", "message": "Only PDF files are supported."})
    check_new_book(db, user, body.size)
    title = pdf.title_from_filename(body.filename)
    book = Book(user_id=user.id, title=title[:300], filename=body.filename[:300], s3_key="", bytes=body.size)
    db.add(book)
    db.flush()
    book.s3_key = f"users/{user.id}/books/{book.id}/source.pdf"
    usage_row(db, user).books_added += 1
    db.commit()
    telemetry.event("book_uploaded", user_id=user.id, book_id=book.id, bytes=body.size, filename=body.filename[:120])
    return {"book": book_summary(db, user, book), "upload_url": presign_put(book.s3_key)}


@router.post("/books/{book_id}/uploaded")
def mark_uploaded(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    if book.status != "uploading":  # a retried request: the first one already queued the book
        return book_summary(db, user, book)
    try:
        head = s3().head_object(Bucket=settings.uploads_bucket, Key=book.s3_key)
    except Exception as e:
        raise HTTPException(400, {"code": "upload_missing", "message": "We didn't receive the file. Try again."}) from e
    book.bytes = head["ContentLength"]
    book.status, book.status_detail = "queued", "Waiting to read the PDF"
    jobs.enqueue(db, "ingest_book", book_id=book.id)
    db.commit()
    return book_summary(db, user, book)


class Password(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/books/{book_id}/password")
def unlock(book_id: str, body: Password, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Decrypt once in memory and replace the stored file; the password is never stored or logged."""
    book = own_book(db, user, book_id)
    if book.status != "needs_password":
        raise HTTPException(409, "This book isn't locked")
    path = local_pdf(book)
    doc = fitz.open(path)
    if not doc.authenticate(body.password):
        doc.close()
        raise HTTPException(400, {"code": "wrong_password", "message": "That password didn't unlock the PDF."})
    fd, out = tempfile.mkstemp(suffix=".pdf", dir=settings.cache_dir)
    os.close(fd)
    doc.save(out, encryption=fitz.PDF_ENCRYPT_NONE, garbage=1)
    doc.close()
    s3().upload_file(out, settings.uploads_bucket, book.s3_key, ExtraArgs={"ContentType": "application/pdf"})
    os.replace(out, path)
    book.status, book.status_detail = "queued", "Unlocked. Reading the PDF"
    jobs.enqueue(db, "ingest_book", book_id=book.id)
    db.commit()
    return book_summary(db, user, book)


@router.get("/books/{book_id}")
def get_book(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    book.last_opened_at = datetime.now(timezone.utc)
    db.commit()
    return book_summary(db, user, book, with_chapters=True)


class ChapterIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    pdf_start: int = Field(ge=1)
    pdf_end: int = Field(ge=1)
    kind: str = "chapter"


class Structure(BaseModel):
    chapters: list[ChapterIn] = Field(min_length=1, max_length=400)


@router.put("/books/{book_id}/chapters")
def save_structure(book_id: str, body: Structure, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Replace the outline (rename, merge, split, fix ranges). Built chapters keep their content if unchanged."""
    book = own_book(db, user, book_id)
    specs = sorted(body.chapters, key=lambda c: c.pdf_start)
    for a in specs:
        if a.pdf_end < a.pdf_start or a.pdf_end > book.pages:
            raise HTTPException(400, {"code": "bad_range", "message": f'"{a.title}": pages must be within 1–{book.pages}.'})
    for a, b in zip(specs, specs[1:]):
        if b.pdf_start <= a.pdf_end:
            raise HTTPException(400, {"code": "overlap", "message": f'"{a.title}" overlaps "{b.title}".'})
    existing = {(c.pdf_start, c.pdf_end): c for c in book.chapters}
    keep = set()
    for n, s in enumerate(specs, start=1):
        c = existing.get((s.pdf_start, s.pdf_end))
        if c:
            c.n, c.title, c.kind, c.check_note = n, s.title, s.kind if s.kind in ("chapter", "front", "back", "appendix") else "chapter", None
            keep.add(c.id)
        else:
            c = Chapter(book_id=book.id, n=n, title=s.title, kind=s.kind, pdf_start=s.pdf_start, pdf_end=s.pdf_end)
            db.add(c)
            db.flush()
            keep.add(c.id)
    for c in list(book.chapters):
        if c.id not in keep:
            db.delete(c)
    if book.status == "no_structure":
        book.status = "review"
    book.structure_source = book.structure_source or "manual"
    db.commit()
    db.refresh(book)
    return book_summary(db, user, book, with_chapters=True)


class Split(BaseModel):
    parts: int = Field(ge=1, le=100)


@router.post("/books/{book_id}/split")
def split_equal(book_id: str, body: Split, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    for c in list(book.chapters):
        db.delete(c)
    db.flush()
    for n, s in enumerate(pdf.equal_split(book.pages, body.parts), start=1):
        db.add(Chapter(book_id=book.id, n=n, title=s.title, pdf_start=s.pdf_start, pdf_end=s.pdf_end))
    book.status, book.structure_source = "review", "equal"
    db.commit()
    db.refresh(book)
    return book_summary(db, user, book, with_chapters=True)


@router.post("/books/{book_id}/confirm")
def confirm(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    if book.status not in ("review", "ready"):
        raise HTTPException(409, "The book isn't ready to confirm yet")
    book.confirmed, book.status = True, "ready"
    first = next((c for c in book.chapters if c.kind == "chapter"), book.chapters[0] if book.chapters else None)
    if first and first.status in ("pending", "failed"):
        first.status = "queued"
        jobs.enqueue(db, "build_chapter", chapter_id=first.id, level=user.level_default)
    db.commit()
    return book_summary(db, user, book, with_chapters=True)


@router.post("/books/{book_id}/redetect")
def redetect(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Run chapter detection again (after detection improvements, or if the outline looks wrong).
    Replaces the outline, so lessons and progress for this book are rebuilt from scratch."""
    book = own_book(db, user, book_id)
    if book.status in ("uploading", "queued", "processing"):
        raise HTTPException(409, "This book is already being processed")
    book.status, book.status_detail, book.confirmed = "queued", "Finding the chapters again", False
    jobs.enqueue(db, "ingest_book", book_id=book.id)
    db.commit()
    return book_summary(db, user, book)


@router.delete("/books/{book_id}")
def delete_book(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    chunks = db.query(func.count(Chunk.id)).filter(Chunk.book_id == book.id).scalar()
    try:
        vectors.delete_book(str(book.id), chunks)
    except Exception:
        pass  # orphaned vectors are filtered out by book_id and harmless
    try:
        delete_object(book.s3_key)
    except Exception:
        pass
    drop_local(book.id)
    db.delete(book)
    db.commit()
    return {"ok": True}


@router.get("/books/{book_id}/pages/{n}")
def get_page(book_id: str, n: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    page = db.get(Page, (book.id, n))
    if page is None:
        raise HTTPException(404, "Page not found")
    ch = next((c for c in book.chapters if c.pdf_start <= n <= c.pdf_end), None)
    return {"pdf_page": n, "label": page.label or str(n), "text": page.text, "pages": book.pages,
            "chapter": {"n": ch.n, "label": chapter_label(db, ch), "title": ch.title} if ch else None}


@router.get("/books/{book_id}/pages/{n}/image")
def page_image(book_id: str, n: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    if not 1 <= n <= book.pages:
        raise HTTPException(404, "Page not found")
    with _doc_lock:
        doc = fitz.open(local_pdf(book))
        try:
            png = pdf.render_png(doc, n)
        finally:
            doc.close()
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------- notes

class NoteIn(BaseModel):
    pdf_page: int | None = None
    page_label: str | None = Field(default=None, max_length=20)  # the page number printed in the book
    kind: str = "note"
    quote: str | None = Field(default=None, max_length=4000)
    text: str | None = Field(default=None, max_length=4000)


def note_out(db, n: Note) -> dict:
    return {"id": str(n.id), "pdf_page": n.pdf_page, "page_label": label_for(db, n.book_id, n.pdf_page),
            "chapter_n": n.chapter_n, "chapter_label": chapter_label_n(db, n.book_id, n.chapter_n), "kind": n.kind, "quote": n.quote, "text": n.text,
            "created_at": n.created_at.isoformat()}


@router.get("/books/{book_id}/notes")
def list_notes(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    notes = (db.query(Note).filter(Note.book_id == book.id, Note.user_id == user.id, Note.kind != "citation_report")
             .order_by(Note.created_at.desc()).all())
    return [note_out(db, n) for n in notes]


@router.post("/books/{book_id}/notes")
def add_note(book_id: str, body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = own_book(db, user, book_id)
    if body.kind not in ("note", "highlight", "citation_report"):
        raise HTTPException(400, "Unknown note kind")
    if body.page_label and not body.pdf_page:
        match = db.query(Page).filter(Page.book_id == book.id, Page.label == body.page_label.strip()).first()
        if match is None and body.page_label.strip().isdigit():
            n = int(body.page_label)
            match = db.get(Page, (book.id, n + (book.page_offset or 0)))
        if match is None:
            raise HTTPException(400, {"code": "bad_page", "message": f"This book has no page {body.page_label}."})
        body.pdf_page = match.pdf_page
    ch = next((c for c in book.chapters if body.pdf_page and c.pdf_start <= body.pdf_page <= c.pdf_end), None)
    note = Note(user_id=user.id, book_id=book.id, chapter_n=ch.n if ch else None, pdf_page=body.pdf_page,
                kind=body.kind, quote=body.quote, text=body.text)
    db.add(note)
    db.commit()
    return note_out(db, note)


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    note = db.get(Note, parse_id(note_id))
    if note is None or note.user_id != user.id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
    return {"ok": True}
