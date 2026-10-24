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
    # 2026-10-24: admin dashboard.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at timestamptz",
    # 2026-10-24: per-type notification switches.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_prefs jsonb NOT NULL DEFAULT '{}'",
    # 2026-10-24: how each page's text was obtained (text layer or which OCR engine).
    "ALTER TABLE pages ADD COLUMN IF NOT EXISTS source varchar(12)",
    # 2026-10-24: books can be uploaded as Word, EPUB, text, images and more (converted to PDF).
    "ALTER TABLE books ADD COLUMN IF NOT EXISTS source_format varchar(12)",
    # 2026-10-24: rebuilds used to stack "Chapter N is ready" notifications; keep only the newest of each.
    "DELETE FROM notifications a USING notifications b WHERE a.user_id = b.user_id AND a.type = b.type "
    "AND a.link = b.link AND a.created_at < b.created_at",
    "DELETE FROM notifications WHERE type = 'chapter_ready' AND NOT EXISTS "
    "(SELECT 1 FROM chapters c WHERE notifications.link LIKE '%chapter=' || c.id::text)",
]


def run(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))  # api and worker may start together
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
