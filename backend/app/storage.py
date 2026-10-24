import os
import threading

from .aws import s3
from .config import settings
from .models import Book

_locks: dict[str, threading.Lock] = {}


def local_pdf(book: Book) -> str:
    """Download the book's PDF to the local cache once and return its path."""
    os.makedirs(settings.cache_dir, exist_ok=True)
    path = os.path.join(settings.cache_dir, f"{book.id}.pdf")
    lock = _locks.setdefault(str(book.id), threading.Lock())
    with lock:
        if not os.path.exists(path):
            tmp = path + ".part"
            s3().download_file(settings.uploads_bucket, book.s3_key, tmp)
            os.replace(tmp, path)
    return path


def drop_local(book_id) -> None:
    try:
        os.remove(os.path.join(settings.cache_dir, f"{book_id}.pdf"))
    except FileNotFoundError:
        pass


def presign_put(key: str, content_type: str = "application/octet-stream", expires: int = 900) -> str:
    return s3().generate_presigned_url("put_object", ExpiresIn=expires,
                                       Params={"Bucket": settings.uploads_bucket, "Key": key, "ContentType": content_type})


def delete_object(key: str) -> None:
    s3().delete_object(Bucket=settings.uploads_bucket, Key=key)


def delete_book_files(book: Book) -> None:
    """The uploaded original and, for converted documents, the PDF made from it."""
    prefix = book.s3_key.rsplit("/", 1)[0]
    for key in {book.s3_key, f"{prefix}/original", f"{prefix}/source.pdf"}:
        try:
            delete_object(key)
        except Exception:  # noqa: BLE001 - a missing object is fine
            pass
