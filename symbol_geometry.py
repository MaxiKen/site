"""Whole-icon validation at native resolution; never stretch a fragment to fit.

Disconnected hatching, borders and glyphs are not separate occurrences. Native
exemplars with analyst-confirmed complete signatures supply the fixed geometry.
The table is an identification hint, never sufficient evidence of a detection.
"""
import collections
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from scipy.signal import correlate

import symbol_identify as si

# Complete body dimensions read against the legend, in 75-dpi pixels.
# Bordered/unbordered variants and sampling phases are retained. Limestone's 7x7 / 10x10 signatures are only hatch fragments.
BODY = {
    'yellow': {12: (14, 10), 26: (8, 8), 25: (7, 7), 10: (8, 8), 5: (4, 8),
               18: (14, 10), 51: (12, 8), 53: (8, 8)},
    'khaki': {34: (14, 10)}, 'light green': {64: (14, 10)},
    'red': {11: (14, 10), 20: (16, 8), 36: (7, 9), 37: (16, 11),
            41: (4, 6), 61: (10, 8)},
    'green': {17: (14, 10), 45: (12, 6), 40: (8, 8), 43: (10, 10),
              35: (4, 10), 16: (11, 11), 21: (6, 8), 60: (6, 8)},
    'green 2': {29: (9, 8)}, 'purple': {23: (15, 8), 33: (10, 7), 57: (8, 8)},
    'dark grey': {14: (12, 8)}, 'blue grey': {44: (9, 10), 63: (8, 8)},
    'bright green': {66: (13, 14)}, 'tan': {54: (8, 8)},
    'blue violet': {67: (12, 7)}, 'orange': {65: (6, 1)},
    'dark tan': {4: (8, 4)}, 'brown': {30: (12, 13)},
    'outline': {3: (10, 4), 31: (10, 4), 32: (10, 4), 49: (10, 4),
                58: (17, 10), 13: (12, 6), 27: (10, 10), 28: (10, 10),
                38: (8, 10), 47: (8, 10), 24: (8, 6), 6: (6, 5)},
}
FULL_FLOOR = 0.94
PARTIAL_FLOOR = 0.72


@dataclass
class Icon:
    no: int
    mineral: str
    masks: dict
    w: int
    h: int


def colour_masks(rgb):
    """Symbol ink only: pure-black roads/text are NOT symbol-outline ink."""
    rgb = rgb.astype(np.int16)
    maps = {k: np.abs(rgb-colour).max(2) <= 10 for k, colour in enumerate(si.PAL)}
    maps[len(si.PAL)] = np.abs(rgb-(31, 26, 23)).max(2) <= 8
    return maps


