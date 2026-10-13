"""Dissolve the cell mosaic into per-unit polygons and write EPSG:4326 shapefiles."""
import numpy as np, json, pickle, os, math
from shapely.geometry import Polygon, MultiPolygon, shape, mapping, box as sbox
from shapely.affinity import affine_transform
from shapely.ops import unary_union
from shapely.validation import make_valid
import geopandas as gpd
import pandas as pd
from collections import defaultdict

PAL = json.load(open('work/palette.json'))
G   = json.load(open('work/georef.json'))
A_LON, B_LON, A_LAT, B_LAT = G['a_lon'], G['b_lon'], G['a_lat'], G['b_lat']
X0, Y0 = 189, 189
WATER, PAPER = 94, 201

d = pickle.load(open('work/cells.pkl', 'rb'))
labels = np.asarray(d['labels']); geoms = d['geoms']
H, W = d['shape']

M = [A_LON, 0, 0, A_LAT, A_LON * X0 + B_LON, A_LAT * Y0 + B_LAT]
# interior of the neatline (drops the black frame line itself)
clip = sbox(A_LON * (X0 + 1) + B_LON, A_LAT * (Y0 + H - 2) + B_LAT,
            A_LON * (X0 + W - 1) + B_LON, A_LAT * (Y0 + 1) + B_LAT)
print('clip box lon/lat:', [round(v, 5) for v in clip.bounds])

buckets = defaultdict(list)
skipped = 0
for lab, g in zip(labels, geoms):
    if int(lab) in (PAPER,): continue
    gg = affine_transform(g, M)
    if not gg.is_valid: gg = make_valid(gg)
    gg = gg.intersection(clip)
    if gg.is_empty: skipped += 1; continue
    buckets[int(lab)].append(gg)
print('cells used', sum(len(v) for v in buckets.values()), 'skipped', skipped)

# equal-area CRS for area measurement (Albers, secants at 5N/14N)
aea = ('+proj=aea +lat_1=5 +lat_2=14 +lat_0=9 +lon_0=8.5 +x_0=0 +y_0=0 '
       '+datum=WGS84 +units=m +no_defs')
rows = []
for lab, gs in buckets.items():
    geo = unary_union(gs)
    if not geo.is_valid: geo = make_valid(geo)
    if geo.geom_type == 'Polygon': geo = MultiPolygon([geo])
    p = PAL[lab - 1] if 1 <= lab <= len(PAL) else None
    area_km2 = gpd.GeoSeries([geo], crs=4326).to_crs(aea).area.iloc[0] / 1e6
    rows.append(dict(
        CLASS_ID=int(lab),
        CODE=(p['code'] if p else 'WATER'),
        NAME=(p['name'] if p and p.get('name') else ('Surface water' if lab == WATER else '')),
        LITH=(p['lith'] if p else 'Water bodies (ocean, lakes, rivers)'),
        AGE=(p.get('age', '') if p else ''),
        RGB=('%d,%d,%d' % tuple(p['rgb'])) if p else '150,216,240',
        HEX=('#%02x%02x%02x' % tuple(p['rgb'])) if p else '#96d8f0',
        AREA_KM2=round(float(area_km2), 3),
        NPART=len(geo.geoms),
        NVERT=sum(len(shapely_exterior(g)) if False else len(g.exterior.coords) + sum(len(r.coords) for r in g.interiors) for g in geo.geoms),
        NOTE=(p.get('note', '') if p else ''),
        geometry=geo))
gdf = gpd.GeoDataFrame(rows, crs='EPSG:4326').sort_values('AREA_KM2', ascending=False)

os.makedirs('output', exist_ok=True)
geo_l = gdf[gdf.CLASS_ID != WATER].copy()
wat_l = gdf[gdf.CLASS_ID == WATER].copy()
for name, layer, cols in (('nigeria_geology', geo_l, None), ('nigeria_hydro', wat_l, None)):
    layer.to_file(f'output/{name}.shp', driver='ESRI Shapefile', encoding='utf-8')
    layer.to_file(f'output/{name}.geojson', driver='GeoJSON')
    print(f'{name}: {len(layer)} features, {layer.AREA_KM2.sum():,.0f} km2')

print('\nUNIT, area km2, parts')
for _, r in gdf.head(28).iterrows():
    print(f'  {r.CODE:10s} {r.AREA_KM2:11,.1f}  {r.NPART:4d}  {r.LITH[:46]}')
print(f'\nTOTAL mapped: {gdf.AREA_KM2.sum():,.0f} km2   (geology {geo_l.AREA_KM2.sum():,.0f}, water {wat_l.AREA_KM2.sum():,.0f})')
