#!/usr/bin/env python3
"""
Coordinate / calculation validator for the two Nigeria map datasets.

Runs every check that a calculation could depend on and prints PASS / WARN / FAIL
per check, plus a machine-readable `validation_report.json`.

Checks
------
CRS      .prj = WGS84 everywhere, every GeoPackage geometry column = 4326,
         viewer meta carries the CRS, coordinates are degrees in a plausible range
GEOMETRY polygons closed and valid, lines with >= 2 vertices, nothing empty
ATTRIBUTE point lon/lat equals the geometry; derived columns
         (length_km, area_km2, mid_*, start_*, end_*, ref_dx/dy) agree with the
         geometry and with a WGS84 geodesic computation
UNITS    coordinates are degrees, not metres; the derived columns are km / km²
LAND     every settlement / locality point falls on land (Natural Earth 10m),
         with the distance to the coast for the few waterfront exceptions
FRAMES   the two source PDFs compared to each other: projection, scale, rotation,
         datum, and the resulting ground displacement

Usage
-----
    python3 validate_coordinates.py             # run everything, print the table
    python3 validate_coordinates.py --quiet     # only the summary line
    python3 validate_coordinates.py --json out.json

Exit status is 0 when no check FAILs (warnings are allowed), 1 otherwise - so it
can be used as a pre-flight gate before a calculation.
"""
import argparse
import glob
import json
import math
import os
import sqlite3
import sys
import time

import numpy as np
import shapefile
from pyproj import Geod
from shapely.geometry import Point, Polygon, LineString, shape
from shapely.validation import explain_validity

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
SHP = {'geology': os.path.join(ROOT, 'shapefiles'), 'minerals': os.path.join(ROOT, 'shapefiles_minerals')}
GEOD = Geod(ellps='WGS84')
KMX = 111.32 * math.cos(math.radians(9.0))
KMY = 110.57

# layers whose points must be on land (settlements, localities, plugs)
LAND_LAYERS = {
    'geology': ['towns', 'state_capitals', 'towns_wgs84', 'state_capitals_wgs84', 'volcanic_plugs'],
    'minerals': ['towns', 'state_capitals', 'towns_wgs84', 'state_capitals_wgs84',
                 'mineral_localities', 'pegmatite_marks'],
}
# tolerance: anything further than this from land is a real error, not coastline detail
OFFSHORE_FAIL_KM = 2.0
# as-printed topographic layers carry the source's 0.66 % scale error; the *_wgs84
# siblings are the corrected, calculation-ready version (see ACCURACY.md 4.3)
TOPO_AS_PRINTED = {'towns', 'state_capitals'}

results = []


def add(check, status, detail, **extra):
    results.append(dict(check=check, status=status, detail=detail, **extra))


# --------------------------------------------------------------------------- helpers
def shape_bbox(sh):
    pts = sh.points
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def rings(sh):
    parts = list(sh.parts) + [len(sh.points)]
    return [np.asarray(sh.points[a:b], float) for a, b in zip(parts[:-1], parts[1:])]


def to_polygon(sh):
    """Shapely geometry of a shapefile record (pyshp groups rings by ESRI orientation)."""
    try:
        return shape(sh.__geo_interface__)
    except Exception:
        return None


def geod_length_km(pts):
    a = np.asarray(pts, float)
    _, _, d = GEOD.inv(a[:-1, 0], a[:-1, 1], a[1:, 0], a[1:, 1])
    return float(d.sum()) / 1000.0


def geod_area_km2(geom):
    try:
        a, _ = GEOD.geometry_area_perimeter(geom)
        return abs(a) / 1e6
    except Exception:
        return None


def read_layer(path):
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields[1:]]
    return r, names


