// Dungeonomicon Adventurers on the player page (services/adventurers, portal/adventurers.py): one world for every
// group. The page asks for a nickname and password first (POST /api/login answers with the key a link would carry).
// Then the map pane's other face, the Adventure (body.advmode): the world as your groups have seen it, your three
// character slots, your group (members, purse and pack, quests, the fight in the way), and - in a settlement - its
// shops, the temple's and the tower's spells and services, and the tavern's quest board. While the group fights, the
// map pane shows the fight (ST.battle is the fight's lobby: portal/battlegrounds.member_lobby) with the usual action
// bar; the leader collects the spoils from here.
'use strict';
const AVN = { char: store('advchar') || null, tab: store('advtab') || 'group', shop: null, shopData: null, shopFor: null,
  q: '', zoom: store('advzoom') ?? 1, hover: null, key: '', checked: false, newChar: false, form: {} };
const BIOME_COL = { water: '#6d8ea0', plains: '#c4b983', forest: '#6c8a4b', hills: '#a48f62', mountains: '#857869',
  swamp: '#66785a', badlands: '#b48f63' };
const FEAT_MARK = { ruins: '⌂', cave: '◒', blighted: '✶', fey: '✿', shadow: '◐', arcane: '✦' };
const KIND_MARK = { city: '♜', town: '■', village: '▪', camp: '△' };
const advOn = () => !!(ST && ST.edition === 'adventurers');
const advS = () => (ST && ST.adv) || null;

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
  const box = h('div', { class: 'advlogin' },
    h('h2', null, title || 'Adventurers'),
    h('p', { class: 'dim' }, S('One world, every group. Log in, or make an account with a nickname of your own.')),
    nick, pw,
    h('div', { class: 'row' }, h('button', { class: 'primary', onclick: () => send(false) }, S('Log in')),
      h('button', { onclick: () => send(true) }, S('Create account'))), msg);
  advStyle();
  $('gate').replaceChildren(box);
  $('gate').classList.remove('hide');
  nick.focus();
}
function advLogout() {
  try { localStorage.removeItem('dm_key'); } catch { /* (nothing kept) */ }
  location.href = '/';
}

// ---------------------------------------------------------------- the face
function advStyle() {
  if ($('advstyle')) return;
  const st = h('style', { id: 'advstyle' }, `
body.advmode #map>:not(#advbody){display:none!important}#advbody{display:none}body.advmode #advbody{display:grid}
#advbody{grid-template-columns:minmax(0,1fr) minmax(300px,420px);gap:8px;height:100%;min-height:0}
#advmapwrap{position:relative;overflow:auto;min-height:0;background:var(--paper-down);border:1px solid var(--border)}
#advmap{display:block;cursor:pointer}#advside{overflow:auto;min-height:0;display:flex;flex-direction:column;gap:8px}
.advbox{background:var(--raised);border:1px solid var(--border);padding:6px 8px}.advbox h3{margin:0 0 4px;font:600 13px var(--head);color:var(--accent)}
.advrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.advrow .grow{flex:1}.advlist>div{display:flex;gap:6px;align-items:center;padding:2px 0;border-bottom:1px dotted var(--border)}
.advlist>div:last-child{border-bottom:0}.advlist .grow{flex:1;min-width:0}.advtabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}
.advq{padding:4px 0;border-bottom:1px dotted var(--border)}.advq b{color:var(--accent)}.advq p{margin:2px 0}
.advenc{border-color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,var(--raised))}.advbar{height:5px;background:var(--paper-down);margin-top:2px}
.advbar i{display:block;height:100%;background:var(--good)}.advlogin{display:flex;flex-direction:column;gap:8px;max-width:340px;margin:auto}
.advlogin input{font-size:16px}.advlogin .row{display:flex;gap:8px;justify-content:center}.advtip{position:absolute;pointer-events:none;
background:var(--paper);border:1px solid var(--edge);padding:3px 7px;font-size:12.5px;z-index:3;max-width:260px}
.advzoom{position:sticky;left:4px;top:4px;z-index:2;display:inline-flex;gap:2px}
@media (max-width:900px){#advbody{grid-template-columns:1fr;grid-template-rows:minmax(220px,45vh) auto}}`);
  document.head.append(st);
}
function advBuild() {
  if ($('advbody')) return;
  advStyle();
  const wrap = h('div', { id: 'advmapwrap' }, h('div', { class: 'advzoom' },
    h('button', { class: 'sm', onclick: () => advZoom(-1) }, '−'), h('button', { class: 'sm', onclick: () => advZoom(1) }, '+')),
  h('canvas', { id: 'advmap' }), h('div', { id: 'advtip', class: 'advtip hide' }));
  $('map').append(h('div', { id: 'advbody' }, wrap, h('div', { id: 'advside' })));
  const cv = $('advmap');
  cv.addEventListener('mousemove', e => { AVN.hover = advCellAt(e); advTip(e); drawAdvMap(); });
  cv.addEventListener('mouseleave', () => { AVN.hover = null; $('advtip').classList.add('hide'); drawAdvMap(); });
  cv.addEventListener('click', e => advClick(advCellAt(e)));
  window.addEventListener('resize', () => { if (advOn()) drawAdvMap(); });
}
function advZoom(d) {
  AVN.zoom = Math.max(0, Math.min(3, AVN.zoom + d)); store('advzoom', AVN.zoom);
  drawAdvMap(true);
}
/** The Adventure, or the fight: while the group fights the map pane shows the fight (world.js mapMode). */
function renderAdv() {
  if (!advOn()) return;
  advBuild();
  const on = mapMode() === 'adv';
  document.body.classList.toggle('advmode', on);
  $('mapmode') && $('mapmode').classList.add('hide');
  const A = advS();
  if (!A) return;
  if (!A.account) { advLogout(); return; }
  const chars = A.characters;
  if (!AVN.char || !chars.some(c => c.name === AVN.char)) AVN.char = chars.length ? chars[0].name : null;
  const key = JSON.stringify([A, AVN.char, AVN.tab, AVN.shop, AVN.shopData, AVN.q, AVN.newChar, wordsLang]);
  if (key !== AVN.key) {
    AVN.key = key;
    keepFocus($('advside'), advSide);
  }
  if (on) drawAdvMap();
}
const advMe = () => { const A = advS(); return A && A.characters.find(c => c.name === AVN.char) || null; };
const advGroup = () => { const A = advS(), c = advMe(); return A && c && c.group != null ? A.groups.find(g => g.id === c.group) || null : null; };
/** The settlement the chosen character stands in, as the page knows it (its group's, or its own when alone). */
function advTown() {
  const A = advS(), c = advMe(), g = advGroup();
  if (g) return g.here.settlement;
  return c && A.solo ? A.solo[c.name] || null : null;
}
const avMoney = cp => { cp = Math.round(cp || 0); const g = Math.floor(cp / 100), s = Math.floor(cp % 100 / 10), c = cp % 10;
  return [g ? g.toLocaleString() + ' gp' : '', s ? s + ' sp' : '', c ? c + ' cp' : ''].filter(Boolean).join(' ') || '0 gp'; };
