"""Chapter detection. Pure functions over an open PDF and its page texts, so they can be tested on any document.

Order, most reliable first:
  1. PDF bookmarks, if they describe a real structure (not file names, "Page 1", duplicates or one giant entry)
  2. the contents page, read by the model and mapped to PDF pages via the printed-page offset
  3. bookmark positions, with titles taken from each start page
  4. "Chapter N" / "Unit N" headings at the top of pages
Nothing found -> ([], None) and the user marks chapters by hand or splits evenly.
"""
import logging
import re
from typing import Callable

import fitz

from . import llm, pdf

log = logging.getLogger("lectern.structure")


CONTENTS_SCHEMA = {"type": "object", "required": ["has_contents", "entries"], "properties": {
    "has_contents": {"type": "boolean"},
    "entries": {"type": "array", "items": {"type": "object", "required": ["title", "printed_page"], "properties": {
        "title": {"type": "string"},
        "printed_page": {"type": "string", "description": "Page number exactly as printed, e.g. '45' or 'xi'"},
        "children": {"type": "array", "description": "Chapters inside this section/part, if the book groups them",
                     "items": {"type": "object", "required": ["title", "printed_page"], "properties": {
                         "title": {"type": "string"}, "printed_page": {"type": "string"}}}}}}}}}


SUBSECTION = re.compile(r"^\s*\d+\.\d+")


def chapters_from_contents(texts: list[str], offset: "int | None", labels: "list[str | None] | None" = None) -> list[pdf.ChapterSpec]:
    """Read the contents pages with the model, then map printed pages to PDF pages.

    Books that group chapters into sections/parts become one Lectern chapter per section (its chapters become
    section hints), unless the sections are so long that teaching chapter by chapter works better.
    """
    front = contents_pages_text(texts)
    rules = (
        "List ONLY the top-level entries in order with the page number exactly as printed. Give each entry its full "
        "title including its name (e.g. 'Chapter 1: Welcome to Economics!', 'Section 1: Introduction to Pharmacy'), "
        "never just 'Chapter 1'. Never list numbered "
        "subsections such as 1.1, 1.2 or 3.4. If the book groups its chapters under section or part headings (for "
        "example 'Section 1 Introduction' followed by chapters '1-1 ...', '1-2 ...'), you MUST return each "
        "section/part as an entry and its chapters as children; a section starts where its first chapter starts. "
        "Include front matter (preface), appendices and back matter (answer key, references, glossary, index) as "
        "their own entries. If there is no contents page, set has_contents=false.")
    try:
        data, _ = llm.call_json(
            system="You read a book's table of contents precisely. Never invent entries or page numbers.",
            prompt=f"{rules}\n\n{front}", schema=CONTENTS_SCHEMA, tool_name="contents", max_tokens=10000, temperature=0)
    except llm.LLMError:
        # Usually an over-long reply for a very detailed contents page: retry without children.
        data, _ = llm.call_json(
            system="You read a book's table of contents precisely. Never invent entries or page numbers.",
            prompt=f"{rules} Do not include children this time; top-level entries only.\n\n{front}",
            schema=CONTENTS_SCHEMA, tool_name="contents", max_tokens=6000, temperature=0)
    if not data.get("has_contents"):
        return []
    n = len(texts)

    def to_pdf(printed, title):
        return printed_to_pdf(printed, title, texts, offset, labels)

    entries = []
    for e in data.get("entries", []):
        kids = [{"title": c["title"], "pdf_page": to_pdf(c["printed_page"], c["title"])} for c in e.get("children") or []]
        kids = [k for k in kids if k["pdf_page"]]
        start = to_pdf(e["printed_page"], e["title"]) or (kids[0]["pdf_page"] if kids else None)
        if start:
            entries.append((start, e["title"], kids))
    entries.sort(key=lambda x: x[0])
    listed = len(data.get("entries", []))
    if len(entries) < 2 or len(entries) < 0.7 * listed:
        return []  # most entries didn't land on a real page: don't trust this reading

    def build(items):
        specs = []
        for j, (p, title, kids) in enumerate(items):
            end = items[j + 1][0] - 1 if j + 1 < len(items) else n
            specs.append(pdf.ChapterSpec(title=title, pdf_start=p, pdf_end=max(p, end), kind=pdf.kind_for(title),
                                         children=[k for k in kids if p <= k["pdf_page"] <= max(p, end)]))
        return specs

    grouped = build(entries)
    longest = max(s.pdf_end - s.pdf_start + 1 for s in grouped)
    # Very long groups (e.g. "Unit 1" holding 14 chapters) are taught chapter by chapter. Entries without children
    # (appendices, answer key, index) are kept, and we never split into numbered subsections like "1.1".
    splittable = [kids for _, _, kids in entries if kids and not all(SUBSECTION.match(k["title"]) for k in kids)]
    if splittable and longest > 150:
        flat = []
        for p, title, kids in entries:
            if kids and not all(SUBSECTION.match(k["title"]) for k in kids):
                flat.extend((k["pdf_page"], k["title"], []) for k in kids)
            else:
                flat.append((p, title, kids))
        flat.sort(key=lambda x: x[0])
        if len(flat) >= 2:
            return build(flat)
    return grouped


