"""Synthetic PDFs covering the book structures we've seen (and the broken ones). Each case knows its right answer."""
import random
from dataclasses import dataclass, field

import fitz

WORDS = ("energy force motion field vector mass charge wave pressure heat drug potency remedy dilution sample "
         "method result theory measure system process value change rate law model data structure analysis").split()


def para(seed: int, n: int = 90) -> str:
    rnd = random.Random(seed)
    words = [rnd.choice(WORDS) for _ in range(n)]
    return (" ".join(words).capitalize() + ".")


@dataclass
class Case:
    name: str
    pdf: bytes
    source: str | None                     # expected detection source (None = nothing found)
    chapters: int | None = None            # expected number of chapter/appendix entries
    titles: list[str] = field(default_factory=list)  # substrings expected in titles, in order
    starts: list[int] = field(default_factory=list)  # expected pdf_start of learnable entries, in order
    offset: int | None = None              # expected printed-page offset (printed p = pdf p - offset)
    scanned: bool = False
    password: str | None = None


def make(pages: list[str], toc=None, labels=None, number_from: int | None = None, image_only=False,
         password: str | None = None) -> bytes:
    doc = fitz.open()
    for i, text in enumerate(pages):
        page = doc.new_page(width=595, height=842)
        if image_only:
            shape = page.new_shape()
            for k in range(20):
                shape.draw_rect(fitz.Rect(40, 40 + k * 38, 555, 60 + k * 38))
            shape.finish(fill=(0.85, 0.85, 0.85))
            shape.commit()
        elif text:
            page.insert_textbox(fitz.Rect(50, 50, 545, 780), text, fontsize=10)
        if number_from is not None and i + 1 >= number_from:
            page.insert_text((290, 815), str(i + 2 - number_from), fontsize=9)  # printed page number footer
    if toc:
        doc.set_toc(toc)
    if labels:
        doc.set_page_labels(labels)
    kw = {}
    if password:
        kw = dict(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "-owner")
    data = doc.tobytes(garbage=1, **kw)
    doc.close()
    return data


def body(chapter_starts: dict[int, str], total: int, offset_pages: int = 0) -> list[str]:
    """Page texts: chapter opener pages start with the given heading; other pages are prose."""
    out = []
    for i in range(1, total + 1):
        head = chapter_starts.get(i)
        out.append((head + "\n\n" if head else "") + para(i) + "\n\n" + para(i + 1000))
    return out


