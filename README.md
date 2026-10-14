# Geological Map of Nigeria (NGSA, 1:2,000,000) – PDF analysis & shapefile extraction

Source file: `ilide.info-geological-map-of-nigeria-pr_a0987e407d194cb02682ac479336acb1.pdf`
(44 × 24.5 in, single page, created with **ESRI ArcMap 9.2.0.1324** on 2011‑01‑30).

## 1. Is it a GeoPDF?

**No.** It is a *layered vector PDF*, not a georeferenced one:

| Check | Result |
|---|---|
| ISO 32000‑2 / Adobe geospatial extension (`/VP` viewports + `/Measure` `/GEO` dictionaries, `/GPTS`, `/GCS` WKT) | **absent** |
| TerraGo GeoPDF (`/LGIDict` registration/projection dictionary) | **absent** |
| PDF layers (`/OCProperties`, Optional Content Groups) | **present – 125 layers**, one per geological unit + Rivers, Roads, Railway, Towns, State boundaries, Faults, Geological boundary classes, Labels … |
| Raster images | none – the whole map face is vector paths (45 625 paths, 15 093 text runs); the only image is the NGSA logo |
| Feature attribute tables (ArcGIS "Export PDF Feature Attributes") | **absent** (only added in ArcGIS 9.3) |

ArcMap 9.2 could export layers but **not** georeferencing (the "Export Map Georeference Information" option arrived in 9.3), so GIS software (QGIS/GDAL, ArcGIS, Avenza) opens this file as a plain, un‑placed drawing.

However, the map carries a full 1° graticule (3°–14° E, 4°–13° N) whose lines and labels are vector objects, and longitude and latitude are equally spaced (157.6 pt / degree in both axes = an unprojected, equirectangular data frame at 1:2 000 000). An affine transform fitted to those 22 graticule lines places the drawing in geographic coordinates with a residual of ≈0.001° (~100 m, well below the 1 pt ≈ 700 m drawing resolution). See `shapefiles/georeferencing.json`.

## 2. Can the shapefiles be extracted?

**Mostly yes – the geometry is complete; attributes have to be rebuilt from the layer names, legend and map labels.** `extract_shapefiles.py` does that and the results are in `shapefiles/` (WGS 84, EPSG:4326 `.prj`) plus a single‑file bundle `shapefiles/nigeria_geology.gpkg`.

| Output | Features | What it is / quality |
|---|---|---|
| `geology_units.shp` | 1 542 polygons | Every geological‑unit polygon from the ~100 unit layers, holes rebuilt with the PDF even‑odd rule, all geometries valid. Summed area 924 555 km² (Nigeria = 923 768 km²) – coverage is complete. Attributes: `unit` (PDF layer name = lithology), `fill` (colour), `code` (legend code, matched by colour + description; `code_src` says whether it came from the legend, the map label inside the polygon, or the layer majority), `leg_code`/`leg_desc`, `lbl_code` (code printed on the map inside the polygon), `area_km2`, `dup_of` (16 exact duplicate polygons exist in the source data). |
| `by_layer.zip` | 125 files | The same polygons split one shapefile per original PDF layer (e.g. `006_Alluvium.shp`), plus the raw, un‑merged line fragments of every line layer. |
| `geological_boundaries.shp` | 2 819 lines | `class` = exact / approximate / inferred / transitional. The dashed classes were exported by ArcMap as individual dashes (≈23 000 pieces); consecutive dashes were re‑chained into lines (`n_frag` = pieces merged). Joins at junctions can be imperfect – the polygon edges in `geology_units` are the authoritative boundaries. |
| `faults.shp` | 648 | major fractures/faults + inferred fractures (dashes re‑chained) |
| `fold_axes.shp` | 90 | anticlinal / synclinal axes |
| `younger_granite_outlines.shp` | 59 | outlines of the Jos‑Plateau ring complexes (18 are closed rings) |
| `volcanic_plugs.shp` | 68 points | centre of each plug/pipe marker |
| `rivers.shp`, `major_rivers_poly.shp`, `major_rivers_outline.shp` | 1 054 / 4 / 72 | rivers as drawn; Niger–Benue & Lake Chad as polygons |
| `state_boundaries.shp` | 83 lines | the continuous grey boundary band (the black dash‑dot on top is only symbol fragments, kept in `by_layer.zip`) |
| `roads.shp` | 122 | the road symbol is a double line, each road was exported twice ~1 km apart; the pairs were collapsed to centrelines |
| `railway.shp` | 6 | rail lines (the 294 cross‑ticks of the symbol were dropped) |
| `ridges.shp` | 2 | |
| `towns.shp` | 486 points | marker centres; 404 got their `name` from the label placed next to them (`name_dist` = match distance in pt) |
| `state_capitals.shp` | 32 points | **approximate** – capitals have no marker in the PDF, only a halo label; point = label centre (checked against real coordinates: median error ≈7 km, max ≈15 km) |
| `labels.shp` | 1 973 points | every text string on the map face (unit codes, town names, water names) with font/size/angle; one‑character text runs were re‑assembled into words |
| `graticule.shp` | 22 | the fitted graticule (QA) |
| `legend.csv` | 92 rows | legend swatch colour → unit code → description, read from the EXPLANATIONS panel |
| `map_raster/` | PNG + `.pgw` | 150 dpi render of the map face with a world file, for overlay/QA |
| `preview.png` | | rendering of the extracted layers |

