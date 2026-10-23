"""Run the production chapter detector over real PDFs and print what it found.

    python -m tests.structure_corpus DIR [--strip]      # --strip also re-runs each file with its bookmarks removed

Uses the real model-backed contents reader (needs AWS credentials with Bedrock access).
"""
import argparse
import glob
import os
import time

import fitz

from app import pdf, structure


def analyze(doc: fitz.Document) -> dict:
    t0 = time.time()
    texts = [pdf.clean(page.get_text("text")) for page in doc]
    labels = [page.get_label() or None for page in doc]
    offset = pdf.detect_offset(labels, texts)
    specs, source = structure.detect(doc, texts, offset)
    learn = [s for s in specs if s.kind in ("chapter", "appendix")]
    sizes = [s.pdf_end - s.pdf_start + 1 for s in learn] or [0]
    warnings = []
    if not specs:
        warnings.append("no structure: user must mark chapters")
    if learn and max(sizes) > 150:
        warnings.append(f"largest chapter {max(sizes)} pages")
    if len(learn) > 60:
        warnings.append(f"{len(learn)} chapters (very granular)")
    return {"pages": doc.page_count, "scanned": pdf.is_scanned(doc), "offset": offset, "source": source,
            "chapters": len(learn), "rows": len(specs), "sizes": (min(sizes), max(sizes)), "specs": specs,
            "warnings": warnings, "secs": time.time() - t0}


def report(name: str, r: dict) -> None:
    print(f"\n=== {name}: {r['pages']} pages, scanned={r['scanned']}, offset={r['offset']}, "
          f"source={r['source']}, {r['chapters']} chapters ({r['rows']} rows), "
          f"chapter size {r['sizes'][0]}–{r['sizes'][1]} pages, {r['secs']:.1f}s")
    for w in r["warnings"]:
        print(f"    ! {w}")
    for s in r["specs"][:6] + ([None] if len(r["specs"]) > 9 else []) + r["specs"][-3:] if len(r["specs"]) > 9 else r["specs"]:
        if s is None:
            print("    ...")
            continue
        kids = f" [{len(s.children)} subsections]" if s.children else ""
        print(f"    {s.kind:8} p{s.pdf_start:>4}-{s.pdf_end:<4} {s.title[:70]}{kids}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--strip", action="store_true", help="also test each file with bookmarks removed")
    args = ap.parse_args()
    for path in sorted(glob.glob(os.path.join(args.dir, "*.pdf"))):
        name = os.path.basename(path)
        doc = fitz.open(path)
        report(name, analyze(doc))
        if args.strip and doc.get_toc():
            doc.set_toc([])
            report(name + " (bookmarks removed)", analyze(doc))
        doc.close()


if __name__ == "__main__":
    main()
