"""Everything the model writes: chapter maps, lessons, quizzes, grading, tutor answers.

Book text is passed as <page n="PDF_PAGE" printed="LABEL"> blocks; the model cites PDF page numbers,
and every citation is clamped to pages that exist in the range we sent.
"""
import concurrent.futures as cf
import logging
import random

from sqlalchemy.orm import Session

from . import llm
from .models import Book, Chapter, Lesson, Page, Section

log = logging.getLogger("lectern.content")

LEVELS = {
    "simple": "Explain in plain, everyday words for a beginner. Short sentences, one idea at a time, a concrete everyday example. Define any technical term the first time it appears.",
    "standard": "Explain clearly at the level of a good textbook for a motivated student. Use the book's terms precisely, with one worked example where it helps.",
    "exam": "Explain rigorously for exam preparation: exact definitions, formulas and conditions, a worked example, and the common mistakes or traps examiners test.",
}

SYSTEM_TEACHER = (
    "You are Lectern, a patient teacher who turns a book into short lessons. "
    "Use ONLY the book text provided. Never invent facts, numbers or page numbers. "
    "Cite pages using the n attribute of the <page> tags (PDF page numbers). "
    "Write in the user's language of the book. Keep a warm, direct tone; no filler."
)


def pages_text(db: Session, book_id, start: int, end: int, max_chars: int = 220_000) -> tuple[str, dict[int, str]]:
    rows = (db.query(Page).filter(Page.book_id == book_id, Page.pdf_page >= start, Page.pdf_page <= end)
            .order_by(Page.pdf_page).all())
    labels = {r.pdf_page: (r.label or str(r.pdf_page)) for r in rows}
    parts, total = [], 0
    for r in rows:
        block = f'<page n="{r.pdf_page}" printed="{labels[r.pdf_page]}">\n{r.text}\n</page>'
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts), labels


def clamp(page, lo: int, hi: int) -> int | None:
    try:
        p = int(page)
    except (TypeError, ValueError):
        return None
    return p if lo <= p <= hi else None


# ---------------------------------------------------------------- chapter build

MAP_SCHEMA = {
    "type": "object",
    "required": ["sections", "key_ideas", "difficulty", "minutes", "explain"],
    "properties": {
        "sections": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "type": "object", "required": ["title", "pdf_start", "pdf_end", "summary"],
            "properties": {"title": {"type": "string"}, "pdf_start": {"type": "integer"},
                           "pdf_end": {"type": "integer"}, "summary": {"type": "string"}}}},
        "key_ideas": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string"}},
        "difficulty": {"type": "string", "enum": ["Easy", "Moderate", "Hard"]},
        "minutes": {"type": "integer"},
        "explain": {"type": "object", "required": ["prompt", "key_points", "page"], "properties": {
            "prompt": {"type": "string"},
            "key_points": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
            "page": {"type": "integer"}}},
    },
}

LESSON_SCHEMA = {
    "type": "object",
    "required": ["blocks", "quick_checks", "minutes"],
    "properties": {
        "minutes": {"type": "integer"},
        "blocks": {"type": "array", "minItems": 3, "maxItems": 14, "items": {
            "type": "object", "required": ["type", "text"],
            "properties": {
                "type": {"type": "string", "enum": ["para", "heading", "key_term", "example", "formula"]},
                "text": {"type": "string", "description": "Paragraph text, or the definition for key_term"},
                "term": {"type": "string", "description": "Only for key_term"},
                "page": {"type": "integer"}}}},
        "quick_checks": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
            "type": "object", "required": ["question", "options", "answer_index", "explanation", "page"],
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "minItems": 3, "maxItems": 4, "items": {"type": "string"}},
                "answer_index": {"type": "integer"},
                "explanation": {"type": "string"},
                "page": {"type": "integer"}}}},
    },
}

QUIZ_SCHEMA = {
    "type": "object", "required": ["questions"],
    "properties": {"questions": {"type": "array", "minItems": 6, "maxItems": 12, "items": {
        "type": "object", "required": ["type", "section_n", "question", "explanation", "page"],
        "properties": {
            "type": {"type": "string", "enum": ["mcq", "short"]},
            "section_n": {"type": "integer"},
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "answer_index": {"type": "integer"},
            "model_answer": {"type": "string"},
            "explanation": {"type": "string"},
            "page": {"type": "integer"}}}}},
}


