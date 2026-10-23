"""Section planning from the book's own subdivisions (no model calls)."""
from types import SimpleNamespace

from app.content import normalise_sections, sections_from_hints


def chapter(start, end, children):
    return SimpleNamespace(pdf_start=start, pdf_end=end, outline_children=children)


def test_contents_hints_become_exact_sections():
    ch = chapter(19, 82, [{"title": "Pharmacy and Pharmacopoeia", "pdf_page": 19}, {"title": "Pharmacology", "pdf_page": 25},
                          {"title": "Sources of Homoeopathic Drugs", "pdf_page": 31},
                          {"title": "Process of Collection of Drug Substances", "pdf_page": 61},
                          {"title": "Preservation of Drugs and Potencies", "pdf_page": 67},
                          {"title": "Standardisation of Drugs", "pdf_page": 71}])
    model = [{"title": "Pharmacology basics", "summary": "What pharmacology covers."}]
    secs = normalise_sections(sections_from_hints(ch, model), 19, 82)
    assert [s["pdf_start"] for s in secs] == [19, 25, 31, 61, 67, 71]
    assert secs[-1]["pdf_end"] == 82 and secs[2]["pdf_end"] == 60
    assert secs[1]["summary"] == "What pharmacology covers."


def test_review_matter_and_one_page_intro_fold_in():
    ch = chapter(17, 52, [{"title": "Introduction", "pdf_page": 17}, {"title": "1.1 The Scope and Scale of Physics", "pdf_page": 18},
                          {"title": "1.2 Units and Standards", "pdf_page": 24}, {"title": "1.3 Unit Conversion", "pdf_page": 30},
                          {"title": "Key Terms", "pdf_page": 45}, {"title": "Summary", "pdf_page": 46},
                          {"title": "Problems", "pdf_page": 48}])
    secs = normalise_sections(sections_from_hints(ch, []), 17, 52)
    assert [s["title"] for s in secs] == ["The Scope and Scale of Physics", "Units and Standards", "Unit Conversion"]
    assert secs[0]["pdf_start"] == 17 and secs[-1]["pdf_end"] == 52


def test_too_few_or_too_many_hints_fall_back_to_model():
    assert sections_from_hints(chapter(1, 40, [{"title": "Only one", "pdf_page": 1}]), []) is None
    many = [{"title": f"Part {i}", "pdf_page": 1 + i * 3} for i in range(12)]
    assert sections_from_hints(chapter(1, 40, many), []) is None
    assert sections_from_hints(chapter(1, 40, [{"title": "Out of range", "pdf_page": 90}, {"title": "x", "pdf_page": 95}]), []) is None
