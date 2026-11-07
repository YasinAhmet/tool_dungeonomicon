// Battlegrounds Mode on the player page (services/battlegrounds, portal/battlegrounds.py): the other face of the map
// pane. While the DM has the mode open, players see the lobbies the DM made - a duel, a skirmish, an arena run or a
// replay - join one as a fighter or watch any of them. In a duel or skirmish lobby they pick what they fight as (a
// configurable hero, one from the DM's pool, or a monster found with the DM's own filters) and their team; in an arena
// they build a level 1 hero and, between battles, level it up, change its spells and share the team's stash. During
// the fight the lobby's own map shows with the same order, action bar and reaction questions as a battle: for a member
// ST.battle *is* the lobby's (the server builds their page on the lobby), for a spectator ST.bgbattle stands in for it
// meanwhile (the campaign's waits in ST._camp). Only your fighter (and what it summons) is yours to play.
// A member's page is in Battlegrounds mode (body.bgmode): no character picker, no campaign modes - their sheet tab shows
// their lobby hero, the Inventory tab's team section the arena's stash.
'use strict';
const BG = { last: null, shown: null, draft: store('bgpick') || null, build: store('bgbuild') || null, opts: null, optsKey: null,
  asking: new Set(), mons: null, monsKey: '', mq: store('bgmq') || {}, mtimer: 0, tab: store('bgtab') || 'hero',
  logOpen: store('bglog') !== false, feature: null, flog: false, teamSeen: null };
const BG_PLAY = new Set(['do', 'preview', 'reaction_mode', 'react', 'end_turn', 'move', 'death_save', 'toggle']);
const TEAM_COL = { 1: '#4ade80', 2: '#f87171', 3: '#60a5fa', 4: '#fbbf24', 5: '#c084fc', 6: '#f472b6', 7: '#2dd4bf', 8: '#fb923c', 9: '#a3e635', 0: '#9aa3b2' };
const POINT_COSTS = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
const ABILS = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

const BG_NONE = { open: false, member: false, lobbies: [], lobby: null, me: null, log: [], watching: false };   // (the mode closed)
const bgApp = () => !!(ST && ST.edition === 'battlegrounds');    // the Battlegrounds app: the page is Battlegrounds alone
const bgState = () => (ST && ST.bg) || (bgApp() ? BG_NONE : null);
const bgLobby = () => (ST && ST.bg && ST.bg.lobby) || null;      // the lobby I look at
const bgMember = () => !!(ST && ST.bg && ST.bg.member);          // I fight in a lobby: my page is in Battlegrounds mode
const bgMine = () => { const l = bgLobby(); return l && ST.bg.me ? l : null; };   // the lobby I look at is the one I fight in
/** A lobby has something on its map: a battle being prepared, fought or just over, or a replay. */
const bgLive = l => !!l && (l.phase !== 'lobby' || l.mode === 'replay');
const bgShown = () => !!(bgState() && mapMode() === 'bg');
/** The fight board of the lobby I look at, as the page holds it now (a member's is ST.battle; a spectator's ST.bgbattle, or
 *  ST.battle once swapped in), else null. */
function bgBoard() {
  const l = bgLobby();
  if (!l) return null;
  for (const b of [ST.battle, ST.bgbattle]) if (b && b.bg && b.room === l.id) return b;
  return null;
}
const bgFight = () => bgShown() && bgLive(bgLobby()) && !!bgBoard();
/** The lobby whose map the page shows (its tokens' pictures: portal.js image()), else 0. */
const bgTokenRoom = () => { const b = ST && ST.battle; return b && b.bg ? b.room : 0; };
/** 'member' while I fight in a lobby (the map stays on Battlegrounds), 'start' once when the lobby I watch begins its
 *  battle, 'gone' while the mode is closed, else '' (world.js mapMode follows it). */
function bgMode() {
  if (bgApp()) return 'member';
  const g = ST && ST.bg, l = g && g.lobby;
  const now = !g ? 'none' : g.member ? 'member' : l && l.phase === 'battle' ? 'on:' + l.id + ':' + l.fights : 'x';
  const was = BG.last;
  BG.last = now;
  if (now === 'member') return 'member';
  if (was !== null && was !== now && now.startsWith('on:')) return 'start';
  return now === 'none' ? 'gone' : '';
}
/** The campaign's battle back in ST.battle (before a state merges in: portal.js load1). */
function bgUnswap() {
  if (ST && '_camp' in ST) { ST.battle = ST._camp; delete ST._camp; }
}
/** On the Battlegrounds face a spectator's page shows the lobby's battle in place of the campaign's. Returns whether what
 *  the map shows changed (the effects of the other map don't play on this one). */
function bgSwap() {
  bgUnswap();
  const g = ST && ST.bg, l = g && g.lobby;
  const on = !!(g && !g.member && bgShown() && l && ST.bgbattle && ST.bgbattle.room === l.id);
  if (on) { ST._camp = ST.battle; ST.battle = ST.bgbattle; }
  bgClasses();
  const b = ST && ST.battle;
  const key = b && b.bg && bgShown() && bgLive(l) ? `${b.room}:${l.phase}:${l.fights}` : null;
  if (key === BG.shown) return false;
  BG.shown = key;
  Object.assign(UI, { cam: null, target: null, inspect: null, aim: null, move: null, ghost: null, place: null });
  FX.seen = null; FX.moves = {}; FX.items = [];
  requestAnimationFrame(() => { if (ST) renderMap(); });      // fitted again once the action bar has come or gone
  return true;
}
/** A battle action sent from a lobby's map acts on that lobby (portal.js api()). */
function bgPlay(body) {
  if (!BG_PLAY.has(body.action) || !bgFight() || (body.action === 'toggle' && !body.bar)) return body;
  const a = ST.battle.actions;
  return { ...body, bg: 1, room: bgLobby().id, cid: a ? a.id : undefined };
}
/** My fighter's hit points and death saves, for the action bar's death save on the lobby's map (else null). */
function bgMe() {
  if (!bgFight()) return null;
  const c = ST.battle.combatants.find(x => x.id === ST.battle.fighter && x.kind === 'pc');
  if (!c) return {};
  return { current_hp: c.hp, death_saves: c.dsaves ? { success: c.dsaves[0], failure: c.dsaves[1] } : null };
}
function bgClasses() {
  const b = document.body;
  b.classList.toggle('bgmode', bgMember() || bgApp());
  b.classList.toggle('bglobby', bgShown() && !bgFight());
  b.classList.toggle('bgfight', bgFight());
}
const bgAct = (action, args = {}, quiet = true) => { const l = bgLobby(); return act(action, { room: l ? l.id : undefined, ...args }, quiet); };
const bgRedo = () => renderBG(mapMode());
const modeIcon = m => ({ duel: '🤺', skirmish: '⚔', arena: '🏟', replay: '🎞' })[m] || '⚔';
const modeWord = m => ({ duel: S('Duel'), skirmish: S('Skirmish'), arena: S('Arena'), replay: S('Replay') })[m] || m;
const teamDot = t => h('span', { class: 'tdot', style: `background:${TEAM_COL[t] || TEAM_COL[0]}`, 'aria-label': S('Team {0}', t) });

