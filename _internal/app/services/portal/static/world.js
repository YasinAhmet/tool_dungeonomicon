// The world map on the player page: the parchment the DM painted and sent (its towns and names), the party on it -
// where it is, the trail behind it, the route ahead - and the group's food: the meals it carries, what a day costs,
// and the food in each character's pack ("Add meal to group" moves one of yours into the group's food). A tap on the
// map pings it for everyone (the DM's editor too). Drawn like the editor's World map (app/ui/panels/world/art.py).
// Loaded after portal.js and uses its helpers (S, h, btn, act, $, store, ST, UI, tip).
'use strict';
const WM = { cam: null, img: null, imgV: 0, pings: [], raf: 0, mode: store('mapmode') || '', lastStatus: null, ptrs: new Map(),
  drag: null, built: false, hover: null, glide: null };       // glide: the party's banner travelling to where the DM moved it
const W_INK = '#3a281a', W_SEA_INK = '#2e4250', W_PAPER = 'rgba(236,222,184,', W_RED = '#a02a1e', W_PARTY = '#b02e22', W_ROUTE = '#462e1e';
const W_SERIF = '"Palatino Linotype","Book Antiqua",Palatino,Georgia,serif';
const W_TITLING = '"Felix Titling",' + W_SERIF;                // region names: a titling face where the player has one
const W_NAME = { capital: 15, city: 13, town: 11, village: 9, fort: 10, ruin: 9, poi: 9 };
const W_R = { capital: 8, city: 5.5, town: 3.6, village: 2.6, fort: 4.5, ruin: 4, poi: 3.5, compass: 24 };
const W_LABEL = { 1: 11, 2: 16, 3: 24, 4: 36 };
const W_TERRAIN = new Set(['mountain', 'hills', 'forest']);
const W_PING_LIFE = 1.6;
// a line's look by style: [colour, width, dashes (in widths, like Qt)] drawn in order (art.py LINE_LOOK)
const W_LINES = {
  road: [['rgba(236,222,184,.59)', 3.6], ['#3a281a', 1.6]],
  path: [['rgba(58,40,26,.92)', 1.4, [2.6, 1.8]]],
  river: [['rgba(236,222,184,.47)', 3.8], ['rgba(52,86,108,.92)', 2.0]],
  border: [['rgba(150,40,28,.18)', 6.0], ['rgba(150,40,28,.86)', 1.5, [4.0, 1.6, 1.0, 1.6]]],
  guide: [['rgba(58,40,26,.47)', 0.7, [6.0, 4.0]]],
  wall: [['#3a281a', 3.0], ['#3a281a', 5.6, [0.3, 1.0]]],
};
const W_LINES_PAINTED = Object.assign({}, W_LINES, {
  guide: [['rgba(240,232,210,.43)', 0.7, [6.0, 4.0]]],   // the painted look's earth roads and water-coloured rivers (art.py)
  road: [['rgba(236,226,196,.59)', 2.8], ['rgba(40,28,18,.98)', 1.45, [2.4, 1.5]]],
  path: [['rgba(236,226,196,.35)', 2.0], ['rgba(44,32,22,.78)', 0.9, [0.8, 2.0]]],
  river: [['rgb(48,62,60)', 3.8], ['rgb(96,138,150)', 2.6], ['rgba(170,200,204,.6)', 0.7]],
});
const W_TAPER = [0.35, 1.9];                            // (painted) a river: narrow at its source, wide at its mouth (art.py)
function wSmoothPts(pts) {                             // the points of wLinePath's curve, close together
  if (pts.length === 2) return pts.slice();
  const out = [pts[0]];
  let from = pts[0];
  for (let i = 1; i < pts.length - 1; i++) {
    const c = pts[i], to = [(pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2];
    const n = Math.max(2, Math.ceil(Math.hypot(to[0] - from[0], to[1] - from[1]) / 1.5));
    for (let k = 1; k <= n; k++) {
      const t = k / n, u = 1 - t;
      out.push([u * u * from[0] + 2 * u * t * c[0] + t * t * to[0], u * u * from[1] + 2 * u * t * c[1] + t * t * to[1]]);
    }
    from = to;
  }
  out.push(pts[pts.length - 1]);
  return out;
}

// ---------------------------------------------------------------- which map the pane shows
/** Battle or World: what the player picked, or (not picked) the battle while one is running, else the world. */
function mapMode() {
  const bg = typeof bgMode === 'function' ? bgMode() : 'gone';   // Battlegrounds (battlegrounds.js): a member's map stays there;
  if (bg === 'member') return 'bg';                                 // the lobby I watch starts fighting: show it; the mode closes: away
  if (WM.mode === 'duel') WM.mode = 'bg';                           // (the old name, kept by a browser)
  const b = ST && (ST._camp || ST.battle), st = b ? b.status : 'none';    // (the campaign's: on the Battlegrounds face ST.battle is the lobby's)
  if (WM.lastStatus !== null && st !== WM.lastStatus && st === 'active') WM.mode = '';    // a fight starts: show it
  WM.lastStatus = st;
  if (bg === 'start') WM.mode = 'bg';
  else if (bg === 'gone' && WM.mode === 'bg') WM.mode = '';
  return WM.mode || (st === 'active' ? 'battle' : 'world');
}
function setMapMode(m) {
  WM.mode = m; store('mapmode', m);
  if (typeof bgSwap === 'function' && bgSwap()) { render(); return; }        // to or from a lobby's map: everything anew
  renderWorld(); if (m === 'battle') renderMap();
}

function buildWorld() {
  if (WM.built) return;
  WM.built = true;
  const bar = document.querySelector('#map .bar');
  bar.prepend(h('span', { class: 'seg', id: 'mapmode' }));
  const pane = $('map');
  const body = h('div', { id: 'worldbody', class: 'hide' },
    h('div', { id: 'worldwrap' }, h('canvas', { id: 'wboard' }),
      h('div', { class: 'wzoom' }, h('button', { class: 'sm', id: 'wzout' }, '−'), h('button', { class: 'sm', id: 'wzin' }, '+'),
        h('button', { class: 'sm', id: 'wzfit' }, '⤢')),
      h('div', { id: 'wempty', class: 'hide' })),
    h('aside', { id: 'worldside' }));
  pane.querySelector('.mapbody').after(body);
  $('wzin').onclick = () => wZoom(1.3);
  $('wzout').onclick = () => wZoom(1 / 1.3);
  $('wzfit').onclick = () => { WM.cam = null; drawWorld(); };
  const cv = $('wboard');
  cv.addEventListener('pointerdown', wDown);
  cv.addEventListener('pointermove', wMove);
  cv.addEventListener('pointerup', wUp);
  cv.addEventListener('pointercancel', e => { WM.ptrs.delete(e.pointerId); WM.drag = null; });
  cv.addEventListener('pointerleave', () => { WM.hover = null; drawWorld(); });
  cv.addEventListener('wheel', e => { e.preventDefault(); const r = cv.getBoundingClientRect(); wZoom(Math.pow(1.0015, -e.deltaY), [e.clientX - r.left, e.clientY - r.top]); }, { passive: false });
  window.addEventListener('resize', () => { if (mapMode() === 'world') drawWorld(); });
}

function renderWorld() {
  if (!ST) return;
  buildWorld();
  const mode = mapMode(), world = mode === 'world';
  const seg = $('mapmode');
  const live = typeof bgLive === 'function' && bgLive(bgLobby());        // (a fight on in the lobby I look at: battlegrounds.js)
  const bgOn = typeof bgState === 'function' && !!bgState();              // (the Battlegrounds app, or the mode open: never in the campaign app)
  const key = mode + (wordsLang || '') + (bgOn ? (live ? ':bg!' : ':bg') : '');
  if (seg.dataset.k !== key) {
    seg.dataset.k = key;
    seg.replaceChildren(
      h('button', { class: 'camp' + (mode === 'battle' ? ' on' : ''), onclick: () => setMapMode('battle'), tip: S('The battle map') }, '⚔ ' + S('Battle')),
      h('button', { class: 'camp' + (world ? ' on' : ''), onclick: () => setMapMode('world'), tip: S('The world map: where the party is, its route and food') }, '🗺 ' + S('World')),
      ...(bgOn ? [h('button', { class: (mode === 'bg' ? 'on' : '') + (live ? ' live' : ''), onclick: () => setMapMode('bg'),
        tip: S('Battlegrounds: fights for fun, apart from the game - a duel, a skirmish or an arena run. Join a lobby, or watch. Nothing of it stays.') }, '⚔ ' + S('Battlegrounds'))] : []));
  }
  document.body.classList.toggle('worldmode', world);
  $('worldbody').classList.toggle('hide', !world);
  if (typeof renderBG === 'function') renderBG(mode);         // a Battlegrounds lobby, or its fight on the map (battlegrounds.js)
  if (!world) return;
  const W = ST.world, m = W.map;
  $('bname').textContent = m ? m.name : S('World map');
  $('round').textContent = S('Day {0}', W.food.day);
  const mapKey = m ? m.id + '_' + m.v + '_' + vq() : '';      // (another picture quality: fetched again at that size)
  if (m && WM.mapId !== m.id) { WM.mapId = m.id; WM.cam = null; WM.shown = null; WM.glide = null; }   // the DM opened another map
  if (m && WM.imgV !== mapKey) {                          // a new version of the map: its picture once (kept by the browser)
    WM.imgV = mapKey;
    const img = new Image();
    img.onload = () => { WM.img = img; drawWorld(); };
    img.src = m.img + '?q=' + vq() + '&k=' + encodeURIComponent(KEY);
  }
  if (!m) { WM.img = null; WM.imgV = 0; }
  const empty = $('wempty');
  empty.classList.toggle('hide', !!m);
  empty.textContent = W.hidden ? S('The DM keeps the world map hidden.') : S("The DM hasn't shared a map yet.");
  for (const [id, words] of [['wzin', S('Zoom in (wheel)')], ['wzout', S('Zoom out (wheel)')], ['wzfit', S('Fit the whole map')]]) $(id).title = words;
  const to = W.party.pos, leg = W.party.leg;
  if (to && WM.shown && (to[0] !== WM.shown[0] || to[1] !== WM.shown[1]) && !CALM.matches) {
    // along the way the party went (the roads; back the same way when the DM took the move back), else straight
    const fresh = leg && leg.n !== WM.legN && wSame(leg.pts[leg.pts.length - 1], to);
    const pts = fresh ? leg.pts.map(p => p.slice()) : [WM.glide ? wPartyAt() || WM.shown : WM.shown, to];
    if (WM.glide && fresh) pts[0] = wPartyAt() || pts[0];
    WM.glide = { pts, back: !!(fresh && leg.back), t0: performance.now() / 1000, dur: wGlideTime(pts) };
    if (!WM.raf) WM.raf = requestAnimationFrame(wFrame);
  }
  if (leg) WM.legN = leg.n;
  WM.shown = to;
  keepFocus($('worldside'), renderWorldSide);
  drawWorld();
}
const W_SPEED = 260;                                  // map pixels a second the banner travels (0.45 to 2.4 s a move)
const wSame = (a, b) => !!a && !!b && Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) < 0.01;
const wLen = pts => pts.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
const wGlideTime = pts => Math.max(0.45, Math.min(2.4, wLen(pts) / W_SPEED));
/** A way cut a fraction `f` of its length along: [the points up to there, ending there; from there on]. */
function wSplit(pts, f) {
  let left = Math.max(0, Math.min(1, f)) * wLen(pts);
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (left <= d && d > 0) {
      const at = [a[0] + (b[0] - a[0]) * left / d, a[1] + (b[1] - a[1]) * left / d];
      return [pts.slice(0, i + 1).concat([at]), [at].concat(pts.slice(i + 1))];
    }
    left -= d;
  }
  return [pts.slice(), [pts[pts.length - 1]]];
}
/** The banner's glide now: [where it is, the way behind it, the way ahead] (null when it is still). */
function wGlideNow() {
  const gl = WM.glide;
  if (!gl || !ST.world.party.pos) return null;
  const t = (performance.now() / 1000 - gl.t0) / gl.dur;
  if (t >= 1) { WM.glide = null; return null; }
  const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  const [done, ahead] = wSplit(gl.pts, e);
  return [done[done.length - 1], done, ahead];
}
/** Where the party's banner is drawn now (on its way, or where the party is). */
function wPartyAt() {
  const now = wGlideNow();
  return now ? now[0] : ST.world.party.pos;
}

