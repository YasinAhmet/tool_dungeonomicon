// The Duel face of the map pane (services/duel, portal/duel.py). While the DM has duel mode open, players open
// lobbies, join one, or watch any of them (the lobby picker in the bar). In a lobby: pick what you fight as - a premade
// hero (a core class, level 1 to 12, the spells you like), a copy of your own character or a random monster of a
// challenge rating - and join; the lobby's host (or the DM) starts it. Then that duel's own map with the same order,
// action bar and reaction questions as a battle: ST.battle is the duel's meanwhile (the campaign's waits in ST._camp),
// and the battle actions sent from here act on it. Only your fighter (and what it summons) is yours to play.
'use strict';
const DU = { last: null, shown: null, draft: store('duelpick') || null, spells: {}, asking: null, monsters: {}, mfind: '' };
const DUEL_PLAY = new Set(['do', 'preview', 'reaction_mode', 'react', 'end_turn', 'move', 'death_save', 'toggle']);

const duelRoom = () => (ST && ST.duel && ST.duel.room) || null;     // the lobby I look at
/** A fight is on in the lobby I look at (the Duel button glows: world.js). */
const duelLive = () => !!(duelRoom() && duelRoom().running);
/** 'start' once when a fight I am in begins, 'gone' while duel mode is closed, else '' (mapMode follows it: world.js). */
function duelMode() {
  const r = duelRoom(), now = !ST || !ST.duel ? 'none' : r && r.running && r.fighting ? 'on:' + r.id : 'x';
  const was = DU.last;
  DU.last = now;
  if (was !== null && was !== now && now.startsWith('on:')) return 'start';
  return now === 'none' ? 'gone' : '';
}
const duelShown = () => !!(ST && ST.duel && mapMode() === 'duel');
const duelFight = () => duelShown() && duelLive() && !!(ST._camp ? ST.battle : ST.dbattle);
/** The lobby whose map the page shows (its tokens' pictures: portal.js image()), else 0. */
const duelTokenRoom = () => duelFight() ? duelRoom().id : 0;

/** The campaign's battle back in ST.battle (before a state merges in: portal.js load1). */
function duelUnswap() {
  if (ST && '_camp' in ST) { ST.battle = ST._camp; delete ST._camp; }
}
/** On the Duel tab during a fight, the page's battle is that duel's. Returns whether what the map shows changed. */
function duelSwap() {
  duelUnswap();
  const on = duelShown() && duelLive() && !!ST.dbattle && ST.dbattle.room === duelRoom().id;
  if (on) { ST._camp = ST.battle; ST.battle = ST.dbattle; }
  duelClasses();
  const key = on ? duelRoom().id : null;
  if (key === DU.shown) return false;
  DU.shown = key;
  Object.assign(UI, { cam: null, target: null, inspect: null, aim: null, move: null, ghost: null, place: null });
  FX.seen = null; FX.moves = {}; FX.items = [];               // the other map's effects don't play on this one
  requestAnimationFrame(() => { if (ST) renderMap(); });      // fitted again once the action bar has come or gone
  return true;
}
/** A battle action sent from a duel's map acts on that duel (portal.js api()). */
function duelPlay(body) {
  if (!DUEL_PLAY.has(body.action) || !duelFight() || (body.action === 'toggle' && !body.bar)) return body;
  const a = ST.battle.actions;
  return { ...body, duel: 1, room: duelRoom().id, cid: a ? a.id : undefined };
}
/** My fighter's hit points and death saves, for the action bar's death save on the duel's map (else null). */
function duelMe() {
  if (!duelFight()) return null;
  const c = ST.battle.combatants.find(x => x.id === ST.battle.fighter && x.kind === 'pc');
  if (!c) return {};
  return { current_hp: c.hp, death_saves: c.dsaves ? { success: c.dsaves[0], failure: c.dsaves[1] } : null };
}
function duelClasses() {
  const lobby = duelShown() && !duelFight();
  document.body.classList.toggle('duellobby', lobby);
  document.body.classList.toggle('duelfight', duelFight());
}

