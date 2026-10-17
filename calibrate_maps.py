#!/usr/bin/env python3
"""
Calibrate the two map datasets against an external reference (Natural Earth 1:50m).

Why
---
The 2011 geological map and the 2023 mineral map were georeferenced independently
(the 2011 page from its graticule, the 2023 page from its GeoPDF /VP viewport).
Both frames are almost the same scale (157.61 vs 157.59 pt/deg), but the *content*
of the 2023 sheet is not in register with its own frame: the raster basemap (and
the linework drawn on top of it) sits several km south of where the frame puts it.
Overlaid on the 2011 map, every 2023 feature therefore appears below the 2011
feature for the same place -- "geology above minerals".

This tool measures each dataset against Natural Earth (national boundary,
coastline) and against the reference city coordinates already used by
extract_mineral_map.py, then writes a calibration file per dataset and (with
--apply) shifts the extracted shapefiles so that both datasets line up with the
reference and with each other.

Reference data
--------------
Natural Earth 1:50m vector, from the public nvkelso/natural-earth-vector
repository (github.com/nvkelso/natural-earth-vector, public domain):
      ne_50m_admin_0_countries.geojson   (Nigeria polygon -> national boundary)
      ne_50m_coastline.geojson           (coastline)
      ne_50m_rivers_lake_centerlines.geojson
      ne_50m_lakes.geojson
The files are downloaded once into reference_data/ (git-ignored) through the
GitHub API when `gh` is available, otherwise with urllib.

Usage
-----
    python calibrate_maps.py --report     # measure only, print the table
    python calibrate_maps.py --write      # write <dataset>/calibration.json
    python calibrate_maps.py --apply      # write + shift the shapefiles in place
    python calibrate_maps.py --apply --force   # re-apply even if already applied
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.request

import numpy as np
import shapefile

ROOT = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(ROOT, 'reference_data')
NE_REPO = 'nvkelso/natural-earth-vector'
NE_FILES = ['ne_50m_admin_0_countries', 'ne_50m_coastline', 'ne_50m_rivers_lake_centerlines', 'ne_50m_lakes']
PDFS = {'geology': glob.glob(os.path.join(ROOT, 'ilide.info-geological-map-of-nigeria*.pdf')),
        'minerals': [os.path.join(ROOT, 'Mineral_Resources_Map_of_Nigeria_2023.pdf')]}
SHP = {'geology': os.path.join(ROOT, 'shapefiles'), 'minerals': os.path.join(ROOT, 'shapefiles_minerals')}

# correction model:  dlat = (A + B*(lat - LAT0)) / KM_PER_DEG   [degrees, north positive]
# The latitude term is what the three independent checks agree on (coastline,
# 2023-vs-2011 linework, capital squares).  Longitude needs no correction: the
# border and the town markers of the 2023 sheet already agree with the 2011 map
# to <1 km, and the raster strips are placed exactly across the frame width
# (a = 1977.5917 pt = frame width), so there is no horizontal registration error.
MODEL = {'A_km': 5.44, 'B_km_per_deg': -0.569, 'lat0': 9.0, 'km_per_deg': 110.57}

# layers that belong to the shifted content of the 2023 sheet (raster basemap and
# everything drawn on top of / traced from it).  The national boundary and the
# town markers are GIS-native in the source document and are already in register.
# layers traced from / placed on the displaced raster basemap
MINERAL_CONTENT_LAYERS = ['rivers', 'roads', 'railway', 'mineral_symbols_raster',
                          'mineral_localities', 'state_capitals']
# text and markers are in register with the 2011 sheet (measured 2023-vs-2011 text: +0.1/+1.1 km):
# map_labels, state_name_labels, river_labels, towns, international_boundary
# feature-level selection for layers that mix raster-derived and text-derived positions
FEATURE_FILTERS = {'mineral_localities': ('pos_src', 'raster symbol'),
                   'state_capitals': ('src', 'raster')}
MINERAL_VERIFIED_CORRECT = ['international_boundary', 'towns', 'map_labels', 'state_name_labels', 'river_labels']

KMX = 111.32 * np.cos(np.radians(9.0))
KMY = 110.57


# --------------------------------------------------------------------------- reference
def fetch_reference(quiet=False):
    """Download the Natural Earth layers into reference_data/ (cached)."""
    os.makedirs(REF_DIR, exist_ok=True)
    for name in NE_FILES:
        dst = os.path.join(REF_DIR, name + '.geojson')
        if os.path.exists(dst) and os.path.getsize(dst) > 1000:
            continue
        path = 'geojson/%s.geojson' % name
        if not quiet:
            print('fetching %s ...' % path, flush=True)
        try:
            sha = subprocess.check_output(['gh', 'api', 'repos/%s/contents/%s' % (NE_REPO, path),
                                           '--jq', '.sha'], stderr=subprocess.DEVNULL).decode().strip()
            blob = subprocess.check_output(['gh', 'api', 'repos/%s/git/blobs/%s' % (NE_REPO, sha),
                                            '--jq', '.content'], stderr=subprocess.DEVNULL).decode()
            import base64
            data = base64.b64decode(blob)
        except Exception:
            url = 'https://raw.githubusercontent.com/%s/master/%s' % (NE_REPO, path)
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
        with open(dst, 'wb') as f:
            f.write(data)
    return {name: os.path.join(REF_DIR, name + '.geojson') for name in NE_FILES}


def _rings(geom):
    if geom['type'] == 'Polygon':
        return geom['coordinates']
    return [r for poly in geom['coordinates'] for r in poly]


def _densify_ring(ring, step=0.002):
    a = np.asarray(ring, float)
    out = []
    for p, q in zip(a[:-1], a[1:]):
        d = np.hypot(*(q - p))
        n = max(1, int(d / step))
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        out.append(p + (q - p) * t)
    return np.vstack(out) if out else np.zeros((0, 2))


def nigeria_ring(path):
    d = json.load(open(path))
    ng = [f for f in d['features'] if f['properties'].get('ADMIN') == 'Nigeria'
          or f['properties'].get('NAME') == 'Nigeria']
    if not ng:
        raise SystemExit('Nigeria not found in %s' % path)
    rings = [np.asarray(r, float) for r in _rings(ng[0]['geometry'])]
    # the mainland ring is the one with the largest extent
    return max(rings, key=lambda r: (r[:, 0].max() - r[:, 0].min()) * (r[:, 1].max() - r[:, 1].min()))


# --------------------------------------------------------------------------- vector helpers
def load_lines(path):
    if not os.path.exists(path):
        return []
    r = shapefile.Reader(path)
    out = []
    for sh in r.shapes():
        p = np.asarray(sh.points, float)
        if sh.parts:
            parts = list(sh.parts) + [len(p)]
            for a, b in zip(parts[:-1], parts[1:]):
                if b - a >= 2:
                    out.append(p[a:b])
        elif len(p) >= 2:
            out.append(p)
    return out


def densify(lines, step=0.002):
    out = []
    for p in lines:
        for a, b in zip(p[:-1], p[1:]):
            d = np.hypot(*(b - a))
            n = max(1, int(np.ceil(d / step)))
            t = np.linspace(0, 1, n, endpoint=False)[:, None]
            out.append(a + (b - a) * t)
        out.append(p[-1:])
    return np.vstack(out) if out else np.zeros((0, 2))


def nearest_offset(ref_pts, ds_pts, max_km=25):
    """median (dE, dN) of ds minus ref for ds points that have a ref point nearby."""
    from scipy.spatial import cKDTree
    if len(ref_pts) == 0 or len(ds_pts) == 0:
        return None
    t = cKDTree(ds_pts)
    d, idx = t.query(ref_pts)
    m = d < max_km / 111.0
    if m.sum() < 20:
        return None
    diff = ds_pts[idx[m]] - ref_pts[m]
    return (float(np.median(diff[:, 0] * KMX)), float(np.median(diff[:, 1] * KMY)), int(m.sum()))


def records(path):
    r = shapefile.Reader(path)
    f = [x[0] for x in r.fields[1:]]
    return [dict(zip(f, rec)) for rec in r.records()]


# --------------------------------------------------------------------------- raster helpers
def _georef(ds):
    g = json.load(open(os.path.join(SHP[ds], 'georeferencing.json')))
    if ds == 'geology':
        return (g['lon = a*x + b']['a'], g['lon = a*x + b']['b'],
                g['lat = c*y + d']['c'], g['lat = c*y + d']['d'])
    (a, b), (c, d) = g['affine']['lon = a*x + b'], g['affine']['lat = c*y + d']
    return a, b, c, d


def render_window(ds, lon0, lon1, lat0, lat1, res=0.002):
    """Render a lon/lat window of the dataset's PDF page through its own georeference."""
    import pymupdf
    a, b, c, d = _georef(ds)
    pdf = PDFS[ds][0] if PDFS[ds] else None
    if not pdf:
        return None
    nx, ny = int((lon1 - lon0) / res), int((lat1 - lat0) / res)
    doc = pymupdf.open(pdf)
    page = doc[0]
    H = page.rect.height
    x0 = (lon0 - b) / a
    y_top = H - (lat1 - d) / c
    pix = page.get_pixmap(matrix=pymupdf.Matrix(a / res, 0, 0, c / res, -x0 * a / res, -y_top * c / res),
                          clip=pymupdf.Rect(x0, y_top, x0 + nx * res / a, y_top + ny * res / c), alpha=False)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
    return arr[:ny, :nx]