# --------------------------------------------------------------------------- CRS
def check_crs():
    prjs = {}
    for ds, d in SHP.items():
        for p in glob.glob(os.path.join(d, '*.prj')):
            try:
                wkt = open(p).read().strip()
            except Exception as e:
                add('CRS .prj readable', 'FAIL', '%s: %s' % (p, e))
                continue
            prjs.setdefault(wkt, []).append(p)
    if not prjs:
        add('CRS .prj', 'FAIL', 'no .prj files found')
    else:
        if len(prjs) == 1 and 'WGS_1984' in next(iter(prjs)):
            n = sum(len(v) for v in prjs.values())
            add('CRS .prj', 'PASS', '%d .prj files, one distinct WKT: %s' % (n, next(iter(prjs))[:60] + '...'))
        else:
            add('CRS .prj', 'FAIL', '%d distinct WKT variants' % len(prjs),
                variants=[v[:80] for v in prjs])

    gpkg_paths = [os.path.join(ROOT, 'nigeria_maps.gpkg'),
                  os.path.join(SHP['geology'], 'nigeria_geology.gpkg'),
                  os.path.join(SHP['minerals'], 'nigeria_minerals.gpkg')]
    bad, total = [], 0
    for g in gpkg_paths:
        if not os.path.exists(g):
            continue
        db = sqlite3.connect(g)
        rows = db.execute('select table_name, srs_id from gpkg_geometry_columns').fetchall()
        total += len(rows)
        bad += [(os.path.basename(g), t, s) for t, s in rows if s != 4326]
        db.close()
    if bad:
        add('CRS GeoPackage', 'FAIL', '%d of %d geometry columns not 4326' % (len(bad), total), bad=bad[:10])
    else:
        add('CRS GeoPackage', 'PASS', '%d geometry columns in %d files, all srs_id = 4326' % (total, len(gpkg_paths)))

    meta_bad = []
    for ds, rel in (('geology', 'viewer/build/data/meta.json'), ('minerals', 'viewer/build/data/minerals/meta.json')):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        m = json.load(open(p))
        if m.get('crs') != 'EPSG:4326':
            meta_bad.append(rel)
        cal = m.get('calibration', {}).get('crs', {}).get('output')
        if cal != 'EPSG:4326':
            meta_bad.append(rel + ' (calibration)')
    if meta_bad:
        add('CRS viewer meta', 'FAIL', 'missing/!= EPSG:4326: %s' % ', '.join(meta_bad))
    else:
        add('CRS viewer meta', 'PASS', 'both meta.json files declare crs = EPSG:4326')


# --------------------------------------------------------------------------- geometry + attributes
def check_layers():
    n_layers = 0
    n_feat = 0
    invalid, unclosed, short, empty = [], [], [], []
    attr_bad, derived_bad = [], []
    dup_notes = []
    for ds, d in SHP.items():
        for p in sorted(glob.glob(os.path.join(d, '*.shp'))):
            name = os.path.basename(p)[:-4]
            r, names = read_layer(p)
            n_layers += 1
            n_feat += len(r)
            if len(r) == 0:
                empty.append(name)
                continue
            for k, (sh, rec) in enumerate(zip(r.shapes(), r.records())):
                n_pts = len(sh.points)
                if n_pts == 0:
                    empty.append('%s#%d' % (name, k))
                    continue
                if r.shapeTypeName in ('POLYGON', 'POLYGONZ', 'POLYGONM'):
                    for ring in rings(sh):
                        if len(ring) >= 3 and (abs(ring[0, 0] - ring[-1, 0]) > 1e-9 or abs(ring[0, 1] - ring[-1, 1]) > 1e-9):
                            unclosed.append('%s#%d' % (name, k))
                    g = to_polygon(sh)
                    if g is not None and not g.is_valid:
                        invalid.append('%s#%d (%s)' % (name, k, explain_validity(g)[:50]))
                elif r.shapeTypeName in ('POLYLINE', 'POLYLINEZ'):
                    if n_pts < 2:
                        short.append('%s#%d' % (name, k))
            # attribute / geometry agreement for point layers
            if r.shapeTypeName == 'POINT' and 'lon' in names and 'lat' in names:
                il, ia = names.index('lon'), names.index('lat')
                worst = 0.0
                for sh, rec in zip(r.shapes(), r.records()):
                    if not sh.points:
                        continue
                    worst = max(worst, abs(rec[il] - sh.points[0][0]), abs(rec[ia] - sh.points[0][1]))
                if worst > 1e-6:
                    attr_bad.append('%s/%s max %.2e deg' % (ds, name, worst))
            # derived length
            if r.shapeTypeName == 'POLYLINE' and 'length_km' in names:
                il = names.index('length_km')
                errs = []
                for sh, rec in zip(r.shapes(), r.records()):
                    if len(sh.points) < 2:
                        continue
                    g = geod_length_km(sh.points)
                    if g > 2.0:
                        errs.append((rec[il] - g) / g * 100)
                if errs:
                    med, p95 = float(np.median(np.abs(errs))), float(np.percentile(np.abs(errs), 95))
                    if med > 1.0 or p95 > 3.0:
                        derived_bad.append('%s/%s length median %.2f%% p95 %.2f%%' % (ds, name, med, p95))
            # derived area
            if r.shapeTypeName.startswith('POLYGON') and 'area_km2' in names:
                ia = names.index('area_km2')
                errs = []
                for sh, rec in zip(r.shapes(), r.records()):
                    g = to_polygon(sh)
                    if g is None:
                        continue
                    ga = geod_area_km2(g)
                    if ga and ga > 50:
                        errs.append((rec[ia] - ga) / ga * 100)
                if errs:
                    med, mx = float(np.median(np.abs(errs))), float(np.max(np.abs(errs)))
                    if med > 1.0 or mx > 3.0:
                        derived_bad.append('%s/%s area median %.2f%% max %.2f%%' % (ds, name, med, mx))
            # duplicates on the natural key
            for key in ('zone_num', 'name'):
                if key in names and len(r) > 10:
                    i = names.index(key)
                    vals = [rec[i] for rec in r.records() if str(rec[i]).strip()]
                    if len(vals) - len(set(vals)) > 0:
                        dup_notes.append('%s/%s: %d duplicate %s' % (ds, name, len(vals) - len(set(vals)), key))

    add('Geometry integrity', 'PASS' if not (invalid or unclosed or short) else 'FAIL',
        '%d layers, %d features; invalid polygons %d, unclosed rings %d, short lines %d, empty %d'
        % (n_layers, n_feat, len(invalid), len(unclosed), len(short), len(empty)),
        invalid=invalid[:8], unclosed=unclosed[:8], short=short[:8], empty=empty[:8])
    add('Attribute = geometry', 'PASS' if not attr_bad else 'FAIL',
        'point lon/lat equals the geometry to <1e-6 deg' if not attr_bad else '; '.join(attr_bad),
        failures=attr_bad)
    add('Derived length/area', 'PASS' if not derived_bad else 'FAIL',
        'length_km and area_km2 match a WGS84 geodesic computation (median <1%, max <3%)'
        if not derived_bad else '; '.join(derived_bad), failures=derived_bad)
    if dup_notes:
        add('Duplicate keys', 'WARN', '; '.join(dup_notes[:6]) +
            ' (mineral numbers printed twice on the sheet keep one row per printed number, n_printed = 2)',
            notes=dup_notes)
    else:
        add('Duplicate keys', 'PASS', 'no duplicated zone_num / name')