def build_map(db: Session, book: Book, ch: Chapter) -> tuple[dict, llm.Usage]:
    text, _ = pages_text(db, book.id, ch.pdf_start, ch.pdf_end)
    hints = "\n".join(f'- "{c["title"]}" starts on page n={c["pdf_page"]}' for c in (ch.outline_children or []))
    prompt = (
        f'Book: "{book.title}". Chapter {ch.n}: "{ch.title}" (pages n={ch.pdf_start}..{ch.pdf_end}).\n'
        + (f"The PDF bookmarks list these subsections:\n{hints}\nAlign sections to them, merging very short ones.\n" if hints else "")
        + "Split the chapter into 3 to 7 teachable sections covering every page in order with no gaps "
          "(each section's pdf_start is the previous section's pdf_end + 1). Give each a short summary. "
          "List 3-5 key ideas a learner must keep, rate difficulty, estimate total study minutes, and write one "
          "'explain it back' prompt (ask the learner to explain the chapter's central idea to a friend in 2-4 "
          "sentences) with 2-4 key points a good answer must contain and the page it comes from.\n\n" + text
    )
    data, usage = llm.call_json(system=SYSTEM_TEACHER, prompt=prompt, schema=MAP_SCHEMA, tool_name="chapter_map",
                                max_tokens=3000, background=True)
    return data, usage


def normalise_sections(raw: list[dict], start: int, end: int) -> list[dict]:
    secs = sorted([s for s in raw if clamp(s.get("pdf_start"), start, end)], key=lambda s: int(s["pdf_start"]))
    if not secs:
        return [{"title": "Whole chapter", "pdf_start": start, "pdf_end": end, "summary": ""}]
    secs[0]["pdf_start"] = start
    for a, b in zip(secs, secs[1:]):
        a["pdf_end"] = max(int(a["pdf_start"]), int(b["pdf_start"]) - 1)
    secs[-1]["pdf_end"] = end
    out = []
    for s in secs:
        if out and int(s["pdf_start"]) <= out[-1]["pdf_end"]:
            out[-1]["pdf_end"] = int(s["pdf_end"])
            continue
        out.append({"title": s["title"].strip()[:300], "pdf_start": int(s["pdf_start"]),
                    "pdf_end": int(s["pdf_end"]), "summary": s.get("summary", "")})
    return out


def generate_lesson(db: Session, book: Book, ch: Chapter, sec: Section, level: str,
                    background: bool) -> tuple[dict, llm.Usage]:
    text, labels = pages_text(db, book.id, sec.pdf_start, sec.pdf_end, max_chars=90_000)
    prompt = (
        f'Book: "{book.title}". Chapter {ch.n}: "{ch.title}". Section {ch.n}.{sec.n}: "{sec.title}" '
        f"(pages n={sec.pdf_start}..{sec.pdf_end}).\n"
        f"Level: {level}. {LEVELS[level]}\n"
        "Teach this section as a short lesson a learner can finish in about 8-15 minutes: 4-10 blocks mixing "
        "paragraphs (2-5 sentences each), 1-3 key_term blocks (term + one-sentence definition), and an example "
        "or formula where the book has one. Each block cites the page it draws on. Then write 2 quick-check "
        "multiple-choice questions that test understanding (not recall of wording), with the correct "
        "answer_index (0-based), a one-sentence explanation and the page.\n\n" + text
    )
    data, usage = llm.call_json(system=SYSTEM_TEACHER, prompt=prompt, schema=LESSON_SCHEMA, tool_name="lesson",
                                max_tokens=5000, background=background)
    lo, hi = sec.pdf_start, sec.pdf_end
    for b in data.get("blocks", []):
        b["page"] = clamp(b.get("page"), lo, hi)
    checks = []
    for q in data.get("quick_checks", []):
        opts = q.get("options") or []
        if not (2 <= len(opts) <= 5) or not (0 <= int(q.get("answer_index", -1)) < len(opts)):
            continue
        q["page"] = clamp(q.get("page"), lo, hi)
        checks.append(q)
    data["quick_checks"] = checks
    data["labels"] = {str(k): v for k, v in labels.items()}
    return data, usage


def build_quiz(db: Session, book: Book, ch: Chapter, sections: list[Section]) -> tuple[list[dict], llm.Usage]:
    text, labels = pages_text(db, book.id, ch.pdf_start, ch.pdf_end)
    outline = "\n".join(f"{s.n}. {s.title} (n={s.pdf_start}..{s.pdf_end})" for s in sections)
    prompt = (
        f'Book: "{book.title}". Chapter {ch.n}: "{ch.title}". Sections:\n{outline}\n\n'
        "Write a 10-question chapter quiz: 7 multiple-choice (4 options, answer_index 0-based) and 3 short-answer "
        "(model_answer of 1-2 sentences, graded for the idea). Spread questions across all sections, test "
        "understanding and application, and give each a one-sentence explanation and the page it comes from.\n\n" + text
    )
    data, usage = llm.call_json(system=SYSTEM_TEACHER, prompt=prompt, schema=QUIZ_SCHEMA, tool_name="quiz",
                                max_tokens=5000, background=True)
    out = []
    for i, q in enumerate(data.get("questions", [])):
        q["id"] = f"q{i + 1}"
        q["page"] = clamp(q.get("page"), ch.pdf_start, ch.pdf_end)
        q["page_label"] = labels.get(q["page"]) if q["page"] else None
        if q["type"] == "mcq":
            opts = q.get("options") or []
            if len(opts) < 2 or not (0 <= int(q.get("answer_index", -1)) < len(opts)):
                continue
        elif not q.get("model_answer"):
            continue
        out.append(q)
    return out, usage


