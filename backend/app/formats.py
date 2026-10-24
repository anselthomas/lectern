"""Every upload becomes a PDF, so pages, chapters, OCR, citations and page images all follow one path.

Formats are recognised by their bytes, not the file name (phones often send names like "1000034521"):

- PDF                                   used as is
- Word, OpenDocument, RTF, WordPerfect, PowerPoint, Excel, Apple Pages/Keynote/Numbers, HTML
                                        LibreOffice (headless) converts; headings become PDF bookmarks
- EPUB, MOBI, FB2, XPS, CBZ, SVG, images (JPEG, PNG, TIFF, BMP, GIF, WebP)
                                        PyMuPDF converts; an e-book's table of contents is kept as bookmarks
- Plain text and Markdown               turned into HTML (headings kept), then LibreOffice
"""
import html
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile

import fitz

log = logging.getLogger("lectern.formats")

CONVERT_TIMEOUT_S = 300
FITZ_TYPES = {"epub", "mobi", "fb2", "xps", "oxps", "cbz", "svg", "jpg", "png", "gif", "bmp", "tiff", "webp"}
NAMES = {"pdf": "PDF", "docx": "Word", "doc": "Word", "odt": "OpenDocument", "rtf": "RTF", "wpd": "WordPerfect",
         "pptx": "PowerPoint", "ppt": "PowerPoint", "odp": "OpenDocument slides", "xlsx": "Excel", "xls": "Excel",
         "ods": "OpenDocument spreadsheet", "pages": "Pages", "key": "Keynote", "numbers": "Numbers",
         "html": "web page", "epub": "EPUB", "mobi": "Kindle (MOBI)", "fb2": "FictionBook", "xps": "XPS",
         "oxps": "XPS", "cbz": "comic archive", "svg": "SVG", "txt": "text", "md": "Markdown", "jpg": "image",
         "png": "image", "gif": "image", "bmp": "image", "tiff": "image", "webp": "image"}
# Extensions the upload picker offers; the bytes decide in the end.
ACCEPT = sorted({".pdf", ".docx", ".doc", ".docm", ".dotx", ".odt", ".ott", ".rtf", ".wpd", ".pptx", ".ppt", ".ppsx",
                 ".odp", ".xlsx", ".xls", ".ods", ".csv", ".pages", ".key", ".numbers", ".html", ".htm", ".xhtml",
                 ".epub", ".mobi", ".azw", ".azw3", ".fb2", ".xps", ".oxps", ".cbz", ".svg", ".txt", ".text", ".md",
                 ".markdown", ".rst", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"})


class ConversionError(Exception):
    """Shown to the learner, so the message is written for them."""


def ext_of(filename: str) -> str:
    e = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return {"jpeg": "jpg", "tif": "tiff", "htm": "html", "xhtml": "html", "markdown": "md", "text": "txt",
            "rst": "txt", "azw": "mobi", "azw3": "mobi", "docm": "docx", "dotx": "docx", "ott": "odt",
            "ppsx": "pptx", "csv": "txt"}.get(e, e)


def _zip_kind(z: zipfile.ZipFile) -> str | None:
    names = set(z.namelist())
    if "mimetype" in names:
        mt = z.read("mimetype")[:100].decode("ascii", "ignore").strip()
        return {"application/epub+zip": "epub", "application/vnd.oasis.opendocument.text": "odt",
                "application/vnd.oasis.opendocument.presentation": "odp",
                "application/vnd.oasis.opendocument.spreadsheet": "ods"}.get(mt)
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if "FixedDocumentSequence.fdseq" in names or any(n.startswith("Documents/") for n in names):
        return "xps"
    if "Index/Document.iwa" in names or "index.xml" in names or any(n.startswith("Index/") for n in names):
        return "pages"  # iWork: LibreOffice tells Pages, Keynote and Numbers apart itself
    if names and all(re.search(r"\.(jpe?g|png|gif|webp)$", n, re.I) or n.endswith("/") for n in names):
        return "cbz"
    return None


def sniff(head: bytes, filename: str = "") -> str | None:
    """A coarse format from the first bytes (enough to accept or refuse an upload), or None if unsupported."""
    ext = ext_of(filename)
    if b"%PDF" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"   # legacy Word, PowerPoint or Excel
    if head.lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"BM"):
        return "bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[60:68] == b"BOOKMOBI":
        return "mobi"
    if head.startswith(b"\xff\x57\x50\x43"):
        return "wpd"
    text = _decode(head)
    if text is None:
        return None
    low = text.lstrip().lower()
    if low.startswith("<?xml") and "<svg" in low[:2000] or low.startswith("<svg"):
        return "svg"
    if "<fictionbook" in low[:2000]:
        return "fb2"
    if low.startswith(("<!doctype html", "<html")) or "<html" in low[:500]:
        return "html"
    return "md" if ext == "md" else "txt"


def _decode(data: bytes) -> str | None:
    """Text if the bytes look like a text file (UTF-8/UTF-16 or mostly printable Latin-1), else None."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "ignore")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start < len(data) - 4:  # a multi-byte character cut at the end of the sample is fine
            text = data.decode("latin-1")
        else:
            text = data[:e.start].decode("utf-8")
    if not text:
        return None
    controls = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t\f")
    return text if controls / len(text) < 0.01 else None


def kind_of(path: str, filename: str) -> str:
    """The exact format of a whole file, or ConversionError if it isn't one we can read."""
    with open(path, "rb") as f:
        head = f.read(8192)
    coarse = sniff(head, filename)
    if coarse is None:
        raise ConversionError("We can't read this kind of file. Upload a PDF, Word, PowerPoint, EPUB, text or image file.")
    if coarse == "zip":
        try:
            with zipfile.ZipFile(path) as z:
                kind = _zip_kind(z)
        except zipfile.BadZipFile as e:
            raise ConversionError("This file looks damaged (it isn't a complete document).") from e
        if kind is None:
            raise ConversionError("This is a ZIP archive, not a document. Unzip it and upload the document inside.")
        return kind
    if coarse == "ole":
        return ext_of(filename) if ext_of(filename) in ("doc", "ppt", "xls") else "doc"
    return coarse


def _soffice(src: str, outdir: str, infilter: str | None = None) -> str:
    profile = os.path.join(tempfile.gettempdir(), f"lo-profile-{uuid.uuid4().hex}")
    cmd = ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore", "--nologo",
           "--nodefault", "--nolockcheck"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", 'pdf:writer_pdf_Export:{"ExportBookmarks":{"type":"boolean","value":"true"}}',
            "--outdir", outdir, src]
    if not src.lower().endswith((".odt", ".doc", ".docx", ".rtf", ".wpd", ".html", ".txt")):
        cmd[-4] = "pdf"  # slides and spreadsheets have their own PDF export filters
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=CONVERT_TIMEOUT_S, text=True)
    except subprocess.TimeoutExpired as e:
        raise ConversionError("Converting this document took too long. Try saving it as a PDF and uploading that.") from e
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if done.returncode != 0 or not os.path.exists(out):
        log.warning("soffice failed (%s): %s %s", done.returncode, done.stdout[-500:], done.stderr[-500:])
        raise ConversionError("We couldn't convert this document. Try saving it as a PDF and uploading that.")
    return out