def cases() -> list[Case]:
    cs: list[Case] = []

    # 1. Clean level-1 bookmarks with front and back matter.
    starts = [5, 17, 29, 41]
    pages = body({p: f"Chapter {k + 1} Topic {k + 1}" for k, p in enumerate(starts)}, 60)
    toc = [[1, "Preface", 2]] + [[1, f"Chapter {k + 1} Topic {k + 1}", p] for k, p in enumerate(starts)] + [[1, "Index", 55]]
    cs.append(Case("clean_bookmarks", make(pages, toc), "bookmarks", 4, ["Chapter 1", "Chapter 4"], starts))

    # 2. Parts at level 1, chapters at level 2 -> chapters are the units.
    toc = [[1, "Part I Mechanics", 3], [2, "Chapter 1 Motion", 3], [2, "Chapter 2 Forces", 15], [2, "Chapter 3 Energy", 27],
           [1, "Part II Waves", 39], [2, "Chapter 4 Oscillations", 39], [2, "Chapter 5 Sound", 51]]
    cs.append(Case("parts_then_chapters", make(body({}, 62), toc), "bookmarks", 5, ["Motion", "Sound"], [3, 15, 27, 39, 51]))

    # 3. Bookmarks named after source files (the DD Banerjee case) + chapter title on each start page, no contents.
    starts = [3, 20, 41, 63]
    names = ["Introduction to Pharmacy", "Vehicles", "Laboratory Methods", "Metrology"]
    pages = body({p: n for p, n in zip(starts, names)}, 80)
    toc = [[1, f"Pharmacy {p}-{p + 15}.pdf", p] for p in starts]
    cs.append(Case("file_named_bookmarks", make(pages, toc), "bookmark positions", 4, names, starts))

    # 4. Junk "Page 1" bookmarks + a real contents page and printed numbers starting at pdf page 7 (offset 6).
    contents = "Contents\n\n" + "\n".join(f"{t} ........ {p}" for t, p in
                                          [("Introduction", 1), ("Solid Vehicles", 13), ("Liquid Vehicles", 27), ("Standardisation", 41)])
    pages = ["Title page", "Copyright 2006", contents, para(3), para(4), para(5)] + body({}, 54)
    toc = [[1, "Page 1", 1], [1, "Page 1", 60]]
    cs.append(Case("page_n_bookmarks_with_contents", make(pages, toc, number_from=7), "contents", 4,
                   ["Introduction", "Standardisation"], [7, 19, 33, 47], offset=6))

    # 5. No bookmarks, contents page with dotted leaders, roman front matter labels.
    contents = "Table of Contents\n\n" + "\n".join(f"{k}. {t} .... {p}" for k, (t, p) in enumerate(
        [("Scope and Scale", 1), ("Units", 9), ("Dimensional Analysis", 18), ("Significant Figures", 30)], start=1))
    pages = ["Cover", "i", contents, "Preface\n\n" + para(7)] + body({}, 46)
    labels = [{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
              {"startpage": 4, "prefix": "", "style": "D", "firstpagenum": 1}]
    cs.append(Case("contents_roman_labels", make(pages, labels=labels), "contents", 4,
                   ["Scope", "Significant"], [5, 13, 22, 34], offset=4))

    # 6. No bookmarks, no contents, "CHAPTER N" headings on opener pages (plus running headers that repeat).
    starts = [2, 14, 26, 38]
    pages = []
    for i in range(1, 50):
        k = sum(1 for s in starts if s <= i)
        if i in starts:
            pages.append(f"CHAPTER {k}\nThe {WORDS[k]} of things\n\n" + para(i))
        else:
            pages.append(f"{WORDS[k].title()} handbook   {i}\n\n" + para(i))
    cs.append(Case("chapter_headings_only", make(pages), "chapter headings", 4, ["Chapter 1", "Chapter 4"], starts))

    # 7. Nothing to go on: plain prose, no bookmarks, no contents, no headings.
    cs.append(Case("no_structure", make(body({}, 30)), None, 0))

    # 8. One bookmark covering the whole book -> rejected, falls through to headings.
    starts = [1, 11, 21]
    pages = []
    for i in range(1, 31):
        unit = sum(1 for s in starts if s <= i)
        pages.append((f"Unit {unit}: Part {unit}\n\n" if i in starts else "") + para(i))
    cs.append(Case("single_giant_bookmark", make(pages, [[1, "Whole book", 1]]), "chapter headings", 3, ["Unit 1", "Unit 3"], starts))

    # 9. Duplicate bookmark titles -> titles rejected, but their positions still mark chapter starts.
    toc = [[1, "Section", p] for p in (1, 8, 15, 22)]
    cs.append(Case("duplicate_bookmark_titles", make(body({}, 28), toc), "bookmark positions", 4, starts=[1, 8, 15, 22]))

    # 10. Bookmarks out of order -> sorted, contiguous ranges.
    toc = [[1, "Chapter 3 Gamma", 31], [1, "Chapter 1 Alpha", 3], [1, "Chapter 2 Beta", 17]]
    cs.append(Case("out_of_order_bookmarks", make(body({}, 45), toc), "bookmarks", 3, ["Alpha", "Beta", "Gamma"], [3, 17, 31]))

    # 11. Tiny one-page document.
    cs.append(Case("single_page", make([para(1)]), None, 0))

    # 12. Scanned (image-only) pages.
    cs.append(Case("scanned_image_only", make([""] * 12, image_only=True), None, 0, scanned=True))

    # 13. Password-protected PDF with clean bookmarks.
    toc = [[1, "Chapter 1 One", 1], [1, "Chapter 2 Two", 11], [1, "Chapter 3 Three", 21]]
    cs.append(Case("password_protected", make(body({}, 30), toc, password="s3cret"), "bookmarks", 3,
                   ["One", "Three"], [1, 11, 21], password="s3cret"))

    # 14. Appendices and an answer key mixed in with chapters.
    toc = [[1, "1 Basics", 2], [1, "2 Methods", 12], [1, "Appendix A Tables", 22], [1, "Answer Key", 26], [1, "Index", 30]]
    cs.append(Case("appendix_and_back_matter", make(body({}, 32), toc), "bookmarks", 3, ["Basics", "Methods", "Appendix"], [2, 12, 22]))

    # 15. Empty and unicode-heavy pages mixed in (shouldn't crash anything).
    pages = body({}, 20)
    pages[3] = ""
    pages[7] = "Ünïcødé — “quotes” • bullets … ∑∫√ 数学 物理 " * 20
    toc = [[1, "Chapter 1 Ünïcødé", 1], [1, "Chapter 2 Ascii", 10]]
    cs.append(Case("unicode_and_empty_pages", make(pages, toc), "bookmarks", 2, ["Ünïcødé", "Ascii"], [1, 10]))
    return cs