def contents_pages_text(texts: list[str]) -> str:
    """The contents pages in full (plus a few after, since contents often run on), else the opening pages."""
    hits = [i for i, t in enumerate(texts[:40]) if re.search(r"\b(contents)\b", t[:400], re.I)]
    if hits:
        end = hits[0] + 1
        while end < min(len(texts), hits[0] + 25) and looks_like_contents(texts[end]):
            end += 1
        pages = range(hits[0], min(len(texts), end + 1))  # one extra page in case the listing continues
        per_page = 15000
    else:
        pages = range(min(30, len(texts)))
        per_page = 4000
    return "\n".join(f'<page n="{i + 1}">\n{texts[i][:per_page]}\n</page>' for i in pages)


def looks_like_contents(text: str) -> bool:
    """A page that is mostly entries ending in page numbers (or bare page numbers on their own lines)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 6:
        return False
    numbered = sum(1 for l in lines if re.search(r"(\.{2,}|\s)\d{1,4}$", l) or re.fullmatch(r"\d{1,4}", l))
    return numbered >= 0.3 * len(lines)


def contents_end(texts: list[str]) -> int:
    """Index just past the contents pages (0 if none found), so title searches skip the contents itself."""
    hits = [i for i, t in enumerate(texts[:40]) if re.search(r"\b(contents)\b", t[:400], re.I)]
    return (hits[-1] + 1) if hits else 0


def printed_to_pdf(printed, title: str, texts: list[str], offset: int | None,
                   labels: list[str | None] | None = None) -> int | None:
    """Printed page -> PDF page: via PDF page labels, the detected offset, or by finding the title on a page."""
    n = len(texts)
    printed = str(printed).strip()
    if labels and printed:
        for i, lab in enumerate(labels):
            if lab and lab.strip().lower() == printed.lower():
                return i + 1
    if offset is not None and printed.isdigit():
        p = int(printed) + offset
        return p if 1 <= p <= n else None
    key = re.sub(r"\W+", " ", title).strip().lower()[:40]
    if len(key) < 4:
        return None
    for i in range(max(contents_end(texts), 1), n):
        head = re.sub(r"\W+", " ", " ".join(texts[i].splitlines()[:3])).lower()
        if key in head:
            return i + 1
    return None


CONTENTS_LINE = re.compile(r"^\s*(?P<title>\S.*?[A-Za-z].*?)\s*(?:\.{2,}|\u2026+|\s{2,}|\s)\s*(?P<page>\d{1,4})\s*$")


def chapters_from_contents_text(texts: list[str], offset: int | None) -> list[pdf.ChapterSpec]:
    """No-model fallback: parse 'Title ...... 45' lines from the contents pages."""
    starts = contents_text_entries(texts, offset)
    if len(starts) < 2:
        return []
    n = len(texts)
    return [pdf.ChapterSpec(title=t, pdf_start=p, pdf_end=(starts[j + 1][0] - 1 if j + 1 < len(starts) else n),
                            kind=pdf.kind_for(t)) for j, (p, t) in enumerate(starts)]


def attach_section_hints(specs: list[pdf.ChapterSpec], texts: list[str], offset: int | None) -> None:
    """Give chapters without sub-entries the contents lines that fall inside them, so lessons follow the book's
    own subdivisions (e.g. Section 1 -> chapters 1-1 ... 1-6) instead of guessed ones."""
    entries = contents_text_entries(texts, offset)
    for sp in specs:
        if sp.children:
            continue
        inside = [{"title": t, "pdf_page": p} for p, t in entries
                  if sp.pdf_start <= p <= sp.pdf_end and t.lower() not in sp.title.lower()]
        if len(inside) >= 2:
            sp.children = inside


def contents_text_entries(texts: list[str], offset: int | None) -> list[tuple[int, str]]:
    """Every 'Title ...... 45' entry on the contents pages, mapped to (pdf_page, title), in page order."""
    entries: list[tuple[str, int]] = []
    started = None
    for i, text in enumerate(texts[:40]):
        if started is None:
            if not re.search(r"\b(contents|table of contents)\b", text, re.I):
                continue
            started = i
        if i > started + 6:
            break
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for k, line in enumerate(lines):
            m = CONTENTS_LINE.match(line)
            if m and not re.fullmatch(r"[\divxlc.\s]+", m["title"], re.I):
                entries.append((m["title"].strip(" .\u2026"), int(m["page"])))
            elif re.fullmatch(r"\d{1,4}", line) and k > 0 and re.search(r"[A-Za-z]{3}", lines[k - 1]) \
                    and not CONTENTS_LINE.match(lines[k - 1]):
                entries.append((lines[k - 1].strip(" .\u2026"), int(line)))  # title, then its page on the next line
    # Keep an increasing run of printed pages (drops stray numbers like years).
    kept: list[tuple[str, int]] = []
    for title, page in entries:
        if not kept or page > kept[-1][1]:
            kept.append((title, page))
    starts = []
    for title, page in kept:
        p = printed_to_pdf(page, title, texts, offset)
        if p:
            starts.append((p, title))
    return starts


ContentsReader = Callable[..., list[pdf.ChapterSpec]]
SHORT_DOC_PAGES = 40
WHOLE_DOCUMENT = "Full document"


def detect(doc: fitz.Document, texts: list[str], offset: int | None,
           read_contents: ContentsReader | None = None) -> tuple[list[pdf.ChapterSpec], str | None]:
    """Return (chapters, source). `read_contents` defaults to the model-backed reader; tests pass a stub."""
    n = doc.page_count
    labels = [(doc[i].get_label() or None) for i in range(n)]
    if read_contents is None:
        read_contents = lambda t, o: chapters_from_contents(t, o, labels)  # noqa: E731
    attempts = [
        ("bookmarks", lambda: pdf.chapters_from_outline(doc)),
        ("contents", lambda: read_contents(texts, offset)),
        ("contents", lambda: chapters_from_contents_text(texts, offset)),
        ("bookmark positions", lambda: pdf.chapters_from_bookmark_positions(doc, texts)),
        ("chapter headings", lambda: pdf.chapters_from_headings(texts)),
    ]
    for source, attempt in attempts:
        try:
            specs = attempt()
        except Exception as e:  # one broken strategy must never sink the upload
            log.warning("structure strategy %s failed: %s", source, e)
            continue
        specs = sanitize(specs, n)
        if specs and pdf.outline_usable(specs, n):
            name_bare_titles(specs, texts)
            specs = refine_with_page_headings(specs, texts)
            try:
                attach_section_hints(specs, texts, offset)
            except Exception as e:  # hints are a bonus; never fail detection over them
                log.warning("section hints failed: %s", e)
            return collapse_short(specs, n), source
    if n <= SHORT_DOC_PAGES:
        return [pdf.ChapterSpec(title=WHOLE_DOCUMENT, pdf_start=1, pdf_end=n)], "whole document"
    return [], None


BARE_TITLE = re.compile(r"^(section|chapter|part|unit|module|lesson|book)?\s*([\dIVXLC]+|one|two|three|four|five|six|"
                        r"seven|eight|nine|ten)[.:]?$", re.I)
PAGE_TAG = re.compile(r"^(\d+[-.]\d+|\d+|(section|chapter|part|unit)\s+[\dIVXLC]+)[.:\s-]*", re.I)


def name_bare_titles(specs: list[pdf.ChapterSpec], texts: list[str]) -> None:
    """A contents line like "Section 13" with the name only on the chapter's own first page: borrow that heading."""
    for s in specs:
        if not BARE_TITLE.match(s.title.strip()) or not (0 < s.pdf_start <= len(texts)):
            continue
        for line in [l.strip() for l in texts[s.pdf_start - 1].splitlines() if l.strip()][:6]:
            name = PAGE_TAG.sub("", line).strip(" .:-")
            if 3 <= len(name) <= 80 and re.search(r"[A-Za-z]{3}", name) and not BARE_TITLE.match(name):
                s.title = f"{s.title.strip()} {name}"
                s.kind = pdf.kind_for(name)
                break