### Caveats – what is *not* recoverable or inherited from the source

* **No real attribute tables.** The PDF carries no feature attributes; `unit`, `code`, `name` etc. are reconstructed from layer names, legend swatches and label placement. Spot‑check before relying on a code: e.g. the map prints **OGe** on the polygons that the legend calls **OGm** (Medium‑ to coarse‑grained biotite granite) – both values are kept (`lbl_code` vs `leg_code`). Seven units (e.g. OGp, 249 polygons) are missing from the printed legend, so their code comes from the map labels.
* **Datum unknown.** The graticule gives geographic coordinates but not the datum; WGS 84 is assumed (Minna datum would differ by ~100–200 m, below drawing resolution).
* **Precision** is that of a 1:2 M drawing: 1 pt = 0.35 mm = ~700 m on the ground; the source data were themselves digitised at this scale.
* **Topology** is as in the source: 16 exact duplicate polygons, some overlaps between adjacent units (≈2 % of the area, mostly Alluvium and Bida‑basin units), small slivers.
* Dashed/decorated line symbols (boundary types, faults, fold axes, roads, railway) were re‑assembled heuristically from symbol fragments; use `by_layer.zip` for the raw fragments if you prefer to do that yourself.
* Layout elements (title, stratigraphic column, legend graphics, scale bar, logo) are not exported.

## 3. Reproducing

```bash
python -m venv .venv && . .venv/bin/activate
pip install pikepdf pymupdf shapely pyshp numpy pyogrio   # pyogrio only needed for the .gpkg bundle
python extract_shapefiles.py ilide.info-geological-map-of-nigeria-pr_a0987e407d194cb02682ac479336acb1.pdf shapefiles
```

The script parses the PDF content stream itself (paths, text and Optional‑Content tags), fits the graticule, rebuilds polygons/lines/points and writes the shapefiles; it runs in ~10 s.

## 4. Live comparison viewer (mobile-first)

```bash
python viewer/serve.py          # then open http://localhost:8080  (bind: 0.0.0.0, flags: --port, --rebuild)
```

The first start runs `viewer/build_data.py` (~30 s): it renders the original PDF page to Leaflet
EPSG:4326 tiles (zoom 4–9 ≈ 330 dpi) placed with the graticule georeference, converts the
shapefiles to GeoJSON and computes PDF-vs-output statistics. Generated data lives in
`viewer/build/` (git-ignored). Extra dependencies: `pymupdf pillow pyogrio` (plus the extraction
dependencies above for the statistics).

What the viewer offers (designed for a phone screen, works on desktop too):

* **Swipe** – original PDF on the left of a draggable divider, extracted layers (drawn with a
  matching symbology) on the right; **Overlay** – extracted layers over the PDF with an opacity
  slider; **PDF only** / **Extracted** – one at a time.
* Tap any extracted feature for its attributes (plus the geology unit under the point).
* Layer switches, legend from `legend.csv` with “highlight this unit” and the units missing from
  the printed legend, a “Compare” tab with the GeoPDF verdict and PDF-primitive vs feature counts,
  quick zooms (Jos Plateau, Niger Delta, Lake Chad, Sokoto, the PDF legend panel).

---

# Mineral Resources Map of Nigeria (2023) – GeoPDF → shapefiles

Source file: `Mineral_Resources_Map_of_Nigeria_2023.pdf` (55 × 30 in, single page, **Esri ArcMap 10.2.2**, 2023‑08‑17).
Script: `extract_mineral_map.py` → outputs in `shapefiles_minerals/` (WGS 84 `.prj`) + `shapefiles_minerals/nigeria_minerals.gpkg`.

## 1. Is it a GeoPDF?

**Yes.** The page carries an ISO‑32000 geospatial viewport (`/VP` → `/Measure` `/GEO`, four corner `/GPTS`, `/GCS` WKT), so GDAL/QGIS/Avenza place it directly. The frame runs 2.47619–15.02138 °E × 3.83671–14.04668 °N, lon/lat are linear in page coordinates (Plate Carrée data frame, 157.586 pt/°); the transform is in `shapefiles_minerals/georeferencing.json`.

