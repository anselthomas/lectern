"""Chapter detection across many book structures. Runs offline: the model-backed contents reader is stubbed.

    docker compose run --rm --no-deps api sh -c "pip install --user -q pytest && python -m pytest -q tests/test_structure.py"
"""
import pytest

from app import pdf, structure
from tests.corpus import Case, cases

CASES = cases()


def analyze(case: Case, read_contents=None):
    """Mirror the worker's ingest: open, extract texts/labels, detect offset and structure."""
    doc = pdf.open_pdf_bytes(case.pdf, case.password)
    texts = [pdf.clean(page.get_text("text")) for page in doc]
    labels = [page.get_label() or None for page in doc]
    offset = pdf.detect_offset(labels, texts)
    specs, source = structure.detect(doc, texts, offset, read_contents=read_contents or (lambda t, o: []))
    scanned = pdf.is_scanned(doc)
    n = doc.page_count
    doc.close()
    return specs, source, offset, scanned, n


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_structure(case: Case):
    specs, source, offset, scanned, n = analyze(case)
    learn = [s for s in specs if s.kind in ("chapter", "appendix")]
    assert source == case.source, f"source {source!r} != {case.source!r}: {[(s.title, s.pdf_start) for s in specs]}"
    if case.chapters is not None:
        assert len(learn) == case.chapters, [(s.title, s.kind, s.pdf_start, s.pdf_end) for s in specs]
    got = [s.title.lower() for s in learn]
    if case.titles and len(case.titles) == len(got):
        assert all(w.lower() in g for w, g in zip(case.titles, got)), got
    elif case.titles:
        assert case.titles[0].lower() in got[0] and case.titles[-1].lower() in got[-1], got
    if case.starts:
        assert [s.pdf_start for s in learn] == case.starts
    if case.offset is not None:
        assert offset == case.offset
    assert scanned == case.scanned


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_outline_invariants(case: Case):
    """Whatever the input, the outline is sorted, contiguous, non-overlapping and inside the document."""
    specs, _, _, _, n = analyze(case)
    prev_end = 0
    for s in specs:
        assert 1 <= s.pdf_start <= s.pdf_end <= n, (s.title, s.pdf_start, s.pdf_end, n)
        assert s.pdf_start > prev_end, "overlap"
        assert prev_end == 0 or s.pdf_start == prev_end + 1, f"gap before {s.title!r}"
        assert s.title.strip()
        prev_end = s.pdf_end


def test_password_required():
    case = next(c for c in CASES if c.password)
    with pytest.raises(PermissionError):
        pdf.open_pdf_bytes(case.pdf, None)
    with pytest.raises(PermissionError):
        pdf.open_pdf_bytes(case.pdf, "wrong")


def test_model_contents_reader_groups_sections(monkeypatch):
    """Sections that contain chapters become one Lectern chapter each, with the chapters as section hints."""
    case = next(c for c in CASES if c.name == "page_n_bookmarks_with_contents")
    reply = {"has_contents": True, "entries": [
        {"title": "Section 1 Introduction", "printed_page": 1, "children": [
            {"title": "1-1 Pharmacy", "printed_page": 1}, {"title": "1-2 Pharmacology", "printed_page": 7}]},
        {"title": "Section 2 Vehicles", "printed_page": 13, "children": [
            {"title": "2-1 Solid", "printed_page": 13}, {"title": "2-2 Liquid", "printed_page": 27}]},
        {"title": "Section 3 Standards", "printed_page": 41, "children": []},
    ]}
    monkeypatch.setattr(structure.llm, "call_json", lambda **kw: (reply, None))
    specs, source, *_ = analyze(case, read_contents=structure.chapters_from_contents)
    assert source == "contents"
    assert [s.title for s in specs] == ["Section 1 Introduction", "Section 2 Vehicles", "Section 3 Standards"]
    assert [s.pdf_start for s in specs] == [7, 19, 47]
    assert [c["title"] for c in specs[0].children] == ["1-1 Pharmacy", "1-2 Pharmacology"]


