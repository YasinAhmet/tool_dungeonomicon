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
// A player may open a duel of their own (skirmishes and arenas are the DM's) and run it: its settings, starting the
// fight once everyone is ready, ending it, taking everyone back to the lobby, closing it (roomFoot, duelForm).
//
// Two screens (bgScreen): the lobby list (browseScreen: find, filter, watch or join) and a lobby (roomScreen). A lobby's
// screen keeps one rule for where things sit - top: look and configure (rules, log, settings); bottom: act; left: back
// and away (the lobby list, Leave, Close); right: onward (Join, Ready, Start). The people are the left column, my
// fighter the middle, the log a right column while it is open. Detail waits for a hover, a fold, a pick list or a sheet.
'use strict';
const BG = { last: null, shown: null, draft: store('bgpick') || null, build: store('bgbuild') || null, opts: null, optsKey: null,
  asking: new Set(), mons: null, monsKey: '', mq: store('bgmq') || {}, mtimer: 0, tab: store('bgtab') || 'hero',
  logOpen: store('bglog') === true, feature: null, flog: false, teamSeen: null,
  view: store('bgview') || 'room', lq: '', lf: '', about: {}, dd: null, ddOpen: {}, more: false, pbOpen: false,
  ctab: store('bgctab') || 'fighter', shop: null, shopKey: null, sq: '', cheap: store('bgcheap') === true,
  sr: '', sg: '', sopen: new Set(store('bgsopen') || []), sshut: new Set() };   // the shop: rarity and kind chips, open / folded categories
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
const bgFight = () => bgShown() && bgLive(bgLobby()) && !!bgBoard() && bgScreen() === 'room';
/** What the Battlegrounds face shows: 'browse' (the lobby list) or 'room' (the lobby I look at). A member whose lobby
 *  fights is held in it; someone who picked no lobby (or went back to the list) sees the list. */
function bgScreen() {
  const g = bgState(), l = g && g.lobby;
  if (!l) return 'browse';
  if (g.me && l.phase !== 'lobby') return 'room';
  if (!g.me && !g.watching) return 'browse';
  return BG.view === 'browse' ? 'browse' : 'room';
}
/** Go to a screen: 'browse' (a spectator stops watching), or a lobby's room (watched first unless it is the one shown). */
function bgGo(view, rid) {
  const g = bgState(), l = bgLobby();
  BG.view = view; store('bgview', view);
  ddClose();
  let p = null;
  if (view === 'browse' && g && !g.me && g.watching) p = act('bg_watch', {}, true);
  else if (view === 'room' && rid != null && !(l && l.id === rid && (g.me || g.watching))) p = act('bg_watch', { room: rid }, true);
  BG.shown = null; bgSwap(); render();
  return p;
}
/** The lobby whose map the page shows (its tokens' pictures: portal.js image()), else 0. */
const bgTokenRoom = () => { const b = ST && ST.battle; return b && b.bg ? b.room : 0; };
/** 'member' while I fight in a lobby (the map stays on Battlegrounds), 'start' once when the lobby I watch begins its
 *  battle, 'gone' while the mode is closed, else '' (world.js mapMode follows it). */
