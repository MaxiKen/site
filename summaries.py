#!/usr/bin/env python3
"""Summary tables derived from the delivered shapefiles (run after both extractions).

  shapefiles/summary_area_by_unit.csv       area of every legend unit (duplicates excluded) with its stratigraphy
  shapefiles/summary_area_by_age.csv        area by era / period / epoch and by rock class
  shapefiles_minerals/summary_localities_by_host_geology.csv
                                            mineral localities (2023) x host rock unit of the 2011 map
  shapefiles_minerals/summary_localities_by_group.csv
                                            commodity group x host era (counts), plus per-zone counts

Usage:  python summaries.py
"""
import collections
import csv
import os

import shapefile

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(HERE, 'shapefiles')
MIN = os.path.join(HERE, 'shapefiles_minerals')


def records(path):
    r = shapefile.Reader(path)
    names = [f[0] for f in r.fields[1:]]
    return [dict(zip(names, rec)) for rec in r.records()]


def geology():
    units = records(os.path.join(GEO, 'geology_units.shp'))
    live = [u for u in units if not u['dup_of']]
    total = sum(u['area_km2'] for u in live)
    # per legend unit
    per = collections.OrderedDict()
    for u in sorted(live, key=lambda u: (u['leg_row'] or 999, u['code'])):
        k = (u['leg_row'], u['code'], u['leg_desc'] or u['unit'])
        d = per.setdefault(k, {'n': 0, 'area': 0.0, 'perim': 0.0, 'u': u})
        d['n'] += 1
        d['area'] += u['area_km2']
        d['perim'] += u['perim_km']
    with open(os.path.join(GEO, 'summary_area_by_unit.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['legend_row', 'code', 'description', 'formation', 'rock_class', 'era', 'period', 'epoch', 'age_ma_min',
                     'age_ma_max', 'age_source', 'polygons', 'area_km2', 'pct_of_mapped_area', 'perimeter_km', 'largest_polygon_km2'])
        for (row, code, desc), d in per.items():
            u = d['u']
            largest = max(x['area_km2'] for x in live if (x['leg_row'], x['code']) == (row, code))
            wr.writerow([row or '', code, desc, u['formation'], u['rock_cls'], u['era'], u['period'], u['epoch'],
                         u['age_ma_min'], u['age_ma_max'], u['age_src'], d['n'], round(d['area'], 1),
                         round(100 * d['area'] / total, 2), round(d['perim'], 1), round(largest, 1)])
    # by age
    with open(os.path.join(GEO, 'summary_area_by_age.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['grouping', 'value', 'polygons', 'area_km2', 'pct_of_mapped_area', 'legend_codes'])
        for key, label in (('era', 'era'), ('period', 'period'), ('epoch', 'epoch'), ('series', 'printed series'),
                           ('period_prt', 'printed period bracket'), ('rock_cls', 'rock class')):
            agg = collections.OrderedDict()
            for u in sorted(live, key=lambda u: (u['age_ma_min'] if u['age_ma_min'] is not None else 1e9)):
                v = u[key] or '(none)'
                d = agg.setdefault(v, {'n': 0, 'area': 0.0, 'codes': set()})
                d['n'] += 1
                d['area'] += u['area_km2']
                d['codes'].add(u['code'])
            for v, d in agg.items():
                wr.writerow([label, v, d['n'], round(d['area'], 1), round(100 * d['area'] / total, 2), ' '.join(sorted(d['codes']))])
    print(f'geology: {len(live)} polygons ({len(units) - len(live)} duplicates excluded), {total:,.0f} km2; '
          f'{len(per)} units -> summary_area_by_unit.csv, summary_area_by_age.csv')


def minerals():
    locs = records(os.path.join(MIN, 'mineral_localities.shp'))
    # localities x host unit
    per = collections.OrderedDict()
    for l in sorted(locs, key=lambda l: (l['geo_era'] or 'zzz', l['geo_code'] or 'zzz')):
        k = l['geo_code'] or '(outside mapped units)'
        d = per.setdefault(k, {'n': 0, 'unit': l['geo_unit'], 'form': l['geo_form'], 'era': l['geo_era'], 'period': l['geo_period'],
                               'minerals': collections.Counter(), 'groups': collections.Counter(), 'zones': collections.Counter()})
        d['n'] += 1
        for m in (l['minerals'] or '').split(' | '):
            if m:
                d['minerals'][m.split(' (')[0]] += 1
        for g in (l['groups'] or '').split(' | '):
            if g:
                d['groups'][g] += 1
        d['zones'][l['zone']] += 1
    with open(os.path.join(MIN, 'summary_localities_by_host_geology.csv'), 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(['host_unit_code', 'host_unit', 'host_formation', 'host_era', 'host_period', 'localities', 'pct',
                     'top_minerals', 'commodity_groups', 'zones'])
        for k, d in sorted(per.items(), key=lambda kv: -kv[1]['n']):
            wr.writerow([k, d['unit'], d['form'], d['era'], d['period'], d['n'], round(100 * d['n'] / len(locs), 1),
                         '; '.join(f'{m} {n}' for m, n in d['minerals'].most_common(5)),
                         '; '.join(f'{g} {n}' for g, n in d['groups'].most_common()),
                         ' '.join(f'{z}{n}' for z, n in sorted(d['zones'].items()))])
    # group x era
    eras = []
    for l in locs:
        e = l['geo_era'] or '(outside mapped units)'
        if e not in eras:
            eras.append(e)
    eras.sort()
    groups = sorted({g for l in locs for g in (l['groups'] or '').split(' | ') if g})
    tab = {g: collections.Counter() for g in groups}
    for l in locs:
        e = l['geo_era'] or '(outside mapped units)'
        for g in (l['groups'] or '').split(' | '):
            if g:
                tab[g][e] += 1
    zones = sorted({l['zone'] for l in locs})
    ztab = {g: collections.Counter() for g in groups}
    for l in locs:
        for g in (l['groups'] or '').split(' | '):
            if g:
                ztab[g][l['zone']] += 1
    with open(os.path.join(MIN, 'summary_localities_by_group.csv'), 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(['commodity_group', 'localities'] + [f'host era: {e}' for e in eras] + [f'zone {z}' for z in zones])
        for g in sorted(groups, key=lambda g: -sum(tab[g].values())):
            wr.writerow([g, sum(tab[g].values())] + [tab[g].get(e, 0) for e in eras] + [ztab[g].get(z, 0) for z in zones])
    print(f'minerals: {len(locs)} localities on {len(per)} host units -> summary_localities_by_host_geology.csv, '
          f'summary_localities_by_group.csv')


if __name__ == '__main__':
    if os.path.exists(os.path.join(GEO, 'geology_units.shp')):
        geology()
    if os.path.exists(os.path.join(MIN, 'mineral_localities.shp')):
        minerals()