// ---------------------------------------------------------------- the face: the bar, the lobby, the fight
function buildBG() {
  if ($('bgbody')) return;
  $('map').querySelector('.mapbody').after(h('div', { id: 'bgbody', class: 'hide' }, h('div', { id: 'bgmain' }), h('aside', { id: 'bgside' })));
  $('round').after(h('span', { id: 'bgbar', class: 'hide' },
    h('select', { id: 'bgroom', onchange: e => act('bg_watch', { room: +e.target.value }, true) }), h('span', { id: 'bgnote' }),
    btn('📜', () => { BG.flog = !BG.flog; bgRedo(); return null; }, 'sm', S('The battle log'))));
  $('mapwrap').append(h('div', { id: 'bgflog', class: 'hide' }));
}
function renderBG(mode) {
  if (!ST) return;
  buildBG();
  bgClasses();
  const g = bgState(), shown = !!g && mode === 'bg', fight = bgFight(), l = bgLobby();
  $('bgbody').classList.toggle('hide', !shown || fight);
  $('bgbar').classList.toggle('hide', !shown);
  if (!shown) { $('bgflog').classList.add('hide'); return; }
  bgFeatured(l);
  bgBar(g, l, fight);
  $('bgflog').classList.toggle('hide', !(fight && BG.flog));
  if (fight) { if (BG.flog) keepFocus($('bgflog'), () => $('bgflog').replaceChildren(bgLog(g, true))); return; }
  $('bname').textContent = l ? modeIcon(l.mode) + ' ' + l.name : '';     // (the mode button already says Battlegrounds)
  $('round').textContent = '';
  keepFocus($('bgbody'), () => { bgMainPane(g, l); bgSidePane(g, l); });
}
/** A lobby the DM featured (a replay for everyone): the page switches to it once. */
function bgFeatured(l) {
  if (!l || !l.featured || BG.feature === l.featured_n) return;
  BG.feature = l.featured_n;
  if (!bgMember() && mapMode() !== 'bg') setMapMode('bg');
  if (!(ST.bg.me) && !ST.bg.watching) act('bg_watch', { room: l.id }, true);
}
const lobbyWords = x => `${x.mine ? '★ ' : ''}${modeIcon(x.mode)} ${x.name} · ${phaseWord(x)} (${x.n})`;
function phaseWord(x) {
  if (x.mode === 'replay') return S('replay');
  return { lobby: S('lobby'), setup: S('preparing'), battle: S('round {0}', x.round || 1), over: S('over') }[x.phase] || x.phase;
}
/** The bar: which lobby to look at, how the fight stands, the log. */
function bgBar(g, l, fight) {
  const sel = $('bgroom'), key = JSON.stringify([g.lobbies, l && l.id, wordsLang]);
  sel.classList.toggle('hide', !g.lobbies.length);
  if (sel.dataset.k !== key && document.activeElement !== sel) {
    sel.dataset.k = key;
    sel.setAttribute('aria-label', S('Lobby'));
    sel.title = S('Pick a lobby to watch or join');
    sel.replaceChildren(...g.lobbies.map(x => h('option', { value: x.id, selected: !!l && x.id === l.id }, lobbyWords(x))));
  }
  const note = $('bgnote');
  note.classList.toggle('hide', !fight);
  if (fight) {
    const me = g.me, r = l.result;
    note.className = r ? (r.players_won && me ? 'good' : r.draw ? 'dim' : me ? 'bad' : 'acc') : me && me.fighting ? 'acc' : 'dim';
    note.textContent = l.mode === 'replay' ? '🎞 ' + replayWords(l)
      : l.phase === 'setup' ? '⏳ ' + S('The DM is preparing the battle')
      : r ? '🏁 ' + (me ? (r.players_won ? S('Victory!') : r.draw ? S('A draw.') : S('Defeat.')) + ' ' : '') + r.text
      : me && me.fighting ? '🤺 ' + S('You fight as {0}', me.char || me.summary) : '👁 ' + S('You are watching.');
  }
}
function replayWords(l) {
  const p = l.replay || {};
  const at = S('frame {0} of {1}', (p.frame || 0) + 1, p.frames || 0);
  return p.playing ? `▶ ${at} · ${p.speed || 1}×` : `⏸ ${at}`;
}
/** The phase banner over the lobby: Lobby / preparing / Battle round N / Victory or Defeat / Replay frame x of y. */
function bgBanner(g, l) {
  const me = g.me, r = l.result;
  let cls = 'dim', text;
  if (l.mode === 'replay') text = '🎞 ' + replayWords(l);
  else if (l.phase === 'lobby') text = me ? (me.ready ? '✔ ' + S('Ready - waiting for the DM to start the battle') : '🕓 ' + S('Lobby - waiting for the DM to start the battle'))
    : '🕓 ' + S('Lobby - the players get ready');
  else if (l.phase === 'setup') { cls = 'warn'; text = '⏳ ' + S('The DM is preparing the battle'); }
  else if (l.phase === 'battle') { cls = 'acc'; text = '⚔ ' + S('Battle · round {0}', l.round || 1); }
  else if (r) { cls = r.players_won && me ? 'good' : r.draw ? 'dim' : me ? 'bad' : 'acc'; text = '🏁 ' + (me ? (r.players_won ? S('Victory!') : r.draw ? S('A draw.') : S('Defeat.')) + ' ' : '') + r.text; }
  else text = '🏁 ' + S('The battle is over');
  return h('div', { class: 'bgphase ' + cls }, h('span', { class: 'mbadge ' + l.mode }, modeIcon(l.mode) + ' ' + modeWord(l.mode)),
    h('b', null, l.name), h('span', { class: 'grow' }), h('span', null, text),
    l.mode === 'arena' ? h('span', { class: 'dim small' }, S('{0} battles won', l.stage)) : null);
}

