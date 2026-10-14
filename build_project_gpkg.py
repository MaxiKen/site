#!/usr/bin/env python3
"""
Bundle the whole project into ONE GeoPackage: nigeria_maps.gpkg

    vector layers   geology2011_<layer>   the 17 layers extracted from the Geological Map of Nigeria (2011)
                    minerals2023_<layer>  the 16 layers extracted from the Mineral Resources Map of Nigeria (2023)
    tile layers     geology2011_map_pdf   the 2011 PDF page, georeferenced, as a tile pyramid (EPSG:4326, zoom 4-8)
                    minerals2023_map_pdf  the 2023 PDF page, georeferenced, as a tile pyramid (EPSG:4326, zoom 4-8)
    tables          geology2011_legend, geology2011_summary_area_by_unit, geology2011_summary_area_by_age,
                    minerals2023_legend, minerals2023_code_dictionary, minerals2023_explanations_table,
                    minerals2023_summary_localities_by_host_geology, minerals2023_summary_localities_by_group
    catalogue       project_layers  (one row per table: source map, kind, geometry, feature count, description)
                    gpkg_metadata   (project description, georeferencing of both maps, build date)

Everything is EPSG:4326.  Attribute names are the shapefile (DBF) names documented in ATTRIBUTES.md.

Run:  python build_project_gpkg.py [--out nigeria_maps.gpkg] [--zmax 8] [--no-rasters]
      python build_project_gpkg.py --check          # verify the file (GDAL raster check if rasterio is installed)

Requirements: pyogrio (vector + attribute tables), PyMuPDF + Pillow + numpy (only if the tile pyramids have to be
rendered - they are re-used from viewer/build/ when the viewer has already been built).
"""
import argparse
import csv
import datetime
import json
import os
import sqlite3
import sys

import numpy as np
from pyogrio.raw import read as ogr_read, write as ogr_write

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'viewer'))

TILE = 256

DATASETS = {
    'geology': {
        'prefix': 'geology2011_', 'dir': 'shapefiles',
        'title': 'Geological Map of Nigeria (2011, Nigerian Geological Survey Agency), 1:2 000 000',
        'pdf': 'ilide.info-geological-map-of-nigeria-pr_a0987e407d194cb02682ac479336acb1.pdf',
        'tables': {'legend.csv': ('legend', 'printed legend: 92 rows with code, unit, formation, rock class, '
                                            'era / period / epoch / series, Ma range and age source'),
                   'summary_area_by_unit.csv': ('summary_area_by_unit', 'area statistics per legend unit'),
                   'summary_area_by_age.csv': ('summary_area_by_age', 'area by era, period, epoch, series and rock class')},
    },
    'minerals': {
        'prefix': 'minerals2023_', 'dir': 'shapefiles_minerals',
        'title': 'Mineral Resources Map of Nigeria (2023, Nigerian Geological Survey Agency), 1:1 978 000',
        'pdf': 'Mineral_Resources_Map_of_Nigeria_2023.pdf',
        'tables': {'mineral_legend.csv': ('legend', 'printed mineral legend: 70 symbols with code, commodity group and symbol image'),
                   'mineral_code_dictionary.csv': ('code_dictionary', 'every code used in the EXPLANATIONS table with its meaning, '
                                                                      'commodity group and confidence'),
                   'explanations_table.csv': ('explanations_table', 'the full EXPLANATIONS table (1 171 numbered rows, zones A-G) '
                                                                    'with parsed codes, minerals and flags'),
                   'summary_localities_by_host_geology.csv': ('summary_localities_by_host_geology',
                                                              'localities per host rock unit of the 2011 map'),
                   'summary_localities_by_group.csv': ('summary_localities_by_group',
                                                       'commodity group x host era x numbering zone')},
    },
}

