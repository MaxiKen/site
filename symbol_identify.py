#!/usr/bin/env python3
"""
Definitive identification of every mineral symbol printed on the 2023 Mineral
Resources Map of Nigeria.

The previous pipeline classified each detected symbol blob only by a coarse
(colour, size, fill) signature and therefore produced a *list of candidates*
(e.g. "Gypsum | Baryte | Phosphate | Phosphate Rock | Trona | Bitumen") – or no
identification at all for 243 of the 1 593 blobs.  This module gives every
symbol exactly one identification, by analysis rather than by option list:

  1. template matching at the map's own resolution.  The map face is a set of
     75 dpi raster strips (1.042 px/pt), so a symbol carries 8-30 px of real
     information; rendering the PDF finer only interpolates.  Each blob is
     therefore cut from map_raster/mineral_map_base_75dpi.png at native
     resolution and compared with every one of the 66 legend symbols (cut from
     the legend sheet, 3.125 px/pt) resampled onto the blob's pixel box.  Three
     independent measures are combined: ink-mask Dice, grey-value NCC and
     palette-colour histogram agreement.  Shifts of +-2 px are tried.
  2. the printed EXPLANATIONS table as the textual authority.  A symbol that
     sits at a numbered locality inherits that row's mineral whenever the
     table's mineral is among the visually possible ones – exactly how a human
     analyst reads the sheet (the table and the symbol are two statements of
     the same fact by the same cartographer).
  3. only when neither applies does the pure visual best match decide, and the
     score margin over the runner-up is kept so the strength of every single
     decision is visible.

The output (symbol_identification.csv/.json) has one row per symbol blob with
exactly one `mineral` each – never a candidate list, never an empty value.
"""
import collections
import csv
import glob
import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SHP = os.path.join(ROOT, 'shapefiles_minerals')
RASTER = os.path.join(SHP, 'map_raster', 'mineral_map_base_75dpi.png')

# palette copied from extract_mineral_map.SYMBOL_PALETTE (keep in sync)
SYMBOL_PALETTE = {
    'yellow': (255, 245, 0), 'khaki': (151, 148, 107), 'green': (0, 146, 63), 'red': (218, 37, 29),
    'purple': (151, 69, 120), 'light green': (132, 194, 37), 'grey': (130, 130, 130), 'dark grey': (96, 93, 92),
    'blue grey': (102, 122, 179), 'brown': (192, 128, 64), 'bright green': (0, 255, 0), 'orange': (231, 120, 23),
    'tan': (187, 130, 91), 'green 2': (0, 160, 64), 'dark tan': (149, 127, 102), 'violet': (132, 0, 168),
    'dark blue': (0, 77, 168), 'purple 2': (169, 0, 230), 'magenta': (224, 32, 128),
}
INK = 720          # RGB sum below this = ink (same threshold as the legend crops)
PAL_NAMES = list(SYMBOL_PALETTE)
PAL = np.array([SYMBOL_PALETTE[n] for n in PAL_NAMES])


def ink_mask(arr):
    return arr[:, :, :3].sum(axis=2) < INK


def colour_hist(arr, mask):
    """Fraction of ink pixels per palette colour (+ black/outline, + ink amount)."""
    h = np.zeros(len(PAL_NAMES) + 2)
    px = arr[:, :, :3][mask]
    if len(px) == 0:
        return h
    dist = np.abs(px[:, None, :] - PAL[None, :, :]).sum(axis=2)
    near, ok = dist.argmin(axis=1), dist.min(axis=1) < 150
    for i in range(len(PAL_NAMES)):
        h[i] = ((near == i) & ok).mean()
    h[-2] = (~ok).mean()
    h[-1] = mask.mean()
    return h


