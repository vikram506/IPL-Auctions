#!/usr/bin/env python3
# End-to-end API test against dev_server.py (mirrors Netlify functions)
import json, time, urllib.request, sys

BASE = 'http://127.0.0.1:8000'
failures = 0

def req(path, body=None):
    if body is None:
        r = urllib.request.urlopen(BASE + path, timeout=5)
        return json.loads(r.read())
    data = json.dumps(body).encode()
    rq = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(rq, timeout=5)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def check(name, cond):
    global failures
    print(('  OK ' if cond else '  FAIL ') + name)
    if not cond: failures += 1

print('[1] create room (host RCB)')
r = req('/api/room', {'action': 'create', 'mode': 'MEGA', 'team': 'RCB', 'name': 'Vikram', 'bidSeconds': 10, 'showRatings': True})
code, host_token = r['code'], r['token']
check('code is 6 chars', len(code) == 6)
check('host token returned', bool(host_token))

print('[2] two friends join')
r1 = req('/api/join', {'code': code, 'team': 'SRH', 'name': 'Aarav'})
r2 = req('/api/join', {'code': code, 'team': 'MI', 'name': 'Priya'})
check('join 1 ok', r1.get('ok'))
check('join 2 ok', r2.get('ok'))
dup = req('/api/join', {'code': code, 'team': 'SRH', 'name': 'SomeoneElse'})
check('duplicate claim rejected', 'error' in dup)

print('[3] host tick folds joins into lobby')
req('/api/room', {'action': 'tick', 'code': code, 'token': host_token})
room = req('/api/room?code=' + code)['room']
check('SRH owner folded', room['teams']['SRH']['owner'] == 'Aarav')
check('MI owner folded', room['teams']['MI']['owner'] == 'Priya')

print('[4] start -> random set-wise queue')
req('/api/room', {'action': 'start', 'code': code, 'token': host_token})
room = req('/api/room?code=' + code)['room']
cur = room['current']
check('phase AUCTION', room['phase'] == 'AUCTION')
check('current player on block', bool(cur and cur['name']))
players = req('/api/room?code=' + code)['players']
pool_names = [p['n'] for p in players]
check('pool has 190+ names', len(pool_names) >= 190)

print('[5] bids: SRH opens at base, MI counter, clock resets, hammer sells')
def step_after(price):
    if price < 100: return 5
    if price < 200: return 10
    if price < 500: return 20
    if price < 1000: return 40
    return 80

p = players[[x['n'] for x in players].index(cur['name'])]
base = cur['base']
b = req('/api/bid', {'code': code, 'team': 'SRH', 'token': 'team:%s:SRH' % code, 'amount': base})
check('SRH opening bid accepted', b.get('ok') is True)
# advance host clock: folds bid + hammer after endsAt
time.sleep(0.3)
req('/api/room', {'action': 'tick', 'code': code, 'token': host_token})
room = req('/api/room?code=' + code)['room']
check('SRH is leader at base', room['current']['leader'] == 'SRH' and room['current']['bid'] == base)
# MI counters +500? no: ladder +5 from base (base < 100)
b2 = req('/api/bid', {'code': code, 'team': 'MI', 'token': 'team:%s:MI' % code, 'amount': base + step_after(base)})
check('MI counter accepted', b2.get('ok') is True)
# wrong-ladder bid rejected
b3 = req('/api/bid', {'code': code, 'team': 'SRH', 'token': 'team:%s:SRH' % code, 'amount': base + 100})
check('off-ladder bid rejected', b3.get('ok') is False)
# wait out the hammer (10s timer) via ticks
for _ in range(12):
    time.sleep(1)
    req('/api/room', {'action': 'tick', 'code': code, 'token': host_token})
    room = req('/api/room?code=' + code)['room']
    if room['current'] and room['current']['name'] != p['n']:
        break
