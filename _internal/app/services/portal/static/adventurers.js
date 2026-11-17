// Dungeonomicon Adventurers on the player page (services/adventurers, portal/adventurers.py): one world for every
// group. The page asks for a nickname and password first (POST /api/login answers with the key a link would carry).
// Then the map pane's other face, the Adventure (body.advmode):
//   - a top strip: your characters (a click picks one; their health on the ring), your purse, experience, your group;
//   - a rail of tabs (Map, Town, Group, Quests, Character, Log; the last tab kept per device);
//   - the Map: the world as your groups have seen it, painted as Packing Merchant paints its country (soft washes per
//     land with wandering pen borders, an inked coast, woods in masses, peaks, seals for the places, browned paper
//     where nobody has been) and moved like the campaign's world map (drag, wheel and pinch, + - fit find; a tap on a
//     neighbouring place moves the group). Over it, folding cards: the fight in the way, the group, the quests;
//   - Town, Group, Quests and Log: their own pages.
// Each part of the page is drawn again only when its own data changed, so a click never throws away a scroll, a
// folded section or what is being typed. Actions are icons; their words show on hover (a held finger on phones).
// While the group fights the map pane shows the fight (world.js mapMode), with the usual action bar.
'use strict';
const AVN = { char: store('advchar') || null, tab: store('advtab') || 'map', fold: store('advfold') || {}, shop: null,
  shopData: null, shopFor: null, q: '', checked: false, newChar: false, form: {}, sheet: store('advsheet') !== false,
  area: {}, pinned: null, route: null, encSeen: null };
const advOn = () => !!(ST && ST.edition === 'adventurers');
const advS = () => (ST && ST.adv) || null;
const ai = (name, cls = '') => h('span', { class: 'gi ' + cls, 'aria-hidden': 'true', style: `--gi:url(/advart/icons/${name}.svg)` });
/** An icon button: the picture, its words on hover (and held on touch), a count beside it if any. */
const aib = (icon, words, fn, cls = '', count) => h('button', { class: 'ib ' + cls, onclick: go(fn), tip: words,
  'aria-label': words.split('\n')[0] }, ai(icon), count != null ? h('span', { class: 'ct' }, count) : null);
const avMoney = cp => { cp = Math.round(cp || 0); const g = Math.floor(cp / 100), s = Math.floor(cp % 100 / 10), c = cp % 10;
  return [g ? g.toLocaleString() + ' gp' : '', s ? s + ' sp' : '', c ? c + ' cp' : ''].filter(Boolean).join(' ') || '0 gp'; };
const aact = (action, args = {}, quiet = false) => act(action, { char: AVN.char, ...args }, quiet);
const AV_TABS = [['map', 'treasure-map', 'Map'], ['town', 'village', 'Town'], ['group', 'three-friends', 'Group'],
  ['quests', 'scroll-unfurled', 'Quests'], ['hero', 'person', 'Character'], ['log', 'open-book', 'Log']];
const SHOP_ICON = { tavern: 'tavern-sign', general: 'shop', blacksmith: 'anvil', fletcher: 'bow-arrow',
  alchemist: 'round-bottom-flask', temple: 'holy-symbol', wizard: 'wizard-staff', trader: 'swap-bag' };
const QUEST_ICON = { slay: 'crossed-swords', retrieve: 'gems', rescue: 'circle-cage', clear: 'ancient-ruins', hunt: 'wolf-head',
  investigate: 'magnifying-glass', scout: 'surrounded-eye', gather: 'pine-tree', deliver: 'envelope', escort: 'footsteps' };
const SERVICE_ICON = { rest: 'night-sleep', heal: 'heart-plus', cure: 'health-increase', raise: 'falling-star' };

// ---------------------------------------------------------------- logging in
/** No key yet (or a stale one): the Adventurers app asks for a nickname and password; another app's page says to ask
 *  the DM for a link. True when it took over. */
function advGate(text) {
  if (AVN.checked) return false;
  AVN.checked = true;
  fetch('/api/edition', { cache: 'no-store' }).then(r => r.json()).then(e => {
    if (e && e.accounts) advLogin(e.title); else gate(text);
  }).catch(() => gate(text));
  return true;
}
function advLogin(title) {
  advStyle();
  const nick = h('input', { autocomplete: 'username', placeholder: S('Nickname'), maxlength: 20 });
  const pw = h('input', { type: 'password', autocomplete: 'current-password', placeholder: S('Password') });
  const msg = h('p', { class: 'small bad' });
  const send = async register => {
    msg.textContent = '';
    try {
      const r = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nick: nick.value, password: pw.value, register }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.key) { msg.textContent = d.error || S('That did not work.'); return; }
      try { localStorage.setItem('dm_key', d.key); } catch { /* (a private window: this visit only) */ }
      location.href = '/?k=' + encodeURIComponent(d.key);
    } catch { msg.textContent = S("Can't reach the table right now - reconnecting…"); }
  };
  pw.addEventListener('keydown', e => { if (e.key === 'Enter') send(false); });
  $('gate').replaceChildren(h('div', { class: 'advlogin' },
    h('img', { src: '/advart/map/compass_rose.webp', alt: '', class: 'avlogo' }),
    h('h2', null, title || 'Adventurers'),
    h('p', { class: 'dim' }, S('One world, every group. Log in, or make an account with a nickname of your own.')),
    nick, pw,
    h('div', { class: 'row' }, h('button', { class: 'primary', onclick: () => send(false) }, S('Log in')),
      h('button', { onclick: () => send(true) }, S('Create account'))), msg));
  $('gate').classList.remove('hide');
  nick.focus();
}
function advLogout() {
  try { localStorage.removeItem('dm_key'); } catch { /* (nothing kept) */ }
  location.href = '/';
}

// ---------------------------------------------------------------- the frame
function advStyle() {
  if ($('advstyle')) return;
  document.head.append(h('style', { id: 'advstyle' }, `
body.advmode #map>:not(#advbody){display:none!important}#advbody{display:none}body.advmode #advbody{display:grid}
body.adv #who{display:none}body.adv.avnosheet #body{grid-template-columns:minmax(0,1fr)}body.adv.avnosheet #sheet{display:none}
#advbody{grid-template-columns:44px minmax(0,1fr);gap:6px;height:100%;min-height:0}
#avrail{display:flex;flex-direction:column;gap:2px;align-items:center;padding:4px 0;background:var(--raised);border:1px solid var(--border)}
#avrail button.ib{width:38px;height:38px;justify-content:center;position:relative}#avrail button.ib .gi{width:22px;height:22px}
#avrail button.ib.on{background:var(--accent-dim);color:var(--on-accent);border-color:var(--gold)}
#avrail .ct{position:absolute;top:1px;right:1px;font-size:11px;background:var(--bad);color:#fff;border-radius:7px;padding:0 4px;line-height:14px}
#avrail .grow{flex:1}#avmain{display:flex;flex-direction:column;gap:6px;min-height:0;min-width:0}
#avtop{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:3px 6px;background:var(--raised);border:1px solid var(--border)}
.avchip{width:30px;height:30px;border-radius:50%;display:inline-grid;place-items:center;font-weight:700;font-size:13px;cursor:pointer;
  background:var(--paper);border:2px solid var(--edge);position:relative;font-family:var(--head)}.avchip.on{outline:2px solid var(--gold);outline-offset:1px}
.avchip .st{position:absolute;top:-6px;right:-6px;color:var(--gold);font-size:12px}.avstat{display:inline-flex;gap:3px;align-items:center;font-size:13px}
.avxp{width:70px;height:6px;background:var(--paper-down);display:inline-block;vertical-align:middle}.avxp i{display:block;height:100%;background:var(--gold)}
#avnext{display:flex;gap:6px;align-items:center;padding:3px 8px;font-size:13px;background:var(--paper);border:1px solid var(--edge);
  color:var(--accent-dim);cursor:pointer}#avnext:hover{background:var(--paper-hover)}#avnext.idle{cursor:default;color:var(--dim)}#avnext .k{margin-left:auto;font-size:11px;color:var(--dim)}
.hov{visibility:hidden}.avlist>div:hover .hov,.avlist>div:focus-within .hov,.avq:hover .hov,.avq:focus-within .hov{visibility:visible}
@media (pointer:coarse){.hov{visibility:visible}}
@keyframes avpulse{0%{box-shadow:0 0 0 0 rgba(168,48,31,.75)}100%{box-shadow:0 0 0 14px rgba(168,48,31,0)}}.avcard.enc{animation:avpulse 1.3s 3}
.avadd{border:1px dashed var(--edge);color:var(--dim);justify-content:center;cursor:pointer}.avadd:hover{color:var(--text);background:var(--paper-hover)}
.avqty{display:inline-flex;align-items:center;gap:2px}.avqty b{min-width:26px;text-align:center}.avtile .own{position:absolute;top:1px;left:3px;font-size:10.5px;color:var(--good)}
#avpanes{position:relative;flex:1;min-height:0}.avpane{position:absolute;inset:0;overflow:auto;display:none;background:var(--panel)}
.avpane.on{display:block}#avp-map{overflow:hidden;background:#5b4632}#avcv{display:block;width:100%;height:100%;touch-action:none;cursor:grab}
#avcv.drag{cursor:grabbing}#avcv.step{cursor:pointer}
#avctl{position:absolute;top:8px;left:8px;display:flex;flex-direction:column;gap:3px}#avctl .avz{font:700 18px/1 serif;width:30px;height:30px;justify-content:center}#avctl button.ib{background:var(--raised);border-color:var(--border);color:var(--text)}
#avside{position:absolute;top:8px;right:8px;bottom:8px;width:min(300px,46%);display:flex;flex-direction:column;gap:6px;overflow:auto;pointer-events:none}
#avside>*{pointer-events:auto}.avcard{background:var(--raised);border:1px solid var(--border);box-shadow:0 3px 10px #0006}
.avcard>.hd{display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;font:600 13px var(--head);color:var(--accent);user-select:none}
.avcard>.hd .grow{flex:1}.avcard>.bd{padding:4px 8px 6px}.avcard.fold>.bd{display:none}.avcard.enc{border-color:var(--bad)}.avcard.enc>.hd{color:var(--bad)}
.avrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.avrow .grow{flex:1;min-width:0}
.avlist>div{display:flex;gap:6px;align-items:center;padding:3px 0;border-bottom:1px dotted var(--border)}.avlist>div:last-child{border-bottom:0}
.avlist .grow{flex:1;min-width:0}.avtile{display:inline-flex;flex-direction:column;align-items:center;gap:2px;width:64px;padding:4px;background:var(--paper);
  border:1px solid var(--edge);cursor:pointer;position:relative;font-size:11.5px;text-align:center;line-height:1.15}.avtile:hover{background:var(--paper-hover)}
.avtile .gi{width:28px;height:28px}.avtile .q{position:absolute;top:1px;right:3px;font-weight:700}.avtiles{display:flex;flex-wrap:wrap;gap:4px}
.avmember{display:flex;gap:6px;align-items:center;flex:1}.avbar{height:5px;background:var(--paper-down)}.avbar i{display:block;height:100%;background:var(--good)}
.avbar i.lo{background:var(--bad)}.avbar i.mid{background:var(--warn)}.avsec{margin:8px 10px}.avsec>h3{margin:0 0 6px;font:600 13px var(--head);color:var(--accent);
  display:flex;gap:6px;align-items:center}.avsec>h3 .grow{flex:1}.avq{padding:6px 0;border-bottom:1px dotted var(--border)}.avq p{margin:3px 0}
.avq .t{font-weight:600;color:var(--accent)}.avempty{display:grid;place-items:center;gap:6px;padding:40px 10px;color:var(--dim);text-align:center}
.avempty .gi{width:48px;height:48px}.avshops{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}.avkeeper{font-size:13px;margin:4px 0 8px}
.avfold>summary{cursor:pointer;font-weight:600;padding:3px 0;list-style:none}.avfold>summary::before{content:'▸ ';color:var(--dim)}.avfold[open]>summary::before{content:'▾ '}
#avcard{position:absolute;pointer-events:none;background:var(--paper);border:1px solid var(--edge);padding:5px 8px;font-size:12.5px;z-index:3;
  max-width:240px;box-shadow:0 3px 10px #0005}#avcard b{font-family:var(--head)}
#avpop{position:fixed;z-index:9;background:var(--raised);border:1px solid var(--gold);padding:8px;box-shadow:0 6px 18px #0008;max-width:300px;font-size:13px;white-space:pre-line}
#avnew{position:absolute;inset:0;z-index:4;background:#0006;display:grid;place-items:center}#avnew>div{width:min(460px,94%);max-height:94%;overflow:auto}
.advlogin{display:flex;flex-direction:column;gap:8px;max-width:340px;margin:auto}.advlogin input{font-size:16px}.advlogin .row{display:flex;gap:8px;justify-content:center}
.advlogin .avlogo{width:96px;margin:0 auto}
@media (max-width:900px){#advbody{grid-template-columns:1fr;grid-template-rows:minmax(0,1fr) auto}#avrail{flex-direction:row;justify-content:space-around;grid-row:2}
  #avmain{grid-row:1}#avrail .grow{display:none}#avside{top:auto;left:8px;width:auto;max-height:46%}}`));
}
function advBuild() {
  if ($('advbody')) return;
  advStyle();
  const panes = h('div', { id: 'avpanes' },
    h('div', { id: 'avp-map', class: 'avpane' }, h('canvas', { id: 'avcv' }),
      h('div', { id: 'avctl' },
        h('button', { class: 'ib avz', onclick: () => amZoom(1.4), tip: S('Zoom in (wheel)'), 'aria-label': S('Zoom in') }, '+'),
        h('button', { class: 'ib avz', onclick: () => amZoom(1 / 1.4), tip: S('Zoom out (wheel)'), 'aria-label': S('Zoom out') }, '−'),
        aib('expand', S('Fit the whole map'), () => { AM.cam = amFit(); amDraw(); }),
        aib('position-marker', S('Find my group'), () => amFind())),
      h('div', { id: 'avside' }), h('div', { id: 'avcard', class: 'hide' })),
    ...AV_TABS.filter(t => t[0] !== 'map' && t[0] !== 'hero').map(t => h('div', { id: 'avp-' + t[0], class: 'avpane' })));
  $('map').append(h('div', { id: 'advbody' }, h('div', { id: 'avrail' }),
    h('div', { id: 'avmain' }, h('div', { id: 'avtop' }), h('div', { id: 'avnext', role: 'button', tabindex: '0' }), panes)));
  $('avnext').addEventListener('click', () => { const n = AVN.next; if (n && n.go) n.go(); });
  document.addEventListener('keydown', advKeys);
  amWire();
  document.addEventListener('pointerdown', e => {          // a click elsewhere closes a confirmation
    const pop = $('avpop');
    if (pop && !pop.contains(e.target)) pop.remove();
  }, true);
}
/** Draw a part of the page again only when its key changed; never under a field being typed in. */
function part(el, key, fn) {
  if (!el || el._k === key) return;
  const a = document.activeElement;
  if (a && el.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) {
    if (!a._avwait) { a._avwait = 1; a.addEventListener('blur', () => { a._avwait = 0; setTimeout(renderAdv, 0); }, { once: true }); }
    return;
  }
  el._k = key;
  const sc = el.scrollTop;
  el.replaceChildren(...[fn()].flat().filter(Boolean));
  el.scrollTop = sc;
}
function avPop(e, ...kids) {
  const old = $('avpop');
  if (old) old.remove();
  const b = (e && e.currentTarget) || document.body, r = b.getBoundingClientRect();
  const pop = h('div', { id: 'avpop' }, ...kids);
  document.body.append(pop);
  pop.style.left = Math.max(6, Math.min(r.left, innerWidth - pop.offsetWidth - 6)) + 'px';
  pop.style.top = (r.bottom + 6 + pop.offsetHeight > innerHeight ? Math.max(6, r.top - pop.offsetHeight - 6) : r.bottom + 6) + 'px';
  return pop;
}
/** "Sure?" next to the button that asked, with yes / no icons (in place of the browser's dialog). */
function avConfirm(e, text, fn) {
  const pop = avPop(e, h('div', null, text), h('div', { class: 'avrow', style: 'justify-content:flex-end;margin-top:6px' },
    aib('cancel', S('No'), () => pop.remove()), aib('check-mark', S('Yes'), () => { pop.remove(); return fn(); }, 'good')));
}
const advMe = () => { const A = advS(); return A && A.characters.find(c => c.name === AVN.char) || null; };
const advGroup = () => { const A = advS(), c = advMe(); return A && c && c.group != null ? A.groups.find(g => g.id === c.group) || null : null; };
function advTown() {
  const A = advS(), c = advMe(), g = advGroup();
  if (g) return g.here.settlement;
  return c && A.solo ? A.solo[c.name] || null : null;
}
function setTab(t) {
  if (t === 'hero') {                                    // the character sheet: its column beside the map, or the phone's view
    if (innerWidth <= 900) { showView('sheet'); return; }
    AVN.sheet = !AVN.sheet; store('advsheet', AVN.sheet);
    renderAdv();
    amDraw();
    return;
  }
  AVN.tab = t; store('advtab', t);
  renderAdv();
}