function bgMode() {
  if (bgApp()) return 'member';
  const g = ST && ST.bg, l = g && g.lobby;
  const now = !g ? 'none' : g.member ? 'member' : l && l.phase === 'battle' && g.watching ? 'on:' + l.id + ':' + l.fights : 'x';
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

// ---------------------------------------------------------------- the face: the lobby list, a lobby, the fight's bar
function buildBG() {
  if ($('bgbody')) return;
  $('map').querySelector('.mapbody').after(h('div', { id: 'bgbody', class: 'hide' }));
  $('round').after(h('span', { id: 'bgbar', class: 'hide' }, h('span', { id: 'bgback' }), h('span', { id: 'bgnote' }),
    h('span', { id: 'bghost' }), btn('📜', () => { BG.flog = !BG.flog; bgRedo(); return null; }, 'sm', S('The battle log'))));
  $('mapwrap').append(h('div', { id: 'bgflog', class: 'hide' }));
  // an open pick list closes on a click beside it or Escape, and follows its field when the page moves
  document.addEventListener('click', e => { const p = $('ddpop'); if (BG.dd && !(p && p.contains(e.target))) ddClose(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && BG.dd) { e.preventDefault(); e.stopPropagation(); ddClose(true); } }, true);
  addEventListener('resize', () => ddPlace());
  document.addEventListener('scroll', e => { const p = $('ddpop'); if (BG.dd && !(p && e.target.nodeType === 1 && p.contains(e.target))) ddPlace(); }, true);
}
function renderBG(mode) {
  if (!ST) return;
  buildBG();
  bgClasses();
  const g = bgState(), shown = !!g && mode === 'bg', fight = bgFight(), l = bgLobby();
  $('bgbody').classList.toggle('hide', !shown || fight);
  $('bgbar').classList.toggle('hide', !shown || !fight);
  if (!shown || fight) ddClose();
  if (!shown) { $('bgflog').classList.add('hide'); return; }
  bgFeatured(l);
  $('bgflog').classList.toggle('hide', !(fight && BG.flog));
  if (fight) { bgBar(g, l); if (BG.flog) keepFocus($('bgflog'), () => $('bgflog').replaceChildren(bgLog(g, true))); return; }
  $('bname').textContent = '';                 // (each screen has its own title row)
  $('round').textContent = '';
  const room = bgScreen() === 'room', scr = room ? 'room:' + l.id : 'browse';
  if (BG.scr !== scr) { BG.scr = scr; tip(); }     // (a hover tip of the screen that went: gone with it)
  keepFocus($('bgbody'), () => $('bgbody').replaceChildren(room ? roomScreen(g, l) : browseScreen(g)));
  if (!document.querySelector('[data-tip]:hover')) tip();   // (the hovered thing was redrawn away: its tip goes too)
  ddPlace();
}
/** A lobby the DM featured (a replay for everyone): the page switches to it once. */
function bgFeatured(l) {
  if (!l || !l.featured || BG.feature === l.featured_n) return;
  BG.feature = l.featured_n;
  BG.view = 'room';
  if (!bgMember() && mapMode() !== 'bg') setMapMode('bg');
  if (!(ST.bg.me) && !ST.bg.watching) act('bg_watch', { room: l.id }, true);
}
function phaseWord(x) {
  if (x.mode === 'replay') return S('replay');
  return { lobby: S('lobby'), setup: S('preparing'), battle: S('round {0}', x.round || 1), over: S('over') }[x.phase] || x.phase;
}
const phasePill = x => h('span', { class: 'lph ph-' + (x.mode === 'replay' ? 'replay' : x.phase) }, phaseWord(x));
/** The bar over the lobby's map while it fights: back to the lobby list (a spectator), how the fight stands, the host's
 *  steps, the log. */
function bgBar(g, l) {
  $('bgback').replaceChildren(...(g.me ? [] : [btn('‹ ' + S('Lobbies'), () => bgGo('browse'), 'sm', S('Back to the lobby list'))]));
  const hostEl = $('bghost'), hosting = l && l.hosting && l.mode !== 'replay';
  hostEl.replaceChildren(...(!hosting ? [] : l.phase === 'battle' ? [btn('⏹', () => endDuel(l), 'sm', S('End the fight'))]
    : l.phase === 'over' ? [btn('✔ ' + S('Back to the lobby'), () => bgAct('bg_finish', {}, true), 'sm primary', S('Everyone rested, back in the lobby for another round'))] : []));
  const [cls, text] = phaseText(g, l);
  const note = $('bgnote');
  note.className = cls;
  note.textContent = text;
}
function replayWords(l) {
  const p = l.replay || {};
  const at = S('frame {0} of {1}', (p.frame || 0) + 1, p.frames || 0);
  return p.playing ? `▶ ${at} · ${p.speed || 1}×` : `⏸ ${at}`;
}
/** How the lobby stands, for me: [colour, words] - waiting, preparing, the round, the result, the replay's frame. */
function phaseText(g, l) {
  const me = g.me, r = l.result;
  if (l.mode === 'replay') return ['dim', '🎞 ' + replayWords(l)];
  if (l.phase === 'lobby' && l.hosting) return ['dim', me && me.ready ? '✔ ' + S('Ready - start the duel once everyone is') : '🕓 ' + S('Lobby - get ready, then start the duel')];
  if (l.phase === 'lobby' && l.host) return ['dim', me ? (me.ready ? '✔ ' + S('Ready - waiting for {0} to start the duel', l.host) : '🕓 ' + S('Lobby - waiting for {0} to start the duel', l.host))
    : '🕓 ' + S('Lobby - the players get ready')];
  if (l.phase === 'lobby') return ['dim', me ? (me.ready ? '✔ ' + S('Ready - waiting for the DM to start the battle') : '🕓 ' + S('Lobby - waiting for the DM to start the battle'))
    : '🕓 ' + S('Lobby - the players get ready')];
  if (l.phase === 'setup') return ['warn', '⏳ ' + S('The DM is preparing the battle')];
  if (l.phase === 'battle' && !r) return [me && me.fighting ? 'acc' : 'dim', me && me.fighting ? '🤺 ' + S('You fight as {0}', me.char || me.summary) + ' · ' + S('round {0}', l.round || 1)
    : '⚔ ' + S('Battle · round {0}', l.round || 1)];
  if (r) return [r.players_won && me ? 'good' : r.draw ? 'dim' : me ? 'bad' : 'acc', '🏁 ' + (me ? (r.players_won ? S('Victory!') : r.draw ? S('A draw.') : S('Defeat.')) + ' ' : '') + r.text];
  return ['dim', '🏁 ' + S('The battle is over')];
}

// ---------------------------------------------------------------- the lobby list: find, filter, watch or join
const LMODES = ['duel', 'skirmish', 'arena', 'replay'];
function browseScreen(g) {
  const mine = g.lobbies.find(x => x.mine);
  const modes = LMODES.filter(m => g.lobbies.some(x => x.mode === m));
  if (BG.lf && !modes.includes(BG.lf)) BG.lf = '';
  const list = h('div', { class: 'lcards' }, ...g.lobbies.map(x => lobbyCard(g, x)));
  const none = h('div', { class: 'empty dim small hide' }, S('No lobby matches.'));
  const sift = () => {
    let n = 0;
    for (const c of list.children) {
      const on = (!BG.lf || c.dataset.mode === BG.lf) && (!BG.lq || c.dataset.find.includes(BG.lq.toLowerCase()));
      c.classList.toggle('hide', !on);
      if (on) n++;
    }
    none.classList.toggle('hide', !!n || !g.lobbies.length);
  };
  const top = h('div', { class: 'bgtop' },
    h('div', { class: 'side l' }, h('span', { class: 'bgtitle' }, '⚔ ' + S('Battlegrounds')),
      h('span', { class: 'about', tabindex: 0, tip: S('Battlegrounds') + '\n' + S('Fights for fun, apart from the game: nothing of them stays, and your real character is never touched.') }, 'ⓘ')),
    h('div', { class: 'side mid' },
      g.lobbies.length > 1 ? h('input', { type: 'search', class: 'lfind', value: BG.lq, placeholder: S('Find a lobby'), 'aria-label': S('Find a lobby'),
        oninput: e => { BG.lq = e.target.value.trim(); sift(); } }) : null,
      modes.length > 1 ? segOf(BG.lf, [['', S('All')], ...modes.map(m => [m, modeIcon(m), modeWord(m)])], v => { BG.lf = v; sift(); }) : null),
    h('div', { class: 'side r' }, g.can_create ? btn('🤺 ' + S('Open a duel'), () => duelForm(null), 'primary', S('Your own duel: players against each other. You set it up and start it.')) : null));
  sift();
  const empty = g.lobbies.length ? null : h('div', { class: 'empty dim' }, g.open ? (g.can_create ? S('No lobbies yet: open a duel of your own, or wait for the DM.') : S('No lobbies yet: the DM opens them.'))
    : S("The DM hasn't opened Battlegrounds yet. This page follows along once a lobby is up."));
  return h('div', { class: 'bgscreen browse' }, top,
    mine ? h('div', { class: 'mineband' }, h('span', null, '★ ' + S('You fight in {0}.', mine.name)), h('span', { class: 'grow' }),
      btn('↩ ' + S('Back to my lobby'), () => bgGo('room', mine.id), 'sm primary')) : null,
    empty || list, none);
}
/** A lobby in the list: what it is, how it stands, who is in it (the rest on hover); a click looks in, Join joins. */
function lobbyCard(g, x) {
  const join = !g.member && x.mode !== 'replay' && x.phase === 'lobby';
  const words = [`${modeWord(x.mode)} · ${x.name}`, `${phaseWord(x)} · ${S('{0} fighting', x.n)} · ${S('{0} watching', x.watching)}`,
    x.host ? S('run by {0}', x.host) : '', x.mode === 'arena' && x.stage ? S('{0} battles won', x.stage) : '',
    x.mine ? S('You fight in {0}.', x.name) : S('Click to look in.')].filter(Boolean).join('\n');
  return h('div', { class: 'lcard m-' + x.mode + (x.mine ? ' me' : ''), 'data-mode': x.mode, tip: words,
    'data-find': [x.name, x.host || '', modeWord(x.mode), phaseWord(x)].join(' ').toLowerCase(), onclick: () => bgGo('room', x.id) },
    h('span', { class: 'lic', 'aria-hidden': 'true' }, modeIcon(x.mode)),
    h('span', { class: 'lname' }, h('b', null, (x.mine ? '★ ' : '') + x.name),
      h('span', { class: 'dim small' }, modeWord(x.mode) + (x.host ? ' · ' + S('run by {0}', x.host) : ''))),
    phasePill(x),
    h('span', { class: 'lct small dim' }, `🤺 ${x.n}  👁 ${x.watching}`),
    h('span', { class: 'lacts' }, join ? btn('⚔ ' + S('Join'), e => { e.stopPropagation(); BG.view = 'room'; store('bgview', 'room'); return act('bg_join', { room: x.id }, true); },
      'sm primary', S('Join this lobby as a fighter')) : null, h('span', { class: 'lgo', 'aria-hidden': 'true' }, '›')));
}

// ---------------------------------------------------------------- a lobby: top (look, configure), people | me | log, bottom (act)
function roomScreen(g, l) {
  return h('div', { class: 'bgscreen room' }, roomTop(g, l),
    h('div', { class: 'bgmid' + (BG.logOpen ? ' withlog' : '') }, rosterPane(g, l), h('div', { class: 'bgcenter' }, ...centerParts(g, l)),
      BG.logOpen ? h('aside', { class: 'bglogpane' }, bgLog(g, false)) : null),
    roomFoot(g, l));
}
/** The lobby's rules, a line each (the host changes them in the settings). */
function rulesWords(g, l) {
  const st = l.settings || {}, map = ((g.maps || []).find(m => m.key === st.map) || {}).name || st.map;
  const kinds = { hero: S('Heroes'), pool: S("The DM's heroes"), monster: S('Monsters') };
  return [l.mode === 'arena' ? S('Start at level 1, up to {0}', st.max_level) : st.free_level ? S('Any level up to {0}', st.max_level) : S('Level {0}', st.level),
    st.ffa ? S('Free-for-all') : S('Teams'), l.mode !== 'duel' && st.difficulty ? S(st.difficulty[0].toUpperCase() + st.difficulty.slice(1)) : null,
    l.mode !== 'arena' ? (st.kinds || []).map(k => kinds[k]).filter(Boolean).join(' · ') : null, map ? '🗺 ' + map : null,
    st.spectators === false ? S('No spectators') : null, l.mode === 'arena' ? S('{0} battles won', l.stage) : null,
    st.gold ? '🪙 ' + S('{0} to shop with each round', gp(st.gold * 100)) : null].filter(Boolean);
}
/** Top: left - back to the list, which lobby, how it stands; right - its rules, the log, the host's settings. */
function roomTop(g, l) {
  const rules = l.mode === 'replay' ? [] : rulesWords(g, l), n = (g.log || []).length;
  return h('div', { class: 'bgtop' },
    h('div', { class: 'side l' },
      btn('‹ ' + S('Lobbies'), () => bgGo('browse'), 'sm', S('Back to the lobby list') + (g.me ? '\n' + S('You stay in this lobby.') : '')),
      h('span', { class: 'mbadge ' + l.mode }, modeIcon(l.mode) + ' ' + modeWord(l.mode)), h('b', { class: 'rname' }, l.name), phasePill(l),
      l.host ? h('span', { class: 'dim small' }, S('run by {0}', l.host)) : null),
    h('div', { class: 'side r' },
      rules.length ? btn('ⓘ ' + S('Rules'), () => { detail(S('The rules of this lobby') + '\n' + rules.join('\n')); return null; }, 'sm flat',
        S('The rules of this lobby') + '\n' + rules.join('\n')) : null,
      btn('📜' + (n ? ' ' + n : ''), () => { BG.logOpen = !BG.logOpen; store('bglog', BG.logOpen); bgRedo(); return null; }, 'sm' + (BG.logOpen ? ' on' : ''),
        BG.logOpen ? S('Hide the battle log') : S('Show the battle log')),
      l.hosting && l.mode !== 'replay' && l.phase === 'lobby' ? btn('⚙', () => duelForm(l), 'sm', S('Duel settings') + '\n' + S('The name, level, teams, fighters and map of your duel')) : null));
}
/** Left: the people - each team with its fighters (ready marks; the rest on hover), moving team, the spectators. */
function rosterPane(g, l) {
  const me = g.me, ffa = !!l.settings.ffa, lobby = l.phase === 'lobby' && l.mode !== 'replay';
  const used = [...new Set(l.members.map(m => m.team))].sort((a, b) => a - b), free = l.teams.find(t => !used.includes(t));
  const row = m => h('div', { class: 'rmem' + (m.me ? ' me' : '') + (m.out ? ' out' : '') + (m.ready ? ' rdy' : ''),
    tip: [m.player, m.name || m.pick || S('No fighter yet'), m.status + (m.pending ? ' · ⬆' : '')].filter(Boolean).join('\n') },
    ffa ? teamDot(m.team) : null,
    h('span', { class: 'rk', 'aria-label': m.ready ? S('Ready') : S('Not ready') }, lobby ? (m.ready ? '✔' : '○') : ''),
    h('b', { class: 'rp' }, m.player), h('span', { class: 'rn dim small' }, m.name || m.pick || ''),
    m.hp != null && !lobby ? h('span', { class: 'small' }, `${m.hp}/${m.max_hp}`) : null,
    l.hosting && !m.me && lobby ? mini('✕', () => ask(S('Send {0} out of your duel?', m.player), S('Send out'), () => bgAct('bg_kick', { uid: m.uid }, true), 'danger'),
      'kick', S('Send {0} out of your duel', m.player)) : null);
  const blocks = ffa ? [h('div', { class: 'rteam ffa' }, ...l.members.map(row))]
    : used.map(t => h('div', { class: 'rteam' + (me && me.team === t ? ' on' : ''), style: `--tc:${TEAM_COL[t] || TEAM_COL[0]}` },
      h('div', { class: 'rth' }, teamDot(t), h('span', null, S('Team {0}', t)), h('span', { class: 'grow' }),
        me && lobby && me.team !== t ? btn(S('Move here'), () => bgAct('bg_team', { team: t }), 'sm flat mv', S('Move to team {0}', t)) : null),
      ...l.members.filter(m => m.team === t).map(row)));
  return h('aside', { class: 'bgroster' },
    h('div', { class: 'title' }, S('Fighters ({0})', l.members.length), ffa ? h('span', { class: 'sup', tip: S('Free-for-all: everyone on a team of their own') }, ' · ' + S('Free-for-all')) : null),
    ...(l.members.length ? blocks : [h('div', { class: 'dim small' }, S('Nobody has joined yet.'))]),
    me && !ffa && lobby && free != null ? h('button', { class: 'rteam new', style: `--tc:${TEAM_COL[free]}`, tip: S('Start team {0}', free),
      onclick: () => bgAct('bg_team', { team: free }) }, '＋ ' + S('New team')) : null,
    l.spectators.length ? h('div', { class: 'dim small rspec', tabindex: 0, tip: S('Watching') + '\n' + l.spectators.join('\n') }, '👁 ' + S('{0} watching', l.spectators.length)) : null);
}
/** Middle: me - my fighter and what to fight as (or the arena hero), else how the lobby's battle stands. */
function centerParts(g, l) {
  const me = g.me, mine = g.lobbies.find(x => x.mine), parts = [];
  if (!me && mine) parts.push(h('div', { class: 'mineband' }, h('span', null, '★ ' + S('You fight in {0}.', mine.name)), h('span', { class: 'grow' }),
    btn('↩ ' + S('Back to my lobby'), () => bgGo('room', mine.id), 'sm')));
  if (l.mode === 'replay') parts.push(h('div', { class: 'card' }, h('div', null, S('A recorded battle plays here, for everyone: the DM plays, pauses and steps it.')),
    l.replay ? h('div', { class: 'dim small' }, replayWords(l)) : null));
  else if (l.phase !== 'lobby') parts.push(h('div', { class: 'card' }, l.phase === 'setup' ? S('The DM is placing everyone and the opposition. The map shows once the DM confirms.')
    : l.phase === 'battle' ? S('The battle is on.') : l.host ? S('The duel is over - {0} takes everyone back to the lobby.', l.host)
      : S('The battle is over - the lobby opens again when the DM finishes it.'),
    bgBoard() ? ' ' : null, bgBoard() ? btn('🗺 ' + S('Show the map'), () => { BG.shown = null; bgSwap(); render(); return null; }, 'sm') : null));
  else if (me && me.cart && BG.ctab === 'shop') parts.push(centerTabs(me), ...shopPane(g, l));   // (the lobby has a shop: settings.gold)
  else parts.push(me && me.cart ? centerTabs(me) : null, ...(l.mode === 'arena' ? arenaPane(g, l) : fighterPane(g, l)));
  return parts.filter(Boolean);
}
/** My fighter | the shop (a lobby with gold to spend each round). */
function centerTabs(me) {
  const tab = (k, words, tipText) => h('button', { class: BG.ctab === k ? 'on' : '', role: 'tab', 'aria-selected': String(BG.ctab === k), tip: tipText,
    onclick: () => { BG.ctab = k; store('bgctab', k); bgRedo(); } }, words);
  if (BG.ctab !== 'shop') BG.ctab = 'fighter';
  return h('div', { class: 'seg ktabs ctabs', role: 'tablist' }, tab('fighter', '⚔ ' + S('Fighter'), S('Your fighter')),
    tab('shop', '🪙 ' + S('Shop') + ' · ' + S('{0} left', gp(me.cart.left)), S("Spend the round's gold on gear: it is yours for the coming battle")));
}
/** What a host's duel still waits for before it may start ('' = nothing). */
function hostWhy(l) {
  const ms = l.members, teams = l.settings.ffa || new Set(ms.map(m => m.team)).size > 1;
  return ms.length < 2 ? S('Waiting for a second fighter.') : !ms.every(m => m.ready) ? S('Waiting for everyone to be ready.')
    : !teams ? S('Everyone is on the same team: someone has to pick another.') : '';
}
/** Bottom: left - away (Leave; the host's Close); middle - how it stands and what is missing; right - onward (Join,
 *  Ready, the host's Start / End / Back to the lobby). */
function roomFoot(g, l) {
  const me = g.me, live = l.mode !== 'replay', lobby = l.phase === 'lobby' && live;
  const [cls, text] = phaseText(g, l), left = [], right = [];
  let why = '';
  if (me && lobby) left.push(btn('⏏ ' + S('Leave'), () => ask(l.hosting ? S('Leave your duel? Your fighter is dropped; the next fighter runs it (nobody left: it closes).')
    : S('Leave this lobby? Your fighter here is dropped.'), S('Leave'), () => { BG.view = 'browse'; store('bgview', 'browse'); return act('bg_leave', {}, true); }, 'danger'),
  'sm flat danger', S('Leave the lobby')));
  if (l.hosting && lobby) left.push(btn('✖ ' + S('Close'), () => ask(S('Close {0}? Everyone in it is sent back.', l.name), S('Close'), () => bgAct('bg_close', {}, true), 'danger'),
    'sm flat', S('Close your duel: everyone in it is sent back')));
  if (me && lobby) {
    const has = me.char || me.kind === 'monster';
    const need = l.mode === 'arena' ? (me.pending ? S('Take your level-up first.') : !me.char ? S('Build your hero first.') : '') : !has ? S('Pick a fighter first.') : '';
    why = need;
    right.push(Object.assign(btn(me.ready ? '✔ ' + S('Ready') : S("I'm ready"), () => bgAct('bg_ready', { on: !me.ready }), me.ready ? 'on' : 'primary',
      need || (me.ready ? S('Not ready after all? Click again.') : l.host ? S('Tell the others you are ready: the duel starts once everyone is')
        : S('Tell the DM you are ready; the DM starts the battle'))), { disabled: !!need }));
  }
  if (l.hosting && live) {
    if (l.phase === 'lobby') {
      const hw = hostWhy(l);
      if (!why) why = hw;
      right.push(Object.assign(btn('▶ ' + S('Start the duel'), () => bgAct('bg_start', {}, false), 'primary', hw || S('Everyone is placed and initiative is rolled: the fight begins')), { disabled: !!hw }));
    } else if (l.phase === 'battle') right.push(btn('⏹ ' + S('End the fight'), () => endDuel(l), 'sm'));
    else if (l.phase === 'over') right.push(btn('✔ ' + S('Back to the lobby'), () => bgAct('bg_finish', {}, true), 'primary', S('Everyone rested, back in the lobby for another round')));
  }
  if (!me && !g.member && lobby) right.push(btn('⚔ ' + S('Join'), () => act('bg_join', { room: l.id }, true), 'primary',
    l.mode === 'arena' ? S('Join to build your hero') : S('Join as a fighter: pick what you fight as afterwards')));
  return h('div', { class: 'bgfoot' }, h('div', { class: 'side l' }, ...left),
    h('div', { class: 'fstat ' + cls }, h('span', { class: 'ft' }, text), why ? h('span', { class: 'why small' }, why) : null),
    h('div', { class: 'side r' }, ...right));
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
/** A choice shown rather than hidden in a list: `sect` is a titled row of the form (a div: its buttons aren't a label's). */
const sect = (label, el, note) => h('div', { class: 'bgs' }, h('span', { class: 'title' }, label, note ? h('span', { class: 'sup' }, ' ' + note) : null), el);
const CLASS_ICON = { Barbarian: 'battle-axe', Bard: 'lyre', Cleric: 'holy-symbol', Druid: 'wolf-head', Fighter: 'crossed-swords', Monk: 'fist', Paladin: 'shield',
  Ranger: 'bow-arrow', Rogue: 'plain-dagger', Sorcerer: 'fire-spell-cast', Warlock: 'pentacle', Wizard: 'spell-book', Artificer: 'cog' };
const pickOne = (el, on) => [...el.children].forEach(x => { x.classList.toggle('on', x === on); x.setAttribute('aria-pressed', String(x === on)); });
/** One of a few, side by side (a segmented control). rows: [[value, words, tip]]. */
function segOf(value, rows, onchange) {
  const el = h('span', { class: 'seg', role: 'group' }, ...rows.map(([v, w, tipText]) => h('button', { class: v === value ? 'on' : '', 'aria-pressed': String(v === value), tip: tipText,
    onclick: e => { pickOne(el, e.currentTarget); onchange(v); } }, w)));
  return el;
}
/** One of several as chips, while they fit on a few lines (a list beyond that). `any`: the words of "no choice". */
function chipsOf(value, rows, onchange, any) {
  if (rows.length > 18) return selectOf(value, rows, onchange, any);
  const all = any != null ? [['', any], ...rows] : rows;
  const el = h('div', { class: 'chips pick', role: 'group' }, ...all.map(([v, w, tipText]) => h('button', { class: 'chip' + (v === (value || '') ? ' on' : ''),
    'aria-pressed': String(v === (value || '')), tip: tipText, onclick: e => { pickOne(el, e.currentTarget); onchange(v); } }, w)));
  return el;
}
/** A whole number within lo..hi: − value +. */
function stepper(value, lo, hi, onchange, what) {
  let v = Math.max(lo, Math.min(hi, +value || lo));
  const out = h('b', null, String(v));
  const step = d => { v = Math.max(lo, Math.min(hi, v + d)); out.textContent = String(v); minus.disabled = v <= lo; plus.disabled = v >= hi; onchange(v); return null; };
  const minus = mini('−', () => step(-1), '', S('Lower {0}', what)), plus = mini('+', () => step(1), '', S('Raise {0}', what));
  minus.disabled = v <= lo; plus.disabled = v >= hi;
  return h('span', { class: 'stepper' }, minus, out, plus);
}
/** A switch as a chip: on or off. */
function toggleChip(words, on, onchange, tipText) {
  const el = h('button', { class: 'chip sw' + (on ? ' on' : ''), 'aria-pressed': String(!!on), tip: tipText,
    onclick: () => { on = !on; el.classList.toggle('on', on); el.setAttribute('aria-pressed', String(on)); onchange(on); } }, words);
  return el;
}
/** The spell presets a new hero may start with (heroes.PRESETS: the hero's class may not have every one). */
const spellStyles = () => [['', S('All-rounder'), S('A bit of everything: the picks a new hero gets.')], ['blaster', S('Blaster'), S('Damage first: bolts, blasts and anything that burns a crowd.')],
  ['control', S('Controller'), S('Hold, hinder and shape the field: saves, zones and counters.')], ['support', S('Support'), S('Keep the team standing: healing, blessings and cures.')],
  ['guard', S('Defender'), S('Hard to hit and hard to pin: wards, escapes and self-buffs.')]];

// ---------------------------------------------------------------- the pick list: a field that opens a searchable, folding list
/** A field showing a choice; a click opens its pick list. o = { key, label, value, sub, any, rows, onpick(value, sub) }:
 *  rows [{ v, label, facts, icon, about: [kind, name], text, off, kids: [rows] }] - a row with kids folds them open (▸: a
 *  class its subclasses, a race its subraces); `any` adds a first row (value '') with those words (Random). The list
 *  (#ddpop, on the page's body: a redraw of the lobby leaves it open) has a search box, the rows with their facts, and
 *  a pane telling the row under the pointer (or the keyboard): its facts and, asked once, its rules text (bg_about). */
function ddPick(o) {
  const row = o.rows.find(r => r.v === (o.value || '')), kid = row && (row.kids || []).find(k => k.v === o.sub);
  const shown = row ? row.label + (kid ? ' · ' + kid.label : '') : o.any != null ? '🎲 ' + o.any : S('Choose…');
  const open = !!(BG.dd && BG.dd.key === o.key);
  if (open) BG.dd.o = o;                               // (redrawn while open: the list keeps the newest rows and handler)
  return h('button', { class: 'ddbtn' + (row && row.v ? ' set' : ''), 'data-dd': o.key, 'aria-haspopup': 'listbox', 'aria-expanded': String(open),
    tip: row && row.v ? [shown, (kid || row).facts].filter(Boolean).join('\n') : null,
    onclick: e => { e.stopPropagation(); if (BG.dd && BG.dd.key === o.key) ddClose(); else ddOpen(o, e.currentTarget); } },
  h('span', { class: 'ddl' }, o.label), h('span', { class: 'ddv' }, shown), h('span', { class: 'ddc', 'aria-hidden': 'true' }, '▾'));
}
function ddOpen(o, anchor) {
  ddClose();
  const st = BG.dd = { key: o.key, o, anchor, q: '', act: -1, flat: [], open: new Set(BG.ddOpen[o.key] || (o.sub ? [o.value] : [])), infoFor: null };
  const find = h('input', { type: 'search', placeholder: S('Search'), 'aria-label': S('Search {0}', o.label), oninput: e => { st.q = e.target.value.trim().toLowerCase(); st.act = -1; ddList(); },
    onkeydown: ddKeys });
  st.list = h('div', { class: 'ddlist', role: 'listbox', 'aria-label': o.label });
  st.info = h('div', { class: 'ddinfo', 'aria-live': 'polite' });
  const pop = h('div', { id: 'ddpop', role: 'dialog', 'aria-label': o.label },
    h('div', { class: 'ddhead' }, h('span', { class: 'title' }, o.label), find, btn('✕', () => { ddClose(true); return null; }, 'sm flat', S('Close'))),
    h('div', { class: 'ddbody' }, st.list, st.info));
  st.find = find;
  document.body.append(pop);
  anchor.setAttribute('aria-expanded', 'true');
  ddList();
  ddPlace();
  const on = st.flat.findIndex(x => x.on);
  if (on >= 0) { st.act = on; ddMark(); } else ddInfo(null);
  if (lastPointer === 'mouse') find.focus({ preventScroll: true });   // (a phone's keyboard waits for a tap on the search)
}
function ddClose(back) {
  const st = BG.dd;
  if (!st) return;
  BG.dd = null;
  BG.ddOpen[st.key] = [...st.open];
  const p = $('ddpop');
  if (p) p.remove();
  const a = document.contains(st.anchor) ? st.anchor : document.querySelector(`[data-dd="${st.key}"]`);
  if (a) { a.setAttribute('aria-expanded', 'false'); if (back) a.focus({ preventScroll: true }); }
}
/** The rows shown for the search: a row matching it shows with all its kids; a row whose kids match opens on them. */
function ddList() {
  const st = BG.dd, o = st.o, q = st.q;
  const hit = r => !q || `${r.label} ${r.v} ${r.facts || ''}`.toLowerCase().includes(q);
  const cur = o.value || '';
  st.flat = [];
  const out = [];
  if (o.any != null && !q) out.push(ddItem({ v: '', label: '🎲 ' + o.any, facts: S('Picked for you when the hero is made') }, null, !cur));
  for (const r of o.rows) {
    const kids = r.kids || [], own = hit(r), kidHits = kids.filter(hit);
    if (!own && !kidHits.length) continue;
    const open = st.open.has(r.v) || (!!q && !!kidHits.length);
    out.push(ddItem(r, null, r.v === cur && !(o.sub && kids.some(k => k.v === o.sub)), kids.length ? open : null));
    if (open) for (const k of q && !own ? kidHits : kids) out.push(ddItem(k, r, r.v === cur && k.v === o.sub));
  }
  st.list.replaceChildren(...(out.length ? out : [h('div', { class: 'dim small ddnone' }, S('Nothing matches.'))]));
  if (st.act >= st.flat.length) st.act = st.flat.length - 1;
  ddMark(true);
}
function ddItem(r, parent, on, open) {
  const st = BG.dd, i = st.flat.length;
  const fold = open == null ? h('span', { class: 'ddfold none' })
    : h('button', { class: 'ddfold' + (open ? ' open' : ''), tabindex: -1, 'aria-label': open ? S('Fold') : S('Unfold'),
      onclick: e => { e.stopPropagation(); ddFold(r.v, !open); } }, '▸');
  const el = h('div', { class: 'ddopt' + (parent ? ' kid' : '') + (on ? ' on' : '') + (r.off ? ' off' : ''), role: 'option', 'aria-selected': String(!!on), id: 'ddo' + i },
    fold, r.icon ? gi(r.icon, 'sm') : null,
    h('span', { class: 'ddn' }, h('span', { class: 'ddt' }, r.label), r.facts ? h('span', { class: 'ddf' }, r.facts) : null),
    open != null ? h('span', { class: 'ddk' }, String((r.kids || []).length)) : null,
    on ? h('span', { class: 'ddok', 'aria-hidden': 'true' }, '✔') : null,
    r.about || r.text ? h('button', { class: 'ddi', tabindex: -1, 'aria-label': S('About {0}', r.label), onclick: e => { e.stopPropagation(); st.act = i; ddMark(); } }, 'ⓘ') : null);
  el.addEventListener('mousemove', () => { if (st.act !== i) { st.act = i; ddMark(true); } });
  el.addEventListener('click', () => ddChoose(i));
  st.flat.push({ r, parent, el, on, open });
  return el;
}
function ddFold(v, open) {
  const st = BG.dd;
  if (!st) return;
  if (open) st.open.add(v); else st.open.delete(v);
  ddList();
}
function ddChoose(i) {
  const st = BG.dd, x = st && st.flat[i];
  if (!x || x.r.off) return;
  const o = st.o;
  ddClose(true);
  if (x.parent) o.onpick(x.parent.v, x.r.v); else o.onpick(x.r.v, '');
}
/** The row under the pointer or the keyboard: lit, in view (keyboard), told in the side pane. */
function ddMark(quiet) {
  const st = BG.dd;
  st.flat.forEach((x, i) => x.el.classList.toggle('act', i === st.act));
  const x = st.flat[st.act];
  st.find.setAttribute('aria-activedescendant', x ? x.el.id : '');
  if (x && !quiet) x.el.scrollIntoView({ block: 'nearest' });
  ddInfo(x || null);
}
function ddInfo(x) {
  const st = BG.dd;
  if (!st) return;
  if (!x) {
    st.infoFor = null;
    st.info.replaceChildren(h('div', { class: 'dim small' }, S('Point at a choice to read about it.')));
    return;
  }
  const r = x.r, key = r.about ? r.about.join(':') + ':' + wordsLang : null;
  if (st.infoFor === (key || r.label)) return;
  st.infoFor = key || r.label;
  const text = h('div', { class: 'ddtx' }, r.text || '');
  st.info.replaceChildren(...[h('b', null, x.parent ? `${x.parent.label} · ${r.label}` : r.label), r.facts ? h('div', { class: 'ddf' }, r.facts) : null,
    r.kids && r.kids.length ? h('div', { class: 'dim small' }, S('{0} to pick from: ▸ unfolds them.', r.kids.length)) : null,
    r.off && r.offWhy ? h('div', { class: 'warn small' }, r.offWhy) : null, text].filter(Boolean));
  if (!key) return;
  if (BG.about[key]) { text.textContent = BG.about[key].text; return; }
  text.classList.add('dim'); text.textContent = S('Loading…');
  clearTimeout(st.timer);
  st.timer = setTimeout(() => bgAbout(r.about[0], r.about[1]).then(d => {
    if (BG.dd === st && st.infoFor === key) { text.classList.remove('dim'); text.textContent = d.text || ''; }
  }).catch(() => { if (BG.dd === st && st.infoFor === key) text.textContent = ''; }), 140);
}
function ddKeys(e) {
  const st = BG.dd;
  if (!st) return;
  const n = st.flat.length, x = st.flat[st.act];
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (n) { st.act = e.key === 'ArrowDown' ? (st.act + 1) % n : (st.act <= 0 ? n : st.act) - 1; ddMark(); } }
  else if (e.key === 'Enter') { e.preventDefault(); ddChoose(st.act >= 0 ? st.act : st.flat.findIndex(y => !y.r.off)); }
  else if (e.key === 'ArrowRight' && x && x.open === false && !st.q) { e.preventDefault(); ddFold(x.r.v, true); }
  else if (e.key === 'ArrowLeft' && x && !st.q && (x.open || x.parent)) {
    e.preventDefault();
    const v = x.parent ? x.parent.v : x.r.v;
    ddFold(v, false);
    st.act = st.flat.findIndex(y => !y.parent && y.r.v === v); ddMark();
  }
  else if (e.key === 'Tab') ddClose();
}
/** The list under its field (above it when the room is there), or a bottom sheet on a phone; its field found again
 *  after a redraw (closed when it is gone). */
function ddPlace() {
  const st = BG.dd, pop = $('ddpop');
  if (!st || !pop) return;
  if (!document.contains(st.anchor)) {
    const now = document.querySelector(`[data-dd="${st.key}"]`);
    if (!now) { ddClose(); return; }
    st.anchor = now;
    now.setAttribute('aria-expanded', 'true');
  }
  const r = st.anchor.getBoundingClientRect(), W = innerWidth, H = innerHeight;
  if (W < 600) { pop.classList.add('sheet'); pop.style.cssText = ''; return; }
  pop.classList.remove('sheet');
  const w = Math.min(640, W - 16), left = Math.max(8, Math.min(r.left, W - w - 8));
  const below = H - r.bottom - 12, above = r.top - 12, up = below < 300 && above > below;
  pop.style.cssText = `left:${left}px;width:${w}px;max-height:${Math.max(200, Math.min(480, up ? above : below))}px;` + (up ? `bottom:${H - r.top + 4}px` : `top:${r.bottom + 4}px`);
}
/** A hero-form choice's rules text (bg_about), asked once. */
function bgAbout(kind, name) {
  const key = kind + ':' + name + ':' + wordsLang;
  if (BG.about[key]) return Promise.resolve(BG.about[key]);
  const l = bgLobby();
  return api('/api/act', { action: 'bg_about', room: l ? l.id : undefined, kind, name }).then(r => (BG.about[key] = r.data || { text: '' }));
}
/** The pick-list rows of the classes (with their subclasses as kids when `subs`) and of the races (with subraces). */
const classRows = (o, subs) => o.heroes.classes.map(c => ({ v: c.name, label: lbl(o, c.name), icon: CLASS_ICON[c.name], facts: (o.facts || {})['class:' + c.name],
  about: ['class', c.name], kids: subs ? c.subclasses.map(s => ({ v: s, label: lbl(o, s), facts: (o.facts || {})[`subclass:${c.name}::${s}`], about: ['subclass', `${c.name}::${s}`] })) : [] }));
const raceRows = o => o.heroes.races.map(r => ({ v: r.name, label: lbl(o, r.name), facts: (o.facts || {})['race:' + r.name], about: ['race', r.name],
  kids: (r.subraces || []).map(s => ({ v: s, label: lbl(o, s), facts: (o.facts || {})[`race:${r.name}::${s}`], about: ['race', `${r.name}::${s}`] })) }));

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

// ---------------------------------------------------------------- duel and skirmish: what I fight as
function fighterPane(g, l) {
  const me = g.me, st = l.settings, o = bgOptions(l), parts = [];
  if (!me && l.phase !== 'lobby') return parts;
  const kinds = (st.kinds || []).filter(k => ['hero', 'pool', 'monster'].includes(k));
  if (!kinds.includes(BG.tab)) BG.tab = kinds[0] || 'hero';
  const words = { hero: ['🛡', S('A new hero'), S('Pick a class and race; the rest is rolled')], pool: ['🎲', S("The DM's heroes") + (l.pool.length ? ` (${l.pool.length})` : ''), S('Ready-made, one each')],
    monster: ['🐉', S('A monster'), S('Any creature of the books')] };
  const tabs = kinds.length > 1 ? h('div', { class: 'seg ktabs', role: 'tablist' }, ...kinds.map(k => h('button', { class: BG.tab === k ? 'on' : '', role: 'tab',
    'aria-selected': String(BG.tab === k), tip: words[k][2], onclick: () => { BG.tab = k; store('bgtab', k); bgRedo(); } }, words[k][0] + ' ' + words[k][1]))) : null;
  const body = BG.tab === 'hero' ? heroForm(g, l, o) : BG.tab === 'pool' ? poolCards(g, l) : monsterSearch(g, l, o);
  const has = me && (me.char || me.kind);
  if (!has) return [h('div', { class: 'drow' }, h('span', { class: 'title' }, S('Fight as')), h('span', { class: 'grow' }), tabs), ...body];
  // a fighter picked: it is on show, the pickers fold away until wanted
  parts.push(h('div', { class: 'card hero mine' },
    h('div', { class: 'drow' }, h('span', { class: 'title' }, S('Your fighter')), h('b', { class: 'nm' }, me.char || me.summary), h('span', { class: 'grow' }),
      me.char && me.kind === 'hero' ? btn('✨', () => bgSpellPicker(l), 'sm', S('Spells…') + '\n' + S('Take a ready-made spell list, or pick your hero\'s spells one by one')) : null,
      me.char ? btn('📜', () => { showView('sheet'); return null; }, 'sm', S('See my hero')) : null),
    me.char && me.summary ? h('div', { class: 'dim small' }, me.summary) : null),
  h('details', { class: 'more', open: BG.redo || null, ontoggle: e => { BG.redo = e.target.open; } },
    h('summary', null, S('Fight as something else'), h('span', { class: 'sup' }, ' ' + kinds.map(k => words[k][1]).join(' · '))), tabs, ...body));
  return parts;
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
/** A new hero: class (subclasses fold under it), race (subraces under it) and level on show; background, spell list,
 *  abilities, hit points, magic items, gender and name under "More options" (its line says what is set there). */
function heroForm(g, l, o) {
  const me = g.me, st = l.settings;
  if (!o) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const p = heroDraft(o), H = o.heroes;
  const keep = (k, v) => saveDraft({ ...BG.draft, [k]: v });      // (a choice that changes nothing else of the form: no redraw)
  const level = st.free_level ? (p.level || st.level) : st.level;
  const styles = spellStyles();
  const abil = { auto: S('Standard array'), point_buy: S('Point buy'), roll: S('Rolled') };
  const hpW = { average: S('Average'), max: S('Maximum'), roll: S('Rolled') }, magW = { none: S('None'), some: S('A few'), tier: S('Fitting the level') };
  const set = [p.background ? lbl(o, p.background) : '', p.spell_style ? (styles.find(s => s[0] === p.spell_style) || [])[1] : '',
    p.abilities !== 'auto' ? abil[p.abilities] : '', p.hp !== 'average' ? S('{0} hit points', hpW[p.hp]) : '', p.magic !== 'none' ? S('Magic items: {0}', magW[p.magic]) : '',
    p.gender ? S(p.gender === 'male' ? 'Male' : 'Female') : '', p.name || ''].filter(Boolean);
  const out = [
    h('div', { class: 'ddrow' },
      ddPick({ key: 'hclass', label: S('Class'), value: p.class, sub: p.subclass, any: S('Random'), rows: classRows(o, true),
        onpick: (v, s) => { saveDraft({ ...BG.draft, class: v, subclass: s || '' }); bgRedo(); } }),
      ddPick({ key: 'hrace', label: S('Race'), value: p.race, sub: p.subrace, any: S('Random'), rows: raceRows(o),
        onpick: (v, s) => { saveDraft({ ...BG.draft, race: v, subrace: s || '' }); bgRedo(); } }),
      st.free_level ? h('span', { class: 'ddbtn lvlf', tip: S('Your level (up to {0})', st.max_level) }, h('span', { class: 'ddl' }, S('Level')),
        stepper(level, 1, st.max_level, v => keep('level', v), S('Level')))
        : h('span', { class: 'ddbtn lvlf', tip: S('Set by the lobby') }, h('span', { class: 'ddl' }, S('Level')), h('b', { class: 'ddv' }, String(level)))),
    h('details', { class: 'more', open: BG.more || null, ontoggle: e => { BG.more = e.target.open; } },
      h('summary', null, S('More options'), h('span', { class: 'sup' }, ' ' + (set.length ? set.join(' · ') : S('background, spells, abilities, hit points, magic items, name')))),
      h('div', { class: 'ddrow' },
        ddPick({ key: 'hbg', label: S('Background'), value: p.background, any: S('Random'),
          rows: H.backgrounds.map(b => ({ v: b, label: lbl(o, b), facts: (o.facts || {})['background:' + b], about: ['background', b] })), onpick: v => { keep('background', v); bgRedo(); } }),
        ddPick({ key: 'hspells', label: S('Spells'), value: p.spell_style || '', rows: styles.map(([v, w, t]) => ({ v, label: w, facts: t })),
          onpick: v => { keep('spell_style', v); bgRedo(); } }),
        h('label', { class: 'ddbtn namef' }, h('span', { class: 'ddl' }, S('Name')),
          h('input', { value: p.name || '', maxlength: 40, placeholder: S('Random'), oninput: e => keep('name', e.target.value) }))),
      sect(S('Abilities'), segOf(p.abilities, [['auto', S('Standard array'), S('Standard array, by class')], ['point_buy', S('Point buy')], ['roll', S('Rolled'), S('Rolled (4d6, drop the lowest)')]],
        v => { keep('abilities', v); bgRedo(); })),
      p.abilities === 'point_buy' ? pointBuy(p.scores, o.point_buy || 27, H.point_buy.costs || POINT_COSTS, () => saveDraft(BG.draft), o.abilities) : null,
      h('div', { class: 'bgrow' },
        sect(S('Hit points'), segOf(p.hp, [['average', hpW.average], ['max', hpW.max], ['roll', hpW.roll]], v => { keep('hp', v); bgRedo(); })),
        sect(S('Magic items'), segOf(p.magic, [['none', magW.none], ['some', magW.some], ['tier', magW.tier]], v => { keep('magic', v); bgRedo(); })),
        sect(S('Gender'), segOf(p.gender || '', [['', '🎲', S('Random')], ['male', S('Male')], ['female', S('Female')]], v => { keep('gender', v); bgRedo(); })))),
  ];
  const pick = () => { const d = BG.draft; return { kind: 'hero', opts: { class: d.class, subclass: d.subclass, race: d.race, subrace: d.subrace, background: d.background,
    level: st.free_level ? (d.level || st.level) : st.level, abilities: d.abilities, scores: d.abilities === 'point_buy' ? d.scores : undefined, hp: d.hp, magic: d.magic,
    name: d.name || '', gender: d.gender || '', spell_style: d.spell_style || '' } }; };
  out.push(h('div', { class: 'drow go' }, h('span', { class: 'dim small' }, S('The rest is rolled for you.')), h('span', { class: 'grow' }),
    btn(me ? '🛡 ' + S('Make this my hero') : '⚔ ' + S('Join with this hero'), () => bgAct('bg_pick', { pick: pick() }, false), 'primary',
      S('The hero is made now; you can change its spells afterwards'))));
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
  // the name finds most monsters; the filters fold away (open while one is set)
  const set = ['cr_min', 'cr_max', 'types', 'sizes', 'envs', 'books'].filter(k => q[k]).length;
  const form = h('div', { class: 'monsfind' },
    h('input', { type: 'search', value: q.q || '', placeholder: S('Find a monster'), 'aria-label': S('Find a monster'), oninput: e => setQ('q', e.target.value) }),
    h('details', { class: 'more', open: BG.mfilters || !!set || null, ontoggle: e => { BG.mfilters = e.target.open; } },
      h('summary', null, S('Filters'), h('span', { class: 'sup' }, set ? ' ' + S('{0} set', set) : ' ' + S('challenge, type, size, environment, book')),
        set ? btn(S('Clear'), () => { for (const k of Object.keys(q)) if (k !== 'q') delete q[k]; store('bgmq', q); bgRedo(); return null; }, 'sm flat') : null),
      h('div', { class: 'bgform mons' },
        field(S('CR from'), selectOf(q.cr_min || '', crs, v => setQ('cr_min', v), S('any'))),
        field(S('CR to'), selectOf(q.cr_max || '', crs, v => setQ('cr_max', v), S('any'))),
        field(S('Type'), selectOf(q.types || '', (F.types || []).map(x => [x, lbl(o, x)]), v => setQ('types', v), S('any'))),
        field(S('Size'), selectOf(q.sizes || '', (F.sizes || []).map(x => [x, lbl(o, x)]), v => setQ('sizes', v), S('any'))),
        field(S('Environment'), selectOf(q.envs || '', (F.envs || []).map(x => [x, lbl(o, x)]), v => setQ('envs', v), S('any'))),
        field(S('Book'), selectOf(q.books || '', (F.books || []).map(([id, name]) => [id, name]), v => setQ('books', v), S('any'))))));
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
    const list = $('bgbody').querySelector('.mlist'), count = $('bgbody').querySelector('.mcount');   // (the list alone: the search box keeps its focus)
    if (list && ST.bg && ST.bg.lobby && ST.bg.lobby.id === l.id) { list.replaceChildren(...monsterRows(l, ST.bg.me)); if (count) count.textContent = monsterCount(); }
    else bgRedo();
  } catch (e) { if (e.message !== 'login') say(e.message, true); }
  finally { BG.asking.delete('mons'); if (BG.monsAgain && BG.monsAgain !== key) { BG.monsAgain = null; monsterFind(l); } }
}

// ---------------------------------------------------------------- the shop: the round's gold, a cart (battlegrounds/shop.py)
/** Copper pieces in words: 1500 -> '15 gp', 30 -> '3 sp', 5 -> '5 cp'. */
function gp(cp) {
  cp = Math.max(0, Math.round(+cp || 0));
  if (cp >= 100) return S('{0} gp', (cp / 100).toLocaleString(undefined, { maximumFractionDigits: 2 }));
  return cp >= 10 && cp % 10 === 0 ? S('{0} sp', cp / 10) : S('{0} cp', cp);
}
/** What the lobby's shop sells (asked once per lobby and language; the page filters it as you type). */
function bgShop(l) {
  const key = l.id + ':' + wordsLang;
  if (BG.shopKey === key) return BG.shop;
  if (!BG.asking.has('shop:' + key)) {
    BG.asking.add('shop:' + key);
    api('/api/act', { action: 'bg_shop', room: l.id }).then(r => {
      BG.shop = r.data; BG.shopKey = key; BG.shopBy = Object.fromEntries(r.data.rows.map(x => [x.name, x])); bgRedo();
    }).catch(e => { if (e.message !== 'login') say(e.message, true); }).finally(() => BG.asking.delete('shop:' + key));
  }
  return null;
}
/** The Shop tab: the cart on top (always: what is in it, gold spent and left), then the items for sale under a filter. */
function shopPane(g, l) {
  const me = g.me, c = me.cart, counts = new Map();
  bgShop(l);
  for (const x of c.items) { const k = counts.get(x.name); if (k) k.n++; else counts.set(x.name, { ...x, n: 1 }); }
  const cart = h('div', { class: 'card cart' },
    h('div', { class: 'drow' }, h('span', { class: 'title' }, '🛒 ' + S('Cart')), h('span', { class: 'grow' }),
      h('span', { class: 'small', tip: S('Your gold for each round: {0}', gp(c.gold * 100)) }, S('Spent {0}', gp(c.spent)) + ' · ', h('b', null, S('{0} left', gp(c.left)))),
      c.items.length ? btn(S('Empty'), () => bgAct('bg_cart_remove', { all: 1 }), 'sm flat', S('Take everything out of your cart')) : null),
    c.items.length ? h('div', { class: 'srows' }, ...[...counts.values()].map(x => shopRow(x, -1, me, ((BG.shopBy || {})[x.name] || {}).kind)))
      : h('div', { class: 'dim small' }, S('Nothing in your cart yet.')),
    h('div', { class: 'dim small' }, S('What you buy is yours for the coming battle: worn, wielded and attuned when it begins.')));
  const o = BG.shopKey === l.id + ':' + wordsLang ? BG.shop : null;
  const narrow = fn => v => { fn(v); BG.sshut.clear(); shopList(l); };     // (a new filter: every category with a match opens again)
  const find = h('div', { class: 'schips' }, h('div', { class: 'drow sfind' },
    h('input', { type: 'search', value: BG.sq, placeholder: S('Find an item'), 'aria-label': S('Find an item'),
      oninput: e => narrow(v => { BG.sq = v; })(e.target.value) }),
    toggleChip(S('Only what I can afford'), BG.cheap, on => { BG.cheap = on; store('bgcheap', on); shopList(l); })),
    o && o.rarities && o.rarities.length > 1 ? chipsOf(BG.sr, o.rarities, narrow(v => { BG.sr = v; }), S('Any rarity')) : null,
    o && o.groups && o.groups.length > 1 ? chipsOf(BG.sg, o.groups.map(x => [x.key, x.label]), narrow(v => { BG.sg = v; }), S('Every kind')) : null);
  return [cart, find, h('div', { class: 'slist' }, ...shopRows(l, me))];
}
/** Words typed or a chip picked: then every category with a match is open (unless folded meanwhile). */
const shopNarrowed = () => !!(BG.sq.trim() || BG.sr || BG.sg);
/** The items for sale, a fold per category (its count in the title), narrowed by the find box, the chips and "Only what
 *  I can afford". Unfiltered, the categories open only when clicked (remembered on this device). */
function shopRows(l, me) {
  const o = BG.shopKey === l.id + ':' + wordsLang ? BG.shop : null;
  if (!o || !me || !me.cart) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const words = BG.sq.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const hit = o.rows.filter(r => (!BG.cheap || r.cp <= me.cart.left) && (!BG.sr || r.rarity === BG.sr) && (!BG.sg || r.group === BG.sg)
    && words.every(w => (r.label + ' ' + r.name + ' ' + r.kind).toLowerCase().includes(w)));
  if (!hit.length) return [h('div', { class: 'empty dim small' }, S('No item matches.'))];
  const by = new Map(), narrowed = shopNarrowed(), rl = Object.fromEntries(o.rarities || []);
  for (const r of hit) { if (!by.has(r.group)) by.set(r.group, []); by.get(r.group).push(r); }
  return (o.groups || []).filter(x => by.has(x.key)).map(x => {
    const rows = by.get(x.key), open = narrowed ? !BG.sshut.has(x.key) : BG.sopen.has(x.key);
    const flip = () => { const s = narrowed ? BG.sshut : BG.sopen; if (s.has(x.key)) s.delete(x.key); else s.add(x.key);
      if (!narrowed) store('bgsopen', [...BG.sopen]); shopList(l); };
    const head = h('span', { class: 'fold', role: 'button', tabindex: 0, 'aria-expanded': String(open), onclick: flip,
      onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } } },
      h('span', { class: 'arw' }, open ? '▾' : '▸'), x.label, h('span', { class: 'cnt' }, `(${rows.length})`));
    return h('div', { class: 'card sgroup' + (open ? '' : ' shut') }, h('div', { class: 'title' }, head),
      open ? h('div', { class: 'srows' }, ...rows.map(r => shopRow(r, 1, me, r.rarity !== 'none' ? rl[r.rarity] || r.rarity : ''))) : null);
  });
}
/** The list alone, redrawn as you type (the search box keeps its focus). */
function shopList(l) { const el = $('bgbody').querySelector('.slist'); if (el) el.replaceChildren(...shopRows(l, ST.bg && ST.bg.me)); }
/** An item: picture, name, `sub` (its kind in the cart, its rarity in a category), price, and + (for sale: one into the
 *  cart) or − (in the cart: one out). Detail on hover. */
