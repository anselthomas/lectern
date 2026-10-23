"""Usage telemetry: every model call (tokens, cost, latency) and product events, attributed to a user/book/chapter.

Callers set attribution with `with telemetry.scope(user_id=..., book_id=..., feature="tutor"):`; anything that
calls Bedrock inside the block is recorded against it. Recording never raises: telemetry must not break a request.
"""
import contextvars
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

log = logging.getLogger("lectern.telemetry")
_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("lectern_scope", default={})

# USD, from the AWS Pricing API for us-east-1 Bedrock on 2026-10-23 (global cross-region profile) and public
# Transcribe/Titan list prices. Update here if AWS prices change.
PRICES = {
    "text": {"standard": (0.30, 2.50), "flex": (0.15, 1.25)},  # per 1M input / output tokens, Nova 2 Lite
    "embed_per_m": 0.02,                                        # Titan Text Embeddings V2, per 1M input tokens
    "transcribe_per_min": 0.024,                                # Amazon Transcribe batch, per audio minute
}
FIXED_MONTHLY_USD = 23.0  # EC2 t4g.small + EBS + public IPv4 + small S3/CloudFront (see docs/architecture-plan.md)


@contextmanager
def scope(**attrs):
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in attrs.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def current() -> dict:
    return dict(_ctx.get())


def text_cost(tokens_in: int, tokens_out: int, tier: str = "standard") -> float:
    p_in, p_out = PRICES["text"].get(tier, PRICES["text"]["standard"])
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def embed_cost(tokens: int) -> float:
    return tokens * PRICES["embed_per_m"] / 1_000_000


def transcribe_cost(seconds: float) -> float:
    return max(seconds, 15) / 60 * PRICES["transcribe_per_min"]  # Transcribe bills a 15 s minimum per job


def record_call(*, kind: str, model: str, tier: str = "standard", tokens_in: int = 0, tokens_out: int = 0,
                cost: float | None = None, latency_ms: int | None = None, ok: bool = True, error: str | None = None,
                units: float | None = None, calls: int = 1) -> None:
    attrs = current()
    if cost is None:
        cost = text_cost(tokens_in, tokens_out, tier)
    try:
        from .db import SessionLocal
        from .models import LlmCall
        with SessionLocal() as db:
            db.add(LlmCall(user_id=attrs.get("user_id"), book_id=attrs.get("book_id"), chapter_id=attrs.get("chapter_id"),
                           feature=attrs.get("feature", "other"), kind=kind, model=model, tier=tier, calls=calls,
                           tokens_in=tokens_in, tokens_out=tokens_out, units=units, cost_usd=round(cost, 6),
                           latency_ms=latency_ms, ok=ok, error=(error or "")[:500] or None))
            db.commit()
    except Exception as e:  # pragma: no cover
        log.warning("telemetry record_call failed: %s", e)


def event(type_: str, **props) -> None:
    attrs = current()
    try:
        from .db import SessionLocal
        from .models import Event
        with SessionLocal() as db:
            db.add(Event(user_id=props.pop("user_id", attrs.get("user_id")), book_id=props.pop("book_id", attrs.get("book_id")),
                         chapter_id=props.pop("chapter_id", attrs.get("chapter_id")), type=type_,
                         props={k: (str(v) if not isinstance(v, (int, float, bool, str, type(None), list, dict)) else v)
                                for k, v in props.items()}))
            db.commit()
    except Exception as e:  # pragma: no cover
        log.warning("telemetry event failed: %s", e)


class EmbedCounter:
    """Thread-safe token/call totals for a batch of embeddings, recorded as one row."""

    def __init__(self):
        self.tokens = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, tokens: int) -> None:
        with self._lock:
            self.tokens += tokens
            self.calls += 1


def now() -> datetime:
    return datetime.now(timezone.utc)
