"""A catalog for tests: the packaged one plus the manual names older tests already use."""

from growbridge.vocab import load_catalog, packaged_text

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
