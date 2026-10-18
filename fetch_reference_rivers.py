#!/usr/bin/env python3
"""Fetch an independent river network to test the two sheets against.

Primary source: **WDBII** (CIA World Data Bank II), the river layer shipped with
matplotlib-basemap (`basemap-data`, derived from GSHHG/WDBII, LGPL-3.0-or-later).
It is a 1:1M-1:3M compilation digitised from aviation/navigation charts, produced
completely independently of both Nigerian map sheets and of Natural Earth.

Secondary source: **Natural Earth 10m rivers** (`ne_10m_rivers_lake_centerlines`,
public domain), used as a cross-check and for the figures.

Neither source was used when the sheets were calibrated, so agreement with them is
independent evidence.  Output goes to reference_data/, which is git-ignored (cached,
re-fetched on demand) - same convention as the Natural Earth downloads in
calibrate_maps.py.

    python3 fetch_reference_rivers.py
"""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'reference_data')
BOX = (1.0, 2.0, 16.0, 15.0)          # lon_min, lat_min, lon_max, lat_max


def wdbii():
    """Extract the WDBII river vertices inside the Nigeria window from basemap-data."""
    tmp = tempfile.mkdtemp()
    res = None
    for pkg in ('basemap-data-hires', 'basemap-data'):
        print('downloading %s ...' % pkg)
        subprocess.check_call([sys.executable, '-m', 'pip', 'download', pkg,
                               '--no-deps', '-q', '-d', tmp])
    wheels = sorted((f for f in os.listdir(tmp) if f.endswith('.whl')),
                    key=lambda f: (0 if 'hires' in f else 1, f))
    for f in wheels:
        with zipfile.ZipFile(os.path.join(tmp, f)) as z:
            names = z.namelist()
            for r in ('f', 'h', 'i', 'l'):
                if 'mpl_toolkits/basemap_data/rivers_%s.dat' % r in names:
                    res = r
                    z.extract('mpl_toolkits/basemap_data/riversmeta_%s.dat' % r, tmp)
                    z.extract('mpl_toolkits/basemap_data/rivers_%s.dat' % r, tmp)
                    break
        if res:
            break
    if not res:
        raise SystemExit('no WDBII river file found in basemap-data')
    print('using WDBII resolution "%s"' % res)
    base = os.path.join(tmp, 'mpl_toolkits/basemap_data')

    segs = []
    with open(os.path.join(base, 'rivers_%s.dat' % res), 'rb') as dat, \
            open(os.path.join(base, 'riversmeta_%s.dat' % res)) as meta:
        for line in meta:
            p = line.split()
            npts, south, north = int(p[2]), float(p[3]), float(p[4])
            off, nby, rid = int(p[5]), int(p[6]), int(p[7])
            if north < BOX[1] or south > BOX[3]:
                continue
            dat.seek(off)
            b = np.frombuffer(dat.read(nby), dtype='<f4').reshape(npts, 2).astype(float)
            if b[:, 0].max() < BOX[0] or b[:, 0].min() > BOX[2]:
                continue
            segs.append({'id': rid, 'coords': b.round(6).tolist()})
    os.makedirs(os.path.join(OUT, 'wdbii'), exist_ok=True)
    path = os.path.join(OUT, 'wdbii', 'rivers_nigeria.json')
    json.dump(segs, open(path, 'w'))
    print('WDBII: %d segments, %d vertices -> %s'
          % (len(segs), sum(len(s['coords']) for s in segs), path))


def natural_earth():
    """Natural Earth 10m river centrelines (public domain), raw GeoJSON from GitHub."""
    path = os.path.join(OUT, 'ne10m', 'rivers10m.geojson')
    if os.path.exists(path):
        print('Natural Earth: already cached')
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = ('repos/nvkelso/natural-earth-vector/contents/geojson/'
           'ne_10m_rivers_lake_centerlines.geojson')
    print('downloading Natural Earth 10m rivers ...')
    with open(path, 'wb') as f:
        subprocess.check_call(['gh', 'api', '-H', 'Accept: application/vnd.github.raw',
                               url], stdout=f)
    print('Natural Earth -> %s (%d bytes)' % (path, os.path.getsize(path)))


if __name__ == '__main__':
    natural_earth()
    wdbii()