// ---------------------------------------------------------------- the main pane
function bgMainPane(g, l) {
  const el = $('bgmain');
  const intro = h('div', { class: 'dim small' }, S('Fights for fun, apart from the game: nothing of them stays, and your real character is never touched.'));
  if (!l) {
    el.replaceChildren(h('div', { class: 'title' }, '⚔ ' + S('Battlegrounds')), intro,
      h('div', { class: 'empty dim' }, g.open ? S('No lobbies yet: the DM opens them.') : S("The DM hasn't opened Battlegrounds yet. This page follows along once a lobby is up.")));
    return;
  }
  const me = g.me, parts = [bgBanner(g, l)];
  const mine = g.lobbies.find(x => x.mine);
  if (!me && mine) parts.push(h('div', { class: 'drow' }, h('span', { class: 'warn small' }, S('You fight in {0}.', mine.name)),
    btn('↩ ' + S('Back to my lobby'), () => act('bg_watch', { room: mine.id }, true), 'sm')));
  if (l.mode === 'replay') parts.push(h('div', { class: 'card' }, h('div', null, S('A recorded battle plays here, for everyone: the DM plays, pauses and steps it.')),
    l.replay ? h('div', { class: 'dim small' }, replayWords(l)) : null));
  else if (l.phase !== 'lobby') parts.push(h('div', { class: 'card' }, l.phase === 'setup' ? S('The DM is placing everyone and the opposition. The map shows once the DM confirms.')
    : l.phase === 'battle' ? S('The battle is on.') : S('The battle is over - the lobby opens again when the DM finishes it.'),
    bgBoard() ? ' ' : null, bgBoard() ? btn('🗺 ' + S('Show the map'), () => { BG.shown = null; bgSwap(); render(); return null; }, 'sm') : null));
  else if (l.mode === 'arena') parts.push(...arenaPane(g, l));
  else parts.push(...fighterPane(g, l));
  if (me && l.phase === 'lobby') parts.push(readyRow(g, l));
  else if (!me && l.phase === 'lobby' && l.mode !== 'replay' && !mine) parts.push(h('div', { class: 'dim small' }, S('Join as a fighter above, or just watch.')));
  el.replaceChildren(...parts.filter(Boolean));
}
function readyRow(g, l) {
  const me = g.me, has = me.char || me.kind === 'monster';
  const need = l.mode === 'arena' ? (me.pending ? S('Take your level-up first.') : !me.char ? S('Build your hero first.') : '') : !has ? S('Pick a fighter first.') : '';
  return h('div', { class: 'drow ready'},
    Object.assign(btn(me.ready ? '✔ ' + S('Ready') : S("I'm ready"), () => bgAct('bg_ready', { on: !me.ready }), me.ready ? 'primary' : 'sm', need || S('Tell the DM you are ready; the DM starts the battle')), { disabled: !!need }),
    me.char ? btn('📜 ' + S('See my hero'), () => { showView('sheet'); return null; }, 'sm', S('Your lobby hero, on the character tab')) : null,
    h('span', { class: 'grow' }),
    btn(S('Leave the lobby'), () => ask(S('Leave this lobby? Your fighter here is dropped.'), S('Leave'), () => act('bg_leave', {}, true), 'danger'), 'flat'));
}

// ---------------------------------------------------------------- the forms' options (asked once per lobby)
function bgOptions(l) {
  const key = l.id + ':' + wordsLang;
  if (BG.optsKey === key) return BG.opts;
  if (!BG.asking.has('opts:' + key)) {
    BG.asking.add('opts:' + key);
    api('/api/act', { action: 'bg_options', room: l.id }).then(r => { BG.opts = r.data; BG.optsKey = key; bgRedo(); })
      .catch(e => { if (e.message !== 'login') say(e.message, true); }).finally(() => BG.asking.delete('opts:' + key));
  }
  return null;
}
const lbl = (o, n) => (o && o.labels && o.labels[n]) || n;
const selectOf = (value, rows, onchange, any) => h('select', { onchange: e => { e.target.blur(); onchange(e.target.value); } },   // (blurred: the form is rebuilt now, not when the field is left)
  any != null ? h('option', { value: '', selected: !value }, any) : null, ...rows.map(([v, t]) => h('option', { value: v, selected: v === value }, t)));
const field = (label, el) => h('label', { class: 'bgf' }, h('span', { class: 'title' }, label), el);

/** The point-buy editor: ± on each score within 8-15, the points left of the budget. */
function pointBuy(scores, budget, costs, onChange, abilities) {
  const cost = v => costs[v] != null ? costs[v] : POINT_COSTS[v] || 0;
  const spent = () => ABILS.reduce((n, a) => n + cost(scores[a]), 0);
  const left = h('span', { class: 'pbleft' });
  const rows = [];
  const refresh = () => {
    const n = budget - spent();
    left.textContent = S('{0} points left', n);
    left.className = 'pbleft ' + (n < 0 ? 'bad' : n === 0 ? 'good' : '');
    rows.forEach(f => f(n));
  };
  const names = Object.fromEntries(abilities || ABILS.map(a => [a, a.toUpperCase()]));
  const grid = h('div', { class: 'pbgrid' }, ...ABILS.map(a => {
    const val = h('b', null, String(scores[a])), mod = h('span', { class: 'dim small' });
    const minus = mini('−', () => { if (scores[a] > 8) { scores[a]--; onChange(); refresh(); } return null; }, '', S('Lower {0}', names[a]));
    const plus = mini('+', () => { if (scores[a] < 15) { scores[a]++; onChange(); refresh(); } return null; }, '', S('Raise {0}', names[a]));
    rows.push(n => { val.textContent = String(scores[a]); mod.textContent = sign(Math.floor((scores[a] - 10) / 2));
      plus.disabled = scores[a] >= 15 || n - (cost(scores[a] + 1) - cost(scores[a])) < 0; minus.disabled = scores[a] <= 8; });
    return h('div', { class: 'pb' }, h('div', { class: 'pbh' }, h('span', { class: 'title', title: names[a] }, names[a]), mod),
      h('div', { class: 'pbc' }, minus, val, plus));
  }));
  refresh();
  return h('div', { class: 'card pointbuy' }, h('div', { class: 'drow' }, h('b', null, S('Point buy')), h('span', { class: 'grow' }), left), grid);
}
const freshScores = () => ({ str: 15, dex: 14, con: 13, int: 12, wis: 10, cha: 8 });

