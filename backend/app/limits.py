"""Plans, usage meters and limit checks. Limit errors are HTTP 402 with a code the frontend maps to the upgrade prompt."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Book, Plan, UsageMonthly, User

MB = 1024 * 1024

PLANS = [
    {"id": "free", "name": "Free", "price_month": 0, "price_year": 0, "limits": {
        "books": 1, "max_mb": 100, "max_pages": 800, "scanned": False, "exam": False, "final_test": False,
        "tutor_messages": 50, "storage_mb": 200, "new_books_month": 1}},
    {"id": "pro", "name": "Pro", "price_month": 9.99, "price_year": 89, "limits": {
        "books": None, "max_mb": 500, "max_pages": 2000, "scanned": True, "exam": True, "final_test": True,
        "tutor_messages": 1000, "storage_mb": 5120, "new_books_month": 10}},
    {"id": "teams", "name": "Teams", "price_month": 8, "price_year": 80, "limits": {
        "books": None, "max_mb": 500, "max_pages": 2000, "scanned": True, "exam": True, "final_test": True,
        "tutor_messages": 1000, "storage_mb": 5120, "new_books_month": 10}},
    {"id": "internal", "name": "Internal", "price_month": None, "price_year": None, "limits": {
        "books": None, "max_mb": 500, "max_pages": 3000, "scanned": True, "exam": True, "final_test": True,
        "tutor_messages": None, "storage_mb": None, "new_books_month": None}},
]


def seed_plans(db: Session) -> None:
    for p in PLANS:
        existing = db.get(Plan, p["id"])
        if existing is None:
            db.add(Plan(**p))
        else:
            existing.name, existing.price_month, existing.price_year = p["name"], p["price_month"], p["price_year"]
            existing.limits = p["limits"]
    db.commit()


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage_row(db: Session, user: User) -> UsageMonthly:
    row = db.get(UsageMonthly, (user.id, month_key()))
    if row is None:
        row = UsageMonthly(user_id=user.id, month=month_key(), books_added=0, tutor_messages=0, tokens_in=0, tokens_out=0)
        db.add(row)
        db.flush()
    return row


def limit(user: User, key: str):
    return user.plan.limits.get(key)


def deny(code: str, message: str):
    raise HTTPException(402, {"code": code, "message": message})


def check_new_book(db: Session, user: User, size_bytes: int) -> None:
    if user.limits_exempt:
        return
    max_books = limit(user, "books")
    if max_books is not None:
        count = db.query(func.count(Book.id)).filter(Book.user_id == user.id).scalar()
        if count >= max_books:
            deny("book_limit", f"Your plan includes {max_books} book. Upgrade to add more.")
    monthly = limit(user, "new_books_month")
    if monthly is not None and usage_row(db, user).books_added >= monthly:
        deny("monthly_book_limit", "You've reached this month's new-book limit.")
    if size_bytes > limit(user, "max_mb") * MB:
        deny("file_too_large", f"PDFs up to {limit(user, 'max_mb')} MB on your plan.")
    storage = limit(user, "storage_mb")
    if storage is not None:
        used = db.query(func.coalesce(func.sum(Book.bytes), 0)).filter(Book.user_id == user.id).scalar()
        if used + size_bytes > storage * MB:
            deny("storage_limit", "This upload would go over your storage limit.")


def check_feature(user: User, feature: str) -> None:
    if user.limits_exempt or limit(user, feature):
        return
    messages = {
        "scanned": "Scanned PDFs need Pro.",
        "exam": "Exam-level explanations need Pro.",
        "final_test": "Final tests need Pro.",
    }
    deny(f"{feature}_requires_pro", messages.get(feature, "This needs Pro."))


def check_tutor(db: Session, user: User) -> UsageMonthly:
    row = usage_row(db, user)
    cap = limit(user, "tutor_messages")
    if not user.limits_exempt and cap is not None and row.tutor_messages >= cap:
        deny("tutor_limit", f"You've used all {cap} tutor messages this month.")
    return row


def record_tokens(db: Session, user: User, tokens_in: int, tokens_out: int) -> None:
    row = usage_row(db, user)
    row.tokens_in += tokens_in
    row.tokens_out += tokens_out


def usage_summary(db: Session, user: User) -> dict:
    row = usage_row(db, user)
    books = db.query(func.count(Book.id)).filter(Book.user_id == user.id).scalar()
    storage = db.query(func.coalesce(func.sum(Book.bytes), 0)).filter(Book.user_id == user.id).scalar()
    lim = user.plan.limits
    return {
        "plan": {"id": user.plan.id, "name": user.plan.name, "price_month": user.plan.price_month,
                 "price_year": user.plan.price_year, "limits": lim},
        "limits_exempt": user.limits_exempt,
        "books": {"used": books, "limit": None if user.limits_exempt else lim.get("books")},
        "storage_mb": {"used": round(storage / MB, 1), "limit": None if user.limits_exempt else lim.get("storage_mb")},
        "tutor_messages": {"used": row.tutor_messages, "limit": None if user.limits_exempt else lim.get("tutor_messages")},
        "tokens": {"in": row.tokens_in, "out": row.tokens_out},
    }
