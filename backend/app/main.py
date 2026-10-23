import hmac
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .db import Base, SessionLocal, engine
from . import migrations
from .limits import seed_plans
from .routes import account, books, learn, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("lectern.api")

app = FastAPI(title="Lectern API", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    """Only CloudFront knows the origin secret; everything else is refused."""
    if settings.origin_verify and request.url.path != "/api/health":  # health is used by the container probe
        got = request.headers.get("x-origin-verify", "")
        if not hmac.compare_digest(got, settings.origin_verify):
            return JSONResponse({"error": "forbidden"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": {"code": "server_error", "message": "Something went wrong on our side."}},
                        status_code=500)


@app.on_event("startup")
def startup() -> None:
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)
    migrations.run(engine)
    with SessionLocal() as db:
        seed_plans(db)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(account.router)
app.include_router(books.router)
app.include_router(learn.router)
app.include_router(voice.router)