# one-line description per vector layer (details: README.md / ATTRIBUTES.md)
DESCRIPTIONS = {
    'geology': {
        'geology_units': 'rock-unit polygons with legend code, unit, formation, rock class, era / period / epoch / series, '
                         'Ma range, basin, area_km2 and perim_km',
        'major_rivers_poly': 'water areas: Gulf of Guinea, Lake Chad, River Niger / Benue, reservoir (named, area_km2)',
        'geological_boundaries': 'geological boundaries (definite / approximate / inferred / transitional) with len_km',
        'younger_granite_outlines': 'outlines of the Jurassic Younger Granite ring complexes',
        'faults': 'faults and fractures (observed / inferred) with len_km',
        'fold_axes': 'anticline / syncline axes',
        'ridges': 'ridge lines',
        'rivers': 'river centrelines with len_km',
        'major_rivers_outline': 'bank lines of the major rivers',
        'state_boundaries': 'state boundary segments',
        'roads': 'road centrelines (merged from the double-line symbol)',
        'railway': 'railway lines',
        'graticule': 'fitted graticule lines used for the georeference (QA layer)',
        'towns': 'town symbols with name (where printed)',
        'volcanic_plugs': 'volcanic plugs and pipes',
        'state_capitals': 'state capitals (approximate symbol position)',
        'labels': 'all map text: unit codes, place and river names, with font size and angle',
    },
    'minerals': {
        'map_zones': 'numbering zones A-G built from the division lines (rows in table, numbers on map, area_km2)',
        'division_lines': 'the lines dividing the map into numbering zones',
        'map_frame': 'the map frame = GeoPDF viewport (scale, extent)',
        'international_boundary': 'international boundary of Nigeria as drawn (len 4 092 km)',
        'rivers': 'rivers and lake shores (72 closed rings) with length_km',
        'roads': 'road centrelines with length_km',
        'railway': 'railway lines',
        'graticule': 'graticule with printed label and GeoPDF (/VP) value',
        'mineral_symbols_raster': 'every mineral symbol detected on the raster map face (colour, size, fill class, candidates)',
        'mineral_localities': 'one point per mineral number printed on the map, joined to the EXPLANATIONS table: locality, '
                              'codes, minerals, commodity groups, position source, n_printed, host rock unit of the 2011 map',
        'towns': 'town symbols with name',
        'state_capitals': 'state capitals with reference coordinates and offsets',
        'state_name_labels': 'state name label positions',
        'river_labels': 'river / lake names assembled from curved glyph runs',
        'pegmatite_marks': 'the "P" pegmatite marks with nearest locality and host unit',
        'map_labels': 'all map text (town, state, river names) with kind, size and text box',
    },
}


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --------------------------------------------------------------------------- vector layers
def add_vector_layers(gpkg, ds, catalogue):
    d = DATASETS[ds]
    shp_dir = os.path.join(ROOT, d['dir'])
    for fn in sorted(os.listdir(shp_dir)):
        if not fn.endswith('.shp'):
            continue
        name = fn[:-4]
        meta, _, geometry, fields = ogr_read(os.path.join(shp_dir, fn))
        gtype = meta['geometry_type']
        promote = gtype == 'Polygon'
        if promote:
            gtype = 'MultiPolygon'
        layer = d['prefix'] + name
        ogr_write(gpkg, geometry, fields, layer=layer, driver='GPKG', crs='EPSG:4326', geometry_type=gtype,
                  fields=meta['fields'], append=True, promote_to_multi=promote,
                  layer_options={'IDENTIFIER': layer, 'DESCRIPTION': DESCRIPTIONS[ds].get(name, '')})
        catalogue.append({'table_name': layer, 'source_map': d['title'], 'kind': 'vector', 'geometry': gtype,
                          'features': int(len(geometry)), 'fields': len(meta['fields']),
                          'source_file': '%s/%s' % (d['dir'], fn), 'description': DESCRIPTIONS[ds].get(name, '')})
        print('  %-45s %-12s %6d features, %2d fields' % (layer, gtype, len(geometry), len(meta['fields'])))


# --------------------------------------------------------------------------- attribute tables
def typed_columns(rows, header):
    """Infer int / float / text per CSV column; return (fields, arrays)."""
    arrays = []
    for col in header:
        vals = [r.get(col, '') for r in rows]
        kind = 'int'
        for v in vals:
            if v in ('', None):
                continue
            try:
                int(v)
            except ValueError:
                try:
                    float(v)
                    kind = 'float' if kind != 'text' else kind
                except ValueError:
                    kind = 'text'
                    break
        if kind == 'int':
            arr = np.array([int(v) if v not in ('', None) else None for v in vals], dtype=object)
            if all(v is not None for v in arr):
                arr = arr.astype(np.int64)
            else:
                arr = np.array([float(v) if v is not None else np.nan for v in arr], dtype=np.float64)
        elif kind == 'float':
            arr = np.array([float(v) if v not in ('', None) else np.nan for v in vals], dtype=np.float64)
        else:
            arr = np.array([v if v is not None else '' for v in vals], dtype=object)
        arrays.append(arr)
    return header, arrays