NUMBERED_TITLE = re.compile(r"^(?:chapter|section|part|unit|module|lesson|appendix)\s+(\d+|[A-Z]\b|[IVXLC]+\b)", re.I)


def chapter_labels(chapters) -> dict[int, str | None]:
    """What to call each chapter row: the book's own number ("Chapter 7 ..." -> "7", "Appendix B ..." -> "B"),
    else its position among the real chapters (or appendices, lettered). Front and back matter get none,
    so a preface or contents page never shifts the numbering."""
    out, n_ch, n_app = {}, 0, 0
    for c in sorted(chapters, key=lambda c: c.n):
        m = NUMBERED_TITLE.match(c.title.strip())
        if c.kind == "chapter":
            n_ch += 1
            out[c.n] = m.group(1).upper() if m else str(n_ch)
        elif c.kind == "appendix":
            n_app += 1
            out[c.n] = m.group(1).upper() if m else chr(64 + n_app) if n_app <= 26 else str(n_app)
        else:
            out[c.n] = None
    return out


APPENDIX_HEAD = re.compile(r"^appendix\b", re.I)
TRAILING_BACK = re.compile(r"^(index|bibliography|references|works cited)$", re.I)


def first_line(text: str) -> str:
    return next((l.strip() for l in text.splitlines() if l.strip()), "")


