"""A catalog for tests: the packaged one plus the manual names older tests already use."""

import re

from growbridge.vocab import load_catalog, packaged_text

_REFS = re.compile(r"^refs = \[.*\]$", re.MULTILINE)
_UNIT_REFS = re.compile(r"^\[unit_refs\]\n(?:[^\[\n].*\n|\n)*", re.MULTILINE)


def bare_packaged_text() -> str:
    """The packaged catalog with its confirmed ontology terms taken out: every ``refs`` empty and
    no ``[unit_refs]`` table. For tests that exercise the term format with their own values, so
    they do not depend on which terms the researcher has confirmed."""
    return _REFS.sub("refs = []", _UNIT_REFS.sub("", packaged_text()))


TEST_ENTRIES = """
[[variable]]
id = "height"
kind = "manual"
label_en = "Plant height"
label_zh = "株高"
quantity = "length"
unit = "cm"
method = "ruler, soil to apex"
refs = []

[[variable]]
id = "yield_g"
kind = "manual"
label_en = "Yield (g)"
label_zh = "产量（克）"
quantity = "mass"
unit = "g"
method = "fresh weight of harvest"
refs = []

[[variable]]
id = "yield"
kind = "manual"
label_en = "Yield"
label_zh = "产量"
quantity = "mass"
unit = "g"
method = "fresh weight of harvest"
refs = []

[[variable]]
id = "canopy_score"
kind = "manual"
label_en = "Canopy score"
label_zh = "冠层评分"
quantity = "score"
unit = "{score}"
method = "visual score of the canopy"
refs = []
"""
TEST_CATALOG = load_catalog(packaged_text() + TEST_ENTRIES)

OLD_ENTRY = """
[[variable]]
id = "canopy_growth_old"
kind = "manual"
label_en = "Canopy growth (old)"
label_zh = "冠层增长（旧）"
quantity = "area_growth_rate"
unit = "cm2/d"
method = "old method"
deprecated = true
replaced_by = "canopy_area_growth"
refs = []
"""
WITH_OLD = load_catalog(packaged_text() + OLD_ENTRY)
