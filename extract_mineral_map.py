#!/usr/bin/env python3
"""
Extract georeferenced shapefiles from the NGSA "Mineral Resources Map of
Nigeria (2023)" PDF.

Unlike the geological map, this PDF *is* a GeoPDF: the page carries an
ISO-32000 viewport (/VP) with a /Measure dictionary that maps the map frame to
geographic coordinates, so the georeferencing is read straight from the file
(and cross-checked against the 1-degree graticule drawn on the map).

The content, however, is a mixed bag:

  * vector layers (PDF Optional Content Groups): roads, rivers, railway,
    international boundary, graticule, the A-G "division lines", town markers
    and all text (town / capital / state / river names, the numbers that key
    every mineral locality to the EXPLANATIONS table, "P" pegmatite marks);
  * ONE big raster (seven 75-dpi strips) that holds the geological background,
    the state boundaries *and every mineral symbol*; the legend symbols are two
    further raster strips.  There is no vector/marker-font geometry for the
    mineral symbols at all;
  * the EXPLANATIONS table (zone A-G, running number, locality, mineral codes)
    as text in the layout area to the right of the map.

What this script produces (see README for the full list):

  * every vector layer, cleaned so that it carries only what it represents
    (e.g. the 1,461 black dashes drawn in the "International_Boundary" group
    are symbol decoration and are dropped; the double-line road symbol is
    collapsed to centrelines; railway keeps only the rail lines, not the white
    dash overprint);
  * mineral_localities: one point per number printed on the map, joined to the
    EXPLANATIONS table on (zone, number) -> locality name + mineral codes,
    with the code expansion, QA flags, and the position snapped to the nearest
    raster symbol when one is unambiguous;
  * explanations_table.csv: the whole table, cleaned (the table text carries
    OCR-style misreads - I/l for 1, S for 5, B for 8, duplicated numbers -
    numbers are repaired from the running sequence and every repair is
    flagged);
  * mineral_symbols_raster: symbol blobs detected in the raster base map, with
    colour / size signature, the candidate legend symbols for that signature,
    and the nearest numbered locality;
  * the raster base map and the legend symbol sheet as georeferenced /
    cropped PNGs, a preview, georeferencing.json and qa_report.json.

Usage:  python extract_mineral_map.py <map.pdf> <output_dir>
Requires: pikepdf, pymupdf, shapely, pyshp, numpy, pillow, scipy (pyogrio
optional for the GeoPackage bundle).
"""
import collections
import csv
import json
import math
import os
import re
import sys

import numpy as np
from scipy import ndimage
import pikepdf
import shapefile
import shapely
from PIL import Image, ImageOps
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize

from extract_shapefiles import (ShpOut, WGS84_PRJ, assemble_words, chain_fragments, geo_area_km2, geo_length_km,
                                geo_perimeter_km, merge_double_lines, parse_content, shapely_to_shp_geom)

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

# EXPLANATIONS table layout: the 8 text columns (x ranges in pt) with the x of
# the "minerals" sub-column of each block.  Blocks run top->bottom, zone
# letters change at the big "BB"/"CC"/"FF" headers printed inside a block.
TABLE_BLOCKS = [  # (x_min, x_max, minerals_x)
    (2200, 2420, 2383), (2420, 2600, 2519), (2600, 2770, 2723), (2770, 2920, 2887),
    (2920, 3110, 3060), (3110, 3280, 3236), (3280, 3440, 3413), (3440, 3640, 3547)]
# Layout quirk of the printed table: zone B's last rows (156-164 Gwagwada ...
# Rafi Gusu River, all southern Kaduna) are typeset at the foot of the D column
# (block 3, below y=320 pt) after D's own list ends.
TABLE_ZONE_OVERRIDES = [(3, 320.0, 'B')]   # (block number, rows with y below this, zone)

# Mineral codes used in the EXPLANATIONS table -> legend name.  The map legend
# prints codes only for a few entries (mc, mi, m, mo, ni, py, r, ss, sl, ag, tc,
# ta, ts, tpz, tm, tr, u, w, zr); the rest is standard chemical/industrial
# shorthand matched to the legend names.  'confidence' says how sure the
# expansion is; unknown codes are kept verbatim and flagged.
CODE_DICT = {
    'Ab': ('Asbestos / Serpentine', 'probable'), 'Ag': ('Silver', 'legend'), 'Aq': ('Beryl, Aquamarine, Emerald', 'probable'),
    'Au': ('Gold', 'certain'), 'Ba': ('Baryte', 'certain'), 'Bc': ('Brick Clay', 'probable'), 'Bcl': ('Ball Clay', 'probable'),
    'Be': ('Beryl, Aquamarine, Emerald', 'certain'), 'Bi': ('Bismuth', 'probable'), 'Bit': ('Bitumen', 'certain'),
    'Bn': ('Bentonite', 'certain'), 'Br': ('Brine', 'probable'), 'Bx': ('Bauxitic Clay', 'probable'),
    'C': ('Coal', 'certain'), 'Ca': ('Calcite', 'probable'), 'Cl': ('Clay / Pottery Clay', 'certain'),
    'Cor': ('Corundum, Sapphire & Ruby', 'certain'), 'Cr': ('Chromite', 'certain'), 'Cu': ('Copper minerals', 'certain'),
    'Dl': ('Dolomite (not in legend)', 'probable'), 'Ds': ('Dimension Stone', 'certain'), 'Dt': ('Diatomite', 'certain'),
    'E': ('Beryl, Aquamarine, Emerald', 'probable'), 'Ev': ('Evaporite', 'certain'), 'Fc': ('Fire Clay', 'probable'),
    'Fe': ('Iron Ore (Magnetite, Ilmenite)', 'certain'), 'Fl': ('Flourite', 'probable'), 'Fr': ('Flourite', 'probable'),
    'Fp': ('Feldspar', 'certain'), 'G': ('Gold (typo for Au?)', 'uncertain'), 'Gm': ('Gemstone (not in legend)', 'uncertain'),
    'Gn': ('Garnet', 'probable'), 'Gr': ('Graphite', 'probable'), 'Gs': ('Glass Sand', 'certain'), 'Gvl': ('River Gravel', 'certain'),
    'Gy': ('Gypsum', 'certain'), 'Ilm': ('Iron Ore (Magnetite, Ilmenite)', 'certain'), 'Ka': ('Kaolin / kaolinitic clay', 'certain'),
    'Ks': ('Kaolinitic sand/clay (not in legend)', 'uncertain'), 'Ky': ('Kyanite', 'certain'), 'Lg': ('Lignite', 'certain'),
    'Li': ('Lithium (Ambligonite, Kunzite, Moganite, Spodumene, etc)', 'certain'), 'Lp': ('Lepidolite', 'certain'),
    'Ls': ('Limestone', 'certain'), 'M': ('Mica', 'legend'), 'Mb': ('Marble', 'certain'), 'Mc': ('Marcasite', 'legend'),
    'Mg': ('Magnesite', 'certain'), 'Mi': ('Marl', 'legend'), 'Ml': ('Marl', 'probable'), 'Mn': ('Manganese', 'certain'),
    'Mo': ('Molybdenite', 'legend'), 'Mu': ('Mica (muscovite)', 'probable'), 'Mz': ('Monazite', 'certain'),
    'Na': ('Saltlake/ Potash (salt)', 'probable'), 'Nb': ('Columbite', 'certain'), 'Ni': ('Nickel', 'legend'),
    'Oil': ('Oil and Gas', 'certain'), 'P': ('Phosphate', 'certain'), 'Pb': ('Lead - Zinc (lead)', 'certain'),
    'Pbs': ('Galena', 'probable'), 'Pr': ('Phosphate Rock', 'probable'), 'Ps': ('Psammite', 'probable'),
    'Py': ('Pyrite / Pyroclore', 'legend'), 'Qa': ('Quartz (not in legend)', 'uncertain'), 'Qs': ('Quartz sand (not in legend)', 'uncertain'),
    'Qz': ('Quartz (not in legend)', 'uncertain'), 'R': ('Rose Quartz', 'legend'), 'Ru': ('Corundum, Sapphire & Ruby (ruby)', 'certain'),
    'S': ('Sulphur / salt (not in legend)', 'uncertain'), 'Sd': ('Sand (not in legend)', 'uncertain'), 'Sl': ('Sillimanite', 'legend'),
    'Sn': ('Tin / cassiterite (no legend symbol)', 'certain'), 'Ss': ('Silica Sand', 'legend'), 'St': ('Stone? (not in legend)', 'uncertain'),
    'Sul': ('Sulphur (not in legend)', 'probable'), 'Ta': ('Tantalite', 'legend'), 'Tc': ('Talc', 'legend'),
    'Tm': ('Tourmaline', 'legend'), 'To': ('Topaz', 'probable'), 'Tpz': ('Topaz', 'legend'), 'Tr': ('Trona', 'legend'),
    'Ts': ('Tar Sand', 'legend'), 'U': ('Uranium', 'legend'), 'W': ('Wolframite', 'legend'), 'Zn': ('Lead - Zinc (zinc)', 'certain'),
    'Zr': ('Zircon', 'legend'), 'Cz': ('unknown code', 'unknown'), 'Cy': ('unknown code (Clay or Gypsum misprint?)', 'unknown'),
    'Da': ('unknown code', 'unknown'), 'Ke': ('unknown code', 'unknown'), 'Us': ('unknown code', 'unknown'),
    'Cs': ('unknown code', 'unknown'), 'F': ('Flourite', 'probable'), 'Grl': ('River Gravel', 'probable'),
    'Gys': ('Gypsum', 'probable'), 'Ocr': ('Ochre (not in legend)', 'probable'), 'Di': ('Diatomite', 'uncertain'),
    'Ms': ('Mica schist / muscovite (not in legend)', 'uncertain'), 'MS': ('Mica schist / muscovite (not in legend)', 'uncertain'),
    'Sm': ('Tin? (probably a misprint of Sn)', 'uncertain'), 'Rb': ('Ruby? (Corundum, Sapphire & Ruby)', 'uncertain'),
    'La': ('Laterite (not in legend)', 'uncertain'), 'Sr': ('unknown code', 'unknown'), 'Cm': ('unknown code', 'unknown'),
    'RS': ('unknown code', 'unknown'), 'Wa': ('unknown code', 'unknown'), 'Sp': ('unknown code', 'unknown'),
    'Os': ('unknown code', 'unknown'), 'Tn': ('unknown code', 'unknown'), 'In': ('unknown code', 'unknown'),
    'By': ('unknown code', 'unknown'), 'Si': ('unknown code (Silica sand?)', 'unknown'), 'Ma': ('unknown code', 'unknown'),
    'EmI': ('Beryl, Aquamarine, Emerald (emerald; printed "EmI")', 'probable'), 'A': ('unknown code', 'unknown'),
    'MI': ('Marl (printed "MI" for the legend code "mi")', 'probable'), 'PbS': ('Galena (PbS)', 'probable'),
    'm': ('Mica', 'legend'), 'sT': ('unknown code', 'unknown'),
}
# OCR variants seen in the table text
CODE_ALIASES = {'CI': 'Cl', 'Ci': 'Cl', 'cl': 'Cl', 'ka': 'Ka', 'GS': 'Gs', 'SS': 'Ss', 'ML': 'Ml', 'ilm': 'Ilm',
                'OIL': 'Oil', 'au': 'Au', 'AU': 'Au', 'PB': 'Pb', 'ZN': 'Zn', 'sn': 'Sn', 'TA': 'Ta', 'NB': 'Nb',
                'Pbs': 'Pbs', 'Bcl': 'Bcl', 'bc': 'Bc', 'Tpz': 'Tpz', 'tpz': 'Tpz', 'Zr': 'Zr', 'zr': 'Zr'}

# commodity group of every legend mineral name (first matching rule wins)
COMMODITY_GROUPS = [
    ('energy',               r'coal|lignite|bitumen|tar sand|oil and gas|uranium'),
    ('precious metals',      r'gold|silver'),
    ('ferrous metals',       r'iron ore|manganese|chromite|nickel|molybden'),
    ('base metals',          r'copper|lead|zinc|galena|bismuth'),
    ('rare metals',          r'\btin\b|cassiterite|columbite|tantalite|lithium|lepidolite|wolfram|monazite|zircon|pyroclore'),
    ('gemstones',            r'beryl|aquamarine|emerald|corundum|sapphire|ruby|garnet|tourmaline|topaz|rose quartz|gemstone'),
    ('industrial minerals',  r'baryte|bentonite|feldspar|flourite|fluorite|gypsum|kaolin|kyanite|sillimanite|talc|mica|magnesite|'
                             r'diatomite|phosphate|graphite|asbestos|serpentine|calcite|trona|evaporite|brine|salt|potash|pyrite|'
                             r'marcasite|sulphur|ochre'),
    ('construction materials', r'limestone|marble|dolomite|dimension stone|clay|glass sand|silica sand|gravel|sand|laterite|marl|'
                               r'psammite|quartz|stone'),
]


def commodity_group(name):
    n = name.lower()
    if n.startswith('unknown code'):
        return 'unknown'
    for grp, rx in COMMODITY_GROUPS:
        if re.search(rx, n):
            return grp
    return 'unknown'


