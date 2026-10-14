#!/usr/bin/env python3
"""
Build the data the comparison viewer needs (everything goes to viewer/build/, which is
not committed):

  build/tiles/{z}/{x}/{y}.png   the ORIGINAL PDF page rendered as Leaflet EPSG:4326
                                 tiles (zoom 4-9, i.e. up to ~330 dpi), placed with the
                                 graticule georeference from shapefiles/georeferencing.json
  build/data/<layer>.geojson     the EXTRACTED shapefiles as GeoJSON (+ .gz copies)
  build/data/meta.json           layer inventory, legend, georeference, PDF-vs-output
                                 comparison statistics

Run:  python viewer/build_data.py [--tiles-only|--data-only] [--zmax 9]
"""
import argparse
import collections
import csv
import glob
import gzip
import json
import math
import os
import shutil
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = (glob.glob(os.path.join(ROOT, 'ilide.info-geological-map-of-nigeria*.pdf'))
       or [f for f in glob.glob(os.path.join(ROOT, '*.pdf')) if 'Mineral' not in os.path.basename(f)])[0]
SHP_DIR = os.path.join(ROOT, 'shapefiles')
BUILD = os.path.join(ROOT, 'viewer', 'build')
TILE = 256


def load_georef():
    g = json.load(open(os.path.join(SHP_DIR, 'georeferencing.json')))
    a, b = g['lon = a*x + b']['a'], g['lon = a*x + b']['b']
    c, d = g['lat = c*y + d']['c'], g['lat = c*y + d']['d']
    return a, b, c, d, g


# --------------------------------------------------------------------------- tiles
def build_tiles(zmin=4, zmax=9):
    import pymupdf
    from PIL import Image

    a, b, c, d, _ = load_georef()
    doc = pymupdf.open(PDF)
    page = doc[0]
    W, H = page.rect.width, page.rect.height
    dl = page.get_displaylist()
    lon0, lon1 = b, a * W + b          # page extent in "map" degrees
    lat0, lat1 = d, c * H + d
    out_root = os.path.join(BUILD, 'tiles')
    if os.path.isdir(out_root):
        shutil.rmtree(out_root)
    t0 = time.time()
    n_tiles = 0
    for z in range(zmin, zmax + 1):
        n = 2 ** z
        deg = 180.0 / n                # degrees per tile (Leaflet L.CRS.EPSG4326)
        tx0 = int(math.floor((lon0 / 180 + 1) * n))
        tx1 = int(math.floor((lon1 / 180 + 1) * n))
        ty0 = int(math.floor((-lat1 / 180 + 0.5) * n))
        ty1 = int(math.floor((-lat0 / 180 + 0.5) * n))
        dpp = deg / TILE               # degrees per pixel
        sx, sy = a / dpp, c / dpp      # pixels per PDF point
        ncols = tx1 - tx0 + 1
        strip_w = ncols * TILE
        x_pt0 = ((tx0 / n - 1) * 180 - b) / a
        x_pt1 = (((tx1 + 1) / n - 1) * 180 - b) / a
        for ty in range(ty0, ty1 + 1):
            lat_top = (0.5 - ty / n) * 180
            lat_bot = lat_top - deg
            yf0 = H - (lat_top - d) / c          # PyMuPDF y axis points down
            yf1 = H - (lat_bot - d) / c
            clip = pymupdf.Rect(x_pt0, yf0, x_pt1, yf1)
            mat = pymupdf.Matrix(sx, 0, 0, sy, -x_pt0 * sx, -yf0 * sy)   # strip origin -> (0,0)
            pix = dl.get_pixmap(matrix=mat, clip=clip, alpha=False)
            strip = np.full((TILE, strip_w, 3), 255, np.uint8)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
            ox, oy = int(pix.x), int(pix.y)      # placement of the rendered area in strip pixels
            sx0, sy0 = max(ox, 0), max(oy, 0)
            sx1, sy1 = min(ox + pix.width, strip_w), min(oy + pix.height, TILE)
            if sx1 > sx0 and sy1 > sy0:
                strip[sy0:sy1, sx0:sx1] = arr[sy0 - oy:sy1 - oy, sx0 - ox:sx1 - ox]
            for i in range(ncols):
                tile = strip[:, i * TILE:(i + 1) * TILE]
                tdir = os.path.join(out_root, str(z), str(tx0 + i))
                os.makedirs(tdir, exist_ok=True)
                # flat-colour map: an adaptive 8-bit palette keeps the PNGs small
                img = Image.fromarray(np.ascontiguousarray(tile)).convert('P', palette=Image.Palette.ADAPTIVE, colors=256)
                img.save(os.path.join(tdir, f'{ty}.png'), optimize=True)
                n_tiles += 1
        print(f'  zoom {z}: {ncols} x {ty1 - ty0 + 1} tiles ({time.time() - t0:.0f} s)', flush=True)
    print(f'tiles: {n_tiles} written to {out_root}')
    return {'zmin': zmin, 'zmax': zmax, 'page_bounds': [[lat0, lon0], [lat1, lon1]]}