/** The Adventure, or the fight: while the group fights the map pane shows the fight (world.js mapMode). */
function renderAdv() {
  if (!advOn()) return;
  advBuild();
  document.body.classList.add('adv');
  document.body.classList.toggle('avnosheet', !AVN.sheet);
  const on = mapMode() === 'adv';
  document.body.classList.toggle('advmode', on);
  if ($('mapmode')) $('mapmode').classList.add('hide');
  const A = advS();
  if (!A) return;
  if (!A.account) { advLogout(); return; }
  if (!AVN.char || !A.characters.some(c => c.name === AVN.char)) AVN.char = A.characters.length ? A.characters[0].name : null;
  const g = advGroup(), c = advMe(), town = advTown();
  const L = wordsLang || '';
  const enc = g && g.encounter ? JSON.stringify([g.encounter.label, g.encounter.text, g.x, g.y]) : null;
  if (enc && enc !== AVN.encSeen) {                      // a fight in the way: the map, the card open, the place flashing
    AVN.fold.enc = false;
    AVN.tab = 'map';
    AM.flash = { at: [g.x, g.y], t0: performance.now() };
  }
  AVN.encSeen = enc;
  if (AVN.route && (!g || !g.lead)) AVN.route = null;     // (a fight only pauses the way: the rest waits for after it)
  if (AVN.route && g && !g.encounter && !g.fight) {       // the group stands elsewhere now (a lost fight's retreat): planned again
    const f = AVN.route.path[0];
    if (!f || Math.max(Math.abs(f[0] - g.x), Math.abs(f[1] - g.y)) !== 1) {
      const way = AVN.route.way.filter(w => !(w[0] === g.x && w[1] === g.y));
      AVN.route = null;
      for (const w of way) amPlan(w, true);
      if (AVN.route) return;                              // (a plan draws the page itself)
    }
  }
  const nx = AVN.next = advNext(A, g, c);
  part($('avnext'), JSON.stringify([nx.icon, nx.text, !!nx.go]), () => {
    $('avnext').classList.toggle('idle', !nx.go);
    $('avnext').title = nx.go ? S('Click: go there') : '';
    return [ai(nx.icon), h('span', null, nx.text), nx.go ? h('span', { class: 'k' }, '➜') : null];
  });
  part($('avrail'), JSON.stringify([AVN.tab, AVN.sheet, g && g.quests.filter(q => q.stage === 'ready').length,
    g && g.requests.length, !!town, L]), () => advRail(A, g, town));
  part($('avtop'), JSON.stringify([A.characters, AVN.char, g && [g.name, g.purse, g.admin], A.slots, L]), () => advTop(A, c, g));
  for (const [t] of AV_TABS) { const p = $('avp-' + t); if (p) p.classList.toggle('on', AVN.tab === t); }
  if (AVN.tab === 'map') {
    part($('avside'), JSON.stringify([g, A.invites, A.asked, c && c.name, AVN.fold, A.max_quests, AVN.route, L]), () => advSidecards(A, g, c));
    if (on) amDraw();
  }
  if (AVN.tab === 'town') {
    advShopFetch(c, town);
    part($('avp-town'), JSON.stringify([town, g && [g.id, g.lead, g.pack], c, AVN.shop, AVN.shopData, L]), () => advTownPage(A, town, g, c));
    const st = $('avstock'), d = AVN.shopData;
    if (st && d) part(st, JSON.stringify([AVN.q, d.key, d.purse, d.stock.length, d.own, L]), () => advStock(d, town.shops.find(s => s.key === d.key) || {}, c));
  }
  if (AVN.tab === 'group') part($('avp-group'), JSON.stringify([g, A.all_groups, A.online, A.invites, A.asked, c,
    ST.character && ST.character.name === (c && c.name) ? (ST.character.inventory || []).map(e => [e.name, e.qty]) : null, L]), () => advGroupPage(A, g, c));
  if (AVN.tab === 'quests') part($('avp-quests'), JSON.stringify([g && [g.quests, g.lead, g.here.settlement && g.here.settlement.id], A.max_quests, L]),
    () => advQuestPage(A, g));
  if (AVN.tab === 'log') part($('avp-log'), JSON.stringify([g && g.log, L]), () => advLogPage(g));
  if (AVN.newChar || (A.characters.length === 0 && !$('avnew'))) advNewChar(A);
}
function advRail(A, g, town) {
  const ready = g ? g.quests.filter(q => q.stage === 'ready').length : 0;
  const counts = { quests: ready || null, group: g && g.requests.length ? g.requests.length : null };
  const out = [];
  for (const [t, icon, words] of AV_TABS) {
    if (t === 'log') out.push(h('span', { class: 'grow' }));
    const k = AV_TABS.findIndex(x => x[0] === t) + 1;
    const b = aib(icon, (t === 'town' && !town ? S('Town (you are out in the wilds)') : t === 'hero' ? S('Character sheet: show or hide it')
      : S(words)) + ` (${k})`, () => setTab(t), (t === 'hero' ? AVN.sheet && innerWidth > 900 : AVN.tab === t) ? 'on' : '');
    if (counts[t]) b.append(h('span', { class: 'ct' }, counts[t]));
    if (t === 'town' && !town) b.style.opacity = '.55';
    out.push(b);
  }
  out.push(aib('cog', S('Account'), e => advAccount(e)));
  return out;
}
function advAccount(e) {
  const o = h('input', { type: 'password', placeholder: S('Old password') }), n = h('input', { type: 'password', placeholder: S('New password') });
  const c = advMe();
  avPop(e, h('b', null, advS().nick),
    h('div', { class: 'avrow', style: 'margin-top:6px' }, o, n, aib('padlock', S('Change the password'), () => act('adv_password', { old: o.value, new: n.value }))),
    c ? h('div', { class: 'avrow', style: 'margin-top:6px' }, h('span', { class: 'grow small' }, S('Archive {0}', c.name)),
      aib('locked-chest', S('Archive this character: frees the slot; the DM can bring them back'),
        ev => avConfirm(ev, S('Archive {0}? Only the DM can bring them back.', c.name), () => aact('adv_archive')), 'warn')) : null,
    h('div', { class: 'avrow', style: 'margin-top:6px' }, h('span', { class: 'grow small' }, S('Log out')), aib('exit-door', S('Log out'), advLogout, 'bad')));
}
function advTop(A, c, g) {
  const chips = A.characters.map(x => {
    const pct = x.max_hp ? x.hp / x.max_hp : 0;
    const ring = pct <= .25 ? 'var(--bad)' : pct <= .5 ? 'var(--warn)' : 'var(--good)';
    return h('span', { class: 'avchip' + (x.name === AVN.char ? ' on' : ''), style: `border-color:${ring}`,
      onclick: () => { AVN.char = x.name; store('advchar', x.name); AVN.shop = null; AVN.shopData = null; renderAdv();
        if (ST.me.characters.includes(x.name)) act('choose', { character: x.name }, true); amFind(); },
      tip: `${x.name}\n${x.summary}\n${S('HP')} ${x.hp}/${x.max_hp} · ${S('XP')} ${x.xp}\n${x.at || S('in the wilds')}` +
        (x.level_up ? '\n★ ' + S('Ready to level up') : '') }, x.name.slice(0, 1).toUpperCase(), x.level_up ? h('span', { class: 'st' }, '★') : null);
  });
  if (A.characters.length < A.slots) chips.push(h('span', { class: 'avchip', style: 'border-style:dashed', onclick: () => { AVN.newChar = true; renderAdv(); },
    tip: S('A new level 1 character ({0} of {1} slots used)', A.characters.length, A.slots) }, '+'));
  const out = [...chips];
  if (c) {
    const pct = c.next_xp ? Math.max(0, Math.min(1, c.xp / c.next_xp)) : 1;
    out.push(h('span', { class: 'avstat', tip: S('{0}: hit points', c.name) }, ai('heart-plus'), `${c.hp}/${c.max_hp}`),
      h('span', { class: 'avstat', tip: S("{0}'s purse", c.name) }, ai('two-coins'), avMoney(c.purse)),
      h('span', { class: 'avstat', tip: S('Experience: {0} of {1} for the next level', c.xp, c.next_xp || '—') }, ai('upgrade'),
        h('span', { class: 'avxp' }, h('i', { style: `width:${Math.round(pct * 100)}%` }))),
      c.level_up ? aib('upgrade', S('Level up {0}', c.name), () => aact('adv_level_up'), 'acc') : null);
  }
  out.push(h('span', { style: 'flex:1' }));
  if (g) out.push(h('span', { class: 'avstat', tip: S('Your group') + (g.admin ? ' · ' + S('you are admin') : '') + '\n' + S('Purse: {0}', g.purse) },
    ai('flying-flag'), h('b', null, g.name)));
  return out;
}