def test_model_contents_reader_flattens_long_sections(monkeypatch):
    """Very long sections are split back into their chapters so lessons stay a manageable size."""
    texts = ["Contents"] + ["x " * 50] * 399
    reply = {"has_contents": True, "entries": [
        {"title": "Part A", "printed_page": 2, "children": [{"title": "A1", "printed_page": 2}, {"title": "A2", "printed_page": 90}]},
        {"title": "Part B", "printed_page": 200, "children": [{"title": "B1", "printed_page": 200}, {"title": "B2", "printed_page": 300}]},
    ]}
    monkeypatch.setattr(structure.llm, "call_json", lambda **kw: (reply, None))
    specs = structure.chapters_from_contents(texts, 0)
    assert [s.title for s in specs] == ["A1", "A2", "B1", "B2"]


def test_failing_strategy_does_not_break_detection():
    case = next(c for c in CASES if c.name == "chapter_headings_only")

    def boom(texts, offset):
        raise RuntimeError("model unavailable")

    specs, source, *_ = analyze(case, read_contents=boom)
    assert source == "chapter headings" and len(specs) == 4


@pytest.mark.parametrize("title,junk", [
    ("Pharmacy 9-63.pdf", True), ("Prepage.pmd", True), ("Page 1", True), ("p. iv", True), ("Untitled", True),
    ("Microsoft Word - final_v2", True), ("12", True), ("Chapter 1 Units", False), ("Vehicles", False),
    ("University Physics Volume 1", False),
])
def test_junk_titles(title, junk):
    assert pdf.junk_title(title) is junk


@pytest.fixture(autouse=True)
def _full_length_rules(request, monkeypatch):
    """Synthetic books are short; test structure rules as if they were full-length unless a test opts out."""
    if "short_doc" not in request.node.name:
        monkeypatch.setattr(structure, "SHORT_DOC_PAGES", 0)


def test_short_doc_limit_keeps_long_books_split():
    case = next(c for c in CASES if c.name == "clean_bookmarks")  # 60 pages: above the limit
    specs, source, *_ = analyze(case)
    assert len([s for s in specs if s.kind == "chapter"]) == 4


def test_short_doc_paper_collapses(monkeypatch):
    case = next(c for c in CASES if c.name == "out_of_order_bookmarks")  # 45 pages
    monkeypatch.setattr(structure, "SHORT_DOC_PAGES", 50)
    specs, source, *_ = analyze(case)
    assert len(specs) == 1 and specs[0].title == structure.WHOLE_DOCUMENT
    assert [c["title"] for c in specs[0].children] == ["Chapter 1 Alpha", "Chapter 2 Beta", "Chapter 3 Gamma"]


def test_short_doc_without_structure_is_one_chapter(monkeypatch):
    monkeypatch.setattr(structure, "SHORT_DOC_PAGES", 40)
    case = next(c for c in CASES if c.name == "no_structure")  # 30 plain pages
    specs, source, *_ = analyze(case)
    assert source == "whole document" and specs[0].pdf_start == 1 and specs[0].pdf_end == 30


def test_section_hints_from_contents_lines():
    """Chapters found without sub-entries get the contents lines inside their range as section hints."""
    contents = "Contents\n\nSection 1 Introduction\n" + "\n".join(f"{t} ........ {p}" for t, p in [
        ("Pharmacy and Pharmacopoeia", 3), ("Pharmacology", 9), ("Sources of Drugs", 15),
        ("Vehicles in General", 31), ("Solid Vehicles", 37), ("Liquid Vehicles", 44)])
    from tests.corpus import body, make
    pages = ["Title", contents] + body({}, 58)
    case = Case("hints", make(pages, number_from=3), "contents")
    doc = pdf.open_pdf_bytes(case.pdf)
    texts = [pdf.clean(p.get_text("text")) for p in doc]
    offset = pdf.detect_offset([None] * doc.page_count, texts)
    assert offset == 2
    specs = [pdf.ChapterSpec("Section 1 Introduction", 5, 32), pdf.ChapterSpec("Section 2 Vehicles", 33, 60)]
    structure.attach_section_hints(specs, texts, offset)
    assert [c["title"] for c in specs[0].children] == ["Pharmacy and Pharmacopoeia", "Pharmacology", "Sources of Drugs"]
    assert [c["pdf_page"] for c in specs[1].children] == [33, 39, 46]
