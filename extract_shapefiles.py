#!/usr/bin/env python3
"""
Extract georeferenced shapefiles from the NGSA "Geological Map of Nigeria" PDF.

The PDF (ESRI ArcMap 9.2 export) is NOT a GeoPDF - it has no embedded
georeferencing - but it is a pure-vector, layered PDF:

  * every geological unit, plus rivers, roads, railway, towns, faults, state
    boundaries ... is a separate Optional Content Group (PDF layer);
  * all geometry is vector paths in PDF page coordinates (points);
  * the map carries a 1-degree graticule (3-14 E, 4-13 N) whose lines are
    themselves vector paths.  Longitude and latitude are equally spaced
    (157.6 pt per degree), i.e. an unprojected / Plate Carree data frame
    at 1:2,000,000, so an axis-aligned affine fitted to the graticule
    converts page coordinates to geographic lon/lat.

This script

  1. parses the page content stream (paths + text, tagged with layer names),
  2. fits the page->lon/lat affine from the graticule lines and labels,
  3. rebuilds polygons (even-odd rule, holes), lines (re-chaining the dash
     fragments ArcMap emitted for dashed symbols), points (marker symbols)
     and labels (re-assembling per-character text runs),
  4. writes shapefiles (WGS84 .prj) + a legend CSV + a georeferenced PNG
     of the map face for QA.

Usage:  python extract_shapefiles.py <map.pdf> <output_dir>

Requires: pikepdf, pymupdf (raster QA image only), shapely, pyshp, numpy
"""
import collections
import csv
import json
import math
import os
import re
import sys

import numpy as np
import pikepdf
import shapefile
from shapely import make_valid
from shapely.geometry import (LineString, MultiLineString, MultiPolygon, Point,
                              Polygon)
from shapely.geometry.polygon import orient
from shapely.prepared import prep

# --------------------------------------------------------------------------
# 1.  PDF content-stream parser (paths + text with Optional Content layer)
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(
    rb"""
    (?P<ws>[\x00\t\n\x0c\r\x20]+)
  | (?P<comment>%[^\r\n]*)
  | (?P<dopen><<)
  | (?P<dclose>>>)
  | (?P<aopen>\[)
  | (?P<aclose>\])
  | (?P<hexstr><[0-9A-Fa-f\s]*>)
  | (?P<name>/[^\s/\[\]<>(){}%]*)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<strstart>\()
  | (?P<op>[A-Za-z'"*][A-Za-z0-9'"*]*)
  | (?P<other>.)
    """, re.X | re.S)

INLINE_IMG_END_RE = re.compile(rb'(?:^|[\s>])EI(?=[\s/\[<(]|$)')


def read_literal_string(data, pos):
    depth, out, n = 1, bytearray(), len(data)
    while pos < n:
        ch = data[pos]
        if ch == 0x5C:                       # backslash escape
            pos += 1
            if pos >= n:
                break
            ch = data[pos]
            if ch in b'nrtbf':
                out.append({0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}[ch])
                pos += 1
            elif 0x30 <= ch <= 0x37:
                digits = bytes([ch])
                pos += 1
                for _ in range(2):
                    if pos < n and 0x30 <= data[pos] <= 0x37:
                        digits += bytes([data[pos]])
                        pos += 1
                    else:
                        break
                out.append(int(digits, 8) & 0xFF)
            elif ch == 0x0D:
                pos += 1
                if pos < n and data[pos] == 0x0A:
                    pos += 1
            elif ch == 0x0A:
                pos += 1
            else:
                out.append(ch)
                pos += 1
        elif ch == 0x28:
            depth += 1
            out.append(ch)
            pos += 1
        elif ch == 0x29:
            depth -= 1
            pos += 1
            if depth == 0:
                return bytes(out), pos
            out.append(ch)
        else:
            out.append(ch)
            pos += 1
    return bytes(out), pos


def skip_inline_image(data, pos):
    """pos is just after 'BI'.  Return the position just after the matching 'EI'."""
    id_m = re.compile(rb'(?:^|\s)ID(?=\s)').search(data, pos)
    if not id_m:
        return len(data)
    hdr = data[pos:id_m.start()]
    start = id_m.end() + 1
    if b'/A85' in hdr or b'/ASCII85Decode' in hdr:
        tail = data.find(b'~>', start)
        if tail >= 0:
            m = INLINE_IMG_END_RE.search(data, tail)
            if m:
                return m.end()
    m = INLINE_IMG_END_RE.search(data, start)
    return m.end() if m else len(data)


def tokenize(data):
    pos, n = 0, len(data)
    while pos < n:
        m = TOKEN_RE.match(data, pos)
        if not m:
            pos += 1
            continue
        kind = m.lastgroup
        if kind == 'strstart':
            s, pos = read_literal_string(data, m.end())
            yield ('str', s)
            continue
        pos = m.end()
        if kind in ('ws', 'comment'):
            continue
        if kind == 'op' and m.group() == b'BI':
            pos = skip_inline_image(data, pos)
            continue
        if kind == 'num':
            yield ('num', float(m.group()))
        elif kind == 'name':
            yield ('name', m.group()[1:].decode('latin1'))
        elif kind == 'hexstr':
            h = re.sub(rb'\s', b'', m.group()[1:-1])
            if len(h) % 2:
                h += b'0'
            yield ('str', bytes.fromhex(h.decode()))
        elif kind == 'op':
            yield ('op', m.group().decode('latin1'))
        elif kind in ('dopen', 'dclose', 'aopen', 'aclose'):
            yield (kind, None)
        else:
            yield ('other', m.group())


def mat_mult(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def bezier(p0, p1, p2, p3, n=8):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        pts.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                    mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def color_to_rgb(spec):
    _, vals = spec
    if len(vals) == 1:
        return (vals[0],) * 3
    if len(vals) == 3:
        return tuple(vals)
    if len(vals) == 4:
        c, m, y, k = vals
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def rgb_hex(rgb):
    if rgb is None:
        return None
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(v * 255)))) for v in rgb)


class GState:
    __slots__ = ('ctm', 'fill', 'stroke', 'lw', 'font', 'fsize')

    def __init__(self):
        self.ctm = (1, 0, 0, 1, 0, 0)
        self.fill = ('g', (0.0,))
        self.stroke = ('G', (0.0,))
        self.lw = 1.0
        self.font = None
        self.fsize = 0

    def copy(self):
        g = GState()
        g.ctm, g.fill, g.stroke, g.lw, g.font, g.fsize = (
            self.ctm, self.fill, self.stroke, self.lw, self.font, self.fsize)
        return g