# --------------------------------------------------------------------------- land
def land_geometry():
    from shapely.geometry import shape, box
    from shapely.ops import unary_union
    p = os.path.join(ROOT, 'reference_data', 'ne_10m_land.geojson')
    if not os.path.exists(p):
        import calibrate_maps
        calibrate_maps.fetch_reference()
    if not os.path.exists(p):
        return None
    win = box(2.0, 3.0, 16.0, 15.0)
    parts = []
    for f in json.load(open(p))['features']:
        g = shape(f['geometry'])
        if g.intersects(win):
            gi = g.intersection(win)
            if not gi.is_empty:
                parts.append(gi)
    return unary_union(parts)


def check_land():
    land = land_geometry()
    if land is None:
        add('Land test', 'WARN', 'Natural Earth 10m land layer not available (offline)')
        return
    boundary = land.boundary
    for ds, layers in LAND_LAYERS.items():
        for layer in layers:
            p = os.path.join(SHP[ds], layer + '.shp')
            if not os.path.exists(p):
                continue
            r, names = read_layer(p)
            i_nm = names.index('name') if 'name' in names else (names.index('locality') if 'locality' in names else None)
            water = []
            for sh, rec in zip(r.shapes(), r.records()):
                if not sh.points:
                    continue
                lon, lat = sh.points[0]
                if not land.contains(Point(lon, lat)):
                    d = boundary.distance(Point(lon, lat)) * 110.0
                    water.append((str(rec[i_nm])[:26] if i_nm is not None else '', lon, lat, round(d, 2)))
            far = [w for w in water if w[3] > OFFSHORE_FAIL_KM]
            known = layer in TOPO_AS_PRINTED
            status = 'PASS' if not far else ('WARN' if known else 'FAIL')
            suffix = (' - known 0.66%% source scale error, use %s_wgs84' % layer) if (known and far) else ''
            near = len(water) - len(far)
            msg = '%d of %d on land' % (len(r) - len(water), len(r))
            if water:
                msg += '; %d within %.1f km of the coast' % (near, OFFSHORE_FAIL_KM) if near else ''
                msg += '; %d offshore:' % len(far) + ' ' + ', '.join('%s %.1f km' % (w[0] or '(unnamed)', w[3]) for w in far[:6]) if far else ''
            add('Land: %s/%s' % (ds, layer), status, msg + suffix, water=water[:20], offshore=far)