class Matcher:
    """Template matching of map-resolution symbol blobs against the legend symbols."""

    def __init__(self, base_png=RASTER, legend_dir=os.path.join(SHP, 'legend_symbols')):
        self.base = np.array(Image.open(base_png).convert('RGB')).astype(int)
        self.templates = []
        for f in sorted(glob.glob(os.path.join(legend_dir, 'symbol_*.png'))):
            arr = np.array(Image.open(f).convert('RGB'))
            m = ink_mask(arr.astype(int))
            if not m.any():
                continue
            rs, cs = np.where(m)
            crop = arr[rs.min():rs.max() + 1, cs.min():cs.max() + 1]
            no = int(os.path.basename(f).split('_')[1])
            # printed size of the legend artwork in points (legend strips are 3.125 px/pt)
            mm = ink_mask(crop.astype(int))
            rs, cs = np.where(mm)
            self.templates.append({'no': no, 'file': os.path.basename(f), 'crop': crop,
                                   'pt_w': (cs.max() - cs.min() + 1) / 3.125,
                                   'pt_h': (rs.max() - rs.min() + 1) / 3.125})
        self._cache = {}
        self.by_colour = collections.defaultdict(list)
        for t in self.templates:
            h = colour_hist(t['crop'].astype(int), ink_mask(t['crop'].astype(int)))
            k = int(h[:len(PAL_NAMES)].argmax())
            self.by_colour[PAL_NAMES[k] if h[k] > 0.15 else 'outline'].append(t['no'])

    def _tpl_at(self, no, w, h):
        key = (no, w, h)
        if key not in self._cache:
            t = next(t for t in self.templates if t['no'] == no)
            im = Image.fromarray(t['crop']).resize((max(2, w), max(2, h)), Image.LANCZOS)
            a = np.array(im).astype(int)
            self._cache[key] = (a, ink_mask(a), colour_hist(a, ink_mask(a)), a[:, :, :3].mean(axis=2))
        return self._cache[key]

    @staticmethod
    def dice(a, b):
        s = a.sum() + b.sum()
        return 2.0 * (a & b).sum() / s if s else 0.0

    @staticmethod
    def ncc(a, b):
        a, b = a - a.mean(), b - b.mean()
        d = np.sqrt((a * a).sum() * (b * b).sum())
        return float((a * b).sum() / d) if d else 0.0

    def patch(self, x0, y0, x1, y1, pad=1):
        H, W = self.base.shape[:2]
        xa, ya = max(0, x0 - pad), max(0, y0 - pad)
        xb, yb = min(W, x1 + pad), min(H, y1 + pad)
        return self.base[ya:yb, xa:xb]

    def rank(self, patch):
        """Score every legend symbol against the patch; return a ranked list of
        (score, template, parts) with the best first."""
        pm = ink_mask(patch)
        if not pm.any():
            return []
        # tighten to the ink box so the +-1 px pad does not bias the size
        rs, cs = np.where(pm)
        patch = patch[rs.min():rs.max() + 1, cs.min():cs.max() + 1]
        pm = ink_mask(patch)
        ph = colour_hist(patch, pm)
        pg = patch[:, :, :3].mean(axis=2)
        h, w = patch.shape[:2]
        out = []
        for t in self.templates:
            _ta, tm0, th, tg0 = self._tpl_at(t['no'], w, h)
            best, parts = 0.0, {}
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    tm = np.roll(np.roll(tm0, dy, 0), dx, 1)
                    if dy:
                        tm[0 if dy > 0 else -1, :] = False
                    if dx:
                        tm[:, 0 if dx > 0 else -1] = False
                    tg = np.roll(np.roll(tg0, dy, 0), dx, 1) + 0.0
                    if dy:
                        tg[0 if dy > 0 else -1, :] = 255.0
                    if dx:
                        tg[:, 0 if dx > 0 else -1] = 255.0
                    d = self.dice(pm, tm)
                    nc = self.ncc(pg, tg)
                    ca = float(np.minimum(ph[:len(PAL_NAMES) + 1], th[:len(PAL_NAMES) + 1]).sum())
                    sc = 0.45 * d + 0.30 * max(0.0, nc) + 0.25 * ca
                    if sc > best:
                        best, parts = sc, {'dice': round(float(d), 3), 'ncc': round(float(nc), 3),
                                           'colour': round(ca, 3), 'shift': (dx, dy)}
            out.append((best, t, parts))
        out.sort(key=lambda r: -r[0])
        return out

    def identify(self, patch):
        r = self.rank(patch)
        return r[0] if r else (0.0, None, {})

    def rank_within(self, patch, names):
        """Rank only the legend symbols whose mineral name is in `names`."""
        r = [x for x in self.rank(patch) if mineral_of_file(x[1]['file']) in names]
        return r