// ---------------------------------------------------------------- the side: the party and its food
function wDays(n) { return n === 1 ? S('{0} day', n) : S('{0} days', n); }
function renderWorldSide() {
  const W = ST.world, f = W.food, side = $('worldside');
  const where = !W.party.pos ? S('The party is not on the map.') : W.near ? (W.near.here ? S('📍 At {0}', W.near.name)
    : S('📍 {0} mi from {1}', Math.round(W.near.miles), W.near.name)) : S('📍 Out in the wilds');
  const parts = [h('div', { class: 'title' }, S('The party'), h('span', { class: 'grow' }),
    W.party.pos && W.map ? btn('⌖ ' + S('Find the party'), () => wFind(), 'sm flat', S('Show where the party is')) : null),
    h('div', { class: 'wwhere' }, where)];
  if (W.route.miles) parts.push(h('div', { class: 'dim small' }, S('🧭 {0} mi to go, about {1} at a {2} pace', Math.round(W.route.miles), wDays(W.route.days), W.pace)));
  const low = f.days_left !== null && f.days_left < 2;
  parts.push(h('div', { class: 'title wgap' }, S('Group food'), h('span', { class: 'grow' }), h('span', { class: 'dim' }, S('Day {0}', f.day))));
  parts.push(h('div', { class: 'wmeals' + (low ? ' bad' : '') }, '🍖 ', h('b', null, String(f.meals)), ' ', S('meals')));
  const bits = [S('{0} eat each day', f.mouths)];
  if (f.average) bits.push(S('{0} spent a day on average', f.average));
  if (f.days_left !== null) bits.push(S('lasts about {0}', wDays(f.days_left)));
  parts.push(h('div', { class: 'small ' + (low ? 'bad' : 'dim') }, bits.join(' · ')));
  // each character's own food: the owner moves a meal into the group's
  const rows = W.packs.map(p => {
    const tipText = p.items.map(e => `${e.qty}× ${e.label}`).join('\n') || S('No food');
    return h('div', { class: 'wpack' + (p.mine ? ' mine' : '') },
      h('span', { class: 'grow', tip: tipText }, p.character),
      h('span', { class: p.meals ? '' : 'dim', tip: tipText }, '🍖 ' + p.meals),
      p.mine && may('trade_items') ? btn(S('Add meal to group'), () => act('give_meal', { who: p.character }), 'sm primary',
        S('Move one meal from {0}\'s pack into the group\'s food', p.character)) : null);
  });
  if (rows.length) parts.push(h('div', { class: 'title wgap' }, S('In their packs')), h('div', { class: 'wpacks' }, ...rows));
  const mineEmpty = W.packs.some(p => p.mine && !p.meals);
  if (mineEmpty) parts.push(h('div', { class: 'dim small' }, S('No food in your pack to share.')));
  if (f.log.length) {
    parts.push(h('div', { class: 'title wgap' }, S('Lately')));
    parts.push(h('div', { class: 'wlog small' }, ...f.log.slice().reverse().map(e =>
      h('div', null, h('span', { class: 'dim' }, S('Day {0}', e.day) + ' '), h('b', { class: e.n > 0 ? 'good' : 'bad' }, (e.n > 0 ? '+' : '') + e.n),
        ' ' + e.why + (e.by ? ` · ${e.by}` : '')))));
  }
  parts.push(h('div', { class: 'dim small wgap' }, touch() ? S('Tap the map to ping a place for everyone.') : S('Click the map to ping a place for everyone.')));
  side.replaceChildren(...parts);
}