def native_icons(symbols, matcher, maps):
    names = {si.mineral_of_file(t['file']): t['no'] for t in matcher.templates}
    groups = collections.defaultdict(list)
    H, W = matcher.base.shape[:2]
    for s in symbols:
        ident = s['ident']
        no = names.get(ident['mineral'])
        if not no or ident['method'] not in ('signature determination', 'template match within family',
                                             'table row at its number'):
            continue
        expected = BODY.get(s['colour'], {}).get(no)
        x0, y0, x1, y1 = map(int, (s['x0'], s['y0'], s['x1'], s['y1']))
        if no == 65 and s['colour'] == 'orange':
            # Zircon is THREE horizontal strokes (two at the top and one nine
            # pixels lower), not two separate symbols. Require the full height.
            k = si.PAL_NAMES.index('orange')
            xa, ya = max(0, x0-1), max(0, y0-10)
            sub = maps[k][ya:min(H, y1+10), xa:min(W, x1+1)]
            lab, _ = ndi.label(ndi.binary_dilation(sub, iterations=3))
            counts = np.bincount(lab[y0-ya:y1-ya, x0-xa:x1-xa].ravel())
            counts[0] = 0
            if not counts.any():
                continue
            yy, xx = np.where(sub & (lab == counts.argmax()))
            x0, x1, y0, y1 = xa+xx.min(), xa+xx.max()+1, ya+yy.min(), ya+yy.max()+1
            if not (5 <= x1-x0 <= 7 and 9 <= y1-y0 <= 11):
                continue
        elif (no, s['colour']) in ((39, 'green'), (30, 'brown')):
            k = si.PAL_NAMES.index(s['colour'])
            xa, ya, xb, yb = max(0, x0-14), max(0, y0-10), min(W, x1+14), min(H, y1+10)
            sub = maps[k][ya:yb, xa:xb]
            lab, _ = ndi.label(ndi.binary_dilation(sub, iterations=2 if no == 30 else 1))
            counts = np.bincount(lab[y0-ya:y1-ya, x0-xa:x1-xa].ravel())
            counts[0] = 0
            if not counts.any():
                continue
            yy, xx = np.where(sub & (lab == counts.argmax()))
            x0, x1, y0, y1 = xa+xx.min(), xa+xx.max()+1, ya+yy.min(), ya+yy.max()+1
            valid = (14 <= x1-x0 <= 19 and 10 <= y1-y0 <= 14) if no == 39 else (8 <= x1-x0 <= 13 and 8 <= y1-y0 <= 13)
            if not valid:
                continue
        elif not expected or abs(s['bw']-expected[0]) > 3 or abs(s['bh']-expected[1]) > 3:
            continue
        if no in (3, 31, 32, 49):  # disconnected dashed circles around the bar
            y0 -= 3
            y1 += 3
        elif no == 5:              # Bentonite's seed is its yellow right half
            x0 -= 5
            x1 += 1
            y0 -= 1
            y1 += 1
        elif no == 6:              # disconnected lower arm of Beryl
            y1 += 4
        elif no == 4:              # Bauxitic Clay's lower coloured semicircle
            y0 -= 5
        allowed = {len(si.PAL)}
        if s['colour'] != 'outline':
            allowed.add(si.PAL_NAMES.index(s['colour']))
        # Include the icon's border, not just its coloured interior.
        pad = 2 if no in (11, 12, 17, 18, 34, 37, 45, 64) else 4
        if no in (65, 67):  # native Zircon strokes / Calcite reference artwork
            allowed.discard(len(si.PAL))
            pad = 0
        x0, y0, x1, y1 = max(0, x0-pad), max(0, y0-pad), min(W, x1+pad), min(H, y1+pad)
        masks = {k: m[y0:y1, x0:x1].copy() for k, m in maps.items() if k in allowed}
        support_mask = np.logical_or.reduce(list(masks.values()))
        if s['colour'] != 'outline' and no != 65:
            # Discard neighbouring, disconnected outline glyphs. They are not
            # part of this symbol's geometry even if inside the search window.
            seed = masks[si.PAL_NAMES.index(s['colour'])]
            lab, _ = ndi.label(ndi.binary_dilation(support_mask, iterations=1))
            counts = np.bincount(lab[seed])
            counts[0] = 0
            if not counts.any():
                continue
            component = lab == counts.argmax()
            masks = {k: m & component for k, m in masks.items()}
            support_mask &= component
        yy, xx = np.where(support_mask)
        if not len(xx):
            continue
        masks = {k: m[yy.min():yy.max()+1, xx.min():xx.max()+1] for k, m in masks.items()}
        x0, y0, x1, y1 = x0+xx.min(), y0+yy.min(), x0+xx.max()+1, y0+yy.max()+1
        if no != 67 and sum(m[y0:y1, x0:x1].sum() for k, m in maps.items() if k not in allowed) > 3:
            continue
        masks = {k: np.pad(m, 1) for k, m in masks.items() if m.sum() >= 3}
        if not masks:
            continue
        # Do not learn a merged cluster as a new, oversized icon variant.
        ew, eh = expected or (18, 13)
        if no in (3, 31, 32, 49):
            eh = 10
        elif no == 5:
            ew, eh = 11, 11
        elif no == 6:
            eh = 9
        elif no == 65:
            eh = 10
        elif no == 4:
            ew, eh = 11, 11
        elif no == 35:
            ew = 11
        if x1-x0 > ew+4 or y1-y0 > eh+4:
            continue
        # Quiet perimeter is validation only; exclude it from output geometry.
        key = (no, x1-x0+2, y1-y0+2, tuple((k, m.tobytes()) for k, m in masks.items()))
        groups[no].append((key, Icon(no, ident['mineral'], masks, x1-x0+2, y1-y0+2)))
    icons = []
    for no, items in sorted(groups.items()):
        counts, by_key = collections.Counter(key for key, _ in items), dict(items)
        # Keep both bordered/unbordered sizes, not just the most frequent phase.
        chosen, sizes = [], set()
        for key, _ in counts.most_common():
            size = key[1:3]
            if size not in sizes:
                chosen.append(key)
                sizes.add(size)
        chosen = chosen[:8]
        for key, _ in counts.most_common(6):
            if key not in chosen:
                chosen.append(key)
        icons.extend(by_key[key] for key in chosen)
    return icons


