import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Computed, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    price_month: Mapped[float | None] = mapped_column(Float)
    price_year: Mapped[float | None] = mapped_column(Float)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    cognito_sub: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(120))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), default="free")
    limits_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    goal: Mapped[str | None] = mapped_column(String(40))
    level_default: Mapped[str] = mapped_column(String(10), default="standard")
    daily_minutes: Mapped[int] = mapped_column(Integer, default=20)
    target_recall: Mapped[float] = mapped_column(Float, default=0.9)
    reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_prefs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # {"ready": false, ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    plan: Mapped[Plan] = relationship(lazy="joined")


class UsageMonthly(Base):
    __tablename__ = "usage_monthly"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    books_added: Mapped[int] = mapped_column(Integer, default=0)
    tutor_messages: Mapped[int] = mapped_column(Integer, default=0)
    voice_clips: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    s3_key: Mapped[str] = mapped_column(String(500))
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str | None] = mapped_column(String(10))  # text | scanned
    source_format: Mapped[str | None] = mapped_column(String(12))  # what was uploaded: pdf, docx, epub, txt, ...
    # uploading | queued | processing | needs_password | no_structure | review | ready | failed
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    status_detail: Mapped[str | None] = mapped_column(Text)
    structure_source: Mapped[str | None] = mapped_column(String(20))  # bookmarks | contents | manual | equal
    page_offset: Mapped[int | None] = mapped_column(Integer)  # printed page 1 = pdf page (offset + 1)
    embed_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | done | failed
    embedded_chunks: Mapped[int] = mapped_column(Integer, default=0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chapters: Mapped[list["Chapter"]] = relationship(order_by="Chapter.n", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    pdf_page: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1-based
    label: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str | None] = mapped_column(String(12))  # text | textract | tesseract | blank | failed


class Chapter(Base):
    __tablename__ = "chapters"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    n: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(12), default="chapter")  # chapter | front | back | appendix
    pdf_start: Mapped[int] = mapped_column(Integer)
    pdf_end: Mapped[int] = mapped_column(Integer)
    check_note: Mapped[str | None] = mapped_column(Text)
    outline_children: Mapped[list] = mapped_column(JSONB, default=list)  # [{title, pdf_page}] from bookmarks
    # pending | queued | building | ready | failed
    status: Mapped[str] = mapped_column(String(12), default="pending")
    status_detail: Mapped[str | None] = mapped_column(Text)
    map: Mapped[dict | None] = mapped_column(JSONB)  # key_ideas, difficulty, minutes, explain prompt/key points
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sections: Mapped[list["Section"]] = relationship(order_by="Section.n", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    n: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    pdf_start: Mapped[int] = mapped_column(Integer)
    pdf_end: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("section_id", "level"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(10))  # simple | standard | exam
    body: Mapped[dict] = mapped_column(JSONB)  # {blocks:[...], key_terms:[...], quick_checks:[...]}
    model: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"), UniqueConstraint("book_id", "n"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    n: Mapped[int] = mapped_column(Integer)  # vector key in S3 Vectors is "{book_id}:{n}"
    chapter_n: Mapped[int | None] = mapped_column(Integer)
    pdf_page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))


class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="chapter")  # chapter | final
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # final tests are per user
    questions: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    answers: Mapped[list] = mapped_column(JSONB)
    results: Mapped[list] = mapped_column(JSONB)
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    pdf_page: Mapped[int | None] = mapped_column(Integer)
    tag: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20), default="key_term")  # key_term | missed_question
    fsrs: Mapped[dict] = mapped_column(JSONB)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Progress(Base):
    __tablename__ = "progress"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), primary_key=True)
    prequestion: Mapped[dict | None] = mapped_column(JSONB)
    sections_done: Mapped[list] = mapped_column(JSONB, default=list)  # section ids
    explain: Mapped[dict | None] = mapped_column(JSONB)
    quiz_best: Mapped[float | None] = mapped_column(Float)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StudyDay(Base):
    __tablename__ = "study_days"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    seconds: Mapped[int] = mapped_column(Integer, default=0)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_n: Mapped[int | None] = mapped_column(Integer)
    pdf_page: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note | highlight | citation_report
    quote: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_pending", "status", "run_after"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LlmCall(Base):
    """One model call (or one batch of embeddings), with tokens and estimated cost."""
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_created", "created_at"), Index("ix_llm_calls_user", "user_id", "created_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    feature: Mapped[str] = mapped_column(String(30))   # chapter_build | lesson_level | tutor | explain | quiz_grading | ...
    kind: Mapped[str] = mapped_column(String(30))      # chapter_map | lesson | quiz | reply | grade | embed | transcribe ...
    model: Mapped[str] = mapped_column(String(80))
    tier: Mapped[str] = mapped_column(String(10), default="standard")
    calls: Mapped[int] = mapped_column(Integer, default=1)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    units: Mapped[float | None] = mapped_column(Float)  # e.g. audio seconds for transcription
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    """Product analytics: what learners do (uploads, sections completed, quiz scores, reviews...)."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_created", "created_at"), Index("ix_events_type", "type", "created_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(40))
    props: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
