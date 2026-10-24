"""PDF reading: text, page labels, bookmarks, printed-page offset, OCR and chunking. Pages are 1-based."""
import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # PyMuPDF

BACK_MATTER = re.compile(r"^(index|glossary|references|bibliography|answer key|answers|credits|about the authors?)\b", re.I)
FRONT_MATTER = re.compile(r"^(preface|contents|table of contents|foreword|acknowledg|copyright|title page|cover|dedication|about (this|the) book)\b", re.I)
APPENDIX = re.compile(r"^appendix\b", re.I)


JUNK_TITLE = re.compile(
    r"(\.(pdf|pmd|p65|indd|qxd|docx?|rtf|txt)$)|(^(page|pg\.?|p\.)\s*[\divx]+$)|(^untitled\b)|(^microsoft word\b)|(^[\d\s.\-_]+$)",
    re.I)


# Names a phone or scanner makes up, not a person: "Inbound4283829095700509506" (Android share), "IMG_20241003",
# "scan0001", "document (3)", "download", or long runs of digits / hex.
MACHINE_NAME = re.compile(
    r"^((inbound|img|image|scan(ned)?|document|doc|download|file|tmp|temp|attachment|whatsapp|pdf|print|output)"
    r"[\s_\-()]*[\d\s_\-()]*|.*\d{8,}.*|[0-9a-f\-]{16,})$", re.I)


def junk_title(title: str) -> bool:
    t = title.strip()
    return not t or bool(JUNK_TITLE.search(t)) or bool(MACHINE_NAME.match(t))


@dataclass
class ChapterSpec:
    title: str
    pdf_start: int
    pdf_end: int
    kind: str = "chapter"
    children: list = field(default_factory=list)
    check_note: str | None = None


def open_pdf(path: str, password: str | None = None) -> fitz.Document:
    doc = fitz.open(path)
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise PermissionError("password required")
    return doc


def open_pdf_bytes(data: bytes, password: str | None = None) -> fitz.Document:
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass and (not password or not doc.authenticate(password)):
        doc.close()
        raise PermissionError("password required")
    return doc


def is_scanned(doc: fitz.Document, sample: int = 40) -> bool:
    n = doc.page_count
    idx = sorted({int(i * n / sample) for i in range(sample)}) if n > sample else range(n)
    empty = sum(1 for i in idx if len(doc[i].get_text("text").strip()) < 40)
    return empty / max(1, len(idx)) > 0.6


def page_text(page: fitz.Page, ocr: bool = False) -> str:
    if ocr:
        tp = page.get_textpage_ocr(language="eng", dpi=200, full=True)
        return page.get_text("text", textpage=tp)
    return page.get_text("text")


_ENGLISH: set[str] | None = None


def english_words() -> set[str]:
    """The system word list (Debian's wamerican, installed in the image); empty if absent."""
    global _ENGLISH
    if _ENGLISH is None:
        _ENGLISH = set()
        for path in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    _ENGLISH = {w.strip().lower() for w in f if w.strip().isalpha()}
                break
            except OSError:
                continue
    return _ENGLISH


LINE_SPLIT = re.compile(r"([A-Za-z]+)[ \t]*\n[ \t]*([a-z]+)")


