# Attribute dictionary – every layer of both extractions

This file documents the attribute table of **every shapefile** in `shapefiles/` (Geological Map of Nigeria, 2011 PDF)
and `shapefiles_minerals/` (Mineral Resources Map of Nigeria, 2023 GeoPDF), how each attribute was derived, and the
fill rate of every field as measured on the delivered files (section 4, generated with
`python inventory_attributes.py --markdown`).  All coordinates are WGS 84 (EPSG:4326); sizes are computed on the
ellipsoid-free sphere (111.32 km per degree of longitude at the equator × cos(lat), 110.57 km per degree of latitude),
which is accurate to well under 1 % at this scale.

## 1. Geology (2011 map) – stratigraphy of the rock units

The PDF has no attribute tables.  The age of each unit was **read from the printed EXPLANATIONS panel itself**:

* the 92 legend swatches (13 pt tall, one every 17.3 pt) were located from the fill polygons of the panel;
* the panel draws three kinds of curly brackets next to the swatches: **period brackets** (NEOGENE, TERTIARY TO RECENT
  VOLCANICS, PALAEOGENE, CRETACEOUS, JURASSIC, PRE-CAMBRIAN TO CAMBRIAN), **sub-age / series brackets** (Holocene,
  Pleistocene / Pliocene, Oligocene / Miocene + Upper Eocene, Middle Eocene, Palaeocene, Coniacian / Maastrichtian,
  Senonian, Turonian / Pre-Maastrichtian, Albian / Cenomanian, Albian, Per-Alkaline Younger Granite Series, Pan-African
  Older Granite Series, Meta-Sedimentary / Meta-Volcanic Series, Migmatite-Gneiss Complex, Cataclastic Rocks) and
  **single-row labels** (Recent, Lower Eocene, Coniacian).  Each bracket is the pair of vertical arms (plus the hook that
  continues the lower arm) of a stroked path in the layout layer; a swatch belongs to a bracket when ≥ 45 % of its
  height lies inside the bracket span.  A bracket label whose two lines belong to different rows (Oligocene / Miocene
  above Upper Eocene) is split one line per row;
