import re

import pytest

from growbridge.research.notes import LANGUAGES, TEMPLATES, note


def test_every_note_has_both_languages_with_the_same_placeholders():
    for code, texts in TEMPLATES.items():
        assert set(texts) == set(LANGUAGES), code
        names = {lang: set(re.findall(r"\{(\w+)\}", text)) for lang, text in texts.items()}
        assert names["en"] == names["zh"], code


def test_a_note_renders_its_params_in_each_language():
    problems = [
        {"channel": "light", "kind": "never_at", "level": 70, "recorded": [20], "share": 0.0}
    ]
    item = note("treatment_not_applied", round=1, treatment="High light", problems=problems)

    assert item.text("en") == (
        "Round 1 did not run its allocated treatment High light: "
        "light was never at 70 (recorded 20)"
    )
    assert item.text() == "第 1 轮没有按分配的处理 High light 运行：光照从未处于 70 档（记录到 20）"
    entry = item.entry("limitation")
    assert entry["code"] == "treatment_not_applied" and entry["kind"] == "limitation"
    assert entry["text"] == {"en": item.text("en"), "zh": item.text("zh")}


def test_an_unknown_code_is_refused():
    with pytest.raises(KeyError):
        note("made_up")


def test_treatment_problems_are_data_and_read_in_both_languages():
    problems = [
        {"channel": "light", "kind": "never_at", "level": 70, "recorded": [0, 20], "share": 0.0},
        {"channel": "fan", "kind": "other_share", "level": 3, "recorded": [3, 5], "share": 0.5},
    ]
    item = note("treatment_not_applied", round=2, treatment="High light", problems=problems)

    zh = item.text("zh")
    assert "never" not in zh and "[" not in zh and "recorded" not in zh and "readings" not in zh
    assert "光照" in zh and "风扇" in zh and "50%" in zh
    en = item.text("en")
    assert "light was never at 70 (recorded 0, 20)" in en and "50%" in en
    assert item.entry("limitation")["params"]["problems"] == problems


def test_unverified_channels_and_missed_tasks_are_lists_and_counts():
    unverified = note("treatment_unverified", round=1, treatment="High", channels=["light", "fan"])
    missed = note(
        "manual_tasks_missed",
        round=2,
        missed=3,
        total=4,
        by_kind={"irrigation": 2, "photo": 1},
    )

    assert unverified.text("zh") == (
        "第 1 轮的样本没有记录 光照、风扇 的档位，无法核对处理 High 是否执行"
    )
    assert "light, fan" in unverified.text("en")
    assert "浇水" in missed.text("zh") and "irrigation" not in missed.text("zh")
    assert missed.text("en").endswith("(irrigation 2, photo 1)")


def test_a_coverage_share_reads_as_a_percentage():
    item = note("snapshot_incomplete", coverage=0.87)

    assert "87%" in item.text("en") and "87%" in item.text("zh")
    assert item.entry("reason")["params"] == {"coverage": 0.87}