def rejoin_split_words(texts: list[str], words: set[str] | None = None) -> list[str]:
    """Undo line wraps that cut a word in two without a hyphen ("rec\\neptor", "str\\nength"), which some
    exporters produce. A break is joined when the halves aren't both words but the whole is one, or when
    neither half is a word at all. Words come from an English list plus the document's own vocabulary."""
    words = english_words() if words is None else words
    seen = Counter(w.lower() for t in texts for w in re.findall(r"[A-Za-z]{2,}", t))
    # Stems of the document's own longer words, so a technical term missing from the word list still counts
    # ("decrement" from "decremental").
    stems = {w[:k] for w in seen if len(w) >= 8 for k in range(6, len(w))}

    def known(w: str, whole: bool = False) -> bool:
        w = w.lower()
        if len(w) == 1:
            return w in ("a", "i")
        return w in words or seen[w] >= 2 or (whole and w in stems)

    def fix(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        whole, a_ok, b_ok = a + b, known(a), known(b)
        if (known(whole, whole=True) and not (a_ok and b_ok)) or (not a_ok and not b_ok):
            return whole
        return m.group(0)
    return [LINE_SPLIT.sub(fix, t) for t in texts]


def clean(text: str) -> str:
    text = text.replace("­", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)          # join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def kind_for(title: str) -> str:
    t = re.sub(r"^\s*[\dIVXivx]+[.:)]?\s+", "", title).strip()
    if APPENDIX.match(t):
        return "appendix"
    if BACK_MATTER.match(t):
        return "back"
    if FRONT_MATTER.match(t):
        return "front"
    return "chapter"


def chapters_from_outline(doc: fitz.Document) -> list[ChapterSpec]:
    # Drop junk entries some exporters add, like a bookmark named after the file itself.
    toc = [(lvl, title.strip(), page) for lvl, title, page in doc.get_toc(simple=True)
           if page and page > 0 and not junk_title(title)]
    if not toc:
        return []
    levels = Counter(lvl for lvl, _, _ in toc)
    top = min(levels)
    # Books split into a few "Parts" put chapters one level down.
    if levels[top] < 3 and levels.get(top + 1, 0) >= 3:
        top += 1
    tops = sorted([(i, t, p) for i, (lvl, t, p) in enumerate(toc) if lvl == top], key=lambda x: (x[2], x[0]))
    specs: list[ChapterSpec] = []
    for j, (i, title, start) in enumerate(tops):
        end_note = None
        if j + 1 < len(tops):
            end = max(start, tops[j + 1][2] - 1)
        else:
            end = doc.page_count
            end_note = f'"{title}" has no bookmark after it, so we assumed it runs to the last page.'
        children = [{"title": t, "pdf_page": p} for (lvl, t, p) in toc[i + 1:(tops[j + 1][0] if j + 1 < len(tops) else len(toc))]
                    if lvl == top + 1 and start <= p <= end]
        specs.append(ChapterSpec(title=title, pdf_start=start, pdf_end=end, kind=kind_for(title),
                                 children=children, check_note=end_note if kind_for(title) == "chapter" else None))
    # Drop zero-length or duplicate-start entries.
    out: list[ChapterSpec] = []
    for s in specs:
        if out and s.pdf_start == out[-1].pdf_start:
            continue
        out.append(s)
    return out


def equal_split(page_count: int, parts: int) -> list[ChapterSpec]:
    parts = max(1, min(parts, page_count))
    size = page_count / parts
    return [ChapterSpec(title=f"Part {i + 1}", pdf_start=int(i * size) + 1, pdf_end=int((i + 1) * size))
            for i in range(parts)]


def detect_offset(labels: list[str | None], texts: list[str]) -> int | None:
    """Return k such that printed page p is pdf page p + k."""
    for i, label in enumerate(labels):
        if label and label.strip() == "1":
            return i  # pdf page i+1 is printed 1
    votes: Counter = Counter()
    for i, text in enumerate(texts):
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        page_votes = set()
        for cand in lines[:3] + lines[-3:]:
            for m in (re.fullmatch(r"(\d{1,4})", cand),
                      re.match(r"(\d{1,4})\s+(?=[A-Za-z\u2022|\d])", cand),      # "10 1 â€¢ Welcome to Economics!"
                      re.search(r"(?<=[A-Za-z)!?.:\u2022|])\s+(\d{1,4})$", cand)):  # "... Why Is It Important? 11"
                if m:
                    page_votes.add((i + 1) - int(m.group(1)))
        for k in page_votes:
            votes[k] += 1
    if not votes:
        return None
    k, count = votes.most_common(1)[0]
    return k if count >= max(5, len(texts) // 20) else None


def chunk_page(text: str, max_chars: int = 1600) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > max_chars:
            for s in re.split(r"(?<=[.!?])\s+", p):
                if len(cur) + len(s) > max_chars and cur:
                    chunks.append(cur)
                    cur = ""
                cur = f"{cur} {s}".strip()
            continue
        if len(cur) + len(p) > max_chars and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}".strip()
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) > 80]