// ---------------------------------------------------------------- the next sensible thing (Packing Merchant's Next line)
const COMPASS = ['east', 'south-east', 'south', 'south-west', 'west', 'north-west', 'north', 'north-east'];
function advDir(from, to) {
  if (!to || (from[0] === to[0] && from[1] === to[1])) return S('here');
  const a = Math.atan2(to[1] - from[1], to[0] - from[0]);
  return S(COMPASS[((Math.round(a / (Math.PI / 4)) % 8) + 8) % 8]);
}
/** Where a quest wants the group next: its target (a scout's next unseen place), its destination, or home for the reward. */
function advQuestSpot(q) {
  const M = advS().map;
  const at = id => { const s = M.settlements.find(x => x.id === id); return s ? [s.x, s.y] : null; };
  if (q.stage === 'ready') return at(q.settlement);
  if (q.kind === 'deliver' || q.kind === 'escort') return at(q.dest);
  if (q.kind === 'scout') return q.targets.find(t => !q.visited.some(v => v[0] === t[0] && v[1] === t[1])) || q.target;
  return q.target;
}
/** To a place on the map: leading, the way there planned (read it, then set out); else the view brought round to it. */
function advGoTo(t) {
  if (!t) return;
  AVN.tab = 'map'; store('advtab', 'map');
  const g = advGroup(), M = advS().map;
  renderAdv();
  setTimeout(() => {
    if (g && g.lead && !g.encounter && !g.fight && M.cells[t[1] * M.w + t[0]] && !(t[0] === g.x && t[1] === g.y)) amPlan(t);
    amLook({ kind: 'x', target: t });
  }, 30);
}
function advNext(A, g, c) {
  const M = A.map;
  if (!c) return { icon: 'person', text: S('Make your first character'), go: () => { AVN.newChar = true; renderAdv(); } };
  if (g && g.fight) return { icon: 'crossed-swords', text: g.fight.phase === 'over' ? S('The fight is over: the spoils are counted') : S('Your group is fighting'), go: null };
  if (g && g.encounter) return { icon: 'crossed-swords', text: S('In the way: {0} - fight or flee', g.encounter.label), go: () => setTab('map') };
  if (c.level_up) return { icon: 'upgrade', text: S('{0} can level up', c.name), go: () => aact('adv_level_up') };
  if (A.invites.length) return { icon: 'envelope', text: S('{0} invites you', A.invites[0].name), go: () => setTab('map') };
  if (!g) return { icon: 'flying-flag', text: S('Found a group, or ask to join one: quests and fights are for groups'), go: () => setTab('group') };
  if (g.admin && g.requests.length) return { icon: 'shaking-hands', text: S('{0} asks to join', g.requests[0].char), go: () => setTab('group') };
  const here = g.here.settlement, me = [g.x, g.y];
  const hurt = g.members.filter(m => m.max_hp && m.hp < m.max_hp / 2);
  const ready = g.quests.find(q => q.stage === 'ready' && q.kind !== 'deliver' && q.kind !== 'escort');
  if (ready) {
    if (here && here.id === ready.settlement) return { icon: 'laurels-trophy', text: S('Claim the reward: {0}', ready.title), go: () => setTab('quests') };
    const s = M.settlements.find(x => x.id === ready.settlement);
    return { icon: 'laurels-trophy', text: S('{0} is done: back to {1} ({2}) for the reward', ready.title, s ? s.name : '?', advDir(me, s && [s.x, s.y])),
      go: () => advGoTo(s && [s.x, s.y]) };
  }
  if (hurt.length && here) return { icon: 'night-sleep', text: S('{0} wounded: a bed at the tavern heals everyone', hurt.map(m => m.char).join(', ')),
    go: () => { const t = here.shops.find(x => x.kind === 'tavern'); if (t) { AVN.shop = t.key; AVN.shopData = null; } setTab('town'); } };
  if (hurt.length && !here) {
    const s = M.settlements.reduce((b, x) => !b || Math.hypot(x.x - g.x, x.y - g.y) < Math.hypot(b.x - g.x, b.y - g.y) ? x : b, null);
    return { icon: 'night-sleep', text: S('Wounded: head back to {0} ({1}) to rest', s.name, advDir(me, [s.x, s.y])), go: () => advGoTo([s.x, s.y]) };
  }
  const q = g.quests.find(x => x.stage === 'active');
  if (q) {
    const t = advQuestSpot(q);
    return { icon: QUEST_ICON[q.kind] || 'scroll-unfurled', text: S('Next: {0} - {1}', q.title, advDir(me, t)), go: () => advGoTo(t) };
  }
  if (here && here.board.length) return { icon: 'scroll-unfurled', text: S('{0} has work on its board', here.name),
    go: () => { const t = here.shops.find(x => x.kind === 'tavern'); if (t) { AVN.shop = t.key; AVN.shopData = null; } setTab('town'); } };
  return { icon: 'treasure-map', text: here ? S('Explore: click a place on the map to plan the way') : S('Explore, or head for a settlement'), go: () => setTab('map') };
}
/** The page's keys: 1-6 the tabs; on the map F finds the group, + and - zoom, Enter sets out; in a shop typing finds;
 *  Esc closes what is open (a question, the find, a pinned card, the planned way). */
function advKeys(e) {
  if (!advOn() || !document.body.classList.contains('advmode')) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '');
  const pop = $('avpop');
  if (e.key === 'Escape') {
    if (pop) { pop.remove(); return; }
    if (AVN.q && AVN.tab === 'town') { if (document.activeElement) document.activeElement.blur(); advFind(''); return; }
    if (AVN.pinned) { AVN.pinned = null; $('avcard').classList.add('hide'); amDraw(); return; }
    if (AVN.tab === 'map') amUnplan(true);
    return;
  }
  if (e.key === 'Enter' && pop) {                          // the open question's yes
    const yes = pop.querySelector('button.good, button.acc');
    if (yes) { e.preventDefault(); yes.click(); }
    return;
  }
  if (typing || e.ctrlKey || e.altKey || e.metaKey || $('avnew')) return;
  if (/^[1-6]$/.test(e.key)) { e.preventDefault(); setTab(AV_TABS[+e.key - 1][0]); return; }
  if (AVN.tab === 'map') {
    if (e.key === 'Enter' && AVN.route) { e.preventDefault(); amSetOut(); }
    else if (e.key === 'f' || e.key === 'F') amFind();
    else if (e.key === '+' || e.key === '=') amZoom(1.4);
    else if (e.key === '-') amZoom(1 / 1.4);
  } else if (AVN.tab === 'town' && e.key.length === 1 && /\S/.test(e.key) && $('avfind')) {
    e.preventDefault();
    advFind(AVN.q + e.key);
    const i = $('avfind');
    i.focus(); i.setSelectionRange(i.value.length, i.value.length);
  }
}

// ---------------------------------------------------------------- the cards over the map
function card(key, icon, title, body, cls = '', extra) {
  const folded = !!AVN.fold[key];
  return h('div', { class: 'avcard ' + cls + (folded ? ' fold' : '') },
    h('div', { class: 'hd', onclick: () => { AVN.fold[key] = !folded; store('advfold', AVN.fold); renderAdv(); }, tip: folded ? S('Unfold') : S('Fold') },
      ai(icon), h('span', { class: 'grow' }, title), extra || null, h('span', { class: 'dim' }, folded ? '▸' : '▾')),
    h('div', { class: 'bd' }, ...[body].flat()));
}
function advSidecards(A, g, c) {
  if (!c) return [];
  const out = [];
  if (A.invites.length) out.push(card('inv', 'envelope', S('Invitations'), A.invites.map(i => h('div', { class: 'avrow' },
    h('span', { class: 'grow' }, S('{0} invites you', i.name)),
    aib('check-mark', S('Join {0} with {1}', i.name, AVN.char), () => aact('adv_invite_accept', { group: i.group }), 'good'),
    aib('cancel', S('Decline'), () => act('adv_invite_decline', { group: i.group }), 'bad')))));
  if (!g) {
    out.push(card('nogroup', 'flying-flag', S('No group yet'), [h('div', { class: 'small dim' },
      S('Quests and fights are for groups: found one, or ask to join one.')),
      h('div', { class: 'avrow', style: 'margin-top:4px' }, aib('three-friends', S('Groups'), () => setTab('group'), 'acc'))]));
    return out;
  }
  if (AVN.route && !g.encounter && !g.fight) {
    const r = amReadout(A.map, g, AVN.route), t = A.map.tiers[r.top];
    out.push(card('route', 'footsteps', S('The way: {0} steps', r.steps), [
      h('div', { class: 'small' }, t ? S('Through the {0} (levels {1}-{2})', S(t.name).toLowerCase(), t.levels[0], t.levels[1]) : ''),
      h('div', { class: 'small ' + (r.risk >= 60 ? 'bad' : r.risk >= 30 ? 'warn' : 'good'),
        tip: S('As rumour has it: each step out of the settlements may meet a fight - more the farther out, less on a road, more at ruins and strange places. The way picked keeps to the safer ground.') },
      S('About {0}% chance of a fight on the way', r.risk)),
      r.town ? h('div', { class: 'small' }, ai('village'), ' ' + S('Ends in {0}', r.town.name)) : null,
      ...r.hits.map(q => h('div', { class: 'small acc' }, ai(QUEST_ICON[q.kind] || 'scroll-unfurled'), ' ' + S('Passes {0}', q.title))),
      h('div', { class: 'avrow', style: 'margin-top:4px' },
        aib('walk', S('Set out (Enter, or click the end again)'), () => amSetOut(), 'acc'),
        AVN.route.way.length > 1 ? aib('return-arrow', S('Take the last stop back (right-click)'), () => amUnplan(false)) : null,
        aib('cancel', S('Forget this way (Esc)'), () => amUnplan(true), 'bad'))]));
  }
  if (g.fight) {
    const f = g.fight;
    out.push(card('fight', 'crossed-swords', f.phase === 'over' ? (f.result ? S('Victory!') : S('Defeat')) : S('Fighting - round {0}', f.round),
      g.lead ? h('div', { class: 'avrow' }, aib('checkered-flag', f.phase === 'over' ? S('Collect the spoils') : S('End the fight'),
        () => act('adv_finish', { group: g.id }), 'acc')) : h('div', { class: 'small dim' }, S('The leader collects the spoils.')), 'enc'));
  } else if (g.encounter) {
    const e = g.encounter;
    out.push(card('enc', 'crossed-swords', e.label, [
      h('div', { class: 'small' }, e.text), e.why ? h('div', { class: 'small dim' }, e.why) : null,
      h('div', { class: 'small', tip: S('How hard the fight is for your group (the DMG rating)') }, S('Rating: {0}', e.rating)),
      g.lead ? h('div', { class: 'avrow', style: 'margin-top:4px' },
        aib('crossed-swords', S('Fight: on the battle map, your wounds as they are'), () => act('adv_fight', { group: g.id }), 'bad'),
        e.cornered ? h('span', { class: 'small bad' }, S('No escape!'))
          : aib('run', e.quest ? S('Withdraw: no fight, no progress - the quest waits') : g.here.chunk.road
            ? S('Flee: 65% to get away (half the time, more on a road); else you must fight') : S('Flee: 50% to get away (more on a road); else you must fight'),
          () => act('adv_flee', { group: g.id })))
        : h('div', { class: 'small dim' }, S('The leader decides: fight or flee.'))], 'enc'));
  }
  out.push(card('group', 'three-friends', g.name, g.members.map(m => advMember(m, false)), '',
    h('span', { class: 'dim small', tip: S('Purse') }, g.purse)));
  const qs = g.quests;
  out.push(card('quests', 'scroll-unfurled', S('Quests') + ` ${qs.length}/${A.max_quests}`, qs.length ? qs.map(q => h('div', { class: 'avrow',
    style: 'cursor:pointer', onclick: () => amLook(q), tip: q.title + '\n' + q.text + '\n' + S('Click: show it on the map') },
  ai(QUEST_ICON[q.kind] || 'scroll-unfurled'), h('span', { class: 'grow small' }, q.title),
  h('span', { class: 'small ' + (q.stage === 'ready' ? 'good' : 'dim') }, q.stage === 'ready' ? '✔' : q.progress)))
    : [h('div', { class: 'small dim' }, S('No quests: a tavern has a board.'))]));
  return out;
}
function advMember(m, actions, g) {
  const pct = m.max_hp ? m.hp / m.max_hp : 0;
  return h('div', { class: 'avmember', tip: `${m.char} (${m.player})\n${S('Level {0}', m.level)} · ${S('HP')} ${m.hp}/${m.max_hp} · ${S('XP')} ${m.xp}` +
      (m.online ? '\n' + S('on the page now') : '') },
  h('span', { class: 'avchip', style: `width:24px;height:24px;font-size:11px;border-color:${pct <= .25 ? 'var(--bad)' : pct <= .5 ? 'var(--warn)' : 'var(--good)'}` },
    m.char.slice(0, 1).toUpperCase(), m.level_up ? h('span', { class: 'st' }, '★') : null),
  h('span', { class: 'grow' }, h('span', { class: 'small' }, m.char, m.online ? h('span', { class: 'good' }, ' ●') : null),
    h('div', { class: 'avbar' }, h('i', { class: pct <= .25 ? 'lo' : pct <= .5 ? 'mid' : '', style: `width:${Math.round(pct * 100)}%` }))),
  actions && m.mine ? aib('exit-door', S('{0} leaves the group', m.char), e => avConfirm(e, S('{0} leaves {1}?', m.char, g.name),
    () => act('adv_leave', { char: m.char })), 'bad hov') : null,
  actions && g && g.admin && !m.mine ? aib('return-arrow', S('Kick {0}', m.char), e => avConfirm(e, S('Kick {0}?', m.char),
    () => act('adv_kick', { group: g.id, char: m.char })), 'bad hov') : null);
}