// ---------------------------------------------------------------- duel and skirmish: team and fighter
function fighterPane(g, l) {
  const me = g.me, st = l.settings, o = bgOptions(l), parts = [];
  if (!me && l.phase !== 'lobby') return parts;
  parts.push(teamPicker(g, l));
  const kinds = (st.kinds || []).filter(k => ['hero', 'pool', 'monster'].includes(k));
  if (!kinds.includes(BG.tab)) BG.tab = kinds[0] || 'hero';
  const tabs = h('div', { class: 'tabs' }, ...kinds.map(k => h('button', { class: BG.tab === k ? 'on' : '', onclick: () => { BG.tab = k; store('bgtab', k); bgRedo(); } },
    { hero: '🛡 ' + S('Hero'), pool: '🎲 ' + S("The DM's pool") + (l.pool.length ? ` (${l.pool.length})` : ''), monster: '🐉 ' + S('Monster') }[k])));
  parts.push(h('div', { class: 'title wgap' }, me && (me.char || me.kind) ? S('Your fighter: {0}', me.summary || me.char) : S('Fight as')));
  if (me && me.char && me.kind === 'hero') parts.push(h('div', { class: 'drow' }, btn('✨ ' + S('Spells…'), () => bgSpellPicker(l), 'sm', S('Pick your hero\'s spells')),
    btn('📜 ' + S('See my hero'), () => { showView('sheet'); return null; }, 'sm')));
  parts.push(tabs);
  if (BG.tab === 'hero') parts.push(...heroForm(g, l, o));
  else if (BG.tab === 'pool') parts.push(...poolCards(g, l));
  else parts.push(...monsterSearch(g, l, o));
  return parts;
}
function teamPicker(g, l) {
  const me = g.me, ffa = !!l.settings.ffa;
  const used = {};
  for (const m of l.members) (used[m.team] = used[m.team] || []).push(m.player);
  const chips = l.teams.map(t => h('button', { class: 'chip team' + (me && me.team === t ? ' on' : ''), disabled: ffa || !me,
    style: `--tc:${TEAM_COL[t]}`, tip: used[t] ? S('Team {0}: {1}', t, used[t].join(', ')) : S('Team {0}', t),
    onclick: () => bgAct('bg_team', { team: t }) }, teamDot(t), String(t), used[t] ? h('span', { class: 'dim small' }, ` ${used[t].length}`) : null));
  return h('div', { class: 'card' }, h('div', { class: 'title' }, S('Team'), ' ', ffa ? h('span', { class: 'sup' }, S('Free-for-all: everyone on a team of their own')) : null),
    h('div', { class: 'chips' }, ...chips), !me ? h('div', { class: 'dim small' }, S('Join to pick a team.')) : null);
}
function heroDraft(o) {
  let p = BG.draft;
  if (!p || p.kind !== 'hero') p = { kind: 'hero', class: '', subclass: '', race: '', subrace: '', background: '', level: 0, abilities: 'auto', scores: freshScores(), hp: 'average', magic: 'none', name: '', gender: '' };
  if (!p.scores) p.scores = freshScores();
  if (o) {
    const cls = o.heroes.classes.find(c => c.name === p.class);
    if (p.class && !cls) p.class = '';
    if (p.subclass && !(cls && cls.subclasses.includes(p.subclass))) p.subclass = '';
    const race = o.heroes.races.find(r => r.name === p.race);
    if (p.race && !race) p.race = '';
    if (p.subrace && !(race && race.subraces.includes(p.subrace))) p.subrace = '';
  }
  BG.draft = p;
  return p;
}
const saveDraft = p => { BG.draft = p; store('bgpick', p); };
function heroForm(g, l, o) {
  const me = g.me, st = l.settings;
  if (!o) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const p = heroDraft(o), H = o.heroes;
  const set = (k, v) => { saveDraft({ ...p, [k]: v, ...(k === 'class' ? { subclass: '' } : k === 'race' ? { subrace: '' } : {}) }); bgRedo(); };
  const cls = H.classes.find(c => c.name === p.class), race = H.races.find(r => r.name === p.race);
  const level = st.free_level ? (p.level || st.level) : st.level;
  const rows = [
    field(S('Class'), selectOf(p.class, H.classes.map(c => [c.name, lbl(o, c.name)]), v => set('class', v), '🎲 ' + S('Random'))),
    cls && cls.subclasses.length ? field(S('Subclass'), selectOf(p.subclass, cls.subclasses.map(s => [s, lbl(o, s)]), v => set('subclass', v), '🎲 ' + S('Random'))) : null,
    field(S('Race'), selectOf(p.race, H.races.map(r => [r.name, lbl(o, r.name)]), v => set('race', v), '🎲 ' + S('Random'))),
    race && race.subraces.length ? field(S('Subrace'), selectOf(p.subrace, race.subraces.map(s => [s, lbl(o, s)]), v => set('subrace', v), '🎲 ' + S('Random'))) : null,
    field(S('Background'), selectOf(p.background, H.backgrounds.map(b => [b, lbl(o, b)]), v => set('background', v), '🎲 ' + S('Random'))),
    st.free_level ? field(S('Level'), selectOf(String(level), H.levels.filter(v => v <= st.max_level).map(v => [String(v), String(v)]), v => set('level', +v))) : field(S('Level'), h('b', null, String(level))),
    field(S('Abilities'), selectOf(p.abilities, [['auto', S('Standard array, by class')], ['point_buy', S('Point buy')], ['roll', S('Rolled (4d6, drop the lowest)')]], v => set('abilities', v))),
    field(S('Hit points'), selectOf(p.hp, [['average', S('Average')], ['max', S('Maximum')], ['roll', S('Rolled')]], v => set('hp', v))),
    field(S('Magic items'), selectOf(p.magic, [['none', S('None')], ['some', S('A few')], ['tier', S('Fitting the level')]], v => set('magic', v))),
    field(S('Name'), h('input', { value: p.name || '', maxlength: 40, placeholder: S('Random'), oninput: e => saveDraft({ ...p, name: e.target.value }) })),
    field(S('Gender'), selectOf(p.gender, [['male', S('Male')], ['female', S('Female')]], v => set('gender', v), '🎲 ' + S('Random'))),
  ];
  const out = [h('div', { class: 'bgform' }, ...rows.filter(Boolean))];
  if (p.abilities === 'point_buy') out.push(pointBuy(p.scores, o.point_buy || 27, H.point_buy.costs || POINT_COSTS, () => saveDraft(p), o.abilities));
  const pick = () => ({ kind: 'hero', opts: { class: p.class, subclass: p.subclass, race: p.race, subrace: p.subrace, background: p.background, level,
    abilities: p.abilities, scores: p.abilities === 'point_buy' ? p.scores : undefined, hp: p.hp, magic: p.magic, name: p.name || '', gender: p.gender || '' } });
  out.push(h('div', { class: 'drow' }, btn(me ? '🛡 ' + S('Make this my hero') : '⚔ ' + S('Join with this hero'), () => bgAct('bg_pick', { pick: pick() }, false), 'primary',
    S('The hero is made now; you can pick its spells afterwards')),
    h('span', { class: 'dim small' }, S('The rest is rolled for you.'))));
  return out;
}
function poolCards(g, l) {
  const me = g.me;
  if (!l.pool.length) return [h('div', { class: 'empty dim small' }, S('The DM has not generated any heroes yet.'))];
  return [h('div', { class: 'pool' }, ...l.pool.map(p => h('div', { class: 'pcard' + (p.mine ? ' me' : p.taken_by ? ' taken' : '') },
    h('b', null, p.name), h('span', { class: 'dim small' }, p.summary),
    h('div', { class: 'drow' }, btn('👁 ' + S('Look'), () => bgPoolLook(l, p), 'sm'),
      p.mine ? h('span', { class: 'good small' }, '✔ ' + S('Yours')) : p.taken_by ? h('span', { class: 'dim small' }, S('Taken by {0}', p.taken_by))
      : btn(me ? S('Take this hero') : '⚔ ' + S('Join as this hero'), () => bgAct('bg_pick', { pick: { kind: 'pool', id: p.id } }), 'sm primary')))))];
}
async function bgPoolLook(l, p) {
  try {
    const r = await api('/api/act', { action: 'bg_pool_sheet', room: l.id, id: p.id });
    const d = r.data;
    detail(() => h('div', { class: 'txt' }, h('b', null, d.name), '\n' + d.summary + '\n',
      h('div', { class: 'tiles' }, ...d.abilities.map(a => h('div', { class: 'tile' }, h('b', null, String(a.score)), h('span', null, `${a.label} ${sign(a.mod)}`)))),
      `\n${S('HP')} ${d.hp} · ${S('AC')} ${d.ac}\n`,
      d.attacks.length ? `\n${S('Attacks')}: ` + d.attacks.map(a => `${a.label} ${sign(a.attack)} (${a.damage})`).join(', ') : '',
      d.spells.length ? `\n${S('Spells')}: ${d.spells.join(', ')}` : '',
      d.features.length ? `\n${S('Features')}: ${d.features.join(', ')}` : '',
      d.items.length ? `\n${S('Items')}: ${d.items.join(', ')}` : ''),
    () => [p.taken_by && !p.mine ? null : [p.mine ? S('Close') : S('Take this hero'), () => p.mine ? null : bgAct('bg_pick', { pick: { kind: 'pool', id: p.id } })]]);
    $('detail').querySelector('.box').classList.add('wide');
  } catch (e) { if (e.message !== 'login') say(e.message, true); }
}