def render_png(doc: fitz.Document, pdf_page: int, zoom: float = 1.6) -> bytes:
    return doc[pdf_page - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


def outline_usable(specs: list[ChapterSpec], page_count: int) -> bool:
    """Bookmarks are only trusted if they describe a real chapter structure."""
    learn = [c for c in specs if c.kind in ("chapter", "appendix")]
    if len(learn) < 2:
        return False
    if max(c.pdf_end - c.pdf_start + 1 for c in learn) > 0.6 * page_count:
        return False
    titles = [c.title.lower() for c in learn]
    return len(set(titles)) >= 0.7 * len(titles)


def heading_title(text: str) -> str | None:
    """A plausible chapter title from the first lines of its opening page."""
    for line in [l.strip() for l in text.splitlines() if l.strip()][:8]:
        if len(line) >= 4 and re.search(r"[A-Za-z]{3}", line) and not re.fullmatch(r"[\divxlc.\-\s]+", line, re.I):
            return line[:120]
    return None


def chapters_from_bookmark_positions(doc: fitz.Document, texts: list[str]) -> list[ChapterSpec]:
    """Bookmarks with useless titles (e.g. source file names) still mark where chapters start."""
    raw = [(lvl, page) for lvl, _, page in doc.get_toc(simple=True) if page and page > 0]
    if not raw:
        return []
    top = min(lvl for lvl, _ in raw)
    starts = sorted({p for lvl, p in raw if lvl == top})
    if len(starts) < 3:
        return []
    specs = []
    for j, start in enumerate(starts):
        end = starts[j + 1] - 1 if j + 1 < len(starts) else doc.page_count
        title = heading_title(texts[start - 1]) or f"Part {j + 1}"
        specs.append(ChapterSpec(title=title, pdf_start=start, pdf_end=max(start, end), kind=kind_for(title),
                                 check_note="Title taken from the first line of the page — check it."))
    return specs


CHAPTER_HEAD = re.compile(r"^\s*(chapter|unit|lesson|part)\s*[-:.]?\s*(\d+|[ivxlc]+)\b[\s:.\-]*(.*)$", re.I)


def chapters_from_headings(texts: list[str]) -> list[ChapterSpec]:
    """Pages whose first lines start with 'Chapter N' (or Unit/Lesson/Part)."""
    found = []
    for i, text in enumerate(texts):
        lines = [l.strip() for l in text.splitlines() if l.strip()][:3]
        for k, line in enumerate(lines):
            m = CHAPTER_HEAD.match(line)
            if m:
                rest = m.group(3).strip() or (lines[k + 1] if k + 1 < len(lines) else "")
                found.append((i + 1, f"{m.group(1).title()} {m.group(2)}{': ' + rest if rest else ''}"[:200]))
                break
    # Ignore repeats (running headers) by keeping the first page for each title.
    seen, starts = set(), []
    for p, t in found:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            starts.append((p, t))
    if len(starts) < 3:
        return []
    return [ChapterSpec(title=t, pdf_start=p, pdf_end=(starts[j + 1][0] - 1 if j + 1 < len(starts) else len(texts)))
            for j, (p, t) in enumerate(starts)]


def title_from_filename(filename: str) -> str:
    """'principles-economics_3e.pdf' -> 'Principles Economics 3e'."""
    import os
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    if MACHINE_NAME.match(stem.strip()):
        return "Untitled book"  # named from the document's own heading once it has been read
    words = stem.replace("_", " ").replace("-", " ").split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words)[:300] or "Untitled book"