def load_host_geology(script_dir):
    """Geology units of the geological-map extraction (shapefiles/geology_units.shp) as an STRtree, if present.
    Used to tag mineral points with the rock unit they fall in (both maps are ~1:2 M, so this is a +-10 km statement)."""
    fn = os.path.join(script_dir, 'shapefiles', 'geology_units.shp')
    if not os.path.exists(fn):
        return None
    from shapely.strtree import STRtree
    from shapely.geometry import shape
    r = shapefile.Reader(fn)
    names = [f[0] for f in r.fields[1:]]
    geoms, recs = [], []
    for sr in r.iterShapeRecords():
        rec = dict(zip(names, sr.record))
        if rec.get('dup_of'):
            continue
        g = shape(sr.shape.__geo_interface__)
        if g.is_empty:
            continue
        geoms.append(g)
        recs.append(rec)
    tree = STRtree(geoms)

    def lookup(lon, lat):
        pt = Point(lon, lat)
        hits = tree.query(pt, predicate='within')
        if len(hits) == 0:
            return None
        # the smallest unit containing the point (islands / inliers are drawn on top of the host)
        i = min(hits, key=lambda k: geoms[k].area)
        return recs[i]
    return lookup


# raster symbol palette (RGB as rendered in the base strips) -> colour class
SYMBOL_PALETTE = {
    'yellow': (255, 245, 0), 'khaki': (151, 148, 107), 'green': (0, 146, 63), 'red': (218, 37, 29),
    'purple': (151, 69, 120), 'light green': (132, 194, 37), 'grey': (130, 130, 130), 'dark grey': (96, 93, 92),
    'blue grey': (102, 122, 179), 'brown': (192, 128, 64), 'bright green': (0, 255, 0), 'orange': (231, 120, 23),
    'tan': (187, 130, 91), 'green 2': (0, 160, 64), 'dark tan': (149, 127, 102), 'violet': (132, 0, 168),
    'dark blue': (0, 77, 168), 'purple 2': (169, 0, 230), 'magenta': (224, 32, 128),
}
WATER_LINE_RGB = (80, 100, 235)          # river / lake outlines drawn in the raster - excluded from symbol detection
SYMBOL_OUTLINE_RGB = (31, 26, 23)        # outline / letter colour of the symbols (line-work is pure black)

