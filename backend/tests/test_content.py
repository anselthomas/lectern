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


def test_too_few_hints_fall_back_to_model():
    assert sections_from_hints(chapter(1, 40, [{"title": "Only one", "pdf_page": 1}]), []) is None
    assert sections_from_hints(chapter(1, 40, [{"title": "Out of range", "pdf_page": 90}, {"title": "x", "pdf_page": 95}]), []) is None


def test_short_subsections_group_into_lessons_without_losing_titles():
    # Think Python ch. 1: seven subsections in eight pages, several sharing a page.
    hints = [("What is a program?", 23), ("Running Python", 24), ("The first program", 25), ("Arithmetic operators", 25),
             ("Values and types", 26), ("Formal and natural languages", 27), ("Debugging", 29), ("Glossary", 29),
             ("Exercises", 30)]
    ch = chapter(23, 30, [{"title": t, "pdf_page": p} for t, p in hints])
    secs = normalise_sections(sections_from_hints(ch, []), 23, 30)
    assert [(s["title"], s["pdf_start"], s["pdf_end"]) for s in secs] == [
        ("What is a program? · Running Python", 23, 24),
        ("The first program · Arithmetic operators · Values and types", 25, 26),
        ("Formal and natural languages", 27, 28), ("Debugging", 29, 30)]


def test_many_subsections_cap_the_number_of_lessons():
    many = [{"title": f"Part {i}", "pdf_page": 1 + i * 3} for i in range(12)]
    secs = sections_from_hints(chapter(1, 40, many), [])
    assert 2 <= len(secs) <= 8
    assert all(f"Part {i}" in " ".join(s["title"] for s in secs) for i in range(12))