def add_tables(gpkg, ds, catalogue):
    d = DATASETS[ds]
    for fn, (short, desc) in d['tables'].items():
        path = os.path.join(ROOT, d['dir'], fn)
        if not os.path.exists(path):
            print('  (missing) ' + path)
            continue
        with open(path, encoding='utf-8', newline='') as f:
            rd = csv.DictReader(f)
            header = [h for h in rd.fieldnames if h]
            rows = list(rd)
        fields, arrays = typed_columns(rows, header)
        layer = d['prefix'] + short
        ogr_write(gpkg, None, arrays, layer=layer, driver='GPKG', geometry_type=None, fields=fields, crs=None,
                  append=True, layer_options={'IDENTIFIER': layer, 'DESCRIPTION': desc})
        catalogue.append({'table_name': layer, 'source_map': d['title'], 'kind': 'attributes', 'geometry': '',
                          'features': len(rows), 'fields': len(fields), 'source_file': '%s/%s' % (d['dir'], fn),
                          'description': desc})
        print('  %-45s %-12s %6d rows, %2d columns' % (layer, 'table', len(rows), len(fields)))


# --------------------------------------------------------------------------- tile pyramids (the PDF pages)
def tile_dirs(ds, zmax):
    """Re-use the viewer's tiles (same EPSG:4326 Leaflet scheme) or render them now."""
    import build_data   # viewer/build_data.py
    out = build_data.DATASETS[ds]['tiles']
    have = os.path.isdir(out) and all(os.path.isdir(os.path.join(out, str(z))) for z in range(4, zmax + 1))
    if not have:
        print('  rendering %s tiles (zoom 4-%d) from the PDF ...' % (ds, max(zmax, 9)))
        build_data.build_tiles(ds, zmin=4, zmax=max(zmax, 9))
    bounds = build_data.load_georef(ds)
    return out, bounds


def add_tile_layer(gpkg, ds, zmax, catalogue):
    d = DATASETS[ds]
    tdir, (a, b, c, dd, raw) = tile_dirs(ds, zmax)
    import pymupdf
    page = pymupdf.open(os.path.join(ROOT, d['pdf']))[0]
    W, H = page.rect.width, page.rect.height
    lon0, lon1 = b, a * W + b
    lat0, lat1 = dd, c * H + dd
    table = d['prefix'] + 'map_pdf'
    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    cur.execute('CREATE TABLE "%s" (id INTEGER PRIMARY KEY AUTOINCREMENT, zoom_level INTEGER NOT NULL, '
                'tile_column INTEGER NOT NULL, tile_row INTEGER NOT NULL, tile_data BLOB NOT NULL, '
                'UNIQUE (zoom_level, tile_column, tile_row))' % table)
    cur.execute('INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change, '
                'min_x, min_y, max_x, max_y, srs_id) VALUES (?,?,?,?,?,?,?,?,?,4326)',
                (table, 'tiles', table, 'the %s PDF page rendered and georeferenced (zoom 4-%d, EPSG:4326 '
                 'global tile scheme, 256 px, PNG)' % (d['title'].split(' (')[0], zmax), iso_now(),
                 lon0, lat0, lon1, lat1))
    cur.execute('INSERT INTO gpkg_tile_matrix_set (table_name, srs_id, min_x, min_y, max_x, max_y) '
                'VALUES (?,4326,-180,-90,180,90)', (table,))
    n_tiles = 0
    for z in range(4, zmax + 1):
        n = 2 ** z
        px = 180.0 / n / TILE
        cur.execute('INSERT INTO gpkg_tile_matrix (table_name, zoom_level, matrix_width, matrix_height, tile_width, '
                    'tile_height, pixel_x_size, pixel_y_size) VALUES (?,?,?,?,?,?,?,?)',
                    (table, z, 2 * n, n, TILE, TILE, px, px))
        zdir = os.path.join(tdir, str(z))
        for tx in sorted(os.listdir(zdir), key=int):
            for fn in sorted(os.listdir(os.path.join(zdir, tx)), key=lambda s: int(s.split('.')[0])):
                ty = int(fn.split('.')[0])
                with open(os.path.join(zdir, tx, fn), 'rb') as f:
                    blob = f.read()
                cur.execute('INSERT INTO "%s" (zoom_level, tile_column, tile_row, tile_data) VALUES (?,?,?,?)' % table,
                            (z, int(tx), ty, sqlite3.Binary(blob)))
                n_tiles += 1
    con.commit()
    con.close()
    catalogue.append({'table_name': table, 'source_map': d['title'], 'kind': 'tiles', 'geometry': 'raster (PNG tiles)',
                      'features': n_tiles, 'fields': 0, 'source_file': d['pdf'],
                      'description': 'georeferenced render of the PDF page, zoom 4-%d (%.4f deg/px at zoom %d)' % (
                          zmax, 180.0 / 2 ** zmax / TILE, zmax)})
    print('  %-45s %-12s %6d tiles (zoom 4-%d)' % (table, 'tiles', n_tiles, zmax))


