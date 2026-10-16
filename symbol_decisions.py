#!/usr/bin/env python3
"""
Analyst determinations for the 2023 Mineral Resources Map of Nigeria.

This file is the written record of the identification pass: every entry states
WHAT was decided and ON WHAT EVIDENCE.  Nothing here is a candidate list - each
row resolves one printed code or one rendering signature to exactly one mineral
(or to an explicit "not a mineral symbol" class).

Two tables:

CODE_RESOLUTIONS
    The EXPLANATIONS table prints 20 codes that are not in the map legend and
    that the previous pipeline left as "unknown code".  Each was resolved by
    reading (a) the printed code cell at 900 dpi, (b) the mineral symbol the
    cartographer printed at that locality's number on the map face, cut from
    the 75 dpi base raster and compared with the legend symbols, and (c) where
    no symbol is printed, single-glyph confusion against the codes the same
    zone of the table actually uses, plus the host geology.  Evidence strings
    say which of these decided it.

GROUP_DECISIONS
    The map face is a set of 75 dpi raster strips, so one mineral symbol always
    renders to the same (colour class, pixel box, fill) signature.  Each
    signature below was read off the raster and compared with the legend sheet;
    where numbered localities sit on the signature their EXPLANATIONS-table
    minerals are quoted as the corroborating vote count.
    A signature may also resolve to a 'family:' entry: the artwork of those
    symbols is identical at map resolution except for the interior glyph, so
    the determination is made per blob by template ranking restricted to that
    family (still one mineral per blob, never a list).
"""

# code -> (legend mineral name, confidence, evidence)
CODE_RESOLUTIONS = {
    'Cy': ('Clay / Pottery Clay', 'resolved',
           'printed identically at A4 Wurno and A5 Taloka; single-glyph confusion l->y with the legend code Cl; '
           'both localities lie in the Sokoto clay belt; no symbol is printed at either number and clay has none there'),
    'Us': ('Limestone', 'resolved',
           'the symbol printed at A6 Zugama and A7 Jama is the green diagonal-hatched Limestone symbol (legend 39), '
           'read off the raster; Us = Ls with L->U glyph confusion'),
    'A':  ('Gold', 'resolved',
           'A57 Sabri (Zamfara gold belt); truncated Au, the dominant code of zone A (29 uses); no symbol printed'),
    'Wa': ('Kaolin / kaolinitic clay', 'resolved',
           'the symbol printed at B26 Adanimai is the khaki K rectangle (legend 34); Wa = Ka with K->W glyph confusion'),
    'Sp': ('Talc', 'resolved',
           'the symbol printed at B27 Shemi is the purple octagon with the white t (legend 57); the row also lists Ab '
           'whose asbestos symbol is absent at the number'),
    'Os': ('Glass Sand', 'resolved',
           'no symbol printed at B33 Babura; single-glyph confusion O->G with Gs, used 6x in zone B; Babura sits on the '
           'Chad Formation sands'),
    'Cz': ('Clay / Pottery Clay', 'resolved',
           'B85 Targo Hills; single-glyph confusion z->l with Cl (16 uses in zone B); a Clay/Pottery Clay rectangle is '
           'printed within 30 pt of the number'),
    'Tn': ('Tin / cassiterite (no legend symbol)', 'resolved',
           'tin shorthand; cassiterite carries no legend symbol and no symbol at all is printed within 45 pt of '
           'C3 Zumugu, which rules out the 1-edit alternatives Tr and Bn whose symbols are absent too'),
    'In': ('Tin / cassiterite (no legend symbol)', 'resolved',
           'single-glyph confusion I->S with Sn; no symbol of any kind is printed within 400 pt of C11 Jawa, '
           'consistent with a mineral that has no legend symbol'),
    'By': ('Baryte', 'resolved',
           'the symbol printed at C30 Bumgai is the dashed circle with the bar and square end-ticks (legend 03), '
           'which distinguishes it from the plain-barred Gypsum circle; 1-edit alternative Gy rejected on that tick'),
    'Si': ('Tin / cassiterite (no legend symbol)', 'resolved',
           'D10 Kumuna; single-glyph confusion i->n with Sn, used 14x in zone D; no symbol printed, consistent with '
           'cassiterite which has none'),
    'sT': ('Tin / cassiterite (no legend symbol)', 'resolved',
           'mis-set Sn at D42 Tegina, a Niger-State tin locality; the nearest symbols (30-40 pt) belong to neighbouring '
           'numbers, i.e. Tegina itself carries no symbol, as cassiterite does not'),
    'Ke': ('Kaolin / kaolinitic clay', 'resolved',
           'the symbol printed at D126 Kwali and D148 Oro is the khaki K rectangle (legend 34); Ke = Ka with a->e '
           'glyph confusion; Kwali is the type locality of Nigerian pottery clay'),
    'Ma': ('Monazite', 'resolved',
           'the symbol printed at E82 Mangu is the barred flag artwork of legend 47; Ma = Mz with z->a glyph confusion; '
           'Mangu lies on the Plateau pegmatite belt that carries monazite'),
    'Sr': ('Brine', 'resolved',
           'the symbol printed at E161 Agwatashi is the yellow circle with the B (legend 10); Sr = Br with B->S '
           'glyph confusion'),
    'Cm': ('Tourmaline', 'resolved',
           'E216 Kabuso koro (not printed on the map); single-glyph confusion C->T with Tm, used 9x in zone E, the '
           'Plateau pegmatite tourmaline belt; Cl (the other 1-edit reading) is excluded because clay symbols are '
           'absent from the locality'),
    'Cs': ('Glass Sand', 'resolved',
           'F17 Lokoja (row also lists Cl); single-glyph confusion C->G with Gs, used 12x in zone F; Lokoja sits on the '
           'Niger alluvial sands; the tar-sand reading (Ts) is excluded, tar sand being mapped on the coastal plain'),
    'SI': ('Sillimanite', 'resolved',
           'F178 Olowu Akeusi, peeled off the name cell; the legend prints the sillimanite code as sl and the table as '
           'Sl, so SI is that code with a capital I for the l; SW Nigeria pegmatite belt; the monazite and gold symbols '
           'within 4 pt belong to the neighbouring numbers of this cluster'),
    'RS': ('Limestone', 'resolved',
           'the symbol printed at G146 Umuahia is the green diagonal-hatched Limestone symbol (legend 39); RS is a '
           'mis-set Ls'),
    'Da': ('Baryte', 'resolved',
           'G158 Uguok (not printed on the map); single-glyph confusion D->B with Ba, the dominant code of zone G '
           '(17 uses, the Cross River baryte belt)'),
}