// ---------------------------------------------------------------- the monster search (the DM's filters)
function monsterSearch(g, l, o) {
  const me = g.me;
  if (!o) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const F = o.monsters, q = BG.mq;
  const setQ = (k, v) => { q[k] = v; store('bgmq', q); clearTimeout(BG.mtimer); BG.mtimer = setTimeout(() => monsterFind(l), k === 'q' ? 250 : 0); };
  const crs = (F.crs || []).map(c => [String(c), String(c)]);
  const form = h('div', { class: 'bgform mons' },
    field(S('Name'), h('input', { type: 'search', value: q.q || '', placeholder: S('Find a monster'), 'aria-label': S('Find a monster'), oninput: e => setQ('q', e.target.value) })),
    field(S('CR from'), selectOf(q.cr_min || '', crs, v => setQ('cr_min', v), S('any'))),
    field(S('CR to'), selectOf(q.cr_max || '', crs, v => setQ('cr_max', v), S('any'))),
    field(S('Type'), selectOf(q.types || '', (F.types || []).map(x => [x, lbl(o, x)]), v => setQ('types', v), S('any'))),
    field(S('Size'), selectOf(q.sizes || '', (F.sizes || []).map(x => [x, lbl(o, x)]), v => setQ('sizes', v), S('any'))),
    field(S('Environment'), selectOf(q.envs || '', (F.envs || []).map(x => [x, lbl(o, x)]), v => setQ('envs', v), S('any'))),
    field(S('Book'), selectOf(q.books || '', (F.books || []).map(([id, name]) => [id, name]), v => setQ('books', v), S('any'))));
  const key = monsKey(l);
  if (BG.monsKey !== key) monsterFind(l);
  const cr = q.cr_max || q.cr_min;
  return [form,
    h('div', { class: 'drow' }, h('span', { class: 'dim small mcount' }, monsterCount()), h('span', { class: 'grow' }),
      cr ? btn('🎲 ' + S('A random one of CR {0}', cr), () => bgAct('bg_pick', { pick: { kind: 'monster', cr } }, false), 'sm', S('Picked when the battle is prepared')) : null),
    h('div', { class: 'mlist' }, ...monsterRows(l, me))];
}
const monsKey = l => l.id + '|' + JSON.stringify(BG.mq) + '|' + wordsLang;
const monsterCount = () => BG.mons && BG.monsKey === monsKey(bgLobby()) ? S('{0} monsters', BG.mons.total) : '';
function monsterRows(l, me) {
  const res = BG.monsKey === monsKey(l) ? BG.mons : null;
  if (!res) return [h('div', { class: 'dim small' }, S('Loading…'))];
  if (!res.rows.length) return [h('div', { class: 'empty dim small' }, S('No monster matches.'))];
  return res.rows.map(m => h('div', { class: 'mrow' + (me && me.pick && me.pick.monster === m.id ? ' me' : ''), tabindex: 0, role: 'button',
    onclick: () => bgAct('bg_pick', { pick: { kind: 'monster', monster: m.id } }, false) },
    h('b', null, m.label), h('span', { class: 'dim small' }, `CR ${m.cr} · ${m.size_label} ${m.kind}`), h('span', { class: 'small' }, `${S('AC')} ${m.ac} · ${S('HP')} ${m.hp}`),
    h('span', { class: 'dim small' }, m.source)));
}
async function monsterFind(l) {
  const key = monsKey(l);
  if (BG.asking.has('mons')) { BG.monsAgain = key; return; }
  BG.asking.add('mons');
  try {
    const r = await api('/api/act', { action: 'bg_monsters', room: l.id, ...BG.mq, limit: 80 });
    BG.mons = r.data; BG.monsKey = key;
    const list = $('bgmain').querySelector('.mlist'), count = $('bgmain').querySelector('.mcount');   // (the list alone: the search box keeps its focus)
    if (list && ST.bg && ST.bg.lobby && ST.bg.lobby.id === l.id) { list.replaceChildren(...monsterRows(l, ST.bg.me)); if (count) count.textContent = monsterCount(); }
    else bgRedo();
  } catch (e) { if (e.message !== 'login') say(e.message, true); }
  finally { BG.asking.delete('mons'); if (BG.monsAgain && BG.monsAgain !== key) { BG.monsAgain = null; monsterFind(l); } }
}

// ---------------------------------------------------------------- the arena: build a hero, then level it up
function arenaPane(g, l) {
  const me = g.me, o = bgOptions(l), parts = [];
  if (!me) {
    if (l.phase === 'lobby') parts.push(h('div', { class: 'card' }, h('div', null, S('An arena run: build a level 1 hero, win battles, gain levels. Join to build yours.')),
      h('div', { class: 'drow' }, btn('⚔ ' + S('Join the arena'), () => act('bg_join', { room: l.id }, true), 'primary'))));
    return parts;
  }
  parts.push(teamPicker(g, l));
  if (!me.char) {
    parts.push(h('div', { class: 'title wgap' }, S('Build your hero')));
    if (l.pool.length) parts.push(h('div', { class: 'dim small' }, S("Or take one of the DM's heroes below.")));
    parts.push(...arenaBuilder(g, l, o));
    if (l.pool.length) parts.push(h('div', { class: 'title wgap' }, S("The DM's pool")), ...poolCards(g, l));
    return parts;
  }
  const mates = l.members.filter(m => !m.me && m.team === me.team);
  parts.push(h('div', { class: 'card hero' },
    h('div', { class: 'drow' }, h('b', { class: 'nm' }, me.char), h('span', { class: 'lvl' }, S('Level {0}', me.level || 1)), h('span', { class: 'grow' }),
      me.hp != null ? h('span', { class: 'small' }, `${S('HP')} ${me.hp}/${me.max_hp}`) : null),
    h('div', { class: 'dim small' }, me.summary),
    h('div', { class: 'drow' },
      me.pending ? btn('⬆ ' + S('Level up!') + (me.pending > 1 ? ` (${me.pending})` : ''), () => bgLevelUp(l), 'primary', S('Spend an earned level: class, hit points, features, spells')) : null,
      btn('✨ ' + S('Change spells'), () => bgSpellPicker(l), 'sm', S('Between battles you may change your spells at will')),
      btn('📜 ' + S('See my hero'), () => { showView('sheet'); return null; }, 'sm'),
      l.stash != null ? btn('🎒 ' + S('Team stash ({0})', l.stash), () => { UI.tab = 'inventory'; store('tab', 'inventory'); showView('sheet'); renderSheet(); return null; }, 'sm', S('The arena\'s team inventory: trophies and what you share')) : null),
    me.pending ? h('div', { class: 'good small' }, S('You have {0} level-up to take.', me.pending)) : null,
    mates.length ? h('div', { class: 'dim small' }, S('Teammates: {0}', mates.map(m => `${m.player} (${m.status})`).join(', '))) : null));
  if (l.history.length) parts.push(h('div', { class: 'dim small' }, S('Battles: {0}', l.history.map(x => `${x.n} ${x.won ? '✔' : '✘'}`).join(' · '))));
  return parts;
}
function arenaBuilder(g, l, o) {
  if (!o) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const H = o.heroes;
  let b = BG.build;
  if (!b || !b.scores) b = { race: '', subrace: '', class: '', scores: freshScores(), name: '' };
  if (b.race && !H.races.find(r => r.name === b.race)) b.race = '';
  if (b.class && !H.classes.find(c => c.name === b.class)) b.class = '';
  BG.build = b;
  const save = () => store('bgbuild', b);
  const set = (k, v) => { b[k] = v; if (k === 'race') b.subrace = ''; save(); bgRedo(); };
  const race = H.races.find(r => r.name === b.race);
  const form = h('div', { class: 'bgform' },
    field(S('Name'), h('input', { value: b.name || '', maxlength: 40, placeholder: S('Random'), oninput: e => { b.name = e.target.value; save(); } })),
    field(S('Race'), selectOf(b.race, H.races.map(r => [r.name, lbl(o, r.name)]), v => set('race', v), S('Choose…'))),
    race && race.subraces.length ? field(S('Subrace'), selectOf(b.subrace, race.subraces.map(s => [s, lbl(o, s)]), v => set('subrace', v), '🎲 ' + S('Random'))) : null,
    field(S('Class'), selectOf(b.class, H.classes.map(c => [c.name, lbl(o, c.name)]), v => set('class', v), S('Choose…'))));
  const ok = b.race && b.class;
  return [form, pointBuy(b.scores, o.point_buy || 27, H.point_buy.costs || POINT_COSTS, save, o.abilities),
    h('div', { class: 'drow' }, Object.assign(btn('🏟 ' + S('Enter the arena'), () => bgAct('bg_build', { race: b.race, subrace: b.subrace, class: b.class, scores: b.scores, name: b.name || '' }, false), 'primary',
      S('A level 1 hero: your race, class and scores; background, spells and gear are picked for you')), { disabled: !ok }),
      h('span', { class: 'dim small' }, S('Level 1, point buy: the rest is picked for you.')))];
}

