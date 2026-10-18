#!/usr/bin/env python3
"""Which of the two sheets puts its rivers in the right place?

Both sheets draw the Niger and the Benue, but they draw them 3-4 km apart.  This
script settles which one is closer to reality by measuring both against river
networks neither sheet was calibrated on:

  * WDBII (CIA World Data Bank II, via basemap-data)  -- independent of both sheets
  * Natural Earth 10m rivers                          -- a second opinion
  * 16 named control points whose true coordinates are published (Lokoja, Idai,
    Onitsha, Makurdi, Yola ...), snapped onto the reference stems

Method: sample the reference main stem every ~2 km and measure the distance to the
nearest line of each sheet's network.  Measuring *reference -> sheet* (rather than
nearest vertices in both directions) is the fair test for "who drew it in the right
place": a sheet is not penalised for drawing extra tributaries.

    python3 compare_rivers.py            # prints the table, writes river_comparison.json
    python3 compare_rivers.py --figure   # also writes rivers_which_is_right.png
"""
import argparse
import json
import os

import numpy as np
import shapefile
import shapely
from shapely.geometry import LineString, shape

ROOT = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(ROOT, 'shapefiles')
MIN = os.path.join(ROOT, 'shapefiles_minerals')
REF = os.path.join(ROOT, 'reference_data')
KM = 110.57
NIGERIA = shapely.box(2.5, 4.0, 15.0, 14.0)

# True coordinates of places that stand on the two rivers (published values).
CONTROL_POINTS = [
    ('Kainji Dam',  4.617,  9.867, 'Niger'),
    ('Jebba',       4.790,  9.130, 'Niger'),
    ('Baro',        6.420,  8.600, 'Niger'),
    ('Lokoja',      6.744,  7.802, 'Niger'),
    ('Idah',        6.743,  7.098, 'Niger'),
    ('Asaba',       6.733,  6.199, 'Niger'),
    ('Onitsha',     6.788,  6.140, 'Niger'),
    ('Aboh',        6.525,  5.548, 'Niger'),
    ('Burutu',      5.750,  5.517, 'Niger'),
    ('Yola',       12.480,  9.200, 'Benue'),
    ('Numan',      12.033,  9.467, 'Benue'),
    ('Lau',        11.270,  9.210, 'Benue'),
    ('Ibi',         9.750,  8.180, 'Benue'),
    ('Wukari',      9.780,  7.870, 'Benue'),
    ('Makurdi',     8.540,  7.733, 'Benue'),
]


# --------------------------------------------------------------------------- data
def sheet_lines(path):
    out = []
    for sh in shapefile.Reader(path).shapes():
        p = np.asarray(sh.points, float)
        if len(p) < 2:
            continue
        parts = list(sh.parts) + [len(p)]
        for a, b in zip(parts[:-1], parts[1:]):
            if b - a >= 2:
                out.append(LineString(p[a:b]))
    return out


def reference_lines():
    """WDBII segments + the Natural Earth Niger and Benue stems."""
    wdb = []
    for f in ('rivers_nigeria.json', 'rivers_f_nigeria.json'):
        p = os.path.join(REF, 'wdbii', f)
        if os.path.exists(p):
            wdb = [LineString(d['coords']) for d in json.load(open(p))
                   if len(d['coords']) > 1]
            break
    ne_n, ne_b = [], []
    p = os.path.join(REF, 'ne10m', 'rivers10m.geojson')
    if os.path.exists(p):
        for f in json.load(open(p))['features']:
            nm = ((f['properties'].get('name') or '') + ' ' +
                  (f['properties'].get('name_en') or '')).strip()
            if 'Niger' not in nm and 'Benue' not in nm:
                continue
            g = shape(f['geometry'])
            for part in shapely.get_parts(g):
                if part.geom_type != 'LineString':
                    continue
                if part.bounds[2] < 1.0 or part.bounds[0] > 16.0:
                    continue
                (ne_n if 'Niger' in nm else ne_b).append(part)
    return wdb, ne_n, ne_b


