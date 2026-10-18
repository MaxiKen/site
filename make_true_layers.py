#!/usr/bin/env python3
"""
Build the land-consistent "true WGS 84" point layers.

Why
---
Both NGSA sheets were plotted on a topographic base (settlements, roads, railway,
state-capital squares) that is **0.66 % under scale**: measured against Natural
Earth and Wikipedia, every town marker sits a median 11 km south-west of its true
position, and the two sheets agree with each other to 0.5 km because they share
that base.  Near the coast the error is large enough that towns, capital squares
and their labels fall into the sea - Cotonou 6.6 km offshore, Port Harcourt 13 km
from its true position.

The raster (geology / mineral symbols), the rivers and the national boundary do
NOT carry that error (verified at <=1 km against Natural Earth), so they are left
alone.

What this script does
---------------------
For `towns` and `state_capitals` of both datasets it writes a sibling layer
`<layer>_wgs84` whose geometry is the model-corrected position, keeping the
printed coordinate and the applied correction as attributes:

    lon, lat            corrected position (the geometry)
    lon_map, lat_map    position as printed on the sheet (the original shapefile)
    de_km, dn_km        correction applied (model value, negative = map west/south of truth)
    move_km             magnitude of the correction
    on_land             1 = inside a Natural Earth 10m land polygon, 0 = water
    coast_km            distance to the nearest coastline (0 when on land)

The model is read from `<dataset>/calibration.json -> topographic_overlay.model`,
i.e. it is the same field that `accuracy_check.py` measures.

Model & limits
--------------
    dE_km = a*lon + b*lat + c ;  dN_km = a'*lon + b'*lat + c'
    (fit on 54 town control points, both sheets, Ogoja excluded)
    residual on the control points: rms 2.0 km; median 2.3 km, p90 4.5 km

The correction is an *estimate*: it removes the systematic 11 km error and leaves
1-5 km of scatter from the source drawing.  It is the right input for area /
distance calculations that involve settlements; it is not a survey.

Usage
-----
    python3 make_true_layers.py            # write the *_wgs84 layers for both datasets
    python3 make_true_layers.py --check    # report land status without writing
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import shapefile
from shapely.geometry import Point, shape, box
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(ROOT, 'reference_data')
SHP = {'geology': os.path.join(ROOT, 'shapefiles'), 'minerals': os.path.join(ROOT, 'shapefiles_minerals')}
KMX = 111.32 * math.cos(math.radians(9.0))
KMY = 110.57


# --------------------------------------------------------------------------- model
def load_model(ds):
    cal = json.load(open(os.path.join(SHP[ds], 'calibration.json')))
    m = cal['topographic_overlay']['model']
    ax = m['dE = a*lon + b*lat + c']
    ay = m['dN = a*lon + b*lat + c']
    return ax, ay


def delta_km(model, lon, lat):
    ax, ay = model
    return ax[0] * lon + ax[1] * lat + ax[2], ay[0] * lon + ay[1] * lat + ay[2]


def true_position(model, lon, lat, iters=4):
    """Invert the field: the printed position p satisfies true = p - field(true)."""
    tlon, tlat = lon, lat
    for _ in range(iters):
        de, dn = delta_km(model, tlon, tlat)
        tlon, tlat = lon - de / (111.32 * math.cos(math.radians(tlat))), lat - dn / KMY
    return tlon, tlat


# --------------------------------------------------------------------------- land
def land_geometry():
    p = os.path.join(REF, 'ne_10m_land.geojson')
    if not os.path.exists(p):
        sys.exit('missing %s - run accuracy_check.py once (it fetches the Natural Earth layers)' % p)
    win = box(2.0, 3.0, 16.0, 15.0)
    parts = []
    for f in json.load(open(p))['features']:
        g = shape(f['geometry'])
        if g.intersects(win):
            gi = g.intersection(win)
            if not gi.is_empty:
                parts.append(gi)
    return unary_union(parts)


def land_status(land, lon, lat):
    p = Point(lon, lat)
    if land.contains(p):
        return 1, 0.0
    return 0, land.boundary.distance(p) * 110.0


# --------------------------------------------------------------------------- layers
def read_layer(path):
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields[1:]]
    fields = r.fields[1:]
    rows = []
    for sh, rec in zip(r.shapes(), r.records()):
        if not sh.points:
            continue
        rows.append((sh.points[0][0], sh.points[0][1], dict(zip(names, rec))))
    return fields, rows


def write_layer(path, fields, rows):
    w = shapefile.Writer(path, shapeType=shapefile.POINT)
    for f in fields:
        w.field(*f)
    for lon, lat, rec in rows:
        w.point(lon, lat)
        w.record(*[rec[f[0]] for f in fields])
    w.close()
    # sidecars
    for ext in ('.prj', '.cpg'):
        src = path[:-4] + ext
        if not os.path.exists(src):
            sib = os.path.join(os.path.dirname(path), 'towns' + ext)
            if os.path.exists(sib):
                import shutil
                shutil.copyfile(sib, src)


# The 2011 sheet's capital names were placed individually and are unbiased (their offsets do not
# correlate with the topographic field; correcting them makes the median error worse: 7.3 -> 11.1 km).
# The 2023 sheet's capitals *do* follow the field (label-centred group: r=0.75 in N, median 13.2 -> 5.3 km).
CAPITAL_CORRECTION = {'geology': False, 'minerals': True}


def build(ds, land, check_only=False):
    model = load_model(ds)
    made = []
    for layer in ('towns', 'state_capitals'):
        src = os.path.join(SHP[ds], layer + '.shp')
        if not os.path.exists(src):
            continue
        fields, rows = read_layer(src)
        names = [f[0] for f in fields]
        extra = [('lon_map', 'N', 12, 6), ('lat_map', 'N', 12, 6),
                 ('de_km', 'N', 7, 2), ('dn_km', 'N', 7, 2), ('move_km', 'N', 7, 2),
                 ('on_land', 'N', 1, 0), ('coast_km', 'N', 6, 2), ('corr', 'C', 28, 0)]
        use_model = layer != 'state_capitals' or CAPITAL_CORRECTION[ds]
        out_fields = fields + [f for f in extra if f[0] not in names]
        out_rows = []
        for lon, lat, rec in rows:
            if use_model:
                tlon, tlat = true_position(model, lon, lat)
                de, dn = delta_km(model, tlon, tlat)
                corr = 'topographic model'
            else:
                tlon, tlat, de, dn = lon, lat, 0.0, 0.0
                corr = 'none (label is unbiased)'
            on_land, coast = land_status(land, tlon, tlat)
            rec = dict(rec)
            rec.update({'lon_map': round(lon, 6), 'lat_map': round(lat, 6),
                        'de_km': round(de, 2), 'dn_km': round(dn, 2), 'move_km': round(math.hypot(de, dn), 2),
                        'on_land': on_land, 'coast_km': round(coast, 2), 'corr': corr})
            rec['lon'] = round(tlon, 6) if 'lon' in rec else rec.get('lon')
            rec['lat'] = round(tlat, 6) if 'lat' in rec else rec.get('lat')
            out_rows.append((tlon, tlat, rec))
        dst = os.path.join(SHP[ds], layer + '_wgs84.shp')
        n_water = sum(1 for r in out_rows if r[2]['on_land'] == 0)
        n_water_before = sum(1 for lon, lat, rec in rows if not land.contains(Point(lon, lat)))
        print('  %s/%s_wgs84: %d features, %d in water (as printed: %d)'
              % (ds, layer, len(out_rows), n_water, n_water_before))
        if not check_only:
            write_layer(dst, out_fields, out_rows)
        made.append((layer + '_wgs84', len(out_rows), n_water, n_water_before))
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='measure only, do not write')
    args = ap.parse_args()
    land = land_geometry()
    for ds in ('geology', 'minerals'):
        print(ds)
        build(ds, land, check_only=args.check)


if __name__ == '__main__':
    main()