# (colour class, size, fill) -> candidate legend symbols.  Derived from the
# legend sheet (colour / shape) and calibrated on the map itself: for every
# single-mineral locality of the EXPLANATIONS table the blob signatures within
# 22 pt of its number were tallied (e.g. 'Au' -> yellow 8x8 solid, 'Br' ->
# yellow 8x8 sparse = circle with a letter, 'Gy'/'Ba'/'P' -> outline 10x4 =
# arc of a white circle, 'Ta' -> outline 17x10 = white bowl, 'C' -> outline
# 12x6 solid = coal bar, 'Ls' -> green 7x7 / 10x10 sparse = hatched square).
# Sizes are the extent of the colour body in raster pixels (1 px ~ 0.96 pt);
# fill = body pixels / bounding box: 'solid' >= 0.88, 'round' 0.68-0.88,
# 'sparse' < 0.68 (triangles, diamonds, hatching, letters eating the body).
ANY = ('solid', 'round', 'sparse')
SYMBOL_RULES = [
    # colour,        min w, max w, min h, max h, fill classes, candidates (legend names)
    ('yellow',        12, 17, 9, 12, ANY, ['Clay / Pottery Clay', 'Dimension Stone']),
    ('yellow',         8,  9, 8,  9, ('solid',), ['Gold']),
    ('yellow',         7, 10, 7, 10, ('round', 'sparse'), ['Brine', 'Evaporite', 'Saltlake/ Potash', 'Marcasite', 'Pyrite / Pyroclore']),
    ('yellow',         6,  7, 6,  7, ANY, ['Gold', 'Psammite', 'Glass Sand']),
    ('yellow',         9, 12, 9, 13, ANY, ['Glass Sand', 'Psammite', 'Pyrite / Pyroclore', 'Gold']),
    ('yellow',         3,  5, 7, 10, ANY, ['Bentonite']),
    ('khaki',         11, 17, 8, 12, ANY, ['Kaolin / kaolinitic clay']),
    ('light green',   11, 17, 8, 12, ANY, ['Wolframite']),
    ('green',          9, 12, 9, 12, ('solid', 'round'), ['Ball Clay', 'Brick Clay', 'Corundum, Sapphire & Ruby', 'Diatomite', 'Magnesite']),
    ('green',          9, 12, 9, 12, ('sparse',), ['Limestone', 'Marl']),
    ('green',          6,  8, 6,  8, ('sparse',), ['Limestone', 'Galena', 'Marl']),
    ('green',          6,  8, 6,  8, ('solid', 'round'), ['Manganese', 'Topaz']),
    ('green',         10, 14, 5,  7, ANY, ['Fire Clay']),
    ('green',         13, 20, 9, 14, ANY, ['Limestone', 'Marl']),
    ('green 2',        6, 12, 6, 12, ANY, ['Manganese', 'Topaz', 'Kyanite']),
    ('bright green',  10, 15, 10, 16, ANY, ['Lithium (Ambligonite, Kunzite, Moganite, Spodumene, etc)']),
    ('red',            6,  9, 8, 10, ANY, ['Lead - Zinc']),
    ('red',           14, 18, 7, 10, ANY, ['Feldspar']),
    ('red',            3,  5, 5,  7, ANY, ['Marble', 'Rose Quartz']),
    ('red',            9, 12, 6,  9, ANY, ['Tourmaline']),
    ('red',           14, 18, 10, 12, ANY, ['Chromite', 'Lepidolite']),
    ('red',           10, 13, 10, 13, ANY, ['Asbestos / Serpentine', 'Chromite', 'Lepidolite']),
    ('purple',         9, 11, 6,  8, ANY, ['Iron Ore (Magnetite, Ilmenite)']),
    ('purple',         7,  9, 7,  9, ANY, ['Talc', 'Molybdenite']),
    ('purple',        10, 16, 8, 12, ANY, ['Garnet', 'Iron Ore (Magnetite, Ilmenite)']),
    ('dark grey',     11, 13, 7,  9, ANY, ['Columbite']),
    ('grey',          10, 12, 10, 12, ANY, ['Silver', 'Bismuth']),
    ('blue grey',      8, 11, 8, 11, ANY, ['Mica', 'Uranium']),
    # 'dark blue' (0,77,168) occurs as 9 small bars; no legend symbol has that colour -> no candidates
    ('brown',          3,  8, 3,  9, ANY, ['Granite', 'Bauxitic Clay']),
    ('tan',            7, 12, 7, 12, ANY, ['Silica Sand', 'Bauxitic Clay']),
    ('dark tan',       7, 12, 3, 12, ANY, ['Bauxitic Clay', 'Granite', 'Silica Sand']),
    ('orange',         5, 12, 1, 12, ANY, ['Zircon', 'Flourite']),
    ('violet',         5, 13, 1, 12, ANY, ['Monazite', 'Molybdenite']),
    ('purple 2',       8, 12, 8, 12, ANY, ['Molybdenite', 'Talc']),
    ('magenta',        2, 10, 4, 16, ANY, ['Lepidolite', 'Marble']),
    ('outline',       11, 14, 5,  7, ('solid', 'round'), ['Coal']),
    ('outline',        9, 11, 3,  5, ANY, ['Gypsum', 'Baryte', 'Phosphate', 'Phosphate Rock', 'Trona', 'Bitumen']),
    ('outline',        9, 13, 9, 13, ANY, ['Gypsum', 'Baryte', 'Phosphate', 'Phosphate Rock', 'Trona', 'Bitumen',
                                           'Graphite', 'River Gravel', 'Sillimanite', 'Lignite', 'Tar Sand', 'Kyanite']),
    ('outline',       15, 19, 8, 12, ANY, ['Tantalite', 'Oil and Gas']),
    ('outline',       11, 15, 7, 12, ANY, ['Oil and Gas', 'Tantalite', 'Graphite', 'Sillimanite']),
    ('outline',        5,  7, 4,  6, ANY, ['Beryl, Aquamarine, Emerald']),
    ('outline',        5,  8, 6, 12, ANY, ['Zircon', 'Monazite', 'Beryl, Aquamarine, Emerald']),
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def fix_type0(s):
    """ArcMap's Type0 fonts (here: ArialMT, Identity CMap) use 2-byte codes that
    are Unicode values - the generic parser decoded the raw bytes as cp1252
    (leaving NUL characters, and e.g. an em dash U+2014 as ' \\x14'); undo that."""
    try:
        raw = s.encode('cp1252', errors='replace')
        if len(raw) % 2:
            return s.replace('\x00', '')
        return raw.decode('utf-16-be', errors='replace')
    except Exception:
        return s.replace('\x00', '')


def group_glyphs_by_geometry(runs, max_dy=0.3, min_adv=0.3, max_adv=0.7):
    """Assemble one-character text runs into labels by geometry AND drawing
    order: same baseline, same size, next glyph starts 0.3-0.7 em to the right
    (the digit advance is 0.57 em, 0.48 em after a '1'; the smallest gap seen
    between two neighbouring labels on one baseline is 0.81 em) and the glyph
    is the next one in the content stream.  The sequence test matters for the
    mineral numbers: the single-digit labels (1-9 of every zone) and two stray
    '0' glyphs are drawn in a separate early pass, and two of those sit exactly
    one advance to the right of another label ('46' + stray '0' would read as
    '460', '1' + '10' as '110')."""
    runs = sorted(runs, key=lambda r: (round(r['y'], 1), r['x']))
    labels, cur = [], None
    for r in runs:
        if cur is not None:
            p = cur[-1]
            dx = r['x'] - p['x']
            if abs(r['y'] - p['y']) <= max_dy * p['size'] and min_adv * p['size'] <= dx <= max_adv * p['size'] \
                    and abs(r['size'] - p['size']) < 0.05 and r['seq'] == p['seq'] + 1:
                cur.append(r)
                continue
            labels.append(cur)
        cur = [r]
    if cur:
        labels.append(cur)
    out = []
    for rs in labels:
        out.append({'text': ''.join(r['text'] for r in rs), 'x0': rs[0]['x'], 'y0': rs[0]['y'], 'x1': rs[-1]['x'],
                    'size': rs[0]['size'], 'font': rs[0]['font'], 'layer': rs[0]['layer'], 'seq': rs[0]['seq'],
                    'nchar': len(rs)})
    return out


def label_box(w):
    """Approximate bounding box (x0, y0, x1, y1) of a horizontal label."""
    adv = 0.57 if w['font'].startswith('Arial') else 0.5
    width = max(w.get('x1', w['x0']) - w['x0'] + adv * w['size'], adv * w['size'] * len(w['text']))
    return (w['x0'], w['y0'] - 0.2 * w['size'], w['x0'] + width, w['y0'] + 0.75 * w['size'])


def label_centre(w):
    b = label_box(w)
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def assemble_curved_labels(runs, letter_gap=1.25, word_gap=2.6):
    """Re-assemble one-glyph text runs that follow a curve (river names: every
    glyph has its own rotation, so baseline/angle-based assembly breaks them
    into fragments).  Consecutive runs (drawing order) of the same font/size
    are chained while the distance between successive glyph origins is at most
    word_gap em; a gap above letter_gap em becomes a space ('RIVER BENUE').
    Returns dicts with text, mean position, mean angle and glyph count."""
    runs = sorted(runs, key=lambda r: r['seq'])
    out, cur = [], None
    for r in runs:
        if cur is not None:
            p = cur['glyphs'][-1]
            dd = math.hypot(r['x'] - p['x'], r['y'] - p['y'])
            if r['seq'] == p['seq'] + 1 and abs(r['size'] - p['size']) < 0.05 and r['font'] == p['font'] \
                    and (r['text'] == ' ' or dd <= word_gap * p['size']):
                if r['text'] != ' ' and dd > letter_gap * p['size'] * max(1, len(p['text'].strip())):
                    cur['text'] += ' '
                cur['text'] += r['text']
                cur['glyphs'].append(r)
                continue
            out.append(cur)
        cur = {'text': r['text'], 'glyphs': [r]}
    if cur is not None:
        out.append(cur)
    res = []
    for w in out:
        g = w['glyphs']
        text = ' '.join(w['text'].split())
        if not text:
            continue
        res.append({'text': text, 'x': sum(t['x'] for t in g) / len(g), 'y': sum(t['y'] for t in g) / len(g),
                    'angle': sum(t['angle'] for t in g) / len(g), 'size': g[0]['size'], 'font': g[0]['font'],
                    'layer': g[0]['layer'], 'seq': g[0]['seq'], 'nglyph': len(g)})
    return res


def extend_line(coords, d):
    c = list(coords)
    if len(c) < 2:
        return LineString(c)

    def ext(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        return (b[0] + dx / n * d, b[1] + dy / n * d)
    return LineString([ext(c[1], c[0])] + c + [ext(c[-2], c[-1])])


# --------------------------------------------------------------------------
# georeferencing from the GeoPDF viewport
# --------------------------------------------------------------------------

def read_viewport(page):
    vp = page.VP[0]
    bbox = [float(v) for v in vp.BBox]            # [x0, y_top, x1, y_bottom] in page pt
    meas = vp.Measure
    gpts = [float(v) for v in meas.GPTS]          # lat, lon pairs
    lpts = [float(v) for v in meas.LPTS]          # unit-square coordinates (u right, v DOWN from top)
    wkt = str(meas.GCS.get('/WKT', ''))
    x0, ytop, x1, ybot = bbox
    pairs = []
    for i in range(0, len(gpts), 2):
        lat, lon = gpts[i], gpts[i + 1]
        u, v = lpts[i], lpts[i + 1]
        x = x0 + u * (x1 - x0)
        y = ytop - v * (ytop - ybot)
        pairs.append((x, y, lon, lat))
    xs = sorted(set(round(p[0], 5) for p in pairs))
    ys = sorted(set(round(p[1], 5) for p in pairs))
    lons = sorted(set(p[2] for p in pairs))
    lats = sorted(set(p[3] for p in pairs))
    a = (lons[-1] - lons[0]) / (xs[-1] - xs[0])
    b = lons[0] - a * xs[0]
    c = (lats[-1] - lats[0]) / (ys[-1] - ys[0])
    d = lats[0] - c * ys[0]
    info = {'bbox_pt': {'x0': x0, 'y_top': ytop, 'x1': x1, 'y_bottom': ybot}, 'GPTS': gpts, 'LPTS': lpts,
            'gcs_wkt': wkt, 'affine': {'lon = a*x + b': [a, b], 'lat = c*y + d': [c, d]},
            'points_per_degree': {'x': 1 / a, 'y': 1 / c}, 'control_points': pairs}
    return (a, b, c, d), info


# --------------------------------------------------------------------------
# EXPLANATIONS table
# --------------------------------------------------------------------------

NUM_RE = re.compile(r'^\s*([0-9IlOSB]{1,3})([A-Z]?)\s*[\.\s]\s*(.*)$')
NUM_GLUED_RE = re.compile(r'^\s*([0-9]{1,3})([A-Za-z].*)$')
NUM_SUFFIX_GLUED_RE = re.compile(r'^\s*([0-9IlO]{1,3})([A-Z])(?=[A-Z][a-z])(.*)$')   # 'I7ADutsin- Ma' = 17A Dutsin-Ma
CODE_TOKEN = re.compile(r'^[A-Za-z]{1,3}\.?$')


def garbled_number(s):
    """Leading token that is not readable as a number but sits where the number
    should be ('SB Afogun', '"7  Vera Hills', 'I7ADutsin- Ma').  Returns
    (token, rest) or None."""
    s = s.strip()
    i = 0
    while i < len(s) and i < 4 and (not s[i].islower() or s[i] == 'l') and not s[i].isspace():
        i += 1
    tok, rest = s[:i], s[i:]
    if rest[:1].islower() and tok[-1:].isalpha() and tok[-1:] != 'l':   # last capital belongs to the name ('I7A' + 'Dutsin')
        tok, rest = tok[:-1], tok[-1:] + rest
    had_dot = tok.endswith('.')
    tok = tok.rstrip('.')
    if not tok or len(tok) > 3 or ((tok in CODE_DICT or tok in CODE_ALIASES) and not had_dot):
        return None
    if not rest.strip() or not (rest[0].isspace() or rest[0].isupper()):
        return None
    if len(tok) == 1 and tok.isalpha() and not had_dot and tok not in ('I', 'l'):
        return None
    return tok, rest.strip()


def parse_number_token(tok):
    t = tok.replace('I', '1').replace('l', '1').replace('O', '0').replace('S', '5').replace('B', '8')
    return int(t) if t.isdigit() else None


def split_codes(s):
    toks = [t for t in re.split(r'[\s,;/()]+|\.(?=\s|$)|\.(?=[A-Z])', s) if t and t != '.']
    out = []
    for t in toks:
        t = t.strip('.,;:')
        if not t:
            continue
        t = CODE_ALIASES.get(t, t)
        out.append(t)
    return out


def is_code_token(tok):
    """True when a token of the name cell is a mineral code (also 'Ta.Nb.W' chains, '(Gys)', 'SI')."""
    tok = tok.strip('().,;:')
    if not tok:
        return False
    parts = [t for t in tok.split('.') if t]
    return all(CODE_TOKEN.match(t) and (t in CODE_DICT or t in CODE_ALIASES or t.capitalize() in CODE_DICT) for t in parts)


def split_codes_from_name(name):
    """The table sometimes prints the codes inside the locality cell.  Peel code tokens off the end of the name
    ("Orukpa C", "AFU HILL Sn. Ta.Nb.W", "Odaru (Gys)") or split a code glued to the last word ("AgilaBr.Ka",
    "IkpaBa", "ljerLs").  Returns (name, codes, changed)."""
    toks = name.split()
    tail = []
    while len(toks) > 1 and is_code_token(toks[-1]):
        tail.insert(0, toks.pop().strip('()'))
    if tail:
        return ' '.join(toks), ' '.join(tail), True
    mg = re.match(r'^(.*?[a-z]{2})((?:[A-Z][a-z]{0,2})(?:\.[A-Z][a-z]{0,2})*)$', name)
    if mg and all(t in CODE_DICT for t in mg.group(2).split('.')) and len(mg.group(1).split()[-1]) >= 3:
        return mg.group(1), mg.group(2), True
    return name, '', False


def fix_name_glitches(name):
    """The EXPLANATIONS table text carries OCR-type glitches in the locality names.  Only patterns that are
    never a real spelling are corrected (the printed form is kept in the entry's flags and raw text):
      * word-initial 'l' before a capital or a consonant is a capital I  ('lFE', 'ljebu-Ode', 'lgbo', 'lkara')
      * a capital 'I' between two lower-case letters is an 'l'            ('MaIlam', 'OrIu', 'AjiaIa', 'fieId')
      * a capital 'I' after the capital of a capitalised word, or before 'll', is an 'i'  ('HIlls', 'hIlls')
      * 'II' at the start of a word before lower case is 'Il'            ('lIe' -> 'IIe' -> 'Ile')
      * 'q' not followed by 'u' is a 'g'                                  ('Kaltunqo', 'Kaqoro', 'Alaqbede')
      * a digit 0 inside an all-capital word is the letter O               ('KAN0')
    """
    fixed = re.sub(r"(?<![A-Za-z])l(?=[A-Z]|[bcdfgjkmnpqrstvxz])", 'I', name)
    fixed = re.sub(r"(?<![A-Za-z])II(?=[a-z])", 'Il', fixed)
    fixed = re.sub(r"(?<=[A-Za-z])I(?=ll)", 'i', fixed)                       # 'hIlls' ('lll' never occurs)
    fixed = re.sub(r"(?<=[a-z])I(?=[a-z])", 'l', fixed)
    fixed = re.sub(r"(?<![A-Za-z])([A-Z])I(?=[a-z]{2})", r"\1i", fixed)
    fixed = re.sub(r"q(?!u)", 'g', fixed)
    fixed = re.sub(r"(?<=[A-Z])0(?=[A-Z]|\b)|(?<=[A-Z]{2})0", 'O', fixed)
    return fixed


def expand_codes(codes):
    names, unknown, conf = [], [], []
    for c in codes:
        key = c if c in CODE_DICT else (c.capitalize() if c.capitalize() in CODE_DICT else None)
        if key is None:
            unknown.append(c)
            names.append(c + ' (?)')
            conf.append('unknown')
        else:
            names.append(CODE_DICT[key][0])
            conf.append(CODE_DICT[key][1])
            if CODE_DICT[key][1] == 'unknown':
                unknown.append(c)
    return names, unknown, conf


def parse_table(words):
    """Return list of entry dicts from the EXPLANATIONS table text."""
    tab = [w for w in words if w['layer'] == 'Other 2' and w['x0'] > 2051 and not (w['x0'] > 3380 and w['y0'] < 335)]
    entries_w = [w for w in tab if 9.5 < w['size'] < 10.5 and w['text'].strip()]
    headers = [w for w in tab if w['size'] > 19 and re.fullmatch(r'[A-G]{1,2}', w['text'].strip())]

    def x_eff(w):
        """x of the first non-blank character (strings may start with spaces)."""
        lead = len(w['text']) - len(w['text'].lstrip(' '))
        return w['x0'] + lead * 0.278 * w['size']

    def block_of(x):
        for i, b in enumerate(TABLE_BLOCKS):
            if b[0] <= x < b[1]:
                return i
        return None

    table, problems = [], []
    zone_prev_end = None
    for bi, b in enumerate(TABLE_BLOCKS):
        ws = sorted([w for w in entries_w if block_of(x_eff(w)) == bi], key=lambda w: -w['y0'])
        hs = sorted([h for h in headers if block_of(h['x0']) == bi], key=lambda h: -h['y0'])
        rows = []
        for w in ws:
            if rows and abs(rows[-1][0] - w['y0']) <= 3.5:
                rows[-1][1].append(w)
            else:
                rows.append([w['y0'], [w]])
        top_hdr = [h for h in hs if h['y0'] > 1800]
        zone = top_hdr[0]['text'][0] if top_hdr else zone_prev_end
        mid_hdrs = [h for h in hs if h['y0'] <= 1800]
        last = None
        for y, rw in rows:
            for h in mid_hdrs:
                if y < h['y0'] - 2 and not h.get('_used'):
                    zone = h['text'][0]
                    h['_used'] = True
            row_zone = zone
            for ob, oy, oz in TABLE_ZONE_OVERRIDES:
                if ob == bi + 1 and y < oy:
                    row_zone = oz
            rw.sort(key=lambda w: w['x0'])
            # split a row that contains a second numbered entry (stray word glued in front)
            segments, cur = [], []
            for w in rw:
                if cur and x_eff(w) < b[2] - 12 and NUM_RE.match(w['text']) and not NUM_RE.match(' '.join(x['text'] for x in cur)):
                    segments.append(cur)
                    cur = []
                cur.append(w)
            segments.append(cur)
            for seg in segments:
                name_words = [w for w in seg if x_eff(w) < b[2] - 12]
                min_words = [w for w in seg if x_eff(w) >= b[2] - 12]
                name_txt = ' '.join(w['text'] for w in name_words).strip()
                min_txt = ' '.join(w['text'] for w in min_words).strip()
                m = NUM_RE.match(name_txt)
                m3 = NUM_SUFFIX_GLUED_RE.match(name_txt)
                if m and parse_number_token(m.group(1)) is not None:
                    num_tok, suffix, rest = m.group(1), m.group(2), m.group(3)
                elif m3 and parse_number_token(m3.group(1)) is not None:
                    num_tok, suffix, rest = m3.group(1), m3.group(2), m3.group(3)
                else:
                    m2 = NUM_GLUED_RE.match(name_txt)
                    if m2:
                        num_tok, suffix, rest = m2.group(1), '', m2.group(2)
                    else:
                        num_tok = None
                forced = None
                if num_tok is not None and not any(ch.isdigit() for ch in num_tok):
                    # all-letter "number" ('SE.', 'SI.', 'S.', 'lOB.'): take it from the running sequence instead
                    forced = (num_tok + suffix, rest.strip())
                    num_tok = None
                if num_tok is not None:
                    num = parse_number_token(num_tok)
                    rest = rest.strip()
                    parts = re.split(r'\s{2,}', rest)
                    name, extra = parts[0].strip(), ' '.join(parts[1:]).strip()
                    if extra and not all(t.strip('.,') in CODE_DICT or t.strip('.,') in CODE_ALIASES or t.strip('.,').isdigit()
                                         for t in re.split(r'[\s,;/.]+', extra) if t.strip('.,')):
                        name, extra = (name + ' ' + extra).strip(), ''       # 'Mai  Samari' is a name, not codes
                    mins = (extra + ' ' + min_txt).strip()
                    flags = []
                    if not num_tok.isdigit():
                        flags.append('number token "%s" read as %d' % (num_tok, num))
                    if suffix:
                        flags.append('number suffix "%s" in source (inserted entry)' % suffix)
                    if not mins:
                        # codes glued to the name ("Orukpa C", "AgilaBr.Ka", "LOKOJA (AGBAJA) Fe",
                        # "AFU HILL Sn. Ta.Nb.W", "Odaru (Gys)", "IkpaBa", "ljerLs")
                        name, mins, split = split_codes_from_name(name)
                        if split:
                            flags.append('codes split from name cell')
                    last = {'zone': row_zone, 'number': num, 'number_printed': num_tok + suffix, 'locality': name,
                            'minerals_raw': mins, 'block': bi + 1, 'y': y, 'flags': flags, 'suffix': suffix,
                            'raw': (name_txt + ' | ' + min_txt).strip()}
                    table.append(last)
                elif (forced or garbled_number(name_txt)) and (last is None or last['y'] - y > 7):
                    # garbled number token ("SB Afogun", '"7  Vera Hills', "I7ADutsin- Ma") -> new entry,
                    # number inferred from the running sequence below
                    tok, rest = forced or garbled_number(name_txt)
                    parts = re.split(r'\s{2,}', rest.strip())
                    name, extra = parts[0].strip(), ' '.join(parts[1:]).strip()
                    mins = (extra + ' ' + min_txt).strip()
                    flags = ['number token "%s" unreadable - inferred from sequence' % tok]
                    if not mins:
                        name, mins, split = split_codes_from_name(name)
                        if split:
                            flags.append('codes split from name cell')
                    guess = parse_number_token(tok.replace('•', ''))
                    last = {'zone': row_zone, 'number': None, 'number_printed': tok, 'locality': name,
                            'minerals_raw': mins, 'block': bi + 1, 'y': y, 'flags': flags, 'guess': guess,
                            'raw': (name_txt + ' | ' + min_txt).strip()}
                    table.append(last)
                elif last is not None and name_txt and not min_txt:
                    if re.fullmatch(r'[A-Za-z\.,\s/]+', name_txt) and len(name_txt) <= 12 and \
                            all(len(t.strip('.,')) <= 3 for t in name_txt.split()) and \
                            all(t.strip('.,') in CODE_DICT or t.strip('.,') in CODE_ALIASES for t in name_txt.split()):
                        last['minerals_raw'] = (last['minerals_raw'] + ' ' + name_txt).strip()
                    else:
                        last['locality'] = (last['locality'] + ' ' + name_txt).strip()
                        last['flags'].append('name continued on next line')
                elif last is not None and min_txt and not name_txt:
                    if last['y'] - y > 7 and last['minerals_raw']:
                        # a full row below with only the minerals cell: the locality name is missing in the PDF text
                        last = {'zone': row_zone, 'number': None, 'number_printed': '', 'locality': '',
                                'minerals_raw': min_txt, 'block': bi + 1, 'y': y,
                                'flags': ['locality name and number missing in PDF text - number inferred from sequence'],
                                'raw': '| ' + min_txt}
                        table.append(last)
                    else:
                        last['minerals_raw'] = (last['minerals_raw'] + ' ' + min_txt).strip()
                elif name_txt or min_txt:
                    problems.append({'block': bi + 1, 'y': y, 'text': name_txt + ' | ' + min_txt})
        zone_prev_end = zone

    # ---- number repair from the running sequence (per zone, in print order)
    for z in sorted(set(e['zone'] for e in table)):
        rows = [e for e in table if e['zone'] == z]
        for i, e in enumerate(rows):
            prev_n = rows[i - 1]['number'] if i > 0 else 0
            nxt = rows[i + 1]['number'] if i + 1 < len(rows) else None
            if e.get('suffix'):
                if e['number'] != prev_n:
                    e['flags'].append('suffixed entry does not follow its base number (previous %d)' % prev_n)
                continue
            if i > 0 and rows[i - 1].get('suffix'):
                prev_n = rows[i - 1]['number']
            if e['number'] is None:
                e['number'] = prev_n + 1
                if nxt is not None and nxt != prev_n + 2:
                    e['flags'].append('sequence ambiguous around inferred number (next printed %s)' % nxt)
                if e.get('guess') not in (None, e['number']):
                    e['flags'].append('letter-for-digit reading would give %d' % e['guess'])
                continue
            exp = prev_n + 1
            one_char = (len(str(e['number'])) == len(str(exp)) and sum(x != y for x, y in zip(str(e['number']), str(exp))) == 1)
            if e['number'] != exp and nxt is not None and nxt == prev_n + 2:
                e['flags'].append('printed number %s out of sequence - corrected to %d' % (e['number_printed'], exp))
                e['number'] = exp
            elif e['number'] != exp and (e['number'] < prev_n or e['number'] > prev_n + 20) and one_char \
                    and nxt is not None and exp < nxt:
                e['flags'].append('printed number %s out of sequence (one digit misread) - corrected to %d' % (e['number_printed'], exp))
                e['number'] = exp
            elif e['number'] != exp and prev_n > 0:
                e['flags'].append('out of sequence (previous %d)' % prev_n)
    for e in table:
        codes = split_codes(e['minerals_raw'])
        names, unknown, conf = expand_codes(codes)
        e['codes'] = codes
        e['minerals'] = names
        e['unknown_codes'] = unknown
        e['code_conf'] = conf
        e['locality'] = re.sub(r'\s+', ' ', e['locality']).strip(' .-')
        fixed = fix_name_glitches(e['locality'])
        if fixed != e['locality']:
            e['flags'].append('name printed "%s" (letter glitch corrected)' % e['locality'])
            e['locality'] = fixed
    return table, problems


# --------------------------------------------------------------------------
# raster helpers
# --------------------------------------------------------------------------

def image_placements(data):
    """[(name, a, d, e, f)] for every 'a 0 0 d e f cm /Image_N Do' in the content stream."""
    out = []
    for m in re.finditer(rb'([-\d.]+)\s+0\s+0\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+cm\s+/(Image_\d+)\s+Do', data):
        out.append((m.group(5).decode(), float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))))
    return out


