"""Whole-map symbol scan: find every printed occurrence of every legend symbol.

The blob segmentation in extract_mineral_map.py can miss a symbol that touches a
river, a road or another symbol (it then merges into a bigger blob) or that sits
on a tinted background.  This module goes the other way: for each of the 66
legend symbols it cross-correlates its colour pattern with the whole 75 dpi map
face and reports every position where the printed colours agree.

    python3 symbol_scan.py [--thr 0.75] [--sheet _scratch/qa/scan_sheet.png]

Output: _scratch/scan_peaks.json - one entry per peak: template number and
mineral, position in raster px and page pt, score, and which existing symbol
blob (if any) covers the position.
"""
import argparse
import collections
import csv
import json
import os

import numpy as np
from PIL import Image
from scipy.ndimage import maximum_filter
from scipy.signal import correlate

import symbol_identify as si

ROOT = os.path.dirname(os.path.abspath(__file__))
SHP = os.path.join(ROOT, 'shapefiles_minerals')
PX_PER_PT = 75.0 / 72.0


def indicator_maps(base, dilate=1):
    """One binary map per palette colour (+ black ink), as in colour_hist.

    The maps are dilated by `dilate` px so that antialiased map linework, which
    never lands exactly on the template grid, still registers as its colour."""
    from scipy.ndimage import binary_dilation
    dist = np.abs(base[:, :, :3][:, :, None, :] - si.PAL[None, None, :, :]).sum(axis=3)
    near, ok = dist.argmin(axis=2), dist.min(axis=2) < 150
    dark = base[:, :, :3].sum(axis=2) < 450      # true linework; geology tints sum > 600
    maps = {si.PAL_NAMES[c]: (near == c) & ok for c in range(len(si.PAL_NAMES))}
    maps['black'] = dark & ~ok
    if dilate:
        maps = {k: binary_dilation(v, iterations=dilate) for k, v in maps.items()}
    return maps


def template_kernels(t, maps_keys):
    """Resize a legend crop to map scale and split its ink into colour kernels."""
    w = max(2, int(round(t['pt_w'] * PX_PER_PT)))
    h = max(2, int(round(t['pt_h'] * PX_PER_PT)))
    im = Image.fromarray(t['crop']).resize((w, h), Image.LANCZOS)
    a = np.array(im).astype(int)
    m = si.ink_mask(a)
    px = a[:, :, :3]
    dist = np.abs(px[:, :, None, :] - si.PAL[None, None, :, :]).sum(axis=3)
    near, ok = dist.argmin(axis=2), dist.min(axis=2) < 150
    kern = {}
    for c in range(len(si.PAL_NAMES)):
        k = m & (near == c) & ok
        if k.sum() >= 2:
            kern[si.PAL_NAMES[c]] = k
    k = m & ~ok
    if k.sum() >= 2:
        kern['black'] = k
    return kern, m.sum(), (w, h)


def scan(thr=0.75):
    m = si.Matcher()
    base = m.base
    imap = indicator_maps(base)
    H, W = base.shape[:2]
    peaks = []
    for t in m.templates:
        kern, n_ink, (w, h) = template_kernels(t, imap)
        if not kern:
            continue
        s = np.zeros((H - h + 1, W - w + 1))
        for name, k in kern.items():
            s += correlate(imap[name].astype(np.float32), k.astype(np.float32),
                           mode='valid', method='fft')
        s /= n_ink
        mx = maximum_filter(s, size=5)
        ys, xs = np.where((s >= thr) & (s == mx))
        kept = []
        for y, x in zip(ys, xs):
            if all((y - y0) ** 2 + (x - x0) ** 2 > (min(w, h) / 2) ** 2 for y0, x0, _ in kept):
                kept.append((y, x, s[y, x]))
        for y, x, sc in kept:
            peaks.append({'no': t['no'], 'mineral': si.mineral_of_file(t['file']),
                          'x': int(x), 'y': int(y), 'w': w, 'h': h,
                          'cx': x + w / 2.0, 'cy': y + h / 2.0, 'score': round(float(sc), 3)})
    return m, peaks


