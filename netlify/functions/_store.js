// ============================================================
// Shared helpers for all API functions (Netlify Blobs storage)
// ============================================================
import { getStore } from '@netlify/blobs';
import { readFileSync } from 'node:fs';

const dataDir = new URL('../../data/', import.meta.url);

function loadJSON(name, fallback) {
  try {
    return JSON.parse(readFileSync(new URL(name, dataDir), 'utf8'));
  } catch (e) {
    return fallback;
  }
}

export const TEAMS = loadJSON('teams.json', []);
let PLAYERS = loadJSON('players.json', []);

export function getPlayers() {
  return PLAYERS;
}

export function playerByName(name) {
  return PLAYERS.find(p => p.n === name) || null;
}

// ---------- admin overrides (persisted in blobs) ----------
const OVERRIDES_KEY = 'rating_overrides.json';
const CUSTOM_KEY = 'custom_players.json';

async function getJSON(key) {
  const store = getStore({ name: 'auction', consistency: 'strong' });
  try { return (await store.get(key, { type: 'json' })) || null; } catch { return null; }
}

async function setJSON(key, obj) {
  const store = getStore({ name: 'auction', consistency: 'strong' });
  await store.setJSON(key, obj);
}

export async function getOverrides() {
  const store = getStore({ name: 'auction', consistency: 'strong' });
  try {
    return (await store.get(OVERRIDES_KEY, { type: 'json' })) || {};
  } catch {
    return {};
  }
}

// Apply persisted overrides + merge admin-added players on cold start
let overridesApplied = false;
export async function ensureOverrides() {
  if (overridesApplied) return;
  const ov = await getOverrides();
  for (const p of PLAYERS) {
    const o = ov[p.n];
    if (o) {
      if (o.o != null) p.o = o.o;
      if (o.b != null) p.b = o.b;
      if (o.r != null) p.r = o.r;
      if (o.c != null) p.c = o.c;
    }
  }
  // merge admin-added players (they are not in the bundled players.json)
  const custom = (await getJSON(CUSTOM_KEY)) || [];
  for (const cp of custom) {
    if (!playerByName(cp.n)) PLAYERS.push(cp);
  }
  overridesApplied = true;
}

export async function saveOverride(name, fields) {
  const ov = await getOverrides();
  ov[name] = Object.assign(ov[name] || {}, fields);
  await setJSON(OVERRIDES_KEY, ov);
  const p = playerByName(name);
  if (p) Object.assign(p, fields);
  return p;
}

export async function addCustomPlayer(player) {
  const custom = (await getJSON(CUSTOM_KEY)) || [];
  custom.push(player);
  await setJSON(CUSTOM_KEY, custom);
  getPlayers().push(player);
}

// ---------- rooms ----------
const ROOM_PREFIX = 'room:';

function store() {
  return getStore({ name: 'auction', consistency: 'strong' });
}

export async function getRoom(code) {
  return store().get(ROOM_PREFIX + code, { type: 'json' });
}

export async function saveRoom(room) {
  await store().setJSON(ROOM_PREFIX + room.code, room);
}

export async function deleteRoom(code) {
  await store().delete(ROOM_PREFIX + code);
}

export function makeCode() {
  const A = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let c = '';
  for (let i = 0; i < 6; i++) c += A[Math.floor(Math.random() * A.length)];
  return c;
}

export function makeToken() {
  const A = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let t = '';
  for (let i = 0; i < 24; i++) t += A[Math.floor(Math.random() * A.length)];
  return t;
}

// ---------- auction rules ----------
export const RULES = {
  MEGA: { label: 'Mega Auction', purse: 12000, minSquad: 16, maxSquad: 25, maxOverseas: 8 },
  MINI: { label: 'Mini Auction', purse: 4000, minSquad: 16, maxSquad: 25, maxOverseas: 8 },
};

export function nextBid(price) {
  if (price < 100) return price + 5;
  if (price < 200) return price + 10;
  if (price < 500) return price + 20;
  if (price < 1000) return price + 40;
  return price + 80;
}

export function fmtLakh(l) {
  if (l == null) return '—';
  if (l >= 100) {
    const cr = l / 100;
    return '₹' + (Number.isInteger(cr) ? cr : cr.toFixed(2)) + ' Cr';
  }
  return '₹' + l + ' L';
}

export function squadSize(t) { return t.squad.length; }

export function overseasCount(t) {
  let n = 0;
  for (const s of t.squad) {
    const p = playerByName(s.n);
    if (p && p.c !== 'IND') n++;
  }
  return n;
}

export function maxBidFor(t, rules, player) {
  const spotsLeft = rules.maxSquad - squadSize(t);
  if (spotsLeft <= 0) return 0;
  let cap = t.purse - (spotsLeft - 1) * 40;   // keep ₹40L per other empty slot
  if (player && player.c !== 'IND' && overseasCount(t) >= rules.maxOverseas) return 0;
  return Math.max(0, cap);
}

// ---------- admin auth ----------
export const ADMIN_USER = 'VikramJain';
export const ADMIN_PASS = 'Vikram@12';

export function checkAdmin(user, pw) {
  return user === ADMIN_USER && pw === ADMIN_PASS;
}

// ---------- public room projection ----------
export function publicRoom(room) {
  const cur = room.current;
  let curPub = null;
  if (cur) {
    const p = playerByName(cur.name);
    curPub = {
      name: cur.name,
      bid: cur.bid,
      leader: cur.leader,
      endsAt: cur.endsAt,
      base: p ? p.b : 20,
      overseas: p ? p.c !== 'IND' : false,
    };
    if (room.showRatings && p) {
      curPub.rating = p.o;
      curPub.role = p.r;
      curPub.country = p.c;
    }
  }
  return {
    code: room.code,
    mode: room.mode,
    rules: room.rules,
    phase: room.phase,          // LOBBY | AUCTION | DONE
    paused: room.paused,
    showRatings: room.showRatings,
    bidSeconds: room.bidSeconds,
    hostTeam: room.hostTeam,
    order: room.order,
    teams: Object.fromEntries(room.order.map(id => {
      const t = room.teams[id];
      return [id, {
        id, name: t.name, short: t.short, gradient: t.gradient,
        purse: t.purse, owner: t.owner,
        squad: t.squad,
      }];
    })),
    current: curPub,
    log: (room.log || []).slice(0, 50),
    queueLeft: (room.queue || []).length + (room.unsold || []).length,
    done: room.phase === 'DONE',
  };
}

// Player list for clients — ratings stripped when the host hides them.
export function playersForRoom(room) {
  const list = getPlayers().map(p => {
    if (room.showRatings) return { n: p.n, c: p.c, r: p.r, o: p.o, b: p.b };
    return { n: p.n, c: p.c, r: null, o: null, b: p.b };
  });
  return list;
}