// ---------------------------------------------------------------- pickers: a list of names, pick N
function picker(title, names, count, sel, labelOf, textOf, note) {
  if (!count || !names.length) return null;
  const total = h('span', { class: 'pct' });
  const boxes = [];
  const recount = () => { total.textContent = S('{0} of {1}', sel.size, count); total.className = 'pct ' + (sel.size === count ? 'good' : sel.size > count ? 'bad' : ''); boxes.forEach(([b, n]) => { b.checked = sel.has(n); }); };
  const rows = names.map(n => {
    const box = h('input', { type: 'checkbox', checked: sel.has(n), onchange: () => {
      if (box.checked && sel.size >= count) { box.checked = false; say(S('You can pick {0} - take one off first.', count), true); return; }
      sel[box.checked ? 'add' : 'delete'](n); recount();
    } });
    boxes.push([box, n]);
    const text = textOf ? textOf(n) : '';
    const more = text ? mini('ⓘ', () => { tx.classList.toggle('hide'); return null; }, 'flat', S('Text')) : null;
    const tx = text ? h('div', { class: 'ptxt hide' }, text) : null;
    return h('div', { class: 'prow' }, h('label', null, box, h('span', { class: 'n' }, labelOf(n))), more, tx);
  });
  const dd = h('details', { open: rows.length <= 14 || null }, h('summary', null, h('b', null, title), h('span', { class: 'grow' }), total,
    btn(S('Clear'), () => { sel.clear(); recount(); return null; }, 'sm flat')), note ? h('div', { class: 'dim small ptxt' }, note) : null, ...rows);
  recount();
  return h('div', { class: 'pcls' }, dd);
}
function spellBlock(title, rows, count, sel, levels) {
  if (!count || !rows.length) return null;
  const total = h('span', { class: 'pct' });
  const boxes = [];
  const recount = () => { total.textContent = S('{0} of {1}', sel.size, count); total.className = 'pct ' + (sel.size === count ? 'good' : sel.size > count ? 'bad' : ''); boxes.forEach(([b, n]) => { b.checked = sel.has(n); }); };
  const groups = levels.map(lv => {
    const list = rows.filter(s => s.level === lv);
    if (!list.length) return null;
    const items = list.map(sp => {
      const box = h('input', { type: 'checkbox', checked: sel.has(sp.name), onchange: () => {
        if (box.checked && sel.size >= count) { box.checked = false; say(S('You can pick {0} - take one off first.', count), true); return; }
        sel[box.checked ? 'add' : 'delete'](sp.name); recount();
      } });
      boxes.push([box, sp.name]);
      const text = h('div', { class: 'ptxt hide' }, `${sp.school} · ${sp.time} · ${sp.range}${sp.conc ? ' · ' + S('Concentration') : ''}\n\n${sp.text}`);
      const row = h('div', { class: 'prow' }, h('label', null, box, sp.icon ? gi(sp.icon, 'sm spi') : null, h('span', { class: 'n' }, sp.label),
        sp.ritual ? h('span', { class: 'dim small' }, ' ®') : null, sp.conc ? h('span', { class: 'dim small' }, ' Ⓒ') : null),
        mini('ⓘ', () => { text.classList.toggle('hide'); return null; }, 'flat', S('Spell text')), text);
      row.dataset.name = (sp.label + ' ' + sp.name).toLowerCase();
      return row;
    });
    return h('details', { open: levels.length === 1 || null }, h('summary', null, h('span', null, lv ? S('Level {0}', lv) : S('Cantrips')), h('span', { class: 'grow' }),
      h('span', { class: 'dim small' }, String(list.length))), ...items);
  }).filter(Boolean);
  recount();
  return h('div', { class: 'pcls' }, h('div', { class: 'ph' }, h('b', null, title), h('span', { class: 'grow' }), total, btn(S('Clear'), () => { sel.clear(); recount(); return null; }, 'sm flat')), ...groups);
}
const spellFind = root => h('input', { type: 'search', placeholder: S('Find a spell'), 'aria-label': S('Find a spell'), oninput: e => {
  const q = e.target.value.trim().toLowerCase();
  root.querySelectorAll('.prow[data-name]').forEach(row => row.classList.toggle('hide', !!q && !row.dataset.name.includes(q)));
  root.querySelectorAll('details').forEach(dd => { if (q) dd.open = true; });
} });

