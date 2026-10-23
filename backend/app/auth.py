"""Cognito ID-token verification and the current-user dependency."""
import time
from datetime import datetime, timezone
from functools import lru_cache

import jwt
import requests
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import telemetry
from .config import settings
from .db import get_db
from .models import User


@lru_cache
def _issuer() -> str:
    return f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.user_pool_id}"


_jwks: dict = {"keys": None, "at": 0.0}


def _signing_key(kid: str):
    if not _jwks["keys"] or time.time() - _jwks["at"] > 3600 or kid not in _jwks["keys"]:
        data = requests.get(f"{_issuer()}/.well-known/jwks.json", timeout=5).json()
        _jwks["keys"] = {k["kid"]: jwt.PyJWK(k) for k in data["keys"]}
        _jwks["at"] = time.time()
    key = _jwks["keys"].get(kid)
    if not key:
        raise HTTPException(401, "Unknown signing key")
    return key.key


def verify_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(
            token, _signing_key(header["kid"]), algorithms=["RS256"],
            audience=settings.user_pool_client_id, issuer=_issuer(),
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}") from e
    if claims.get("token_use") != "id":
        raise HTTPException(401, "ID token required")
    return claims


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    claims = verify_token(authorization.split(" ", 1)[1])
    user = db.query(User).filter_by(cognito_sub=claims["sub"]).one_or_none()
    created = user is None
    if user is None:
        user = User(cognito_sub=claims["sub"], email=claims.get("email", ""), name=claims.get("name"))
        db.add(user)
    elif claims.get("email") and user.email != claims["email"]:
        user.email = claims["email"]
    if user.email and user.email.lower() in settings.admin_emails and not user.is_admin:
        user.is_admin = True
    now = datetime.now(timezone.utc)
    if user.last_seen_at is None or (now - user.last_seen_at).total_seconds() > 300:
        user.last_seen_at = now
    if db.dirty or db.new:
        db.commit()
    if created:
        telemetry.event("signup", user_id=user.id)
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user
