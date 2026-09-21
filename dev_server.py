#!/usr/bin/env python3
# ============================================================
# Local dev emulator — mirrors the Netlify Functions API.
# Storage: data/_dev/ (blobs equivalent).
#   python dev_server.py  ->  http://localhost:8000
# ============================================================
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(ROOT, 'data', '_dev')
os.makedirs(DEV, exist_ok=True)

ADMIN_USER = 'VikramJain'
ADMIN_PASS = 'Vikram@12'
LOCK = threading.RLock()

def load(name, default):
    try:
        with open(os.path.join(DEV, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def save(name, obj):
    os.makedirs(DEV, exist_ok=True)
    with open(os.path.join(DEV, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)

TEAMS = json.load(open(os.path.join(ROOT, 'data', 'teams.json'), encoding='utf-8'))
PLAYERS = json.load(open(os.path.join(ROOT, 'data', 'players.json'), encoding='utf-8'))

def ensure_overrides():
    ov = load('rating_overrides.json', {})
    for p in PLAYERS:
        o = ov.get(p['n'])
        if o:
            for k in ('o', 'b', 'r', 'c'):
                if o.get(k) is not None:
                    p[k] = o[k]

def player_by_name(n):
    return next((p for p in PLAYERS if p['n'] == n), None)

def next_bid(price):
    if price < 100: return price + 5
    if price < 200: return price + 10
    if price < 500: return price + 20
    if price < 1000: return price + 40
    return price + 80

def fmt_lakh(l):
    if l >= 100:
        cr = l / 100
        return ('₹%d Cr' % cr) if cr == int(cr) else ('₹%.2f Cr' % cr)
    return '₹%d L' % l

RULES = {
    'MEGA': {'label': 'Mega Auction', 'purse': 12000, 'minSquad': 16, 'maxSquad': 25, 'maxOverseas': 8},
    'MINI': {'label': 'Mini Auction', 'purse': 4000, 'minSquad': 16, 'maxSquad': 25, 'maxOverseas': 8},
}

def get_room(code):
    return load('room:%s.json' % code, None)

def save_room(room):
    save('room:%s.json' % room['code'], room)

def blob_get(name):
    return load(name.replace(':', '_') + '.json', None)

def blob_set(name, obj):
    save(name.replace(':', '_') + '.json', obj)

def blob_del(name):
    p = os.path.join(DEV, name.replace(':', '_') + '.json')
    if os.path.exists(p):
        os.remove(p)

def public_room(room):
    cur = room.get('current')
    cur_pub = None
    if cur:
        p = player_by_name(cur['name'])
        cur_pub = {'name': cur['name'], 'bid': cur['bid'], 'leader': cur['leader'],
                   'endsAt': cur['endsAt'], 'base': p['b'] if p else 20,
                   'overseas': bool(p and p['c'] != 'IND')}
        if room.get('showRatings') and p:
            cur_pub.update({'rating': p['o'], 'role': p['r'], 'country': p['c']})
    return {
        'code': room['code'], 'mode': room['mode'], 'rules': room['rules'],
        'phase': room['phase'], 'paused': room['paused'],
        'showRatings': room['showRatings'], 'bidSeconds': room['bidSeconds'],
        'hostTeam': room['hostTeam'], 'order': room['order'],
        'teams': room['teams'], 'current': cur_pub,
        'log': room['log'][:50],
        'queueLeft': len(room['queue']) + len(room['unsold']),
        'done': room['phase'] == 'DONE',
    }

def players_for_room(room):
    out = []
    for p in PLAYERS:
        if room.get('showRatings'):
            out.append({'n': p['n'], 'c': p['c'], 'r': p['r'], 'o': p['o'], 'b': p['b']})
        else:
            out.append({'n': p['n'], 'c': p['c'], 'r': None, 'o': None, 'b': p['b']})
    return out

def build_set_queue():
    pool = sorted(PLAYERS, key=lambda p: -p['o'])
    out, SET = [], 8
    for i in range(0, len(pool), SET):
        s = pool[i:i + SET]
        random.shuffle(s)
        out.extend(p['n'] for p in s)
    return out

import random

def next_player(room):
    if not room['queue'] and room['unsold']:
        random.shuffle(room['unsold'])
        room['queue'] = room['unsold'][:]
        room['unsold'] = []
        room['log'].insert(0, '🔄 Round two: unsold players re-enter')
    if not room['queue']:
        room['phase'] = 'DONE'
        room['current'] = None
        room['log'].insert(0, '🏆 Auction complete!')
        return
    name = room['queue'].pop(0)
    room['current'] = {'name': name, 'bid': 0, 'leader': None,
                       'endsAt': time.time() * 1000 + room['bidSeconds'] * 1000}
    p = player_by_name(name)
    room['log'].insert(0, '🎤 On the block: %s (base %s)' % (name, fmt_lakh(p['b']) if p else '—'))

def sell_current(room):
    cur = room['current']
    t = room['teams'][cur['leader']]
    t['squad'].append({'n': cur['name'], 'p': cur['bid']})
    t['purse'] -= cur['bid']
    room['log'].insert(0, '🔨 SOLD %s to %s for %s' % (cur['name'], t['short'], fmt_lakh(cur['bid'])))
    room['history'].append({'n': cur['name'], 'team': cur['leader'], 'p': cur['bid']})
    next_player(room)

def mark_unsold(room):
    cur = room['current']
    p = player_by_name(cur['name'])
    room['unsold'].append(cur['name'])
    room['log'].insert(0, '❌ UNSOLD %s (base %s)' % (cur['name'], fmt_lakh(p['b']) if p else 0))
    next_player(room)

def fold_bids(room):
    cur = room['current']
    if not cur:
        return
    expected = (player_by_name(cur['name'])['b'] if cur['bid'] == 0 and player_by_name(cur['name']) else 20) \
        if cur['bid'] == 0 else next_bid(cur['bid'])
    claims = []
    for tid in room['order']:
        c = blob_get('bid:%s:%s' % (room['code'], tid))
        if c and c.get('amount') == expected:
            claims.append(c)
    if not claims:
        return
    claims.sort(key=lambda c: c['at'])
    for c in claims:
        t = room['teams'].get(c['team'])
        if not t or cur['leader'] == c['team']:
            continue
        spots = room['rules']['maxSquad'] - len(t['squad'])
        if spots <= 0:
            continue
        cap = t['purse'] - max(0, spots - 1) * 40
        if c['amount'] > cap:
            continue
        p = player_by_name(cur['name'])
        ov = sum(1 for s in t['squad'] if player_by_name(s['n']) and player_by_name(s['n'])['c'] != 'IND')
        if p and p['c'] != 'IND' and ov >= room['rules']['maxOverseas']:
            continue
        cur['bid'] = c['amount']
        cur['leader'] = c['team']
        cur['endsAt'] = c['at'] + room['bidSeconds'] * 1000
        room['log'].insert(0, '💰 %s bids %s for %s' % (t['short'], fmt_lakh(c['amount']), p['n']))
        break
    for tid in room['order']:
        blob_del('bid:%s:%s' % (room['code'], tid))

def fold_joins(room):
    if room['phase'] != 'LOBBY':
        return
    for tid in room['order']:
        if room['teams'][tid]['owner']:
            continue
        c = blob_get('join:%s:%s' % (room['code'], tid))
        if c and c.get('name'):
            room['teams'][tid]['owner'] = c['name']
            room['log'].insert(0, '👋 %s joins as %s' % (c['name'], room['teams'][tid]['short']))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def j(self, obj, status=200):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split('?')[0]
        qs = dict(p.split('=', 1) for p in self.path.split('?')[1].split('&') if '=' in p) if '?' in self.path else {}
        if path == '/api/teams':
            return self.j({'teams': TEAMS})
        if path == '/api/room':
            with LOCK:
                room = get_room(qs.get('code', '').upper())
                if not room:
                    return self.j({'error': 'Room not found'}, 404)
                return self.j({'room': public_room(room), 'players': players_for_room(room)})
        return self.static(path)

    def static(self, path):
        name = path.lstrip('/') or 'index.html'
        full = os.path.normpath(os.path.join(ROOT, name))
        if not full.startswith(ROOT) or not os.path.isfile(full):
            return self.j({'error': 'Not found'}, 404)
        ctype = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                 '.css': 'text/css; charset=utf-8', '.json': 'application/json'}.get(
                     os.path.splitext(name)[1], 'application/octet-stream')
        with open(full, 'rb') as f:
            b = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        path = self.path.split('?')[0]
        b = self.body()
        with LOCK:
            if path == '/api/room':
                return self.room_api(b)
            if path == '/api/join':
                return self.join_api(b)
            if path == '/api/bid':
                return self.bid_api(b)
            if path == '/api/admin':
                return self.admin_api(b)
        return self.j({'error': 'Not found'}, 404)

    def room_api(self, b):
        act = b.get('action')
        if act == 'create':
            mode = b.get('mode') if b.get('mode') in RULES else 'MEGA'
            team = b.get('team')
            if team not in [t['id'] for t in TEAMS]:
                return self.j({'error': 'Pick a franchise'}, 400)
            secs = b.get('bidSeconds') if b.get('bidSeconds') in (10, 7, 5, 3) else 10
            import secrets
            code = ''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
            rules = RULES[mode]
            room = {
                'code': code, 'mode': mode, 'rules': rules, 'bidSeconds': secs,
                'showRatings': b.get('showRatings', True), 'hostTeam': team,
                'hostToken': secrets.token_hex(12), 'phase': 'LOBBY', 'paused': False,
                'order': [t['id'] for t in TEAMS],
                'teams': {t['id']: {'id': t['id'], 'name': t['name'], 'short': t['short'],
                                    'gradient': t['gradient'], 'purse': rules['purse'],
                                    'owner': None, 'squad': []} for t in TEAMS},
                'queue': [], 'unsold': [], 'current': None, 'log': [], 'history': [],
            }
            room['teams'][team]['owner'] = (b.get('name') or 'Host')[:24]
            save_room(room)
            return self.j({'code': code, 'token': room['hostToken']})

        room = get_room((b.get('code') or '').upper())
        if not room:
            return self.j({'error': 'Room not found'}, 404)
        if not room.get('hostToken') or b.get('token') != room['hostToken']:
            return self.j({'error': 'Host only'}, 403)

        if act == 'start':
            if room['phase'] != 'LOBBY':
                return self.j({'error': 'Already started'}, 409)
            fold_joins(room)
            for tid in room['order']:
                blob_del('join:%s:%s' % (room['code'], tid))
                blob_del('bid:%s:%s' % (room['code'], tid))
            room['queue'] = build_set_queue()
            room['unsold'] = []
            room['phase'] = 'AUCTION'
            room['log'] = ['Auction started — %d players, random set-wise order' % len(room['queue'])]
            next_player(room)
            save_room(room)
            return self.j({'ok': True})

        if act == 'tick':
            if room['phase'] == 'LOBBY':
                fold_joins(room)
                save_room(room)
                return self.j({'ok': True, 'room': public_room(room)})
            if room['phase'] == 'AUCTION' and not room['paused']:
                fold_bids(room)
                if room['current'] and time.time() * 1000 >= room['current']['endsAt']:
                    if room['current']['leader']:
                        sell_current(room)
                    else:
                        mark_unsold(room)
                save_room(room)
            return self.j({'ok': True, 'room': public_room(room)})

        if act == 'pause':
            room['paused'] = True
            room['pausedAt'] = time.time() * 1000
            save_room(room)
            return self.j({'ok': True})

        if act == 'resume':
            room['paused'] = False
            delta = time.time() * 1000 - room.get('pausedAt', time.time() * 1000)
            if room['current']:
                room['current']['endsAt'] += delta
            save_room(room)
            return self.j({'ok': True})

        if act == 'ratings':
            room['showRatings'] = bool(b.get('show'))
            room['log'].insert(0, '👁 Ratings shown by host' if room['showRatings'] else '🙈 Ratings hidden by host')
            save_room(room)
            return self.j({'ok': True, 'showRatings': room['showRatings']})

        if act == 'timer':
            if b.get('seconds') not in (10, 7, 5, 3):
                return self.j({'error': 'Timer must be 10/7/5/3'}, 400)
            room['bidSeconds'] = b['seconds']
            if room['current']:
                room['current']['endsAt'] = time.time() * 1000 + b['seconds'] * 1000
            room['log'].insert(0, '⏱ Bid timer set to %ds by host' % b['seconds'])
            save_room(room)
            return self.j({'ok': True, 'bidSeconds': room['bidSeconds']})

        if act == 'reset':
            room['phase'] = 'LOBBY'
            room['paused'] = False
            room['current'] = None
            room['queue'] = []
            room['unsold'] = []
            room['history'] = []
            for tid in room['order']:
                room['teams'][tid]['squad'] = []
                room['teams'][tid]['purse'] = room['rules']['purse']
            room['log'] = ['Room reset for a new auction']
            save_room(room)
            return self.j({'ok': True})

        return self.j({'error': 'Unknown action'}, 400)

    def join_api(self, b):
        code = (b.get('code') or '').upper()
        team = b.get('team')
        name = (b.get('name') or '').strip()[:24]
        if not code or not team or not name:
            return self.j({'error': 'Enter code, name and pick a franchise'}, 400)
        room = get_room(code)
        if not room:
            return self.j({'error': 'Room not found'}, 404)
        if room['phase'] != 'LOBBY':
            return self.j({'error': 'Auction already started'}, 409)
        t = room['teams'].get(team)
        if not t:
            return self.j({'error': 'Unknown franchise'}, 400)
        if t['owner'] and t['owner'] != name:
            return self.j({'error': 'That franchise is taken — pick another'}, 409)
        existing = blob_get('join:%s:%s' % (code, team))
        if existing and existing['name'] != name and time.time() - existing['at'] < 20:
            return self.j({'error': 'That franchise was just taken — pick another'}, 409)
        blob_set('join:%s:%s' % (code, team), {'name': name, 'team': team, 'at': time.time()})
        return self.j({'ok': True, 'team': team, 'token': 'team:%s:%s' % (code, team)})

    def bid_api(self, b):
        code = (b.get('code') or '').upper()
        team = b.get('team')
        room = get_room(code)
        if not room:
            return self.j({'ok': False, 'msg': 'Room not found'})
        if b.get('token') != 'team:%s:%s' % (code, team):
            return self.j({'ok': False, 'msg': 'Not your team'})
        if room['phase'] != 'AUCTION' or room['paused'] or not room['current']:
            return self.j({'ok': False, 'msg': 'Auction not live'})
        cur = room['current']
        p = player_by_name(cur['name'])
        expected = p['b'] if cur['bid'] == 0 and p else next_bid(cur['bid'])
        if b.get('amount') != expected:
            return self.j({'ok': False, 'msg': 'Bid must be exactly %s' % fmt_lakh(expected)})
        if cur['leader'] == team:
            return self.j({'ok': False, 'msg': 'You are already the highest bidder'})
        t = room['teams'][team]
        spots = room['rules']['maxSquad'] - len(t['squad'])
        cap = t['purse'] - max(0, spots - 1) * 40
        if b['amount'] > cap:
            return self.j({'ok': False, 'msg': 'Not enough purse'})
        if p and p['c'] != 'IND':
            ov = sum(1 for s in t['squad'] if (player_by_name(s['n']) or {}).get('c') != 'IND')
            if ov >= room['rules']['maxOverseas']:
                return self.j({'ok': False, 'msg': 'Overseas cap reached'})
        blob_set('bid:%s:%s' % (code, team),
                 {'amount': b['amount'], 'team': team, 'at': time.time() * 1000})
        return self.j({'ok': True})

    def admin_api(self, b):
        if b.get('user') != ADMIN_USER or b.get('pw') != ADMIN_PASS:
            return self.j({'error': 'Wrong username or password'}, 401)
        act = b.get('action')
        if act == 'list':
            return self.j({'players': PLAYERS})
        if act == 'update':
            p = player_by_name(b.get('name', ''))
            if not p:
                return self.j({'error': 'Player not found'}, 404)
            if b.get('o') is not None:
                p['o'] = max(40, min(99, int(b['o'])))
            if b.get('b') is not None:
                p['b'] = max(20, min(2000, int(b['b'])))
            ov = load('rating_overrides.json', {})
            ov[p['n']] = {'o': p['o'], 'b': p['b']}
            save('rating_overrides.json', ov)
            return self.j({'ok': True, 'player': p})
        if act == 'add':
            name = (b.get('name') or '').strip()
            if not name:
                return self.j({'error': 'Name required'}, 400)
            if player_by_name(name):
                return self.j({'error': 'Player already exists'}, 409)
            p = {'n': name, 'c': (b.get('c') or 'IND').upper()[:3],
                 'r': b.get('r') if b.get('r') in ('BAT', 'BOW', 'AR', 'WK') else 'BAT',
                 'o': max(40, min(99, int(b.get('o') or 75))),
                 'b': max(20, min(2000, int(b.get('b') or 75))), 't': ''}
            PLAYERS.append(p)
            ov = load('rating_overrides.json', {})
            ov[name] = {'o': p['o'], 'b': p['b'], 'r': p['r'], 'c': p['c']}
            save('rating_overrides.json', ov)
            return self.j({'ok': True, 'player': p})
        return self.j({'error': 'Unknown action'}, 400)

def main():
    try:
        import sys
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ensure_overrides()
    try:
        port = int(os.environ.get('PORT') or 8000) or 8000
    except Exception:
        port = 8000
    httpd = ThreadingHTTPServer(('0.0.0.0', port), H)
    print('[OK] Dev server (same API as Netlify) at http://localhost:%d' % port)
    print('     Admin: /admin.html  (VikramJain)')
    httpd.serve_forever()

if __name__ == '__main__':
    main()