def parse_content(data, oc_names):
    """Yield path / text features.  oc_names maps property name -> (ocg_id, layer name)."""
    stack, gs, gstack, mc_stack = [], GState(), [], []
    seq = 0
    subpaths, cur = [], None
    tm = tlm = (1, 0, 0, 1, 0, 0)
    leading = 0.0

    def current_layer():
        for item in reversed(mc_stack):
            if item is not None:
                return item
        return (None, None)

    def collect_until(tokens, closer):
        items = []
        for t in tokens:
            if t[0] == closer:
                return items
            if t[0] == 'dopen':
                items.append(('dict', collect_until(tokens, 'dclose')))
            elif t[0] == 'aopen':
                items.append(('array', collect_until(tokens, 'aclose')))
            else:
                items.append(t)
        return items

    tokens = tokenize(data)
    for t in tokens:
        kind, val = t
        if kind == 'dopen':
            stack.append(('dict', collect_until(tokens, 'dclose')))
            continue
        if kind == 'aopen':
            stack.append(('array', collect_until(tokens, 'aclose')))
            continue
        if kind != 'op':
            stack.append(t)
            continue
        op = val
        nums = [v for k, v in stack if k == 'num']
        if op == 'q':
            gstack.append(gs.copy())
        elif op == 'Q':
            if gstack:
                gs = gstack.pop()
        elif op == 'cm' and len(nums) >= 6:
            gs.ctm = mat_mult(tuple(nums[-6:]), gs.ctm)
        elif op == 'w' and nums:
            gs.lw = nums[-1]
        elif op in ('g', 'rg', 'k', 'sc', 'scn'):
            gs.fill = (op, tuple(nums))
        elif op in ('G', 'RG', 'K', 'SC', 'SCN'):
            gs.stroke = (op, tuple(nums))
        elif op == 'BDC':
            names = [v for k, v in stack if k == 'name']
            tag = None
            if len(names) >= 2 and names[0] == 'OC':
                tag = oc_names.get(names[1], (None, names[1]))
            mc_stack.append(tag)
        elif op == 'BMC':
            mc_stack.append(None)
        elif op == 'EMC':
            if mc_stack:
                mc_stack.pop()
        # ---- path construction
        elif op == 'm' and len(nums) >= 2:
            if cur:
                subpaths.append((cur, False))
            cur = [apply(gs.ctm, nums[-2], nums[-1])]
        elif op == 'l' and len(nums) >= 2:
            p = apply(gs.ctm, nums[-2], nums[-1])
            if cur is None:
                cur = [p]
            else:
                cur.append(p)
        elif op in ('c', 'v', 'y') and len(nums) >= 4:
            if cur is None:
                cur = [apply(gs.ctm, nums[0], nums[1])]
            p0 = cur[-1]
            if op == 'c':
                p1 = apply(gs.ctm, nums[-6], nums[-5])
                p2 = apply(gs.ctm, nums[-4], nums[-3])
            elif op == 'v':
                p1 = p0
                p2 = apply(gs.ctm, nums[-4], nums[-3])
            else:
                p1 = apply(gs.ctm, nums[-4], nums[-3])
                p2 = None
            p3 = apply(gs.ctm, nums[-2], nums[-1])
            if p2 is None:
                p2 = p3
            cur.extend(bezier(p0, p1, p2, p3))
        elif op == 'h':
            if cur:
                subpaths.append((cur, True))
            cur = None
        elif op == 're' and len(nums) >= 4:
            if cur:
                subpaths.append((cur, False))
            x, y, w, h = nums[-4:]
            subpaths.append(([apply(gs.ctm, x, y), apply(gs.ctm, x + w, y),
                              apply(gs.ctm, x + w, y + h), apply(gs.ctm, x, y + h)], True))
            cur = None
        elif op in ('S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'):
            if cur:
                subpaths.append((cur, False))
            cur = None
            if op == 'F':
                op = 'f'
            if op != 'n' and subpaths:
                seq += 1
                closes = op in ('s', 'b', 'b*')
                ocg_id, layer = current_layer()
                yield {
                    'kind': 'path', 'seq': seq, 'ocg_id': ocg_id, 'layer': layer, 'op': op,
                    'fill': rgb_hex(color_to_rgb(gs.fill)) if op in ('f', 'f*', 'B', 'B*', 'b', 'b*') else None,
                    'stroke': rgb_hex(color_to_rgb(gs.stroke)) if op in ('S', 's', 'B', 'B*', 'b', 'b*') else None,
                    'lw': gs.lw,
                    'subpaths': [(pts, closed or closes) for pts, closed in subpaths],
                }
            subpaths = []
        # ---- text
        elif op == 'BT':
            tm = tlm = (1, 0, 0, 1, 0, 0)
        elif op == 'Tf':
            names = [v for k, v in stack if k == 'name']
            if names:
                gs.font = names[-1]
            if nums:
                gs.fsize = nums[-1]
        elif op == 'Tm' and len(nums) >= 6:
            tm = tlm = tuple(nums[-6:])
        elif op in ('Td', 'TD') and len(nums) >= 2:
            if op == 'TD':
                leading = -nums[-1]
            tlm = mat_mult((1, 0, 0, 1, nums[-2], nums[-1]), tlm)
            tm = tlm
        elif op == 'TL' and nums:
            leading = nums[-1]
        elif op == 'T*':
            tlm = mat_mult((1, 0, 0, 1, 0, -leading), tlm)
            tm = tlm
        elif op in ('Tj', "'", '"', 'TJ'):
            if op in ("'", '"'):
                tlm = mat_mult((1, 0, 0, 1, 0, -leading), tlm)
                tm = tlm
            if op == 'TJ':
                arr = [v for k, v in stack if k == 'array']
                s = b''.join(v for k, v in (arr[-1] if arr else []) if k == 'str')
            else:
                strs = [v for k, v in stack if k == 'str']
                s = strs[-1] if strs else b''
            if s:
                full = mat_mult(tm, gs.ctm)
                seq += 1
                ocg_id, layer = current_layer()
                yield {
                    'kind': 'text', 'seq': seq, 'ocg_id': ocg_id, 'layer': layer,
                    'text': s.decode('cp1252', errors='replace'),
                    'x': full[4], 'y': full[5],
                    'angle': math.degrees(math.atan2(full[1], full[0])),
                    'size': gs.fsize * math.hypot(full[0], full[1]),
                    'font': gs.font,
                }
        stack = []


# --------------------------------------------------------------------------
# 2.  Helpers: text re-assembly, georeferencing, geometry building
# --------------------------------------------------------------------------

def assemble_words(runs):
    """ArcMap emits one Tj per character; glue consecutive runs on a common baseline."""
    out, cur = [], None
    for t in runs:
        if cur is not None:
            prev = cur[-1]
            ang = math.radians(prev['angle'])
            dx, dy = t['x'] - prev['x'], t['y'] - prev['y']
            along = dx * math.cos(ang) + dy * math.sin(ang)
            perp = -dx * math.sin(ang) + dy * math.cos(ang)
            same = (t['font'] == prev['font'] and abs(t['size'] - prev['size']) < 0.05
                    and t['layer'] == prev['layer'] and abs(t['angle'] - prev['angle']) < 25
                    and abs(perp) < 0.6 * prev['size'] and -0.2 * prev['size'] < along < 1.6 * prev['size'])
            if same:
                cur.append(t)
                continue
            out.append(cur)
        cur = [t]
    if cur:
        out.append(cur)
    words = []
    for rs in out:
        words.append({
            'text': ''.join(r['text'] for r in rs), 'x0': rs[0]['x'], 'y0': rs[0]['y'],
            'x1': rs[-1]['x'], 'y1': rs[-1]['y'], 'size': rs[0]['size'], 'font': rs[0]['font'],
            'angle': rs[0]['angle'], 'layer': rs[0]['layer'], 'ocg_id': rs[0]['ocg_id'],
            'seq': rs[0]['seq'], 'nchar': len(rs)})
    return words


GRAT_RE = re.compile(r"^(\d{1,3})°\s*(\d{1,2})'\s*(\d{1,2})\"\s*([NSEW])$")


def fit_georef(paths, words):
    """Fit lon = a*x + b, lat = c*y + d from graticule lines + their degree labels."""
    labels = []
    for w in words:
        m = GRAT_RE.match(w['text'].replace('º', '°'))
        if m:
            deg = int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3)) / 3600
            if m.group(4) in 'SW':
                deg = -deg
            labels.append((m.group(4), deg, w))
    lon_labels = [(d, w) for h, d, w in labels if h in 'EW']
    lat_labels = [(d, w) for h, d, w in labels if h in 'NS']
    if not lon_labels or not lat_labels:
        raise SystemExit('No graticule labels found - cannot georeference')
    # candidate graticule lines: long, axis-parallel strokes
    vert, horiz = [], []
    for p in paths:
        if p['op'] not in ('S', 's'):
            continue
        for pts, _ in p['subpaths']:
            if len(pts) < 2:
                continue
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            if max(xs) - min(xs) < 0.5 and max(ys) - min(ys) > 300:
                vert.append((sum(xs) / len(xs), min(ys), max(ys)))
            if max(ys) - min(ys) < 0.5 and max(xs) - min(xs) > 300:
                horiz.append((sum(ys) / len(ys), min(xs), max(xs)))
    # keep only the dominant family (same extent) of lines
    def dominant(lines):
        fam = collections.Counter((round(a), round(b)) for _, a, b in lines).most_common(1)[0][0]
        return sorted(set(round(v, 3) for v, a, b in lines if (round(a), round(b)) == fam))
    vx = dominant(vert)
    hy = dominant(horiz)

    def pair(line_coords, labs, axis):
        pairs = []
        for lc in line_coords:
            best = None
            for d, w in labs:
                # label centre (approximate glyph advance = 0.55 em)
                if axis == 'x':
                    c = w['x0'] + 0.5 * 0.55 * w['size'] * len(w['text'])
                else:
                    c = w['y0'] + 0.35 * w['size']
                dist = abs(c - lc)
                if best is None or dist < best[0]:
                    best = (dist, d)
            if best and best[0] < 40:
                pairs.append((lc, best[1]))
        return pairs
    px = pair(vx, lon_labels, 'x')
    py = pair(hy, lat_labels, 'y')
    if len(px) < 2 or len(py) < 2:
        raise SystemExit('Could not pair graticule lines with labels')
    A = np.vstack([[x for x, _ in px], np.ones(len(px))]).T
    (a, b), *_ = np.linalg.lstsq(A, np.array([d for _, d in px]), rcond=None)
    B = np.vstack([[y for y, _ in py], np.ones(len(py))]).T
    (c, d), *_ = np.linalg.lstsq(B, np.array([v for _, v in py]), rcond=None)
    res_x = max(abs(d_ - (a * x + b)) for x, d_ in px)
    res_y = max(abs(v - (c * y + d)) for y, v in py)
    info = {
        'lon = a*x + b': {'a': a, 'b': b}, 'lat = c*y + d': {'c': c, 'd': d},
        'points_per_degree_x': 1 / a, 'points_per_degree_y': 1 / c,
        'n_meridians': len(px), 'n_parallels': len(py),
        'max_residual_deg': max(res_x, res_y),
        'approx_scale_denominator': round(111_320 * 1000 / ((1 / a) / 72 * 25.4)),
        'graticule_x': px, 'graticule_y': py,
    }
    return (a, b, c, d), info


def pdf_to_ll(affine, x, y):
    a, b, c, d = affine
    return (a * x + b, c * y + d)


