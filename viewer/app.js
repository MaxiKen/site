/* Nigeria geological map: original PDF (tiles) vs extracted shapefiles (GeoJSON) – mobile-first viewer */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => (n == null ? '–' : Number(n).toLocaleString('en'));

  // ------------------------------------------------------------------ layer catalogue
  // Styles mimic the symbology of the PDF so the two sides can be compared visually.
  const LAYERS = [
    { id: 'geology_units', title: 'Geology units', kind: 'polygon', on: true,
      swatch: 'linear-gradient(90deg,#f08080 0 33%,#f5ff9e 33% 66%,#7adeb0 66%)',
      style: f => unitStyle(f),
      name: p => (p.code ? p.code + ' – ' : '') + (p.unit || '') },
    { id: 'major_rivers_poly', title: 'Major rivers & Lake Chad (areas)', kind: 'polygon', on: true, swatch: '#a9d2f6',
      style: () => ({ fillColor: '#a9d2f6', fillOpacity: 1, stroke: false }), name: () => 'Major river / lake' },
    { id: 'geological_boundaries', title: 'Geological boundaries', kind: 'line', on: true, swatch: '#222',
      style: f => {
        const c = f.properties.class;
        return { color: '#222', weight: 0.9, opacity: 1,
          dashArray: c === 'approximate' ? '6 4' : c === 'inferred' ? '2 4' : c === 'transitional' ? '9 3 2 3' : null };
      }, name: p => 'Boundary (' + p.class + ')' },
    { id: 'younger_granite_outlines', title: 'Younger Granite outlines', kind: 'line', on: true, swatch: '#000',
      style: () => ({ color: '#000', weight: 1.1 }), name: () => 'Younger Granite outline' },
    { id: 'faults', title: 'Faults / fractures', kind: 'line', on: true, swatch: '#d7191c',
      style: f => ({ color: '#d7191c', weight: 1.3, dashArray: /inferred/.test(f.properties.class) ? '5 4' : null }),
      name: p => p.class },
    { id: 'fold_axes', title: 'Fold axes', kind: 'line', on: true, swatch: '#7b1fa2',
      style: () => ({ color: '#7b1fa2', weight: 1.5 }), name: p => p.class + ' axis' },
    { id: 'ridges', title: 'Ridges', kind: 'line', on: true, swatch: '#8d6e63',
      style: () => ({ color: '#8d6e63', weight: 1.8 }), name: () => 'Ridge' },
    { id: 'rivers', title: 'Rivers', kind: 'line', on: true, swatch: '#3b82f6',
      style: () => ({ color: '#3b82f6', weight: 0.9 }), name: () => 'River' },
    { id: 'major_rivers_outline', title: 'Major river outlines', kind: 'line', on: true, swatch: '#3b82f6',
      style: () => ({ color: '#3b82f6', weight: 0.8 }), name: () => 'Major river outline' },
    { id: 'state_boundaries', title: 'State boundaries', kind: 'line', on: true, swatch: '#8a8a8a',
      style: () => ({ color: '#8a8a8a', weight: 2.6, opacity: 0.9, dashArray: '10 4 2 4' }), name: () => 'State boundary' },
    { id: 'roads', title: 'Roads (centrelines)', kind: 'line', on: true, swatch: '#555',
      style: () => ({ color: '#555', weight: 1.4 }), name: () => 'Road' },
    { id: 'railway', title: 'Railway', kind: 'line', on: true, swatch: '#000',
      style: () => ({ color: '#000', weight: 1.6, dashArray: '6 3' }), name: () => 'Railway' },
    { id: 'graticule', title: 'Fitted graticule (QA)', kind: 'line', on: false, swatch: '#999',
      style: () => ({ color: '#999', weight: 0.7 }), name: p => p.axis + ' ' + p.value + '°' },
    { id: 'towns', title: 'Towns', kind: 'point', on: true, swatch: '#000',
      point: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: '#000', weight: 1, fillColor: '#000', fillOpacity: 1 }),
      name: p => p.name || '(unnamed town)' },
    { id: 'volcanic_plugs', title: 'Volcanic plugs & pipes', kind: 'point', on: true, swatch: '#000',
      point: (f, ll) => L.circleMarker(ll, { radius: 4, color: '#000', weight: 1.3, fill: false }),
      name: () => 'Volcanic plug / pipe' },
    { id: 'state_capitals', title: 'State capitals (approx.)', kind: 'point', on: true, swatch: '#e53935',
      point: (f, ll) => L.circleMarker(ll, { radius: 5.5, color: '#fff', weight: 1.5, fillColor: '#e53935', fillOpacity: 1 }),
      name: p => p.name },
    { id: 'labels', title: 'Map text (unit codes, names)', kind: 'labels', on: true, swatch: '#fff',
      name: p => p.text },
  ];
  const byId = {};
  LAYERS.forEach(d => { byId[d.id] = d; });

  // ------------------------------------------------------------------ state
  let meta, map, pdfLayer, labelLayer;
  let mode = 'swipe', swipeFrac = 0.5, highlighted = null, outlineUnits = false;
  const data = {}, groups = {}, visible = {};
  let unitsIndex = [];     // [{bbox:[minx,miny,maxx,maxy], feature}]

  function unitStyle(f) {
    const p = f.properties;
    const dim = highlighted && p.code !== highlighted;
    return { fillColor: p.fill || '#cccccc', fillOpacity: dim ? 0.10 : 1,
      stroke: outlineUnits, color: '#333', weight: 0.6, opacity: 1 };
  }

  // ------------------------------------------------------------------ canvas label layer
  const LabelLayer = L.Layer.extend({
    options: { pane: 'labels' },
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
      const ptPerPx = degPerPx / meta.georef.a;          // PDF points per screen pixel
      const bounds = m.getBounds().pad(0.15);
      ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left'; ctx.lineJoin = 'round';
      for (const f of this._features) {
        const p = f.properties, c = f.geometry.coordinates;
        if (c[1] < bounds.getSouth() || c[1] > bounds.getNorth() || c[0] < bounds.getWest() || c[0] > bounds.getEast()) continue;
        const natural = p.size_pt / ptPerPx;             // text height as printed, in px
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
        ctx.fillStyle = p.kind === 'water name' ? '#1d4ed8' : p.kind === 'state capital' ? '#7f1d1d' : '#111';
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
  function initMap() {
    const page = meta.tiles.page_bounds;
    map = L.map('map', {
      crs: L.CRS.EPSG4326,
      renderer: L.canvas({ tolerance: 8, padding: 0.3 }),
      zoomControl: false, attributionControl: false,
      zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,
      minZoom: 4, maxZoom: 11,
      maxBounds: L.latLngBounds([[page[0][0] - 2, page[0][1] - 2], [page[1][0] + 2, page[1][1] + 2]]),
      maxBoundsViscosity: 0.6,
    });
    map.createPane('pdf').style.zIndex = 250;
    map.createPane('labels').style.zIndex = 450;
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft', maxWidth: 120 }).addTo(map);
    L.control.attribution({ prefix: false, position: 'bottomleft' })
      .addAttribution('NGSA Geological Map of Nigeria 1:2M (PDF) · extraction: extract_shapefiles.py').addTo(map);

    pdfLayer = L.tileLayer('build/tiles/{z}/{x}/{y}.png', {
      pane: 'pdf', tileSize: 256, minZoom: 4, maxZoom: 11,
      minNativeZoom: meta.tiles.zmin, maxNativeZoom: meta.tiles.zmax,
      noWrap: true, bounds: L.latLngBounds(page), keepBuffer: 2, updateWhenIdle: true,
    }).addTo(map);

    map.fitBounds(L.latLngBounds(meta.map_face_bounds), { padding: [6, 6] });
    map.on('move resize', updateClip);
    map.on('click', () => { if ($('#sheet').classList.contains('open')) closeSheet(); });
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
      const fc = data[def.id];
      if (!fc) continue;
      if (def.kind === 'labels') {
        // the PDF draws halo text twice (two slightly offset copies): keep one
        const seen = new Set();
        const feats = fc.features.filter(f => {
          const c = f.geometry.coordinates, p = f.properties;
          const key = p.kind + '|' + p.text + '|' + Math.round(c[0] / 0.01) + '|' + Math.round(c[1] / 0.01);
          if (seen.has(key)) return false;
          seen.add(key); return true;
        });
        labelLayer = new LabelLayer(feats);
        groups[def.id] = labelLayer;
      } else {
        groups[def.id] = L.geoJSON(fc, {
          style: def.style,
          pointToLayer: def.point,
          bubblingMouseEvents: false,
          smoothFactor: 0.8,
          onEachFeature: (f, layer) => layer.on('click', e => showFeature(def, f, e.latlng)),
        });
      }
      visible[def.id] = def.on;
      if (def.on) groups[def.id].addTo(map);
    }
    // spatial index for "what unit is here?"
    unitsIndex = data.geology_units.features.map(f => {
      let minx = 180, miny = 90, maxx = -180, maxy = -90;
      eachRing(f.geometry, ring => ring.forEach(c => {
        if (c[0] < minx) minx = c[0]; if (c[0] > maxx) maxx = c[0];
        if (c[1] < miny) miny = c[1]; if (c[1] > maxy) maxy = c[1];
      }));
      return { bbox: [minx, miny, maxx, maxy], feature: f };
    });
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
    width_pt: 'line width (pt)', n_frag: 'fragments merged', len_km: 'length (km)', name_kind: 'name source',
    name_dist: 'label distance (pt)', size_pt: 'text size (pt)', stroke: 'stroke colour', 'class': 'class', text: 'text', kind: 'kind', font: 'font', angle: 'angle (°)' };
  const SKIP = { layer: 1 };

  function propsTable(p) {
    let h = '<table class="kv">';
    for (const k of Object.keys(p)) {
      if (SKIP[k]) continue;
      let v = p[k];
      if (v == null || v === '' || (k === 'dup_of' && !v)) continue;
      if (typeof v === 'number' && !Number.isInteger(v)) v = v.toLocaleString('en', { maximumFractionDigits: 2 });
      if (k === 'fill' || k === 'stroke') v = '<span class="pill" style="background:' + esc(v) + ';color:#000;border:1px solid #0003">' + esc(v) + '</span>';
      else v = esc(v);
      h += '<tr><th>' + esc(PRETTY[k] || k) + '</th><td>' + v + '</td></tr>';
    }
    return h + '</table>';
  }

  function featureCard(def, f) {
    const p = f.properties || {};
    const colour = def.id === 'geology_units' ? (p.fill || '#ccc') : (typeof def.swatch === 'string' && def.swatch[0] === '#' ? def.swatch : '#ddd');
    let flags = '';
    if (def.id === 'geology_units') {
      flags += '<span class="pill">code from ' + esc(p.code_src) + '</span>';
      if (p.lbl_code && p.leg_code && p.lbl_code !== p.leg_code) flags += '<span class="pill warn">map label says ' + esc(p.lbl_code) + '</span>';
      if (p.dup_of) flags += '<span class="pill warn">duplicate geometry (of #' + esc(p.dup_of) + ')</span>';
      if (!p.leg_code) flags += '<span class="pill warn">not in printed legend</span>';
    }
    if (def.id === 'state_capitals') flags += '<span class="pill warn">position ≈ label centre (±7–15 km)</span>';
    if (def.id === 'towns' && !p.name) flags += '<span class="pill warn">no label matched</span>';
    return '<div class="feature-head"><div class="sw" style="background:' + esc(colour) + '"></div><div>' +
      '<div class="name">' + esc(def.name(p)) + '</div><div class="sub">' + esc(def.title) + '</div></div></div>' +
      (flags ? '<p>' + flags + '</p>' : '') + propsTable(p);
  }

  function showFeature(def, f, latlng) {
    let h = featureCard(def, f);
    if (def.id !== 'geology_units' && latlng) {
      const under = unitsAt(latlng.lng, latlng.lat);
      if (under.length) {
        h += '<div class="under"><h3>Geology unit at this point</h3>' +
          under.map(u => featureCard(byId.geology_units, u)).join('<hr>') + '</div>';
      }
    } else if (latlng) {
      const under = unitsAt(latlng.lng, latlng.lat).filter(u => u !== f);
      if (under.length) {
        h += '<div class="under"><h3>Overlapping unit polygon' + (under.length > 1 ? 's' : '') + '</h3>' +
          under.map(u => featureCard(byId.geology_units, u)).join('<hr>') + '</div>';
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
    const counts = {}; meta.layers.forEach(l => { counts[l.id] = l.count; });
    let h = '<div class="row-actions"><button class="btn" id="all-on">All on</button><button class="btn" id="all-off">All off</button>' +
      '<button class="btn" id="units-only">Units only</button></div>';
    for (const def of LAYERS) {
      if (!groups[def.id]) continue;
      h += '<label class="layer-row"><span class="sw" style="background:' + def.swatch + '"></span>' +
        '<span class="lbl">' + esc(def.title) + '<br><span class="cnt">' + fmt(counts[def.id]) + ' features</span></span>' +
        '<span class="switch"><input type="checkbox" data-layer="' + def.id + '"' + (visible[def.id] ? ' checked' : '') + '><i></i></span></label>';
    }
    h += '<label class="layer-row"><span class="sw" style="background:#fff;border:1.5px solid #333"></span><span class="lbl">Outline unit polygons</span>' +
      '<span class="switch"><input type="checkbox" id="outline-toggle"><i></i></span></label>';
    const el = $('[data-panel="layers"]'); el.innerHTML = h;
    $$('input[data-layer]', el).forEach(cb => cb.addEventListener('change', () => setLayerVisible(cb.dataset.layer, cb.checked)));
    const setAll = pred => { $$('input[data-layer]', el).forEach(cb => { const on = pred(cb.dataset.layer); if (cb.checked !== on) { cb.checked = on; setLayerVisible(cb.dataset.layer, on); } }); };
    $('#all-on', el).addEventListener('click', () => setAll(() => true));
    $('#all-off', el).addEventListener('click', () => setAll(() => false));
    $('#units-only', el).addEventListener('click', () => setAll(id => id === 'geology_units'));
    $('#outline-toggle', el).addEventListener('change', e => { outlineUnits = e.target.checked; groups.geology_units.setStyle(unitStyle); });
  }

  // ------------------------------------------------------------------ legend panel
  function renderLegendPanel() {
    const n = {}; data.geology_units.features.forEach(f => { const c = f.properties.code; n[c] = (n[c] || 0) + 1; });
    const el = $('[data-panel="legend"]');
    let h = '<input class="legend-search" id="legend-q" type="search" placeholder="Filter legend (code or description)…">' +
      '<p class="muted" style="margin:2px 0 6px">From the EXPLANATIONS panel of the PDF (legend.csv). Tap a row to highlight those polygons.</p>' +
      '<div id="legend-rows">';
    meta.legend.forEach((e, i) => {
      h += '<div class="legend-row" data-code="' + esc(e.code) + '" data-i="' + i + '"><span class="sw" style="background:' + esc(e.fill) + '"></span>' +
        '<span class="code">' + esc(e.code) + '</span><span class="desc">' + esc(e.description) + '</span>' +
        '<span class="n">' + (n[e.code] ? fmt(n[e.code]) + ' pol.' : '<span class="pill warn">0</span>') + '</span></div>';
    });
    h += '</div>';
    // units whose code is not in the printed legend
    const legendCodes = new Set(meta.legend.map(e => e.code));
    const missing = {};
    data.geology_units.features.forEach(f => { const p = f.properties; if (!legendCodes.has(p.code)) { const k = p.code || '(none)'; missing[k] = missing[k] || { n: 0, unit: p.unit, fill: p.fill }; missing[k].n++; } });
    const mk = Object.keys(missing);
    if (mk.length) {
      h += '<h3>Drawn on the map but missing from the printed legend</h3>';
      mk.forEach(k => { const m = missing[k]; h += '<div class="legend-row" data-code="' + esc(k === '(none)' ? '' : k) + '"><span class="sw" style="background:' + esc(m.fill) + '"></span><span class="code">' + esc(k) + '</span><span class="desc">' + esc(m.unit) + '</span><span class="n">' + fmt(m.n) + ' pol.</span></div>'; });
    }
    el.innerHTML = h;
    $$('.legend-row', el).forEach(row => row.addEventListener('click', () => {
      const code = row.dataset.code;
      const same = highlighted === code;
      $$('.legend-row', el).forEach(r => r.classList.remove('sel'));
      highlighted = same ? null : code;
      if (!same) row.classList.add('sel');
      groups.geology_units.setStyle(unitStyle);
      if (!same) toast('Highlighting ' + (code || 'uncoded') + ' polygons – tap again to clear');
    }));
    $('#legend-q', el).addEventListener('input', e => {
      const q = e.target.value.trim().toLowerCase();
      $$('#legend-rows .legend-row', el).forEach(r => { r.style.display = !q || r.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    });
  }

  // ------------------------------------------------------------------ compare / about panels
  function renderComparePanel() {
    const s = meta.pdf_stats, total = meta.layers.reduce((a, l) => a + l.count, 0);
    let h = '<div class="verdict"><b>Is the PDF a GeoPDF?</b> No. It is a layered vector PDF exported by ArcMap 9.2 (2011) with ' +
      'no geospatial dictionaries, no projection and no attribute tables. The georeference used here was fitted to the drawn graticule ' +
      '(' + meta.georef.points_per_degree.toFixed(2) + ' pt/°, residual ≈ ' + Math.round(meta.georef.max_residual_deg * 111000) + ' m, scale ≈ 1:' + fmt(meta.georef.scale) + ').</div>' +
      '<div class="verdict"><b>Could the shapefiles be extracted?</b> Geometry: yes, completely (swipe to check the registration). ' +
      'Attributes: rebuilt from layer names, the legend and map labels – see the caveats under “About”.</div>' +
      '<div class="stat-grid">' +
      '<div class="stat"><b>' + fmt(s.n_paths) + '</b><span>vector paths in the PDF</span></div>' +
      '<div class="stat"><b>' + fmt(s.n_layers) + '</b><span>PDF layers (optional content groups)</span></div>' +
      '<div class="stat"><b>' + fmt(s.n_words) + '</b><span>text strings (from ' + fmt(s.n_text_runs) + ' one-character runs)</span></div>' +
      '<div class="stat"><b>' + fmt(total) + '</b><span>features in the 17 extracted layers</span></div></div>' +
      '<h3>PDF primitives → extracted features</h3><table class="cmp"><tr><th>Output layer</th><th class="num">In PDF</th><th class="num">Extracted</th></tr>';
    s.compare.forEach(r => {
      h += '<tr><td><div class="out">' + esc(r.output) + '</div><div class="src">' + esc(r.sources) + (r.note ? ' · ' + esc(r.note) : '') + '</div></td>' +
        '<td class="num">' + (r.pdf_primitives ? fmt(r.pdf_primitives) : '–') + '<div class="src">' + esc(r.pdf_kind) + '</div></td>' +
        '<td class="num">' + esc(r.features == null ? '–' : (typeof r.features === 'number' ? fmt(r.features) : r.features)) + '</td></tr>';
    });
    h += '</table><details style="margin-top:10px"><summary style="font-size:13px;font-weight:600;color:var(--bar)">All ' + s.layers.length + ' PDF layers (paths / text)</summary><table class="cmp"><tr><th>PDF layer</th><th class="num">fills</th><th class="num">strokes</th><th class="num">text</th></tr>';
    s.layers.forEach(l => { h += '<tr><td>' + esc(l.layer) + '</td><td class="num">' + fmt(l.fills) + '</td><td class="num">' + fmt(l.strokes) + '</td><td class="num">' + fmt(l.text) + '</td></tr>'; });
    h += '</table></details>';
    $('[data-panel="compare"]').innerHTML = h;
  }

  function renderAboutPanel() {
    $('[data-panel="about"]').innerHTML =
      '<h3>How to compare</h3>' +
      '<p><b>Swipe</b> – left of the divider is the original PDF (rendered at up to 330 dpi), right are the extracted layers drawn with a matching symbology. Drag the handle.<br>' +
      '<b>Overlay</b> – extracted layers drawn over the PDF; use the slider to fade them in and out.<br>' +
      '<b>PDF only / Extracted</b> – one side at a time. Tap any extracted feature for its attributes.</p>' +
      '<h3>What you are looking at</h3>' +
      '<p>Left: <code>' + esc(meta.pdf) + '</code>, placed on a longitude/latitude grid (EPSG:4326) with an affine fit to its graticule. ' +
      'Right: the 17 shapefiles in <code>shapefiles/</code> produced by <code>extract_shapefiles.py</code> (same georeference), converted to GeoJSON for the browser.</p>' +
      '<h3>Known limits of the extraction</h3>' +
      '<p>• No attribute tables exist in the PDF; unit codes come from the legend colours + layer names (label on the map as fallback). The map prints “OGe” where the legend says “OGm”; seven units are missing from the printed legend.<br>' +
      '• Datum is not stated – WGS 84 assumed (Minna datum would differ by ~100–200 m).<br>' +
      '• Dashed symbols (boundary classes, faults, roads, railway) were re-assembled from fragments; roads were a double-line symbol and are shown as centrelines.<br>' +
      '• State capitals have no marker in the PDF – points are label centres (±7–15 km). 82 of 486 towns have no matched name.<br>' +
      '• Source topology is inherited: 16 duplicate polygons, ~2 % overlaps, small slivers.</p>' +
      '<h3>Files</h3><p><code>shapefiles/*.shp</code>, <code>shapefiles/nigeria_geology.gpkg</code>, <code>shapefiles/legend.csv</code>, <code>shapefiles/georeferencing.json</code>, <code>README.md</code>. ' +
      'Viewer data built ' + esc(meta.generated) + '.</p>';
  }

  // ------------------------------------------------------------------ bookmarks, toast
  function initChips() {
    const V = {
      face: () => meta.map_face_bounds,
      jos: () => [[9.45, 8.3], [10.25, 9.35]],
      delta: () => [[4.2, 5.2], [5.8, 7.7]],
      chad: () => [[12.5, 12.8], [13.9, 14.7]],
      sokoto: () => [[12.3, 4.5], [13.5, 6.1]],
      legend: () => [[meta.tiles.page_bounds[0][0], 14.45], [meta.tiles.page_bounds[1][0], meta.tiles.page_bounds[1][1]]],
    };
    $$('#chips button').forEach(b => b.addEventListener('click', () => {
      const k = b.dataset.view;
      map.fitBounds(L.latLngBounds(V[k]()), { padding: [8, 8], animate: true });
      if (k === 'legend') {
        if (mode !== 'pdf' && mode !== 'overlay') { setMode('pdf'); toast('Showing the PDF only – the legend panel has no vector counterpart. legend.csv is under Legend.'); }
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
  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
    return r.json();
  }
  async function boot() {
    const txt = $('#loading-text');
    try {
      meta = await fetchJSON('build/data/meta.json');
      initMap(); initSwipe(); initSheet(); initChips();
      $$('#mode button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
      $('#opacity-range').addEventListener('input', e => { $('#opacity-val').textContent = e.target.value + '%'; setVecOpacity(e.target.value / 100); });
      let done = 0;
      await Promise.all(LAYERS.map(async def => {
        data[def.id] = await fetchJSON('build/data/' + def.id + '.geojson');
        done++; txt.textContent = 'Loading extracted layers… ' + done + '/' + LAYERS.length;
      }));
      buildGroups();
      renderLayersPanel(); renderLegendPanel(); renderComparePanel(); renderAboutPanel();
      setMode('swipe');
      $('#loading').classList.add('hidden');
      toast('Drag the handle to compare · tap features for attributes');
      window.__viewer = { map, groups, data, setMode, showFeature, unitsAt, setLayerVisible, LAYERS, byId };  // for debugging / tests
    } catch (err) {
      txt.textContent = 'Failed to load: ' + err.message;
      console.error(err);
    }
  }
  boot();
})();
