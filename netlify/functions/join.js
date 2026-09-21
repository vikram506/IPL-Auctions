// ============================================================
// POST /api/join  { code, team, name }
// Claim is written to the team's own blob (no write conflicts).
// The host's tick() folds claims into room state.
// Token = "team:CODE:TEAMID" (friendly game — no real auth needed)
// ============================================================
import { getStore } from '@netlify/blobs';
import { TEAMS } from './_store.js';

export const config = { path: '/api/join' };

export default async (req) => {
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  const body = await req.json().catch(() => ({}));
  const code = (body.code || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const team = body.team;
  const name = (body.name || '').trim().slice(0, 24);

  if (!code || !team || !name) return json({ error: 'Enter code, name and pick a franchise' }, 400);
  if (!TEAMS.find(t => t.id === team)) return json({ error: 'Unknown franchise' }, 400);

  const store = getStore({ name: 'auction', consistency: 'strong' });
  const room = await store.get('room:' + code, { type: 'json' });
  if (!room) return json({ error: 'Room not found' }, 404);
  if (room.phase !== 'LOBBY') return json({ error: 'Auction already started' }, 409);

  // taken in room state OR claimed in a blob within the last 20s
  const t = room.teams[team];
  const claimedInRoom = t && t.owner && t.owner !== name;
  let claimedInBlob = false;
  try {
    const existing = await store.get('join:' + code + ':' + team, { type: 'json' });
    if (existing && existing.name !== name && Date.now() - existing.at < 20000) claimedInBlob = true;
  } catch (e) {}

  if (claimedInRoom || claimedInBlob) return json({ error: 'That franchise was just taken — pick another' }, 409);

  await store.setJSON('join:' + code + ':' + team, { name, team, at: Date.now() });

  return json({ ok: true, team, token: 'team:' + code + ':' + team });
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
