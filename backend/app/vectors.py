"""Chunk embeddings in S3 Vectors. Keys are "{book_id}:{chunk_n}"; every query filters by user and book."""
from .aws import s3vectors
from .config import settings

BATCH = 400  # PutVectors accepts up to 500 per call


def _target():
    return {"vectorBucketName": settings.vector_bucket, "indexName": settings.vector_index}


def put(vectors: list[dict]) -> None:
    """vectors: [{key, embedding, user_id, book_id, chapter_n, pdf_page}]"""
    for i in range(0, len(vectors), BATCH):
        batch = [
            {
                "key": v["key"],
                "data": {"float32": v["embedding"]},
                "metadata": {
                    "user_id": v["user_id"],
                    "book_id": v["book_id"],
                    "chapter_n": v["chapter_n"] if v["chapter_n"] is not None else -1,
                    "pdf_page": v["pdf_page"],
                },
            }
            for v in vectors[i:i + BATCH]
        ]
        s3vectors().put_vectors(**_target(), vectors=batch)


def query(embedding: list[float], *, user_id: str, book_id: str, top_k: int = 8,
          chapter_n: int | None = None) -> list[dict]:
    clauses = [{"user_id": user_id}, {"book_id": book_id}]
    if chapter_n is not None:
        clauses.append({"chapter_n": chapter_n})
    resp = s3vectors().query_vectors(
        **_target(), queryVector={"float32": embedding}, topK=top_k,
        filter={"$and": clauses}, returnMetadata=True, returnDistance=True,
    )
    return resp.get("vectors", [])


def delete_book(book_id: str, chunk_count: int) -> None:
    keys = [f"{book_id}:{n}" for n in range(chunk_count)]
    for i in range(0, len(keys), 500):
        s3vectors().delete_vectors(**_target(), keys=keys[i:i + 500])