HEADING_LINE = re.compile(r"^\s*((chapter|part|section|unit|lesson|module|appendix)\s+[\w.]+\b.*|\d{1,2}(\.\d{1,2})*\s+[A-Z].{2,80})$", re.I)


def text_to_html(text: str, markdown_source: bool) -> str:
    """Markdown keeps its headings, lists and tables; plain text gets headings from lines like "Chapter 3 ..."
    and paragraphs from blank lines, so chapter detection has something to work with."""
    if markdown_source:
        import markdown
        body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    else:
        parts = []
        for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            if len(lines) == 1 and HEADING_LINE.match(lines[0]) and len(lines[0]) < 100:
                parts.append(f"<h1>{html.escape(lines[0].strip())}</h1>")
            else:
                parts.append("<p>" + "<br/>".join(html.escape(l) for l in lines) + "</p>")
        body = "\n".join(parts)
    return f'<!doctype html><html><head><meta charset="utf-8"></head><body>{body}</body></html>'


def to_pdf(path: str, filename: str, workdir: str) -> tuple[str, str]:
    """Convert the file at `path` to PDF inside `workdir`. Returns (pdf path, format)."""
    kind = kind_of(path, filename)
    if kind == "pdf":
        return path, kind
    if kind in FITZ_TYPES:
        try:
            src = fitz.open(path, filetype=kind)
            if src.is_reflowable:
                src.layout(width=595, height=842, fontsize=11)  # A4 pages for e-books
            out = fitz.open("pdf", src.convert_to_pdf())
            toc = src.get_toc(simple=True)
            if toc:
                out.set_toc([[lvl, title, min(max(page, 1), out.page_count)] for lvl, title, page in toc if page > 0])
            dest = os.path.join(workdir, "converted.pdf")
            out.save(dest, garbage=3, deflate=True)
            return dest, kind
        except Exception as e:
            raise ConversionError(f"We couldn't open this {NAMES.get(kind, kind)} file. It may be damaged or DRM-protected.") from e
    if kind in ("txt", "md"):
        with open(path, "rb") as f:
            text = _decode(f.read()) or ""
        if not text.strip():
            raise ConversionError("This file is empty.")
        src = os.path.join(workdir, "document.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(text_to_html(text, kind == "md"))
        return _soffice(src, workdir, infilter="HTML (StarWriter)"), kind
    src = os.path.join(workdir, f"document.{kind}")
    shutil.copyfile(path, src)
    return _soffice(src, workdir, infilter="HTML (StarWriter)" if kind == "html" else None), kind