* the **correlation chart** (top of the panel) gives the formation name for 31 codes ("Al Alluvium … Arlsh Asu River
  group") and the basins (Bida-Lokoja, Sokoto, Yola, Numan, Maiduguri, Gombe, S.E., S.W.) in which each code is drawn
  (`basins`); the legend descriptions that end in "--- Name Formation" give 40 more formation names (`formation`,
  `strat_grp`);
* the printed terms were then mapped to the International Chronostratigraphic Chart (2023) – `eon`, `era`, `period`,
  `epoch` (epoch / stage text) and numeric `age_ma_min` / `age_ma_max`.  Basement units get the series-level
  refinement that the printed series label allows (Pan-African granites = Ediacaran–Cambrian c. 485–1000 Ma; schist
  belts = Neoproterozoic; Migmatite-Gneiss Complex = Archaean–Palaeoproterozoic protoliths reworked in the
  Neoproterozoic).  `age_lit` (legend.csv only) carries a one-line literature note where the map's bracket is coarser
  than what is known (e.g. the Younger Granites are 213–141 Ma, the plateau basalts Miocene–Holocene).

`age_src` says, for every row and polygon, which of these produced the age.  91 of the 92 legend rows are dated from
the printed panel: 79 by a sub-age bracket, 3 by a row label, 1 by the extra Albian
bracket, 2 (Sa, bS) by the nearest series bracket (the two swatches sit ≤ 1.5 pt outside it), and
5 rows have **no bracket at all in the print** and are filled with a flagged fall-back (`Gss` Gombe Fm – Senonian
band of the chart; `Ajst` Ajali Fm – between Gombe and Nsukka; `Ts` – chart key Rima group; `MyP` – 2 pt above the
JURASSIC bracket; `P` Pegmatite – no age printed, left blank with a note).  Rows 8–9 (basalts) carry only the period
bracket "TERTIARY TO RECENT VOLCANICS" (epoch blank by design).

Two source errors were found while joining the legend to the polygons and are corrected **with the correction recorded
in `age_src`**:

* **Code `MS` is used twice** (row 4 "Sand, Clay and Mangrove Swamps", row 78 "Pelitic Schist / Muscovite Schist")
  and the two swatch colours are swapped relative to the map face – the coastal Niger-Delta polygons are drawn in the
  row-78 colour, the inland schist-belt polygons (labelled `Sm` on the map) in the row-4 colour.  13 polygons are
  assigned by position (south of 7° N = mangrove swamp, else schist).
* **`OGp` "Coarse porphyritic biotite and biotite hornblende granite" (246 polygons, 84 000 km²) is missing from the
  printed legend**; it is the largest Older-Granite unit.  It gets the Pan-African Older Granite Series age from its
  code family (`OG…`, rows 62–70), flagged as a fall-back.  Four more omitted units (`Gdss`, `Gmsh`, `s`, `BCT`;
  9 polygons, 5 300 km²) stay without an age (`age_src = not in printed legend; no age inferred`).

### 1.1 The 92 legend rows as dated

| row | code | description | formation / group (printed) | age / series (printed) | period bracket | era | period (ICS) | epoch / stage | Ma | how it was read |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `Al` | Alluvium | Sediments | Recent | NEOGENE | Cenozoic | Quaternary | Holocene | 0.0–0.0117 | legend row label |
| 2 | `MWS` | Sands,Gravels and Clay | Meader belt, back swamps, fresh water swamps | Holocene | NEOGENE | Cenozoic | Quaternary | Holocene | 0.0–0.0117 | sub-age bracket |
| 3 | `AB` | Sands and Pebbles |  | Holocene | NEOGENE | Cenozoic | Quaternary | Holocene | 0.0–0.0117 | sub-age bracket |
| 4 | `MS` | Sand, Clay and Mangrove Swamps | Mangroves swamps | Holocene | NEOGENE | Cenozoic | Quaternary | Holocene | 0.0–0.0117 | sub-age bracket |
| 5 | `SDsm` | Sand,Clay and Swamp | Sombreiro Deltaic Formation | Holocene | NEOGENE | Cenozoic | Quaternary | Holocene | 0.0–0.0117 | sub-age bracket |
| 6 | `Cst` | Sands, Clays, siltstones and limestones | Chad Formation | Pleistocene / Pliocene | NEOGENE | Cenozoic | Neogene-Quaternary | Pliocene-Pleistocene | 0.0117–5.333 | sub-age bracket |
| 7 | `Bnst` | Sand and Clay | Benin Formation (chart key) | Pleistocene / Pliocene | NEOGENE | Cenozoic | Neogene-Quaternary | Pliocene-Pleistocene | 0.0117–5.333 | sub-age bracket |
| 8 | `b` | Younger Basalt |  |  | TERTIARY TO RECENT VOLCANICS | Cenozoic | Paleogene-Quaternary (Tertiary-Recent) |  | 0.0–66.0 |  |
| 9 | `bb` | Basalt | Newer Basalt |  | TERTIARY TO RECENT VOLCANICS | Cenozoic | Paleogene-Quaternary (Tertiary-Recent) |  | 0.0–66.0 |  |
| 10 | `OAlgs` | Lignite,Claystone and shale | Ogwashi - Asaba Formation | Oligocene / Miocene | PALAEOGENE | Cenozoic | Paleogene-Neogene | Oligocene-Miocene | 5.333–33.9 | sub-age bracket (stacked label, one line per row) |
| 11 | `Issh` | Clay clayey sands and shale | Ilaro Formation | Upper Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Late / Priabonian) | 33.9–37.71 | sub-age bracket (stacked label, one line per row) |
| 12 | `Gwss` | Sandstone and Clay | Gwandu Formation (chart key) | Middle Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Middle / Lutetian-Bartonian) | 37.71–47.8 | sub-age bracket |
| 13 | `Glcl` | Sandstones and Clays | Gwandu Formation | Middle Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Middle / Lutetian-Bartonian) | 37.71–47.8 | sub-age bracket |
| 14 | `Wss` | Sandstone and Clay |  | Middle Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Middle / Lutetian-Bartonian) | 37.71–47.8 | sub-age bracket |
| 15 | `Esh` | Shale and limestone | Ewekoro Formation (chart key) | Middle Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Middle / Lutetian-Bartonian) | 37.71–47.8 | sub-age bracket |
| 16 | `Imsh` | Clay and Shale with Limestone Intercalations | Imo group | Lower Eocene | PALAEOGENE | Cenozoic | Paleogene | Eocene (Early / Ypresian) | 47.8–56.0 | legend row label |
| 17 | `Kss` | Sandstone,shale and Clay | Kerri - Kerri Formation | Palaeocene | PALAEOGENE | Cenozoic | Paleogene | Paleocene | 56.0–66.0 | sub-age bracket |
| 18 | `Dsh` | Shale | Dange Formation | Palaeocene | PALAEOGENE | Cenozoic | Paleogene | Paleocene | 56.0–66.0 | sub-age bracket |
| 19 | `Kls` | Limestone | Kalambaina Formation | Palaeocene | PALAEOGENE | Cenozoic | Paleogene | Paleocene | 56.0–66.0 | sub-age bracket |
| 20 | `Gss` | Sandstone,Siltstone,Shale and ironstone | Gombe Formation | Senonian |  | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | fall-back: correlation chart (Gombe Formation drawn in the Senonian band) |
| 21 | `Ajst` | False - bedded sandstone | Ajali Formation | Coniancian / Maestrichtian |  | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | fall-back: legend position between Gombe Fm and Nsukka Fm; Ajali Formation is Maastrichtian |
| 22 | `Ncsh` | Coal, shale and sandstone | Nsukka Formation (chart key) | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 23 | `Ncsh` | Sandstone, limestone, Coal | Nsukka Formation (chart key) | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 24 | `Asl` | Sandstone and Limestone | Abeokuta Formation | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 25 | `Mcst` | Coal,Sandstone and Shale | Mamu Formation (chart key) | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 26 | `Bssf` | Sandstone and Ironstone | Bassange Formation | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 27 | `Nsh` | Shale and mudstone | Nkporo Formation | Coniancian / Maestrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian-Maastrichtian | 66.0–89.8 | sub-age bracket |
| 28 | `ANsh` | Shale and Limestone | Awgu - Formation | Coniancian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Coniacian | 86.3–89.8 | legend row label |
| 29 | `Tst` | Sandstone, siltstone and shale | Taloka Formation | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | sub-age bracket |
| 30 | `GIls` | Limestone | Dukamaje Formation | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | sub-age bracket |
| 31 | `Wss` | Sandstone, clays and shale |  | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | sub-age bracket |
| 32 | `Wcs` | Clays and loose sandstone |  | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | sub-age bracket |
| 33 | `Wsh` | Shale (Phosphate nodules) |  | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | sub-age bracket |
| 34 | `Ts` | Siltstone and Sandstone |  | Senonian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Senonian (Coniacian-Maastrichtian) | 66.0–89.8 | fall-back: correlation chart key: ts, Tst, Tss, Tcs = Rima Group (Senonian band) |
| 35 | `Psh` | Shale,limestone and sandstone | Pindiga Formation | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 36 | `Lass` | Sandstone,shale and sandyshale | Lafia - Wukari Formation | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 37 | `NPss` | Feldspathic sandstone and siltstone | Nupe Formation | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 38 | `GIpg` | Pebbles and grit | Illo Formation (chart key) | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 39 | `GIss` | Clay grit and pebbles | Gundumi Formation (chart key) | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 40 | `GIgss` | Gravel and sand | Gundumi Formation (chart key) | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 41 | `Fsh` | Blackshale, siltstone and sandstone | Fika Formation | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 42 | `Ess` | Sandstone | Ezeaku group (chart key) | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 43 | `Esh` | Blackshale, siltstone and sandstone | Ezeaku group (chart key) | Turonian / Pre maastrichtian | CRETACEOUS | Mesozoic | Cretaceous | Late Cretaceous: Turonian-Campanian | 72.1–93.9 | sub-age bracket |
| 44 | `Mlst` | Limestone and Siltstone |  | Albian / Cenomanian | CRETACEOUS | Mesozoic | Cretaceous | Albian-Cenomanian | 93.9–113.0 | sub-age bracket |
| 45 | `Awst` | Sandstone | Awi - Odukpani  Formation (chart key) | Albian / Cenomanian | CRETACEOUS | Mesozoic | Cretaceous | Albian-Cenomanian | 93.9–113.0 | sub-age bracket |
| 46 | `Yls` | Shale, sandyclay, calcerous sandstones | Yola - Bima - Yolde Formation | Albian / Cenomanian | CRETACEOUS | Mesozoic | Cretaceous | Albian-Cenomanian | 93.9–113.0 | sub-age bracket |
| 47 | `Bss` | Feldspathic sandstone calcerous sandstone and shelly limestone | Bima Formation | Albian / Cenomanian | CRETACEOUS | Mesozoic | Cretaceous | Albian-Cenomanian | 93.9–113.0 | sub-age bracket |
| 48 | `Arlsh` | Shale and limestone with sandstone intercalations | Asu River group | Albian | CRETACEOUS | Mesozoic | Cretaceous | Early Cretaceous: Albian | 100.5–113.0 | extra bracket |
| 49 | `MyP` | Quartz porphyry |  |  | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | fall-back: code family My- (Younger Granite series); row sits 2 pt above the JURASSIC bracket |
| 50 | `MyG` | Granite and granite porphery |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 51 | `Myl` | Ignimbrite |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 52 | `Mys` | Syenite, quartz-syenite and gabbro |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 53 | `MGp` | Granites and granite porphyry |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 54 | `MyP` | Porphyry / quartz porphyry |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 55 | `r` | Rhyolite |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 56 | `Jyr` | Rhyolite |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 57 | `JyG` | Biotite granite |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 58 | `JyA` | Trachy- andesine |  | Per Alkaline young Granite Series | JURASSIC | Mesozoic | Jurassic |  | 145.0–201.4 | sub-age bracket |
| 59 | `P` | Pegmatite |  |  |  |  |  |  | – | fall-back: no age printed; basement pegmatites of Nigeria are late Pan-African (c. 560-530 Ma) |
| 60 | `D` | Dolerite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 61 | `ODh` | Bauchite quartz- diorite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 62 | `OGd` | Biotite and biotite hornblende granodiorite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 63 | `OGS` | Syenite,mainly of pyroxene diorite composition |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 64 | `OSq` | Coarse biotite and biotite muscovite granite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 65 | `OGh` | Coarse hornblende granite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 66 | `OGf` | Fine-grained biotite granite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 67 | `OGm` | Medium-to coarse-grained biotite granite |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 68 | `OGu` | Undifferentiated granite,migmatite and granite Gneiss |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 69 | `OGCh` | Charnockitic rocks |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 70 | `OGr` | Gabbro and quartz gabbro |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 71 | `MV` | Meta Volcanic Meta Sedimentary including pebbly schist |  | Pan - African Older Granite Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 72 | `Sa` | Amphibole Schist,Amphibolite |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | nearest series bracket (1.1 pt away) |
| 73 | `BIF` | Banded Iron Formation |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 74 | `Sp` | Slate phylite and meta siltstone, locally hornfelstic / carbonaceous |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 75 | `m` | Marble |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 76 | `Sf` | Fine-grained flaggy quartzite and Quartz Schist. |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 77 | `Qs` | Quartzite, massive and schistose, also occuring as ridges |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 78 | `MS` | Pelitic Schist / Muscovite Schist |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 79 | `Su` | Undifferentiated schists,including phyllities. |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 80 | `Mc` | Meta-conglomerate |  | Meta - Sedimentary / Meta - Volcanic Series | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic (Pan-African deformed) |  |  | 538.8–1000.0 | sub-age bracket |
| 81 | `bS` | Biotite Garnet Gneiss Schist |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | nearest series bracket (1.4 pt away) |
| 82 | `bG-h` | Biotite hornblende gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 83 | `OPg` | Porphroblastic Gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 84 | `GG` | Granite Gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 85 | `Ge` | Granulite and gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 86 | `bG` | Banded gneiss / biotite gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 87 | `MaG` | Migmatitic augen gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 88 | `MG` | Migmatitic gneiss |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 89 | `M` | Migmatite |  | Migmatite - Gneiss Complex | PRE - CAMBRIAN TO CAMBRIAN | Archaean-Palaeoproterozoic, reworked in the Neoproterozoic |  |  | 538.8–4000.0 | sub-age bracket |
| 90 | `qs` | Silicified, sheared rocks, large quartz veins |  | Cataclastic Rocks | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 91 | `My` | Mylonites |  | Cataclastic Rocks | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |
| 92 | `aMy` | Mylonites interlayered with amphibolites |  | Cataclastic Rocks | PRE - CAMBRIAN TO CAMBRIAN | Neoproterozoic-Palaeozoic | Ediacaran-Cambrian |  | 485.4–1000.0 | sub-age bracket |