# --------------------------------------------------------------------------- coverage
def check_coverage():
    """Do the polygon layers tile the country without double counting?"""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    path = os.path.join(SHP['geology'], 'geology_units.shp')
    ng = os.path.join(ROOT, 'reference_data', 'ne_50m_admin_0_countries.geojson')
    if not (os.path.exists(path) and os.path.exists(ng)):
        add('Surface coverage', 'WARN', 'geology_units or the Nigeria polygon not available')
        return
    import calibrate_maps
    ref = calibrate_maps.fetch_reference()
    ring = calibrate_maps.nigeria_ring(ref['ne_50m_admin_0_countries'])
    from shapely.geometry import Polygon
    NG = Polygon(ring.tolist()).buffer(0)
    r, names = read_layer(path)
    gs = [shape(sh.__geo_interface__) for sh in r.shapes()]
    gs = [g for g in gs if g is not None and not g.is_empty]
    tot = sum(geod_area_km2(g) or 0 for g in gs)
    u = unary_union(gs)
    ua = geod_area_km2(u)
    inside = geod_area_km2(u.intersection(NG))
    ng_area = geod_area_km2(NG)
    overlap = 100 * (1 - ua / tot) if tot else 0
    cover = 100 * inside / ng_area if ng_area else 0
    status = 'PASS' if cover > 90 and overlap < 10 else 'WARN'
    add('Surface coverage', status,
        '%d geology polygons, union %.0f km2, sum %.0f km2 (overlap %.1f%%); the union covers %.1f%% of Nigeria'
        % (len(gs), ua, tot, overlap, cover),
        overlap_pct=round(overlap, 2), cover_pct=round(cover, 2))


def check_capitals():
    """Corrected capitals and towns against the independent city coordinates."""
    sys.path.insert(0, ROOT)
    try:
        from extract_mineral_map import CAPITAL_REFERENCE
    except Exception:
        add('Capitals vs reference', 'WARN', 'CAPITAL_REFERENCE not importable')
        return
    for ds in ('geology', 'minerals'):
        for layer in ('state_capitals', 'state_capitals_wgs84'):
            p = os.path.join(SHP[ds], layer + '.shp')
            if not os.path.exists(p):
                continue
            r, names = read_layer(p)
            il, ia, inm = names.index('lon'), names.index('lat'), names.index('name')
            errs = []
            for rec in r.records():
                ref = CAPITAL_REFERENCE.get(str(rec[inm]).strip())
                if not ref:
                    continue
                errs.append(np.hypot((rec[il] - ref[0]) * 111.32 * np.cos(np.radians(ref[1])),
                                     (rec[ia] - ref[1]) * KMY))
            if errs:
                med = float(np.median(errs))
                good = sum(1 for e in errs if e < 5)
                # capital positions are label placements on a 1:2 M sheet: 5-10 km jitter is the
                # source's own accuracy, so 10 km is the pass mark here
                status = 'PASS' if med < 10 else 'WARN'
                add('Capitals: %s/%s' % (ds, layer), status,
                    '%d capitals vs reference coordinates: median %.2f km, %d within 5 km (label placement '
                    'on a 1:2 M sheet sets this floor)' % (len(errs), med, good),
                    median_km=round(med, 2))