// ---------------------------------------------------------------- Town
function advShopFetch(c, town) {
  if (!c || !town) { AVN.shopData = null; AVN.shopFor = null; return; }
  if (!AVN.shop || !town.shops.some(s => s.key === AVN.shop)) AVN.shop = town.shops[0].key;
  const key = AVN.shop + '|' + town.id + '|' + c.name + '|' + c.purse + '|' + c.level;
  if (AVN.shopFor === key) return;
  AVN.shopFor = key;
  aact('adv_shop', { shop: AVN.shop }, true).then(r => { if (r && r.data && AVN.shopFor === key) { AVN.shopData = r.data; renderAdv(); } });
}
const KIND_WORDS = { M: 'Melee weapons', R: 'Ranged weapons', A: 'Ammunition', LA: 'Light armour', MA: 'Medium armour', HA: 'Heavy armour',
  S: 'Shields', P: 'Potions', G: 'Gear', FD: 'Food and drink', T: 'Tools', AT: "Artisan's tools", INS: 'Instruments', GS: 'Gaming sets',
  SC: 'Scrolls', SCF: 'Spellcasting foci', WD: 'Wands', RD: 'Rods', RG: 'Rings', '': 'Wondrous items' };
const short = n => n.length > 22 ? n.slice(0, 20) + '…' : n;
function advTownPage(A, town, g, c) {
  if (!c) return advEmpty('village', S('Make a character first.'));
  if (!town) return advEmpty('village', S('{0} is out in the wilds: towns, villages and camps have shops and a tavern.', c.name));
  const sh = town.shops.find(s => s.key === AVN.shop) || town.shops[0];
  const out = [h('div', { class: 'avsec' }, h('h3', null, ai('village'), h('span', { class: 'grow' }, town.name), h('span', { class: 'dim small' }, S(town.kind))),
    h('div', { class: 'avshops' }, ...town.shops.map(s => h('button', { class: 'ib' + (s.key === sh.key ? ' on' : ''),
      onclick: () => { AVN.shop = s.key; AVN.shopData = null; AVN.q = ''; renderAdv(); },
      tip: `${s.name}\n${s.owner.name}, ${S(s.owner.title)} (${s.owner.race})\n${s.owner.trait}` }, ai(SHOP_ICON[s.kind] || 'shop'), h('span', { class: 'small' }, S(s.label))))),
    h('div', { class: 'avkeeper' }, h('b', null, sh.name), h('span', { class: 'dim' }, ` · ${sh.owner.name}, ${S(sh.owner.title)}: `),
      h('i', null, '"' + sh.owner.greeting + '"')))];
  if (sh.kind === 'tavern') out.push(advBoard(town, g));
  const d = AVN.shopData;
  if (!d || d.key !== sh.key) { out.push(h('div', { class: 'avsec dim small' }, S('Loading…'))); return out; }
  if (d.services.length) out.push(h('div', { class: 'avsec' }, h('h3', null, ai('hand'), S('Services')), h('div', { class: 'avtiles' },
    ...d.services.map(s => h('div', { class: 'avtile', onclick: e => avConfirm(e, `${S(s.label)}: ${avMoney(s.cp)}?\n${S(s.text)}`,
      () => aact('adv_service', { shop: sh.key, what: s.key })), tip: `${S(s.label)} - ${avMoney(s.cp)}\n${S(s.text)}` },
    ai(SERVICE_ICON[s.key] || 'hand'), h('span', null, avMoney(s.cp)))))));
  if (d.spells.length) {
    const lv = {};
    for (const s of d.spells) (lv[s.level] = lv[s.level] || []).push(s);
    out.push(h('div', { class: 'avsec' }, h('h3', null, ai('spell-book'), S('Spells taught here')),
      ...Object.keys(lv).map(l => advFold('spells' + l, l === '0' ? S('Cantrips') : S('Level {0}', l), lv[l].length, h('div', { class: 'avlist' },
        ...lv[l].map(s => h('div', { tip: `${s.name}\n${s.school} · ${s.class}` }, ai('spell-book'), h('span', { class: 'grow' }, s.name),
          h('span', { class: 'small' + (s.cp > d.purse ? ' bad' : '') }, avMoney(s.cp)),
          aib('upgrade', S('Learn {0}', s.name), e => avLearn(e, sh, s, c))))), true))));
  }
  if (d.stock.length) {                                  // the find line stays put while the goods under it change (advStock)
    out.push(h('div', { class: 'avsec' }, h('h3', null, ai('shopping-cart'), h('span', { class: 'grow' }, S('For sale')),
      h('span', { class: 'small dim', tip: S("{0}'s purse", c.name) }, ai('two-coins'), ' ' + avMoney(d.purse))),
    h('input', { id: 'avfind', placeholder: S('Find…'), value: AVN.q, style: 'width:100%;margin-bottom:4px' + (AVN.q ? '' : ';display:none'),
      oninput: e => { AVN.q = e.target.value; renderAdv(); } }),
    h('div', { id: 'avfindhint', class: 'small dim', style: 'margin-bottom:4px' + (AVN.q ? ';display:none' : '') }, S('Type to find (Esc clears)')),
    h('div', { id: 'avstock' })));
  }
  if ((d.own || []).length) {
    out.push(h('div', { class: 'avsec' }, h('h3', null, ai('sell-card'), S("Sell from {0}'s pack", c.name)), h('div', { class: 'avtiles' },
      ...d.own.map(e => h('div', { class: 'avtile', tip: `${e.name} ×${e.qty}` + (e.equipped ? '\n' + S('in use') : '') + `\n${S('{0} each', avMoney(e.cp))}\n${S('Click: sell')}`,
        onclick: ev => avSell(ev, sh, { name: e.name, qty: e.qty, worth: e.cp }, false), style: e.equipped ? 'opacity:.6' : '' },
      e.icon ? gi(e.icon) : ai('knapsack'), e.qty > 1 ? h('span', { class: 'q' }, e.qty) : null,
      h('span', null, short(e.name)), h('span', { class: 'good' }, avMoney(e.cp)))))));
  }
  if (g && sh.kind !== 'tavern' && g.pack.some(e => !e.quest && e.worth)) {
    out.push(h('div', { class: 'avsec' }, h('h3', null, ai('sell-card'), S('Sell from the pack')), h('div', { class: 'avtiles' },
      ...g.pack.filter(e => !e.quest && e.worth).map(e => h('div', { class: 'avtile', tip: `${e.name} ×${e.qty}\n${S('{0} each', avMoney(e.worth))}\n${S('Click: sell')}`,
        onclick: ev => avSell(ev, sh, e) }, e.icon ? gi(e.icon) : ai('knapsack'), e.qty > 1 ? h('span', { class: 'q' }, e.qty) : null,
      h('span', null, short(e.name)), h('span', { class: 'good' }, avMoney(e.worth)))))));
  }
  return out;
}
function advStock(d, sh, c) {
  const owned = {};
  for (const e of d.own || []) owned[e.name] = (owned[e.name] || 0) + e.qty;
  const rows = d.stock.filter(r => !AVN.q || r.name.toLowerCase().includes(AVN.q.toLowerCase()));
  if (!rows.length) return h('div', { class: 'small dim' }, S('Nothing here matches.'));
  const kinds = {};
  for (const r of rows) (kinds[r.kind || ''] = kinds[r.kind || ''] || []).push(r);
  return Object.keys(kinds).sort().map(k => advFold('kind' + k, S(KIND_WORDS[k] || 'Other'), kinds[k].length, h('div', { class: 'avtiles' },
    ...kinds[k].map(r => h('div', { class: 'avtile', tip: `${r.name}\n${avMoney(r.cp)}` + (r.magic ? '\n' + S(r.rarity) : '') +
        (owned[r.name] ? '\n' + S('{0} has {1}', c.name, owned[r.name]) : '') + '\n' + S('Click: buy'),
      onclick: e => avBuy(e, sh, r, d.purse), style: r.cp > d.purse ? 'opacity:.5' : '' },
    owned[r.name] ? h('span', { class: 'own' }, '×' + owned[r.name]) : null,
    r.icon ? gi(r.icon) : ai('knapsack'), h('span', null, short(r.name)),
    h('span', { class: r.magic ? 'acc' : 'dim' }, avMoney(r.cp))))), !!AVN.q));
}
/** The find line in a shop: shown while it has words (typing over the goods starts it), hidden again by Esc. */
function advFind(q) {
  AVN.q = q;
  const i = $('avfind'), hint = $('avfindhint');
  if (i) { i.value = q; i.style.display = q ? '' : 'none'; }
  if (hint) hint.style.display = q ? 'none' : '';
  renderAdv();
}
function advFold(key, title, count, body, open) {
  const d = h('details', { class: 'avfold' }, h('summary', null, title, h('span', { class: 'dim' }, ` (${count})`)), body);
  d.open = AVN.fold[key] === undefined ? !!open : AVN.fold[key] === true;
  d.addEventListener('toggle', () => { AVN.fold[key] = d.open; store('advfold', AVN.fold); });
  return d;
}
async function avLearn(e, sh, s, c) {
  const at = { currentTarget: e.currentTarget };
  const r = await aact('adv_learn', { shop: sh.key, spell: s.name }, true);
  if (r) { say(r.text); return; }
  const inp = h('input', { placeholder: S('The spell to forget') });
  const pop = avPop(at, h('div', null, S('Which spell does {0} forget to learn {1}?', c.name, s.name)),
    h('div', { class: 'avrow', style: 'margin-top:6px' }, inp,
      aib('check-mark', S('Learn {0}', s.name), () => { pop.remove(); return aact('adv_learn', { shop: sh.key, spell: s.name, forget: inp.value }); }, 'good'),
      aib('cancel', S('No'), () => pop.remove())));
}
/** A quantity picker: − n + and the total, for buying or selling. */
function avQty(max, each, onTotal) {
  let n = 1;
  const b = h('b', null, '1'), tot = h('span', { class: 'small' });
  const show = () => { b.textContent = n; tot.textContent = '= ' + avMoney(n * each); onTotal && onTotal(n); };
  const step = k => { n = Math.max(1, Math.min(max, n + k)); show(); };
  const el = h('span', { class: 'avqty' }, h('button', { class: 'ib', onclick: () => step(-1), onwheel: e => { e.preventDefault(); step(e.deltaY < 0 ? 1 : -1); } }, '−'), b,
    h('button', { class: 'ib', onclick: () => step(1) }, '+'), h('button', { class: 'ib small', onclick: () => step(max), tip: S('All') }, '»'), tot);
  show();
  return { el, get: () => n };
}
function avBuy(e, sh, r, purse) {
  const can = Math.max(1, Math.min(99, Math.floor(purse / Math.max(1, r.cp))));
  const q = avQty(can, r.cp);
  const pop = avPop(e, h('div', null, h('b', null, r.name), ' ', h('span', { class: 'dim' }, avMoney(r.cp))),
    h('div', { class: 'avrow', style: 'margin-top:6px' }, q.el, h('span', { class: 'grow' }),
      aib('shopping-cart', S('Buy (Enter)'), () => { pop.remove(); return aact('adv_buy', { shop: sh.key, item: r.name, qty: q.get() }); }, 'good'),
      aib('cancel', S('No'), () => pop.remove())));
}
function avSell(ev, sh, e, pack = true) {
  const q = avQty(e.qty, e.worth);
  const pop = avPop(ev, h('div', null, h('b', null, e.name), ' ', h('span', { class: 'dim' }, S('{0} each', avMoney(e.worth)))),
    h('div', { class: 'avrow', style: 'margin-top:6px' }, q.el, h('span', { class: 'grow' }),
      aib('sell-card', S('Sell (Enter)'), () => { pop.remove(); return aact('adv_sell', { shop: sh.key, item: e.name, qty: q.get(), pack }); }, 'good'),
      aib('cancel', S('No'), () => pop.remove())));
}
function advBoard(town, g) {
  const ban = town.banned_until;
  return h('div', { class: 'avsec' }, h('h3', null, ai('scroll-unfurled'), S('Quest board')),
    ban ? h('div', { class: 'small bad' }, S('No work for your group until {0}: you dropped a job here.', new Date(ban * 1000).toLocaleString())) : null,
    !g ? h('div', { class: 'small dim' }, S('Quests are taken by groups: found or join one.')) : null,
    ...(town.board.length ? town.board.map(q => advQuestCard(q, g, { take: g && g.lead && !ban }))
      : [h('div', { class: 'small dim' }, S('Nothing pinned up right now.'))]));
}
function advEmpty(icon, text) { return h('div', { class: 'avempty' }, ai(icon), h('div', null, text)); }