// ---------------------------------------------------------------- the view
function wSize() { const m = ST.world.map; return m ? [m.w, m.h] : [1024, 640]; }
function wFit(vw, vh) {
  const [w, h_] = wSize(), z = Math.min((vw - 12) / w, (vh - 12) / h_);
  return { z, x: (vw - w * z) / 2, y: (vh - h_ * z) / 2 };
}
function wCam() { const wrap = $('worldwrap'); return WM.cam || wFit(wrap.clientWidth, Math.max(200, wrap.clientHeight)); }
function wZoom(f, at) {
  const wrap = $('worldwrap'), c = { ...wCam() };
  const [ax, ay] = at || [wrap.clientWidth / 2, wrap.clientHeight / 2];
  const fit = wFit(wrap.clientWidth, Math.max(200, wrap.clientHeight)).z;
  const nz = Math.max(fit * 0.6, Math.min(10, c.z * f));
  const mx = (ax - c.x) / c.z, my = (ay - c.y) / c.z;
  WM.cam = { z: nz, x: ax - mx * nz, y: ay - my * nz };
  drawWorld();
}
/** Fly the view to the party. */
function wFind() {
  const p = ST.world.party.pos, wrap = $('worldwrap');
  if (!p) return;
  const fit = wFit(wrap.clientWidth, Math.max(200, wrap.clientHeight)).z, z = Math.max(fit * 2.2, wCam().z);
  WM.cam = { z, x: wrap.clientWidth / 2 - p[0] * z, y: wrap.clientHeight / 2 - p[1] * z };
  drawWorld();
}
function wPoint(e) { const r = $('wboard').getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function wDown(e) {
  $('wboard').setPointerCapture(e.pointerId);
  WM.ptrs.set(e.pointerId, wPoint(e));
  const c = wCam();
  if (WM.ptrs.size === 2) {                            // two fingers: pinch to zoom
    const [a, b] = [...WM.ptrs.values()];
    WM.drag = { pinch: Math.hypot(a[0] - b[0], a[1] - b[1]), cam: { ...c }, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
  } else WM.drag = { at: wPoint(e), cam: { ...c }, t: performance.now(), moved: false };
}
function wMove(e) {
  const p = wPoint(e);
  const c = wCam();
  WM.hover = [(p[0] - c.x) / c.z, (p[1] - c.y) / c.z];
  if (!WM.ptrs.has(e.pointerId)) return;
  WM.ptrs.set(e.pointerId, p);
  const d = WM.drag;
  if (!d) return;
  if (d.pinch && WM.ptrs.size === 2) {
    const [a, b] = [...WM.ptrs.values()];
    const f = Math.hypot(a[0] - b[0], a[1] - b[1]) / d.pinch, nz = Math.max(0.1, Math.min(10, d.cam.z * f));
    const mx = (d.mid[0] - d.cam.x) / d.cam.z, my = (d.mid[1] - d.cam.y) / d.cam.z, mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    WM.cam = { z: nz, x: mid[0] - mx * nz, y: mid[1] - my * nz };
  } else if (d.at) {
    if (Math.hypot(p[0] - d.at[0], p[1] - d.at[1]) > 6) d.moved = true;
    if (d.moved) WM.cam = { ...d.cam, x: d.cam.x + p[0] - d.at[0], y: d.cam.y + p[1] - d.at[1] };
  }
  drawWorld();
}
function wUp(e) {
  const d = WM.drag;
  WM.ptrs.delete(e.pointerId);
  if (WM.ptrs.size === 0) WM.drag = null;
  if (d && d.at && !d.moved && !d.pinch && performance.now() - d.t < 600 && ST.world.map) {   // a tap: ping it
    const c = wCam(), p = wPoint(e), [w, h_] = wSize();
    const x = (p[0] - c.x) / c.z, y = (p[1] - c.y) / c.z;
    if (x >= 0 && y >= 0 && x <= w && y <= h_) act('world_ping', { x, y }, true);
  }
}

/** A ping down the live stream ("wping {x, y, who}"): rings rippling out on the map, for a moment. */
function wping(msg) {
  let p;
  try { p = JSON.parse(msg.slice(6)); } catch { return; }
  p.at = performance.now() / 1000;
  WM.pings.push(p);
  if (WM.pings.length > 12) WM.pings.shift();
  if (p.uid !== ST?.me?.id) buzz();
  if (!WM.raf) WM.raf = requestAnimationFrame(wFrame);
}
function wFrame() {
  WM.raf = 0;
  const now = performance.now() / 1000;
  WM.pings = WM.pings.filter(p => now - p.at < W_PING_LIFE);
  drawWorld();
  if (WM.pings.length || WM.glide) WM.raf = requestAnimationFrame(wFrame);
}

// ---------------------------------------------------------------- drawing
function wFont(size, italic, bold, face) { return `${italic ? 'italic ' : ''}${bold ? 'bold ' : ''}${size.toFixed(2)}px ${face || W_SERIF}`; }
function wName(g, text, x, y, size, opts = {}) {      // a mark's name: on a plaque when the map wants (art.py name_text)
  if (!(ST.world.map || {}).plaques) return wText(g, text, x, y, size, opts);
  g.font = wFont(size, false, opts.bold);
  if ('letterSpacing' in g) g.letterSpacing = ((opts.spacing || 0) * size * 0.55).toFixed(2) + 'px';
  const x0 = x + size * 0.6, tw = g.measureText(text).width;
  wPlaque(g, x0, y - size * 0.72, tw, size * 0.72);
  wText(g, text, x0, y, size, Object.assign({}, opts, { noHalo: true, haloRGB: W_PAPER, color: opts.color || '#3a281a' }));
}
function wText(g, text, x, y, size, opts = {}) {
  g.font = wFont(size, opts.italic, opts.bold, opts.face);
  g.textAlign = opts.align || 'left';
  g.textBaseline = 'alphabetic';
  if ('letterSpacing' in g) g.letterSpacing = ((opts.spacing || 0) * size * 0.55).toFixed(2) + 'px';
  g.lineJoin = 'round';
  let color = opts.color || W_INK, haloRGB = opts.haloRGB || W_PAPER, haloA = opts.haloA ?? 0.78;
  if (wPainted() && !opts.haloRGB && (color === W_INK || color === 'rgba(58,40,26,.6)')) {   // pale names, dark halo (art.py)
    color = color === W_INK ? 'rgb(244,236,216)' : 'rgba(244,236,216,.6)'; haloRGB = 'rgba(26,20,14,'; haloA = Math.min(haloA, 0.69);
  }
  g.lineWidth = opts.halo || 2.4;
  g.strokeStyle = haloRGB + haloA + ')';
  if (!opts.noHalo) g.strokeText(text, x, y);
  g.fillStyle = color;
  g.fillText(text, x, y);
  if ('letterSpacing' in g) g.letterSpacing = '0px';
}
function wRand(v, i) { const x = Math.sin(v * 12.9898 + i * 78.233) * 43758.5453; return x - Math.floor(x); }
function wCircle(g, x, y, r) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); }
let W_NAMES = 'with';                                  // marks drawn with their names, 'without' them, or 'only' the names
function wMarks(g, marks) {                            // marks back to front, then all their names over them (art.py paint_marks)
  try {
    W_NAMES = 'without'; for (const m of marks) wMark(g, m);
    W_NAMES = 'only'; for (const m of marks) wMark(g, m);
  } finally { W_NAMES = 'with'; }
}
function wMark(g, m) {                                 // a mark and its name, s times their size (drawn: sharp at any zoom)
  const { kind, x, y } = m, s = +m.s || 1;
  if (W_NAMES === 'only' && (W_TERRAIN.has(kind) || kind === 'compass')) return;
  if (W_TERRAIN.has(kind)) return wTerrain(g, m);
  if (kind === 'compass') return wCompass(g, x, y, 24 * s);
  if (kind === 'art') return wStamp(g, m);
  if (wPainted() && m.pa) {                              // a painted town, castle or ruin (art.py paint_mark)
    if (W_NAMES !== 'only') wStamp(g, { kind: 'art', art: m.pa, x, y, s: m.ps, r: 0 });
    const img = W_STAMPS[m.pa], look = (ST.world.map.stamps || {})[m.pa];
    if (m.name && W_NAMES !== 'without' && look) {
      const h = look[0] * m.ps, w = img && img.naturalHeight ? h * img.naturalWidth / img.naturalHeight : h, size = (W_NAME[kind] || 10) * s;
      wName(g, m.name, x + w / 2 + 2.5, y - h / 2 + size * 0.34, size, { bold: kind === 'capital', spacing: kind === 'capital' || kind === 'city' ? 0.04 : 0 });
    }
    return;
  }
  if (s !== 1) { g.save(); g.translate(x, y); g.scale(s, s); g.translate(-x, -y); }
  wSettlement(g, m);
  if (s !== 1) g.restore();
}
function wPainted() { const look = (ST.world.map || {}).look; return look === 'painted' || look === 'teal' || look === 'antique'; }   // in colour (render.COLOUR_LOOKS)
const W_SHADOW = 0.5;
const W_INK_TINTS = {   // the painted look: an ink stamp's paper by its family (art.py INK_TINTS)
  tree: '112,146,76', wood: '98,134,70', bush: '112,146,76', pine: '78,116,74', palm: '118,152,82',
  deadtree: '150,132,102', cactus: '112,150,92', swamp: '112,126,82', grass: '138,146,78',
  mountain: '186,170,138', range: '186,170,138', cliffs: '176,160,128', volcano: '150,118,100',
  hills: '160,156,98', dunes: '224,202,150', fields: '204,182,108',
  village: '222,200,160', town: '222,200,160', city: '222,200,160', farmstead: '222,200,160',
  castle: '206,198,182', tower: '206,198,182', watchtower: '206,198,182', lighthouse: '230,222,206',
  temple: '218,206,184', ruins: '190,182,166', stones: '180,176,166', obelisk: '190,184,170',
  serpent: '104,140,132', whale: '126,146,156', kraken: '156,108,112', searocks: '150,146,136',
};
const W_INK_PALE = new Set(['waves', 'whirlpool']);
const W_SIZED = {};                                    // a picture scaled down to about px tall, smoothly, once (key -> size -> canvas)
const W_MIPS = {};                                     // a picture halved step by step, once (key -> [canvas, ...])
function wSized(src, key, px) {
  const sh = src.naturalHeight || src.height;
  px = Math.max(4, Math.ceil(px / 4) * 4);              // (a size every 4 px: zooming doesn't make new ones all the time)
  if (px >= sh * 0.8) return src;
  const sizes = W_SIZED[key] || (W_SIZED[key] = {});
  if (sizes[px]) return sizes[px];
  let mips = W_MIPS[key];
  if (!mips) {                                           // halved step by step: fine lines stay whole
    mips = W_MIPS[key] = [src];
    for (let cur = src; (cur.naturalHeight || cur.height) >= 16;) {
      const c = document.createElement('canvas');
      c.width = Math.max(1, Math.round((cur.naturalWidth || cur.width) / 2)); c.height = Math.max(1, Math.round((cur.naturalHeight || cur.height) / 2));
      const cg = c.getContext('2d'); cg.imageSmoothingQuality = 'high'; cg.drawImage(cur, 0, 0, c.width, c.height);
      mips.push(c); cur = c;
    }
  }
  const from = mips.filter(c => (c.naturalHeight || c.height) >= px).pop() || src;   // the smallest still at least px tall
  const out = document.createElement('canvas');
  out.width = Math.max(1, Math.round((from.naturalWidth || from.width) * px / (from.naturalHeight || from.height))); out.height = px;
  const og = out.getContext('2d'); og.imageSmoothingQuality = 'high'; og.drawImage(from, 0, 0, out.width, out.height);
  return (sizes[px] = out);
}
const W_SHADOWS = {};                                  // a stamp's soft shadow, blurred once: {cv, mx, my} (margins as shares)
function wShadow(img, key) {
  if (W_SHADOWS[key]) return W_SHADOWS[key];
  const nw = img.naturalWidth, nh = img.naturalHeight, blur = Math.max(1.5, nh * 0.035), mg = Math.ceil(blur * 3);
  const cv = document.createElement('canvas');
  cv.width = nw + 2 * mg; cv.height = nh + 2 * mg;
  const g = cv.getContext('2d');                       // (the picture drawn off the canvas: only its shadow lands on it)
  g.shadowColor = `rgba(0,0,0,${W_SHADOW})`; g.shadowBlur = blur * 2; g.shadowOffsetX = cv.width * 2;
  g.drawImage(img, mg - cv.width * 2, mg);
  return (W_SHADOWS[key] = { cv, mx: mg / nw, my: mg / nh });
}
const W_STAMPS = {};                                   // a stamp's picture by its key, loaded once (kept by the browser)
function wStamp(g, m) {                                // a picture from a pack: h × s tall, standing on its point or around it
  const look = (ST.world.map.stamps || {})[m.art];
  if (!look) return;
  if (look.length > 3) return wInkStamp(g, m, look);
  let img = W_STAMPS[m.art];
  if (!img) {
    img = W_STAMPS[m.art] = new Image();
    img.onload = () => {                                   // the layer drawn again with it (once for a batch of pictures)
      clearTimeout(WM.stampWait);
      WM.stampWait = setTimeout(() => { WM.layerVer = (WM.layerVer || 0) + 1; drawWorld(); }, 60);
    };
    img.src = `/worldart/${m.art}?k=${encodeURIComponent(KEY)}`;
  }
  if (!img.complete || !img.naturalHeight) return;
  const h = look[0] * (+m.s || 1), w = h * img.naturalWidth / img.naturalHeight, turn = +m.r || 0;
  const top = look[1] === 'b' ? m.y - h : m.y - h / 2;
  if (W_NAMES !== 'only') {
  g.imageSmoothingQuality = 'high';
  if (turn) { g.save(); g.translate(m.x, m.y); g.rotate(turn * Math.PI / 180); g.translate(-m.x, -m.y); }
  const t = g.getTransform(), px = h * Math.hypot(t.a, t.b);   // (its height on the canvas: a picture made that size, once)
  if (wPainted()) {                                      // a soft shadow down and to the right (art.py paint_stamp)
    const sh = wShadow(img, m.art), off = 0.4 + h * (h > 15 ? 0.09 : 0.05);
    g.drawImage(wSized(sh.cv, 's' + m.art, px * (1 + 2 * sh.my)), m.x - w / 2 - w * sh.mx + off * 0.7, top - h * sh.my + off,
      w * (1 + 2 * sh.mx), h * (1 + 2 * sh.my));
  }
  if ((ST.world.map || {}).look === 'antique' && 'filter' in g) g.filter = 'sepia(0.55) saturate(0.85)';   // (art.py grade)
  g.drawImage(wSized(img, m.art, px), m.x - w / 2, top, w, h);
  if ('filter' in g) g.filter = 'none';
  if (turn) g.restore();
  }
  if (m.name && W_NAMES !== 'without') {
    const [size, bold] = wStampName(m), half = turn ? Math.max(w, h) / 2 : w / 2;
    wName(g, m.name, m.x + half + 2.5, top + h / 2 + size * 0.34, size, { bold, spacing: bold ? 0.03 : 0 });
  }
}
const W_STAMP_NAME = [['city', 13.5, true], ['castle', 12, true], ['palace', 12, true], ['harbour', 11.5, false], ['town', 11.5, false],
  ['village', 9.5, false], ['hamlet', 9.5, false]];      // a stamp's name by what it shows (art.py STAMP_NAME)