def build_chapter(db: Session, book: Book, ch: Chapter, level: str) -> llm.Usage:
    """Map, sections, lessons at the learner's level, and the quiz. Caller commits."""
    total = llm.Usage()
    m, u = build_map(db, book, ch)
    total.add(u)
    for s in list(ch.sections):
        db.delete(s)
    db.flush()
    secs = []
    for i, s in enumerate(normalise_sections(m.get("sections", []), ch.pdf_start, ch.pdf_end), start=1):
        sec = Section(chapter_id=ch.id, n=i, title=s["title"], pdf_start=s["pdf_start"], pdf_end=s["pdf_end"],
                      summary=s.get("summary"))
        db.add(sec)
        secs.append(sec)
    explain = m.get("explain") or {}
    explain["page"] = clamp(explain.get("page"), ch.pdf_start, ch.pdf_end)
    ch.map = {"key_ideas": m.get("key_ideas", []), "difficulty": m.get("difficulty", "Moderate"),
              "minutes": m.get("minutes"), "explain": explain}
    db.commit()  # lesson threads read sections through their own sessions

    # Lessons in parallel; each worker only reads, writes happen here.
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_lesson_job, book.id, ch.id, sec.id, level): sec for sec in secs}
        for fut in cf.as_completed(futures):
            sec = futures[fut]
            body, u = fut.result()
            total.add(u)
            db.add(Lesson(section_id=sec.id, level=level, body=body, model=llm.settings.text_model))

    from .models import Quiz  # local import keeps module graph simple
    questions, u = build_quiz(db, book, ch, secs)
    total.add(u)
    db.query(Quiz).filter(Quiz.chapter_id == ch.id, Quiz.kind == "chapter").delete()
    db.add(Quiz(book_id=book.id, chapter_id=ch.id, kind="chapter", questions=questions))
    return total


def _lesson_job(book_id, chapter_id, section_id, level):
    from .db import SessionLocal
    db = SessionLocal()
    try:
        book, ch, sec = db.get(Book, book_id), db.get(Chapter, chapter_id), db.get(Section, section_id)
        return generate_lesson(db, book, ch, sec, level, background=True)
    finally:
        db.close()


# ---------------------------------------------------------------- interactive calls