// ---------------------------------------------------------------- Quests and the log
function advQuestCard(q, g, how = {}) {
  const here = g && g.here.settlement;
  return h('div', { class: 'avq' },
    h('div', { class: 'avrow' }, ai(QUEST_ICON[q.kind] || 'scroll-unfurled'), h('span', { class: 't grow' }, q.title),
      h('span', { class: 'small dim', tip: S('Danger: tier {0}', q.tier) }, '☠'.repeat(q.tier))),
    h('p', { class: 'small' }, q.text),
    h('div', { class: 'avrow small' },
      h('span', { class: 'avstat', tip: S('The reward') }, ai('two-coins'), avMoney(q.reward.cp)), h('span', { class: 'avstat' }, ai('upgrade'), `${q.reward.xp} XP`),
      q.progress ? h('span', { class: q.stage === 'ready' ? 'good' : 'dim' }, q.progress) : h('span', { class: 'dim' }, S('asks') + ' ' + q.giver),
      h('span', { class: 'grow' }),
      q.target ? aib('target-arrows', S('Show it on the map (leading: plan the way there)'), () => advGoTo(advQuestSpot(q))) : null,
      how.take ? aib('check-mark', S('Take this quest'), () => act('adv_take_quest', { group: g.id, quest: q.id }), 'good') : null,
      how.mine && g.lead && q.stage === 'ready' && here && here.id === q.settlement
        ? aib('laurels-trophy', S('Claim the reward'), () => act('adv_turn_in', { group: g.id, quest: q.id }), 'good') : null,
      how.mine && g.lead ? aib('cancel', S('Drop it (the settlement gives your group no work for a day)'),
        e => avConfirm(e, S("Drop {0}? The settlement won't give your group work for a day.", q.title),
          () => act('adv_cancel_quest', { group: g.id, quest: q.id })), 'bad hov') : null));
}
function advQuestPage(A, g) {
  if (!g) return advEmpty('scroll-unfurled', S('Quests are taken by groups: found or join one.'));
  if (!g.quests.length) return advEmpty('scroll-unfurled', S('No quests yet: the tavern of a settlement has a board.'));
  return h('div', { class: 'avsec' }, h('h3', null, ai('scroll-unfurled'), S('Quests') + ` ${g.quests.length}/${A.max_quests}`),
    ...g.quests.map(q => advQuestCard(q, g, { mine: true })));
}
function advLogPage(g) {
  if (!g) return advEmpty('open-book', S("Your group's story is written here."));
  return h('div', { class: 'avsec' }, h('h3', null, ai('open-book'), g.name), h('div', { class: 'avlist' },
    ...g.log.slice().reverse().map(l => h('div', null, h('span', { class: 'dim small', style: 'min-width:44px' },
      new Date(l.t * 1000).toTimeString().slice(0, 5)), h('span', { class: 'grow small' }, l.text)))));
}

// ---------------------------------------------------------------- Group
function advGroupPage(A, g, c) {
  if (!c) return advEmpty('three-friends', S('Make a character first.'));
  if (!g) return advNoGroup(A, c);
  const out = [h('div', { class: 'avsec' }, h('h3', null, ai('flying-flag'), h('span', { class: 'grow' }, g.name),
    h('span', { class: 'small dim' }, S('Leader: {0}', g.leader || '—') + (g.admin ? ' · ' + S('you are admin') : ''))),
  h('div', { class: 'avlist' }, ...g.members.map(m => h('div', null, advMember(m, true, g)))))];
  const gp = h('input', { type: 'number', min: 1, value: 1, style: 'width:70px', 'aria-label': S('Gold') });
  out.push(h('div', { class: 'avsec' }, h('h3', null, ai('two-coins'), h('span', { class: 'grow' }, S('Purse: {0}', g.purse))),
    h('div', { class: 'avrow' }, gp, aib('hand', S("Take that much gold into {0}'s purse", c.name), () => aact('adv_take_gold', { gp: gp.value })),
      aib('swap-bag', S("Put that much of {0}'s gold in the purse", c.name), () => aact('adv_put_gold', { gp: gp.value })),
      g.lead ? aib('trade', S('Share the purse evenly among the members'), e => avConfirm(e, S('Share the purse evenly?'), () => act('adv_share', { group: g.id }))) : null)));
  const mine = ST.character && ST.character.name === c.name ? (ST.character.inventory || []) : [];
  out.push(h('div', { class: 'avsec' }, h('h3', null, ai('knapsack'), h('span', { class: 'grow' }, S("The group's pack"))),
    g.pack.length ? h('div', { class: 'avtiles' }, ...g.pack.map(e => h('div', { class: 'avtile',
      tip: `${e.name} ×${e.qty}` + (e.worth ? '\n' + S('Worth {0} each', avMoney(e.worth)) : '') + (e.note ? '\n' + S(e.note) : '') +
        (e.quest ? '\n' + S('A quest item: it stays in the pack') : '\n' + S("Click: into {0}'s pack", c.name)),
      onclick: () => e.quest ? null : aact('adv_take', { item: e.name, qty: 1 }) },
    e.icon ? gi(e.icon) : ai(e.quest ? 'wax-seal' : 'knapsack'), e.qty > 1 ? h('span', { class: 'q' }, e.qty) : null,
    h('span', null, short(e.name)))))
      : h('div', { class: 'dim small' }, S('The pack is empty: loot from fights lands here.')),
    mine.length ? advFold('put', S("Put something of {0}'s in the pack", c.name), mine.length, h('div', { class: 'avtiles' },
      ...mine.map(e => h('div', { class: 'avtile', tip: S("{0}: into the group's pack", e.name), onclick: () => aact('adv_put', { item: e.name, qty: 1 }) },
        e.icon ? gi(e.icon) : ai('knapsack'), e.qty > 1 ? h('span', { class: 'q' }, e.qty) : null, h('span', null, short(e.name)))))) : null));
  if (g.admin) {
    const pw = h('input', { type: 'password', placeholder: S('New group password') });
    out.push(h('div', { class: 'avsec' }, h('h3', null, ai('key'), S('Admin')),
      advFold('reqs', S('Asking to join'), g.requests.length, h('div', { class: 'avlist' }, ...(g.requests.length ? g.requests.map(r => h('div', null,
        h('span', { class: 'grow' }, `${r.char} (${r.player})`),
        aib('check-mark', S('Let {0} in', r.char), () => act('adv_accept', { group: g.id, who: String(r.uid), char: r.char }), 'good'),
        aib('cancel', S('Turn {0} away', r.char), () => act('adv_decline', { group: g.id, who: String(r.uid) }), 'bad')))
        : [h('div', { class: 'dim small' }, S('Nobody.'))])), g.requests.length > 0),
      advFold('online', S('Players online'), A.online.length, h('div', { class: 'avlist' }, ...(A.online.length ? A.online.map(p => h('div', null,
        h('span', { class: 'grow' }, p.nick), g.invites.some(i => i.uid === p.uid) ? h('span', { class: 'dim small' }, S('invited'))
          : aib('envelope', S('Invite {0}', p.nick), () => act('adv_invite', { group: g.id, who: String(p.uid) })))) : [h('div', { class: 'dim small' }, S('Nobody else is on.'))]))),
      advFold('pw', S('Password'), 1, h('div', { class: 'avrow' }, pw, aib('padlock', S('Change the group password (other admins log in again)'),
        () => act('adv_group_password', { group: g.id, password: pw.value })),
      aib('exit-door', S('Log out as admin'), () => act('adv_group_logout', { group: g.id }))))));
  }
  return out;
}
function advFound(e, c) {
  const nm = h('input', { placeholder: S('Group name'), maxlength: 32 }), pw = h('input', { type: 'password', placeholder: S('Group password') });
  const pop = avPop(e, h('b', null, S('Found a group')), h('div', { class: 'small dim' }, S('You are its admin: you let others in. The password makes others admins too.')),
    h('div', { class: 'avrow', style: 'margin-top:6px' }, nm, pw,
      aib('flying-flag', S('Found it with {0} (Enter)', c.name), () => { pop.remove(); return aact('adv_group_create', { name: nm.value, password: pw.value }); }, 'acc')));
  nm.focus();
}
function advAdminLogin(e) {
  const ln = h('input', { placeholder: S('Group name') }), lp = h('input', { type: 'password', placeholder: S('Password') });
  const pop = avPop(e, h('b', null, S('Admin login')), h('div', { class: 'avrow', style: 'margin-top:6px' }, ln, lp,
    aib('key', S("Log in with the group's password (Enter)"), () => { pop.remove(); return act('adv_group_login', { name: ln.value, password: lp.value }); }, 'acc')));
  ln.focus();
}
function advNoGroup(A, c) {
  const asked = A.asked.filter(x => x.char === c.name);
  return [h('div', { class: 'avsec' }, h('h3', null, ai('shaking-hands'), h('span', { class: 'grow' }, S('Groups')),
    aib('key', S("Admin login: a group's name and password"), e => advAdminLogin(e))),
    asked.length ? h('div', { class: 'small warn' }, S('Waiting for {0} to answer.', asked.map(x => x.name).join(', '))) : null,
    h('div', { class: 'avlist' }, ...(A.all_groups.length ? A.all_groups.map(g => h('div', null,
      h('span', { class: 'grow' }, h('b', null, g.name), h('span', { class: 'dim small' }, ' · ' + S('{0} members', g.size) + (g.at ? ' · ' + g.at : '') +
        (g.done ? ' · ' + S('{0} quests done', g.done) : ''))),
      asked.some(x => x.group === g.id) ? aib('cancel', S('Withdraw the request'), () => act('adv_withdraw', { group: g.id }))
        : aib('shaking-hands', S('Ask to join with {0}', c.name), () => aact('adv_request', { group: g.id }), 'acc')))
      : []),
    h('div', { class: 'avadd avrow', onclick: e => advFound(e, c), tip: S('Found a group with {0}: you are its admin', c.name) }, '+ ' + S('Found a group'))))];
}

