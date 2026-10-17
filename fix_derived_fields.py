#!/usr/bin/env python3
"""
Refresh the *derived* attribute columns after the latitude calibration.

`calibrate_maps.py --apply` moves the geometry and every latitude column
(`lat`, `label_lat`, `mid_lat`, `start_lat`, `end_lat`) in step.  A few columns
are computed *from* those coordinates and would otherwise still describe the
pre-calibration positions:

  rivers / roads / railway   mid_lon, mid_lat, start_*, end_*  -> re-derived from the geometry
                             length_km                            -> re-measured on the geometry
  state_capitals             ref_dx_km, ref_dy_km               -> re-measured against ref_lon/ref_lat

The script is idempotent: running it twice changes nothing.  It reports every
column it rewrites so the change can be audited.

Columns that are deliberately NOT rewritten (they are extraction QA metrics, in
PDF points, and describe the source document, not the delivered coordinates):
  mineral_localities.snap_pt, mineral_symbols_raster.near_dist

Usage:  python3 fix_derived_fields.py [--dataset minerals]
"""
import argparse
import math
import os
import sys

import numpy as np
import shapefile
from shapely.geometry import LineString

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from extract_shapefiles import geo_length_km          # noqa: E402

SHP = {'geology': os.path.join(ROOT, 'shapefiles'), 'minerals': os.path.join(ROOT, 'shapefiles_minerals')}
KMX = 111.32 * math.cos(math.radians(9.0))
KMY = 110.57


def rewrite(path, fn):
    """Rewrite a shapefile in place, letting fn(shape, record_dict) mutate record_dict."""
    r = shapefile.Reader(path)
    fields = r.fields[1:]
    names = [f[0] for f in fields]
    tmp = path[:-4] + '.fix.shp'
    w = shapefile.Writer(tmp, shapeType=r.shapeType)
    w.fields = fields
    changes = {}
    for sh, rec in zip(r.shapes(), r.records()):
        d = dict(zip(names, rec))
        fn(sh, d)
        w.shape(sh)
        w.record(*[d[n] for n in names])
    w.close()
    r.close()
    for ext in ('.shp', '.shx', '.dbf'):
        os.replace(tmp[:-4] + ext, path[:-4] + ext)
    for ext in ('.prj', '.cpg'):
        if os.path.exists(tmp[:-4] + ext):
            os.remove(tmp[:-4] + ext)
    return changes


def fix_lines(ds, name):
    path = os.path.join(SHP[ds], name + '.shp')
    if not os.path.exists(path):
        return 0

    def fn(sh, d):
        pts = np.asarray(sh.points, float)
        if len(pts) < 2:
            return
        L = LineString(pts)
        mid = L.interpolate(0.5, normalized=True)
        d['mid_lon'] = round(mid.x, 6)
        d['mid_lat'] = round(mid.y, 6)
        d['start_lon'], d['start_lat'] = round(pts[0, 0], 6), round(pts[0, 1], 6)
        d['end_lon'], d['end_lat'] = round(pts[-1, 0], 6), round(pts[-1, 1], 6)
        d['length_km'] = round(geo_length_km([tuple(p) for p in pts]), 2)

    rewrite(path, fn)
    print('  refreshed %-16s mid/start/end/length' % name)
    return 1


def fix_capitals(ds):
    path = os.path.join(SHP[ds], 'state_capitals.shp')
    if not os.path.exists(path):
        return 0
    n = 0

    def fn(sh, d):
        nonlocal n
        if d.get('ref_lon') is None or d.get('ref_lat') is None:
            return
        dx = (d['lon'] - d['ref_lon']) * 111.32 * math.cos(math.radians(d['ref_lat']))
        dy = (d['lat'] - d['ref_lat']) * KMY
        d['ref_dx_km'] = round(dx, 1)
        d['ref_dy_km'] = round(dy, 1)
        n += 1

    rewrite(path, fn)
    print('  refreshed state_capitals  ref_dx_km/ref_dy_km on %d rows' % n)
    return 1


def verify():
    """Assert that attribute coordinates still describe the geometry and the CSV exports."""
    import csv
    ok = True
    for ds in ('geology', 'minerals'):
        for path in sorted(__import__('glob').glob(os.path.join(SHP[ds], '*.shp'))):
            r = shapefile.Reader(path)
            names = [f[0] for f in r.fields[1:]]
            if r.shapeTypeName == 'POINT' and 'lon' in names and 'lat' in names:
                worst = 0.0
                for sh, rec in zip(r.shapes(), r.records()):
                    if not sh.points:
                        continue
                    d = dict(zip(names, rec))
                    worst = max(worst, abs(d['lon'] - sh.points[0][0]), abs(d['lat'] - sh.points[0][1]))
                if worst > 1e-6:
                    ok = False
                    print('  FAIL %s: attribute vs geometry %.2e deg' % (path, worst))
        csv_p = os.path.join(SHP[ds], 'mineral_localities.csv')
        shp_p = os.path.join(SHP[ds], 'mineral_localities.shp')
        if os.path.exists(csv_p) and os.path.exists(shp_p):
            r = shapefile.Reader(shp_p)
            names = [f[0] for f in r.fields[1:]]
            rows = [dict(zip(names, rec)) for rec in r.records()]
            cs = list(csv.DictReader(open(csv_p)))
            bad = sum(1 for c, d in zip(cs, rows) if abs(float(c['lat']) - d['lat']) > 1e-6)
            print('  %s: CSV vs DBF latitude, %d of %d rows differ' % (ds, bad, len(rows)))
            ok &= bad == 0
    print('coordinate consistency:', 'OK' if ok else 'FAILED')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', choices=['geology', 'minerals', 'all'], default='all')
    args = ap.parse_args()
    for ds in (['geology', 'minerals'] if args.dataset == 'all' else [args.dataset]):
        print(ds)
        for layer in ('rivers', 'roads', 'railway', 'international_boundary'):
            fix_lines(ds, layer)
        fix_capitals(ds)
    verify()


if __name__ == '__main__':
    main()
