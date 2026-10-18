#!/usr/bin/env python3
"""Draw 'why_two_sheets_differ.png' - the paper-scale answer to "why don't they match?".

Two things are easy to confuse when two 1:2,000,000 sheets disagree:

  * the *paper* difference - 1 mm of ink on the original sheet is 2 km on the ground,
    so a 1.8 mm disagreement is 3.7 km;
  * the *causes* - a wrong CRS, a datum, rotation, a scale error.  Each of those has a
    maximum size that can be computed, and all of them are an order of magnitude smaller
    than the disagreement being explained.

Numbers are the measured ones from ACCURACY.md / VALIDATION.md / RIVERS_COMPARISON.md.
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MM = 2.002                     # km per mm on a 1:2,002,085 sheet
C_MEAS, C_HYP, C_REF, C_BAD = '#1f4e79', '#999999', '#2a9d3f', '#c0392b'

fig = plt.figure(figsize=(14.5, 7.6))
gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.34)
fig.suptitle('Why two professional 1:2,000,000 sheets disagree by kilometres \u2014 and why a CRS '
             'cannot explain it', fontsize=14.5, y=0.98)

# ---------------------------------------------------------------- left: millimetres
ax = fig.add_subplot(gs[0, 0])
bars = [
    ('printed hairline (0.2 mm)', 0.2, C_REF),
    ('the two borders agree', 0.066 / MM, C_MEAS),
    ('the two frames differ in scale', 0.185 / MM, C_MEAS),
    ('a datum guess could move a point', 0.096 / MM, C_HYP),
    ('the two rivers disagree', 3.7 / MM, C_BAD),
    ('2011 rivers vs truth', 6.6 / MM, C_BAD),
    ('2023 rivers vs truth', 2.6 / MM, C_BAD),
]
y = np.arange(len(bars))[::-1]
for yy, (label, mm, colour) in zip(y, bars):
    ax.barh(yy, mm, color=colour, height=0.62)
    lab = ('%.2f mm' % mm) if mm < 0.3 else ('%.2f mm  =  %.1f km' % (mm, mm * MM))
    ax.text(mm * 1.10, yy, lab, va='center', fontsize=9.5)
    ax.text(0.011, yy, '\u25cf', color=colour, fontsize=8, va='center', clip_on=False)
ax.set_yticks(y)
ax.set_yticklabels([b[0] for b in bars], fontsize=9.5)
ax.set_xscale('log')
ax.set_xlim(0.01, 14)
ax.set_xlabel('size on the original sheet (mm, log scale) \u2014 1 mm = 2.0 km at 1:2,002,085',
              labelpad=6)
ax.set_title('Measured differences, converted to millimetres of ink', fontsize=11.5)
ax.axvline(0.2, ls='--', lw=1, color=C_REF, alpha=0.8)
ax.grid(axis='x', alpha=0.3, lw=0.5)

# ---------------------------------------------------------------- right: hypotheses
ax = fig.add_subplot(gs[0, 1])
hyp = [
    ('projection', 0.000, C_HYP),
    ('datum', 0.096, C_HYP),
    ('frame scale', 0.185, C_HYP),
    ('CRS guess', 0.400, C_HYP),
    ('the real gap', 3.700, C_BAD),
]
x = np.arange(len(hyp))
vals = [h[1] for h in hyp]
ax.bar(x, vals, color=[h[2] for h in hyp], width=0.62)
for xx, v in zip(x, vals):
    ax.text(xx, v + 0.12, ('%.0f m' % (v * 1000)) if v and v < 1 else ('%.1f km' % v),
            ha='center', fontsize=10)
ax.set_xticks(x)
ax.set_xticklabels([h[0] for h in hyp], fontsize=9.6)
ax.tick_params(axis='x', pad=2)
ax.set_ylabel('largest error each cause can produce (km)')
ax.set_ylim(0, 4.4)
ax.set_title('Every georeferencing explanation is 10\u2013100\u00d7 too small\n'
             '(projection is exactly 0: measured tilt 0.0000\u00b0, datum upper bound 96 m)',
             fontsize=10.5)
ax.grid(axis='y', alpha=0.3, lw=0.5)
ax.text(3.42, 1.75, 'gap left over\n= the drawing', fontsize=9, color=C_BAD,
        ha='center', bbox=dict(fc='white', ec='none', alpha=0.85))

# a caption block under both axes
fig.subplots_adjust(bottom=0.22, top=0.86)
fig.text(0.5, 0.035,
         'The sheets do not disagree with each other because their coordinate systems were read '
         'wrongly: their frames are the same projection, the same orientation, and agree to '
         '0.016 % in scale (0.09 mm).\n'
         'They disagree because 1.8 mm of ink is 3.7 km at this scale, and because each sheet '
         'carries its own production errors \u2014 a 0.66 % under-scale overlay on the 2011 sheet, '
         'a 5 km register slip on the 2023 raster.',
         ha='center', fontsize=9.2, color='0.25')

out = os.path.join(ROOT, 'why_two_sheets_differ.png')
fig.savefig(out, dpi=120, bbox_inches='tight')
print('wrote', out)