### 1.2 Fields of `geology_units.shp` (also `by_layer.zip`)

| field | content |
|---|---|
| `ocg_id`, `layer_no`, `unit` | PDF optional-content group, its order, and the PDF layer name (= lithology as typed by the compiler) |
| `fill` | fill colour as drawn |
| `code`, `code_src` | legend code; `legend` (colour + description match), `legend (MS colour swap corrected)`, `label` (code printed inside the polygon), `layer` (majority code of the layer) |
| `leg_code`, `leg_desc`, `leg_row` | the matched legend row (blank for the 6 units missing from the print) |
| `lbl_code`, `n_lbl` | code(s) printed inside the polygon and how many |
| `area_km2`, `perim_km`, `cen_lon`, `cen_lat`, `n_rings` | size and position (centroid = representative point inside the polygon) |
| `src_seq`, `dup_of` | drawing order; 16 polygons are exact duplicates of an earlier one |
| `formation`, `strat_grp` | formation / group name printed in the legend or the correlation chart (`(chart key)` marks the latter) |
| `age_print`, `series`, `period_prt` | the words printed next to the swatch: sub-age label, series / complex label, period bracket |
| `eon`, `era`, `period`, `epoch`, `age_ma_min`, `age_ma_max` | ICS equivalents of the printed words (see above) |
| `age_src` | how the age was obtained, incl. every fall-back and correction |
| `rock_cls` | sedimentary / volcanic / plutonic / metamorphic / fault rock / minor intrusive, from the description |
| `basins` | basins of the correlation chart in which the code is drawn |

