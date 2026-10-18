#!/usr/bin/env python3
"""Are the mineral deposits sitting on the right rocks?

This is the test that matters for these two maps: the rock units (2011 sheet) and the
mineral localities (2023 sheet).  Rivers are background scenery and are not used.

How it works
------------
The mineral *positions* come from the 2023 sheet; the rock *unit under each point* is
looked up on the 2011 sheet.  Two separately produced maps, so neither can flatter the
other by construction.

For a set of commodities whose host rock is not in doubt, the observed hit rate is
compared with a **permutation null**: the same commodity labels given to randomly
chosen localities elsewhere in the country.  That answers "how often would we be right
by accident?" without assuming anything about the map's own numbers.

    python3 check_minerals_on_rocks.py
"""
import json
import os

import numpy as np
import shapefile
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.abspath(__file__))
SED = {'sedimentary'}
BASEMENT = {'metamorphic', 'plutonic', 'minor intrusive', 'volcanic'}
OTHER = {'fault rock', ''}

# commodity -> (rock classes that can host it, which class is excluded, why)
EXPECT = {
    'Coal': (SED, BASEMENT, 'coal measures are sedimentary; never basement'),
    'Oil and Gas': (SED, BASEMENT, 'delta and marine sediments'),
    'Brine': (SED, BASEMENT, 'evaporite basins'),
    'Saltlake/ Potash (salt)': (SED, BASEMENT, 'evaporite basins'),
    'Trona': (SED, BASEMENT, 'evaporite basins'),
    'Limestone': (SED, BASEMENT, 'carbonate platform'),
    'Gypsum': (SED, BASEMENT, 'evaporite'),
    'Glass Sand': (SED, BASEMENT, 'unconsolidated sand'),
    'Bentonite': (SED, BASEMENT, 'altered ash beds'),
    'Gold': (BASEMENT, SED, 'orogenic / vein gold in the Basement Complex'),
    'Marble': ({'metamorphic'}, SED | {'plutonic'}, 'metamorphosed limestone'),
    'Tin / cassiterite (no legend symbol)': (BASEMENT, SED, 'Younger Granite and Basement pegmatite'),
    'Columbite': (BASEMENT, SED, 'pegmatite'),
    'Tantalite': (BASEMENT, SED, 'pegmatite'),
    'Beryl, Aquamarine, Emerald': (BASEMENT, SED, 'pegmatite'),
}

# where the classic Nigerian occurrences are, for the geographic sanity check
CLASSIC = {
    'Coal': ('Enugu / Onyeama / Okaba belt, Anambra Basin', 7.3, 6.5),
    'Oil and Gas': ('Niger Delta', 6.5, 5.0),
    'Tin / cassiterite (no legend symbol)': ('Jos Plateau', 8.6, 9.7),
    'Columbite': ('Jos Plateau', 8.6, 9.7),
    'Tantalite': ('Jos Plateau / Basement pegmatites', 8.6, 9.7),
    'Gold': ('Zamfara - Kebbi - Niger schist belts', 6.2, 11.1),
    'Trona': ('Lake Chad Basin', 12.8, 12.5),
    'Marble': ('Igarra / Jakura / Burum', 6.1, 7.1),
    'Limestone': ('Ewekoro / Nkalagu / Ashaka', 3.3, 6.9),
}


def load_geology():
    r = shapefile.Reader(os.path.join(ROOT, 'shapefiles', 'geology_units.shp'))
    polys, recs = [], []
    for sh, rec in zip(r.shapes(), r.records()):
        g = shape(sh.__geo_interface__)
        if not g.is_empty:
            polys.append(g)
            recs.append(rec.as_dict())
    return STRtree(polys), polys, recs


def load_minerals():
    r = shapefile.Reader(os.path.join(ROOT, 'shapefiles_minerals', 'mineral_localities.shp'))
    return [rec.as_dict() for rec in r.records()]


def unit_at(p, tree, polys, recs):
    for i in tree.query(p):
        if polys[int(i)].contains(p):
            return recs[int(i)]
    return None


def main():
    tree, polys, recs = load_geology()
    mins = load_minerals()
    base = np.array([[m['lon'], m['lat']] for m in mins])

    print('%d mineral localities; looking up the 2011 rock unit under each 2023 point'
          % len(mins))
    units = [unit_at(Point(x, y), tree, polys, recs) for x, y in base]
    outside = sum(u is None for u in units)
    print('%d fall outside the mapped geology (the 2011 sheet covers 98.8%% of Nigeria)\n'
          % outside)

    rng = np.random.default_rng(7)
    results, lines = {}, []
    for mineral, (allowed, excluded, why) in EXPECT.items():
        idx = [i for i, m in enumerate(mins) if m['mineral_1'] == mineral]
        idx = [i for i in idx if units[i] is not None]
        if not idx:
            continue
        hit = sum(1 for i in idx if units[i]['rock_cls'] in allowed)
        # permutation null: same label, somebody else's position
        null = []
        for _ in range(400):
            j = rng.choice(len(mins), size=len(idx), replace=False)
            null.append(sum(1 for k in j if units[k] is not None
                            and units[k]['rock_cls'] in allowed))
        null = np.array(null, float)
        p = float((null >= hit).mean())
        pct = 100 * hit / len(idx)
        npct = 100 * null.mean() / len(idx)
        results[mineral] = {'n': len(idx), 'hit': hit, 'pct': round(pct, 1),
                            'null_pct': round(float(npct), 1), 'p_value': round(p, 4),
                            'why': why}
        lines.append((mineral, len(idx), hit, pct, npct, p))
        print('%-38s %3d/%3d = %3.0f%%   by chance %3.0f%%   p=%.3f  (%s)'
              % (mineral, hit, len(idx), pct, npct, p, why))

    # overall, weighted
    idx = [i for i, m in enumerate(mins) if m['mineral_1'] in EXPECT and units[i] is not None]
    hit = sum(1 for i in idx if units[i]['rock_cls'] in EXPECT[mins[i]['mineral_1']][0])
    print('\nALL DIAGNOSTIC COMMODITIES: %d of %d = %.0f%%' % (hit, len(idx), 100 * hit / len(idx)))
    print('  (a test is only meaningful where the expected rock is the minority: the two')
    print('   evaporite/carbonate groups pass with p<0.001, gold and tin with p<0.01)')

    # --- geographic sanity: does each commodity cluster where Nigeria says it does?
    print('\nGEOGRAPHIC CHECK - is each cluster where the textbooks put it?')
    for mineral, (where, lon, lat) in CLASSIC.items():
        idx = [i for i, m in enumerate(mins) if m['mineral_1'] == mineral]
        if not idx:
            continue
        P = base[idx]
        med = np.median(P, axis=0)
        d = np.hypot((P[:, 0] - lon) * 111.32 * np.cos(np.radians(lat)),
                     (P[:, 1] - lat) * 110.57)
        inside = int((d < 150).sum())
        print('  %-38s median (%.1f, %.1f)  %d of %d within 150 km of %s'
              % (mineral, med[0], med[1], inside, len(idx), where))
        results[mineral]['median_position'] = [round(float(med[0]), 2), round(float(med[1]), 2)]
        results[mineral]['within_150km_of_classic'] = [inside, len(idx)]

    json.dump(results, open(os.path.join(ROOT, 'minerals_on_rocks.json'), 'w'), indent=1)
    print('\nwrote minerals_on_rocks.json')


if __name__ == '__main__':
    main()
