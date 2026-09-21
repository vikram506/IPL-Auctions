// ============================================================
// GET  /api/room?code=XXXXXX    -> { room, players }
// POST /api/room                -> actions:
//   create  { mode, team, name, bidSeconds, showRatings } -> { code }
//   start   { code, token }        (host)  build random set-wise queue
//   tick    { code, token }        (host)  fold claims, run clock
//   pause   { code, token }        (host)
//   resume  { code, token }        (host)
//   ratings { code, token, show }  (host)
//   timer   { code, token, seconds: 10|7|5|3 }  (host)
//   reset   { code, token }        (host)  back to lobby, fresh purses
// ============================================================
import {
  TEAMS, RULES, getRoom, saveRoom, makeCode, makeToken,
  publicRoom, fmtLakh, getPlayers, playerByName, playersForRoom, ensureOverrides,
} from './_store.js';
import { getStore } from '@netlify/blobs';

export const config = { path: '/api/room' };
import { getStore } from '@netlify/blobs';

export default async (req, context) => {
  const url = new URL(req.url);

  // ---------- GET ----------
  if (req.method === 'GET') {
    await ensureOverrides();
    const code = (url.searchParams.get('code') || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    const room = await getRoom(code);
    if (!room) return json({ error: 'Room not found' }, 404);
    return json({ room: publicRoom(room), players: playersForRoom(room) });
  }

  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  const body = await req.json().catch(() => ({}));
  const action = body.action;

  // ---------- create ----------
  if (action === 'create') {
    await ensureOverrides();
    const mode = body.mode === 'MINI' ? 'MINI' : 'MEGA';
    const team = body.team;
    if (!TEAMS.find(t => t.id === team)) return json({ error: 'Pick a franchise' }, 400);
    const bidSeconds = [10, 7, 5, 3].includes(body.bidSeconds) ? body.bidSeconds : 10;
    const code = makeCode();
    const rules = RULES[mode];
    const room = {
      code, mode, rules,
      bidSeconds,
      showRatings: body.showRatings !== false,
      hostTeam: team,
      hostToken: makeToken(),
      phase: 'LOBBY',
      paused: false,
      createdAt: Date.now(),
      order: TEAMS.map(t => t.id),
      teams: Object.fromEntries(TEAMS.map(t => [t.id, {
        id: t.id, name: t.name, short: t.short, gradient: t.gradient,
        purse: rules.purse, owner: null, squad: [],
      }])),
      queue: [], unsold: [], current: null, log: [], history: [],
    };
    room.teams[team].owner = (body.name || 'Host').slice(0, 24);
    await saveRoom(room);
    return json({ code, token: room.hostToken });
  }

  // ---------- host-authenticated actions ----------
  const code = (body.code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const room = await getRoom(code);
  if (!room) return json({ error: 'Room not found' }, 404);
  if (!room.hostToken || body.token !== room.hostToken) {
    return json({ error: 'Host only' }, 403);
  }

  const store = getStore({ name: 'auction', consistency: 'strong' });

  switch (action) {
    case 'start': {
      if (room.phase !== 'LOBBY') return json({ error: 'Already started' }, 409);
      await ensureOverrides();
      await foldJoins(room, store);   // last-chance fold of pending joins
      // clear join + bid claims so a reset/restart starts clean
      for (const id of room.order) {
        try { await store.delete('join:' + room.code + ':' + id); } catch (e) {}
        try { await store.delete('bid:' + room.code + ':' + id); } catch (e) {}
      }
      room.queue = buildSetQueue();
      room.unsold = [];
      room.phase = 'AUCTION';
      room.log = ['Auction started — ' + room.queue.length + ' players, random set-wise order'];
      nextPlayer(room);
      await saveRoom(room);
      return json({ ok: true });
    }

    case 'tick': {
      if (room.phase === 'LOBBY') await foldJoins(room, store);
      if (room.phase !== 'AUCTION' || room.paused) {
        await saveRoom(room);
        return json({ ok: true, room: publicRoom(room) });
      }
      await foldBids(room, store);
      // clock: hammer falls when endsAt passes
      if (room.current && Date.now() >= room.current.endsAt) {
        if (room.current.leader) sellCurrent(room);
        else markUnsold(room);
      }
      await saveRoom(room);
      return json({ ok: true, room: publicRoom(room) });
    }

    case 'pause': {
      room.paused = true;
      room.pausedAt = Date.now();
      await saveRoom(room);
      return json({ ok: true });
    }

    case 'resume': {
      room.paused = false;
      const delta = Date.now() - (room.pausedAt || Date.now());
      if (room.current) room.current.endsAt += delta;
      await saveRoom(room);
      return json({ ok: true });
    }

    case 'ratings': {
      room.showRatings = !!body.show;
      room.log.unshift(room.showRatings ? '👁 Ratings shown by host' : '🙈 Ratings hidden by host');
      await saveRoom(room);
      return json({ ok: true, showRatings: room.showRatings });
    }

    case 'timer': {
      if (![10, 7, 5, 3].includes(body.seconds)) return json({ error: 'Timer must be 10/7/5/3' }, 400);
      room.bidSeconds = body.seconds;
      if (room.current) room.current.endsAt = Date.now() + body.seconds * 1000;
      room.log.unshift('⏱ Bid timer set to ' + body.seconds + 's by host');
      await saveRoom(room);
      return json({ ok: true, bidSeconds: room.bidSeconds });
    }

    case 'reset': {
      room.phase = 'LOBBY';
      room.paused = false;
      room.current = null;
      room.queue = []; room.unsold = []; room.history = [];
      for (const id of room.order) {
        room.teams[id].squad = [];
        room.teams[id].purse = room.rules.purse;
      }
      room.log = ['Room reset for a new auction'];
      await saveRoom(room);
      return json({ ok: true });
    }

    default:
      return json({ error: 'Unknown action' }, 400);
  }
};

// ---------- random set-wise queue ----------
// Sort pool by rating, chunk into sets of 8, shuffle WITHIN each set,
// play set 1 (marquee tier) first, then set 2, etc.
function buildSetQueue() {
  const pool = [...getPlayers()].sort((a, b) => b.o - a.o);
  const SET = 8;
  const out = [];
  for (let i = 0; i < pool.length; i += SET) {
    const set = pool.slice(i, i + SET);
    for (let j = set.length - 1; j > 0; j--) {
      const k = Math.floor(Math.random() * (j + 1));
      [set[j], set[k]] = [set[k], set[j]];
    }
    out.push(...set.map(p => p.n));
  }
  return out;
}

// ---------- folding claims ----------
async function foldJoins(room, store) {
  if (room.phase !== 'LOBBY') return;
  for (const id of room.order) {
    if (room.teams[id].owner) continue;
    try {
      const c = await store.get('join:' + room.code + ':' + id, { type: 'json' });
      if (c && c.name) {
        room.teams[id].owner = c.name;
        room.log.unshift('👋 ' + c.name + ' joins as ' + room.teams[id].short);
      }
    } catch (e) { /* no claim */ }
  }
}

async function foldBids(room, store) {
  const cur = room.current;
  if (!cur) return;
  const expected = cur.bid === 0 ? (playerByName(cur.name)?.b ?? 20) : nextBid(cur.bid);

  const claims = [];
  for (const id of room.order) {
    try {
      const c = await store.get('bid:' + room.code + ':' + id, { type: 'json' });
      if (c && c.amount === expected) claims.push(c);
    } catch (e) { /* no claim */ }
  }
  if (!claims.length) return;

  // earliest bid wins the auction price; others stay for the next round
  claims.sort((a, b) => a.at - b.at);

  let sold = false;
  for (const c of claims) {
    if (sold) break;
    const t = room.teams[c.team];
    if (!t || room.current.leader === c.team) continue;
    // full validation at fold time
    const player = playerByName(room.current.name);
    const spotsLeft = room.rules.maxSquad - t.squad.length;
    if (spotsLeft <= 0) continue;
    const cap = t.purse - Math.max(0, spotsLeft - 1) * 40;
    if (c.amount > cap) continue;
    if (player && player.c !== 'IND' && overseasCount(room, c.team) >= room.rules.maxOverseas) continue;

    room.current.bid = c.amount;
    room.current.leader = c.team;
    room.current.endsAt = c.at + room.bidSeconds * 1000;   // clock resets on every bid
    room.log.unshift('💰 ' + t.short + ' bids ' + fmtLakh(c.amount) + ' for ' + player.n);
    sold = true;
  }

  // clear all consumed claims
  for (const id of room.order) {
    try { await store.delete('bid:' + room.code + ':' + id); } catch (e) {}
  }
}

function overseasCount(room, teamId) {
  let n = 0;
  for (const s of room.teams[teamId].squad) {
    const p = playerByName(s.n);
    if (p && p.c !== 'IND') n++;
  }
  return n;
}

function nextPlayer(room) {
  if (!room.queue.length && room.unsold.length) {
    room.queue = shuffle(room.unsold.slice());
    room.unsold = [];
    room.log.unshift('🔄 Round two: unsold players re-enter');
  }
  if (!room.queue.length) {
    room.phase = 'DONE';
    room.current = null;
    room.log.unshift('🏆 Auction complete!');
    return;
  }
  const name = room.queue.shift();
  room.current = {
    name,
    bid: 0,
    leader: null,
    endsAt: Date.now() + room.bidSeconds * 1000,
  };
  const p = playerByName(name);
  room.log.unshift('🎤 On the block: ' + name + (p ? ' (base ' + fmtLakh(p.b) + ')' : ''));
}

function sellCurrent(room) {
  const cur = room.current;
  const t = room.teams[cur.leader];
  t.squad.push({ n: cur.name, p: cur.bid });
  t.purse -= cur.bid;
  room.log.unshift('🔨 SOLD ' + cur.name + ' to ' + t.short + ' for ' + fmtLakh(cur.bid));
  room.history.push({ n: cur.name, team: cur.leader, p: cur.bid, at: Date.now() });
  nextPlayer(room);
}

function markUnsold(room) {
  const cur = room.current;
  const p = playerByName(cur.name);
  room.unsold.push(cur.name);
  room.log.unshift('❌ UNSOLD ' + cur.name + ' (base ' + fmtLakh(p ? p.b : 0) + ')');
  nextPlayer(room);
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function nextBid(price) {
  if (price < 100) return price + 5;
  if (price < 200) return price + 10;
  if (price < 500) return price + 20;
  if (price < 1000) return price + 40;
  return price + 80;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