def clean_ring(pts):
    out = []
    for p in pts:
        if not out or (abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9):
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def build_polygon(subpaths, affine):
    """Even-odd polygon reconstruction -> (Multi)Polygon in lon/lat, or None."""
    rings = []
    for pts, _ in subpaths:
        r = clean_ring([pdf_to_ll(affine, *p) for p in pts])
        if len(r) >= 3:
            poly = Polygon(r)
            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.geom_type == 'GeometryCollection':
                    polys = [g for g in poly.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
                    if not polys:
                        continue
                    poly = polys[0] if len(polys) == 1 else MultiPolygon(
                        [g for p in polys for g in (p.geoms if p.geom_type == 'MultiPolygon' else [p])])
            if poly.area > 0:
                rings.append(poly)
    if not rings:
        return None
    if len(rings) == 1:
        return rings[0]
    # nesting depth of each ring (even = outer, odd = hole)
    rings.sort(key=lambda g: g.area, reverse=True)
    reps = [g.representative_point() for g in rings]
    prepared = [prep(g) for g in rings]
    parent = [None] * len(rings)
    for i in range(len(rings)):
        for j in range(i - 1, -1, -1):          # smallest enclosing ring = last containing one
            if prepared[j].contains(reps[i]):
                parent[i] = j
                break
    depth = [0] * len(rings)
    for i in range(len(rings)):
        depth[i] = 0 if parent[i] is None else depth[parent[i]] + 1
    result = []
    for i, g in enumerate(rings):
        if depth[i] % 2 == 0:
            holes = [rings[k] for k in range(len(rings)) if parent[k] == i]
            poly = g
            for h in holes:
                poly = poly.difference(h)
            result.append(poly)
    geoms = []
    for g in result:
        if g.is_empty:
            continue
        if g.geom_type == 'Polygon':
            geoms.append(g)
        elif g.geom_type == 'MultiPolygon':
            geoms.extend(g.geoms)
        elif g.geom_type == 'GeometryCollection':
            geoms.extend(x for x in g.geoms if x.geom_type == 'Polygon')
    if not geoms:
        return None
    return geoms[0] if len(geoms) == 1 else MultiPolygon(geoms)


def chain_fragments(paths, tol_pt):
    """Re-join consecutive line fragments (ArcMap exports dashes/segments in drawing
    order along each feature).  Returns list of (list_of_pts_pdf, n_fragments, seq)."""
    chains = []
    cur, n, seq0 = None, 0, None
    for p in paths:
        for pts, _ in p['subpaths']:
            if len(pts) < 2:
                continue
            if cur is not None and math.hypot(pts[0][0] - cur[-1][0], pts[0][1] - cur[-1][1]) <= tol_pt:
                cur.extend(pts if math.hypot(pts[0][0] - cur[-1][0], pts[0][1] - cur[-1][1]) > 1e-9 else pts[1:])
                n += 1
            else:
                if cur is not None:
                    chains.append((cur, n, seq0))
                cur, n, seq0 = list(pts), 1, p['seq']
    if cur is not None:
        chains.append((cur, n, seq0))
    return chains


def merge_double_lines(chains, max_sep_pt):
    """The road symbol is a double line: ArcMap emitted every road twice, offset
    ~0.7 pt either side of the centreline (side A, then side B).  Collapse each
    pair back to a centreline by averaging side A with its projection on side B."""
    out, i = [], 0
    while i < len(chains):
        pts, n, seq = chains[i]
        if i + 1 < len(chains):
            pts2, n2, _ = chains[i + 1]
            la, lb = LineString(pts), LineString(pts2)
            if la.hausdorff_distance(lb) <= max_sep_pt:
                mid = []
                for x, y in pts:
                    q = lb.interpolate(lb.project(Point(x, y)))
                    mid.append(((x + q.x) / 2, (y + q.y) / 2))
                out.append((mid, n + n2, seq))
                i += 2
                continue
        out.append((pts, n, seq))
        i += 1
    return out


def path_length_pt(p):
    L = 0.0
    for pts, _ in p['subpaths']:
        for i in range(1, len(pts)):
            L += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
    return L


def centroid_pdf(p):
    pts = [q for sp, _ in p['subpaths'] for q in sp]
    return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))


def geo_length_km(coords):
    L = 0.0
    for i in range(1, len(coords)):
        (x0, y0), (x1, y1) = coords[i - 1], coords[i]
        latm = math.radians((y0 + y1) / 2)
        L += math.hypot((x1 - x0) * 111.32 * math.cos(latm), (y1 - y0) * 110.57)
    return L


def geo_area_km2(geom):
    lat = math.radians(geom.centroid.y)
    return geom.area * 111.32 * math.cos(lat) * 110.57


def geo_perimeter_km(geom):
    polys = geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]
    L = 0.0
    for pg in polys:
        for ring in [pg.exterior] + list(pg.interiors):
            L += geo_length_km(list(ring.coords))
    return L


def safe_name(s):
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    return s[:48] or 'layer'


WGS84_PRJ = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


class ShpOut:
    """Small wrapper around pyshp with WGS84 .prj and utf-8 .cpg."""

    def __init__(self, path, shape_type, fields):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.w = shapefile.Writer(path, shapeType=shape_type, encoding='utf-8')
        for name, ftype, size, dec in fields:
            self.w.field(name, ftype, size, dec)
        self.n = 0

    def add(self, geom, record):
        if isinstance(geom, Point):
            self.w.point(geom.x, geom.y)
        elif isinstance(geom, LineString):
            self.w.line([[list(c) for c in geom.coords]])
        elif isinstance(geom, MultiLineString):
            self.w.line([[list(c) for c in g.coords] for g in geom.geoms])
        else:                       # GeoJSON-like dict (polygons) - pyshp fixes ring orientation
            self.w.shape(geom)
        self.w.record(*record)
        self.n += 1

    def close(self):
        self.w.close()
        with open(self.path + '.prj', 'w') as f:
            f.write(WGS84_PRJ)
        with open(self.path + '.cpg', 'w') as f:
            f.write('UTF-8')
        return self.n


def shapely_to_shp_geom(geom):
    """Shapefile needs CW exterior / CCW holes; return a GeoJSON-like dict."""
    if geom.geom_type == 'Polygon':
        return orient(geom, sign=-1.0).__geo_interface__
    if geom.geom_type == 'MultiPolygon':
        return MultiPolygon([orient(g, sign=-1.0) for g in geom.geoms]).__geo_interface__
    return geom.__geo_interface__


# --------------------------------------------------------------------------
# 2b. Stratigraphy from the EXPLANATIONS panel
# --------------------------------------------------------------------------
# The legend column of the PDF carries, left of the colour swatches, three levels of
# curly brackets with printed age / series labels:
#   x ~ 2593 pt  period brackets      (NEOGENE, PALAEOGENE, CRETACEOUS, JURASSIC, PRE-CAMBRIAN TO CAMBRIAN,
#                                      TERTIARY TO RECENT VOLCANICS)
#   x ~ 2673 pt  one extra bracket    (Albian: Bima Fm + Asu River Group)
#   x ~ 2680 pt  sub-age / series brackets or single-row labels (Holocene, Pleistocene / Pliocene, ...,
#                                      Pan-African Older Granite Series, Migmatite-Gneiss Complex, ...)
# Right of the descriptions "--- <Formation>" names are printed, and the stratigraphic
# correlation chart (x 2145-2380) lists the unit codes per sedimentary basin.  The functions
# below read those printed elements geometrically; nothing is typed in by hand except the
# ICS translation of the printed terms and three documented fall-backs (see STRAT_FALLBACK).