def sample(g, step=0.02):
    out = []
    for part in shapely.get_parts(g):
        if part.geom_type != 'LineString' or part.length < 0.05:
            continue
        n = max(2, int(part.length / step))
        out.append(np.array([[part.interpolate(t, normalized=True).x,
                              part.interpolate(t, normalized=True).y]
                             for t in np.linspace(0, 1, n)]))
    return np.vstack(out) if out else np.zeros((0, 2))


def nearest_km(P, net):
    return np.asarray(shapely.distance(shapely.points(P), net), float) * KM


# --------------------------------------------------------------------------- tests
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--figure', action='store_true')
    args = ap.parse_args()

    wdb, ne_n, ne_b = reference_lines()
    if not wdb:
        raise SystemExit('no reference rivers - run fetch_reference_rivers.py first')
    print('reference: WDBII %d segments (%d vertices), Natural Earth 10m %d+%d parts'
          % (len(wdb), sum(len(list(g.coords)) for g in wdb), len(ne_n), len(ne_b)))

    sheets = {'2011': sheet_lines(os.path.join(GEO, 'rivers.shp')),
              '2023': sheet_lines(os.path.join(MIN, 'rivers.shp'))}
    nets = {k: shapely.union_all(v) for k, v in sheets.items()}

    # the two references agree with each other to <1 km, so either can be the truth;
    # the WDBII stem is restricted to the WDBII lines that follow the Natural Earth one
    stems = {'Niger': (shapely.union_all(ne_n).intersection(NIGERIA) if ne_n else None),
             'Benue': (shapely.union_all(ne_b).intersection(NIGERIA) if ne_b else None)}
    wdb_stem = {}
    for name, g in stems.items():
        sel = [l for l in wdb if l.length > 0.15 and l.distance(g) < 0.15]
        wdb_stem[name] = shapely.union_all(sel) if sel else None
    truth = {'Natural Earth 10 m': stems, 'WDBII (CIA)': wdb_stem}

    result = {'reference': {'primary': 'WDBII (basemap-data, LGPL-3.0-or-later)',
                            'secondary': 'Natural Earth 10m rivers (public domain)'}}
    print('\n-- distance from the reference main stem to each sheet\'s network (km)')
    for provider, group in truth.items():
        for name, g in group.items():
            if g is None or g.is_empty:
                continue
            P = sample(g)
            row = {'provider': provider, 'samples': len(P)}
            for year, net in nets.items():
                d = nearest_km(P, net)
                row[year] = {'median': round(float(np.median(d)), 2),
                             'p90': round(float(np.percentile(d, 90)), 2),
                             'pct_within_2km': round(float((d < 2).mean() * 100), 0),
                             'pct_within_5km': round(float((d < 5).mean() * 100), 0)}
                print('  %-18s %-6s %-8s median %5.2f  p90 %6.2f  <2 km %3.0f%%  <5 km %3.0f%%'
                      % (provider, name, year, row[year]['median'], row[year]['p90'],
                         row[year]['pct_within_2km'], row[year]['pct_within_5km']))
            result.setdefault('main_stem', {}).setdefault(name, []).append(row)

    # --- control points: snap the published coordinate onto the reference stem
    print('\n-- named control points (published coordinates, snapped to WDBII)')
    verts = np.vstack([np.asarray(g.coords)[::2] for g in wdb if g.length > 0.1])
    from scipy.spatial import cKDTree
    tree = cKDTree(verts)
    rows = []
    for name, lon, lat, river in CONTROL_POINTS:
        _, i = tree.query([lon, lat])
        rp = verts[i]
        snap = float(np.hypot((rp[0] - lon) * 111.32 * np.cos(np.radians(lat)),
                              (rp[1] - lat) * KM))
        row = {'place': name, 'river': river, 'nominal': [lon, lat],
               'snapped': [round(rp[0], 4), round(rp[1], 4)], 'snap_km': round(snap, 2)}
        for year, net in nets.items():
            row[year] = round(float(shapely.distance(shapely.Point(rp), net) * KM), 2)
            row['nominal_' + year] = round(
                float(shapely.distance(shapely.Point(lon, lat), net) * KM), 2)
        step = '' if snap < 2.5 else '  (snap %.0f km - not used)' % snap
        rows.append(row)
        print('  %-12s %-6s  distance to the drawn river: 2011 %6.2f   2023 %6.2f   %s%s'
              % (name, river, row['2011'], row['2023'],
                 '2023 closer' if row['2023'] < row['2011'] else '2011 closer', step))
    result['control_points'] = rows
    keep = [r for r in rows if r['snap_km'] < 2.5]
    better = sum(1 for r in keep if r['2023'] < r['2011'])
    med = {y: round(float(np.median([r[y] for r in keep])), 2) for y in ('2011', '2023')}
    medn = {y: round(float(np.median([r['nominal_' + y] for r in keep])), 2)
            for y in ('2011', '2023')}
    result['control_points_summary'] = {'2023_closer_at': better, 'of': len(keep),
                                        'median': med, 'median_from_printed_coordinate': medn}
    print('  -> %d points with a clean snap: median %.2f km (2011) vs %.2f km (2023); '
          '2023 closer at %d of %d' % (len(keep), med['2011'], med['2023'], better, len(keep)))
    print('     measured from the published coordinate itself: %.2f km (2011) vs %.2f km (2023)'
          % (medn['2011'], medn['2023']))

    # --- is either sheet simply shifted?  (a transform could then fix it)
    print('\n-- systematic offset of each sheet from the reference (median, km)')
    for name, g in stems.items():
        P = sample(g)
        for year, net in nets.items():
            V = np.vstack([np.asarray(l.coords) for l in sheets[year]])
            _, idx = cKDTree(V).query(P)
            off = V[idx] - P
            de = float(np.median(off[:, 0]) * 111.32 * np.cos(np.radians(P[:, 1].mean())))
            dn = float(np.median(off[:, 1]) * KM)
            result.setdefault('bias', {}).setdefault(name, {})[year] = [round(de, 2), round(dn, 2)]
            print('  %-6s %-6s %+6.2f E / %+6.2f N' % (name, year, de, dn))

    out = os.path.join(ROOT, 'river_comparison.json')
    json.dump(result, open(out, 'w'), indent=1)
    print('\nwrote', out)

    if args.figure:
        figure(result, sheets, nets, stems, wdb, ne_n, ne_b, rows)
    return result


