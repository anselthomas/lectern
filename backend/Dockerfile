FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract is the OCR fallback when Textract fails (PyMuPDF calls it); wamerican-large is the word list used to
# repair words split across lines.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng wamerican-large \
    && rm -rf /var/lib/apt/lists/*
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY tests ./tests

RUN useradd --create-home --uid 10001 lectern && mkdir -p /data/cache && chown -R lectern /data
USER lectern
EXPOSE 8000
# CloudFront reuses origin connections for up to 5 s (OriginKeepaliveTimeout); the server must keep them open longer,
# or a request sent just as uvicorn closes an idle connection comes back as a 502.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-keep-alive", "75"]
