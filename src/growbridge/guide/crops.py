"""The crops a guided setup offers. Each NCBI Taxonomy ID was looked up in NCBI Taxonomy
(E-utilities esearch on the scientific name, then esummary to confirm rank is species) on
``CHECKED_ON``; never add one from memory."""

from growbridge.archive.models import Model

CHECKED_ON = "2026-11-27"


class Crop(Model):
    key: str
    label_en: str
    label_zh: str
    scientific_name: str  # as NCBI Taxonomy spells it
    taxon: str  # NCBITaxon:<id>


CROPS: tuple[Crop, ...] = (
    Crop(
        key="lettuce",
        label_en="Lettuce",
        label_zh="生菜",
        scientific_name="Lactuca sativa",
        taxon="NCBITaxon:4236",
    ),
    Crop(
        key="tomato",
        label_en="Tomato",
        label_zh="番茄",
        scientific_name="Solanum lycopersicum",
        taxon="NCBITaxon:4081",
    ),
    Crop(
        key="cucumber",
        label_en="Cucumber",
        label_zh="黄瓜",
        scientific_name="Cucumis sativus",
        taxon="NCBITaxon:3659",
    ),
    Crop(
        key="pepper",
        label_en="Pepper",
        label_zh="辣椒",
        scientific_name="Capsicum annuum",
        taxon="NCBITaxon:4072",
    ),
    Crop(
        key="strawberry",
        label_en="Strawberry",
        label_zh="草莓",
        scientific_name="Fragaria x ananassa",
        taxon="NCBITaxon:3747",
    ),
    Crop(
        key="spinach",
        label_en="Spinach",
        label_zh="菠菜",
        scientific_name="Spinacia oleracea",
        taxon="NCBITaxon:3562",
    ),
    Crop(
        key="basil",
        label_en="Basil",
        label_zh="罗勒",
        scientific_name="Ocimum basilicum",
        taxon="NCBITaxon:39350",
    ),
    Crop(
        key="arabidopsis",
        label_en="Arabidopsis",
        label_zh="拟南芥",
        scientific_name="Arabidopsis thaliana",
        taxon="NCBITaxon:3702",
    ),
)