# rendering signature (colour class, body width px, body height px, fill) ->
#   (determination, evidence)   or   ('family:' + names, evidence)
GROUP_DECISIONS = {
    ('yellow', 14, 10, 'solid'):  ('Clay / Pottery Clay', 'yellow rectangle with the black C (legend 12); 94 table votes'),
    ('yellow', 8, 8, 'solid'):    ('Gold', 'plain yellow square with black border (legend 26); 58 table votes'),
    ('khaki', 14, 10, 'solid'):   ('Kaolin / kaolinitic clay', 'khaki rectangle with the K (legend 34); 38 table votes'),
    ('green', 7, 7, 'sparse'):    ('Limestone', 'green square with white diagonal hatch (legend 39); 13 table votes'),
    ('green', 10, 10, 'sparse'):  ('family:Limestone|Marl', 'green hatched square; Marl (43) is the same hatch in a paler green - decided per blob'),
    ('outline', 6, 5, 'sparse'):  ('Beryl, Aquamarine, Emerald', 'black spade with dots (legend 06); 24 table votes'),
    ('yellow', 8, 8, 'sparse'):   ('family:Brine|Marcasite|Pyrite / Pyroclore|Evaporite|Saltlake/ Potash',
                                   'yellow circle with a letter (legend 10/42/51/19/53); the letter decides, per blob'),
    ('red', 4, 6, 'sparse'):      ('Marble', 'red vertical lens with black tips (legend 41); 23 table votes'),
    ('dark grey', 12, 8, 'solid'): ('Columbite', 'grey bowl (legend 14); 33 table votes, all rows listing columbite'),
    ('purple', 10, 7, 'sparse'):  ('Iron Ore (Magnetite, Ilmenite)', 'purple triangle (legend 33); 17 table votes'),
    ('red', 7, 9, 'sparse'):      ('Lead - Zinc', 'red inverted triangle (legend 36); 19 table votes'),
    ('red', 16, 8, 'sparse'):     ('Feldspar', 'red horizontal diamond... (legend 20 is the red diamond; the 16x8 body is its bar); 15 table votes'),
    ('yellow', 7, 7, 'solid'):    ('Glass Sand', 'yellow tag/bucket (legend 25); 21 table votes'),
    ('outline', 17, 10, 'sparse'): ('family:Tantalite|Oil and Gas', 'white bowl (58) vs derrick (24); decided per blob'),
    ('outline', 12, 6, 'solid'):  ('Coal', 'solid black bar (legend 13); 19 table votes'),
    ('orange', 6, 1, 'solid'):    ('Zircon', 'orange bar (legend 65 body); 5 table votes'),
    ('purple', 8, 8, 'round'):    ('family:Talc|Molybdenite', 'purple octagon with t (57) or Mo (46); the letter decides'),
    ('outline', 10, 4, 'sparse'): ('family:Gypsum|Baryte|Phosphate|Phosphate Rock|Trona|Bitumen',
                                   'white circle with bar/cross/T; the interior glyph and end-ticks decide, per blob'),
    ('outline', 10, 10, 'sparse'): ('family:Graphite|River Gravel|Kyanite|Sillimanite',
                                    'white square with bars/hatch; decided per blob'),
    ('light green', 14, 10, 'round'): ('Wolframite', 'light green rectangle with the W (legend 64); 8 table votes'),
    ('yellow', 4, 8, 'solid'):    ('Bentonite', 'yellow half-circle with black left (legend 05 body); 9 table votes'),
    ('yellow', 9, 9, 'solid'):    ('Gold', 'yellow square (legend 26), smaller render; 5 table votes'),
    ('red', 10, 8, 'sparse'):     ('Tourmaline', 'red right-pointing triangle (legend 61); 9 table votes'),
    ('blue grey', 9, 10, 'round'): ('Mica', 'blue-grey octagon (legend 44); 7 table votes'),
    # ---- read off the raster in this pass (no table vote available) ----
    ('brown', 3, 8, 'sparse'):    ('Granite', 'scattered tan dashes = legend 30 artwork, read off the raster'),
    ('brown', 3, 4, 'sparse'):    ('Granite', 'scattered tan dashes = legend 30 artwork (smaller cluster)'),
    ('brown', 4, 5, 'sparse'):    ('Granite', 'scattered tan dashes = legend 30 artwork (smaller cluster)'),
    ('brown', 6, 6, 'sparse'):    ('Granite', 'scattered tan dashes = legend 30 artwork'),
    ('brown', 7, 6, 'sparse'):    ('Granite', 'scattered tan dashes = legend 30 artwork'),
    ('grey', 11, 11, 'sparse'):   ('not a mineral symbol: state capital square',
                                   'grey double square with diagonal = the capital marker of the 2023 map; positions '
                                   'coincide with state_capitals.shp'),
    ('outline', 8, 6, 'sparse'):  ('Oil and Gas', 'black derrick (legend 24); the 22 occurrences trace the Niger/'
                                                  'Benue valley and the delta, i.e. the oil belt'),
    ('outline', 7, 10, 'sparse'): ('family:Beryl, Aquamarine, Emerald|Zircon|Monazite', 'tall outline symbols; decided per blob'),
    ('green', 12, 6, 'round'):    ('Magnesite', 'green rectangle with white Mg (legend 45), read off the raster'),
    ('outline', 8, 10, 'round'):  ('family:Lignite|Monazite|Bentonite', 'black rect with white band (38) / barred flag (47) / half circle (05); per blob'),
    ('red', 16, 11, 'round'):     ('Lepidolite', 'red rectangle with Lp (legend 37), read off the raster'),
    ('yellow', 12, 8, 'round'):   ('Pyrite / Pyroclore', 'yellow bowl with the P (legend 51), read off the raster'),
    ('yellow', 15, 11, 'solid'):  ('Clay / Pottery Clay', 'yellow rectangle with C (legend 12), larger render'),
    ('yellow', 14, 10, 'round'):  ('family:Clay / Pottery Clay|Dimension Stone', 'yellow rectangle; C vs Ds letter decides'),
    ('bright green', 13, 14, 'sparse'): ('Lithium (Ambligonite, Kunzite, Moganite, Spodumene, etc)',
                                         'bright green circle with Li (legend 66), read off the raster'),
    ('dark blue', 11, 4, 'sparse'): ('not a mineral symbol: bridge/water marking',
                                     'dark blue (0,77,168) occurs only as five bar+arch pairs in the Lagos-Ibadan '
                                     'waterways; no legend symbol carries that colour'),
    ('red', 2, 9, 'round'):       ('Marble', 'red vertical lens (legend 41), narrow render'),
    # ---- second visual pass (signatures with no table vote, read off the raster) ----
    ('khaki', 16, 11, 'solid'):   ('Kaolin / kaolinitic clay', 'khaki K rectangle, larger render'),
    ('purple', 11, 11, 'sparse'): ('Talc', 'purple octagon with the white t (legend 57), larger render'),
    ('purple', 11, 11, 'round'):  ('Talc', 'purple octagon with the red t (legend 57)'),
    ('purple', 15, 8, 'sparse'):  ('Garnet', 'purple triangle (legend 23), wide render; the 10x7 triangle is Iron Ore'),
    ('green 2', 9, 8, 'sparse'):  ('Galena', 'green triangle with the white a (legend 29)'),
    ('outline', 10, 7, 'sparse'): ('Bauxitic Clay', 'hexagon, dark brown top over tan bottom (legend 04)'),
    ('green', 18, 13, 'sparse'):  ('Limestone', 'green hatched square, large render (orange zircon bars overprint it)'),
    ('grey', 11, 12, 'sparse'):   ('not a mineral symbol: state capital square', 'grey double square, capital marker'),
    ('grey', 10, 11, 'sparse'):   ('not a mineral symbol: state capital square', 'grey double square, capital marker'),
    ('red', 14, 10, 'round'):     ('Chromite', 'red rectangle with Cr (legend 11)'),
    ('green', 14, 10, 'round'):   ('Diatomite', 'green rectangle with dt (legend 17)'),
    ('red', 20, 10, 'sparse'):    ('Tourmaline', 'red right-pointing triangle (legend 61), large render'),
    ('red', 21, 11, 'sparse'):    ('Tourmaline', 'red right-pointing triangle (legend 61), large render'),
    ('blue grey', 11, 11, 'sparse'): ('Uranium', 'blue-grey octagon with the U (legend 63)'),
    ('blue violet', 12, 7, 'sparse'): ('Calcite',
        'the triangle body before its black outline merges in; same determination as the 14x9 signature'),
    ('blue violet', 14, 9, 'sparse'): ('Calcite',
        'blue-violet triangle with a white C, printed at raster px (240,732) and (986,866); legend cell 67 (Calcite) '
        'prints no artwork, so the template was cut from the map face; the EXPLANATIONS code Ca of six localities '
        'maps to Calcite through that legend row'),
    ('outline', 12, 15, 'sparse'): ('Glass Sand', 'yellow bucket with black border (legend 25)'),
    ('outline', 6, 7, 'sparse'):  ('Clay / Pottery Clay', 'yellow rectangle with C (legend 12), small render'),
    ('yellow', 17, 20, 'round'):  ('Clay / Pottery Clay', 'two touching Clay rectangles merged by the blob detector'),
    ('outline', 26, 10, 'sparse'): ('Pyrite / Pyroclore', 'yellow bowl with P (legend 51) merged with a neighbouring triangle'),
    ('outline', 19, 10, 'sparse'): ('Tantalite', 'white bowl (legend 58) with a river overprint'),
    ('outline', 28, 10, 'sparse'): ('Columbite', 'grey bowl (legend 14) merged with a white bowl neighbour'),
    ('outline', 25, 13, 'sparse'): ('Columbite', 'grey bowl (legend 14) with a river overprint'),
    ('green', 9, 13, 'sparse'):   ('Limestone', 'green hatched square, tall render'),
}
