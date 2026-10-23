from app.content import copied_blocks

SOURCE = ("Pharmacy is the art and science of collecting, combining, compounding, preparing, preserving and "
          "standardising drugs and medicines from natural and synthetic sources. It also includes dispensing.")


def test_verbatim_block_is_detected():
    blocks = [{"type": "para", "text": "Pharmacy is the art and science of collecting, combining, compounding, "
                                       "preparing, preserving and standardising drugs."}]
    assert copied_blocks(blocks, SOURCE) == 1


def test_paraphrase_and_key_terms_pass():
    blocks = [{"type": "para", "text": "Think of pharmacy as the craft of turning raw plant, animal or mineral "
                                       "material into medicines you can safely take."},
              {"type": "key_term", "term": "Pharmacy", "text": SOURCE}]  # short quoted definitions are allowed
    assert copied_blocks(blocks, SOURCE) == 0