# --------------------------------------------------------------------------- catalogue + metadata
def add_catalogue(gpkg, catalogue):
    cols = ['table_name', 'source_map', 'kind', 'geometry', 'features', 'fields', 'source_file', 'description']
    arrays = []
    for c in cols:
        vals = [row[c] for row in catalogue]
        arrays.append(np.array(vals, dtype=np.int64) if c in ('features', 'fields') else np.array(vals, dtype=object))
    ogr_write(gpkg, None, arrays, layer='project_layers', driver='GPKG', geometry_type=None, fields=cols, crs=None,
              append=True, layer_options={'IDENTIFIER': 'project_layers',
                                          'DESCRIPTION': 'catalogue of every table in this GeoPackage'})


def add_metadata(gpkg, zmax, with_rasters):
    geo = json.load(open(os.path.join(ROOT, 'shapefiles', 'georeferencing.json')))
    mn = json.load(open(os.path.join(ROOT, 'shapefiles_minerals', 'georeferencing.json')))
    text = {
        'title': 'Nigeria geological (2011) and mineral resources (2023) maps - extracted GIS layers',
        'built': iso_now(),
        'crs': 'EPSG:4326 (WGS 84 geographic)',
        'layers': 'geology2011_* = 17 layers from the Geological Map of Nigeria 2011 (not a GeoPDF; georeferenced from the '
                  'printed graticule); minerals2023_* = 16 layers from the Mineral Resources Map of Nigeria 2023 '
                  '(GeoPDF /VP georeference); *_map_pdf = the PDF pages as tile pyramids' if with_rasters else
                  'geology2011_* = 17 layers from the Geological Map of Nigeria 2011; minerals2023_* = 16 layers from the '
                  'Mineral Resources Map of Nigeria 2023',
        'geology_2011_georeference': geo,
        'minerals_2023_georeference': {k: mn[k] for k in mn if k in ('affine', 'points_per_degree', 'capital_check_km',
                                                                     'scale', 'map_frame_deg', 'source')} or mn,
        'tiles': 'EPSG:4326 global scheme (Leaflet L.CRS.EPSG4326): at zoom z 2^(z+1) x 2^z tiles of 256 px, '
                 'zoom 4-%d' % zmax if with_rasters else 'not included (--no-rasters)',
        'accuracy': 'both maps are ~1:2 000 000; the two georeferences differ by ~8 km (rms 11 km on 33 state capitals), '
                    'so cross-map joins (minerals2023_mineral_localities.geo_*) are +-10 km statements',
        'documentation': 'README.md and ATTRIBUTES.md in the repository (field dictionary, derivation of the '
                         'stratigraphic ages, audit of every layer)',
    }
    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS gpkg_metadata (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                "md_scope TEXT NOT NULL DEFAULT 'dataset', md_standard_uri TEXT NOT NULL, "
                "mime_type TEXT NOT NULL DEFAULT 'text/xml', metadata TEXT NOT NULL DEFAULT '')")
    cur.execute('CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (reference_scope TEXT NOT NULL, table_name TEXT, '
                'column_name TEXT, row_id_value INTEGER, timestamp DATETIME NOT NULL DEFAULT '
                "(strftime('%Y-%m-%dT%H:%M:%fZ','now')), md_file_id INTEGER NOT NULL, md_parent_id INTEGER, "
                'CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id) REFERENCES gpkg_metadata(id), '
                'CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id) REFERENCES gpkg_metadata(id))')
    cur.execute("INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, metadata) VALUES "
                "('dataset', 'https://www.json.org', 'application/json', ?)", (json.dumps(text, indent=1, default=float),))
    mid = cur.lastrowid
    cur.execute("INSERT INTO gpkg_metadata_reference (reference_scope, md_file_id) VALUES ('geopackage', ?)", (mid,))
    for ext in (('gpkg_metadata', None), ('gpkg_metadata_reference', None)):
        cur.execute("INSERT OR IGNORE INTO gpkg_extensions (table_name, column_name, extension_name, definition, scope) "
                    "VALUES (?, ?, 'gpkg_metadata', 'http://www.geopackage.org/spec120/#extension_metadata', 'read-write')", ext)
    con.commit()
    con.close()