# --------------------------------------------------------------------------- vectors
LAYER_FILES = ['geology_units', 'major_rivers_poly', 'geological_boundaries', 'younger_granite_outlines',
               'faults', 'fold_axes', 'ridges', 'rivers', 'major_rivers_outline', 'state_boundaries',
               'roads', 'railway', 'graticule', 'towns', 'volcanic_plugs', 'state_capitals', 'labels']


def build_vectors():
    from pyogrio.raw import read, write
    out_dir = os.path.join(BUILD, 'data')
    os.makedirs(out_dir, exist_ok=True)
    layers = []
    for name in LAYER_FILES:
        src = os.path.join(SHP_DIR, name + '.shp')
        meta, _, geometry, field_data = read(src)
        dst = os.path.join(out_dir, name + '.geojson')
        if os.path.exists(dst):
            os.remove(dst)
        write(dst, geometry, field_data, fields=meta['fields'], driver='GeoJSON',
              geometry_type=meta['geometry_type'], crs=meta['crs'],
              layer_options={'COORDINATE_PRECISION': '5', 'WRITE_BBOX': 'NO', 'WRITE_NAME': 'NO'})
        with open(dst, 'rb') as f_in, gzip.open(dst + '.gz', 'wb', compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        layers.append({'id': name, 'geometry': meta['geometry_type'], 'count': int(len(geometry)),
                       'fields': list(meta['fields']), 'bytes': os.path.getsize(dst),
                       'gz_bytes': os.path.getsize(dst + '.gz')})
        print(f'  {name}: {len(geometry)} features, {os.path.getsize(dst) / 1e6:.2f} MB '
              f'({os.path.getsize(dst + ".gz") / 1e6:.2f} MB gz)')
    return layers


# --------------------------------------------------------------------------- PDF statistics
def pdf_statistics():
    """Count the drawing primitives per PDF layer (optional content group) so the viewer can
    show "what was in the PDF" next to "what was extracted"."""
    sys.path.insert(0, ROOT)
    import pikepdf
    import extract_shapefiles as ex

    pdf = pikepdf.open(PDF)
    page = pdf.pages[0]
    oc_names = {}
    for k, v in page.Resources.get('/Properties', {}).items():
        oc_names[k.lstrip('/')] = (v.objgen[0], str(v.get('/Name', '')).rstrip('\x00'))
    data = page.Contents.read_bytes() if not isinstance(page.Contents, pikepdf.Array) \
        else b''.join(c.read_bytes() for c in page.Contents)
    feats = list(ex.parse_content(data, oc_names))
    paths = [f for f in feats if f['kind'] == 'path']
    texts = [f for f in feats if f['kind'] == 'text']
    words = ex.assemble_words(texts)

    per_layer = collections.OrderedDict()
    for p in paths:
        e = per_layer.setdefault(p['layer'], {'fills': 0, 'strokes': 0, 'text': 0, 'ocg_ids': set()})
        e['ocg_ids'].add(p['ocg_id'])
        if p['op'] in ('f', 'f*', 'B', 'B*', 'b', 'b*'):
            e['fills'] += 1
        else:
            e['strokes'] += 1
    for w in words:
        e = per_layer.setdefault(w['layer'], {'fills': 0, 'strokes': 0, 'text': 0, 'ocg_ids': set()})
        e['text'] += 1
    n_ocg = len({(p['ocg_id'], p['layer']) for p in paths})

    def total(names, key):
        return sum(per_layer.get(nm, {}).get(key, 0) for nm in names)

    unit_layers = [nm for nm in per_layer if nm not in ex.NON_UNIT_LAYERS
                   and nm not in ex.LINE_LAYERS and nm != 'State_Boundarys']
    line_sources = collections.defaultdict(list)
    for src, (out, *_rest) in ex.LINE_LAYERS.items():
        line_sources[out].append(src)

    compare = [{'output': 'geology_units', 'sources': f'{len(unit_layers)} unit layers',
                'pdf_primitives': total(unit_layers, 'fills'), 'pdf_kind': 'filled paths (even-odd)',
                'note': 'one polygon per filled path; holes rebuilt'}]
    for out in ['geological_boundaries', 'faults', 'fold_axes', 'younger_granite_outlines', 'ridges',
                'rivers', 'roads', 'railway']:
        srcs = line_sources[out]
        notes = {'geological_boundaries': 'dash fragments re-chained into lines',
                 'faults': 'dash fragments re-chained',
                 'fold_axes': 'fragments re-chained',
                 'younger_granite_outlines': 'as drawn',
                 'ridges': 'fragments re-chained',
                 'rivers': 'as drawn',
                 'roads': 'double-line symbol merged to centrelines',
                 'railway': 'symbol cross-ticks dropped'}
        compare.append({'output': out, 'sources': ', '.join(srcs), 'pdf_primitives': total(srcs, 'strokes'),
                        'pdf_kind': 'stroked paths', 'note': notes[out]})
    compare += [
        {'output': 'state_boundaries', 'sources': 'State_Boundarys', 'pdf_primitives': total(['State_Boundarys'], 'strokes'),
         'pdf_kind': 'stroked paths', 'note': 'grey band kept, black dash fragments dropped'},
        {'output': 'major_rivers_poly / _outline', 'sources': 'Major River',
         'pdf_primitives': total(['Major River'], 'fills') + total(['Major River'], 'strokes'),
         'pdf_kind': 'filled + stroked paths', 'note': ''},
        {'output': 'towns', 'sources': 'Towns', 'pdf_primitives': total(['Towns'], 'fills'),
         'pdf_kind': 'triangle markers', 'note': 'centroids; names from nearest label'},
        {'output': 'volcanic_plugs', 'sources': 'Volcanic Plugs&Pipes', 'pdf_primitives': total(['Volcanic Plugs&Pipes'], 'fills') + total(['Volcanic Plugs&Pipes'], 'strokes'),
         'pdf_kind': 'circle markers', 'note': 'centres'},
        {'output': 'state_capitals', 'sources': 'Labels (ArialMT 7.2 pt)', 'pdf_primitives': 0,
         'pdf_kind': 'no marker in the PDF', 'note': 'point = label centre (approx.)'},
        {'output': 'labels', 'sources': 'Labels, <Default>', 'pdf_primitives': total(['Labels', '<Default>'], 'text'),
         'pdf_kind': 'text strings (after word assembly)', 'note': 'halo duplicates removed'},
    ]
    layer_table = [{'layer': nm, 'fills': e['fills'], 'strokes': e['strokes'], 'text': e['text'],
                    'ocgs': len(e['ocg_ids'])} for nm, e in per_layer.items()]
    return {'n_paths': len(paths), 'n_text_runs': len(texts), 'n_words': len(words), 'n_layers': n_ocg,
            'compare': compare, 'layers': layer_table}


def build_meta(tile_info, layers):
    a, b, c, d, g = load_georef()
    legend = list(csv.DictReader(open(os.path.join(SHP_DIR, 'legend.csv'), newline='')))
    pgw = [float(v) for v in open(os.path.join(SHP_DIR, 'map_raster', 'geological_map_nigeria.pgw')).read().split()]
    # map face bounds from the QA raster world file
    from PIL import Image
    im = Image.open(os.path.join(SHP_DIR, 'map_raster', 'geological_map_nigeria.png'))
    face = [[pgw[5] + pgw[3] * im.height, pgw[4]], [pgw[5], pgw[4] + pgw[0] * im.width]]
    stats = pdf_statistics()
    counts = {l['id']: l['count'] for l in layers}
    for row in stats['compare']:
        key = row['output'].split(' /')[0]
        row['features'] = counts.get(key)
        if row['output'].startswith('major_rivers'):
            row['features'] = f"{counts['major_rivers_poly']} / {counts['major_rivers_outline']}"
    meta = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'pdf': os.path.basename(PDF),
        'tiles': tile_info,
        'map_face_bounds': face,
        'georef': {'a': a, 'b': b, 'c': c, 'd': d, 'points_per_degree': g['points_per_degree_x'],
                   'max_residual_deg': g['max_residual_deg'], 'scale': g['approx_scale_denominator']},
        'layers': layers,
        'legend': legend,
        'pdf_stats': stats,
    }
    with open(os.path.join(BUILD, 'data', 'meta.json'), 'w') as f:
        json.dump(meta, f, indent=1, default=lambda o: int(o) if isinstance(o, np.integer) else float(o))
    with open(os.path.join(BUILD, 'data', 'meta.json'), 'rb') as f_in, \
            gzip.open(os.path.join(BUILD, 'data', 'meta.json.gz'), 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    print('meta.json written')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tiles-only', action='store_true')
    ap.add_argument('--data-only', action='store_true')
    ap.add_argument('--zmax', type=int, default=9)
    args = ap.parse_args()
    os.makedirs(BUILD, exist_ok=True)
    tile_info = None
    if not args.data_only:
        print('rendering PDF tiles ...', flush=True)
        tile_info = build_tiles(zmax=args.zmax)
        json.dump(tile_info, open(os.path.join(BUILD, 'tiles.json'), 'w'))
    if not args.tiles_only:
        if tile_info is None:
            tile_info = json.load(open(os.path.join(BUILD, 'tiles.json')))
        print('converting shapefiles ...', flush=True)
        layers = build_vectors()
        build_meta(tile_info, layers)
    print('done')


if __name__ == '__main__':
    main()