/** The hero's spells (bg_spells_info): a block per spellcasting class - cantrips, then known or prepared spells by level. */
async function bgSpellPicker(l) {
  let info;
  try { info = (await api('/api/act', { action: 'bg_spells_info', room: l.id })).data; }
  catch (e) { if (e.message !== 'login') say(e.message, true); return; }
  if (!info.classes.length) { say(S('Your hero has no spells to pick.')); return; }
  const picks = {};
  const blocks = info.classes.map(c => {
    const chosen = new Set(c.picked);
    const tricks = new Set(c.options.filter(s => s.level === 0 && chosen.has(s.name)).map(s => s.name));
    const spells = new Set(c.options.filter(s => s.level > 0 && chosen.has(s.name)).map(s => s.name));
    picks[c.class] = [tricks, spells];
    const levels = [...new Set(c.options.filter(s => s.level > 0).map(s => s.level))].sort((a, b) => a - b);
    return h('div', { class: 'spcls' }, h('div', { class: 'title' }, c.label, ' ', h('span', { class: 'sup' },
      c.spells ? S('{0} cantrips and {1} spells up to level {2}', c.cantrips, c.spells, c.max_level) : S('{0} cantrips', c.cantrips))),
      c.always.length ? h('div', { class: 'dim small' }, S('Always prepared: {0}', c.always.join(', '))) : null,
      spellBlock(S('Cantrips'), c.options.filter(s => s.level === 0), c.cantrips, tricks, [0]),
      spellBlock(c.prepares ? S('Prepared spells') : S('Known spells'), c.options.filter(s => s.level > 0), c.spells, spells, levels));
  });
  const root = h('div', { class: 'prep' }, h('div', { class: 'txt' }, h('b', null, S('Your spells')), '\n' + info.summary));
  root.append(spellFind(root), ...blocks);
  detail(() => root, () => [[S('Use these spells'), () => bgAct('bg_spells_set', { picks: Object.fromEntries(Object.entries(picks).map(([k, [a, b]]) => [k, [...a, ...b]])) }, false)],
    [S('Cancel'), () => null, 'flat']]);
  $('detail').querySelector('.box').classList.add('wide');
}

/** The level-up panel (bg_levelup_plan): class (multiclass options with their notes), hit points, subclass with its
 *  blurb, ASI or feat, skills, tools, expertise, class options, spells - everything prefilled with sensible picks - and
 *  the features gained; bg_levelup applies it. */
async function bgLevelUp(l, cls, sub) {
  let plan;
  try { plan = (await api('/api/act', { action: 'bg_levelup_plan', room: l.id, class: cls || '', subclass: sub || '' })).data; }
  catch (e) { if (e.message !== 'login') say(e.message, true); return; }
  const sg = plan.suggested || {}, L = n => (plan.labels || {})[n] || n, sp = plan.spells || {};
  const ch = { hp: sg.hp === 'roll' ? 'roll' : 'average', subclass: sg.subclass, skills: new Set(sg.skills || []), tools: new Set(sg.tools || []),
    expertise: new Set(sg.expertise || []), options: Object.fromEntries((plan.options || []).map(g => [g.key, new Set((sg.options || {})[g.key] || [])])),
    cantrips: new Set(sg.cantrips || []), spells: new Set(sg.spells || []), spellbook: new Set(sg.spellbook || []), prepared: new Set(sg.prepared || []),
    grants: Object.fromEntries(Object.keys(plan.subclass_grants || {}).map(k => [k, new Set(((sg.subclass_choices || {})[k]) || [])])),
    asi: sg.asi && sg.asi.feat ? { kind: 'feat', feat: sg.asi.feat } : { kind: '+2', a: Object.keys((sg.asi || {}).abilities || {})[0] || 'str', b: 'dex' } };
  if (sg.asi && sg.asi.abilities && Object.keys(sg.asi.abilities).length === 2) { const [a, b] = Object.keys(sg.asi.abilities); ch.asi = { kind: '+1+1', a, b }; }
  const again = (c, s) => { closeDetail(); return bgLevelUp(l, c, s); };
  const parts = [];
  const classes = (plan.classes || []).length ? plan.classes : [{ class: plan.class, ok: true }];
  parts.push(h('div', { class: 'txt' }, h('b', null, S('Level {0}', plan.total_level)), '\n' + S('{0} level {1}', L(plan.class), plan.level)));
  parts.push(h('div', { class: 'bgform' }, field(S('Class'), h('select', { onchange: e => again(e.target.value, '') }, ...classes.map(c => h('option', { value: c.class, selected: c.class === plan.class, disabled: c.ok === false }, L(c.class) + (c.note ? ` - ${c.note}` : '')))))));
  const hpSeg = h('span', { class: 'seg' }, ...[['average', S('Average') + ` (+${(plan.hp || {}).average || '?'})`], ['roll', S('Roll a d{0}', plan.hit_die)]].map(([k, w]) =>
    h('button', { class: ch.hp === k ? 'on' : '', onclick: e => { ch.hp = k; [...hpSeg.children].forEach(x => x.classList.toggle('on', x === e.currentTarget)); } }, w)));
  if (!plan.first_ever) parts.push(field(S('Hit points'), hpSeg));
  if (plan.subclass) {
    const opts = plan.subclass.options, cur = ch.subclass && opts.includes(ch.subclass) ? ch.subclass : opts[0];
    ch.subclass = cur;
    parts.push(field(plan.subclass.title || S('Subclass'), h('select', { onchange: e => again(plan.class, e.target.value) }, ...opts.map(s => h('option', { value: s, selected: s === cur }, L(s))))));
    for (const f of (plan.blurbs || {})[cur] || []) parts.push(h('div', { class: 'dim small ptxt' }, h('b', null, f.label + ': '), f.text));
  }
  if (plan.asi) {
    const names = Object.fromEntries((plan.ability_names || []).length ? plan.ability_names : ABILS.map(a => [a, a.toUpperCase()]));
    const abSel = (key, val) => h('select', { onchange: e => { ch.asi[key] = e.target.value; } }, ...ABILS.map(a => h('option', { value: a, selected: a === val }, names[a])));
    const feats = plan.feat_pool || [];
    const body = h('div', { class: 'drow' });
    const draw = () => {
      body.replaceChildren(ch.asi.kind === '+2' ? abSel('a', ch.asi.a) : ch.asi.kind === '+1+1' ? h('span', { class: 'drow' }, abSel('a', ch.asi.a), abSel('b', ch.asi.b))
        : h('select', { onchange: e => { ch.asi.feat = e.target.value; ftext.textContent = (plan.feat_texts || {})[e.target.value] || ''; } }, ...feats.map(f => h('option', { value: f, selected: f === ch.asi.feat }, L(f)))));
      ftext.textContent = ch.asi.kind === 'feat' ? (plan.feat_texts || {})[ch.asi.feat] || '' : '';
    };
    const ftext = h('div', { class: 'dim small ptxt' });
    const seg = h('span', { class: 'seg' }, ...[['+2', S('+2 to one score')], ['+1+1', S('+1 to two scores')], ...(feats.length ? [['feat', S('A feat')]] : [])].map(([k, w]) =>
      h('button', { class: ch.asi.kind === k ? 'on' : '', onclick: e => { ch.asi.kind = k; if (k === 'feat' && !ch.asi.feat) ch.asi.feat = feats[0]; [...seg.children].forEach(x => x.classList.toggle('on', x === e.currentTarget)); draw(); } }, w)));
    draw();
    parts.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Ability Score Improvement')), seg, body, ftext));
  }
  if (plan.skills) parts.push(picker(S('Skills'), plan.skills.from, plan.skills.count, ch.skills, L));
  if (plan.tools && plan.tools.count) parts.push(picker(S('Tools'), plan.tools.from, plan.tools.count, ch.tools, L));
  if (plan.expertise) parts.push(picker(S('Expertise'), plan.expertise.from, plan.expertise.count, ch.expertise, L));
  for (const g of plan.options || []) parts.push(picker(L(g.name), g.pool, g.count, ch.options[g.key], L));
  for (const [k, g] of Object.entries(plan.subclass_grants || {})) if (g && g.from) parts.push(picker(L(k), g.from, g.count, ch.grants[k], L));
  const rowsOf = names => names.map(n => (plan.spell_rows || {})[n] || { name: n, label: L(n), level: 1, school: '', time: '', range: '', text: '' });
  const levelsOf = rows => [...new Set(rows.map(s => s.level))].sort((a, b) => a - b);
  if (sp.cantrips) { const rows = rowsOf(sp.cantrip_pool || []); parts.push(spellBlock(S('Cantrips'), rows, sp.cantrips, ch.cantrips, [0])); }
  if (sp.known) { const rows = rowsOf([...(sp.spell_pool || []), ...(sp.any_class_pool || [])]); parts.push(spellBlock(S('New spells'), rows, sp.known, ch.spells, levelsOf(rows))); }
  if (sp.spellbook) { const rows = rowsOf(sp.spell_pool || []); parts.push(spellBlock(S('Into the spellbook'), rows, sp.spellbook, ch.spellbook, levelsOf(rows))); }
  if (sp.prepared) { const rows = rowsOf([...new Set([...(sp.spell_pool || []), ...ch.prepared])]); parts.push(spellBlock(S('Prepared spells'), rows, sp.prepared, ch.prepared, levelsOf(rows))); }
  if ((plan.features || []).length) parts.push(h('div', { class: 'card' }, h('div', { class: 'title' }, S('Features gained')),
    ...plan.features.map(f => h('details', null, h('summary', null, f.label || f.name), h('div', { class: 'ptxt' }, f.text)))));
  const root = h('div', { class: 'prep' }, ...parts.filter(Boolean));
  const choices = () => {
    const out = { hp: ch.hp, skills: [...ch.skills], tools: [...ch.tools], expertise: [...ch.expertise], options: Object.fromEntries(Object.entries(ch.options).map(([k, v]) => [k, [...v]])),
      cantrips: [...ch.cantrips], spells: [...ch.spells], spellbook: [...ch.spellbook], subclass_choices: Object.fromEntries(Object.entries(ch.grants).map(([k, v]) => [k, [...v]])) };
    if (plan.subclass) out.subclass = ch.subclass;
    if (sp.prepared) out.prepared = [...ch.prepared];
    if (plan.asi) out.asi = ch.asi.kind === 'feat' ? { feat: ch.asi.feat } : ch.asi.kind === '+2' ? { abilities: { [ch.asi.a]: 2 } }
      : ch.asi.a === ch.asi.b ? { abilities: { [ch.asi.a]: 2 } } : { abilities: { [ch.asi.a]: 1, [ch.asi.b]: 1 } };
    for (const k of ['skills', 'tools', 'expertise', 'cantrips', 'spells', 'spellbook']) if (!out[k].length) delete out[k];
    return out;
  };
  detail(() => root, () => [['⬆ ' + S('Gain the level'), () => bgAct('bg_levelup', { class: plan.class, choices: choices() }, false)], [S('Cancel'), () => null, 'flat']]);
  $('detail').querySelector('.box').classList.add('wide');
}

