import re

import pytest

from growbridge.research.notes import LANGUAGES, TEMPLATES, note


def test_every_note_has_both_languages_with_the_same_placeholders():
    for code, texts in TEMPLATES.items():
        assert set(texts) == set(LANGUAGES), code
        names = {lang: set(re.findall(r"\{(\w+)\}", text)) for lang, text in texts.items()}
        assert names["en"] == names["zh"], code


def test_a_note_renders_its_params_in_each_language():
    item = note("treatment_not_applied", round=1, treatment_id="high", problems=["a", "b"])

    assert item.text("en") == "Round 1 did not run its allocated treatment high: a; b"
    assert item.text() == "第 1 轮没有按分配的处理 high 运行：a; b"  # the plain-text language
    entry = item.entry("limitation")
    assert entry["code"] == "treatment_not_applied" and entry["kind"] == "limitation"
    assert entry["text"] == {"en": item.text("en"), "zh": item.text("zh")}


def test_an_unknown_code_is_refused():
    with pytest.raises(KeyError):
        note("made_up")