// ---------------------------------------------------------------- a new character
function advNewChar(A) {
  const old = $('avnew');
  const o = A.create || {}, f = AVN.form;
  const close = A.characters.length ? () => { AVN.newChar = false; const n = $('avnew'); if (n) n.remove(); } : null;
  const redo = () => advNewChar(A);
  const pick = (k, list, label) => h('select', { 'aria-label': label, onchange: e => { f[k] = e.target.value; if (k === 'race') f.subrace = ''; redo(); } },
    h('option', { value: '' }, label), ...(list || []).map(n => h('option', { value: n, selected: f[k] === n }, n)));
  const race = (o.races || []).find(r => r.name === f.race);
  const costs = (o.point_buy && o.point_buy.costs) || { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
  const budget = (o.point_buy && o.point_buy.budget) || 27;
  f.scores = f.scores || { str: 13, dex: 13, con: 13, int: 12, wis: 12, cha: 12 };
  const spent = Object.values(f.scores).reduce((a, v) => a + (costs[v] ?? 99), 0);
  const box = h('div', { id: 'avnew' }, h('div', { class: 'avcard' },
    h('div', { class: 'hd' }, ai('person'), h('span', { class: 'grow' }, S('New character')), close ? aib('cancel', S('Close'), close) : null),
    h('div', { class: 'bd' },
      h('div', { class: 'avrow' }, h('input', { placeholder: S('Name (empty: one is made up)'), value: f.name || '', maxlength: 40, style: 'flex:1',
        oninput: e => { f.name = e.target.value; } })),
      h('div', { class: 'avrow', style: 'margin-top:6px' }, pick('race', (o.races || []).map(r => r.name), S('Race')),
        race && race.subraces && race.subraces.length ? pick('subrace', race.subraces, S('Subrace')) : null,
        pick('class', (o.classes || []).map(c => c.name), S('Class')),
        pick('background', (o.backgrounds || []).map(b => b.name || b), S('Background (random)'))),
      h('div', { class: 'avrow small', style: 'margin-top:6px' }, h('label', null, h('input', { type: 'checkbox', checked: !!f.pb,
        onchange: e => { f.pb = e.target.checked; redo(); } }), ' ' + S("Point buy (else the class's standard array)"))),
      f.pb ? h('div', { class: 'avrow small' }, ...['str', 'dex', 'con', 'int', 'wis', 'cha'].map(k =>
        h('label', null, k.toUpperCase() + ' ', h('select', { onchange: e => { f.scores[k] = +e.target.value; redo(); } },
          ...Object.keys(costs).map(v => h('option', { value: v, selected: +v === f.scores[k] }, v))))),
      h('b', { class: spent > budget ? 'bad' : 'good' }, S('{0} of {1} points', spent, budget))) : null,
      h('div', { class: 'avrow', style: 'margin-top:8px' }, h('span', { class: 'small dim grow' }, S("Level 1, the class's kit and the background's purse; you start in a village.")),
        h('button', { class: 'primary', onclick: go(async () => {
          const spec = { name: f.name || '', race: f.race || '', subrace: f.subrace || '', class: f.class || '', background: f.background || '' };
          if (f.pb) spec.scores = f.scores;
          const r = await act('adv_create_char', { spec });
          if (r) { AVN.newChar = false; AVN.form = {}; const n = $('avnew'); if (n) n.remove(); }
        }) }, S('Create'))))));
  if (old) old.replaceWith(box); else $('avpanes').append(box);
}

// ---------------------------------------------------------------- the map: Packing Merchant's look
// The world is a grid of places (A.map.w × A.map.h); a camera {z: pixels a place, x, y} shows it like the campaign's
// world map. Drawn in two parts: the ground (washes, coast, fog) painted once into a picture whenever what is known
// changes, and everything standing on it (stamps, roads, seals, names, groups) drawn at the camera's size each frame
// so it stays sharp.
const AM = { cam: null, sheet: null, key: '', img: {}, stamps: [], roads: [], ptrs: new Map(), drag: null, hover: null,
  centered: false, flash: null };
const SHEET = 28;                                          // the ground picture's pixels a place
const FOG = [224, 208, 170], SEA = [150, 172, 162], INK = [64, 50, 36];   // fog: old unwritten paper; land: washes in its colour
const LAND = { plains: [206, 196, 128], forest: [128, 150, 96], hills: [178, 166, 108], mountains: [168, 154, 134],
  swamp: [138, 156, 124], badlands: [214, 174, 116] };
const AMART = ('tree_a tree_b tree_c pine_a pine_b pine_c ash_tree bush dead_tree hill_a hill_b peak_a peak_b crag boulder boulder_b ' +
  'reeds_a reeds_b pool dune_a dune_b field_a field_b field_c heather_a heather_b palm_a ruin_a ruin_b wave_a wave_b town_hamlet ' +
  'town_village town_city town_capital town_unknown town_ruin waypoint_camp compass_rose den_dungeon_cave den_dungeon_crypt ' +
  'meteor_crater oddity_marker map_goal_quest group_adventurer').split(' ');
const SEAL = { camp: ['waypoint_camp', 0.9], village: ['town_village', 1.0], town: ['town_city', 1.2], city: ['town_capital', 1.45] };
function amImg(n) {
  let im = AM.img[n];
  if (!im) { im = AM.img[n] = new Image(); im.onload = () => amDraw(); im.src = '/advart/map/' + n + '.webp'; }
  return im.complete && im.naturalWidth ? im : null;
}
function amRand(i, k) { const x = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); }
/** Smooth noise over the map (for the borders' wander and the paper's grain): a fixed lattice, eased between. */
function amNoise(x, y, k) {
  const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi, e = t => t * t * (3 - 2 * t);
  const r = (a, b) => amRand(a * 131 + b * 977, k) * 2 - 1;
  const a = r(xi, yi) + (r(xi + 1, yi) - r(xi, yi)) * e(fx), b = r(xi, yi + 1) + (r(xi + 1, yi + 1) - r(xi, yi + 1)) * e(fx);
  return a + (b - a) * e(fy);
}
function amWire() {
  const cv = $('avcv');
  const pt = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const cellAt = (p, c) => [Math.floor((p[0] - c.x) / c.z), Math.floor((p[1] - c.y) / c.z)];
  cv.addEventListener('pointerdown', e => {
    cv.setPointerCapture(e.pointerId);
    AM.ptrs.set(e.pointerId, pt(e));
    const c = amCam();
    if (AM.ptrs.size === 2) {
      const [a, b] = [...AM.ptrs.values()];
      AM.drag = { pinch: Math.hypot(a[0] - b[0], a[1] - b[1]), cam: { ...c }, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
    } else AM.drag = { at: pt(e), cam: { ...c }, t: performance.now(), moved: false };
  });
  cv.addEventListener('pointermove', e => {
    const p = pt(e), c = amCam(), cell = cellAt(p, c);
    if (!AM.hover || AM.hover[0] !== cell[0] || AM.hover[1] !== cell[1]) { AM.hover = cell; if (!AVN.pinned) amCard(p, cell); amDraw(); }
    else if (!AVN.pinned) amCardMove(p);
    if (!AM.ptrs.has(e.pointerId)) return;
    AM.ptrs.set(e.pointerId, p);
    const d = AM.drag;
    if (!d) return;
    if (d.pinch && AM.ptrs.size === 2) {
      const [a, b] = [...AM.ptrs.values()];
      const f = Math.hypot(a[0] - b[0], a[1] - b[1]) / d.pinch, nz = amClampZ(d.cam.z * f);
      const mx = (d.mid[0] - d.cam.x) / d.cam.z, my = (d.mid[1] - d.cam.y) / d.cam.z, mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      AM.cam = { z: nz, x: mid[0] - mx * nz, y: mid[1] - my * nz };
    } else if (d.at) {
      if (Math.hypot(p[0] - d.at[0], p[1] - d.at[1]) > 6) { d.moved = true; cv.classList.add('drag'); }
      if (d.moved) AM.cam = { ...d.cam, x: d.cam.x + p[0] - d.at[0], y: d.cam.y + p[1] - d.at[1] };
    }
    amDraw();
  });
  const up = e => {
    const d = AM.drag;
    AM.ptrs.delete(e.pointerId);
    if (AM.ptrs.size === 0) AM.drag = null;
    cv.classList.remove('drag');
    if (e.type === 'pointerup' && e.button === 0 && d && d.at && !d.moved && !d.pinch && performance.now() - d.t < 600) {
      const p = pt(e);
      amTap(cellAt(p, amCam()), p, e.shiftKey);
    }
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  cv.addEventListener('contextmenu', e => { e.preventDefault(); amUnplan(false); });   // the right button takes a stop back
  cv.addEventListener('pointerleave', () => { AM.hover = null; if (!AVN.pinned) $('avcard').classList.add('hide'); amDraw(); });
  cv.addEventListener('wheel', e => { e.preventDefault(); const r = cv.getBoundingClientRect(); amZoom(Math.pow(1.0015, -e.deltaY), [e.clientX - r.left, e.clientY - r.top]); }, { passive: false });
  window.addEventListener('resize', () => { if (advOn()) amDraw(); });
}
function amSize() { const cv = $('avcv'); return [cv.clientWidth || 600, cv.clientHeight || 400]; }
function amFit() {
  const M = advS().map, [vw, vh] = amSize(), z = Math.min((vw - 20) / (M.w + 2), (vh - 20) / (M.h + 2));
  return { z, x: (vw - M.w * z) / 2, y: (vh - M.h * z) / 2 };
}
function amClampZ(z) { return Math.max(amFit().z * 0.7, Math.min(160, z)); }
function amCam() { return AM.cam || amFit(); }
function amZoom(f, at) {
  const [vw, vh] = amSize(), c = amCam(), [ax, ay] = at || [vw / 2, vh / 2], nz = amClampZ(c.z * f);
  const mx = (ax - c.x) / c.z, my = (ay - c.y) / c.z;
  AM.cam = { z: nz, x: ax - mx * nz, y: ay - my * nz };
  amDraw();
}
/** Fly to the group (else the chosen character). */
function amFind() {
  if (!advS() || !$('avcv') || !$('avcv').clientWidth) return;
  const g = advGroup(), me = advMe(), p = g ? [g.x, g.y] : me ? [me.x, me.y] : null;
  if (!p) return;
  const [vw, vh] = amSize(), z = Math.max(amCam().z, Math.min(64, Math.max(amFit().z * 3, 36)));
  AM.cam = { z, x: vw / 2 - (p[0] + .5) * z, y: vh / 2 - (p[1] + .5) * z };
  amDraw();
}
function amLook(q) {
  const t = q.kind === 'scout' ? (q.targets.find(p => !q.visited.some(v => v[0] === p[0] && v[1] === p[1])) || q.target) : q.target;
  if (!t) return;
  const [vw, vh] = amSize(), z = Math.max(amCam().z, 36);
  AM.cam = { z, x: vw / 2 - (t[0] + .5) * z, y: vh / 2 - (t[1] + .5) * z };
  AM.flash = { at: t, t0: performance.now() };
  amDraw();
}
/** A tap on the map: on a neighbouring place, a step there; on a place further off, a route planned to it (Shift: a
 *  stop added to the route); on the route's end again, set out. Anywhere else (or not leading): its card, pinned. */
function amTap(cell, p, shift) {
  const g = advGroup(), M = advS().map, c = M.cells[cell[1] * M.w + cell[0]];
  const free = g && g.lead && !g.encounter && !g.fight;
  if (free && c && c[0] !== 'water' && !(cell[0] === g.x && cell[1] === g.y)) {
    AVN.pinned = null;
    const end = AVN.route && AVN.route.way[AVN.route.way.length - 1];
    if (end && end[0] === cell[0] && end[1] === cell[1] && !shift) { amSetOut(); return; }
    if (!AVN.route && !shift && Math.max(Math.abs(cell[0] - g.x), Math.abs(cell[1] - g.y)) === 1) {
      amWalk([[cell[0], cell[1]]]);
      return;
    }
    amPlan(cell, shift);
    amCard(p, cell);
    return;
  }
  AVN.pinned = AVN.pinned && AVN.pinned[0] === cell[0] && AVN.pinned[1] === cell[1] ? null : cell;
  amCard(p, cell);
  amDraw();
}
// ---- routes, as Packing Merchant draws a road: click where to go, read what it costs, set out
const RISK = { 1: .14, 2: .20, 3: .26, 4: .32 };            // a fight's chance a step (regions.chance), as rumour has it
const SIGHT = { plains: 2, forest: 1, swamp: 1, hills: 3, mountains: 4, badlands: 2, water: 2 };
function amRisk(M, x, y) {
  const c = M.cells[y * M.w + x];
  if (!c || c[0] === 'water' || M.settlements.some(s => s.x === x && s.y === y)) return 0;
  return Math.max(.03, RISK[c[3]] - (c[2] ? .05 : 0) + (c[1] ? .06 : 0));
}
/** The safest short way over known land from a to b (each step one place, diagonals too): [[x, y], ...] without a. */
function amPath(M, a, b) {
  const N = M.w * M.h, dist = new Float64Array(N).fill(Infinity), prev = new Int32Array(N).fill(-1), done = new Uint8Array(N);
  const start = a[1] * M.w + a[0], goal = b[1] * M.w + b[0];
  dist[start] = 0;
  const open = [start];
  while (open.length) {
    let bi = 0;
    for (let k = 1; k < open.length; k++) if (dist[open[k]] < dist[open[bi]]) bi = k;
    const cur = open.splice(bi, 1)[0];
    if (done[cur]) continue;
    done[cur] = 1;
    if (cur === goal) break;
    const x = cur % M.w, y = (cur / M.w) | 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const nx = x + dx, ny = y + dy, n = ny * M.w + nx;
      if ((!dx && !dy) || nx < 0 || ny < 0 || nx >= M.w || ny >= M.h || done[n]) continue;
      const c = M.cells[n];
      if (!c || c[0] === 'water') continue;
      const d = dist[cur] + 1 + amRisk(M, nx, ny) * 4 + (dx && dy ? .01 : 0);
      if (d < dist[n]) { dist[n] = d; prev[n] = cur; open.push(n); }
    }
  }
  if (!done[goal]) return null;
  const out = [];
  for (let n = goal; n !== start; n = prev[n]) out.push([n % M.w, (n / M.w) | 0]);
  return out.reverse();
}
function amPlan(dest, add) {
  const g = advGroup(), M = advS().map, r = add ? AVN.route : null;
  const from = r ? r.way[r.way.length - 1] : [g.x, g.y];
  const leg = amPath(M, from, dest);
  if (!leg || !leg.length) { say(S('No way there over the land your group knows.'), true); return; }
  AVN.route = { way: (r ? r.way : []).concat([[dest[0], dest[1]]]), path: (r ? r.path : []).concat(leg) };
  renderAdv(); amDraw();
}
/** Take the route's last stop back (a right-click), or the whole route. */
function amUnplan(all) {
  const r = AVN.route, g = advGroup();
  if (!r) return false;
  AVN.route = null;
  if (!all && r.way.length > 1 && g) for (const w of r.way.slice(0, -1)) amPlan(w, true);
  renderAdv(); amDraw();
  return true;
}
function amReadout(M, g, r) {
  const steps = r.path.length;
  let safe = 1, top = 0;
  for (const [x, y] of r.path) { safe *= 1 - amRisk(M, x, y); const c = M.cells[y * M.w + x]; if (c) top = Math.max(top, c[3]); }
  const end = r.path[steps - 1], town = M.settlements.find(s => s.x === end[0] && s.y === end[1]);
  const hits = g.quests.filter(q => q.stage === 'active' && (q.kind === 'scout' ? q.targets : q.target ? [q.target] : [])
    .some(t => r.path.some(p => p[0] === t[0] && p[1] === t[1])));
  return { steps, risk: Math.round((1 - safe) * 100), top, town, hits };
}
async function amSetOut() {
  const r = AVN.route;
  if (r) await amWalk(r.path);
}
/** Walk steps (the table moves the group a step at a time and stops where something happens); the token glides. */
async function amWalk(path) {
  const g = advGroup();
  if (!g) return;
  const from = [g.x, g.y];
  const res = await act('adv_travel', { group: g.id, path }, true);
  const d = res && res.data;
  if (!d) return;
  if (d.text) say(d.text);
  amGlide([from, ...d.steps]);
  if (AVN.route) {
    const rest = AVN.route.path.slice(d.steps.length);
    AVN.route = d.done || !rest.length ? null : { way: AVN.route.way.filter(w => rest.some(p => p[0] === w[0] && p[1] === w[1])), path: rest };
  }
  renderAdv();
  amFollow();
}
function amGlide(pts) {
  if (pts.length < 2) return;
  AM.glide = { pts, t0: performance.now(), dur: Math.min(2400, 260 * (pts.length - 1)) };
  amDraw();
}
/** Where the group's token is drawn now: gliding along its last walk, else its place. */
function amGroupAt(G) {
  const gl = AM.glide;
  if (!gl) return [G.x, G.y];
  const t = (performance.now() - gl.t0) / gl.dur;
  if (t >= 1) { AM.glide = null; return [G.x, G.y]; }
  const f = t * (gl.pts.length - 1), k = Math.floor(f), e = f - k, a = gl.pts[k], b = gl.pts[Math.min(k + 1, gl.pts.length - 1)];
  return [a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e];
}
/** After a step: keep the group in sight (the view moves only when it nears the edge). */
function amFollow() {
  const g = advGroup();
  if (!g || !AM.cam) return;
  const c = AM.cam, [vw, vh] = amSize(), x = (g.x + .5) * c.z + c.x, y = (g.y + .5) * c.z + c.y, m = Math.min(vw, vh) * .2;
  if (x < m || y < m || x > vw - m || y > vh - m) amFind();
}
const AREA_NAMES = { water: 'Water', plains: 'Plains', forest: 'Forest', hills: 'Hills', mountains: 'Mountains', swamp: 'Swamp', badlands: 'Badlands' };
const FEAT_NAMES = { ruins: 'Ruins', cave: 'Cave', blighted: 'Blighted land', fey: 'Fey-touched glade', shadow: 'Shadow rift', arcane: 'Arcane scar' };
/** The card under the pointer: what is known of the place (what lives there once asked of the table). */
function amCard(p, cell) {
  const A = advS(), el = $('avcard');
  if (!A || !cell) return;
  const M = A.map, i = cell[1] * M.w + cell[0], c = M.cells[i];
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= M.w || cell[1] >= M.h) { el.classList.add('hide'); return; }
  const s = M.settlements.find(s => s.x === cell[0] && s.y === cell[1]);
  const gs = M.groups.filter(o => o.x === cell[0] && o.y === cell[1]);
  const lines = [];
  if (s && c) lines.push(h('div', null, h('b', null, s.name), ' ', h('span', { class: 'dim' }, S(s.kind))));
  else if (s) lines.push(h('div', null, h('b', null, '?'), ' ', h('span', { class: 'dim' }, S('A place nobody of yours has seen'))));
  if (c) {
    lines.push(h('div', null, S(AREA_NAMES[c[0]]) + (c[1] ? ' · ' + S(FEAT_NAMES[c[1]]) : '') + (c[2] ? ' · ' + S('road') : '')));
    if (M.landmarks[i]) lines.push(h('div', { class: 'dim' }, M.landmarks[i]));
    const t = M.tiers[c[3]];
    if (c[0] !== 'water' && t) lines.push(h('div', { class: c[3] >= 3 ? 'bad' : c[3] === 2 ? 'warn' : 'good' }, `${S(t.name)} · ${S('levels {0}-{1}', t.levels[0], t.levels[1])}`));
    const known = AVN.area[i];
    if (known && known.lives && known.lives.length) lines.push(h('div', { class: 'dim small' }, S('Lives here: {0}', known.lives.join(', '))));
    else if (known === undefined && c[0] !== 'water' && !s) amAsk(cell, i);
  } else if (!s) lines.push(h('div', { class: 'dim' }, S('Unexplored')));
  for (const o of gs) lines.push(h('div', null, ai('flying-flag'), ' ' + o.name + ` (${o.size})` + (o.fighting ? ' ⚔' : '')));
  const g = advGroup();
  if (g && g.lead && !g.encounter && !g.fight && c && c[0] !== 'water' && !(cell[0] === g.x && cell[1] === g.y)) {
    const end = AVN.route && AVN.route.way[AVN.route.way.length - 1];
    lines.push(h('div', { class: 'acc small' }, '➜ ' + (end && end[0] === cell[0] && end[1] === cell[1] ? S('Click again: set out')
      : !AVN.route && Math.max(Math.abs(cell[0] - g.x), Math.abs(cell[1] - g.y)) === 1 ? S('Click: step here')
        : S('Click: plan the way here (Shift: add a stop, right-click: take one back)'))));
  }
  if (c && c[0] !== 'water' && !s) lines.push(h('div', { class: 'dim small' }, S('A fight on about {0}% of the steps here', Math.round(amRisk(M, cell[0], cell[1]) * 100))));
  el.replaceChildren(...lines);
  el.classList.remove('hide');
  if (p) amCardMove(p);
}
function amCardMove(p) {
  const el = $('avcard'), [vw, vh] = amSize();
  if (!p || el.classList.contains('hide')) return;
  el.style.left = Math.max(4, Math.min(p[0] + 14, vw - el.offsetWidth - 4)) + 'px';
  el.style.top = Math.max(4, Math.min(p[1] + 14, vh - el.offsetHeight - 4)) + 'px';
}
function amAsk(cell, i) {
  AVN.area[i] = null;
  setTimeout(() => {
    const here = (AM.hover && AM.hover[0] === cell[0] && AM.hover[1] === cell[1]) || (AVN.pinned && AVN.pinned[0] === cell[0] && AVN.pinned[1] === cell[1]);
    if (!here) { delete AVN.area[i]; return; }
    act('adv_area', { x: cell[0], y: cell[1] }, true).then(r => {
      if (r && r.data) { AVN.area[i] = r.data; if (AM.hover && AM.hover[0] === cell[0] && AM.hover[1] === cell[1]) amCard(null, cell); }
      else delete AVN.area[i];
    });
  }, 350);
}

