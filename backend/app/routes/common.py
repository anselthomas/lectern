import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Book, Chapter, Progress, Section, User


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(404, "Not found") from e


def own_book(db: Session, user: User, book_id: str) -> Book:
    book = db.get(Book, parse_id(book_id))
    if book is None or book.user_id != user.id:
        raise HTTPException(404, "Book not found")
    return book


def own_chapter(db: Session, user: User, chapter_id: str) -> tuple[Chapter, Book]:
    ch = db.get(Chapter, parse_id(chapter_id))
    if ch is None:
        raise HTTPException(404, "Chapter not found")
    return ch, own_book(db, user, str(ch.book_id))


def own_section(db: Session, user: User, section_id: str) -> tuple[Section, Chapter, Book]:
    sec = db.get(Section, parse_id(section_id))
    if sec is None:
        raise HTTPException(404, "Section not found")
    ch, book = own_chapter(db, user, str(sec.chapter_id))
    return sec, ch, book


def progress_row(db: Session, user: User, ch: Chapter) -> Progress:
    p = db.get(Progress, (user.id, ch.id))
    if p is None:
        p = Progress(user_id=user.id, chapter_id=ch.id, sections_done=[])
        db.add(p)
        db.flush()
    return p


def label_for(db: Session, book_id, pdf_page: int | None) -> str | None:
    if not pdf_page:
        return None
    from ..models import Page
    page = db.get(Page, (book_id, pdf_page))
    return (page.label if page and page.label else str(pdf_page)) if page else str(pdf_page)
