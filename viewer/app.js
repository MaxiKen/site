/* Nigeria maps viewer: original PDFs (tiles) vs extracted shapefiles (GeoJSON) – mobile-first.
   Two datasets share one map: the Geological Map (2011, vector PDF, graticule georeference) and the
   Mineral Resources Map (2023, GeoPDF).  Each layer of either dataset can be toggled; either PDF can
   be shown on the "PDF" side. */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => (n == null ? '–' : Number(n).toLocaleString('en'));

  // ------------------------------------------------------------------ symbology helpers (mineral map)
  // colour classes of the raster symbol detector -> RGB (see SYMBOL_PALETTE in extract_mineral_map.py)
  const SYMBOL_RGB = { yellow: '#fff500', khaki: '#97946b', green: '#00923f', red: '#da251d', purple: '#974578',
    'light green': '#84c225', grey: '#828282', 'dark grey': '#605d5c', 'blue grey': '#667ab3', brown: '#c08040',
    'bright green': '#00ff00', orange: '#e77817', tan: '#bb825b', 'green 2': '#00a040', 'dark tan': '#957f66',
    violet: '#8400a8', 'dark blue': '#004da8', 'purple 2': '#a900e6', magenta: '#e02080', outline: '#1f1a17' };
  // first mineral code of a locality -> colour of its printed symbol (calibrated signatures; others grey)
  const CODE_COLOUR = { Au: '#fff500', Cl: '#fff500', Br: '#fff500', Gs: '#fff500', Ev: '#fff500', Ka: '#97946b',
    W: '#84c225', Ls: '#00923f', Mn: '#00923f', Bcl: '#00923f', Bc: '#00923f', Gy: '#ffffff', Ba: '#ffffff', P: '#ffffff',
    Ta: '#ffffff', Be: '#ffffff', C: '#1f1a17', Lg: '#1f1a17', Fe: '#974578', Tc: '#974578', Mo: '#974578', M: '#667ab3',
    Mb: '#da251d', Fp: '#da251d', Pb: '#da251d', Zn: '#da251d', Tm: '#da251d', Nb: '#605d5c', Sn: '#828282', Li: '#00ff00',
    Fr: '#e77817', F: '#e77817', Bt: '#1f1a17', Oil: '#1f1a17', Ts: '#1f1a17' };
  const codeColour = raw => { const m = /^[A-Za-z]+/.exec(String(raw || '').trim()); return (m && CODE_COLOUR[m[0]]) || '#8a8a8a'; };
  const textColourFor = p => {
    const k = (p.kind || '') + ' ' + (p.layer || '');
    if (/water|Rivers/i.test(k)) return '#1d4ed8';
    if (/capital/i.test(k)) return '#7f1d1d';
    if (/State_Boundarys|state name/i.test(k)) return '#374151';
    if (/mineral number/i.test(k)) return '#000';
    return '#111';
  };

  // ------------------------------------------------------------------ layer catalogue
  // Styles mimic the symbology of the PDFs so the two sides can be compared visually.
  const GEOLOGY_LAYERS = [
    { file: 'geology_units', title: 'Geology units', kind: 'polygon', on: true,
      swatch: 'linear-gradient(90deg,#f08080 0 33%,#f5ff9e 33% 66%,#7adeb0 66%)',
      style: f => unitStyle(f),
      name: p => (p.code ? p.code + ' – ' : '') + (p.unit || '') },
    { file: 'major_rivers_poly', title: 'Major rivers & Lake Chad (areas)', kind: 'polygon', on: true, swatch: '#a9d2f6',
      style: () => ({ fillColor: '#a9d2f6', fillOpacity: 1, stroke: false }), name: () => 'Major river / lake' },
    { file: 'geological_boundaries', title: 'Geological boundaries', kind: 'line', on: true, swatch: '#222',
      style: f => {
        const c = f.properties.class;
        return { color: '#222', weight: 0.9, opacity: 1,
          dashArray: c === 'approximate' ? '6 4' : c === 'inferred' ? '2 4' : c === 'transitional' ? '9 3 2 3' : null };
      }, name: p => 'Boundary (' + p.class + ')' },
    { file: 'younger_granite_outlines', title: 'Younger Granite outlines', kind: 'line', on: true, swatch: '#000',
      style: () => ({ color: '#000', weight: 1.1 }), name: () => 'Younger Granite outline' },
    { file: 'faults', title: 'Faults / fractures', kind: 'line', on: true, swatch: '#d7191c',
      style: f => ({ color: '#d7191c', weight: 1.3, dashArray: /inferred/.test(f.properties.class) ? '5 4' : null }),
      name: p => p.class },
    { file: 'fold_axes', title: 'Fold axes', kind: 'line', on: true, swatch: '#7b1fa2',
      style: () => ({ color: '#7b1fa2', weight: 1.5 }), name: p => p.class + ' axis' },
    { file: 'ridges', title: 'Ridges', kind: 'line', on: true, swatch: '#8d6e63',
      style: () => ({ color: '#8d6e63', weight: 1.8 }), name: () => 'Ridge' },
    { file: 'rivers', title: 'Rivers', kind: 'line', on: true, swatch: '#3b82f6',
      style: () => ({ color: '#3b82f6', weight: 0.9 }), name: () => 'River' },
    { file: 'major_rivers_outline', title: 'Major river outlines', kind: 'line', on: true, swatch: '#3b82f6',
      style: () => ({ color: '#3b82f6', weight: 0.8 }), name: () => 'Major river outline' },
    { file: 'state_boundaries', title: 'State boundaries', kind: 'line', on: true, swatch: '#8a8a8a',
      style: () => ({ color: '#8a8a8a', weight: 2.6, opacity: 0.9, dashArray: '10 4 2 4' }), name: () => 'State boundary' },
    { file: 'roads', title: 'Roads (centrelines)', kind: 'line', on: true, swatch: '#555',
      style: () => ({ color: '#555', weight: 1.4 }), name: () => 'Road' },
    { file: 'railway', title: 'Railway', kind: 'line', on: true, swatch: '#000',
      style: () => ({ color: '#000', weight: 1.6, dashArray: '6 3' }), name: () => 'Railway' },
    { file: 'graticule', title: 'Fitted graticule (QA)', kind: 'line', on: false, swatch: '#999',
      style: () => ({ color: '#999', weight: 0.7 }), name: p => p.axis + ' ' + p.value + '°' },
    { file: 'towns', title: 'Towns', kind: 'point', on: true, swatch: '#000',
      point: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: '#000', weight: 1, fillColor: '#000', fillOpacity: 1 }),
      name: p => p.name || '(unnamed town)' },
    { file: 'volcanic_plugs', title: 'Volcanic plugs & pipes', kind: 'point', on: true, swatch: '#000',
      point: (f, ll) => L.circleMarker(ll, { radius: 4, color: '#000', weight: 1.3, fill: false }),
      name: () => 'Volcanic plug / pipe' },
    { file: 'state_capitals', title: 'State capitals (approx.)', kind: 'point', on: true, swatch: '#e53935',
      point: (f, ll) => L.circleMarker(ll, { radius: 5.5, color: '#fff', weight: 1.5, fillColor: '#e53935', fillOpacity: 1 }),
      name: p => p.name },
    { file: 'labels', title: 'Map text (unit codes, names)', kind: 'labels', on: true, swatch: '#fff', anchor: 'origin',
      name: p => p.text },
  ];

  const MINERAL_LAYERS = [
    { file: 'map_zones', title: 'Numbering zones A–G', kind: 'polygon', on: true, swatch: '#d946ef',
      style: () => ({ color: '#d946ef', weight: 1.6, dashArray: '8 5', fill: true, fillOpacity: 0.02 }),
      tooltip: p => p.zone, name: p => 'Zone ' + p.zone + ' (' + p.tbl_rows + ' table rows, ' + p.labels + ' numbers on the map)' },
    { file: 'division_lines', title: 'Division lines', kind: 'line', on: false, swatch: '#d946ef',
      style: () => ({ color: '#d946ef', weight: 2 }), name: () => 'Division line' },
    { file: 'map_frame', title: 'Map frame (GeoPDF viewport)', kind: 'line', on: false, swatch: '#777',
      style: () => ({ color: '#777', weight: 1.2, fill: false }), name: p => p.name },
    { file: 'international_boundary', title: 'International boundary', kind: 'line', on: true, swatch: '#16a34a',
      style: () => ({ color: '#16a34a', weight: 2.4, opacity: 0.9 }), name: () => 'International boundary' },
    { file: 'rivers', title: 'Rivers (2023 map)', kind: 'line', on: false, swatch: '#60a5fa',
      style: () => ({ color: '#60a5fa', weight: 0.9 }), name: () => 'River' },
    { file: 'roads', title: 'Roads (2023 map, centrelines)', kind: 'line', on: false, swatch: '#9a3412',
      style: () => ({ color: '#9a3412', weight: 1.3 }), name: () => 'Road' },
    { file: 'railway', title: 'Railway (2023 map)', kind: 'line', on: false, swatch: '#000',
      style: () => ({ color: '#000', weight: 1.6, dashArray: '6 3' }), name: () => 'Railway' },
    { file: 'graticule', title: 'Graticule (printed vs /VP)', kind: 'line', on: false, swatch: '#999',
      style: () => ({ color: '#999', weight: 0.7, dashArray: '3 3' }),
      name: p => p.axis + ' – printed ' + p.printed + '°, GeoPDF ' + p.vp_value + '°' },
    { file: 'mineral_symbols_raster', title: 'Raster symbol blobs (all detections)', kind: 'point', on: false, swatch: '#fff500',
      point: (f, ll) => {
        const c = SYMBOL_RGB[f.properties.colour] || '#999', hollow = f.properties.fill === 'sparse';
        return L.circleMarker(ll, { radius: f.properties.fill === 'round' ? 3.5 : 3, color: hollow ? c : '#000', weight: hollow ? 1.6 : 0.6,
          fillColor: hollow ? '#fff' : c, fillOpacity: hollow ? 0.6 : 0.9 });
      },
      name: p => (p.candidates || 'no matching rule') + (p.near_num ? ' · near ' + p.near_num : '') },
    { file: 'mineral_localities', title: 'Mineral localities (numbered)', kind: 'point', on: true, swatch: '#fff500',
      point: (f, ll) => localityMarker(f, ll),
      name: p => p.zone_num + ' ' + (p.locality || '(not in table)') + (p.codes_raw ? ' – ' + p.codes_raw : '') },
    { virtual: 'mineral_numbers', from: 'mineral_localities', title: 'Printed numbers (as on the map)', kind: 'labels', on: true, swatch: '#fff', anchor: 'centre',
      derive: fc => fc.features.map(f => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.properties.label_lon, f.properties.label_lat] },
        properties: { text: String(f.properties.number), size_pt: 6.72, font: 'ArialMT', angle: 0, kind: 'mineral number' } })),
      name: p => p.text },
    { file: 'towns', title: 'Towns (2023 map)', kind: 'point', on: false, swatch: '#000',
      point: (f, ll) => L.circleMarker(ll, { radius: 3, color: '#000', weight: 1, fillColor: f.properties.kind === 'town marker' ? '#000' : '#fff', fillOpacity: 1 }),
      name: p => p.name || '(unnamed town)' },
    { file: 'state_capitals', title: 'State capitals (2023 map)', kind: 'point', on: true, swatch: '#b91c1c',
      point: (f, ll) => L.circleMarker(ll, { radius: 5.5, color: '#fff', weight: 1.5, fillColor: '#b91c1c', fillOpacity: 1 }),
      name: p => p.name },
    { file: 'map_labels', title: 'Map text (towns, states, rivers)', kind: 'labels', on: true, swatch: '#fff', anchor: 'centre',
      name: p => p.text },
    { file: 'river_labels', title: 'River names (points)', kind: 'point', on: false, swatch: '#1d4ed8',
      point: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: '#1d4ed8', weight: 1.2, fill: false }), name: p => p.name },
    { file: 'state_name_labels', title: 'State names (points)', kind: 'point', on: false, swatch: '#374151',
      point: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: '#374151', weight: 1.2, fill: false }), name: p => p.name },
    { file: 'pegmatite_marks', title: 'Pegmatite marks “P”', kind: 'point', on: false, swatch: '#7c2d12',
      point: (f, ll) => L.circleMarker(ll, { radius: 4, color: '#7c2d12', weight: 1.4, fill: false }), name: p => p.meaning },
  ];

  const DATASETS = {
    geology: { key: 'geology', title: 'Geological Map (2011)', short: 'Geology 2011', metaUrl: 'build/data/meta.json',
      dataDir: 'build/data/', tilesUrl: 'build/tiles/{z}/{x}/{y}.png', layers: GEOLOGY_LAYERS,
      attribution: 'NGSA Geological Map of Nigeria 1:2M (PDF) · extract_shapefiles.py' },
    minerals: { key: 'minerals', title: 'Mineral Resources Map (2023)', short: 'Minerals 2023', metaUrl: 'build/data/minerals/meta.json',
      dataDir: 'build/data/minerals/', tilesUrl: 'build/tiles_minerals/{z}/{x}/{y}.png', layers: MINERAL_LAYERS,
      attribution: 'NGSA Mineral Resources Map of Nigeria 2023 (GeoPDF) · extract_mineral_map.py' },
  };
  const LAYERS = [];                       // flat list in drawing order, ids prefixed with the dataset key
  const byId = {};
  for (const ds of Object.values(DATASETS)) {
    for (const def of ds.layers) {
      def.ds = ds.key;
      def.id = ds.key + ':' + (def.file || def.virtual);
      LAYERS.push(def); byId[def.id] = def;
    }
  }

  // ------------------------------------------------------------------ state
  const metas = {};                        // dataset key -> meta.json
  let map, pdfLayer, pdfSource = 'geology';
  let mode = 'swipe', swipeFrac = 0.5, highlighted = null, outlineUnits = false, highlightMineral = null;
  let unitScheme = 'fill';                 // 'fill' (printed colour) | 'era' | 'period' | 'rock_cls'
  const SCHEME_COLOURS = {
    era: { 'Cenozoic': '#f9f97f', 'Mesozoic': '#67c5ca', 'Neoproterozoic-Palaeozoic': '#f9b4c0',
      'Neoproterozoic (Pan-African deformed)': '#b8e986', 'Archaean-Palaeoproterozoic, reworked in the Neoproterozoic': '#f0a06a',
      'Archaean-Proterozoic (to Cambrian)': '#d9a0d9' },
    period: { 'Quaternary': '#f9f97f', 'Neogene-Quaternary': '#ffe619', 'Paleogene-Neogene': '#fdb462', 'Paleogene': '#fd9a52',
      'Paleogene-Quaternary (Tertiary-Recent)': '#e76f51', 'Cretaceous': '#7fc64e', 'Jurassic': '#34b2c9',
      'Ediacaran-Cambrian': '#fed96a', '(Precambrian) - Cambrian': '#f74370' },
    rock_cls: { 'sedimentary': '#f6e27f', 'volcanic': '#c0392b', 'plutonic': '#e67e9a', 'metamorphic': '#5dade2',
      'fault rock': '#7f8c8d', 'minor intrusive': '#8e44ad' } };
  const SCHEME_TITLES = { fill: 'printed legend colour', era: 'era (from the legend brackets)', period: 'period (ICS)', rock_cls: 'rock class' };
  const UNDATED = '#e5e5e5';
  function schemeColour(p) {
    if (unitScheme === 'fill') return p.fill || '#cccccc';
    let v = p[unitScheme];
    if (unitScheme === 'period' && !v && p.era) v = p.era.indexOf('Archaean') === 0 ? '(Precambrian) - Cambrian' : (p.era.indexOf('Neoproterozoic') === 0 ? 'Ediacaran-Cambrian' : '');
    return (v && SCHEME_COLOURS[unitScheme][v]) || UNDATED;
  }
  const data = {}, groups = {}, visible = {};
  let unitsIndex = [];     // [{bbox:[minx,miny,maxx,maxy], feature}]

  function unitStyle(f) {
    const p = f.properties;
    const dim = highlighted && p.code !== highlighted;
    return { fillColor: schemeColour(p), fillOpacity: dim ? 0.10 : 1,
      stroke: outlineUnits, color: '#333', weight: 0.6, opacity: 1 };
  }
  function localityColour(p) {
    // colour of the matched raster symbol when there is one, otherwise the colour the legend gives the first code
    const sc = p.sym_colour && !/^nearest/.test(p.sym_colour) ? SYMBOL_RGB[p.sym_colour] : null;
    return sc || codeColour(p.codes_raw);
  }
  function localityStyle(p) {
    const dim = highlightMineral && !(' ' + (p.minerals || '') + ' ').toLowerCase().includes(highlightMineral.toLowerCase());
    const snapped = /raster symbol/.test(p.pos_src || '');
    return { radius: dim ? 3 : 4.5, color: dim ? '#999' : '#000', weight: snapped ? 1 : 1.4, dashArray: snapped ? null : '2 2',
      fillColor: localityColour(p), fillOpacity: dim ? 0.15 : 0.95, opacity: dim ? 0.3 : 1 };
  }
  function localityMarker(f, ll) { return L.circleMarker(ll, localityStyle(f.properties)); }

  // ------------------------------------------------------------------ canvas label layer
  const LabelLayer = L.Layer.extend({
    options: { pane: 'labels', ptPerDeg: 157.6, anchor: 'origin' },
    initialize: function (features, options) { L.setOptions(this, options); this._features = features; },
    onAdd: function (m) {
      this._canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide');
      this._canvas.style.pointerEvents = 'none';
      this._canvas.style.position = 'absolute';
      this.getPane().appendChild(this._canvas);
      m.on('moveend zoomend viewreset resize', this._reset, this);
      this._reset();
    },
    onRemove: function (m) {
      m.off('moveend zoomend viewreset resize', this._reset, this);
      L.DomUtil.remove(this._canvas);
    },
    _reset: function () {
      const m = this._map, size = m.getSize(), dpr = window.devicePixelRatio || 1;
      L.DomUtil.setPosition(this._canvas, m.containerPointToLayerPoint([0, 0]));
      this._canvas.width = Math.round(size.x * dpr);
      this._canvas.height = Math.round(size.y * dpr);
      this._canvas.style.width = size.x + 'px';
      this._canvas.style.height = size.y + 'px';
      this._draw(dpr, size);
    },
    _draw: function (dpr, size) {
      const m = this._map, ctx = this._canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.x, size.y);
      const degPerPx = 180 / (256 * Math.pow(2, m.getZoom()));
      const ptPerPx = degPerPx * this.options.ptPerDeg;          // PDF points per screen pixel
      const bounds = m.getBounds().pad(0.15);
      const centre = this.options.anchor === 'centre';
      ctx.textBaseline = centre ? 'middle' : 'alphabetic'; ctx.textAlign = centre ? 'center' : 'left'; ctx.lineJoin = 'round';
      for (const f of this._features) {
        const p = f.properties, c = f.geometry.coordinates;
        if (c[1] < bounds.getSouth() || c[1] > bounds.getNorth() || c[0] < bounds.getWest() || c[0] > bounds.getEast()) continue;
        const natural = (p.size_pt || 7) / ptPerPx;      // text height as printed, in px
        if (natural < 6) continue;                        // too small to read: skip (as on paper)
        const px = Math.max(natural, 9);
        const pt = m.latLngToContainerPoint([c[1], c[0]]);
        ctx.save();
        ctx.translate(pt.x, pt.y);
        if (p.angle) ctx.rotate(-p.angle * Math.PI / 180);
        ctx.font = fontFor(p.font, px);
        ctx.lineWidth = Math.max(2, px / 5);
        ctx.strokeStyle = 'rgba(255,255,255,0.85)';
        ctx.strokeText(p.text, 0, 0);
        ctx.fillStyle = textColourFor(p);
        ctx.fillText(p.text, 0, 0);
        ctx.restore();
      }
    }
  });
  function fontFor(font, px) {
    font = font || '';
    const serif = /Times/i.test(font);
    const bold = /Bold/i.test(font) ? 'bold ' : '';
    const italic = /Italic/i.test(font) ? 'italic ' : '';
    return italic + bold + px.toFixed(1) + 'px ' + (serif ? 'Georgia, "Times New Roman", serif' : 'Arial, Helvetica, sans-serif');
  }

  // ------------------------------------------------------------------ map
  function unionBounds() {
    let b = null;
    for (const m of Object.values(metas)) {
      const pb = L.latLngBounds(m.tiles.page_bounds);
      b = b ? b.extend(pb) : pb;
    }
    return b;
  }
  function initMap() {
    const page = unionBounds();
    map = L.map('map', {
      crs: L.CRS.EPSG4326,
      renderer: L.canvas({ tolerance: 8, padding: 0.3 }),
      zoomControl: false, attributionControl: false,
      zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,
      minZoom: 4, maxZoom: 11,
      maxBounds: page.pad(0.15),
      maxBoundsViscosity: 0.6,
    });
    map.createPane('pdf').style.zIndex = 250;
    map.createPane('labels').style.zIndex = 450;
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft', maxWidth: 120 }).addTo(map);
    map._attrib = L.control.attribution({ prefix: false, position: 'bottomleft' }).addTo(map);
    setPdfSource(metas.geology ? 'geology' : 'minerals', true);
    map.fitBounds(L.latLngBounds(metas[pdfSource].map_face_bounds), { padding: [6, 6] });
    map.on('move resize', updateClip);
    map.on('click', () => { if ($('#sheet').classList.contains('open')) closeSheet(); });
  }

  function setPdfSource(key, silent) {
    if (!metas[key]) return;
    pdfSource = key;
    const m = metas[key], ds = DATASETS[key];
    if (pdfLayer) map.removeLayer(pdfLayer);
    pdfLayer = L.tileLayer(ds.tilesUrl, {
      pane: 'pdf', tileSize: 256, minZoom: 4, maxZoom: 11,
      minNativeZoom: m.tiles.zmin, maxNativeZoom: m.tiles.zmax,
      noWrap: true, bounds: L.latLngBounds(m.tiles.page_bounds), keepBuffer: 2, updateWhenIdle: true,
    }).addTo(map);
    Object.values(DATASETS).forEach(d => map._attrib.removeAttribution(d.attribution));
    map._attrib.addAttribution(ds.attribution);
    $('#badge-left').textContent = 'PDF · ' + ds.short;
    $$('input[name="pdf-src"]').forEach(r => { r.checked = r.value === key; });
    const chip = $('#chip-pdf'); if (chip) chip.textContent = 'PDF: ' + ds.short + ' ⇄';
    if (!silent) toast('PDF side now shows the ' + ds.title);
  }

  function vecPanes() { return [map.getPane('overlayPane'), map.getPane('labels'), map.getPane('tooltipPane')]; }

  function updateClip() {
    if (!map || mode !== 'swipe') return;
    const size = map.getSize();
    const nw = map.containerPointToLayerPoint([0, 0]);
    const se = map.containerPointToLayerPoint(size);
    const x = nw.x + size.x * swipeFrac;
    map.getPane('pdf').style.clip = 'rect(' + nw.y + 'px, ' + x + 'px, ' + se.y + 'px, ' + nw.x + 'px)';
    vecPanes().forEach(p => { p.style.clip = 'rect(' + nw.y + 'px, ' + se.x + 'px, ' + se.y + 'px, ' + x + 'px)'; });
    $('#swipe').style.left = (size.x * swipeFrac) + 'px';
    $('#swipe-handle').setAttribute('aria-valuenow', Math.round(swipeFrac * 100));
  }

  function setMode(m) {
    mode = m;
    $$('#mode button').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
    const showPdf = m !== 'vector', showVec = m !== 'pdf';
    map.getPane('pdf').style.display = showPdf ? '' : 'none';
    vecPanes().forEach(p => { p.style.display = showVec ? '' : 'none'; });
    ['#swipe', '#badge-left', '#badge-right'].forEach(s => $(s).classList.toggle('hidden', m !== 'swipe'));
    $('#opacity').classList.toggle('hidden', m !== 'overlay');
    if (m === 'swipe') { updateClip(); } else {
      map.getPane('pdf').style.clip = 'auto';
      vecPanes().forEach(p => { p.style.clip = 'auto'; });
    }
    setVecOpacity(m === 'overlay' ? $('#opacity-range').value / 100 : 1);
  }
  function setVecOpacity(v) { vecPanes().forEach(p => { p.style.opacity = v; }); }

  // swipe handle (pointer events; the handle lives outside the map container)
  function initSwipe() {
    const wrap = $('#map-wrap'), el = $('#swipe');
    let dragging = false;
    const move = e => {
      if (!dragging) return;
      const r = wrap.getBoundingClientRect();
      swipeFrac = clamp((e.clientX - r.left) / r.width, 0.04, 0.96);
      updateClip();
    };
    el.addEventListener('pointerdown', e => { dragging = true; el.setPointerCapture(e.pointerId); e.preventDefault(); move(e); });
    el.addEventListener('pointermove', move);
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(t => el.addEventListener(t, () => { dragging = false; }));
  }

  // ------------------------------------------------------------------ vector layers
  function buildGroups() {
    for (const def of LAYERS) {
      const fc = def.virtual ? data[def.ds + ':' + def.from] : data[def.id];
      if (!fc) continue;
      const ptPerDeg = (metas[def.ds] && metas[def.ds].georef.points_per_degree) || 157.6;
      if (def.kind === 'labels') {
        let feats = def.derive ? def.derive(fc) : fc.features;
        if (def.id === 'geology:labels') {
          // the PDF draws halo text twice (two slightly offset copies): keep one
          const seen = new Set();
          feats = feats.filter(f => {
            const c = f.geometry.coordinates, p = f.properties;
            const key = p.kind + '|' + p.text + '|' + Math.round(c[0] / 0.01) + '|' + Math.round(c[1] / 0.01);
            if (seen.has(key)) return false;
            seen.add(key); return true;
          });
        }
        groups[def.id] = new LabelLayer(feats, { ptPerDeg, anchor: def.anchor || 'origin' });
      } else {
        groups[def.id] = L.geoJSON(fc, {
          style: def.style,
          pointToLayer: def.point,
          bubblingMouseEvents: false,
          smoothFactor: 0.8,
          onEachFeature: (f, layer) => {
            layer.on('click', e => showFeature(def, f, e.latlng));
            if (def.tooltip) layer.bindTooltip(def.tooltip(f.properties), { permanent: true, direction: 'center', className: 'zone-tip' });
          },
        });
      }
      visible[def.id] = def.on;
      if (def.on) groups[def.id].addTo(map);
    }
    restackLayers();
    // spatial index for "what geology unit is here?"
    const units = data['geology:geology_units'];
    unitsIndex = units ? units.features.map(f => {
      let minx = 180, miny = 90, maxx = -180, maxy = -90;
      eachRing(f.geometry, ring => ring.forEach(c => {
        if (c[0] < minx) minx = c[0]; if (c[0] > maxx) maxx = c[0];
        if (c[1] < miny) miny = c[1]; if (c[1] > maxy) maxy = c[1];
      }));
      return { bbox: [minx, miny, maxx, maxy], feature: f };
    }) : [];
  }
  function eachRing(geom, fn) {
    if (geom.type === 'Polygon') geom.coordinates.forEach(fn);
    else if (geom.type === 'MultiPolygon') geom.coordinates.forEach(poly => poly.forEach(fn));
  }
  function pointInRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }
  function pointInPoly(x, y, rings) {
    if (!pointInRing(x, y, rings[0])) return false;
    for (let k = 1; k < rings.length; k++) if (pointInRing(x, y, rings[k])) return false;
    return true;
  }
  function unitsAt(lng, lat) {
    const hits = [];
    for (const it of unitsIndex) {
      const b = it.bbox;
      if (lng < b[0] || lng > b[2] || lat < b[1] || lat > b[3]) continue;
      const g = it.feature.geometry;
      const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
      if (polys.some(rings => pointInPoly(lng, lat, rings))) hits.push(it.feature);
    }
    return hits;
  }

  function restackLayers() {
    // keep the canonical drawing order after toggling layers on/off
    for (const def of LAYERS) {
      const g = groups[def.id];
      if (g && visible[def.id] && g.bringToFront) g.bringToFront();
    }
  }
  function setLayerVisible(id, on) {
    visible[id] = on;
    const g = groups[id];
    if (!g) return;
    if (on && !map.hasLayer(g)) g.addTo(map);
    if (!on && map.hasLayer(g)) map.removeLayer(g);
    restackLayers();
    const cb = $('input[data-layer="' + id + '"]');
    if (cb && cb.checked !== on) cb.checked = on;
  }

  // ------------------------------------------------------------------ bottom sheet
  function openSheet(tab) { $('#sheet').classList.add('open'); $('#sheet').setAttribute('aria-hidden', 'false'); if (tab) setTab(tab); }
  function closeSheet() { $('#sheet').classList.remove('open', 'tall'); $('#sheet').setAttribute('aria-hidden', 'true'); }
  function setTab(t) {
    $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    $$('.panel').forEach(p => p.classList.toggle('active', p.dataset.panel === t));
    $('.sheet-body').scrollTop = 0;
  }
  function initSheet() {
    $$('#tabs button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
    $('#sheet-close').addEventListener('click', closeSheet);
    $('#btn-layers').addEventListener('click', () => openSheet('layers'));
    $('#btn-legend').addEventListener('click', () => openSheet('legend'));
    $('#btn-about').addEventListener('click', () => openSheet('compare'));
    // grip: drag down to close, up to expand, tap to toggle height
    const grip = $('#sheet-grip'); let y0 = null;
    grip.addEventListener('pointerdown', e => { y0 = e.clientY; grip.setPointerCapture(e.pointerId); });
    grip.addEventListener('pointerup', e => {
      if (y0 == null) return;
      const dy = e.clientY - y0; y0 = null;
      if (dy > 50) closeSheet();
      else if (dy < -50) $('#sheet').classList.add('tall');
      else $('#sheet').classList.toggle('tall');
    });
  }

  // ------------------------------------------------------------------ feature panel
  const PRETTY = { ocg_id: 'PDF layer id', layer_no: 'layer order', unit: 'unit (PDF layer name)', fill: 'fill colour',
    code: 'code', code_src: 'code source', leg_code: 'legend code', leg_desc: 'legend description', lbl_code: 'label on map',
    n_lbl: 'labels inside', area_km2: 'area (km²)', n_rings: 'rings', src_seq: 'PDF sequence no.', dup_of: 'duplicate of',
    width_pt: 'line width (pt)', n_frag: 'fragments merged', len_km: 'length (km)', length_km: 'length (km)', name_kind: 'name source',
    name_dist: 'label distance (pt)', size_pt: 'text size (pt)', stroke: 'stroke colour', 'class': 'class', text: 'text', kind: 'kind', font: 'font', angle: 'angle (°)',
    zone_num: 'map number', zone: 'zone', number: 'number', locality: 'locality (table)', codes_raw: 'codes as printed', minerals: 'minerals',
    min_conf: 'code confidence', match: 'table join', tbl_flags: 'table flags', pos_src: 'point position', snap_pt: 'snap distance (pt)',
    sym_colour: 'symbol colour', sym_cands: 'symbol candidates', label_lon: 'number printed at lon', label_lat: 'number printed at lat',
    colour: 'colour class', w_px: 'width (px)', h_px: 'height (px)', body_w: 'body width (px)', body_h: 'body height (px)', candidates: 'candidate minerals',
    link: 'link to a number', near_num: 'nearest number', near_dist: 'distance (pt)', near_loc: 'its locality', near_mins: 'its minerals',
    tbl_rows: 'table rows', labels: 'numbers on the map', src: 'position source', vp_value: 'GeoPDF value (°)', printed: 'printed label (°)',
    n_glyphs: 'glyphs', meaning: 'meaning', symbol: 'symbol',
    // stratigraphy / sizes / joins added in the attribute pass
    perim_km: 'perimeter (km)', cen_lon: 'centroid lon', cen_lat: 'centroid lat', leg_row: 'legend row', formation: 'formation (legend / chart)',
    strat_grp: 'group', age_print: 'age as printed', series: 'series / complex (printed)', period_prt: 'period bracket (printed)',
    eon: 'eon', era: 'era', period: 'period', epoch: 'epoch / stage', age_ma_min: 'youngest (Ma)', age_ma_max: 'oldest (Ma)',
    age_src: 'how the age was read', rock_cls: 'rock class', basins: 'basins (correlation chart)', lon: 'lon', lat: 'lat',
    unit_code: 'unit code here', unit_era: 'unit era', unit_per: 'unit period', n_chars: 'characters', page_x: 'page x (pt)', page_y: 'page y (pt)',
    label: 'label', page_pt: 'page position (pt)', n_lines: 'lines of this axis', name_src: 'name source', labels_in: 'water names inside',
    min_lon: 'west', max_lon: 'east', min_lat: 'south', max_lat: 'north', n_minerals: 'minerals listed', mineral_1: 'first mineral',
    group_1: 'commodity group (first)', groups: 'commodity groups', n_unknown: 'unknown codes', geo_code: 'host unit code (2011 map)',
    geo_unit: 'host unit', geo_form: 'host formation', geo_era: 'host era', geo_period: 'host period', geo_epoch: 'host epoch / stage',
    geo_src: 'host geology source', w_pt: 'width (pt)', h_pt: 'height (pt)', w_mm: 'width on paper (mm)', h_mm: 'height on paper (mm)',
    w_km: 'width on the ground (km)', h_km: 'height on the ground (km)', n_cands: 'candidate count', near_grps: 'its commodity groups',
    n_local: 'localities', n_symbols: 'raster symbols', top_grps: 'main commodity groups', zones: 'zones separated', n_vert: 'vertices',
    len_pt: 'length on page (pt)', offset_deg: 'VP minus printed (°)', width_deg: 'width (°)', height_deg: 'height (°)', width_pt: 'width (pt)',
    height_pt: 'height (pt)', scale: 'scale', near_km: 'distance (km)', ref_lon: 'reference lon', ref_lat: 'reference lat',
    ref_dx_km: 'offset E (km)', ref_dy_km: 'offset N (km)', capital: 'state capital', in_frame: 'inside map frame', mid_lon: 'midpoint lon',
    mid_lat: 'midpoint lat', start_lon: 'start lon', start_lat: 'start lat', end_lon: 'end lon', end_lat: 'end lat', closed: 'closed ring' };
  const SKIP = { layer: 1 };
  function stratStrip(p) {
    if (!p.era && !p.period_prt && !p.age_print) return '';
    const parts = [];
    if (p.era) parts.push('<span class="pill strat">' + esc(p.era) + '</span>');
    if (p.period) parts.push('<span class="pill strat">' + esc(p.period) + '</span>');
    if (p.epoch) parts.push('<span class="pill strat">' + esc(p.epoch) + '</span>');
    if (p.age_ma_max != null && p.age_ma_min != null) parts.push('<span class="pill">' + esc(p.age_ma_min) + '–' + esc(p.age_ma_max) + ' Ma</span>');
    if (p.age_print) parts.push('<span class="pill">printed: ' + esc(p.age_print) + '</span>');
    else if (p.series) parts.push('<span class="pill">printed: ' + esc(p.series) + '</span>');
    else if (p.period_prt) parts.push('<span class="pill">printed: ' + esc(p.period_prt) + '</span>');
    if (p.age_src && /fall-back|nearest|swapped|not in printed/.test(p.age_src)) parts.push('<span class="pill warn">inferred – see "how the age was read"</span>');
    return '<p class="strat-strip">' + parts.join(' ') + '</p>';
  }

  function propsTable(p) {
    let h = '<table class="kv">';
    for (const k of Object.keys(p)) {
      if (SKIP[k]) continue;
      let v = p[k];
      if (v == null || v === '' || (k === 'dup_of' && !v)) continue;
      if (typeof v === 'number' && !Number.isInteger(v)) v = v.toLocaleString('en', { maximumFractionDigits: 4 });
      if ((k === 'fill' || k === 'stroke') && /^#/.test(String(v))) v = '<span class="pill" style="background:' + esc(v) + ';color:#000;border:1px solid #0003">' + esc(v) + '</span>';
      else v = esc(v);
      h += '<tr><th>' + esc(PRETTY[k] || k) + '</th><td>' + v + '</td></tr>';
    }
    return h + '</table>';
  }

  function featureCard(def, f) {
    const p = f.properties || {};
    let colour = typeof def.swatch === 'string' && def.swatch[0] === '#' ? def.swatch : '#ddd';
    if (def.id === 'geology:geology_units') colour = p.fill || '#ccc';
    if (def.id === 'minerals:mineral_localities') colour = localityColour(p);
    if (def.id === 'minerals:mineral_symbols_raster') colour = SYMBOL_RGB[p.colour] || '#999';
    let flags = '';
    if (def.id === 'geology:geology_units') {
      flags += '<span class="pill">code from ' + esc(p.code_src) + '</span>';
      if (p.lbl_code && p.leg_code && p.lbl_code !== p.leg_code) flags += '<span class="pill warn">map label says ' + esc(p.lbl_code) + '</span>';
      if (p.dup_of) flags += '<span class="pill warn">duplicate geometry (of #' + esc(p.dup_of) + ')</span>';
      if (!p.leg_code) flags += '<span class="pill warn">not in printed legend</span>';
    }
    if (def.id === 'geology:state_capitals') flags += '<span class="pill warn">position ≈ label centre (±7–15 km)</span>';
    if (def.id === 'geology:towns' && !p.name) flags += '<span class="pill warn">no label matched</span>';
    if (def.id === 'minerals:mineral_localities') {
      flags += /raster symbol/.test(p.pos_src || '') ? '<span class="pill">on its raster symbol (' + esc(p.snap_pt) + ' pt from the number)</span>'
        : '<span class="pill warn">position = printed number (symbol not matched)</span>';
      if (p.match !== 'exact') flags += '<span class="pill warn">' + esc(p.match) + '</span>';
      if (/unknown/.test(p.min_conf || '')) flags += '<span class="pill warn">code not in legend</span>';
      if (p.tbl_flags) flags += '<span class="pill warn">table row flagged</span>';
    }
    if (def.id === 'minerals:state_capitals') flags += '<span class="pill">' + esc(p.src) + '</span>';
    if (def.id === 'minerals:towns' && p.kind !== 'town marker') flags += '<span class="pill warn">' + esc(p.kind) + '</span>';
    let strip = '';
    if (def.id === 'geology:geology_units') strip = stratStrip(p);
    if (def.id === 'minerals:mineral_localities' && p.groups) strip = '<p class="strat-strip">' + String(p.groups).split(' | ').map(g => '<span class="pill strat">' + esc(g) + '</span>').join(' ') +
      (p.geo_unit ? ' <span class="pill">on ' + esc(p.geo_code) + ' · ' + esc(p.geo_era || '') + '</span>' : '') + '</p>';
    if (/^geology:(towns|state_capitals|volcanic_plugs)$/.test(def.id) && p.unit_code) strip = '<p class="strat-strip"><span class="pill strat">on ' + esc(p.unit_code) + ' · ' + esc(p.unit_era || '') + '</span></p>';
    return '<div class="feature-head"><div class="sw" style="background:' + esc(colour) + '"></div><div>' +
      '<div class="name">' + esc(def.name(p)) + '</div><div class="sub">' + esc(def.title) + ' · ' + esc(DATASETS[def.ds].short) + '</div></div></div>' +
      (flags ? '<p>' + flags + '</p>' : '') + strip + propsTable(p);
  }

  function showFeature(def, f, latlng) {
    let h = featureCard(def, f);
    const unitDef = byId['geology:geology_units'];
    if (unitDef && def.id !== 'geology:geology_units' && latlng) {
      const under = unitsAt(latlng.lng, latlng.lat);
      if (under.length) {
        h += '<div class="under"><h3>Geology unit at this point (2011 map)</h3>' +
          under.map(u => featureCard(unitDef, u)).join('<hr>') + '</div>';
      }
    } else if (unitDef && latlng) {
      const under = unitsAt(latlng.lng, latlng.lat).filter(u => u !== f);
      if (under.length) {
        h += '<div class="under"><h3>Overlapping unit polygon' + (under.length > 1 ? 's' : '') + '</h3>' +
          under.map(u => featureCard(unitDef, u)).join('<hr>') + '</div>';
      }
    }
    $('[data-panel="feature"]').innerHTML = h;
    openSheet('feature');
    // keep the tapped point visible above the sheet
    if (latlng && window.innerWidth < 900) {
      const pt = map.latLngToContainerPoint(latlng), size = map.getSize();
      if (pt.y > size.y * 0.38) map.panBy([0, pt.y - size.y * 0.25], { animate: true });
    }
  }

  // ------------------------------------------------------------------ layers panel
  function renderLayersPanel() {
    const counts = {};
    for (const [k, m] of Object.entries(metas)) m.layers.forEach(l => { counts[k + ':' + l.id] = l.count; });
    counts['minerals:mineral_numbers'] = counts['minerals:mineral_localities'];
    let h = '<div class="pdf-src"><span class="lbl">PDF side shows</span>';
    for (const ds of Object.values(DATASETS)) {
      if (!metas[ds.key]) continue;
      h += '<label><input type="radio" name="pdf-src" value="' + ds.key + '"' + (pdfSource === ds.key ? ' checked' : '') + '> ' + esc(ds.title) + '</label>';
    }
    h += '</div>';
    for (const ds of Object.values(DATASETS)) {
      if (!metas[ds.key]) continue;
      const defs = ds.layers.filter(d => groups[d.id]);
      h += '<div class="group" data-group="' + ds.key + '"><div class="group-head"><h3>' + esc(ds.title) + '</h3>' +
        '<div class="row-actions"><button class="btn" data-all="on">All on</button><button class="btn" data-all="off">All off</button>' +
        (ds.key === 'geology' ? '<button class="btn" data-all="units">Units only</button>' : '<button class="btn" data-all="minerals">Minerals only</button>') +
        '</div></div>';
      for (const def of defs) {
        h += '<label class="layer-row"><span class="sw" style="background:' + def.swatch + '"></span>' +
          '<span class="lbl">' + esc(def.title) + '<br><span class="cnt">' + fmt(counts[def.id]) + ' features</span></span>' +
          '<span class="switch"><input type="checkbox" data-layer="' + def.id + '"' + (visible[def.id] ? ' checked' : '') + '><i></i></span></label>';
      }
      if (ds.key === 'geology') {
        h += '<label class="layer-row"><span class="sw" style="background:#fff;border:1.5px solid #333"></span><span class="lbl">Outline unit polygons</span>' +
          '<span class="switch"><input type="checkbox" id="outline-toggle"><i></i></span></label>';
        h += '<div class="layer-row scheme-row"><span class="sw" style="background:linear-gradient(90deg,#f9f97f,#67c5ca,#f9b4c0,#f0a06a)"></span>' +
          '<span class="lbl">Colour rock units by<br><select id="unit-scheme">' +
          Object.keys(SCHEME_TITLES).map(k => '<option value="' + k + '"' + (unitScheme === k ? ' selected' : '') + '>' + esc(SCHEME_TITLES[k]) + '</option>').join('') +
          '</select></span></div><div id="scheme-key" class="scheme-key"></div>';
      }
      h += '</div>';
    }
    const el = $('[data-panel="layers"]'); el.innerHTML = h;
    $$('input[data-layer]', el).forEach(cb => cb.addEventListener('change', () => setLayerVisible(cb.dataset.layer, cb.checked)));
    $$('input[name="pdf-src"]', el).forEach(r => r.addEventListener('change', () => { if (r.checked) setPdfSource(r.value); }));
    $$('.group', el).forEach(g => {
      const key = g.dataset.group;
      $$('button[data-all]', g).forEach(b => b.addEventListener('click', () => {
        const what = b.dataset.all;
        $$('input[data-layer]', g).forEach(cb => {
          const id = cb.dataset.layer;
          const on = what === 'on' ? true : what === 'off' ? false : what === 'units' ? id === 'geology:geology_units'
            : (id === 'minerals:mineral_localities' || id === 'minerals:mineral_numbers');
          if (cb.checked !== on) { cb.checked = on; setLayerVisible(id, on); }
        });
        if (what === 'minerals') { /* make the mineral points readable: hide the dense geology text */ setLayerVisible('geology:labels', false); }
        toast(what === 'on' ? 'All ' + DATASETS[key].short + ' layers on' : what === 'off' ? 'All ' + DATASETS[key].short + ' layers off' : 'Showing only the main layer');
      }));
    });
    const ot = $('#outline-toggle', el);
    if (ot) ot.addEventListener('change', e => { outlineUnits = e.target.checked; groups['geology:geology_units'].setStyle(unitStyle); });
    const sel = $('#unit-scheme', el);
    if (sel) {
      const renderKey = () => {
        const key = $('#scheme-key', el);
        if (!key) return;
        if (unitScheme === 'fill') { key.innerHTML = ''; return; }
        const n = {}; let undated = 0;
        data['geology:geology_units'].features.forEach(f => { const c = schemeColour(f.properties); if (c === UNDATED) undated++; else { n[c] = (n[c] || 0) + 1; } });
        let k = '';
        Object.entries(SCHEME_COLOURS[unitScheme]).forEach(([name, col]) => { if (n[col]) k += '<div class="legend-row"><span class="sw" style="background:' + col + '"></span><span class="desc">' + esc(name) + '</span><span class="n">' + fmt(n[col]) + ' pol.</span></div>'; });
        if (undated) k += '<div class="legend-row"><span class="sw" style="background:' + UNDATED + '"></span><span class="desc">no age in the printed legend</span><span class="n">' + fmt(undated) + ' pol.</span></div>';
        key.innerHTML = k;
      };
      sel.addEventListener('change', () => { unitScheme = sel.value; groups['geology:geology_units'].setStyle(unitStyle); renderKey(); toast('Units coloured by ' + SCHEME_TITLES[unitScheme]); });
      renderKey();
    }
  }

  // ------------------------------------------------------------------ legend panel
  function renderLegendPanel() {
    const el = $('[data-panel="legend"]');
    let h = '<input class="legend-search" id="legend-q" type="search" placeholder="Filter legends (code, mineral, unit)…">';
    if (metas.geology) {
      const n = {}; data['geology:geology_units'].features.forEach(f => { const c = f.properties.code; n[c] = (n[c] || 0) + 1; });
      h += '<h3>Geological Map (2011) – rock units</h3><p class="muted" style="margin:2px 0 6px">From the EXPLANATIONS panel of the PDF (legend.csv). Tap a row to highlight those polygons.</p>' +
        '<div id="legend-rows" class="legend-list">';
      metas.geology.legend.forEach((e, i) => {
        const age = e.age_print || e.series || e.period_prt || '';
        const ageTxt = age ? esc(age) + (e.era && e.era !== age ? ' · ' + esc(e.era) : '') + (e.age_ma_max ? ' · ' + esc(e.age_ma_min) + '–' + esc(e.age_ma_max) + ' Ma' : '') : 'no age printed';
        h += '<div class="legend-row" data-code="' + esc(e.code) + '" data-i="' + i + '"><span class="sw" style="background:' + esc(e.fill) + '"></span>' +
          '<span class="code">' + esc(e.code) + '</span><span class="desc">' + esc(e.description) + (e.formation ? ' <i>(' + esc(e.formation) + ')</i>' : '') +
          '<br><span class="age">' + ageTxt + '</span></span>' +
          '<span class="n">' + (n[e.code] ? fmt(n[e.code]) + ' pol.' : '<span class="pill warn">0</span>') + '</span></div>';
      });
      h += '</div>';
      // units whose code is not in the printed legend
      const legendCodes = new Set(metas.geology.legend.map(e => e.code));
      const missing = {};
      data['geology:geology_units'].features.forEach(f => { const p = f.properties; if (!legendCodes.has(p.code)) { const k = p.code || '(none)'; missing[k] = missing[k] || { n: 0, unit: p.unit, fill: p.fill }; missing[k].n++; } });
      const mk = Object.keys(missing);
      if (mk.length) {
        h += '<h3>Drawn on the 2011 map but missing from its printed legend</h3><div class="legend-list">';
        mk.forEach(k => { const m = missing[k]; h += '<div class="legend-row" data-code="' + esc(k === '(none)' ? '' : k) + '"><span class="sw" style="background:' + esc(m.fill) + '"></span><span class="code">' + esc(k) + '</span><span class="desc">' + esc(m.unit) + '</span><span class="n">' + fmt(m.n) + ' pol.</span></div>'; });
        h += '</div>';
      }
    }
    if (metas.minerals) {
      const locs = data['minerals:mineral_localities'].features;
      const nMin = {};
      locs.forEach(f => { const seen = new Set(); String(f.properties.minerals || '').split(' | ').forEach(m => { const k = m.split(' (')[0].trim(); if (k && !seen.has(k)) { seen.add(k); nMin[k] = (nMin[k] || 0) + 1; } }); });
      h += '<h3>Mineral Resources Map (2023) – find a locality</h3>' +
        '<input class="legend-search" id="loc-q" type="search" placeholder="Number (e.g. B 12) or locality name…"><div id="loc-results" class="legend-list"></div>';
      h += '<h3>Mineral Resources Map (2023) – legend symbols</h3><p class="muted" style="margin:2px 0 6px">The 67 legend entries (mineral_legend.csv) with their symbol cut from the PDF, the codes the table uses for them and the number of numbered localities listing that mineral. Tap a row to highlight those localities.</p>' +
        '<div class="legend-list" id="mineral-legend-rows">';
      metas.minerals.legend.forEach(e => {
        const img = e.symbol_png ? '<img class="symimg" src="' + esc(DATASETS.minerals.dataDir + e.symbol_png) + '" alt="">' : '<span class="sw"></span>';
        const nm = e.mineral;
        h += '<div class="legend-row mineral" data-mineral="' + esc(nm) + '">' + img +
          '<span class="code">' + esc(e.table_codes_mapped_here || (e.code_printed_in_legend || '')) + '</span><span class="desc">' + esc(nm) + '</span>' +
          '<span class="n">' + (nMin[nm] ? fmt(nMin[nm]) + ' loc.' : '<span class="pill warn">0</span>') + '</span></div>';
      });
      h += '</div>';
      const unknown = (metas.minerals.codes || []).filter(c => c.confidence === 'unknown' && Number(c.uses_in_table) > 0);
      if (unknown.length) {
        h += '<h3>Table codes that could not be resolved</h3><p class="muted">' + unknown.map(c => '<code>' + esc(c.code) + '</code> (' + esc(c.uses_in_table) + ')').join(', ') + '</p>';
      }
    }
    el.innerHTML = h;
    $$('.legend-row:not(.mineral)', el).forEach(row => row.addEventListener('click', () => {
      const code = row.dataset.code;
      const same = highlighted === code;
      $$('.legend-row:not(.mineral)', el).forEach(r => r.classList.remove('sel'));
      highlighted = same ? null : code;
      if (!same) row.classList.add('sel');
      groups['geology:geology_units'].setStyle(unitStyle);
      if (!same) toast('Highlighting ' + (code || 'uncoded') + ' polygons – tap again to clear');
    }));
    $$('.legend-row.mineral', el).forEach(row => row.addEventListener('click', () => {
      const m = row.dataset.mineral;
      const same = highlightMineral === m;
      $$('.legend-row.mineral', el).forEach(r => r.classList.remove('sel'));
      highlightMineral = same ? null : m;
      if (!same) row.classList.add('sel');
      const g = groups['minerals:mineral_localities'];
      g.eachLayer(l => l.setStyle(localityStyle(l.feature.properties)));
      if (!same) { setLayerVisible('minerals:mineral_localities', true); toast('Highlighting localities with ' + m + ' – tap again to clear'); }
    }));
    const lq = $('#loc-q', el);
    if (lq) {
      const res = $('#loc-results', el);
      lq.addEventListener('input', () => {
        const hits = findLocalities(lq.value);
        res.innerHTML = hits.slice(0, 25).map((f, i) => { const p = f.properties; return '<div class="legend-row loc" data-i="' + i + '"><span class="sw" style="background:' + esc(localityColour(p)) + '"></span>' +
          '<span class="code">' + esc(p.zone + ' ' + p.number) + '</span><span class="desc">' + esc(p.locality || '(not in table)') + '<br><span class="muted">' + esc(p.minerals || '') + '</span></span></div>'; }).join('') +
          (hits.length > 25 ? '<p class="muted">… ' + (hits.length - 25) + ' more – refine the search</p>' : (lq.value.trim() && !hits.length ? '<p class="muted">no locality matches</p>' : ''));
        $$('.legend-row.loc', res).forEach(row => row.addEventListener('click', () => {
          const f = hits[+row.dataset.i], c = f.geometry.coordinates;
          setLayerVisible('minerals:mineral_localities', true);
          map.setView([c[1], c[0]], Math.max(map.getZoom(), 8.5), { animate: true });
          showFeature(byId['minerals:mineral_localities'], f, L.latLng(c[1], c[0]));
        }));
      });
    }
    $('#legend-q', el).addEventListener('input', e => {
      const q = e.target.value.trim().toLowerCase();
      $$('.legend-row', el).forEach(r => { r.style.display = !q || r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    });
  }

  function findLocalities(q) {
    const fc = data['minerals:mineral_localities'];
    q = String(q || '').trim().toLowerCase();
    if (!fc || !q) return [];
    const num = /^([a-g])\s*(\d+)$/.exec(q);
    return fc.features.filter(f => {
      const p = f.properties;
      if (num) return p.zone.toLowerCase() === num[1] && String(p.number) === num[2];
      return (p.locality || '').toLowerCase().includes(q) || (p.minerals || '').toLowerCase().includes(q) || p.zone_num.toLowerCase() === q.replace(/\s+/g, '');
    });
  }

  // ------------------------------------------------------------------ compare / about panels
  function renderComparePanel() {
    let h = '';
    if (metas.geology) {
      const meta = metas.geology, s = meta.pdf_stats, total = meta.layers.reduce((a, l) => a + l.count, 0);
      h += '<h3>Geological Map of Nigeria (2011)</h3>' +
        '<div class="verdict"><b>Is the PDF a GeoPDF?</b> No. It is a layered vector PDF exported by ArcMap 9.2 (2011) with ' +
        'no geospatial dictionaries, no projection and no attribute tables. The georeference used here was fitted to the drawn graticule ' +
        '(' + meta.georef.points_per_degree.toFixed(2) + ' pt/°, residual ≈ ' + Math.round(meta.georef.max_residual_deg * 111000) + ' m, scale ≈ 1:' + fmt(meta.georef.scale) + ').</div>' +
        '<div class="verdict"><b>Could the shapefiles be extracted?</b> Geometry: yes, completely (swipe to check the registration). ' +
        'Attributes: rebuilt from layer names, the legend and map labels – see the caveats under “About”.</div>' +
        '<div class="stat-grid">' +
        '<div class="stat"><b>' + fmt(s.n_paths) + '</b><span>vector paths in the PDF</span></div>' +
        '<div class="stat"><b>' + fmt(s.n_layers) + '</b><span>PDF layers (optional content groups)</span></div>' +
        '<div class="stat"><b>' + fmt(s.n_words) + '</b><span>text strings (from ' + fmt(s.n_text_runs) + ' one-character runs)</span></div>' +
        '<div class="stat"><b>' + fmt(total) + '</b><span>features in the 17 extracted layers</span></div></div>' +
        '<details><summary>PDF primitives → extracted features</summary><table class="cmp"><tr><th>Output layer</th><th class="num">In PDF</th><th class="num">Extracted</th></tr>';
      s.compare.forEach(r => {
        h += '<tr><td><div class="out">' + esc(r.output) + '</div><div class="src">' + esc(r.sources) + (r.note ? ' · ' + esc(r.note) : '') + '</div></td>' +
          '<td class="num">' + (r.pdf_primitives ? fmt(r.pdf_primitives) : '–') + '<div class="src">' + esc(r.pdf_kind) + '</div></td>' +
          '<td class="num">' + esc(r.features == null ? '–' : (typeof r.features === 'number' ? fmt(r.features) : r.features)) + '</td></tr>';
      });
      h += '</table></details><details><summary>All ' + s.layers.length + ' PDF layers (paths / text)</summary><table class="cmp"><tr><th>PDF layer</th><th class="num">fills</th><th class="num">strokes</th><th class="num">text</th></tr>';
      s.layers.forEach(l => { h += '<tr><td>' + esc(l.layer) + '</td><td class="num">' + fmt(l.fills) + '</td><td class="num">' + fmt(l.strokes) + '</td><td class="num">' + fmt(l.text) + '</td></tr>'; });
      h += '</table></details>';
    }
    if (metas.minerals) {
      const m = metas.minerals, q = m.qa || {}, t = q.table || {}, nl = q.number_labels || {}, rs = q.raster_symbols || {}, cc = q.capital_check_km || {};
      const total = m.layers.reduce((a, l) => a + l.count, 0);
      h += '<h3>Mineral Resources Map of Nigeria (2023)</h3>' +
        '<div class="verdict"><b>Is the PDF a GeoPDF?</b> Yes. ArcMap 10.2.2 wrote an ISO-32000 viewport (/VP with /Measure, 4 corner coordinates, GCS “' + esc(m.georef.gcs) + '”), ' +
        'so the map frame is placed directly from the file (' + m.georef.points_per_degree.toFixed(2) + ' pt/°). Parallels agree with whole degrees to ' + (m.georef.parallel_max_residual_deg * 1).toFixed(4) + '°; ' +
        'the printed <b>meridian labels sit ' + Math.abs(m.georef.meridian_label_offset_deg).toFixed(3) + '° (≈' + Math.round(Math.abs(m.georef.meridian_label_offset_deg) * 110) + ' km) west</b> of the GeoPDF values – the capital-city check (rms ' + esc(cc.VP_affine ? cc.VP_affine.rms_km : '–') + ' km vs ' + esc(cc.if_meridian_labels_were_right ? cc.if_meridian_labels_were_right.rms_km : '–') + ' km) shows the GeoPDF is right.</div>' +
        '<div class="verdict"><b>Could the shapefiles be extracted?</b> Vector layers: yes. The mineral symbols and the geology background are a 75-dpi raster inside the PDF, so localities are keyed through the printed numbers and the EXPLANATIONS table; ' +
        'symbols were detected in the raster and matched to the numbers by colour/size/fill.</div>' +
        '<div class="stat-grid">' +
        '<div class="stat"><b>' + fmt(t.entries) + '</b><span>EXPLANATIONS table rows (zones A–G)</span></div>' +
        '<div class="stat"><b>' + fmt(nl.labels) + '</b><span>numbers printed on the map · ' + fmt(nl.matched) + ' joined to the table</span></div>' +
        '<div class="stat"><b>' + fmt(rs.labels_snapped_to_colour_consistent_symbol_within_25pt) + '</b><span>numbers placed on their raster symbol (of ' + fmt(rs.labels_whose_minerals_have_a_legend_symbol) + ' with a legend symbol)</span></div>' +
        '<div class="stat"><b>' + fmt(rs.blobs) + '</b><span>symbol blobs detected · ' + fmt(rs.symbols_without_any_label_within_14pt) + ' without a number</span></div>' +
        '<div class="stat"><b>' + fmt(total) + '</b><span>features in the ' + m.layers.length + ' extracted layers</span></div>' +
        '<div class="stat"><b>' + (cc.VP_affine ? cc.VP_affine.mean_dx_km + ' / ' + cc.VP_affine.mean_dy_km : '–') + '</b><span>km mean E / N offset of 33 capitals vs reference</span></div></div>';
      if (nl.unmatched && nl.unmatched.length) h += '<p class="muted">Numbers on the map without a table row: ' + nl.unmatched.map(u => esc(u[0] + u[1])).join(', ') + ' (F110, G53, G86 are missing from the printed list; D256 is a misprint). ' + fmt(nl.table_entries_without_label) + ' table rows have no number on the map.</p>';
      if (nl.rezoned_by_numbering_sequence && nl.rezoned_by_numbering_sequence.length) h += '<details><summary>Numbers re-zoned by numbering sequence (' + nl.rezoned_by_numbering_sequence.length + ')</summary><p class="muted">' + nl.rezoned_by_numbering_sequence.map(r => esc(r[1] + ': ' + r[0])).join('<br>') + '</p></details>';
      h += '<details><summary>Extracted layers (2023)</summary><table class="cmp"><tr><th>Layer</th><th class="num">Features</th><th>Geometry</th></tr>';
      m.layers.forEach(l => { h += '<tr><td>' + esc(l.id) + '</td><td class="num">' + fmt(l.count) + '</td><td>' + esc(l.geometry) + '</td></tr>'; });
      h += '</table></details>';
    }
    h += statisticsHtml();
    $('[data-panel="compare"]').innerHTML = h;
  }

  // attribute statistics computed from the loaded layers (area by era / rock class, localities by host geology)
  function statisticsHtml() {
    let h = '';
    const bar = (v, max, col) => '<span class="bar" style="width:' + Math.max(2, Math.round(100 * v / max)) + '%;background:' + col + '"></span>';
    if (data['geology:geology_units']) {
      const live = data['geology:geology_units'].features.map(f => f.properties).filter(p => !p.dup_of);
      const total = live.reduce((a, p) => a + (p.area_km2 || 0), 0);
      const agg = key => { const m = {}; live.forEach(p => { const k = p[key] || 'no age in the printed legend'; m[k] = m[k] || { n: 0, a: 0 }; m[k].n++; m[k].a += p.area_km2 || 0; }); return Object.entries(m).sort((x, y) => y[1].a - x[1].a); };
      h += '<h3>Attribute statistics – 2011 rock units</h3><p class="muted">' + fmt(live.length) + ' polygons (16 duplicates excluded), ' + fmt(Math.round(total)) + ' km² mapped; ages read from the printed legend brackets.</p>';
      [['era', 'Area by era'], ['rock_cls', 'Area by rock class'], ['period', 'Area by period (ICS)']].forEach(([key, title]) => {
        const rows = agg(key), max = rows[0][1].a;
        h += '<details' + (key === 'era' ? ' open' : '') + '><summary>' + title + '</summary><table class="cmp stats">';
        rows.forEach(([k, v]) => { const col = (SCHEME_COLOURS[key] && SCHEME_COLOURS[key][k]) || UNDATED; h += '<tr><td><div class="out">' + esc(k === '' ? '(none)' : k) + '</div><div class="barwrap">' + bar(v.a, max, col) + '</div></td><td class="num">' + fmt(Math.round(v.a)) + ' km²<div class="src">' + (100 * v.a / total).toFixed(1) + '% · ' + fmt(v.n) + ' pol.</div></td></tr>'; });
        h += '</table></details>';
      });
    }
    if (data['minerals:mineral_localities']) {
      const locs = data['minerals:mineral_localities'].features.map(f => f.properties);
      const grp = {}, host = {}, unit = {};
      locs.forEach(p => {
        String(p.groups || '').split(' | ').forEach(g => { if (g) grp[g] = (grp[g] || 0) + 1; });
        const e = p.geo_era || 'outside the 2011 mapped units'; host[e] = (host[e] || 0) + 1;
        if (p.geo_code) { const u = unit[p.geo_code] = unit[p.geo_code] || { n: 0, name: p.geo_unit, era: p.geo_era }; u.n++; }
      });
      const gr = Object.entries(grp).sort((a, b) => b[1] - a[1]), hr = Object.entries(host).sort((a, b) => b[1] - a[1]), ur = Object.entries(unit).sort((a, b) => b[1].n - a[1].n).slice(0, 12);
      h += '<h3>Attribute statistics – 2023 mineral localities</h3><p class="muted">' + fmt(locs.length) + ' numbered localities; commodity groups from the legend minerals, host rock from the 2011 map (±10 km).</p>';
      h += '<details open><summary>Localities by commodity group</summary><table class="cmp stats">';
      gr.forEach(([k, v]) => { h += '<tr><td><div class="out">' + esc(k) + '</div><div class="barwrap">' + bar(v, gr[0][1], '#b45309') + '</div></td><td class="num">' + fmt(v) + '</td></tr>'; });
      h += '</table></details><details><summary>Localities by host era (2011 geology)</summary><table class="cmp stats">';
      hr.forEach(([k, v]) => { h += '<tr><td><div class="out">' + esc(k) + '</div><div class="barwrap">' + bar(v, hr[0][1], SCHEME_COLOURS.era[k] || UNDATED) + '</div></td><td class="num">' + fmt(v) + '</td></tr>'; });
      h += '</table></details><details><summary>Most frequent host units (top 12)</summary><table class="cmp stats">';
      ur.forEach(([k, v]) => { h += '<tr><td><div class="out">' + esc(k) + ' – ' + esc(v.name) + '</div><div class="src">' + esc(v.era || '') + '</div></td><td class="num">' + fmt(v.n) + '</td></tr>'; });
      h += '</table></details><p class="muted">Full tables: <code>shapefiles/summary_area_by_unit.csv</code>, <code>summary_area_by_age.csv</code>, <code>shapefiles_minerals/summary_localities_by_host_geology.csv</code>, <code>summary_localities_by_group.csv</code> (from <code>summaries.py</code>).</p>';
    }
    return h;
  }

  function renderAboutPanel() {
    const g = metas.geology, m = metas.minerals;
    $('[data-panel="about"]').innerHTML =
      '<h3>How to compare</h3>' +
      '<p><b>Swipe</b> – left of the divider is an original PDF (rendered at up to 330 dpi), right are the extracted layers drawn with a matching symbology. Drag the handle. ' +
      'Choose which PDF is on the left under <b>Layers → PDF side shows</b> (or the chip above the map).<br>' +
      '<b>Overlay</b> – extracted layers drawn over the PDF; use the slider to fade them in and out.<br>' +
      '<b>PDF only / Extracted</b> – one side at a time. Tap any extracted feature for its attributes; the geology unit of the 2011 map under the tapped point is shown as well.</p>' +
      '<h3>Two maps, one grid</h3>' +
      '<p>Both maps are placed on the same longitude/latitude grid (EPSG:4326), so the mineral localities of the 2023 map can be read against the 2011 geology. Every layer of either map has its own switch under <b>Layers</b>.</p>' +
      (g ? '<p><b>2011:</b> <code>' + esc(g.pdf) + '</code> – an affine fit to its graticule; 17 shapefiles in <code>shapefiles/</code> from <code>extract_shapefiles.py</code>.</p>' : '') +
      (m ? '<p><b>2023:</b> <code>' + esc(m.pdf) + '</code> – a GeoPDF, placed with its own /VP viewport; ' + m.layers.length + ' shapefiles in <code>shapefiles_minerals/</code> from <code>extract_mineral_map.py</code>. ' +
        'A locality point sits on its raster symbol when the symbol was matched (solid outline), otherwise on the printed number (dashed outline); the printed numbers themselves are drawn as text. Point colour = colour of the printed symbol for the first mineral code.</p>' : '') +
      '<h3>Known limits</h3>' +
      '<p>• 2011: no attribute tables in the PDF; unit codes come from legend colours + layer names. Datum not stated (WGS 84 assumed). Dashed symbols were re-assembled from fragments. State capitals are label centres. Source topology inherited.<br>' +
      '• 2023: the GeoPDF declares an “assumed” geographic CRS; its printed meridian labels are 0.17° off the embedded georeference (the georeference is used). Mineral names come from the compiler’s codes – 19 codes are unresolved; 4 numbers of the printed list are missing (F 110, G 53, G 86, G 111) and D 256 is a misprint. Unnumbered symbols only carry candidate minerals. The geology background of the 2023 map is raster only.</p>' +
      '<h3>Files</h3><p><code>shapefiles/</code>, <code>shapefiles_minerals/</code>, the two <code>georeferencing.json</code>, <code>shapefiles_minerals/qa_report.json</code>, <code>README.md</code>. ' +
      'Viewer data built ' + esc((m || g).generated) + '.</p>';
  }

  // ------------------------------------------------------------------ bookmarks, toast
  function initChips() {
    const V = {
      face: () => metas[pdfSource].map_face_bounds,
      jos: () => [[9.45, 8.3], [10.25, 9.35]],
      delta: () => [[4.2, 5.2], [5.8, 7.7]],
      chad: () => [[12.5, 12.8], [13.9, 14.7]],
      sokoto: () => [[12.3, 4.5], [13.5, 6.1]],
      legend: () => [[metas.geology.tiles.page_bounds[0][0], 14.45], [metas.geology.tiles.page_bounds[1][0], metas.geology.tiles.page_bounds[1][1]]],
      mintable: () => metas.minerals.table_bounds,
    };
    const chips = $('#chips');
    if (metas.minerals) {
      const b = document.createElement('button'); b.dataset.view = 'mintable'; b.textContent = 'Mineral table (PDF)'; chips.appendChild(b);
      const c = document.createElement('button'); c.id = 'chip-pdf'; c.className = 'chip-pdf'; c.textContent = 'PDF: ' + DATASETS[pdfSource].short + ' ⇄';
      chips.insertBefore(c, chips.firstChild);
      c.addEventListener('click', () => setPdfSource(pdfSource === 'geology' ? 'minerals' : 'geology'));
    }
    if (!metas.geology) $('button[data-view="legend"]', chips).remove();
    $$('#chips button[data-view]').forEach(b => b.addEventListener('click', () => {
      const k = b.dataset.view;
      if (k === 'legend' && pdfSource !== 'geology') setPdfSource('geology', true);
      if (k === 'mintable' && pdfSource !== 'minerals') setPdfSource('minerals', true);
      map.fitBounds(L.latLngBounds(V[k]()), { padding: [8, 8], animate: true });
      if (k === 'legend' || k === 'mintable') {
        if (mode !== 'pdf' && mode !== 'overlay') { setMode('pdf'); toast(k === 'legend' ? 'Showing the PDF only – the legend panel has no vector counterpart. legend.csv is under Legend.' : 'Showing the 2023 PDF – the EXPLANATIONS table is in explanations_table.csv (tap a locality for its row).'); }
      }
    }));
  }
  let toastTimer;
  function toast(msg) {
    let t = $('#toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t);
      Object.assign(t.style, { position: 'fixed', left: '50%', bottom: 'calc(96px + env(safe-area-inset-bottom, 0px))', transform: 'translateX(-50%)', background: 'rgba(27,42,65,.95)', color: '#fff', padding: '9px 14px', borderRadius: '10px', fontSize: '13px', zIndex: 1300, maxWidth: '86vw', textAlign: 'center', boxShadow: '0 3px 10px rgba(0,0,0,.3)', transition: 'opacity .2s' }); }
    t.textContent = msg; t.style.opacity = 1;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.style.opacity = 0; }, 3200);
  }

  // ------------------------------------------------------------------ boot
  async function fetchJSON(url, optional) {
    const r = await fetch(url);
    if (!r.ok) { if (optional) return null; throw new Error(url + ' → HTTP ' + r.status); }
    return r.json();
  }
  async function boot() {
    const txt = $('#loading-text');
    try {
      const [g, m] = await Promise.all([fetchJSON(DATASETS.geology.metaUrl, true), fetchJSON(DATASETS.minerals.metaUrl, true)]);
      if (g) metas.geology = g;
      if (m) metas.minerals = m;
      if (!g && !m) throw new Error('no viewer data – run python viewer/build_data.py');
      initMap(); initSwipe(); initSheet(); initChips();
      $$('#mode button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
      $('#opacity-range').addEventListener('input', e => { $('#opacity-val').textContent = e.target.value + '%'; setVecOpacity(e.target.value / 100); });
      const toLoad = LAYERS.filter(d => metas[d.ds] && d.file);
      let done = 0;
      await Promise.all(toLoad.map(async def => {
        data[def.id] = await fetchJSON(DATASETS[def.ds].dataDir + def.file + '.geojson');
        done++; txt.textContent = 'Loading extracted layers… ' + done + '/' + toLoad.length;
      }));
      buildGroups();
      renderLayersPanel(); renderLegendPanel(); renderComparePanel(); renderAboutPanel();
      setMode('swipe');
      $('#loading').classList.add('hidden');
      toast(metas.minerals ? 'Both maps loaded · Layers ▸ toggle any layer, choose the PDF side' : 'Drag the handle to compare · tap features for attributes');
      window.__viewer = { map, groups, data, metas, setMode, showFeature, unitsAt, setLayerVisible, setPdfSource, LAYERS, byId, findLocalities };  // for debugging / tests
    } catch (err) {
      txt.textContent = 'Failed to load: ' + err.message;
      console.error(err);
    }
  }
  boot();
})();