def xobject_image(page, name):
    xo = page.Resources.XObject[pikepdf.Name('/' + name)]
    return pikepdf.PdfImage(xo).as_pil_image().convert('RGB')

# Reference positions (WGS84, city centres, ~1 km) used only to sanity-check the georeferencing.
CAPITAL_REFERENCE = {
    'ABAKILIKI': (8.113, 6.325), 'ABEOKUTA': (3.345, 7.150), 'ADO - EKITI': (5.221, 7.623), 'AKURE': (5.195, 7.251),
    'ASABA': (6.730, 6.198), 'AWKA': (7.072, 6.212), 'BAUCHI': (9.844, 10.314), 'BENIN - CITY': (5.627, 6.335),
    'BIRNIN KEBBI': (4.197, 12.453), 'CALABAR': (8.327, 4.958), 'DAMATURU': (11.961, 11.747), 'DUTSE': (9.338, 11.756),
    'ENUGU': (7.495, 6.441), 'GOMBE': (11.167, 10.290), 'GUSAU': (6.662, 12.163), 'IBADAN': (3.896, 7.378),
    'IKEJA': (3.349, 6.605), 'ILORIN': (4.542, 8.496), 'JALINGO': (11.366, 8.893), 'JOS': (8.892, 9.918),
    'KADUNA': (7.438, 10.523), 'KANO': (8.516, 12.002), 'KATSINA': (7.601, 12.990), 'LAFIA': (8.515, 8.493),
    'LOKOJA': (6.740, 7.802), 'MAIDUGURI': (13.151, 11.846), 'MAKURDI': (8.533, 7.733), 'MINNA': (6.557, 9.614),
    'PORT HARCOURT': (7.013, 4.815), 'SOKOTO': (5.243, 13.062), 'UMUAHIA': (7.491, 5.532), 'UYO': (7.927, 5.038),
    'YOLA': (12.481, 9.209),
}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    qa = {}
    pdf = pikepdf.open(pdf_path)
    page = pdf.pages[0]
    oc_names = {}
    for k, v in page.Resources.get('/Properties', {}).items():
        oc_names[k.lstrip('/')] = (v.objgen[0], str(v.get('/Name', '')).rstrip('\x00'))
    data = page.Contents.read_bytes() if not isinstance(page.Contents, pikepdf.Array) \
        else b''.join(c.read_bytes() for c in page.Contents)
    feats = list(parse_content(data, oc_names))
    paths = [f for f in feats if f['kind'] == 'path']
    texts = [f for f in feats if f['kind'] == 'text']
    type0_fonts = {str(k).lstrip('/') for k, f in page.Resources.Font.items() if str(f.get('/Subtype')) == '/Type0'}
    for t in texts:
        if t['font'] in type0_fonts:
            t['text'] = fix_type0(t['text'])
        t['layer'] = t['layer'].rstrip('\x00')
    for p in paths:
        p['layer'] = p['layer'].rstrip('\x00')
    words = assemble_words(texts)
    print(f'parsed {len(paths)} paths, {len(texts)} text runs -> {len(words)} strings')

    # ---- georeferencing (GeoPDF viewport) + graticule cross-check
    affine, ginfo = read_viewport(page)
    a, b, c, d = affine

    def ll(x, y):
        return (a * x + b, c * y + d)
    FR = ginfo['bbox_pt']
    frame = box(FR['x0'], FR['y_bottom'], FR['x1'], FR['y_top'])
    grat_lines = []
    for p in paths:
        if p['layer'] != 'Graticule' or p['op'] != 'S':
            continue
        for pts, _ in p['subpaths']:
            L = LineString(pts)
            if L.length < 500 or frame.boundary.distance(L) < 2 and frame.boundary.buffer(2).contains(L):
                continue                  # short ticks / the frame itself
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            if abs(x1 - x0) < 1:          # meridian
                lon = a * (x0 + x1) / 2 + b
                grat_lines.append(('lon', (x0 + x1) / 2, lon, round(lon) - lon))
            elif abs(y1 - y0) < 1:        # parallel
                lat = c * (y0 + y1) / 2 + d
                grat_lines.append(('lat', (y0 + y1) / 2, lat, round(lat) - lat))
    grat_lines = sorted(set(grat_lines))
    ginfo['graticule_check'] = [{'axis': g[0], 'page_pt': g[1], 'value_from_VP': g[2], 'printed_label': round(g[2]),
                                 'residual_deg': g[3]} for g in grat_lines]
    par = [g[3] for g in grat_lines if g[0] == 'lat']
    mer = [g[3] for g in grat_lines if g[0] == 'lon']
    ginfo['parallel_max_residual_deg'] = max(map(abs, par)) if par else None
    ginfo['meridian_label_offset_deg'] = (sum(mer) / len(mer)) if mer else None
    ginfo['notes'] = [
        'Affine read from the GeoPDF /VP /Measure dictionary (4 corner GPTS).  lon/lat are linear in page x/y '
        '(Plate Carree data frame, %.3f pt/deg).' % ginfo['points_per_degree']['x'],
        'The PDF declares GCS_Assumed_Geographic_1 (NAD27 / Clarke 1866) - the ArcGIS default for data with an unknown '
        'datum; the data are almost certainly Minna/WGS84-era lat/lon.  Outputs are written as EPSG:4326 (the '
        'difference is far below the ~1.2 km/pixel resolution of the raster symbols).',
        'Cross-check 1 (parallels): the %d long parallels fall on whole degrees of the /VP affine within %.4f deg - OK.'
        % (len(par), ginfo['parallel_max_residual_deg'] or 0),
        'Cross-check 2 (meridians): the %d long meridians are labelled 4..14 E but sit at %.3f deg LARGER longitude in '
        'the /VP affine (about %.0f km).  The printed meridian labels and the embedded georeferencing disagree; the '
        'capital-city check in qa_report.json (capital_check_km) shows the /VP affine is the better of the two, so it '
        'is used for every layer.  The graticule layer carries both values (printed label and VP value).'
        % (len(mer), -(ginfo['meridian_label_offset_deg'] or 0), -(ginfo['meridian_label_offset_deg'] or 0) * 110)]
    with open(os.path.join(out_dir, 'georeferencing.json'), 'w') as f:
        json.dump(ginfo, f, indent=2, default=float)
    print('georef: %.3f pt/deg; parallels within %.4f deg of whole degrees; meridian labels offset %.3f deg from VP' % (
        ginfo['points_per_degree']['x'], ginfo['parallel_max_residual_deg'] or 0, ginfo['meridian_label_offset_deg'] or 0))

    # ---- zones A-G from the division lines + frame
    div_lines = [extend_line(s[0], 20) for p in paths if p['layer'] == 'division line' for s in p['subpaths']]
    zone_polys = [pg for pg in polygonize(shapely.union_all([frame.boundary] + div_lines, grid_size=0.5)) if pg.area > 1000]
    big_letters = [t for t in texts if t['layer'] == 'Other 2' and t['x'] < FR['x1'] and round(t['size']) == 48]
    zones = {}
    for pg in zone_polys:
        inside = [t['text'] for t in big_letters if pg.contains(Point(t['x'] + 15, t['y'] + 15))]
        if len(inside) == 1:
            zones[inside[0]] = pg
    assert sorted(zones) == list('ABCDEFG'), sorted(zones)

    def zone_of(x, y):
        pt = Point(x, y)
        for z, pg in zones.items():
            if pg.contains(pt):
                return z
        return None

    # ---- EXPLANATIONS table
    table, problems = parse_table(words)
    qa['table'] = {'entries': len(table), 'unparsed_rows': problems,
                   'per_zone': {z: len([e for e in table if e['zone'] == z]) for z in 'ABCDEFG'},
                   'entries_with_flags': sum(1 for e in table if e['flags']),
                   'unknown_codes': sorted(set(c for e in table for c in e['unknown_codes']))}
    print('table: %d entries, %d unparsed rows, %d flagged' % (len(table), len(problems), qa['table']['entries_with_flags']))
    idx = collections.defaultdict(list)
    for e in table:
        idx[(e['zone'], e['number'])].append(e)

    # ---- number labels on the map (geometry-based assembly)
    num_runs = [t for t in texts if t['layer'] == 'mineral numbers - Default' and t['x'] < FR['x1']]
    all_labels = [l for l in group_glyphs_by_geometry(num_runs) if l['text'].isdigit()]
    stray = [l for l in all_labels if int(l['text']) == 0]      # lone '0' glyphs: no locality is numbered 0
    num_labels = [l for l in all_labels if int(l['text']) != 0]
    for l in num_labels:
        cx, cy = label_centre(l)
        l['cx'], l['cy'] = cx, cy
        l['zone'] = zone_of(cx, cy)
        l['zone_note'] = ''
        l['number'] = int(l['text'])

    # Labels printed on or across a division line can fall in the wrong zone (the number is placed beside the
    # symbol, which may be on the other side).  The numbering of every zone is spatially coherent (consecutive
    # numbers are usually close together), so for labels within DIV_BAND of a division line the zone is chosen
    # by the distance to the nearest labels numbered n-3..n+3 of each candidate zone; a label moves only when the
    # other zone's neighbours are less than half as far away (and < 80 pt) and that zone's list has the number.
    # A few passes let a chain of misplaced labels (e.g. F 8, 9, 10 printed just above the D/F line) resolve.
    DIV_BAND = 20.0
    div_geoms = [LineString(sp) for p in paths if p['layer'] == 'division line' for sp, _ in p['subpaths']]
    for l in num_labels:
        l['div_dist'] = min(g.distance(Point(l['cx'], l['cy'])) for g in div_geoms) if div_geoms else 1e9

    def seq_neighbour_dist(zone, n, lab):
        best = None
        for o in num_labels:
            if o is lab or o['zone'] != zone or not (1 <= abs(o['number'] - n) <= 3):
                continue
            dd = math.hypot(o['cx'] - lab['cx'], o['cy'] - lab['cy'])
            if best is None or dd < best:
                best = dd
        return best
    n_rezoned = 0
    for _pass in range(5):
        moved = 0
        for l in num_labels:
            if l['div_dist'] >= DIV_BAND or l['zone_note']:
                continue
            own = seq_neighbour_dist(l['zone'], l['number'], l)
            best = (own if own is not None else 1e9, l['zone'])
            for z, pg in zones.items():
                if z == l['zone'] or pg.distance(Point(l['cx'], l['cy'])) > DIV_BAND or not idx.get((z, l['number'])):
                    continue
                dz = seq_neighbour_dist(z, l['number'], l)
                if dz is not None and dz < 80 and dz < 0.5 * best[0]:
                    best = (dz, z)
            if best[1] != l['zone']:
                l['zone_note'] = 'printed %.0f pt from the %s/%s division line on the %s side; assigned to %s by numbering sequence' % (
                    l['div_dist'], min(l['zone'], best[1]), max(l['zone'], best[1]), l['zone'], best[1])
                l['zone'] = best[1]
                moved += 1
        n_rezoned += moved
        if not moved:
            break

    label_count = collections.Counter((l['zone'], l['number']) for l in num_labels)
    for l in num_labels:
        hits = idx.get((l['zone'], l['number']), [])
        l['entry'], l['match'] = None, 'number not in table'
        l['n_printed'] = label_count[(l['zone'], l['number'])]
        if hits:
            l['entry'] = hits[0]
            l['match'] = 'exact' if len(hits) == 1 else 'exact (%d table rows share this number)' % len(hits)
            if l['n_printed'] > len(hits):
                # the map face prints this number more than once (all copies are complete labels drawn in the
                # zone's own sequence, so they are not assembly artefacts): every copy gets the same table row
                l['match'] += ' (number printed %dx in zone %s)' % (l['n_printed'], l['zone'])
    dup_numbers = sorted((z, n, c) for (z, n), c in label_count.items() if c > 1 and c > len(idx.get((z, n), [])))
    qa['number_labels'] = {'labels': len(num_labels), 'matched': sum(1 for l in num_labels if l['entry']),
                           'stray_zero_glyphs_dropped': [(round(l['x0'], 1), round(l['y0'], 1)) for l in stray],
                           'rezoned_by_numbering_sequence': [(l['zone_note'], l['number']) for l in num_labels if l['zone_note']],
                           'match_kinds': dict(collections.Counter(l['match'].split(' (')[0] for l in num_labels)),
                           'numbers_printed_more_than_once': dup_numbers,
                           'per_zone': dict(collections.Counter(l['zone'] for l in num_labels)),
                           'unmatched': sorted((l['zone'] or '?', l['number']) for l in num_labels if not l['entry'])}
    lab_keys = set((l['zone'], l['number']) for l in num_labels)
    qa['number_labels']['table_entries_without_label'] = len([e for e in table if (e['zone'], e['number']) not in lab_keys])
    print('number labels: %d (%d stray zero glyphs dropped, %d re-zoned by numbering sequence), matched to table: %d' % (
        len(num_labels), len(stray), n_rezoned, qa['number_labels']['matched']))

    # ---- raster base map (7 strips) + legend symbol sheet
    placements = image_placements(data)
    strips = [p for p in placements if abs(p[1] - (FR['x1'] - FR['x0'])) < 5]
    strips.sort(key=lambda p: -p[4])
    sx = None
    rows_total = 0
    tiles = []
    for name, w_pt, h_pt, ex, fy in strips:
        im = ImageOps.flip(xobject_image(page, name))         # d < 0: rows stored bottom-up
        sx = im.width / w_pt
        tiles.append((im, fy))
    top_y = strips[0][4]
    bottom_y = min(p[4] + p[2] for p in strips)              # d is negative
    H = int(round((top_y - bottom_y) * sx))
    base = Image.new('RGB', (tiles[0][0].width, H), 'white')
    for im, fy in tiles:
        base.paste(im, (0, int(round((top_y - fy) * sx))))
    rdir = os.path.join(out_dir, 'map_raster')
    os.makedirs(rdir, exist_ok=True)
    base.save(os.path.join(rdir, 'mineral_map_base_75dpi.png'))
    px_deg = a / sx
    ulx, uly = ll(FR['x0'], top_y)
    with open(os.path.join(rdir, 'mineral_map_base_75dpi.pgw'), 'w') as f:
        f.write(f'{px_deg:.10f}\n0\n0\n{-px_deg:.10f}\n{ulx + px_deg / 2:.8f}\n{uly - px_deg / 2:.8f}\n')
    with open(os.path.join(rdir, 'mineral_map_base_75dpi.png.aux.xml'), 'w') as f:
        f.write(f'<PAMDataset><SRS>{WGS84_PRJ}</SRS></PAMDataset>')
    raster_info = {'width': base.width, 'height': base.height, 'px_per_pt': sx, 'x0_pt': FR['x0'], 'y_top_pt': top_y}
    print('base raster: %dx%d px (%.4f px/pt)' % (base.width, base.height, sx))

    def px_to_pt(col, row):
        return (FR['x0'] + col / sx, top_y - row / sx)

    # legend symbol sheet (two strips to the right of the map) -> flipped PNGs + per-entry crops
    legend_words = sorted([w for w in words if w['layer'] == 'Other 2' and 2100 < w['x0'] < 2200 and 10.5 < w['size'] < 11.5],
                          key=lambda w: -w['y0'])
    legend_names = []
    for w in legend_words:
        if w['text'].startswith('Moganite'):
            legend_names[-1] = 'Lithium (Ambligonite, Kunzite, Moganite, Spodumene, etc)'
        else:
            legend_names.append(re.sub(r'\s+', ' ', w['text']).strip())
    legend_strips = [p for p in placements if p[3] > FR['x1'] and p[1] < 40]
    legend_strips.sort(key=lambda p: -p[4])
    blobs_leg = []
    ldir = os.path.join(out_dir, 'legend_symbols')
    os.makedirs(ldir, exist_ok=True)
    for name, w_pt, h_pt, ex, fy in legend_strips:
        im = ImageOps.flip(xobject_image(page, name))
        im.save(os.path.join(ldir, f'legend_sheet_{name}.png'))
        arr = np.array(im).astype(int)
        s = im.height / -h_pt
        nonwhite = arr.sum(axis=2) < 720
        rows = nonwhite.any(axis=1)
        start = None
        for i, r in enumerate(list(rows) + [False]):
            if r and start is None:
                start = i
            elif not r and start is not None:
                if (i - start) / s >= 6:
                    cols = np.where(nonwhite[start:i].any(axis=0))[0]
                    crop = im.crop((max(0, cols.min() - 1), max(0, start - 1), cols.max() + 2, i + 1))
                    blobs_leg.append((fy - (start + i) / 2 / s, crop))
                start = None
    blobs_leg.sort(key=lambda t: -t[0])
    raster_legend_names = [n for n in legend_names if n != 'Calcite']   # Calcite's symbol is a vector marker only
    legend_rows = []
    for i, n in enumerate(legend_names):
        legend_rows.append({'legend_no': i + 1, 'mineral': n, 'symbol_png': ''})
    if len(blobs_leg) == len(raster_legend_names):
        for (yc, crop), n in zip(blobs_leg, raster_legend_names):
            fn = 'symbol_%02d_%s.png' % (legend_names.index(n) + 1, re.sub(r'[^A-Za-z0-9]+', '_', n).strip('_')[:40])
            crop.save(os.path.join(ldir, fn))
            legend_rows[legend_names.index(n)]['symbol_png'] = 'legend_symbols/' + fn
    else:
        print('WARNING: legend symbol count %d != legend names %d' % (len(blobs_leg), len(raster_legend_names)))
    codes_by_name = collections.defaultdict(list)
    for code, (nm, conf) in CODE_DICT.items():
        codes_by_name[nm.split(' (')[0]].append(code)
    with open(os.path.join(out_dir, 'mineral_legend.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['legend_no', 'mineral', 'commodity_group', 'code_printed_in_legend', 'table_codes_mapped_here',
                     'localities_in_table', 'symbol_png'])
        uses = collections.Counter(c for e in table for c in e['codes'])
        for r in legend_rows:
            m = re.search(r'\(([a-z]+)\)', r['mineral'])
            clean = re.sub(r'\s*\([a-z]+\)\s*$', '', r['mineral']).strip()
            codes_here = codes_by_name.get(clean, [])
            n_loc = sum(1 for e in table if any(expand_codes([c])[0][0].split(' (')[0] == clean for c in e['codes']))
            wr.writerow([r['legend_no'], clean, commodity_group(clean), m.group(1) if m else '', ' '.join(codes_here), n_loc, r['symbol_png']])
    with open(os.path.join(out_dir, 'mineral_code_dictionary.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['code', 'meaning', 'commodity_group', 'confidence', 'uses_in_table', 'uses_on_map'])
        on_map = collections.Counter(c for e in table if (e['zone'], e['number']) in lab_keys for c in e['codes'])
        for code in sorted(set(list(CODE_DICT) + list(uses))):
            nm, conf = expand_codes([code])[0][0], expand_codes([code])[2][0]
            wr.writerow([code, nm, commodity_group(nm), conf, uses.get(code, 0), on_map.get(code, 0)])
    print('legend: %d entries (%d raster symbols)' % (len(legend_names), len(blobs_leg)))

    # ---- raster symbol detection (colour-class blobs + outline blobs)
    arr = np.array(base).astype(int)
    R, G, B = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    symbol_blobs = []

    def components(mask, min_px):
        lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
        objs = ndimage.find_objects(lab)
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        out = []
        for i, sl in enumerate(objs):
            if sizes[i] < min_px:
                continue
            out.append((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop, int(sizes[i])))
        return out
    for cname, (r, g, bb) in SYMBOL_PALETTE.items():
        m = (abs(R - r) <= 8) & (abs(G - g) <= 8) & (abs(B - bb) <= 8)
        for x0, y0, x1, y1, npx in components(m, 6):
            w, h = x1 - x0, y1 - y0
            if w > 30 or h > 30:
                continue                     # water bodies / fills, not symbols
            symbol_blobs.append({'colour': cname, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'npx': npx})
    r, g, bb = WATER_LINE_RGB
    m = (abs(R - r) <= 8) & (abs(G - g) <= 8) & (abs(B - bb) <= 8)
    qa_water_fragments = len([1 for x0, y0, x1, y1, npx in components(m, 6) if x1 - x0 <= 30 and y1 - y0 <= 30])
    r, g, bb = SYMBOL_OUTLINE_RGB
    m = (abs(R - r) <= 8) & (abs(G - g) <= 8) & (abs(B - bb) <= 8)
    for x0, y0, x1, y1, npx in components(m, 12):
        w, h = x1 - x0, y1 - y0
        if w < 6 or h < 3 or w > 30 or h > 30:
            continue
        symbol_blobs.append({'colour': 'outline', 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'npx': npx})
    # merge: outline blobs (letters, borders) that lie mostly inside a coloured body belong to it;
    # coloured blobs are only merged when one contains the other (never two touching symbols)
    coloured = [s for s in symbol_blobs if s['colour'] != 'outline']
    outlines = [s for s in symbol_blobs if s['colour'] == 'outline']

    def overlap_frac(s, t):
        ix = max(0, min(s['x1'], t['x1']) - max(s['x0'], t['x0']))
        iy = max(0, min(s['y1'], t['y1']) - max(s['y0'], t['y0']))
        return ix * iy / float((s['x1'] - s['x0']) * (s['y1'] - s['y0']))
    coloured.sort(key=lambda s: -s['npx'])
    merged = []
    for s in coloured:
        for mcur in merged:
            if overlap_frac(s, mcur) >= 0.6:
                mcur['parts'] += 1
                break
        else:
            merged.append(dict(s, bw=s['x1'] - s['x0'], bh=s['y1'] - s['y0'], parts=1))
    for s in outlines:
        host = None
        for mcur in merged:
            if overlap_frac(s, mcur) >= 0.5:
                host = mcur
                break
        if host is not None:
            host['parts'] += 1
            host['x0'], host['y0'] = min(host['x0'], s['x0']), min(host['y0'], s['y0'])
            host['x1'], host['y1'] = max(host['x1'], s['x1']), max(host['y1'], s['y1'])
        else:
            merged.append(dict(s, bw=s['x1'] - s['x0'], bh=s['y1'] - s['y0'], parts=1))
    symbols = []
    for s in merged:
        fill = s['npx'] / float(max(1, s['bw'] * s['bh']))
        s['fill'] = 'solid' if fill >= 0.88 else ('round' if fill >= 0.68 else 'sparse')
        cands = []
        for cname, w0, w1, h0, h1, fills, names in SYMBOL_RULES:
            if cname == s['colour'] and w0 <= s['bw'] <= w1 and h0 <= s['bh'] <= h1 and s['fill'] in fills:
                cands = names
                break
        s['candidates'] = cands
        cx, cy = (s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2
        s['pt'] = px_to_pt(cx, cy)
        s['labels'] = []
        if frame.contains(Point(*s['pt'])):
            symbols.append(s)
    qa['raster_symbols'] = {'blobs': len(symbols), 'water_line_fragments_excluded': qa_water_fragments, 'by_colour': dict(collections.Counter(s['colour'] for s in symbols)),
                            'with_candidate_rule': sum(1 for s in symbols if s['candidates'])}
    print('raster symbol blobs: %d' % len(symbols))

    # ---- link number labels and symbols.  ArcMap placed each number wherever
    # there was room (median 14 pt from its symbol, in any direction), so pure
    # proximity is unreliable in clusters.  A label is snapped to a symbol only
    # when the symbol's colour/size signature is consistent with the minerals the
    # table lists for that number (nearest such symbol within SNAP_R).
    def consistent(entry, cands):
        if not entry or not cands:
            return False
        for n in entry['minerals']:
            n0 = n.split(' (')[0].lower()
            for cnd in cands:
                c0 = cnd.split(' (')[0].lower()
                if n0.startswith(c0) or c0.startswith(n0):
                    return True
        return False
    sym_pts = np.array([s['pt'] for s in symbols]) if symbols else np.zeros((0, 2))
    SNAP_R, HINT_R = 25.0, 14.0
    for i, l in enumerate(num_labels):
        l['sym'] = None
        if not len(sym_pts):
            continue
        dd = np.hypot(sym_pts[:, 0] - l['cx'], sym_pts[:, 1] - l['cy'])
        order = np.argsort(dd)
        for j in order:
            if dd[j] > SNAP_R:
                break
            if consistent(l['entry'], symbols[j]['candidates']):
                l['sym'], l['sym_dist'] = int(j), float(dd[j])
                symbols[j]['labels'].append((float(dd[j]), i))
                break
        if l['sym'] is None:
            j = int(order[0])
            if dd[j] <= HINT_R:
                l['hint'], l['hint_dist'] = j, float(dd[j])
    lab_pts = np.array([(l['cx'], l['cy']) for l in num_labels])
    for j, s in enumerate(symbols):
        s['near_label'], s['link'] = None, ''
        if s['labels']:
            s['labels'].sort()
            s['near_label'], s['near_dist'] = s['labels'][0][1], s['labels'][0][0]
            s['link'] = 'colour-consistent' + (' (+%d more labels)' % (len(s['labels']) - 1) if len(s['labels']) > 1 else '')
        else:
            dd = np.hypot(lab_pts[:, 0] - s['pt'][0], lab_pts[:, 1] - s['pt'][1])
            i = int(np.argmin(dd))
            if dd[i] <= HINT_R:
                s['near_label'], s['near_dist'], s['link'] = i, float(dd[i]), 'nearest only (unverified)'
    snapped = sum(1 for l in num_labels if l['sym'] is not None)
    with_entry = [l for l in num_labels if l['entry']]
    symbol_expected = [l for l in with_entry if any(not n.endswith('(no legend symbol)') and '(?)' not in n and 'not in legend' not in n for n in l['entry']['minerals'])]
    qa['raster_symbols'].update({
        'labels_total': len(num_labels), 'labels_with_table_entry': len(with_entry),
        'labels_whose_minerals_have_a_legend_symbol': len(symbol_expected),
        'labels_snapped_to_colour_consistent_symbol_within_%dpt' % int(SNAP_R): snapped,
        'symbols_linked_to_a_label': sum(1 for s in symbols if s['labels']),
        'symbols_claimed_by_several_labels': sum(1 for s in symbols if len(s['labels']) > 1),
        'symbols_without_any_label_within_%dpt' % int(HINT_R): sum(1 for s in symbols if s['near_label'] is None),
        'snap_distance_pt_quartiles': [float(v) for v in np.percentile([l['sym_dist'] for l in num_labels if l['sym'] is not None], [25, 50, 75])] if snapped else None,
        'snapped_by_colour': dict(collections.Counter(symbols[l['sym']]['colour'] for l in num_labels if l['sym'] is not None)),
    })
    print('labels snapped to a colour-consistent symbol within %.0f pt: %d / %d (of %d whose minerals have a legend symbol)' % (
        SNAP_R, snapped, len(num_labels), len(symbol_expected)))

    if os.environ.get('MINERAL_DEBUG'):
        import pickle
        pickle.dump({'symbols': symbols, 'labels': num_labels, 'table': table}, open(os.path.join(out_dir, '_debug.pkl'), 'wb'))

    # ======================================================================
    # outputs
    # ======================================================================
    def deg(v):
        return round(v, 6)

    # ---- mineral_localities (one per number printed on the map)
    host = load_host_geology(os.path.dirname(os.path.abspath(__file__)))
    GEO_SRC = 'geological map extraction (1:2 M), +-10 km' if host else 'shapefiles/geology_units.shp not found'

    def host_fields(lon, lat):
        rec = host(lon, lat) if host else None
        if not rec:
            return ['', '', '', '', '', '', 'outside mapped units' if host else GEO_SRC]
        return [rec.get('code') or '', (rec.get('unit') or '')[:64], (rec.get('formation') or '')[:48],
                (rec.get('era') or '')[:48], (rec.get('period') or '')[:40], (rec.get('epoch') or '')[:48], GEO_SRC]

    o = ShpOut(os.path.join(out_dir, 'mineral_localities'), shapefile.POINT, [
        ('zone', 'C', 1, 0), ('number', 'N', 5, 0), ('zone_num', 'C', 6, 0), ('locality', 'C', 80, 0),
        ('codes_raw', 'C', 40, 0), ('minerals', 'C', 254, 0), ('min_conf', 'C', 40, 0), ('match', 'C', 80, 0),
        ('tbl_flags', 'C', 200, 0), ('pos_src', 'C', 36, 0), ('snap_pt', 'N', 6, 1), ('sym_colour', 'C', 24, 0),
        ('sym_cands', 'C', 254, 0), ('label_lon', 'N', 12, 6), ('label_lat', 'N', 12, 6),
        # added attributes: coordinates, commodity summary, host rock unit from the geological map
        ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('n_minerals', 'N', 3, 0), ('mineral_1', 'C', 60, 0),
        ('group_1', 'C', 24, 0), ('groups', 'C', 120, 0), ('n_unknown', 'N', 3, 0), ('n_printed', 'N', 2, 0),
        ('geo_code', 'C', 8, 0), ('geo_unit', 'C', 64, 0), ('geo_form', 'C', 48, 0), ('geo_era', 'C', 48, 0),
        ('geo_period', 'C', 40, 0), ('geo_epoch', 'C', 48, 0), ('geo_src', 'C', 60, 0)])
    loc_rows = []
    group_count = collections.Counter()
    for l in sorted(num_labels, key=lambda l: (l['zone'] or 'Z', l['number'])):
        e = l['entry']
        if l['sym'] is not None:
            px_, py_ = symbols[l['sym']]['pt']
            pos_src, snap_d = 'raster symbol (colour-consistent)', round(l['sym_dist'], 1)
            scol, scand = symbols[l['sym']]['colour'], ' | '.join(symbols[l['sym']]['candidates'])
        else:
            px_, py_ = l['cx'], l['cy']
            pos_src, snap_d, scol, scand = 'label centre', None, '', ''
            if l.get('hint') is not None:
                scol = 'nearest: ' + symbols[l['hint']]['colour']
                scand = 'nearest symbol %.0f pt away (unverified): ' % l['hint_dist'] + (' | '.join(symbols[l['hint']]['candidates']) or 'no rule')
        lon, lat = ll(px_, py_)
        llon, llat = ll(l['cx'], l['cy'])
        mins = e['minerals'] if e else []
        groups = sorted({commodity_group(m) for m in mins})
        if not groups:
            groups = ['no code printed' if e else 'not in table']
        group_count.update(groups)
        rec = [l['zone'] or '', l['number'], '%s%d' % (l['zone'] or '?', l['number']),
               e['locality'] if e else '', e['minerals_raw'] if e else '', ' | '.join(mins),
               ' '.join(e['code_conf']) if e else '', l['match'], '; '.join(e['flags'])[:200] if e else '',
               pos_src, snap_d, scol, scand[:254], deg(llon), deg(llat),
               deg(lon), deg(lat), len(mins), (mins[0] if mins else '')[:60],
               commodity_group(mins[0]) if mins else groups[0], ' | '.join(groups)[:120],
               len(e['unknown_codes']) if e else 0, l['n_printed']] + host_fields(lon, lat)
        o.add(Point(deg(lon), deg(lat)), rec)
        loc_rows.append(dict(zip(['zone', 'number', 'zone_num', 'locality', 'codes_raw', 'minerals', 'code_conf', 'match',
                                  'table_flags', 'position_source', 'snap_dist_pt', 'symbol_colour', 'symbol_candidates',
                                  'label_lon', 'label_lat', 'lon', 'lat', 'n_minerals', 'mineral_1', 'group_1', 'groups',
                                  'n_unknown_codes', 'n_printed', 'geo_code', 'geo_unit', 'geo_formation', 'geo_era', 'geo_period',
                                  'geo_epoch', 'geo_source'], rec)))
    print('mineral_localities:', o.close(), '| commodity groups:', dict(group_count.most_common()),
          '| host geology:', 'joined' if host else 'not available')
    qa['commodity_groups'] = dict(group_count.most_common())
    with open(os.path.join(out_dir, 'mineral_localities.csv'), 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=list(loc_rows[0].keys()))
        wr.writeheader()
        wr.writerows(loc_rows)

    # ---- explanations table CSV (all entries, incl. the ones without a label on the map)
    with open(os.path.join(out_dir, 'explanations_table.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['zone', 'number', 'number_printed', 'locality', 'codes_raw', 'codes', 'minerals', 'commodity_groups',
                     'code_confidence', 'unknown_codes', 'on_map', 'flags', 'table_column', 'raw_text'])
        for e in sorted(table, key=lambda e: (e['zone'], e['number'], -e['y'])):
            wr.writerow([e['zone'], e['number'], e['number_printed'], e['locality'], e['minerals_raw'], ' '.join(e['codes']),
                         ' | '.join(e['minerals']), ' | '.join(sorted({commodity_group(m) for m in e['minerals']})),
                         ' '.join(e['code_conf']), ' '.join(e['unknown_codes']),
                         'yes' if (e['zone'], e['number']) in lab_keys else 'no', '; '.join(e['flags']), e['block'], e['raw']])

    # ---- raster symbol blobs
    o = ShpOut(os.path.join(out_dir, 'mineral_symbols_raster'), shapefile.POINT, [
        ('colour', 'C', 16, 0), ('w_px', 'N', 4, 0), ('h_px', 'N', 4, 0), ('body_w', 'N', 4, 0), ('body_h', 'N', 4, 0),
        ('fill', 'C', 8, 0), ('candidates', 'C', 254, 0), ('link', 'C', 40, 0), ('near_num', 'C', 8, 0), ('near_dist', 'N', 6, 1),
        ('near_loc', 'C', 80, 0), ('near_mins', 'C', 200, 0),
        ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('w_pt', 'N', 6, 2), ('h_pt', 'N', 6, 2), ('w_mm', 'N', 6, 2),
        ('h_mm', 'N', 6, 2), ('w_km', 'N', 7, 2), ('h_km', 'N', 7, 2), ('n_cands', 'N', 3, 0), ('group_1', 'C', 24, 0),
        ('near_grps', 'C', 120, 0)])
    km_per_pt_x = a * 111.32 * math.cos(math.radians(9.0))     # at the map's mid-latitude
    km_per_pt_y = c * 110.57
    for j, s in enumerate(symbols):
        lon, lat = ll(*s['pt'])
        nl = num_labels[s['near_label']] if s['near_label'] is not None else None
        e = nl['entry'] if nl else None
        wpx, hpx = s['x1'] - s['x0'], s['y1'] - s['y0']
        wpt, hpt = wpx / sx, hpx / sx
        o.add(Point(deg(lon), deg(lat)), [s['colour'], wpx, hpx, s['bw'], s['bh'],
                                         s['fill'], ' | '.join(s['candidates'])[:254], s['link'][:40],
                                         ('%s%d' % (nl['zone'] or '?', nl['number'])) if nl else '',
                                         round(s['near_dist'], 1) if nl else None, e['locality'] if e else '',
                                         e['minerals_raw'] if e else '',
                                         deg(lon), deg(lat), round(wpt, 2), round(hpt, 2), round(wpt * 25.4 / 72, 2),
                                         round(hpt * 25.4 / 72, 2), round(wpt * km_per_pt_x, 2), round(hpt * km_per_pt_y, 2),
                                         len(s['candidates']), commodity_group(s['candidates'][0]) if s['candidates'] else '',
                                         ' | '.join(sorted({commodity_group(m) for m in e['minerals']}))[:120] if e else ''])
    print('mineral_symbols_raster:', o.close())

    # ---- zones (A-G) polygons + division lines
    o = ShpOut(os.path.join(out_dir, 'map_zones'), shapefile.POLYGON, [
        ('zone', 'C', 1, 0), ('tbl_rows', 'N', 5, 0), ('labels', 'N', 5, 0), ('n_local', 'N', 5, 0), ('n_symbols', 'N', 5, 0),
        ('area_km2', 'N', 12, 1), ('perim_km', 'N', 10, 1), ('cen_lon', 'N', 10, 5), ('cen_lat', 'N', 10, 5),
        ('min_lon', 'N', 10, 5), ('max_lon', 'N', 10, 5), ('min_lat', 'N', 10, 5), ('max_lat', 'N', 10, 5),
        ('top_grps', 'C', 120, 0)])
    for z in 'ABCDEFG':
        pg = zones[z]
        geo = Polygon([ll(x, y) for x, y in pg.exterior.coords])
        zl = [l for l in num_labels if l['zone'] == z]
        zg = collections.Counter(g for l in zl if l['entry'] for g in {commodity_group(m) for m in l['entry']['minerals']})
        cen = geo.representative_point()
        zb = geo.bounds
        o.add(shapely_to_shp_geom(geo), [z, len([e for e in table if e['zone'] == z]), len(zl),
                                        len({(l['zone'], l['number']) for l in zl}),
                                        sum(1 for s_ in symbols if pg.contains(Point(*s_['pt']))),
                                        round(geo_area_km2(geo), 1), round(geo_perimeter_km(geo), 1),
                                        round(cen.x, 5), round(cen.y, 5), round(zb[0], 5), round(zb[2], 5), round(zb[1], 5), round(zb[3], 5),
                                        '; '.join('%s %d' % (g, n) for g, n in zg.most_common(3))[:120]])
    print('map_zones:', o.close())
    o = ShpOut(os.path.join(out_dir, 'division_lines'), shapefile.POLYLINE, [
        ('layer', 'C', 20, 0), ('len_pt', 'N', 8, 1), ('length_km', 'N', 10, 2), ('zones', 'C', 8, 0), ('n_vert', 'N', 5, 0)])
    for p in paths:
        if p['layer'] == 'division line':
            for pts, _ in p['subpaths']:
                L = LineString(pts).intersection(frame)
                if L.is_empty:
                    continue
                geoms = [L] if L.geom_type == 'LineString' else list(L.geoms)
                for gm in geoms:
                    coords = [ll(x, y) for x, y in gm.coords]
                    touching = ''.join(z for z in 'ABCDEFG' if zones[z].buffer(1.5).intersects(gm))
                    o.add(LineString(coords), ['division line', round(gm.length, 1), round(geo_length_km(coords), 2),
                                               touching, len(coords)])
    print('division_lines:', o.close())

    # ---- line layers
    LINE_EXTRA = [('length_km', 'N', 10, 2), ('n_vert', 'N', 6, 0), ('mid_lon', 'N', 11, 6), ('mid_lat', 'N', 11, 6),
                  ('zone', 'C', 1, 0), ('start_lon', 'N', 11, 6), ('start_lat', 'N', 11, 6), ('end_lon', 'N', 11, 6),
                  ('end_lat', 'N', 11, 6), ('closed', 'C', 3, 0)]

    def write_lines(fname, items, fields, extra=None):
        o = ShpOut(os.path.join(out_dir, fname), shapefile.POLYLINE, fields + LINE_EXTRA)
        for pts, rec in items:
            coords = [ll(x, y) for x, y in pts]
            if len(coords) >= 2:
                L = LineString(coords)
                mid = L.interpolate(0.5, normalized=True)
                mx_, my_ = pts[len(pts) // 2]
                o.add(L, rec + [round(geo_length_km(coords), 2), len(coords), round(mid.x, 6), round(mid.y, 6),
                                next((z for z in 'ABCDEFG' if zones[z].contains(Point(mx_, my_))), ''),
                                round(coords[0][0], 6), round(coords[0][1], 6), round(coords[-1][0], 6), round(coords[-1][1], 6),
                                'yes' if L.is_ring or Point(coords[0]).distance(Point(coords[-1])) < 1e-6 else 'no'])
        return o.close()

    # roads: double-line symbol -> centrelines
    road_paths = [p for p in paths if p['layer'] == 'Roads' and p['op'] == 'S']
    chains = chain_fragments(road_paths, 0.5)
    chains = merge_double_lines(chains, 2.5)
    n = write_lines('roads', [(pts, ['road', nfr]) for pts, nfr, _ in chains], [('class', 'C', 10, 0), ('n_frag', 'N', 6, 0)])
    print('roads:', n, '(from %d stroked paths)' % len(road_paths))

    river_paths = [p for p in paths if p['layer'] == 'Rivers' and p['op'] == 'S']
    chains = chain_fragments(river_paths, 0.0)
    n = write_lines('rivers', [(pts, ['river', nfr]) for pts, nfr, _ in chains], [('class', 'C', 10, 0), ('n_frag', 'N', 6, 0)])
    print('rivers:', n)

    rail_paths = [p for p in paths if p['layer'] == 'Railway' and p['op'] == 'S' and p['stroke'] not in ('#ffffff',) and p['lw'] > 1.0]
    chains = chain_fragments(rail_paths, 0.5)
    n = write_lines('railway', [(pts, ['railway', nfr]) for pts, nfr, _ in chains], [('class', 'C', 10, 0), ('n_frag', 'N', 6, 0)])
    print('railway:', n, '(dropped %d white dash overprints)' % len([p for p in paths if p['layer'] == 'Railway' and p['stroke'] == '#ffffff']))

    ib_paths = [p for p in paths if p['layer'] == 'International_Boundary' and p['op'] == 'S' and p['lw'] > 2]
    chains = chain_fragments(ib_paths, 1.0)
    n = write_lines('international_boundary', [(pts, ['international boundary', 'Nigeria', nfr]) for pts, nfr, _ in chains],
                    [('class', 'C', 24, 0), ('name', 'C', 24, 0), ('n_frag', 'N', 6, 0)])
    print('international_boundary:', n, '(dropped %d black 0.3-pt dashes = symbol decoration)' % len(
        [p for p in paths if p['layer'] == 'International_Boundary' and p['lw'] <= 1]))

    grat_items = []
    for p in paths:
        if p['layer'] != 'Graticule' or p['op'] != 'S':
            continue
        for pts, _ in p['subpaths']:
            L = LineString(pts)
            if L.length < 500 or frame.boundary.buffer(2).contains(L):
                continue
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            axis = 'lon' if abs(x1 - x0) < 1 else ('lat' if abs(y1 - y0) < 1 else 'frame')
            val = (a * x0 + b) if axis == 'lon' else ((c * y0 + d) if axis == 'lat' else 0)
            grat_items.append((pts, [axis, round(val, 3), int(round(val)) if axis != 'frame' else None]))
    o = ShpOut(os.path.join(out_dir, 'graticule'), shapefile.POLYLINE, [
        ('axis', 'C', 5, 0), ('vp_value', 'N', 8, 3), ('printed', 'N', 3, 0), ('label', 'C', 12, 0), ('length_km', 'N', 10, 2),
        ('offset_deg', 'N', 8, 4)])
    for pts, rec in grat_items:
        coords = [ll(x, y) for x, y in pts]
        axis, val, printed = rec
        label = ('%d%s%s' % (abs(printed), '\u00b0', 'E' if val >= 0 else 'W') if axis == 'lon'
                 else '%d%s%s' % (abs(printed), '\u00b0', 'N' if val >= 0 else 'S')) if printed is not None else ''
        o.add(LineString(coords), rec + [label, round(geo_length_km(coords), 2),
                                         round(val - printed, 4) if printed is not None else None])
    print('graticule:', o.close())
    o = ShpOut(os.path.join(out_dir, 'map_frame'), shapefile.POLYGON, [
        ('name', 'C', 24, 0), ('area_km2', 'N', 12, 1), ('perim_km', 'N', 10, 1), ('width_deg', 'N', 9, 5), ('height_deg', 'N', 9, 5),
        ('min_lon', 'N', 10, 5), ('max_lon', 'N', 10, 5), ('min_lat', 'N', 10, 5), ('max_lat', 'N', 10, 5),
        ('width_pt', 'N', 9, 2), ('height_pt', 'N', 9, 2), ('scale', 'C', 16, 0)])
    fgeo = Polygon([ll(x, y) for x, y in frame.exterior.coords])
    fb = fgeo.bounds
    pt_per_deg = ginfo['points_per_degree']['x']
    scale_den = 111320.0 * math.cos(math.radians((fb[1] + fb[3]) / 2)) / (pt_per_deg * 0.0254 / 72)
    o.add(shapely_to_shp_geom(fgeo), ['map frame (VP BBox)', round(geo_area_km2(fgeo), 1), round(geo_perimeter_km(fgeo), 1),
                                      round(fb[2] - fb[0], 5), round(fb[3] - fb[1], 5), round(fb[0], 5), round(fb[2], 5),
                                      round(fb[1], 5), round(fb[3], 5), round(FR['x1'] - FR['x0'], 2),
                                      round(FR['y_top'] - FR['y_bottom'], 2), '1:%s' % format(int(round(scale_den, -3)), ',')])
    o.close()

    # ---- towns (markers) + names, state capitals, state labels, river labels, pegmatite marks
    town_markers = []
    for p in paths:
        if p['layer'] == 'Towns' and p['op'] in ('f', 'f*', 'B', 'B*', 'b', 'b*'):
            pts = [q for sp, _ in p['subpaths'] for q in sp]
            town_markers.append((sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts), p['seq']))
    town_names = [w for w in words if w['layer'] == 'Towns - Default' and w['text'].strip()]
    cap_names = [w for w in words if w['layer'] == 'STATE CAPITALS - Default' and w['text'].strip()]

    def assign_names(markers, names, max_d):
        """Greedy nearest marker for each label.  The circle normally sits just left of the text, but it can also be
        at the right end or above/below, so the distance is measured from the marker to the label's bounding box."""
        pairs = []
        for i, w in enumerate(names):
            bx0, by0, bx1, by1 = label_box(w)
            for j, (mx, my, _) in enumerate(markers):
                dd = math.hypot(max(bx0 - mx, 0, mx - bx1), max(by0 - my, 0, my - by1))
                if dd <= max_d:
                    pairs.append((dd, i, j))
        pairs.sort()
        used_l, used_m, out = set(), set(), {}
        for dd, i, j in pairs:
            if i in used_l or j in used_m:
                continue
            used_l.add(i)
            used_m.add(j)
            out[j] = (i, dd)
        return out
    # The 478 vector circles of the 'Towns' layer are ordinary towns.  State capitals have NO vector marker:
    # their symbol (grey square with a centre dot) is part of the raster and is drawn under the middle of the
    # bold capital-name label, so capitals are positioned from the label and never matched to a town circle.
    town_assign = assign_names(town_markers, town_names, 12)
    zone_of_pt = lambda x, y: next((z for z in 'ABCDEFG' if zones[z].contains(Point(x, y))), '')

    def nearest_locality(x, y):
        best = None
        for l in num_labels:
            dd = math.hypot(l['cx'] - x, l['cy'] - y)
            if best is None or dd < best[0]:
                best = (dd, l)
        if best is None:
            return ['', None]
        return ['%s%d' % (best[1]['zone'] or '?', best[1]['number']), round(best[0] * a * 111.32 * math.cos(math.radians(9.0)), 1)]

    o = ShpOut(os.path.join(out_dir, 'towns'), shapefile.POINT, [
        ('name', 'C', 60, 0), ('kind', 'C', 24, 0), ('name_dist', 'N', 6, 1), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6),
        ('zone', 'C', 1, 0), ('near_loc', 'C', 8, 0), ('near_km', 'N', 7, 1), ('src_seq', 'N', 10, 0)])
    for j, (mx, my, seq) in enumerate(town_markers):
        lon_, lat_ = map(deg, ll(mx, my))
        if j in town_assign:
            i, dd = town_assign[j]
            o.add(Point(lon_, lat_), [town_names[i]['text'].strip(), 'town marker', round(dd, 1), lon_, lat_, zone_of_pt(mx, my)]
                  + nearest_locality(mx, my) + [seq])
        else:
            o.add(Point(lon_, lat_), ['', 'town marker (no name)', None, lon_, lat_, zone_of_pt(mx, my)] + nearest_locality(mx, my) + [seq])
    named = {i for i, dd in town_assign.values()}
    for i, w in enumerate(town_names):
        if i not in named:                 # name whose circle is shared with / hidden by a neighbouring label
            bx0, by0, bx1, by1 = label_box(w)
            px_, py_ = bx0 - 2, (by0 + by1) / 2
            lon_, lat_ = map(deg, ll(px_, py_))
            o.add(Point(lon_, lat_), [w['text'].strip(), 'name only (no marker)', None, lon_, lat_, zone_of_pt(px_, py_)]
                  + nearest_locality(px_, py_) + [w.get('seq', 0) or 0])
    n_towns = o.close()
    print('towns: %d markers (%d named, %d unnamed) + %d names without their own marker' % (
        len(town_markers), len(town_assign), len(town_markers) - len(town_assign), len(town_names) - len(town_assign)))

    def capital_square(w):
        """Locate the raster capital symbol (grey square, ~10 px) under a capital label.  Returns (x, y, src)."""
        cx, cy = label_centre(w)
        ex, ey = cx + 1.1, cy + 0.4            # measured mean offset of the square from label_centre()
        R = 16
        c, r = int(round((ex - FR['x0']) * sx)), int(round((top_y - ey) * sx))
        win = arr[max(r - R, 0):r + R, max(c - R, 0):c + R]
        if win.size:
            v = win.mean(axis=2)
            grey = (win.max(axis=2) - win.min(axis=2) <= 6) & (v > 80) & (v < 240)
            lab, n = ndimage.label(grey, structure=np.ones((3, 3)))
            best = None
            for i in range(1, n + 1):
                ys, xs = np.nonzero(lab == i)
                bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
                if 8 <= bw <= 14 and 8 <= bh <= 14 and len(xs) >= 40:
                    qx = (xs.max() + xs.min()) / 2 - min(R, c); qy = (ys.max() + ys.min()) / 2 - min(R, r)
                    dd = math.hypot(qx, qy)
                    if dd <= 6 and (best is None or dd < best[0]):
                        best = (dd, ex + qx / sx, ey - qy / sx)
            if best:
                return best[1], best[2], 'raster capital square'
        return ex, ey, 'label centre (square not isolated)'

    o = ShpOut(os.path.join(out_dir, 'state_capitals'), shapefile.POINT, [
        ('name', 'C', 60, 0), ('src', 'C', 40, 0), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('zone', 'C', 1, 0),
        ('ref_lon', 'N', 10, 4), ('ref_lat', 'N', 10, 4), ('ref_dx_km', 'N', 7, 1), ('ref_dy_km', 'N', 7, 1),
        ('near_loc', 'C', 8, 0), ('near_km', 'N', 7, 1)])
    cap_points = {}
    n_sq = 0
    for w in cap_names:
        x, y, src = capital_square(w)
        n_sq += src.startswith('raster')
        name_ = w['text'].strip()
        cap_points[name_] = (x, y)
        lon_, lat_ = map(deg, ll(x, y))
        ref = CAPITAL_REFERENCE.get(name_)
        if ref:
            dx_ = round((lon_ - ref[0]) * 111.32 * math.cos(math.radians(9.0)), 1)
            dy_ = round((lat_ - ref[1]) * 111.32, 1)
        o.add(Point(lon_, lat_), [name_, src, lon_, lat_, zone_of_pt(x, y), ref[0] if ref else None, ref[1] if ref else None,
                                  dx_ if ref else None, dy_ if ref else None] + nearest_locality(x, y))
    print('state_capitals: %d (%d located on the raster square)' % (o.close(), n_sq))

    # independent georeferencing check: capitals (positioned from the map) vs. reference coordinates, for the
    # /VP affine and for the alternative implied by the printed meridian labels (see graticule_check)
    km_lon = 111.32 * math.cos(math.radians(9.0))
    cap_check = {'n': 0, 'per_capital': []}
    dxs, dys = [], []
    for name, (x, y) in cap_points.items():
        if name not in CAPITAL_REFERENCE:
            continue
        lon, lat = ll(x, y)
        rlon, rlat = CAPITAL_REFERENCE[name]
        dx, dy = (lon - rlon) * km_lon, (lat - rlat) * 111.32
        dxs.append(dx)
        dys.append(dy)
        cap_check['per_capital'].append({'name': name, 'map_lon': round(lon, 4), 'map_lat': round(lat, 4),
                                         'ref_lon': rlon, 'ref_lat': rlat, 'dx_km': round(dx, 1), 'dy_km': round(dy, 1)})
    if dxs:
        n = len(dxs)
        mx_, my_ = sum(dxs) / n, sum(dys) / n
        cap_check.update({'n': n, 'VP_affine': {
            'mean_dx_km': round(mx_, 1), 'mean_dy_km': round(my_, 1),
            'sd_dx_km': round((sum((v - mx_) ** 2 for v in dxs) / n) ** 0.5, 1),
            'sd_dy_km': round((sum((v - my_) ** 2 for v in dys) / n) ** 0.5, 1),
            'rms_km': round((sum(v * v + u * u for v, u in zip(dxs, dys)) / n) ** 0.5, 1)}})
        if ginfo.get('meridian_label_offset_deg') is not None:
            sh = ginfo['meridian_label_offset_deg'] * km_lon
            cap_check['if_meridian_labels_were_right'] = {
                'mean_dx_km': round(mx_ + sh, 1), 'mean_dy_km': round(my_, 1),
                'rms_km': round((sum((v + sh) ** 2 + u * u for v, u in zip(dxs, dys)) / n) ** 0.5, 1)}
    qa['capital_check_km'] = cap_check
    if dxs:
        print('capital check vs reference: /VP mean offset (%.1f, %.1f) km, rms %.1f km (n=%d)' % (
            mx_, my_, cap_check['VP_affine']['rms_km'], n))

    o = ShpOut(os.path.join(out_dir, 'state_name_labels'), shapefile.POINT, [
        ('name', 'C', 60, 0), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('zone', 'C', 1, 0), ('font', 'C', 32, 0),
        ('size_pt', 'N', 6, 2), ('angle', 'N', 6, 1), ('capital', 'C', 60, 0)])
    STATE_CAPITAL = {'ABIA': 'Umuahia', 'ADAMAWA': 'Yola', 'AKWA IBOM': 'Uyo', 'ANAMBRA': 'Awka', 'BAUCHI': 'Bauchi',
                     'BAYELSA': 'Yenagoa', 'BENUE': 'Makurdi', 'BORNO': 'Maiduguri', 'CROSS RIVER': 'Calabar', 'DELTA': 'Asaba',
                     'EBONYI': 'Abakaliki', 'EDO': 'Benin City', 'EKITI': 'Ado-Ekiti', 'ENUGU': 'Enugu', 'GOMBE': 'Gombe',
                     'IMO': 'Owerri', 'JIGAWA': 'Dutse', 'KADUNA': 'Kaduna', 'KANO': 'Kano', 'KATSINA': 'Katsina', 'KEBBI': 'Birnin Kebbi',
                     'KOGI': 'Lokoja', 'KWARA': 'Ilorin', 'LAGOS': 'Ikeja', 'NASARAWA': 'Lafia', 'NIGER': 'Minna', 'OGUN': 'Abeokuta',
                     'ONDO': 'Akure', 'OSUN': 'Osogbo', 'OYO': 'Ibadan', 'PLATEAU': 'Jos', 'RIVERS': 'Port Harcourt', 'SOKOTO': 'Sokoto',
                     'TARABA': 'Jalingo', 'YOBE': 'Damaturu', 'ZAMFARA': 'Gusau', 'FCT': 'Abuja', 'F.C.T': 'Abuja', 'ABUJA': 'Abuja'}
    for w in words:
        if w['layer'] == 'State_Boundarys - Default' and w['text'].strip():
            cx, cy = label_centre(w)
            lon_, lat_ = map(deg, ll(cx, cy))
            nm = w['text'].strip()
            key_ = re.sub(r'\bSTATE\b', '', nm.upper()).replace(',', ' ').replace('.', '')
            key_ = re.sub(r'\s+', ' ', key_).strip()
            cap_ = STATE_CAPITAL.get(key_) or STATE_CAPITAL.get(key_.split(' ')[0], '')
            o.add(Point(lon_, lat_), [nm, lon_, lat_, zone_of_pt(cx, cy), w['font'][:32], round(w['size'], 2), round(w['angle'], 1), cap_])
    print('state_name_labels:', o.close())

    # river names follow the river curves (one rotation per glyph) -> assemble along the drawing order
    river_words = assemble_curved_labels([t for t in texts if t['layer'] == 'Rivers - Default'])
    o = ShpOut(os.path.join(out_dir, 'river_labels'), shapefile.POINT, [
        ('name', 'C', 60, 0), ('angle', 'N', 6, 1), ('n_glyphs', 'N', 3, 0), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6),
        ('zone', 'C', 1, 0), ('size_pt', 'N', 6, 2), ('kind', 'C', 16, 0), ('in_frame', 'C', 3, 0)])
    for w in river_words:
        px_, py_ = w['x'] + 0.3 * w['size'], w['y'] + 0.3 * w['size']
        lon_, lat_ = map(deg, ll(px_, py_))
        t_ = w['text']
        kind_ = 'lake' if re.search(r'\blake\b|\bl\.', t_, re.I) else ('river' if re.search(r'\br\.|river', t_, re.I) else 'water name')
        o.add(Point(lon_, lat_), [t_[:60], round(w['angle'], 1), w['nglyph'], lon_, lat_, zone_of_pt(px_, py_), round(w['size'], 2),
                                  kind_, 'yes' if frame.contains(Point(px_, py_)) else 'no'])
    print('river_labels: %d names (from %d glyph runs)' % (o.close(), sum(w['nglyph'] for w in river_words)))

    o = ShpOut(os.path.join(out_dir, 'pegmatite_marks'), shapefile.POINT, [
        ('symbol', 'C', 2, 0), ('meaning', 'C', 40, 0), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('zone', 'C', 1, 0),
        ('size_pt', 'N', 6, 2), ('near_loc', 'C', 8, 0), ('near_km', 'N', 7, 1), ('near_mins', 'C', 120, 0),
        ('geo_code', 'C', 8, 0), ('geo_unit', 'C', 64, 0), ('geo_era', 'C', 48, 0)])
    loc_by_key = {('%s%d' % (l['zone'] or '?', l['number'])): l for l in num_labels}
    for w in words:
        if w['layer'] == 'Pegmatite - Default' and w['text'].strip() == 'P' and frame.contains(Point(w['x0'], w['y0'])):
            cx, cy = label_centre(w)
            lon_, lat_ = map(deg, ll(cx, cy))
            nl_ = nearest_locality(cx, cy)
            ent = loc_by_key.get(nl_[0])
            ent = ent['entry'] if ent else None
            hf = host_fields(lon_, lat_)
            o.add(Point(lon_, lat_), ['P', 'Pegmatite (geology legend)', lon_, lat_, zone_of_pt(cx, cy), round(w['size'], 2)]
                  + nl_ + [(' | '.join(ent['minerals']) if ent else '')[:120], hf[0], hf[1], hf[3]])
    print('pegmatite_marks:', o.close())

    # ---- all map text (everything inside the frame, with layer + font)
    LABEL_KIND = {'Towns - Default': 'town name', 'STATE CAPITALS - Default': 'state capital name',
                  'State_Boundarys - Default': 'state name', 'Rivers - Default': 'river / lake name',
                  'Pegmatite - Default': 'pegmatite mark', 'mineral numbers - Default': 'locality number',
                  'Graticule': 'graticule label', 'Other 2': 'inset legend / title text', 'Other': 'layout text'}
    o = ShpOut(os.path.join(out_dir, 'map_labels'), shapefile.POINT, [
        ('text', 'C', 100, 0), ('layer', 'C', 32, 0), ('font', 'C', 32, 0), ('size_pt', 'N', 6, 2), ('angle', 'N', 6, 1),
        ('kind', 'C', 28, 0), ('lon', 'N', 12, 6), ('lat', 'N', 12, 6), ('zone', 'C', 1, 0), ('n_chars', 'N', 4, 0),
        ('width_pt', 'N', 7, 2), ('height_pt', 'N', 6, 2)])
    for w in words:
        if not w['text'].strip() or not frame.contains(Point(w['x0'], w['y0'])):
            continue
        if w['layer'] in ('mineral numbers - Default', 'Rivers - Default'):
            continue   # see mineral_localities / river_labels (added below)
        if 'ESRI' in w['font']:
            continue   # pattern fills of the geology legend swatches
        cx, cy = label_centre(w)
        lon_, lat_ = map(deg, ll(cx, cy))
        bx0, by0, bx1, by1 = label_box(w)
        t_ = w['text'].strip()
        o.add(Point(lon_, lat_), [t_[:100], w['layer'], w['font'][:32], round(w['size'], 2), round(w['angle'], 1),
                                  LABEL_KIND.get(w['layer'], 'other text'), lon_, lat_, zone_of_pt(cx, cy), len(t_),
                                  round(bx1 - bx0, 2), round(by1 - by0, 2)])
    for w in river_words:
        if frame.contains(Point(w['x'], w['y'])):
            px_, py_ = w['x'] + 0.3 * w['size'], w['y'] + 0.3 * w['size']
            lon_, lat_ = map(deg, ll(px_, py_))
            o.add(Point(lon_, lat_), [w['text'][:100], w['layer'], w['font'][:32], round(w['size'], 2), round(w['angle'], 1),
                                      LABEL_KIND.get(w['layer'], 'other text'), lon_, lat_, zone_of_pt(px_, py_), len(w['text']),
                                      round(w['nglyph'] * w['size'] * 0.55, 2), round(w['size'], 2)])
    print('map_labels:', o.close())

    # geology legend (text + swatch colours) of the inset legend inside the frame
    geol = []
    for w in words:
        if w['layer'] == 'Other 2' and 1655 < w['x0'] < 1760 and 500 < w['y0'] < 650 and w['text'].strip() and 'ESRI' not in w['font']:
            geol.append((w['y0'], w['text'].strip()))
    with open(os.path.join(out_dir, 'geology_legend.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['order', 'unit', 'note'])
        for i, (y, t) in enumerate(sorted(geol, key=lambda t: -t[0])):
            wr.writerow([i + 1, t, 'background geology is raster only (see map_raster/)'])

    # ---- preview
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        pg = doc[0]
        Hp = pg.rect.height
        clip = pymupdf.Rect(FR['x0'] - 10, Hp - FR['y_top'] - 10, FR['x1'] + 10, Hp - FR['y_bottom'] + 10)
        pix = pg.get_pixmap(dpi=96, clip=clip)
        pix.save(os.path.join(out_dir, 'preview_map_face.png'))
        pix = pg.get_pixmap(dpi=150, clip=clip)
        pix.save(os.path.join(rdir, 'mineral_map_face_150dpi.png'))
        px_deg2 = a * 72 / 150
        ulx2, uly2 = ll(FR['x0'] - 10, FR['y_top'] + 10)
        with open(os.path.join(rdir, 'mineral_map_face_150dpi.pgw'), 'w') as f:
            f.write(f'{px_deg2:.10f}\n0\n0\n{-px_deg2:.10f}\n{ulx2 + px_deg2 / 2:.8f}\n{uly2 - px_deg2 / 2:.8f}\n')
        with open(os.path.join(rdir, 'mineral_map_face_150dpi.png.aux.xml'), 'w') as f:
            f.write(f'<PAMDataset><SRS>{WGS84_PRJ}</SRS></PAMDataset>')
    except Exception as ex:  # pragma: no cover
        print('preview skipped:', ex)

    # ---- QA report
    qa['georef'] = {'points_per_degree': ginfo['points_per_degree'], 'parallel_max_residual_deg': ginfo['parallel_max_residual_deg'],
                    'meridian_label_offset_deg': ginfo['meridian_label_offset_deg']}
    qa['raster'] = raster_info
    with open(os.path.join(out_dir, 'qa_report.json'), 'w') as f:
        json.dump(qa, f, indent=2, default=float)

    # ---- GeoPackage bundle
    try:
        from pyogrio.raw import read as ogr_read, write as ogr_write
        gpkg = os.path.join(out_dir, 'nigeria_minerals.gpkg')
        if os.path.exists(gpkg):
            os.remove(gpkg)
        for fn in sorted(os.listdir(out_dir)):
            if fn.endswith('.shp'):
                meta, _, geometry, fields = ogr_read(os.path.join(out_dir, fn))
                gtype = meta['geometry_type']
                if gtype == 'Polygon':
                    gtype = 'MultiPolygon'
                ogr_write(gpkg, geometry, fields, layer=fn[:-4], driver='GPKG', crs='EPSG:4326',
                          geometry_type=gtype, fields=meta['fields'], append=True, promote_to_multi=(gtype == 'MultiPolygon'))
        print('geopackage:', gpkg)
    except ImportError:
        print('pyogrio not installed - GeoPackage bundle skipped')
    print('done ->', out_dir)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
