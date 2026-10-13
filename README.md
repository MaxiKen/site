# Geological map of Nigeria (NGSA) — raster → GIS polygons

Digitised from the single supplied scan
`pic NGSA geological-map-of-nigeria-.jpg` (6600 × 3675 px).

## Deliverables

| file | what it is |
|---|---|
| `output/nigeria_geology.shp` (+ `.shx .dbf .prj .cpg`) | **88 map units**, 1 404 polygons, 150 691 vertices — EPSG:4326 |
| `output/nigeria_hydro.shp` | surface water (ocean, Lake Chad, Kainji, lagoons) as its own layer |
| `output/*.geojson` | the same data in GeoJSON (for web / QGIS interchange) |
| `web/` | live comparison viewer (see below) |

Attribute table of `nigeria_geology.shp`:

`CLASS_ID, CODE, NAME, LITH, AGE, RGB, HEX, AREA_KM2, NPART, NVERT, NOTE`

* `CODE` – the map's own unit symbol (OGp, Cst, Ajst, …)
* `NAME` / `LITH` / `AGE` – legend text (OCR'd and cleaned)
* `RGB`, `HEX` – the exact colour of the unit on the scan
* `AREA_KM2` – equal-area measurement (Albers, secants 5°N/14°N)
* `NOTE` – flags the two legend/map colour conflicts (see *Known issues*)

## Method

1. **Georeferencing.** The neatline graticule ticks were located on the frame
   (12 longitude ticks x = 408…4020, 10 latitude ticks y = 485…3440) and fitted
   by least squares. Residual < 0.6 px (≈ 200 m).

   ```
   lon =  0.00304544 * x + 1.756135
   lat = -0.00304560 * y + 14.475621      (x, y = pixel on the full 6600×3675 scan)
   ```
   Verified: Lake Chad, Lake Kainji and the Lagos lagoon all fall on water;
   Port Harcourt on the mangrove belt; Maiduguri/Damaturu on the Chad Formation;
   Potiskum on the Kerri-Kerri Formation; Jos on the Younger Granite.

2. **Legend → palette.** 94 legend swatches were read from the right-hand legend
   column and matched to their code / lithology / age text by OCR
   (`work/legend.py`, `work/build_palette.py`).

3. **Pixel classification.** Every pixel was matched to the nearest legend
   colour. Black linework (labels, contacts, faults, graticule) was treated as
   *unknown*, not as a unit.

4. **Road / rail stripping.** The map prints its road and rail network in a
   grey (~rgb 170,170,170) linear overlay. It was detected structurally
   (low saturation + thin: distance-to-edge ≤ 5 px), closed, dilated 1 px and
   removed. 6.5 % of the map body was road overlay; the underlying geology was
   then interpolated across it.

5. **Gap filling.** All remaining unknown pixels (linework, type, graticule,
   antialiasing, JPEG fringe) were filled from the nearest classified pixel, so
   every removed black feature is absorbed into the geology that surrounds it —
   no slivers, no holes.

6. **De-speckling.** Iterated removal of connected components below 40 / 50 /
   90 px, each pass followed by re-filling, then a 9-px majority vote.

7. **Vectorisation with shared, pre-smoothed arcs** (`work/vectorize.py`,
   `work/build_polys.py`). Boundaries were extracted as a planar graph of unit
   segments, chained into 4 598 arcs between junction nodes, and each arc
   simplified **once** — so both sides of every shared border receive byte-
   identical geometry. Per arc: Douglas–Peucker (0.9 px) → densify (3 px) →
   Chaikin ×2 → re-simplify (0.25 px). The densify step matters: Chaikin's
   corner cut scales with segment length, so long straight edges must be
   subdivided first or the frame corners get rounded away.
   The arcs are then reassembled with `shapely.ops.polygonize`, giving a
   gap-free, overlap-free mosaic (**100.000 % of the map body is covered**).

8. **Dissolve & export.** Cells were labelled by majority vote from the raster,
   dissolved per unit, clipped to the neatline interior, measured in an
   equal-area projection and written as EPSG:4326 shapefiles.

## Verification

`work/verify2.py` re-rasterises the delivered polygons and compares them with
the scan, block by block (32 × 32 px, 9 118 blocks), after excluding black
linework and the road overlay:

* **mosaic coverage of the map body: 100.000 %**
* **block-by-block unit agreement: 94.4 %**
* 0 invalid geometries, 0 slivers < 1 × 10⁻⁷ deg²
* average 107 vertices per polygon — no staircase edges

Ground-truth spot checks (32 well-known locations) now return the expected
geology, e.g. Port Harcourt / Warri → mangrove swamps, Benin City / Owerri →
Benin Formation, Ibadan / Akure / Ilorin / Kaduna → migmatite-basement,
Zaria / Kano → Older Granite, Katsina → Gundumi-Illo, Sokoto → Rima Group,
Birnin Kebbi → Gwandu, Jos → Younger Granite, Maiduguri / Damaturu → Chad
Formation, Potiskum → Kerri-Kerri, Lake Chad / Kainji → water.

## Known issues

* **Two legend rows share the code `MS` and their colour chips are printed
  interchanged with what the map actually uses.** The map paints the Niger
  Delta mangrove belt vivid yellow (242,246,0) — the colour the legend assigns
  to *Pelitic Schist / Muscovite Schist* — and paints the schist belts of
  central Nigeria periwinkle (150,170,254) — the colour the legend assigns to
  *Mangrove swamps*. Attribution follows the **map** (the left-hand correlation
  chart independently prints "MS / Mangrove swamps" against a yellow bar).
  Both rows carry a `NOTE` and keep their own `CLASS_ID`.
* **Psh (121,223,176) and NPss (123,223,176) differ by 2/255 in one channel**
  and cannot be separated by colour on a JPEG scan; they account for the
  largest single confusion group (52 of 9 118 blocks).
* Roads and railways are removed, so their corridors now carry the geology of
  the surrounding unit (that is what "absorb the gaps" implies). The corridors
  are 3–10 px ≈ 1–3 km wide.
* Water is kept as a separate layer (`nigeria_hydro.shp`). Small water bodies
  (< 20 000 px ≈ 2 300 km², i.e. rivers and minor lakes) were absorbed into the
  geology so the geology layer stays gap-free; the ocean, Lake Chad, Lake
  Kainji and the lagoons remain as their own polygons.

## Live comparison viewer

```
python3 web/serve.py          # serves http://0.0.0.0:8000
```

* **side-by-side** mode: the scan on the left, the shapefile on the right, pan
  and zoom synchronised
* **overlay** mode: the polygons drawn straight on top of the scan
* polygon-opacity slider, "scan under polygons" toggle, hydro-layer toggle
* click any polygon for its attributes; the right-hand list filters and
  highlights units

Leaflet is bundled locally (`web/leaflet.js`), so no external CDN is used.

## Reproducing

```bash
python3 work/clean2.py                                    # classified + cleaned raster
python3 - <<'EOF'                                         # absorb small water bodies
...
EOF
python3 work/build_polys.py 0.9 2 work/lab_final.npy work/cells.pkl
python3 work/export.py
python3 work/mkweb.py
python3 work/verify2.py
```

Key intermediates: `work/lab_raw.npy` (raw nearest-legend classification),
`work/dist.npy` (colour residual), `work/road_mask.npy`,
`work/lab_final.npy` (cleaned raster actually vectorised),
`work/cells.pkl` (the polygon mosaic before dissolve).
