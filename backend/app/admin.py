"""Admin tasks run on the server: `python -m app.admin grant-internal EMAIL`.

Marks an existing Cognito user as the internal QA account (plan=internal, no usage limits).
The Cognito user and its password are created separately with admin credentials (see deploy/create-test-user.sh).
"""
import sys

from .aws import cognito
from .config import settings
from .db import Base, SessionLocal, engine
from .limits import seed_plans
from .models import User


def grant_internal(email: str) -> None:
    Base.metadata.create_all(engine)
    attrs = cognito().admin_get_user(UserPoolId=settings.user_pool_id, Username=email)["UserAttributes"]
    sub = next(a["Value"] for a in attrs if a["Name"] == "sub")
    with SessionLocal() as db:
        seed_plans(db)
        user = db.query(User).filter_by(cognito_sub=sub).one_or_none()
        if user is None:
            user = User(cognito_sub=sub, email=email, name="Lectern QA")
            db.add(user)
        user.plan_id, user.limits_exempt = "internal", True
        db.commit()
    print(f"{email}: plan=internal, limits_exempt=true")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "grant-internal":
        grant_internal(sys.argv[2])
    else:
        sys.exit("usage: python -m app.admin grant-internal EMAIL")