def score_maps(icon, maps):
    """Native ink recall minus extra ink, including holes and quiet perimeter."""
    H, W = next(iter(maps.values())).shape
    score = np.zeros((H-icon.h+1, W-icon.w+1), np.float32)
    n = sum(int(m.sum()) for m in icon.masks.values())
    for k, mask in icon.masks.items():
        source = maps[k].astype(np.float32)
        score += correlate(source, mask.astype(np.float32), 'valid', method='fft') / n
        score -= .4 * correlate(source, (~mask).astype(np.float32), 'valid', method='fft') / n
    return score


def scan_icons(symbols, matcher, floor=PARTIAL_FLOOR):
    maps = colour_masks(matcher.base)
    icons = native_icons(symbols, matcher, maps)
    peaks = []
    for idx, icon in enumerate(icons):
        scores = score_maps(icon, maps)
        yy, xx = np.where((scores >= floor) & (scores == ndi.maximum_filter(scores, size=5)))
        for y, x in zip(yy, xx):
            peaks.append(dict(x0=int(x+1), y0=int(y+1), x1=int(x+icon.w-1), y1=int(y+icon.h-1),
                              cx=float(x+icon.w/2), cy=float(y+icon.h/2),
                              score=min(1., float(scores[y, x])), mineral=icon.mineral,
                              no=icon.no, template=idx))
    return icons, maps, peaks


def support(p, icons, maps=None):
    """Global raster pixel IDs of expected ink (or of visibly matching ink)."""
    t = icons[p['template']]
    x, y = p['x0']-1, p['y0']-1
    pixels = set()
    for k, mask in t.masks.items():
        if maps is not None:
            mask = mask & maps[k][y:y+t.h, x:x+t.w]
        yy, xx = np.where(mask)
        pixels.update(zip((xx+x).tolist(), (yy+y).tolist()))
    return pixels


def competing(a, b):
    """Same-icon hypotheses, NOT a blanket distance-based point deduplication."""
    close = (abs(a['cx']-b['cx']) < .35*min(a['x1']-a['x0'], b['x1']-b['x0']) and
             abs(a['cy']-b['cy']) < .35*min(a['y1']-a['y0'], b['y1']-b['y0']))
    shared = len(a['_visible'] & b['_visible'])
    return close or shared > .55 * min(len(a['_visible']), len(b['_visible']))


def select_icons(icons, maps, proposals, symbols):
    """Full matches alone; partial matches only with pixel-level occlusion proof."""
    proposals = [p for p in proposals if p['score'] + 1e-6 >= PARTIAL_FLOOR]
    for p in proposals:
        p['_ink'] = support(p, icons)
        p['_visible'] = support(p, icons, maps)
        # Visually identical low-resolution rings keep the existing table-backed
        # determination; matching geometry must not arbitrarily rename them.
        p['_prior'] = max((1 if s['ident']['mineral'] == p['mineral'] else 0
                          for s in symbols if abs((s['x0']+s['x1'])/2-p['cx']) < 3
                          and abs((s['y0']+s['y1'])/2-p['cy']) < 3), default=0)
    order = sorted(proposals, key=lambda p: (-round(p['score'], 5), -p['_prior'],
                   -len(p['_ink']), p['y0'], p['x0'], p['no']))
    kept = []
    for p in order:
        if p['score'] + 1e-6 < FULL_FLOOR:
            continue
        if not any(competing(p, q) for q in kept):
            p['match_kind'] = 'complete'
            kept.append(p)
    def minimum_visible(p):
        # Tiny black chevrons can occur by chance where hatching meets an
        # outline. Do not invent a mineral from ten generic black pixels.
        outline_only = set(icons[p['template']].masks) == {len(si.PAL)}
        return max(20 if outline_only else 10, .25*len(p['_ink']))

    # A partially visible icon must have its own substantial, distinct ink.
    # Missing pixels must actually be occupied by an already accepted neighbour,
    # not merely be inside a nearby blob's bounding rectangle.
    for _ in range(2):
        added = 0
        occupied = set().union(*(q['_visible'] for q in kept)) if kept else set()
        for p in order:
            if p.get('match_kind') or any(competing(p, q) for q in kept):
                continue
            missing = p['_ink'] - p['_visible']
            own = p['_visible'] - occupied
            if (len(own) < minimum_visible(p) or not missing or
                    len(missing & occupied) < .65*len(missing)):
                continue
            p['match_kind'] = 'partial (overlapping icons)'
            kept.append(p)
            occupied.update(p['_visible'])
            added += 1
        if not added:
            break
    # A cluster can have no completely exposed member. Accept complementary
    # pairs only when BOTH fits pass the same pixel-level occlusion test.
    from scipy.spatial import cKDTree
    if order:
        tree = cKDTree([(p['cx'], p['cy']) for p in order])
        occupied = set().union(*(q['_visible'] for q in kept)) if kept else set()
        for i, p in enumerate(order):
            if p.get('match_kind') or any(competing(p, q) for q in kept):
                continue
            for j in sorted(tree.query_ball_point((p['cx'], p['cy']), 22)):
                q = order[j]
                if j <= i or q.get('match_kind') or competing(p, q) or any(competing(q, r) for r in kept):
                    continue
                if min(len(p['_visible'])/len(p['_ink']), len(q['_visible'])/len(q['_ink'])) < .60:
                    continue
                good = True
                for a, b in ((p, q), (q, p)):
                    missing = a['_ink'] - a['_visible']
                    blockers = occupied | b['_visible']
                    if (not missing or len(missing & blockers) < .65*len(missing) or
                            len(a['_visible']-blockers) < minimum_visible(a)):
                        good = False
                        break
                if good:
                    for a in (p, q):
                        a['match_kind'] = 'partial (overlapping icons)'
                        kept.append(a)
                        occupied.update(a['_visible'])
                    break
    return sorted(kept, key=lambda p: (p['no'], p['y0'], p['x0']))