# printed term (normalised) -> eon, era, period, epoch/stage, age range (Ma, ICS 2023) and a literature note
ICS = {
    'recent':                     ('Phanerozoic', 'Cenozoic', 'Quaternary', 'Holocene', 0.0, 0.0117, ''),
    'holocene':                   ('Phanerozoic', 'Cenozoic', 'Quaternary', 'Holocene', 0.0, 0.0117, ''),
    'pleistocene / pliocene':     ('Phanerozoic', 'Cenozoic', 'Neogene-Quaternary', 'Pliocene-Pleistocene', 0.0117, 5.333, ''),
    'tertiary to recent volcanics': ('Phanerozoic', 'Cenozoic', 'Paleogene-Quaternary (Tertiary-Recent)', '', 0.0, 66.0,
                                   'Nigerian plateau basalts (Jos, Biu, Mambilla) are Miocene to Holocene'),
    'oligocene / miocene':        ('Phanerozoic', 'Cenozoic', 'Paleogene-Neogene', 'Oligocene-Miocene', 5.333, 33.9, ''),
    'upper eocene':               ('Phanerozoic', 'Cenozoic', 'Paleogene', 'Eocene (Late / Priabonian)', 33.9, 37.71, ''),
    'middle eocene':              ('Phanerozoic', 'Cenozoic', 'Paleogene', 'Eocene (Middle / Lutetian-Bartonian)', 37.71, 47.8, ''),
    'lower eocene':               ('Phanerozoic', 'Cenozoic', 'Paleogene', 'Eocene (Early / Ypresian)', 47.8, 56.0, ''),
    'palaeocene':                 ('Phanerozoic', 'Cenozoic', 'Paleogene', 'Paleocene', 56.0, 66.0, ''),
    'coniancian / maestrichtian': ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Late Cretaceous: Coniacian-Maastrichtian', 66.0, 89.8, ''),
    'coniancian':                 ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Late Cretaceous: Coniacian', 86.3, 89.8, ''),
    'senonian':                   ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Late Cretaceous: Senonian (Coniacian-Maastrichtian)', 66.0, 89.8,
                                   'Rima Group of the Sokoto Basin is Maastrichtian'),
    'turonian / pre maastrichtian': ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Late Cretaceous: Turonian-Campanian', 72.1, 93.9, ''),
    'albian / cenomanian':        ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Albian-Cenomanian', 93.9, 113.0, ''),
    'albian':                     ('Phanerozoic', 'Mesozoic', 'Cretaceous', 'Early Cretaceous: Albian', 100.5, 113.0, ''),
    'jurassic':                   ('Phanerozoic', 'Mesozoic', 'Jurassic', '', 145.0, 201.4,
                                   'Younger Granite ring complexes are dated c. 213-141 Ma (Late Triassic-Jurassic)'),
    'pre - cambrian to cambrian': ('Precambrian-Phanerozoic', 'Archaean-Proterozoic (to Cambrian)', '(Precambrian) - Cambrian', '', 485.4, 4000.0,
                                   'basement: Archaean-Palaeoproterozoic gneiss protoliths reworked and intruded in the Pan-African (c. 750-500 Ma)'),
}
# series-level refinements of the Precambrian-Cambrian bracket (the printed series / complex label decides)
SERIES_ICS = {
    'pan - african older granite series': ('Proterozoic-Phanerozoic', 'Neoproterozoic-Palaeozoic', 'Ediacaran-Cambrian', '', 485.4, 1000.0,
                                           'Pan-African granitoids, c. 750-500 Ma'),
    'meta - sedimentary / meta - volcanic series': ('Proterozoic', 'Neoproterozoic (Pan-African deformed)', '', '', 538.8, 1000.0,
                                                    'schist belts: Neoproterozoic metasediments / metavolcanics, deformed c. 600 Ma'),
    'migmatite - gneiss complex': ('Archaean-Proterozoic', 'Archaean-Palaeoproterozoic, reworked in the Neoproterozoic', '', '', 538.8, 4000.0,
                                   'protoliths c. 2.7-2.0 Ga (Eburnean / Liberian), Pan-African migmatisation c. 600 Ma'),
    'cataclastic rocks': ('Proterozoic-Phanerozoic', 'Neoproterozoic-Palaeozoic', 'Ediacaran-Cambrian', '', 485.4, 1000.0,
                          'Pan-African shear zones (c. 600-550 Ma)'),
}
# rows the legend leaves without any bracket or label: printed evidence used instead
STRAT_FALLBACK = {
    ('Gss', 20): ('Senonian', 'correlation chart (Gombe Formation drawn in the Senonian band)'),
    ('Ajst', 21): ('Coniancian / Maestrichtian', 'legend position between Gombe Fm and Nsukka Fm; Ajali Formation is Maastrichtian'),
    ('Ts', 34): ('Senonian', 'correlation chart key: ts, Tst, Tss, Tcs = Rima Group (Senonian band)'),
    ('MyP', 49): ('JURASSIC', 'code family My- (Younger Granite series); row sits 2 pt above the JURASSIC bracket'),
    ('P', 59): ('', 'no age printed; basement pegmatites of Nigeria are late Pan-African (c. 560-530 Ma)'),
}
ROCK_CLASS_RULES = [
    ('fault rock',     r'mylonite|cataclas|sheared'),
    ('minor intrusive', r'pegmatite|dolerite'),
    ('metamorphic',    r'schist|gneiss|migmat|quartzite|marble|amphibol|banded iron|phyl|slate|meta|granulite|charnock'),
    ('volcanic',       r'basalt|rhyolite|ignimbrite|trachy|andes|volcanic'),
    ('plutonic',       r'granite|syenite|gabbro|diorite|granodiorite|porph'),
    ('sedimentary',    r'sand|clay|shale|limestone|silt|coal|lignite|gravel|pebble|grit|alluvium|swamp|ironstone|mudstone|conglomerate|beach'),
]
CHART_COLUMNS = [  # x range (pt) of the basin columns of the correlation chart, header as printed
    (2145.6, 2163.6, 'N.W.: Bida - Lokoja'), (2163.6, 2183.4, 'N.W.: Sokoto'), (2183.4, 2203.6, 'N.W.: Yola'),
    (2203.6, 2224.1, 'N.E.: Numan'), (2224.1, 2243.2, 'N.E.: Maiduguri'), (2243.2, 2262.6, 'N.E.: Gombe'),
    (2262.6, 2321.7, 'S.E.'), (2321.7, 2380.3, 'S.W.')]
CHART_ALIASES = {'cst': 'Cst', 'ncst': 'Ncsh', 'kst': 'Kss', 'ims': 'Imsh', 'ash': 'ANsh', 'ylsh': 'Yls', 'bst': 'Bss',
                 'mcs': 'Mcst', 'gicl': 'Glcl'}


def rock_class(desc, code=''):
    d = desc.lower()
    for cls, rx in ROCK_CLASS_RULES:
        if re.search(rx, d):
            return cls
    return ''


def _vertical_runs(paths, x_lo, x_hi, min_len=8.0):
    """Vertical straight runs (x, y_lo, y_hi) of stroked layout paths inside an x window (page coords)."""
    runs = []
    for p in paths:
        if p['layer'] not in ('Other 3', 'Other 2') or p['op'] not in ('S', 's', 'B', 'B*', 'b', 'b*'):
            continue
        for pts, _ in p['subpaths']:
            i = 0
            while i < len(pts):
                j = i
                while j + 1 < len(pts) and abs(pts[j + 1][0] - pts[i][0]) < 1.5:
                    j += 1
                if j > i:
                    ys = [q[1] for q in pts[i:j + 1]]
                    x = sum(q[0] for q in pts[i:j + 1]) / (j - i + 1)
                    if x_lo <= x <= x_hi and max(ys) - min(ys) >= min_len:
                        runs.append((x, min(ys), max(ys)))
                i = max(j, i + 1)
    return runs


def _brackets(runs):
    """Pair vertical arms into curly brackets: upper arm, lower arm, optional hook continuing the lower arm.
    Works in page-down coordinates (y_d = top .. bottom); returns [(top, bottom, gap_top, gap_bottom)]."""
    arms = sorted(runs)                     # (top_d, bottom_d)
    merged = []
    for a in arms:                          # join touching pieces (the hooks)
        if merged and a[0] <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], a[1]))
        else:
            merged.append(a)
    out = []
    i = 0
    while i + 1 < len(merged):
        up, lo = merged[i], merged[i + 1]
        out.append((up[0], lo[1], up[1], lo[0]))
        i += 2
    return out


