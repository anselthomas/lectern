"""PDF reading: text, page labels, bookmarks, printed-page offset, OCR and chunking. Pages are 1-based."""
import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # PyMuPDF

BACK_MATTER = re.compile(r"^(index|glossary|references|bibliography|answer key|answers|credits|about the authors?)\b", re.I)
FRONT_MATTER = re.compile(r"^(preface|contents|table of contents|foreword|acknowledg|copyright|title page|cover|dedication|about (this|the) book)\b", re.I)
APPENDIX = re.compile(r"^appendix\b", re.I)


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
    toc = [(lvl, title.strip(), page) for lvl, title, page in doc.get_toc(simple=True) if page and page > 0]
    if not toc:
        return []
    levels = Counter(lvl for lvl, _, _ in toc)
    top = min(levels)
    # Books split into a few "Parts" put chapters one level down.
    if levels[top] < 3 and levels.get(top + 1, 0) >= 3:
        top += 1
    tops = [(i, t, p) for i, (lvl, t, p) in enumerate(toc) if lvl == top]
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
        for cand in lines[:2] + lines[-2:]:
            if re.fullmatch(r"\d{1,4}", cand):
                votes[(i + 1) - int(cand)] += 1
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