# --------------------------------------------------------------------------- check
def check(gpkg):
    """Structural check: SQLite integrity, gpkg_contents, every layer readable; tile layers opened with GDAL if
    rasterio is installed (pip install rasterio)."""
    import pyogrio
    con = sqlite3.connect(gpkg)
    print('integrity:', con.execute('PRAGMA integrity_check').fetchone()[0])
    print('contents:', con.execute('select data_type, count(*) from gpkg_contents group by data_type').fetchall())
    for (t,) in con.execute("select table_name from gpkg_contents where data_type='tiles'"):
        print('  %s: %s' % (t, con.execute('select zoom_level, count(*) from "%s" group by zoom_level' % t).fetchall()))
    con.close()
    n = 0
    for name, gtype in pyogrio.list_layers(gpkg):
        meta, _, geometry, fields = ogr_read(gpkg, layer=name)
        n += len(fields[0]) if fields else 0
    print('vector/attribute layers readable: %d (%d rows in total)' % (len(pyogrio.list_layers(gpkg)), n))
    os.environ.setdefault('GDAL_PAM_ENABLED', 'NO')     # no "GPKG:...aux.xml" side-car files next to the cwd
    try:
        import rasterio
    except ImportError:
        print('rasterio not installed - tile layers not opened with GDAL (QGIS will read them)')
        return
    con = sqlite3.connect(gpkg)
    for (t,) in con.execute("select table_name from gpkg_contents where data_type='tiles'"):
        with rasterio.open('GPKG:%s:%s' % (gpkg, t)) as src:
            print('  GDAL opens %s: %s, %d x %d px, %.5f deg/px, overviews %s, bounds %s' % (
                t, src.crs, src.width, src.height, src.res[0], src.overviews(1), tuple(round(v, 3) for v in src.bounds)))
    con.close()


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(ROOT, 'nigeria_maps.gpkg'))
    ap.add_argument('--zmax', type=int, default=8, help='max zoom of the PDF tile pyramids (default 8 = 0.0027 deg/px '
                                                        '~ 300 m; 9 doubles that and adds ~25 MB)')
    ap.add_argument('--no-rasters', action='store_true', help='vector layers and tables only')
    ap.add_argument('--check', action='store_true', help='only verify an existing GeoPackage')
    args = ap.parse_args()
    if args.check:
        check(args.out)
        return
    if os.path.exists(args.out):
        os.remove(args.out)
    catalogue = []
    for ds in ('geology', 'minerals'):
        print(DATASETS[ds]['title'])
        add_vector_layers(args.out, ds, catalogue)
        add_tables(args.out, ds, catalogue)
    if not args.no_rasters:
        print('PDF pages as tile pyramids')
        for ds in ('geology', 'minerals'):
            add_tile_layer(args.out, ds, args.zmax, catalogue)
    add_catalogue(args.out, catalogue)
    add_metadata(args.out, args.zmax, not args.no_rasters)
    con = sqlite3.connect(args.out)
    con.execute('VACUUM')
    con.close()
    print('%s: %d tables, %.1f MB' % (os.path.relpath(args.out, ROOT), len(catalogue) + 1,
                                      os.path.getsize(args.out) / 1e6))


if __name__ == '__main__':
    main()
