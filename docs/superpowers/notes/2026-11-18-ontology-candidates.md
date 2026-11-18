# Ontology term candidates for the variable catalog

Lookup date: 2026-11-18. Nothing here is in `src/growbridge/vocab/catalog.toml` yet.

## Purpose

The training-dataset export will be merged with crop data from other sources, aligned through the ontology
terms in each catalog entry's `refs` and in `[unit_refs]`. A wrong term is worse than none: two sources
carrying the same term are treated as the same quantity. So each term below is a proposal, and only the
rows you confirm go into the catalog (catalog `version` 1 → 2).

## How to answer

Reply with each numbered row and yes or no, for example: `1 yes, 2 no, 10 yes (the probe is in soil)`.

- "My pick" is my recommendation only.
- Rows marked *conditional* need one fact from you (stated in the row).
- Items under "Considered, not proposed" have no number. They show what was checked and why it was left out.
  Name one if you want it promoted.
- Only the prefixes the loader accepts are numbered (`CO_<digits>`, `PECO`, `ENVO`, `AGRO`, `PATO`, `UO`,
  `NCBITaxon`). Better-fitting terms from other ontologies are in the last-but-one section, for a later
  decision on widening the list.

## Ontology versions used

| Ontology | Version | Where |
|---|---|---|
| ENVO | 2026-10-23 | OLS4 |
| PATO | 2026-10-01 | OLS4 |
| PECO | release 2025-12-02 | OLS4 |
| AGRO | release 2022-11-02 (the version OLS4 serves) | OLS4 |
| UO | 2026-10-12 | OLS4 |
| CO_715 Crop Research Ontology | last submission 2018-06-07, status **Retired** | AgroPortal |
| CO_325 Banana, CO_330 Potato | 2019-04-18, 2019-01-22 | cropontology.org BrAPI |

OLS term pages: `https://www.ebi.ac.uk/ols4/ontologies/<ontology>/classes/<IRI, URL-encoded twice>`, linked as
"OLS" in each row. Definitions are the term's `IAO:0000115` text (one sentence at most); comments and
editor notes are labelled as such.

## Summary

| Entry / unit | My pick | Rows |
|---|---|---|
| `air_temperature` | ENVO:09200001 | 1–2 |
| `air_relative_humidity` | AGRO:00000637 | 3–4 |
| `vapour_pressure_deficit` | none (only a retired, undefined term exists) | 5 |
| `co2_concentration` | ENVO:04000004 | 6–7 |
| `photosynthetic_photon_flux_density` | ENVO:06105204 | 8–9 |
| `soil_temperature` | ENVO:09200012 *conditional* (else ENVO:09200000) | 10–11 |
| `canopy_area_growth` | **no fitting term** | — |
| `light` | PECO:0007224, as the factor's type only | 12 |
| `Cel` | UO:0000027 | 13 |
| `%` | UO:0000187 | 14 |
| `kPa` | **no fitting term** | — |
| `[ppm]` | UO:0000169 | 15 |
| `umol/m2/s` | UO:0000160 | 16 |
| `cm2/d` | **no fitting term** | — |

## Entries

### `air_temperature`: sensor, `Cel`

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 1 | ENVO:09200001 | temperature of air | "The temperature of some air." | Quantity and material both named; exact synonym "air temperature"; parent ENVO:09200000 temperature of environmental material → PATO:0000146 temperature. ENVO's "air" (ENVO:00002005) is defined by its gas composition, so tent air qualifies. | Says nothing about sensor height or shading (that is method, not quantity). | **yes** |
| 2 | PATO:0000146 | temperature | "A physical quality of the thermal energy of a system." | The general quality. | Too general on its own: `soil_temperature` would carry the same term and a merge on it would mix air and soil. Row 1 already implies it. | no |