/** The ground: each land's wash meeting the next along a pen line that wanders; the sea, its shallows and the inked
 *  shore; browned paper where nothing is known; a little grain. One pixel pass over the picture, again only when
 *  what is known changes. */
function amGround(M) {
  const W = M.w * SHEET, H = M.h * SHEET, known = M.cells;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const g = cv.getContext('2d'), img = g.createImageData(W, H), d = img.data;
  const kind = new Uint8Array(W * H);                   // 0 fog, 1 sea, 2+ land (biome index)
  const BI = ['plains', 'forest', 'hills', 'mountains', 'swamp', 'badlands'];
  const warp = 0.42;
  for (let py = 0; py < H; py++) {
    const v = (py + .5) / SHEET;
    for (let px = 0; px < W; px++) {
      const u = (px + .5) / SHEET;
      const nu = amNoise(u * 1.6, v * 1.6, 1), nv = amNoise(u * 1.6, v * 1.6, 2);
      const at = (k) => known[Math.min(M.h - 1, Math.max(0, Math.floor(v + nv * k))) * M.w + Math.min(M.w - 1, Math.max(0, Math.floor(u + nu * k)))];
      const near = at(0.12);                        // what is known: close to the true edge (stamps never stand in the fog)
      const c = near ? (at(warp) || near) : null;   // which land: its borders wander as a pen draws them
      kind[py * W + px] = !c ? 0 : c[0] === 'water' ? 1 : 2 + Math.max(0, BI.indexOf(c[0]));
    }
  }
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]];
  const near = (x, y, want, r) => {                      // how near a pixel of `want` is (8 directions), 0: none within r
    for (let k = 1; k <= r; k++) for (const [dx, dy] of DIRS) {
      const nx = x + dx * k, ny = y + dy * k;
      if (nx >= 0 && ny >= 0 && nx < W && ny < H && want(kind[ny * W + nx])) return k;
    }
    return 0;
  };
  const isFog = t => t === 0, isSea = t => t === 1, isLand = t => t >= 2;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x, k = kind[i], u = x / SHEET, v = y / SHEET;
    let col;
    if (k === 0) {
      const n = amNoise(u * 1.1, v * 1.1, 7) * 6 + amNoise(u * .35, v * .35, 8) * 9;     // a stain or two, softly
      col = [FOG[0] + n, FOG[1] + n, FOG[2] + n * .8];
    } else if (k === 1) {
      const shore = near(x, y, isLand, 5), n = amNoise(u * 2, v * 2, 5) * 6;
      col = shore ? [SEA[0] + 26 - shore * 4 + n, SEA[1] + 22 - shore * 4 + n, SEA[2] + 14 - shore * 2 + n] : [SEA[0] + n, SEA[1] + n, SEA[2] + n];
      if (shore === 1) col = col.map((c, j) => c * .55 + INK[j] * .45);
    } else {
      const base = LAND[BI[k - 2]] || LAND.plains;
      const n = amNoise(u * 2.2, v * 2.2, 3) * 9 + amNoise(u * 9, v * 9, 4) * 4;
      col = [base[0] + n, base[1] + n, base[2] + n * .7];
      if (near(x, y, isSea, 1)) col = INK.slice();                                   // the inked shore
      else if (near(x, y, t => t >= 2 && t !== k, 1)) col = col.map(c => c - 20);  // the pen line between lands
    }
    if (k !== 0) {
      const f = near(x, y, isFog, 4);
      if (f) { const a = 1 - f / 5; col = col.map((c, j) => c * (1 - a) + FOG[j] * a); }
    }
    const grain = (amRand(i, 9) - .5) * 7;
    d[i * 4] = col[0] + grain; d[i * 4 + 1] = col[1] + grain; d[i * 4 + 2] = col[2] + grain; d[i * 4 + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return cv;
}
/** The stamps standing on the known land, seeded by the place so the same world always draws the same: woods in
 *  masses, peaks, hills, reeds, dunes, fields near the settlements, the features' marks, waves on the sea. */
function amStamps(M) {
  const out = [], known = M.cells;
  const at = new Set(M.settlements.map(s => s.y * M.w + s.x));
  const near = new Set();
  for (const s of M.settlements) for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) near.add((s.y + dy) * M.w + s.x + dx);
  const add = (i, n, k, size, ox, oy) => out.push({ x: i % M.w + (ox ?? .2 + amRand(i, k) * .6), y: Math.floor(i / M.w) + (oy ?? .35 + amRand(i, k + 50) * .6), n, size });
  for (const [key, c] of Object.entries(known)) {
    const i = +key, [b, feat, road] = c;
    if (at.has(i)) continue;
    const r = k => amRand(i, k);
    if (b === 'water') { if (r(1) < .08) add(i, r(2) < .5 ? 'wave_a' : 'wave_b', 3, .3); continue; }
    const spots = road ? [[.18, .3], [.82, .35], [.2, .88], [.8, .92]] : [[.25, .32], [.75, .36], [.3, .82], [.72, .86], [.5, .6]];
    if (b === 'forest') {
      const pine = amNoise((i % M.w) * .3, Math.floor(i / M.w) * .3, 11) > .1;
      for (let k = 0; k < spots.length; k++) {
        const n = pine ? ['pine_a', 'pine_b', 'pine_c'][Math.floor(r(k + 10) * 3)] : ['tree_a', 'tree_b', 'tree_c', 'ash_tree'][Math.floor(r(k + 10) * 4)];
        add(i, n, k + 20, .42 + r(k + 30) * .12, spots[k][0] + (r(k + 40) - .5) * .15, spots[k][1] + (r(k + 41) - .5) * .12);
      }
    } else if (b === 'mountains') {
      add(i, r(3) < .5 ? 'peak_a' : 'peak_b', 4, .95 + r(5) * .25, .5 + (r(6) - .5) * .2, .8);
      if (r(7) < .6) add(i, r(8) < .5 ? 'crag' : 'boulder', 9, .32, r(10) < .5 ? .15 : .85, .95);
    } else if (b === 'hills') {
      add(i, r(3) < .5 ? 'hill_a' : 'hill_b', 4, .5, .35, .55);
      if (r(5) < .55) add(i, r(6) < .5 ? 'hill_a' : 'hill_b', 7, .42, .75, .92);
    } else if (b === 'swamp') {
      for (let k = 0; k < 3; k++) add(i, r(k + 10) < .5 ? 'reeds_a' : 'reeds_b', k + 20, .3, spots[k][0], spots[k][1]);
      if (r(3) < .35) add(i, 'pool', 4, .3, .55, .62);
    } else if (b === 'badlands') {
      add(i, r(3) < .4 ? 'dune_a' : r(3) < .7 ? 'dune_b' : 'crag', 4, .45);
      if (r(5) < .2) add(i, 'dead_tree', 6, .35);
    } else {
      if (near.has(i) && r(3) < .45) add(i, ['field_a', 'field_b', 'field_c'][Math.floor(r(4) * 3)], 5, .45, .5, .6);
      else if (r(6) < .22) add(i, r(7) < .5 ? 'bush' : r(7) < .8 ? 'heather_a' : 'heather_b', 8, .26);
    }
    if (feat === 'ruins') add(i, r(11) < .5 ? 'ruin_a' : 'ruin_b', 12, .55, .5, .72);
    else if (feat === 'cave') add(i, 'den_dungeon_cave', 12, .55, .5, .78);
    else if (feat === 'blighted') { add(i, 'dead_tree', 12, .42, .35, .7); add(i, 'dead_tree', 13, .36, .7, .88); }
    else if (feat === 'fey') add(i, 'oddity_marker', 12, .42, .5, .72);
    else if (feat === 'shadow') add(i, 'den_dungeon_crypt', 12, .55, .5, .78);
    else if (feat === 'arcane') add(i, 'meteor_crater', 12, .55, .5, .78);
  }
  out.sort((a, b) => a.y - b.y);
  return out;
}
/** The roads between known road places: a curve through each place's middle (shifted a little, so they don't run
 *  on a grid), straight spokes where three or more meet. */
