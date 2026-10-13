#!/bin/sh
# full pipeline: scan -> EPSG:4326 shapefiles -> web viewer
set -e
python3 work/clean2.py                 # classify, strip roads, de-speckle, fill gaps
python3 work/make_final.py             # absorb small water bodies into the geology
python3 work/build_polys.py 0.9 2 work/lab_final.npy work/cells.pkl
python3 work/export.py                 # output/nigeria_geology.shp + nigeria_hydro.shp
python3 work/mkweb.py                  # web/*.geojson + bundled leaflet
python3 work/verify2.py                # block-by-block fidelity report
