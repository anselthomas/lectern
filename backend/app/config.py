import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


@dataclass(frozen=True)
class Settings:
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "ap-southeast-2"))
    bedrock_region: str = field(default_factory=lambda: _env("BEDROCK_REGION", "us-east-1"))
    text_model: str = field(default_factory=lambda: _env("TEXT_MODEL", "global.amazon.nova-2-lite-v1:0"))
    embed_model: str = field(default_factory=lambda: _env("EMBED_MODEL", "amazon.titan-embed-text-v2:0"))
    uploads_bucket: str = field(default_factory=lambda: _env("UPLOADS_BUCKET", ""))
    vector_bucket: str = field(default_factory=lambda: _env("VECTOR_BUCKET", ""))
    vector_index: str = field(default_factory=lambda: _env("VECTOR_INDEX", "chunks"))
    user_pool_id: str = field(default_factory=lambda: _env("COGNITO_USER_POOL_ID", ""))
    user_pool_client_id: str = field(default_factory=lambda: _env("COGNITO_CLIENT_ID", ""))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql+psycopg://lectern:lectern@localhost/lectern"))
    origin_verify: str = field(default_factory=lambda: _env("ORIGIN_VERIFY", ""))
    cache_dir: str = field(default_factory=lambda: _env("CACHE_DIR", "/data/cache"))
    # Comma-separated emails that get the admin dashboard (set from SSM /lectern/admin-emails at deploy).
    admin_emails: frozenset = field(default_factory=lambda: frozenset(
        e.strip().lower() for e in _env("ADMIN_EMAILS", "").split(",") if e.strip()))
    # Background chapter builds use Bedrock's cheaper flex tier; interactive calls use the default tier.
    build_service_tier: str = field(default_factory=lambda: _env("BUILD_SERVICE_TIER", "flex"))


settings = Settings()