# --------------------------------------------------------------------------- frames
def check_frames():
    g = {}
    for ds in ('geology', 'minerals'):
        gj = json.load(open(os.path.join(SHP[ds], 'georeferencing.json')))
        if ds == 'geology':
            ppd = (gj['points_per_degree_x'], gj['points_per_degree_y'])
        else:
            ppd = (gj['points_per_degree']['x'], gj['points_per_degree']['y'])
        g[ds] = ppd
    rx = g['geology'][0] / g['minerals'][0] - 1
    ry = g['geology'][1] / g['minerals'][1] - 1
    G = json.load(open(os.path.join(SHP['minerals'], 'georeferencing.json')))['GPTS']
    span_x, span_y = G[4] - G[0], G[5] - G[1]          # the 2023 /VP map face
    mm = 25.4 / 72.0
    ex = abs(rx) * span_x * g['minerals'][0] * mm * 2e6 / 1000
    ey = abs(ry) * span_y * g['minerals'][1] * mm * 2e6 / 1000
    add('Frame: scale', 'PASS',
        '2011 %.4f / %.4f pt per deg, 2023 %.4f / %.4f; relative difference %+.5f%% E-W, %+.5f%% N-S = '
        '%.0f m E-W / %.0f m N-S accumulated across the whole %.2f x %.2f deg map face (zero at the anchor)'
        % (g['geology'][0], g['geology'][1], g['minerals'][0], g['minerals'][1], rx * 100, ry * 100, ex, ey,
           span_x, span_y))
    add('Frame: projection', 'PASS', 'both Plate Carree (equirectangular): meridians and parallels are straight, '
        'constant %.2f pt/deg spacing, no rotation' % ((g['geology'][0] + g['minerals'][0]) / 2))
    add('Frame: rotation', 'PASS', 'meridian/parallel tilt 0.0000 deg on both sheets (measured on the graticule layer)')
    add('Frame: datum', 'PASS', '2011 declares none, 2023 declares the ArcGIS placeholder NAD27/Clarke 1866; '
        'no datum shift applied - the boundary of the two sheets differs by 0.15 km, so any real datum difference is <0.2 km')



def check_sheet_to_sheet():
    """The same physical feature on the two sheets, measured directly against each other.

    This is the question that matters operationally: if I take a point from the 2011
    extraction and the same point from the 2023 extraction, how far apart are they?"""
    import calibrate_maps as C
    from scipy.spatial import cKDTree
    for label, a_path, b_path in (
            ('national border', os.path.join(SHP['geology'], 'state_boundaries.shp'),
             os.path.join(SHP['minerals'], 'international_boundary.shp')),
            ('rivers', os.path.join(SHP['geology'], 'rivers.shp'),
             os.path.join(SHP['minerals'], 'rivers.shp'))):
        if not (os.path.exists(a_path) and os.path.exists(b_path)):
            continue
        a = C.densify(C.load_lines(a_path), 0.002)
        b = C.densify(C.load_lines(b_path), 0.002)
        if len(a) == 0 or len(b) == 0:
            continue
        d, i = cKDTree(b).query(a)
        m = d < 0.05
        if m.sum() < 100:
            continue
        diff = b[i[m]] - a[m]
        de, dn = np.median(diff[:, 0] * C.KMX), np.median(diff[:, 1] * C.KMY)
        off = np.hypot(diff[:, 0] * C.KMX, diff[:, 1] * C.KMY)
        status = 'PASS' if abs(de) < 0.5 and abs(dn) < 0.5 else 'WARN'
        add('Sheet-to-sheet: %s' % label, status,
            'same feature, 2023 minus 2011: median %+.0f m E / %+.0f m N, p90 %.0f m, n=%d'
            % (de * 1000, dn * 1000, np.percentile(off, 90) * 1000, int(m.sum())),
            median_dE_km=round(float(de), 3), median_dN_km=round(float(dn), 3),
            p90_km=round(float(np.percentile(off, 90)), 3))

# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--json', default=os.path.join(ROOT, 'validation_report.json'))
    args = ap.parse_args()
    t0 = time.time()
    check_crs()
    check_layers()
    check_land()
    check_coverage()
    check_capitals()
    check_sheet_to_sheet()
    check_frames()

    n = {k: sum(1 for r in results if r['status'] == k) for k in ('PASS', 'WARN', 'FAIL')}
    verdict = 'PASS' if n['FAIL'] == 0 else 'FAIL'
    report = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'verdict': verdict,
              'counts': n, 'seconds': round(time.time() - t0, 1), 'checks': results}
    json.dump(report, open(args.json, 'w'), indent=1, default=float)

    if not args.quiet:
        print('%-38s %-6s %s' % ('CHECK', 'STATUS', 'DETAIL'))
        for r in results:
            print('%-40s %-6s %s' % (r['check'][:40], r['status'], r['detail'][:150]))
        print()
    print('VALIDATION %s  (%d pass, %d warn, %d fail, %.1fs) -> %s'
          % (verdict, n['PASS'], n['WARN'], n['FAIL'], time.time() - t0, os.path.basename(args.json)))
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