def coalesce(mask, bridge_px, min_px=20000):
    """Keep the largest blob; close small gaps (graticule lines, label halos) first."""
    from scipy.ndimage import label, binary_closing
    m = binary_closing(mask, np.ones((bridge_px, bridge_px)))
    lab, _ = label(m)
    if lab.max() == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep = [i for i in range(1, lab.max() + 1) if sizes[i] >= min_px]
    return np.isin(lab, keep) if keep else mask


SEA_RGB = (151, 219, 242)


def coastline_lat(ds, lons, lon0, lon1, lat0, lat1, res=0.002):
    """Latitude of the northern edge of the open sea, per longitude (NaN if no sea)."""
    arr = render_window(ds, lon0, lon1, lat0, lat1, res)
    if arr is None:
        return None
    m = np.abs(arr.astype(int) - np.array(SEA_RGB)[None, None, :]).sum(2) < 45
    # close over the graticule lines with a kernel of ~3 km, whatever the pixel size
    sea = coalesce(m, max(3, int(round(3.0 / 111.0 / res)) | 1))
    out = np.full(len(lons), np.nan)
    for k, lon in enumerate(lons):
        col = int((lon - lon0) / res)
        if not (0 <= col < sea.shape[1]):
            continue
        rows = np.nonzero(sea[:, col])[0]
        if len(rows) < 150:
            continue
        # first row from which the next 0.2 deg are mostly sea (skips 'GULF OF GUINEA')
        span = max(20, int(round(0.2 / res)))
        for r in rows:
            if sea[r:r + span, col].mean() > 0.6:
                out[k] = lat1 - (r + 0.5) * res
                break
    return out