Two things to know about that georeference (both recorded in `georeferencing.json`/`qa_report.json`):

* The declared CRS is `GCS_Assumed_Geographic_1` (ArcGIS' placeholder for "lat/lon, datum unknown", nominally NAD27/Clarke 1866). The data are plainly Nigerian lat/lon; outputs are written as EPSG:4326 – the datum difference is far below the ≈1 km symbol resolution.
* The **printed meridian labels disagree with the embedded georeference by 0.172 ° (≈19 km)**: the lines labelled 4…14 °E sit at 4.17…14.17 °E in the `/VP` affine (parallels agree to < 0.001 °). An independent check against the 33 state‑capital markers shows the `/VP` affine is the better of the two (mean offset −7 km E / −7 km N, rms 11 km; shifting to the meridian labels would make it −26 km E), so `/VP` is used for every layer and the `graticule` layer carries both values (`printed`, `vp_value`).

## 2. What is in the PDF, and what the layers carry

Unlike the geological map, only part of this map is vector. The **background geology, the mineral symbols and the state‑capital squares are a raster** (7 image strips, 2060 × 1677 px ≈ 75 dpi); the vector layers are Roads, Rivers, Railway, International boundary, division lines, Towns (circles), Graticule, and all text (town/capital/state/river names, mineral numbers, the EXPLANATIONS table and legend text). The map locates mineral occurrences by a **number printed on the map** which is resolved through the EXPLANATIONS table (seven numbering zones A–G, each restarting at 1), and by a **coloured legend symbol** next to the number. The extraction therefore joins three sources: the number labels (vector text), the table (vector text) and the symbols (raster blobs).

| Output | Features | What it carries |
|---|---|---|
| `mineral_localities.shp` / `.csv` | 999 points | One point per mineral number printed on the map. `zone`, `number`, `zone_num` (e.g. `E109`); from the table join: `locality`, `codes_raw` (as printed), `minerals` (expanded names), `min_conf` (certain / legend / probable / uncertain / unknown per code), `match` (995 `exact`, 4 `number not in table`), `tbl_flags`. Position: `pos_src` = `raster symbol (colour-consistent)` for the 672 numbers whose legend symbol (right colour, size and fill class for the listed mineral) was found within 25 pt – the point is the symbol centre, `snap_pt` the distance – otherwise `label centre` (327; the number itself, ~5–15 pt ≈ 3–10 km from the symbol). `label_lon/lat` always hold the number's own position. |
| `explanations_table.csv` | 1 171 rows | The complete EXPLANATIONS list (A 103, B 165, C 86, D 157, E 234, F 202, G 224 rows), parsed from the eight text columns: `zone`, `number` (sequential, see caveats), `number_printed`, `locality`, `codes_raw`, `codes`, `minerals`, `code_confidence`, `unknown_codes`, `on_map` (958 rows have their number on the map, 213 do not), `flags`, `table_column`, `raw_text`. |
| `mineral_symbols_raster.shp` | 1 642 points | Every coloured symbol blob detected in the raster: `colour` class, size, `fill` (solid / round / sparse – distinguishes e.g. the solid gold square from the lettered brine circle), `candidates` (legend minerals consistent with colour+size+fill; 1 377 blobs have a rule), `link` + `near_*` (the number label it serves, if any). 559 blobs have no number within 14 pt – unnumbered symbols, geology‑pattern fragments and water bodies (`blue`). |
| `mineral_legend.csv`, `legend_symbols/` | 67 rows, 66 PNGs | Legend order, mineral name, the code printed in the legend (only 19 entries have one), the table codes mapped to that mineral, cut‑outs of each legend symbol. |
| `mineral_code_dictionary.csv` | 120 codes | Every code used in the table → mineral, with confidence (36 certain, 20 from the legend, 30 probable, 15 uncertain, 19 unknown – e.g. `Us`, `Ke`, `Cy`, each used once or twice). |
| `map_zones.shp`, `division_lines.shp` | 7 / 5 | The A–G numbering zones polygonised from the division lines + frame (`tbl_rows`, `labels` per zone). |
| `roads.shp` | 115 lines, 18 400 km | Double‑line symbol collapsed to centrelines (`n_frag` fragments merged). |
| `rivers.shp` | 876 lines, 43 200 km | As drawn (the vector river layer; lakes/large rivers are raster only). |
| `railway.shp` | 6 lines | The 114 white dash overprints of the symbol dropped. |
| `international_boundary.shp` | 1 line, 4 090 km | The red band; the black dashes of the symbol dropped. |
| `graticule.shp`, `map_frame.shp` | 11 / 1 | `axis`, `vp_value`, `printed` (see §1). |
| `towns.shp` | 483 points | 478 vector circles (`town marker`), 411 named from the label beside them (`name_dist` = marker‑to‑label distance), 67 without a legible name; plus 5 names whose circle is shared with/hidden by a neighbour (`name only (no marker)`, placed at the label). |
| `state_capitals.shp` | 33 points | Capitals have no vector marker – the grey square is in the raster, centred under the bold label. 14 were located on that square (`src = raster capital square`), the rest sit at the label centre (within ≈1 pt of the square where both exist). |
| `state_name_labels.shp` | 37 | the 36 states + FCT labels |
| `river_labels.shp` | 119 | italic water names as placed (curved names come in pieces) |
| `pegmatite_marks.shp` | 23 | the "P" pegmatite marks of the geology legend |
| `map_labels.shp` | 683 | every text string on the map face except the mineral numbers, with layer, font, size, angle |
| `geology_legend.csv` | 9 | the background‑geology legend order – the geology itself is raster only |
| `map_raster/` | PNG + `.pgw` | the untouched 75 dpi raster strips reassembled and world‑filed (`mineral_map_base_75dpi.png`, the actual symbol source) and a 150 dpi render of the full map face |
| `qa_report.json` | | all counts above, the unmatched numbers, snap statistics, the capital check |

### How the table/number join was verified

* Every zone's list is contiguous after parsing: the only numbers absent from the printed list are **F 110, G 53, G 86, G 111** (F110, G53 and G86 *are* printed on the map – those three labels are kept with `match = number not in table`). One printed number exists in no list (D 256, a misprint). Two lone `0` glyphs drawn in a separate pass of the content stream sit exactly one character to the right of other numbers (`46`→"460", `115`→"1150"); glyphs are grouped by geometry *and* drawing order so these are recognised as strays and dropped (`qa_report.json → stray_zero_glyphs_dropped`).
* 30 rows have a misprinted number that is unambiguous from its neighbours (e.g. `109. Kafin‑chiri` followed by `109 Kofin‑chini`, `53. Basuras` between 82 and 84) – `number` holds the sequential value, `number_printed` the print, `flags` says so. 10 numbers were printed in a broken font (`I`, `SI`, `SE`, `lOB`, `•7` …) and are inferred from the sequence; 2 entries carry a suffix in the source (B 17A, D 67A). All of these were checked against the rendered PDF.
* Three numbers printed on or just across a division line (F 9, F 10 = Obajana and E 15) fall geometrically in the neighbouring zone; the zone is chosen from the numbering sequence (consecutive numbers are placed close together) and the change is recorded in `qa_report.json → rezoned_by_numbering_sequence`. Every one of the 2 393 digit glyphs on the map is accounted for by exactly one label.
* Zone B's rows 156–164 are typeset at the foot of the D column; they are assigned to B by position (`TABLE_ZONE_OVERRIDES`). 113 rows had the mineral codes typed into the locality cell; they are split off only when every token is a known code.
* Symbol detection was calibrated on localities with a single mineral (gold = solid yellow 8 × 8 px square, clay = yellow 14 × 10 rectangle, kaolin = khaki rectangle, limestone = hatched green, tantalite = white bowl, barytes/gypsum = white ring arcs, lead‑zinc = red triangle …) and is applied as colour + size + fill‑class rules; a number is only snapped to a symbol whose rule contains one of its minerals. Tin (`Sn`, 73 rows) and quartz/monazite/ruby codes have no legend symbol by design and stay at the label.

### Caveats

* **Positions**: 1 pt ≈ 0.7 km; a snapped point is the symbol centre (±1–2 px), an unsnapped one is the number's centre, which is typically 3–10 km from the deposit symbol. The `/VP` georeference itself is ≈7 km off true positions in both axes (capital check), consistent with a 1:2 M compilation.
* **Minerals come from codes typed by the map compiler**, with inconsistent spelling (`CI`/`Cl`, `MI`/`mi`, `PbS`/`Pbs`); confidence is recorded per code and 19 codes could not be resolved at all.
* Mineral symbols without a number (559 blobs) are delivered as raw raster blobs with candidate minerals only – the map gives no other way to identify them.
* Background geology, lakes and the large rivers exist only as raster.

## 3. Reproducing

```bash
pip install pikepdf pymupdf shapely pyshp numpy pillow scipy pyogrio   # pyogrio only for the .gpkg
python extract_mineral_map.py Mineral_Resources_Map_of_Nigeria_2023.pdf shapefiles_minerals   # ~10 s
```