LEGEND_MINERAL = {}


def mineral_of_file(fn):
    """legend_symbols/symbol_12_Clay_Pottery_Clay.png -> 'Clay / Pottery Clay'."""
    if not LEGEND_MINERAL:
        with open(os.path.join(SHP, 'mineral_legend.csv')) as f:
            for row in csv.DictReader(f):
                if row['symbol_png']:
                    LEGEND_MINERAL[int(os.path.basename(row['symbol_png']).split('_')[1])] = row['mineral']
    return LEGEND_MINERAL.get(int(fn.split('_')[1]), fn)


# --------------------------------------------------------------------------- the pass
def identify_all(symbols, labels, matcher=None, towns=None):
    """Give every symbol blob exactly one identification.

    Returns a list (one dict per blob, same order as `symbols`) with
        mineral  the single determination (or an explicit 'not a mineral
                 symbol: ...' class),
        method   how it was determined,
        evidence the corroborating fact (vote count / template score / host),
        score, margin, family  template-match diagnostics when used.
    Precedence (first that applies):
      1. the analyst's signature determination (symbol_decisions.GROUP_DECISIONS);
         a 'family:' entry is resolved per blob by template ranking inside the
         family, with the table row at the blob's number preferred when the row
         names a member of the family;
      2. the EXPLANATIONS-table row of a number snapped to the blob;
      3. the row of the nearest number within 14 pt;
      4. fragment of an identified neighbouring blob of the same colour;
      5. map furniture (capital square, town marker, pegmatite mark, label,
         road, rail, water, frame) when the blob sits on one;
      6. unrestricted visual template match.
    """
    import symbol_decisions as dec
    if matcher is None:
        matcher = Matcher()

    def norm(n):
        return n.split(' (')[0]

    snap, hint = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for l in labels:
        e = l.get('entry')
        if not e:
            continue
        mins = tuple(sorted({norm(x) for x in e['minerals']}))
        if l.get('sym') is not None:
            snap[l['sym']][mins] += 1
        elif l.get('hint') is not None:
            hint[l['hint']][mins] += 1
    lab_pt = np.array([(l['cx'], l['cy']) for l in labels]) if labels else np.zeros((0, 2))
    cent = np.array([[(s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2] for s in symbols])

    out = [None] * len(symbols)
    SIG_KNOWN = {}
    for sig, gd in dec.GROUP_DECISIONS.items():
        if not gd[0].startswith('family:'):
            SIG_KNOWN[sig] = gd[0]
    sig_votes = collections.defaultdict(collections.Counter)
    for i in range(len(symbols)):
        for mins, n in snap[i].items():
            if len(mins) == 1:
                sig_votes[(symbols[i]['colour'], symbols[i]['bw'], symbols[i]['bh'], symbols[i]['fill'])][mins[0]] += 2 * n
        for mins, n in hint[i].items():
            if len(mins) == 1:
                sig_votes[(symbols[i]['colour'], symbols[i]['bw'], symbols[i]['bh'], symbols[i]['fill'])][mins[0]] += n
    for sig, tot in sig_votes.items():
        if sig not in SIG_KNOWN and tot:
            nm, n = tot.most_common(1)[0]
            if n >= 3 and n >= 0.7 * sum(tot.values()):
                SIG_KNOWN[sig] = nm

    def vote_mineral(i, votes, family=None):
        if not votes:
            return None, None
        tot = collections.Counter()
        for mins, n in votes.items():
            if len(mins) == 1:
                tot[mins[0]] += n
        if not tot:
            return None, None
        nm, n = tot.most_common(1)[0]
        if family and nm not in family:
            return None, None
        return nm, n

    # passes 1-3 and 6
    for i, s in enumerate(symbols):
        sig = (s['colour'], s['bw'], s['bh'], s['fill'])
        gd = dec.GROUP_DECISIONS.get(sig)
        patch = None
        family = None
        if gd and gd[0].startswith('family:'):
            family = gd[0][7:].split('|')
        if gd and not family:
            out[i] = {'mineral': gd[0], 'method': 'signature determination', 'evidence': gd[1],
                      'score': None, 'margin': None, 'family': None}
            continue
        nm, n = vote_mineral(i, snap[i], family)
        if nm:
            out[i] = {'mineral': nm, 'method': 'table row at its number', 'evidence': '%d numbered localit%s on this '
                      'signature list it' % (n, 'y' if n == 1 else 'ies'), 'score': None, 'margin': None,
                      'family': family}
            continue
        nm, n = vote_mineral(i, hint[i], family)
        if nm:
            out[i] = {'mineral': nm, 'method': 'table row at nearest number', 'evidence': 'nearest number within '
                      '14 pt lists it (%d vote%s)' % (n, '' if n == 1 else 's'), 'score': None, 'margin': None,
                      'family': family}
            continue
        if family:
            patch = matcher.patch(s['x0'], s['y0'], s['x1'], s['y1'])
            r = matcher.rank_within(patch, family)
            if r:
                (sc, t, parts), (sc2, t2, _p) = r[0], (r[1] if len(r) > 1 else (0.0, None, {}))
                out[i] = {'mineral': mineral_of_file(t['file']), 'method': 'template match within family',
                          'evidence': gd[1], 'score': round(sc, 3), 'margin': round(sc - sc2, 3), 'family': family}
                continue
        # pass 5a: raster linework and slivers are not symbols
        if s['colour'] == 'outline' and s['fill'] == 'solid' and (s['bw'] >= 3 * s['bh'] or s['bh'] >= 3 * s['bw']):
            out[i] = {'mineral': 'not a mineral symbol: map linework (road/rail/boundary/text stroke)',
                      'method': 'linework signature', 'evidence': 'solid black bar %dx%d px, aspect %.1f - the '
                      'linework of the base raster, not a legend symbol' % (s['bw'], s['bh'],
                      max(s['bw'] / max(1, s['bh']), s['bh'] / max(1, s['bw']))),
                      'score': None, 'margin': None, 'family': None}
            continue
        if min(s['bw'], s['bh']) <= 2:
            out[i] = {'mineral': 'not a mineral symbol: raster sliver', 'method': 'sliver signature',
                      'evidence': '%dx%d px sliver, one side <= 2 px - the edge of a symbol or linework cut by an '
                      'overprint' % (s['bw'], s['bh']), 'score': None, 'margin': None, 'family': None}
            continue
        if s['bw'] * s['bh'] <= 12:
            out[i] = {'mineral': 'not a mineral symbol: raster sliver', 'method': 'sliver signature',
                      'evidence': '%dx%d px (%d px of ink room) - the edge of a symbol or linework cut by an '
                      'overprint' % (s['bw'], s['bh'], s['bw'] * s['bh']), 'score': None, 'margin': None, 'family': None}
            continue
        # a blob much larger than every known signature of its colour is several symbols touching
        known_area = [dw_ * dh_ for (cl, dw_, dh_, _fl) in SIG_KNOWN if cl == s['colour']]
        if known_area and s['bw'] * s['bh'] >= 1.8 * max(known_area):
            cols_ = colour_hist(patch if patch is not None else
                                matcher.patch(s['x0'], s['y0'], s['x1'], s['y1']), ink_mask(patch if patch is not None
                                else matcher.patch(s['x0'], s['y0'], s['x1'], s['y1'])))
            present = [PAL_NAMES[k] for k in range(len(PAL_NAMES)) if cols_[k] >= 0.15]
            out[i] = {'mineral': 'not a mineral symbol: merged cluster of touching symbols',
                      'method': 'cluster signature', 'evidence': '%dx%d px is %.1fx the largest known %s signature; '
                      'ink colours present: %s' % (s['bw'], s['bh'], s['bw'] * s['bh'] / max(known_area), s['colour'],
                      ', '.join(present) or s['colour']),
                      'score': None, 'margin': None, 'family': None}
            continue
        # pass 5b: same signature within +-1 px (rendering jitter / merge order)
        hit = None
        for dw in (-1, 0, 1):
            for dh in (-1, 0, 1):
                for fl in (s['fill'], 'solid', 'round', 'sparse'):
                    if (s['colour'], s['bw'] + dw, s['bh'] + dh, fl) in SIG_KNOWN:
                        hit = SIG_KNOWN[(s['colour'], s['bw'] + dw, s['bh'] + dh, fl)]
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            out[i] = {'mineral': hit, 'method': 'signature determination (within 1 px)', 'evidence':
                      ('rendering signature agrees with the %s signature within 1 px' % hit)
                      if not hit.startswith('not a mineral') else
                      ('rendering signature agrees with the %s signature within 1 px' % hit),
                      'score': None, 'margin': None, 'family': None}
            continue
        # pass 6
        patch = patch if patch is not None else matcher.patch(s['x0'], s['y0'], s['x1'], s['y1'])
        col = s['colour']
        if col == 'outline':
            h = colour_hist(patch, ink_mask(patch))
            k = int(h[:len(PAL_NAMES)].argmax())
            if h[k] > 0.12:
                col = PAL_NAMES[k]
        # a legend symbol can only explain a blob of a comparable printed size
        bw_pt, bh_pt = s['bw'] / 1.0417, s['bh'] / 1.0417
        sized = [t['no'] for t in matcher.templates
                 if abs(t['pt_w'] - bw_pt) <= 0.5 * t['pt_w'] + 1.5 and abs(t['pt_h'] - bh_pt) <= 0.5 * t['pt_h'] + 1.5]
        short = [n for n in (matcher.by_colour.get(col) or []) if n in sized] or sized
        r = matcher.rank_within(patch, [mineral_of_file(matcher.templates[k - 1]['file']) for k in short]) \
            if short else matcher.rank(patch)
        r = r or matcher.rank(patch)
        if r and r[0][0] < 0.45:
            out[i] = {'mineral': 'not a mineral symbol: linework or label fragment',
                      'method': 'no legend symbol matches (score %.2f)' % r[0][0],
                      'evidence': 'best legend symbol %s scores %.2f, below the 0.45 acceptance floor'
                                  % (mineral_of_file(r[0][1]['file']), r[0][0]),
                      'score': round(r[0][0], 3), 'margin': None, 'family': None}
            continue
        if r:
            (sc, t, parts), (sc2, t2, _p) = r[0], (r[1] if len(r) > 1 else (0.0, None, {}))
            out[i] = {'mineral': mineral_of_file(t['file']), 'method': 'visual template match',
                      'evidence': 'best of %d legend symbols (dice %.2f, ink ncc %.2f, colour %.2f)'
                                  % (len(r), parts.get('dice', 0), parts.get('ncc', 0), parts.get('colour', 0)),
                      'score': round(sc, 3), 'margin': round(sc - sc2, 3), 'family': None}
        else:
            out[i] = {'mineral': 'not a mineral symbol: blank raster', 'method': 'no ink', 'evidence': 'no ink pixels',
                      'score': None, 'margin': None, 'family': None}

    # pass 3b: a blob cut in two by an overprint - the union of it and its same-colour
    # neighbour reproduces the signature of the whole symbol
    import symbol_decisions as dec2
    sig_of = {(s['colour'], s['bw'], s['bh'], s['fill']): i for i, s in enumerate(symbols)}
    votes_all = collections.Counter()
    for i in range(len(symbols)):
        votes_all[(symbols[i]['colour'], symbols[i]['bw'], symbols[i]['bh'], symbols[i]['fill'])] += 1
    for i, s in enumerate(symbols):
        if out[i]['method'] != 'visual template match':
            continue
        for j, t in enumerate(symbols):
            if j == i or t['colour'] != s['colour']:
                continue
            dx = abs(cent[j][0] - cent[i][0]) - (t['bw'] + s['bw']) / 2
            dy = abs(cent[j][1] - cent[i][1]) - (t['bh'] + s['bh']) / 2
            if dx > 2 or dy > 2:
                continue
            uw = max(s['x1'], t['x1']) - min(s['x0'], t['x0'])
            uh = max(s['y1'], t['y1']) - min(s['y0'], t['y0'])
            for dw in (0, 1, -1):
                for dh in (0, 1, -1):
                    gd = dec2.GROUP_DECISIONS.get((s['colour'], uw + dw, uh + dh, s['fill'])) or \
                         dec2.GROUP_DECISIONS.get((s['colour'], uw + dw, uh + dh, 'solid')) or \
                         dec2.GROUP_DECISIONS.get((s['colour'], uw + dw, uh + dh, 'round')) or \
                         dec2.GROUP_DECISIONS.get((s['colour'], uw + dw, uh + dh, 'sparse'))
                    if gd and not gd[0].startswith('family:') and not gd[0].startswith('not a mineral'):
                        out[i] = {'mineral': gd[0], 'method': 'half of a symbol cut by an overprint',
                                  'evidence': 'union with the same-colour blob %d px away reproduces the %s signature'
                                              % (int(np.hypot(cent[j][0] - cent[i][0], cent[j][1] - cent[i][1])),
                                                 gd[0]),
                                  'score': None, 'margin': None, 'family': None}
                        break
                if out[i]['method'] != 'visual template match':
                    break
            if out[i]['method'] != 'visual template match':
                break

    # pass 4: fragments of an identified host
    for i, s in enumerate(symbols):
        if out[i]['method'] not in ('visual template match', 'no ink'):
            continue
        best = None
        for j, t in enumerate(symbols):
            if j == i or t['colour'] != s['colour'] or t['npx'] < 1.5 * s['npx'] or out[j]['method'] in ('no ink',):
                continue
            if abs(cent[j][0] - cent[i][0]) <= (t['bw'] + s['bw']) / 2 + 3 and \
               abs(cent[j][1] - cent[i][1]) <= (t['bh'] + s['bh']) / 2 + 3:
                if best is None or t['npx'] > symbols[best]['npx']:
                    best = j
        if best is not None and not out[best]['mineral'].startswith('not a mineral symbol'):
            out[i] = {'mineral': out[best]['mineral'], 'method': 'fragment of a symbol of the same colour',
                      'evidence': 'cut by an overprint from the %s symbol %d px away' % (out[best]['mineral'],
                                 int(np.hypot(cent[best][0] - cent[i][0], cent[best][1] - cent[i][1]))),
                      'score': out[best]['score'], 'margin': out[best]['margin'], 'family': None}

    # pass 5: map furniture
    if towns is not None:
        for i, s in enumerate(symbols):
            if not out[i]['mineral'].startswith('not a mineral symbol') and \
               out[i]['method'] == 'visual template match' and (out[i]['score'] or 0) < 0.55:
                for nm, pts in towns.items():
                    if len(pts) and np.hypot(pts[:, 0] - s['pt'][0], pts[:, 1] - s['pt'][1]).min() < 2.0:
                        out[i] = {'mineral': 'not a mineral symbol: %s' % nm, 'method': 'map furniture',
                                  'evidence': 'blob centre within 2 pt of a %s' % nm, 'score': None,
                                  'margin': None, 'family': None}
                        break
    return out


if __name__ == '__main__':
    import pickle
    d = pickle.load(open(os.path.join(SHP, '_debug.pkl'), 'rb'))
    m = Matcher()
    res = identify_all(d['symbols'], d['labels'], m)
    import collections as _c
    print(_c.Counter(r['method'] for r in res))
    print(_c.Counter(r['mineral'] for r in res).most_common(12))
    with open(os.path.join(SHP, 'symbol_identification.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['blob', 'colour', 'w_px', 'h_px', 'fill', 'mineral', 'method', 'evidence', 'score', 'margin'])
        for i, (s, r) in enumerate(zip(d['symbols'], res)):
            w.writerow([i, s['colour'], s['bw'], s['bh'], s['fill'], r['mineral'], r['method'], r['evidence'],
                        r['score'], r['margin']])
    print('wrote symbol_identification.csv')
