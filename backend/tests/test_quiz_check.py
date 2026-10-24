from app import content


def test_examiner_fixes_keys_and_drops_ambiguous(monkeypatch):
    qs = [{"id": "q1", "type": "mcq", "question": "Which is NOT a branch?", "options": ["A", "B", "C", "D"],
           "answer_index": 0, "explanation": "Mentions some other option."},
          {"id": "q2", "type": "mcq", "question": "Two right answers?", "options": ["A", "B", "C", "D"],
           "answer_index": 1, "explanation": "x"},
          {"id": "q3", "type": "short", "question": "Explain it.", "model_answer": "Because."},
          {"id": "q4", "type": "mcq", "question": "Fine one", "options": ["A", "B", "C", "D"],
           "answer_index": 2, "explanation": "kept"}]
    reply = {"questions": [{"n": 1, "correct_option": "d.", "explanation": "D is not a branch."},
                           {"n": 2, "correct_option": "NONE", "explanation": "B and C both fit."}]}
    monkeypatch.setattr(content.llm, "call_json", lambda **kw: (reply, content.llm.Usage()))
    out, _ = content.verify_mcqs(qs, "pages")
    assert [q["id"] for q in out] == ["q1", "q3", "q4"]
    assert out[0]["answer_index"] == 3 and out[0]["explanation"] == "D is not a branch."
    assert out[2] == qs[3]  # no verdict returned: left as written
