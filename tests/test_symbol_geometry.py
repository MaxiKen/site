"""Run with: python -m unittest discover -s tests -v"""
import copy
import csv
import json
from pathlib import Path
import sqlite3
import unittest

import numpy as np
import shapefile

from symbol_geometry import Icon, score_maps, select_icons

ROOT = Path(__file__).resolve().parents[1]


def square(no, colour, width=8, height=8):
    return Icon(no, str(no), {colour: np.pad(np.ones((height, width), bool), 1)},
                width+2, height+2)


def proposal(t, index, x, y, score):
    return dict(x0=x, y0=y, x1=x+t.w-2, y1=y+t.h-2,
                cx=x+(t.w-2)/2, cy=y+(t.h-2)/2,
                mineral=t.mineral, no=t.no, template=index, score=score)


class DetectionRules(unittest.TestCase):
    def setUp(self):
        self.a = square(1, 0)
        self.b = square(2, 1, 6)
        self.maps = {k: np.zeros((32, 32), bool) for k in (0, 1)}

    def test_complete_match_and_fragment_penalty(self):
        self.maps[0][3:11, 3:11] = True
        self.assertAlmostEqual(float(score_maps(self.a, self.maps)[2, 2]), 1., places=5)
        self.maps[0][3:7, 3:11] = False
        self.assertLess(float(score_maps(self.a, self.maps)[2, 2]), .6)

    def test_partial_is_rejected_when_alone(self):
        self.maps[0][3:11, 3:9] = True
        p = proposal(self.a, 0, 3, 3, .75)
        self.assertEqual(select_icons([self.a], self.maps, [p], []), [])

    def test_partial_requires_actual_occluding_pixels_and_keeps_full_centre(self):
        self.maps[0][3:11, 3:9] = True
        self.maps[1][3:11, 9:15] = True
        p = proposal(self.a, 0, 3, 3, .75)
        q = proposal(self.b, 1, 9, 3, 1.)
        found = select_icons([self.a, self.b], self.maps, [p, q], [])
        self.assertEqual(len(found), 2)
        self.assertEqual(p['match_kind'], 'partial (overlapping icons)')
        self.assertEqual((p['cx'], p['cy']), (7., 7.))  # NOT visible-ink centre (6,7)

    def test_nearby_bounding_box_is_not_occlusion_proof(self):
        self.maps[0][3:11, 3:9] = True
        self.maps[1][16:24, 9:15] = True
        p = proposal(self.a, 0, 3, 3, .75)
        q = proposal(self.b, 1, 9, 16, 1.)
        self.assertEqual(len(select_icons([self.a, self.b], self.maps, [p, q], [])), 1)

    def test_cross_template_duplicates_are_suppressed(self):
        self.maps[0][3:11, 3:11] = True
        p = proposal(self.a, 0, 3, 3, 1.)
        q = copy.deepcopy(p)
        q['no'], q['mineral'] = 9, 'alternative label'
        self.assertEqual(len(select_icons([self.a], self.maps, [p, q], [])), 1)

    def test_tiny_outline_fragment_in_hatching_is_not_a_new_mineral(self):
        # Regression from visual coverage QA: a black hatch corner inside a
        # Limestone icon looked like a partially covered Beryl chevron.
        import symbol_identify as si
        black = len(si.PAL)
        a = square(1, black, 4, 4)
        b = square(2, 1, 4, 4)
        maps = {k: np.zeros((32, 32), bool) for k in (black, 1)}
        maps[black][3:7, 3:6] = True
        maps[1][3:7, 6:10] = True
        p = proposal(a, 0, 3, 3, .75)
        q = proposal(b, 1, 6, 3, 1.)
        found = select_icons([a, b], maps, [p, q], [])
        self.assertEqual([r['no'] for r in found], [2])

    def test_touching_real_icons_are_not_distance_deduplicated(self):
        self.maps[0][3:11, 3:11] = True
        self.maps[1][3:11, 11:17] = True
        proposals = [proposal(self.a, 0, 3, 3, 1.), proposal(self.b, 1, 11, 3, 1.)]
        self.assertEqual(len(select_icons([self.a, self.b], self.maps, proposals, [])), 2)


class ShippedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / 'shapefiles_minerals'
        cls.qa = json.loads((cls.directory / 'qa_report.json').read_text()).get('symbol_geometry')
        if cls.qa is None:
            raise unittest.SkipTest('run extract_mineral_map.py to rebuild whole-icon outputs')

    def test_centres_are_full_box_midpoints_and_world_file_aligned(self):
        with (self.directory / 'symbol_identification.csv').open() as f:
            rows = list(csv.DictReader(f))
        a, _, _, e, c, f = map(float, (self.directory / 'map_raster/mineral_map_base_75dpi.pgw').read_text().split())
        self.assertEqual(len(rows), len(self.qa['icons']))
        for row, icon in zip(rows, self.qa['icons']):
            x0, y0, x1, y1 = icon['pixel_box']
            cx, cy = icon['centre_px']
            self.assertEqual([cx, cy], [(x0+x1)/2, (y0+y1)/2])
            # PGW origin is the centre of pixel zero, not its upper-left edge.
            self.assertAlmostEqual(float(row['lon']), c+(cx-.5)*a, delta=6e-7)
            self.assertAlmostEqual(float(row['lat']), f+(cy-.5)*e, delta=6e-7)
            if icon['match_kind'] == 'complete':
                self.assertGreaterEqual(icon['score']+1e-4, self.qa['full_floor'])

    def test_disconnected_granite_grains_form_one_centred_icon(self):
        matches = [p for p in self.qa['icons'] if p['mineral'] == 'Granite'
                   and p['pixel_box'] == [325, 938, 337, 951]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['centre_px'], [331, 944.5])
        self.assertGreaterEqual(len(matches[0]['source_blobs']), 3)

    def test_coverage_recovery_keeps_real_icons_not_a_hatch_corner(self):
        found = {(p['mineral'], tuple(p['centre_px'])) for p in self.qa['icons']}
        self.assertIn(('Limestone', (941, 1440.5)), found)
        self.assertIn(('Tantalite', (985.5, 849)), found)
        self.assertNotIn(('Beryl, Aquamarine, Emerald', (936, 1438)), found)

    def test_three_zircon_strokes_share_one_full_height_centre(self):
        zircon = [p for p in self.qa['icons'] if p['mineral'] == 'Zircon']
        self.assertTrue(zircon)
        for icon in zircon:
            self.assertGreaterEqual(icon['pixel_box'][3]-icon['pixel_box'][1], 9)
        matches = [p for p in zircon if p['pixel_box'] == [1457, 612, 1463, 622]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['centre_px'], [1460, 617])
        self.assertEqual(len(matches[0]['source_blobs']), 3)

    def test_no_duplicate_centres(self):
        centres = [tuple(p['centre_px']) for p in self.qa['icons']]
        self.assertEqual(len(centres), len(set(centres)))

    def test_bundles_and_shapefile_have_identical_geometry_and_identification(self):
        shp = shapefile.Reader(str(self.directory / 'mineral_symbols_raster.shp'))
        expected = [(r['blob'], r['mineral'], tuple(s.points[0])) for r, s in zip(shp.records(), shp.shapes())]
        self.assertEqual(len(expected), self.qa['accepted_icons'])
        for path, prefix in ((ROOT / 'nigeria_maps.gpkg', 'minerals2023_'),
                             (self.directory / 'nigeria_minerals.gpkg', '')):
            from pyogrio.raw import read
            from shapely import from_wkb
            _, _, geometries, fields = read(str(path), layer=prefix+'mineral_symbols_raster',
                                            columns=['blob', 'mineral'])
            actual = [(int(blob), mineral, (g.x, g.y)) for blob, mineral, g in
                      zip(fields[0], fields[1], from_wkb(geometries))]
            self.assertEqual(actual, expected)
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
                rows = con.execute('SELECT blob, mineral, lon, lat FROM '+prefix+'symbol_identification ORDER BY blob').fetchall()
                self.assertEqual([(b, m, (x, y)) for b, m, x, y in rows], expected)

    def test_linked_localities_share_corrected_symbol_centres(self):
        symbols = shapefile.Reader(str(self.directory / 'mineral_symbols_raster.shp'))
        centres = {tuple(s.points[0]) for s in symbols.shapes()}
        localities = shapefile.Reader(str(self.directory / 'mineral_localities.shp'))
        for record, shape in zip(localities.records(), localities.shapes()):
            if record['pos_src'].startswith('raster symbol'):
                self.assertIn(tuple(shape.points[0]), centres)


if __name__ == '__main__':
    unittest.main()
