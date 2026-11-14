// The player side of the table: the battle map, your character sheet (the same tabs as the DM's editor) and the
// table feed - rolls and chat, synced with the DM and the other players - with a line for chat and /commands.
// Every word on the page is S('English text'): the server sends the translations (app/locale CSVs), so the
// strings live in one place; the server finds the S('...') literals in this file by itself.
'use strict';
const KEY = (() => {
  const q = new URLSearchParams(location.search).get('k');
  try {
    const k = q || localStorage.getItem('dm_key') || localStorage.getItem('dp_key') || '';   // dp_key: before the rename
    if (k) localStorage.setItem('dm_key', k);
    localStorage.removeItem('dp_key');
    return k;
  } catch { return q || ''; }
})();
if (new URLSearchParams(location.search).get('k')) history.replaceState(null, '', '/');
const $ = id => document.getElementById(id);
const store = (k, v) => { try {   // dp_: what a browser kept before the rename, read until it is written again
  if (v === undefined) return JSON.parse(localStorage.getItem('dm_' + k) ?? localStorage.getItem('dp_' + k));
  localStorage.setItem('dm_' + k, JSON.stringify(v)); localStorage.removeItem('dp_' + k);
} catch { return null; } };
const FOLDS = new Set(store('folds') || []);   // the categories folded away on this device: spell levels, feature sources, action groups
const folded = k => FOLDS.has(k);
const flipFold = (k, redraw) => { FOLDS.has(k) ? FOLDS.delete(k) : FOLDS.add(k); store('folds', [...FOLDS]); redraw(); };
// a category's heading that folds it away: ▾/▸, its name and how many it holds (Enter or Space from the keyboard too)
const foldHead = (k, text, n, redraw) => h('span', { class: 'fold', role: 'button', tabindex: 0, 'aria-expanded': String(!folded(k)),
  onclick: () => flipFold(k, redraw), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flipFold(k, redraw); } } },
  h('span', { class: 'arw' }, folded(k) ? '▸' : '▾'), text, n != null ? h('span', { class: 'cnt' }, `(${n})`) : null);
const UI = { tab: store('tab') || 'overview', view: 'map', adv: '', target: null, inspect: null, cam: null, camFit: null, feed: store('feed') || 'all',
  open: new Set(), slot: '', amount: '', drag: null, ghost: null, move: null, tile: 32, local: [], editNote: store('editnote'),
  noteDraft: store('notedraft') || '', editDraft: store('editdraft') || {}, spellsOpen: !!store('spells'), mute: !!store('mute'),
  notify: !!store('notify'), seenFeed: null, coin: 'gp', coinAmt: '', quick: {},
  tnEdit: store('tnedit'), tnDraft: store('tndraft') || { title: '', text: '' }, tnOpen: null };
let ST = null;
let WORDS = {}, wordsLang = null;                     // the page's words in the player's language (sent on demand)
let UICONS = {};                                      // the page's own buttons: key -> picture (icons.UI, sent with the words)
let CONDS = {};                                       // condition name (in my language) -> its rules: hover in the feed
const imgs = {};
const TOUCH = matchMedia('(pointer:coarse)'), CALM = matchMedia('(prefers-reduced-motion: reduce)'), NARROW = matchMedia('(max-width:900px)');
const touch = () => TOUCH.matches;
let lastPointer = 'mouse';
document.addEventListener('pointerdown', e => { lastPointer = e.pointerType || 'mouse'; }, true);

// ---------------------------------------------------------------- helpers
function S(key, ...args) {
  let t = WORDS[key] || key;
  args.forEach((a, i) => { t = t.split(`{${i}}`).join(a); });
  return t;
}
const PLAIN = /^(BUTTON|A|INPUT|SELECT|TEXTAREA|LABEL|OPTION|SUMMARY)$/;
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props && props.tip) hold(el, () => detail(props.tip, props.more));    // touch: hold for the text (and its actions)
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false || k === 'more') continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'tip') {
      el.addEventListener('mouseover', e => { if (lastPointer === 'mouse' && e.target.closest('[data-tip]') === el) tip({ clientX: e.clientX, clientY: e.clientY, currentTarget: el }, v); });
      el.addEventListener('mouseleave', () => tip());
      el.setAttribute('data-tip', '');
    }
    else if (k === 'value') el.value = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  if (props && props.onclick && !PLAIN.test(el.tagName)) {       // clickable, not a button: reachable by keyboard too
    if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
    el.tabIndex = 0;
    el.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === el && !e.ctrlKey) { e.preventDefault(); el.click(); } });
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
/** A button that does something slow: disabled (with a small spinner) until the promise its handler returns settles. */
function busyWhile(b, p) {
  if (!b || !p || typeof p.then !== 'function') return p;
  b.classList.add('wait'); b.setAttribute('aria-busy', 'true');
  return p.finally(() => { b.classList.remove('wait'); b.removeAttribute('aria-busy'); });
}
const go = fn => e => { const b = e.currentTarget; if (b && b.classList && b.classList.contains('wait')) return null; return busyWhile(b, fn(e)); };
const btn = (text, fn, cls = 'sm', tipText, more) => h('button', { class: cls, onclick: go(fn), tip: tipText, more }, text);
/** A picture from icons.UI (or a picture's own name, or a condition), tinted by the text colour (CSS mask). */
const gi = (key, cls = '') => h('span', { class: 'gi ' + cls, 'aria-hidden': 'true',
  style: `--gi:url(/icon/${UICONS[key] || ((ST && ST.battle.badge_look || {})[key] || [])[0] || key}.webp)` });
/** An icon button: the picture, its words on hover (and in aria-label), `cls` colours it (danger, good, warn...). */
const ibtn = (key, words, fn, cls = '', more, count) => h('button',
  { class: 'ib ' + cls, onclick: go(fn), tip: words, more, 'aria-label': words.split('\n')[0] }, gi(key),
  count != null ? h('span', { class: 'ct' }, count) : null);
/** Touch screens have no hover: holding a finger on something opens its text in a sheet (the click is then skipped). */
function hold(el, fn) {
  let timer = 0, at = null;
  const stop = () => { clearTimeout(timer); timer = 0; };
  el.addEventListener('click', e => { if (el._held && Date.now() - el._held < 900) { el._held = 0; e.preventDefault(); e.stopImmediatePropagation(); } }, true);
  el.addEventListener('pointerdown', e => {
    if (e.pointerType === 'mouse') return;
    at = [e.clientX, e.clientY]; stop();
    timer = setTimeout(() => { timer = 0; el._held = Date.now(); try { navigator.vibrate && navigator.vibrate(12); } catch { /* none */ } fn(); }, 480);
  });
  el.addEventListener('pointermove', e => { if (timer && at && Math.hypot(e.clientX - at[0], e.clientY - at[1]) > 10) stop(); });
  for (const k of ['pointerup', 'pointercancel', 'pointerleave']) el.addEventListener(k, stop);
  el.addEventListener('contextmenu', e => { if (lastPointer !== 'mouse') e.preventDefault(); });
}
/** The detail sheet (a bottom sheet on phones): a text or an action card, and buttons [label, fn, class]; `gone()` runs
 *  when it closes without a button picked (✕, Escape, a tap beside it, another sheet in its place). */
let detailGone = null;
const dismissed = () => { const g = detailGone; detailGone = null; if (g) g(); };
function detail(v, more, gone) {
  tip();
  dismissed();
  const el = $('detail'), back = document.activeElement;
  const close = picked => {
    el.classList.add('hide'); el.replaceChildren();
    if (picked) detailGone = null; else dismissed();
    if (back && back.focus && document.contains(back)) back.focus({ preventScroll: true });
  };
  detailGone = gone || null;
  const lines = typeof v === 'function' ? null : String(v).split('\n');      // like the hover tips: a short first line is the title
  const body = typeof v === 'function' ? v() : lines.length > 1 && lines[0].length < 60
    ? h('div', { class: 'txt' }, h('b', null, lines[0]), '\n' + lines.slice(1).join('\n')) : h('div', { class: 'txt' }, v);
  const acts = (more ? more() : []).filter(Boolean);
  el.replaceChildren(h('div', { class: 'box', role: 'dialog', 'aria-modal': 'true', 'aria-label': S('Details') },
    h('div', { class: 'dh' }, h('span', { class: 'grow' }), btn('✕', () => close(), 'sm flat', null)), body,
    acts.length ? h('div', { class: 'row' }, ...acts.map(([label, fn, cls]) => btn(label, () => { close(true); return fn(); }, cls || 'primary'))) : null));
  el.onclick = e => { if (e.target === el) close(); };
  el.classList.remove('hide');
  const first = el.querySelector('.row button') || el.querySelector('button');
  if (first) first.focus({ preventScroll: true });
}
/** Ask before something that can't be taken back, in the page's own sheet (not the browser's box): yes runs fn. */
const ask = (question, yes, fn, cls = 'primary') => { detail(question, () => [[yes, fn, cls], [S('Cancel'), () => null, 'flat']]); return null; };
const closeDetail = () => { if (!$('detail').classList.contains('hide')) { $('detail').classList.add('hide'); $('detail').replaceChildren(); dismissed(); return true; } return false; };
function rich(text) {
  const out = h('span', { class: 'x' });
  String(text || '').split('\n').forEach((line, i) => {
    if (i) out.append(h('br'));
    line.split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach(p => p.startsWith('**') && p.endsWith('**')
      ? out.append(h('b', CONDS[p.slice(2, -2)] ? { class: 'rl', tip: `${p.slice(2, -2)}\n${CONDS[p.slice(2, -2)]}` } : null, p.slice(2, -2)))   // a condition: its rules on hover
      : p.length > 1 && p.startsWith('`') && p.endsWith('`') ? out.append(h('span', { class: 'itm' }, p.slice(1, -1)))   // `an item`
      : out.append(p.replace(/\*([^*]+)\*/g, '$1').replace(/`/g, '')));
  });
  return out;
}
const sign = n => (n >= 0 ? '+' : '') + n;
const pips = (left, total) => '●'.repeat(Math.max(0, left)) + '○'.repeat(Math.max(0, total - left));
function tip(e, text) {
  let t = $('tip');
  if (!e || !text) { if (t) t.remove(); UI.tipFor = null; return; }
  if (!t) { t = h('div', { id: 'tip' }); document.body.append(t); }
  const card = typeof text === 'function';                 // an action's hover card (a builder), or plain text
  t.classList.toggle('card', card);
  const lines = card ? null : String(text).split('\n');   // several lines: the first is the tip's title
  if (card) t.replaceChildren(text()); else if (lines.length > 1 && lines[0].length < 60) t.replaceChildren(h('b', null, lines[0]), '\n' + lines.slice(1).join('\n'));
  else t.textContent = text;
  t.setAttribute('role', 'tooltip');
  if (card) {                                              // above the button, like a game's action bar
    const r = e.currentTarget && e.currentTarget.getBoundingClientRect ? e.currentTarget.getBoundingClientRect() : { left: e.clientX, top: e.clientY, bottom: e.clientY };
    const x = Math.max(4, Math.min(r.left - 4, innerWidth - t.offsetWidth - 6));
    const y = r.top - t.offsetHeight - 8 > 4 ? r.top - t.offsetHeight - 8 : r.bottom + 8;
    t.style.left = x + 'px'; t.style.top = y + 'px';
    return;
  }
  const x = Math.min(e.clientX + 14, innerWidth - 370), y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 10);
  t.style.left = x + 'px'; t.style.top = Math.max(4, y) + 'px';
}

// ---------------------------------------------------------------- talking to the table
// The connection: live, reconnecting (the table doesn't answer), or closed (gone for a while: the DM stopped sharing,
// and the next session's address is a new one). Proxies (Cloudflare) answer 502-504 / 52x / 530 when the app is away.
const NET = { state: 'live', down: 0, busy: 0 }, CLOSED_AFTER = 45000;
const PAGE = Math.random().toString(36).slice(2, 12);   // this page, to the table: its stream knows what the page loaded
const AWAY = s => s === 502 || s === 503 || s === 504 || (s >= 520 && s <= 530);
async function api(path, body, more) {
  if (body && path === '/api/act' && typeof bgPlay === 'function') body = bgPlay(body);   // on a lobby's map: acts on that lobby (battlegrounds.js)
  let r;
  try {
    r = await fetch(path, { method: body ? 'POST' : 'GET', headers: { 'X-Key': KEY, 'X-Page': PAGE, 'Content-Type': 'application/json', ...more },
      body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
  } catch {
    offline(); throw new Error(navigator.onLine === false ? S('You are offline - check your connection.') : S("Can't reach the table right now - reconnecting…"));
  }
  const d = await r.json().catch(() => ({}));
  if (AWAY(r.status)) { offline(); throw new Error(S("The table isn't answering - the DM's app may be closed.")); }
  online();
  if (r.status === 403) { gate(S("This link isn't valid any more. Ask your DM for a new one.")); throw new Error('login'); }
  if (r.status === 429) throw new Error(S('Slow down a little.'));
  if (r.status >= 500) throw new Error(S('Something went wrong at the table. Try again.'));
  if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}
function online() {
  if (NET.state === 'live') return;
  NET.state = 'live'; NET.down = 0; conn(); refresh(); tokenRetry(true);   // (pictures that failed while it was down)
}
function offline() {
  if (!NET.down) NET.down = Date.now();
  const s = Date.now() - NET.down > CLOSED_AFTER ? 'closed' : 'retry';
  if (s !== NET.state) { NET.state = s; conn(); }
}
/** The status pill in the header (live / reconnecting / closed), the closed-table banner, buttons off while away. */
function conn() {
  const el = $('conn'), s = NET.state;
  el.className = `conn ${s}${NET.busy > 0 && s === 'live' ? ' busy' : ''}`;
  el.replaceChildren(h('i'), h('span', null, { live: NET.busy > 0 ? S('Working…') : S('Live'), retry: S('Reconnecting…'), closed: S('Table closed') }[s]));
  el.title = { live: S('Connected to the table'), retry: S("Can't reach the table right now - reconnecting…"), closed: S('The table is closed - ask your DM for a new link.') }[s];
  document.body.classList.toggle('offline', s !== 'live');
  $('closed').classList.toggle('hide', s !== 'closed');
  $('closed').replaceChildren(h('b', null, S('The table is closed - ask your DM for a new link.')), ' ',
    h('span', { class: 'dim' }, S('This page keeps trying to reconnect.')));
}
function gate(text) {
  $('gatetext').textContent = text;
  $('gatemore').textContent = S("The table's address changes every session, so old links stop working. Ask your DM for today's link.");
  $('gate').classList.remove('hide');
}
function say(text, err) {
  if (!text) return;
  const d = h('div', { class: err ? 'err' : '' }, rich(text));
  $('results').prepend(d);
  while ($('results').children.length > 3) $('results').lastChild.remove();
  setTimeout(() => d.remove(), err ? 7000 : 5000);
}
const inflight = new Set();
const ADV_ONCE = new Set(['check', 'save', 'attack', 'cast', 'initiative']);      // advantage is for one roll
/** Do something at the table. The same action with the same details can't be sent twice while the first is on its way.
 *  opts.adv: this action rolls (advantage, if set, is used up). */
async function act(action, args = {}, quiet = false, opts = {}) {
  if (NET.state !== 'live') { say(S('Not connected to the table right now.'), true); return null; }
  const key = action + JSON.stringify(args);
  if (inflight.has(key)) return null;
  inflight.add(key); NET.busy++; conn();
  try {
    const r = await api('/api/act', { action, character: ST && ST.me.active, adv: UI.adv, target: UI.target, ...args });
    if (!quiet) say(r.text);
    if (UI.adv && (ADV_ONCE.has(action) || opts.adv)) UI.adv = '';
    if (!(await pushedBy(r.v))) await load();       // the live stream brings the new state (no request of its own)
    return r;
  } catch (e) { if (e.message !== 'login') say(e.message, true); return null; }
  finally { inflight.delete(key); NET.busy--; conn(); }
}
/** One state download at a time; asked again meanwhile: once more afterwards. The words come only when needed.
 *  parts: only these parts of the state (what a change touched; the page keeps the rest), none: everything. */
let loading = null, again = false;
const DIRTY = new Set();                 // parts a change touched that the page hasn't reloaded yet ('all': everything)
let PRINTS = {};                         // fingerprint of every part (and battle key) the page holds, from the server
function load(parts) {
  for (const p of parts || ['all']) DIRTY.add(p);
  if (loading) { again = true; return loading; }
  loading = (async () => {
    try { do { again = false; await load1(); } while (again); } finally { loading = null; }
  })();
  return loading;
}
async function load1() {
  const ask = wordsLang === null;
  const full = !ST || ask || DIRTY.has('all');
  const parts = full ? [] : [...DIRTY];
  DIRTY.clear();
  const q = [ask ? 'strings=1' : '', parts.length ? 'parts=' + parts.join(',') : ''].filter(Boolean).join('&');
  // what the page holds, by fingerprint: the server leaves out every part (and battle key) that is still the same
  const have = ST && !ask ? Object.entries(PRINTS).map(([k, h]) => k + '=' + h).join(',') : '';
  let st;
  try { st = await api('/api/state' + (q ? '?' + q : ''), undefined, have ? { 'X-Have': have } : {}); }
  catch (e) { for (const p of full ? ['all'] : parts) DIRTY.add(p); throw e; }       // not lost: the next load asks again
  if (st.strings) { WORDS = st.strings; wordsLang = st.me.lang; UICONS = st.ui_icons || UICONS; CONDS = st.conditions || CONDS; }
  else if (!ask && st.me.lang !== wordsLang) { wordsLang = null; DIRTY.add('all'); return load1(); }      // the language changed
  if (!merge(st, full)) { DIRTY.add('all'); return load1(); }
}
/** Each part's newest version on the page: an answer older than what a part already shows leaves that part alone
 *  (a pushed state and a requested one may cross on the way). */
let PARTV = {};
/** Merge a state (asked for or pushed) into the page's; false: it said "unchanged" of something the page lacks (a
 *  pushed state names each unchanged unit with its fingerprint: one the page holds differently counts as lacking). */
function merge(st, full) {
  const shown = ST && ST.battle;                       // the battle the page showed (on the Battlegrounds face a lobby's: battlegrounds.js)
  if (typeof bgUnswap === 'function') bgUnswap();      // (the campaign's battle back in its place while the parts merge)
  const was = ST, prints = st.prints || {}, sameIn = st.same || [], v = st.v || 0;
  const same = Array.isArray(sameIn) ? new Set(sameIn) : new Set(Object.keys(sameIn));
  delete st.prints; delete st.same;
  for (const p of (full ? [] : st.parts || [])) {      // a part older than the page's: kept as the page has it
    if (was && p in was && (PARTV[p] || 0) > v) {
      delete st[p];
      for (const k of [...same]) if (k === p || k.startsWith(p + '.')) same.delete(k);
      for (const k of Object.keys(prints)) if (k === p || k.startsWith(p + '.')) delete prints[k];
    }
  }
  const next = { ...(full ? {} : ST), ...st };
  let lost = false;
  for (const k of same) {                              // unchanged: kept from what the page has
    if (!Array.isArray(sameIn) && PRINTS[k] !== sameIn[k]) { lost = true; break; }
    const [part, key] = k.split('.');
    if (!key) { if (was && part in was) next[part] = was[part]; else lost = true; }
    else if (next[part] && was && was[part] && key in was[part]) next[part][key] = was[part][key];
    else lost = true;
  }
  if (lost) { if (typeof bgSwap === 'function') bgSwap(); PRINTS = {}; PARTV = {}; return false; }
  if (!was) PRINTS = {};
  Object.assign(PRINTS, prints);                       // (only what came: the rest the page kept, prints and all)
  for (const p of (full ? Object.keys(next) : st.parts || [])) if (p in st) PARTV[p] = Math.max(PARTV[p] || 0, v);
  ST = next;
  ST.fullV = full ? v : (was && was.fullV) || 0;        // everything is at least this new
  ST.pv = Math.max((was && was.pv) || 0, v);            // the newest change merged
  if (typeof bgSwap === 'function') bgSwap();
  render();
  alerts(was && { ...was, battle: shown });
  for (const w of [...PUSHWAIT]) if (ST.pv >= w.v) { PUSHWAIT.delete(w); w.done(true); }
  return true;
}
/** The stream pushes each change's state (server: _stream push); LIVE.at: when it was last heard from (its
 *  keep-alives too), so the page asks for nothing itself while it is. */
const LIVE = { push: false, at: 0, state: 0 };    // state: when a pushed state last came
const pushLive = () => LIVE.push && Date.now() - LIVE.at < 25000;
const PUSHWAIT = new Set();
/** After an action (its reply's v: the change it made): true once the pushed state has it, false when the stream
 *  isn't pushing or is late (the page then asks itself). */
function pushedBy(v) {
  if (!v || (ST && (ST.pv || 0) >= v)) return Promise.resolve(!!v && pushLive());
  if (!pushLive()) return Promise.resolve(false);
  return new Promise(done => {
    const w = { v, done };
    PUSHWAIT.add(w);
    setTimeout(() => { if (PUSHWAIT.delete(w)) done(false); }, 2500);
  });
}
function pushed(st) {
  LIVE.at = Date.now();
  if (st.reload || !ST || loading || wordsLang === null || st.me.lang !== wordsLang) {   // not now: the page asks itself
    if (!(ST && st.v && ST.fullV >= st.v)) load(st.reload ? null : st.parts).catch(() => {});
    return;
  }
  if (!merge(st, false)) load().catch(() => {});
}
/** What a change of each topic touches on the page (an unknown one: everything). */
const TOUCHES = { battle: ['battle', 'character', 'team'], characters: ['battle', 'character', 'team', 'world'], dice: ['feed'],
  feed: ['feed'], nowplaying: ['now'], team: ['team', 'world'], world: ['world', 'team'], notes: ['notes'],     // (the team's view shows the food's days)
  duel: ['bg', 'bgbattle'] };                        // (Battlegrounds; a member's battle, character and team parts are their lobby's too)
const touchesOf = t => TOUCHES[t] === undefined ? ['all'] : t === 'duel' && typeof bgMember === 'function' && bgMember() ? ['bg', 'bgbattle', 'battle', 'character', 'team'] : TOUCHES[t];
let soon = null, seenV = 0;              // seenV: the newest change the live stream told of
const WANT = new Set();
/** A change at the table (topics, v: its number): reload what it touched, unless the page already has it all (it
 *  reloaded everything after an action). No topics: everything. */
const refresh = (v, topics) => {
  if (v && ST && ST.fullV >= v) return;
  for (const t of topics && topics.length ? topics : ['?']) for (const p of touchesOf(t)) WANT.add(p);
  clearTimeout(soon);
  soon = setTimeout(() => {
    if (v && ST && ST.fullV >= v) { WANT.clear(); return; }
    const parts = WANT.has('all') ? null : [...WANT];
    WANT.clear();
    load(parts).catch(() => {});
  }, 30);                                  // (the server already sends a burst of changes as one line)
};
function listen() {
  const stream = () => {
    const es = new EventSource('/api/events?push=1&p=' + PAGE + '&k=' + encodeURIComponent(KEY));
    es.addEventListener('state', e => { LIVE.push = true; LIVE.state = Date.now(); try { pushed(JSON.parse(e.data)); } catch { load().catch(() => {}); } });
    es.addEventListener('ka', () => { LIVE.push = true; LIVE.at = Date.now(); });
    es.onmessage = e => {
      LIVE.at = Date.now();
      const m = String(e.data);
      if (m.startsWith('ping ')) ping(m);
      else if (m.startsWith('wping ')) wping(m);
      else { const [topics, v] = m.split(' '); seenV = Math.max(seenV, +v || 0); refresh(+v || 0, topics.split(',')); }   // "battle,characters 12"
    };
    es.onerror = () => { LIVE.at = 0; setTimeout(poll, 300); if (es.readyState === 2) setTimeout(stream, 5000); };   // closed for good: open a new one
    es.onopen = () => {                    // a pushing stream sends what the page missed at once; else the page asks
      const t0 = LIVE.at = Date.now(); online();
      setTimeout(() => { if (!(LIVE.state >= t0)) refresh(); }, 800);
    };
  };
  stream();
  // A proxy may hold the live stream back: also ask every couple of seconds whether anything changed. Behind the
  // stream twice in a row (once may be a line still on its way): it missed something, so everything reloads.
  // While the stream pushes and is heard from, once in 10 s is enough (a safety net, not the way changes come).
  let wait = 2000, timer = 0, lagging = false, asked = 0;   // backs off while the table is offline (up to 30 s)
  async function poll() {
    clearTimeout(timer);
    if (pushLive() && Date.now() - asked < 10000) { timer = setTimeout(poll, wait); return; }
    asked = Date.now();
    try {
      const { v } = await api('/api/version');
      const behind = ST && v > Math.max(seenV, ST.fullV || 0, ST.pv || 0);
      if (behind && lagging) { seenV = v; refresh(v); }
      lagging = behind && !lagging;
      wait = 2000;
    }
    catch { wait = Math.min(30000, wait * 2); }
    timer = setTimeout(poll, wait);
  }
  timer = setTimeout(poll, wait);
}

// ---------------------------------------------------------------- alerts: your turn, a reaction to answer
// The title blinks until the tab is looked at, the phone buzzes, a short chime (made here, no sound files; mute in ⚙),
// and a notification when the page is in the background (allowed with 🔔 in ⚙ - the browser asks only then).
const ALERT = { base: document.title, timer: 0, ctx: null };
const CHIME = { turn: [[660, 0, .35], [880, .14, .4], [1320, .3, .6]], react: [[988, 0, .16], [740, .12, .16], [988, .24, .32]] };
function audio() {
  if (!ALERT.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; try { ALERT.ctx = new C(); } catch { return null; } }
  if (ALERT.ctx.state === 'suspended') ALERT.ctx.resume().catch(() => {});
  return ALERT.ctx;
}
for (const k of ['pointerdown', 'keydown']) document.addEventListener(k, () => { if (!UI.mute && (!ALERT.ctx || ALERT.ctx.state === 'suspended')) audio(); }, true);   // browsers allow sound after a tap
function chime(notes) {
  if (UI.mute) return;
  const c = audio();
  if (!c) return;
  const t0 = c.currentTime + .03;
  for (const [f, at, len] of notes) {
    const o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.value = f;
    g.gain.setValueAtTime(0, t0 + at); g.gain.linearRampToValueAtTime(.16, t0 + at + .015); g.gain.exponentialRampToValueAtTime(.0001, t0 + at + len);
    o.connect(g); g.connect(c.destination); o.start(t0 + at); o.stop(t0 + at + len + .05);
  }
}
const looking = () => document.visibilityState === 'visible' && document.hasFocus();
function flashTitle(text) {
  clearInterval(ALERT.timer); ALERT.timer = 0;
  if (looking()) return;
  let on = true;
  document.title = text;
  ALERT.timer = setInterval(() => { on = !on; document.title = on ? text : ALERT.base; }, 1000);
}
function unflash() { if (ALERT.timer && looking()) { clearInterval(ALERT.timer); ALERT.timer = 0; document.title = ALERT.base; } }
document.addEventListener('visibilitychange', unflash);
window.addEventListener('focus', unflash);
function alertMe(kind) {
  const text = kind === 'turn' ? S('Your turn!') : S('A reaction is waiting for your answer');
  chime(CHIME[kind]);
  try { navigator.vibrate && navigator.vibrate(kind === 'turn' ? [200, 100, 200, 100, 320] : [110, 60, 110]); } catch { /* no vibration */ }
  flashTitle('▶ ' + text);
  if (document.hidden && UI.notify && window.Notification && Notification.permission === 'granted') {
    try {
      const n = new Notification(text, { body: ST.character ? ST.character.name : '', tag: 'dm-' + kind, renotify: true });
      n.onclick = () => { window.focus(); n.close(); };
    } catch { /* this browser shows them only from a service worker */ }
  }
}
function alerts(was) {
  if (!was || !ST.battle) return;
  if (ST.battle.my_turn && !(was.battle && was.battle.my_turn)) alertMe('turn');
  const p = ST.battle.pending, q = was.battle && was.battle.pending;
  if (p && p.mine && (!q || q.rid !== p.rid)) alertMe('react');
}
async function toggleNotify() {
  if (!window.Notification) return say(S("This browser can't show notifications."), true);
  if (!UI.notify) {
    const p = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
    if (p !== 'granted') return say(S('Notifications are blocked for this page in the browser settings.'), true);
  }
  UI.notify = !UI.notify; store('notify', UI.notify); menu(true);
}
function toggleMute() { UI.mute = !UI.mute; store('mute', UI.mute); if (!UI.mute) chime(CHIME.turn); menu(true); }

// ---------------------------------------------------------------- advantage: for the next roll only
const ADV = () => [['', S('Normal')], ['advantage', S('Advantage')], ['disadvantage', S('Disadvantage')]];
function setAdv(v) { UI.adv = v; renderActions(); renderAimbar(); keepFocus($('sheet'), renderSheet); }
function advSeg() {
  const glyph = { '': '=', advantage: '▲', disadvantage: '▼' };        // the words on hover: the switch stays small
  return h('span', { class: 'seg adv3', role: 'group', 'aria-label': S('Next roll') }, ...ADV().map(([v, l]) =>
    h('button', { class: (UI.adv === v ? 'on ' : '') + (v || 'normal'), 'aria-pressed': String(UI.adv === v), 'aria-label': l, onclick: () => setAdv(v),
      tip: `${l}\n${S('For your next roll only: it goes back to normal afterwards')}` }, glyph[v])));
}

// ---------------------------------------------------------------- the page
/** What the DM lets players do (api.RIGHTS, ST.rights): what is off is hidden - an element marked data-need="rest"
 *  goes while the body has the class no-rest. The server refuses it anyway. */
const may = k => !ST || !ST.rights || ST.rights[k] !== false;
const needs = (k, el) => { if (el && el.setAttribute) el.setAttribute('data-need', k); return el; };
function applyRights() {
  const keys = Object.keys(ST.rights || {});
  let css = $('rightscss');
  if (!css) { css = h('style', { id: 'rightscss' }); document.head.append(css); }
  if (keys.length && css.dataset.k !== keys.join()) {
    css.dataset.k = keys.join();
    css.textContent = keys.map(k => `body.no-${k} [data-need~="${k}"]`).join(',') + '{display:none!important}';
  }
  for (const k of keys) document.body.classList.toggle('no-' + k, !may(k));
  const chat = may('chat'), cmds = may('commands');       // the feed's line: chat, /commands, both or gone
  $('say').closest('.bar').classList.toggle('hide', !chat && !cmds);
  $('say').placeholder = chat && cmds ? S('Say something to the table, or type a /command (/help)')
    : chat ? S('Say something to the table') : S('Type a /command (/help)');
  if (UI.tab === 'teamnotes' && !may('team_notes')) UI.tab = 'overview';
}
function render() {
  applyRights();
  header();
  const b = ST.battle;
  if (UI.aim && !b.actions) UI.aim = null;
  turnPick(b);
  if (UI.move && !moveArmed(b)) UI.move = null;
  if (UI.place && !(ST.team && canTeamDrop())) UI.place = null;
  renderNow();
  renderMusic();
  FX.feed(b);
  renderMap();
  if (typeof renderWorld === 'function') renderWorld();   // the world map (world.js): the other face of the map pane
  renderAimbar();
  renderActions();
  renderPending();
  if (UI.dragging) UI.staleSheet = true; else keepFocus($('sheet'), renderSheet);
  renderFeed();
}
/** The header and the fixed words of the page; the pickers are rebuilt only when their choices changed. */
/** My character's hit points in the header, on every view (the map on a phone too): the heart in the health's colour,
 *  temporary HP and conditions beside it; the rest on hover; a click opens the sheet. */
function hpChip() {
  let el = $('hpchip');
  const c = ST.character;
  if (!c) { if (el) el.remove(); return; }
  if (!el) { el = h('button', { id: 'hpchip', class: 'flat', onclick: () => showView('sheet') }); $('who').after(el); }
  const pct = c.max_hp ? c.current_hp / c.max_hp : 0, look = badgeLook();
  el.className = 'flat ' + (c.current_hp <= 0 ? 'down' : pct <= .25 ? 'bad' : pct <= .5 ? 'warn' : 'good');
  el.replaceChildren(...[gi('heal'), h('b', null, `${c.current_hp}/${c.max_hp}`), c.temp_hp ? h('span', { class: 'tmp' }, `+${c.temp_hp}`) : null,
    ...(c.condition_info || []).map(x => h('span', { class: 'cnd', style: `color:${(look[x.name] || [])[1] || 'var(--warn)'}` }, gi(x.name)))].filter(Boolean));
  const words = [`${c.name}: ${S('HP')} ${c.current_hp}/${c.max_hp}` + (c.temp_hp ? ` (+${c.temp_hp})` : ''),
    ...(c.condition_info || []).map(x => x.label), c.exhaustion ? S('Exhaustion {0}', c.exhaustion) : '', S('Click: open your character')].filter(Boolean);
  el.setAttribute('aria-label', words.join(' · '));
  el.onmouseover = e => { if (lastPointer === 'mouse') tip(e, words.join('\n')); };
  el.onmouseleave = () => tip();
}
function header() {
  const title = ST.title || 'Dungeonomicon';                 // which app this is (api.state: edition): Dungeonomicon, or Battlegrounds
  if (document.querySelector('.brand .name').textContent !== title) {
    document.querySelector('.brand .name').textContent = title;
    document.querySelector('.brand').title = title;
    document.querySelector('.brand .mark').textContent = ST.edition === 'battlegrounds' ? 'BG' : 'DM';
    if (!ALERT.timer) document.title = title;
    ALERT.base = title;
  }
  const whoKey = JSON.stringify([ST.me.characters, ST.me.active]);
  if (UI.whoKey !== whoKey && document.activeElement !== $('who')) {
    UI.whoKey = whoKey;
    $('who').replaceChildren(...(ST.me.characters.length ? ST.me.characters : ['—']).map(n => h('option', { value: n, selected: n === ST.me.active }, n)));
  }
  $('who').setAttribute('aria-label', S('Character'));
  $('turn').textContent = ST.battle.my_turn ? S('Your turn!') : '';
  document.body.classList.toggle('myturn', !!ST.battle.my_turn);
  hpChip();
  for (const [v, words, pic] of [['map', S('Map'), 'view_map'], ['sheet', S('Character'), 'view_sheet'], ['feed', S('Table'), 'view_feed']]) {
    const b = document.querySelector(`[data-view=${v}]`);       // a picture and a word (phones: the picture, the word on hold)
    if (!b.querySelector('.gi')) { if (!b.querySelector('.lbl')) b.replaceChildren(h('span', { class: 'lbl' })); b.prepend(gi(pic)); }
    b.querySelector('.lbl').textContent = words;         // (kept for screen readers when phones hide it: with the unread count)
    b.title = words;
  }
  $('views').setAttribute('aria-label', S('Views'));
  $('menu').title = S('Settings');
  $('menu').setAttribute('aria-label', S('Settings'));
  $('zfit').textContent = '⤢'; $('zfit').setAttribute('aria-label', S('Fit'));
  $('zin').setAttribute('aria-label', S('Zoom in')); $('zout').setAttribute('aria-label', S('Zoom out'));
  if (!$('zfit').dataset.tip) for (const [id, words] of [['zfit', S('Fit: the creatures (or the whole map)')], ['zin', S('Zoom in (wheel)')], ['zout', S('Zoom out (wheel)')]]) {
    const b = $(id); b.dataset.tip = '1';
    b.addEventListener('mouseover', e => { if (lastPointer === 'mouse') tip(e, words); });
    b.addEventListener('mouseleave', () => tip());
  }
  $('send').textContent = S('Send');
  $('feedtitle').textContent = S('Table');
  if (!$('menupop').classList.contains('hide')) menu(true);
}
/** ⚙: the language, the chime and notifications. */
function menu(rebuild) {
  const pop = $('menupop');
  if (!rebuild) { const open = pop.classList.toggle('hide'); $('menu').setAttribute('aria-expanded', String(!open)); if (open) return; }
  const a = document.activeElement;
  if (a && pop.contains(a) && a.tagName === 'SELECT') return;
  const lang = h('select', { id: 'lang', 'aria-label': S('Language'), onchange: e => { wordsLang = null; act('language', { lang: e.target.value }, true); } },
    ...(ST ? ST.languages : []).map(([c, n]) => h('option', { value: c, selected: ST && c === ST.me.lang }, n)));
  const notifyOk = window.Notification && Notification.permission !== 'denied';
  pop.replaceChildren(...[                              // (no null: replaceChildren would print it)
    h('label', { class: 'f' }, S('Language')), lang,
    ...qualityPickers(),
    h('button', { class: UI.mute ? '' : 'on', 'aria-pressed': String(!UI.mute), onclick: toggleMute }, (UI.mute ? '🔇 ' : '🔊 ') + S('Sound when it is your turn')),
    h('button', { class: UI.notify && notifyOk ? 'on' : '', 'aria-pressed': String(!!UI.notify), onclick: toggleNotify, disabled: !window.Notification },
      (UI.notify && notifyOk ? '🔔 ' : '🔕 ') + S('Notify me when the page is in the background')),
    window.Notification && Notification.permission === 'denied' ? h('div', { class: 'small dim' }, S('Notifications are blocked for this page in the browser settings.')) : null,
    h('div', { class: 'small dim' }, h('a', { href: 'https://game-icons.net', target: '_blank', rel: 'noopener noreferrer', class: 'dim' },
      S('Icons: game-icons.net')), ' (CC BY 3.0)')].filter(Boolean));
}
/** How much the table sends this page (portal/quality.py): sound and pictures apart, Potato…High - the player's pick,
 *  never above the DM's limit for them. A poor connection picks Potato: small pictures, no portraits but their own. */
const TIERS = ['potato', 'low', 'normal', 'high'];
const TIER_WORDS = { potato: 'Potato', low: 'Low', normal: 'Normal', high: 'High' };
const quality = kind => (ST && ST.me && ST.me.quality && ST.me.quality[kind]) || { want: 'normal', max: 'high', use: 'normal' };
const vq = () => quality('visual').use, aq = () => quality('audio').use;
function qualityPickers() {
  const out = [];
  for (const [kind, words] of [['audio', S('Sound quality')], ['visual', S('Picture quality')]]) {
    const q = quality(kind), top = TIERS.indexOf(q.max);
    out.push(h('label', { class: 'f' }, words), h('select', { 'aria-label': words, onchange: e => setQuality(kind, e.target.value) },
      ...TIERS.map((t, i) => h('option', { value: t, selected: t === q.want, disabled: i > top },
        S(TIER_WORDS[t]) + (i > top ? ' ' + S("(over the DM's limit)") : '')))));
    if (q.use !== q.want) out.push(h('div', { class: 'small dim' }, S('The DM limits you to {0}.', S(TIER_WORDS[q.use]))));
  }
  out.push(h('div', { class: 'small dim' }, S('A slow connection: pick Potato. Only your own token shows its picture.')));
  return out;
}
async function setQuality(kind, tier) {
  const r = await act('quality', { kind, tier }, true);
  if (r && r.data && r.data.quality && ST) { ST.me.quality = r.data.quality; render(); renderMusic(); }   // (listening: the
}                                                       // stream starts over at the new tier)
$('menu').onclick = e => { e.stopPropagation(); $('musicpop').classList.add('hide'); menu(); };
document.addEventListener('click', e => { if (!$('menupop').classList.contains('hide') && !$('menupop').contains(e.target) && e.target !== $('menu')) { $('menupop').classList.add('hide'); $('menu').setAttribute('aria-expanded', 'false'); } });
/** Don't rebuild a part of the page while someone is typing or choosing in it; do it when they leave the field. */
function keepFocus(root, fn) {
  const a = document.activeElement;
  if (a && root.contains(a) && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT')) {
    if (!a._kept) { a._kept = true; a.addEventListener('blur', () => { a._kept = false; keepFocus(root, fn); }, { once: true }); }
    return;
  }
  const scroll = root.scrollTop;
  fn();
  root.scrollTop = scroll;
}

/** What the DM's Spotify plays: cover, song, artist (click: open it on Spotify) and the heart (once per song). */
let artKey = null;
function renderNow() {
  const n = ST.now;
  $('now').classList.toggle('hide', !n);
  if (!n) return;
  $('nowsong').textContent = n.song;
  $('nowartist').textContent = n.artist;
  $('nowlink').href = n.url;
  $('nowlink').title = S('Open on Spotify');
  const art = n.art && vq() !== 'potato';                // (Potato: no cover)
  if (artKey !== n.key + n.art + art) { artKey = n.key + n.art + art; $('nowart').src = art ? `/api/art?k=${encodeURIComponent(KEY)}&s=${encodeURIComponent(n.key)}` : ''; }
  const hb = $('nowheart');
  hb.textContent = n.hearted_by ? '♥' : '♡';
  hb.classList.toggle('on', !!n.hearted_by);
  hb.title = n.hearted_by ? S('{0} loved this song', n.hearted_by) : S('Love this song (shows in the table chat)');
}
$('nowheart').onclick = () => act('heart', {}, false);

// ---------------------------------------------------------------- the table's music
// What the DM shares - the apps they stream and the table's loops - from /api/music, an endless Ogg Opus stream (🎧 in
// the header). Each player sets their own volume, and the slider is loudness, not amplitude, like the DM's own sliders
// (app/bot/volume.py): loudness grows with about the 0.6th power of amplitude, so 50 % sounds half as loud as 100 % and
// 3 % feels like 3 %, not like silence.
const MUSIC = { el: null, gain: null, on: false, live: false, want: !!store('music'), vol: store('musicvol') ?? 50, retry: 0, timer: 0, tried: false };
const loudness = p => Math.pow(Math.max(0, Math.min(100, p)) / 100, 1 / 0.6);
const canMusic = () => !!(window.Audio && new Audio().canPlayType('audio/ogg; codecs=opus'));
function musicVolume() {
  const a = MUSIC.el, g = loudness(MUSIC.vol);
  if (!a) return;
  if (MUSIC.gain) { MUSIC.gain.gain.value = g; return; }
  a.volume = g;
  if (Math.abs(a.volume - g) > .01) {            // iPhone and iPad keep an element's volume at 1: go through Web Audio
    const c = audio();
    if (!c) return;
    MUSIC.gain = c.createGain();
    c.createMediaElementSource(a).connect(MUSIC.gain);
    MUSIC.gain.connect(c.destination);
    MUSIC.gain.gain.value = g;
  }
}
function musicPlay() {
  clearTimeout(MUSIC.timer);
  if (!ST || !ST.music || !canMusic()) return;
  if (!MUSIC.el) {
    const a = MUSIC.el = new Audio();
    a.preload = 'none';
    const live = on => { if (MUSIC.live !== on) { MUSIC.live = on; renderMusic(); } };   // sound comes out, or not yet / not any more
    const lost = () => { live(false); if (MUSIC.on) MUSIC.timer = setTimeout(musicPlay, Math.min(30000, 2000 * 2 ** MUSIC.retry++)); };   // the app or the tunnel went away: try again
    a.addEventListener('error', lost);
    a.addEventListener('ended', lost);
    a.addEventListener('playing', () => { MUSIC.retry = 0; live(MUSIC.on); });
    a.addEventListener('waiting', () => live(false));
  }
  MUSIC.on = true;
  MUSIC.live = false;                                  // "Connecting…" until the first sound plays
  MUSIC.q = aq();                                      // the sound quality it is sent at (⚙; the DM may cap it)
  MUSIC.el.src = `/api/music?k=${encodeURIComponent(KEY)}&q=${MUSIC.q}&t=${Date.now()}`;     // a fresh stream, never a cached one
  musicVolume();
  MUSIC.el.play().catch(e => {
    if (e.name !== 'NotAllowedError' || !MUSIC.on) return;                         // other failures retry through 'error'
    MUSIC.on = false;                                  // browsers start sound only after a tap on the page: at the next one
    musicHangUp();
    document.addEventListener('pointerdown', ev => { if (MUSIC.want && !MUSIC.on && !ev.target.closest('#music,#musicpop')) musicPlay(); }, { once: true, capture: true });
    renderMusic();
  });
  renderMusic();
}
function musicHangUp() {                               // drop the connection: the app stops sending
  if (MUSIC.el) { MUSIC.el.pause(); MUSIC.el.removeAttribute('src'); MUSIC.el.load(); }
}
function musicStop() { clearTimeout(MUSIC.timer); MUSIC.on = MUSIC.live = false; musicHangUp(); renderMusic(); }
function musicToggle() {
  MUSIC.want = !MUSIC.on;
  store('music', MUSIC.want);
  if (MUSIC.want) musicPlay(); else musicStop();
}
function musicIcon() {
  const b = $('music');
  b.textContent = !MUSIC.on ? '🎧' : MUSIC.vol <= 0 ? '🔇' : MUSIC.vol < 50 ? '🔉' : '🔊';
  b.classList.toggle('on', MUSIC.on);
  b.classList.toggle('connecting', MUSIC.on && !MUSIC.live);
}
/** 🎧 shows while the DM lets players listen; a player who listened last time hears it again as soon as the page may. */
function renderMusic() {
  $('music').classList.toggle('hide', !ST.music);
  if (!ST.music) {
    MUSIC.tried = false;
    $('musicpop').classList.add('hide');
    if (MUSIC.on) musicStop();
    return;
  }
  if (MUSIC.want && !MUSIC.on && !MUSIC.tried) { MUSIC.tried = true; musicPlay(); return; }
  if (MUSIC.on && MUSIC.q !== aq()) { musicPlay(); return; }    // the DM changed the limit: start over at the new tier
  musicIcon();
  $('music').title = S('Music');
  $('music').setAttribute('aria-label', S('Music'));
  if (!$('musicpop').classList.contains('hide')) musicPop(true);
}
/** 🎧: listen or stop, and your own volume. */
function musicPop(rebuild) {
  const pop = $('musicpop');
  if (!rebuild) {
    const shut = pop.classList.toggle('hide');
    $('music').setAttribute('aria-expanded', String(!shut));
    if (shut) return;
    $('menupop').classList.add('hide');
  }
  if (pop.contains(document.activeElement) && document.activeElement.type === 'range') return;    // not under a dragged slider
  const ok = canMusic(), out = h('output', {}, MUSIC.vol + '%'), wait = MUSIC.on && !MUSIC.live;
  pop.replaceChildren(
    h('button', { class: !MUSIC.on ? 'primary' : wait ? 'on wait' : 'on', disabled: !ok, 'aria-pressed': String(MUSIC.on),
      'aria-busy': String(wait), title: wait ? S('Stop listening') : '', onclick: musicToggle },
      !MUSIC.on ? '▶ ' + S("Listen to the table's music") : wait ? S('Connecting…') : '⏸ ' + S('Stop listening')),
    h('label', { class: 'vol' }, h('span', { 'aria-hidden': 'true' }, '🔈'),
      h('input', { type: 'range', min: 0, max: 100, step: 1, value: MUSIC.vol, 'aria-label': S('Music volume'),
        oninput: e => { MUSIC.vol = +e.target.value; out.textContent = MUSIC.vol + '%'; musicVolume(); musicIcon(); store('musicvol', MUSIC.vol); } }),
      out),
    h('div', { class: 'small dim' }, ok ? S('What the DM plays for the table. The volume is only yours: the others hear it as loud as they like.')
      : S("This browser can't play the table's music. Try Chrome, Edge or Firefox.")));
}
$('music').onclick = e => { e.stopPropagation(); musicPop(); };
$('musicpop').onclick = e => e.stopPropagation();     // its button is rebuilt under the click: not a click outside
document.addEventListener('click', e => { if (!$('musicpop').classList.contains('hide') && !$('musicpop').contains(e.target) && e.target !== $('music')) { $('musicpop').classList.add('hide'); $('music').setAttribute('aria-expanded', 'false'); } });

// ---------------------------------------------------------------- effects
// What the battle lists in fx (steps, hits, misses, crits, areas, saves, heals...) played on the map: tokens walk tile
// by tile, tiles flash in the colour of the damage, numbers rise, the map shakes a little - more, with a red edge on
// the screen, when your own creature gets hurt. The DM's map plays the same list (app/ui/panels/battle/vfx.py).
const DMG = { acid: '#a3e635', bludgeoning: '#d6c3a1', cold: '#7dd3fc', fire: '#ff7a1a', force: '#e879f9', lightning: '#fde047',
  necrotic: '#8fa85a', piercing: '#e5e7eb', poison: '#4ade80', psychic: '#f472b6', radiant: '#fff3b0', slashing: '#f87171', thunder: '#60a5fa' };
const SHATTER = { potion_orange: '#ff7a1a', potion_green: '#a3e635', potion_white: '#e0f2fe', potion_brown: '#a16207' };   // a broken flask's splash
const FXC = { hit:'#f87171', miss: '#9aa3b2', crit: '#fbbf24', magic: '#a78bfa', heal: '#5eead4', saved: '#93c5fd', failed: '#f87171', down: '#7f1d1d' };
const BURSTS = ['sphere', 'cylinder', 'cube', 'square', 'emanation', 'burst'];
const LOBBED = ['fire', 'acid', 'cold', 'poison'];      // bursts of these arc over as a bead; sound and energy just go off there
const DECAL = { fire: ['#1c1008', .42], cold: ['#dbeafe', .16], acid: ['#84cc16', .16], poison: ['#4ade80', .1] };   // left on the floor
const LEGENDARY = '#f59e0b';
// a damage number's look by its type: how far it rises (tiles; below 0 it sinks), a glow, an outline, doubles beside it
const NUM_LOOK = { fire: { rise: .8, glow: '#ff5a00' }, cold: { rise: .4, edge: '#f0f9ff' }, lightning: { rise: .7, glow: '#fef08a' },
  acid: { rise: .25 }, poison: { rise: .5 }, necrotic: { rise: -.3 }, radiant: { rise: .8, glow: '#fffbe6' },
  thunder: { rise: .5 }, force: { rise: .6, edge: '#fae8ff' }, psychic: { rise: .6, ghosts: true },
  bludgeoning: { rise: .35 }, piercing: { rise: 1 }, slashing: { rise: .6 } };
const NUM_SPARKS = { fire: ['#ff7a1a', 6, 'rise', .3, .035], cold: ['#e0f2fe', 6, 'fall', .35, .03], acid: ['#a3e635', 4, 'fall', .25, .035] };  // embers, frost, drips
const noise = (k, j) => { const v = Math.sin(k * 12.9898 + j * 78.233) * 43758.5453; return (v - Math.floor(v)) * 2 - 1; };   // -1..1, the same for (k, j)
const mixHex = (a, b, k) => '#' + [16, 8, 0].map(sh => { const x = (parseInt(a.slice(1), 16) >> sh) & 255, y = (parseInt(b.slice(1), 16) >> sh) & 255;
  return Math.round(x + (y - x) * k).toString(16).padStart(2, '0'); }).join('');
/** How the j-th of n characters of a damage number sits u (0..1) into its life, s seconds in: [dx, dy] (tiles), scale,
 *  turn (degrees), colour, alpha. Each damage type moves its own way; num_glyph in vfx.py is the twin. */
function numGlyph(dtype, u, s, j, n) {
  let col = tint(dtype), dx = 0, dy = 0, rot = 0, sx = 1, sy = 1, a = 1;
  if (dtype === 'fire') {                              // burning: the digits lick upward and flicker through the flame colours
    dy = Math.sin(s * 15 + j * 1.7) * .035 - Math.abs(noise(Math.floor(s * 18), j)) * .03;
    sy = 1 + .1 * Math.abs(Math.sin(s * 11 + j * 2.1));
    const f = noise(Math.floor(s * 14), j + 7);
    col = f > .45 ? '#fde047' : f < -.55 ? '#ef4444' : col;
  } else if (dtype === 'cold') {                       // shivering: quick little shakes, calming as it fades
    const k = Math.floor(s * 32), amp = .045 * (1 - .6 * u);
    dx = noise(k, j) * amp; dy = noise(k, j + 31) * amp * .5; rot = noise(k, j + 63) * 6 * (1 - .6 * u);
  } else if (dtype === 'lightning') {                  // crackling: the number jumps about and flashes white
    const k = Math.floor(s * 20);
    dx = noise(k, 0) * .05; dy = noise(k, 1) * .05;
    if (noise(k, 2) > .3) col = '#ffffff';
  } else if (dtype === 'acid') {                       // melting: the digits sag and drip down, one after another
    const v = Math.max(0, u - .15 * j / Math.max(1, n));
    dy = v * v * .35 * (1 + .5 * noise(j, 5)); sy = 1 + .5 * v;
  } else if (dtype === 'poison') {                     // a sickly sway, the colour throbbing
    dx = Math.sin(s * 7 + j * .9) * .05; rot = Math.sin(s * 7 + j * .9 + 1) * 8; a = .75 + .25 * Math.sin(s * 9);
  } else if (dtype === 'necrotic') {                   // it sinks, darkening, the digits drifting apart
    dx = (j - (n - 1) / 2) * .05 * u; a = 1 - .2 * u; col = mixHex(col, '#1a1f12', u * .4);
  } else if (dtype === 'radiant') {                    // a slow bright swell
    sx = sy = 1 + .15 * Math.sin(Math.PI * Math.min(1, u * 1.5));
  } else if (dtype === 'thunder') {                    // a boom: big at once, snapping back, the shudder dying out
    const b = Math.max(0, 1 - u / .25);
    sx = sy = 1 + .7 * b * b; dx = Math.sin(s * 60) * .04 * b;
  } else if (dtype === 'force') {                      // popped out, settling with a wobble
    sx = sy = 1 + .35 * Math.exp(-u * 9) * Math.cos(u * 40);
  } else if (dtype === 'psychic') {                    // the digits tilt and drift as if unreal (the painter adds the doubles)
    rot = Math.sin(s * 5 + j) * 10; dy = Math.sin(s * 6 + j * 1.4) * .03;
  } else if (dtype === 'bludgeoning') {                // slammed down from above, squashing flat, springing back
    dy = -.35 * (1 - Math.min(1, u / .15)) ** 2;
    const sq = Math.max(0, 1 - Math.abs(u - .17) / .08);
    sx = 1 + .35 * sq; sy = 1 - .35 * sq;
  } else if (dtype === 'piercing') {                   // shot up fast, thin and tall at first
    const b = Math.max(0, 1 - u / .3);
    sx = 1 - .3 * b; sy = 1 + .4 * b;
  } else if (dtype === 'slashing') {                   // slid in from the side, slanted along the cut
    const d = 1 - Math.min(1, u / .18);
    dx = -.3 * d * d * (1 + j * .3); rot = -12 * d - 4;
  }
  return [dx, dy, sx, sy, rot, col, a];
}
const SRC ={ arcane: FXC.magic, divine: '#fcd34d', primal: '#86efac', ki: '#bae6fd', martial: '#cbd5e1', fury: '#ef4444', song: '#f9a8d4' };
const GATHER = [.15, .25, .35, .45];                   // seconds a casting circle shows before its spell goes, by tier
const BADGE = .16, BADGE_GAP = .36, BADGE_MAX = 3;     // condition badges over a token: radius, spacing (tiles), how many
const BLINK = .45;                                     // seconds a badge blinks when its effect changes a number
const badgeLook = () => (ST.battle && ST.battle.badge_look) || {};  // condition or effect -> [picture, colour] (icons.BADGES)
const pictures = {};
function picture(slug) {                               // an icon (white on transparent); the map redraws when it arrives
  if (!pictures[slug]) { pictures[slug] = new Image(); pictures[slug].onload = () => renderMap(); pictures[slug].src = `/icon/${slug}.webp`; }
  return pictures[slug];
}
function badges(c) {                                   // the badges a token shows: conditions, Bless, Rage..., or the first and '+N'
  const shown = (c.badges || []).filter(x => badgeLook()[x]);
  return shown.length <= BADGE_MAX ? shown : [...shown.slice(0, BADGE_MAX - 1), `+${shown.length - BADGE_MAX + 1}`];
}
function pipSpots(px, py, s, least = 2.5) {           // [[x, y] x6, r]: a dying creature's death save pips on its bottom edge
  const r = Math.max(least, s * .05), gap = r * 2.7;
  return [[0, 1, 2, 3, 4, 5].map(i => [px + s * .42 + (i - 2.5) * gap + (i >= 3 ? r * .6 : -r * .6), py + s - r * 1.8]), r];
}
function paintPips(g, c, px, py, s) {                  // green pips for successes, red for failures
  const ds = c.dsaves;
  if (!ds) return;
  const [spots, r] = pipSpots(px, py, s);
  g.fillStyle = 'rgba(11,13,18,.8)'; g.beginPath();
  g.roundRect ? g.roundRect(spots[0][0] - r * 1.6, spots[0][1] - r * 1.6, spots[5][0] - spots[0][0] + r * 3.2, r * 3.2, r * 1.6) : g.rect(spots[0][0] - r * 1.6, spots[0][1] - r * 1.6, spots[5][0] - spots[0][0] + r * 3.2, r * 3.2);
  g.fill();
  spots.forEach(([x, y], i) => {
    const col = i < 3 ? '#4ade80' : '#f87171', done = i < 3 ? ds[0] > i : ds[1] > i - 3;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2);
    if (done) { g.fillStyle = col; g.fill(); }
    g.strokeStyle = col; g.lineWidth = Math.max(1, r * .35); g.stroke();
  });
}
function badgeSlot(cx, top, i, n, T) {                 // [x, y, r]: in a row just over the token's top edge, centred on it
  const r = Math.max(7, BADGE * T), gap = Math.max(2 * r + 2, BADGE_GAP * T);
  return [cx + (i - (n - 1) / 2) * gap, top - r - 1, r];
}
function paintBadge(g, x, y, r, name, alpha = 1) {     // a dark disc ringed in the badge's colour, with its icon (or '+N')
  const [slug, col] = badgeLook()[name] || [null, '#9aa3b2'];
  g.save();
  g.globalAlpha *= alpha;
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2);
  g.fillStyle = 'rgba(11,13,18,.86)'; g.fill();
  g.strokeStyle = col; g.lineWidth = Math.max(1.2, r * .16); g.stroke();
  const im = slug ? picture(slug) : null;
  if (im && im.complete && im.naturalWidth) g.drawImage(im, x - r * .68, y - r * .68, r * 1.36, r * 1.36);
  else if (!slug) { g.fillStyle = '#e6e9ef'; g.font = `700 ${Math.max(8, Math.round(r * .95))}px Segoe UI, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(name, x, y); }
  g.restore();
}
const STEP = 0.085, REVEAL = 0.8;
const tint = (d, dflt = FXC.hit) => DMG[(d || '').toLowerCase()] || dflt;
const now_ = () => performance.now() / 1000;
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${Math.max(0, Math.min(1, a)).toFixed(3)})`; };
const FX = {
  seen: null, items: [], moves: {}, poses: {}, landing: {}, blinks: {}, zoneMoves: {}, shakes: [], clock: 0, prev: {}, frame: false, raf: 0,
  flying: {},                                          // 'gid:7' / 'did:3' -> when a thrown item (prop) lands: hidden till then
  hidden(key) {                                        // the ground stacks ('gid') or props ('did') a thrown thing is still flying to
    const out = new Set(), now = now_();
    for (const k in this.flying) { const [kind, id] = k.split(':'); if (kind === key && now < this.flying[k]) out.add(+id); }
    return out;
  },
  feed(b) {
    const n = b.fx_n || 0, bodies = {};
    for (const c of b.combatants) bodies[c.id] = c;
    const snap = () => { this.prev = {}; for (const c of b.combatants) if (c.pos) this.prev[c.id] = [...c.pos]; };
    if (this.seen === null || n < this.seen) { this.seen = n; snap(); this.bodies = bodies; return; }   // a fresh page: the past doesn't replay
    const fresh = (b.fx || []).filter(f => f.n > this.seen);
    this.seen = n;
    const now = now_();
    let t = Math.max(now, this.clock);
    if (t - now > 1.5) t = now;
    this.where = { ...this.prev }; this.old = this.bodies || {}; this.bodies = bodies;   // old: a creature that just left
    const walked = new Set();
    for (const f of fresh) { try { if (f.k === 'step' || f.k === 'blink') walked.add(f.id); t = this.queue(f, t); } catch { /* not shown */ } }
    for (const c of b.combatants) {                    // moved by the DM: walk there in a straight line rather than jump
      const a = this.where[c.id];
      if (!c.pos || !a || walked.has(c.id) || (a[0] === c.pos[0] && a[1] === c.pos[1])) continue;
      const steps = Math.max(Math.abs(c.pos[0] - a[0]), Math.abs(c.pos[1] - a[1]));
      if (steps > 14) continue;
      let p = [...a], s = now;
      for (let i = 1; i <= steps; i++) {
        const q = [Math.round(a[0] + (c.pos[0] - a[0]) * i / steps), Math.round(a[1] + (c.pos[1] - a[1]) * i / steps)];
        (this.moves[c.id] = this.moves[c.id] || []).push([s, STEP, p, q]); p = q; s += STEP;
      }
    }
    this.clock = t;
    snap();
    if (fresh.length || Object.keys(this.moves).length) this.loop();
  },
  centre(id) {
    const c = this.bodies[id], p = this.where[id] || (c && c.pos);
    if (!p) return null;
    const s = (c && c.span) || 1;
    return [p[0] + s / 2, p[1] + s / 2];
  },
  tiles(id) {
    const c = this.bodies[id], p = this.where[id] || (c && c.pos), out = [];
    if (!p) return out;
    const s = (c && c.span) || 1;
    for (let i = 0; i < s; i++) for (let j = 0; j < s; j++) out.push([p[0] + i, p[1] + j, 0]);
    return out;
  },
  add(kind, t0, dur, o) { this.items.push({ kind, t0, dur, ...o }); },
  shake(t0, amp, dur = .28) { if (!CALM.matches) this.shakes.push([t0, dur, amp]); },      // still with reduced motion
  mine(id) { const c = this.bodies[id]; return !!(c && c.mine); },
  // a token drawn off its place for a while: moved (dx, dy tiles), scaled 1 + k, opacity 1 + a; ease 'bump' there and
  // back, 'to' going there, 'from' coming back. With reduced motion only the fades play.
  bend(id, t0, dur, ease, dx = 0, dy = 0, k = 0, a = 0) {
    if (CALM.matches && !a) return;
    (this.poses[id] = this.poses[id] || []).push([t0, dur, ease, dx, dy, k, a]);
  },
  // small glowing dots around a point: 'rise' (good things), 'fall' (bad things), 'burst' (an impact), 'inward' (gathering)
  motes(t0, dur, at, col, n, mode, spread, size = .055, arc = null) {     // arc [angle, half width]: only that way (a cone)
    const dots = [], lo = arc ? arc[0] - arc[1] : 0, span = arc ? 2 * arc[1] : Math.PI * 2;
    for (let j = 0; j < (CALM.matches ? Math.ceil(n / 2) : n); j++)
      dots.push([lo + Math.random() * span, .25 + Math.random() * .75, Math.random() * .3, .75 + Math.random() * .5]);
    this.add('motes', t0, dur, { at, col, mode, spread, size, dots });
  },
  decal(t0, tiles, dtype) {                            // what an area leaves on the floor for a few seconds (scorch, rime...)
    if (DECAL[dtype]) this.add('decal', t0, 3, { cells: tiles.map(p => [p[0], p[1]]), col: DECAL[dtype][0], peak: DECAL[dtype][1] });
  },
  puff(t0, at, col, r) {                               // a soft cloud swelling and thinning out: hides a creature arriving or leaving
    const blobs = [];
    for (let j = 0; j < 7; j++) blobs.push([Math.random() * 2 - 1, Math.random() * 1.6 - .8, .7 + Math.random() * .5]);
    this.add('puff', t0, .6, { at, col, r, blobs });
  },
  cracks(t0, at, col, size) {                          // jagged cracks running out over the floor from a point, glowing
    const lines = [];
    for (let j = 0; j < 6; j++) {
      let a = Math.PI * 2 * j / 6 + (Math.random() - .5) * .6, r = .12 * size;
      const pts = [[at[0], at[1]]];
      for (let k = 0; k < 4; k++) { a += (Math.random() - .5) * 1.1; r += .17 * size; pts.push([at[0] + Math.cos(a) * r, at[1] + Math.sin(a) * r]); }
      lines.push(pts);
    }
    this.add('crack', t0, 1, { col, lines });
  },
  // what a summoning circle brings with it, by the kind of creature arriving (not by spell): one look per kind
  twist(kind, T, s, t, col, name) {
    const r = s / 2 + .2;
    if (kind === 'celestial') { this.add('column', t + .05, .7, { at: T, r, col: '#fff3b0' }); this.motes(t + .15, .9, T, '#fcd34d', 10, 'fall', r); }
    else if (kind === 'fiend') { this.cracks(t, T, '#ef4444', s); this.motes(t + .2, .7, T, '#ff7a1a', 12, 'rise', r); this.puff(t + .2, T, '#57534e', s * .7); }
    else if (kind === 'undead') { this.cracks(t, T, '#8fa85a', s); this.motes(t + .2, .8, T, '#8fa85a', 10, 'rise', r); }
    else if (kind === 'elemental') {
      const low = (name || '').toLowerCase();
      const elem = ([['fire', DMG.fire], ['water', '#38bdf8'], ['earth', '#d6c3a1'], ['air', '#e5e7eb'], ['ice', DMG.cold]].find(([w]) => low.includes(w)) || [0, '#5eead4'])[1];
      this.motes(t, .8, T, elem, 14, 'orbit', r);
    }
    else if (kind === 'fey') { this.motes(t, .8, T, '#f9a8d4', 8, 'orbit', r); this.motes(t + .05, .8, T, '#86efac', 6, 'orbit', r * .8); }
    else if (kind === 'beast' || kind === 'plant') this.motes(t + .25, .6, T, '#86efac', 10, 'burst', r + .2);
    else if (kind === 'construct') { this.motes(t, .4, T, '#7dd3fc', 12, 'inward', r + .3); this.motes(t + .3, .4, T, '#e0f2fe', 8, 'burst', r); }
    else if (kind === 'aberration') { this.add('ring', t, .5, { at: T, col: '#a78bfa', r0: .1, r1: r + .1, width: 3 }); this.motes(t, .5, T, '#c084fc', 10, 'inward', r + .2); }
    else if (kind === 'dragon') { this.add('ring', t + .25, .45, { at: T, col: '#e5e7eb', r0: s / 2, r1: s / 2 + .8, width: 3 }); this.motes(t + .25, .5, T, '#d6c3a1', 12, 'burst', r + .5); }
    else this.motes(t, .4, T, col, 10, 'inward', r + .2);
  },
  // a lasting area's moments: it spreads out from its middle as it appears; it flares under whoever it strikes, in its
  // own way (embers rise, a cloud billows, strands tighten, blades glint); it ends its own way; moved, it glides
  zoneFx(f, t) {
    const fam = f.fam || 'area', sub = f.sub || '', col = zoneColour(fam, sub, f.dtype || '');
    if (f.op === 'move') { const d = f.d || [0, 0]; this.zoneMoves[f.zid] = [t, .3, +d[0], +d[1]]; return t + .05; }
    if (f.op === 'hit') {
      for (const id of f.ids || []) {
        const T = this.centre(id);
        if (!T) continue;
        this.add('flash', t, .4, { tiles: this.tiles(id), col, peak: .5 });
        if (['fire', 'help', 'light'].includes(fam)) this.motes(t, .6, T, col, 8, 'rise', .4);
        else if (fam === 'cloud' || fam === 'dark') this.puff(t, T, fam === 'cloud' ? col : '#4c1d95', .5);
        else if (fam === 'tangle') this.motes(t, .4, T, col, 8, 'inward', .7);      // strands drawing tight around it
        else if (fam === 'beam') this.add('column', t, .45, { at: T, r: .5, col });
        else this.motes(t, .4, T, col, 8, 'burst', .55);
      }
      return t + .05;
    }
    const tiles = f.tiles || [];
    if (!tiles.length) return t;
    const mid = [tiles.reduce((s, p) => s + p[0], 0) / tiles.length + .5, tiles.reduce((s, p) => s + p[1], 0) / tiles.length + .5];
    const dist = ([x, y]) => Math.hypot(x + .5 - mid[0], y + .5 - mid[1]), far = Math.max(...tiles.map(dist));
    if (f.op === 'on') {                               // it spreads out from its middle
      this.add('flash', t, .5, { tiles: tiles.map(p => [p[0], p[1], dist(p) * .03]), col, peak: .45 });
      this.add('ring', t, .35 + far * .03, { at: mid, col, r0: .2, r1: far + .3, width: 3 });
      return t + .1;
    }
    this.add('flash', t, .6, { tiles: tiles.map(p => [p[0], p[1], 0]), col, peak: .3 });   // 'off': its own way of going
    const spread = Math.min(far + .3, 4);
    if (['fire', 'help', 'light', 'beam'].includes(fam)) this.motes(t, .8, mid, col, 14, 'rise', spread);
    else if (['cloud', 'dark', 'silence', 'illusion'].includes(fam)) this.puff(t, mid, fam === 'dark' ? '#4c1d95' : col, spread * .8);
    else this.motes(t, .6, mid, col, 16, 'burst', spread);    // walls crumble, strands snap, blades scatter
    return t + .1;
  },
  // how a creature falls, by what it is: the living bleed, the undead crumble, constructs spark apart, elementals come
  // undone into their element, oozes splat, fiends burn away, celestials and fey turn to light
  death(kind, T, tiles, t, name) {
    const cells = tiles.map(p => [p[0], p[1]]);
    if (kind === 'undead') { this.motes(t, .8, T, '#9ca3af', 12, 'fall', .45); this.puff(t + .1, T, '#9ca3af', .6); }
    else if (kind === 'construct') { this.motes(t, .5, T, '#e0f2fe', 12, 'burst', .8); this.shake(t, 2); }
    else if (kind === 'elemental') {
      const low = name.toLowerCase();
      const elem = ([['fire', DMG.fire], ['water', '#38bdf8'], ['earth', '#d6c3a1'], ['air', '#e5e7eb'], ['ice', DMG.cold]].find(([w]) => low.includes(w)) || [0, '#5eead4'])[1];
      this.motes(t, .8, T, elem, 14, 'burst', 1);
    } else if (kind === 'ooze') this.add('decal', t, 3, { cells, col: '#65a30d', peak: .3 });
    else if (kind === 'fiend') this.motes(t, .8, T, DMG.fire, 12, 'rise', .45);
    else if (kind === 'celestial' || kind === 'fey') this.motes(t, .9, T, kind === 'celestial' ? '#fcd34d' : '#f9a8d4', 12, 'rise', .45);
    else this.add('decal', t, 3, { cells, col: '#7f1d1d', peak: .32 });     // beasts, humanoids, giants...: blood
  },
  dsave(f, t) {
    const T = this.centre(f.id), c = this.bodies[f.id] || {};
    if (!T || !c.pos) return t;
    const span = c.span || 1, s = +f.s || 0, fl = +f.f || 0, nat = f.nat;
    if (nat === 20 || f.up) {                          // back on its feet
      this.motes(t, .7, T, FXC.crit, 14, 'burst', .9);
      this.add('ring', t, .5, { at: T, col: FXC.crit, r0: .2, r1: span / 2 + .5, width: 4 });
      this.add('text', t, 1.1, { at: [T[0], T[1] - .2], text: S('back up!'), col: FXC.crit, size: .34 });
      return t + .15;
    }
    if (fl >= 3) {                                     // dead: a pale wisp rises and is gone
      this.motes(t, 1.2, T, '#e5e7eb', 12, 'rise', .3);
      this.add('text', t, 1.3, { at: [T[0], T[1] - .1], text: S('dead'), col: '#e5e7eb', size: .34, rise: .4 });
      return t + .2;
    }
    if (s >= 3) {                                      // stable: a heartbeat drawn over it
      this.add('ecg', t, 1, { at: [T[0], c.pos[1] - .15], w: span * .8, col: FXC.heal });
      this.add('text', t + .2, 1, { at: [T[0], T[1] + .3], text: S('stable'), col: FXC.heal, size: .3 });
      return t + .15;
    }
    const failed = f.hit || (nat != null && nat < 10), idx = [failed ? 3 + fl - 1 : s - 1];
    if (nat === 1 && fl >= 2) idx.push(3 + fl - 2);
    const [spots] = pipSpots(c.pos[0], c.pos[1], span, 0);
    for (const i of idx) if (i >= 0 && i < 6) this.add('ring', t, .45, { at: spots[i], col: i >= 3 ? '#f87171' : '#4ade80', r0: .03, r1: .28, width: 3 });
    if (f.hit) this.shake(t, 2);
    return t + .1;
  },
  zoneOffset(id) {                                     // [dx, dy] a moved area is still drawn back from its new place, or null
    const mv = this.zoneMoves[id];
    if (!mv) return null;
    const u = (now_() - mv[0]) / mv[1];
    if (u >= 1) { delete this.zoneMoves[id]; return null; }
    const v = Math.max(0, u), k = 1 - v * v * (3 - 2 * v);
    return [-mv[2] * k, -mv[3] * k];
  },
  // a class feature or a standard action: its name under the creature, then a look made of the usual pieces in the
  // colour of where it comes from (vfx.py _feature_fx); healing and damage they cause play by themselves after this
  featureFx(f, t) {
    const C = this.centre(f.id);
    if (!C) return t;
    const s = (this.bodies[f.id] || {}).span || 1, O = this.centre(f.other), key = f.key || '', r = s / 2;
    const steel = SRC.martial, ki = SRC.ki, gold = SRC.divine, song = SRC.song, fury = SRC.fury;
    this.add('text', t, 1, { at: [C[0], C[1] + r + .2], text: S(f.name || ''), col: '#e6e9ef', size: .24, rise: .2 });
    if (key === 'second_wind') {                       // a breath drawn in, then the heal
      this.add('ring', t, .4, { at: C, col: steel, r0: r + .6, r1: r * .6, width: 3 });
      this.motes(t, .4, C, steel, 10, 'inward', r + .7);
      return t + .3;
    }
    if (key === 'action_surge') { this.add('ring', t, .4, { at: C, col: '#fde68a', r0: r, r1: r + .7, width: 4 }); this.motes(t, .5, C, '#fde68a', 14, 'burst', r + .6); this.shake(t, 2); }
    else if (key === 'rage') { this.add('ring', t, .5, { at: C, col: fury, r0: r, r1: r + 1.4, width: 5 }); this.motes(t, .6, C, fury, 16, 'burst', r + .8); this.shake(t, 4); }
    else if (key === 'reckless') { this.add('slash', t, .3, { at: C, col: fury, big: true }); this.add('slash', t + .08, .3, { at: C, col: fury, big: true, flip: true }); }
    else if (['cunning_dash', 'step_of_the_wind', 'dash', 'charge'].includes(key)) {
      this.motes(t, .45, C, key === 'step_of_the_wind' ? ki : '#e5e7eb', 12, 'burst', r + .7);
      this.add('ring', t, .35, { at: C, col: '#d6c3a1', r0: r * .8, r1: r + .3, width: 2 });
    } else if (['cunning_disengage', 'disengage', 'cunning_hide', 'hide'].includes(key)) this.puff(t, C, '#9ca3af', s * .5);
    else if (key === 'steady_aim' || key === 'ready') this.add('ring', t, .5, { at: O || C, col: key === 'steady_aim' ? '#ffffff' : steel, r0: r + .9, r1: r * .5, width: 2 });
    else if ((key === 'martial_arts' || key === 'flurry') && O) { this.motes(t, .3, O, ki, 8, 'burst', .5); if (key === 'flurry') this.motes(t + .1, .3, O, ki, 8, 'burst', .5); }
    else if (key === 'patient_defense' || key === 'dodge') {
      const col = key === 'patient_defense' ? ki : steel;
      this.add('ring', t, .5, { at: C, col, r0: r + .5, r1: r + .1, width: 3 });
      this.add('shell', t, .6, { at: C, r: r + .18, col, ang: -Math.PI / 2 });
    } else if (key === 'stunning_strike' && O) this.add('ring', t, .4, { at: O, col: ki, r0: .2, r1: 1, width: 3 });
    else if (key === 'lay_on_hands' || key === 'healing_hands') {
      const A = O || C;
      this.add('ring', t, .45, { at: A, col: gold, r0: .9, r1: .3, width: 3 });
      this.motes(t, .5, A, gold, 10, 'inward', .9);
      return t + .25;
    } else if (key === 'divine_smite' && O) this.add('column', t, .5, { at: O, r: .55, col: DMG.radiant });
    else if (key === 'bardic_inspiration' && O) { this.add('bolt', t, .3, { a: C, b: O, col: song }); this.motes(t + .3, .6, O, song, 10, 'rise', .4); return t + .3; }
    else if (key === 'turn_undead') { this.add('ring', t, .7, { at: C, col: gold, r0: r, r1: 6.5, width: 5 }); this.motes(t, .7, C, gold, 18, 'burst', 3); this.shake(t, 2); }
    else if (key === 'wild_shape') { this.puff(t, C, '#65a30d', s * .6); this.motes(t, .7, C, '#86efac', 12, 'orbit', r + .3); }
    else if (key === 'relentless_endurance') {
      this.add('ring', t, .5, { at: C, col: fury, r0: r, r1: r + 1, width: 5 });
      this.motes(t, .5, C, fury, 14, 'burst', r + .7);
      this.add('text', t, 1.1, { at: [C[0], C[1] - .2], text: S('Relentless!'), col: fury, size: .34 });
      this.shake(t, 3);
    } else if (key === 'help' && O) { this.add('bolt', t, .25, { a: C, b: O, col: gold }); this.add('ring', t + .25, .4, { at: O, col: gold, r0: .8, r1: .3, width: 2 }); }
    else if ((key === 'grapple' || key === 'shove') && O) { this.bend(f.id, t, .25, 'bump', ...this.away(C, O, .2)); this.motes(t + .1, .35, O, steel, 8, key === 'shove' ? 'burst' : 'inward', .5); }
    else if (key === 'stand_up' || key === 'drop_prone') this.motes(t, .4, [C[0], C[1] + r * .6], '#d6c3a1', 8, 'burst', r * .8);
    else if (key === 'stabilize' && O) { const b = this.bodies[f.other] || {}; if (b.pos) this.add('ecg', t, 1, { at: [O[0], b.pos[1] - .15], w: (b.span || 1) * .8, col: FXC.heal }); }
    else if (key === 'search') this.add('ring', t, .6, { at: C, col: '#e5e7eb', r0: r, r1: r + 2, width: 2 });
    return t + .15;
  },
  // every reaction: a '!' over the reactor, its outline blinks white, its name under it (and a casting circle for a
  // spell); then a picture of its own: Shield's shell facing the attacker, crossed steel for a parry, a side-step...
  react(f, t) {
    const R = this.centre(f.id);
    if (!R) return t;
    const s = (this.bodies[f.id] || {}).span || 1, O = this.centre(f.other), key = f.key || '';
    this.add('text', t, .55, { at: [R[0], R[1] - s / 2 - .4], text: '!', col: '#ffffff', size: .55, rise: .15 });
    this.add('ring', t, .3, { at: R, col: '#ffffff', r0: s / 2, r1: s / 2 + .12, width: 3 });
    this.add('text', t + .05, 1.1, { at: [R[0], R[1] + s / 2 + .2], text: S(f.name || ''), col: '#e6e9ef', size: .24, rise: .2 });
    if (f.src) {
      const tier = Math.max(0, Math.min(3, f.tier | 0));
      this.add('glyph', t, .6, { at: R, r: s / 2 + [.15, .35, .6, .9][tier], col: SRC[f.src] || FXC.magic, tier, spin: 1 });
    }
    const ang = O ? Math.atan2(O[1] - R[1], O[0] - R[0]) : -Math.PI / 2;
    if (key === 'shield' || key === 'absorb') this.add('shell', t + .05, .8, { at: R, r: s / 2 + .22, col: key === 'shield' ? FXC.magic : tint(f.arg, FXC.magic), ang });
    else if (['parry', 'duelist', 'riposte'].includes(key)) {      // steel meets steel between them
      const P = [R[0] + Math.cos(ang) * s * .45, R[1] + Math.sin(ang) * s * .45];
      this.add('slash', t + .05, .26, { at: P, col: '#e5e7eb' });
      this.add('slash', t + .1, .26, { at: P, col: '#e5e7eb', flip: true });
      this.motes(t + .1, .35, P, '#ffffff', 8, 'burst', .4);
    } else if (key === 'uncanny' || key === 'deflect') {             // a side-step away from the line of the blow
      this.bend(f.id, t + .05, .3, 'bump', -Math.sin(ang) * .22, Math.cos(ang) * .22);
      if (key === 'deflect') this.motes(t + .1, .35, [R[0] + Math.cos(ang) * s * .45, R[1] + Math.sin(ang) * s * .45], '#e5e7eb', 8, 'burst', .35);
    } else if (key === 'counterspell' && O) this.add('ray', t + .15, .4, { a: R, b: O, col: FXC.magic, jag: false });
    else if ((key === 'barbs' || key === 'cutting') && O) this.motes(t + .1, .5, O, key === 'barbs' ? '#e5e7eb' : SRC.song, 10, 'inward', .9);
    else if (['lucky', 'second_chance', 'indomitable'].includes(key)) this.motes(t + .05, .5, R, FXC.crit, 10, 'burst', .7);
    else if (key === 'rebuke' && O) { this.add('column', t + .15, .6, { at: O, r: .6, col: DMG.fire }); this.motes(t + .15, .6, O, DMG.fire, 12, 'rise', .5); }
    else if (key === 'smite' && O) this.add('column', t, .5, { at: O, r: .55, col: DMG.radiant });
    else if (key === 'stun' && O) this.add('ring', t, .4, { at: O, col: SRC.ki, r0: .2, r1: 1, width: 3 });
    else if (key === 'orcish_fury') this.motes(t, .45, R, SRC.fury, 10, 'burst', .6);
    else if (key === 'fade_away') this.puff(t, R, '#cbd5e1', s * .55);
    else if (key === 'wings') this.add('shell', t + .05, .7, { at: R, r: s / 2 + .2, col: SRC.divine, ang });
    else if (key === 'reprisal' && O) this.add('ring', t + .1, .4, { at: O, col: FXC.magic, r0: .2, r1: .9, width: 3 });
    return t + .15;
  },
  away(A, T, d) {                                      // [dx, dy]: d tiles from A toward T
    if (!A || !T) return [0, 0];
    const L = Math.hypot(T[0] - A[0], T[1] - A[1]) || 1;
    return [(T[0] - A[0]) / L * d, (T[1] - A[1]) / L * d];
  },
  queue(f, t) {
    const k = f.k;
    if (k === 'roll') {                                // a player's d20 rolled on screen: nothing else plays meanwhile
      const roll = Math.max(.3, +f.dur || 1.8);
      this.add('dice', t, roll + REVEAL, { roll, f });
      return t + roll + REVEAL;
    }
    if (k === 'step') {
      const a = this.where[f.id] || f.to;
      (this.moves[f.id] = this.moves[f.id] || []).push([t, STEP * (f.push ? 1.4 : 1), [...a], [...f.to]]);
      this.where[f.id] = [...f.to];
      return t + STEP;
    }
    if (k === 'blink') {
      const a = this.where[f.id] || f.at || f.to, s = (this.bodies[f.id] || {}).span || 1;
      (this.moves[f.id] = this.moves[f.id] || []).push([t, .16, [...a], [...a]]);
      this.bend(f.id, t, .16, 'to', 0, 0, 0, -1);            // fades out where it was, in where it lands
      this.bend(f.id, t + .16, .2, 'from', 0, 0, 0, -1);
      this.add('ring', t, .4, { at: [a[0] + s / 2, a[1] + s / 2], col: FXC.magic, r0: .2, r1: .9 });
      this.add('ring', t + .16, .4, { at: [f.to[0] + s / 2, f.to[1] + s / 2], col: FXC.magic, r0: .9, r1: .2 });
      this.where[f.id] = [...f.to];
      return t + .2;
    }
    if (k === 'attack') {
      const A = this.centre(f.by), T = this.centre(f.id);
      if (!T) return t;
      const col = tint(f.dtype);
      let hit = t;
      if (f.melee && A) {                              // the attacker leans into its swing
        this.bend(f.by, t, .24, 'bump', ...this.away(A, T, .2));
        hit = t + .08;
      }
      if (!f.melee && A && f.item) {                   // a thrown thing: it arcs over, turning
        const dist = Math.hypot(T[0] - A[0], T[1] - A[1]), fly = Math.max(.3, Math.min(.75, .22 + dist * .05));
        const end = f.res === 'miss' ? [T[0] + .55, T[1] - .45] : T;
        this.add('toss', t, fly, { a: A, b: end, look: f.item, h: Math.min(1.4, .25 + dist * .12), spin: f.n % 2 ? 1 : -1 });
        hit = t + fly;
        if (f.item.shatter) {                          // a flask breaks where it comes down
          const glass = SHATTER[f.item.sprite] || '#e5e7eb';
          this.motes(hit, .45, end, glass, 12, 'burst', .6);
          this.add('ring', hit, .35, { at: end, col: glass, r0: .1, r1: .55 });
        }
      } else if (!f.melee && A) {
        const fly = Math.max(.12, Math.min(.32, Math.hypot(T[0] - A[0], T[1] - A[1]) * .028));
        this.add('bolt', t, fly, { a: A, b: f.res === 'miss' ? [T[0] + .55, T[1] - .45] : T, col: f.res === 'miss' ? FXC.miss : col });
        hit = t + fly;
      }
      if (f.res === 'miss') {
        if (f.melee) this.add('slash', hit, .26, { at: [T[0] + .3, T[1] - .25], col: FXC.miss });
        this.add('ring', hit, .32, { at: [T[0] + (f.melee ? .3 : .55), T[1] - .4], col: FXC.miss, r0: .05, r1: .3 });
        this.add('text', hit, .8, { at: T, text: S('miss'), col: FXC.miss, size: .34 });
        return hit + .12;
      }
      const crit = f.res === 'crit';
      if (f.melee) {
        this.add('slash', hit, .28, { at: T, col, big: crit });
        if (crit) this.add('slash', hit + .06, .28, { at: T, col: FXC.crit, big: true, flip: true });
      }
      this.add('flash', hit, .38, { tiles: this.tiles(f.id), col, peak: .55 });
      this.motes(hit, .4, T, col, crit ? 12 : 6, 'burst', crit ? .75 : .5);
      if (A) this.bend(f.id, hit, .22, 'bump', ...this.away(A, T, crit ? .14 : .08));   // the one hit flinches away
      if (crit) {
        const cx = Math.floor(T[0]), cy = Math.floor(T[1]), ring = [];
        for (const i of [-1, 0, 1]) for (const j of [-1, 0, 1]) if (i || j) ring.push([cx + i, cy + j, .05]);
        this.add('flash', hit, .45, { tiles: ring, col: FXC.crit, peak: .35 });
        this.add('ring', hit, .45, { at: T, col: FXC.crit, r0: .3, r1: 1.4 });
        this.add('text', hit, 1, { at: [T[0], T[1] - .8], text: S('CRIT!'), col: FXC.crit, size: .42 });
        this.shake(hit, 5);
      }
      return hit + .14;
    }
    if (k === 'land') {                                // the thrown thing drops to where it lies (a bounce, a short roll)
      const a = f.at, b = f.to, dur = Math.max(.28, Math.min(.5, .25 + Math.hypot(b[0] - a[0], b[1] - a[1]) * .08));
      this.add('toss', t, dur, { a, b, look: f.item, h: .35, spin: f.n % 2 ? 1 : -1, slow: true });
      for (const key of ['gid', 'did']) if (f[key] != null) this.flying[`${key}:${f[key]}`] = t + dur;   // hidden until it gets there
      return t + .05;
    }
    if (k === 'dmg') {
      const T = this.centre(f.id);
      if (!T) return t;
      const n = f.amt || 0, dtype = (f.dtype || '').toLowerCase();
      if (n > 0) {                                     // the number in its type's colour, moving its type's way
        this.add('num', t, NUM_LOOK[dtype] ? 1.1 : .95, { at: [T[0], T[1] - .1], text: String(-n), dtype, size: f.crit ? .5 : .4 });
        if (NUM_SPARKS[dtype]) this.motes(t, .9, [T[0], T[1] - .15], ...NUM_SPARKS[dtype]);
      } else this.add('text', t, .95, { at: [T[0], T[1] - .1], text: '0', col: FXC.miss, size: .4 });
      if (n > 0) {
        if (this.mine(f.id)) { this.shake(t, 10, .4); hurt(t); }
        else this.shake(t, f.crit ? 4 : 2);
      }
      return t + .05;
    }
    if (k === 'save') {
      const T = this.centre(f.id);
      if (!T) return t;
      const col = f.ok ? FXC.saved : FXC.failed;
      this.add('ring', t, .45, { at: T, col, r0: .55, r1: f.ok ? .4 : .7, width: 3 });
      this.add('text', t, .8, { at: [T[0], T[1] + .35], text: f.ok ? S('save') : S('fail'), col, size: .3 });
      return t + .04;
    }
    if (k === 'area') {
      const tiles = f.tiles || [];
      if (!tiles.length) return t;
      const dtype = (f.dtype || '').toLowerCase(), shape = f.shape || '', col = dtype ? tint(dtype, FXC.magic) : FXC.magic, A = this.centre(f.by);
      const mid = [tiles.reduce((s, p) => s + p[0], 0) / tiles.length + .5, tiles.reduce((s, p) => s + p[1], 0) / tiles.length + .5];
      const from = (q, [x, y]) => Math.hypot(x + .5 - q[0], y + .5 - q[1]);
      if ((shape === 'cone' || shape === 'line') && A) {   // from the caster outward: a sweep
        const far = Math.max(...tiles.map(p => from(A, p))), speed = shape === 'cone' ? .02 : .012, ang = Math.atan2(mid[1] - A[1], mid[0] - A[0]);
        this.add('flash', t, .4, { tiles: tiles.map(p => [p[0], p[1], from(A, p) * speed]), col, peak: .6 });
        if (shape === 'cone') {                        // a bright front running out, motes streaming with it
          const off = ([x, y]) => { let d = Math.atan2(y + .5 - A[1], x + .5 - A[0]) - ang; d = Math.atan2(Math.sin(d), Math.cos(d)); return Math.abs(d); };
          const half = Math.min(.9, Math.max(...tiles.map(off)) + .1);
          this.add('front', t, .12 + far * speed, { at: A, ang, half, far, col });
          this.motes(t, .3 + far * speed, A, col, 16, 'burst', far, .065, [ang, half]);
        } else {                                       // the whole line at once (lightning flickers)
          const B = tiles.map(([x, y]) => [x + .5, y + .5]).reduce((m, q) => Math.hypot(q[0] - A[0], q[1] - A[1]) > Math.hypot(m[0] - A[0], m[1] - A[1]) ? q : m);
          this.add('ray', t, .4, { a: A, b: B, col, jag: dtype === 'lightning' });
        }
        if (tiles.length > 12) this.shake(t, 2);
        this.decal(t + .2, tiles, dtype);
        return t + Math.min(.5, .15 + far * speed);
      }
      const o = f.at || A || mid;
      if (shape === 'cylinder') {                      // it comes from above
        this.add('column', t, .6, { at: o, r: Math.max(.6, Math.sqrt(tiles.length / Math.PI)), col });
        t += .12;
      } else if (BURSTS.includes(shape) && A && Math.hypot(o[0] - A[0], o[1] - A[1]) > 1.5 && LOBBED.includes(dtype)) {
        const fly = Math.max(.25, Math.min(.5, Math.hypot(o[0] - A[0], o[1] - A[1]) * .035));   // a bead (a flask, a glob) arcs over
        this.add('lob', t, fly, { a: A, b: o, col });
        t += fly;
      }
      const burst = BURSTS.includes(shape), speed = burst ? .035 : .025, small = tiles.length <= 9;
      let far = 0;
      const cells = tiles.map(([x, y]) => { const d = Math.hypot(x + .5 - o[0], y + .5 - o[1]); far = Math.max(far, d); return [x, y, d * speed]; });
      this.add('flash', t, small ? .3 : .5, { tiles: cells, col, peak: .6 });
      this.decal(t + .15, tiles, dtype);
      if (burst && !small) {
        this.add('ring', t, .35 + far * speed, { at: o, col, r0: .2, r1: far + .5, width: 4 });
        this.add('ring', t, .25, { at: o, col: '#fff7e0', r0: .1, r1: 1, width: 6 });
        this.motes(t, .55, o, col, 16, 'burst', Math.min(far, 3), .07);
        this.shake(t, Math.min(7, 2 + tiles.length / 25));
      } else if (small) this.add('ring', t, .3, { at: o, col, r0: .1, r1: 1.1 });
      return t + Math.min(.45, .15 + far * speed);
    }
    if (k === 'heal') {
      const T = this.centre(f.id);
      if (!T) return t;
      this.add('flash', t, .5, { tiles: this.tiles(f.id), col: FXC.heal, peak: .45 });
      this.add('ring', t, .5, { at: T, col: FXC.heal, r0: .7, r1: .2 });
      this.motes(t, .85, T, FXC.heal, 9, 'rise', .4);
      this.add('text', t, .95, { at: [T[0], T[1] - .1], text: '+' + (f.amt || 0), col: FXC.heal, size: .4 });
      return t + .06;
    }
    if (k === 'down') {
      const T = this.centre(f.id);
      if (!T) return t;
      const tiles = this.tiles(f.id), pc = f.pc !== false;
      this.add('flash', t + .1, .9, { tiles, col: FXC.down, peak: .75 });
      this.add('text', t + .1, 1.1, { at: [T[0], T[1] + .25], text: pc ? S('down') : S('defeated'), col: '#fca5a5', size: .34 });
      if (!pc && !f.summoned) this.death(f.type || '', T, tiles, t + .1, (this.bodies[f.id] || {}).name || '');   // a summon: its puff follows
      return t + .1;
    }
    if (k === 'dsave') return this.dsave(f, t);       // a death save: a pip fills; three of a kind: stable, or dead
    if (k === 'feature' || k === 'action') return this.featureFx(f, t);   // a class feature, a standard action: name and look
    if (k === 'inhale') {                              // a breath weapon draws in before it goes: the telegraph
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1;
      this.motes(t, .45, T, tint(f.dtype, '#e5e7eb'), 16, 'inward', s / 2 + 1.2, .06);
      this.bend(f.id, t, .4, 'bump', 0, 0, .06);
      return t + .35;
    }
    if (k === 'multi') {                               // Multiattack: how many attacks are coming
      const T = this.centre(f.id);
      if (T) this.add('text', t, .9, { at: [T[0], T[1] - ((this.bodies[f.id] || {}).span || 1) / 2 - .3], text: `×${f.n || 1}`, col: FXC.hit, size: .36, rise: .2 });
      return t + .05;
    }
    if (k === 'banner') {                              // the battle begins, a new round, victory: a strip across the screen
      this.add('banner', t, f.tone === 'round' ? 1.1 : 1.7, { text: S(f.text || '', f.round), tone: f.tone || '' });
      return t + .1;
    }
    if (k === 'turn') {                                // whose turn: its ring draws itself and pulses once
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1;
      this.add('sweep', t, .55, { at: T, r: s / 2 + .04, col: FXC.crit });
      this.add('ring', t + .3, .45, { at: T, col: FXC.crit, r0: s / 2, r1: s / 2 + .35, width: 2 });
      if (this.mine(f.id)) this.add('banner', t, 1.1, { text: S('Your turn'), tone: 'mine' });     // your creature: it's your turn
      return t + .05;
    }
    if (k === 'legendary') {                           // a crown flashes over it, the action's name under it
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1;
      this.add('crown', t, .9, { at: [T[0], T[1] - s / 2 - .35] });
      this.add('text', t + .05, 1.2, { at: [T[0], T[1] + s / 2 + .2], text: S(f.name || 'Legendary action'), col: LEGENDARY, size: .26, rise: .2 });
      return t + .2;
    }
    if (k === 'lres') {                                // Legendary Resistance: a gold shield bursts out of it and shatters
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1;
      this.add('shell', t, .5, { at: T, r: s / 2 + .3, col: LEGENDARY, ang: -Math.PI / 2 });
      this.add('shatter', t + .35, .5, { at: T, r: s / 2 + .3, col: LEGENDARY, spin: Math.random() * Math.PI * 2 });
      this.add('text', t + .1, 1.4, { at: [T[0], T[1] - s / 2 - .2], text: S('Legendary Resistance ({0} left)', f.left || 0), col: LEGENDARY, size: .26, rise: .3 });
      return t + .3;
    }
    if (k === 'recharge') {                            // a recharge ability is ready again: a glint
      const T = this.centre(f.id);
      if (!T) return t;
      this.motes(t, .5, T, LEGENDARY, 8, 'burst', .6);
      this.add('text', t, 1, { at: [T[0], T[1] - .3], text: S('{0} recharged', S(f.name || '')), col: LEGENDARY, size: .24, rise: .3 });
      return t + .05;
    }
    if (k === 'cast') {
      const A = this.centre(f.by), col = f.dtype ? tint(f.dtype) : SRC[f.src] || FXC.magic;
      if (A) this.add('ring', t, .4, { at: A, col, r0: .25, r1: .85, width: 3 });
      for (const id of f.ids || []) {
        const T = this.centre(id);
        if (T && (!A || T[0] !== A[0] || T[1] !== A[1])) this.add('ring', t + .12, .4, { at: T, col, r0: .85, r1: .3 });
        if (T && !f.dtype) this.motes(t + .12, .7, T, col, 7, 'rise', .4);      // no damage: something given - it rises
      }
      return t + .12;
    }
    if (k === 'cond') {                                // a condition: its icon pops over the token, then becomes a badge
      const T = this.centre(f.id), look = badgeLook()[f.name];
      if (!T || !look) return t;
      const col = look[1];
      if (f.on) {
        this.add('icon', t, .8, { id: f.id, name: f.name, col, on: true });
        this.add('ring', t + .08, .4, { at: T, col, r0: .3, r1: .85, width: 3 });
        this.add('text', t + .08, .9, { at: [T[0], T[1] + .45], text: S(f.name), col, size: .28, rise: .3 });
        this.landing[f.id + '|' + f.name] = t + .8;
        return t + .25;
      }
      this.add('icon', t, .55, { id: f.id, name: f.name, col, on: false });
      return t + .08;
    }
    if (k === 'summon') {                              // a circle where it arrives, then the token pops in out of it
      const T = this.centre(f.id);
      if (!T) return t;
      const c = this.bodies[f.id] || {}, s = c.span || 1, kind = f.type || '', col = SRC[f.src] || FXC.magic;
      const tier = Math.max(0, Math.min(3, f.tier | 0));
      let start;
      if (kind === 'familiar') { this.puff(t, T, '#cbd5e1', s * .55); start = t + .05; }      // a familiar, a steed: a little puff
      else {
        this.add('glyph', t, .85, { at: T, r: s / 2 + [.25, .35, .5, .7][tier], col, tier, spin: f.n % 2 ? 1 : -1 });
        this.twist(kind, T, s, t, col, c.name);
        start = t + .25;
      }
      this.bend(f.id, start, .12, 'in', 0, 0, 0, -1);  // unseen until now, then it pops: small, a little too big, settled
      if (kind === 'undead') this.bend(f.id, start, .35, 'in', 0, .35 * s);     // climbing up out of the floor
      else { this.bend(f.id, start, .3, 'in', 0, 0, -.8); this.bend(f.id, start + .22, .18, 'bump', 0, 0, .08); }
      this.add('ring', start + .25, .35, { at: T, col: '#d6c3a1', r0: s / 2, r1: s / 2 + .45, width: 2 });
      this.add('ring', start + .3, .4, { at: T, col: c.ally ? '#4ade80' : '#f87171', r0: s / 2 + .05, r1: s / 2 + .2, width: 3 });
      return t + .05;                                  // several arriving: one after another, quickly
    }
    if (k === 'unsummon') {                            // it shrinks away into a puff
      const s = f.span || 1, T = [f.at[0] + s / 2, f.at[1] + s / 2], c = this.old[f.id] || this.bodies[f.id];
      if (c) this.add('ghost', t, .45, { c, at: [...f.at], s });
      this.add('ring', t, .45, { at: T, col: FXC.magic, r0: s / 2 + .3, r1: .1, width: 2 });
      this.puff(t + .3, T, '#cbd5e1', s * .55);
      return t + .05;
    }
    if (k === 'turned') {                              // a summon breaks free and turns on its caster
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1;
      this.bend(f.id, t, .3, 'bump', .12);
      this.add('ring', t, .5, { at: T, col: FXC.failed, r0: s / 2, r1: s / 2 + .6, width: 4 });
      this.motes(t, .5, T, FXC.failed, 10, 'burst', s / 2 + .3);
      this.add('text', t, 1.1, { at: [T[0], T[1] - s / 2 - .3], text: S('breaks free!'), col: FXC.failed, size: .3 });
      this.shake(t, 3);
      return t + .1;
    }
    if (k === 'zone') return f.hidden ? t : this.zoneFx(f, t);   // a lasting area appears, strikes, ends, or is moved (not a hidden one)
    if (k === 'react') return this.react(f, t);        // a reaction: the same tell for all, then what it does
    if (k === 'countered') {                           // Counterspell decided: the caster's circle breaks, or the counter's ray does
      const C = this.centre(f.id), B = this.centre(f.by);
      if (!C) return t;
      if (f.ok) {
        const s = (this.bodies[f.id] || {}).span || 1;
        this.add('shatter', t, .5, { at: C, r: s / 2 + .35, col: FXC.magic, spin: Math.random() * Math.PI * 2 });
        this.add('text', t, 1, { at: [C[0], C[1] - .2], text: S('countered!'), col: FXC.magic, size: .32, rise: .4 });
        this.shake(t, 2);
      } else if (B) {
        this.add('snap', t, .5, { a: B, b: C, col: FXC.magic });
        this.add('text', t, .9, { at: [B[0], B[1] - .2], text: S('counter failed'), col: FXC.miss, size: .26, rise: .3 });
      }
      return t + .15;
    }
    if (k === 'conc') {                                // concentration: a save wobbles the ring; kept it brightens, lost it shatters
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1, col = SRC[f.src] || FXC.magic, r = s / 2 + .1;
      if (f.check) { this.add('wobble', t, .35, { at: T, r, col }); t += .35; }
      if (f.ok) { this.add('ring', t, .4, { at: T, col, r0: r, r1: r + .18, width: 4 }); return t + .05; }
      this.add('shatter', t, .5, { at: T, r, col, spin: Math.random() * Math.PI * 2 });
      for (const end of f.ends || []) this.add('snap', t, .6, { a: T, b: end, col });      // every link flashes into view and snaps
      this.add('text', t, 1, { at: [T[0], T[1] + s / 2 + .1], text: S('{0} ends', S(f.spell || '')), col, size: .24, rise: .25 });
      return t + .1;
    }
    if (k === 'tell') {                                // a lasting effect changed a number: its badge blinks, the number rises
      const T = this.centre(f.id);
      if (!T) return t;
      const s = (this.bodies[f.id] || {}).span || 1, col = (badgeLook()[f.name] || [])[1] || FXC.magic;
      this.blinks[f.id + '|' + f.name] = t;
      const text = f.half ? `½ ${S(f.name)}` : `${(+f.amt || 0) >= 0 ? '+' : ''}${+f.amt || 0} ${S(f.name)}`;
      this.add('text', t, .9, { at: [T[0], T[1] - s / 2 - .5], text, col, size: .22, rise: .35 });
      return t;
    }
    if (k === 'glyph') {                               // a casting circle under the caster: the spell gathers
      const A = this.centre(f.id);
      if (!A) return t;
      const tier = Math.max(0, Math.min(3, f.tier | 0)), s = (this.bodies[f.id] || {}).span || 1;
      const col = SRC[f.src] || FXC.magic, hold = GATHER[tier], r = s / 2 + [.15, .35, .6, .9][tier];
      this.add('glyph', t, hold + .35, { at: A, r, col, tier, spin: f.n % 2 ? 1 : -1 });
      this.motes(t, hold + .1, A, col, 6 + 4 * tier, 'inward', r);
      if (tier >= 2 && f.spell) this.add('text', t, hold + .7, { at: [A[0], A[1] - s / 2 - .2], text: S(f.spell), col, size: .26, rise: .25 });
      return t + hold;
    }
    return t;
  },
  busy() { return this.items.length || Object.keys(this.moves).length || Object.keys(this.poses).length || Object.keys(this.zoneMoves).length || this.shakes.length || Object.keys(this.flying).length; },
  loop() {
    if (this.raf) return;
    const tick = () => {
      const now = now_();
      this.items = this.items.filter(i => now < i.t0 + i.dur + Math.max(0, ...(i.tiles || []).map(c => c[2])));
      this.shakes = this.shakes.filter(s => now < s[0] + s[1]);
      for (const id in this.poses) { this.poses[id] = this.poses[id].filter(p => now < p[0] + p[1]); if (!this.poses[id].length) delete this.poses[id]; }
      for (const key in this.landing) if (now >= this.landing[key]) delete this.landing[key];
      for (const key in this.blinks) if (now >= this.blinks[key] + BLINK) delete this.blinks[key];
      for (const key in this.zoneMoves) if (now >= this.zoneMoves[key][0] + this.zoneMoves[key][1]) delete this.zoneMoves[key];
      for (const key in this.flying) if (now >= this.flying[key]) delete this.flying[key];
      this.frame = true;
      try { renderMap(); } finally { this.frame = false; }
      drawDice();
      this.raf = this.busy() ? requestAnimationFrame(tick) : 0;
    };
    this.raf = requestAnimationFrame(tick);
  },
  pos(id) {
    const segs = this.moves[id];
    if (!segs) return null;
    const now = now_();
    while (segs.length && now >= segs[0][0] + segs[0][1]) segs.shift();
    if (!segs.length) { delete this.moves[id]; return null; }
    const [t0, dur, a, b] = segs[0];
    if (now <= t0) return a;
    let u = (now - t0) / dur; u = u * u * (3 - 2 * u);
    return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
  },
  pose(id) {                                           // [dx, dy tiles, scale, opacity] a token is drawn with now, or null
    const segs = this.poses[id];
    if (!segs) return null;
    const now = now_();
    let dx = 0, dy = 0, k = 0, a = 0;
    for (const [t0, dur, ease, sx, sy, sk, sa] of segs) {
      const u = ease === 'in' ? Math.max(0, (now - t0) / dur) : (now - t0) / dur;    // 'in': already there until it starts
      if (u < 0 || u > 1) continue;
      const w = ease === 'bump' ? Math.sin(Math.PI * u) : ease === 'to' ? u * u * (3 - 2 * u) : 1 - u * u * (3 - 2 * u);
      dx += sx * w; dy += sy * w; k += sk * w; a += sa * w;
    }
    return [dx, dy, Math.max(.05, 1 + k), Math.max(0, Math.min(1, 1 + a))];
  },
  offset() {
    const now = now_();
    let dx = 0, dy = 0;
    for (const [t0, dur, amp] of this.shakes) {
      const u = (now - t0) / dur;
      if (u >= 0 && u <= 1) { const k = amp * (1 - u) ** 2; dx += k * Math.sin(u * 47); dy += k * Math.cos(u * 39); }
    }
    return [dx, dy];
  },
  under(g, T) {
    const now = now_();
    for (const i of this.items) {
      if (i.kind === 'glyph' && now >= i.t0 && now <= i.t0 + i.dur) this.glyph(g, i, now, T);
      if (i.kind === 'crack' && now >= i.t0 && now <= i.t0 + i.dur) this.crack(g, i, (now - i.t0) / i.dur, T);
      if (i.kind === 'decal' && now >= i.t0 && now <= i.t0 + i.dur) {   // fades in quickly, then slowly away
        const u = (now - i.t0) / i.dur;
        g.fillStyle = rgba(i.col, i.peak * (u < .3 ? Math.min(1, u / .05) : (1 - u) / .7));
        for (const [x, y] of i.cells) g.fillRect(x * T, y * T, T, T);
      }
      if (i.kind !== 'flash') continue;
      for (const [x, y, delay] of i.tiles) {
        const u = (now - i.t0 - delay) / i.dur;
        if (u < 0 || u > 1) continue;
        g.fillStyle = rgba(i.col, i.peak * (u < .31 ? Math.sin(Math.PI * Math.min(1, u * 1.6)) : (1 - u) / .69));
        g.fillRect(x * T, y * T, T, T);
      }
    }
  },
  // a casting circle on the floor: a soft glow, a ring of runes turning (and an inner ring from a 1st-level slot, a
  // triangle from a 3rd, a star and a broken outer ring from a 6th). Grows in, fades out as the spell goes.
  glyph(g, i, now, T) {
    const e = now - i.t0, tier = i.tier, col = i.col;
    const a = e < .15 ? Math.min(1, e / .15) : e > i.dur - .3 ? Math.max(0, (i.dur - e) / .3) : 1;
    const R = i.r * T * (.7 + .3 * (1 - (1 - Math.min(1, e / .2)) ** 2)), x = i.at[0] * T, y = i.at[1] * T;
    const spin = i.spin * e * (50 + 25 * tier) * Math.PI / 180, inner = R * .8, P = (r, q) => [x + r * Math.cos(q), y + r * Math.sin(q)];
    g.save();
    const grad = g.createRadialGradient(x, y, 0, x, y, R);
    grad.addColorStop(0, rgba(col, .22 * a)); grad.addColorStop(1, rgba(col, 0));
    g.fillStyle = grad; g.beginPath(); g.arc(x, y, R, 0, Math.PI * 2); g.fill();
    g.strokeStyle = rgba(col, .9 * a); g.lineWidth = Math.max(1.5, T * .035);
    g.beginPath(); g.arc(x, y, R, 0, Math.PI * 2); g.stroke();
    if (tier) { g.strokeStyle = rgba(col, .65 * a); g.lineWidth = Math.max(1, T * .022); g.beginPath(); g.arc(x, y, inner, 0, Math.PI * 2); g.stroke(); }
    g.strokeStyle = rgba(col, .85 * a); g.lineWidth = Math.max(1, T * .03); g.lineCap = 'round';
    const n = 8 + 4 * tier;
    g.beginPath();
    for (let j = 0; j < n; j++) {                      // the runes: ticks between the rings, long and short
      const q = spin + Math.PI * 2 * j / n, [r0, r1] = tier ? [inner * 1.04, R * (j % 2 ? .96 : .9)] : [R * .8, R * (j % 2 ? .95 : .88)];
      g.moveTo(...P(r0, q)); g.lineTo(...P(r1, q));
    }
    g.stroke();
    if (tier >= 2) {                                   // a triangle inside, a star (two triangles) at the top tier
      g.strokeStyle = rgba(col, .6 * a); g.lineWidth = Math.max(1, T * .022);
      for (const off of tier >= 3 ? [0, Math.PI] : [0]) {
        g.beginPath();
        for (let j = 0; j < 3; j++) g.lineTo(...P(inner, -spin * .6 + off + Math.PI * 2 * j / 3 - Math.PI / 2));
        g.closePath(); g.stroke();
      }
    }
    if (tier >= 3) {                                   // a broken ring outside, turning the other way
      g.strokeStyle = rgba(col, .7 * a); g.lineWidth = Math.max(1.5, T * .03);
      for (let j = 0; j < 6; j++) { const q = -spin * .8 + Math.PI / 3 * j; g.beginPath(); g.arc(x, y, R * 1.15, q, q + 38 * Math.PI / 180); g.stroke(); }
    }
    g.restore();
  },
  // a token's badges over its top edge, where it is drawn; one whose effect just changed a number swells and flashes
  // (a '+N' badge for the ones it stands for)
  badges(g, c, cx, top, T) {
    const shown = badges(c), every = (c.badges || []).filter(x => badgeLook()[x]), now = now_();
    shown.forEach((name, i) => {
      if ((this.landing[c.id + '|' + name] || 0) > now) return;       // its icon is still on its way there
      let [x, y, r] = badgeSlot(cx, top, i, shown.length, T);
      const under = name.startsWith('+') ? every.slice(BADGE_MAX - 1) : [name];
      const u = Math.max(-1, ...under.map(k => this.blinks[c.id + '|' + k] != null ? (now - this.blinks[c.id + '|' + k]) / BLINK : -1));
      const on = u >= 0 && u <= 1;
      if (on) {
        const col = (badgeLook()[name] || [])[1] || '#e6e9ef', grad = g.createRadialGradient(x, y, 0, x, y, r * 2.2);
        grad.addColorStop(0, rgba(col, .55 * (1 - u))); grad.addColorStop(1, rgba(col, 0));
        g.fillStyle = grad; g.beginPath(); g.arc(x, y, r * 2.2, 0, Math.PI * 2); g.fill();
        if (!CALM.matches) r *= 1 + .4 * Math.sin(Math.PI * u);
      }
      paintBadge(g, x, y, r, name);
      if (on) { g.strokeStyle = `rgba(255,255,255,${(.9 * (1 - u)).toFixed(3)})`; g.lineWidth = Math.max(1.5, r * .2); g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke(); }
    });
  },
  // a thrown thing in flight: its sprite (or prop) arcing from a to b over its shadow, turning over and over - or point
  // first along its path (a javelin, a dart) - with a faint trail (vfx.py: _paint_toss)
  toss(g, i, u, T) {
    const look = i.look || {}, im = look.prop ? propImage(look.prop) : spriteImage(look.sprite || 'sack');
    if (!im || !im.complete || !im.naturalWidth) return;
    const [ax, ay] = i.a, [bx, by] = i.b, h = i.h, size = T * (look.prop ? .9 : .62), turns = (i.slow ? 1.2 : 2.6) * i.dur;
    const at = v => { v = Math.min(1, Math.max(0, v)); return [ax + (bx - ax) * v, ay + (by - ay) * v - 4 * v * (1 - v) * h]; };
    const turn = v => look.point ? Math.atan2((by - ay) - 4 * h * (1 - 2 * v), bx - ax) + look.point * Math.PI / 180   // tip `point` degrees up
      : i.spin * 2 * Math.PI * turns * v - (look.prop ? 0 : .35);
    const lift = 4 * u * (1 - u) * h, k = 1 + lift * .6;
    g.fillStyle = `rgba(0,0,0,${(.35 / (1 + lift)).toFixed(3)})`;
    g.beginPath(); g.ellipse((ax + (bx - ax) * u) * T, ((ay + (by - ay) * u) + .22) * T, T * .2 / k, T * .07 / k, 0, 0, Math.PI * 2); g.fill();
    if (!i.slow) for (const [back, al] of [[.12, .18], [.06, .35]]) if (u > back) { const [x, y] = at(u - back); drawItem(g, im, x * T, y * T, size, turn(u - back), 0, al); }
    const [x, y] = at(u);
    drawItem(g, im, x * T, y * T, size * (1 + .15 * lift / Math.max(h, .01)), turn(u), 0);
  },
  // a condition's icon: going on, it pops big over the token, holds, then shrinks into its badge; going off, it lifts
  // off the badge row and fades
  icon(g, i, u, T) {
    const c = this.bodies[i.id] || {}, at = this.pos(i.id) || c.pos;
    if (!at) return;
    const s = c.span || 1, cx = (at[0] + s / 2) * T, top = at[1] * T;
    if (!i.on) {
      const [x, y, r] = badgeSlot(cx, top, 0, 1, T);
      paintBadge(g, x, y - .35 * T * u, r * (1 + .3 * u), i.name, 1 - u);
      return;
    }
    const shown = badges(c), k = shown.includes(i.name) ? shown.indexOf(i.name) : Math.max(0, shown.length - 1);
    const [sx, sy, sr] = badgeSlot(cx, top, k, Math.max(1, shown.length), T), big = .42 * T, mx = cx, my = top + s * T / 2;
    let x = mx, y = my, r = big;
    if (u < .15) { const v = u / .15 - 1; r = big * (1 + 2.70158 * v ** 3 + 1.70158 * v ** 2); }     // pops, a little too big, settles
    else if (u >= .5) { let v = (u - .5) / .5; v = v * v * (3 - 2 * v); x = mx + (sx - mx) * v; y = my + (sy - my) * v; r = big + (sr - big) * v; }
    const glow = 1 - Math.max(0, (u - .5) / .5), grad = g.createRadialGradient(x, y, 0, x, y, r * 1.9);
    grad.addColorStop(0, rgba(i.col, .4 * glow)); grad.addColorStop(1, rgba(i.col, 0));
    g.fillStyle = grad; g.beginPath(); g.arc(x, y, r * 1.9, 0, Math.PI * 2); g.fill();
    paintBadge(g, x, y, Math.max(1, r), i.name);
  },
  dots(g, i, u, T) {
    const [ax, ay] = i.at, R = i.spread;
    for (const [ang, dist, delay, sp] of i.dots) {
      const v = (u - delay) / .7;
      if (v < 0 || v > 1) continue;
      const ca = Math.cos(ang), sa = Math.sin(ang);
      let q, alpha;
      if (i.mode === 'burst') { const d = R * dist * sp * (1 - (1 - v) ** 2); q = [ax + ca * d, ay + sa * d]; alpha = 1 - v; }
      else if (i.mode === 'inward') { const d = R * (.8 + .2 * dist) * (1 - v); q = [ax + ca * d, ay + sa * d]; alpha = Math.min(1, v * 4); }
      else if (i.mode === 'fall') { q = [ax + ca * R * dist, ay - .45 + sa * R * .3 + v * .7 * sp]; alpha = Math.sin(Math.PI * v); }
      else if (i.mode === 'orbit') {                   // round and round, drawing in a little
        const a = ang + v * 2 * Math.PI * .8 * sp, d = R * (.6 + .4 * dist) * (1 - .4 * v);
        q = [ax + Math.cos(a) * d, ay + Math.sin(a) * d]; alpha = Math.sin(Math.PI * v);
      }
      else { q = [ax + ca * R * dist + Math.sin(v * 6 + ang) * .05, ay + sa * R * dist * .6 - v * .9 * sp]; alpha = Math.sin(Math.PI * v); }
      const r = Math.max(1.2, i.size * T * (i.mode === 'burst' ? 1 - .5 * v : 1));
      g.fillStyle = rgba(i.col, alpha * .25); g.beginPath(); g.arc(q[0] * T, q[1] * T, r * 2.2, 0, Math.PI * 2); g.fill();
      g.fillStyle = rgba(i.col, alpha); g.beginPath(); g.arc(q[0] * T, q[1] * T, r, 0, Math.PI * 2); g.fill();
    }
  },
  crack(g, i, u, T) {                                  // cracks running out over the floor (a dark line, a glowing core)
    const grow = Math.min(1, u / .25), a = u < .6 ? 1 : (1 - u) / .4;
    g.save(); g.lineCap = 'round'; g.lineJoin = 'round';
    for (const [style, w] of [[`rgba(11,13,18,${(.75 * a).toFixed(3)})`, Math.max(2, T * .05)], [rgba(i.col, .85 * a), Math.max(1, T * .022)]]) {
      g.strokeStyle = style; g.lineWidth = w;
      for (const pts of i.lines) {
        const n = 1 + Math.floor(grow * (pts.length - 1));
        g.beginPath(); pts.slice(0, n).forEach(([x, y], j) => j ? g.lineTo(x * T, y * T) : g.moveTo(x * T, y * T)); g.stroke();
      }
    }
    g.restore();
  },
  over(g, T) {
    const now = now_();
    g.save();
    for (const i of this.items) {
      let u = (now - i.t0) / i.dur;
      if (i.kind === 'ghost' && u < 0) u = 0;          // a leaving creature stays where it was until its turn to go
      if (u < 0 || u > 1 || ['flash', 'glyph', 'crack', 'decal'].includes(i.kind)) continue;
      g.lineCap = 'round';
      if (i.kind === 'sweep') {                        // a ring drawing itself round, then fading
        g.strokeStyle = rgba(i.col, u < .7 ? 1 : (1 - u) / .3); g.lineWidth = Math.max(2, T * .06);
        g.beginPath(); g.arc(i.at[0] * T, i.at[1] * T, i.r * T, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(1, u / .6)); g.stroke();
        continue;
      }
      if (i.kind === 'crown') {                        // a crown popping over a legendary creature
        const im = picture('crown'), x = i.at[0] * T, y = i.at[1] * T, sz = T * .55 * (1 + .25 * Math.sin(Math.PI * Math.min(1, u / .3)));
        const rg = g.createRadialGradient(x, y, 0, x, y, sz);
        rg.addColorStop(0, rgba(LEGENDARY, .5 * (1 - u))); rg.addColorStop(1, rgba(LEGENDARY, 0));
        g.fillStyle = rg; g.beginPath(); g.arc(x, y, sz, 0, Math.PI * 2); g.fill();
        if (im.complete && im.naturalWidth) { g.save(); g.globalAlpha *= u < .7 ? 1 : (1 - u) / .3; g.drawImage(im, x - sz / 2, y - sz / 2, sz, sz); g.restore(); }
        continue;
      }
      if (i.kind === 'ecg') {                          // a heartbeat line drawn across, then fading
        const trace = [[-.5, 0], [-.18, 0], [-.1, -.12], [-.03, .18], [.05, -.32], [.12, 0], [.5, 0]], n = Math.max(2, Math.floor(1 + Math.min(1, u * 1.6) * 6));
        g.strokeStyle = rgba(i.col, u < .7 ? 1 : (1 - u) / .3); g.lineWidth = Math.max(1.5, T * .05); g.lineJoin = 'round';
        g.beginPath(); trace.slice(0, n).forEach(([x, y], j) => { const X = (i.at[0] + x * i.w) * T, Y = (i.at[1] + y * i.w) * T; j ? g.lineTo(X, Y) : g.moveTo(X, Y); }); g.stroke();
        continue;
      }
      if (i.kind === 'shell') {                        // a faceted bubble; the facet facing the blow is the bright one
        const x = i.at[0] * T, y = i.at[1] * T, R = i.r * T, a = u < .12 ? Math.min(1, u / .12) : u < .6 ? 1 : (1 - u) / .4;
        const pts = [0, 1, 2, 3, 4, 5].map(j => [x + R * Math.cos(i.ang + (30 + 60 * j) * Math.PI / 180), y + R * Math.sin(i.ang + (30 + 60 * j) * Math.PI / 180)]);
        g.beginPath(); pts.forEach(([px, py], j) => j ? g.lineTo(px, py) : g.moveTo(px, py)); g.closePath();
        g.fillStyle = rgba(i.col, .12 * a); g.fill();
        g.strokeStyle = rgba(i.col, .55 * a); g.lineWidth = Math.max(1.5, T * .04); g.stroke();
        for (const [w, col, al] of [[T * .12, i.col, .9], [T * .04, '#ffffff', .9]]) {   // the facing facet
          g.strokeStyle = rgba(col, al * a); g.lineWidth = Math.max(1.5, w);
          g.beginPath(); g.moveTo(...pts[5]); g.lineTo(...pts[0]); g.stroke();
        }
        continue;
      }
      if (i.kind === 'wobble') {                       // a concentration ring shaken by a hit, while the save is rolled
        const R = i.r * T * (1 + .08 * Math.sin(u * 40) * (1 - u)), d = Math.cos(u * 33) * T * .03;
        g.strokeStyle = rgba(i.col, .95); g.lineWidth = Math.max(2, T * .05);
        g.beginPath(); g.ellipse(i.at[0] * T, i.at[1] * T, R + d, Math.max(1, R - d), 0, 0, Math.PI * 2); g.stroke();
        continue;
      }
      if (i.kind === 'shatter') {                      // the ring breaks: its pieces fly off, turning, fading
        const R = i.r * T * (1 + .9 * u);
        g.strokeStyle = rgba(i.col, 1 - u); g.lineWidth = Math.max(2, T * .05);
        for (let j = 0; j < 8; j++) {
          const a0 = i.spin + Math.PI / 4 * j + 2.1 * u * (j % 2 ? 1 : -1);
          g.beginPath(); g.arc(i.at[0] * T, i.at[1] * T, R, a0, a0 + .49); g.stroke();
        }
        continue;
      }
      if (i.kind === 'snap') {                         // a link to what the spell held: it flashes, then breaks in the middle
        const [a, b] = [i.a, i.b], m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], v = Math.max(0, (u - .35) / .65);
        const segs = u < .35 ? [[a, b]] : [a, b].map(e => [e, [e[0] + (m[0] - e[0]) * (1 - v), e[1] + (m[1] - e[1]) * (1 - v)]]);
        for (const [w, col, k2] of [[T * .14, i.col, .35], [T * .04, '#ffffff', .9]]) {
          g.strokeStyle = rgba(col, k2 * (1 - v)); g.lineWidth = Math.max(1, w);
          for (const [p0, p1] of segs) { g.beginPath(); g.moveTo(p0[0] * T, p0[1] * T); g.lineTo(p1[0] * T, p1[1] * T); g.stroke(); }
        }
        continue;
      }
      if (i.kind === 'front') {                        // a cone's bright leading edge running out from the caster
        const R = i.far * T * (1 - (1 - u) ** 2);
        g.strokeStyle = rgba(i.col, .9 * (1 - u * u)); g.lineWidth = Math.max(2, T * .12);
        g.beginPath(); g.arc(i.at[0] * T, i.at[1] * T, Math.max(.5, R), i.ang - i.half, i.ang + i.half); g.stroke();
        continue;
      }
      if (i.kind === 'ray') {                          // a line all at once: a glow, a core; lightning zig-zags and flickers
        const a = u < .5 ? 1 : (1 - u) / .5, [ax, ay] = i.a, [bx, by] = i.b;
        let pts = [i.a, i.b];
        if (i.jag) {
          let seed = Math.floor(now * 25) * 9301 + 49297;
          const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
          const L = Math.hypot(bx - ax, by - ay) || 1, nx = -(by - ay) / L, ny = (bx - ax) / L, n = Math.max(2, Math.floor(L * 2));
          pts = [i.a];
          for (let j = 1; j < n; j++) { const o = (rnd() - .5) * .36; pts.push([ax + (bx - ax) * j / n + nx * o, ay + (by - ay) * j / n + ny * o]); }
          pts.push(i.b);
        }
        g.lineJoin = 'round';
        for (const [w, col, al] of [[T * .32, i.col, .3], [T * .1, i.col, .95], [T * .035, '#ffffff', .9]]) {
          g.strokeStyle = rgba(col, al * a); g.lineWidth = Math.max(1, w);
          g.beginPath(); pts.forEach(([x, y], j) => j ? g.lineTo(x * T, y * T) : g.moveTo(x * T, y * T)); g.stroke();
        }
        continue;
      }
      if (i.kind === 'lob') {                          // a bead arcing over, its shadow running along the floor
        const [ax, ay] = i.a, [bx, by] = i.b, hgt = Math.min(2.5, Math.hypot(bx - ax, by - ay) * .25);
        const at = v => [ax + (bx - ax) * v, ay + (by - ay) * v - 4 * v * (1 - v) * hgt];
        g.fillStyle = 'rgba(0,0,0,.35)'; g.beginPath(); g.ellipse((ax + (bx - ax) * u) * T, (ay + (by - ay) * u) * T, T * .12, T * .06, 0, 0, Math.PI * 2); g.fill();
        for (const [back, rr, al] of [[.1, .1, .3], [.05, .13, .55], [0, .16, 1]]) {     // a short tail behind the bead
          const [hx, hy] = at(Math.max(0, u - back));
          g.fillStyle = rgba(i.col, al); g.beginPath(); g.arc(hx * T, hy * T, T * rr, 0, Math.PI * 2); g.fill();
        }
        const [hx, hy] = at(u);
        g.fillStyle = 'rgba(255,255,255,.9)'; g.beginPath(); g.arc(hx * T, hy * T, T * .06, 0, Math.PI * 2); g.fill();
        continue;
      }
      if (i.kind === 'ghost') {                        // it shrinks away
        const r = (i.s * T / 2 - 2) * (1 - .85 * u * u);
        g.save(); g.globalAlpha *= 1 - u ** 1.5; tokenDisc(g, i.c, (i.at[0] + i.s / 2) * T, (i.at[1] + i.s / 2) * T, Math.max(1, r)); g.restore();
      } else if (i.kind === 'column') {                // a light from above: a tall soft band standing on the point
        const x = i.at[0] * T, y = i.at[1] * T, R = i.r * T, H = 3 * T, a = u < .2 ? Math.min(1, u / .2) : (1 - u) / .8;
        const lg = g.createLinearGradient(x, y - H, x, y);
        lg.addColorStop(0, rgba(i.col, 0)); lg.addColorStop(1, rgba(i.col, .55 * a));
        g.fillStyle = lg; g.fillRect(x - R * .6, y - H, R * 1.2, H);
        g.fillStyle = `rgba(255,255,255,${(.35 * a).toFixed(3)})`; g.fillRect(x - R * .12, y - H * .8, R * .24, H * .8);
        const rg = g.createRadialGradient(x, y, 0, x, y, R);
        rg.addColorStop(0, rgba(i.col, .6 * a)); rg.addColorStop(1, rgba(i.col, 0));
        g.fillStyle = rg; g.beginPath(); g.ellipse(x, y, R, R * .5, 0, 0, Math.PI * 2); g.fill();
      } else if (i.kind === 'puff') {                  // soft blobs swelling out and thinning
        const R = i.r * T, spread = R * (.3 + .7 * u), x = i.at[0] * T, y = i.at[1] * T;
        g.fillStyle = rgba(i.col, .45 * (1 - u));
        for (const [dx, dy, rs] of i.blobs) { g.beginPath(); g.arc(x + dx * spread, y + dy * spread, R * .45 * (.5 + .5 * u) * rs, 0, Math.PI * 2); g.fill(); }
      } else if (i.kind === 'motes') this.dots(g, i, u, T);
      else if (i.kind === 'icon') this.icon(g, i, u, T);
      else if (i.kind === 'toss') this.toss(g, i, u, T);
      else if (i.kind === 'bolt') {
        const L = v => [i.a[0] + (i.b[0] - i.a[0]) * v, i.a[1] + (i.b[1] - i.a[1]) * v], hd = L(u), tl = L(Math.max(0, u - .35));
        for (const [w, a] of [[Math.max(3, T * .16), .35], [Math.max(1.5, T * .06), .95]]) {
          g.strokeStyle = rgba(i.col, a); g.lineWidth = w;
          g.beginPath(); g.moveTo(tl[0] * T, tl[1] * T); g.lineTo(hd[0] * T, hd[1] * T); g.stroke();
        }
        g.fillStyle = 'rgba(255,255,255,.9)'; g.beginPath(); g.arc(hd[0] * T, hd[1] * T, Math.max(2, T * .07), 0, Math.PI * 2); g.fill();
      } else if (i.kind === 'slash') {
        const r = T * (i.big ? .62 : .45), st = i.flip ? Math.PI * 5 / 6 : -Math.PI / 6, sw = Math.PI * 5 / 6 * Math.min(1, u * 2.2);
        g.strokeStyle = rgba(i.col, 1 - Math.max(0, u - .45) / .55); g.lineWidth = Math.max(2, T * (i.big ? .11 : .08));
        g.beginPath(); g.arc(i.at[0] * T, i.at[1] * T, r, st, st + sw); g.stroke();
      } else if (i.kind === 'ring') {
        const r = (i.r0 + (i.r1 - i.r0) * (1 - (1 - u) ** 2)) * T;
        g.strokeStyle = rgba(i.col, (1 - u) * .9); g.lineWidth = i.width || 2;
        g.beginPath(); g.arc(i.at[0] * T, i.at[1] * T, Math.max(.5, r), 0, Math.PI * 2); g.stroke();
      } else if (i.kind === 'text') {
        const a = u < .6 ? 1 : (1 - u) / .4, x = i.at[0] * T, y = (i.at[1] - (i.rise ?? .7) * u) * T;
        g.font = `700 ${Math.max(11, Math.round(T * i.size))}px Segoe UI, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillStyle = `rgba(11,13,18,${(a * .85).toFixed(3)})`; g.fillText(i.text, x + 1.2, y + 1.2);
        g.fillStyle = rgba(i.col, a); g.fillText(i.text, x, y);
      } else if (i.kind === 'num') this.num(g, i, u, now - i.t0, T);
    }
    g.restore();
  },
  num(g, i, u, s, T) {                                 // a damage number, character by character (numGlyph), with its type's glow, rim or doubles
    const look = NUM_LOOK[i.dtype] || {}, rise = look.rise ?? .7, chars = [...i.text];
    const lift = i.dtype === 'piercing' ? rise * (1 - (1 - u) ** 3) : rise * u, fade = u < .6 ? 1 : (1 - u) / .4;
    g.font = `700 ${Math.max(11, Math.round(T * i.size))}px Segoe UI, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
    const widths = chars.map(ch => g.measureText(ch).width), y = (i.at[1] - lift) * T;
    let x = i.at[0] * T - widths.reduce((m, w) => m + w, 0) / 2;
    chars.forEach((ch, j) => {
      const [dx, dy, sx, sy, rot, col, al] = numGlyph(i.dtype, u, s, j, chars.length), a = al * fade;
      g.save();
      g.translate(x + widths[j] / 2 + dx * T, y + dy * T); g.rotate(rot * Math.PI / 180); g.scale(sx, sy);
      if (look.ghosts) {                               // psychic: faint doubles drifting either side
        const off = Math.sin(s * 4 + j) * T * .07;
        g.fillStyle = rgba(col, .35 * a); g.fillText(ch, off, -off * .4); g.fillText(ch, -off, off * .4);
      }
      g.fillStyle = `rgba(11,13,18,${(a * .85).toFixed(3)})`; g.fillText(ch, 1.2, 1.2);
      if (look.edge) { g.strokeStyle = rgba(look.edge, .9 * a); g.lineWidth = 2; g.strokeText(ch, 0, 0); }   // cold, force: a thin bright rim
      if (look.glow) { g.shadowColor = rgba(look.glow, .9 * a); g.shadowBlur = Math.max(4, T * .18); }       // fire, lightning, radiant: a halo
      g.fillStyle = rgba(col, a); g.fillText(ch, 0, 0);
      g.restore();
      x += widths[j];
    });
  },
};
/** Async rolling: a player's d20 tumbling in the middle of the screen (over the map or the sheet) until it lands,
 *  then the total against the AC or DC and what came of it. The DM's screens show the same roll. */
const OUTCOME = { crit: 'Critical hit!', hit: 'Hit', miss: 'Miss', saved: 'Saved', failed: 'Failed', success: 'Success',
  failure: 'Failure', 'two failures': 'Two failures', 'back up': 'Natural 20: back up with 1 HP' };
const GOOD = { hit: '#4ade80', saved: '#4ade80', success: '#4ade80', 'back up': '#fbbf24', crit: '#fbbf24' };
function outcomeWord(r) {
  return { crit: S('Critical hit!'), hit: S('Hit'), miss: S('Miss'), saved: S('Saved'), failed: S('Failed'), success: S('Success'),
    failure: S('Failure'), 'two failures': S('Two failures'), 'back up': S('Natural 20: back up with 1 HP') }[r] || OUTCOME[r] || r;
}
function drawDice() {
  const now = now_(), live = FX.items.filter(i => (i.kind === 'dice' || i.kind === 'banner') && now >= i.t0 && now <= i.t0 + i.dur);
  let cv = $('dicefx');
  if (!cv) { if (!live.length) return; cv = document.createElement('canvas'); cv.id = 'dicefx'; document.body.appendChild(cv); }
  const dpr = window.devicePixelRatio || 1, W = innerWidth, H = innerHeight;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
  }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  for (const i of live) (i.kind === 'banner' ? paintBanner : paintDice)(g, W, H, i, now);
}
const BANNER = { start: '#fbbf24', round: '#e6e9ef', victory: '#fcd34d', end: '#9aa3b2', mine: '#fbbf24' };   // text colour by tone
/** A strip across the screen with a word, sliding in and out: a new round high up and small; the battle beginning,
 *  victory and your turn bigger, a third of the way down (vfx.py _paint_banner draws the same on the DM's map). */
function paintBanner(g, W, H, i, now) {
  const u = (now - i.t0) / i.dur, small = i.tone === 'round', h = small ? 34 : 60, y = H * (small ? .08 : .26);
  const a = u < .15 ? Math.min(1, u / .15) : u < .75 ? 1 : (1 - u) / .25;
  const slide = CALM.matches ? 0 : (1 - Math.min(1, u / .15)) ** 2 * 60 - (Math.max(0, u - .75) / .25) ** 2 * 60, col = BANNER[i.tone] || '#e6e9ef';
  const lg = g.createLinearGradient(0, y, W, y);
  [[0, 0], [.2, .78], [.8, .78], [1, 0]].forEach(([stop, al]) => lg.addColorStop(stop, `rgba(10,12,16,${(al * a).toFixed(3)})`));
  g.save();
  g.fillStyle = lg; g.fillRect(0, y, W, h);
  g.fillStyle = rgba(col, .6 * a); g.fillRect(W * .25, y, W * .5, 1.5); g.fillRect(W * .25, y + h - 1.5, W * .5, 1.5);
  g.font = `700 ${small ? 18 : 30}px Segoe UI, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillStyle = rgba(col, a); g.fillText(i.text, W / 2 + slide, y + h / 2);
  g.restore();
}
function paintDice(g, W, H, i, now) {
  const f = i.f, e = now - i.t0, prog = Math.min(1, e / i.roll), ease = 1 - (1 - prog) ** 3, done = prog >= 1;
  const dice = (f.dice && f.dice.length ? f.dice : [f.kept || 1]).map(Number), kept = +f.kept || dice[0], n = dice.length;
  const R = Math.max(30, Math.min(60, Math.min(W, H) * .085)), cx = W / 2, cy = H * .42;
  g.font = '700 20px Segoe UI, sans-serif';
  const segs = rollMaths(f, kept), widths = segs.map(([text, , chip]) => g.measureText(text).width + (chip == null ? 0 : 12));
  const w = Math.min(W - 16, Math.max(280, n * R * 2.5 + 60, widths.reduce((a, b) => a + b, 0) + 40));
  const fade = e < i.dur - .25 ? 1 : Math.max(0, (i.dur - e) / .25);
  g.save();
  g.globalAlpha = fade;
  g.fillStyle = 'rgba(10,12,16,.73)';
  g.beginPath(); g.roundRect ? g.roundRect(cx - w / 2, cy - R - 36, w, 2 * R + 104, 14) : g.rect(cx - w / 2, cy - R - 36, w, 2 * R + 104); g.fill();
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.font = '13px Segoe UI, sans-serif'; g.fillStyle = 'rgba(230,233,239,.82)';
  g.fillText(`${f.who || ''} · ${f.label || ''}`, cx, cy - R - 21);
  const first = Math.max(0, dice.indexOf(kept));
  dice.forEach((d, k) => {
    const calm = CALM.matches, x = cx + (k - (n - 1) / 2) * R * 2.5, spin = calm ? 0 : (1 - ease) * 900 * (k % 2 ? -1 : 1);
    const hop = calm ? 0 : Math.abs(Math.sin(ease * Math.PI * 3)) * (1 - ease) * R * .5;
    const step = Math.floor(ease * 24);               // the ease-out spends its last third on step 23: settle on the real face
    const shown = done || step >= 23 ? d : (kept * 7 + k * 11 + d * 3 + step * 7) % 20 + 1;
    const pop = done && e - i.roll < .25 ? 1 + .16 * Math.sin(Math.min(1, (e - i.roll) / .25) * Math.PI) : 1;
    d20(g, x, cy - hop, R * pop, spin, shown, done ? d : 0, done && n > 1 && k !== first);
  });
  if (done) {
    g.font = '700 20px Segoe UI, sans-serif';
    let x = cx - widths.reduce((a, b) => a + b, 0) / 2;
    segs.forEach(([text, col, chip], j) => {
      const wd = widths[j], mid = x + wd / 2;
      if (chip == null) { g.fillStyle = col; g.fillText(text, mid, cy + R + 22); }
      else {                                           // an effect's die joins the roll: it drops in, one after another
        const u = Math.max(0, Math.min(1, (e - i.roll - .12 - .16 * chip) / .22)), y = cy + R + 22 - (CALM.matches ? 0 : 12 * (1 - u) ** 2);
        g.globalAlpha = fade * u;
        g.fillStyle = rgba(col, .22); g.beginPath();
        g.roundRect ? g.roundRect(x + 4, y - 12, wd - 8, 24, 8) : g.rect(x + 4, y - 12, wd - 8, 24); g.fill();
        g.fillStyle = col; g.fillText(text, mid, y);
        g.globalAlpha = fade;
      }
      x += wd;
    });
    g.font = '700 17px Segoe UI, sans-serif'; g.fillStyle = GOOD[f.res] || '#f87171';
    g.fillText(outcomeWord(f.res), cx, cy + R + 50);
  }
  g.restore();
}
/** The landed roll's sum as [text, colour, chip number or null]: the die, the creature's own bonus, each effect that
 *  added to it as a chip in its colour (Bless, Bane...), the total and what it is against. */
function rollMaths(f, kept) {
  const bonus = +f.bonus || 0, total = +f.total || kept, chips = f.chips || [];
  const own = bonus - chips.reduce((s, [, n]) => s + (+n), 0), sign = n => `${n >= 0 ? '+' : '−'} ${Math.abs(n)}`;
  const segs = [[String(kept), '#f5f6f8', null]];
  if (own) segs.push([` ${sign(own)}`, '#f5f6f8', null]);
  chips.forEach(([name, n], j) => segs.push([`${sign(+n)} ${S(name)}`, (badgeLook()[name] || [])[1] || (+n >= 0 ? '#fcd34d' : '#a78bfa'), j]));
  segs.push([(bonus ? ` = ${total}` : '') + `   ${S('vs')} ${f.vs || ''}`, '#f5f6f8', null]);
  return segs;
}
/** A d20 seen face on: a hexagon, the front triangle with the number, the edges running out to the rim. */
function d20(g, x, y, R, angle, shown, nat, dim) {
  const [body, face, edge] = nat === 20 ? ['#7a4b05', '#b8860b', '#fde68a'] : nat === 1 ? ['#5b1010', '#8b1a1a', '#fca5a5'] : ['#3b1f75', '#5b34a8', '#c4b5fd'];
  const at = (r, a) => [r * Math.cos(a * Math.PI / 180), r * Math.sin(a * Math.PI / 180)];
  const rim = [0, 1, 2, 3, 4, 5].map(j => at(R, -90 + 60 * j)), tri = [-90, 30, 150].map(a => at(R * .6, a));
  const poly = pts => { g.beginPath(); pts.forEach(([px, py], j) => j ? g.lineTo(px, py) : g.moveTo(px, py)); g.closePath(); };
  g.save(); g.translate(x, y); g.rotate(angle * Math.PI / 180);
  if (dim) g.globalAlpha *= .35;
  g.strokeStyle = edge; g.lineWidth = 2; g.fillStyle = body; poly(rim); g.fill(); g.stroke();
  g.lineWidth = 1.4;
  [[5, 0, 1], [1, 2, 3], [3, 4, 5]].forEach((js, t) => js.forEach(j => { g.beginPath(); g.moveTo(...tri[t]); g.lineTo(...rim[j]); g.stroke(); }));
  g.fillStyle = face; g.lineWidth = 1.6; poly(tri); g.fill(); g.stroke();
  g.fillStyle = '#fff'; g.font = `700 ${Math.round(R * .42)}px Segoe UI, sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(String(shown), 0, 0);
  g.restore();
}
/** The red edge on the screen when your own creature gets hurt: in fast, gone within a second. */
function hurt(at) {
  if (CALM.matches) return;
  let el = $('hurt');
  if (!el) { el = document.createElement('div'); el.id = 'hurt'; document.body.appendChild(el); }
  setTimeout(() => { el.classList.remove('on'); void el.offsetWidth; el.classList.add('on'); }, Math.max(0, (at - now_()) * 1000));
}

// ---------------------------------------------------------------- the map
function tokenDisc(g, c, cx, cy, r) {                  // a token's picture (or initials) in its circle
  g.save(); g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.closePath();
  g.fillStyle = c.kind === 'pc' ? '#2f4a7a' : c.ally ? '#2f6a4a' : '#6a2f35'; g.fill();
  const im = c.token && (c.mine || vq() !== 'potato') ? image(c.id, c.token) : null;   // (Potato: only their own picture)
  if (im && im.complete && im.naturalWidth) { g.clip(); g.drawImage(im, cx - r, cy - r, r * 2, r * 2); }
  else { g.fillStyle = '#fff'; g.font = `600 ${Math.max(8, r * .8)}px Segoe UI`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(c.name.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase(), cx, cy); }
  g.restore();
}
/** [x, y, w, h] in tiles that the map fits to: the placed creatures with room around them (it only grows, so moving
 *  tokens don't shift the view; Fit starts it over), or the whole map when they spread over most of it. */
function fitBox(b) {
  const W = b.map.w, H = b.map.h, key = `${b.name}|${W}x${H}`;
  if (UI.fitKey !== key) { UI.fitKey = key; UI.fitBox = null; }
  const placed = b.combatants.filter(c => c.pos);
  if (!placed.length) return [0, 0, W, H];
  let [x0, y0, x1, y1] = UI.fitBox || [Infinity, Infinity, -Infinity, -Infinity];
  for (const c of placed) {
    const s = c.span || 1;
    x0 = Math.min(x0, c.pos[0] - 2); y0 = Math.min(y0, c.pos[1] - 2); x1 = Math.max(x1, c.pos[0] + s + 2); y1 = Math.max(y1, c.pos[1] + s + 2);
  }
  const grow = (lo, hi, least, max) => {                // at least `least` tiles across, inside the map
    const extra = Math.max(0, least - (hi - lo)) / 2;
    lo -= extra; hi += extra;
    if (lo < 0) { hi -= lo; lo = 0; }
    if (hi > max) { lo = Math.max(0, lo - (hi - max)); hi = max; }
    return [lo, hi];
  };
  [x0, x1] = grow(x0, x1, 12, W); [y0, y1] = grow(y0, y1, 8, H);
  UI.fitBox = [x0, y0, x1, y1];
  if ((x1 - x0) * (y1 - y0) > .6 * W * H) return [0, 0, W, H];
  return [x0, y0, x1 - x0, y1 - y0];
}
function renderMap() {
  if (document.body.classList.contains('worldmode') || document.body.classList.contains('bglobby')) return;   // the world map (world.js), a Battlegrounds lobby (battlegrounds.js)
  const b = ST.battle, cv = $('board'), wrap = $('mapwrap');
  let veil = $('bhidden');                             // the DM keeps the map to themselves: the turn order only
  if (!veil) { veil = h('div', { id: 'bhidden', class: 'hide' }); wrap.append(veil); }
  veil.textContent = S('The DM keeps the battle map hidden. You see the turn order.');
  veil.classList.toggle('hide', !b.hidden);
  $('bname').textContent = b.name || S('Battle');
  $('round').textContent = b.status === 'active' ? S('Round {0}', b.round) : b.status === 'setup' ? S('Waiting for the battle to start.') : S('No battle right now.');
  if (UI.target && !b.combatants.some(c => c.id === UI.target)) UI.target = null;
  if (UI.inspect && !b.combatants.some(c => c.id === UI.inspect)) UI.inspect = null;
  if (UI.sel && !b.combatants.some(c => c.id === UI.sel)) UI.sel = null;
  const walker = moveArmed(b) ? mover() : null;      // the token a right-click walks: ringed
  const W = b.map.w, H = b.map.h, vw = wrap.clientWidth, vh = Math.max(160, wrap.clientHeight), dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(vw * dpr) || cv.height !== Math.round(vh * dpr)) {
    cv.width = Math.round(vw * dpr); cv.height = Math.round(vh * dpr); cv.style.width = vw + 'px'; cv.style.height = vh + 'px';
  }
  if (!UI.cam) {                                       // fit the creatures (or the whole map) until the player pans or zooms
    const top = (b.map.hi || 0) > (b.map.lo || 0) ? 18 : 0;   // room for the floors' names
    const [bx, by, bw, bh] = fitBox(b);
    const z = Math.max(6, Math.min(72, (vw - 16) / bw, (vh - 16 - top) / bh));
    const spread = (lo, len, want, max) => {            // the view holds more than the box: more of the map, not the void past its edge
      if (want <= len) return lo - (want - len) / 2;
      if (want >= max) return (max - want) / 2;          // the whole map fits that way: centred
      return Math.max(0, Math.min(max - want, lo - (want - len) / 2));
    };
    UI.camFit = { x: 8 - spread(bx, bw, (vw - 16) / z, W) * z, y: 8 + top - spread(by, bh, (vh - 16 - top) / z, H) * z, z };
  }
  const main = floorsOf(b.map).find(([f]) => f === 0)[1] + (b.map.ox || 0), top = b.map.oy || 0;   // a floor added or taken
  if (UI.cam && UI.main != null && UI.main !== main) UI.cam.x -= (main - UI.main) * UI.cam.z;      // away below, the map grown
  if (UI.cam && UI.top != null && UI.top !== top) UI.cam.y -= (top - UI.top) * UI.cam.z;           // on its left or top: what
  UI.main = main; UI.top = top;                                                                    // is on it stays put
  const cam = UI.cam || UI.camFit, T = cam.z;
  UI.tile = T;
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = '#0f1115'; g.fillRect(0, 0, vw, vh);
  g.translate(cam.x, cam.y);
  const [shx, shy] = FX.offset();
  g.translate(shx, shy);
  const FW = b.map.fw || W, floors = floorsOf(b.map);   // the floors of a building, side by side (gaps between them)
  g.fillStyle = b.map.light === 'dark' ? '#0c0e12' : b.map.light === 'dim' ? '#12151c' : '#161a22';
  for (const [, x0] of floors) g.fillRect(x0 * T, 0, FW * T, H * T);
  const view = [(-cam.x - shx) / T, (-cam.y - shy) / T, (vw - cam.x - shx) / T, (vh - cam.y - shy) / T];   // the tiles in sight
  UI.view = view;
  const ground = drawImages(g, b, T, 'ground');        // a battle map picture: under the grid
  drawTerrain(g, b, T, view);                          // painted mud, water, undergrowth...
  drawRoads(g, b, T, view);
  drawHighGround(g, b, T, view);
  g.strokeStyle = ground ? 'rgba(170,180,200,.22)' : '#232a37'; g.lineWidth = 1;
  if (T >= 6) {                                        // (zoomed far out the lines would only grey the map)
    g.beginPath();                                     // only the lines in sight, in one go
    const j0 = Math.max(0, Math.floor(view[1])), j1 = Math.min(H, Math.ceil(view[3]));
    for (const [, x0] of floors) {
      const i0 = Math.max(0, Math.floor(view[0] - x0)), i1 = Math.min(FW, Math.ceil(view[2] - x0));
      if (i0 > i1 || j0 > j1) continue;
      for (let x = x0 + i0; x <= x0 + i1; x++) { g.moveTo(Math.round(x * T) + .5, j0 * T); g.lineTo(Math.round(x * T) + .5, j1 * T); }
      for (let y = j0; y <= j1; y++) { g.moveTo((x0 + i0) * T, Math.round(y * T) + .5); g.lineTo((x0 + i1) * T, Math.round(y * T) + .5); }
    }
    g.stroke();
  }
  if (floors.length > 1) {                             // each floor's name over it
    g.font = `600 ${Math.max(10, Math.min(14, T * .45))}px Segoe UI`; g.textAlign = 'center'; g.textBaseline = 'bottom';
    for (const [f, x0] of floors) { g.fillStyle = f === 0 ? '#e6e9ef' : '#9aa3b5'; g.fillText(floorName(f), (x0 + FW / 2) * T, -4); }
  }
  drawRooms(g, b, T, dpr);
  drawCliffs(g, b, T, view);
  drawMap(g, b, T, view);
  drawLight(g, b, T, dpr);
  drawZones(g, b, T);                                  // (spell areas over the dark: they stay readable)
  drawGround(g, b, T);
  FX.under(g, T);
  drawAim(g, b, T);
  const disc = (c, cx, cy, r) => tokenDisc(g, c, cx, cy, r);
  const ghost = UI.ghost && b.combatants.find(c => c.id === UI.ghost.id);
  if (ghost) {                                         // where my token goes, until the table answers
    const s = ghost.span * T, cx = UI.ghost.at[0] * T + s / 2, cy = UI.ghost.at[1] * T + s / 2, r = s / 2 - 2;
    g.save(); g.globalAlpha = .5; disc(ghost, cx, cy, r); g.restore();
    g.strokeStyle = '#7c8cff'; g.lineWidth = 2; g.setLineDash([4, 3]); g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
  }
  for (const c of b.combatants) {
    if (!c.pos) continue;
    const box = c.box || [c.pos[0], c.pos[1], c.span], walked = FX.pos(c.id);   // a Tiny token: half a tile, where it stands
    const [x, y] = walked ? [walked[0] + box[0] - c.pos[0], walked[1] + box[1] - c.pos[1]] : box;
    const pose = FX.pose(c.id);   // a lunge, a flinch, a fade
    const s = box[2] * T, cx = x * T + s / 2 + (pose ? pose[0] * T : 0), cy = y * T + s / 2 + (pose ? pose[1] * T : 0);
    const veil = c.veil;   // banished, invisible...: see-through and tinted
    const r = (s / 2 - 2) * (pose ? pose[2] : 1) * (veil ? veil[1] : 1);
    g.globalAlpha = (pose ? pose[3] : 1) * (veil ? veil[0] : 1);
    if (c.conc && !c.out) {                            // concentrating: a dashed ring at its feet, in the colour of its magic
      g.strokeStyle = rgba(SRC[c.conc.src] || FXC.magic, .85); g.lineWidth = Math.max(1.5, T * .04); g.setLineDash([3, 2]);
      g.beginPath(); g.arc(cx, cy, r + 2 + T * .1, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
    }
    disc(c, cx, cy, r);
    if (veil) {
      g.fillStyle = rgba(veil[2], .28); g.strokeStyle = veil[2]; g.lineWidth = 2; g.setLineDash([4, 3]);
      g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill(); g.stroke(); g.setLineDash([]);
    }
    const aimed = UI.aim && (UI.aim.targets.includes(c.id) || (UI.aim.hit || []).includes(c.id));
    g.lineWidth = c.turn || aimed ? 3 : 2;
    g.strokeStyle = aimed ? '#ff8c28' : c.turn ? '#fbbf24' : c.mine ? '#7c8cff' : c.ring || '#0009';   // else its faction's colour
    if (!c.framed || aimed || c.turn || c.mine) { g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.stroke(); }   // a framed token has its own border
    if (c.turn) { g.lineWidth = 1.5; g.beginPath(); g.arc(cx, cy, r + 3.5, 0, Math.PI * 2); g.stroke(); }          // whose turn: a double ring
    if (walker && c.id === walker.id && !UI.aim) {      // picked to walk: a soft green halo outside its rings
      g.save(); g.strokeStyle = '#4ade80'; g.lineWidth = 2.5; g.shadowColor = '#4ade80'; g.shadowBlur = Math.max(6, r * .5);
      g.beginPath(); g.arc(cx, cy, r + (c.turn ? 7 : 4), 0, Math.PI * 2); g.stroke(); g.restore();
    } else if (c.id === UI.target || c.id === UI.inspect) {      // the target: a dashed ring (not only a colour)
      g.strokeStyle = c.id === UI.target ? '#f87171' : '#e6e9ef'; g.lineWidth = 2.5; g.setLineDash([Math.max(3, r * .35), Math.max(2, r * .22)]);
      g.beginPath(); g.arc(cx, cy, r + (c.turn ? 7 : 3.5), 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
    }
    if (T >= 14 && c.kind !== 'pc') {                   // a foe's red triangle, an ally's green dot: the side by shape too
      const m = Math.max(4, r * .34), mx = cx - r * .72, my = cy - r * .72;
      g.beginPath();
      if (!c.ally) { g.moveTo(mx, my - m * .6); g.lineTo(mx + m * .6, my + m * .5); g.lineTo(mx - m * .6, my + m * .5); g.closePath(); g.fillStyle = '#f87171'; }
      else { g.arc(mx, my, m * .45, 0, Math.PI * 2); g.fillStyle = '#4ade80'; }
      g.fill(); g.lineWidth = 1; g.strokeStyle = '#0b0d12'; g.stroke();
    }
    const n = UI.aim ? UI.aim.targets.filter(x => x === c.id).length : 0;
    if (n > 1) { g.fillStyle = '#ff8c28'; g.font = `700 ${Math.max(9, r * .7)}px Segoe UI`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('×' + n, cx + r * .7, cy - r * .7); }
    if (c.out) { g.strokeStyle = '#f87171'; g.beginPath(); g.moveTo(cx - r * .6, cy - r * .6); g.lineTo(cx + r * .6, cy + r * .6); g.stroke(); }
    if (T >= 40) { g.fillStyle = '#e6e9efcc'; g.font = '11px Segoe UI'; g.textAlign = 'center'; g.textBaseline = 'alphabetic'; g.fillText(c.name.slice(0, Math.floor(s / 6.5)), cx, y * T + s + 11); }
    if (!c.out) FX.badges(g, c, cx, cy - r - 2, T);    // its conditions, over its top edge
    g.globalAlpha = 1;
    paintPips(g, c, cx - r - 2, cy - r - 2, 2 * r + 4);    // dying: its death saves, on its bottom edge
  }
  const holder = b.combatants.find(c => c.conc && c.pos && (c.id === UI.inspect || c.id === UI.target));
  if (holder) {                                        // the tapped caster: what its concentration holds, faint dashed lines
    const mid = c => [c.pos[0] + (c.span || 1) / 2, c.pos[1] + (c.span || 1) / 2], A = mid(holder), col = SRC[holder.conc.src] || FXC.magic;
    const ends = b.combatants.filter(c => c !== holder && c.pos && (c.held_by || []).includes(holder.id)).map(mid)
      .concat((b.zones || []).filter(z => z.conc_by === holder.id && z.tiles.length)
        .map(z => [z.tiles.reduce((s, p) => s + p[0], 0) / z.tiles.length + .5, z.tiles.reduce((s, p) => s + p[1], 0) / z.tiles.length + .5]));
    g.lineWidth = Math.max(1.5, T * .035); g.setLineDash([6, 4]);
    for (const [x, y] of ends) {
      g.strokeStyle = rgba(col, .6); g.beginPath(); g.moveTo(A[0] * T, A[1] * T); g.lineTo(x * T, y * T); g.stroke();
      g.fillStyle = rgba(col, .8); g.beginPath(); g.arc(x * T, y * T, Math.max(2.5, T * .07), 0, Math.PI * 2); g.fill();
    }
    g.setLineDash([]);
  }
  drawImages(g, b, T, 'top');                          // roofs, canopies: over the tokens
  groundLabel(g, b, T);
  FX.over(g, T);
  drawPing(g, T);
  if (FX.frame) return;                                // an animation frame: the board only
  $('target').replaceChildren(...targetInfo(b));
  renderKnown(b);
  const tap = touch(), walk = walker ? 'armed' : canMove(b) && mover() ? 'pick' : '';
  $('hint').textContent = UI.aim ? (tap ? S('Tap to aim, tap the same place again (or Confirm) to use it. Tap ✕ to cancel.') : S('Right-click or Esc cancels.')) :
    (walk === 'armed' ? (tap ? S('Tap a tile to see the way, tap again (or Move here) to go.') : S('Right-click a tile to walk there.')) + ' · '
      : walk === 'pick' ? (tap ? S('Tap your token to pick it, then tap where it should go.') : S('Click your token to pick it, then right-click where it should go.')) + ' · ' : '') +
    (tap ? S('Drag to move around, pinch to zoom, tap a creature to target it. Hold a button for its details.') : S('Drag to move around, scroll to zoom, click a creature to target it.')) +
    (!tap && !UI.aim && b.actions ? ' · ' + S('Keys 1–9: actions, Ctrl+Space: end turn') : '');
  $('hint').title = $('hint').textContent;          // (one line on short screens: all of it on hover)
  renderOrder(b);
}
/** A creature's hit points as this player may see them: exact (their own side's, or shown by the DM), else in words
 *  coloured green (Stable) to red (Extremely Wounded). */
function hpWords(c) {
  if (c.hp != null) return h('span', null, `${c.hp}/${c.max_hp}`);
  return h('span', { class: 'hpword', style: c.health_color ? `color:${c.health_color}` : '' }, c.health || '');
}
/** The target line above the map: the creature you target (or last tapped) - name, health, conditions, distance. */
function targetInfo(b) {
  const id = UI.inspect || UI.target, c = b.combatants.find(x => x.id === id);
  if (!c) return [];                                  // (nothing picked: the hint under the map says how)
  const me = meInBattle() || b.combatants.find(x => x.mine && x.pos), look = badgeLook();
  const far = me && me.pos && c.pos && me.id !== c.id ? Geo.dist(me, c) : null;
  return [h('span', { class: 'tgt', tip: () => tokenCard(c), 'aria-label': (c.id === UI.target ? S('Target') : S('Selected')) + ': ' + c.name },
    c.id === UI.target ? '🎯 ' : '👁 ', h('b', null, c.name), ' · ', c.form ? `${c.form.name} ${c.form.hp}/${c.form.max_hp} · ` : '', hpWords(c),   // the rest on hover
    ...(c.badges || []).slice(0, 3).map(k => h('span', { class: 'bdg', style: `color:${(look[k] || [])[1] || 'var(--warn)'}` }, gi(k, 'sm'))),
    far != null ? ' · ' + S('{0} ft', far) : null),
    ' ', h('button', { class: 'sm flat', onclick: () => { UI.target = null; UI.inspect = null; renderMap(); }, 'aria-label': S('Clear the target') }, '✕')];
}
/** The initiative order beside the map. Whose turn it is: green = yours, red = an enemy's, yellow = another player's. */
function renderOrder(b) {
  $('inittitle').textContent = S('Initiative');
  const side = c => c.mine ? 'us' : c.ally ? 'ally' : 'foe';
  const dot = { us: '#4ade80', ally: '#fbbf24', foe: '#f87171' };
  $('order').replaceChildren(...b.combatants.map(c => h('div', {
    class: `oc ${side(c)}` + (c.turn ? ' turn' : '') + (c.mine ? ' mine' : '') + (c.id === UI.target ? ' tgt' : '') + (c.out ? ' out' : ''),
    tip: () => tokenCard(c),                            // the map's hover card
    onclick: () => { if (c.pos) centerOn(c); tapToken(c); } },
    h('i', null, c.init ?? '–'), h('span', { class: 'dot', style: `background:${dot[side(c)]}` }),
    h('span', { class: 'n' }, (c.turn ? '▶ ' : '') + c.name),
    ...(c.badges || []).slice(0, 3).map(k => h('span', { class: 'bdg', style: `color:${(badgeLook()[k] || [])[1] || 'var(--warn)'}` }, gi(k))),
    h('span', { class: 'hpw' }, hpWords(c)))));
  const cur = b.combatants.findIndex(c => c.turn);
  if (cur >= 0 && b.status === 'active' && $('order').children[cur]) $('order').children[cur].scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const btn = $('endturn');
  btn.textContent = '⏭ ' + S('End turn');                 // (the DM says Next turn: for a player it is the end of theirs)
  btn.disabled = !(b.status === 'active' && b.my_turn);
  btn.title = btn.disabled ? S('You can end your turn when it is your turn.') : S('End your turn: the next creature in the order goes') + ' (Ctrl+Space)';
}
/** Ending the turn early: say what is still unused (action, bonus action, movement) and ask first. */
$('endturn').onclick = go(() => {
  const a = ST.battle.actions, left = [];
  if (a && a.economy && a.is_turn) {
    const t = a.turn, all = [...a.groups.flatMap(g => g.items), ...a.spells.flatMap(g => g.items)];
    const can = k => all.some(i => i.ok && COST_CLASS[(i.cost || '').split(':')[0]] === k);
    if (t.action > 0 && can('action')) left.push(S('your action'));
    if (t.bonus > 0 && can('bonus')) left.push(S('your bonus action'));
    if (t.move > 0) left.push(S('{0} ft of movement', t.move));
  }
  const end = () => { UI.move = null; if (UI.aim) cancelAim(); return act('end_turn', {}, true); };
  if (!left.length) return end();
  detail(S('End your turn? You still have {0}.', left.join(', ')), () => [[S('End turn'), end], [S('Keep playing'), () => null, 'flat']]);
  return null;                                            // (the page's own sheet, not the browser's: Enter ends, Esc stays)
});
/** The DM's rooms (b.rooms, the plan from battle/rooms.py), in the old-school hand-drawn look the DM's map has
 * (roomart.py): paper with stipple and a stone here and there, a pale floor with an inked grid and cracks, a shadow
 * inside the walls, thick walls and doors. The scatter comes from roomRand, the same numbers as the DM's map; the
 * rooms are drawn once for a zoom into a picture, panning only moves it. */
const ROOM = { ink: '#1d1915', paper: '#f2ede1', floor: '#f6f2e9', cache: null };
function roomRand(x, y, k) {
  let h = (Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(k, 2147483647)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) & 0xffffff) / 16777216;
}
function drawRooms(g, b, T, dpr) {
  const r = b.rooms;
  if (!r || !((r.floor || []).length || (r.walls || []).length || (r.slants || []).length)) return;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [ax, ay, bx, by] of r.runs.concat(r.slants || [])) { x0 = Math.min(x0, ax, bx); y0 = Math.min(y0, ay, by); x1 = Math.max(x1, ax, bx); y1 = Math.max(y1, ay, by); }
  x0 = Math.floor(x0 - 1.1); y0 = Math.floor(y0 - 1.1); x1 = Math.ceil(x1 + 1.1); y1 = Math.ceil(y1 + 1.1);
  const k = Math.min(T * (dpr || 1), 4096 / Math.max(1, x1 - x0, y1 - y0));
  let c = ROOM.cache;
  if (!c || c.src !== r || Math.abs(c.k - k) > 1e-3) {
    const cv = document.createElement('canvas');
    cv.width = Math.max(1, Math.floor((x1 - x0) * k)); cv.height = Math.max(1, Math.floor((y1 - y0) * k));
    const q = cv.getContext('2d');
    q.scale(k, k); q.translate(-x0, -y0);
    roomArt(q, r);
    c = ROOM.cache = { src: r, k, cv, x0, y0, x1, y1 };
  }
  g.save(); g.imageSmoothingEnabled = true;
  g.beginPath();                                       // the rooms' paper stays on its floor
  for (const [, fx] of floorsOf(b.map)) g.rect((fx - .1) * T, -T * .1, ((b.map.fw || b.map.w) + .2) * T, (b.map.h + .2) * T);
  g.clip();
  g.drawImage(c.cv, c.x0 * T, c.y0 * T, (c.x1 - c.x0) * T, (c.y1 - c.y0) * T);
  g.restore();
}
function roomArt(q, r) {
  const rnd = roomRand, floor = new Set(r.floor.map(([x, y]) => x + ',' + y)), walls = new Map();
  for (const [x, y, v, s] of r.walls) walls.set(x + ',' + y + ',' + (v ? 1 : 0), s);
  const wallPath = new Path2D(), floorPath = new Path2D(), halo = new Path2D(), shadow = new Path2D(), soft = new Path2D();
  const grid = new Path2D(), marks = new Path2D(), stones = new Path2D(), dots = [[], [], []];
  for (const [ax, ay, bx, by] of r.runs.concat(r.slants || [])) { wallPath.moveTo(ax, ay); wallPath.lineTo(bx, by); }
  for (const [x, y] of r.floor) floorPath.rect(x, y, 1, 1);
  for (const [x, y, v, side] of r.walls) {
    for (const s of side === 0 ? [1, -1] : side === 2 ? [] : [side]) {   // the shadow on the floor side(s); deeper under the top and left walls
      const w0 = s === 1 ? .24 : .12;
      for (const [w, p] of [[w0, shadow], [w0 * 1.9, soft]]) {
        if (v) p.rect(s === 1 ? x : x - w, y, w, 1); else p.rect(x, s === 1 ? y : y - w, 1, w);
      }
    }
    if (side === 0) continue;
    const kx = x * 2 + (v ? 1 : 0);
    for (const out of side === 2 ? [1, -1] : [side]) {  // a drawn wall standing on its own: rock on both sides
      const nx = v ? -out : 0, ny = v ? 0 : -out, q = out === side ? 0 : 500, lone = side === 2;
      const at = (along, off) => v ? [x + off * nx, y + along] : [x + along, y + off * ny];
      for (let i = 0; i < 2; i++) {                    // the paper's ragged edge
        const [px, py] = at(rnd(kx, y, q + 50 + i), .25 + .2 * rnd(kx, y, q + 70 + i)), rr = .3 + .25 * rnd(kx, y, q + 60 + i);
        halo.moveTo(px + rr, py); halo.arc(px, py, rr, 0, Math.PI * 2);
      }
      for (let i = 0; i < (lone ? 12 : 22); i++) {     // stipple: thick by the wall, thinning out
        const a = rnd(kx, y, q + i * 3 + 1), bb = rnd(kx, y, q + i * 3 + 2);
        dots[Math.floor(rnd(kx, y, q + i * 3 + 3) * 3)].push(at(-.25 + 1.5 * a, .1 + (lone ? .4 : .7) * bb * bb));
      }
      if (rnd(kx, y, q + 99) < .09) {                  // a loose stone
        const [cx, cy] = at(.2 + .6 * rnd(kx, y, q + 101), .45 + .3 * rnd(kx, y, q + 102)), rr = .07 + .06 * rnd(kx, y, q + 103);
        for (let j = 0; j < 5; j++) {
          const px = cx + rr * (.7 + .5 * rnd(kx, y, q + 110 + j)) * Math.cos(j * 1.2566 + .4), py = cy + rr * (.7 + .5 * rnd(kx, y, q + 120 + j)) * Math.sin(j * 1.2566 + .4);
          if (j) stones.lineTo(px, py); else stones.moveTo(px, py);
        }
        stones.closePath();
      }
    }
  }
  for (const [x, y] of r.floor) {                      // the grid between floor tiles, a little wobbly
    for (const [vert, nx, ny] of [[1, x + 1, y], [0, x, y + 1]]) {
      if (!floor.has(nx + ',' + ny) || walls.has(nx + ',' + ny + ',' + vert)) continue;
      const j = [0, 1, 2].map(i => (rnd(x, y, 200 + i + (vert ? 0 : 10)) - .5) * .05);
      if (vert) { grid.moveTo(x + 1 + j[0], y); grid.lineTo(x + 1 + j[1], y + .5); grid.lineTo(x + 1 + j[2], y + 1); }
      else { grid.moveTo(x, y + 1 + j[0]); grid.lineTo(x + .5, y + 1 + j[1]); grid.lineTo(x + 1, y + 1 + j[2]); }
    }
    for (let i = 0; i < Math.floor(rnd(x, y, 300) * 4); i++) {   // scratches
      const cx = x + .1 + .8 * rnd(x, y, 310 + i), cy = y + .1 + .8 * rnd(x, y, 320 + i), a = rnd(x, y, 330 + i) * Math.PI, n = .03 + .06 * rnd(x, y, 340 + i);
      marks.moveTo(cx - n * Math.cos(a), cy - n * Math.sin(a)); marks.lineTo(cx + n * Math.cos(a), cy + n * Math.sin(a));
    }
    if (rnd(x, y, 400) < .3) {                         // a crack
      let cx = x + .2 + .6 * rnd(x, y, 401), cy = y + .2 + .6 * rnd(x, y, 402), a = rnd(x, y, 403) * Math.PI * 2;
      marks.moveTo(cx, cy);
      for (let i = 0; i < 3; i++) {
        a += (rnd(x, y, 410 + i) - .5) * 1.6;
        const step = .07 + .08 * rnd(x, y, 420 + i);
        cx += step * Math.cos(a); cy += step * Math.sin(a); marks.lineTo(cx, cy);
      }
    }
  }
  q.lineCap = 'round'; q.lineJoin = 'round';
  q.strokeStyle = 'rgba(242,237,225,.16)'; q.lineWidth = 1.6; q.stroke(wallPath);    // the paper, fading out at its edge
  q.strokeStyle = ROOM.paper; q.lineWidth = .9; q.stroke(wallPath);
  q.fillStyle = ROOM.paper; q.fill(halo);
  dots.forEach((list, i) => {
    q.fillStyle = `rgba(29,25,21,${[.9, .82, .75][i]})`;
    const rr = [.0125, .02, .03][i];
    for (const [px, py] of list) { q.beginPath(); q.arc(px, py, rr, 0, Math.PI * 2); q.fill(); }
  });
  q.fillStyle = ROOM.paper; q.fill(stones); q.strokeStyle = ROOM.ink; q.lineWidth = .03; q.stroke(stones);
  q.fillStyle = ROOM.floor; q.fill(floorPath);
  q.save(); q.clip(floorPath);
  q.fillStyle = 'rgba(0,0,0,.08)'; q.fill(soft);
  q.fillStyle = 'rgba(0,0,0,.16)'; q.fill(shadow);
  q.restore();
  q.strokeStyle = 'rgba(29,25,21,.67)'; q.lineWidth = .028; q.stroke(grid);
  q.strokeStyle = 'rgba(29,25,21,.5)'; q.lineWidth = .02; q.stroke(marks);
  q.strokeStyle = ROOM.ink; q.lineWidth = .16; q.lineCap = 'square'; q.lineJoin = 'miter'; q.stroke(wallPath);
  for (const d of r.doors) roomDoor(q, d);
}
/** What stands in a room's wall, as the DM's map draws it (roomart.py: _paint_door): a door (two for a double door, a
 * bolt on a locked one, an S beside the wall for a secret one; open: a gap and its leaf), a window, a portcullis, an
 * archway. In tile units about the middle of its edge, turned so the wall runs along x. */
function roomDoor(q, d) {
  const kind = d.kind || 'door', ink = ROOM.ink;
  q.save();
  q.translate(d.v ? d.x : d.x + .5, d.v ? d.y + .5 : d.y);
  if (d.v) q.rotate(Math.PI / 2);
  q.lineCap = 'square'; q.lineJoin = 'miter';
  const gap = half => { q.fillStyle = ROOM.floor; q.fillRect(-half, -.11, 2 * half, .22); };
  const box = (x0, w, h = .3) => { q.fillStyle = ROOM.floor; q.fillRect(x0, -h / 2, w, h); q.strokeStyle = ink; q.lineWidth = .05; q.strokeRect(x0, -h / 2, w, h); };
  const line = (w, ...pts) => { q.strokeStyle = ink; q.lineWidth = w; q.beginPath(); q.moveTo(pts[0], pts[1]); q.lineTo(pts[2], pts[3]); q.stroke(); };
  q.fillStyle = ink;
  if (['door', 'double', 'locked', 'secret'].includes(kind) && d.open) {
    gap(.36);
    if (kind === 'double') { line(.06, -.36, 0, -.36, .32); line(.06, .36, 0, .36, .32); } else line(.06, -.36, 0, -.36, .6);
  } else if (kind === 'double') { box(-.32, .31, .28); box(.01, .31, .28); }
  else if (kind === 'door' || kind === 'locked') { box(-.3, .6); if (kind === 'locked') { q.fillStyle = ink; q.fillRect(-.06, -.06, .12, .12); } }
  else if (kind === 'window' && d.open) { gap(.36); line(.025, -.36, -.07, -.36, .07); line(.025, .36, -.07, .36, .07); line(.04, -.36, 0, -.2, .3); line(.04, .36, 0, .2, .3); }   // casements swung in
  else if (kind === 'window') { gap(.36); q.fillStyle = ROOM.floor; q.fillRect(-.36, -.07, .72, .14); q.strokeStyle = ink; q.lineWidth = .025; q.strokeRect(-.36, -.07, .72, .14); line(.025, -.36, 0, .36, 0); }
  else if (kind === 'portcullis' && d.open) {          // raised: two posts, the bars faint overhead
    gap(.4); q.fillStyle = ink; q.fillRect(-.47, -.09, .09, .18); q.fillRect(.38, -.09, .09, .18);
    q.fillStyle = 'rgba(29,25,21,.27)'; for (let i = 0; i < 5; i++) q.fillRect(-.36 + i * .18 - .03, -.03, .06, .06);
  }
  else if (kind === 'portcullis') { gap(.4); line(.025, -.4, 0, .4, 0); q.fillStyle = ink; for (let i = 0; i < 5; i++) q.fillRect(-.36 + i * .18 - .035, -.035, .07, .07); }
  else if (kind === 'archway') { gap(.4); q.fillStyle = ink; q.fillRect(-.5, -.13, .13, .26); q.fillRect(.37, -.13, .13, .26); }
  if (kind === 'secret') {                             // the S, upright
    q.translate(0, .33); if (d.v) q.rotate(-Math.PI / 2);
    const s = .1, p = new Path2D();
    p.moveTo(s, -s * 1.3); p.bezierCurveTo(s * .2, -s * 2, -s * 1.2, -s * 1.5, -s * .9, -s * .5);
    p.bezierCurveTo(-s * .6, s * .2, s * .9, -s * .1, s, s * .7); p.bezierCurveTo(s * 1.1, s * 1.7, -s * .5, s * 2, -s, s * 1.3);
    q.strokeStyle = d.open ? 'rgba(29,25,21,.43)' : ink; q.lineWidth = .04; q.lineCap = 'round'; q.stroke(p);
  }
  q.restore();
}
/** The floors of the map ([floor, its first column]), side by side 2 tiles apart: upstairs on the right, downstairs
 * on the left (battle/floors.py). One floor: [[0, 0]]. */
function floorsOf(m) {
  const fw = m.fw || m.w, lo = m.lo || 0, hi = m.hi || 0;
  return Array.from({ length: hi - lo + 1 }, (_, i) => [lo + i, i * (fw + 2)]);
}
function floorName(f) { return f === 0 ? S('Main floor') : f > 0 ? S('Floor +{0}', f) : S('Floor −{0}', -f); }
/** The DM's pointer (the editor's ping tool): a ring where it is, rings rippling out where the DM clicked. Nothing of
 * it is kept: it comes down the live stream ("ping x y press" / "ping off") and fades on its own. */
const PING = { at: null, seen: 0, rings: [], raf: 0 }, PING_LIFE = 1400, PING_STALE = 4000;
function ping(msg) {
  const [, x, y, press] = msg.split(' '), now = performance.now();
  if (x === 'off') PING.at = null;
  else {
    PING.at = [+x, +y]; PING.seen = now;
    if (press === '1') { PING.rings.push([+x, +y, now]); buzz(); }
  }
  if (!PING.raf) PING.raf = requestAnimationFrame(pingFrame);
}
function buzz() { try { if (navigator.vibrate && touch()) navigator.vibrate(30); } catch (e) { /* not on this device */ } }
function pingFrame() {
  PING.raf = 0;
  const now = performance.now();
  PING.rings = PING.rings.filter(r => now - r[2] < PING_LIFE);
  if (PING.at && now - PING.seen > PING_STALE) PING.at = null;
  if (ST && ST.battle && $('board') && !FX.raf) {      // (an FX animation running draws the ring too)
    FX.frame = true;                                   // the board only, like an FX frame
    try { renderMap(); } finally { FX.frame = false; }
  }
  if (PING.rings.length || PING.at) PING.raf = requestAnimationFrame(pingFrame);
}
function drawPing(g, T) {
  const now = performance.now();
  for (const [x, y, t0] of PING.rings) {
    for (let k = 0; k < 3; k++) {
      const u = (now - t0) / PING_LIFE * 1.5 - k * .25;
      if (u < 0 || u > 1) continue;
      g.strokeStyle = `rgba(250,204,21,${.9 * (1 - u)})`; g.lineWidth = 2 + 3 * (1 - u);
      g.beginPath(); g.arc(x * T, y * T, T * (.3 + 2.2 * u), 0, Math.PI * 2); g.stroke();
    }
  }
  if (!PING.at) return;
  const [x, y] = PING.at, r = Math.max(10, T * .45), pulse = .5 + .5 * Math.sin(now / 180);
  g.fillStyle = `rgba(250,204,21,${.14 + .12 * pulse})`; g.strokeStyle = '#facc15'; g.lineWidth = 2.5;
  g.beginPath(); g.arc(x * T, y * T, r, 0, Math.PI * 2); g.fill(); g.stroke();
  g.fillStyle = '#facc15'; g.beginPath(); g.arc(x * T, y * T, 3, 0, Math.PI * 2); g.fill();
}
/** The DM's drawings: walls and rooms along the grid, free lines, and map symbols (doors, stairs...). */
/** What a drawn line is on the battlefield (rooms.py: cover_of): 'wall', 'total', 'half' or 'none'. */
function coverOf(d) {
  if (['total', 'half', 'none'].includes(d.cover)) return d.cover;
  if (d.pts.length > 1 && d.wall !== false && d.pts.every(([x, y]) => Number.isInteger(x) && Number.isInteger(y))) return 'wall';
  return d.wall === true ? 'total' : 'none';
}
/** A half-cover line's ticks across it, every `step` tiles (drawtools.py: cover_ticks). */
function coverTicks(pts, closed, step = .3, half = .11) {
  const seq = closed && pts.length > 2 ? pts.concat([pts[0]]) : pts, out = [];
  for (let i = 1; i < seq.length; i++) {
    const [x1, y1] = seq[i - 1], [x2, y2] = seq[i], n = Math.hypot(x2 - x1, y2 - y1);
    if (n < 1e-6) continue;
    const ux = (x2 - x1) / n, uy = (y2 - y1) / n, k = Math.max(1, Math.floor(n / step));
    for (let j = 0; j < k; j++) {
      const t = (j + .5) * n / k, cx = x1 + ux * t, cy = y1 + uy * t;
      out.push([cx - uy * half, cy + ux * half, cx + uy * half, cy - ux * half]);
    }
  }
  return out;
}
/** A drawn line as what it is: a plain stroke (no cover), a railing of ticks (half cover), a thick inked band (full). */
function drawLine(g, d, T) {
  const cover = coverOf(d), trace = () => {
    g.beginPath(); g.moveTo(d.pts[0][0] * T, d.pts[0][1] * T);
    for (const [x, y] of d.pts.slice(1)) g.lineTo(x * T, y * T);
    if (d.closed) g.closePath();
  };
  g.lineCap = g.lineJoin = 'round';
  if (d.closed && cover === 'none') { trace(); g.fillStyle = d.color + '1c'; g.fill(); }
  let w = Math.max(1.5, (d.width || 3) * T / 14);
  if (cover === 'total') { trace(); g.strokeStyle = 'rgba(20,18,15,.9)'; g.lineWidth = Math.max(4, T * .2); g.stroke(); w = Math.max(2, T * .11); }
  else if (cover === 'half') {
    g.strokeStyle = d.color; g.lineWidth = Math.max(1.2, T * .035); g.lineCap = 'butt'; g.beginPath();
    for (const [x1, y1, x2, y2] of coverTicks(d.pts, d.closed)) { g.moveTo(x1 * T, y1 * T); g.lineTo(x2 * T, y2 * T); }
    g.stroke(); g.lineCap = 'round'; w = Math.max(1.5, T * .05);
  }
  trace(); g.strokeStyle = d.color; g.lineWidth = w; g.stroke();
}
/** Painted difficult terrain (mud, water, undergrowth...): each kind one patch, tile by tile, its standing-out corners
 * rounded off and its inside corners filled in round (groundart.py: terrain_shape draws the same). */
const TERRAIN = { round: .35, cache: new WeakMap() };
function terrainPiece(path, pts) {                     // wound the way rect() winds: the pieces meet without a seam
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
  if (a < 0) pts = pts.slice().reverse();
  pts.forEach(([x, y], i) => i ? path.lineTo(x, y) : path.moveTo(x, y)); path.closePath();
}
function terrainArc(cx, cy, sx, sy, r) {
  const out = [];
  for (let i = 0; i <= 5; i++) { const t = i * Math.PI / 10; out.push([cx + sx * r * Math.cos(t), cy + sy * r * Math.sin(t)]); }
  return out;
}
function terrainShape(cells) {
  const has = new Set(cells.map(([x, y]) => x + ',' + y)), on = (x, y) => has.has(x + ',' + y), r = TERRAIN.round;
  const fill = new Path2D(), edge = new Path2D(), near = new Map(), Q = [[-1, -1], [1, -1], [-1, 1], [1, 1]];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of cells) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + 1); y1 = Math.max(y1, y + 1);
    const whole = Q.every(([sx, sy]) => on(x + sx, y) || on(x, y + sy));
    for (const [sx, sy] of Q) {
      for (const [nx, ny] of [[x + sx, y], [x, y + sy], [x + sx, y + sy]]) if (!on(nx, ny)) near.set(nx + ',' + ny, [nx, ny]);
      if (whole) continue;
      const cx = x + (sx > 0 ? 1 : 0), cy = y + (sy > 0 ? 1 : 0), mx = x + .5, my = y + .5;
      if (on(x + sx, y) || on(x, y + sy)) { fill.rect(Math.min(mx, cx), Math.min(my, cy), .5, .5); continue; }
      const arc = terrainArc(cx - sx * r, cy - sy * r, sx, sy, r);         // a corner standing out: rounded
      terrainPiece(fill, [[mx, my], [cx, my], ...arc, [mx, cy]]);
      arc.forEach(([px, py], i) => i ? edge.lineTo(px, py) : edge.moveTo(px, py));
    }
    if (whole) fill.rect(x, y, 1, 1);
    for (const [dx, dy, ax, ay, bx, by, ends] of [[0, -1, x, y, x + 1, y, [[-1, -1], [1, -1]]], [0, 1, x, y + 1, x + 1, y + 1, [[-1, 1], [1, 1]]],
                                                  [-1, 0, x, y, x, y + 1, [[-1, -1], [-1, 1]]], [1, 0, x + 1, y, x + 1, y + 1, [[1, -1], [1, 1]]]]) {
      if (on(x + dx, y + dy)) continue;                // an open side: its outline, cut short where a corner is round
      const cut = ends.map(([sx, sy]) => { const [nx, ny] = dy ? [x + sx, y] : [x, y + sy]; return on(nx, ny) && !on(x + sx, y + sy) ? 0 : r; });
      if (dy) { edge.moveTo(ax + cut[0], ay); edge.lineTo(bx - cut[1], by); } else { edge.moveTo(ax, ay + cut[0]); edge.lineTo(bx, by - cut[1]); }
    }
  }
  for (const [x, y] of near.values()) {                // inside corners: filled in round
    for (const [sx, sy] of Q) {
      if (!(on(x + sx, y) && on(x, y + sy) && on(x + sx, y + sy))) continue;
      const cx = x + (sx > 0 ? 1 : 0), cy = y + (sy > 0 ? 1 : 0), arc = terrainArc(cx - sx * r, cy - sy * r, sx, sy, r);
      terrainPiece(fill, [[cx, cy], ...arc]);
      arc.forEach(([px, py], i) => i ? edge.lineTo(px, py) : edge.moveTo(px, py));
    }
  }
  return { fill, edge, box: [x0, y0, x1, y1] };
}
function shade(hex, k, a) {                            // a colour darker (k < 1) or lighter (k > 1), with alpha a
  const n = parseInt(hex.slice(1), 16), c = v => Math.max(0, Math.min(255, Math.round(k > 1 ? v + (255 - v) * (k - 1) : v * k)));
  return `rgba(${c(n >> 16)},${c((n >> 8) & 255)},${c(n & 255)},${a})`;
}
function terrainMarks(g, kind, col, cells, view) {     // each tile's texture, fixed for the tile (groundart.py: _marks)
  const rnd = roomRand, dark = shade(col, .74, .67), light = shade(col, 1.35, .59);
  const seen = cells.filter(([x, y]) => x >= view[0] - 1 && x <= view[2] + 1 && y >= view[1] - 1 && y <= view[3] + 1);
  g.beginPath();
  if (kind === 'water') {
    for (const [x, y] of seen) for (let i = 0; i < 2; i++) {
      const cx = x + .22 + .5 * rnd(x, y, 510 + i), cy = y + .25 + .5 * rnd(x, y, 520 + i), w = .14 + .08 * rnd(x, y, 530 + i);
      g.moveTo(cx - w, cy); g.quadraticCurveTo(cx - w / 2, cy - .06, cx, cy); g.quadraticCurveTo(cx + w / 2, cy + .06, cx + w, cy);
    }
    g.strokeStyle = light; g.lineWidth = .035; g.lineCap = 'round'; g.stroke(); return;
  }
  if (kind === 'brush') {
    for (const [x, y] of seen) for (let i = 0; i < 3; i++) {
      const cx = x + .18 + .64 * rnd(x, y, 610 + i), cy = y + .3 + .55 * rnd(x, y, 620 + i);
      for (const a of [-.5, 0, .5]) { g.moveTo(cx, cy); g.lineTo(cx + .09 * Math.sin(a), cy - .11 * Math.cos(a)); }
    }
    g.strokeStyle = dark; g.lineWidth = .03; g.lineCap = 'round'; g.stroke(); return;
  }
  if (kind === 'ice') {
    for (const [x, y] of seen) { const cx = x + .2 + .6 * rnd(x, y, 710), cy = y + .2 + .6 * rnd(x, y, 720); g.moveTo(cx - .12, cy + .08); g.lineTo(cx + .12, cy - .08); }
    g.strokeStyle = 'rgba(255,255,255,.67)'; g.lineWidth = .03; g.lineCap = 'round'; g.stroke(); return;
  }
  if (kind === 'sand') {
    for (const [x, y] of seen) for (let i = 0; i < 5; i++) {
      const cx = x + .12 + .76 * rnd(x, y, 810 + i), cy = y + .12 + .76 * rnd(x, y, 820 + i); g.moveTo(cx + .022, cy); g.arc(cx, cy, .022, 0, Math.PI * 2);
    }
    g.fillStyle = dark; g.fill(); return;
  }
  if (kind === 'rubble') {
    for (const [x, y] of seen) for (let i = 0; i < 3; i++) {
      const cx = x + .2 + .6 * rnd(x, y, 910 + i), cy = y + .2 + .6 * rnd(x, y, 920 + i), r = .06 + .05 * rnd(x, y, 930 + i);
      g.beginPath();
      for (let j = 0; j < 5; j++) {
        const px = cx + r * (.7 + .4 * rnd(x, y, 940 + i * 5 + j)) * Math.cos(j * 1.2566), py = cy + r * (.7 + .4 * rnd(x, y, 960 + i * 5 + j)) * Math.sin(j * 1.2566);
        j ? g.lineTo(px, py) : g.moveTo(px, py);
      }
      g.closePath(); g.fillStyle = i % 2 ? light : dark; g.fill(); g.strokeStyle = 'rgba(40,36,30,.78)'; g.lineWidth = .02; g.stroke();
    }
    return;
  }
  for (const [x, y] of seen) for (let i = 0; i < 2; i++) {     // mud: darker clods, and a wet glint below
    const cx = x + .2 + .6 * rnd(x, y, 410 + i), cy = y + .2 + .6 * rnd(x, y, 420 + i);
    g.moveTo(cx + .07 + .06 * rnd(x, y, 430 + i), cy); g.ellipse(cx, cy, .07 + .06 * rnd(x, y, 430 + i), .05 + .04 * rnd(x, y, 440 + i), 0, 0, Math.PI * 2);
  }
  g.fillStyle = dark; g.fill(); g.beginPath();
  for (const [x, y] of seen) { const cx = x + .25 + .5 * rnd(x, y, 450), cy = y + .25 + .5 * rnd(x, y, 460); g.moveTo(cx + .03, cy); g.ellipse(cx, cy, .03, .02, 0, 0, Math.PI * 2); }
  g.fillStyle = light; g.fill();
}
function drawTerrain(g, b, T, view) {
  const ds = (b.drawings || []).filter(d => d.type === 'terrain' && d.tiles && d.tiles.length);
  if (!ds.length) return;
  let shapes = TERRAIN.cache.get(b.drawings);         // (worked out once a board: b.drawings is new with every change)
  if (!shapes) {
    const kinds = {};
    for (const d of ds) (kinds[d.kind || 'mud'] ||= []).push(...d.tiles);
    shapes = Object.entries(kinds).map(([kind, cells]) => ({ kind, cells, ...terrainShape(cells) }));
    TERRAIN.cache.set(b.drawings, shapes);
  }
  const colors = b.terrain_colors || {};
  g.save(); g.scale(T, T);
  for (const t of shapes) {
    if (!inSight(t.box, view, 1)) continue;
    const col = colors[t.kind] || '#6e4f33';
    g.fillStyle = shade(col, 1, .82); g.fill(t.fill);
    terrainMarks(g, t.kind, col, t.cells, view);
    g.strokeStyle = shade(col, .62, .85); g.lineWidth = .05; g.lineCap = g.lineJoin = 'round'; g.stroke(t.edge);
  }
  g.restore();
}
/** Roads: the surface between two edges drawn side by side (paired by the table: battle/shapes.py road_pairs), then
 * every edge as a kerb with stones along it (groundart.py: paint_roads). */
function drawRoads(g, b, T, view) {
  const roads = (b.drawings || []).filter(d => d.type === 'road' && d.pts && d.pts.length > 1);
  if (!roads.length) return;
  const col = Object.fromEntries(roads.map(d => [d.id, d.color || '#c9b27a'])), rnd = roomRand;
  g.save(); g.scale(T, T);
  for (const pr of b.roads || []) {
    const box = drawingBox({ pts: pr.poly });
    if (!inSight(box, view)) continue;
    g.beginPath();
    for (const ring of [pr.poly, pr.hole]) if (ring) { ring.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.closePath(); }
    g.fillStyle = shade(col[pr.ids[0]] || '#c9b27a', 1, .59); g.fill('evenodd');
  }
  for (const d of roads) {
    if (!inSight(drawingBox(d), view)) continue;
    const pts = d.closed ? d.pts.concat([d.pts[0]]) : d.pts, c = col[d.id];
    g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
    g.strokeStyle = shade(c, .45, .86); g.lineWidth = .07; g.lineCap = g.lineJoin = 'round'; g.stroke();
    g.beginPath();
    for (let i = 0; i < pts.length - 1; i++) {        // stones along the kerb, either side
      const [x1, y1] = pts[i], [x2, y2] = pts[i + 1], n = Math.hypot(x2 - x1, y2 - y1);
      if (n < 1e-6) continue;
      const ux = (x2 - x1) / n, uy = (y2 - y1) / n;
      for (let k = 0; k < Math.floor(n / .55); k++) {
        const t = (k + .5) * .55, s = rnd(d.id * 31 + i, k, 1) < .5 ? 1 : -1, off = .1 + .08 * rnd(d.id * 31 + i, k, 2);
        const cx = x1 + ux * t - uy * off * s, cy = y1 + uy * t + ux * off * s, r = .035 + .02 * rnd(d.id * 31 + i, k, 3);
        g.moveTo(cx + r, cy); g.ellipse(cx, cy, r, .03, 0, 0, Math.PI * 2);
      }
    }
    g.fillStyle = shade(c, .77, 1); g.fill(); g.strokeStyle = shade(c, .45, .86); g.lineWidth = .02; g.stroke();
  }
  g.restore();
}
/** A cliff's edges as [a, b, high]: the high ground where orient(a, b, p) * high > 0 - inside a closed one, else on its
 * 'side' (battle/sight.py: cliff_segments). */
function cliffSegments(d) {
  const seq = d.pts.map(([x, y]) => [x, y]);
  if (d.closed && seq.length > 2) seq.push(seq[0]);
  let high = (d.side || 1) >= 0 ? 1 : -1;
  if (d.closed && seq.length > 3) { let a = 0; for (let i = 1; i < seq.length; i++) a += seq[i - 1][0] * seq[i][1] - seq[i][0] * seq[i - 1][1]; high = a > 0 ? 1 : -1; }
  const out = [];
  for (let i = 1; i < seq.length; i++) if (seq[i - 1][0] !== seq[i][0] || seq[i - 1][1] !== seq[i][1]) out.push([seq[i - 1], seq[i], high]);
  return out;
}
const HACHURE = { slope: [.34, .16], steep: [.2, .26], sheer: [.13, .36] };
function drawHighGround(g, b, T, view) {               // inside a closed cliff the ground is a shade lighter
  const tops = (b.drawings || []).filter(d => d.type === 'cliff' && d.closed && d.pts && d.pts.length > 2 && inSight(drawingBox(d), view));
  if (!tops.length) return;
  g.save(); g.scale(T, T); g.fillStyle = 'rgba(255,238,205,.12)';
  for (const d of tops) { g.beginPath(); d.pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.closePath(); g.fill(); }
  g.restore();
}
function drawCliffs(g, b, T, view) {                   // the edge in ink, hachures down its low side (groundart.py: paint_cliffs)
  const cliffs = (b.drawings || []).filter(d => d.type === 'cliff' && d.pts && d.pts.length > 1 && inSight(drawingBox(d), view, .8));
  if (!cliffs.length) return;
  g.save(); g.scale(T, T); g.lineCap = 'round'; g.lineJoin = 'round';
  for (const d of cliffs) {
    const [step, size] = HACHURE[d.steep] || HACHURE.steep, ticks = new Path2D(), edge = new Path2D();
    for (const [[ax, ay], [bx, by], high] of cliffSegments(d)) {
      const n = Math.hypot(bx - ax, by - ay), ux = (bx - ax) / n, uy = (by - ay) / n, lx = uy * high, ly = -ux * high, k = Math.max(1, Math.floor(n / step));
      for (let i = 0; i < k; i++) {
        const t = (i + .5) * n / k, len = size * (i % 2 ? .55 : 1), px = ax + ux * t, py = ay + uy * t;
        ticks.moveTo(px, py); ticks.lineTo(px + lx * len, py + ly * len);
      }
    }
    (d.closed ? d.pts.concat([d.pts[0]]) : d.pts).forEach(([x, y], i) => i ? edge.lineTo(x, y) : edge.moveTo(x, y));
    const w = d.steep === 'sheer' ? .11 : .07;
    for (const [col, extra] of [['rgba(232,218,190,.59)', .06], ['#3a2e24', 0]]) {   // a pale halo under the ink: seen on any ground
      g.strokeStyle = col; g.lineWidth = .03 + extra; g.stroke(ticks); g.lineWidth = w + extra; g.stroke(edge);
    }
  }
  g.restore();
}
/** An opened door's leaf swung out of the wall, a window's casements, a gate's two leaves (drawtools.py: paint_leaf),
 * about the tile's middle, already turned; `s` the picture's size in pixels. */
const LEAVES = { window: 'panes', ink_window: 'panes', ink_double_door: 'pair', ink_gate: 'pair', ink_sliding_door: null, ink_revolving_door: null, ink_portcullis: null };
function drawLeaf(g, sym, s) {
  const kind = sym in LEAVES ? LEAVES[sym] : 'door';
  if (!kind) return;
  g.strokeStyle = '#1d1915'; g.lineWidth = Math.max(1.5, s * .05); g.lineCap = 'butt'; g.beginPath();
  if (kind === 'door') { g.moveTo(-.27 * s, 0); g.lineTo(-.27 * s, .52 * s); }
  else if (kind === 'pair') { g.moveTo(-.27 * s, 0); g.lineTo(-.27 * s, .27 * s); g.moveTo(.27 * s, 0); g.lineTo(.27 * s, .27 * s); }
  else { g.moveTo(-.27 * s, 0); g.lineTo(-.1 * s, .24 * s); g.moveTo(.27 * s, 0); g.lineTo(.1 * s, .24 * s); }
  g.stroke();
}
/** The dark of a dim or dark map, with each light's lit area cut out of it - walls throw the shadows (sight.py:
 * light_shapes) - and a warm glow in it (lighting.py draws the DM's). Drawn once a board and zoom; panning only moves it. */
const LIGHT = { dim: .4, dark: .8 };
function drawLight(g, b, T, dpr) {
  const dark = LIGHT[b.map.light];
  if (!dark) return;
  const floors = floorsOf(b.map), FW = b.map.fw || b.map.w, H = b.map.h, x1 = floors[floors.length - 1][1] + FW;
  const k = Math.min(T * (dpr || 1), 4096 / Math.max(1, x1, H));
  let c = LIGHT.cache;
  if (!c || c.src !== b.lights || c.light !== b.map.light || Math.abs(c.k - k) > 1e-3 || c.w !== x1 || c.h !== H) {
    const cv = document.createElement('canvas');
    cv.width = Math.max(1, Math.floor(x1 * k)); cv.height = Math.max(1, Math.floor(H * k));
    const q = cv.getContext('2d');
    q.scale(k, k);
    q.fillStyle = `rgba(4,5,10,${dark})`; q.fillRect(0, 0, x1, H);
    for (const s of b.lights || []) {
      const reach = s.bright + s.dim, inner = s.bright / reach, band = floors.map(([, fx]) => fx).filter(fx => fx <= s.x).pop() ?? 0;
      const poly = () => { q.beginPath(); s.poly.forEach(([x, y], i) => i ? q.lineTo(x, y) : q.moveTo(x, y)); q.closePath(); };
      q.save(); q.beginPath(); q.rect(band, 0, FW, H); q.clip();   // a light stays on its own floor
      q.globalCompositeOperation = 'destination-out';
      let gr = q.createRadialGradient(s.x, s.y, 0, s.x, s.y, reach);
      const stops = b.map.light === 'dim' ? [[0, 1], [inner * .8, 1], [Math.min(1, inner * 1.25), 0], [1, 0]]
        : [[0, 1], [inner * .8, 1], [inner, .6], [.85, .35], [1, 0]];
      for (const [at, cut] of stops) gr.addColorStop(at, `rgba(0,0,0,${cut})`);
      q.fillStyle = gr; poly(); q.fill();
      q.globalCompositeOperation = 'source-over';    // firelight: warm in the middle, fading out
      gr = q.createRadialGradient(s.x, s.y, 0, s.x, s.y, reach);
      gr.addColorStop(0, 'rgba(255,160,70,.27)'); gr.addColorStop(inner, 'rgba(255,160,70,.12)'); gr.addColorStop(1, 'rgba(255,160,70,0)');
      q.fillStyle = gr; poly(); q.fill();
      q.restore();
    }
    c = LIGHT.cache = { src: b.lights, light: b.map.light, k, cv, w: x1, h: H };
  }
  g.save(); g.beginPath();
  for (const [, fx] of floors) g.rect(fx * T, 0, FW * T, H * T);
  g.clip(); g.imageSmoothingEnabled = true;
  g.drawImage(c.cv, 0, 0, x1 * T, H * T);
  g.restore();
}
/** Where a drawing lies, [x0, y0, x1, y1] in tiles (a turned picture: the square round it); null when unknown. */
function drawingBox(d) {
  if (d.pts && d.pts.length) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of d.pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    return [x0, y0, x1, y1];
  }
  if (d.type === 'image') { const r = Math.max(d.w, d.h) * .75, cx = d.x + d.w / 2, cy = d.y + d.h / 2; return [cx - r, cy - r, cx + r, cy + r]; }
  if (d.type === 'symbol') { const n = ((ST.battle.props || {})[d.sym]) || 1; return [d.x, d.y, d.x + n, d.y + n]; }
  return null;
}
function inSight(box, view, pad = .6) {
  return !view || !box || !(box[2] + pad < view[0] || box[0] - pad > view[2] || box[3] + pad < view[1] || box[1] - pad > view[3]);
}
function drawMap(g, b, T, view) {
  const flying = FX.hidden('did');                     // a thrown prop still in the air: not yet where it lands
  for (const d of b.drawings || []) {
    if (d.type === 'road' || d.type === 'cliff' || d.type === 'terrain') continue;   // (drawTerrain, drawRoads, drawCliffs)
    if (!inSight(drawingBox(d), view)) continue;
    if (d.type === 'image') { if ((d.layer || 'map') === 'map') drawImage(g, d, T); continue; }
    if (flying.has(d.id)) continue;
    if (d.type === 'path' && d.pts.length > 1 && coverOf(d) === 'wall') continue;   // a wall: drawn like a room's (drawRooms)
    if (d.type === 'path' && d.pts.length > 1) {
      drawLine(g, d, T);
    } else if (d.type === 'symbol' && (b.props || {})[d.sym]) {
      const key = d.open && (b.opens || DOORS).includes(d.sym) && b.props.door_open ? 'door_open' : d.sym;   // an opened door, window, gate
      const n = b.props[d.sym], im = propImage(key);
      if (!im.complete || !im.naturalWidth) continue;
      g.save(); g.imageSmoothingEnabled = (b.props_smooth || []).includes(key);   // hand-drawn: smoothed; pixel art: square pixels
      g.imageSmoothingQuality = 'high';
      g.translate((d.x + n / 2) * T, (d.y + n / 2) * T); g.rotate((d.rot || 0) * Math.PI / 2);
      g.drawImage(im, -n * T / 2, -n * T / 2, n * T, n * T);
      if (key === 'door_open') drawLeaf(g, d.sym, n * T);
      g.restore();
    } else if (d.type === 'symbol') {
      const x = d.x * T, y = d.y * T;
      g.fillStyle = 'rgba(20,24,32,.68)'; g.fillRect(x + 1, y + 1, T - 2, T - 2);
      g.save(); g.translate(x + T / 2, y + T / 2); g.rotate((d.rot || 0) * Math.PI / 2);
      g.fillStyle = '#f2e6c8'; g.font = `${Math.max(8, Math.floor(T * .62))}px Segoe UI Emoji, Segoe UI, sans-serif`;
      g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText((b.symbols || {})[d.sym] || '?', 0, 1);
      g.restore();
    }
  }
}
/** Items lying on the map: a little sack each (several on one tile spread around it); the name shows on hover. */
function groundSpots(b) {
  const tiles = {}, out = [];
  for (const it of b.ground || []) {
    if (it.at && Math.floor(it.at[0]) === it.x && Math.floor(it.at[1]) === it.y) out.push([it, it.at[0], it.at[1]]);   // dropped on a point
    else (tiles[it.x + ',' + it.y] ||= []).push(it);
  }
  for (const list of Object.values(tiles)) list.forEach((it, i) => {
    const a = 2 * Math.PI * i / list.length - Math.PI / 2, r = list.length > 1 ? .22 : 0;
    out.push([it, it.x + .5 + r * Math.cos(a), it.y + .5 + r * Math.sin(a)]);
  });
  return out;
}
function groundAt(p) { return (groundSpots(ST.battle).reverse().find(([, cx, cy]) => Math.abs(cx - p[0]) <= .3 && Math.abs(cy - p[1]) <= .3) || [])[0]; }
const spriteImgs = {};
function spriteImage(key) {          // an item's sprite (32 px pixel art), fetched once and kept by the browser
  if (!spriteImgs[key]) { spriteImgs[key] = new Image(); spriteImgs[key].onload = () => renderMap(); spriteImgs[key].src = `/itemsprite/${key}.png`; }
  const im = spriteImgs[key];
  return im.complete && im.naturalWidth ? im : null;
}
/** One item sprite centred on (x, y) pixels, s across, turned `rot` radians, over a soft shadow (`shadow`: 0 none). */
function drawItem(g, im, x, y, s, rot = 0, shadow = 1, alpha = 1) {
  g.save(); g.globalAlpha *= alpha;
  if (shadow > 0) { g.fillStyle = `rgba(0,0,0,${(.31 * shadow).toFixed(3)})`; g.beginPath(); g.ellipse(x, y + s * .3, s * .34, s * .12, 0, 0, Math.PI * 2); g.fill(); }
  g.imageSmoothingEnabled = !!rot; g.translate(x, y); if (rot) g.rotate(rot);
  g.drawImage(im, -s / 2, -s / 2, s, s);
  g.restore();
}
/** Items lying on the map: each its own sprite (a sword, a potion, a ring...); a stack shows a second one behind it. */
function drawGround(g, b, T) {
  const carried = UI.item && UI.item.moved ? UI.item.id : null, flying = FX.hidden('gid');
  for (const [it, cx, cy] of groundSpots(b)) {
    if ((it.id === carried && it.qty <= 1) || flying.has(it.id)) continue;
    const im = spriteImage(it.sprite || 'sack'), s = T * .7;
    if (!im) continue;
    if (it.qty > 1) drawItem(g, im, cx * T + s * .16, cy * T - s * .12, s * .9, 0, 0, .8);   // a pile: another peeking out behind
    drawItem(g, im, cx * T, cy * T, s);
  }
  const it = carried != null && (b.ground || []).find(x => x.id === carried), im = it && spriteImage(it.sprite || 'sack');
  if (im) drawItem(g, im, UI.item.at[0] * T, UI.item.at[1] * T, T * .85, 0, 1, .9);
}
/** The hovered (or tapped, or carried) item's name over its sack: the amount in brackets above it. */
function groundLabel(g, b, T) {
  const spot = UI.item && UI.item.moved ? [(b.ground || []).find(it => it.id === UI.item.id), ...UI.item.at] : groundSpots(b).find(([it]) => it.id === UI.groundHover);
  if (!spot || !spot[0]) return;
  const [it, cx, cy] = spot, lines = (it.qty > 1 ? [[`(${it.qty}×)`, '#7fd8ff']] : []).concat([[it.label, '#f2f2f2']]);
  g.font = '600 11px Segoe UI'; g.textAlign = 'center'; g.textBaseline = 'middle';
  const w = Math.max(...lines.map(([t]) => g.measureText(t).width)) + 10, lh = 14, hh = lines.length * lh + 4, x = cx * T, y = (cy - .3) * T - hh - 2;
  g.fillStyle = '#00000096'; g.fillRect(x - w / 2, y, w, hh);
  lines.forEach(([t, col], i) => { g.fillStyle = '#000c'; g.fillText(t, x + 1, y + 2 + lh * (i + .5) + 1); g.fillStyle = col; g.fillText(t, x, y + 2 + lh * (i + .5)); });
}
/** The pictures the DM put on the map, of one layer, in their order. Returns how many were drawn. */
function drawImages(g, b, T, layer) {
  let n = 0;
  for (const d of b.drawings || []) if (d.type === 'image' && (d.layer || 'map') === layer && drawImage(g, d, T)) n++;
  return n;
}
const mapImgs = {};
function drawImage(g, d, T) {
  const key = d.img + '|' + vq();                      // (another picture quality: fetched again at that size)
  if (!mapImgs[key]) { const im = mapImgs[key] = new Image(); im.onload = () => renderMap(); im.src = `/mapimg/${d.img}?q=${vq()}&k=${encodeURIComponent(KEY)}`; }
  const im = mapImgs[key];
  if (!im.complete || !im.naturalWidth) return false;
  g.save();
  g.translate((d.x + d.w / 2) * T, (d.y + d.h / 2) * T); g.rotate((d.rot || 0) * Math.PI / 180);
  g.drawImage(im, -d.w * T / 2, -d.h * T / 2, d.w * T, d.h * T);
  g.restore();
  return true;
}
const DOORS = ['door', 'locked_door', 'secret_door'];      // symbols that open (an open one shows the door_open picture)
const propImgs = {};
function propImage(key) {            // a map prop's (or symbol's) picture, fetched once and kept by the browser
  if (!propImgs[key]) { propImgs[key] = new Image(); propImgs[key].onload = () => renderMap(); propImgs[key].src = `/prop/${key}.webp`; }
  return propImgs[key];
}
function image(id, v) {             // kept by its version: a new portrait (or a new creature under this id) loads again
  const d = typeof bgTokenRoom === 'function' ? bgTokenRoom() : 0;   // (a token on a Battlegrounds lobby's map: battlegrounds.js)
  const q = vq(), key = `${d}:${id}:${v}:${q}`;
  let im = imgs[key];
  if (!im) {
    im = imgs[key] = new Image();
    im.url = `/token/${id}?v=${v}&q=${q}${d ? '&duel=' + d : ''}&k=${encodeURIComponent(KEY)}`;
    im.tries = 0;
    // a picture that didn't come (the tunnel dropped it, the table was busy, it came broken) is marked failed and
    // asked again by tokenRetry(): never given up on while the token is drawn, so no one is left with initials
    im.onload = () => { if (im.naturalWidth) { im.failed = false; renderMap(); } else tokenFailed(im); };
    im.onerror = () => tokenFailed(im);
    im.asked = Date.now(); im.src = im.url;
  }
  im.seen = Date.now();
  return im;
}
const TOKEN_STALL = 20000;                          // a picture still not here after this long: the request hung, asked again
function tokenFailed(im) {
  im.failed = true;
  im.due = Date.now() + Math.min(15000, 600 * 2 ** Math.min(im.tries, 5));   // 0.6 s, 1.2 s ... then every 15 s
}
function tokenAsk(im) { im.tries++; im.failed = false; im.asked = Date.now(); im.src = `${im.url}&r=${im.tries}`; }
/** Asks again for the token pictures that failed (when due; `now`: all of them at once) or hung; one no longer
 *  drawn for a minute (an old version, a creature gone) is dropped, and fetched afresh if it shows up again. */
function tokenRetry(now) {
  const t = Date.now();
  for (const [key, im] of Object.entries(imgs)) {
    if (im.complete && im.naturalWidth && !im.failed) continue;
    if (t - im.seen > 60000) { if (im.failed) delete imgs[key]; continue; }
    if (im.failed ? now || t >= im.due : t - im.asked > TOKEN_STALL) tokenAsk(im);
  }
}
setInterval(() => tokenRetry(false), 2000);
window.addEventListener('online', () => tokenRetry(true));
document.addEventListener('visibilitychange', () => { if (!document.hidden) tokenRetry(true); });

// ---------------------------------------------------------------- moving around the map: drag to pan, wheel / pinch to zoom
const camNow = () => ({ ...(UI.cam || UI.camFit) });
function screenAt(e) { const r = $('board').getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function tileAt(e) { const [x, y] = screenAt(e), c = camNow(); return [Math.floor((x - c.x) / c.z), Math.floor((y - c.y) / c.z)]; }
function propAt([x, y]) {                                   // the topmost prop or map symbol on a tile (its hover card)
  const tips = ST.battle.prop_tips || {}, props = ST.battle.props || {};
  return [...(ST.battle.drawings || [])].reverse().find(d => d.type === 'symbol' && tips[d.sym] && x >= d.x && x < d.x + (props[d.sym] || 1) && y >= d.y && y < d.y + (props[d.sym] || 1));
}
function propTip(e, d) {                                    // its name, cover and what it does; a door says how it stands
  const key = 'p' + d.id + (d.open ? 'o' : '');
  if (UI.tipFor === key) return;
  UI.tipFor = key;
  const opens = (ST.battle.opens || DOORS).includes(d.sym);
  tip(e, ST.battle.prop_tips[d.sym] + (opens ? '\n' + (d.open ? S('(open now)') : S('(shut now)')) : ''));
}
/** The creature at a point of the map (tile units: where the pointer is, or a tile's corner): a Tiny token drawn under
 *  the point first, then a Tiny one anywhere on that tile (half a tile across: hard to hit on a phone), then whoever
 *  stands there - a Tiny token over the big one it shares a tile with. */
function tokenAt([x, y]) {
  const tx = Math.floor(x), ty = Math.floor(y);
  const drawn = c => { const b = c.box || (c.pos && [c.pos[0], c.pos[1], c.span]); return b && x >= b[0] && x < b[0] + b[2] && y >= b[1] && y < b[1] + b[2]; };
  const on = c => c.pos && tx >= c.pos[0] && tx < c.pos[0] + c.span && ty >= c.pos[1] && ty < c.pos[1] + c.span;
  const all = [...ST.battle.combatants].reverse();
  return all.find(c => c.tiny && drawn(c)) || all.find(c => c.tiny && on(c)) || all.find(on);
}
function zoomAt(f, sx, sy) {
  const c = camNow(), z = Math.max(6, Math.min(140, c.z * f)), k = z / c.z;
  UI.cam = { x: sx - (sx - c.x) * k, y: sy - (sy - c.y) * k, z };
  renderMap();
}
function centerOn(t) {
  const c = camNow(), wrap = $('mapwrap'), s = t.span * c.z;
  UI.cam = { x: wrap.clientWidth / 2 - t.pos[0] * c.z - s / 2, y: Math.max(160, wrap.clientHeight) / 2 - t.pos[1] * c.z - s / 2, z: c.z };
}
const pointers = new Map();          // active pointers (two = pinch)
let press = null;                    // {sx, sy, cam, token, mode: 'pan' | 'item' | 'pinch', moved}
const board = $('board');
function pinchDistance() { const [a, b] = [...pointers.values()]; return Math.max(1, Math.hypot(a[0] - b[0], a[1] - b[1])); }
function pinchMid() { const [a, b] = [...pointers.values()]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; }
/* The mouse: the left button picks (a creature, an action's target, a confirmation) and drags the map around; the right
 * button walks my token - on my turn in a fight, or out of one once I've picked my token. The middle button drags too.
 * Touch: a drag moves the map; with my token picked, a tap on a tile shows the way and a second tap (or Move here) goes. */
let rpress = null;                   // the right button: {sx, sy} where it went down
board.addEventListener('pointerdown', e => {
  if (!ST) return;
  if (e.button === 2) { rpress = { sx: screenAt(e)[0], sy: screenAt(e)[1] }; return; }
  if (e.button > 1) return;
  try { board.setPointerCapture(e.pointerId); } catch { /* a pointer already gone */ }
  pointers.set(e.pointerId, screenAt(e));
  if (pointers.size === 2) { press = { mode: 'pinch', d: pinchDistance(), mid: pinchMid(), cam: camNow() }; return; }
  const c = tokenAt(pointAt(e)), [sx, sy] = screenAt(e);
  const fingers = e.pointerType !== 'mouse';                 // a finger wobbles: more slack before a tap becomes a drag
  const me = mover(), it = !c && !UI.aim && e.button === 0 ? groundAt(pointAt(e)) : null;
  const reach = !!(it && me && me.pos && Geo.toPoint(me, [it.x, it.y]) <= 5);
  press = { sx, sy, cam: camNow(), token: c, mode: reach ? 'item' : 'pan', moved: false, touch: fingers, slop: fingers ? 10 : 5, middle: e.button === 1 };
  if (e.button === 1) e.preventDefault();                    // (no auto-scroll)
  if (reach) UI.item = { id: it.id, at: pointAt(e), moved: false };
});
board.addEventListener('pointermove', e => {
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, screenAt(e));
  if (press && press.mode === 'pinch') {
    if (pointers.size < 2) return;
    const d = pinchDistance(), [mx, my] = pinchMid(), c = press.cam, z = Math.max(6, Math.min(140, c.z * d / press.d)), k = z / c.z;
    UI.cam = { x: mx - (press.mid[0] - c.x) * k, y: my - (press.mid[1] - c.y) * k, z };
    renderMap(); return;
  }
  if (!press) {
    const c = ST && tokenAt(pointAt(e)), it = ST && !c && !UI.aim ? groundAt(pointAt(e)) : null;
    board.style.cursor = UI.aim || UI.place ? 'crosshair' : c || it ? 'pointer' : 'grab';
    if ((it ? it.id : null) !== (UI.groundHover ?? null)) { UI.groundHover = it ? it.id : null; requestAnimationFrame(renderMap); }
    if (c && !UI.aim) { if (UI.tipFor !== c.id + '|' + ST.v) { UI.tipFor = c.id + '|' + ST.v; tip({ clientX: e.clientX, clientY: e.clientY, currentTarget: { getBoundingClientRect: () => ({ left: e.clientX + 12, top: e.clientY - 8, bottom: e.clientY + 18 }) } }, () => tokenCard(c)); } }
    else if (!c && !it && !UI.aim && propAt(tileAt(e))) propTip(e, propAt(tileAt(e)));
    else if (UI.tipFor) { UI.tipFor = null; tip(); }
    const p = pointAt(e), key = UI.aim || (ST && moveArmed(ST.battle)) ? p.join(',') : '';
    if (key !== UI.hoverKey) { UI.hoverKey = key; UI.hover = key ? p : null; requestAnimationFrame(renderMap); }
    return;
  }
  const [sx, sy] = screenAt(e), dx = sx - press.sx, dy = sy - press.sy;
  if (!press.moved && Math.abs(dx) + Math.abs(dy) < press.slop) return;
  press.moved = true; tip();
  if (press.mode === 'item') {
    UI.item.at = pointAt(e); UI.item.moved = true;
  } else {
    board.style.cursor = 'grabbing';
    UI.cam = { x: press.cam.x + dx, y: press.cam.y + dy, z: press.cam.z };
  }
  renderMap();
});
function release(e) {
  pointers.delete(e.pointerId);
  const p = press;
  if (!p || (p.mode === 'pinch' && pointers.size)) return;
  press = null;
  board.style.cursor = 'grab';
  if (p.mode === 'item') {                                   // an item dragged onto my token: picked up; a tap shows its name
    const d = UI.item, c = tokenAt(pointAt(e)); UI.item = null;
    if (d.moved && c && c.mine) act('do', { item: 'pickup', option: String(d.id) });
    else if (!d.moved) UI.groundHover = UI.groundHover === d.id ? null : d.id;
    renderMap();
    return;
  }
  if (p.mode === 'pan' && !p.moved && !p.middle) {
    if (Date.now() < (UI.quietUntil || 0)) return;           // the second tap of a double tap that just used an action
    if (UI.place) { const d = UI.place; UI.place = null; renderAimbar(); moveItem(d, 'map', tileAt(e)); return; }
    if (UI.aim) { if (p.touch) aimTap(pointAt(e), p.token); else aimClick(pointAt(e), p.token); return; }
    const b = ST.battle;
    if (p.token) tapToken(p.token);                          // a click on a creature targets it (yours: picks it)
    else if (p.touch && moveArmed(b)) { const [x, y] = tileAt(e); moveTap(x, y); }   // touch: the way there, to confirm
    else {                                                   // a click on the ground: lets go of my token
      if (UI.move) cancelMove();
      if (UI.sel) { if (UI.inspect === UI.sel) UI.inspect = null; UI.sel = null; renderMap(); }
    }
  }
}
/** A right-click: cancels the aim (or the item being put down); otherwise walks my token to that tile. */
function rightClick(e) {
  if (!ST) return;
  if (UI.aim) return cancelAim();
  if (UI.place) return cancelPlace();
  const b = ST.battle, me = mover();
  if (!canMove(b) || !me) {
    if (me && b.settings.move_tokens && b.status === 'active') say(S('You can move your token on your turn.'), true);
    return;
  }
  if (!moveArmed(b)) { say(S('Click your token first to pick it, then right-click where it should go.')); return; }
  const [x, y] = tileAt(e);
  if (me.pos && x >= me.pos[0] && x < me.pos[0] + me.span && y >= me.pos[1] && y < me.pos[1] + me.span) return;   // on itself
  if (UI.move) { UI.move = null; renderAimbar(); }
  if (me.pos) walkTo(me.id, x, y); else act('move', { x, y });   // (not on the map yet: put there)
}
/** A creature's hover card on the map: its name and health, its conditions and effects as pictures, how far it is,
 *  and what a click does. */
function tokenCard(c) {
  const b = ST.battle, me = meInBattle() || b.combatants.find(x => x.mine && x.pos), look = badgeLook();
  const pct = c.hp != null && c.max_hp ? Math.max(0, Math.min(100, 100 * c.hp / c.max_hp)) : null;
  const f = c.form, fpct = f && f.max_hp ? Math.max(0, Math.min(100, 100 * f.hp / f.max_hp)) : null;   // in a beast's shape: its bar first
  return h('div', { class: 'tokcard' },
    h('div', { class: 'tc-head' }, h('b', null, c.name), h('span', { class: 'grow' }), hpWords(c)),
    c.sub ? h('div', { class: 'dim small' }, c.sub) : null,                // a character's race and class
    fpct != null ? h('div', { class: 'dim small' }, `${f.name} ${f.hp}/${f.max_hp}`) : null,
    fpct != null ? h('div', { class: 'hpbar' }, h('div', { style: `width:${fpct}%;background:#d6a35c` })) : null,
    pct != null ? h('div', { class: 'hpbar' }, h('div', { style: `width:${pct}%;background:${pct > 50 ? '#4ade80' : pct > 25 ? '#fbbf24' : '#f87171'}` })) : null,
    ...effectLines(c, look),
    me && me.pos && c.pos && me.id !== c.id ? h('div', { class: 'dim small' }, S('{0} ft away', Geo.dist(me, c))) : null,
    c.untargetable && !c.mine ? h('div', { class: 'small warn' }, S("Can't be targeted now (banished, ethereal or sealed away)")) : null,
    h('div', { class: 'dim small' }, c.mine ? (isMover(c) && ST.battle.settings.move_tokens ? S('Click: pick your token (then right-click a tile to walk there)') : S('Click: show your details'))
      : c.id === UI.target ? S('Click: clear the target')
      : c.untargetable ? S('Click: show it') : S('Click: make it your target')));
}
/** Each condition and effect on a creature, a line each: its picture, rounds left, the save that ends it, whose it is. */
function effectLines(c, look) {
  return (c.effects || []).map(e => {
    const note = [e.rounds ? S('{0} rds', e.rounds) : '', e.save || '', e.from ? S('from {0}', e.from) : ''].filter(Boolean).join(', ');
    const colour = (look[e.key] || [])[1] || 'var(--warn)';
    return h('div', { class: 'conds small', style: 'gap:4px' }, look[e.key] ? h('span', { style: `color:${colour}` }, gi(e.key)) : null,
      h('span', { style: `color:${colour}` }, e.name), note ? h('span', { class: 'dim' }, ` (${note})`) : null);
  });
}
/** The known-info card over the map for the creature you picked: what anyone at the table can see of it - its
 *  picture, what it is, how hurt it looks, what it wears and holds, its conditions and effects, what it holds its
 *  mind on - never its numbers, its spells or what is in its pack (the server sends none of that: api._seen). */
function renderKnown(b) {
  const box = $('known');
  if (!box) return;
  const id = UI.inspect || UI.target, c = id != null ? b.combatants.find(x => x.id === id) : null;
  box.classList.toggle('hide', !c);
  if (!c) { box.replaceChildren(); return; }
  const seen = c.seen || {}, look = badgeLook(), me = meInBattle() || b.combatants.find(x => x.mine && x.pos);
  const px = 46, dpr = window.devicePixelRatio || 1, cv = h('canvas', { class: 'kn-pic', width: px * dpr, height: px * dpr, style: `width:${px}px;height:${px}px` });
  const g = cv.getContext('2d'); g.scale(dpr, dpr); tokenDisc(g, c, px / 2, px / 2, px / 2 - 1);
  const side = c.mine ? S('You') : c.kind === 'pc' || c.ally ? S('Ally') : S('Enemy');
  const pct = c.hp != null && c.max_hp ? Math.max(0, Math.min(100, 100 * c.hp / c.max_hp)) : null;
  const line = (label, items) => items && items.length ? h('div', { class: 'small' }, h('span', { class: 'dim' }, label + ' '), items.join(', ')) : null;
  box.replaceChildren(
    h('div', { class: 'kn-head' }, cv,
      h('div', { class: 'grow' }, h('b', null, c.name), h('div', { class: 'dim small' }, [side, seen.what, c.sub].filter(Boolean).join(' · '))),
      h('button', { class: 'sm flat', onclick: () => { UI.target = null; UI.inspect = null; renderMap(); }, 'aria-label': S('Close') }, '✕')),
    h('div', { class: 'small' }, h('span', { class: 'dim' }, S('Looks:') + ' '), c.out ? S('Down') : c.health,
      c.form ? h('span', { class: 'dim' }, ' · ' + S('in the shape of {0}', c.form.name)) : null),
    pct != null ? h('div', { class: 'hpbar' }, h('div', { style: `width:${pct}%;background:${pct > 50 ? '#4ade80' : pct > 25 ? '#fbbf24' : '#f87171'}` })) : null,
    line(S('Wears:'), seen.wears), line(S('Holds:'), seen.holds),
    c.conc ? h('div', { class: 'small' }, S('Concentrating on {0}', c.conc.spell)) : null,
    ...effectLines(c, look),
    me && me.pos && c.pos && me.id !== c.id ? h('div', { class: 'dim small' }, S('{0} ft away', Geo.dist(me, c))) : null);
}
function tapToken(c) {
  if (isMover(c)) {                                          // my token: picked (its details shown) or let go
    const on = UI.sel === c.id; UI.sel = on ? null : c.id; UI.inspect = on ? null : c.id;
  } else if (c.mine || (c.untargetable && c.id !== UI.target)) UI.inspect = UI.inspect === c.id ? null : c.id;   // (out of reach: shown, not a target)
  else { UI.target = c.id === UI.target ? null : c.id; UI.inspect = null; }
  if (UI.move) { UI.move = null; renderAimbar(); }
  renderMap();
}
/** May I move my token now: on my turn in a fight; any time out of combat. */
const canMove = b => !!b.settings.move_tokens && (b.status === 'active' ? !!b.my_turn : true);   // out of combat, before or after: free
/** The token a move walks: the one whose turn it is (mine), else my character's. */
const mover = () => ST && (meInBattle() || myToken() || ST.battle.combatants.find(c => c.mine && c.pos));
const isMover = c => { const m = mover(); return !!(m && c && m.id === c.id); };
/** Does a right-click walk my token now: on my turn in a fight (it is picked for me); out of one, once I've picked it
 *  (a click on it) - or, not on the map yet, to put it there. */
const moveArmed = b => {
  if (!canMove(b)) return false;
  const m = mover();
  return !!m && (b.status === 'active' || !m.pos || UI.sel === m.id);
};
/** My turn starts: my token is picked (and shown, when it is off the screen); it ends: let go. */
function turnPick(b) {
  const mine = b.status === 'active' && !!b.my_turn;
  if (mine && !UI.myTurn) {
    const m = mover();
    if (m) {
      UI.sel = m.id;
      if (m.pos && UI.cam) {
        const c = UI.cam, wrap = $('mapwrap'), x = m.pos[0] * c.z + c.x, y = m.pos[1] * c.z + c.y, s = m.span * c.z, pad = Math.max(s, 40);
        if (x < pad || y < pad || x + s > wrap.clientWidth - pad || y + s > Math.max(160, wrap.clientHeight) - pad) centerOn(m);   // off (or at) the edge
      }
    }
  } else if (!mine && UI.myTurn && b.status === 'active') UI.sel = null;
  UI.myTurn = mine;
}
/** The movement left this turn (out of combat: no limit). */
const moveLeft = b => b.status === 'active' && b.actions && b.actions.turn ? b.actions.turn.move : null;
/** Walk my token there; a ghost stays at the destination until the table answers (no snapping back meanwhile). */
function walkTo(id, x, y) {
  UI.ghost = { id, at: [x, y] }; renderMap();
  return act('move', { x, y }).finally(() => { UI.ghost = null; renderMap(); });
}
/** Touch: the first tap on a tile shows the way there and what it costs (the table works it out); the second goes. */
async function moveTap(x, y) {
  const me = meInBattle() || ST.battle.combatants.find(c => c.mine && c.pos);
  if (!me || !me.pos) return act('move', { x, y });          // putting the token on the map: at once
  if (UI.move && UI.move.x === x && UI.move.y === y) return moveGo();
  UI.move = { x, y, id: me.id, cost: null, path: null };
  renderAimbar(); renderMap();
  try {
    const r = await api('/api/act', { action: 'preview', character: ST.me.active, item: 'move', point: [x, y] });
    if (UI.move && UI.move.x === x && UI.move.y === y) { Object.assign(UI.move, r.data || {}); renderAimbar(); renderMap(); }
  } catch (e) { if (UI.move && UI.move.x === x && UI.move.y === y) { UI.move.ok = false; UI.move.why = e.message; renderAimbar(); } }
}
function moveGo() {
  const m = UI.move;
  UI.move = null; renderAimbar();
  return m ? walkTo(m.id, m.x, m.y) : null;
}
function cancelMove() { UI.move = null; renderAimbar(); renderMap(); }
board.addEventListener('contextmenu', e => e.preventDefault());   // the right button is the map's: no browser menu
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (closeDetail()) return;
    if (!$('menupop').classList.contains('hide')) { $('menupop').classList.add('hide'); $('menu').focus(); return; }
    if (UI.place) cancelPlace(); else if (UI.aim) cancelAim(); else if (UI.move) cancelMove();
    else if (UI.sel && ST && ST.battle.status !== 'active') { if (UI.inspect === UI.sel) UI.inspect = null; UI.sel = null; renderMap(); }
  }
  if (e.key === 'Enter' && UI.aim && document.activeElement === document.body) { if (UI.aim.pending) aimPick(); else commitAim(); }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '');
  const asked = !$('detail').classList.contains('hide') || !$('react').classList.contains('hide');   // a sheet or a reaction is open
  if (e.key === ' ' && e.ctrlKey && !typing && !asked && !$('endturn').disabled) { e.preventDefault(); $('endturn').click(); }   // as the DM's Next turn
  if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.altKey && !e.metaKey && !typing && !asked) {
    const it = (UI.hotkeys || [])[+e.key - 1];            // the action bar's first nine, like a game's hotbar
    if (it && ST && ST.battle.actions) { e.preventDefault(); tip(); startAim(it); }
  }
});
board.addEventListener('pointerup', e => {
  if (e.button === 2) {                                      // a right-click (not a right-drag)
    const r = rpress; rpress = null;
    if (r) { const [sx, sy] = screenAt(e); if (Math.abs(sx - r.sx) + Math.abs(sy - r.sy) < 8) rightClick(e); }
    return;
  }
  release(e);
});
board.addEventListener('dragover', e => { if (dragKind(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; } });
board.addEventListener('drop', e => {                       // an item card: on that tile, or to the creature there (Ctrl: one)
  const d = dragData(e);
  if (!d) return;
  e.preventDefault();
  moveItem(d, 'map', tileAt(e), e.ctrlKey);
});
board.addEventListener('pointercancel', release);
board.addEventListener('pointerleave', () => { if (!press) { tip(); UI.tipFor = null; } });
board.addEventListener('wheel', e => { e.preventDefault(); const [sx, sy] = screenAt(e); zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, sx, sy); }, { passive: false });
const middle = () => { const w = $('mapwrap'); return [w.clientWidth / 2, Math.max(160, w.clientHeight) / 2]; };
$('zin').onclick = () => zoomAt(1.25, ...middle());
$('zout').onclick = () => zoomAt(0.8, ...middle());
$('zfit').onclick = () => { UI.cam = null; UI.fitBox = null; renderMap(); };

// ---------------------------------------------------------------- areas on the grid (mirrors app/services/battle/geometry.py)
function pointAt(e) { const [x, y] = screenAt(e), c = camNow(); return [(x - c.x) / c.z, (y - c.y) / c.z]; }
const Geo = {
  box: (pos, span) => [pos[0], pos[1], pos[0] + span - 1, pos[1] + span - 1],
  centre: (pos, span) => [pos[0] + span / 2, pos[1] + span / 2],
  gap: (a, b) => Math.max(Math.max(0, b[0] - a[2], a[0] - b[2]), Math.max(0, b[1] - a[3], a[1] - b[3])),
  dist: (a, b) => 5 * Geo.gap(Geo.box(a.pos, a.span), Geo.box(b.pos, b.span)),
  toPoint: (c, p) => 5 * Geo.gap(Geo.box(c.pos, c.span), [Math.floor(p[0]), Math.floor(p[1]), Math.floor(p[0]), Math.floor(p[1])]),
  edge(bx, to) {
    const cx = (bx[0] + bx[2] + 1) / 2, cy = (bx[1] + bx[3] + 1) / 2, dx = to[0] - cx, dy = to[1] - cy, half = (bx[2] - bx[0] + 1) / 2, m = Math.max(Math.abs(dx), Math.abs(dy));
    return m < 1e-6 ? [cx + half, cy] : [cx + dx / m * half, cy + dy / m * half];
  },
  tiles(area, caster, aim, W, H) {
    const out = [], add = (x, y) => { if (x >= 0 && y >= 0 && x < W && y < H) out.push([x, y]); };
    const n = area.size / 5, bx = caster ? Geo.box(caster.pos, caster.span) : null, e = 1e-6;
    let shape = area.shape;
    if (area.origin === 'caster' && ['sphere', 'cylinder', 'emanation'].includes(shape)) shape = 'emanation';
    if (shape === 'emanation' && area.origin !== 'caster') shape = 'sphere';
    if (shape === 'emanation') {
      if (!bx) return out;
      for (let x = bx[0] - n; x <= bx[2] + n; x++) for (let y = bx[1] - n; y <= bx[3] + n; y++)
        if (!(x >= bx[0] && x <= bx[2] && y >= bx[1] && y <= bx[3])) add(x, y);
      return out;
    }
    if (shape === 'sphere' || shape === 'cylinder') {
      if (!aim) return out;
      for (let x = Math.floor(aim[0] - n) - 1; x <= Math.ceil(aim[0] + n); x++) for (let y = Math.floor(aim[1] - n) - 1; y <= Math.ceil(aim[1] + n); y++)
        if (Math.hypot(x + .5 - aim[0], y + .5 - aim[1]) <= n + e) add(x, y);
      return out;
    }
    if ((shape === 'cube' || shape === 'square') && area.origin === 'point') {
      if (!aim) return out;
      const hf = n / 2;
      for (let x = Math.floor(aim[0] - hf) - 1; x <= Math.ceil(aim[0] + hf); x++) for (let y = Math.floor(aim[1] - hf) - 1; y <= Math.ceil(aim[1] + hf); y++)
        if (Math.abs(x + .5 - aim[0]) <= hf + e && Math.abs(y + .5 - aim[1]) <= hf + e) add(x, y);
      return out;
    }
    if (!bx) return out;
    const to = aim || [bx[2] + 2, bx[1] + .5];
    if (shape === 'cube' || shape === 'square') {
      const c = Geo.centre(caster.pos, caster.span), dx = to[0] - c[0], dy = to[1] - c[1], m = Math.hypot(dx, dy) || 1, ux = dx / m, uy = dy / m;
      const sx = Math.abs(ux) < .383 ? 0 : Math.sign(ux), sy = Math.abs(uy) < .383 ? 0 : Math.sign(uy), k = Math.max(1, Math.round(n));
      const span = (lo, hi, s) => s > 0 ? [hi + 1, hi + k] : s < 0 ? [lo - k, lo - 1] : [Math.floor((lo + hi) / 2) - Math.floor((k - 1) / 2), Math.floor((lo + hi) / 2) - Math.floor((k - 1) / 2) + k - 1];
      const [x0, x1] = span(bx[0], bx[2], sx), [y0, y1] = span(bx[1], bx[3], sy);
      for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) add(x, y);
      return out;
    }
    const o = Geo.edge(bx, to), dx = to[0] - o[0], dy = to[1] - o[1], m = Math.hypot(dx, dy) || 1, ux = dx / m, uy = dy / m, hw = Math.max((area.width || 5) / 10, .5);
    for (let x = Math.floor(o[0] - n) - 2; x <= Math.ceil(o[0] + n) + 1; x++) for (let y = Math.floor(o[1] - n) - 2; y <= Math.ceil(o[1] + n) + 1; y++) {
      if (x >= bx[0] && x <= bx[2] && y >= bx[1] && y <= bx[3]) continue;
      const vx = x + .5 - o[0], vy = y + .5 - o[1], along = vx * ux + vy * uy, side = Math.abs(-vx * uy + vy * ux);
      if (along <= e || along > n + e) continue;
      if (shape === 'cone' ? side <= along / 2 + e : side <= hw + e) add(x, y);
    }
    return out;
  },
};
// lasting areas: a colour per family (and kind), the damage type's for the ones that hurt by it (vfx.py ZONE_COL)
const ZONE_COL = { fire: '#ff7a1a', 'cloud:fog': '#c8d2e6', 'cloud:poison': '#a3e635', 'cloud:smoke': '#9ca3af', 'cloud:sleet': '#dbeafe',
  dark: '#05060a', light: '#fde047', 'tangle:web': '#e7e5e4', 'tangle:vine': '#65a30d', 'tangle:thorn': '#84cc16', 'tangle:grease': '#57534e',
  'tangle:earth': '#d6c3a1', 'whirl:daggers': '#e5e7eb', 'whirl:insects': '#57534e', 'whirl:wind': '#e5e7eb', 'whirl:storm': '#60a5fa',
  'wall:stone': '#9ca3af', 'wall:ice': '#bae6fd', 'wall:force': '#67e8f9', 'wall:wind': '#e5e7eb', 'wall:water': '#38bdf8', 'wall:sand': '#d6c3a1',
  'beam:moon': '#e0f2fe', 'beam:sick': '#bef264', 'beam:sun': '#fff3b0', help: '#5eead4', dome: '#93c5fd', silence: '#94a3b8',
  illusion: '#c4b5fd', arrows: '#d6c3a1', area: '#7c8cff' };
function zoneColour(fam, sub, dtype) {
  if (dtype && (fam === 'whirl' || fam === 'beam') && ['spirits', '', 'storm'].includes(sub) && DMG[dtype]) return DMG[dtype];
  return ZONE_COL[`${fam}:${sub}`] || ZONE_COL[fam] || ZONE_COL[Object.keys(ZONE_COL).find(k => k.startsWith(fam + ':'))] || ZONE_COL.area;
}
function tileRnd(x, y, k, seed) { const v = Math.sin(x * 12.9898 + y * 78.233 + k * 37.719 + seed * .137) * 43758.5453; return v - Math.floor(v); }
// a lasting area under the tokens: its family's colour, a still texture that says what it is (embers, cloud, strands,
// blades, stone...), and a crisp outline. Nothing in it moves (vfx.py paint_zone draws the same on the DM's map).
function paintZone(g, z, tiles, T) {
  const fam = z.family || 'area', sub = z.kind || '', col = zoneColour(fam, sub, z.dtype || ''), seed = z.id || 0;
  const base = { dark: .6, wall: .5, fire: .2, cloud: .14, light: .1, beam: .12, help: .12, silence: .16, illusion: .08, dome: .07 }[fam] ?? .12;
  g.save();
  g.fillStyle = rgba(col, base);
  for (const [x, y] of tiles) g.fillRect(x * T, y * T, T, T);
  g.save();                                            // the glow and the texture stay inside its tiles: no bigger than it is
  g.beginPath(); for (const [x, y] of tiles) g.rect(x * T, y * T, T, T); g.clip('nonzero');
  if ((fam === 'light' || fam === 'beam') && tiles.length) {     // a glow from its middle
    const cx = tiles.reduce((s, p) => s + p[0], 0) / tiles.length + .5, cy = tiles.reduce((s, p) => s + p[1], 0) / tiles.length + .5;
    const R = Math.max(1, Math.max(...tiles.map(([x, y]) => Math.hypot(x + .5 - cx, y + .5 - cy))) + .5) * T;
    const rg = g.createRadialGradient(cx * T, cy * T, 0, cx * T, cy * T, R);
    rg.addColorStop(0, rgba(col, fam === 'beam' ? .35 : .22)); rg.addColorStop(1, rgba(col, 0));
    g.fillStyle = rg; g.beginPath(); g.arc(cx * T, cy * T, R, 0, Math.PI * 2); g.fill();
  }
  const dot = (x, y, r) => { g.beginPath(); g.arc(x * T, y * T, r, 0, Math.PI * 2); g.fill(); };
  const line = (x0, y0, x1, y1) => { g.beginPath(); g.moveTo(x0 * T, y0 * T); g.lineTo(x1 * T, y1 * T); g.stroke(); };
  g.lineCap = 'round';
  for (const [x, y] of tiles) {                        // the texture, tile by tile
    const r = k => tileRnd(x, y, k, seed);
    if (fam === 'fire') for (let k = 0; k < 3; k++) { g.fillStyle = rgba(k % 2 ? '#fde047' : col, .7); dot(x + .15 + .7 * r(k), y + .15 + .7 * r(k + 9), T * (.04 + .04 * r(k + 3))); }
    else if (fam === 'cloud' || fam === 'dark') {     // soft overlapping blobs
      g.fillStyle = rgba(fam === 'cloud' ? col : '#4c1d95', fam === 'cloud' ? .13 : .1);
      for (let k = 0; k < 2; k++) dot(x + .2 + .6 * r(k), y + .2 + .6 * r(k + 7), T * (.42 + .25 * r(k + 5)));
    } else if (fam === 'help' || fam === 'arrows' || (fam === 'tangle' && sub === 'earth')) {
      g.fillStyle = rgba(col, .6);
      for (let k = 0; k < 2; k++) dot(x + .2 + .6 * r(k), y + .2 + .6 * r(k + 4), T * .035);
    } else if (fam === 'tangle' && ['web', 'vine', 'thorn', 'grease'].includes(sub)) {
      g.strokeStyle = rgba(col, sub === 'grease' ? .25 : .55); g.lineWidth = Math.max(1, T * (sub === 'web' ? .02 : .03));
      for (let k = 0; k < (sub === 'web' || sub === 'thorn' ? 3 : 2); k++) {
        const a = Math.PI * r(k), mx = x + .5 + (r(k + 3) - .5) * .4, my = y + .5 + (r(k + 6) - .5) * .4, L = sub === 'web' ? .5 : sub === 'thorn' ? .12 : .3;
        if (sub === 'vine') { g.beginPath(); g.arc(mx * T, my * T, T * .25, -a, -a - 200 * Math.PI / 180, true); g.stroke(); }    // curls
        else line(mx - Math.cos(a) * L, my - Math.sin(a) * L, mx + Math.cos(a) * L, my + Math.sin(a) * L);
      }
    } else if (fam === 'whirl') {                      // blades glinting, insects swarming
      g.strokeStyle = rgba(col, .75); g.lineWidth = Math.max(1, T * (sub === 'insects' ? .05 : .025));
      for (let k = 0; k < (sub === 'insects' ? 5 : 3); k++) {
        const a = Math.PI * 2 * r(k), mx = x + .15 + .7 * r(k + 3), my = y + .15 + .7 * r(k + 6), L = sub === 'insects' ? .01 : .1;
        line(mx - Math.cos(a) * L, my - Math.sin(a) * L, mx + Math.cos(a) * L, my + Math.sin(a) * L);
      }
    } else if (fam === 'wall') {                       // its material: block joints, ice glints, wind streaks
      g.strokeStyle = sub === 'stone' || sub === 'sand' ? 'rgba(11,13,18,.3)' : 'rgba(255,255,255,.3)'; g.lineWidth = Math.max(1, T * .02);
      if (sub === 'stone' || sub === 'sand') { line(x, y + .5, x + 1, y + .5); const jx = x + (y % 2 ? .3 : .7); line(jx, y, jx, y + .5); }
      else if (['ice', 'water', 'wind'].includes(sub)) line(x + .2, y + .8, x + .5, y + .2);
    }
  }
  g.restore();
  const have = new Set(tiles.map(([x, y]) => `${Math.round(x)},${Math.round(y)}`));    // the outline: every edge with nothing beyond it
  g.strokeStyle = rgba(fam === 'dark' ? '#7c3aed' : col, .75); g.lineWidth = Math.max(1.5, T * .04); g.lineCap = 'butt';
  if (fam === 'illusion' || fam === 'dome') g.setLineDash([6, 4]);
  for (const [x, y] of tiles) for (const [dx, dy, a, b] of [[0, -1, [0, 0], [1, 0]], [0, 1, [0, 1], [1, 1]], [-1, 0, [0, 0], [0, 1]], [1, 0, [1, 0], [1, 1]]])
    if (!have.has(`${Math.round(x + dx)},${Math.round(y + dy)}`)) line(x + a[0], y + a[1], x + b[0], y + b[1]);
  g.restore();
}
function drawZones(g, b, T) {
  for (const z of b.zones || []) {
    const off = FX.zoneOffset(z.id) || [0, 0];         // gliding after a move
    paintZone(g, z, z.tiles.map(([x, y]) => [x + off[0], y + off[1]]), T);
    if (z.tiles.length && T >= 18) {
      const [x, y] = z.tiles[0];
      g.fillStyle = '#e6e9efaa'; g.font = '10px Segoe UI'; g.textAlign = 'left'; g.textBaseline = 'top'; g.fillText(z.name, x * T + 2, y * T + 2);
    }
  }
}

// ---------------------------------------------------------------- aiming (BG3 style): pick a spell or action, then its target
const meInBattle = () => ST && ST.battle.actions && ST.battle.combatants.find(c => c.id === ST.battle.actions.id);
function aimCount(a) {
  const t = a.item.target || {}, lvl = a.item.level || 0, slot = parseInt(a.slot || lvl, 10) || lvl;
  if (t.type === 'split') {
    const per = t.per_level || 0, base = t.base_level != null ? t.base_level : lvl;
    return (t.count || 1) + per * Math.max(0, slot - base);
  }
  return (t.count || 1) + (t.per_level || 0) * Math.max(0, slot - (t.base_level != null ? t.base_level : lvl));
}
function aimArea(a) { return a.item.area || (a.item.target || {}).area || null; }
/** Throw / Use an Object: options that carry what the inventory picker shows (an older battle's are plain labels). */
const richOptions = opts => !!(opts && opts.length && opts.every(o => 'group' in o));
/** A long list of plain choices (Wild Shape's beasts, a summon's forms...): boxes in the character panel while aiming,
 *  not a dropdown as tall as the screen. A short one stays a dropdown in the aim bar. */
const longOptions = a => !!(a && a.options.length >= 7 && !richOptions(a.options));
/** "Brown Bear (CR 1, 34 HP)" → ['Brown Bear', 'CR 1, 34 HP']. */
function optionBits(o) {
  const m = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(o.label || '');
  return m ? [m[1], m[2]] : [o.label || String(o.value), ''];
}
/** The aim's choices as a card of boxes over the sheet - only while aiming; the card is kept on the aim, so a search
 *  and the list's scroll outlive the sheet's redraws. Grouped under a heading when the brackets start alike (CR 1...). */
function optionCard(a) {
  if (a.card) { syncOptionCard(a); return a.card; }
  const bits = a.options.map(optionBits), heads = bits.map(([, m]) => m.split(',')[0].trim());
  const kinds = new Set(heads), runs = heads.filter((x, i) => !i || x !== heads[i - 1]).length;
  const grouped = heads.every(Boolean) && kinds.size > 1 && kinds.size <= a.options.length / 2 && runs === kinds.size;
  const list = h('div', { class: 'optpick', role: 'listbox', 'aria-label': a.item.label || a.item.name });
  const draw = () => {
    const kids = [];
    let last = null;
    a.options.forEach((o, i) => {
      if (a.needle && !(o.label || '').toLowerCase().includes(a.needle)) return;
      if (grouped && heads[i] !== last) { last = heads[i]; kids.push(h('div', { class: 'title' }, heads[i])); }
      const more = grouped ? bits[i][1].split(',').slice(1).join(',').trim() : bits[i][1];
      kids.push(h('button', { class: 'opt', role: 'option', 'data-v': String(o.value), onclick: () => pickOption(a, o.value) },
        h('b', null, bits[i][0]), more ? h('span', { class: 'dim small' }, more) : null));
    });
    list.replaceChildren(...(kids.length ? kids : [h('div', { class: 'dim' }, S('Nothing matches.'))]));
    syncOptionCard(a);
  };
  a.card = h('div', { class: 'card optcard' },
    h('div', { class: 'row' }, h('div', { class: 'title grow' }, `${a.item.label || a.item.name} · ${S('Choose one')}`),
      a.options.length > 12 ? h('input', { type: 'search', placeholder: S('search…'), 'aria-label': S('Search'),
        oninput: e => { a.needle = e.target.value.trim().toLowerCase(); draw(); } }) : null),
    list,
    h('div', { class: 'row' }, aimNeedsClick(a) ? h('span', { class: 'dim small' }, S('Then pick the target on the map')) : null, h('span', { class: 'grow' }),
      aimNeedsClick(a) ? null : btn(S('Confirm'), commitAim, 'sm primary'), btn('✕ ' + S('Cancel'), cancelAim, 'sm')));
  draw();
  return a.card;
}
function syncOptionCard(a) {
  if (a.card) a.card.querySelectorAll('.opt').forEach(b => {
    const on = b.dataset.v === String(a.option);
    b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on));
  });
}
function pickOption(a, v) {
  if (UI.aim !== a) return;
  a.option = v; syncOptionCard(a); renderAimbar();
  if (NARROW.matches && aimNeedsClick(a)) showView('map');   // phones: on to the map for the target
}
/** The aim bar's word on the choice: a tap shows the boxes (phones: the character view). */
function showOptions(a) {
  if (NARROW.matches) showView('sheet');
  requestAnimationFrame(() => { if (a.card && UI.aim === a) { a.card.scrollIntoView({ block: 'nearest' }); (a.card.querySelector('input') || a.card.querySelector('.opt.on') || a.card).focus(); } });
}
const PICK_GROUPS = { pack: 'In your pack', ground: 'On the ground within reach', prop: 'Within reach' };
const PICK_COSTS = { action: 'Action', bonus: 'Bonus action', attack: 'One attack', object: 'Free object use' };
/** The inventory picker of Throw and Use an Object: each thing with its picture and what it does - to hit, damage
 *  (its average) and range for a throw; the effect and the action it takes for a use - and how long a goodberry lasts. */
function pickInventory(item, opts, done) {
  const throwing = item.kind === 'throw';
  let order = 'pack', needle = '';
  const list = h('div', { class: 'invpick', role: 'listbox', 'aria-label': throwing ? S('Throw what?') : S('Use what?') });
  const num = x => Number.isInteger(x) ? String(x) : x.toFixed(1);
  const row = o => {
    const bits = [];
    if (throwing) {
      if (o.hit != null) bits.push(h('span', { class: 'acc' }, S('{0} to hit', (o.hit >= 0 ? '+' : '') + o.hit)));
      if (o.dmg) bits.push(h('span', null, h('span', { class: 'warn' }, o.dmg), o.avg != null ? h('span', { class: 'dim' }, ` (${S('avg {0}', num(o.avg))})`) : null));
      if (o.range) bits.push(h('span', null, o.range));
      if (o.cost === 'action') bits.push(h('span', { class: 'dim' }, S('takes the action')));
    } else if (o.effect) bits.push(h('span', { class: 'good' }, S(o.effect)));
    if (o.expires) bits.push(h('span', { class: 'warn' }, '⏳ ' + o.expires));
    const sep = []; bits.forEach((b, i) => { if (i) sep.push(h('span', { class: 'dim' }, ' · ')); sep.push(b); });
    const chip = throwing ? S((o.kind || 'improvised').charAt(0).toUpperCase() + (o.kind || 'improvised').slice(1)) : S(PICK_COSTS[o.cost] || 'Action');
    return h('button', { class: 'ipr', role: 'option', onclick: () => { detailGone = null; closeDetail(); done(o.value); } },
      h('img', { class: 'ipi', alt: '', src: o.prop ? `/prop/${o.prop}.webp` : `/itemsprite/${o.sprite || 'sack'}.png` }),
      h('span', { class: 'ipt' },
        h('span', { class: 'ipn' }, h('b', null, o.name || o.label), o.qty > 1 ? h('span', { class: 'dim' }, ` ×${o.qty}`) : null,
          h('span', { class: 'chip' + (o.kind === 'thrown weapon' || o.cost === 'bonus' ? ' on' : '') }, chip)),
        h('span', { class: 'ips small' }, ...sep)));
  };
  const draw = () => {
    let rows = opts.filter(o => !needle || `${o.name || ''} ${o.label || ''}`.toLowerCase().includes(needle));
    if (order === 'damage') rows = [...rows].sort((a, b) => (b.avg || 0) - (a.avg || 0));
    if (order === 'hit') rows = [...rows].sort((a, b) => (b.hit != null ? b.hit : -99) - (a.hit != null ? a.hit : -99));
    const groups = order === 'pack' ? Object.keys(PICK_GROUPS).filter(g => rows.some(o => o.group === g)) : [null];
    const kids = [];
    for (const g of groups) {
      if (g && (groups.length > 1 || g !== 'pack')) kids.push(h('div', { class: 'title' }, S(PICK_GROUPS[g])));
      kids.push(...(g ? rows.filter(o => o.group === g) : rows).map(row));
    }
    list.replaceChildren(...(kids.length ? kids : [h('div', { class: 'dim' }, S('Nothing matches.'))]));
  };
  draw();
  detail(() => h('div', { class: 'invwrap' },
    h('b', null, throwing ? S('Throw what?') : S('Use what?')),
    h('div', { class: 'qrow' },
      opts.length > 6 ? h('input', { type: 'search', placeholder: S('search…'), 'aria-label': S('Search'), oninput: e => { needle = e.target.value.trim().toLowerCase(); draw(); } }) : null,
      throwing ? h('select', { 'aria-label': S('Order'), onchange: e => { order = e.target.value; draw(); } },
        h('option', { value: 'pack' }, S('Pack order')), h('option', { value: 'damage' }, S('Most damage')), h('option', { value: 'hit' }, S('Best to hit'))) : null),
    list));
}
function startAim(item, chosen) {
  if (!item.ok) { say(item.why || S('Not now'), true); return; }
  if (chosen == null && richOptions(item.options)) return pickInventory(item, item.options, v => startAim(item, v));   // Throw / Use: pick it first
  const t = item.target || { type: 'none' };
  UI.move = null;
  if (touch()) { UI.hover = null; UI.hoverKey = null; }      // no hover on touch: the area shows from the first tap
  const free = item.kind === 'spell' && item.level ? slotLevels(item) : [];    // the lowest slot that is left (a pact slot counts)
  UI.aim = { item, targets: [], point: null, slot: item.level ? String(free.length ? free[0].level : item.level) : '', dtype: (item.types || [])[0] || '',
    option: chosen != null ? chosen : item.options && item.options.length ? item.options[0].value : '', options: item.options || [], metamagic: '' };
  if (t.type === 'fixed' || item.readied) { if (t.type === 'fixed') UI.aim.targets = [t.id]; return commitAim(); }   // a readied smite: one click lets it go
  if (!aimNeedsClick(UI.aim) && item.kind !== 'spell' && !(item.types || []).length && (!UI.aim.options.length || chosen != null)) return commitAim();   // Dash, Dodge, a potion picked...: at once
  const tgt = UI.target && ['creature', 'split'].includes(t.type) && ST.battle.combatants.find(c => c.id === UI.target), me = meInBattle();
  if (tgt && tgt.pos && !(me && me.pos && item.range != null && Geo.dist(me, tgt) > Math.max(5, item.range)))      // your target, in reach:
    UI.aim.pending = { key: tgt.pos.join(','), p: [tgt.pos[0] + .5, tgt.pos[1] + .5], token: tgt };                // one click (or Enter) on
  else if (tgt && tgt.pos && me && me.pos) say(S('{0} is out of reach ({1} ft): pick another creature', tgt.name, Geo.dist(me, tgt)));
  if (item.kind === 'spell') api('/api/act', { action: 'preview', character: ST.me.active, item: item.id, slot: UI.aim.slot }).then(r => {
    if (UI.aim && UI.aim.item === item && r.data && r.data.options && r.data.options.length) {
      UI.aim.options = r.data.options; UI.aim.option = r.data.options[0].value; UI.aim.card = null; renderAimbar(); renderSheet();
    }
  }).catch(() => {});
  renderAimbar(); renderMap(); renderActions();
  if (longOptions(UI.aim)) { renderSheet(); showOptions(UI.aim); }
}
function cancelAim() { const had = UI.aim && UI.aim.card; UI.aim = null; renderAimbar(); renderMap(); renderActions(); if (had) renderSheet(); }
/** The levels a spell can be cast at now, lowest first: [{level, left, pact}] (a warlock's pact slots at their level). */
function slotLevels(item) {
  return (item && item.slot_levels) || [];
}
/** Touch aiming: the first tap only shows (the area, who is hit, the creature picked); the same tap again or Confirm uses it. */
function aimTap(p, token) {
  const a = UI.aim, t = a.item.target || {}, tile = [Math.floor(p[0]), Math.floor(p[1])], key = tile.join(',');
  if (!aimNeedsClick(a)) return;
  const tok = token || tokenAt(p);
  if ((t.type === 'creature' || t.type === 'split') && !tok) return;
  if (a.pending && a.pending.key === key) return aimPick();
  a.pending = { key, p, token: tok };
  UI.hover = p; UI.hoverKey = null;
  renderMap(); renderAimbar();
}
function aimPick() {
  const a = UI.aim, q = a && a.pending;
  if (!q) return;
  a.pending = null;
  aimClick(q.p, q.token);
}
function aimNeedsClick(a) {
  const t = a.item.target || {};
  return ['creature', 'split', 'point'].includes(t.type) || (t.type === 'self_area' && t.aim);
}
function aimClick(p, token) {
  const a = UI.aim, t = a.item.target || {}, me = meInBattle(), tile = [Math.floor(p[0]), Math.floor(p[1])];
  const tok = token || tokenAt(p);
  if (t.type === 'creature' || t.type === 'split') {
    if (!tok) return;
    if (tok.untargetable && !tok.mine) return say(S("{0} can't be targeted now", tok.name), true);   // banished, ethereal, sealed
    if (me && me.pos && tok.pos && a.item.range != null && Geo.dist(me, tok) > Math.max(5, a.item.range)) return say(S('Out of range'), true);
    if (t.type === 'creature' && a.targets.includes(tok.id)) a.targets = a.targets.filter(x => x !== tok.id);
    else a.targets.push(tok.id);
    if (a.targets.length >= aimCount(a)) return commitAim();
    renderAimbar(); renderMap(); return;
  }
  if (t.type === 'point' || t.type === 'self_area') {
    const area = aimArea(a);
    a.point = area && ['sphere', 'cylinder'].includes(area.shape) ? [Math.round(p[0]), Math.round(p[1])] : [tile[0] + .5, tile[1] + .5];
    if (t.type === 'point' && me && me.pos && a.item.range != null && Geo.toPoint(me, a.point) > (t.teleport || a.item.range)) { a.point = null; return say(S('Out of range'), true); }
    return commitAim();
  }
  commitAim();
}
async function commitAim() {
  const a = UI.aim;
  if (!a) return;
  UI.aim = null; UI.quietUntil = Date.now() + 350; renderAimbar(); renderMap();
  if (a.card) renderSheet();                                 // the choice's boxes go
  const rolls = a.item.kind === 'spell' || ['creature', 'split', 'point', 'self_area'].includes((a.item.target || {}).type);
  await act('do', { item: a.item.id, targets: a.targets, point: a.point, slot: a.slot || null, dtype: a.dtype || null, option: a.option || null,
    metamagic: a.metamagic || null }, false, { adv: rolls });
}
/** The bar over the map while aiming (what to click, the slot it spends, who is hit) - or, on touch, the walk to confirm. */
function renderAimbar() {
  const bar = $('aimbar'), a = UI.aim;
  let vig = $('vignette');                                   // aiming (or putting an item down): the map's edges dim in
  if (!vig) { vig = h('div', { id: 'vignette', 'aria-hidden': 'true' }); $('mapwrap').append(vig); }
  vig.classList.toggle('on', !!(a || UI.place));
  if (!a && UI.place) {
    bar.classList.remove('hide');
    bar.replaceChildren(h('b', null, '🎒 ' + UI.place.label), h('span', { class: 'dim' },
      touch() ? S('Tap a tile to put it there (on a creature: handed over)') : S('Click a tile to put it there (on a creature: handed over)')),
      h('span', { class: 'grow' }), btn('✕ ' + S('Cancel'), cancelPlace, 'sm'));
    return;
  }
  if (!a) {
    const m = UI.move;
    if (!m) { bar.classList.add('hide'); return; }
    bar.classList.remove('hide');
    const left = m.left != null ? m.left : moveLeft(ST.battle);
    const txt = m.cost == null && m.ok == null ? S('Working out the way…') : m.ok === false ? '⛔ ' + (m.why || S('Not now'))
      : left != null ? S('{0} ft - {1} ft left after', m.cost, Math.max(0, left - m.cost)) : S('{0} ft', m.cost);
    const oa = (m.threats || []).length ? h('span', { class: 'bad' }, '⚔ ' + S('Opportunity attack: {0}', m.threats.map(t => t.name).join(', '))) : null;
    bar.replaceChildren(h('b', null, '🦶 ' + S('Move')), h('span', { class: m.ok === false ? 'bad' : 'dim' }, txt), ...(oa ? [oa] : []), h('span', { class: 'grow' }),
      h('button', { class: 'sm primary', onclick: go(moveGo), disabled: m.ok === false }, S('Move here')), btn('✕ ' + S('Cancel'), cancelMove, 'sm'));
    return;
  }
  bar.classList.remove('hide');
  const t = a.item.target || {}, kids = [h('b', null, a.item.label || a.item.name)], tap = touch();
  const say_ = (tap ? {
    creature: S('Tap {0} creature(s), then confirm ({1}/{0})', aimCount(a), a.targets.length), split: S('Tap targets for each of {0}, confirming each ({1}/{0}) - the same creature more than once is fine', aimCount(a), a.targets.length),
    point: t.teleport ? S('Tap where to go (up to {0} ft), then confirm', t.teleport) : S('Tap a point within {0} ft, then confirm', a.item.range), self_area: S('Tap the direction to aim, then confirm'),
  } : {
    creature: S('Click {0} creature(s) ({1}/{0})', aimCount(a), a.targets.length), split: S('Click targets for each of {0} ({1}/{0}) - the same creature more than once is fine', aimCount(a), a.targets.length),
    point: t.teleport ? S('Click where to go (up to {0} ft)', t.teleport) : S('Click a point within {0} ft', a.item.range), self_area: S('Click the direction to aim'),
  })[t.type] || S('Confirm to use it');
  kids.push(h('span', { class: 'dim' }, say_));
  if (a.item.kind === 'spell' && a.item.level > 0 && ST.battle.actions) {
    const lv = slotLevels(a.item);                  // the level to cast at: any slot left at the spell's level or up
    const word = l => l.pact ? S('Level {0} pact slot ({1} left)', l.level, l.left) : S('Level {0} slot ({1} left)', l.level, l.left);
    if (lv.length > 1) kids.push(h('span', { class: 'dim' }, S('Cast at')), h('select', { onchange: e => { a.slot = e.target.value; e.target.blur(); renderAimbar(); }, 'aria-label': S('Spell slot') },
      ...lv.map(l => h('option', { value: String(l.level), selected: String(l.level) === a.slot }, word(l)))));
    else if (lv.length) kids.push(h('span', { class: 'acc' }, S('Uses: {0}', word(lv[0]))));     // one way only (a warlock's pact level): nothing to ask
    else kids.push(h('span', { class: 'bad' }, S('No spell slot left')));
  }
  if ((a.item.types || []).length) kids.push(h('select', { onchange: e => { a.dtype = e.target.value; } },
    ...a.item.types.map(x => h('option', { value: x, selected: x === a.dtype }, S(x.charAt(0).toUpperCase() + x.slice(1))))));
  if (richOptions(a.options)) {                              // Throw: what was picked; a tap picks again
    const o = a.options.find(x => x.value === a.option) || a.options[0];
    kids.push(btn('🎒 ' + (o.name || o.label) + (o.dmg ? ` (${o.dmg})` : o.effect ? ` (${S(o.effect)})` : ''),
      () => pickInventory(a.item, a.options, v => { if (UI.aim === a) { a.option = v; renderAimbar(); } }), 'sm', S('Pick something else')));
  } else if (longOptions(a)) {                               // a long list: its boxes in the character panel
    const o = a.options.find(x => String(x.value) === String(a.option)) || a.options[0];
    kids.push(btn('▤ ' + optionBits(o)[0], () => showOptions(a), 'sm on', S('Choose in the character panel')));
  } else if (a.options.length) kids.push(h('select', { onchange: e => { a.option = e.target.value; } },
    ...a.options.map(o => h('option', { value: o.value, selected: o.value === a.option }, o.label))));
  if ((a.item.metamagic || []).length) kids.push(h('select', { onchange: e => { a.metamagic = e.target.value; }, tip: S('Metamagic (sorcery points)') },
    h('option', { value: '' }, S('No Metamagic')),
    ...a.item.metamagic.map(m => h('option', { value: m.name, selected: m.name === a.metamagic }, `${S(m.name)} (${m.cost} ${S('SP')})`))));
  kids.push(advSeg());
  const names = ids => [...new Set(ids)].map(id => (ST.battle.combatants.find(c => c.id === id) || {}).name).filter(Boolean).join(', ');
  if (aimArea(a) && (a.hit || []).length) kids.push(h('span', { class: 'hits' }, S('Hits: {0}', names(a.hit))));
  else if (a.targets.length) kids.push(h('span', { class: 'hits' }, S('Targets: {0}', names(a.targets))));
  kids.push(h('span', { class: 'grow' }));
  if (a.pending) {
    const tok = a.pending.token;
    kids.push(btn(['creature', 'split'].includes(t.type) && tok ? S('Pick {0}', tok.name) : S('Confirm'), aimPick, 'sm primary'));
  } else if (!aimNeedsClick(a) || (['creature', 'split'].includes(t.type) && a.targets.length)) kids.push(btn(S('Confirm'), commitAim, 'sm primary'));
  kids.push(btn('✕ ' + S('Cancel'), cancelAim, 'sm'));
  keepFocus(bar, () => bar.replaceChildren(...kids));
}
function drawAim(g, b, T) {
  const a = UI.aim, me = a ? meInBattle() : mover();
  if (!a && UI.move) {                                       // touch: the way to the tapped tile, to confirm
    const m = UI.move, c = b.combatants.find(x => x.id === m.id);
    if (c && c.pos) drawWay(g, T, c, m);
    return;
  }
  if (!a) {
    const hv = UI.hover;                                     // my token picked: where a right-click would walk to
    if (hv && !touch() && moveArmed(b) && me && me.pos) {
      const tile = [Math.floor(hv[0]), Math.floor(hv[1])];
      if (!tokenAt(tile) && tile[0] >= 0 && tile[1] >= 0 && tile[0] < b.map.w && tile[1] < b.map.h) {
        const pk = movePeek(me, tile[0], tile[1]);          // the table's answer: the real way, and opportunity attacks on it
        if (pk && pk.path && pk.path.length) return drawWay(g, T, me, { ...pk, x: tile[0], y: tile[1] });
        const sp = me.span || 1, half = sp / 2;              // (its own size: a Large wild shape takes 2x2)
        const d = 5 * Math.max(Math.abs(tile[0] - me.pos[0]), Math.abs(tile[1] - me.pos[1])), left = moveLeft(b);
        const no = (pk && pk.ok === false) || (left != null && d > left);    // the table said no (that space is taken): red
        g.strokeStyle = no ? '#f87171aa' : '#4ade80aa'; g.setLineDash([4, 4]); g.lineWidth = 2;
        g.beginPath(); g.moveTo((me.pos[0] + half) * T, (me.pos[1] + half) * T); g.lineTo((tile[0] + half) * T, (tile[1] + half) * T); g.stroke(); g.setLineDash([]);
        g.strokeRect(tile[0] * T + 2, tile[1] * T + 2, sp * T - 4, sp * T - 4);
        if (T >= 16) { g.fillStyle = '#e6e9ef'; g.font = '11px Segoe UI'; g.textAlign = 'center'; g.textBaseline = 'bottom'; g.fillText(pk && pk.why ? S(pk.why) : `~${d} ft`, (tile[0] + half) * T, tile[1] * T - 1); }
      }
    }
    return;
  }
  drawAimArea(g, b, T, a, me);
}
/** A way to walk drawn on the board: the line, the box it ends in, its cost, and - marked "!" where it leaves an enemy's
 *  reach - who would get an opportunity attack. `lift`: room kept over the box for a label drawn there already. */
function drawWay(g, T, c, m, lift = 0) {
  const half = c.span / 2, bad = m.ok === false, col = bad ? '#f87171' : '#4ade80';
  const pts = m.path && m.path.length ? m.path : [c.pos, [m.x, m.y]];
  g.strokeStyle = col; g.lineWidth = 3; g.lineJoin = g.lineCap = 'round'; if (!m.path) g.setLineDash([4, 4]);
  g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo((x + half) * T, (y + half) * T) : g.moveTo((x + half) * T, (y + half) * T)); g.stroke(); g.setLineDash([]);
  g.lineWidth = 2; g.strokeRect(m.x * T + 2, m.y * T + 2, c.span * T - 4, c.span * T - 4);
  if (m.cost != null && T >= 14) {
    const text = `${m.cost} ${S('ft')}`, x = (m.x + half) * T, y = m.y * T - 4;
    g.font = '600 12px Segoe UI'; g.textAlign = 'center'; g.textBaseline = 'bottom';
    const w = g.measureText(text).width + 8;
    g.fillStyle = '#0b0d12d0'; g.fillRect(x - w / 2, y - 16, w, 17); g.fillStyle = bad ? '#f87171' : '#e6e9ef'; g.fillText(text, x, y);
  }
  const spots = new Set((m.threats || []).map(t => t.at.join(',')));   // where the way leaves an enemy's reach
  g.lineWidth = 2; g.font = `700 ${Math.max(10, T * .3)}px Segoe UI`; g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const s of spots) {
    const [x, y] = s.split(',').map(Number), r = Math.max(7, T * .22);
    g.fillStyle = '#fb923c'; g.strokeStyle = '#0f1115'; g.beginPath(); g.arc((x + half) * T, (y + half) * T, r, 0, Math.PI * 2); g.fill(); g.stroke();
    g.fillStyle = '#0f1115'; g.fillText('!', (x + half) * T, (y + half) * T + 1);
  }
  if (spots.size) {                                          // who: over the box (and over its cost)
    const text = '⚔ ' + S('Opportunity attack: {0}', m.threats.map(t => t.name).join(', '));
    const x = (m.x + half) * T, y = m.y * T - 4 - lift - (m.cost != null && T >= 14 ? 18 : 0);
    g.font = '600 12px Segoe UI'; g.textAlign = 'center'; g.textBaseline = 'bottom';
    const w = g.measureText(text).width + 8;
    g.fillStyle = '#0b0d12d0'; g.fillRect(x - w / 2, y - 16, w, 17); g.fillStyle = '#fb923c'; g.fillText(text, x, y);
  }
}
/** The table's word on walking `c` to a tile - the way, its cost, the opportunity attacks on it - for the mouse's hover
 *  and a dragged token: asked once the pointer rests there a moment (one at a time); null until it answers. */
const PEEKS = new Map();                 // the table's answers by key (several kept: the pointer goes back and forth)
function peekKey(c, x, y) {
  const b = ST.battle;
  return `${c.id}|${x},${y}|${moveLeft(b)}|${b.combatants.map(o => o.pos).join(';')}`;   // (someone moved: asked again)
}
function keepPeek(key, data) {
  PEEKS.delete(key); PEEKS.set(key, data);
  while (PEEKS.size > 300) PEEKS.delete(PEEKS.keys().next().value);
}
function movePeek(c, x, y) {
  const key = peekKey(c, x, y);
  if (PEEKS.has(key)) return PEEKS.get(key);
  if (UI.peekWant !== key) {
    UI.peekWant = key; clearTimeout(UI.peekTimer);
    UI.peekTimer = setTimeout(() => api('/api/act', { action: 'preview', character: ST.me.active, item: 'move', point: [x, y], near: 1 })
      .then(r => {
        const d = r.data || {};
        for (const [at, q] of Object.entries(d.near || {})) {      // the tiles around it came too: no trip for them
          const [nx, ny] = at.split(',').map(Number);
          keepPeek(peekKey(c, nx, ny), q);
        }
        delete d.near;
        keepPeek(key, d);
      }, () => { keepPeek(key, null); })
      .finally(() => { if (UI.peekWant === key) requestAnimationFrame(renderMap); }), 150);
  }
  return null;
}
/** The board while aiming: the reach, the area and who it hits, the targets picked. */
function drawAimArea(g, b, T, a, me) {
  const t = a.item.target || {}, area = aimArea(a), reach = t.teleport || a.item.range;
  if (me && me.pos && reach != null && reach > 0 && reach < 2000) {
    const k = reach / 5, bx = Geo.box(me.pos, me.span);
    g.strokeStyle = '#7c8cffaa'; g.setLineDash([6, 4]); g.lineWidth = 2;
    g.strokeRect((bx[0] - k) * T, (bx[1] - k) * T, (bx[2] - bx[0] + 1 + 2 * k) * T, (bx[3] - bx[1] + 1 + 2 * k) * T); g.setLineDash([]);
  }
  a.hit = [];
  if (area && me && me.pos) {
    const hv = UI.hover, aim = t.type === 'point' || (t.type === 'self_area' && t.aim) ?
      (hv ? (['sphere', 'cylinder'].includes(area.shape) ? [Math.round(hv[0]), Math.round(hv[1])] : [Math.floor(hv[0]) + .5, Math.floor(hv[1]) + .5]) : null) : null;
    const tiles = Geo.tiles(area, me, aim, b.map.w, b.map.h), set = new Set(tiles.map(p => p.join(',')));
    g.fillStyle = 'rgba(255,140,40,.28)'; g.strokeStyle = 'rgba(255,140,40,.9)'; g.lineWidth = 1;
    for (const [x, y] of tiles) { g.fillRect(x * T + .5, y * T + .5, T - 1, T - 1); }
    for (const c of b.combatants) {
      if (!c.pos || c.id === me.id && area.origin === 'caster' || c.untargetable) continue;   // (banished, ethereal: out of the area's reach)
      for (let i = 0; i < c.span; i++) for (let j = 0; j < c.span; j++) if (set.has(`${c.pos[0] + i},${c.pos[1] + j}`) && !a.hit.includes(c.id)) a.hit.push(c.id);
    }
  } else if (UI.hover && (t.type === 'creature' || t.type === 'split')) {
    const tok = tokenAt(UI.hover);
    if (tok && !tok.untargetable) a.hit = [tok.id];
  } else if (UI.hover && t.type === 'point') {
    const x = Math.floor(UI.hover[0]), y = Math.floor(UI.hover[1]);
    g.strokeStyle = '#ff8c28'; g.lineWidth = 2; g.strokeRect(x * T + 2, y * T + 2, T - 4, T - 4);
  }
  const hk = a.hit.join(',');                                // who would be hit changed: the aim bar lists them
  if (hk !== a.hitKey) { a.hitKey = hk; requestAnimationFrame(() => { if (UI.aim === a) keepFocus($('aimbar'), renderAimbar); }); }
}

// ---------------------------------------------------------------- the action bar: what my character can do now
const COST_CLASS = { action: 'action', attack: 'action', multi: 'action', bonus: 'bonus', reaction: 'reaction', free: 'free', long: 'action', on_hit: 'spell' };
const MODES = ['ask', 'always', 'never'];
function renderActions() {
  const el = $('actionbar'), b = ST.battle, a = b && b.actions;
  if (!a) { el.classList.add('hide'); return; }
  el.classList.remove('hide');
  const t = a.turn, kids = [];
  const res = (cls, n, label, about) => h('span', { class: `res ${cls}${n > 0 ? '' : ' used'}`, 'aria-label': label,
    tip: `${label}: ${n > 0 ? S('ready') : S('used this turn')}\n${about}` },
    h('i'), h('span', { class: 'lbl' }, label));             // (on phones the dot alone: its word on hold)
  const left = Math.min(t.move, a.speed);                   // (speed 0 mid-turn: nothing left)
  const econ = [res('action', t.action, S('Action'), S('One a turn: attack, cast a spell, Dash, Dodge, Disengage, Help, Hide... The green-edged buttons use it.')),
    res('bonus', t.bonus, S('Bonus action'), S('One a turn, only for things that say so: an off-hand attack, some spells and class features. The yellow-edged buttons use it.')),
    res('reaction', t.reaction, S('Reaction'), S("One a round, even on others' turns: an opportunity attack, Shield... It comes back at the start of your turn.")),
    h('span', { class: 'res move' + (left > 0 ? '' : ' used'), tip: `${S('Movement')}: ${S('{0} of {1} ft left', left, a.speed)}\n${S('On your turn, click a square on the map to walk there; you can split it up between actions. Dash doubles it.')}` },
      `🦶 ${left}/${a.speed} ${S('ft')}`)];
  const me = (typeof bgMe === 'function' && bgMe()) || ST.character, ds = me && me.death_saves;   // (on a lobby's map: my fighter)
  if (me && me.current_hp <= 0 && ds && ds.success < 3 && ds.failure < 3)    // dying: the save right here (the map view on a phone too)
    econ.push(needs('roll', btn(`🎲 ${S('Death save')}  ✔ ${pips(ds.success, 3)} ✘ ${pips(ds.failure, 3)}`, () => act('death_save'), 'sm danger',
      S('Roll a death saving throw') + '\n' + S('10 or more is a success, under 10 a failure; a 20 brings you back with 1 HP. Three successes: stable. Three failures: dead.'))));
  for (const g of a.spells) if (g.level > 0 && g.slots && g.slots.total) econ.push(h('span', { class: 'res slot' + (g.slots.left ? '' : ' used'),
    tip: S('Level {0} spell slots: {1} of {2} left', g.level, g.slots.left, g.slots.total), 'aria-label': S('Level {0} spell slots: {1} of {2} left', g.level, g.slots.left, g.slots.total) },
    h('small', null, g.level), h('span', { class: 'pips' }, pips(g.slots.left, g.slots.total))));
  if (t.attacks) econ.push(h('span', { class: 'acc', tip: S('{0} more attack(s)', t.attacks) + '\n' + S('Extra Attack: your Attack action has more swings left this turn - attack again without spending anything.') },
    S('{0} more attack(s)', t.attacks)));
  if (t.legendary_max) econ.push(h('span', { class: 'res', tip: S('Legendary actions: {0} of {1} left', t.legendary, t.legendary_max) + '\n' + S('Used at the end of the others\' turns; they come back at the start of yours.') },
    `★ ${t.legendary}/${t.legendary_max}`));
  if (a.concentrating) econ.push(h('span', { class: 'warn', tip: S('Concentrating on {0}', a.concentrating) + '\n' + S('Taking damage asks for a Constitution save to keep it; casting another concentration spell ends it.') },
    '◎ ' + a.concentrating));
  if (!a.economy && a.in_combat) econ.push(h('span', { class: 'dim small' }, S('(the DM turned the action economy off)')));
  econ.push(h('span', { class: 'grow' }), advSeg(), !a.in_combat ? h('b', { class: 'good' }, S('Out of combat: any action, any time'))
    : a.is_turn ? h('b', { class: 'good' }, S('Your turn')) : h('span', { class: 'dim small' }, S('Not your turn: reactions only')));
  kids.push(h('div', { class: 'econ' }, ...econ));
  const COST_WORD = { action: S('Action'), attack: S('Action'), multi: S('Action'), bonus: S('Bonus action'), reaction: S('Reaction'),
    free: S('Free'), legendary: S('Legendary action'), long: S('Takes longer than a turn'), on_hit: S('On hit') };
  const button = it => h('button', { class: `act ico ${!it.ok ? 'off' : it.kind === 'spell' ? 'spell' : COST_CLASS[(it.cost || '').split(':')[0]] || 'action'}${UI.aim && UI.aim.item.id === it.id ? ' aiming' : ''}${it.readied ? ' readied' : ''}${!it.icon || NOICON.has(it.icon) ? ' txt' : ''}`,
    onclick: () => startAim(it), 'aria-label': it.label, 'aria-disabled': it.ok ? null : 'true', tip: () => actionCard(it),
    more: () => [it.ok ? [it.kind === 'spell' ? S('Cast') : S('Use'), () => startAim(it)] : null] },
    iconOr(it.icon, 30, it.label, 'sync'),   // (no lazy: the bar is redrawn often - no blink)
    it.uses != null && it.uses !== '' ? h('span', { class: 'uses' }, it.uses) : null);
  const strip = [];                       // every group in one wrapping strip, a thin bar in its cost colour first (its name on hover)
  UI.hotkeys = a.groups.filter(g => g.key !== 'reaction').flatMap(g => g.items).slice(0, 9);   // keys 1-9, in the strip's order
  const divider = (title, cls) => h('span', { class: 'gdiv ' + cls, tip: title, 'aria-label': title, role: 'separator' });
  const flip = k => () => { tip(); flipFold(k, renderActions); };
  const grip = (g, cls) => {             // a group's bar folds it away; folded, it shows ▸ and how many it holds
    const k = 'bar:' + g.key, shut = folded(k), words = `${g.title}\n${shut ? S('Folded: click to unfold') : S('Click to fold away')}`;
    return h('button', { class: 'gdiv fold ' + cls + (shut ? ' shut' : ''), tip: words, 'aria-label': g.title, 'aria-expanded': String(!shut), onclick: flip(k) },
      shut ? `▸${g.items.length}` : null);
  };
  for (const g of a.groups) {
    if (g.key === 'reaction') continue;
    strip.push(grip(g, COST_CLASS[g.key] || 'free'), ...(folded('bar:' + g.key) ? [] : g.items.map(button)));
  }
  const open = UI.spellsOpen;
  if (a.spells.length) strip.push(divider(S('Spells'), 'spell'), ibtn('spell-book', open ? S('Hide spells') : S('Show spells'),
    () => { UI.spellsOpen = !open; store('spells', UI.spellsOpen); renderActions(); }, 'act ico spell' + (open ? ' on' : '')));
  if (strip.length) kids.push(h('div', { class: 'row strip' }, ...strip));
  if (a.spells.length && open) {            // one strip too: a level tag (its slots on hover) before each level's spells
    const tag = g => { const k = 'barspells:' + g.level, shut = folded(k), n = g.level ? String(g.level) : '◌';
      const words = g.title + (g.slots ? `\n${S('Level {0} spell slots: {1} of {2} left', g.level, g.slots.left, g.slots.total)}` : '')
        + `\n${shut ? S('Folded: click to unfold') : S('Click to fold away')}`;
      return h('button', { class: 'lvtag fold' + (g.slots && !g.slots.left ? ' used' : '') + (shut ? ' shut' : ''), tip: words, 'aria-label': words,
        'aria-expanded': String(!shut), onclick: flip(k) }, shut ? `${n}▸${g.items.length}` : n); };
    kids.push(h('div', { class: 'row strip spellstrip' }, ...a.spells.flatMap(g => [tag(g), ...(folded('barspells:' + g.level) ? [] : g.items.map(button))])));
  }
  if ((a.toggles || []).length) kids.push(h('div', { class: 'row' }, h('span', { class: 'title' }, S('Feats')), ...toggleChips(a.toggles, true)));
  if (a.reactions.length) {                 // a picture per reaction, its setting as a corner mark: ? ask, ✓ always, ✕ never
    const MARK = { ask: '?', always: '✓', never: '✕' }, WORD = { ask: S('Ask'), always: S('Always'), never: S('Never') };
    const help = S('Ask: you are asked each time · Always: it happens by itself · Never: it is skipped');
    kids.push(h('div', { class: 'row reacts' }, divider(S('Reactions'), 'reaction'), ...a.reactions.map(r => {
      const next = MODES[(MODES.indexOf(r.mode) + 1) % 3], words = `${r.label}: ${WORD[r.mode]}\n${S('Click: {0}', WORD[next])}\n\n${help}`;
      return h('button', { class: 'rmode ' + r.mode, tip: words, 'aria-label': `${r.label}: ${WORD[r.mode]}`,
        onclick: () => act('reaction_mode', { family: r.family, mode: next }, true) },
        r.icon ? gi(r.icon) : h('span', null, r.label), h('span', { class: 'mk' }, MARK[r.mode]));
    })));
  }
  el.replaceChildren(...kids);
}

/** The hover card of an action: icon, name and cost, then the generic facts, the roll, a short summary, why not. */
const COST_LOOK = () => ({ action: [S('Action'), 'var(--good)'], attack: [S('Action'), 'var(--good)'], multi: [S('Action'), 'var(--good)'],
  bonus: [S('Bonus action'), 'var(--warn)'], reaction: [S('Reaction'), '#c084fc'], free: [S('Free'), 'var(--dim)'],
  legendary: [S('Legendary action'), '#f472b6'], long: [S('Takes longer than a turn'), 'var(--bad)'], on_hit: [S('On hit'), '#c084fc'] });
function actionCard(it) {
  const info = it.info || {}, kind = (it.cost || '').split(':')[0], [cost, color] = COST_LOOK()[kind] || [it.cost, 'var(--dim)'];
  return h('div', null,
    h('div', { class: 'tc-head' }, iconOr(it.icon, 22, null),
      h('b', null, it.label), h('span', { class: 'grow' }),
      h('span', { style: `color:${it.kind === 'spell' ? '#c084fc' : color}` }, cost), it.uses != null && it.uses !== '' ? h('span', { class: 'dim' }, ' · ' + it.uses) : null),
    (info.tags || []).length ? h('div', { class: 'tc-tags' }, info.tags.join(' · ')) : null,
    info.roll ? h('div', { class: 'tc-roll' }, info.roll) : null,
    info.text ? h('div', { class: 'tc-text' }, info.text) : null,
    kind === 'on_hit' ? h('div', { class: 'tc-ready' }, it.readied ? S('Readied: the next hit asks whether to cast it (the slot is spent then). Click again to let it go.')
      : S('Click to ready it: nothing is spent until a hit lands and you choose to cast it.')) : null,
    it.why ? h('div', { class: 'tc-why' }, '⛔ ' + it.why) : null,
    !touch() && (UI.hotkeys || []).some(x => x.id === it.id) ? h('div', { class: 'tc-key' }, S('Key {0}', (UI.hotkeys || []).findIndex(x => x.id === it.id) + 1)) : null);
}

/** A reaction choice's rules on hover: the feature, maneuver or spell of that name on my sheet ('maneuver:Disarming Attack'). */
function rulesOf(o) {
  const c = ST.character, key = o.key || '', label = (o.label || '').replace(/\s*\(.*$/, '');
  if (!c) return {};                                   // 'maneuver:Disarming Attack', 'shield' / "Cast Shield (+5 AC)", "Lucky: make it reroll"...
  const bare = label.replace(/^(Cast|Use)\s+/i, '');
  const names = [key.includes(':') ? key.split(':').slice(1).join(':') : key, label, bare, bare.split(/[:,]/)[0]]
    .filter(Boolean).map(n => n.trim().toLowerCase());
  for (const g of c.features || []) for (const f of g.items) if (names.includes(f.name.toLowerCase())) return { tip: `${f.label}\n${f.text}` };
  for (const g of c.spells || []) for (const s of g.spells) if (names.includes(s.name.toLowerCase()))
    return { tip: `${s.label}\n${s.time} · ${s.range}\n\n${s.text}`, icon: s.icon };
  return {};
}
/** A reaction the battle is waiting on: mine to answer (Shield? Counterspell? an opportunity attack?). */
function renderPending() {
  const p = ST.battle && ST.battle.pending, el = $('react');
  if (!p || !p.mine) { el.classList.add('hide'); UI.reactKey = null; return; }
  const fresh = UI.reactShown !== p.rid;
  if (fresh) { UI.reactShown = p.rid; UI.reactRemember = false; UI.reactBusy = false; }
  const key = JSON.stringify([p, UI.reactBusy, wordsLang]);
  if (!fresh && key === UI.reactKey && !el.classList.contains('hide')) return;     // unchanged: keep focus and the tick
  UI.reactKey = key;
  el.classList.remove('hide');
  const family = o => (o.key || '').split(':')[0];
  const answer = async (o) => {
    if (UI.reactBusy) return;                                // one answer only (a double tap would send two)
    UI.reactBusy = true;
    el.querySelectorAll('.opts button, .opts select').forEach(b => { b.disabled = true; });
    if (UI.reactRemember) await act('reaction_mode', { character: p.character, family: family(o || p.options[0]), mode: o ? 'always' : 'never' }, true);
    const r = await act('react', { rid: p.rid, choice: o ? o.key : null, character: p.character });
    if (!r) { UI.reactBusy = false; UI.reactKey = null; renderPending(); }
  };
  const remember = h('label', { class: 'small dim' }, h('input', { type: 'checkbox', checked: !!UI.reactRemember, onchange: e => { UI.reactRemember = e.target.checked; } }),
    ' ' + S("Don't ask me again for this (do what I pick from now on)"));
  el.replaceChildren(h('div', { class: 'box', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'reacttitle', 'aria-describedby': 'reacttext' },
    h('div', { class: 'title', id: 'reacttitle' }, '⚡ ' + S('Reaction') + ' · ' + p.reactor_name),
    h('div', { class: 'big', id: 'reacttext' }, p.text),
    h('div', { class: 'opts' }, ...p.options.map((o, i) => {
      if (o.group) {                                       // a smite's slot levels: one button and a level dropdown
        if (p.options.findIndex(x => x.group === o.group) !== i) return null;
        const levels = p.options.filter(x => x.group === o.group), r = rulesOf({ key: o.key, label: o.group });
        const pick = h('select', { 'aria-label': o.group, disabled: !!UI.reactBusy }, ...levels.map(x => h('option', { value: x.key }, x.choice)));
        return h('div', { class: 'levels' },
          h('button', { class: 'primary grow', onclick: () => answer(levels.find(x => x.key === pick.value) || o), disabled: !!UI.reactBusy, tip: r.tip || null },
            r.icon ? gi(r.icon) : null, h('b', null, o.group)), pick);
      }
      const r = rulesOf(o);
      return h('button', { class: 'primary', onclick: () => answer(o), disabled: !!UI.reactBusy, tip: r.tip || null },
        r.icon ? gi(r.icon) : null, h('b', null, o.label), o.detail ? h('span', { class: 'dim small' }, '  ' + o.detail) : null); }),
      h('button', { onclick: () => answer(null), disabled: !!UI.reactBusy }, S("Don't react"))),
    remember,
    h('div', { class: 'small dim' }, S('The battle waits for your answer.'))));
  if (fresh) { const first = el.querySelector('.opts button'); if (first) first.focus({ preventScroll: true }); }
}

// ---------------------------------------------------------------- the character sheet
const TABS = () => [['overview', S('Overview')], ['spells', S('Spells')], ['inventory', S('Inventory')], ['features', S('Features')], ['notes', S('Notes')], ['teamnotes', S('Team notes')]];
function renderSheet() {
  const c = ST.character, el = $('sheet');
  if (!c) { el.replaceChildren(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Your characters')),
    typeof bgApp === 'function' && bgApp() && !bgMember() ? S('Join a lobby to get a hero: it shows here.')      // (the Battlegrounds app)
    : typeof bgMember === 'function' && bgMember() ? S('Battlegrounds: your hero shows here once you have one.')     // (a member's sheet is their lobby hero's)
    : ST.me.characters.length ? S('Choose a character') : S('Ask your DM to give you a character.'))); return; }
  const pct = c.max_hp ? Math.max(0, Math.min(100, 100 * c.current_hp / c.max_hp)) : 0;
  const amount = h('input', { type: 'number', min: 0, placeholder: S('amt'), value: UI.amount, oninput: e => { UI.amount = e.target.value; } });
  const hp = kind => {
    const n = parseInt(amount.value, 10);
    if (!(n >= 0)) return say(S('Enter the amount first.'), true);
    UI.amount = ''; amount.value = '';                       // cleared at once: a second tap can't send it again
    return act('hp', { kind, amount: n }, true);
  };
  amount.setAttribute('aria-label', S('Hit points'));
  amount.setAttribute('inputmode', 'numeric');
  const head = [
    h('div', { class: 'head' }, h('span', { class: 'nm' }, c.name), h('span', { class: 'dim line', tip: c.line }, c.line), h('span', { class: 'grow' }), advSeg()),
    h('div', { class: 'hp' }, h('span', { class: 'big' }, `${S('HP')} ${c.current_hp}/${c.max_hp}`), c.temp_hp ? h('span', { class: 'acc' }, `+${c.temp_hp}`) : null,
      needs('edit_hp', amount), needs('edit_hp', ibtn('damage', S('Damage: take the amount off your hit points'), () => hp('damage'), 'bad')),
      needs('edit_hp', ibtn('heal', S('Heal the amount'), () => hp('heal'), 'good')),
      needs('edit_hp', ibtn('temp_hp', S('Set temporary hit points (they don\'t stack: the larger pool stays)'), () => hp('temp'), 'cyan')),
      h('span', { class: 'grow' }),
      ...Object.entries(c.hit_dice).map(([cls, hd]) => needs('rest', ibtn('hit_die', `${S('Spend a hit die')} (d${hd.die})\n${S('{0} of {1} left', hd.total - hd.used, hd.total)}`,
        () => hd.total - hd.used > 0 ? ask(S('Spend a d{0} hit die to heal?', hd.die), S('Spend a hit die'), () => act('hit_die', { cls })) : null,
        hd.total - hd.used ? '' : 'off', null, `d${hd.die} ${hd.total - hd.used}/${hd.total}`))),
      needs('rest', ibtn('short_rest', `${S('Short rest')}\n${S('Recover the features that come back on a short rest; spend hit dice to heal.')}`,
        () => ask(S('Take a short rest? (Agree it with your DM first.)'), S('Short rest'), () => act('rest', { kind: 'short' })), 'warn')),
      needs('rest', ibtn('long_rest', `${S('Long rest')}\n${S('Restore HP, spell slots, hit dice and features.')}`,
        () => longRest(), 'acc'))),
    h('div', { class: 'hpbar' }, h('div', { style: `width:${pct}%;background:${pct > 50 ? '#4ade80' : pct > 25 ? '#fbbf24' : '#f87171'}` })),
  ];
  const idf = c.identify || {};
  if (idf.pending > 0) {                             // an Identify spell was cast: which item does it look at?
    head.push(h('div', { class: 'card warn' }, h('div', { class: 'title' }, '🔍 ' + S('Identify')),
      h('div', { class: 'dim small' }, idf.options.length ? S('Choose the item your Identify spell looks at.') : S('None of your items is unidentified.')),
      h('div', { class: 'row', style: 'flex-wrap:wrap;gap:6px;margin-top:6px' },
        ...idf.options.map(o => btn('🔍 ' + o.label, () => act('identify', { item: o.name }), 'sm primary', S('Identify it'))),
        btn(S('Not an item'), () => act('identify_cancel', {}, true), 'sm', S('The spell looked at something else (a creature, an item the DM tells you about)')))));
  }
  if (longOptions(UI.aim)) head.push(optionCard(UI.aim));  // aiming something with many choices: its boxes, until it is used
  if (c.current_hp <= 0) {
    const s = c.death_saves;
    head.push(h('div', { class: 'card warn' }, h('div', { class: 'title' }, S('Death saves')),
      `✔ ${pips(s.success, 3)}   ✘ ${pips(s.failure, 3)}  `, needs('roll', btn('🎲 ' + S('Roll'), () => act('death_save'), 'sm primary'))));
  }
  const tabs = h('div', { class: 'tabs' }, ...TABS().filter(([k]) => k !== 'teamnotes' || (may('team_notes') && !(typeof bgApp === 'function' && bgApp()))).map(([k, l]) => h('button', { class: UI.tab === k ? 'on' : '', onclick: () => { UI.tab = k; store('tab', k); renderSheet(); } }, l)));
  const body = { overview: overviewTab, spells: spellsTab, inventory: inventoryTab, features: featuresTab, notes: notesTab, teamnotes: teamNotesTab }[UI.tab](c);
  el.replaceChildren(...head, tabs, ...body);
  el.querySelectorAll('textarea').forEach(fitText);
}
/** A note or detail box as tall as its text (one line while empty, up to ~12 lines, then it scrolls). */
function fitText(t) { if (!t.offsetParent) return; t.rows = 1; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight + 2, 260) + 'px'; }
document.addEventListener('input', e => { if (e.target.tagName === 'TEXTAREA' && e.target.closest('#sheet')) fitText(e.target); });

function overviewTab(c) {
  const out = [];
  out.push(h('div', { class: 'tiles' }, ...c.vitals.map(v => h('div', { class: 'tile', tip: v.tip }, h('b', null, v.value), h('span', null, v.label)))));
  const look = badgeLook();                          // conditions as their pictures and names, the rules on hover
  const flags = [...(c.condition_info || []).map(x => h('span', { class: 'cond', style: `color:${(look[x.name] || [])[1] || 'var(--warn)'}`, tip: `${x.label}\n${x.text}` },
      gi(x.name), x.label)),
    c.exhaustion ? h('span', { class: 'cond warn', tip: S('Exhaustion {0}', c.exhaustion) }, gi('exhaustion'), S('Exhaustion {0}', c.exhaustion)) : null,
    c.inspiration ? h('span', { class: 'cond warn', tip: S('Inspiration') }, gi('inspiration'), S('Inspiration')) : null,
    c.next_xp ? h('span', { class: 'dim small' }, `${c.xp} XP · ${S('next level at {0}', c.next_xp)}`) : null].filter(Boolean);
  if (flags.length) out.push(h('div', { class: 'conds', style: 'margin-top:4px' }, ...flags));
  const roll = (label, fn) => [label, fn];
  out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Abilities')),      // the check and the save: two separate taps
    h('div', { class: 'tiles' }, ...c.abilities.map(a => h('div', { class: 'tile ab' },
      h('div', { class: 'chk', onclick: go(() => act('check', { what: a.name })), 'aria-label': S('Roll a {0} check', a.label),
        tip: `${a.tip}\n\n${S('Click: roll a {0} check', a.label)}`,
        more: () => [roll(S('Roll a {0} check', a.label), () => act('check', { what: a.name })), roll(S('Roll the saving throw'), () => act('save', { ability: a.key }))] },
        h('b', null, sign(a.mod)), h('span', null, `${a.label} ${a.score}`)),
      h('button', { onclick: go(() => act('save', { ability: a.key })), class: 'sv' + (a.save_prof ? ' on' : ''),
        tip: `${a.save_tip}\n\n${S('Click: roll the saving throw')}`, more: () => [roll(S('Roll the saving throw'), () => act('save', { ability: a.key }))] },
        S('Save {0}', sign(a.save))))))));
  out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Skills')), h('div', { class: 'cols skills' }, ...c.skills.map(s =>
    h('div', { class: 'li click', onclick: go(() => act('check', { what: s.name })), tip: s.tip, more: () => [roll(S('Roll'), () => act('check', { what: s.name }))] },
      h('span', { class: s.prof ? 'acc' : 'dim' }, s.prof ? '●' : '○'),
      h('span', { class: 'n' }, s.label), h('span', { class: 'dim small' }, s.ability), h('b', null, sign(s.bonus)))))));
  out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Attacks')), ...c.attacks.map(a =>
    h('div', { class: 'li atk', tip: a.tip ? `${a.label}\n${a.tip}` : null }, a.icon ? gi(a.icon, 'sm ii') : null, h('span', { class: 'n' }, a.label), h('span', { class: 'dim small' }, `${sign(a.attack)} · ${a.damage}`),
      may('roll') || (ST.battle.my_turn && may('battle_actions')) ? btn(S('Attack'), () => act('attack', { weapon: a.name }), 'sm primary', ST.battle.my_turn ? S('Attacks your target in the battle') : null) : null,
      needs('roll', ibtn('rolling-dices', S('Roll damage'), () => act('damage', { weapon: a.name }), 'sm')),          // pictures: room for the weapon's name
      needs('roll', ibtn('bright-explosion', S('Roll critical damage'), () => act('damage', { weapon: a.name, crit: true }), 'sm warn'))))));
  if ((c.toggles || []).length) out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Combat options')),
    h('div', { class: 'chips' }, ...toggleChips(c.toggles))));
  if (c.resources.length) out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Resources')), ...c.resources.map(r => {
    const use = () => act('resource', { resource: r.name, use: true }, true), back = () => act('resource', { resource: r.name, use: false }, true);
    const left = r.max ? r.max - r.used : null, short = r.recharge === 'short';
    const rest = h('span', { class: short ? 'warn' : 'acc', tip: short ? S('Comes back on a short rest') : S('Comes back on a long rest') }, gi(short ? 'short_rest' : 'long_rest', 'sm'));
    const count = r.max && r.max <= 10                 // a pip per use: a full one uses it, an empty one gets it back
      ? Array.from({ length: r.max }, (_, i) => h('button', { class: 'pip' + (i < left ? ' on' : ''), onclick: go(i < left ? use : back),
        tip: `${r.label}: ${S('{0} of {1} left', left, r.max)}\n${i < left ? S('Click to use one') : S('Click to get one back')}`,
        'aria-label': i < left ? S('Use one') : S('Get one back') }, i < left ? '●' : '○'))
      : [h('span', { class: 'pips' }, r.max ? `${left}/${r.max}` : '∞'), btn('−', use, 'sm', S('Use one')), btn('+', back, 'sm', S('Get one back'))];
    return h('div', { class: 'li' }, h('span', { class: 'n' }, r.label), rest, ...count);
  })));
  if (c.defense.length) out.push(h('div', { class: 'small warn' }, c.defense.join(' ')));
  out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Proficiencies')), ...c.proficiencies.filter(g => g.items.length).map(g =>
    h('div', { class: 'small' }, h('span', { class: 'dim' }, g.title + ': '), g.items.join(', ')))));
  out.push(needs('roll', h('div', { class: 'row' }, btn('⚡ ' + S('Roll initiative'), () => act('initiative'), 'sm primary'))));
  return out;
}

/** Situational feats as switches: Great Weapon Master's −5 / +10, Sentinel, Lucky... (hover: what they do). */
const TOGGLE_HELP = () => ({ power: S('Click to turn it on for your attacks.'), auto: S('On: the battle applies it by itself.'),
  reaction: S('On: it is offered when it applies.'), option: S('Pick the damage type.') });
/** An action's picture - or, when there is none (no picture module installed: an icon the server can't find), its
 * words instead of a broken image. A picture that failed once isn't asked for again. */
const NOICON = new Set();
function iconOr(icon, px, label, decoding) {
  if (!icon || NOICON.has(icon)) return label;
  return h('img', { src: `/icon/${icon}.webp`, alt: '', width: px, height: px, decoding: decoding || 'async',
    onerror: e => { NOICON.add(icon); const b = e.target.closest('button.act'); if (b) b.classList.add('txt');
      e.target.replaceWith(label == null ? '' : label); } });
}
function toggleChips(list, bar) {            // bar: the action bar's (on a lobby's map: the fighter's, battlegrounds.js)
  const more = bar ? { bar: 1 } : {};
  return list.map(t => {
    const tipText = `${t.feat_label || t.feat}\n${t.does}\n\n${TOGGLE_HELP()[t.kind]}` + (t.text ? `\n\n${t.text}` : '');
    if (t.kind === 'option') return h('select', { class: 'toggle', tip: tipText, onchange: e => act('toggle', { key: t.key, value: e.target.value || false, ...more }, true) },
      h('option', { value: '' }, S('{0}: off', t.label)), ...t.options.map(o => h('option', { value: o, selected: o === t.on }, `${t.label}: ${S(o)}`)));
    return h('span', { class: `chip toggle ${t.kind}${t.on ? ' on' : ''}`, tip: tipText, onclick: () => act('toggle', { key: t.key, value: !t.on, ...more }, true) },
      (t.on ? '● ' : '○ ') + t.label);
  });
}

/** The long rest: a class that prepares its spells (Cleric, Druid, Paladin, Artificer, Wizard from the spellbook) picks
 *  them for the new day, in a fold per spell level, counting what is chosen against what it may prepare. */
async function longRest() {
  const plain = () => ask(S('Take a long rest? Hit points, slots and resources come back. (Agree it with your DM first.)'), S('Long rest'), () => act('rest', { kind: 'long' }));
  let r;
  try { r = await api('/api/act', { action: 'prepare_options', character: ST.me.active }); }
  catch (e) { if (e.message !== 'login') say(e.message, true); return null; }
  const classes = (r.data && r.data.classes) || [];
  if (!classes.some(k => k.prepares)) return plain();
  const picks = Object.fromEntries(classes.filter(k => k.prepares).map(k => [k.class, new Set(k.prepared)]));
  const counters = [];                                       // run after every change: the counts and the rest button
  const recount = () => {
    counters.forEach(f => f());
    const over = classes.some(k => k.prepares && picks[k.class].size > k.limit);
    const ok = $('detail').querySelector('.row button');
    if (ok) ok.disabled = over;
  };
  const query = h('input', { type: 'search', placeholder: S('Find a spell'), 'aria-label': S('Find a spell'), oninput: () => {
    const q = query.value.trim().toLowerCase();
    $('detail').querySelectorAll('.prep details').forEach(d => {
      let any = false;
      d.querySelectorAll('.prow').forEach(row => { const hit = !q || row.dataset.name.includes(q); row.classList.toggle('hide', !hit); any = any || hit; });
      d.classList.toggle('hide', !any);
      d.open = q ? any : d.dataset.open === '1';
    });
  } });
  const block = k => {
    if (!k.prepares) return h('div', { class: 'small dim' }, S('{0}: you know your spells - they change when you level up ({1} known).', k.label, k.known));
    const sel = picks[k.class], always = new Set(k.always), boxes = [];
    const total = h('span', { class: 'pct' });
    counters.push(() => {
      total.textContent = S('{0} of {1} prepared', sel.size, k.limit) + (always.size ? ' · ' + S('+{0} always', always.size) : '');
      total.classList.toggle('bad', sel.size > k.limit); total.classList.toggle('good', sel.size === k.limit);
      boxes.forEach(([b, n]) => { if (!always.has(n)) b.checked = sel.has(n); });
    });
    const head = h('div', { class: 'ph' }, h('b', null, k.label), k.spellbook ? h('span', { class: 'dim small' }, S('from your spellbook')) : null,
      h('span', { class: 'grow' }), total,
      btn(S('Reset'), () => { sel.clear(); k.prepared.forEach(n => sel.add(n)); recount(); }, 'sm flat'),        // (no tips: holding one would close the sheet)
      btn(S('Clear'), () => { sel.clear(); recount(); }, 'sm flat'));
    if (!k.levels.length) return h('div', { class: 'pcls' }, head, h('div', { class: 'dim small' }, k.spellbook ? S('Your spellbook is empty.') : S('No spells to prepare.')));
    const one = k.levels.length === 1;
    const groups = k.levels.map(g => {
      const cnt = h('span', { class: 'dim small' });
      counters.push(() => {
        const n = g.spells.filter(sp => sel.has(sp.name)).length, a = g.spells.filter(sp => always.has(sp.name)).length;
        cnt.textContent = S('{0} of {1}', n, g.spells.length - a) + (a ? ' · ' + S('+{0} always', a) : '');
        cnt.classList.toggle('acc', n > 0);
      });
      const rows = g.spells.map(sp => {
        const fixed = always.has(sp.name);
        const box = h('input', { type: 'checkbox', checked: fixed || sel.has(sp.name), disabled: fixed, onchange: () => {
          if (box.checked && sel.size >= k.limit) { box.checked = false; say(S('{0} can prepare {1} spells - unprepare one first.', k.label, k.limit), true); return; }
          sel[box.checked ? 'add' : 'delete'](sp.name); recount();
        } });
        boxes.push([box, sp.name]);
        const text = h('div', { class: 'ptxt hide' }, `${sp.school} · ${sp.time} · ${sp.range}${sp.conc ? ' · ' + S('Concentration') : ''}\n\n${sp.text}`);
        const info = mini('ⓘ', () => { text.classList.toggle('hide'); return null; }, 'flat');
        info.setAttribute('aria-label', S('Spell text'));
        const row = h('div', { class: 'prow' + (fixed ? ' fixed' : '') },
          h('label', null, box, sp.icon ? gi(sp.icon, 'sm spi') : null, h('span', { class: 'n' }, sp.label), sp.ritual ? h('span', { class: 'dim small' }, ' ®') : null,
            sp.conc ? h('span', { class: 'dim small' }, ' Ⓒ') : null, fixed ? h('span', { class: 'tag' }, S('always')) : null),
          info, text);
        row.dataset.name = sp.label.toLowerCase() + ' ' + sp.name.toLowerCase();
        return row;
      });
      const d = h('details', { open: one || null }, h('summary', null, h('span', null, g.title), h('span', { class: 'grow' }), cnt), ...rows);
      d.dataset.open = one ? '1' : '0';
      d.addEventListener('toggle', () => { if (!query.value) d.dataset.open = d.open ? '1' : '0'; });
      return d;
    });
    return h('div', { class: 'pcls' }, head, ...groups);
  };
  const many = classes.reduce((n, k) => n + (k.levels || []).reduce((m, g) => m + g.spells.length, 0), 0);
  detail(() => h('div', { class: 'prep' },
    h('div', { class: 'txt' }, h('b', null, S('Long rest')), '\n' + S('Hit points, slots and resources come back, and you prepare your spells for the new day. (Agree it with your DM first.)')),
    many > 12 ? query : null, ...classes.map(block)),
  () => [[S('Long rest'), () => act('rest', { kind: 'long', prepare: Object.fromEntries(Object.entries(picks).map(([cls, set]) => [cls, [...set]])) })],
    [S('Cancel'), () => null, 'flat']]);
  $('detail').querySelector('.box').classList.add('wide');
  recount();
  return null;
}
function spellsTab(c) {
  if (!c.spells.length) return [h('div', { class: 'dim' }, S('No spells.'))];
  const out = [];
  const slot = c.slots.length ? h('select', { onchange: e => { UI.slot = e.target.value; }, tip: S('Which slot a levelled spell uses') },
    h('option', { value: '' }, S('Lowest slot that works')),
    ...c.slots.map(s => h('option', { value: s.key, selected: UI.slot === s.key }, `${s.label} (${s.left}/${s.total})`))) : null;
  const how = touch() ? S('Tap a spell to cast it (a levelled spell asks first, and offers the ritual ®); hold it for its text.')
    : S('Click a spell to cast it (a levelled spell asks first, and offers the ritual ®); right-click casts a ritual without a slot.');
  out.push(h('div', { class: 'row casting' }, h('span', { class: 'small dim' }, (c.casting || []).map(k =>
    `${k.label}: ${S('save DC {0}', k.dc)} · ${S('attack {0}', sign(k.attack))}`).join('   ')),
    h('span', { class: 'small dim info', tip: how, 'aria-label': how, onclick: () => detail(how) }, 'ⓘ'), h('span', { class: 'grow' }), slot));   // the how-to on hover (hold)
  const pipsOf = s => [...Array.from({ length: s.total }, (_, i) => h('button', { class: 'pip' + (i < s.left ? ' on' : ''),   // a full pip spends a slot, an empty one gets it back
      onclick: go(() => act('slot', { key: s.key, use: i < s.left }, true)), 'aria-label': i < s.left ? S('Spend a slot') : S('Get a slot back'),
      tip: `${s.label}: ${S('{0} of {1} left', s.left, s.total)}\n${i < s.left ? S('Click to use one') : S('Click to get one back')}` }, i < s.left ? '●' : '○')),
    h('span', { class: 'dim small' }, `${s.left}/${s.total}`)];
  const own = new Set(c.spells.map(g => String(g.level)));         // slots go on their level's title; the others (pact) get a line
  const loose = c.slots.filter(s => !own.has(String(s.key)));
  if (loose.length) out.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Spell slots')),
    ...loose.map(s => h('div', { class: 'li' }, h('span', { class: 'n' }, s.label), ...pipsOf(s)))));
  for (const g of c.spells) {
    const mine = c.slots.find(s => String(s.key) === String(g.level)), k = 'spells:' + g.level;   // each level folds under its title
    out.push(h('div', { class: 'card' + (folded(k) ? ' shut' : '') }, h('div', { class: 'title lvl' }, foldHead(k, g.title, g.spells.length, renderSheet),
      mine ? h('span', { class: 'grow' }) : null, ...(mine ? pipsOf(mine) : [])),
      folded(k) ? null : h('div', { class: 'chips' }, ...g.spells.map(sp => h('span', { class: 'chip', tip: `${sp.label}\n${sp.time} · ${sp.range}\n\n${sp.text}`,
        more: () => spellButtons(c, sp, g.level),
        onclick: go(() => castChip(c, sp, g.level)),
        oncontextmenu: e => { if (sp.ritual && lastPointer === 'mouse') { e.preventDefault(); act('cast', { spell: sp.name, ritual: true }); } } },
        sp.icon ? gi(sp.icon, 'sm spi') : null, sp.label + (sp.ritual ? ' ®' : ''))))));
  }
  return out;
}
/** A spell chip: in a battle, aim it on the map (BG3 style); a cantrip at once; a levelled spell asks before the slot goes. */
function castChip(c, sp, level) {
  const it = battleSpell(sp.name);
  if (it) {
    showView('map'); startAim(it);
    if (UI.aim && UI.slot && UI.slot !== 'pact') { UI.aim.slot = UI.slot; renderAimbar(); }
    return null;
  }
  if (!level) return act('cast', { spell: sp.name, slot: UI.slot || null });
  detail(`${sp.label}\n${sp.time} · ${sp.range}\n\n${sp.text}`, () => spellButtons(c, sp, level));
  return null;
}
function spellButtons(c, sp, level) {
  if (battleSpell(sp.name)) return [[S('Cast'), () => castChip(c, sp, level)]];
  const chosen = c.slots.find(s => s.key === UI.slot);
  const low = c.slots.find(s => /^\d+$/.test(String(s.key)) && +s.key >= level && s.left > 0) || c.slots.find(s => s.left > 0 && s.key === 'pact');
  const cast = !level ? S('Cast') : chosen ? S('Cast (uses a {0} slot, {1} left)', chosen.label, chosen.left)
    : low ? S('Cast (uses a {0} slot, {1} left)', low.label, low.left) : S('Cast (uses a slot)');
  return [[cast, () => act('cast', { spell: sp.name, slot: UI.slot || null })],
    sp.ritual ? [S('Cast as a ritual (no slot, 10 minutes longer)'), () => act('cast', { spell: sp.name, ritual: true }), ''] : null];
}

function battleSpell(name) {
  const a = ST.battle && ST.battle.status === 'active' && ST.battle.actions;
  if (!a) return null;
  for (const g of a.spells) { const it = g.items.find(i => i.name === name); if (it) return it; }
  return null;
}

// ---------------------------------------------------------------- items as cards
// Dragged between your pack, the team inventory, a teammate and the battle map (onto a token: handed over); more than
// one asks how many. Touch screens: a tap on a card offers the same moves.
const DRAG = { mine: 'text/x-dm-item', team: 'text/x-dm-team' };
const dragKind = e => { const t = [...e.dataTransfer.types]; return t.includes(DRAG.team) ? 'team' : t.includes(DRAG.mine) ? 'mine' : null; };
function dragData(e) {
  for (const [from, type] of Object.entries(DRAG)) {
    const raw = e.dataTransfer.getData(type);
    if (raw) { try { return { from, ...JSON.parse(raw) }; } catch { return null; } }
  }
  return null;
}
function dragDone() {
  document.body.classList.remove('dragging', 'drag-mine', 'drag-team');
  document.querySelectorAll('.dz.over').forEach(x => x.classList.remove('over'));
  UI.dragging = null;
  if (UI.staleSheet && ST) { UI.staleSheet = false; keepFocus($('sheet'), renderSheet); }
}
document.addEventListener('dragend', dragDone);
document.addEventListener('drop', () => setTimeout(dragDone), true);
/** A place a card may be dropped on: `takes` the kinds it accepts ('mine', 'team'); `to` where moveItem sends it. */
function dropZone(el, takes, to) {
  el.addEventListener('dragover', e => {
    if (!takes.includes(dragKind(e))) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move'; el.classList.add('over');
  });
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('over'); });
  el.addEventListener('drop', e => {
    const d = dragData(e);
    el.classList.remove('over');
    if (!d || !takes.includes(d.from)) return;
    e.preventDefault();
    moveItem(d, to, null, e.ctrlKey);
  });
  return el;
}
const myToken = () => ST && ST.battle.combatants.find(c => c.mine && c.character === ST.me.active);
/** Team items go on the map any time out of a fight; in one, on my turn. */
const canTeamDrop = () => !(typeof bgShown === 'function' && bgShown() && !bgMember()) && (ST.battle.status !== 'active' || !!ST.battle.my_turn);   // (a member: onto the arena's map)
/** How many of a stack: 1 when there is one; otherwise a small sheet (null: cancelled). */
function askQty(question, max, verb) {
  if (!(max > 1)) return Promise.resolve(1);
  return new Promise(done => {
    let n = max;
    const num = h('input', { type: 'number', min: 1, max, value: n, inputmode: 'numeric', 'aria-label': S('How many') });
    const range = h('input', { type: 'range', min: 1, max, value: n, 'aria-label': S('How many') });
    const set = v => { n = Math.max(1, Math.min(max, parseInt(v, 10) || 1)); num.value = n; range.value = n; };
    num.addEventListener('input', () => { if (num.value !== '') set(num.value); });
    num.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const ok = $('detail').querySelector('.row button'); if (ok) ok.click(); } });
    range.addEventListener('input', () => set(range.value));
    detail(() => h('div', { class: 'qty' }, h('b', null, question),
      h('div', { class: 'qrow' }, btn('1', () => set(1), 'sm'), range, num, btn(S('All'), () => set(max), 'sm'))),
    () => [[verb || S('Move'), () => done(n)]], () => done(null));
    if (!touch()) { num.focus({ preventScroll: true }); num.select(); }
  });
}
/** Move a card's items (d: {from: 'mine'|'team', item, qty, label}) to 'mine', 'team', 'map' (at: the tile) or a teammate. */
async function moveItem(d, to, at, one) {
  if (d.from === to) return null;
  if (to === 'map' && d.from === 'mine' && !(myToken() || {}).pos) { say(S('Your token isn\'t on the map.'), true); return null; }
  if (to === 'map' && d.from === 'team' && !canTeamDrop()) { say(S('In a fight you can lay team items on the map on your turn.'), true); return null; }
  const n = one ? 1 : await askQty(S('How many {0}? (of {1})', d.label, d.qty), d.qty);
  if (!n) return null;
  const a = { item: d.item, amount: n };
  if (to === 'map') return act(d.from === 'team' ? 'team_drop' : 'drop_item', { ...a, x: at[0], y: at[1] }, true);
  if (d.from === 'mine') return to === 'team' ? act('team_put', a, true) : act('give', { ...a, to }, true);
  return act('team_take', to === 'mine' ? a : { ...a, to }, true);
}
function startPlace(d) { UI.place = d; if (UI.aim) cancelAim(); UI.move = null; showView('map'); renderAimbar(); }
function cancelPlace() { UI.place = null; renderAimbar(); }
/** A small button on a card (its click doesn't open the card). */
const mini = (text, fn, cls, tipText) => h('button', { class: 'mini ' + (cls || ''), tip: tipText, draggable: 'false',
  onclick: e => { e.stopPropagation(); return go(fn)(e); } }, text);
function itemCard(it, from, menu, ...extras) {
  return h('div', { class: `icard ${from}${it.equipped ? ' eq' : ''}`, tip: it.tip || it.label, more: menu, draggable: touch() ? null : 'true',
    'aria-label': it.label + (it.qty > 1 ? ` ×${it.qty}` : ''), onclick: () => detail(it.tip || it.label, menu),
    ondragstart: e => {
      tip();
      e.dataTransfer.setData(DRAG[from], JSON.stringify({ item: it.name, qty: it.qty, label: it.label }));
      e.dataTransfer.effectAllowed = 'move';
      UI.dragging = from;
      setTimeout(() => { if (UI.dragging) document.body.classList.add('dragging', 'drag-' + from); });
    } },
    it.icon ? gi(it.icon, 'sm ii') : null, h('span', { class: 'n' }, it.label), it.note ? h('span', { class: 'nt', 'aria-hidden': 'true' }, '📝') : null,
    it.qty > 1 ? h('span', { class: 'q' }, '×' + it.qty) : null,
    it.expires ? h('span', { class: 'q warn', tip: S('Made by a spell: it runs out with time (rests, rounds, days on the road)') }, '⏳ ' + it.expires) : null, ...extras);
}
/** An item's name, count and description in the detail sheet (a new entry, or an item changed): save({item, amount, note}). */
function itemForm(title, init, save, verb) {
  const name = h('input', { type: 'text', value: init.name || '', maxlength: 120, placeholder: S('Item name'), 'aria-label': S('Item name') });
  const qty = h('input', { type: 'number', min: 1, value: init.qty || 1, inputmode: 'numeric', 'aria-label': S('How many') });
  const note = h('textarea', { value: init.note || '', maxlength: 500, placeholder: S('Description (optional)'), 'aria-label': S('Description (optional)') });
  const ok = () => {
    const v = { item: name.value.trim(), amount: Math.max(1, parseInt(qty.value, 10) || 1), note: note.value.trim() };
    if (!v.item) { say(S('Give it a name first.'), true); return null; }
    return save(v);
  };
  name.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const b = $('detail').querySelector('.row button'); if (b) b.click(); } });
  detail(() => h('div', { class: 'iform' }, h('b', null, title), name, h('div', { class: 'qrow' }, h('span', { class: 'dim small' }, S('How many')), qty,
    btn('−', () => { qty.value = Math.max(1, (parseInt(qty.value, 10) || 1) - 1); }, 'sm'), btn('+', () => { qty.value = (parseInt(qty.value, 10) || 0) + 1; }, 'sm')), note),
  () => [[verb || S('Save'), ok]]);
  if (!touch()) { name.focus({ preventScroll: true }); name.select(); }
}
/** A one-line quick entry above a list of cards: a name, how many, + (✎: with a description). where: 'mine' | 'team'. */
function quickAdd(where) {
  const q = UI.quick[where] || (UI.quick[where] = { name: '', qty: '' });
  const send = v => act(where === 'team' ? 'team_add' : 'add_item', v, true).then(r => {
    if (r) {                                   // shown at once (a focused field holds the sheet back), ready for the next
      q.name = ''; q.qty = ''; UI.quickFocus = where;
      const el = $('sheet'), top = el.scrollTop;
      renderSheet(); el.scrollTop = top;
    }
    return r;
  });
  const now = () => {
    const item = name.value.trim();
    if (!item) { name.focus(); return null; }
    return send({ item, amount: Math.max(1, parseInt(qty.value, 10) || 1), note: '' });
  };
  const name = h('input', { type: 'text', value: q.name, maxlength: 120, class: 'qname', 'aria-label': S('Item name'),
    placeholder: where === 'team' ? S('Add to the team…') : S('Add an item…'),
    oninput: e => { q.name = e.target.value; }, onkeydown: e => { if (e.key === 'Enter') { e.preventDefault(); go(now)(e); } } });
  const qty = h('input', { type: 'number', min: 1, value: q.qty, placeholder: '1', inputmode: 'numeric', class: 'qn', 'aria-label': S('How many'),
    oninput: e => { q.qty = e.target.value; } });
  if (UI.quickFocus === where) { UI.quickFocus = null; setTimeout(() => name.focus({ preventScroll: true })); }
  return h('div', { class: 'row quick' }, name, qty, btn('+', now, 'sm primary', S('Add')),
    btn('✎', () => itemForm(where === 'team' ? S('Into the team inventory') : S('Into your pack'), { name: name.value.trim(), qty: parseInt(qty.value, 10) || 1 },
      send, S('Add')), 'sm flat', S('Add it with a description')));
}

function inventoryTab(c) {
  const COINS = ['pp', 'gp', 'ep', 'sp', 'cp'];
  const coins = COINS.filter(k => c.currency[k]).map(k => `${c.currency[k]} ${k}`).join(' · ') || '0 gp';
  const amt = h('input', { type: 'number', min: 1, inputmode: 'numeric', placeholder: S('amt'), value: UI.coinAmt, 'aria-label': S('Coins'),
    oninput: e => { UI.coinAmt = e.target.value; } });
  const coin = h('select', { 'aria-label': S('Coin'), onchange: e => { UI.coin = e.target.value; } }, ...COINS.map(k => h('option', { value: k, selected: k === UI.coin }, k)));
  const money = sgn => {
    const n = parseInt(amt.value, 10);
    if (!(n > 0)) return say(S('Enter the amount first.'), true);
    UI.coinAmt = ''; amt.value = '';
    return act('coins', { coins: { [coin.value]: sgn * n } }, true);
  };
  const onMap = !!(myToken() || {}).pos, team = ST.team;
  const trade = may('trade_items'), write = may('write_items');
  const mates = team && trade ? team.members.filter(m => m.name !== c.name && (!onMap || m.on_map)) : [];   // on the map: only those with a token there
  const drop = async it => {
    const n = await askQty(S('Drop how many {0}? (you have {1})', it.label, it.qty), it.qty, S('Drop'));
    if (!n) return null;
    const off = () => act(onMap ? 'drop_item' : 'remove_item', { item: it.name, amount: n }, true);   // on the map: it lies beside you
    return it.qty <= 1 && !onMap ? ask(S('Drop {0}? It leaves your inventory.', it.label), S('Drop'), off, 'danger') : off();
  };
  const card = (it, from) => ({ from, item: it.name, qty: it.qty, label: it.label });
  const passOn = d => mates.map(m => ['→ ' + m.name, () => moveItem(d, m.name), '']);
  const identifying = (c.identify || {}).pending > 0;
  const myMenu = it => () => [it.unidentified && identifying ? ['🔍 ' + S('Identify it'), () => act('identify', { item: it.name })] : null,
    it.usable ? [S('Use'), () => act('use_item', { item: it.name })] : null,
    it.wearable ? [it.equipped ? S('Unequip') : S('Equip'), () => act('equip', { item: it.name, on: !it.equipped }, true), ''] : null,
    it.attunable ? [it.attuned ? S('Break attunement') : S('Attune'), () => act('attune', { item: it.name, on: !it.attuned }, true), ''] : null,
    team && trade ? ['→ ' + S('Team inventory'), () => moveItem(card(it, 'mine'), 'team'), ''] : null, ...passOn(card(it, 'mine')),
    write ? [S('Edit…'), () => edit(it, 'edit_item'), ''] : null, may(onMap ? 'trade_items' : 'write_items') ? [S('Drop'), () => drop(it), 'danger'] : null];
  const edit = (it, action) => itemForm(S('Change {0}', it.label), { name: it.unidentified ? it.label : it.name, qty: it.qty, note: it.note },
    v => act(action, { item: it.name, qty: v.amount, note: v.note, new_name: v.item }, true));
  const outOfTeam = async it => {
    const n = await askQty(S('Take how many {0} out of the team inventory for good? (of {1})', it.label, it.qty), it.qty, S('Remove'));
    return n ? act('team_remove', { item: it.name, amount: n }, true) : null;
  };
  const teamMenu = it => () => [trade ? [S('Take it'), () => moveItem(card(it, 'team'), 'mine')] : null, ...passOn(card(it, 'team')),
    trade && canTeamDrop() ? [S('Put it on the map'), () => startPlace(card(it, 'team')), ''] : null,
    write ? [S('Edit…'), () => edit(it, 'team_edit'), ''] : null, write ? [S('Used up / lost…'), () => outOfTeam(it), 'danger'] : null];
  const items = [...c.inventory].sort((a, b) => (b.equipped - a.equipped) || a.label.localeCompare(b.label));
  const mine = items.map(it => itemCard(it, 'mine', myMenu(it),
    it.usable ? mini(S('Use'), () => act('use_item', { item: it.name }), 'primary', S('Use one up')) : null,
    it.wearable ? mini('🛡', () => act('equip', { item: it.name, on: !it.equipped }, true), it.equipped ? 'on' : '', it.equipped ? S('Unequip') : S('Equip')) : null,
    it.attunable ? mini('✦', () => act('attune', { item: it.name, on: !it.attuned }, true), it.attuned ? 'on' : '', it.attuned ? S('Break attunement') : S('Attune')) : null));
  const out = [h('div', { class: 'card' }, h('div', { class: 'row coins' }, h('span', { class: 'title' }, S('Coins')), h('b', null, coins), h('span', { class: 'grow' }),
    needs('write_items', h('span', { class: 'cc' }, amt, coin, btn('+', () => money(1), 'sm primary', S('Coins you got')), btn('−', () => money(-1), 'sm', S('Coins you paid or lost'))))))];
  if (mates.length) out.push(h('div', { class: 'mates' }, h('span', { class: 'title' }, S('Hand to')),
    ...mates.map(m => dropZone(h('span', { class: 'chip mate dz', tip: S('Drop an item here to hand it to {0}', m.name) }, m.name), ['mine', 'team'], m.name))));
  if (team) {
    const sup = team.supplies, low = sup && sup.days_left != null && sup.days_left < 2;
    const food = sup ? h('span', { class: 'sup' + (low ? ' bad' : ''), tip: S('The group\'s food on the World map is the food in here: a day\'s meals are eaten from it, rations first.') },
      '🍖 ' + S('{0} meals', sup.meals) + (sup.days_left != null ? ' · ' + S('lasts about {0} days', sup.days_left) : '')) : null;
    const shared = [...team.items].sort((a, b) => (b.food - a.food) || a.label.localeCompare(b.label));     // the supplies first
    out.push(dropZone(h('div', { class: 'card dz team' }, h('div', { class: 'title' }, '🎒 ' + S('Team inventory'), h('span', { class: 'grow' }), food),
      shared.length ? h('div', { class: 'icards' }, ...shared.map(it => itemCard(it, 'team', teamMenu(it),
        trade ? mini('↓', () => moveItem(card(it, 'team'), 'mine'), '', S('Take it')) : null)))
        : h('div', { class: 'empty dim small' }, touch() ? S('Empty. Tap an item of yours to put it here.') : S('Empty. Drag an item of yours here to share it.')),
      needs('write_items', quickAdd('team'))), ['mine'], 'team'));
  }
  const how = touch() ? S('Tap a card for what you can do with it; hold it for its text.')     // the how-to: on the ⓘ's hover (hold)
    : S('Drag a card to the team inventory, a teammate or the map (onto a token: handed over); Ctrl moves just one. Click a card for more.');
  out.push(dropZone(h('div', { class: 'card dz mine' }, h('div', { class: 'title' }, S('Items'), ' ', h('span', { class: 'info', tip: how, 'aria-label': how, onclick: () => detail(how) }, 'ⓘ'),
    h('span', { class: 'grow' }), h('span', { class: 'dim small' }, c.weight)),
    mine.length ? h('div', { class: 'icards' }, ...mine) : h('div', { class: 'empty dim small' }, S('Nothing carried.')), needs('write_items', quickAdd('mine'))), ['team'], 'mine'));
  return out;
}

function featuresTab(c) {
  return c.features.map(g => h('div', { class: 'card' + (folded('features:' + g.source) ? ' shut' : '') },   // each source folds under its title
    h('div', { class: 'title' }, foldHead('features:' + g.source, g.source, g.items.length, renderSheet)),
    ...(folded('features:' + g.source) ? [] : g.items).map(f => {
    const key = g.source + '|' + f.name, open = UI.open.has(key);
    return h('div', { class: 'feat' }, h('div', { class: 'li click', tip: open ? null : `${f.label}\n${f.text}`,   // folded: its text on hover
      onclick: () => { tip(); open ? UI.open.delete(key) : UI.open.add(key); renderSheet(); } },
      h('span', { class: 'dim' }, open ? '▾' : '▸'), h('span', { class: 'n' }, f.label), f.level ? h('span', { class: 'dim small' }, S('Level {0}', f.level)) : null),
      open ? h('div', { class: 'txt' }, f.text) : null);
  })));
}

function notesTab(c) {
  // Drafts live in UI (and the browser's storage): a refresh, a re-render or a closing keyboard doesn't lose the text.
  const drafts = () => { store('notedraft', UI.noteDraft); store('editdraft', UI.editDraft); store('editnote', UI.editNote); };
  const add = h('textarea', { placeholder: S('A new note…'), value: UI.noteDraft, 'aria-label': S('A new note…'), oninput: e => { UI.noteDraft = e.target.value; drafts(); } });
  if (UI.editNote != null && !c.notes.some(n => n.id === UI.editNote)) UI.editNote = null;
  const list = c.notes.map(n => {
    if (UI.editNote === n.id) {
      const ed = h('textarea', { value: UI.editDraft[n.id] != null ? UI.editDraft[n.id] : n.text, oninput: e => { UI.editDraft[n.id] = e.target.value; drafts(); } });
      return h('div', { class: 'note' }, ed, btn(S('Save'), () => {
        const text = ed.value;
        return act('note_edit', { id: n.id, text }, true).then(r => { if (r) { UI.editNote = null; delete UI.editDraft[n.id]; drafts(); keepFocus($('sheet'), renderSheet); } });
      }, 'sm primary'),
      btn(S('Cancel'), () => { UI.editNote = null; delete UI.editDraft[n.id]; drafts(); renderSheet(); }));
    }
    return h('div', { class: 'note' }, h('div', null, n.text), needs('edit_notes', btn('✎', () => { UI.editNote = n.id; drafts(); renderSheet(); }, 'sm flat', S('Edit'))),
      needs('edit_notes', btn('×', () => ask(S('Delete this note?'), S('Delete'), () => act('note_remove', { id: n.id }, true), 'danger'), 'sm flat', S('Delete'))));
  });
  const labels = { personality: S('Personality traits'), ideal: S('Ideals'), bond: S('Bonds'), flaw: S('Flaws'), appearance: S('Appearance'), backstory: S('Backstory') };
  const details = Object.entries(labels).map(([k, l]) => [h('label', { class: 'f' }, l),       // (read only while the DM keeps them)
    h('textarea', { value: c.details[k] || '', readonly: !may('edit_notes'), onchange: e => act('details', { fields: { [k]: e.target.value } }, true) })]);
  return [h('div', { class: 'card' }, h('div', { class: 'title' }, S('Notes')), ...list, needs('edit_notes', add),
    needs('edit_notes', h('div', { class: 'row' }, btn(S('Add note'), () => {
      const text = add.value;
      if (!text.trim()) return null;
      return act('note_add', { text }, true).then(r => { if (r) { UI.noteDraft = ''; add.value = ''; drafts(); keepFocus($('sheet'), renderSheet); } });
    }, 'sm primary')))),
  h('div', { class: 'card' }, h('div', { class: 'title' }, S('Details')), ...details.flat())];
}

// ---------------------------------------------------------------- team notes: everyone's, one editor at a time
// UI.tnEdit {id, title, text}: the note this page has open for editing (kept in the browser's storage with its text:
// a refresh doesn't lose it). While it is open the page renews its hold on the note; others see who is editing.
const TN_HOLD_MS = 15000;
let tnTimer = 0, tnExpiry = 0;
function tnStore() { store('tnedit', UI.tnEdit); store('tndraft', UI.tnDraft); }
/** Keep the hold while editing: lost (it lapsed) and no one else has it: take it again. */
function tnHeartbeat() {
  clearInterval(tnTimer); tnTimer = 0;
  if (!UI.tnEdit) return;
  tnTimer = setInterval(async () => {
    const e = UI.tnEdit;
    if (!e || NET.state !== 'live') return;
    try {
      const r = await api('/api/act', { action: 'tnote_hold', id: e.id });
      const n = ((ST.notes || {}).notes || []).find(x => x.id === e.id);
      if (!r.data.held && n && !n.editing) await api('/api/act', { action: 'tnote_begin', id: e.id });
    } catch { /* the next beat tries again */ }
  }, TN_HOLD_MS);
}
async function tnBegin(n) {
  const r = await act('tnote_begin', { id: n.id }, true);
  if (!r) return;
  UI.tnEdit = { id: n.id, title: r.data.title, text: r.data.text }; UI.tnOpen = n.id; tnStore(); tnHeartbeat(); renderSheet();
  const f = $('sheet').querySelector('.tnedit textarea'); if (f) f.focus();
}
function tnClose() { UI.tnEdit = null; tnStore(); tnHeartbeat(); }
// Leaving the page: let the note go at once (a refresh takes it back), not after the hold lapses.
addEventListener('pagehide', () => { if (UI.tnEdit && navigator.sendBeacon) navigator.sendBeacon('/api/act?k=' + encodeURIComponent(KEY), JSON.stringify({ action: 'tnote_cancel', id: UI.tnEdit.id })); });
function teamNotesTab() {
  const N = ST.notes;
  if (!N) return [h('div', { class: 'card dim' }, typeof bgApp === 'function' && bgApp() ? S('No team notes in Battlegrounds.') : S('Ask your DM to give you a character.'))];
  const notes = N.notes;
  if (UI.tnEdit && !notes.some(n => n.id === UI.tnEdit.id)) tnClose();
  if (UI.tnEdit && !tnTimer) {                       // back after a refresh: take the note again (kept text stays)
    const e = UI.tnEdit, n = notes.find(x => x.id === e.id);
    if (n && (!n.editing || n.editing.mine)) api('/api/act', { action: 'tnote_begin', id: e.id }).catch(() => {});
    tnHeartbeat();
  }
  // someone else's hold lapses unless renewed: look again then (their page closed without saying so)
  clearTimeout(tnExpiry);
  const next = Math.min(...notes.filter(n => n.editing && !n.editing.mine).map(n => n.editing.left));
  if (isFinite(next)) tnExpiry = setTimeout(() => load(['notes']).catch(() => {}), (Math.max(0, next) + 1) * 1000);
  const when = t => t ? new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';
  const list = notes.map(n => {
    const ed = UI.tnEdit && UI.tnEdit.id === n.id ? UI.tnEdit : null, other = n.editing && !n.editing.mine ? n.editing : null;
    const lockTag = other ? h('span', { class: 'tnlock small' }, '✎ ' + S('{0} is editing', other.who)) : null;
    if (ed) {
      const title = h('input', { value: ed.title, maxlength: 120, placeholder: S('Header'), 'aria-label': S('Header'), oninput: e => { ed.title = e.target.value; tnStore(); } });
      const text = h('textarea', { value: ed.text, placeholder: S('Description'), 'aria-label': S('Description'), oninput: e => { ed.text = e.target.value; tnStore(); } });
      return h('div', { class: 'tnote open tnedit' }, title, text,
        other ? h('div', { class: 'small bad' }, S('{0} is editing this note now; your text is kept - save when they are done.', other.who)) : null,
        h('div', { class: 'row' },
          btn(S('Save'), () => act('tnote_save', { id: n.id, title: ed.title, text: ed.text }, true).then(r => { if (r) { tnClose(); keepFocus($('sheet'), renderSheet); } }), 'sm primary'),
          btn(S('Cancel'), () => { tnClose(); renderSheet(); return act('tnote_cancel', { id: n.id }, true); })));
    }
    const open = UI.tnOpen === n.id;
    const by = [n.by ? S('by {0}', n.by) : '', n.edited_by ? S('edited by {0}, {1}', n.edited_by, when(n.edited_at)) : when(n.at)].filter(Boolean).join(' · ');
    const head = h('div', { class: 'li click', tip: open || !n.text ? null : `${n.title}\n${n.text}`,     // folded: its description on hover
      onclick: () => { tip(); UI.tnOpen = open ? null : n.id; renderSheet(); } },
      h('span', { class: 'dim' }, open ? '▾' : '▸'), h('span', { class: 'n' }, n.title), lockTag, h('span', { class: 'dim small' }, by));
    return h('div', { class: 'tnote' + (open ? ' open' : '') }, head, open ? [
      h('div', { class: 'txt' + (n.text ? '' : ' dim') }, n.text || S('No description yet.')),
      h('div', { class: 'row' },
        btn('✎ ' + S('Edit'), () => tnBegin(n), 'sm' + (other ? ' off' : ''), other ? S('{0} is editing this note right now.', other.who) : S('Change the header or add details')),
        n.can_delete ? btn('×', () => ask(S('Delete the note "{0}" for everyone?', n.title), S('Delete'), () => act('tnote_remove', { id: n.id }, true), 'danger'),
          'sm flat', S('Delete')) : null)] : null);
  });
  const d = UI.tnDraft;
  const title = h('input', { value: d.title, maxlength: 120, placeholder: S('Header'), 'aria-label': S('Header'), oninput: e => { d.title = e.target.value; tnStore(); } });
  const text = h('textarea', { value: d.text, placeholder: S('Description (shown on hover)'), 'aria-label': S('Description'), oninput: e => { d.text = e.target.value; tnStore(); } });
  return [h('div', { class: 'card' }, h('div', { class: 'title' }, S('Team notes'), h('span', { class: 'grow' }), h('span', { class: 'dim small' }, String(notes.length))),
    notes.length ? list : h('div', { class: 'empty dim small' }, S('No team notes yet.')),
    h('div', { class: 'small dim' }, S('Every player sees these notes and can add to them. One person edits a note at a time.'))),
  h('div', { class: 'card tnedit' }, h('div', { class: 'title' }, S('New team note')), title, text,
    h('div', { class: 'row' }, btn(S('Add note'), () => {
      if (!d.title.trim()) { say(S('A note needs a header.'), true); return null; }
      return act('tnote_add', { title: d.title, text: d.text }, true).then(r => { if (r) { UI.tnDraft = { title: '', text: '' }; tnStore(); keepFocus($('sheet'), renderSheet); } });
    }, 'sm primary')))];
}

// ---------------------------------------------------------------- the table feed: rolls and chat
const FILTERS = () => [['all', S('All')], ['roll', S('Rolls')], ['chat', S('Chat')]];
function renderFeed() {
  const drawn = [ST.feed, UI.local, UI.local.length, UI.feed, wordsLang];   // a battle move leaves the feed as it was
  if (UI.feedDrawn && UI.feedDrawn.every((x, i) => x === drawn[i])) { unread(); return; }
  UI.feedDrawn = drawn;
  $('feedfilter').replaceChildren(...FILTERS().map(([k, l]) => h('button', { class: UI.feed === k ? 'on' : '', onclick: () => { UI.feed = k; store('feed', k); renderFeed(); } }, l)));
  const box = $('feed'), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  const entries = [...ST.feed.map(e => ({ ...e, sort: e.id })), ...UI.local].sort((a, b) => a.sort - b.sort)
    .filter(e => UI.feed === 'all' || (UI.feed === 'roll' ? e.kind === 'roll' || e.kind === 'xp' : e.kind === 'chat' || e.kind === 'private'));
  box.replaceChildren(...entries.slice(-120).map(e => h('div', { class: `e ${e.kind}${e.dm ? ' dm' : ''}${e.uid === ST.me.id ? ' me' : ''}` },
    h('span', { class: 't' }, e.time), e.who ? h('span', { class: 'w' }, (e.dm ? '👑 ' : '') + e.who) : null, rich(e.text))));
  if (atEnd) box.scrollTop = box.scrollHeight;
  unread();
}
/** New lines in the feed while it is out of sight (phones: another tab; desktop: folded): a count on its tab. */
function unread() {
  if (!ST) return;
  const last = ST.feed.length ? ST.feed[ST.feed.length - 1].id : 0;
  const shown = NARROW.matches ? UI.view === 'feed' : !document.body.classList.contains('folded');
  if (UI.seenFeed === null || shown || UI.seenFeed > last) UI.seenFeed = last;
  const n = ST.feed.filter(e => e.id > UI.seenFeed && e.uid !== ST.me.id).length;
  $('unread').textContent = n > 99 ? '99+' : String(n);
  $('unread').classList.toggle('hide', !n);
  $('unread').setAttribute('aria-label', S('{0} new', n));
  $('dockfold').textContent = (document.body.classList.contains('folded') ? '▴' : '▾') + (n && !NARROW.matches ? ` ${n}` : '');
  $('dockfold').setAttribute('aria-label', document.body.classList.contains('folded') ? S('Show the table feed') : S('Hide the table feed'));
}
async function send() {
  const text = $('say').value.trim();
  if (!text) return;
  $('say').value = '';
  if (text.startsWith('/')) {
    const r = await act('command', { text }, true);
    if (r && r.text) {
      const last = ST.feed.length ? ST.feed[ST.feed.length - 1].id : 0;
      UI.local.push({ kind: 'private', time: new Date().toTimeString().slice(0, 5), who: '', text: '› ' + text + '\n' + r.text, sort: last + 0.5 });
      UI.local = UI.local.slice(-20);
      renderFeed();
    }
  } else act('chat', { text }, true);
}
$('send').onclick = send;
$('say').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
needs('roll', $('quick'));
$('quick').append(...['d4', 'd6', 'd8', 'd10', 'd12', 'd20', 'd100'].map(d => h('button', { onclick: go(() => act('roll', { expr: '1' + d }, true)), 'aria-label': S('Roll a {0}', d) }, d)));
if (store('folded')) document.body.classList.add('folded');
$('dockfold').onclick = () => { store('folded', document.body.classList.toggle('folded')); unread(); if (ST) renderMap(); };

// ---------------------------------------------------------------- the rest
/** Phones show one view at a time: the map, the character, or the table feed. */
function showView(v) {
  UI.view = v;
  document.body.dataset.show = v;                     // (not data-view: the tab buttons use that)
  document.querySelectorAll('[data-view]').forEach(x => { x.classList.toggle('on', x.dataset.view === v); x.setAttribute('aria-pressed', String(x.dataset.view === v)); });
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === v));
  if (v === 'feed') { const box = $('feed'); box.scrollTop = box.scrollHeight; }
  if (v === 'sheet') $('sheet').querySelectorAll('textarea').forEach(fitText);      // sized now it shows (hidden, they can't be)
  if (ST) { renderMap(); if (typeof renderWorld === 'function') renderWorld(); unread(); }
}
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
$('order').addEventListener('wheel', e => {             // the order as a strip (laptops, phones): the wheel scrolls it sideways
  const o = $('order');
  if (o.scrollWidth > o.clientWidth + 2 && o.scrollHeight <= o.clientHeight + 2 && Math.abs(e.deltaY) > Math.abs(e.deltaX)) { o.scrollLeft += e.deltaY; e.preventDefault(); }
}, { passive: false });
showView('map');
$('who').addEventListener('change', e => act('choose', { character: e.target.value }, true));
window.addEventListener('resize', () => { if (ST) { renderMap(); unread(); } });
document.addEventListener('pointerdown', () => tip(), true);              // touch screens: a tap or scroll closes the tooltip
document.addEventListener('scroll', () => tip(), true);
window.addEventListener('online', () => setTimeout(() => load().catch(() => {}), 500));
conn();

if (!KEY) gate(S('This page needs your personal link from the DM.'));
else load().then(listen).catch(e => { if (e.message !== 'login') { say(e.message, true); listen(); } });
