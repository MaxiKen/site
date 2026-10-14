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