def legend_stratigraphy(legend, words, paths, page_h):
    """Attach formation / age / series / basin attributes (all read from the printed panel) to the legend rows."""
    H = page_h
    rows = []
    for i, e in enumerate(legend, 1):
        e['row'] = i
        rows.append((i, H - e['y_top'], H - e['y_bot']))          # top_d, bottom_d
    row_h = sum(b - t for _, t, b in rows) / len(rows)

    def overlap(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0))

    def members(top, bot):
        return [i for i, t, b in rows if overlap(t, b, top, bot) >= 0.45 * row_h]

    # ---- printed labels (layout layer words -> lines -> blocks)
    lw = [w for w in words if w['layer'] in ('Other 3', 'Other 2') and abs(w['angle']) < 5 and w['text'].strip()]
    lw.sort(key=lambda w: (-w['y0'], w['x0']))
    lines = []
    for w in lw:
        if lines and abs(lines[-1]['y0'] - w['y0']) < 2.0 and -1.0 <= w['x0'] - lines[-1]['x1'] < 1.2 * w['size']:
            lines[-1]['text'] += ' ' + w['text'].strip()
            lines[-1]['x1'] = w['x1'] + 0.6 * w['size']
        else:
            lines.append({'text': w['text'].strip(), 'x0': w['x0'], 'x1': w['x1'] + 0.6 * w['size'], 'y0': w['y0'],
                          'size': w['size'], 'yc': H - (w['y0'] + 0.35 * w['size'])})
    sub = [l for l in lines if 2596 <= l['x0'] <= 2672 and l['yc'] > 80]
    per = [l for l in lines if 2500 <= l['x0'] < 2592 and l['yc'] > 80 and l['text'].upper() == l['text']
           and re.search('[A-Z]{4}', l['text'])]
    blocks = []
    for l in sorted(sub, key=lambda l: l['yc']):
        if blocks and l['yc'] - blocks[-1]['lines'][-1]['yc'] < 9 and abs(l['x0'] - blocks[-1]['lines'][0]['x0']) < 40:
            blocks[-1]['lines'].append(l)
        else:
            blocks.append({'lines': [l]})
    for b in blocks:
        b['yc'] = sum(l['yc'] for l in b['lines']) / len(b['lines'])
        series_like = any(re.search(r'series|complex|rocks', l['text'], re.I) for l in b['lines'])
        text = ''
        for l in b['lines']:
            sep = ' / ' if (text.endswith('/') or not series_like) else ' '
            text = (text.rstrip(' /') + sep + l['text'].strip()) if text else l['text'].strip()
        b['text'] = text.rstrip(' /')
    pblocks = []
    for l in sorted(per, key=lambda l: l['yc']):
        if pblocks and l['yc'] - pblocks[-1]['lines'][-1]['yc'] < 9:
            pblocks[-1]['lines'].append(l)
        else:
            pblocks.append({'lines': [l]})
    for b in pblocks:
        b['yc'] = sum(l['yc'] for l in b['lines']) / len(b['lines'])
        b['text'] = ' '.join(l['text'] for l in b['lines'])

    # ---- brackets (page-down coordinates)
    def runs_d(x_lo, x_hi):
        return [(H - y_hi, H - y_lo) for x, y_lo, y_hi in _vertical_runs(paths, x_lo, x_hi)]
    br_period = _brackets(runs_d(2588, 2598))
    br_sub = _brackets(runs_d(2676, 2683))
    br_extra = _brackets(runs_d(2670, 2676))

    info = {i: {'age_print': '', 'series': '', 'period_prt': '', 'age_src': '', 'note': ''} for i, _, _ in rows}

    def is_series(t):
        return bool(re.search(r'series|complex|rocks|volcanics', t, re.I))

    used_blocks = set()
    for level, brs in (('sub-age bracket', br_sub), ('extra bracket', br_extra)):
        for top, bot, g0, g1 in brs:
            mem = members(top, bot)
            labs = [b for b in blocks if top <= b['yc'] <= bot and id(b) not in used_blocks]
            if not mem or not labs:
                continue
            for b in labs:
                used_blocks.add(id(b))
            if len(labs) == 1 and len(labs[0]['lines']) == len(mem) and len(mem) > 1:
                # stacked label, one line per row (Oligocene / Miocene over Upper Eocene)
                for i, l in zip(mem, labs[0]['lines']):
                    info[i]['age_print'] = l['text']
                    info[i]['age_src'] = level + ' (stacked label, one line per row)'
            else:
                for b in labs:
                    key = 'series' if is_series(b['text']) else 'age_print'
                    for i in mem:
                        if not info[i][key]:
                            info[i][key] = b['text']
                            info[i]['age_src'] = info[i]['age_src'] or level
    # single-row labels (no bracket)
    for b in blocks:
        if id(b) in used_blocks:
            continue
        best = max(rows, key=lambda r: overlap(r[1], r[2], b['yc'] - 0.5 * b['lines'][0]['size'], b['yc'] + 0.5 * b['lines'][0]['size']))
        i = best[0]
        key = 'series' if is_series(b['text']) else 'age_print'
        if not info[i][key]:
            info[i][key] = b['text']
            info[i]['age_src'] = 'legend row label'
            used_blocks.add(id(b))
    # period brackets
    for top, bot, g0, g1 in br_period:
        labs = [b for b in pblocks if top <= b['yc'] <= bot]
        for i in members(top, bot):
            info[i]['period_prt'] = ' / '.join(b['text'] for b in labs)
    # a row that shares a sub-age bracket or a series label with dated rows inherits their period label
    # (bracket ends are drawn up to ~7 pt short of the swatch edge)
    for top, bot, g0, g1 in br_sub + br_extra:
        mem = members(top, bot)
        pp = collections.Counter(info[i]['period_prt'] for i in mem if info[i]['period_prt'])
        if pp:
            for i in mem:
                if not info[i]['period_prt']:
                    info[i]['period_prt'] = pp.most_common(1)[0][0]
    # rows without series inside the Precambrian bracket: nearest sub-age bracket (<= 10 pt)
    for i, t, b in rows:
        if info[i]['period_prt'].startswith('PRE') and not info[i]['series']:
            best = None
            for top, bot, g0, g1 in br_sub:
                d = max(0.0, top - b, t - bot)
                if d <= 10 and (best is None or d < best[0]):
                    best = (d, top, bot)
            if best:
                mem = members(best[1], best[2])
                if mem and info[mem[0]]['series']:
                    info[i]['series'] = info[mem[0]]['series']
                    info[i]['age_src'] = f'nearest series bracket ({best[0]:.1f} pt away)'

    # ---- "--- Formation" names right of the descriptions and spanning group names
    names = [l for l in lines if l['x0'] >= 2700 and '---' in l['text']]
    spans = [l for l in lines if l['x0'] >= 2860 and '---' not in l['text'] and re.search(r'Formation|Group|group', l['text'])]
    for i, t, b in rows:
        e = legend[i - 1]
        e['formation'] = ''
        e['strat_grp'] = ''
        for l in names:
            y0, y1 = l['yc'] - 0.55 * l['size'], l['yc'] + 0.55 * l['size']
            if overlap(t, b, y0, y1) >= 0.35 * l['size']:
                e['formation'] = l['text'].split('---', 1)[1].strip()
        for l in spans:
            y0, y1 = l['yc'] - 0.55 * l['size'] - 4, l['yc'] + 0.55 * l['size'] + 4
            if overlap(t, b, y0, y1) > 0:
                e['strat_grp'] = l['text'].strip()

    # ---- correlation chart: key (code -> formation) and basin columns
    chart = [l for l in lines if 2145 <= l['x0'] <= 2381 and 180 <= l['yc'] <= 746]
    key_codes = [l for l in lines if 2384 <= l['x0'] <= 2423 and 180 <= l['yc'] <= 746]
    key = collections.defaultdict(list)
    for kc in key_codes:
        name = [l for l in lines if 2426 <= l['x0'] <= 2440 and abs(l['y0'] - kc['y0']) < 2]
        if not name:
            continue
        for c in re.split(r'[,\s]+', kc['text']):
            c = c.strip()
            if c:
                key[CHART_ALIASES.get(c.lower(), c)].append((name[0]['text'], kc['yc']))
    cells = []     # filled cells of the chart: (x0, x1, top_d, bottom_d, area)
    for pth in paths:
        if pth['layer'] not in ('Other 3', 'Other 2') or pth['op'] not in ('f', 'f*', 'B', 'B*', 'b', 'b*'):
            continue
        pts = [q for sp, _ in pth['subpaths'] for q in sp]
        if not pts:
            continue
        x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
        t, b = H - max(q[1] for q in pts), H - min(q[1] for q in pts)
        if 2140 <= x0 and x1 <= 2385 and 178 <= t and b <= 748 and x1 - x0 > 12 and b - t > 6:
            cells.append((x0, x1, t, b, (x1 - x0) * (b - t)))
    basins = collections.defaultdict(set)
    for l in chart:
        xc, yc = (l['x0'] + l['x1']) / 2, l['yc']
        inside = [c for c in cells if c[0] - 1 <= xc <= c[1] + 1 and c[2] - 1 <= yc <= c[3] + 1]
        if inside:
            c = min(inside, key=lambda c: c[4])
            cols = [name for x0, x1, name in CHART_COLUMNS if c[0] - 2 <= (x0 + x1) / 2 <= c[1] + 2]
        else:
            cols = [name for x0, x1, name in CHART_COLUMNS if x0 <= xc < x1]
        for code_ in re.split(r'[,\s]+', l['text']):
            code_ = code_.strip()
            if re.fullmatch(r'[A-Za-z]{1,6}', code_):
                basins[CHART_ALIASES.get(code_.lower(), code_)].update(cols)
    chart_age = {}   # rough era of a key line from the age labels at the left of the chart
    age_lab = [l for l in lines if 2060 <= l['x0'] <= 2141 and 180 <= l['yc'] <= 746 and l['text'].upper() == l['text']]

    def era_of_key_line(yc):
        near = min(age_lab, key=lambda l: abs(l['yc'] - yc), default=None)
        if not near:
            return ''
        return 'Mesozoic' if re.search(r'SENON|CRETAC|TURON|CENOMAN|ALBIAN', near['text']) else 'Cenozoic'

    # ---- translate the printed terms
    def norm(t):
        return re.sub(r'\s+', ' ', t.replace('–', '-').replace('/', ' ')).strip().lower()
    SERIES_N = {norm(k): v for k, v in SERIES_ICS.items()}
    ICS_N = {norm(k): v for k, v in ICS.items()}
    for i, t, b in rows:
        e = legend[i - 1]
        inf = info[i]
        code = e['code']
        fb = STRAT_FALLBACK.get((code, i))
        if fb and not inf['age_print']:
            if fb[0] and fb[0].upper() == fb[0]:
                inf['period_prt'] = inf['period_prt'] or fb[0]
            else:
                inf['age_print'] = fb[0]
            inf['age_src'] = 'fall-back: ' + fb[1]
            inf['note'] = fb[1]
        term = norm(inf['age_print']) or norm(inf['period_prt'])
        ics = ICS_N.get(term)
        if norm(inf['series']) in SERIES_N and inf['period_prt'].startswith('PRE'):
            ics = SERIES_N[norm(inf['series'])]
        if ics is None and term:
            # try each part of a composite term, e.g. 'turonian / pre maastrichtian'
            ics = next((ICS_N[k] for k in ICS_N if k in term), None)
        e.update({
            'age_print': inf['age_print'], 'series': inf['series'], 'period_prt': inf['period_prt'],
            'age_src': inf['age_src'], 'strat_note': inf['note'],
            'eon': ics[0] if ics else '', 'era': ics[1] if ics else '', 'period': ics[2] if ics else '',
            'epoch': ics[3] if ics else '', 'age_ma_min': ics[4] if ics else None, 'age_ma_max': ics[5] if ics else None,
            'age_lit': ics[6] if ics else '', 'rock_cls': rock_class(e['description']),
            'basins': '; '.join(sorted(basins.get(code, []))),
        })
        if not e['formation'] and code in key and e['rock_cls'] == 'sedimentary' and e['era'] in ('Cenozoic', 'Mesozoic'):
            cands = key[code]
            if len(cands) == 1:
                e['formation'] = cands[0][0] + ' (chart key)'
            else:
                era = e['era']
                pick = [c for c in cands if era_of_key_line(c[1]) == era.split('-')[0]]
                if len(pick) == 1:
                    e['formation'] = pick[0][0] + ' (chart key)'
                    e['strat_note'] = (e['strat_note'] + '; ' if e['strat_note'] else '') + \
                        'code %s appears twice in the chart key (%s); chosen by age' % (code, ' / '.join(c[0] for c in cands))
        if e['strat_grp'] and e['strat_grp'] == e['formation'].replace(' (chart key)', ''):
            e['strat_grp'] = ''
    n_age = sum(1 for e in legend if e['age_print'] or e['period_prt'])
    print(f'stratigraphy: {n_age}/{len(legend)} legend rows dated from the printed panel '
          f'({len(br_period)} period brackets, {len(br_sub) + len(br_extra)} sub-age brackets, '
          f'{sum(1 for e in legend if e["formation"])} formation names, {len(basins)} codes in the correlation chart)')
    return legend


# --------------------------------------------------------------------------
# 3.  Main
# --------------------------------------------------------------------------

# layers that are not geological-unit polygons
NON_UNIT_LAYERS = {'Other', 'Other 2', 'Other 3', 'LINES', '<Default>', 'Labels', 'Towns',
                   'Major River', 'Geological Boundary Transitional', 'Volcanic Plugs&Pipes'}