def coverage(peaks):
    """Mark each peak with the existing symbol blob (if any) that covers it.

    Positions come from the PGW sidecar of the 75 dpi base raster (the raster is
    a crop of the map face, so the page-pt georeference does not apply to it)."""
    pgw = [float(x) for x in open(os.path.join(SHP, 'map_raster', 'mineral_map_base_75dpi.pgw'))]
    a, b, d, e, c0, f0 = pgw
    rows = list(csv.DictReader(open(os.path.join(SHP, 'symbol_identification.csv'))))
    blobs = []
    for r in rows:
        lon, lat = float(r['lon']), float(r['lat'])
        blobs.append({'blob': int(r['blob']), 'mineral': r['mineral'], 'method': r['method'],
                      'cx': (lon - c0) / a, 'cy': (lat - f0) / e,
                      'bw': float(r['body_w_px']), 'bh': float(r['body_h_px'])})
    for p in peaks:
        hit = None
        for b in blobs:
            if abs(p['cx'] - b['cx']) <= b['bw'] / 2 + 2 and abs(p['cy'] - b['cy']) <= b['bh'] / 2 + 2:
                hit = b
                break
        p['covered_by'] = hit['blob'] if hit else None
        p['covered_mineral'] = hit['mineral'] if hit else None
        p['covered_method'] = hit['method'] if hit else None
    return peaks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--thr', type=float, default=0.75)
    ap.add_argument('--out', default=os.path.join(ROOT, '_scratch', 'scan_peaks.json'))
    args = ap.parse_args()
    m, peaks = scan(args.thr)
    peaks = coverage(peaks)
    peaks.sort(key=lambda p: -p['score'])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(peaks, open(args.out, 'w'), indent=1)
    un = [p for p in peaks if p['covered_by'] is None]
    print('peaks >= %.2f: %d (%d not covered by any existing blob)' % (args.thr, len(peaks), len(un)))
    per = collections.Counter(p['mineral'] for p in peaks)
    print('templates found:', len(per), 'of', len(m.templates))
    missing = [si.mineral_of_file(t['file']) for t in m.templates
               if si.mineral_of_file(t['file']) not in per]
    print('legend minerals with no peak at all:', missing)
    for p in un[:40]:
        print('  NEW  #%02d %-28s (%4d,%4d) score %.2f' % (p['no'], p['mineral'], p['cx'], p['cy'], p['score']))


if __name__ == '__main__':
    main()


def carve_merged(base, x0, y0, x1, y1, matcher, colour, thr=0.80, max_parts=3):
    """Local template scan inside one merged ink body: return the symbol-sized
    windows of the legend symbols printed inside it (greedy, non-overlapping)."""
    pad = 2
    patch = base[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    dist = np.abs(patch[:, :, :3][:, :, None, :] - si.PAL[None, None, :, :]).sum(axis=3)
    near, ok = dist.argmin(axis=2), dist.min(axis=2) < 150
    dark = patch[:, :, :3].sum(axis=2) < 450
    imap = {si.PAL_NAMES[c]: (near == c) & ok for c in range(len(si.PAL_NAMES))}
    imap['black'] = dark & ~ok
    nos = list(matcher.by_colour.get(colour, [])) or [t['no'] for t in matcher.templates]
    hits = []
    for t in matcher.templates:
        if t['no'] not in nos and t['no'] in matcher.SIGNATURE_ONLY:
            continue
        kern, n_ink, (w, h) = template_kernels(t, imap)
        if not kern or w > patch.shape[1] or h > patch.shape[0]:
            continue
        sc = np.zeros((patch.shape[0] - h + 1, patch.shape[1] - w + 1))
        for name, k in kern.items():
            sc += correlate(imap[name].astype(np.float32), k.astype(np.float32), 'valid', method='fft')
        sc /= n_ink
        for _ in range(3):                      # a template may occur several times
            yy, xx = np.unravel_index(int(sc.argmax()), sc.shape)
            if sc[yy, xx] < thr:
                break
            hits.append((float(sc[yy, xx]), t['no'], int(xx), int(yy), w, h))
            ya, yb = max(0, yy - h // 2), min(sc.shape[0], yy + h // 2 + 1)
            xa, xb = max(0, xx - w // 2), min(sc.shape[1], xx + w // 2 + 1)
            sc[ya:yb, xa:xb] = 0
    hits.sort(key=lambda z: -z[0])
    kept = []
    for sc, no, xx, yy, w, h in hits:
        ax0, ay0, ax1, ay1 = xx - pad, yy - pad, xx - pad + w, yy - pad + h
        if any(not (ax1 <= k[0] or ax0 >= k[2] or ay1 <= k[1] or ay0 >= k[3]) for k in kept):
            continue
        kept.append((ax0, ay0, ax1, ay1))
        if len(kept) >= max_parts:
            break
    out = []
    for ax0, ay0, ax1, ay1 in kept:
        sub = patch[max(0, ay0 + pad):ay1 + pad, max(0, ax0 + pad):ax1 + pad]
        mkk = sub[:, :, :3].sum(axis=2) < 720
        if mkk.sum() < 20:
            continue
        rs, cs = np.where(mkk)
        out.append((x0 + ax0 + cs.min(), y0 + ay0 + rs.min(),
                    x0 + ax0 + cs.max() + 1, y0 + ay0 + rs.max() + 1))
    return out