const aact = (action, args = {}, quiet = false) => act(action, { char: AVN.char, ...args }, quiet);
function advSide() {
  const A = advS(), side = $('advside');
  const out = [advHead(A)];
  if (AVN.newChar || !A.characters.length) out.push(advCreate(A));
  const c = advMe();
  if (c) {
    out.push(advCharBox(c));
    const g = advGroup();
    out.push(g ? advGroupBox(A, g, c) : advNoGroup(A, c));
    const town = advTown();
    if (town) out.push(advTownBox(A, town, g, c));
  }
  if (A.invites.length) out.splice(1, 0, advInvites(A));
  side.replaceChildren(...out.filter(Boolean));
}
function advHead(A) {
  return h('div', { class: 'advbox' }, h('div', { class: 'advrow' },
    h('b', null, A.nick), h('span', { class: 'grow' }),
    ...A.characters.map(c => h('button', { class: 'chip' + (c.name === AVN.char ? ' on' : ''), onclick: () => { AVN.char = c.name; store('advchar', c.name);
      AVN.shop = null; AVN.shopData = null; renderAdv(); if (ST.me.characters.includes(c.name)) act('choose', { character: c.name }, true); },
    tip: `${c.summary} · ${S('HP')} ${c.hp}/${c.max_hp} · ${c.at || S('in the wilds')}` }, c.name + (c.level_up ? ' ★' : ''))),
    A.characters.length < A.slots ? h('button', { class: 'chip', onclick: () => { AVN.newChar = !AVN.newChar; renderAdv(); },
      tip: S('A new level 1 character ({0} of {1} slots used)', A.characters.length, A.slots) }, '+') : null,
    btn('⎋', advLogout, 'sm flat', S('Log out'))));
}
function advCharBox(c) {
  return h('div', { class: 'advbox' },
    h('div', { class: 'advrow' }, h('b', null, c.name), h('span', { class: 'dim' }, c.summary), h('span', { class: 'grow' }),
      c.level_up ? btn('★ ' + S('Level up'), () => aact('adv_level_up'), 'sm primary', S('Enough experience for the next level')) : null,
      btn('🗄', () => { if (window.confirm(S('Archive {0}? Only the DM can bring them back.', c.name))) return aact('adv_archive'); }, 'sm flat',
        S('Archive: frees the slot; the DM can bring the character back'))),
    h('div', { class: 'small dim' }, `${S('HP')} ${c.hp}/${c.max_hp} · ${S('XP')} ${c.xp} · ${avMoney(c.purse)} · ` +
      (c.at ? S('in {0}', c.at) : S('in the wilds'))));
}
function advCreate(A) {
  const o = A.create || {}, f = AVN.form;
  const pick = (k, list, label) => h('select', { 'aria-label': label, onchange: e => { f[k] = e.target.value; if (k === 'race') f.subrace = ''; AVN.key = ''; renderAdv(); } },
    h('option', { value: '' }, label), ...(list || []).map(n => h('option', { value: n, selected: f[k] === n }, n)));
  const race = (o.races || []).find(r => r.name === f.race);
  const costs = (o.point_buy && o.point_buy.costs) || { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
  const budget = (o.point_buy && o.point_buy.budget) || 27;
  f.scores = f.scores || { str: 13, dex: 13, con: 13, int: 12, wis: 12, cha: 12 };
  const spent = Object.values(f.scores).reduce((a, v) => a + (costs[v] ?? 99), 0);
  const name = h('input', { placeholder: S('Name (empty: one is made up)'), value: f.name || '', maxlength: 40, oninput: e => { f.name = e.target.value; } });
  return h('div', { class: 'advbox' }, h('h3', null, S('New character')),
    h('div', { class: 'advrow' }, name),
    h('div', { class: 'advrow' }, pick('race', (o.races || []).map(r => r.name), S('Race')),
      race && race.subraces && race.subraces.length ? pick('subrace', race.subraces, S('Subrace')) : null,
      pick('class', (o.classes || []).map(c => c.name), S('Class')),
      pick('background', (o.backgrounds || []).map(b => b.name || b), S('Background (random)'))),
    h('div', { class: 'advrow small' }, h('label', null, h('input', { type: 'checkbox', checked: !!f.pb, onchange: e => { f.pb = e.target.checked; AVN.key = ''; renderAdv(); } }),
      ' ' + S('Point buy (else the class\'s standard array)'))),
    f.pb ? h('div', { class: 'advrow small' }, ...['str', 'dex', 'con', 'int', 'wis', 'cha'].map(k =>
      h('label', null, k.toUpperCase() + ' ', h('select', { onchange: e => { f.scores[k] = +e.target.value; AVN.key = ''; renderAdv(); } },
        ...Object.keys(costs).map(v => h('option', { value: v, selected: +v === f.scores[k] }, v))))),
    h('b', { class: spent > budget ? 'bad' : 'good' }, S('{0} of {1} points', spent, budget))) : null,
    h('div', { class: 'advrow' }, h('span', { class: 'small dim grow' }, S('Level 1, the class\'s kit and the background\'s purse; you start in a village.')),
      btn(S('Create'), async () => {
        const spec = { name: f.name || '', race: f.race || '', subrace: f.subrace || '', class: f.class || '', background: f.background || '' };
        if (f.pb) spec.scores = f.scores;
        const r = await act('adv_create_char', { spec });
        if (r) { AVN.newChar = false; AVN.form = {}; }
      }, 'sm primary')));
}
function advInvites(A) {
  return h('div', { class: 'advbox' }, h('h3', null, S('Invitations')), h('div', { class: 'advlist' }, ...A.invites.map(i => h('div', null,
    h('span', { class: 'grow' }, S('{0} invites you (from {1})', i.name, i.by)),
    btn(S('Join with {0}', AVN.char || '?'), () => aact('adv_invite_accept', { group: i.group }), 'sm primary'),
    btn('✕', () => act('adv_invite_decline', { group: i.group }), 'sm flat', S('Decline'))))));
}
function advNoGroup(A, c) {
  const nm = h('input', { placeholder: S('Group name'), maxlength: 32 }), pw = h('input', { type: 'password', placeholder: S('Group password') });
  const ln = h('input', { placeholder: S('Group name') }), lp = h('input', { type: 'password', placeholder: S('Password') });
  const asked = A.asked.filter(x => x.char === c.name);
  return h('div', { class: 'advbox' }, h('h3', null, S('No group yet')),
    h('div', { class: 'small dim' }, S('Found a group (you are its admin), or ask to join one - its admin lets you in.')),
    h('div', { class: 'advrow' }, nm, pw, btn(S('Found'), () => aact('adv_group_create', { name: nm.value, password: pw.value }), 'sm primary')),
    asked.length ? h('div', { class: 'small warn' }, S('Waiting for {0} to answer.', asked.map(x => x.name).join(', '))) : null,
    h('div', { class: 'advlist' }, ...A.all_groups.map(g => h('div', null,
      h('span', { class: 'grow' }, h('b', null, g.name), h('span', { class: 'dim small' }, ' · ' + S('{0} members', g.size) + (g.at ? ' · ' + g.at : '') +
        (g.done ? ' · ' + S('{0} quests done', g.done) : ''))),
      asked.some(x => x.group === g.id) ? btn(S('Withdraw'), () => act('adv_withdraw', { group: g.id }), 'sm flat')
        : btn(S('Ask to join'), () => aact('adv_request', { group: g.id }), 'sm')))),
    h('div', { class: 'advrow small' }, h('span', { class: 'dim' }, S('Admin login:')), ln, lp,
      btn(S('Log in'), () => act('adv_group_login', { name: ln.value, password: lp.value }), 'sm')));
}
function advGroupBox(A, g, c) {
  const lead = g.lead, out = [];
  const head = h('div', { class: 'advrow' }, h('b', null, g.name), h('span', { class: 'dim small' },
    S('Leader: {0}', g.leader || '—') + (g.admin ? ' · ' + S('you are admin') : '')), h('span', { class: 'grow' }),
  ...['group', 'quests', 'pack', 'admin'].filter(t => t !== 'admin' || g.admin).map(t => h('button', { class: 'chip' + (AVN.tab === t ? ' on' : ''),
    onclick: () => { AVN.tab = t; store('advtab', t); renderAdv(); } }, { group: S('Group'), quests: S('Quests') + ` ${g.quests.length}/${A.max_quests}`,
    pack: S('Pack'), admin: S('Admin') + (g.requests.length ? ` (${g.requests.length})` : '') }[t])));
  out.push(head);
  const here = g.here;
  out.push(h('div', { class: 'small dim' }, (here.settlement ? here.settlement.name + ' · ' : '') + here.biome +
    (here.feature ? ' · ' + here.feature : '') + (here.chunk.landmark ? ' · ' + here.chunk.landmark : '') +
    ' · ' + here.danger + ` (${S('levels {0}-{1}', here.chunk.levels[0], here.chunk.levels[1])})`));
  if (g.fight) {
    const f = g.fight;
    out.push(h('div', { class: 'advbox advenc' }, h('div', { class: 'advrow' }, h('b', null, f.phase === 'over' ? (f.result ? S('Victory!') : S('Defeat…'))
      : S('Fighting - round {0}', f.round)), h('span', { class: 'grow' }),
    lead ? btn(f.phase === 'over' ? S('Collect the spoils') : S('End the fight'), () => act('adv_finish', { group: g.id }), 'sm primary',
      S('Back to the map: loot, experience and quests are counted')) : null)));
  } else if (g.encounter) {
    const e = g.encounter;
    out.push(h('div', { class: 'advbox advenc' }, h('div', null, h('b', null, '⚔ ' + e.label), ' ', h('span', { class: 'dim small' }, `(${e.rating})`)),
      h('div', { class: 'small' }, e.text + (e.why ? ' - ' + e.why : '')),
      lead ? h('div', { class: 'advrow' }, btn(S('Fight'), () => act('adv_fight', { group: g.id }), 'sm primary'),
        e.cornered ? h('span', { class: 'small bad' }, S('No escape!')) : btn(e.quest ? S('Withdraw') : S('Flee'), () => act('adv_flee', { group: g.id }), 'sm',
          e.quest ? S('Leave without a fight: the quest waits') : S('Half the time you get away; otherwise you must fight')))
        : h('div', { class: 'small dim' }, S('The leader decides: fight or flee.'))));
  }
  if (AVN.tab === 'quests') out.push(advQuests(A, g));
  else if (AVN.tab === 'pack') out.push(advPack(A, g, c));
  else if (AVN.tab === 'admin' && g.admin) out.push(advAdmin(A, g));
  else {
    out.push(h('div', { class: 'advlist' }, ...g.members.map(m => h('div', null,
      h('span', { class: 'grow' }, h('b', null, m.char), h('span', { class: 'dim small' }, ` ${S('Lv')} ${m.level} · ${m.player}${m.online ? ' ●' : ''}`),
        h('div', { class: 'advbar' }, h('i', { style: `width:${m.max_hp ? Math.max(0, Math.round(100 * m.hp / m.max_hp)) : 0}%;` +
          (m.hp <= m.max_hp / 4 ? 'background:var(--bad)' : '') }))),
      h('span', { class: 'small' }, `${m.hp}/${m.max_hp}`),
      m.mine ? btn(S('Leave'), () => { if (window.confirm(S('{0} leaves {1}?', m.char, g.name))) return act('adv_leave', { char: m.char }); }, 'sm flat') : null))));
    out.push(h('div', { class: 'small dim' }, lead ? S('Click a neighbouring place on the map to travel.') : S('The leader moves the group.')));
    out.push(h('div', { class: 'small' }, ...g.log.slice(-6).reverse().map(l => h('div', { class: 'dim' }, l.text))));
  }
  return h('div', { class: 'advbox' }, ...out);
}
function advQuests(A, g) {
  if (!g.quests.length) return h('div', { class: 'small dim' }, S('No quests: the tavern of a settlement has a board.'));
  const here = g.here.settlement;
  return h('div', null, ...g.quests.map(q => h('div', { class: 'advq' },
    h('div', { class: 'advrow' }, h('b', { class: 'grow' }, q.title), h('span', { class: 'small ' + (q.stage === 'ready' ? 'good' : 'dim') }, q.progress)),
    h('p', { class: 'small' }, q.text),
    h('div', { class: 'advrow small' }, h('span', { class: 'dim grow' }, S('Reward: {0}, {1} XP', avMoney(q.reward.cp), q.reward.xp)),
      g.lead && q.stage === 'ready' && here && here.id === q.settlement ? btn(S('Claim the reward'), () => act('adv_turn_in', { group: g.id, quest: q.id }), 'sm primary') : null,
      g.lead ? btn(S('Drop'), () => { if (window.confirm(S('Drop {0}? The settlement won\'t give your group work for a day.', q.title))) return act('adv_cancel_quest', { group: g.id, quest: q.id }); }, 'sm flat') : null))));
}
function advPack(A, g, c) {
  const gp = h('input', { type: 'number', min: 1, value: 1, style: 'width:70px' });
  const mine = ST.character && ST.character.name === c.name ? (ST.character.inventory || []) : [];
  const put = h('select', { 'aria-label': S('Put in the pack') }, h('option', { value: '' }, S('Put in the pack…')),
    ...mine.map(e => h('option', { value: e.name }, e.name + (e.qty > 1 ? ` ×${e.qty}` : ''))));
  return h('div', null,
    h('div', { class: 'advrow' }, h('b', null, S('Purse: {0}', g.purse)), h('span', { class: 'grow' }), gp,
      btn(S('Take'), () => aact('adv_take_gold', { gp: gp.value }), 'sm'), btn(S('Put'), () => aact('adv_put_gold', { gp: gp.value }), 'sm'),
      g.lead ? btn(S('Share'), () => act('adv_share', { group: g.id }), 'sm', S('Share the purse evenly among the members')) : null),
    h('div', { class: 'advlist' }, ...(g.pack.length ? g.pack.map(e => h('div', null,
      h('span', { class: 'grow' }, e.name + (e.qty > 1 ? ` ×${e.qty}` : ''), e.note ? h('span', { class: 'dim small' }, ` (${S(e.note)})`) : null),
      e.worth ? h('span', { class: 'small dim' }, avMoney(e.worth)) : null,
      e.quest ? null : btn(S('Take'), () => aact('adv_take', { item: e.name, qty: 1 }), 'sm', S('Into {0}\'s pack', c.name))))
      : [h('div', { class: 'dim small' }, S('The pack is empty.'))])),
    mine.length ? h('div', { class: 'advrow' }, put, btn(S('Put'), () => put.value && aact('adv_put', { item: put.value, qty: 1 }), 'sm')) : null);
}
function advAdmin(A, g) {
  const pw = h('input', { type: 'password', placeholder: S('New group password') });
  return h('div', null,
    h('h3', null, S('Asking to join')), h('div', { class: 'advlist' }, ...(g.requests.length ? g.requests.map(r => h('div', null,
      h('span', { class: 'grow' }, `${r.char} (${r.player})`),
      btn(S('Accept'), () => act('adv_accept', { group: g.id, who: String(r.uid), char: r.char }), 'sm primary'),
      btn(S('Decline'), () => act('adv_decline', { group: g.id, who: String(r.uid) }), 'sm flat'))) : [h('div', { class: 'dim small' }, S('Nobody.'))])),
    h('h3', null, S('Players online')), h('div', { class: 'advlist' }, ...(A.online.length ? A.online.map(p => h('div', null,
      h('span', { class: 'grow' }, p.nick), g.invites.some(i => i.uid === p.uid) ? h('span', { class: 'dim small' }, S('invited'))
        : btn(S('Invite'), () => act('adv_invite', { group: g.id, who: String(p.uid) }), 'sm'))) : [h('div', { class: 'dim small' }, S('Nobody else is on.'))])),
    h('h3', null, S('Members')), h('div', { class: 'advlist' }, ...g.members.filter(m => !m.mine).map(m => h('div', null,
      h('span', { class: 'grow' }, `${m.char} (${m.player})`),
      btn(S('Kick'), () => { if (window.confirm(S('Kick {0}?', m.char))) return act('adv_kick', { group: g.id, char: m.char }); }, 'sm flat')))),
    h('div', { class: 'advrow' }, pw, btn(S('Change'), () => act('adv_group_password', { group: g.id, password: pw.value }), 'sm')),
    h('div', { class: 'advrow' }, btn(S('Log out as admin'), () => act('adv_group_logout', { group: g.id }), 'sm flat')));
}
function advTownBox(A, town, g, c) {
  if (!AVN.shop || !town.shops.some(s => s.key === AVN.shop)) AVN.shop = town.shops[0].key;
  const sh = town.shops.find(s => s.key === AVN.shop);
  const tabs = h('div', { class: 'advtabs' }, ...town.shops.map(s => h('button', { class: 'chip' + (s.key === AVN.shop ? ' on' : ''),
    onclick: () => { AVN.shop = s.key; AVN.shopData = null; AVN.q = ''; renderAdv(); }, tip: `${s.owner.name}, ${s.owner.title} (${s.owner.race}) - ${s.owner.trait}` }, s.icon + ' ' + s.label)));
  const body = [h('div', { class: 'small' }, h('b', null, sh.name), h('span', { class: 'dim' }, ` · ${sh.owner.name}, ${S(sh.owner.title)}: `), h('i', null, '"' + sh.owner.greeting + '"'))];
  const dataKey = sh.key + '|' + c.name + '|' + c.purse + '|' + (ST.character ? ST.character.name : '');
  if (AVN.shopFor !== dataKey) {                        // the shop's stock and offers: asked once per visit and purse
    AVN.shopFor = dataKey;
    AVN.shopData = null;
    aact('adv_shop', { shop: sh.key }, true).then(r => { if (r && r.data && AVN.shopFor === dataKey) { AVN.shopData = r.data; AVN.key = ''; renderAdv(); } });
  }
  if (sh.kind === 'tavern') body.push(advBoard(town, g));
  const d = AVN.shopData;
  if (d) {
    if (d.services.length) body.push(h('div', { class: 'advlist' }, ...d.services.map(s => h('div', null,
      h('span', { class: 'grow' }, h('b', null, S(s.label)), h('span', { class: 'dim small' }, ' ' + S(s.text))), h('span', { class: 'small' }, avMoney(s.cp)),
      btn(S('Ask'), () => aact('adv_service', { shop: sh.key, what: s.key }), 'sm')))));
    if (d.spells.length) body.push(h('h3', null, S('Spells taught here')), h('div', { class: 'advlist' }, ...d.spells.map(s => h('div', null,
      h('span', { class: 'grow' }, s.name, h('span', { class: 'dim small' }, ` ${s.level ? S('level {0}', s.level) : S('cantrip')} · ${s.class}`)),
      h('span', { class: 'small' }, avMoney(s.cp)),
      btn(S('Learn'), async () => {
        let r = await aact('adv_learn', { shop: sh.key, spell: s.name }, false);
        if (!r) {
          const forget = window.prompt(S('Which spell does {0} forget to learn {1}?', c.name, s.name));
          if (forget) r = await aact('adv_learn', { shop: sh.key, spell: s.name, forget });
        }
      }, 'sm')))));
    const rows = d.stock.filter(r => !AVN.q || r.name.toLowerCase().includes(AVN.q.toLowerCase()));
    if (d.stock.length) {
      body.push(h('div', { class: 'advrow' }, h('input', { placeholder: S('Find…'), value: AVN.q, oninput: e => { AVN.q = e.target.value; renderAdv(); } }),
        h('span', { class: 'small dim' }, S('Your purse: {0}', avMoney(d.purse)))));
      body.push(h('div', { class: 'advlist' }, ...rows.slice(0, 80).map(r => h('div', null,
        h('span', { class: 'grow' + (r.magic ? ' acc' : '') }, r.name), h('span', { class: 'small' + (r.cp > d.purse ? ' bad' : '') }, avMoney(r.cp)),
        btn(S('Buy'), () => aact('adv_buy', { shop: sh.key, item: r.name, qty: 1 }), 'sm', null)))),
      rows.length > 80 ? h('div', { class: 'small dim' }, S('{0} more: narrow it down', rows.length - 80)) : null);
    }
    if (g && sh.kind !== 'tavern' && g.pack.some(e => !e.quest && e.worth)) {
      body.push(h('h3', null, S('Sell from the pack')), h('div', { class: 'advlist' }, ...g.pack.filter(e => !e.quest && e.worth).map(e => h('div', null,
        h('span', { class: 'grow' }, e.name + (e.qty > 1 ? ` ×${e.qty}` : '')), h('span', { class: 'small' }, avMoney(e.worth)),
        btn(S('Sell'), () => aact('adv_sell', { shop: sh.key, item: e.name, qty: 1, pack: true }), 'sm'),
        e.qty > 1 ? btn(S('All'), () => aact('adv_sell', { shop: sh.key, item: e.name, qty: e.qty, pack: true }), 'sm flat') : null))));
    }
  } else body.push(h('div', { class: 'small dim' }, S('Loading…')));
  return h('div', { class: 'advbox' }, h('h3', null, town.name), tabs, ...body);
}
function advBoard(town, g) {
  const ban = town.banned_until;
  return h('div', null, h('h3', null, S('Quest board')),
    ban ? h('div', { class: 'small bad' }, S('No work for your group until {0}: you dropped a job here.', new Date(ban * 1000).toLocaleString())) : null,
    !g ? h('div', { class: 'small dim' }, S('Quests are taken by groups: found or join one.')) : null,
    ...(town.board.length ? town.board.map(q => h('div', { class: 'advq' },
      h('div', { class: 'advrow' }, h('b', { class: 'grow' }, q.title), h('span', { class: 'small dim' }, S('tier {0}', q.tier))),
      h('p', { class: 'small' }, q.text),
      h('div', { class: 'advrow small' }, h('span', { class: 'dim grow' }, S('Reward: {0}, {1} XP', avMoney(q.reward.cp), q.reward.xp) + ` · ${S('asks')} ${q.giver}`),
        g && g.lead && !ban ? btn(S('Take'), () => act('adv_take_quest', { group: g.id, quest: q.id }), 'sm primary') : null)))
      : [h('div', { class: 'small dim' }, S('Nothing pinned up right now.'))]));
}

// ---------------------------------------------------------------- the map
const ADVMAP = { cell: 10, ox: 0, oy: 0 };
function drawAdvMap(center) {
  const A = advS(), cv = $('advmap');
  if (!A || !cv || !document.body.classList.contains('advmode')) return;
  const M = A.map, wrap = $('advmapwrap');
  const fit = Math.max(6, Math.floor(Math.min((wrap.clientWidth - 2) / M.w, (wrap.clientHeight - 2) / M.h)));
  const cell = ADVMAP.cell = AVN.zoom <= 0 ? fit : Math.max(6, Math.round(Math.max(fit, wrap.clientWidth / 18) * AVN.zoom));   // (0: all of it)
  const dpr = window.devicePixelRatio || 1;
  const W = M.w * cell, H = M.h * cell;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
  }
  const x = cv.getContext('2d');
  x.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  x.fillStyle = css.getPropertyValue('--paper-down') || '#baa77d';
  x.fillRect(0, 0, W, H);
  const known = M.cells;
  for (const [i, c] of Object.entries(known)) {
    const cx = (+i % M.w) * cell, cy = Math.floor(+i / M.w) * cell;
    x.fillStyle = BIOME_COL[c[0]] || '#999';
    x.fillRect(cx, cy, cell, cell);
    if (c[0] !== 'water' && c[3] > 1) { x.fillStyle = ['', '', 'rgba(150,40,20,.10)', 'rgba(150,30,20,.22)', 'rgba(90,20,110,.30)'][c[3]]; x.fillRect(cx, cy, cell, cell); }
    if (c[1] && cell >= 9) { x.fillStyle = '#2b1d10'; x.font = `${Math.round(cell * .7)}px serif`; x.textAlign = 'center'; x.textBaseline = 'middle';
      x.fillText(FEAT_MARK[c[1]] || '•', cx + cell / 2, cy + cell / 2 + 1); }
  }
  x.strokeStyle = '#6b4a22'; x.lineWidth = Math.max(1, cell / 6); x.setLineDash([cell / 3, cell / 4]);
  for (const [i, c] of Object.entries(known)) {                // roads: to the road neighbours further on
    if (!c[2]) continue;
    const ix = +i % M.w, iy = Math.floor(+i / M.w);
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      const n = known[(iy + dy) * M.w + ix + dx];
      if (n && n[2] && ix + dx < M.w && iy + dy >= 0) { x.beginPath(); x.moveTo((ix + .5) * cell, (iy + .5) * cell); x.lineTo((ix + dx + .5) * cell, (iy + dy + .5) * cell); x.stroke(); }
    }
  }
  x.setLineDash([]);
  x.textAlign = 'center'; x.textBaseline = 'middle';
  for (const s of M.settlements) {
    const cx = (s.x + .5) * cell, cy = (s.y + .5) * cell;
    x.fillStyle = '#3a2412'; x.font = `bold ${Math.round(cell * (s.kind === 'city' ? 1.1 : .9))}px serif`;
    x.fillText(KIND_MARK[s.kind] || '▪', cx, cy);
    if (cell >= 8 && (s.kind !== 'camp' || cell >= 14)) {
      x.font = `${Math.max(9, Math.round(cell * .65))}px sans-serif`; x.fillStyle = '#1f150b';
      x.fillText(s.name, cx, cy + cell * .95);
    }
  }
  const g = advGroup(), me = g ? g.id : null;
  if (g) {                                               // quest marks
    x.fillStyle = '#a8301f'; x.font = `bold ${Math.round(cell * .9)}px sans-serif`;
    for (const q of g.quests) {
      const marks = q.kind === 'scout' ? q.targets.filter(t => !q.visited.some(v => v[0] === t[0] && v[1] === t[1])) : q.target && q.stage === 'active' ? [q.target] : [];
      for (const t of marks) x.fillText('!', (t[0] + .5) * cell, (t[1] + .5) * cell);
    }
  }
  for (const o of M.groups) {
    const cx = (o.x + .5) * cell, cy = (o.y + .5) * cell, r = Math.max(3, cell * (o.id === me ? .42 : .3));
    x.beginPath(); x.arc(cx + (o.id === me ? 0 : cell * .2), cy - (o.id === me ? 0 : cell * .2), r, 0, Math.PI * 2);
    x.fillStyle = o.id === me ? '#d9a253' : o.mine ? '#e6d29c' : '#f3ead2'; x.fill();
    x.lineWidth = o.id === me ? 2.5 : 1.2; x.strokeStyle = o.fighting ? '#a8301f' : '#2b1d10'; x.stroke();
  }
  if (g && g.lead && !g.encounter && !g.fight) {           // where the group may step
    x.strokeStyle = 'rgba(255,245,220,.9)'; x.lineWidth = 1.5;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const nx = g.x + dx, ny = g.y + dy, c = known[ny * M.w + nx];
      if (!c || c[0] === 'water' || nx < 0 || ny < 0 || nx >= M.w || ny >= M.h) continue;
      x.strokeRect(nx * cell + 1, ny * cell + 1, cell - 2, cell - 2);
    }
  }
  if (AVN.hover) { x.strokeStyle = '#1f150b'; x.lineWidth = 2; x.strokeRect(AVN.hover[0] * cell, AVN.hover[1] * cell, cell, cell); }
  if (center || !ADVMAP.centered) {
    const o = g || (advMe() ? { x: advMe().x, y: advMe().y } : null);
    if (o) { wrap.scrollLeft = (o.x + .5) * cell - wrap.clientWidth / 2; wrap.scrollTop = (o.y + .5) * cell - wrap.clientHeight / 2; ADVMAP.centered = true; }
  }
}
function advCellAt(e) {
  const cv = $('advmap'), r = cv.getBoundingClientRect(), A = advS();
  if (!A) return null;
  const cx = Math.floor((e.clientX - r.left) / ADVMAP.cell), cy = Math.floor((e.clientY - r.top) / ADVMAP.cell);
  return cx >= 0 && cy >= 0 && cx < A.map.w && cy < A.map.h ? [cx, cy] : null;
}
const BIOME_WORDS = { water: 'Water', plains: 'Plains', forest: 'Forest', hills: 'Hills', mountains: 'Mountains', swamp: 'Swamp', badlands: 'Badlands' };
const FEAT_WORDS = { ruins: 'Ruins', cave: 'Cave', blighted: 'Blighted land', fey: 'Fey-touched glade', shadow: 'Shadow rift', arcane: 'Arcane scar' };
function advTip(e) {
  const t = $('advtip'), A = advS(), p = AVN.hover;
  if (!p || !A) { t.classList.add('hide'); return; }
  const M = A.map, i = p[1] * M.w + p[0], c = M.cells[i];
  const s = M.settlements.find(s => s.x === p[0] && s.y === p[1]);
  const gs = M.groups.filter(o => o.x === p[0] && o.y === p[1]);
  const lines = [];
  if (s) lines.push(`${s.name} (${S(s.kind)})`);
  if (c) {
    lines.push(S(BIOME_WORDS[c[0]]) + (c[1] ? ' · ' + S(FEAT_WORDS[c[1]]) : '') + (c[2] ? ' · ' + S('road') : ''));
    if (M.landmarks[i]) lines.push(M.landmarks[i]);
    const tier = M.tiers[c[3]];
    if (c[0] !== 'water' && tier) lines.push(`${S(tier.name)} (${S('levels {0}-{1}', tier.levels[0], tier.levels[1])})`);
  } else lines.push(S('Unexplored'));
  for (const o of gs) lines.push('⚑ ' + o.name + ` (${o.size})` + (o.fighting ? ' ⚔' : ''));
  t.replaceChildren(...lines.map((l, k) => h('div', { class: k ? 'dim' : '' }, l)));
  const wrap = $('advmapwrap'), r = wrap.getBoundingClientRect();
  t.style.left = (e.clientX - r.left + wrap.scrollLeft + 14) + 'px'; t.style.top = (e.clientY - r.top + wrap.scrollTop + 14) + 'px';
  t.classList.remove('hide');
}
function advClick(p) {
  const g = advGroup();
  if (!p || !g || !g.lead || g.encounter || g.fight) return;
  if (Math.max(Math.abs(p[0] - g.x), Math.abs(p[1] - g.y)) !== 1) { say(S('One step at a time: a neighbouring place.'), true); return; }
  act('adv_move', { group: g.id, x: p[0], y: p[1] });
}
