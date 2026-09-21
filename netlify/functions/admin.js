// ============================================================
// POST /api/admin  { action: 'login'|'list'|'update'|'add', ... }
// Login:  { user, pw }
// List:   { user, pw }  (credentials re-sent per request — simple & stateless)
// Update: { user, pw, name, o, b }
// Add:    { user, pw, name, c, r, o, b }
// ============================================================
import {
  checkAdmin, getPlayers, saveOverride, ensureOverrides, playerByName, addCustomPlayer,
} from './_store.js';

export const config = { path: '/api/admin' };

export default async (req) => {
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  const body = await req.json().catch(() => ({}));
  if (!checkAdmin(body.user, body.pw)) return json({ error: 'Wrong username or password' }, 401);

  await ensureOverrides();

  if (body.action === 'list') {
    return json({ players: getPlayers() });
  }

  if (body.action === 'update') {
    const name = body.name;
    const p = playerByName(name);
    if (!p) return json({ error: 'Player not found' }, 404);
    const fields = {};
    if (body.o != null) fields.o = Math.max(40, Math.min(99, parseInt(body.o, 10)));
    if (body.b != null) fields.b = Math.max(20, Math.min(2000, parseInt(body.b, 10)));
    await saveOverride(name, fields);
    return json({ ok: true, player: p });
  }

  if (body.action === 'add') {
    const name = (body.name || '').trim();
    if (!name) return json({ error: 'Name required' }, 400);
    if (playerByName(name)) return json({ error: 'Player already exists' }, 409);
    const p = {
      n: name,
      c: (body.c || 'IND').toUpperCase().slice(0, 3),
      r: ['BAT', 'BOW', 'AR', 'WK'].includes(body.r) ? body.r : 'BAT',
      o: Math.max(40, Math.min(99, parseInt(body.o, 10) || 75)),
      b: Math.max(20, Math.min(2000, parseInt(body.b, 10) || 75)),
      t: '',
    };
    getPlayers().push(p);
    await addCustomPlayer(p);
    await saveOverride(name, { o: p.o, b: p.b, r: p.r, c: p.c });
    return json({ ok: true, player: p });
  }

  return json({ error: 'Unknown action' }, 400);
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