function wStampName(m) {
  const hit = W_STAMP_NAME.find(([k]) => (m.art || '').includes(k)) || [null, W_NAME.town, false];
  return [hit[1] * Math.sqrt(+m.s || 1), hit[2]];
}
const W_SHAPES = {};                                   // an ink stamp's paper and ink as Path2D, made once
function wInkStamp(g, m, look) {                       // [h, anchor, w, paper, ink]: two fills, turned and sized
  let sh = W_SHAPES[m.art];
  if (!sh) sh = W_SHAPES[m.art] = [new Path2D(look[3] || ''), new Path2D(look[4] || '')];
  const s = +m.s || 1, turn = +m.r || 0;
  if (W_NAMES !== 'only') {
  g.save(); g.translate(m.x, m.y);
  if (turn) g.rotate(turn * Math.PI / 180);
  g.scale(s, s);
  const painted = wPainted(), fam = m.art.replace(/[\d_]+$/, '').slice(4);
  if (painted) {                                         // its shadow, and its paper coloured as what it is (art.py)
    const off = 0.3 + look[0] * 0.05;
    g.translate(off * 0.7, off); g.fillStyle = 'rgba(0,0,0,.27)'; g.fill(sh[0], 'evenodd'); g.translate(-off * 0.7, -off);
  }
  const tint = painted && W_INK_TINTS[fam];
  if ((ST.world.map || {}).look === 'antique' && 'filter' in g) g.filter = 'sepia(0.55) saturate(0.85)';   // (art.py grade)
  g.fillStyle = tint ? `rgb(${tint})` : 'rgb(226,208,164)'; g.fill(sh[0], 'evenodd');
  if ('filter' in g) g.filter = 'none';
  g.fillStyle = painted && W_INK_PALE.has(fam) ? 'rgba(214,228,224,.86)' : 'rgb(28,22,16)'; g.fill(sh[1], 'evenodd');
  g.restore();
  }
  if (m.name && W_NAMES !== 'without') {
    const [size, bold] = wStampName(m), h = look[0] * s, w = look[2] * s, half = turn ? Math.max(w, h) / 2 : w / 2;
    const cy = look[1] === 'b' ? m.y - h / 2 : m.y;
    wName(g, m.name, m.x + half + 2.5, cy + size * 0.34, size, { bold, spacing: bold ? 0.03 : 0 });
  }
}
function wSettlement(g, m) {
  const { kind, x, y } = m;
  g.lineWidth = 1.3; g.strokeStyle = W_INK; g.setLineDash([]);
  if (W_NAMES === 'only') { /* the name alone */ } else if (kind === 'capital') {
    wCircle(g, x, y, 7.5); g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
    g.beginPath();
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? 2.6 : 6.2; g.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
    g.closePath(); g.fillStyle = W_INK; g.fill();
  } else if (kind === 'city') {
    g.lineWidth = 1.4; wCircle(g, x, y, 5.5); g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
    wCircle(g, x, y, 2.9); g.fillStyle = W_INK; g.fill();
  } else if (kind === 'town') {
    wCircle(g, x, y, 3.6); g.fillStyle = W_INK; g.fill(); g.lineWidth = 1; g.strokeStyle = W_PAPER + '1)'; g.stroke();
  } else if (kind === 'village') {
    g.lineWidth = 1.2; wCircle(g, x, y, 2.6); g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
  } else if (kind === 'fort') {
    g.beginPath(); g.moveTo(x - 4.5, y + 4); g.lineTo(x - 4.5, y - 4.5);
    const tops = [-4.5, -2.8, -4.5, -2.8, -4.5];
    tops.forEach((t, i) => { g.lineTo(x - 4.5 + i * 2.25, y + t); g.lineTo(i < 4 ? x - 4.5 + (i + 1) * 2.25 : x + 4.5, y + t); });
    g.lineTo(x + 4.5, y + 4); g.closePath();
    g.fillStyle = W_INK; g.fill(); g.lineWidth = 0.8; g.strokeStyle = W_PAPER + '1)'; g.stroke();
    g.fillStyle = W_PAPER + '1)'; g.fillRect(x - 1.1, y + 0.6, 2.2, 3.4);
  } else if (kind === 'ruin') {
    g.setLineDash([2.2 * 1.3, 1.6 * 1.3]); wCircle(g, x, y, 4); g.stroke(); g.setLineDash([]);
    g.lineWidth = 1.1; g.beginPath(); g.moveTo(x - 1.6, y - 1.6); g.lineTo(x + 1.6, y + 1.6); g.moveTo(x - 1.6, y + 1.6); g.lineTo(x + 1.6, y - 1.6); g.stroke();
  } else if (kind === 'poi') {
    g.strokeStyle = W_RED; g.lineWidth = 1.8; g.lineCap = 'round';
    g.beginPath(); g.moveTo(x - 3.4, y - 3.4); g.lineTo(x + 3.4, y + 3.4); g.moveTo(x - 3.4, y + 3.4); g.lineTo(x + 3.4, y - 3.4); g.stroke();
    g.lineCap = 'butt';
  }
  if (m.name && W_NAMES !== 'without') {
    const r = W_R[kind] || 4, size = W_NAME[kind] || 10;
    wName(g, m.name, x + r + 2.5, y + size * 0.34, size, { bold: kind === 'capital', spacing: kind === 'capital' || kind === 'city' ? 0.04 : 0,
      color: kind === 'poi' ? W_RED : W_INK });
  }
}
function wCompass(g, x, y, r) {
  g.setLineDash([]);
  if (wPainted()) {                                      // rhumb lines right across the sea (art.py paint_compass)
    for (let i = 0; i < 16; i++) {
      const a = i * Math.PI / 8;
      g.strokeStyle = `rgba(232,222,196,${i % 4 ? 0.15 : 0.27})`; g.lineWidth = i % 4 ? 0.5 : 0.7;
      wLine(g, [[x + Math.cos(a) * r * 0.8, y + Math.sin(a) * r * 0.8], [x + Math.cos(a) * 4000, y + Math.sin(a) * 4000]]);
    }
  }
  g.strokeStyle = W_INK;
  g.lineWidth = 0.9; wCircle(g, x, y, r * 0.72); g.stroke();
  g.lineWidth = 0.5; wCircle(g, x, y, r * 0.64); g.stroke();
  g.beginPath();
  for (let i = 0; i < 32; i++) { const a = i * Math.PI / 16; g.moveTo(x + Math.cos(a) * r * 0.64, y + Math.sin(a) * r * 0.64); g.lineTo(x + Math.cos(a) * r * 0.72, y + Math.sin(a) * r * 0.72); }
  g.stroke();
  g.lineWidth = 0.7; g.lineJoin = 'miter';
  for (let i = 0; i < 8; i++) {
    const len = i < 4 ? r : r * 0.62, wd = i < 4 ? r * 0.16 : r * 0.12;
    const a = -Math.PI / 2 + (i % 4) * Math.PI / 2 + (i >= 4 ? Math.PI / 4 : 0);
    const tip = [x + Math.cos(a) * len, y + Math.sin(a) * len];
    const left = [x + Math.cos(a - Math.PI / 2) * wd, y + Math.sin(a - Math.PI / 2) * wd], right = [x + Math.cos(a + Math.PI / 2) * wd, y + Math.sin(a + Math.PI / 2) * wd];
    g.beginPath(); g.moveTo(x, y); g.lineTo(...left); g.lineTo(...tip); g.closePath(); g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
    g.beginPath(); g.moveTo(x, y); g.lineTo(...tip); g.lineTo(...right); g.closePath(); g.fillStyle = W_INK; g.fill(); g.stroke();
  }
  wText(g, 'N', x, y - r * 1.06, r * 0.42, { align: 'center', bold: true, halo: r * 0.08 });
}
function wTerrain(g, m) {
  if (wPainted() && m.pa) return wStamp(g, { kind: 'art', art: m.pa, x: m.x, y: m.y, s: m.ps, r: 0 });   // its painted picture (art.py)
  const { x, y, kind } = m, s = +m.s || 1, v = +m.v || 0;
  g.strokeStyle = W_INK; g.lineWidth = 1; g.lineJoin = 'round'; g.lineCap = 'round'; g.setLineDash([]);
  const shade = 'rgba(58,40,26,.27)';
  if (kind === 'mountain') {
    const w = (13 + wRand(v, 1) * 6) * s, hh = (11 + wRand(v, 2) * 6) * s, px = x + (wRand(v, 3) - 0.5) * w * 0.3;
    g.beginPath(); g.moveTo(x - w / 2, y);
    if (wRand(v, 4) > 0.45) { g.lineTo(x - w * 0.28, y - hh * 0.45); g.lineTo(x - w * 0.2, y - hh * 0.38); }
    g.lineTo(px, y - hh); g.lineTo(px + w * 0.12, y - hh * 0.82); g.lineTo(px + w * 0.18, y - hh * 0.86); g.lineTo(x + w / 2, y);
    g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
    g.beginPath(); g.moveTo(px, y - hh); g.lineTo(px + w * 0.12, y - hh * 0.82); g.lineTo(px + w * 0.18, y - hh * 0.86); g.lineTo(x + w / 2, y);
    g.lineTo(px + w * 0.05, y); g.closePath(); g.fillStyle = shade; g.fill();
    g.lineWidth = 0.8; g.beginPath(); g.moveTo(px, y - hh); g.quadraticCurveTo(px + w * 0.02, y - hh * 0.45, px + w * 0.05, y); g.stroke();
    for (let i = 1; i < 4; i++) {
      const t = i / 4.5, ax = px + w * 0.05 + (x + w / 2 - px - w * 0.05) * t * 0.85, ay = y - hh * (1 - t) * 0.72;
      g.beginPath(); g.moveTo(ax, ay); g.lineTo(ax + w * 0.02, Math.min(y, ay + hh * 0.28)); g.stroke();
    }
  } else if (kind === 'hills') {
    const w = (12 + wRand(v, 1) * 6) * s, hh = (5 + wRand(v, 2) * 3) * s;
    g.beginPath(); g.moveTo(x - w / 2, y); g.bezierCurveTo(x - w * 0.3, y - hh * 1.3, x + w * 0.3, y - hh * 1.3, x + w / 2, y);
    g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke();
    g.lineWidth = 0.7; g.beginPath();
    g.moveTo(x + w * 0.12, y - hh * 0.55); g.lineTo(x + w * 0.24, y - hh * 0.2); g.moveTo(x + w * 0.24, y - hh * 0.62); g.lineTo(x + w * 0.34, y - hh * 0.3);
    g.stroke();
  } else if (kind === 'forest') {
    const r = (3.2 + wRand(v, 1) * 1.6) * s;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x, y - r * 0.9); g.stroke();
    g.beginPath();
    for (let i = 0; i <= 7; i++) { const a = Math.PI * 2 * i / 7, rr = r * (0.88 + 0.14 * wRand(v, 10 + i % 7)); g.lineTo(x + Math.cos(a) * rr, y - r * 1.6 + Math.sin(a) * rr); }
    g.fillStyle = 'rgb(206,200,158)'; g.fill(); g.stroke();
    g.beginPath(); g.moveTo(x, y - r * 1.6); g.arc(x, y - r * 1.6, r, Math.PI / 6, Math.PI / 6 + Math.PI * 150 / 180); g.closePath(); g.fillStyle = shade; g.fill();
  }
}
function wLinePath(g, pts) {                         // straight to each midpoint, curving round the corners
  g.beginPath(); g.moveTo(pts[0][0], pts[0][1]);
  if (pts.length === 2) { g.lineTo(pts[1][0], pts[1][1]); return; }
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    g.quadraticCurveTo(a[0], a[1], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
  }
  g.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
}
function wDrawnLine(g, line) {
  wLinePath(g, line.pts);
  g.lineJoin = 'round';
  const looks = wPainted() ? W_LINES_PAINTED : W_LINES;
  if (wPainted() && line.style === 'river') {            // widening from its source to its mouth
    const pts = wSmoothPts(line.pts), n = pts.length - 1, layers = looks.river;
    g.lineCap = 'round';
    for (const [color, width] of layers.slice(0, -1)) {
      g.strokeStyle = color;
      for (let i = 0; i < n; i++) {
        g.lineWidth = width * (W_TAPER[0] + (W_TAPER[1] - W_TAPER[0]) * i / n);
        g.beginPath(); g.moveTo(pts[i][0], pts[i][1]); g.lineTo(pts[i + 1][0], pts[i + 1][1]); g.stroke();
      }
    }
    const [color, width] = layers[layers.length - 1];
    wLinePath(g, line.pts); g.strokeStyle = color; g.lineWidth = width; g.stroke();
    return;
  }
  for (const [color, width, dashes] of looks[line.style] || looks.road) {
    g.strokeStyle = color; g.lineWidth = width; g.lineCap = dashes ? 'butt' : 'round';
    g.setLineDash(dashes ? dashes.map(d => d * width) : []);
    g.stroke();
  }
  g.setLineDash([]);
}
function wCaps(t) { return /[ıİşŞğĞçÇöÖüÜ]/.test(t) ? t.toLocaleUpperCase('tr') : t.toUpperCase(); }   // (art.py caps)
function wLabel(g, lab) {
  const size = W_LABEL[lab.size] || 16, style = lab.style;
  g.save(); g.translate(lab.x, lab.y); g.rotate((+lab.angle || 0) * Math.PI / 180); g.scale(+lab.s || 1, +lab.s || 1);
  const pale = style === 'sea' && wPainted();           // the painted look's sea names: pale on the dark water
  if (style === 'banner' || style === 'plaque') {       // dark letters on a ribbon or a tag (art.py paint_ribbon, paint_plaque)
    const fs = size * 0.8, text = wCaps(lab.text);
    g.font = wFont(fs, false, true);
    if ('letterSpacing' in g) g.letterSpacing = (0.12 * fs * 0.55).toFixed(2) + 'px';
    const tw = g.measureText(text).width;
    (style === 'banner' ? wRibbon : wPlaque)(g, -tw / 2, size * 0.35 - fs * 0.72, tw, fs * 0.72);
    wText(g, text, 0, size * 0.35, fs, { align: 'center', bold: true, spacing: 0.12, color: '#3a281a', noHalo: true, haloRGB: W_PAPER });
    g.restore();
    return;
  }
  if (style === 'title') {                               // the map's name with flourishes either side (art.py paint_flourish)
    const fs = size * 1.5, text = wCaps(lab.text);
    g.font = wFont(fs, false, true, W_TITLING);
    if ('letterSpacing' in g) g.letterSpacing = (0.18 * fs * 0.55).toFixed(2) + 'px';
    const tw = g.measureText(text).width, h = fs * 0.72, cy = size * 0.35 - h / 2;
    for (const side of [-1, 1]) {
      const x0 = side < 0 ? -tw / 2 - h * 0.35 : tw / 2 + h * 0.35, x1 = x0 + side * h * 2.6;
      const pair = wPainted() ? ['rgb(26,20,14)', 'rgb(244,236,216)'] : [W_PAPER + '1)', W_INK];   // (as the letters)
      for (const [color, width] of [[pair[0], h * 0.12], [pair[1], 0]]) {
        g.fillStyle = color; g.strokeStyle = color; g.lineWidth = width; g.lineJoin = 'round';
        g.beginPath(); g.moveTo(x0, cy - h * 0.035); g.lineTo(x1, cy); g.lineTo(x0, cy + h * 0.035); g.closePath();
        g.moveTo(x0 + side * h * 0.9, cy - h * 0.16); g.lineTo(x0 + side * h * 1.12, cy); g.lineTo(x0 + side * h * 0.9, cy + h * 0.16);
        g.lineTo(x0 + side * h * 0.68, cy); g.closePath();
        g.moveTo(x1 + side * h * 0.18 + h * 0.06, cy); g.arc(x1 + side * h * 0.18, cy, h * 0.06, 0, Math.PI * 2);
        if (width) g.stroke(); g.fill();
      }
    }
    wText(g, text, 0, size * 0.35, fs, { align: 'center', bold: true, spacing: 0.18, face: W_TITLING, color: W_INK, halo: Math.max(2, size * 0.22),
      haloA: 0.82 });
    g.restore();
    return;
  }
  const text = style === 'sea' ? lab.text : wCaps(lab.text), opts = {
    align: 'center', italic: style === 'sea', bold: style === 'region', spacing: style === 'sea' ? 0.14 : style === 'region' ? 0.32 : 0.1,
    face: style === 'region' ? W_TITLING : null,
    color: pale ? 'rgb(230,238,234)' : style === 'sea' ? W_SEA_INK : style === 'region' ? (wPainted() ? 'rgba(58,40,26,.6)' : 'rgba(58,40,26,.78)') : W_INK,
    halo: Math.max(2, size * (pale ? 0.18 : 0.16)), haloA: style === 'sea' ? 0.6 : 0.75, haloRGB: pale ? 'rgba(14,28,38,' : null };
  if (+lab.bend) wBent(g, text, size * 0.35, size, opts, +lab.bend);
  else wText(g, text, 0, size * 0.35, size, opts);
  g.restore();
}
function wBarMiles(mpp, w) {                           // a round number of miles, about a sixth of the map (art.py bar_miles)
  const want = mpp * w / 6, k = Math.pow(10, Math.floor(Math.log10(want)));
  return Math.max(...[1, 2, 5, 10].map(n => n * k).filter(v => v <= want));
}
function wScaleBar(g, mpp, w, h) {                     // a bar of miles in the bottom left corner (art.py paint_scale_bar)
  if (!mpp) return;
  const miles = wBarMiles(mpp, w), len = miles / mpp, x = 34, y = h - 30, bh = 3.4;
  const dark = wPainted() ? 'rgb(30,24,18)' : W_INK, light = wPainted() ? 'rgb(240,232,212)' : W_PAPER + '1)';
  g.setLineDash([]); g.lineWidth = 0.7; g.strokeStyle = dark;
  for (let i = 0; i < 4; i++) { g.fillStyle = i % 2 ? light : dark; g.fillRect(x + len * i / 4, y, len / 4, bh); g.strokeRect(x + len * i / 4, y, len / 4, bh); }
  wText(g, '0', x, y + bh + 8.5, 7.5, { align: 'center', bold: true, halo: 2 });
  wText(g, S('{0} mi', miles), x + len, y + bh + 8.5, 7.5, { align: 'center', bold: true, halo: 2 });
}
function wGrid(g, grid, w, h) {                       // a faint grid over the map: hexes or squares (art.py paint_grid)
  if (!grid) return;
  const px = +grid.px;
  g.save(); g.beginPath(); g.rect(0, 0, w, h); g.clip();
  g.strokeStyle = wPainted() ? 'rgba(250,244,226,.24)' : 'rgba(58,40,26,.22)'; g.lineWidth = 0.6; g.setLineDash([]);
  g.beginPath();
  if (grid.kind === 'square') {
    for (let x = px; x <= w; x += px) { g.moveTo(x, 0); g.lineTo(x, h); }
    for (let y = px; y <= h; y += px) { g.moveTo(0, y); g.lineTo(w, y); }
  } else {
    const r = px / Math.sqrt(3);
    for (let row = 0; row < h / (1.5 * r) + 2; row++) {
      const cy = row * 1.5 * r, off = (row % 2) * px / 2;
      for (let c = -1; c < w / px + 2; c++) {
        const cx = c * px + off;
        [90, 150, 210, 270].forEach((a, i) => {
          const x = cx + Math.cos(a * Math.PI / 180) * r, y = cy + Math.sin(a * Math.PI / 180) * r;
          if (i) g.lineTo(x, y); else g.moveTo(x, y);
        });
      }
    }
  }
  g.stroke(); g.restore();
}
function wPlaque(g, rx, ry, rw, rh) {                // a parchment tag behind letters in the box (art.py paint_plaque)
  const px = rh * 0.9, py = rh * 0.55, x0 = rx - px, y0 = ry - py, w = rw + 2 * px, h = rh + 2 * py, c = h * 0.22;
  const cut = (x, y, ww, hh, k) => { g.beginPath(); g.moveTo(x + k, y); g.lineTo(x + ww - k, y); g.lineTo(x + ww, y + k); g.lineTo(x + ww, y + hh - k);
    g.lineTo(x + ww - k, y + hh); g.lineTo(x + k, y + hh); g.lineTo(x, y + hh - k); g.lineTo(x, y + k); g.closePath(); };
  cut(x0 + h * 0.06, y0 + h * 0.09, w, h, c); g.fillStyle = 'rgba(0,0,0,.27)'; g.fill();
  cut(x0, y0, w, h, c);
  const gr = g.createLinearGradient(0, y0, 0, y0 + h); gr.addColorStop(0, 'rgb(240,226,190)'); gr.addColorStop(1, 'rgb(206,184,140)');
  g.fillStyle = gr; g.fill(); g.lineJoin = 'round'; g.lineWidth = h * 0.07; g.strokeStyle = 'rgb(58,40,26)'; g.stroke();
  const k = h * 0.12; cut(x0 + k, y0 + k, w - 2 * k, h - 2 * k, c * 0.7); g.lineWidth = h * 0.03; g.strokeStyle = 'rgb(150,120,80)'; g.stroke();
}
function wRibbon(g, rx, ry, rw, rh) {                // a ribbon banner behind letters in the box (rx, ry, rw, rh)
  const h = rh * 1.7, pad = h * 0.7, x0 = rx - pad, x1 = rx + rw + pad, cy = ry + rh / 2, bow = h * 0.12;
  g.lineJoin = 'round'; g.strokeStyle = 'rgb(58,40,26)'; g.lineWidth = h * 0.05;
  for (const side of [-1, 1]) {                         // the folded ends, behind and below the band
    const xe = side < 0 ? x0 : x1;
    g.beginPath(); g.moveTo(xe - side * h * 0.1, cy - h * 0.2); g.lineTo(xe + side * h * 0.95, cy + h * 0.05);
    g.lineTo(xe + side * h * 0.65, cy + h * 0.55); g.lineTo(xe + side * h * 0.95, cy + h * 1.05); g.lineTo(xe - side * h * 0.1, cy + h * 0.8);
    g.closePath(); g.fillStyle = 'rgb(186,160,112)'; g.fill(); g.stroke();
  }
  g.beginPath(); g.moveTo(x0, cy - h / 2); g.quadraticCurveTo((x0 + x1) / 2, cy - h / 2 - bow * 2, x1, cy - h / 2);
  g.lineTo(x1, cy + h / 2); g.quadraticCurveTo((x0 + x1) / 2, cy + h / 2 - bow * 2, x0, cy + h / 2); g.closePath();
  const gr = g.createLinearGradient(0, cy - h / 2, 0, cy + h / 2); gr.addColorStop(0, 'rgb(236,218,176)'); gr.addColorStop(1, 'rgb(186,160,112)');
  g.fillStyle = gr; g.fill(); g.stroke();
  g.strokeStyle = 'rgb(186,160,112)'; g.lineWidth = h * 0.03;
  for (const k of [-1, 1]) {
    g.beginPath(); g.moveTo(x0 + h * 0.15, cy + k * h * 0.36); g.quadraticCurveTo((x0 + x1) / 2, cy + k * h * 0.36 - bow * 2, x1 - h * 0.15, cy + k * h * 0.36); g.stroke();
  }
}
function wBent(g, text, y0, size, opts, bend) {     // a name bowed along an arc of `bend` degrees, letter by letter (art.py bend_path)
  g.font = wFont(size, opts.italic, opts.bold, opts.face);
  if ('letterSpacing' in g) g.letterSpacing = ((opts.spacing || 0) * size * 0.55).toFixed(2) + 'px';
  const ws = [...text].map(c => g.measureText(c).width), total = ws.reduce((a, b) => a + b, 0);
  const sign = bend > 0 ? 1 : -1, radius = total / (Math.abs(bend) * Math.PI / 180), d = radius - sign * (y0 - size * 0.35);
  let x = -total / 2;
  [...text].forEach((c, i) => {
    const a = (x + ws[i] / 2) / radius;
    g.save(); g.translate(Math.sin(a) * d, sign * (radius - Math.cos(a) * d)); g.rotate(sign * a);
    wText(g, c, 0, size * 0.35, size, Object.assign({}, opts, { align: 'center' }));
    g.restore();
    x += ws[i];
  });
}
function wLine(g, pts) { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke(); }
function wParty(g, pos, k) {
  const [x, y] = pos, s = Math.max(0.6, Math.min(2.6, k * 0.95));
  g.setLineDash([]); g.lineWidth = 1.1 * s; g.strokeStyle = '#1e120a';
  wCircle(g, x, y, 4.2 * s); g.fillStyle = 'rgba(236,222,184,.86)'; g.fill(); g.stroke();
  wCircle(g, x, y, 2 * s); g.fillStyle = W_PARTY; g.fill(); g.stroke();
  g.lineWidth = 1.3 * s; g.lineCap = 'round'; wLine(g, [[x, y - 2 * s], [x, y - 20 * s]]);
  g.beginPath(); g.moveTo(x, y - 20 * s);
  g.bezierCurveTo(x + 5 * s, y - 22 * s, x + 8 * s, y - 17 * s, x + 13 * s, y - 18 * s);
  g.lineTo(x + 9 * s, y - 15 * s); g.lineTo(x + 13 * s, y - 12 * s);
  g.bezierCurveTo(x + 8 * s, y - 11 * s, x + 5 * s, y - 15 * s, x, y - 13 * s); g.closePath();
  g.fillStyle = W_PARTY; g.fill(); g.lineWidth = 0.8 * s; g.stroke();
}
function wRoute(g, pos, route, k, text) {
  const pts = (pos ? [pos] : []).concat(route);
  if (pts.length < 2) return;
  g.strokeStyle = W_ROUTE; g.lineWidth = 1.8; g.setLineDash([4 * 1.8, 2.6 * 1.8]); g.lineCap = 'round';
  wLine(g, pts); g.setLineDash([]);
  g.lineWidth = 1;
  for (const p of route.slice(0, -1)) { wCircle(g, p[0], p[1], 2.4); g.fillStyle = W_PAPER + '1)'; g.fill(); g.stroke(); }
  const [[ax, ay], [bx, by]] = pts.slice(-2), a = Math.atan2(by - ay, bx - ax);
  g.beginPath(); g.moveTo(bx, by); g.lineTo(bx - Math.cos(a - 0.45) * 8, by - Math.sin(a - 0.45) * 8); g.lineTo(bx - Math.cos(a + 0.45) * 8, by - Math.sin(a + 0.45) * 8);
  g.closePath(); g.fillStyle = W_ROUTE; g.fill();
  if (text) wText(g, text, bx + 9 * k, by - 7 * k, 13 * k, { bold: true, color: W_ROUTE, halo: 3.5 * k });
}
function wPing(g, p, age, k) {
  const t = Math.max(0, Math.min(1, age / W_PING_LIFE));
  for (let i = 0; i < 3; i++) {
    const tt = t - i * 0.18;
    if (tt <= 0 || tt >= 1) continue;
    g.strokeStyle = `rgba(250,204,21,${(1 - tt) * 0.95})`; g.lineWidth = 2.4 * k;
    wCircle(g, p.x, p.y, (4 + tt * 34) * k); g.stroke();
  }
  wCircle(g, p.x, p.y, 3.2 * k); g.fillStyle = `rgba(250,204,21,${1 - t})`; g.fill(); g.lineWidth = k; g.strokeStyle = '#1e120a'; g.stroke();
  if (p.who && t < 0.85) wText(g, p.who, p.x, p.y - 9 * k, 12 * k, { align: 'center', bold: true, color: `rgba(30,18,10,${1 - t})`, halo: 3 * k, haloA: 0.8 * (1 - t) });
}
// The lines, marks and names change only when the DM sends the map again: they are drawn once onto a layer of
// their own (the whole sheet, up to W_LAYER_MAX canvas pixels a map pixel) and each frame just draws that layer.
const W_LAYER_MAX = 4;
function wLayer(map, want) {
  const key = map.id + ':' + map.v + ':' + (WM.layerVer || 0), lay = WM.layer;
  if (lay && lay.key === key && lay.scale >= want) return lay;
  if (lay && lay.key === key && !WM.layerSharp) {         // zoomed in: drawn sharper once the zoom rests
    clearTimeout(WM.layerWait);
    WM.layerWait = setTimeout(() => { WM.layerSharp = true; drawWorld(); }, 180);
    return lay;
  }
  WM.layerSharp = false;
  const scale = Math.max(1, want), cv = document.createElement('canvas');
  cv.width = Math.ceil(map.w * scale); cv.height = Math.ceil(map.h * scale);
  const g = cv.getContext('2d');
  g.scale(scale, scale);
  wGrid(g, map.grid, map.w, map.h);
  for (const ln of map.lines || []) if (ln.pts && ln.pts.length > 1) wDrawnLine(g, ln);   // (sent bottom to top)
  wMarks(g, map.marks.slice().sort((a, b) => a.y - b.y));
  for (const lab of map.labels) wLabel(g, lab);
  wScaleBar(g, map.scale_bar, map.w, map.h);
  WM.layer = { cv, key, scale };
  return WM.layer;
}
function drawWorld() {
  if (!ST || !WM.built || mapMode() !== 'world') return;
  const cv = $('wboard'), wrap = $('worldwrap'), W = ST.world;
  const vw = wrap.clientWidth, vh = Math.max(200, wrap.clientHeight), dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(vw * dpr) || cv.height !== Math.round(vh * dpr)) {
    cv.width = Math.round(vw * dpr); cv.height = Math.round(vh * dpr); cv.style.width = vw + 'px'; cv.style.height = vh + 'px';
  }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const bg = g.createLinearGradient(0, 0, 0, vh); bg.addColorStop(0, '#1e1813'); bg.addColorStop(1, '#100d0b');
  g.fillStyle = bg; g.fillRect(0, 0, vw, vh);
  if (!W.map) return;
  const c = wCam(), [w, h_] = wSize(), k = 1 / c.z;
  g.translate(c.x, c.y); g.scale(c.z, c.z);
  g.fillStyle = 'rgba(0,0,0,.28)'; g.fillRect(6, 8, w, h_);
  if (WM.img) { g.imageSmoothingQuality = 'high'; g.drawImage(WM.img, 0, 0, w, h_); }
  else { g.fillStyle = '#e1cca0'; g.fillRect(0, 0, w, h_); }
  const lay = wLayer(W.map, Math.min(W_LAYER_MAX, Math.ceil(c.z * dpr - 0.1)));   // the lines, marks and names: drawn once
  g.drawImage(lay.cv, 0, 0, w, h_);
  const p = W.party, gl = WM.glide, go = wGlideNow(), at = go ? go[0] : p.pos;
  const trail = !go ? p.trail.concat(p.pos ? [p.pos] : [])
    : gl.back ? p.trail.concat(go[2].slice().reverse())                                   // taken back: it shrinks behind the banner
      : p.trail.slice(0, Math.max(1, p.trail.length - (gl.pts.length - 1))).concat(go[1]);
  if (trail.length > 1) { g.strokeStyle = 'rgba(150,40,28,.75)'; g.lineWidth = 1.6; g.setLineDash([1.2 * 1.6, 2.2 * 1.6]); g.lineCap = 'round'; wLine(g, trail); g.setLineDash([]); }
  wRoute(g, at, p.route, k, W.route.miles ? S('{0} mi · {1} d', Math.round(W.route.miles), W.route.days) : '');
  if (at) wParty(g, at, k);
  const now = performance.now() / 1000;
  for (const pg of WM.pings) wPing(g, pg, now - pg.at, k);
}
