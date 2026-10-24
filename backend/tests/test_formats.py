"""Recognising uploads by their bytes and converting the formats PyMuPDF handles (LibreOffice ones run on the server)."""
import io
import zipfile

import fitz
import pytest

from app import formats


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("head,name,kind", [
    (b"%PDF-1.7\n...", "1000034521", "pdf"),
    (b"PK\x03\x04rest", "x.docx", "zip"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 20, "old.doc", "ole"),
    (b"{" + b"\\" + b"rtf1 hello}", "a.rtf", "rtf"),
    (b"\xff\xd8\xff\xe0JFIF", "IMG_2041", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "page.png", "png"),
    (b"<!DOCTYPE html><html><body>hi</body></html>", "page", "html"),
    (b"# Chapter 1\n\nSome notes about cells.", "notes.md", "md"),
    (b"Chapter 1\n\nPlain text notes about receptors.", "notes", "txt"),
    (b"\x7fELF\x02\x01\x01" + bytes(range(256)) * 4, "program", None),
])
def test_sniff_by_content_not_name(head, name, kind):
    assert formats.sniff(head, name) == kind


def test_zip_documents_are_told_apart(tmp_path):
    cases = {"docx": {"[Content_Types].xml": b"x", "word/document.xml": b"x"},
             "pptx": {"[Content_Types].xml": b"x", "ppt/presentation.xml": b"x"},
             "epub": {"mimetype": b"application/epub+zip", "OEBPS/a.xhtml": b"x"},
             "odt": {"mimetype": b"application/vnd.oasis.opendocument.text", "content.xml": b"x"}}
    for kind, files in cases.items():
        p = tmp_path / f"f{kind}"
        p.write_bytes(zip_bytes(files))
        assert formats.kind_of(str(p), "1000034521") == kind
    p = tmp_path / "archive"
    p.write_bytes(zip_bytes({"photo.txt": b"x", "data.bin": b"y"}))
    with pytest.raises(formats.ConversionError, match="ZIP archive"):
        formats.kind_of(str(p), "stuff.zip")


def test_image_becomes_a_one_page_pdf(tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 600), False)
    pix.clear_with(255)
    src = tmp_path / "photo"
    src.write_bytes(pix.tobytes("png"))
    out, kind = formats.to_pdf(str(src), "IMG_2041", str(tmp_path))
    assert kind == "png" and fitz.open(out).page_count == 1


def test_epub_keeps_its_table_of_contents(tmp_path):
    chap = lambda n: (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>C{n}</title></head>'
                      f'<body><h1>Chapter {n}</h1>' + "<p>Receptors convert stimuli into signals.</p>" * 60 + "</body></html>").encode()
    opf = b'''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test Book</dc:title><dc:identifier id="id">x</dc:identifier><dc:language>en</dc:language></metadata>
      <manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/></manifest>
      <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine></package>'''
    ncx = b'''<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>Test Book</text></docTitle>
      <navMap><navPoint id="n1" playOrder="1"><navLabel><text>Chapter 1</text></navLabel><content src="c1.xhtml"/></navPoint>
      <navPoint id="n2" playOrder="2"><navLabel><text>Chapter 2</text></navLabel><content src="c2.xhtml"/></navPoint></navMap></ncx>'''
    nav = (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
           b'<nav epub:type="toc"><ol><li><a href="c1.xhtml">Chapter 1</a></li><li><a href="c2.xhtml">Chapter 2</a></li></ol></nav></body></html>')
    container = b'''<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    src = tmp_path / "book"
    src.write_bytes(zip_bytes({"mimetype": b"application/epub+zip", "META-INF/container.xml": container,
                               "OEBPS/book.opf": opf, "OEBPS/nav.xhtml": nav, "OEBPS/toc.ncx": ncx, "OEBPS/c1.xhtml": chap(1), "OEBPS/c2.xhtml": chap(2)}))
    out, kind = formats.to_pdf(str(src), "book.epub", str(tmp_path))
    doc = fitz.open(out)
    assert kind == "epub" and doc.page_count >= 2
    assert [t for _, t, _ in doc.get_toc()] == ["Chapter 1", "Chapter 2"]
    assert "Receptors convert" in doc[0].get_text()


def test_plain_text_headings_survive_into_html():
    html = formats.text_to_html("Chapter 1 Receptors\n\nThey sense things.\nLine two.\n\nChapter 2 Pathways\n\nMore.", False)
    assert "<h1>Chapter 1 Receptors</h1>" in html and "<h1>Chapter 2 Pathways</h1>" in html
    assert "<p>They sense things.<br/>Line two.</p>" in html
    md = formats.text_to_html("# Receptors\n\n| a | b |\n|---|---|\n| 1 | 2 |", True)
    assert "<h1>Receptors</h1>" in md and "<table>" in md