def coastline_from_tiles(ds, lons, lon0, lon1, lat0, lat1):
    """Same coastline measurement, but on the pre-built viewer tiles (i.e. after calibration)."""
    import glob
    from PIL import Image
    tdir = os.path.join(ROOT, 'viewer', 'build', 'tiles' if ds == 'geology' else 'tiles_minerals')
    zs = sorted(int(os.path.basename(p)) for p in glob.glob(os.path.join(tdir, '*')) if os.path.basename(p).isdigit())
    if not zs:
        return None
    z = max(zs)
    n = 2 ** z
    px = 180.0 / n / 256.0
    tx0 = int(np.floor((lon0 / 180 + 1) * n)); tx1 = int(np.floor((lon1 / 180 + 1) * n))
    ty0 = int(np.floor((-lat1 / 180 + 0.5) * n)); ty1 = int(np.floor((-lat0 / 180 + 0.5) * n))
    W = (tx1 - tx0 + 1) * 256; H = (ty1 - ty0 + 1) * 256
    arr = np.full((H, W, 3), 255, np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            p = os.path.join(tdir, str(z), str(tx), '%d.png' % ty)
            if os.path.exists(p):
                im = np.asarray(Image.open(p).convert('RGB'))
                arr[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = im
    lonA = (tx0 / n - 1) * 180
    latA = (0.5 - ty0 / n) * 180
    m = np.abs(arr.astype(int) - np.array(SEA_RGB)[None, None, :]).sum(2) < 45
    sea = coalesce(m, max(3, int(round(3.0 / 111.0 / px)) | 1))
    lats = []
    for lon in lons:
        col = int((lon - lonA) / px)
        if not (0 <= col < sea.shape[1]):
            lats.append(np.nan); continue
        rows = np.nonzero(sea[:, col])[0]
        v = np.nan
        if len(rows) > 20:
            span = max(20, int(round(0.2 / px)))
            for r in rows:
                if sea[r:min(r + span, sea.shape[0]), col].mean() > 0.6:
                    v = latA - (r + 0.5) * px
                    break
        lats.append(v)
    return np.array(lats)


# --------------------------------------------------------------------------- measurements
def measure(datasets=('geology', 'minerals')):
    ref = fetch_reference()
    ring = nigeria_ring(ref['ne_50m_admin_0_countries'])
    border = _densify_ring(ring, 0.001)
    out = {}

    # 1. national boundary (2011: the state-boundary layer contains it; 2023: the international boundary)
    sb = os.path.join(SHP['geology'], 'state_boundaries.shp')
    near = densify(load_lines(sb), 0.002)
    from scipy.spatial import cKDTree
    d, _ = cKDTree(border).query(near)
    out['geology_border_km'] = nearest_offset(border, near[d < 0.06])
    out['minerals_border_km'] = nearest_offset(
        border, np.vstack(load_lines(os.path.join(SHP['minerals'], 'international_boundary.shp'))))

    # 2. coastline (raster sea edge) - the coastline exists only as imagery, so this
    #    measures the *picture*, not the extracted vectors
    lons = np.arange(3.0, 8.51, 0.25)
    lon0, lon1, lat0, lat1 = 2.6, 8.9, 3.7, 6.8
    # reference: latitude where the NE polygon ends (southernmost land) per longitude
    xs = lon0 + (np.arange(int((lon1 - lon0) / 0.002)) + 0.5) * 0.002
    ne_lat = np.full(len(xs), np.nan)
    for i, lon in enumerate(xs):
        cr = []
        for p, q in zip(ring[:-1], ring[1:]):
            if (p[0] - lon) * (q[0] - lon) <= 0 and p[0] != q[0]:
                t = (lon - p[0]) / (q[0] - p[0])
                v = p[1] + t * (q[1] - p[1])
                if v < 7.5:
                    cr.append(v)
        if cr:
            ne_lat[i] = min(cr)
    for ds in datasets:
        lat = coastline_lat(ds, lons, lon0, lon1, lat0, lat1)
        if lat is None:
            continue
        diffs = []
        for k, lon in enumerate(lons):
            i = int((lon - lon0) / 0.002)
            if 0 <= i < len(ne_lat) and np.isfinite(lat[k]) and np.isfinite(ne_lat[i]):
                diffs.append((lat[k] - ne_lat[i]) * KMY)
        out[ds + '_coast_km'] = (float(np.median(diffs)), len(diffs)) if diffs else None

    # 3. capitals against the reference coordinates shipped with the extractor
    sys.path.insert(0, ROOT)
    from extract_mineral_map import CAPITAL_REFERENCE
    for ds, fn in (('geology', 'state_capitals'), ('minerals', 'state_capitals')):
        rows = records(os.path.join(SHP[ds], fn + '.shp'))
        de, dn = [], []
        for r in rows:
            ref_ll = CAPITAL_REFERENCE.get(str(r.get('name', '')).strip())
            if not ref_ll:
                continue
            de.append((r['lon'] - ref_ll[0]) * KMX * np.cos(np.radians(ref_ll[1])) / np.cos(np.radians(9)))
            dn.append((r['lat'] - ref_ll[1]) * KMY)
        if de:
            out[ds + '_capitals_km'] = (float(np.median(de)), float(np.median(dn)), len(de))

    # 4. 2023 linework against the 2011 linework (tile medians; catches the offset field)
    if os.path.exists(os.path.join(SHP['minerals'], 'rivers.shp')):
        out['minerals_vs_geology_linework_km'] = linework_offset()

    # 5. towns 2023 vs 2011 (both are GIS-native in the source documents -> must stay ~0)
    if os.path.exists(os.path.join(SHP['minerals'], 'towns.shp')):
        out['towns_2023_minus_2011_km'] = towns_offset()
    return out


def linework_offset():
    """Median (dE, dN) of the 2023 rivers+roads+railway relative to the 2011 ones."""
    from scipy.ndimage import distance_transform_edt
    res = 0.0025

    def raster(lines, x0, y0, nx, ny):
        g = np.zeros((ny, nx), bool)
        for p in lines:
            for a, b in zip(p[:-1], p[1:]):
                d = np.hypot(*(b - a))
                n = max(1, int(np.ceil(d / (res / 2))))
                t = np.linspace(0, 1, n, endpoint=False)[:, None]
                q = a + (b - a) * t
                ix = ((q[:, 0] - x0) / res).astype(int)
                iy = ((q[:, 1] - y0) / res).astype(int)
                ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
                g[iy[ok], ix[ok]] = True
        return g

    G = load_lines(os.path.join(SHP['geology'], 'rivers.shp')) + \
        load_lines(os.path.join(SHP['geology'], 'roads.shp')) + \
        load_lines(os.path.join(SHP['geology'], 'railway.shp'))
    M = load_lines(os.path.join(SHP['minerals'], 'rivers.shp')) + \
        load_lines(os.path.join(SHP['minerals'], 'roads.shp')) + \
        load_lines(os.path.join(SHP['minerals'], 'railway.shp'))
    tiles = []
    for ty in np.arange(5, 13, 1.0):
        for tx in np.arange(3, 14, 1.0):
            def clip(P):
                return [p for p in P if tx - 0.15 <= p[:, 0].min() and p[:, 0].max() < tx + 1.15
                        and ty - 0.15 <= p[:, 1].min() and p[:, 1].max() < ty + 1.15]
            A, B = clip(G), clip(M)
            if not A or not B:
                continue
            x0, y0 = tx - 0.15, ty - 0.15
            nx, ny = int(1.3 / res), int(1.3 / res)
            gA, gB = raster(A, x0, y0, nx, ny), raster(B, x0, y0, nx, ny)
            if gA.sum() < 40 or gB.sum() < 40:
                continue
            dA = distance_transform_edt(~gA) * res * (KMX + KMY) / 2
            pts = np.argwhere(gB)
            if len(pts) > 4000:
                pts = pts[np.random.default_rng(0).choice(len(pts), 4000, replace=False)]
            best = None
            for dy in np.arange(-12, 12.01, 1.0):
                for dx in np.arange(-12, 12.01, 1.0):
                    ix = np.clip((pts[:, 1] + dx / (res * KMX)).astype(int), 0, nx - 1)
                    iy = np.clip((pts[:, 0] - dy / (res * KMY)).astype(int), 0, ny - 1)
                    s = dA[iy, ix].mean()
                    if best is None or s < best[0]:
                        best = (s, dx, dy)
            tiles.append((tx + 0.5, ty + 0.5, best[1], best[2]))
    T = np.array(tiles)
    if len(T) == 0:
        return None
    return (float(np.median(T[:, 2])), float(np.median(T[:, 3])), len(T))


def towns_offset():
    a = {str(r.get('name', '')).strip(): (r['lon'], r['lat'])
         for r in records(os.path.join(SHP['geology'], 'towns.shp')) if str(r.get('name', '')).strip()}
    b = {str(r.get('name', '')).strip(): (r['lon'], r['lat'])
         for r in records(os.path.join(SHP['minerals'], 'towns.shp')) if str(r.get('name', '')).strip()}
    de, dn = [], []
    for n in set(a) & set(b):
        dx = (b[n][0] - a[n][0]) * KMX
        dy = (b[n][1] - a[n][1]) * KMY
        if abs(dx) < 40 and abs(dy) < 40:
            de.append(dx)
            dn.append(dy)
    if not de:
        return None
    return (float(np.median(de)), float(np.median(dn)), len(de))


# --------------------------------------------------------------------------- calibration
def dlat_deg(lat):
    return (MODEL['A_km'] + MODEL['B_km_per_deg'] * (np.asarray(lat, float) - MODEL['lat0'])) / MODEL['km_per_deg']


def write_calibration(meas, datasets=('geology', 'minerals')):
    for ds in datasets:
        d = os.path.join(SHP[ds])
        if not os.path.isdir(d):
            continue
        prev = {}
        if os.path.exists(os.path.join(d, 'calibration.json')):
            prev = json.load(open(os.path.join(d, 'calibration.json')))
        applied = ds == 'geology' or bool(prev.get('applied'))   # the 2011 sheet needs no correction
        extracted = ({'measured_as_extracted': prev['measured_as_extracted']}
                     if prev.get('applied') and 'measured_as_extracted' in prev
                     else {'measured_as_extracted': {k: v for k, v in meas.items() if k.startswith(ds) or
                                                     (ds == 'minerals' and k in ('minerals_vs_geology_linework_km',
                                                                                 'towns_2023_minus_2011_km'))}})
        georef = json.load(open(os.path.join(d, 'georeferencing.json')))
        if ds == 'geology':
            crs_block = {
                'output': 'EPSG:4326',
                'output_datum': 'WGS84',
                'input_declared': None,
                'input_georeference': 'fitted printed graticule (12 meridians, 10 parallels); the PDF has no /VP, /LGIDict or /Measure object and no projection statement',
                'input_units': 'degrees',
                'points_per_degree': [round(georef['points_per_degree_x'], 4), round(georef['points_per_degree_y'], 4)],
                'fit_max_residual_deg': georef.get('max_residual_deg'),
                'datum_shift_applied': 'none',
                'note': ('No CRS object is embedded.  The graticule fit is the georeference; its values are treated as '
                         'WGS84 degrees.  If the printed graticule was on the Minna datum (Clarke 1880), the WGS84 '
                         'difference is ~0.1-0.2 km, below the ~1 km accuracy of the sheet.'),
            }
        else:
            crs_block = {
                'output': 'EPSG:4326',
                'output_datum': 'WGS84',
                'input_declared': 'GCS_Assumed_Geographic_1 / D_North_American_1927 / Clarke_1866 (GeoPDF /VP /Measure /GCS)',
                'input_georeference': 'GeoPDF /VP /Measure: 4 corner GPTS + LPTS, Plate Carree data frame',
                'input_bounds_deg': [georef['GPTS'][0], georef['GPTS'][1], georef['GPTS'][4], georef['GPTS'][5]],
                'input_units': 'degrees',
                'points_per_degree': [round(georef['points_per_degree']['x'], 4), round(georef['points_per_degree']['y'], 4)],
                'datum_shift_applied': 'none',
                'note': ('The declared GCS is the ArcGIS "assumed geographic" placeholder (it even names NAD27, a North '
                         'American datum).  The degrees it carries are the map graticule and are WGS84-consistent: the '
                         'national boundary agrees with Natural Earth to +0.25/+0.04 km and the rivers to -0.9/+0.5 km.  '
                         'A literal NAD27->WGS84 transform would be wrong here (NAD27 is not defined in Nigeria).  '
                         'The printed meridian labels sit 0.172 deg west of the /VP graticule lines; the /VP values are '
                         'used (the labels are a typographic offset, and the /VP choice is confirmed by the two checks above).'),
            }
        cal = {
            'crs': crs_block,
            'reference': {
                'source': 'Natural Earth 1:50m (public domain), github.com/%s' % NE_REPO,
                'features': ['national boundary (ne_50m_admin_0_countries)',
                             'coastline / sea edge (raster of the map sheet)',
                             'city coordinates (CAPITAL_REFERENCE in extract_mineral_map.py)'],
            },
            **extracted,
            'model': dict(MODEL, note='dlat = (A + B*(lat-lat0)) / km_per_deg degrees, north positive; dlon = 0'),
            'applied': applied,
        }
        if prev.get('verified_after'):
            cal['verified_after'] = prev['verified_after']
        if prev.get('topographic_overlay'):
            cal['topographic_overlay'] = prev['topographic_overlay']
        if ds == 'minerals':
            cal['layers_corrected'] = MINERAL_CONTENT_LAYERS
            cal['layers_verified_correct'] = MINERAL_VERIFIED_CORRECT
            cal['notes'] = [
                'The 2023 sheet is a GeoPDF whose raster basemap (and the rivers/roads/railway/symbols',
                'drawn over it) is out of register with its own /VP frame by several km, while its text',
                '(towns, states, river names, mineral numbers), the national boundary and the town',
                'markers are in register -- text-to-text against the 2011 sheet: +0.1 km E, +1.1 km N.',
                'The 2011 sheet agrees with Natural Earth to ~1 km everywhere, so only the raster-derived',
                'content of the 2023 sheet is corrected.  Measured against NE: 2023 coastline 7.6 km south',
                '(2011: 0.4 km), capitals 6.8 km south (2011: 1.0 km), linework 5.0 km south of 2011.',
            ]
        else:
            cal['layers_corrected'] = []
            cal['layers_verified_correct'] = ['all']
            cal['notes'] = ['The 2011 geological sheet agrees with Natural Earth to ~1 km',
                            '(border +0.1/-0.0 km, coastline -0.4 km): no correction applied.']
        out = os.path.join(d, 'calibration.json')
        with open(out, 'w') as f:
            json.dump(cal, f, indent=1)
        print('wrote %s (applied=%s)' % (out, applied))


# --------------------------------------------------------------------------- apply
def apply_shift_to_shapefiles(ds):
    """Shift every layer listed as content by the model, in place."""
    from shapefile import Reader, Writer
    d = os.path.join(SHP[ds])
    cal = json.load(open(os.path.join(d, 'calibration.json')))
    if cal.get('applied') and not APPLY_FORCE:
        print('%s: calibration already applied (use --force to re-apply)' % ds)
        return 0
    n = 0
    for name in cal.get('layers_corrected', []):
        src = os.path.join(d, name + '.shp')
        if not os.path.exists(src):
            print('  %-24s missing, skipped' % name)
            continue
        r = Reader(src)
        tmp = src[:-4] + '.cal.shp'
        w = Writer(tmp, shapeType=r.shapeType)
        for f in r.fields[1:]:
            w.field(*f)
        lat_fields = [i for i, f in enumerate(r.fields[1:])
                      if f[0] in ('lat', 'label_lat', 'mid_lat', 'start_lat', 'end_lat')]
        filt = None
        if name in FEATURE_FILTERS:
            col, needle = FEATURE_FILTERS[name]
            cols = [f[0] for f in r.fields[1:]]
            if col in cols:
                fi = cols.index(col)
                filt = (fi, needle)
        n_shift = n_keep = 0
        for sr in r.iterShapeRecords():
            sh = sr.shape
            pts = np.asarray(sh.points, float)
            rec = list(sr.record)
            if filt is None or filt[1] in str(rec[filt[0]]):
                pts[:, 1] += dlat_deg(pts[:, 1])
                for i in lat_fields:      # keep the mirrored lat attributes in step
                    if isinstance(rec[i], (int, float)):
                        rec[i] = rec[i] + float(dlat_deg(rec[i]))
                n_shift += 1
            else:
                n_keep += 1
            sh.points = pts.tolist()
            w.shape(sh)
            w.record(*rec)
        w.close()
        r.close()
        for ext in ['.shp', '.shx', '.dbf']:
            os.replace(tmp[:-4] + ext, src[:-4] + ext)
        for ext in ['.prj', '.cpg']:
            if os.path.exists(src[:-4] + ext) and os.path.exists(tmp[:-4] + ext):
                os.remove(tmp[:-4] + ext)
        n += 1
        extra = ' (%d of %d features; %d text-derived left in place)' % (n_shift, n_shift + n_keep, n_keep) if filt else ''
        print('  shifted %s%s' % (name, extra))
    cal['applied'] = True
    with open(os.path.join(d, 'calibration.json'), 'w') as f:
        json.dump(cal, f, indent=1)
    return n


def apply_shift_to_csv(ds):
    """Shift the latitude columns of the per-locality CSV exports, if present."""
    import csv
    d = os.path.join(SHP[ds])
    targets = {'mineral_localities.csv': ('lat', 'label_lat', ('pos_src', 'position_source', 'raster symbol')),
               'symbol_identification.csv': ('lat', None)}
    n = 0
    for fn, (cols, filt) in targets.items():
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        with open(p, newline='') as f:
            rows = list(csv.DictReader(f))
            fields = rows[0].keys() if rows else []
        if not rows or not any(c in fields for c in cols):
            continue
        filt_col = None
        if filt:
            names, needle = filt[0], filt[1]
            filt_col = next((c for c in names if c in fields), None)
            if filt_col is None:
                print('  WARNING: %s has no %s column - shifting every row' % (fn, '/'.join(names)))
        for r in rows:
            # per-feature filter, exactly as apply_shift_to_shapefiles() does it
            if filt_col and needle not in str(r.get(filt_col, '')):
                continue
            for c in cols:
                if r.get(c):
                    try:
                        r[c] = '%.6f' % (float(r[c]) + float(dlat_deg(float(r[c]))))
                    except ValueError:
                        pass
        with open(p, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            w.writerows(rows)
        n += 1
        print('  shifted %s' % fn)
    return n


def apply_dataset(ds, force=False, quiet=False):
    """Shift the calibrated layers (shapefiles + CSV exports) of one dataset."""
    global APPLY_FORCE
    if force:
        APPLY_FORCE = True
    cal_p = os.path.join(SHP[ds], 'calibration.json')
    if not os.path.exists(cal_p):
        if not quiet:
            print('%s: no calibration.json - run "calibrate_maps.py --write" first' % ds)
        return 0
    n = apply_shift_to_shapefiles(ds) + apply_shift_to_csv(ds)
    return n


# --------------------------------------------------------------------------- main
APPLY_FORCE = False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--report', action='store_true', help='measure and print (default)')
    ap.add_argument('--write', action='store_true', help='write <dataset>/calibration.json')
    ap.add_argument('--apply', action='store_true', help='write and shift the shapefiles in place')
    ap.add_argument('--force', action='store_true', help='re-apply even if calibration.json says applied')
    ap.add_argument('--verify', action='store_true',
                    help='measure the calibrated output (shapefiles + viewer tiles) and record it')
    ap.add_argument('--dataset', choices=['geology', 'minerals', 'all'], default='all')
    args = ap.parse_args()
    global APPLY_FORCE
    APPLY_FORCE = args.force
    datasets = ('geology', 'minerals') if args.dataset == 'all' else (args.dataset,)

    meas = measure(datasets)

    print('\nmeasurements against Natural Earth 1:50m')
    print('  %-42s %s' % ('2011 border (state boundaries)  dE/dN km', _fmt(meas.get('geology_border_km'))))
    print('  %-42s %s' % ('2011 coastline (raster, median N-S km)', _fmt(meas.get('geology_coast_km'))))
    print('  %-42s %s' % ('2011 capitals vs city coordinates', _fmt(meas.get('geology_capitals_km'))))
    print('  %-42s %s' % ('2023 border (international boundary)', _fmt(meas.get('minerals_border_km'))))
    print('  %-42s %s' % ('2023 coastline (raster, median N-S km)', _fmt(meas.get('minerals_coast_km'))))
    print('  %-42s %s' % ('2023 capitals vs city coordinates', _fmt(meas.get('minerals_capitals_km'))))
    print('  %-42s %s' % ('2023 linework minus 2011 linework', _fmt(meas.get('minerals_vs_geology_linework_km'))))
    print('  %-42s %s' % ('2023 towns minus 2011 towns', _fmt(meas.get('towns_2023_minus_2011_km'))))
    print('\ncorrection model (2023 content):  dlat = (%.2f %+.3f*(lat-%.0f)) / %.2f  degrees'
          % (MODEL['A_km'], MODEL['B_km_per_deg'], MODEL['lat0'], MODEL['km_per_deg']))
    for lat in (4.5, 9.0, 13.0):
        print('    at lat %4.1f -> %+5.2f km north' % (lat, dlat_deg(lat) * MODEL['km_per_deg']))

    if args.verify:
        v = verify(datasets)
        print('\ncalibrated output (shapefiles + viewer tiles)')
        for k, val in v.items():
            print('  %-42s %s' % (k.replace('_', ' '), _fmt(val)))
    if args.write or args.apply:
        write_calibration(meas, datasets)
    if args.apply:
        for ds in datasets:
            n = apply_shift_to_shapefiles(ds) + apply_shift_to_csv(ds)
            print('%s: %d layers/files shifted' % (ds, n))


def verify(datasets):
    """Measure the calibrated output: shapefiles (vectors) and the viewer tiles (raster)."""
    ref = fetch_reference()
    ring = nigeria_ring(ref['ne_50m_admin_0_countries'])
    lons = np.arange(3.0, 8.51, 0.25)
    lon0, lon1, lat0, lat1 = 2.6, 8.9, 3.7, 6.8
    xs = lon0 + (np.arange(int((lon1 - lon0) / 0.002)) + 0.5) * 0.002
    ne_lat = np.full(len(xs), np.nan)
    for i, lon in enumerate(xs):
        cr = []
        for p, q in zip(ring[:-1], ring[1:]):
            if (p[0] - lon) * (q[0] - lon) <= 0 and p[0] != q[0]:
                t = (lon - p[0]) / (q[0] - p[0])
                v = p[1] + t * (q[1] - p[1])
                if v < 7.5:
                    cr.append(v)
        if cr:
            ne_lat[i] = min(cr)
    out = {}
    for ds in datasets:
        lat = coastline_from_tiles(ds, lons, lon0, lon1, lat0, lat1)
        if lat is None:
            continue
        diffs = [(lat[k] - ne_lat[int((lon - lon0) / 0.002)]) * KMY
                 for k, lon in enumerate(lons)
                 if np.isfinite(lat[k]) and np.isfinite(ne_lat[int((lon - lon0) / 0.002)])]
        out[ds + '_coast_tiles_km'] = (float(np.median(diffs)), len(diffs)) if diffs else None
    if os.path.exists(os.path.join(SHP['minerals'], 'rivers.shp')):
        out['minerals_vs_geology_linework_km'] = linework_offset()
    if os.path.exists(os.path.join(SHP['minerals'], 'towns.shp')):
        out['towns_2023_minus_2011_km'] = towns_offset()
    sys.path.insert(0, ROOT)
    from extract_mineral_map import CAPITAL_REFERENCE
    rows = records(os.path.join(SHP['minerals'], 'state_capitals.shp'))
    de, dn = [], []
    for r in rows:
        ref_ll = CAPITAL_REFERENCE.get(str(r.get('name', '')).strip())
        if ref_ll:
            de.append((r['lon'] - ref_ll[0]) * KMX * np.cos(np.radians(ref_ll[1])) / np.cos(np.radians(9)))
            dn.append((r['lat'] - ref_ll[1]) * KMY)
    if de:
        out['minerals_capitals_km'] = (float(np.median(de)), float(np.median(dn)), len(de))
    # record it next to the model
    p = os.path.join(SHP['minerals'], 'calibration.json')
    if os.path.exists(p):
        cal = json.load(open(p))
        cal['verified_after'] = {k: v for k, v in out.items()}
        with open(p, 'w') as f:
            json.dump(cal, f, indent=1)
        print('recorded verified_after in %s' % p)
    return out


def _fmt(v):
    if v is None:
        return '-'
    if len(v) == 2:
        return 'median %+.2f km (n=%d)' % (v[0], v[1])
    return 'dE %+.2f  dN %+.2f km (n=%d)' % (v[0], v[1], v[2])


if __name__ == '__main__':
    main()