Points of `towns`, `state_capitals` and `volcanic_plugs` carry `lon`, `lat` and the unit they fall in (`unit_code`,
`unit`, `unit_era`, `unit_per`); `labels` carries `lon`/`lat`, the page position and the text box width; every line
layer carries `len_km` (`length_km` for the graticule); `major_rivers_poly` is named (Gulf of Guinea, Lake Chad,
River Niger / River Benue, one unnamed reservoir) with `kind`, `labels_in`, area, perimeter and bounds.

## 2. Minerals (2023 map) – attributes of the mineral layers

| layer | attributes added in this pass (all earlier fields kept) |
|---|---|
| `mineral_localities` | `lon`, `lat` (final point), `n_minerals`, `mineral_1`, `group_1`, `groups` (commodity groups: energy, precious metals, ferrous metals, base metals, rare metals, gemstones, industrial minerals, construction materials, unknown), `n_unknown` (codes not in the legend), and the **host rock unit from the 2011 geological map**: `geo_code`, `geo_unit`, `geo_form`, `geo_era`, `geo_period`, `geo_epoch`, `geo_src` (both maps are 1:2 M and their georeferences differ by ~8 km, so treat this as ±10 km) |
| `mineral_symbols_raster` | `lon`, `lat`, symbol size on the page (`w_pt`, `h_pt`, `w_mm`, `h_mm`) and on the ground (`w_km`, `h_km`), `n_cands`, `group_1`, `near_grps` |
| `map_zones` | `n_local`, `n_symbols`, `area_km2`, `perim_km`, centroid and bounds, `top_grps` (three most frequent commodity groups) |
| `map_frame` | `area_km2`, `perim_km`, extent in degrees and points, nominal `scale` (1:1,978,000 from the /VP affine) |
| `division_lines` | `length_km`, `zones` (zones the line separates), `n_vert` |
| `graticule` | `label` (e.g. `12°E`), `length_km`, `offset_deg` (GeoPDF value minus printed label – the 0.172° meridian discrepancy of §1 of the README) |
| `roads`, `rivers`, `railway`, `international_boundary` | `length_km`, `n_vert`, midpoint / start / end coordinates, `zone`, `closed` (72 river features are closed rings = lake shores) |
| `towns`, `state_capitals` | `lon`, `lat`, `zone`, nearest numbered locality (`near_loc`, `near_km`); capitals also `ref_lon`/`ref_lat` and their offset from the reference coordinates (`ref_dx_km`, `ref_dy_km`) |
| `state_name_labels` | `lon`, `lat`, `zone`, font, size, angle, `capital` |
| `river_labels` | `lon`, `lat`, `zone`, `size_pt`, `kind` (river / lake / water name), `in_frame` |
| `pegmatite_marks` | `lon`, `lat`, `zone`, nearest locality and its minerals, host unit from the geological map |
| `map_labels` | `kind` (town name, state capital name, state name, river / lake name, …), `lon`, `lat`, `zone`, `n_chars`, text box size |

`explanations_table.csv` and `mineral_localities.csv` carry the same commodity-group column; `mineral_legend.csv`
gains `commodity_group` and `localities_in_table` per legend mineral, `mineral_code_dictionary.csv` gains
`commodity_group` and `uses_on_map` per code.

### 2.1 Summary tables (`summaries.py`)

| file | content |
|---|---|
| `shapefiles/summary_area_by_unit.csv` | every legend unit (101 incl. the omitted ones): polygons, area (16 duplicate polygons excluded), % of the mapped 912 896 km², perimeter, largest polygon, with formation / rock class / era / period / epoch / Ma / age source |
| `shapefiles/summary_area_by_age.csv` | area by era, period, epoch, printed series, printed period bracket and rock class (e.g. Cenozoic 33.7 %, Mesozoic 19.9 %, Migmatite-Gneiss basement 24.6 %, Pan-African granites + cataclastics 15.0 %, schist belts 6.2 %, undated 0.6 %; sedimentary 51.6 %, metamorphic 31.9 %, plutonic 14.4 %, volcanic 1.5 %) |
| `shapefiles_minerals/summary_localities_by_host_geology.csv` | the 999 localities by host unit of the 2011 map (67 units): count, %, top minerals, commodity groups, zones – e.g. 128 on Migmatite, 80 on the porphyritic Older Granite, 66 on Granite Gneiss, 55 on Alluvium |
| `shapefiles_minerals/summary_localities_by_group.csv` | commodity group × host era and × zone A–G |

The same statistics are shown live under **Compare → Attribute statistics** in the viewer.

## 3. Size fields