// ---------------------------------------------------------------- the face: the lobby picker, the lobby, the fight
function buildDuel() {
  if ($('duelbody')) return;
  $('map').querySelector('.mapbody').after(h('div', { id: 'duelbody', class: 'hide' }, h('div', { id: 'duelpick' }), h('aside', { id: 'duelside' })));
  $('round').after(h('span', { id: 'duelbar', class: 'hide' },
    h('select', { id: 'duelroom', onchange: e => act('duel_watch', { room: +e.target.value }, true) }), h('span', { id: 'duelhost' }), h('span', { id: 'duelnote' })));
}
function pickWords(p) {
  if (!p) return '';
  if (p.kind === 'hero') return S('{0}, level {1}', p.label || S(p.class), p.level) + (p.spells && p.spells.length ? ' · ' + S('{0} spells picked', p.spells.length) : '');
  if (p.kind === 'copy') return S('A copy of {0}', p.character);
  if (p.monster && p.name) return S('{0}, CR {1}', p.name, p.cr);
  return S('A random monster, CR {0}', p.cr);
}
const roomWords = x => `${x.mine ? '★ ' : ''}${x.name} · ${x.running ? S('fighting') : S('lobby')} (${x.n})`;
function renderDuel(mode) {
  if (!ST) return;
  buildDuel();
  duelClasses();
  const d = ST.duel, shown = !!d && mode === 'duel', fight = duelFight(), r = duelRoom();
  $('duelbody').classList.toggle('hide', !shown || fight);
  $('duelbar').classList.toggle('hide', !shown);
  if (!shown) return;
  duelBar(d, r, fight);
  if (fight) return;
  $('bname').textContent = '🤺 ' + S('Duel');
  $('round').textContent = '';
  keepFocus($('duelbody'), () => { duelPickPane(d, r); duelSidePane(d, r); });
}
/** The bar: which lobby to look at (any of them), a lobby of your own, the host's End, how the fight stands. */
function duelBar(d, r, fight) {
  const sel = $('duelroom'), key = JSON.stringify([d.rooms, r && r.id, wordsLang]);
  sel.classList.toggle('hide', !d.rooms.length);
  if (sel.dataset.k !== key && document.activeElement !== sel) {
    sel.dataset.k = key;
    sel.setAttribute('aria-label', S('Duel lobby'));
    sel.title = S('Pick a duel lobby to watch or join');
    sel.replaceChildren(...d.rooms.map(x => h('option', { value: x.id, selected: !!r && x.id === r.id }, roomWords(x))));
  }
  const busy = r && r.running && r.fighting;
  $('duelhost').replaceChildren(...[
    busy ? null : btn('＋ ' + S('New lobby'), () => act('duel_create', {}, true), 'sm', S('Open a duel lobby of your own: the others join it, you start it')),
    r && r.host_me && r.running ? btn('⏹ ' + S('End the duel'), () => ask(S('End this duel? The fight and its fighters are thrown away and everyone goes back to the lobby.'),
      S('End the duel'), () => act('duel_stop', { room: r.id }, true), 'danger'), 'sm danger') : null].filter(Boolean));
  const note = $('duelnote');
  note.classList.toggle('hide', !fight);
  if (fight) {
    const me = r.rows.find(x => x.me);
    note.className = r.winner ? 'good' : me && me.name ? 'acc' : 'dim';
    note.textContent = r.winner ? '🏆 ' + S('{0} wins the duel!', r.winner) : me && me.name ? '🤺 ' + S('You fight as {0}', me.name) : '👁 ' + S('You are watching the duel.');
  }
}