// ---------------------------------------------------------------- the side pane: fighters, lobbies, spectators, the log
function bgSidePane(g, l) {
  const rows = (l ? l.members : []).map(x => h('div', { class: 'drowp fighter' + (x.me ? ' me' : '') + (x.out ? ' out' : '') + (x.ready ? ' rdy' : '') },
    teamDot(x.team), h('b', null, x.player), h('span', { class: 'dim small n' }, x.name || x.pick || ''),
    x.hp != null ? h('span', { class: 'small' }, `${x.hp}/${x.max_hp}`) : null,
    h('span', { class: 'small st' }, (x.ready && l.phase === 'lobby' ? '✔ ' : '') + x.status + (x.pending ? ' ⬆' : ''))));
  const lobbies = g.lobbies.map(x => h('div', { class: 'drowp lobby click' + (l && x.id === l.id ? ' me' : ''), tabindex: 0, role: 'button',
    onclick: () => { if (!l || x.id !== l.id) act('bg_watch', { room: x.id }, true); } },
    h('span', { class: 'mbadge ' + x.mode }, modeIcon(x.mode)), h('b', { class: 'n' }, (x.mine ? '★ ' : '') + x.name),
    h('span', { class: 'dim small' }, `${phaseWord(x)} · ${x.n} 🤺 ${x.watching} 👁`),
    !x.mine && x.mode !== 'replay' && x.phase === 'lobby' ? btn('⚔ ' + S('Join'), e => { e.stopPropagation(); return act('bg_join', { room: x.id }, true); }, 'sm', S('Join this lobby as a fighter')) : null));
  $('bgside').replaceChildren(...[
    l ? h('div', { class: 'title' }, S('Fighters ({0})', l.members.length), l.spectators.length ? h('span', { class: 'sup' }, ` · ${S('{0} watching', l.spectators.length)}`) : null) : null,
    ...(l ? (rows.length ? rows : [h('div', { class: 'dim small' }, S('Nobody has joined yet.'))]) : []),
    g.lobbies.length ? h('div', { class: 'title wgap' }, S('Lobbies ({0})', g.lobbies.length)) : null, ...lobbies,
    l ? bgLog(g, false) : null].filter(Boolean));
}
/** The lobby's battle log: actions and dice (no movement), coloured by kind, a marker when the round changes. */
function bgLog(g, floating) {
  const entries = g.log || [];
  const items = [];
  let round = null;
  for (const e of entries) {
    if (e.round && e.round !== round) { round = e.round; items.push(h('div', { class: 'lround' }, S('Round {0}', e.round))); }
    items.push(h('div', { class: 'lentry lk-' + (e.kind || 'plain') }, rich(e.text)));
  }
  const body = h('div', { class: 'lbody' }, ...(items.length ? items : [h('div', { class: 'dim small' }, S('Nothing yet.'))]));
  if (floating) {
    const el = h('div', { class: 'lfloat' }, h('div', { class: 'title' }, '📜 ' + S('Battle log'), h('span', { class: 'grow' }), btn('✕', () => { BG.flog = false; bgRedo(); return null; }, 'sm flat')), body);
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
    return el;
  }
  const dd = h('details', { id: 'bglog', class: 'wgap', open: BG.logOpen || null, ontoggle: e => { BG.logOpen = e.target.open; store('bglog', BG.logOpen); } },
    h('summary', null, h('span', { class: 'title' }, '📜 ' + S('Battle log')), h('span', { class: 'grow' }), h('span', { class: 'dim small' }, String(entries.length))), body);
  requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  return dd;
}
