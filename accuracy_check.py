#!/usr/bin/env python3
"""
Independent accuracy check of the two georeferenced map datasets.

Everything in this file is measured against *external* coordinates, i.e. data
that did not come from either PDF:

  * Natural Earth 1:10m populated places   (github.com/nvkelso/natural-earth-vector)
  * Natural Earth 1:10m rivers              (idem)
  * Natural Earth 1:50m admin boundary      (idem)
  * English Wikipedia coordinates           (action=query&prop=coordinates)

It answers three questions:

  1. are the *coordinates* in the datasets on the true WGS84 graticule
     (hydrography, national boundary)?
  2. are the topographic symbols (towns, roads, capitals) on the same graticule?
  3. how large is the residual, and is there a systematic field left?

Usage
-----
    python3 accuracy_check.py                # measure, print, write accuracy_report.json
    python3 accuracy_check.py --true-csv     # also write <dataset>/towns_true_wgs84.csv

The report is deliberately conservative: it reports medians, 90th percentiles
and the fraction of points inside 5 km, because a single number would hide the
spread that the source cartography actually has.
"""
import argparse
import csv
import glob
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(ROOT, 'reference_data')
SHP = {'geology': os.path.join(ROOT, 'shapefiles'), 'minerals': os.path.join(ROOT, 'shapefiles_minerals')}
KMX = 111.32 * np.cos(np.radians(9.0))
KMY = 110.57

# --------------------------------------------------------------------------- external control points
# English Wikipedia coordinates (fetched 2026-10-17 through the MediaWiki API,
# action=query&prop=coordinates).  lat, lon in WGS84 degrees.
WIKIPEDIA = {
    'Aba, Nigeria': (5.11666667, 7.36666667),
    'Nsukka': (6.85666667, 7.39583333),
    'Ogbomosho': (8.13333333, 4.25),
    'Kontagora': (10.403, 5.473),
    'Kaura Namoda': (12.6, 6.58972222),
    'Wukari': (7.85, 9.78333333),
    'Okene': (7.56194444, 6.24111111),
    'Jebba': (9.15388889, 4.81194444),
    'Sapele, Nigeria': (5.9, 5.66666667),
    'Warri': (5.51666667, 5.75),
    'Ogoja': (6.5, 8.66666667),
    'Idah': (7.09777778, 6.74333333),
    'Eket': (4.65, 7.93333333),
    'Iseyin': (7.96666667, 3.6),
    'Iwo, Osun State': (7.63333333, 4.18333333),
    'Ede, Osun State': (7.73888889, 4.43611111),
    'Shaki, Oyo State': (8.66666667, 3.4),
    'Ilaro': (6.89, 3.017),
    'Kabba': (7.83333333, 6.06666667),
    'Keffi': (8.8464, 7.8733),
    'Wudil': (11.81666667, 8.85),
    'Gaya, Nigeria': (11.86805556, 9.01111111),
    'Gumel': (12.62833333, 9.38972222),
    'Azare': (11.67416667, 10.19111111),
    'Nguru, Nigeria': (12.87916667, 10.4525),
    'Dutsin-Ma': (12.455, 7.49138889),
    'Argungu': (12.73333333, 4.51666667),
    'Zungeru': (9.81277778, 6.15583333),
    'Wamba, Nigeria': (8.93333333, 8.6),
    # large cities (state capitals - the sheets place these from the label, not a marker)
    'Lokoja': (7.802, 6.74),
    'Makurdi': (7.733, 8.533),
    'Onitsha': (6.166, 6.783),
    'Kano': (12.002, 8.516),
    'Lagos': (6.455, 3.384),
    'Abuja': (9.06, 7.49),
    'Jos': (9.918, 8.892),
    'Kaduna': (10.523, 7.438),
    'Enugu': (6.441, 7.495),
    'Benin City': (6.335, 5.627),
}


def load_points(ds, layer='towns'):
    import shapefile
    r = shapefile.Reader(os.path.join(SHP[ds], layer))
    fields = [f[0] for f in r.fields[1:]]
    out = []
    for sh, rec in zip(r.shapes(), r.records()):
        d = dict(zip(fields, rec))
        p = sh.points[0] if sh.points else (None, None)
        d['_lon'], d['_lat'] = p
        out.append(d)
    return out