PREQ_SCHEMA = {"type": "object", "required": ["plan", "level", "focus"], "properties": {
    "plan": {"type": "string", "description": "One or two sentences addressed to the learner"},
    "level": {"type": "string", "enum": ["simple", "standard", "exam"]},
    "focus": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}


def prequestion_plan(ch: Chapter, rating: str, answer: str, default_level: str) -> tuple[dict, llm.Usage]:
    sections = "\n".join(f"{s.n}. {s.title}: {s.summary or ''}" for s in ch.sections)
    prompt = (
        f'Chapter "{ch.title}". Sections:\n{sections}\nKey ideas: {", ".join((ch.map or {}).get("key_ideas", []))}\n\n'
        f'The learner rated their prior knowledge as "{rating}" and wrote: "{answer or "(nothing)"}".\n'
        f"Their default explanation level is {default_level}. Suggest a level, up to 3 things to focus on, and a "
        "one-or-two-sentence plan addressed to them (e.g. 'We'll start with ... and spend extra time on ...'). "
        "If they wrote a misconception, gently name it in the plan."
    )
    return llm.call_json(system=SYSTEM_TEACHER, prompt=prompt, schema=PREQ_SCHEMA, tool_name="plan", max_tokens=600)


EXPLAIN_SCHEMA = {"type": "object", "required": ["verdict", "points", "stronger_version"], "properties": {
    "verdict": {"type": "string", "enum": ["Good explanation", "Getting there", "Not yet"]},
    "points": {"type": "array", "items": {"type": "object", "required": ["point", "met", "feedback"], "properties": {
        "point": {"type": "string"}, "met": {"type": "boolean"}, "feedback": {"type": "string"}}}},
    "example_used": {"type": "boolean"},
    "stronger_version": {"type": "string"}}}


def grade_explanation(db: Session, ch: Chapter, text: str) -> tuple[dict, llm.Usage]:
    ex = (ch.map or {}).get("explain") or {}
    page = ex.get("page")
    source = ""
    if page:
        source, _ = pages_text(db, ch.book_id, max(ch.pdf_start, page - 1), min(ch.pdf_end, page + 1), 12_000)
    prompt = (
        f'Prompt given to the learner: "{ex.get("prompt", "Explain the main idea of this chapter.")}"\n'
        f"Key points a good answer contains:\n" + "\n".join(f"- {p}" for p in ex.get("key_points", [])) +
        f'\n\nLearner\'s explanation:\n"""{text}"""\n\n'
        "For each key point say whether the learner covered it (be fair to paraphrases) with one short sentence of "
        "feedback addressed to them. Note whether they used an example. Then write a stronger version in 2-3 "
        "sentences that keeps their voice.\n\n" + source
    )
    data, usage = llm.call_json(system=SYSTEM_TEACHER, prompt=prompt, schema=EXPLAIN_SCHEMA, tool_name="feedback",
                                max_tokens=900)
    data["page"] = page
    data["met"] = sum(1 for p in data.get("points", []) if p.get("met"))
    data["total"] = len(data.get("points", []))
    return data, usage


GRADE_SCHEMA = {"type": "object", "required": ["correct", "feedback"], "properties": {
    "correct": {"type": "boolean"}, "feedback": {"type": "string"}}}


def grade_short_answer(question: str, model_answer: str, answer: str) -> tuple[dict, llm.Usage]:
    prompt = (
        f"Question: {question}\nReference answer: {model_answer}\nLearner's answer: {answer}\n\n"
        "Grade for the idea, not the wording. Mark correct if the core idea is right even if phrased differently "
        "or incomplete in minor details. Give one sentence of feedback addressed to the learner."
    )
    return llm.call_json(system="You grade short answers fairly and briefly.", prompt=prompt, schema=GRADE_SCHEMA,
                         tool_name="grade", max_tokens=300, temperature=0)


TUTOR_SCHEMA = {"type": "object", "required": ["answer", "citations", "in_book"], "properties": {
    "answer": {"type": "string", "description": "Answer in 2-6 sentences. Use **bold** for key terms."},
    "citations": {"type": "array", "maxItems": 4, "items": {"type": "integer"}},
    "in_book": {"type": "boolean", "description": "False if the excerpts don't cover the question"},
    "follow_ups": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}

SYSTEM_TUTOR = (
    "You are the Lectern tutor. Answer ONLY from the book excerpts provided. If the excerpts don't contain the "
    "answer, set in_book=false and say briefly that this book doesn't cover it, then point to the closest thing "
    "it does cover. Cite the page n values you used. Be concise, friendly and concrete. "
    "If asked to quiz the learner, ask one question at a time and wait."
)


def tutor_answer(book: Book, excerpts: list[dict], history: list[dict], question: str,
                 chapter_title: str | None, level: str) -> tuple[dict, llm.Usage]:
    ex = "\n".join(f'<page n="{e["pdf_page"]}" printed="{e["label"]}">\n{e["text"]}\n</page>' for e in excerpts)
    convo = "\n".join(f'{m["role"]}: {m["text"]}' for m in history[-6:])
    prompt = (
        f'Book: "{book.title}". The learner is studying: {chapter_title or "the book"}. Explanation level: {level}. '
        f"{LEVELS[level]}\n\nRecent conversation:\n{convo or '(none)'}\n\nExcerpts:\n{ex}\n\n"
        f"Learner's question: {question}"
    )
    data, usage = llm.call_json(system=SYSTEM_TUTOR, prompt=prompt, schema=TUTOR_SCHEMA, tool_name="reply",
                                max_tokens=900)
    allowed = {e["pdf_page"] for e in excerpts}
    data["citations"] = [p for p in dict.fromkeys(data.get("citations", [])) if p in allowed][:4]
    return data, usage


def final_test_questions(pools: list[tuple[Chapter, list[dict], float | None]], n: int = 40) -> list[dict]:
    """Sample a cumulative test from chapter quizzes, weighted toward chapters with low quiz scores."""
    weighted = []
    for ch, questions, best in pools:
        w = 1.5 - (best if best is not None else 0.5)  # 0.5 .. 1.5
        for q in questions:
            weighted.append((w * random.random(), {**q, "id": f"c{ch.n}-{q['id']}", "chapter_n": ch.n,
                                                    "chapter_title": ch.title}))
    weighted.sort(key=lambda x: -x[0])
    return [q for _, q in weighted[:n]]