function shopRow(r, sign, me, sub) {
  const info = (BG.shopBy && BG.shopBy[r.name]) || r, dear = sign > 0 && r.cp > me.cart.left;
  const add = mini(sign < 0 ? '−' : '+', () => sign < 0 ? bgAct('bg_cart_remove', { item: r.name }) : bgAct('bg_cart_add', { item: r.name }), '',
    sign < 0 ? S('Take one out of your cart') : dear ? S('Costs more than you have left') : S('Add one to your cart'));
  add.disabled = dear;
  return h('div', { class: 'srow' + (dear ? ' dear' : ''), tip: info.tip || r.label },
    h('span', { class: 'si' }, iconOr(info.icon, 20, '')), h('b', null, (info.label || r.label) + (r.n > 1 ? ' ×' + r.n : '')),
    h('span', { class: 'dim small' }, sub || ''), h('span', { class: 'small sp' }, gp(r.cp * (r.n || 1))), add);
}

// ---------------------------------------------------------------- the arena: build a hero, then level it up
function arenaPane(g, l) {
  const me = g.me, o = bgOptions(l), parts = [];
  if (!me) {
    if (l.phase === 'lobby') parts.push(h('div', { class: 'card' }, S('An arena run: build a level 1 hero, win battles, gain levels. Join to build yours.')));
    return parts;
  }
  if (!me.char) {
    parts.push(h('div', { class: 'drow' }, h('span', { class: 'title' }, S('Build your hero')), h('span', { class: 'grow' }),
      l.pool.length ? h('span', { class: 'dim small' }, S("Or take one of the DM's heroes below.")) : null));
    parts.push(...arenaBuilder(g, l, o));
    if (l.pool.length) parts.push(h('details', { class: 'more' }, h('summary', null, S("The DM's pool"), h('span', { class: 'sup' }, ` (${l.pool.length})`)), ...poolCards(g, l)));
    return parts;
  }
  parts.push(h('div', { class: 'card hero mine' },
    h('div', { class: 'drow' }, h('b', { class: 'nm' }, me.char), h('span', { class: 'lvl' }, S('Level {0}', me.level || 1)), h('span', { class: 'grow' }),
      me.hp != null ? h('span', { class: 'small' }, `${S('HP')} ${me.hp}/${me.max_hp}`) : null,
      btn('✨', () => bgSpellPicker(l), 'sm', S('Change spells') + '\n' + S('Between battles you may change your spells at will')),
      btn('📜', () => { showView('sheet'); return null; }, 'sm', S('See my hero')),
      l.stash != null ? btn('🎒 ' + l.stash, () => { UI.tab = 'inventory'; store('tab', 'inventory'); showView('sheet'); renderSheet(); return null; }, 'sm',
        S('Team stash ({0})', l.stash) + '\n' + S('The arena\'s team inventory: trophies and what you share')) : null),
    h('div', { class: 'dim small' }, me.summary),
    me.pending ? h('div', { class: 'drow' }, h('span', { class: 'good small' }, S('You have {0} level-up to take.', me.pending)), h('span', { class: 'grow' }),
      btn('⬆ ' + S('Level up!') + (me.pending > 1 ? ` (${me.pending})` : ''), () => bgLevelUp(l), 'primary', S('Spend an earned level: class, hit points, features, spells'))) : null));
  if (l.history.length) parts.push(h('div', { class: 'dim small' }, S('Battles: {0}', l.history.map(x => `${x.n} ${x.won ? '✔' : '✘'}`).join(' · '))));
  return parts;
}
/** A level 1 arena hero: class and race (subraces under it) and a name on show; the point buy folds away under a line
 *  of its scores and the points left. */