def match_towns(rows, ref, max_km=40):
    """Match each reference place to the town point of the same name nearest to it."""
    named = [r for r in rows if str(r.get('name', '')).strip()]
    by_name = {}
    for r in named:
        by_name.setdefault(str(r['name']).strip().lower(), []).append(r)
    out = []
    for label, (lat, lon) in ref.items():
        base = label.split(',')[0].split(' -')[0].strip().lower()
        cands = by_name.get(base, []) + by_name.get(label.strip().lower(), [])
        if not cands:
            continue
        best = min(cands, key=lambda r: (r['_lon'] - lon) ** 2 + (r['_lat'] - lat) ** 2)
        de = (best['_lon'] - lon) * KMX
        dn = (best['_lat'] - lat) * KMY
        if np.hypot(de, dn) > max_km:
            continue
        out.append({'name': label, 'map_name': best['name'], 'lon': lon, 'lat': lat,
                    'map_lon': best['_lon'], 'map_lat': best['_lat'], 'dE_km': de, 'dN_km': dn})
    return out


def stats(pairs):
    if not pairs:
        return None
    a = np.asarray(pairs, float)
    r = np.hypot(a[:, 0], a[:, 1])
    return {'n': len(a), 'median_dE_km': round(float(np.median(a[:, 0])), 2),
            'median_dN_km': round(float(np.median(a[:, 1])), 2),
            'median_km': round(float(np.median(r)), 2), 'p90_km': round(float(np.percentile(r, 90)), 2),
            'within_5km': int((r < 5).sum()), 'within_2km': int((r < 2).sum())}


# --------------------------------------------------------------------------- Natural Earth helpers
NE_EXTRA = ['ne_10m_rivers_lake_centerlines', 'ne_10m_populated_places', 'ne_10m_land']


def ensure_ne(names):
    """Fetch the extra Natural Earth layers once (GitHub API, else raw URL)."""
    import base64
    import subprocess
    import urllib.request
    os.makedirs(REF_DIR, exist_ok=True)
    repo = 'nvkelso/natural-earth-vector'
    for name in names:
        dst = os.path.join(REF_DIR, name + '.geojson')
        if os.path.exists(dst) and os.path.getsize(dst) > 1000:
            continue
        path = 'geojson/%s.geojson' % name
        try:
            sha = subprocess.check_output(['gh', 'api', 'repos/%s/contents/%s' % (repo, path),
                                           '--jq', '.sha'], stderr=subprocess.DEVNULL).decode().strip()
            blob = subprocess.check_output(['gh', 'api', 'repos/%s/git/blobs/%s' % (repo, sha),
                                            '--jq', '.content'], stderr=subprocess.DEVNULL).decode()
            data = base64.b64decode(blob)
        except Exception:
            url = 'https://raw.githubusercontent.com/%s/master/%s' % (repo, path)
            data = urllib.request.urlopen(url, timeout=180).read()
        open(dst, 'wb').write(data)
        print('fetched', dst)


def ne_features(path):
    ensure_ne([os.path.basename(path)[:-len('.geojson')]])
    d = json.load(open(path))
    return d['features']


def ne_places_ng():
    """Natural Earth 1:10m populated places in Nigeria (independent of Wikipedia)."""
    ensure_ne(['ne_10m_populated_places'])
    p = os.path.join(REF_DIR, 'ne_10m_populated_places.geojson')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p))
    out = {}
    for f in d['features']:
        if (f['properties'].get('ADM0NAME') or '').lower() != 'nigeria':
            continue
        lon, lat = f['geometry']['coordinates'][:2]
        out[f['properties'].get('NAME')] = (lat, lon)
    return out


def corrected_rows(ds):
    path = os.path.join(SHP[ds], 'towns_true_wgs84.csv')
    if not os.path.exists(path):
        return {}
    return {(r['name'] or '').strip().lower(): r for r in csv.DictReader(open(path))}


