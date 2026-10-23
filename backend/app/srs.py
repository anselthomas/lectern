"""FSRS scheduling via the `fsrs` package. Card state is stored as the package's dict form."""
from datetime import datetime, timezone

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler

RATINGS = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}


def new_state() -> dict:
    return FsrsCard().to_dict()


def _scheduler(target_recall: float) -> Scheduler:
    return Scheduler(desired_retention=target_recall, enable_fuzzing=False)


def review(state: dict, rating: int, target_recall: float) -> tuple[dict, datetime]:
    card, _ = _scheduler(target_recall).review_card(FsrsCard.from_dict(state), RATINGS[rating],
                                                     datetime.now(timezone.utc))
    return card.to_dict(), card.due


def humanize(delta_seconds: float) -> str:
    m = delta_seconds / 60
    if m < 10:
        return "< 10 min"
    if m < 60:
        return f"{round(m)} min"
    h = m / 60
    if h < 24:
        return f"{round(h)} h"
    d = h / 24
    if d < 31:
        return f"{round(d)} day" + ("s" if round(d) != 1 else "")
    return f"{round(d / 30)} mo"


def previews(state: dict, target_recall: float) -> dict[int, str]:
    now = datetime.now(timezone.utc)
    sched = _scheduler(target_recall)
    out = {}
    for value, rating in RATINGS.items():
        card, _ = sched.review_card(FsrsCard.from_dict(state), rating, now)
        out[value] = humanize((card.due - now).total_seconds())
    return out
