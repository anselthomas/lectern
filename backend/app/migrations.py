"""Schema changes for tables that already exist. `create_all` only creates missing tables, so column changes go here.

Each statement must be idempotent: they all run on every startup, in order.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

STATEMENTS = [
    # 2026-10-24: "citation_report" didn't fit in varchar(12).
    "ALTER TABLE notes ALTER COLUMN kind TYPE varchar(20)",
    # 2026-10-24: voice answers (Amazon Transcribe) are metered per clip.
    "ALTER TABLE usage_monthly ADD COLUMN IF NOT EXISTS voice_clips integer NOT NULL DEFAULT 0",
]


def run(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))  # api and worker may start together
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