def towns_after_correction(ref):
    """Median error of the model-corrected town coordinates against an external set."""
    out = {}
    for ds in ('geology', 'minerals'):
        rows = corrected_rows(ds)
        printed, corrected = [], []
        for name, (lat, lon) in ref.items():
            r = rows.get(name.strip().lower())
            if not r:
                continue
            kmx = 111.32 * np.cos(np.radians(lat))
            for key, dst in (('lon_map', printed), ('lon', corrected)):
                pass
            printed.append(float(np.hypot((float(r['lon_map']) - lon) * kmx, (float(r['lat_map']) - lat) * KMY)))
            corrected.append(float(np.hypot((float(r['lon']) - lon) * kmx, (float(r['lat']) - lat) * KMY)))
        if printed:
            out[ds] = {'n': len(printed),
                       'printed_median_km': round(float(np.median(printed)), 2),
                       'printed_p90_km': round(float(np.percentile(printed, 90)), 2),
                       'corrected_median_km': round(float(np.median(corrected)), 2),
                       'corrected_p90_km': round(float(np.percentile(corrected, 90)), 2),
                       'corrected_within5_km': int(sum(1 for v in corrected if v < 5)),
                       'corrected_within10_km': int(sum(1 for v in corrected if v < 10))}
    return out


def ne_rivers_ng(step=0.01):
    pts = []
    for f in ne_features(os.path.join(REF_DIR, 'ne_10m_rivers_lake_centerlines.geojson')):
        g = f['geometry']
        co = g['coordinates']
        lines = [co] if g['type'] == 'LineString' else co
        for ln in lines:
            a = np.asarray(ln, float)
            m = (a[:, 0] > 2.5) & (a[:, 0] < 15.5) & (a[:, 1] > 3.5) & (a[:, 1] < 14.5)
            if m.sum() > 1:
                pts.append(a[m])
    return np.vstack(pts) if pts else np.zeros((0, 2))


def ne_border_ng():
    import sys
    sys.path.insert(0, ROOT)
    import calibrate_maps as C
    ref = C.fetch_reference()
    ring = C.nigeria_ring(ref['ne_50m_admin_0_countries'])
    return C._densify_ring(ring, 0.001)


def nearest_offset(ref, pts, max_km=25):
    from scipy.spatial import cKDTree
    if len(ref) == 0 or len(pts) == 0:
        return None
    d, i = cKDTree(pts).query(ref)
    m = d < max_km / 111.0
    if m.sum() < 20:
        return None
    diff = pts[i[m]] - ref[m]
    return (float(np.median(diff[:, 0] * KMX)), float(np.median(diff[:, 1] * KMY)), int(m.sum()))


# --------------------------------------------------------------------------- topo field
def fit_field(matches, drop=()):
    """dE, dN = affine(lon, lat); returns coefficients and residuals."""
    matches = [m for m in matches if m['name'] not in drop]
    A = np.array([[m['lon'], m['lat'], 1.0] for m in matches])
    bx = np.array([m['dE_km'] for m in matches])
    by = np.array([m['dN_km'] for m in matches])
    cx, *_ = np.linalg.lstsq(A, bx, rcond=None)
    cy, *_ = np.linalg.lstsq(A, by, rcond=None)
    px, py = A @ cx, A @ cy
    return {'dE = a*lon + b*lat + c': [round(float(v), 4) for v in cx],
            'dN = a*lon + b*lat + c': [round(float(v), 4) for v in cy],
            'rms_after_km': [round(float(np.sqrt(((bx - px) ** 2).mean())), 2),
                             round(float(np.sqrt(((by - py) ** 2).mean())), 2)],
            'rms_before_km': [round(float(np.sqrt((bx ** 2).mean())), 2), round(float(np.sqrt((by ** 2).mean())), 2)],
            'n': len(matches), 'excluded': list(drop)}


