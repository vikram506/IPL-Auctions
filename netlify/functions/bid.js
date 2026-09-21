// ============================================================
// POST /api/bid  { code, team, token, amount }
// Player's bid is written to their own blob — no conflicts.
// Host's tick() folds claims into room state.
// ============================================================
import { getStore } from '@netlify/blobs';
import { playerByName } from './_store.js';

export const config = { path: '/api/bid' };

export default async (req) => {
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  const body = await req.json().catch(() => ({}));
  const code = (body.code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const team = body.team;

  if (!code || !team || !body.token) return json({ error: 'Missing fields' }, 400);

  const store = getStore({ name: 'auction', consistency: 'strong' });

  // Lightweight validation against room state (avoids most junk bids early;
  // host re-validates everything authoritatively when folding).
  let valid = true, msg = 'ok';
  try {
    const room = await store.get('room:' + code, { type: 'json' });
    if (!room) { valid = false; msg = 'Room not found'; }
    else {
      const t = room.teams[team];
      const cur = room.current;
      if (!t || body.token !== 'team:' + code + ':' + team) { valid = false; msg = 'Not your team'; }
      else if (room.phase !== 'AUCTION' || room.paused) { valid = false; msg = 'Auction not live'; }
      else if (!cur) { valid = false; msg = 'No player on the block'; }
      else {
        const expected = cur.bid === 0 ? currentBase(room, cur.name) : nextBid(cur.bid);
        if (body.amount !== expected) { valid = false; msg = 'Bid must be exactly ' + expected; }
        else if (cur.leader === team) { valid = false; msg = 'You are already the highest bidder'; }
        else {
          const spotsLeft = room.rules.maxSquad - t.squad.length;
          const cap = t.purse - Math.max(0, spotsLeft - 1) * 40;
          if (body.amount > cap) { valid = false; msg = 'Not enough purse'; }
          else {
            const p = playerByName(cur.name);
            if (p && p.c !== 'IND' && overseasCount(room, team) >= room.rules.maxOverseas) {
              valid = false; msg = 'Overseas cap reached';
            }
          }
        }
      }
    }
  } catch (e) { /* fall through — host still re-validates */ }

  if (!valid) return json({ ok: false, msg });

  // Write claim to the team's own blob (last-write-wins per team)
  await store.setJSON('bid:' + code + ':' + team, {
    amount: body.amount,
    team,
    token: body.token,
    at: Date.now(),
  });

  return json({ ok: true });
};

function currentBase(room, name) {
  const p = playerByName(name);
  return p ? p.b : 20;
}

// local copies to avoid a circular import with _store.js
function nextBid(price) {
  if (price < 100) return price + 5;
  if (price < 200) return price + 10;
  if (price < 500) return price + 20;
  if (price < 1000) return price + 40;
  return price + 80;
}

function overseasCount(room, teamId) {
  let n = 0;
  for (const s of room.teams[teamId].squad) {
    const p = playerByName(s.n);
    if (p && p.c !== 'IND') n++;
  }
  return n;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
