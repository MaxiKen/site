#!/usr/bin/env python3
"""Recompute the host-rock attributes of the mineral localities at their final position.

Why this exists
---------------
`geo_code` / `geo_unit` / `geo_form` / `geo_era` / `geo_period` / `geo_epoch` say which
rock unit of the 2011 geological map lies under each 2023 mineral locality.  They were
written by extract_mineral_map.py, i.e. **before** the 2023 sheet's 5 km register error
was corrected.  686 of the 999 localities come from a raster symbol and were then moved
~5 km north; their host-rock fields still described the old position.

Measured, before this fix:
    label-derived localities (never moved)       307/310 still correct  (99 %)
    symbol-derived localities (moved 5 km)       495/686 still correct  (72 %)

So ~191 localities named the wrong rock formation, and 111 named a different *class* of
rock.  This script recomputes all of them from the final coordinates and rewrites
    shapefiles_minerals/mineral_localities.shp + .csv
    shapefiles_minerals/nigeria_minerals.gpkg            (table mineral_localities)
    nigeria_maps.gpkg                                    (table minerals2023_mineral_localities
                                                          + the by-host-geology summary)
Idempotent: it only rewrites values that changed, and it can be re-run after any rebuild.

    python3 fix_host_rock.py            # report only
    python3 fix_host_rock.py --apply    # rewrite the outputs
"""
import argparse
import csv
import os
import sqlite3

import shapefile
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(ROOT, 'shapefiles', 'geology_units.shp')
MIN = os.path.join(ROOT, 'shapefiles_minerals')
FIELDS = ['geo_code', 'geo_unit', 'geo_form', 'geo_era', 'geo_period', 'geo_epoch']
SRC = 'geology 1:2 M at the corrected position, +-2 km'


def load_geology():
    r = shapefile.Reader(GEO)
    polys, recs = [], []
    for sh, rec in zip(r.shapes(), r.records()):
        g = shape(sh.__geo_interface__)
        if not g.is_empty:
            polys.append(g)
            recs.append(rec.as_dict())
    return STRtree(polys), polys, recs


def host_fields(lon, lat, tree, polys, recs):
    p = Point(lon, lat)
    for i in tree.query(p):
        if polys[int(i)].contains(p):
            r = recs[int(i)]
            return [r.get('code') or 'uncoded',
                    (r.get('unit') or 'unit not named')[:64],
                    (r.get('formation') or 'formation not named in the 2011 legend')[:48],
                    (r.get('era') or 'era not stated')[:48],
                    (r.get('period') or 'period not subdivided')[:40],
                    (r.get('epoch') or 'epoch not subdivided')[:48]]
    return ['outside', 'outside mapped units', 'not applicable', 'not applicable',
            'not applicable', 'not applicable']