def field_at(model, lon, lat):
    ax = model['dE = a*lon + b*lat + c']
    ay = model['dN = a*lon + b*lat + c']
    return (ax[0] * lon + ax[1] * lat + ax[2], ay[0] * lon + ay[1] * lat + ay[2])


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--true-csv', action='store_true', help='write <dataset>/towns_true_wgs84.csv')
    args = ap.parse_args()

    report = {'reference': {
        'wikipedia': 'English Wikipedia coordinates (MediaWiki action=query&prop=coordinates), fetched 2026-10-17',
        'natural_earth': 'Natural Earth 1:10m populated places + rivers, 1:50m admin boundary (public domain)',
        'crs': 'EPSG:4326 (WGS84 geographic, degrees)'}}

    # ---- 1. towns vs external coordinates
    all_matches = []
    report['towns'] = {}
    for ds in ('geology', 'minerals'):
        rows = load_points(ds)
        m = match_towns(rows, {k: v for k, v in WIKIPEDIA.items()})
        report['towns'][ds] = {'stats': stats([(x['dE_km'], x['dN_km']) for x in m]), 'points': m}
        all_matches += m
    # a single field fitted on both sheets (they share the topographic overlay)
    model = fit_field(all_matches, drop=('Ogoja',))
    report['topo_field'] = model
    report['topo_field']['description'] = (
        'displacement of the sheets\' topographic overlay (towns, roads, railway, capital symbols) '
        'relative to true WGS84, in km, positive east/north')

    # ---- 1b. the corrected town layers against a second, independent reference set
    places = ne_places_ng()
    if places:
        report['towns_corrected_vs_ne10m'] = towns_after_correction(places)

    # ---- 2. hydrography vs NE 10m
    ne_riv = ne_rivers_ng()
    report['rivers'] = {}
    import sys
    sys.path.insert(0, ROOT)
    import calibrate_maps as C
    for ds in ('geology', 'minerals'):
        L = C.load_lines(os.path.join(SHP[ds], 'rivers.shp'))
        P = C.densify(L, 0.002) if L else np.zeros((0, 2))
        off = nearest_offset(ne_riv, P, max_km=10)
        report['rivers'][ds] = None if off is None else {
            'median_dE_km': round(off[0], 2), 'median_dN_km': round(off[1], 2), 'n': off[2]}

    # ---- 3. national boundary vs NE 50m
    import sys
    sys.path.insert(0, ROOT)
    import calibrate_maps as C
    border = ne_border_ng()
    report['border'] = {}
    for ds, layer in (('geology', 'state_boundaries'), ('minerals', 'international_boundary')):
        L = C.load_lines(os.path.join(SHP[ds], layer + '.shp'))
        P = C.densify(L, 0.002) if L else np.zeros((0, 2))
        if len(P):
            from scipy.spatial import cKDTree
            dist, _ = cKDTree(border).query(P)
            off = nearest_offset(border, P[dist < 0.06], max_km=6)
        else:
            off = None
        report['border'][ds] = None if off is None else {
            'median_dE_km': round(off[0], 2), 'median_dN_km': round(off[1], 2), 'n': off[2]}

    # ---- 4. optional corrected positions
    if args.true_csv:
        import csv
        for ds in ('geology', 'minerals'):
            rows = load_points(ds)
            path = os.path.join(SHP[ds], 'towns_true_wgs84.csv')
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['name', 'kind', 'lon_map', 'lat_map', 'lon', 'lat', 'de_km', 'dn_km'])
                for r in rows:
                    if r['_lon'] is None:
                        continue
                    de = dn = 0.0
                    lon_t, lat_t = r['_lon'], r['_lat']
                    for _ in range(3):       # invert the field: map = true + field(true)
                        de, dn = field_at(model, lon_t, lat_t)
                        lon_t, lat_t = r['_lon'] - de / KMX, r['_lat'] - dn / KMY
                    w.writerow([r.get('name', ''), r.get('kind', ''), '%.6f' % r['_lon'], '%.6f' % r['_lat'],
                                '%.6f' % lon_t, '%.6f' % lat_t, '%.2f' % de, '%.2f' % dn])
            print('wrote', path)

    out = os.path.join(ROOT, 'accuracy_report.json')
    json.dump(report, open(out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != 'towns'}, indent=1))
    for ds in ('geology', 'minerals'):
        print(ds, 'towns:', report['towns'][ds]['stats'])
    if report.get('towns_corrected_vs_ne10m'):
        for ds, v in report['towns_corrected_vs_ne10m'].items():
            print(ds, 'corrected towns vs NE 10m:', v)


if __name__ == '__main__':
    main()
