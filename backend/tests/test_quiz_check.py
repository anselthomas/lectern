from app import content


def mcq(i, key, question="Q"):
    return {"id": f"q{i}", "type": "mcq", "question": question, "options": ["A", "B", "C", "D"],
            "answer_index": key, "explanation": "original"}


def verdict(n, option, confident=True, why="because"):
    return {"n": n, "working": "...", "correct_option": option, "confident": confident, "explanation": why}


def run(monkeypatch, qs, *replies):
    calls = []

    def fake(**kw):
        calls.append(kw["prompt"])
        return replies[len(calls) - 1], content.llm.Usage()
    monkeypatch.setattr(content.llm, "call_json", fake)
    out, _ = content.verify_mcqs(qs, "pages")
    return out, calls


def test_agreeing_examiner_keeps_the_key(monkeypatch):
    out, calls = run(monkeypatch, [mcq(1, 0), {"id": "s", "type": "short", "question": "Why?", "model_answer": "x"}],
                     {"questions": [verdict(1, "a.", why="A is right.")]})
    assert [q["id"] for q in out] == ["q1", "s"] and out[0]["explanation"] == "A is right."
    assert len(calls) == 1  # no dispute, no tie-break


def test_dispute_is_settled_two_out_of_three(monkeypatch):
    qs = [mcq(1, 0), mcq(2, 0), mcq(3, 0)]
    first = {"questions": [verdict(1, "D"), verdict(2, "B"), verdict(3, "C")]}
    tie = {"questions": [verdict(1, "D", why="D wins."), verdict(2, "A", why="A after all."), verdict(3, "B")]}
    out, calls = run(monkeypatch, qs, first, tie)
    assert len(calls) == 2 and "1. Q" in calls[1]
    assert [(q["id"], q["answer_index"], q["explanation"]) for q in out] == [
        ("q1", 3, "D wins."), ("q2", 0, "A after all.")]  # q3: three different answers, dropped


def test_unsure_or_unmatched_answers_drop_the_question(monkeypatch):
    qs = [mcq(1, 0), mcq(2, 1), mcq(3, 2)]
    out, _ = run(monkeypatch, qs, {"questions": [verdict(1, "A", confident=False), verdict(2, "NONE")]})
    assert [q["id"] for q in out] == ["q3"]  # q3 got no verdict, so it stays as written
