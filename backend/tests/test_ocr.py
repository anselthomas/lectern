"""Pages without a usable text layer go to OCR; broken line wraps are repaired."""
import fitz

from app import ocr, pdf


def test_text_usable_rejects_empty_and_garbled_layers():
    assert not ocr.text_usable("")
    assert not ocr.text_usable("12")
    assert not ocr.text_usable("(cid:12)(cid:45)(cid:7) " * 10)
    assert not ocr.text_usable("■□▪▫ ◆◇ ● ○ " * 20)
    assert ocr.text_usable("Sensory receptors convert stimulus energy into electrical signals in neurons.")


def test_blank_pages_are_not_sent_to_ocr():
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    doc[1].insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    blank, pic = doc[0], doc[1]
    assert not ocr.has_visible_content(blank)
    assert ocr.has_visible_content(pic)
    assert len(ocr.page_image(pic)) < ocr.TEXTRACT_MAX_BYTES


def test_ocr_pages_falls_back_to_tesseract_and_never_raises(monkeypatch):
    doc = fitz.open()
    doc.new_page()
    doc.new_page()

    def textract(img):
        raise RuntimeError("throttled")
    monkeypatch.setattr(ocr, "textract_text", textract)
    monkeypatch.setattr(ocr.pdf, "page_text", lambda page, ocr=False: "from tesseract" if page.number == 0 else 1 / 0)
    monkeypatch.setattr(ocr.telemetry, "record_call", lambda **kw: None)
    out = ocr.ocr_pages(doc, [1, 2])
    assert out == {1: ("from tesseract", "tesseract"), 2: ("", "failed")}


def test_ocr_pages_uses_textract_text(monkeypatch):
    doc = fitz.open()
    doc.new_page()
    calls = []
    monkeypatch.setattr(ocr, "textract_text", lambda img: "Line one\nLine two")
    monkeypatch.setattr(ocr.telemetry, "record_call", lambda **kw: calls.append(kw))
    assert ocr.ocr_pages(doc, [1]) == {1: ("Line one\nLine two", "textract")}
    assert calls[0]["units"] == 1 and calls[0]["cost"] == ocr.telemetry.PRICES["textract_page"]


WORDS = {"a", "the", "receptor", "receptors", "potential", "strength", "specified", "particular", "adequate",
         "stimulus", "of", "an", "graded", "change", "in", "membrane", "minimum", "required", "to", "produce",
         "response", "or", "pain", "proprioception", "varies", "with", "area", "from", "which"}


def test_split_words_are_rejoined_but_real_line_breaks_stay():
    pages = ["A graded change in the membrane potential of a sensory rec\neptor in response",
             "The minimum stimulus required to produce a speci\nfied response. Amplitude varies with stimulus str\nength",
             "the area from which stimulation influences a pa\nrticular neuron, called its adequ\nate stimulus",
             "temperature, pain\n or proprioception. The receptor\npotential varies"]
    out = pdf.rejoin_split_words(pages, WORDS)
    assert "sensory receptor in response" in out[0]
    assert "specified response" in out[1] and "stimulus strength" in out[1]
    assert "particular neuron" in out[2] and "adequate stimulus" in out[2]
    assert "pain\n or proprioception" in out[3] and "receptor\npotential" in out[3]


def test_technical_words_join_using_the_documents_own_longer_forms():
    pages = ["Usually local and decremental.", "Propagates along the nerve fibre without dec\nrement"]
    out = pdf.rejoin_split_words(pages, {"dec", "without", "the", "nerve", "fibre", "along", "and", "local"})
    assert "without decrement" in out[1]