function amRoads(M) {
  const known = M.cells, out = [];
  const isRoad = (x, y) => { const c = known[y * M.w + x]; return !!(c && c[2]) && x >= 0 && y >= 0 && x < M.w && y < M.h; };
  const mid = (x, y) => { const i = y * M.w + x; return [x + .5 + (amRand(i, 61) - .5) * .3, y + .5 + (amRand(i, 62) - .5) * .3]; };
  for (const [key, c] of Object.entries(known)) {
    if (!c[2]) continue;
    const i = +key, x = i % M.w, y = Math.floor(i / M.w), me = mid(x, y), nb = [];
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) if (isRoad(x + dx, y + dy)) nb.push([dx, dy]);
    for (const [dx, dy] of [[1, 1], [-1, -1], [1, -1], [-1, 1]]) {
      if (isRoad(x + dx, y + dy) && !isRoad(x + dx, y) && !isRoad(x, y + dy)) nb.push([dx, dy]);
    }
    const ends = nb.map(([dx, dy]) => { const o = mid(x + dx, y + dy); return [(me[0] + o[0]) / 2, (me[1] + o[1]) / 2]; });
    if (ends.length === 2) out.push({ a: ends[0], c: me, b: ends[1] });
    else for (const e of ends) out.push({ a: me, c: me, b: e });
  }
  return out;
}
let amPending = false;
function amDraw() {
  if (amPending) return;
  amPending = true;
  requestAnimationFrame(() => { amPending = false; amPaint(); });
}
function amPaint() {
  const A = advS(), cv = $('avcv');
  if (!A || !cv || !document.body.classList.contains('advmode') || AVN.tab !== 'map' || !cv.clientWidth) return;
  const M = A.map, dpr = window.devicePixelRatio || 1, [vw, vh] = amSize();
  if (cv.width !== Math.round(vw * dpr) || cv.height !== Math.round(vh * dpr)) { cv.width = Math.round(vw * dpr); cv.height = Math.round(vh * dpr); }
  const key = M.w + 'x' + M.h + ':' + Object.keys(M.cells).join(',').length + ':' + Object.keys(M.cells).length;
  if (AM.key !== key) { AM.key = key; AM.sheet = amGround(M); AM.stamps = amStamps(M); AM.roads = amRoads(M); }
  if (!AM.centered) { AM.centered = true; amFind(); }
  const g = cv.getContext('2d'), c = amCam(), z = c.z;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = '#5b4632'; g.fillRect(0, 0, vw, vh);             // the desk
  const pad = .8, X = c.x - pad * z, Y = c.y - pad * z, PW = (M.w + pad * 2) * z, PH = (M.h + pad * 2) * z;
  g.save();                                                         // the sheet: a little beyond the world, a torn edge
  g.shadowColor = '#0009'; g.shadowBlur = 14; g.shadowOffsetY = 4;
  g.beginPath();
  const steps = 90;
  for (let k = 0; k <= steps * 4; k++) {
    const side = Math.floor(k / steps), f = (k % steps) / steps, j = (amRand(k, 3) - .5) * Math.min(10, z * .25);
    const p = side === 0 ? [X + PW * f, Y + j] : side === 1 ? [X + PW + j, Y + PH * f] : side === 2 ? [X + PW * (1 - f), Y + PH + j] : [X + j, Y + PH * (1 - f)];
    if (k) g.lineTo(p[0], p[1]); else g.moveTo(p[0], p[1]);
  }
  g.closePath();
  g.fillStyle = `rgb(${FOG.join(',')})`; g.fill();
  g.restore();
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.drawImage(AM.sheet, c.x, c.y, M.w * z, M.h * z);
  const x0 = Math.floor(-c.x / z) - 1, y0 = Math.floor(-c.y / z) - 1, x1 = x0 + vw / z + 3, y1 = y0 + vh / z + 3;
  const sx = u => c.x + u * z, sy = v => c.y + v * z;
  if (z >= 6) for (const [w, col] of [[Math.max(2, z * .12), '#5a3f22'], [Math.max(1, z * .065), '#dcc590']]) {   // roads: inked
    g.lineWidth = w; g.strokeStyle = col; g.lineCap = 'round'; g.lineJoin = 'round';
    g.beginPath();
    for (const r of AM.roads) {
      if (r.c[0] < x0 || r.c[0] > x1 || r.c[1] < y0 || r.c[1] > y1) continue;
      g.moveTo(sx(r.a[0]), sy(r.a[1])); g.quadraticCurveTo(sx(r.c[0]), sy(r.c[1]), sx(r.b[0]), sy(r.b[1]));
    }
    g.stroke();
  }
  if (z >= 9) for (const s of AM.stamps) {                          // stamps, back to front
    if (s.x < x0 || s.x > x1 || s.y < y0 || s.y > y1) continue;
    const im = amImg(s.n);
    if (!im) continue;
    const hgt = s.size * z, wid = hgt * im.naturalWidth / im.naturalHeight;
    g.drawImage(im, sx(s.x) - wid / 2, sy(s.y) - hgt, wid, hgt);
  }
  const rose = amImg('compass_rose');
  if (rose) { const r = Math.min(150, Math.max(50, z * 3)); g.globalAlpha = .85; g.drawImage(rose, sx(M.w) - r - 6, sy(0) + 6, r, r); g.globalAlpha = 1; }
  const G = advGroup(), known = M.cells;
  if (G) {                                                          // quest marks
    const im = amImg('map_goal_quest');
    for (const q of G.quests) {
      const marks = q.kind === 'scout' ? q.targets.filter(t => !q.visited.some(v => v[0] === t[0] && v[1] === t[1])) : q.target && q.stage === 'active' ? [q.target] : [];
      for (const t of marks) if (im) { const s = Math.max(18, Math.min(40, z * .7)); g.drawImage(im, sx(t[0] + .5) - s / 2, sy(t[1] + .5) - s / 2, s, s); }
    }
  }
  const head = getComputedStyle(document.body).getPropertyValue('--head').trim() || 'serif';
  for (const s of M.settlements) {                                  // the places: seals, names at a steady size
    if (s.x < x0 || s.x > x1 || s.y < y0 || s.y > y1) continue;
    const seen = !!known[s.y * M.w + s.x];
    const [art, k] = SEAL[s.kind] || SEAL.village;
    const im = amImg(seen ? art : 'town_unknown');
    const size = Math.max(14, Math.min(68, z * .95 * k));
    if (im) g.drawImage(im, sx(s.x + .5) - size / 2, sy(s.y + .5) - size / 2, size, size);
    if (seen && (z >= 14 || s.kind === 'city' || s.kind === 'town')) {
      const fs = Math.max(11, Math.min(16, 9 + z * .1)) * (s.kind === 'city' ? 1.2 : 1);
      g.font = `${s.kind === 'city' ? 'bold ' : ''}${fs.toFixed(1)}px ${head}`;
      g.textAlign = 'center'; g.textBaseline = 'top';
      const t = s.kind === 'city' ? s.name.toUpperCase() : s.name, ty = sy(s.y + .5) + size / 2 + 2;
      g.lineWidth = 3.5; g.strokeStyle = 'rgba(236,224,192,.92)'; g.strokeText(t, sx(s.x + .5), ty);
      g.fillStyle = '#2b2118'; g.fillText(t, sx(s.x + .5), ty);
    }
  }
  if (G) {                                                          // badges on the places: a reward waiting, a parcel's end
    for (const q of G.quests) {
      const at = q.stage === 'ready' && q.kind !== 'deliver' && q.kind !== 'escort' ? [q.settlement, 'laurels-trophy']
        : (q.kind === 'deliver' || q.kind === 'escort') && q.stage === 'active' ? [q.dest, q.kind === 'deliver' ? 'envelope' : 'footsteps'] : null;
      const s = at && M.settlements.find(x => x.id === at[0]);
      if (!s) continue;
      const r = Math.max(9, Math.min(15, z * .25)), bx = sx(s.x + .5) - z * .45, by = sy(s.y + .5) - z * .45;
      g.beginPath(); g.arc(bx, by, r, 0, Math.PI * 2); g.fillStyle = '#efe2bd'; g.fill(); g.lineWidth = 2; g.strokeStyle = '#7b4a14'; g.stroke();
      const ic = amIcon(at[1]);
      if (ic) g.drawImage(ic, bx - r * .7, by - r * .7, r * 1.4, r * 1.4);
    }
  }
  const gat = G ? amGroupAt(G) : null;
  if (G && gat) {                                                   // how far the group sees
    const cc = known[Math.round(gat[1]) * M.w + Math.round(gat[0])];
    const rr = (SIGHT[cc ? cc[0] : 'plains'] + .5) * z;
    g.lineWidth = 1.5; g.setLineDash([2, 6]); g.strokeStyle = 'rgba(123,74,20,.45)';
    g.beginPath(); g.arc(sx(gat[0] + .5), sy(gat[1] + .5), rr, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
  }
  if (G && AVN.route && !G.encounter && !G.fight) {                // the planned way: an inked dashed line, its stops, its end
    const pts = [[G.x, G.y], ...AVN.route.path].map(p => [sx(p[0] + .5), sy(p[1] + .5)]);
    g.lineWidth = Math.max(2.5, z * .07); g.strokeStyle = '#7b2e1a'; g.setLineDash([z * .18, z * .12]); g.lineCap = 'round';
    g.beginPath(); pts.forEach((p, k) => k ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.stroke(); g.setLineDash([]);
    for (const w of AVN.route.way) {
      g.beginPath(); g.arc(sx(w[0] + .5), sy(w[1] + .5), Math.max(5, z * .14), 0, Math.PI * 2);
      g.fillStyle = '#efe2bd'; g.fill(); g.lineWidth = 2.5; g.strokeStyle = '#7b2e1a'; g.stroke();
    }
    const e = pts[pts.length - 1];
    g.font = 'bold 13px sans-serif'; g.textAlign = 'left'; g.textBaseline = 'bottom';
    const t = S('{0} steps', AVN.route.path.length);
    g.lineWidth = 3.5; g.strokeStyle = 'rgba(239,226,189,.95)'; g.strokeText(t, e[0] + 10, e[1] - 6);
    g.fillStyle = '#7b2e1a'; g.fillText(t, e[0] + 10, e[1] - 6);
  }
  if (G && G.lead && !G.encounter && !G.fight && !AM.glide) {       // where the group may step
    g.lineWidth = 2; g.setLineDash([4, 4]); g.strokeStyle = 'rgba(43,33,24,.65)';
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const nx = G.x + dx, ny = G.y + dy, cc = known[ny * M.w + nx];
      if ((!dx && !dy) || !cc || cc[0] === 'water') continue;
      g.beginPath(); g.arc(sx(nx + .5), sy(ny + .5), Math.max(5, z * .18), 0, Math.PI * 2); g.stroke();
    }
    g.setLineDash([]);
  }
  const by = {};                                                    // every group on the map; yours larger, ringed in gold
  for (const o of M.groups) (by[o.y * M.w + o.x] = by[o.y * M.w + o.x] || []).push(o);
  const tok = amImg('group_adventurer');
  const towns = new Set(M.settlements.map(s => s.y * M.w + s.x));
  for (const list of Object.values(by)) list.forEach((o, n) => {
    const mine = G && o.id === G.id, size = Math.max(mine ? 26 : 18, Math.min(mine ? 54 : 38, z * (mine ? .8 : .55)));
    const ang = list.length > 1 ? n / list.length * Math.PI * 2 : 0, off = list.length > 1 ? size * .45 : 0;
    const at = mine && gat ? gat : [o.x, o.y];
    const inTown = !(mine && AM.glide) && towns.has(o.y * M.w + o.x);    // (beside the seal, not over it)
    const px = sx(at[0] + .5) + Math.cos(ang) * off + (inTown ? Math.max(size * .75, z * .55) : 0);
    const py = sy(at[1] + .5) - size * .35 + Math.sin(ang) * off - (inTown ? size * .3 : 0);
    g.beginPath(); g.arc(px, py, size * .55, 0, Math.PI * 2);
    g.fillStyle = mine ? 'rgba(217,164,65,.45)' : 'rgba(236,224,192,.6)'; g.fill();
    g.lineWidth = mine ? 3 : 1.5; g.strokeStyle = o.fighting ? '#a8301f' : mine ? '#d9a441' : '#2b2118'; g.stroke();
    if (tok) g.drawImage(tok, px - size / 2, py - size / 2, size, size);
    if (z >= 18 || mine) {
      g.font = `${mine ? 'bold ' : ''}11px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'bottom';
      g.lineWidth = 3; g.strokeStyle = 'rgba(236,224,192,.92)'; g.strokeText(o.name, px, py - size * .58);
      g.fillStyle = mine ? '#7b4a14' : '#2b2118'; g.fillText(o.name, px, py - size * .58);
    }
  });
  if (AM.hover) { g.lineWidth = 1.5; g.strokeStyle = 'rgba(43,33,24,.7)'; g.strokeRect(sx(AM.hover[0]) + 1, sy(AM.hover[1]) + 1, z - 2, z - 2); }
  if (AVN.pinned) { g.lineWidth = 2.5; g.strokeStyle = '#7b4a14'; g.strokeRect(sx(AVN.pinned[0]) + 1, sy(AVN.pinned[1]) + 1, z - 2, z - 2); }
  if (AM.flash) {
    const t = (performance.now() - AM.flash.t0) / 1400;
    if (t < 1) {
      g.lineWidth = 3; g.strokeStyle = `rgba(168,48,31,${1 - t})`;
      g.beginPath(); g.arc(sx(AM.flash.at[0] + .5), sy(AM.flash.at[1] + .5), z * (.4 + t * 1.2), 0, Math.PI * 2); g.stroke();
      amDraw();
    } else AM.flash = null;
  }
  if (AM.glide) amDraw();
  const hov = AM.hover && G && G.lead && !G.encounter && !G.fight && Math.max(Math.abs(AM.hover[0] - G.x), Math.abs(AM.hover[1] - G.y)) === 1;
  cv.classList.toggle('step', !!hov);
}
function amIcon(n) {                                              // an icon (black on clear) for the canvas
  let im = AM.img['i:' + n];
  if (!im) { im = AM.img['i:' + n] = new Image(); im.onload = () => amDraw(); im.src = '/advart/icons/' + n + '.svg'; }
  return im.complete && im.naturalWidth ? im : null;
}
function amPreload() { for (const n of AMART) amImg(n); }
setTimeout(() => { if (advOn()) amPreload(); }, 1500);
