#!/usr/bin/env python3
"""
QA contact sheets for the symbol-identification pass.

Renders, for every signature group that has no table-text evidence of its own,
two example patches cut from the map raster at native resolution (8x nearest
neighbour) together with the evidence a human analyst would have at hand:
the number(s) printed within 25 pt and their EXPLANATIONS-table minerals.
The analyst reads the sheets and writes the determination into
symbol_decisions.py - one row per group, no candidate lists.
"""
import collections
import json
import os
import pickle
import sys

import numpy as np
from PIL import Image, ImageDraw

import symbol_identify as si

ROOT = os.path.dirname(os.path.abspath(__file__))
SHP = os.path.join(ROOT, 'shapefiles_minerals')
OUT = os.path.join(ROOT, '_scratch', 'qa')


def norm(n):
    return n.split(' (')[0]


def load():
    d = pickle.load(open(os.path.join(SHP, '_debug.pkl'), 'rb'))
    syms, labs = d['symbols'], d['labels']
    m = si.Matcher()
    snap, hint = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for l in labs:
        e = l.get('entry')
        if not e:
            continue
        mins = tuple(sorted({norm(x) for x in e['minerals']}))
        if l.get('sym') is not None:
            snap[l['sym']][mins] += 1
        elif l.get('hint') is not None:
            hint[l['hint']][mins] += 1
    near = collections.defaultdict(list)
    lab_pt = np.array([(l['cx'], l['cy']) for l in labs])
    for i, s in enumerate(syms):
        dd = np.hypot(lab_pt[:, 0] - s['pt'][0], lab_pt[:, 1] - s['pt'][1])
        for j in np.argsort(dd)[:2]:
            if dd[j] <= 25:
                e = labs[j].get('entry')
                near[i].append((labs[j]['zone'], labs[j]['number'],
                                ' | '.join(sorted({norm(x) for x in e['minerals']})) if e else 'no table row',
                                round(float(dd[j]), 1)))
    return syms, labs, m, snap, hint, near


def groups_of(syms, snap, hint):
    g = collections.defaultdict(list)
    for i, s in enumerate(syms):
        g[(s['colour'], s['bw'], s['bh'], s['fill'])].append(i)
    out = []
    for k, idx in sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        votes = snap[idx[0]] if False else collections.Counter()
        for i in idx:
            votes.update({m: 2 * n for m, n in snap[i].items()})
            votes.update({m: n for m, n in hint[i].items()})
        out.append({'sig': k, 'idx': idx, 'votes': votes})
    return out


def sheet(m, syms, rows, path, z=8, per_sheet=24, cell_w=300, cell_h=110, start=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0
    for b0 in range(start, len(rows), per_sheet):
        chunk = rows[b0:b0 + per_sheet]
        cols = 2
        rr = (len(chunk) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell_w, rr * cell_h), 'white')
        dr = ImageDraw.Draw(sheet)
        for k, row in enumerate(chunk):
            sig, idx, votes = row['sig'], row['idx'], row['votes']
            cx, cy = (k % cols) * cell_w, (k // cols) * cell_h
            tiles = []
            for i in idx[:2]:
                s = syms[i]
                p = m.patch(s['x0'], s['y0'], s['x1'], s['y1'])
                tiles.append(Image.fromarray(p.astype(np.uint8)).resize(
                    (min(cell_h - 30, p.shape[1] * z), min(cell_h - 30, p.shape[0] * z)), Image.NEAREST))
            x = cx + 4
            for t in tiles:
                sheet.paste(t, (x, cy + 24))
                x += t.width + 6
            dr.text((cx + 4, cy + 4), '%s %dx%d %s  n=%d' % (sig[0], sig[1], sig[2], sig[3], len(idx)), fill='black')
            vt = '; '.join('%s x%d' % ('+'.join(v[0]), v[1]) for v in votes.most_common(2)) or 'no table vote'
            nt = '; '.join('%s%d:%s@%s' % (q[0], q[1], q[2][:22], q[3]) for q in row.get('near', [])[:2]) or 'no number within 25pt'
            dr.text((cx + 4, cy + 14), vt[:64], fill=(140, 0, 0))
            dr.text((cx + 4, cy + cell_h - 14), nt[:64], fill=(0, 0, 140))
        sheet.save('%s_%02d.png' % (path, b0 // per_sheet))
        n += 1
    return n


if __name__ == '__main__':
    syms, labs, m, snap, hint, near = load()
    rows = []
    for gr in groups_of(syms, snap, hint):
        if gr['votes']:
            continue
        gr['near'] = near[gr['idx'][0]]
        rows.append(gr)
    print('groups without table evidence:', len(rows), 'blobs', sum(len(r['idx']) for r in rows))
    only = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if only == 'big':
        rows = [r for r in rows if len(r['idx']) >= 5]
    n = sheet(m, syms, rows, os.path.join(OUT, 'open'))
    print('sheets written:', n)