function arenaBuilder(g, l, o) {
  if (!o) return [h('div', { class: 'dim small' }, S('Loading…'))];
  const H = o.heroes;
  let b = BG.build;
  if (!b || !b.scores) b = { race: '', subrace: '', class: '', scores: freshScores(), name: '' };
  if (b.race && !H.races.find(r => r.name === b.race)) b.race = '';
  if (b.class && !H.classes.find(c => c.name === b.class)) b.class = '';
  BG.build = b;
  const save = () => store('bgbuild', b);
  const budget = o.point_buy || 27, costs = H.point_buy.costs || POINT_COSTS, short = Object.fromEntries((o.abilities || ABILS.map(a => [a, a])).map(([a]) => [a, a.toUpperCase()]));
  const line = h('span', { class: 'sup' });
  const sumUp = () => {
    const left = budget - ABILS.reduce((n, a) => n + (costs[b.scores[a]] != null ? costs[b.scores[a]] : POINT_COSTS[b.scores[a]] || 0), 0);
    line.textContent = ' ' + ABILS.map(a => `${short[a]} ${b.scores[a]}`).join(' · ') + ' · ' + S('{0} points left', left);
  };
  sumUp();
  const ok = b.race && b.class;
  return [h('div', { class: 'ddrow' },
    ddPick({ key: 'aclass', label: S('Class'), value: b.class, rows: classRows(o, false), onpick: v => { b.class = v; save(); bgRedo(); } }),
    ddPick({ key: 'arace', label: S('Race'), value: b.race, sub: b.subrace, rows: raceRows(o), onpick: (v, s) => { b.race = v; b.subrace = s || ''; save(); bgRedo(); } }),
    h('label', { class: 'ddbtn namef' }, h('span', { class: 'ddl' }, S('Name')),
      h('input', { value: b.name || '', maxlength: 40, placeholder: S('Random'), oninput: e => { b.name = e.target.value; save(); } }))),
  h('details', { class: 'more', open: BG.pbOpen || null, ontoggle: e => { BG.pbOpen = e.target.open; } }, h('summary', null, S('Point buy'), line),
    pointBuy(b.scores, budget, costs, () => { save(); sumUp(); }, o.abilities)),
  h('div', { class: 'drow go' }, h('span', { class: 'dim small' }, ok ? S('Level 1, point buy: the rest is picked for you.') : S('Pick a class and a race.')), h('span', { class: 'grow' }),
    Object.assign(btn('🏟 ' + S('Enter the arena'), () => bgAct('bg_build', { race: b.race, subrace: b.subrace, class: b.class, scores: b.scores, name: b.name || '' }, false), 'primary',
      S('A level 1 hero: your race, class and scores; background, spells and gear are picked for you')), { disabled: !ok }))];
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
function spellBlock(title, rows, count, sel, levels, changed) {
  if (!count || !rows.length) return null;
  const total = h('span', { class: 'pct' });
  const boxes = [];
  const recount = () => { total.textContent = S('{0} of {1}', sel.size, count); total.className = 'pct ' + (sel.size === count ? 'good' : sel.size > count ? 'bad' : ''); boxes.forEach(([b, n]) => { b.checked = sel.has(n); });
    if (changed) changed(); };
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
  return Object.assign(h('div', { class: 'pcls' }, h('div', { class: 'ph' }, h('b', null, title), h('span', { class: 'grow' }), total, btn(S('Clear'), () => { sel.clear(); recount(); return null; }, 'sm flat')), ...groups),
    { recount });
}
/** A class's ready-made spell lists as cards: the name, what it is for, its telling spells. A click takes the whole
 *  list (the picks below follow, and stay free to change); the card whose list is the one picked now is lit. */
function presetCards(c, tricks, spells, redraw) {
  if (!(c.presets || []).length) return null;
  const level = Object.fromEntries(c.options.map(s => [s.name, s.level]));
  const same = p => { const now = new Set([...tricks, ...spells]); return p.picks.length === now.size && p.picks.every(n => now.has(n)); };
  const cards = c.presets.map(p => h('button', { class: 'preset', tip: p.picks.map(n => (c.options.find(s => s.name === n) || {}).label || n).join(', '),
    onclick: () => { tricks.clear(); spells.clear(); for (const n of p.picks) (level[n] === 0 ? tricks : spells).add(n); redraw(); } },
    h('b', null, p.name), h('span', { class: 'dim small' }, p.blurb),
    h('span', { class: 'signs' }, ...p.signs.map(s => h('span', { class: 'sign', tip: s.label }, gi(s.icon, 'spi'), h('span', { class: 'small' }, s.label))))));
  const note = h('span', { class: 'sup' });
  const mark = () => { let hit = null; c.presets.forEach((p, i) => { const on = same(p); cards[i].classList.toggle('on', on); cards[i].setAttribute('aria-pressed', String(on)); if (on) hit = p; });
    note.textContent = ' ' + (hit ? hit.name : S('your own list')); };
  mark();
  return Object.assign(h('div', { class: 'presetbox' }, h('div', { class: 'title' }, S('Ready-made lists'), note), h('div', { class: 'presets' }, ...cards)), { mark });
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
    let cards = null;
    const mark = () => { if (cards) cards.mark(); };
    const a = spellBlock(S('Cantrips'), c.options.filter(s => s.level === 0), c.cantrips, tricks, [0], mark);
    const b = spellBlock(c.prepares ? S('Prepared spells') : S('Known spells'), c.options.filter(s => s.level > 0), c.spells, spells, levels, mark);
    cards = presetCards(c, tricks, spells, () => { if (a) a.recount(); if (b) b.recount(); });
    return h('div', { class: 'spcls' }, h('div', { class: 'title' }, c.label, ' ', h('span', { class: 'sup' },
      c.spells ? S('{0} cantrips and {1} spells up to level {2}', c.cantrips, c.spells, c.max_level) : S('{0} cantrips', c.cantrips))),
      c.always.length ? h('div', { class: 'dim small' }, S('Always prepared: {0}', c.always.join(', '))) : null, cards, a, b);
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
  const pickRow = h('div', { class: 'ddrow' }, ddPick({ key: 'luclass', label: S('Class'), value: plan.class,
    rows: classes.map(c => ({ v: c.class, label: L(c.class), icon: CLASS_ICON[c.class], facts: c.note || '', about: ['class', c.class], off: c.ok === false, offWhy: c.note })),
    onpick: v => { if (v !== plan.class) again(v, ''); } }));
  parts.push(pickRow);
  const hpSeg = h('span', { class: 'seg' }, ...[['average', S('Average') + ` (+${(plan.hp || {}).average || '?'})`], ['roll', S('Roll a d{0}', plan.hit_die)]].map(([k, w]) =>
    h('button', { class: ch.hp === k ? 'on' : '', onclick: e => { ch.hp = k; [...hpSeg.children].forEach(x => x.classList.toggle('on', x === e.currentTarget)); } }, w)));
  if (!plan.first_ever) parts.push(field(S('Hit points'), hpSeg));
  if (plan.subclass) {
    const opts = plan.subclass.options, cur = ch.subclass && opts.includes(ch.subclass) ? ch.subclass : opts[0];
    ch.subclass = cur;
    pickRow.append(ddPick({ key: 'lusub', label: plan.subclass.title || S('Subclass'), value: cur,
      rows: opts.map(s => ({ v: s, label: L(s), facts: (((plan.blurbs || {})[s] || [])[0] || {}).label || '', about: ['subclass', `${plan.class}::${s}`] })),
      onpick: v => { if (v !== cur) again(plan.class, v); } }));
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

// ---------------------------------------------------------------- a duel of your own: open it, set it up, run it
/** The duel form: a name and the room's rules - the hero level (or each picks theirs), teams or free-for-all, what
 *  the fighters may be, the map, whether others may watch. `l`: my duel, to change; null: a new one. */
function duelForm(l) {
  const g = bgState(), st = l ? l.settings : { level: 3, free_level: true, max_level: 20, ffa: true, kinds: ['hero', 'monster'], map: 'arena', spectators: true };
  const v = { name: l ? l.name : '', level: st.level || 3, free_level: !!st.free_level, max_level: st.max_level || 20, ffa: !!st.ffa,
    kinds: new Set((st.kinds || []).filter(k => k === 'hero' || k === 'monster')), map: st.map || 'arena', spectators: st.spectators !== false,
    gold: Math.max(0, +st.gold || 0) };
  const kind = (k, label) => toggleChip(label, v.kinds.has(k), on => { if (on) v.kinds.add(k); else v.kinds.delete(k); });
  const maps = ((g && g.maps) || []).map(m => [m.key, m.name, m.blurb]);
  if (!maps.some(([k]) => k === v.map)) maps.push([v.map, v.map]);
  // the level: one for all (a stepper), or each their own up to a highest (the same stepper, read as the cap)
  const lvl = h('span');
  const drawLvl = () => lvl.replaceChildren(v.free_level ? stepper(v.max_level, 1, 20, x => { v.max_level = x; }, S('Highest level')) : stepper(v.level, 1, 20, x => { v.level = x; }, S('Hero level')),
    h('span', { class: 'dim small' }, ' ' + (v.free_level ? S('the highest level anyone may pick') : S('everyone fights at this level'))));
  drawLvl();
  detail(() => h('div', { class: 'iform duelform bgstack' },
    h('b', null, l ? '⚙ ' + S('Duel settings') : '🤺 ' + S('Open a duel')),
    h('div', { class: 'dim small' }, S('Players against each other. You run it: you start the fight once everyone is ready.')),
    field(S('Name'), h('input', { type: 'text', maxlength: 40, value: v.name, placeholder: S('a name the others see'), oninput: e => { v.name = e.target.value; } })),
    sect(S('Sides'), segOf(v.ffa ? 'ffa' : 'teams', [['ffa', S('Free-for-all'), S('Free-for-all: everyone on a team of their own')], ['teams', S('Teams'), S('Everyone picks a team')]], x => { v.ffa = x === 'ffa'; })),
    sect(S('Level'), h('div', { class: 'drow' }, segOf(v.free_level ? 'own' : 'same', [['own', S('Each their own'), S('Everyone picks their own level (up to the highest)')], ['same', S('Same for all')]],
      x => { v.free_level = x === 'own'; drawLvl(); }), lvl)),
    sect(S('Fight as'), h('div', { class: 'chips pick' }, kind('hero', '🛡 ' + S('A hero')), kind('monster', '🐉 ' + S('A monster')))),
    sect(S('Map'), chipsOf(v.map, maps, x => { v.map = x; })),
    sect(S('Shop'), h('div', { class: 'drow' }, h('input', { type: 'number', min: 0, max: 1000000, step: 10, value: v.gold, class: 'goldin', 'aria-label': S('Gold'),
      oninput: e => { v.gold = Math.max(0, Math.min(1000000, parseInt(e.target.value, 10) || 0)); } }),
      h('span', { class: 'dim small' }, S('gp for each fighter to shop with, every round (0: no shop)')))),
    sect(S('Audience'), h('div', { class: 'chips pick' }, toggleChip('👁 ' + S('Others may watch'), v.spectators, x => { v.spectators = x; })))),
  () => [[l ? S('Save') : S('Open the duel'), () => {
    const settings = { level: v.free_level ? Math.min(v.level, v.max_level) : v.level, free_level: v.free_level, max_level: v.free_level ? v.max_level : Math.max(v.level, v.max_level), ffa: v.ffa, kinds: [...v.kinds], map: v.map,
      spectators: v.spectators, gold: v.gold };
    const name = v.name.trim();
    if (!l) return act('bg_create', { mode: 'duel', name, settings });
    return act('bg_settings', { room: l.id, settings }, true).then(() => name && name !== l.name ? act('bg_rename', { room: l.id, name }, true) : null);
  }], [S('Cancel'), () => null, 'flat']]);
  return null;
}
const endDuel = l => ask(S('End the fight now? Whoever is left standing wins (several teams: nobody).'), S('End it'), () => bgAct('bg_end', {}, true), 'danger');
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
