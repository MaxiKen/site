#!/usr/bin/env python3
"""
Build the data the comparison viewer needs (everything goes to viewer/build/, which is
not committed).  Two datasets are supported:

  geology   (ilide.info-geological-map-of-nigeria-*.pdf  ->  shapefiles/)
      build/tiles/{z}/{x}/{y}.png        the PDF page rendered as Leaflet EPSG:4326 tiles
                                         (zoom 4-9, ~330 dpi), placed with the graticule fit
      build/data/<layer>.geojson(.gz)    the extracted shapefiles
      build/data/meta.json               inventory, legend, georeference, PDF-vs-output stats

  minerals  (Mineral_Resources_Map_of_Nigeria_2023.pdf  ->  shapefiles_minerals/)
      build/tiles_minerals/{z}/{x}/{y}.png   placed with the GeoPDF /VP affine
      build/data/minerals/<layer>.geojson(.gz)
      build/data/minerals/legend_symbols/*.png
      build/data/minerals/meta.json      inventory, legend, code dictionary, QA report

Run:  python viewer/build_data.py [--dataset geology|minerals|all] [--tiles-only|--data-only] [--zmax 9]
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
BUILD = os.path.join(ROOT, 'viewer', 'build')
TILE = 256

GEOLOGY_PDF = (glob.glob(os.path.join(ROOT, 'ilide.info-geological-map-of-nigeria*.pdf'))
               or [f for f in glob.glob(os.path.join(ROOT, '*.pdf')) if 'Mineral' not in os.path.basename(f)] or [None])[0]
MINERALS_PDF = os.path.join(ROOT, 'Mineral_Resources_Map_of_Nigeria_2023.pdf')

GEOLOGY_LAYERS = ['geology_units', 'major_rivers_poly', 'geological_boundaries', 'younger_granite_outlines',
                  'faults', 'fold_axes', 'ridges', 'rivers', 'major_rivers_outline', 'state_boundaries',
                  'roads', 'railway', 'graticule', 'towns', 'volcanic_plugs', 'state_capitals', 'labels']
MINERAL_LAYERS = ['map_zones', 'division_lines', 'map_frame', 'international_boundary', 'rivers', 'roads', 'railway',
                  'graticule', 'mineral_symbols_raster', 'mineral_localities', 'towns', 'state_capitals',
                  'state_name_labels', 'river_labels', 'pegmatite_marks', 'map_labels']

DATASETS = {
    'geology': {'pdf': GEOLOGY_PDF, 'shp_dir': os.path.join(ROOT, 'shapefiles'),
                'tiles': os.path.join(BUILD, 'tiles'), 'data': os.path.join(BUILD, 'data'),
                'layers': GEOLOGY_LAYERS},
    'minerals': {'pdf': MINERALS_PDF, 'shp_dir': os.path.join(ROOT, 'shapefiles_minerals'),
                 'tiles': os.path.join(BUILD, 'tiles_minerals'), 'data': os.path.join(BUILD, 'data', 'minerals'),
                 'layers': MINERAL_LAYERS},
}


# --------------------------------------------------------------------------- georeference
def load_georef(ds):
    """Return (a, b, c, d, raw) with lon = a*x + b, lat = c*y + d in PDF points (y up)."""
    g = json.load(open(os.path.join(DATASETS[ds]['shp_dir'], 'georeferencing.json')))
    if ds == 'geology':
        return g['lon = a*x + b']['a'], g['lon = a*x + b']['b'], g['lat = c*y + d']['c'], g['lat = c*y + d']['d'], g
    (a, b), (c, d) = g['affine']['lon = a*x + b'], g['affine']['lat = c*y + d']
    return a, b, c, d, g


# --------------------------------------------------------------------------- tiles
def build_tiles(ds, zmin=4, zmax=9):
    import pymupdf
    from PIL import Image

    a, b, c, d, _ = load_georef(ds)
    doc = pymupdf.open(DATASETS[ds]['pdf'])
    page = doc[0]
    W, H = page.rect.width, page.rect.height
    dl = page.get_displaylist()
    lon0, lon1 = b, a * W + b          # page extent in "map" degrees
    lat0, lat1 = d, c * H + d
    out_root = DATASETS[ds]['tiles']
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
def build_vectors(ds):
    from pyogrio.raw import read, write
    out_dir = DATASETS[ds]['data']
    os.makedirs(out_dir, exist_ok=True)
    layers = []
    for name in DATASETS[ds]['layers']:
        src = os.path.join(DATASETS[ds]['shp_dir'], name + '.shp')
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


def write_json(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=1, default=lambda o: int(o) if isinstance(o, np.integer) else float(o))
    with open(path, 'rb') as f_in, gzip.open(path + '.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)


# --------------------------------------------------------------------------- geology: PDF statistics
def pdf_statistics():
    """Count the drawing primitives per PDF layer (optional content group) so the viewer can
    show "what was in the PDF" next to "what was extracted"."""
    sys.path.insert(0, ROOT)
    import pikepdf
    import extract_shapefiles as ex

    pdf = pikepdf.open(GEOLOGY_PDF)
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


def build_meta_geology(tile_info, layers):
    a, b, c, d, g = load_georef('geology')
    shp = DATASETS['geology']['shp_dir']
    legend = list(csv.DictReader(open(os.path.join(shp, 'legend.csv'), newline='')))
    pgw = [float(v) for v in open(os.path.join(shp, 'map_raster', 'geological_map_nigeria.pgw')).read().split()]
    from PIL import Image
    im = Image.open(os.path.join(shp, 'map_raster', 'geological_map_nigeria.png'))
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
        'pdf': os.path.basename(GEOLOGY_PDF),
        'tiles': tile_info,
        'map_face_bounds': face,
        'georef': {'a': a, 'b': b, 'c': c, 'd': d, 'points_per_degree': g['points_per_degree_x'],
                   'max_residual_deg': g['max_residual_deg'], 'scale': g['approx_scale_denominator']},
        'layers': layers,
        'legend': legend,
        'pdf_stats': stats,
    }
    write_json(os.path.join(DATASETS['geology']['data'], 'meta.json'), meta)
    print('meta.json written')


def build_meta_minerals(tile_info, layers):
    a, b, c, d, g = load_georef('minerals')
    shp = DATASETS['minerals']['shp_dir']
    out = DATASETS['minerals']['data']
    bb = g['bbox_pt']
    face = [[c * bb['y_bottom'] + d, a * bb['x0'] + b], [c * bb['y_top'] + d, a * bb['x1'] + b]]
    legend = list(csv.DictReader(open(os.path.join(shp, 'mineral_legend.csv'), newline='')))
    codes = list(csv.DictReader(open(os.path.join(shp, 'mineral_code_dictionary.csv'), newline='')))
    qa = json.load(open(os.path.join(shp, 'qa_report.json')))
    # legend symbol cut-outs for the legend panel
    sym_dir = os.path.join(out, 'legend_symbols')
    os.makedirs(sym_dir, exist_ok=True)
    for row in legend:
        src = os.path.join(shp, row['symbol_png']) if row['symbol_png'] else ''
        if src and os.path.exists(src):
            shutil.copyfile(src, os.path.join(sym_dir, os.path.basename(src)))
            row['symbol_png'] = 'legend_symbols/' + os.path.basename(src)
    # the EXPLANATIONS table (for search / "not on the map" rows)
    table = []
    for r in csv.DictReader(open(os.path.join(shp, 'explanations_table.csv'), newline='')):
        table.append({'z': r['zone'], 'n': int(r['number']), 'np': r['number_printed'], 'loc': r['locality'],
                      'codes': r['codes'], 'min': r['minerals'], 'on': r['on_map'] == 'yes', 'flags': r['flags']})
    write_json(os.path.join(out, 'table.json'), table)
    # map face area (pt) -> degrees, for the "PDF table" bookmark: everything right of the frame
    page_w = 3960.0
    meta = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'pdf': os.path.basename(MINERALS_PDF),
        'tiles': tile_info,
        'map_face_bounds': face,
        'table_bounds': [[tile_info['page_bounds'][0][0], a * bb['x1'] + b], [tile_info['page_bounds'][1][0], a * page_w + b]],
        'georef': {'a': a, 'b': b, 'c': c, 'd': d, 'points_per_degree': g['points_per_degree']['x'],
                   'gcs': g['gcs_wkt'].split(',')[0].split('[')[1].strip('"'),
                   'parallel_max_residual_deg': g.get('parallel_max_residual_deg'),
                   'meridian_label_offset_deg': g.get('meridian_label_offset_deg'),
                   'notes': g.get('notes', [])},
        'layers': layers,
        'legend': legend,
        'codes': codes,
        'qa': {'table': qa.get('table'), 'number_labels': qa.get('number_labels'),
               'raster_symbols': {k: v for k, v in qa.get('raster_symbols', {}).items() if k != 'by_colour'},
               'capital_check_km': {k: v for k, v in qa.get('capital_check_km', {}).items() if k != 'per_capital'}},
    }
    write_json(os.path.join(out, 'meta.json'), meta)
    print('minerals/meta.json written')


def build(ds, tiles=True, data=True, zmax=9):
    if not DATASETS[ds]['pdf'] or not os.path.exists(DATASETS[ds]['pdf']):
        print(f'{ds}: PDF not found, skipped')
        return
    if not os.path.isdir(DATASETS[ds]['shp_dir']):
        print(f'{ds}: {DATASETS[ds]["shp_dir"]} not found, skipped')
        return
    os.makedirs(DATASETS[ds]['data'], exist_ok=True)
    tiles_json = os.path.join(DATASETS[ds]['data'], 'tiles.json')
    tile_info = None
    if tiles:
        print(f'[{ds}] rendering PDF tiles ...', flush=True)
        tile_info = build_tiles(ds, zmax=zmax)
        json.dump(tile_info, open(tiles_json, 'w'))
    if data:
        if tile_info is None:
            legacy = os.path.join(BUILD, 'tiles.json')
            tile_info = json.load(open(tiles_json if os.path.exists(tiles_json) else legacy))
        print(f'[{ds}] converting shapefiles ...', flush=True)
        layers = build_vectors(ds)
        (build_meta_geology if ds == 'geology' else build_meta_minerals)(tile_info, layers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', choices=['geology', 'minerals', 'all'], default='all')
    ap.add_argument('--tiles-only', action='store_true')
    ap.add_argument('--data-only', action='store_true')
    ap.add_argument('--zmax', type=int, default=9)
    args = ap.parse_args()
    os.makedirs(BUILD, exist_ok=True)
    for ds in (['geology', 'minerals'] if args.dataset == 'all' else [args.dataset]):
        build(ds, tiles=not args.data_only, data=not args.tiles_only, zmax=args.zmax)
    print('done')


if __name__ == '__main__':
    main()