function duelDraft(d) {
  const classes = d.classes.map(c => c[0]);
  let p = DU.draft;
  if (!p || (p.kind === 'hero' && !classes.includes(p.class))) p = { kind: 'hero', class: classes.includes('Fighter') ? 'Fighter' : classes[0], level: 3, spells: [], cr: '1' };
  if (!classes.includes(p.class)) p.class = classes.includes('Fighter') ? 'Fighter' : classes[0];
  if (!d.crs.includes(p.cr)) p.cr = d.crs.includes('1') ? '1' : d.crs[0];
  if (!d.levels.includes(p.level)) p.level = d.levels[0];
  const own = (d.copies || []).map(c => c.name);
  if (p.kind === 'copy' && !own.length) p.kind = 'hero';
  if (!own.includes(p.character)) p.character = own[0];
  DU.draft = p;
  return p;
}
function saveDraft(p) { DU.draft = p; store('duelpick', p); }
function duelPickPane(d, r) {
  const el = $('duelpick');
  const intro = h('div', { class: 'dim small' }, S('A fight for fun, apart from the game: your own character is not touched and nothing of the duel stays. Pick what you fight as and join - or just watch.'));
  if (!r) {                                          // no lobby yet: open one
    const name = h('input', { placeholder: S('Lobby name (optional)'), maxlength: 40, 'aria-label': S('Lobby name (optional)') });
    el.replaceChildren(h('div', { class: 'title' }, '🤺 ' + S('Duel')), intro,
      h('div', null, S('No duel lobbies yet. Open one and the others can join it.')),
      h('div', { class: 'drow' }, name, btn('＋ ' + S('Open a lobby'), () => act('duel_create', { name: name.value }), 'primary')));
    return;
  }
  const mine = r.mine, joined = !!mine;
  if (!DU.draft && mine) DU.draft = { cr: '1', level: 3, spells: [], ...mine };
  const p = duelDraft(d), hero = p.kind === 'hero', copy = p.kind === 'copy';
  const redo = () => renderDuel(mapMode());
  const set = (k, v) => { saveDraft({ ...p, [k]: v, ...(k === 'class' || k === 'level' ? { spells: [] } : k === 'cr' ? { monster: '', name: '' } : {}) }); redo(); };
  const kind = h('span', { class: 'seg' },
    h('button', { class: hero ? 'on' : '', onclick: () => set('kind', 'hero') }, '🛡 ' + S('Premade hero')),
    (d.copies || []).length ? h('button', { class: copy ? 'on' : '', onclick: () => set('kind', 'copy') }, '📜 ' + S('My character')) : '',
    h('button', { class: hero || copy ? '' : 'on', onclick: () => set('kind', 'monster') }, '🐉 ' + S('Monster')));
  const parts = [h('div', { class: 'title' }, '🤺 ' + r.name),
    h('div', { class: 'dim small' }, r.host_me ? S('Your lobby: start it when everyone has picked.') : r.dm_host ? S("The DM's lobby: the DM starts it.") : S('Hosted by {0}, who starts it.', r.host_name)),
    intro,
    d.joined && d.joined.id !== r.id ? h('div', { class: 'warn small' }, S('You are in {0}: joining this lobby takes you out of it.', d.joined.name)) : null,
    kind];
  if (hero) {
    const info = DU.spells[p.class + ':' + p.level];
    if (!info) duelSpellInfo(p.class, p.level);
    parts.push(h('div', { class: 'drow' },
      h('label', null, S('Class'), h('select', { onchange: e => set('class', e.target.value) }, ...d.classes.map(([v, l]) => h('option', { value: v, selected: v === p.class }, l)))),
      h('label', null, S('Level'), h('select', { onchange: e => set('level', +e.target.value) }, ...d.levels.map(v => h('option', { value: v, selected: v === p.level }, String(v)))))));
    parts.push(h('div', { class: 'dim small' }, info ? info.summary : S('Loading…')));
    if (info && info.caster) {
      const c = info.caster, n = (p.spells || []).length;
      parts.push(h('div', { class: 'drow' },
        h('span', null, n ? S('Spells: {0} picked, the rest the premade\'s own', n) : S("Spells: the premade's own")),
        btn('✨ ' + S('Choose spells…'), () => duelSpellPicker(p, info), 'sm'),
        n ? btn(S('Reset'), () => { saveDraft({ ...p, spells: [] }); redo(); }, 'sm flat') : null));
      parts.push(h('div', { class: 'dim small' }, c.spells ? S('{0} cantrips and {1} spells up to level {2}', c.cantrips, c.spells, c.max_level) : S('{0} cantrips', c.cantrips)));
    } else if (info) parts.push(h('div', { class: 'dim small' }, S('No spells to pick at this level.')));
  } else if (copy) {
    const c = d.copies.find(x => x.name === p.character) || d.copies[0];
    parts.push(h('div', { class: 'drow' },
      h('label', null, S('Character'), h('select', { onchange: e => set('character', e.target.value) }, ...d.copies.map(x => h('option', { value: x.name, selected: x.name === c.name }, x.name))))));
    parts.push(h('div', { class: 'dim small' }, `${c.summary} · ${S('HP')} ${c.hp}/${c.max_hp}`));
    parts.push(h('div', { class: 'dim small' }, S('A copy of your character as it is now fights: whatever happens to it in the duel, your real character is not touched.')));
  } else {                                           // a monster of a CR: one from its list, or a random one
    const list = DU.monsters[p.cr];
    if (!list) duelMonsterList(p.cr);
    const picked = (list || []).find(m => m.id === p.monster);
    const which = h('select', { 'aria-label': S('Monster'), onchange: e => { const m = (list || []).find(x => x.id === e.target.value);
      saveDraft({ ...p, monster: m ? m.id : '', name: m ? m.name : '' }); redo(); } });
    const fill = () => {                              // (the search narrows the list as you type)
      const q = (DU.mfind || '').trim().toLowerCase();
      which.replaceChildren(h('option', { value: '' }, '🎲 ' + S('A random one')),
        ...(list || []).filter(m => m.id === p.monster || !q || m.label.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
          .map(m => h('option', { value: m.id, selected: m.id === p.monster }, `${m.label} (${m.source})`)));
    };
    fill();
    const find = h('input', { type: 'search', class: 'mfind', placeholder: S('Find a monster'), 'aria-label': S('Find a monster'),
      value: DU.mfind || '', oninput: e => { DU.mfind = e.target.value; fill(); } });
    parts.push(h('div', { class: 'drow' },
      h('label', null, S('Challenge rating'), h('select', { onchange: e => set('cr', e.target.value) }, ...d.crs.map(v => h('option', { value: v, selected: v === p.cr }, v)))),
      h('label', null, S('Monster'), which), list ? find : h('span', { class: 'dim small' }, S('Loading…'))));
    parts.push(h('div', { class: 'dim small' }, picked ? `${picked.size} ${picked.kind} · ${S('AC')} ${picked.ac} · ${S('HP')} ${picked.hp} · ${picked.source}`
      : S('A random monster of this challenge rating, picked when the duel starts.') + (list ? ' ' + S('({0} to pick from)', list.length) : '')));
  }
  const pick = () => hero ? { kind: 'hero', class: p.class, level: p.level, spells: p.spells || [] }
    : copy ? { kind: 'copy', character: p.character } : { kind: 'monster', cr: p.cr, monster: p.monster || '' };
  if (r.running) parts.push(h('div', { class: 'warn' }, r.fighting ? S('The duel is on.') : S('The duel has started - you are watching. Join the next one.')));
  else parts.push(h('div', { class: 'drow' },
    btn(joined ? S('Update my pick') : '⚔ ' + S('Join this lobby'), () => act('duel_join', { room: r.id, pick: pick() }), 'primary'),
    joined ? btn(S('Leave the lobby'), () => act('duel_leave'), 'flat') : null));
  if (joined && !r.running) parts.push(h('div', { class: 'good small' }, '✔ ' + S("You're in as {0}.", pickWords({ ...mine, label: (d.classes.find(c => c[0] === mine.class) || [])[1] }))));
  if (r.host_me && !r.running) parts.push(h('div', { class: 'drow' },
    Object.assign(btn('▶ ' + S('Start the duel'), () => act('duel_start', { room: r.id }, true), 'primary'), { disabled: !r.rows.length }),
    btn(S('Close the lobby'), () => ask(S('Close this lobby? Everyone in it is taken out.'), S('Close the lobby'), () => act('duel_close', { room: r.id }, true), 'danger'), 'flat')));
  else if (joined && !r.running) parts.push(h('div', { class: 'dim small' }, r.dm_host ? S('Waiting for the DM to start the duel.') : S('Waiting for {0} to start the duel.', r.host_name)));
  el.replaceChildren(...parts.filter(Boolean));
}
function duelSidePane(d, r) {
  const rows = (r ? r.rows : []).map(x => h('div', { class: 'drowp' + (x.me ? ' me' : '') + (x.out ? ' out' : '') },
    h('b', null, (x.host ? '👑 ' : '') + x.player), h('span', { class: 'dim small' }, x.name || pickWords(x.pick)),
    x.hp != null ? h('span', { class: 'small' }, `${x.hp}/${x.max_hp}`) : null));
  const lobbies = d.rooms.map(x => h('div', { class: 'drowp click' + (r && x.id === r.id ? ' me' : ''), tabindex: 0, role: 'button',
    onclick: () => { if (!r || x.id !== r.id) act('duel_watch', { room: x.id }, true); } },
    h('b', null, (x.mine ? '★ ' : '') + x.name), h('span', { class: 'dim small' }, (x.running ? S('fighting') : S('lobby')) + ` (${x.n})`)));
  $('duelside').replaceChildren(...[
    r ? h('div', { class: 'title' }, S('Fighters ({0})', r.rows.length)) : null,
    ...(r ? (rows.length ? rows : [h('div', { class: 'dim small' }, S('Nobody has joined yet.'))]) : []),
    r && r.winner ? h('div', { class: 'good' }, '🏆 ' + S('{0} wins the duel!', r.winner)) : null,
    d.rooms.length ? h('div', { class: 'title wgap' }, S('Lobbies ({0})', d.rooms.length)) : null, ...lobbies,
    h('div', { class: 'dim small' }, S('Those who don\'t join watch the duel on this tab.'))].filter(Boolean));
}

// ---------------------------------------------------------------- the spells: what a class and level may pick
async function duelMonsterList(cr) {               // a challenge rating's monsters, asked once
  const key = 'cr:' + cr;
  if (DU.asking === key) return;
  DU.asking = key;
  try {
    const r = await api('/api/act', { action: 'duel_monsters', cr });
    DU.monsters[cr] = r.data.monsters;
    renderDuel(mapMode());
  } catch (e) { if (e.message !== 'login') say(e.message, true); }
  finally { if (DU.asking === key) DU.asking = null; }
}
async function duelSpellInfo(cls, level) {
  const key = cls + ':' + level;
  if (DU.asking === key) return;
  DU.asking = key;
  try {
    const r = await api('/api/act', { action: 'duel_spells', class: cls, level });
    DU.spells[key] = r.data;
    renderDuel(mapMode());
  } catch (e) { if (e.message !== 'login') say(e.message, true); }
  finally { if (DU.asking === key) DU.asking = null; }
}
function duelSpellPicker(p, info) {
  const c = info.caster, opts = c.options;
  const chosen = new Set(p.spells && p.spells.length ? p.spells : c.picked);
  const tricks = new Set(opts.filter(s => s.level === 0 && chosen.has(s.name)).map(s => s.name));
  const spells = new Set(opts.filter(s => s.level > 0 && chosen.has(s.name)).map(s => s.name));
  const counters = [];
  const recount = () => counters.forEach(f => f());
  const query = h('input', { type: 'search', placeholder: S('Find a spell'), 'aria-label': S('Find a spell'), oninput: () => {
    const q = query.value.trim().toLowerCase();
    $('detail').querySelectorAll('.prep details').forEach(dd => {
      let any = false;
      dd.querySelectorAll('.prow').forEach(row => { const hit = !q || row.dataset.name.includes(q); row.classList.toggle('hide', !hit); any = any || hit; });
      dd.classList.toggle('hide', !any);
      dd.open = q ? any : dd.dataset.open === '1';
    });
  } });
  const block = (title, sel, limit, levels) => {
    if (!limit) return null;
    const total = h('span', { class: 'pct' });
    const boxes = [];
    counters.push(() => {
      total.textContent = S('{0} of {1}', sel.size, limit);
      total.classList.toggle('good', sel.size === limit);
      boxes.forEach(([b, n]) => { b.checked = sel.has(n); });
    });
    const head = h('div', { class: 'ph' }, h('b', null, title), h('span', { class: 'grow' }), total,
      btn(S('Clear'), () => { sel.clear(); recount(); }, 'sm flat'));
    const groups = levels.map(lv => {
      const list = opts.filter(s => s.level === lv);
      const rows = list.map(sp => {
        const box = h('input', { type: 'checkbox', checked: sel.has(sp.name), onchange: () => {
          if (box.checked && sel.size >= limit) { box.checked = false; say(S('You can pick {0} - take one off first.', limit), true); return; }
          sel[box.checked ? 'add' : 'delete'](sp.name); recount();
        } });
        boxes.push([box, sp.name]);
        const text = h('div', { class: 'ptxt hide' }, `${sp.school} · ${sp.time} · ${sp.range}${sp.conc ? ' · ' + S('Concentration') : ''}\n\n${sp.text}`);
        const more = mini('ⓘ', () => { text.classList.toggle('hide'); return null; }, 'flat');
        more.setAttribute('aria-label', S('Spell text'));
        const row = h('div', { class: 'prow' }, h('label', null, box, sp.icon ? gi(sp.icon, 'sm spi') : null, h('span', { class: 'n' }, sp.label),
          sp.ritual ? h('span', { class: 'dim small' }, ' ®') : null, sp.conc ? h('span', { class: 'dim small' }, ' Ⓒ') : null), more, text);
        row.dataset.name = sp.label.toLowerCase() + ' ' + sp.name.toLowerCase();
        return row;
      });
      const one = levels.length === 1;
      const dd = h('details', { open: one || null }, h('summary', null, h('span', null, lv ? S('Level {0}', lv) : S('Cantrips')), h('span', { class: 'grow' }),
        h('span', { class: 'dim small' }, String(list.length))), ...rows);
      dd.dataset.open = one ? '1' : '0';
      dd.addEventListener('toggle', () => { if (!query.value) dd.dataset.open = dd.open ? '1' : '0'; });
      return dd;
    });
    return h('div', { class: 'pcls' }, head, ...groups);
  };
  const levels = [...new Set(opts.filter(s => s.level > 0).map(s => s.level))].sort((a, b) => a - b);
  detail(() => h('div', { class: 'prep' },
    h('div', { class: 'txt' }, h('b', null, S('Spells for the duel')), '\n' + info.summary + '\n' +
      S("What you leave open keeps the premade's own pick.") + (c.always.length ? '\n' + S('Always prepared: {0}', c.always.join(', ')) : '')),
    opts.length > 12 ? query : null,
    block(S('Cantrips'), tricks, c.cantrips, [0]),
    block(c.prepares ? S('Prepared spells') : S('Known spells'), spells, c.spells, levels)),
  () => [[S('Use these spells'), () => {
    saveDraft({ ...p, spells: [...tricks, ...spells] });
    const r = duelRoom();
    if (r && r.mine && !r.running) return act('duel_join', { room: r.id, pick: { kind: 'hero', class: p.class, level: p.level, spells: [...tricks, ...spells] } });
    renderDuel(mapMode());
    return null;
  }], [S('Cancel'), () => null, 'flat']]);
  $('detail').querySelector('.box').classList.add('wide');
  recount();
}