Every polygon layer has `area_km2` and `perim_km`; every line layer has `len_km` / `length_km`; point layers have
`lon`/`lat` (and, where the symbol has a size, `w_*`/`h_*`).  Totals (from section 4): geology units 924 555 km²
(Nigeria = 923 768 km²; the 16 duplicate polygons add 11 700 km², the rest is the sliver overlap of the source),
geological boundaries 81 832 km, faults 17 700 km, rivers 40 199 km (2011) / 43 219 km (2023), roads 19 625 km /
18 408 km, railway 3 084 km / 3 091 km, state boundaries 35 581 km, international boundary 4 092 km (the land border
of Nigeria is ≈4 500 km; the map's line stops at the coast and rounds the Lake Chad corner).

## 4. Fill rate of every field (measured on the delivered files)

A field is "filled" when the value is not empty / null.  Fields that are legitimately sparse are explained in the
layer notes above (e.g. `formation` exists only for the sedimentary units; `tbl_flags` only for flagged table rows;
`name` of `volcanic_plugs` – the map prints no plug names).

## shapefiles/ (17 layers)


### faults  (Polyline, 648 features)

Size fields: len_km: 648/648 filled, total 17,700

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 648 | 100 |
| `layer` | C64 | 648 | 100 |
| `class` | C48 | 648 | 100 |
| `stroke` | C7 | 648 | 100 |
| `width_pt` | N6.2 | 648 | 100 |
| `n_frag` | N6 | 648 | 100 |
| `len_km` | N12.3 | 648 | 100 |
| `src_seq` | N10 | 648 | 100 |

### fold_axes  (Polyline, 90 features)

Size fields: len_km: 90/90 filled, total 1,962

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 90 | 100 |
| `layer` | C64 | 90 | 100 |
| `class` | C48 | 90 | 100 |
| `stroke` | C7 | 90 | 100 |
| `width_pt` | N6.2 | 90 | 100 |
| `n_frag` | N6 | 90 | 100 |
| `len_km` | N12.3 | 90 | 100 |
| `src_seq` | N10 | 90 | 100 |

### geological_boundaries  (Polyline, 2819 features)

Size fields: len_km: 2819/2819 filled, total 81,832

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 2819 | 100 |
| `layer` | C64 | 2819 | 100 |
| `class` | C48 | 2819 | 100 |
| `stroke` | C7 | 2819 | 100 |
| `width_pt` | N6.2 | 2819 | 100 |
| `n_frag` | N6 | 2819 | 100 |
| `len_km` | N12.3 | 2819 | 100 |
| `src_seq` | N10 | 2819 | 100 |

### geology_units  (Polygon, 1542 features)

Size fields: area_km2: 1542/1542 filled, total 924,555; perim_km: 1542/1542 filled, total 191,553

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 1542 | 100 |
| `layer_no` | N4 | 1542 | 100 |
| `unit` | C120 | 1542 | 100 |
| `fill` | C7 | 1542 | 100 |
| `code` | C12 | 1541 | 100 |
| `code_src` | C36 | 1541 | 100 |
| `leg_code` | C12 | 1280 | 83 |
| `leg_desc` | C120 | 1280 | 83 |
| `lbl_code` | C12 | 1447 | 94 |
| `n_lbl` | N5 | 1542 | 100 |
| `area_km2` | N14.3 | 1542 | 100 |
| `perim_km` | N12.2 | 1542 | 100 |
| `cen_lon` | N11.6 | 1542 | 100 |
| `cen_lat` | N11.6 | 1542 | 100 |
| `n_rings` | N5 | 1542 | 100 |
| `src_seq` | N10 | 1542 | 100 |
| `dup_of` | N10 | 1542 | 100 |
| `leg_row` | N4 | 1289 | 84 |
| `formation` | C64 | 340 | 22 |
| `strat_grp` | C48 | 70 | 5 |
| `age_print` | C48 | 347 | 23 |
| `series` | C64 | 1105 | 72 |
| `period_prt` | C40 | 1520 | 99 |
| `eon` | C40 | 1533 | 99 |
| `era` | C64 | 1533 | 99 |
| `period` | C48 | 1035 | 67 |
| `epoch` | C64 | 347 | 23 |
| `age_ma_min` | N9.4 | 1533 | 99 |
| `age_ma_max` | N9.4 | 1533 | 99 |
| `age_src` | C120 | 1465 | 95 |
| `rock_cls` | C16 | 1538 | 100 |
| `basins` | C120 | 288 | 19 |

### graticule  (Polyline, 22 features)

Size fields: length_km: 22/22 filled, total 24,037

| field | type | filled | % |
|---|---|---:|---:|
| `axis` | C3 | 22 | 100 |
| `value` | N8.3 | 22 | 100 |
| `label` | C12 | 22 | 100 |
| `page_pt` | N9.2 | 22 | 100 |
| `length_km` | N10.2 | 22 | 100 |
| `n_lines` | N3 | 22 | 100 |

### labels  (Point, 1973 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `text` | C100 | 1973 | 100 |
| `kind` | C16 | 1973 | 100 |
| `font` | C32 | 1973 | 100 |
| `size_pt` | N8.2 | 1973 | 100 |
| `angle` | N8.2 | 1973 | 100 |
| `layer` | C32 | 1973 | 100 |
| `src_seq` | N10 | 1973 | 100 |
| `lon` | N11.6 | 1973 | 100 |
| `lat` | N11.6 | 1973 | 100 |
| `n_chars` | N4 | 1973 | 100 |
| `width_pt` | N7.2 | 1973 | 100 |
| `page_x` | N9.2 | 1973 | 100 |
| `page_y` | N9.2 | 1973 | 100 |

### major_rivers_outline  (Polyline, 72 features)

Size fields: len_km: 72/72 filled, total 11,707

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 72 | 100 |
| `layer` | C64 | 72 | 100 |
| `class` | C48 | 72 | 100 |
| `stroke` | C7 | 72 | 100 |
| `width_pt` | N6.2 | 72 | 100 |
| `n_frag` | N6 | 72 | 100 |
| `len_km` | N12.3 | 72 | 100 |
| `src_seq` | N10 | 72 | 100 |

### major_rivers_poly  (Polygon, 4 features)

Size fields: area_km2: 4/4 filled, total 152,849; perim_km: 4/4 filled, total 11,693

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 4 | 100 |
| `layer` | C32 | 4 | 100 |
| `name` | C80 | 3 | 75 |
| `kind` | C24 | 4 | 100 |
| `name_src` | C48 | 4 | 100 |
| `labels_in` | C254 | 2 | 50 |
| `fill` | C7 | 4 | 100 |
| `area_km2` | N14.3 | 4 | 100 |
| `perim_km` | N12.2 | 4 | 100 |
| `cen_lon` | N11.6 | 4 | 100 |
| `cen_lat` | N11.6 | 4 | 100 |
| `min_lon` | N10.5 | 4 | 100 |
| `max_lon` | N10.5 | 4 | 100 |
| `min_lat` | N10.5 | 4 | 100 |
| `max_lat` | N10.5 | 4 | 100 |
| `n_rings` | N5 | 4 | 100 |
| `src_seq` | N10 | 4 | 100 |

### railway  (Polyline, 6 features)

Size fields: len_km: 6/6 filled, total 3,084

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 6 | 100 |
| `layer` | C64 | 6 | 100 |
| `class` | C48 | 6 | 100 |
| `stroke` | C7 | 6 | 100 |
| `width_pt` | N6.2 | 6 | 100 |
| `n_frag` | N6 | 6 | 100 |
| `len_km` | N12.3 | 6 | 100 |
| `src_seq` | N10 | 6 | 100 |

### ridges  (Polyline, 2 features)

Size fields: len_km: 2/2 filled, total 624

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 2 | 100 |
| `layer` | C64 | 2 | 100 |
| `class` | C48 | 2 | 100 |
| `stroke` | C7 | 2 | 100 |
| `width_pt` | N6.2 | 2 | 100 |
| `n_frag` | N6 | 2 | 100 |
| `len_km` | N12.3 | 2 | 100 |
| `src_seq` | N10 | 2 | 100 |

### rivers  (Polyline, 1054 features)

Size fields: len_km: 1054/1054 filled, total 40,199

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 1054 | 100 |
| `layer` | C64 | 1054 | 100 |
| `class` | C48 | 1054 | 100 |
| `stroke` | C7 | 1054 | 100 |
| `width_pt` | N6.2 | 1054 | 100 |
| `n_frag` | N6 | 1054 | 100 |
| `len_km` | N12.3 | 1054 | 100 |
| `src_seq` | N10 | 1054 | 100 |

### roads  (Polyline, 122 features)

Size fields: len_km: 122/122 filled, total 19,625

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 122 | 100 |
| `layer` | C64 | 122 | 100 |
| `class` | C48 | 122 | 100 |
| `stroke` | C7 | 122 | 100 |
| `width_pt` | N6.2 | 122 | 100 |
| `n_frag` | N6 | 122 | 100 |
| `len_km` | N12.3 | 122 | 100 |
| `src_seq` | N10 | 122 | 100 |

### state_boundaries  (Polyline, 83 features)

Size fields: len_km: 83/83 filled, total 35,581

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 83 | 100 |
| `layer` | C64 | 83 | 100 |
| `class` | C48 | 83 | 100 |
| `stroke` | C7 | 83 | 100 |
| `width_pt` | N6.2 | 83 | 100 |
| `n_frag` | N6 | 83 | 100 |
| `len_km` | N12.3 | 83 | 100 |
| `src_seq` | N10 | 83 | 100 |

### state_capitals  (Point, 32 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 32 | 100 |
| `layer` | C32 | 32 | 100 |
| `name` | C64 | 32 | 100 |
| `name_kind` | C16 | 32 | 100 |
| `name_dist` | N8.2 | 32 | 100 |
| `src_seq` | N10 | 32 | 100 |
| `lon` | N11.6 | 32 | 100 |
| `lat` | N11.6 | 32 | 100 |
| `unit_code` | C12 | 32 | 100 |
| `unit` | C120 | 32 | 100 |
| `unit_era` | C64 | 32 | 100 |
| `unit_per` | C48 | 26 | 81 |

### towns  (Point, 486 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 486 | 100 |
| `layer` | C32 | 486 | 100 |
| `name` | C64 | 404 | 83 |
| `name_kind` | C16 | 404 | 83 |
| `name_dist` | N8.2 | 486 | 100 |
| `src_seq` | N10 | 486 | 100 |
| `lon` | N11.6 | 486 | 100 |
| `lat` | N11.6 | 486 | 100 |
| `unit_code` | C12 | 467 | 96 |
| `unit` | C120 | 467 | 96 |
| `unit_era` | C64 | 462 | 95 |
| `unit_per` | C48 | 314 | 65 |

### volcanic_plugs  (Point, 68 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 68 | 100 |
| `layer` | C32 | 68 | 100 |
| `name` | C64 | 0 | 0 |
| `name_kind` | C16 | 68 | 100 |
| `name_dist` | N8.2 | 68 | 100 |
| `src_seq` | N10 | 68 | 100 |
| `lon` | N11.6 | 68 | 100 |
| `lat` | N11.6 | 68 | 100 |
| `unit_code` | C12 | 68 | 100 |
| `unit` | C120 | 68 | 100 |
| `unit_era` | C64 | 68 | 100 |
| `unit_per` | C48 | 68 | 100 |

### younger_granite_outlines  (Polyline, 59 features)

Size fields: len_km: 59/59 filled, total 2,465

| field | type | filled | % |
|---|---|---:|---:|
| `ocg_id` | N6 | 59 | 100 |
| `layer` | C64 | 59 | 100 |
| `class` | C48 | 59 | 100 |
| `stroke` | C7 | 59 | 100 |
| `width_pt` | N6.2 | 59 | 100 |
| `n_frag` | N6 | 59 | 100 |
| `len_km` | N12.3 | 59 | 100 |
| `src_seq` | N10 | 59 | 100 |

## shapefiles_minerals/ (16 layers)


### division_lines  (Polyline, 5 features)

Size fields: length_km: 5/5 filled, total 4,335

| field | type | filled | % |
|---|---|---:|---:|
| `layer` | C20 | 5 | 100 |
| `len_pt` | N8.1 | 5 | 100 |
| `length_km` | N10.2 | 5 | 100 |
| `zones` | C8 | 5 | 100 |
| `n_vert` | N5 | 5 | 100 |

### graticule  (Polyline, 11 features)

Size fields: length_km: 11/11 filled, total 13,662

| field | type | filled | % |
|---|---|---:|---:|
| `axis` | C5 | 11 | 100 |
| `vp_value` | N8.3 | 11 | 100 |
| `printed` | N3 | 11 | 100 |
| `label` | C12 | 11 | 100 |
| `length_km` | N10.2 | 11 | 100 |
| `offset_deg` | N8.4 | 11 | 100 |

### international_boundary  (Polyline, 1 features)

Size fields: length_km: 1/1 filled, total 4,092

| field | type | filled | % |
|---|---|---:|---:|
| `class` | C24 | 1 | 100 |
| `name` | C24 | 1 | 100 |
| `n_frag` | N6 | 1 | 100 |
| `length_km` | N10.2 | 1 | 100 |
| `n_vert` | N6 | 1 | 100 |
| `mid_lon` | N11.6 | 1 | 100 |
| `mid_lat` | N11.6 | 1 | 100 |
| `zone` | C1 | 1 | 100 |
| `start_lon` | N11.6 | 1 | 100 |
| `start_lat` | N11.6 | 1 | 100 |
| `end_lon` | N11.6 | 1 | 100 |
| `end_lat` | N11.6 | 1 | 100 |
| `closed` | C3 | 1 | 100 |

### map_frame  (Polygon, 1 features)

Size fields: area_km2: 1/1 filled, total 1,557,406; perim_km: 1/1 filled, total 5,006

| field | type | filled | % |
|---|---|---:|---:|
| `name` | C24 | 1 | 100 |
| `area_km2` | N12.1 | 1 | 100 |
| `perim_km` | N10.1 | 1 | 100 |
| `width_deg` | N9.5 | 1 | 100 |
| `height_deg` | N9.5 | 1 | 100 |
| `min_lon` | N10.5 | 1 | 100 |
| `max_lon` | N10.5 | 1 | 100 |
| `min_lat` | N10.5 | 1 | 100 |
| `max_lat` | N10.5 | 1 | 100 |
| `width_pt` | N9.2 | 1 | 100 |
| `height_pt` | N9.2 | 1 | 100 |
| `scale` | C16 | 1 | 100 |

### map_labels  (Point, 657 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `text` | C100 | 657 | 100 |
| `layer` | C32 | 657 | 100 |
| `font` | C32 | 657 | 100 |
| `size_pt` | N6.2 | 657 | 100 |
| `angle` | N6.1 | 657 | 100 |
| `kind` | C28 | 657 | 100 |
| `lon` | N12.6 | 657 | 100 |
| `lat` | N12.6 | 657 | 100 |
| `zone` | C1 | 657 | 100 |
| `n_chars` | N4 | 657 | 100 |
| `width_pt` | N7.2 | 657 | 100 |
| `height_pt` | N6.2 | 657 | 100 |

### map_zones  (Polygon, 7 features)

Size fields: area_km2: 7/7 filled, total 1,555,673; perim_km: 7/7 filled, total 13,672

| field | type | filled | % |
|---|---|---:|---:|
| `zone` | C1 | 7 | 100 |
| `tbl_rows` | N5 | 7 | 100 |
| `labels` | N5 | 7 | 100 |
| `n_local` | N5 | 7 | 100 |
| `n_symbols` | N5 | 7 | 100 |
| `area_km2` | N12.1 | 7 | 100 |
| `perim_km` | N10.1 | 7 | 100 |
| `cen_lon` | N10.5 | 7 | 100 |
| `cen_lat` | N10.5 | 7 | 100 |
| `min_lon` | N10.5 | 7 | 100 |
| `max_lon` | N10.5 | 7 | 100 |
| `min_lat` | N10.5 | 7 | 100 |
| `max_lat` | N10.5 | 7 | 100 |
| `top_grps` | C120 | 7 | 100 |

### mineral_localities  (Point, 999 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `zone` | C1 | 999 | 100 |
| `number` | N5 | 999 | 100 |
| `zone_num` | C6 | 999 | 100 |
| `locality` | C80 | 994 | 99 |
| `codes_raw` | C40 | 985 | 99 |
| `minerals` | C254 | 985 | 99 |
| `min_conf` | C40 | 985 | 99 |
| `match` | C80 | 999 | 100 |
| `tbl_flags` | C200 | 135 | 14 |
| `pos_src` | C36 | 999 | 100 |
| `snap_pt` | N6.1 | 672 | 67 |
| `sym_colour` | C24 | 849 | 85 |
| `sym_cands` | C254 | 849 | 85 |
| `label_lon` | N12.6 | 999 | 100 |
| `label_lat` | N12.6 | 999 | 100 |
| `lon` | N12.6 | 999 | 100 |
| `lat` | N12.6 | 999 | 100 |
| `n_minerals` | N3 | 999 | 100 |
| `mineral_1` | C60 | 985 | 99 |
| `group_1` | C24 | 985 | 99 |
| `groups` | C120 | 985 | 99 |
| `n_unknown` | N3 | 999 | 100 |
| `geo_code` | C8 | 995 | 100 |
| `geo_unit` | C64 | 995 | 100 |
| `geo_form` | C48 | 475 | 48 |
| `geo_era` | C48 | 995 | 100 |
| `geo_period` | C40 | 662 | 66 |
| `geo_epoch` | C48 | 478 | 48 |
| `geo_src` | C60 | 999 | 100 |

### mineral_symbols_raster  (Point, 1593 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `colour` | C16 | 1593 | 100 |
| `w_px` | N4 | 1593 | 100 |
| `h_px` | N4 | 1593 | 100 |
| `body_w` | N4 | 1593 | 100 |
| `body_h` | N4 | 1593 | 100 |
| `fill` | C8 | 1593 | 100 |
| `candidates` | C254 | 1350 | 85 |
| `link` | C40 | 1077 | 68 |
| `near_num` | C8 | 1077 | 68 |
| `near_dist` | N6.1 | 1077 | 68 |
| `near_loc` | C80 | 1073 | 67 |
| `near_mins` | C200 | 1064 | 67 |
| `lon` | N12.6 | 1593 | 100 |
| `lat` | N12.6 | 1593 | 100 |
| `w_pt` | N6.2 | 1593 | 100 |
| `h_pt` | N6.2 | 1593 | 100 |
| `w_mm` | N6.2 | 1593 | 100 |
| `h_mm` | N6.2 | 1593 | 100 |
| `w_km` | N7.2 | 1593 | 100 |
| `h_km` | N7.2 | 1593 | 100 |
| `n_cands` | N3 | 1593 | 100 |
| `group_1` | C24 | 1350 | 85 |
| `near_grps` | C120 | 1064 | 67 |

### pegmatite_marks  (Point, 23 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `symbol` | C2 | 23 | 100 |
| `meaning` | C40 | 23 | 100 |
| `lon` | N12.6 | 23 | 100 |
| `lat` | N12.6 | 23 | 100 |
| `zone` | C1 | 23 | 100 |
| `size_pt` | N6.2 | 23 | 100 |
| `near_loc` | C8 | 23 | 100 |
| `near_km` | N7.1 | 23 | 100 |
| `near_mins` | C120 | 23 | 100 |
| `geo_code` | C8 | 23 | 100 |
| `geo_unit` | C64 | 23 | 100 |
| `geo_era` | C48 | 23 | 100 |

### railway  (Polyline, 6 features)

Size fields: length_km: 6/6 filled, total 3,091

| field | type | filled | % |
|---|---|---:|---:|
| `class` | C10 | 6 | 100 |
| `n_frag` | N6 | 6 | 100 |
| `length_km` | N10.2 | 6 | 100 |
| `n_vert` | N6 | 6 | 100 |
| `mid_lon` | N11.6 | 6 | 100 |
| `mid_lat` | N11.6 | 6 | 100 |
| `zone` | C1 | 6 | 100 |
| `start_lon` | N11.6 | 6 | 100 |
| `start_lat` | N11.6 | 6 | 100 |
| `end_lon` | N11.6 | 6 | 100 |
| `end_lat` | N11.6 | 6 | 100 |
| `closed` | C3 | 6 | 100 |

### river_labels  (Point, 93 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `name` | C60 | 93 | 100 |
| `angle` | N6.1 | 93 | 100 |
| `n_glyphs` | N3 | 93 | 100 |
| `lon` | N12.6 | 93 | 100 |
| `lat` | N12.6 | 93 | 100 |
| `zone` | C1 | 93 | 100 |
| `size_pt` | N6.2 | 93 | 100 |
| `kind` | C16 | 93 | 100 |
| `in_frame` | C3 | 93 | 100 |

### rivers  (Polyline, 876 features)

Size fields: length_km: 876/876 filled, total 43,219

| field | type | filled | % |
|---|---|---:|---:|
| `class` | C10 | 876 | 100 |
| `n_frag` | N6 | 876 | 100 |
| `length_km` | N10.2 | 876 | 100 |
| `n_vert` | N6 | 876 | 100 |
| `mid_lon` | N11.6 | 876 | 100 |
| `mid_lat` | N11.6 | 876 | 100 |
| `zone` | C1 | 876 | 100 |
| `start_lon` | N11.6 | 876 | 100 |
| `start_lat` | N11.6 | 876 | 100 |
| `end_lon` | N11.6 | 876 | 100 |
| `end_lat` | N11.6 | 876 | 100 |
| `closed` | C3 | 876 | 100 |

### roads  (Polyline, 115 features)

Size fields: length_km: 115/115 filled, total 18,408

| field | type | filled | % |
|---|---|---:|---:|
| `class` | C10 | 115 | 100 |
| `n_frag` | N6 | 115 | 100 |
| `length_km` | N10.2 | 115 | 100 |
| `n_vert` | N6 | 115 | 100 |
| `mid_lon` | N11.6 | 115 | 100 |
| `mid_lat` | N11.6 | 115 | 100 |
| `zone` | C1 | 115 | 100 |
| `start_lon` | N11.6 | 115 | 100 |
| `start_lat` | N11.6 | 115 | 100 |
| `end_lon` | N11.6 | 115 | 100 |
| `end_lat` | N11.6 | 115 | 100 |
| `closed` | C3 | 115 | 100 |

### state_capitals  (Point, 33 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `name` | C60 | 33 | 100 |
| `src` | C40 | 33 | 100 |
| `lon` | N12.6 | 33 | 100 |
| `lat` | N12.6 | 33 | 100 |
| `zone` | C1 | 33 | 100 |
| `ref_lon` | N10.4 | 33 | 100 |
| `ref_lat` | N10.4 | 33 | 100 |
| `ref_dx_km` | N7.1 | 33 | 100 |
| `ref_dy_km` | N7.1 | 33 | 100 |
| `near_loc` | C8 | 33 | 100 |
| `near_km` | N7.1 | 33 | 100 |

### state_name_labels  (Point, 37 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `name` | C60 | 37 | 100 |
| `lon` | N12.6 | 37 | 100 |
| `lat` | N12.6 | 37 | 100 |
| `zone` | C1 | 37 | 100 |
| `font` | C32 | 37 | 100 |
| `size_pt` | N6.2 | 37 | 100 |
| `angle` | N6.1 | 37 | 100 |
| `capital` | C60 | 37 | 100 |

### towns  (Point, 483 features)

Size fields: -

| field | type | filled | % |
|---|---|---:|---:|
| `name` | C60 | 416 | 86 |
| `kind` | C24 | 483 | 100 |
| `name_dist` | N6.1 | 411 | 85 |
| `lon` | N12.6 | 483 | 100 |
| `lat` | N12.6 | 483 | 100 |
| `zone` | C1 | 483 | 100 |
| `near_loc` | C8 | 483 | 100 |
| `near_km` | N7.1 | 483 | 100 |
| `src_seq` | N10 | 483 | 100 |