Sources: [OLS ENVO:09200001](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_09200001),
[OLS PATO:0000146](https://www.ebi.ac.uk/ols4/ontologies/pato/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPATO_0000146).

Considered, not proposed:
- ENVO:01000753 "obsolete air temperature": obsolete in ENVO, replaced by ENVO:09200001. Some other
  ontologies on OLS (e.g. APOLLO_SV) still show it as live; do not use it.
- AGRO:00000628 "temperature of air average" and the daily/monthly/yearly/minimum/maximum variants
  (AGRO:00000626–00000633): aggregates. The export's `sensor_readings.csv` holds time-point readings.
- PECO:0007319 / 0007332 / 0007384 high / cold / freezing air temperature exposure: treatments, not a
  measured variable.
- CO_715:0000118 "Temperature" (retired ontology): its definition asks for "either the monthly or the
  annual mean".

### `air_relative_humidity`: sensor, `%`

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 3 | AGRO:00000637 | relative humidity | "Humidity that correspond to moisture content of the atmosphere, expressed as a percentage of the amount of moisture that can be retained by the atmosphere at a given temperature and pressure without condensation." | The relative quantity, in percent, of air; parent PATO:0015009 humidity. | Says "atmosphere" where the tent is enclosed indoor air; the ratio is the same physical quantity. The AGRO release on OLS4 is from 2022. | **yes** |
| 4 | PATO:0015009 | humidity | "A quality inhering in air by virtue of the partial pressure exerted by the bearer's water vapour content." | Humidity of air. | Does not separate relative from absolute humidity, and the definition is about partial pressure (closer to vapour pressure in kPa). A merge on it could join RH % with absolute humidity. | no |

Sources: [OLS AGRO:00000637](https://www.ebi.ac.uk/ols4/ontologies/agro/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FAGRO_00000637),
[OLS PATO:0015009](https://www.ebi.ac.uk/ols4/ontologies/pato/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPATO_0015009).

Considered, not proposed:
- ENVO:09200015 "humidity of soil": wrong material.
- PECO:0007197 "humidity exposure": a treatment.
- ENVO has no "relative humidity" term (searched OLS ENVO for "relative humidity" and "humidity of air").

### `vapour_pressure_deficit`: sensor, `kPa`

No usable term in the allowed prefixes. The only label match is row 5, which I recommend rejecting.

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 5 | CO_715:0000164 | Vapor pressure deficit | none given | Label matches; prefix is allowed. Parent CO_715:0000163 "Climatic condition". | The ontology (Crop Research Ontology) is marked **Retired** on AgroPortal, last submitted 2018. No definition, so it cannot be checked against our quantity (air saturation deficit vs leaf-to-air VPD). It sits with site climate descriptors. The IRI the export's `@context` would write, `https://cropontology.org/rdf/CO_715:0000164`, returns RDF with no class for this term; cropontology.org's BrAPI returns an empty result for it. | no |

Source: [AgroPortal CO_715:0000164](https://agroportal.eu/ontologies/CO_715?p=classes&conceptid=http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FCO_715_0000164),
found via [AgroPortal search](https://agroportal.eu/search?query=vapour+pressure+deficit).

Considered, not proposed:
- ENVO:09200033 "pressure of atmospheric water vapour" ("The pressure of some atmospheric water vapour."):
  the actual vapour pressure, not the deficit (VPD = saturation pressure − actual pressure). Different quantity.
- PATO:0001025 "pressure": too general.

### `co2_concentration`: sensor, `[ppm]`

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 6 | ENVO:04000004 | concentration of carbon dioxide in air | "The concentration of carbon dioxide when measured in air." | Quantity (parent PATO:0000033 "concentration of"), substance and material all named. Not tied to the outdoor atmosphere. | Does not say mole vs mass basis; the unit row (15) carries ppm. | **yes** |
| 7 | ENVO:01001865 | concentration of carbon dioxide in an atmosphere | "The concentration of carbon dioxide when measured in air that is part of an atmosphere." | Same quantity. | ENVO's "atmosphere" (ENVO:01000267) is "a layer of gases surrounding a material body of sufficient mass that is held in place by the gravity of the body", i.e. ambient outdoor air. Tent air is enclosed and may be CO2-enriched. | no |

Sources: [OLS ENVO:04000004](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_04000004),
[OLS ENVO:01001865](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_01001865).

Considered, not proposed:
- ENVO:04000003 "concentration of carbon dioxide in soil": wrong material.
- ENVO:01000451 "atmospheric carbon dioxide": the material, not its concentration.
- PECO:0001020 "carbon dioxide exposure", PECO:0001056 "elevated carbon dioxide exposure": treatments.
  They would fit a CO2 *factor*, not this sensor reading.

### `photosynthetic_photon_flux_density`: sensor, `umol/m2/s`

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 8 | ENVO:06105204 | photosynthetic photon flux density | "A rate which is characteristic of irradiance by photosynthetically active radiation by virtue of the number of photons received by an irradiated surface over time." | Exact synonym "PPFD"; its comment gives the unit as micromoles of photons per square meter per second. Not limited to sunlight. | Editor note: "A best-guess at representing 'density' of massless entities - likely to require further expert input and refinement." Its modelling may change; the IRI should stay. | **yes** |
| 9 | ENVO:01001864 | photosynthetically active radiation | "Electromagnetic radidation which involves radiant energy in a spectral range (wave band) between 400 to 700 nanometers, that photosynthetic organisms are able to use in the process of photosynthesis." | The radiation that PPFD counts. | It is the radiation itself, not a flux density, so it cannot carry a value in µmol m⁻² s⁻¹. | no |

Sources: [OLS ENVO:06105204](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_06105204),
[OLS ENVO:01001864](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_01001864).

Considered, not proposed:
- ENVO:06105213 "photosynthetic photon flux" (synonym PPF): photons per second without the area, i.e. a
  lamp's output. Different quantity.
- PECO:0007224 "light intensity exposure": a treatment (see `light`).

### `soil_temperature`: sensor, `Cel`

**Question for you:** what is the `tempSoil` probe in? Soil, a soil-based mix, a soilless potting mix
(peat, coco, perlite), rockwool, or nutrient solution?

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 10 | ENVO:09200012 | temperature of soil | "The temperature of some soil." | Quantity and material named; exact synonym "soil temperature". | ENVO's soil (ENVO:00001998) is "primarily composed of minerals, varying proportions of sand, silt, and clay, organic material such as humus, interstitial gases, liquids, and a broad range of resident micro- and macroorganisms". A soilless mix is a different ENVO material: ENVO:03000133 agricultural potting mixture, whose comment says it often contains "little or no actual soil". | *conditional*: **yes** if the probe is in soil or a soil-based mix |
| 11 | ENVO:09200000 | temperature of environmental material | "The temperature of some environmental material." | Covers any substrate, including potting mix (ENVO:03000133 → agricultural → anthropogenic → environmental material) and water. | Generic. It is also the parent of ENVO:09200001 (air), so a merge that follows subclasses would group it with air temperature; an exact-CURIE merge would not. | *conditional*: yes only if the substrate is not soil (then also consider relabelling the entry) |

Sources: [OLS ENVO:09200012](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_09200012),
[OLS ENVO:09200000](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_09200000),
[OLS ENVO:03000133](https://www.ebi.ac.uk/ols4/ontologies/envo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FENVO_03000133).

Considered, not proposed:
- ENVO:09200014 "temperature of water": fits only if the probe sits in nutrient solution; tell me and I
  will add it as a row.

### `canopy_area_growth`: manual, `cm2/d`, "Canopy area from top-view images, change per day"

**No fitting term.** Nothing in any searched ontology names the daily change of projected canopy area. No
Crop Ontology exists for lettuce (none among the 40 trait dictionaries listed by cropontology.org BrAPI),
and a Crop Ontology term belongs to one crop's trait dictionary.

Considered, not proposed:
- CO_325:0000954 "Increase of leaf area" (Banana). Trait description: "Leaf area increase over time". Its
  variable CO_325:0000916 is the difference between two time points in cm² (not per day). Banana's
  dictionary, so a merge would claim a banana trait.
- CO_325:0000921 "Projected top area" (Banana). Trait description: "The projected leaf area of a plant
  (photosynthetic surface)". The method is "Top view image", like ours, but it is the area, not its daily
  change, and it is for banana.
- CO_330:0000703 "Canopy cover" (Potato): percent ground cover, a different quantity.
- PATO:0001492 "growth rate" ("The rate or speed of the change in size of an individual entity or change in
  number of a population."), PATO:0040046 "single organismal growth rate", PATO:0001323 "area",
  ENVO:01001241 "crop canopy". These are the pieces of an entity–quality description. Each is far too
  general alone (growth rate of anything; area of anything), and `refs` is a flat list that cannot say
  "rate of change of the area of the crop canopy". Any one of them would set `mapped = true` and match
  unrelated growth rates.

If the first experiment's crop has a Crop Ontology, or Crop Ontology curators add a lettuce dictionary,
this entry should be looked up again.

### `light`: treatment factor, `%` (dimming level set by the controller)

**No PECO term describes a dimming level.** PECO "describes the treatments, growing conditions, and/or
study types used in plant biology experiments" (OLS ontology description), so it can name the *kind* of
treatment this factor applies, but not a lamp-driver setting.

| # | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|
| 12 | PECO:0007224 | light intensity exposure | "An exposure of a plant or a plant part to the amount of light energy incident upon (or flowing through) a unit area in unit time." | Names the treatment the dimming manipulates: how much light reaches the plants. Annotating a factor's type with PECO is PECO's purpose. | The factor's values are a percent of the lamp's maximum output, not an intensity. The same % gives a different intensity with another lamp, hanging height or tent. So the term fits the factor's type, never its levels. Other sources' "light intensity" factors will have levels in µmol m⁻² s⁻¹ or lux. A merge must also match on unit and must not compare levels across sources; the PPFD sensor column is the comparable quantity. | **yes, as factor type only**, if the merge keeps the unit; otherwise leave empty |

Source: [OLS PECO:0007224](https://www.ebi.ac.uk/ols4/ontologies/peco/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPECO_0007224).

Considered, not proposed:
- PECO:0007075 / 0007076 / 0007271 high / moderate / low light intensity exposure: each is a level defined
  by a foot-candle range (high: "between 500–1,000 foot-candles"). A dimming % cannot be placed in one
  without measuring at the canopy, and these would describe levels, not the variable.
- PECO:0007078 "light quantity exposure": about duration and total light (photoperiod), not intensity.
- PECO:0007151 "radiation exposure": too general.
- CO_715:0000124 "Light intensity": retired ontology, no definition, does not resolve on cropontology.org.
- UO:0000312 "relative light unit": a luminometer unit, not a dimming level.
- Aside, not a catalog row: PECO:0007269 "growth chamber study" ("A plant study condition (PECO:0007231)
  where plants were grown in growth chambers under controlled light and temperature conditions.") may suit
  study-level metadata later.

## Units (`[unit_refs]`)

`[unit_refs]` maps each UCUM code to one UO term for the whole catalog, so a mapping applies to every entry
that uses that code, now and later.

| # | UCUM | CURIE | Label | Definition | Fits | Does not quite fit | My pick |
|---|---|---|---|---|---|---|---|
| 13 | `Cel` | UO:0000027 | degree Celsius | "A temperature unit which is equal to one kelvin degree." | Exact; synonym "C". | — | **yes** |
| 14 | `%` | UO:0000187 | percent | "A dimensionless ratio unit which denotes numbers as fractions of 100." | Exact; synonym "%". Serves both `air_relative_humidity` and `light`. | — | **yes** |
| — | `kPa` | **no fitting term** | | | UO has no kilopascal. Under UO:0000109 pressure unit there are only millimetres of mercury, pounds per square inch and "pascal based unit" (pascal, bar). | Mapping `kPa` to UO:0000110 pascal would be off by a factor of 1000. | leave empty |
| 15 | `[ppm]` | UO:0000169 | parts per million | "A dimensionless concentration notation which denotes the amount of a given substance in a total amount of 1,000,000 regardless of the units of measure used as long as they are the same or 1 part in 10^[6]." | Exact; synonym "ppm". | Does not say mole vs mass basis (CO2 sensors give µmol/mol); UCUM `[ppm]` does not either, so the two match. | **yes** |
| 16 | `umol/m2/s` | UO:0000160 | microeinstein per square meter per second | "An irradiance unit which is equal to one microeinstein per square meter per second or 10^[-6] microeinstein/sm^[2]." | One einstein is one mole of photons, so for PPFD the values are identical; UO lists the synonym "micromole per second and square meter". | It is a photon unit, while UCUM `umol/m2/s` is any substance. If a later entry uses `umol/m2/s` for something else (e.g. CO2 assimilation), this mapping would be wrong for it. "einstein" is not SI. The definition's own arithmetic is garbled. | **yes**, while PPFD is the only user |
| — | `cm2/d` | **no fitting term** | | | UO has square centimeter (UO:0000081) and day (UO:0000033) but no compound. | | leave empty |

Sources: [OLS UO:0000027](https://www.ebi.ac.uk/ols4/ontologies/uo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FUO_0000027),
[OLS UO:0000187](https://www.ebi.ac.uk/ols4/ontologies/uo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FUO_0000187),
[OLS UO:0000169](https://www.ebi.ac.uk/ols4/ontologies/uo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FUO_0000169),
[OLS UO:0000160](https://www.ebi.ac.uk/ols4/ontologies/uo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FUO_0000160),
[OLS UO:0000109 children](https://www.ebi.ac.uk/ols4/ontologies/uo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FUO_0000109).

## Outside the allowed prefixes

Not proposable now: the loader refuses these prefixes. Listed in case the prefix list is widened.
Definitions marked "paraphrased" were read on an AgroPortal page that did not give the full text.

| Entry / unit | Term | Ontology (version) | Definition | Why it is of interest | Source |
|---|---|---|---|---|---|
| `vapour_pressure_deficit` | CGO `#VPD` "Vapour Pressure Deficit" | Common Greenhouse Ontology 2.2, AgroPortal last submission 2024-12-19 | starts "Vapour-pressure deficit, or VPD, is the difference (deficit) between the amount of moisture in the air" (truncated on the page) | Greenhouse-specific; subclass of `sosa:ObservableProperty`, i.e. a measured property. Best fit found anywhere. | [AgroPortal](https://agroportal.eu/ontologies/CGO?p=classes&conceptid=https%3A%2F%2Fwww.tno.nl%2Fagrifood%2Fontology%2Fcommon-greenhouse-ontology%23VPD) |
| `vapour_pressure_deficit` | MIAPPE_DP_V2_0111 "Vapour pressure deficit" | DataPLANT MIAPPE Ontology V2, last submission 2026-09-16 | paraphrased: hourly VPD over the experiment during the light period, in kPa | MIAPPE-aligned (Swate templates). | [AgroPortal](https://agroportal.eu/ontologies/MIAPPE-DP-V2?p=classes&conceptid=http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FMIAPPE_DP_V2_0111) |
| `vapour_pressure_deficit` | AGROVOC c_3eb4cfb4; NALT 324729 | thesauri | paraphrased: moisture in air vs. what saturated air holds | Thesaurus concepts, not formal quantities. | [AgroPortal search](https://agroportal.eu/search?query=vapour+pressure+deficit) |
| `air_relative_humidity` | AFO `AFR_0002614` "relative humidity" | Allotrope REC/2026/09 | "Relative humidity is the ratio, often expressed as a percentage, of the partial pressure of water in the atmosphere at some observed temperature, to the saturation vapor pressure of pure water at this temperature." | IUPAC definition; more precise than AGRO's. | [OLS search](https://www.ebi.ac.uk/ols4/api/search?q=relative+humidity&rows=15) |
| `air_relative_humidity` | CGO `#RelativeHumidity`; OM `om-2:RelativeHumidity` | CGO 2.2; OM 2 | paraphrased: moisture in air as a ratio to its holding capacity at that temperature and pressure | Greenhouse context; OM pairs it with a unit. | [AgroPortal search](https://agroportal.eu/search?query=humidity&ontologies=MIAPPE-DP-V2,CGO) |
| `air_temperature` | XCO:0000011 "air temperature" | XCO 2026-11-14 | "The degree of heat or cold of the air surrounding an organism." | Parent XCO:0000111 "temperature exposure": an exposure condition, not a measured quantity. | [OLS search](https://www.ebi.ac.uk/ols4/api/search?q=air+temperature&rows=15) |
| `air_temperature` | MIXS:0000124 "air temperature"; MIAPPE_DP_V2_0096 "Air temperature" | MIxS (OLS, 2026-11-18); MIAPPE-DP-V2 | MIxS: "Temperature of the air at the time of sampling" | Metadata fields rather than quantities. | OLS; [AgroPortal search](https://agroportal.eu/search?query=air+temperature&ontologies=CGO,MIAPPE-DP-V2,AGROVOC) |
| `co2_concentration` | CHEBI:16526 "carbon dioxide" | ChEBI 257 | — | Only needed for a PATO-composed form (PATO:0000033 + CHEBI:16526); ENVO:04000004 already composes it. | OLS |
| `co2_concentration` | CGO `#CO2` "Carbon Dioxide" | CGO 2.2 | paraphrased: CO2 and its effect on greenhouse photosynthesis, unit ppm | The substance, not its concentration. | [AgroPortal search](https://agroportal.eu/search?query=carbon+dioxide&ontologies=MIAPPE-DP-V2,CGO) |
| `photosynthetic_photon_flux_density` | MIAPPE_DP_V2_0101 "Light intensity" | MIAPPE-DP-V2 | example unit "[μmol m–2 s–1]" | MIAPPE's slot for PPFD-type light intensity. | [AgroPortal search](https://agroportal.eu/search?query=light&ontologies=MIAPPE-DP-V2,CGO) |
| `soil_temperature` | MIAPPE_DP_V2_0126 "Medium temperature" | MIAPPE-DP-V2 | example "[°C]" | Substrate-neutral; useful if the probe is not in soil. | [AgroPortal search](https://agroportal.eu/search?query=air+temperature&ontologies=CGO,MIAPPE-DP-V2,AGROVOC) |
| `canopy_area_growth` | TOP73 "Plant leaf area"; SOY_0002230 "Canopy coverage"; TO:0012001 "leaf area index" | TOP; SOY; TO 2026-01-14 | paraphrased: sum of leaf areas on a shoot; percent of ground covered; leaf area per ground area | None is projected canopy area or its rate; listed to show nothing fits outside either. | [AgroPortal](https://agroportal.eu/search?query=projected+leaf+area), [AgroPortal](https://agroportal.eu/search?query=canopy+area) |
| `kPa` | NCIT:C67284 "Kilopascal" | NCIT 26.02d | "A SI derived unit of pressure equivalent to 1000 newtons per square meter or 10000 bars or to 0.145 pound per square inch." | The only kilopascal term on OLS. Its definition is wrong (1 kPa is 0.01 bar). | [OLS search](https://www.ebi.ac.uk/ols4/api/search?q=kilopascal&rows=8) |

## Searches that found nothing usable

OLS4 (`https://www.ebi.ac.uk/ols4/api/search?q=<words>[&ontology=<id>]`):
- "vapour pressure deficit", "vapor pressure deficit" (all ontologies, and envo, agro, peco), "VPD",
  "pressure deficit", "saturation deficit"
- "relative humidity" in envo, pato, peco; "humidity of air" in envo
- "photosynthetic photon flux density" in agro, peco
- "projected leaf area", "projected shoot area", "rosette area", "shoot area", "canopy size",
  "canopy growth", "leaf area growth rate", "area growth rate", "absolute growth rate",
  "vegetative growth rate" (all ontologies); "growth rate" in to; "canopy", "leaf area" in agro;
  "plant growth" in peco
- "dimming", "dimmer", "light level", "light intensity setting", "lamp power" (all ontologies);
  "artificial light" in peco
- "kilopascal", "kPa" in uo; "square centimeter per day", "square centimeters per day" (all ontologies);
  "area per time" in uo
- "indoor air" in envo

cropontology.org (`https://cropontology.org/search?q=<words>`):
- 0 results: "canopy area", "canopy growth", "relative humidity", "vapor pressure deficit",
  "vapour pressure deficit"
- Results, none usable: "lettuce" (two strawberry lab methods), "air temperature" (canopy temperature
  depression), "photosynthetically active radiation" / "photon flux" / "PPFD" / "light intensity" (woody
  plant leaf gas-exchange protocols), "soil temperature" (sweet potato reaction to heat), "carbon dioxide" /
  "CO2" (leaf gas-exchange traits), "canopy cover", "ground cover", "leaf area", "plant area",
  "growth rate", "rosette" (other crops' traits)

AgroPortal, filtered to CO_715: "humidity", "radiation", "carbon dioxide" (no results).
