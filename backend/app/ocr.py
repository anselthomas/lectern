"""OCR for pages without a usable text layer: Amazon Textract first, Tesseract (local) as the fallback.

A page needs OCR when its text layer is missing or unreadable (scanned pages, photographed handouts, text drawn
as an image, broken font encodings) and it actually shows something. Truly blank pages are left blank.
"""
import concurrent.futures as cf
import logging
import time
from typing import Callable

import fitz
from botocore.exceptions import BotoCoreError, ClientError

from . import pdf, telemetry
from .aws import textract

log = logging.getLogger("lectern.ocr")

MIN_CHARS = 40
OCR_DPI = 200
TEXTRACT_MAX_BYTES = 9 * 1024 * 1024   # the synchronous API takes up to 10 MB per image
TEXTRACT_MAX_SIDE = 9000               # and at most 10,000 px on a side
PERMANENT = {"UnsupportedDocumentException", "BadDocumentException", "DocumentTooLargeException",
             "InvalidParameterException", "AccessDeniedException"}


def text_usable(text: str) -> bool:
    """False for an empty or garbage text layer: too short, "(cid:12)" glyph codes, replacement characters,
    or mostly symbols."""
    t = (text or "").strip()
    if len(t) < MIN_CHARS:
        return False
    if t.count("(cid:") >= 3 or t.count("�") > 0.02 * len(t):
        return False
    return sum(c.isalpha() for c in t) / len(t) >= 0.35


def has_visible_content(page: fitz.Page) -> bool:
    """Images or a fair amount of vector drawing: worth reading. A page with neither is blank."""
    try:
        return bool(page.get_images(full=False)) or len(page.get_drawings()) > 10
    except Exception:  # noqa: BLE001 - when in doubt, read it
        return True


def page_image(page: fitz.Page) -> bytes:
    """The page as an image Textract accepts: 200 dpi PNG, shrunk or JPEG-compressed if too large."""
    zoom = OCR_DPI / 72
    side = max(page.rect.width, page.rect.height) * zoom
    if side > TEXTRACT_MAX_SIDE:
        zoom *= TEXTRACT_MAX_SIDE / side
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = pix.tobytes("png")
    if len(img) > TEXTRACT_MAX_BYTES:
        img = pix.tobytes("jpeg", jpg_quality=85)
    while len(img) > TEXTRACT_MAX_BYTES and zoom > 0.8:
        zoom *= 0.75
        img = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("jpeg", jpg_quality=80)
    return img


def textract_text(img: bytes) -> str:
    """LINE blocks in Textract's reading order. Retries transient failures; raises on permanent ones."""
    delay = 1.0
    for attempt in range(4):
        try:
            blocks = textract().detect_document_text(Document={"Bytes": img})["Blocks"]
            return "\n".join(b["Text"] for b in blocks if b["BlockType"] == "LINE")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in PERMANENT or attempt == 3:
                raise
        except BotoCoreError:
            if attempt == 3:
                raise
        time.sleep(delay)
        delay *= 2
    return ""


def ocr_pages(doc: fitz.Document, numbers: list[int], progress: Callable[[int, int], None] | None = None,
              workers: int = 6) -> dict[int, tuple[str, str]]:
    """{pdf page (1-based): (text, source)} where source is textract, tesseract or failed.
    Pages are rendered here (PyMuPDF isn't thread-safe) and sent to Textract in parallel, a batch at a time
    so memory stays flat on long scanned books."""
    out: dict[int, tuple[str, str]] = {}
    fallback: list[int] = []
    started = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(numbers), workers * 2):
            batch = numbers[i:i + workers * 2]
            futures = {pool.submit(textract_text, page_image(doc[n - 1])): n for n in batch}
            for fut in cf.as_completed(futures):
                n = futures[fut]
                try:
                    out[n] = (fut.result(), "textract")
                except Exception as e:  # noqa: BLE001 - this page falls back to Tesseract
                    log.warning("textract failed on page %s: %s", n, e)
                    fallback.append(n)
            if progress:
                progress(min(i + len(batch), len(numbers)), len(numbers))
    for n in fallback:
        try:
            out[n] = (pdf.page_text(doc[n - 1], ocr=True), "tesseract")
        except Exception as e:  # noqa: BLE001 - keep the book; this page stays empty
            log.warning("tesseract failed on page %s: %s", n, e)
            out[n] = ("", "failed")
    done = sum(1 for _, src in out.values() if src == "textract")
    if numbers:
        telemetry.record_call(kind="ocr", model="textract-detect-document-text", units=done, calls=done,
                              cost=done * telemetry.PRICES["textract_page"],
                              latency_ms=int((time.monotonic() - started) * 1000), ok=not fallback,
                              error=f"{len(fallback)} page(s) fell back to Tesseract" if fallback else None)
    return out