def refine_symbols(symbols, matcher, px_to_pt, frame):
    """Return one centred, accepted feature per printed icon, plus audit metrics."""
    from shapely.geometry import Point
    icons, maps, peaks = scan_icons(symbols, matcher)
    selected = select_icons(icons, maps, peaks, symbols)
    result, audit = [], []
    for p in selected:
        pt = px_to_pt(p['cx'], p['cy'])
        if not frame.contains(Point(*pt)):
            continue
        visible = p['_visible']
        source = [i for i, s in enumerate(symbols)
                  if s['x0'] < p['x1'] and s['x1'] > p['x0'] and
                     s['y0'] < p['y1'] and s['y1'] > p['y0']]
        t = icons[p['template']]
        colours = [(int(m.sum()), k) for k, m in t.masks.items() if k < len(si.PAL)]
        colour = si.PAL_NAMES[max(colours)[1]] if colours else 'outline'
        method = 'whole-icon template: ' + ('complete' if p['match_kind']=='complete' else 'partial overlap')
        evidence = ('fixed native %dx%d icon; centre of full artwork; %s; source blobs %s' %
                    (p['x1']-p['x0'], p['y1']-p['y0'], p['match_kind'], ','.join(map(str, source)) or 'new coverage'))
        ident = dict(mineral=p['mineral'], method=method, score=round(p['score'], 3),
                     margin=None, family=None, evidence=evidence)
        fill_ratio = len(visible) / ((p['x1']-p['x0']) * (p['y1']-p['y0']))
        fill = 'solid' if fill_ratio >= .88 else ('round' if fill_ratio >= .68 else 'sparse')
        result.append(dict(x0=p['x0'], y0=p['y0'], x1=p['x1'], y1=p['y1'],
                           bw=p['x1']-p['x0'], bh=p['y1']-p['y0'], colour=colour,
                           npx=len(visible), fill=fill, parts=max(1, len(source)),
                           pt=pt, candidates=[p['mineral']], labels=[], near_label=None,
                           link='', ident=ident))
        audit.append(dict(pixel_box=[p['x0'], p['y0'], p['x1'], p['y1']],
                          centre_px=[p['cx'], p['cy']], mineral=p['mineral'],
                          match_kind=p['match_kind'], score=round(p['score'], 4), source_blobs=source))
    return result, dict(input_blobs=len(symbols), accepted_icons=len(result),
                        complete=sum(r['match_kind']=='complete' for r in audit),
                        partial=sum(r['match_kind']!='complete' for r in audit),
                        recovered=sum(not r['source_blobs'] for r in audit),
                        templates=len(icons), full_floor=FULL_FLOOR, partial_floor=PARTIAL_FLOOR,
                        icons=audit)