def rewrite_shapefile(tree, polys, recs):
    r = shapefile.Reader(os.path.join(MIN, 'mineral_localities.shp'))
    fields = r.fields[1:]
    shapes, records, changed = [], [], 0
    for sh, rec in zip(r.shapes(), r.records()):
        d = rec.as_dict()
        new = host_fields(d['lon'], d['lat'], tree, polys, recs)
        if [str(d[f]) for f in FIELDS] != new:
            changed += 1
        d.update(dict(zip(FIELDS, new)))
        d['geo_src'] = SRC
        shapes.append(sh)
        records.append(d)
    return fields, shapes, records, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    tree, polys, recs = load_geology()
    fields, shapes, records, changed = rewrite_shapefile(tree, polys, recs)
    print('%d of %d localities get a corrected host-rock unit' % (changed, len(records)))
    if not args.apply:
        print('(dry run - pass --apply to rewrite)')
        return

    w = shapefile.Writer(os.path.join(MIN, 'mineral_localities'), shapeType=shapefile.POINT)
    for f in fields:
        w.field(*f)
    for sh, d in zip(shapes, records):
        w.point(*sh.points[0])
        w.record(*[d[f[0]] for f in fields])
    w.close()
    print('wrote shapefiles_minerals/mineral_localities.shp')

    # CSV mirror
    p = os.path.join(MIN, 'mineral_localities.csv')
    if os.path.exists(p):
        rows = list(csv.DictReader(open(p, newline='')))
        cols = list(rows[0].keys())
        by_key = {d['zone_num']: d for d in records}
        n = 0
        for row in rows:
            d = by_key.get(row['zone_num'])
            if not d:
                continue
            for f in FIELDS + ['geo_src']:
                if f in row and str(row[f]) != str(d[f]):
                    row[f] = d[f]
                    n += 1
        with open(p, 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)
        print('wrote mineral_localities.csv (%d cells updated)' % n)

    # GeoPackages - attribute-only UPDATE, geometry and rtree untouched
    for path, table in (('shapefiles_minerals/nigeria_minerals.gpkg', 'mineral_localities'),
                        ('nigeria_maps.gpkg', 'minerals2023_mineral_localities')):
        fp = os.path.join(ROOT, path)
        if not os.path.exists(fp):
            continue
        c = sqlite3.connect(fp)
        # the rtree triggers call ST_IsEmpty, which sqlite3 does not provide; the geometry
        # is not being touched, so suspend them and put them back afterwards
        trg = [(n_, s_) for n_, s_ in c.execute(
            "select name, sql from sqlite_master where type='trigger' and name like ?",
            ('rtree_%s_%%' % table,))]
        for n_, _ in trg:
            c.execute('DROP TRIGGER "%s"' % n_)
        n = 0
        for d in records:
            c.execute('UPDATE %s SET geo_code=?, geo_unit=?, geo_form=?, geo_era=?, '
                      'geo_period=?, geo_epoch=?, geo_src=? WHERE zone_num=? AND number=?'
                      % table,
                      [d[f] for f in FIELDS] + [d['geo_src'], d['zone_num'], d['number']])
            n += c.total_changes
        for _, s_ in trg:
            c.execute(s_)
        c.commit()
        c.close()
        print('updated %s (%d rows touched)' % (table, n))

    # the by-host-geology summary in the project GeoPackage
    fp = os.path.join(ROOT, 'nigeria_maps.gpkg')
    c = sqlite3.connect(fp)
    has = c.execute("select count(*) from sqlite_master where type='table' and "
                    "name='minerals2023_summary_localities_by_host_geology'").fetchone()[0]
    if has:
        import collections
        groups = collections.Counter()
        loc_by = collections.defaultdict(list)
        for d in records:
            loc_by[d['geo_code']].append(d)
        c.execute('DELETE FROM minerals2023_summary_localities_by_host_geology')
        fid = 0
        for code, rows in sorted(loc_by.items(), key=lambda kv: -len(kv[1])):
            fid += 1
            r0 = rows[0]
            mins = collections.Counter(d['mineral_1'] for d in rows).most_common(5)
            grp = collections.Counter()
            for d in rows:
                for g in str(d.get('groups') or '').split(';'):
                    g = g.strip()
                    if g:
                        grp[g] += 1
            zones = collections.Counter(d['zone'] for d in rows)
            c.execute('INSERT INTO minerals2023_summary_localities_by_host_geology VALUES '
                      '(?,?,?,?,?,?,?,?,?,?,?)',
                      (fid, code, r0.get('geo_unit'), r0.get('geo_form'), r0.get('geo_era'),
                       r0.get('geo_period'), len(rows),
                       round(100 * len(rows) / len(records), 1),
                       '; '.join('%s %d' % (m, n) for m, n in mins),
                       '; '.join('%s %d' % (g, n) for g, n in grp.most_common()),
                       ' '.join('%s%d' % (z, zones[z]) for z in sorted(zones))))
        c.commit()
        print('rebuilt the by-host-geology summary (%d units)' % fid)
    c.close()


if __name__ == '__main__':
    main()