# dashed / segmented line symbols: re-chain consecutive fragments within tolerance (pt)
LINE_LAYERS = {
    # layer name: (output file, class, chain tolerance in pt, min fragment length filter)
    'Geological Boundary Exact': ('geological_boundaries', 'exact', 1.0, 0),
    'Geological boundary approximate': ('geological_boundaries', 'approximate', 2.5, 0),
    'Geological Boundary inferred.': ('geological_boundaries', 'inferred', 3.5, 0),
    'Geological Boundary Transitional': ('geological_boundaries', 'transitional', 6.0, 0),
    'Major Fractures / Faults': ('faults', 'major fracture / fault', 3.0, 0),
    'Fractures / Fault (inferred)': ('faults', 'fracture / fault (inferred)', 5.0, 0),
    'Anticlinal Axis': ('fold_axes', 'anticline', 10.0, 0),
    'Synclinal Axis': ('fold_axes', 'syncline', 10.0, 0),
    'Ridges': ('ridges', 'ridge', 16.0, 0),
    'Rivers': ('rivers', 'river', 0.0, 0),
    'Roads': ('roads', 'road', 0.5, 0),
    'Railway': ('railway', 'railway', 0.5, 10.0),      # drop the 5-pt cross ticks of the symbol
    'Younger Granite': ('younger_granite_outlines', 'younger granite (ring complex) outline', 0.0, 0),
}