def refine_with_page_headings(specs: list[pdf.ChapterSpec], texts: list[str]) -> list[pdf.ChapterSpec]:
    """Use what each chapter's own pages say: "Appendix A ..." on its first page makes it an appendix, and an
    index or bibliography inside the last chapter (nothing marked where it ends) is split off as back matter."""
    for s in specs:
        if s.kind == "chapter" and 0 < s.pdf_start <= len(texts) and APPENDIX_HEAD.match(first_line(texts[s.pdf_start - 1])):
            s.kind = "appendix"
    if specs and specs[-1].kind in ("chapter", "appendix"):
        last = specs[-1]
        for p in range(last.pdf_start + 1, min(last.pdf_end, len(texts)) + 1):
            head = first_line(texts[p - 1])
            if TRAILING_BACK.match(head):
                specs.append(pdf.ChapterSpec(title=head.title(), pdf_start=p, pdf_end=last.pdf_end, kind="back"))
                last.pdf_end, last.check_note = p - 1, None
                break
    return specs


def collapse_short(specs: list[pdf.ChapterSpec], page_count: int) -> list[pdf.ChapterSpec]:
    """A paper or short guide is taught as one chapter; its parts become section hints for the lesson builder."""
    if page_count > SHORT_DOC_PAGES:
        return specs
    learn = [s for s in specs if s.kind in ("chapter", "appendix")]
    if len(learn) <= 1:
        return specs
    hints = [{"title": s.title, "pdf_page": s.pdf_start} for s in learn]
    return [pdf.ChapterSpec(title=WHOLE_DOCUMENT, pdf_start=1, pdf_end=page_count, children=hints)]


def sanitize(specs: list[pdf.ChapterSpec], page_count: int) -> list[pdf.ChapterSpec]:
    """Clamp to real pages, sort, and remove overlaps/empties so every strategy returns a valid outline."""
    out: list[pdf.ChapterSpec] = []
    for sp in sorted(specs, key=lambda x: x.pdf_start):
        start = max(1, min(sp.pdf_start, page_count))
        end = max(start, min(sp.pdf_end, page_count))
        if out and start <= out[-1].pdf_end:
            if start == out[-1].pdf_start:
                continue  # duplicate start: keep the first
            out[-1].pdf_end = start - 1
        elif out and start > out[-1].pdf_end + 1:
            out[-1].pdf_end = start - 1  # close gaps so no pages fall outside every chapter
        sp.pdf_start, sp.pdf_end = start, end
        sp.title = (sp.title or "").strip()[:300] or f"Part {len(out) + 1}"
        out.append(sp)
    return out