# --------------------------------------------------------------------------- figure
def figure(result, sheets, nets, stems, wdb, ne_n, ne_b, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    C = {'2011': '#c0392b', '2023': '#1f4e79', 'wdb': '#111111', 'ne': '#2a9d3f'}
    fig = plt.figure(figsize=(15.5, 10))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1.0], width_ratios=[1.0, 1.6],
                          hspace=0.30, wspace=0.14)
    fig.suptitle('Which sheet puts the rivers in the right place?\n'
                 'both tested against WDBII (CIA) and Natural Earth 10 m \u2014 independent of both',
                 fontsize=14, y=0.985)

    def zoom(ax, win, title):
        x0, x1, y0, y1 = win
        for g, c, lw, alpha in ((shapely.union_all(wdb), C['wdb'], 2.6, 0.35),
                                (shapely.union_all(ne_n + ne_b), C['ne'], 1.3, 0.95),
                                (nets['2011'], C['2011'], 1.0, 0.9),
                                (nets['2023'], C['2023'], 1.0, 0.9)):
            for part in shapely.get_parts(g):
                if part.geom_type != 'LineString':
                    continue
                if (part.bounds[2] < x0 or part.bounds[0] > x1
                        or part.bounds[3] < y0 or part.bounds[1] > y1):
                    continue
                x, y = part.xy
                ax.plot(x, y, color=c, lw=lw, alpha=alpha,
                        solid_capstyle='round', zorder=1 if c == C['wdb'] else 2)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect(1 / np.cos(np.radians((y0 + y1) / 2)))
        ax.set_title(title, fontsize=11)
        ax.grid(alpha=0.25, lw=0.4)
        ax.tick_params(labelsize=8)

    d = {k: v[0] for k, v in result['main_stem'].items()}   # Natural Earth provider
    dw = {k: v[1] for k, v in result['main_stem'].items()}   # WDBII provider
    zoom(fig.add_subplot(gs[0, 0]), (6.35, 7.25, 6.02, 7.98),
         'Niger, Lokoja \u2192 Onitsha\nmedian distance to truth: 2011 %.1f km, 2023 %.1f km'
         % (d['Niger']['2011']['median'], d['Niger']['2023']['median']))
    zoom(fig.add_subplot(gs[0, 1]), (8.15, 12.75, 7.45, 9.75),
         'Benue, Makurdi \u2192 Yola\nmedian distance to truth: 2011 %.1f km, 2023 %.1f km'
         % (d['Benue']['2011']['median'], d['Benue']['2023']['median']))
    handles = [Line2D([], [], color=C['wdb'], lw=3, alpha=0.35, label='WDBII (CIA)'),
               Line2D([], [], color=C['ne'], lw=1.6, label='Natural Earth 10 m'),
               Line2D([], [], color=C['2011'], lw=1.4, label='2011 sheet'),
               Line2D([], [], color=C['2023'], lw=1.4, label='2023 sheet')]
    fig.axes[0].legend(handles=handles, fontsize=8.5, loc='lower left',
                       framealpha=0.92, edgecolor='0.8')

    ax = fig.add_subplot(gs[1, 0])
    labels, v11, v23 = [], [], []
    for river in ('Niger', 'Benue'):
        labels.append('%s\n(NE truth)' % river)
        v11.append(d[river]['2011']['median'])
        v23.append(d[river]['2023']['median'])
        labels.append('%s\n(WDBII truth)' % river)
        v11.append(dw[river]['2011']['median'])
        v23.append(dw[river]['2023']['median'])
    labels.append('%d control\npoints' % result['control_points_summary']['of'])
    v11.append(result['control_points_summary']['median']['2011'])
    v23.append(result['control_points_summary']['median']['2023'])
    x = np.arange(len(labels))
    ax.bar(x - 0.19, v11, 0.36, color=C['2011'], label='2011 sheet')
    ax.bar(x + 0.19, v23, 0.36, color=C['2023'], label='2023 sheet')
    for i, (a, b) in enumerate(zip(v11, v23)):
        ax.text(i - 0.19, a + 0.12, '%.1f' % a, ha='center', fontsize=9.5)
        ax.text(i + 0.19, b + 0.12, '%.1f' % b, ha='center', fontsize=9.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5)
    ax.set_ylabel('distance to the reference (km)')
    ax.set_title('Closer to reality is shorter', fontsize=11)
    ax.legend(fontsize=9, frameon=False)
    ax.set_ylim(0, max(v11) * 1.25)
    ax.grid(axis='y', alpha=0.3, lw=0.5)

    ax = fig.add_subplot(gs[1, 1])
    order = [r['place'] for r in rows]
    y = np.arange(len(rows))[::-1]
    for r, yy in zip(rows, y):
        ax.plot([r['2011'], r['2023']], [yy, yy], color='0.75', lw=1, zorder=1)
        ax.scatter(r['2011'], yy, s=26, color=C['2011'], zorder=3)
        ax.scatter(r['2023'], yy, s=26, color=C['2023'], zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=8.5)
    ax.set_xlabel('distance from the place to that sheet\u2019s river line (km)')
    ax.set_title('Every named place, one pair of dots', fontsize=11)
    ax.grid(axis='x', alpha=0.3, lw=0.5)
    ax.legend(handles=[Line2D([], [], marker='o', ls='', color=C['2011'], label='2011'),
                       Line2D([], [], marker='o', ls='', color=C['2023'], label='2023')],
              fontsize=9, frameon=False, loc='lower right')

    out = os.path.join(ROOT, 'rivers_which_is_right.png')
    fig.savefig(out, dpi=110, bbox_inches='tight')
    print('wrote', out)


if __name__ == '__main__':
    main()