check('hammer fell and MI bought player', room['current']['name'] != p['n'])
sold_line = next((l for l in room['log'] if 'SOLD' in l and p['n'] in l), None)
check('SOLD log line for ' + p['n'], bool(sold_line))
mi = room['teams']['MI']
check('MI squad has player & purse deducted', any(s['n'] == p['n'] for s in mi['squad']) and mi['purse'] == 12000 - (base + step_after(base)))

print('[6] ratings hidden by host -> API strips them')
req('/api/room', {'action': 'ratings', 'code': code, 'token': host_token, 'show': False})
data = req('/api/room?code=' + code)
check('showRatings false', data['room']['showRatings'] is False)
check('player ratings stripped from API', all(p['o'] is None for p in data['players']))
cur2 = data['room']['current']
check('current player rating hidden but base visible', cur2 and 'rating' not in cur2 and cur2.get('base', 0) > 0)
req('/api/room', {'action': 'ratings', 'code': code, 'token': host_token, 'show': True})
check('ratings shown again', req('/api/room?code=' + code)['room']['showRatings'] is True)

print('[7] timer change 10 -> 3s')
req('/api/room', {'action': 'timer', 'code': code, 'token': host_token, 'seconds': 3})
room = req('/api/room?code=' + code)['room']
check('bidSeconds now 3', room['bidSeconds'] == 3)

print('[8] pause freezes clock')
req('/api/room', {'action': 'pause', 'code': code, 'token': host_token})
name_at_pause = req('/api/room?code=' + code)['room']['current']['name']
for _ in range(4):
    time.sleep(0.6)
    req('/api/room', {'action': 'tick', 'code': code, 'token': host_token})
room = req('/api/room?code=' + code)['room']
check('paused blocks hammer', room['current'] and room['current']['name'] == name_at_pause and room['paused'])
req('/api/room', {'action': 'resume', 'code': code, 'token': host_token})
check('resumed', req('/api/room?code=' + code)['room']['paused'] is False)

print('[9] admin: login, list, update rating')
bad = req('/api/admin', {'action': 'list', 'user': 'VikramJain', 'pw': 'wrong'})
check('wrong password rejected', 'error' in bad)
lst = req('/api/admin', {'action': 'list', 'user': 'VikramJain', 'pw': 'Vikram@12'})
vb = next((x for x in lst['players'] if x['n'] == 'Vaibhav Suryavanshi'), None)
check('Vaibhav Suryavanshi in pool (rating %s)' % (vb['o'] if vb else '?'), vb is not None)
up = req('/api/admin', {'action': 'update', 'user': 'VikramJain', 'pw': 'Vikram@12', 'name': 'Vaibhav Suryavanshi', 'o': 95, 'b': 200})
check('updated to 95', up.get('ok') and up['player']['o'] == 95)
lst2 = req('/api/admin', {'action': 'list', 'user': 'VikramJain', 'pw': 'Vikram@12'})
vb2 = next(x for x in lst2['players'] if x['n'] == 'Vaibhav Suryavanshi')
check('override persisted in listing', vb2['o'] == 95)
lst_before = req('/api/admin', {'action': 'list', 'user': 'VikramJain', 'pw': 'Vikram@12'})
already = any(x['n'] == 'Test Star Man' for x in lst_before['players'])
if not already:
    add = req('/api/admin', {'action': 'add', 'user': 'VikramJain', 'pw': 'Vikram@12', 'name': 'Test Star Man', 'c': 'IND', 'r': 'BAT', 'o': 90, 'b': 150})
    check('add player works', add.get('ok'))
else:
    check('add player works (already added in earlier run)', True)

print('[10] reset room')
req('/api/room', {'action': 'reset', 'code': code, 'token': host_token})
room = req('/api/room?code=' + code)['room']
check('back to LOBBY with fresh purse', room['phase'] == 'LOBBY' and room['teams']['MI']['purse'] == 12000 and room['teams']['MI']['squad'] == [])

print()
print('ALL PASSED' if failures == 0 else '%d FAILURES' % failures)
sys.exit(1 if failures else 0)