def main(pdf_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
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
    words = assemble_words(texts)
    print(f'parsed {len(paths)} paths, {len(texts)} text runs -> {len(words)} strings')

    # layer drawing order (bottom -> top) for file prefixes
    layer_order = []
    for p in paths:
        key = (p['ocg_id'], p['layer'])
        if key not in layer_order:
            layer_order.append(key)
    layer_index = {k: i for i, k in enumerate(layer_order)}

    # ---- georeference
    affine, ginfo = fit_georef(paths, words)
    print('georef: %.4f pt/deg, max residual %.5f deg (~%.0f m), scale ~1:%d' % (
        ginfo['points_per_degree_x'], ginfo['max_residual_deg'], ginfo['max_residual_deg'] * 111000,
        ginfo['approx_scale_denominator']))
    with open(os.path.join(out_dir, 'georeferencing.json'), 'w') as f:
        json.dump(ginfo, f, indent=2, default=float)
    ll = lambda x, y: pdf_to_ll(affine, x, y)

    # map frame = clip box used by the data layers (approximate from graticule extent)
    gx = [x for x, _ in ginfo['graticule_x']]
    gy = [y for y, _ in ginfo['graticule_y']]

    # ---- legend (swatch colour -> code -> description), drawn in the layout layer
    legend = []
    layout_words = [w for w in words if w['layer'] in ('Other 3', 'Other 2')]
    for p in paths:
        if p['layer'] not in ('Other 3', 'Other 2') or p['op'] not in ('f*', 'f') or len(p['subpaths']) != 1:
            continue
        pts = p['subpaths'][0][0]
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        w_, h_ = max(xs) - min(xs), max(ys) - min(ys)
        if not (15 < w_ < 40 and 8 < h_ < 20) or min(xs) < max(gx):
            continue
        inside = [w for w in layout_words if min(xs) - 1 <= w['x0'] <= max(xs) and min(ys) <= w['y0'] <= max(ys)]
        right = [w for w in layout_words if max(xs) <= w['x0'] <= max(xs) + 6 and min(ys) - 2 <= w['y0'] <= max(ys)]
        code = ' '.join(w['text'] for w in sorted(inside, key=lambda w: w['x0'])).strip()
        desc = ' '.join(w['text'] for w in sorted(right, key=lambda w: w['x0'])).strip()
        legend.append({'fill': p['fill'], 'code': code, 'description': desc, 'x': min(xs), 'y': min(ys),
                       'y_top': max(ys), 'y_bot': min(ys)})
    legend.sort(key=lambda e: (-e['y'], e['x']))
    page_h = float(page.MediaBox[3])
    legend_stratigraphy(legend, words, paths, page_h)
    LEGEND_COLS = ['row', 'code', 'description', 'fill', 'formation', 'strat_grp', 'age_print', 'series', 'period_prt',
                   'eon', 'era', 'period', 'epoch', 'age_ma_min', 'age_ma_max', 'age_lit', 'age_src', 'rock_cls',
                   'basins', 'strat_note']
    with open(os.path.join(out_dir, 'legend.csv'), 'w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=LEGEND_COLS)
        wr.writeheader()
        for e in legend:
            wr.writerow({k: ('' if e.get(k) is None else e.get(k)) for k in LEGEND_COLS})
    colour_counts = collections.Counter(e['fill'] for e in legend)
    legend_by_colour = {e['fill']: e for e in legend if colour_counts[e['fill']] == 1}
    print(f'legend entries: {len(legend)} ({len(legend_by_colour)} with a unique colour)')

    # ---- labels -> point layer
    def label_kind(w):
        if w['layer'] == '<Default>':
            return 'water name'
        if w['layer'] != 'Labels':
            return 'layout'
        if w['font'] == 'TimesNewRomanPSMT':
            return 'town'
        if w['font'] == 'ArialMT' and w['size'] > 6:
            return 'state capital'
        return 'unit code'

    map_words = [w for w in words if w['layer'] in ('Labels', '<Default>')]
    # drop exact duplicates (halo text is drawn twice)
    seen, uniq_words = set(), []
    for w in map_words:
        key = (w['text'], round(w['x0'], 1), round(w['y0'], 1))
        if key in seen:
            continue
        seen.add(key)
        uniq_words.append(w)
    lab = ShpOut(os.path.join(out_dir, 'labels'), shapefile.POINT, [
        ('text', 'C', 100, 0), ('kind', 'C', 16, 0), ('font', 'C', 32, 0),
        ('size_pt', 'N', 8, 2), ('angle', 'N', 8, 2), ('layer', 'C', 32, 0), ('src_seq', 'N', 10, 0)])
    for w in uniq_words:
        if not w['text'].strip():
            continue
        x, y = ll(w['x0'], w['y0'])
        lab.add(Point(x, y), [w['text'], label_kind(w), w['font'], round(w['size'], 2),
                              round(w['angle'], 2), w['layer'], w['seq']])
    print('labels:', lab.close())

    unit_code_pts = [(Point(*ll(w['x0'] + 0.3 * w['size'] * w['nchar'], w['y0'] + 0.35 * w['size'])), w['text'].strip())
                     for w in uniq_words if label_kind(w) == 'unit code' and w['text'].strip()]

    # ---- geology polygons
    unit_layers = [(oid, name) for oid, name in layer_order if name not in NON_UNIT_LAYERS]
    unit_paths = collections.defaultdict(list)
    for p in paths:
        if p['layer'] not in NON_UNIT_LAYERS and p['op'] in ('f', 'f*', 'B', 'B*', 'b', 'b*'):
            unit_paths[(p['ocg_id'], p['layer'])].append(p)
    poly_fields = [('ocg_id', 'N', 6, 0), ('layer_no', 'N', 4, 0), ('unit', 'C', 120, 0),
                   ('fill', 'C', 7, 0), ('code', 'C', 12, 0), ('code_src', 'C', 6, 0),
                   ('leg_code', 'C', 12, 0), ('leg_desc', 'C', 120, 0), ('lbl_code', 'C', 12, 0),
                   ('n_lbl', 'N', 5, 0), ('area_km2', 'N', 14, 3), ('perim_km', 'N', 12, 2),
                   ('cen_lon', 'N', 11, 6), ('cen_lat', 'N', 11, 6), ('n_rings', 'N', 5, 0),
                   ('src_seq', 'N', 10, 0), ('dup_of', 'N', 10, 0),
                   # stratigraphy read from the EXPLANATIONS panel (see legend.csv for the full record)
                   ('leg_row', 'N', 4, 0), ('formation', 'C', 64, 0), ('strat_grp', 'C', 48, 0),
                   ('age_print', 'C', 48, 0), ('series', 'C', 64, 0), ('period_prt', 'C', 40, 0),
                   ('eon', 'C', 40, 0), ('era', 'C', 64, 0), ('period', 'C', 48, 0), ('epoch', 'C', 64, 0),
                   ('age_ma_min', 'N', 9, 4), ('age_ma_max', 'N', 9, 4), ('age_src', 'C', 120, 0),
                   ('rock_cls', 'C', 16, 0), ('basins', 'C', 120, 0)]
    STRAT_KEYS = ['row', 'formation', 'strat_grp', 'age_print', 'series', 'period_prt', 'eon', 'era', 'period',
                  'epoch', 'age_ma_min', 'age_ma_max', 'age_src', 'rock_cls', 'basins']
    legend_by_code = collections.defaultdict(list)
    for e in legend:
        legend_by_code[e['code']].append(e)

    def hex_rgb(h):
        h = (h or '#000000').lstrip('#')
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)

    def code_key(c):
        # map labels confuse capital I and lower-case l (GIls / Glls); compare codes without that distinction
        return c.lower().replace('i', 'l')
    legend_by_ckey = collections.defaultdict(list)
    legend_by_form = collections.defaultdict(list)
    for e in legend:
        legend_by_ckey[code_key(e['code'])].append(e)
        if e.get('formation'):
            legend_by_form[re.sub(r'[^a-z0-9]+', '', e['formation'].replace('(chart key)', '').lower())].append(e)
    older_granite = next((e for e in legend if 'older' in (e.get('series') or '').lower() and e['code'] == 'OGh'), None)

    def strat_record(leg, code, fill, layer_name=''):
        """legend row for a polygon: the colour/description match, else its code (nearest colour if ambiguous),
        else the formation name; units missing from the printed legend get a flagged fall-back or stay blank."""
        e, note = leg, ''
        if e is None and code:
            cands = legend_by_code.get(code) or legend_by_ckey.get(code_key(code)) or []
            if len(cands) > 1:
                fr = hex_rgb(fill)
                cands = sorted(cands, key=lambda c: sum((a - b) ** 2 for a, b in zip(hex_rgb(c['fill']), fr)))
            if cands:
                e = cands[0]
                if e['code'] != code:
                    note = f'legend row matched by code with I/l confusion ({code} = {e["code"]})'
        if e is None and layer_name:
            cands = legend_by_form.get(re.sub(r'[^a-z0-9]+', '', layer_name.lower()), [])
            if len(cands) == 1:
                e = cands[0]
                note = f'not in printed legend; layer name "{layer_name}" = formation of legend row {e["row"]} ({e["code"]})'
        if e is None and code.startswith('OG') and older_granite is not None:
            # e.g. OGp 'Coarse porphyritic biotite and biotite hornblende granite' (245 polygons) has no legend row
            rec = [None, '', '', '', older_granite['series'], older_granite['period_prt'], older_granite['eon'],
                   older_granite['era'], older_granite['period'], older_granite['epoch'],
                   older_granite['age_ma_min'], older_granite['age_ma_max'],
                   'fall-back: unit not in printed legend; code family OG- = Pan-African Older Granite rows 62-70',
                   rock_class(layer_name, code), '']
            return rec
        if e is None:
            return [None, '', '', '', '', '', '', '', '', '', None, None,
                    'not in printed legend; no age inferred' if (code or layer_name) else '',
                    rock_class(layer_name, code) if layer_name else '', '']
        rec = [e.get(k) if e.get(k) is not None else ('' if k not in ('row', 'age_ma_min', 'age_ma_max') else None)
               for k in STRAT_KEYS]
        if note:
            rec[STRAT_KEYS.index('age_src')] = (note + '; ' + rec[STRAT_KEYS.index('age_src')]).strip('; ')
        return rec
    units_out = ShpOut(os.path.join(out_dir, 'geology_units'), shapefile.POLYGON, poly_fields)
    from shapely.strtree import STRtree
    code_tree = STRtree([pt for pt, _ in unit_code_pts]) if unit_code_pts else None
    per_layer_records = collections.defaultdict(list)
    unit_records_all = []
    n_invalid = 0
    layer_codes = collections.defaultdict(collections.Counter)
    polys_tmp = []
    for key in unit_layers:
        for p in unit_paths.get(key, []):
            geom = build_polygon(p['subpaths'], affine)
            if geom is None or geom.is_empty:
                continue
            if not geom.is_valid:
                n_invalid += 1
                geom = make_valid(geom)
            lbl_codes = collections.Counter()
            if code_tree is not None:
                for idx in code_tree.query(geom, predicate='contains'):
                    lbl_codes[unit_code_pts[idx][1]] += 1
            lbl_code = lbl_codes.most_common(1)[0][0] if lbl_codes else ''
            if lbl_code:
                layer_codes[key][lbl_code] += 1
            polys_tmp.append((key, p, geom, lbl_code, sum(lbl_codes.values())))
    def norm(s):
        return re.sub(r'[^a-z0-9]+', '', s.lower())
    legend_by_desc = collections.defaultdict(list)
    for e in legend:
        legend_by_desc[norm(e['description'])].append(e)

    def legend_lookup(fill, layer_name):
        # 1) colour + description both match, 2) unique colour, 3) unique description
        same_col = [e for e in legend if e['fill'] == fill]
        hit = [e for e in same_col if norm(e['description']) == norm(layer_name)]
        if len(hit) == 1:
            return hit[0]
        if len(same_col) == 1:
            return same_col[0]
        hit = legend_by_desc.get(norm(layer_name), [])
        if len(hit) == 1:
            return hit[0]
        return None

    seen_geoms = {}
    for key, p, geom, lbl_code, n_lbl in polys_tmp:
        leg = legend_lookup(p['fill'], key[1])
        leg_code = leg['code'] if leg else ''
        leg_desc = leg['description'] if leg else ''
        if leg_code:
            code, src = leg_code, 'legend'
        elif lbl_code:
            code, src = lbl_code, 'label'
        elif layer_codes[key]:
            code, src = layer_codes[key].most_common(1)[0][0], 'layer'
        else:
            code, src = '', ''
        dup_of = seen_geoms.setdefault(geom.wkb, p['seq'])
        dup_of = 0 if dup_of == p['seq'] else dup_of
        cen = geom.representative_point()
        rec = [key[0], layer_index[key], key[1], p['fill'] or '', code, src, leg_code, leg_desc,
               lbl_code, n_lbl, round(geo_area_km2(geom), 3), round(geo_perimeter_km(geom), 2),
               round(cen.x, 6), round(cen.y, 6),
               len(geom.geoms) if geom.geom_type == 'MultiPolygon' else 1, p['seq'], dup_of] + \
            strat_record(leg, code, p['fill'], key[1])
        units_out.add(shapely_to_shp_geom(geom), rec)
        per_layer_records[key].append((geom, rec))
        unit_records_all.append((geom, rec))
    print('geology polygons:', units_out.close(), f'({n_invalid} needed make_valid)')
    # one shapefile per original PDF layer
    for key, recs in per_layer_records.items():
        fn = os.path.join(out_dir, 'by_layer', f'{layer_index[key]:03d}_{safe_name(key[1])}')
        o = ShpOut(fn, shapefile.POLYGON, poly_fields)
        for geom, rec in recs:
            o.add(shapely_to_shp_geom(geom), rec)
        o.close()

    # ---- line layers
    line_fields = [('ocg_id', 'N', 6, 0), ('layer', 'C', 64, 0), ('class', 'C', 48, 0),
                   ('stroke', 'C', 7, 0), ('width_pt', 'N', 6, 2), ('n_frag', 'N', 6, 0),
                   ('len_km', 'N', 12, 3), ('src_seq', 'N', 10, 0)]
    outs = {}
    counts = collections.Counter()
    for (oid, lname) in layer_order:
        if lname not in LINE_LAYERS:
            continue
        fname, cls, tol, min_len = LINE_LAYERS[lname]
        lps = [p for p in paths if p['ocg_id'] == oid and p['op'] in ('S', 's', 'B', 'B*', 'b', 'b*')
               and path_length_pt(p) >= min_len]
        if fname not in outs:
            outs[fname] = ShpOut(os.path.join(out_dir, fname), shapefile.POLYLINE, line_fields)
        chains = chain_fragments(lps, tol) if tol > 0 else [(pts, 1, p['seq']) for p in lps for pts, _ in p['subpaths'] if len(pts) >= 2]
        if lname == 'Roads':
            chains = merge_double_lines(chains, 3.0)
        style = collections.Counter((p['stroke'], round(p['lw'], 2)) for p in lps).most_common(1)
        stroke, lw = style[0][0] if style else ('', 0)
        for pts, nfrag, seq in chains:
            coords = clean_ring([ll(*q) for q in pts]) if False else [ll(*q) for q in pts]
            coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
            if len(coords) < 2:
                continue
            outs[fname].add(LineString(coords), [oid, lname, cls, stroke or '', lw, nfrag,
                                                 round(geo_length_km(coords), 3), seq])
            counts[fname] += 1
        # raw (un-chained) copy per layer for reference
        raw = ShpOut(os.path.join(out_dir, 'by_layer', f'{layer_index[(oid, lname)]:03d}_{safe_name(lname)}'),
                     shapefile.POLYLINE, line_fields)
        for p in lps:
            for pts, _ in p['subpaths']:
                coords = [ll(*q) for q in pts]
                coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
                if len(coords) >= 2:
                    raw.add(LineString(coords), [oid, lname, cls, p['stroke'] or '', round(p['lw'], 2), 1,
                                                 round(geo_length_km(coords), 3), p['seq']])
        raw.close()
    for fname, o in outs.items():
        o.close()
        print(f'{fname}: {counts[fname]} lines')

    # state boundaries: the continuous wide grey band carries the full geometry;
    # the black dash-dot pieces drawn on top are symbol fragments.
    sb = [p for p in paths if p['layer'] == 'State_Boundarys']
    wide = [p for p in sb if p['lw'] > 1.0]
    o = ShpOut(os.path.join(out_dir, 'state_boundaries'), shapefile.POLYLINE, line_fields)
    for p in wide:
        for pts, _ in p['subpaths']:
            coords = [ll(*q) for q in pts]
            coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
            if len(coords) >= 2:
                o.add(LineString(coords), [p['ocg_id'], 'State_Boundarys', 'state boundary', p['stroke'] or '',
                                           round(p['lw'], 2), 1, round(geo_length_km(coords), 3), p['seq']])
    print('state_boundaries:', o.close())
    dashes = [p for p in sb if p['lw'] <= 1.0]
    if dashes:
        oid = dashes[0]['ocg_id']
        raw = ShpOut(os.path.join(out_dir, 'by_layer', f'{layer_index[(oid, "State_Boundarys")]:03d}_State_Boundarys_dashes'),
                     shapefile.POLYLINE, line_fields)
        for pts, nfrag, seq in chain_fragments(dashes, 2.5):
            coords = [ll(*q) for q in pts]
            coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
            if len(coords) >= 2:
                raw.add(LineString(coords), [oid, 'State_Boundarys', 'state boundary (dash fragments)', '#000000',
                                             0.36, nfrag, round(geo_length_km(coords), 3), seq])
        raw.close()

    # major rivers: filled polygons (+ their outlines are the strokes)
    mr = [p for p in paths if p['layer'] == 'Major River']
    o = ShpOut(os.path.join(out_dir, 'major_rivers_poly'), shapefile.POLYGON, [
        ('ocg_id', 'N', 6, 0), ('layer', 'C', 32, 0), ('name', 'C', 254, 0), ('fill', 'C', 7, 0),
        ('area_km2', 'N', 14, 3), ('perim_km', 'N', 12, 2), ('n_rings', 'N', 5, 0), ('src_seq', 'N', 10, 0)])
    water_names = [(Point(*ll(w['x0'] + 0.3 * w['size'] * w['nchar'], w['y0'] + 0.35 * w['size'])),
                    re.sub(r'\s+', ' ', w['text']).strip()) for w in uniq_words if label_kind(w) == 'water name']
    for p in mr:
        if p['op'] in ('f', 'f*', 'B', 'B*', 'b', 'b*'):
            geom = build_polygon(p['subpaths'], affine)
            if geom is not None and not geom.is_empty:
                pg = prep(geom)
                inside = []
                for pt, name in water_names:
                    if pg.contains(pt) and name not in inside:
                        inside.append(name)
                o.add(shapely_to_shp_geom(geom), [p['ocg_id'], 'Major River', '; '.join(inside), p['fill'] or '',
                                                  round(geo_area_km2(geom), 3), round(geo_perimeter_km(geom), 2),
                                                  len(geom.geoms) if geom.geom_type == 'MultiPolygon' else 1, p['seq']])
    print('major_rivers_poly:', o.close())
    o = ShpOut(os.path.join(out_dir, 'major_rivers_outline'), shapefile.POLYLINE, line_fields)
    for p in mr:
        if p['op'] in ('S', 's'):
            for pts, _ in p['subpaths']:
                coords = [ll(*q) for q in pts]
                coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1]]
                if len(coords) >= 2:
                    o.add(LineString(coords), [p['ocg_id'], 'Major River', 'major river outline', p['stroke'] or '',
                                               round(p['lw'], 2), 1, round(geo_length_km(coords), 3), p['seq']])
    print('major_rivers_outline:', o.close())

    # ---- point layers from marker symbols
    pt_fields = [('ocg_id', 'N', 6, 0), ('layer', 'C', 32, 0), ('name', 'C', 64, 0),
                 ('name_kind', 'C', 16, 0), ('name_dist', 'N', 8, 2), ('src_seq', 'N', 10, 0),
                 ('lon', 'N', 11, 6), ('lat', 'N', 11, 6),
                 # geology unit of this map under the point
                 ('unit_code', 'C', 12, 0), ('unit', 'C', 120, 0), ('unit_era', 'C', 64, 0), ('unit_per', 'C', 48, 0)]
    unit_geoms = [g for g, _ in unit_records_all if not g.is_empty]
    unit_recs = [r for g, r in unit_records_all if not g.is_empty]
    unit_tree = STRtree(unit_geoms) if unit_geoms else None
    FI = {name: k for k, (name, *_rest) in enumerate(poly_fields)}

    def under(pt):
        """[unit_code, unit, era, period] of the (smallest) unit polygon containing the point."""
        if unit_tree is None:
            return ['', '', '', '']
        hits = [k for k in unit_tree.query(pt, predicate='within')]
        if not hits:
            return ['', '', '', '']
        k = min(hits, key=lambda k: unit_recs[k][FI['area_km2']])
        r = unit_recs[k]
        return [r[FI['code']], r[FI['unit']], r[FI['era']] or '', r[FI['period']] or '']

    def pt_rec(ocg, layer, name, kind, dist, seq, lon, lat):
        return [ocg, layer, name, kind, dist, seq, round(lon, 6), round(lat, 6)] + under(Point(lon, lat))
    towns = [p for p in paths if p['layer'] == 'Towns']
    town_labels = [w for w in uniq_words if label_kind(w) == 'town']
    # ArcMap put each town label up-right of its marker: the marker centre sits
    # ~0.15 em left and ~0.4 em below the first glyph.  Greedy nearest matching.
    cands = []
    for li, w in enumerate(town_labels):
        ax, ay = w['x0'] - 0.15 * w['size'], w['y0'] - 0.41 * w['size']
        for ti, p in enumerate(towns):
            cx, cy = centroid_pdf(p)
            dist = math.hypot(cx - ax, cy - ay)
            if dist < 14:
                cands.append((dist, li, ti))
    cands.sort()
    town_name, used_lab = {}, set()
    for dist, li, ti in cands:
        if ti in town_name or li in used_lab:
            continue
        town_name[ti] = (town_labels[li]['text'], 'town', dist)
        used_lab.add(li)
    o = ShpOut(os.path.join(out_dir, 'towns'), shapefile.POINT, pt_fields)
    for ti, p in enumerate(towns):
        cx, cy = centroid_pdf(p)
        name, kind, dist = town_name.get(ti, ('', '', 0))
        lon, lat = ll(cx, cy)
        o.add(Point(lon, lat), pt_rec(p['ocg_id'], 'Towns', name, kind, round(dist, 2), p['seq'], lon, lat))
    print('towns:', o.close(), f'({len(town_name)} named)')

    # state capitals have no marker in the PDF (label only, drawn twice for the halo).
    # The labels were placed roughly centred on the city, so use the label centre
    # (checked against real coordinates: median error ~7 km, max ~15 km).
    caps, cap_seen = [], []
    for w in uniq_words:
        if label_kind(w) != 'state capital':
            continue
        if any(w['text'] == t and math.hypot(w['x0'] - x, w['y0'] - y) < 3 for t, x, y in cap_seen):
            continue
        cap_seen.append((w['text'], w['x0'], w['y0']))
        caps.append(w)
    o = ShpOut(os.path.join(out_dir, 'state_capitals'), shapefile.POINT, pt_fields)
    for w in caps:
        width = (w['x1'] - w['x0']) + 0.65 * w['size']
        px, py = w['x0'] + width / 2, w['y0'] + 0.35 * w['size']
        lon, lat = ll(px, py)
        o.add(Point(lon, lat), pt_rec(w['ocg_id'], 'Labels', w['text'], 'label centre', 0, w['seq'], lon, lat))
    print('state_capitals:', o.close())

    vp = [p for p in paths if p['layer'] == 'Volcanic Plugs&Pipes']
    o = ShpOut(os.path.join(out_dir, 'volcanic_plugs'), shapefile.POINT, pt_fields)
    for p in vp:
        cx, cy = centroid_pdf(p)
        lon, lat = ll(cx, cy)
        o.add(Point(lon, lat), pt_rec(p['ocg_id'], 'Volcanic Plugs&Pipes', '', 'no name on map', 0, p['seq'], lon, lat))
    print('volcanic_plugs:', o.close())

    # ---- graticule + frame (QA)
    o = ShpOut(os.path.join(out_dir, 'graticule'), shapefile.POLYLINE, [('axis', 'C', 3, 0), ('value', 'N', 8, 3)])
    for x, lon in ginfo['graticule_x']:
        o.add(LineString([ll(x, min(gy)), ll(x, max(gy))]), ['lon', lon])
    for y, lat in ginfo['graticule_y']:
        o.add(LineString([ll(min(gx), y), ll(max(gx), y)]), ['lat', lat])
    o.close()

    # ---- georeferenced raster of the map face (for overlay QA)
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        pg = doc[0]
        H = pg.rect.height
        x0, x1 = min(gx) - 20, max(gx) + 20
        y0, y1 = min(gy) - 20, max(gy) + 20
        clip = pymupdf.Rect(x0, H - y1, x1, H - y0)
        dpi = 150
        pix = pg.get_pixmap(dpi=dpi, clip=clip)
        rdir = os.path.join(out_dir, 'map_raster')
        os.makedirs(rdir, exist_ok=True)
        pix.save(os.path.join(rdir, 'geological_map_nigeria.png'))
        a, b, c, d = affine
        px_deg_x = a * 72 / dpi
        px_deg_y = -c * 72 / dpi
        ulx, uly = ll(x0, y1)
        with open(os.path.join(rdir, 'geological_map_nigeria.pgw'), 'w') as f:
            f.write(f'{px_deg_x:.10f}\n0\n0\n{px_deg_y:.10f}\n{ulx + px_deg_x / 2:.8f}\n{uly + px_deg_y / 2:.8f}\n')
        with open(os.path.join(rdir, 'geological_map_nigeria.png.aux.xml'), 'w') as f:
            f.write(f'<PAMDataset><SRS>{WGS84_PRJ}</SRS></PAMDataset>')
        print('raster:', pix.width, 'x', pix.height)
    except Exception as e:  # pragma: no cover
        print('raster skipped:', e)

    # ---- optional: bundle all main layers into one GeoPackage (needs pyogrio/GDAL)
    try:
        import pyogrio
        from pyogrio.raw import read as ogr_read, write as ogr_write
        gpkg = os.path.join(out_dir, 'nigeria_geology.gpkg')
        if os.path.exists(gpkg):
            os.remove(gpkg)
        for fn in sorted(os.listdir(out_dir)):
            if fn.endswith('.shp'):
                meta, _, geometry, fields = ogr_read(os.path.join(out_dir, fn))
                gtype = meta['geometry_type']
                if gtype == 'Polygon':
                    gtype = 'MultiPolygon'
                ogr_write(gpkg, geometry, fields, layer=fn[:-4], driver='GPKG', crs='EPSG:4326',
                          geometry_type=gtype, fields=meta['fields'], append=True,
                          promote_to_multi=(gtype == 'MultiPolygon'))
        print('geopackage:', gpkg)
    except ImportError:
        print('pyogrio not installed - GeoPackage bundle skipped')

    print('done ->', out_dir)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
