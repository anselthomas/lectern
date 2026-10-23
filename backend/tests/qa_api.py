"""End-to-end QA against the real stack (Postgres, S3, S3 Vectors, Bedrock), run inside the api container:

    docker compose exec -T api python -m tests.qa_api EMAIL PDF_URL

Acts as an existing user by overriding the auth dependency, so no password or token is involved.
Prints a PASS/FAIL line per check plus samples of the AI output.
"""
import json
import os
import sys
import tempfile
import time

import requests
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import SessionLocal, get_db
from app.main import app
from app.models import User

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  :: ' + detail if detail else ''}", flush=True)
    return ok


def sample(label: str, value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    print(f"      {label}: {text[:600]}", flush=True)


def as_user(user_id):
    """Auth override that loads the user in the request's own DB session, like the real dependency."""
    def dep(db: Session = Depends(get_db)) -> User:
        return db.get(User, user_id)
    return dep


def poll(fn, until, timeout: int, every: float = 5):
    end = time.time() + timeout
    while True:
        value = fn()
        if until(value) or time.time() > end:
            return value
        time.sleep(every)


def main(email: str, pdf_url: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        user_id = user.id
    app.dependency_overrides[current_user] = as_user(user_id)
    c = TestClient(app, headers={"X-Origin-Verify": os.environ.get("ORIGIN_VERIFY", "")})

    def get(path, **kw):
        r = c.get(f"/api{path}", **kw)
        return r

    def post(path, body=None):
        return c.post(f"/api{path}", json=body)

    # ---- account
    me = get("/me").json()
    check("GET /me", me.get("email") == email, f"plan={me['usage']['plan']['id']} exempt={me['usage']['limits_exempt']}")
    r = c.patch("/api/me", json={"onboarded": True, "goal": "course", "level_default": "standard", "daily_minutes": 20})
    check("PATCH /me onboarding", r.status_code == 200 and r.json()["onboarded"])

    # ---- upload
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    with requests.get(pdf_url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_content(1 << 20):
            tmp.write(chunk)
    tmp.close()
    size = os.path.getsize(tmp.name)
    r = post("/books", {"filename": "university-physics-volume-1.pdf", "size": size})
    check("POST /books (presigned upload)", r.status_code == 200, f"{size / 1048576:.1f} MB")
    book_id, url = r.json()["book"]["id"], r.json()["upload_url"]
    with open(tmp.name, "rb") as f:
        up = requests.put(url, data=f, headers={"Content-Type": "application/pdf"}, timeout=600)
    check("PUT to S3 presigned URL", up.status_code == 200, str(up.status_code))
    os.unlink(tmp.name)
    r = post(f"/books/{book_id}/uploaded")
    check("POST /books/:id/uploaded", r.status_code == 200 and r.json()["status"] == "queued")

    t0 = time.time()
    book = poll(lambda: get(f"/books/{book_id}").json(), lambda b: b["status"] not in ("queued", "processing"), 300)
    check("Ingest finished", book["status"] == "review", f"{book['status']} in {time.time() - t0:.0f}s, {book['pages']} pages, source={book['structure_source']}, offset={book['page_offset']}")
    chapters = book["chapters"]
    learn = [ch for ch in chapters if ch["kind"] == "chapter"]
    check("Chapters detected", len(learn) >= 15, f"{len(learn)} chapters, {sum(ch['kind'] == 'appendix' for ch in chapters)} appendices, {len(chapters)} rows")
    check("No file-named fake chapter", not any(ch["title"].lower().endswith(".pdf") for ch in chapters))
    idx = next((ch for ch in chapters if ch["title"].lower() == "index"), None)
    check("Index runs to last page", idx is None or idx["pdf_end"] == book["pages"], f"index={idx and (idx['pdf_start'], idx['pdf_end'])}")
    sample("first chapters", [(ch["n"], ch["kind"], ch["title"], ch["pages_label"]) for ch in chapters[:5]])

    # ---- structure edit validation
    bad = [{"title": ch["title"], "pdf_start": ch["pdf_start"], "pdf_end": ch["pdf_end"], "kind": ch["kind"]} for ch in chapters]
    bad[3]["pdf_end"] = bad[4]["pdf_start"] + 2
    r = c.put(f"/api/books/{book_id}/chapters", json={"chapters": bad})
    check("Overlapping ranges rejected", r.status_code == 400, r.text[:120])
    good = [{"title": ch["title"], "pdf_start": ch["pdf_start"], "pdf_end": ch["pdf_end"], "kind": ch["kind"]} for ch in chapters]
    r = c.put(f"/api/books/{book_id}/chapters", json={"chapters": good})
    check("Unchanged outline saves", r.status_code == 200)

    r = post(f"/books/{book_id}/confirm")
    check("POST /books/:id/confirm", r.status_code == 200 and r.json()["status"] == "ready")
    ch1 = next(ch for ch in r.json()["chapters"] if ch["kind"] == "chapter")
    t0 = time.time()
    chapter = poll(lambda: get(f"/chapters/{ch1['id']}").json(), lambda x: x["status"] in ("ready", "failed"), 600, 8)
    check("Chapter 1 built", chapter["status"] == "ready", f"{chapter['status']} in {time.time() - t0:.0f}s {chapter.get('status_detail') or ''}")
    check("Chapter map has key ideas + explain prompt", bool(chapter["map"]["key_ideas"]) and bool(chapter["map"]["explain"]["prompt"]))
    sample("sections", [(s["n"], s["title"], s["pages_label"]) for s in chapter["sections"]])
    sample("key ideas", chapter["map"]["key_ideas"])
    check("Quiz has ~10 questions", chapter["quiz"] and chapter["quiz"]["count"] >= 8, f"{chapter['quiz'] and chapter['quiz']['count']}")
    nxt = chapter.get("next_chapter")
    check("Next chapter pre-build queued", nxt and nxt["status"] in ("queued", "building", "ready"), str(nxt and nxt["status"]))

    # ---- pre-question
    r = post(f"/chapters/{ch1['id']}/prequestion", {"rating": "some", "answer": "Physics measures things using units like meters and seconds."})
    check("Pre-question plan", r.status_code == 200 and bool(r.json().get("plan")), r.text[:80] if r.status_code != 200 else "")
    sample("plan", r.json())

    # ---- lessons
    sec = chapter["sections"][0]
    lesson = get(f"/sections/{sec['id']}?level=standard").json()
    blocks = lesson["lesson"]["blocks"]
    check("Standard lesson present", lesson["status"] == "ready" and len(blocks) >= 3, f"{len(blocks)} blocks, {len(lesson['lesson']['quick_checks'])} quick checks")
    pages_ok = all(b.get("page") is None or lesson["pdf_start"] <= b["page"] <= lesson["pdf_end"] for b in blocks)
    check("Lesson citations inside section pages", pages_ok)
    check("Citations show printed labels", any(b.get("page_label") for b in blocks))
    sample("first block", blocks[0])
    sample("quick check", lesson["lesson"]["quick_checks"][0] if lesson["lesson"]["quick_checks"] else None)
    simple = get(f"/sections/{sec['id']}?level=simple").json()
    check("Simple level starts building on demand", simple["status"] in ("building", "ready"))
    t0 = time.time()
    simple = poll(lambda: get(f"/sections/{sec['id']}?level=simple").json(), lambda x: x["status"] == "ready", 240, 5)
    check("Simple level lesson built", simple["status"] == "ready", f"{time.time() - t0:.0f}s")
    if simple["status"] == "ready":
        sample("simple first block", simple["lesson"]["blocks"][0]["text"])
    r = get(f"/sections/{sec['id']}?level=bogus")
    check("Unknown level rejected", r.status_code == 400)

    # ---- tutor
    t = post("/tutor", {"book_id": book_id, "chapter_id": ch1["id"], "message": "What is the difference between accuracy and precision?"})
    tj = t.json()
    check("Tutor answers an in-book question", t.status_code == 200 and tj["in_book"] and len(tj["citations"]) > 0,
          f"citations={[x['label'] for x in tj.get('citations', [])]}")
    sample("tutor answer", tj.get("answer"))
    t = post("/tutor", {"book_id": book_id, "chapter_id": ch1["id"], "message": "Who won the 2018 FIFA World Cup?"})
    check("Tutor declines off-book question", t.status_code == 200 and not t.json()["in_book"], t.json().get("answer", "")[:160])
    t = post("/tutor", {"book_id": book_id, "message": "What does the book say about Bernoulli's equation?"})
    tj = t.json()
    check("Tutor retrieves from a far chapter", t.status_code == 200 and tj["in_book"] and any(int(x["pdf_page"]) > 600 for x in tj["citations"]),
          f"pages={[x['pdf_page'] for x in tj.get('citations', [])]}")
    hist = get(f"/tutor/{book_id}/history").json()
    check("Tutor history stored", len(hist) >= 6, f"{len(hist)} messages")

    # ---- source page
    page = chapter["sections"][0]
    img = get(f"/books/{book_id}/pages/{lesson['pdf_start']}/image")
    check("Source page renders as PNG", img.status_code == 200 and img.content[:4] == b"\x89PNG", f"{len(img.content) // 1024} KB")
    pj = get(f"/books/{book_id}/pages/{lesson['pdf_start']}").json()
    check("Page text + label", bool(pj["text"]) and bool(pj["label"]), f"pdf {pj['pdf_page']} = printed {pj['label']}")

    # ---- complete sections -> key-term cards
    for s in chapter["sections"]:
        r = post(f"/sections/{s['id']}/complete")
    check("All sections completed", r.json()["sections_done"] == len(chapter["sections"]))

    # ---- explain it back
    ex = chapter["map"]["explain"]
    sample("explain prompt", ex)
    # A faithful answer written from the key points, in a learner's voice.
    good_text = "So basically, " + " Also, ".join(p.rstrip(".") + "." for p in ex["key_points"])
    r = post(f"/chapters/{ch1['id']}/explain", {"text": good_text})
    ej = r.json()
    check("Explain-back graded fairly", r.status_code == 200 and ej["total"] >= 2 and ej["met"] >= ej["total"] - 1, f"{ej.get('verdict')} {ej.get('met')}/{ej.get('total')}")
    sample("explain feedback", {"points": ej.get("points"), "stronger": ej.get("stronger_version")})
    r = post(f"/chapters/{ch1['id']}/explain", {"text": "Physics is about cooking pasta and the colours of paint."})
    check("Weak explanation scored lower", r.status_code == 200 and r.json()["met"] < max(1, ej["met"]), f"{r.json().get('verdict')} {r.json().get('met')}/{r.json().get('total')}")

    # ---- quiz
    quiz = get(f"/chapters/{ch1['id']}/quiz").json()
    qs = quiz["questions"]
    check("Quiz hides answers", all("answer_index" not in q and "model_answer" not in q for q in qs))
    mcqs = [q for q in qs if q["type"] == "mcq"]
    shorts = [q for q in qs if q["type"] == "short"]
    check("Quiz mix", len(mcqs) >= 5 and len(shorts) >= 2, f"{len(mcqs)} mcq, {len(shorts)} short")
    from app.models import Quiz as QuizRow
    with SessionLocal() as db:
        key = {q["id"]: q for q in db.get(QuizRow, quiz["id"]).questions}
    right = post(f"/quizzes/{quiz['id']}/check", {"question_id": mcqs[0]["id"], "answer": key[mcqs[0]["id"]]["answer_index"]}).json()
    wrong = post(f"/quizzes/{quiz['id']}/check", {"question_id": mcqs[1]["id"], "answer": (key[mcqs[1]["id"]]["answer_index"] + 1) % 4}).json()
    check("MCQ check right/wrong", right["correct"] and not wrong["correct"])
    sa = post(f"/quizzes/{quiz['id']}/check", {"question_id": shorts[0]["id"], "answer": key[shorts[0]["id"]]["model_answer"]}).json()
    check("Short answer graded correct for the model idea", sa["correct"], sa.get("feedback", "")[:160])
    sb = post(f"/quizzes/{quiz['id']}/check", {"question_id": shorts[0]["id"], "answer": "I don't know, something about bananas."}).json()
    check("Short answer nonsense marked wrong", not sb["correct"], sb.get("feedback", "")[:160])
    answers = {}
    for i, q in enumerate(qs):
        k = key[q["id"]]
        if q["type"] == "mcq":
            answers[q["id"]] = k["answer_index"] if i % 4 else (k["answer_index"] + 1) % 4  # miss a couple
        else:
            answers[q["id"]] = k["model_answer"]
    sub = post(f"/quizzes/{quiz['id']}/submit", {"answers": answers}).json()
    check("Quiz submitted + scored", "score" in sub, f"{sub.get('correct')}/{sub.get('total')} mastered={sub.get('mastered')} new_cards={sub.get('new_cards')}")
    check("Missed questions became cards", sub.get("new_cards", 0) >= 1)
    check("Results by section", len(sub.get("by_section", [])) >= 2)

    # ---- review
    due = get("/review/due").json()
    check("Flashcards due", len(due["cards"]) >= 1, f"{len(due['cards'])} due of {due['total_cards']} total; intervals={due['cards'][0]['intervals'] if due['cards'] else None}")
    if due["cards"]:
        r1 = post(f"/review/{due['cards'][0]['id']}", {"rating": 3}).json()
        r2 = post(f"/review/{due['cards'][1]['id']}", {"rating": 1}).json() if len(due["cards"]) > 1 else {}
        check("FSRS scheduling", "due_at" in r1, f"good->{r1.get('due_at')} again->{r2.get('due_at')}")

    # ---- progress, search, notes, notifications, export
    post("/activity", {"book_id": book_id, "seconds": 300})
    pr = get("/progress?days=14").json()
    check("Progress", pr["minutes_total"] >= 5 and pr["cards_reviewed"] >= 1 and pr["streak"] >= 1, f"min={pr['minutes_total']} cards={pr['cards_reviewed']} streak={pr['streak']} quiz_avg={pr['quiz_avg']}")
    s = get("/search?q=significant figures").json()
    check("Search finds passages", len(s["passages"]) >= 1, f"{len(s['passages'])} passages; first p.{s['passages'][0]['page_label'] if s['passages'] else None}")
    n = post(f"/books/{book_id}/notes", {"kind": "highlight", "pdf_page": lesson["pdf_start"], "quote": "SI units", "text": "Remember the 7 base units"})
    check("Add note", n.status_code == 200)
    check("List notes", len(get(f"/books/{book_id}/notes").json()) >= 1)
    nt = get("/notifications").json()
    check("Notifications", any(x["type"] == "chapter_ready" for x in nt["items"]), f"{len(nt['items'])} items, {nt['unread']} unread")
    check("CSV export", get("/me/cards.csv").text.startswith("front,back"))
    check("JSON export", get("/me/export").status_code == 200)

    # ---- final test (internal account unlocks early)
    fs = get(f"/books/{book_id}/final").json()
    check("Final test status", fs["eligible"], json.dumps(fs))
    ft = c.post(f"/api/books/{book_id}/final/start")
    ftj = ft.json()
    check("Final test starts", ft.status_code == 200 and len(ftj.get("questions", [])) >= 5, f"{len(ftj.get('questions', []))} questions")
    if ft.status_code == 200:
        fsub = post(f"/quizzes/{ftj['id']}/submit", {"answers": {}}).json()
        check("Final test submit", "passed" in fsub, f"score={fsub.get('score')} passed={fsub.get('passed')}")

    # ---- isolation: another user can't read this book
    with SessionLocal() as db:
        other = db.query(User).filter_by(cognito_sub="qa-isolation").one_or_none()
        if other is None:
            other = User(cognito_sub="qa-isolation", email="isolation@lectern.invalid")
            db.add(other)
            db.commit()
        other_id = other.id
    app.dependency_overrides[current_user] = as_user(other_id)
    check("Other user gets 404 on this book", get(f"/books/{book_id}").status_code == 404)
    check("Other user can't use tutor on it", post("/tutor", {"book_id": book_id, "message": "hi"}).status_code == 404)
    r = post("/books", {"filename": "a.pdf", "size": 1024})
    r2 = post("/books", {"filename": "b.pdf", "size": 1024})
    check("Free plan: second book blocked with 402", r.status_code == 200 and r2.status_code == 402, r2.text[:120])
    r3 = get(f"/sections/{sec['id']}?level=exam")
    check("Free plan: other users' sections hidden", r3.status_code == 404)
    with SessionLocal() as db:
        db.delete(db.get(User, other_id))
        db.commit()

    with SessionLocal() as db:
        from app.limits import usage_row
        u = usage_row(db, db.get(User, user_id))
        print(f"\nTOKENS this month: {u.tokens_in} in / {u.tokens_out} out; tutor messages {u.tutor_messages}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name, _, detail in failed:
        print(f"  FAILED: {name} {detail}")
    print(f"BOOK_ID={book_id}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
