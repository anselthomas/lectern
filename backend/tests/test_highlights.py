from app.content import highlight_blocks


def test_model_highlights_are_kept_but_capped():
    blocks = [{"type": "para", "text": "==One== then ==two== then ==three== then ==four=="}]
    out = highlight_blocks(blocks)[0]["text"]
    assert out == "==One== then ==two== then ==three== then four"


def test_whole_sentence_highlight_is_dropped():
    long = "this highlight runs on for far too many words to be a real student highlight at all"
    out = highlight_blocks([{"type": "para", "text": f"Start. =={long}== End."}])[0]["text"]
    assert "==" not in out and long in out


def test_unmarked_lesson_falls_back_to_key_terms():
    blocks = [{"type": "key_term", "term": "Mother tincture", "text": "A ==strong== alcoholic extract."},
              {"type": "para", "text": "A mother tincture is made first; every mother tincture is then diluted."},
              {"type": "heading", "text": "==Making== it"}]
    term, para, heading = highlight_blocks(blocks)
    assert term["text"] == "A strong alcoholic extract."
    assert para["text"] == "A ==mother tincture== is made first; every mother tincture is then diluted."
    assert heading["text"] == "Making it"


def test_running_twice_changes_nothing():
    blocks = [{"type": "key_term", "term": "dose", "text": "Amount taken."},
              {"type": "para", "text": "The dose matters."}]
    once = highlight_blocks(blocks)
    assert highlight_blocks(once) == once


def test_backfill_keeps_only_unchanged_wording(monkeypatch):
    from app import content
    blocks = [{"type": "para", "text": "Drugs come from plants and minerals."},
              {"type": "para", "text": "Potency is diluted step by step."}]
    reply = {"texts": ["Drugs come from ==plants and minerals==.", "Potency is ==reduced== gradually."]}
    monkeypatch.setattr(content.llm, "call_json", lambda **kw: (reply, None))
    out, _ = content.add_highlights(blocks)
    assert out[0]["text"] == "Drugs come from ==plants and minerals==."
    assert out[1]["text"] == "Potency is diluted step by step."  # the model changed the words, so it's ignored
