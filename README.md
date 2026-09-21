# 🏏 IPL Auction Simulator — Multiplayer

Private IPL auction rooms you play with friends — **no bots**. Host a room,
share the code, everyone bids live from their own phone. Deployed on **Netlify**
with a serverless backend (no external database needed).

## ✨ Features

- **Room codes** — 6-character codes, shareable join link (`/join.html?code=XXXXXX`)
- **Random set-wise auction order** — players are ranked into tiers of 8 and shuffled *within* each set, so Bumrah isn't always first
- **Ratings show/hide** — host can toggle player ratings live mid-auction (nerves of steel mode)
- **Bid timer options** — 10s (default), 7s, 5s, 3s. Host can change it any time during the auction
- **Admin rating editor** — login and change any rating/base price live, add players
- **No bots** — only real friends, real bids
- Real IPL rules: ₹120 Cr / ₹40 Cr purses, squad 16–25, max 8 overseas, official bid ladder, ₹40 L reserved per empty slot
- Unsold players return in a second round (re-shuffled)

## 🚀 Get your public link (Netlify — free)

1. Push this folder to a GitHub repo (or use Netlify Drop)
2. Go to [app.netlify.com](https://app.netlify.com) → **Add new site** → **Import an existing project**
3. Pick your repo → settings are already in `netlify.toml` → **Deploy**
4. Your link: `https://<your-site>.netlify.app`

> Netlify Blobs is enabled automatically — rooms, joins, bids and admin edits are stored serverlessly.

### Quick alternative: Netlify CLI

```bash
npm install
npx netlify-cli deploy --prod
```

(First time it will ask you to log in and create/link a site.)

## 🖥 Play on your own Wi-Fi (no deploy)

```bash
pip install -r requirements.txt 2>/dev/null   # nothing needed — stdlib only
python dev_server.py          # http://localhost:8000
```

Friends on the same Wi-Fi open `http://<your-ip>:8000`.
This dev server exposes the **same API** as the Netlify functions.

## 🎮 How a game runs

1. **Host** → `Host a Room` → name, Mega/Mini, timer, ratings on/off, franchise → get code
2. **Friends** → `Join with Code` → enter code + name → claim a free franchise
3. Host presses **Start Auction** — random set-wise queue begins (top-rated tiers first, shuffled within each set)
4. Bid button shows the exact next amount. Every bid **resets the timer**. Hammer falls when the clock hits zero
5. Unsold names come back in round two. Final squads on the **Results** page

### Host controls (in-room)

| Control | What it does |
|---|---|
| ⏱ Timer select | Switch 10s → 7s → 5s → 3s any time |
| 🙈/👁 Ratings | Hide or show all player ratings live |
| ⏸ Pause | Freezes the clock for everyone |
| ↺ Reset | Clears squads, back to lobby, same room code |

## 🔐 Admin

Open `/admin.html`

- **Username:** `VikramJain`
- **Password:** `Vikram@12`

- Change any player's **rating** or **base price** — applies to every room instantly, even mid-auction
- **Add new players** to the pool (persists across deploys/restarts)

## 📁 Files

```
netlify/functions/   serverless API (room, join, bid, admin + shared store)
data/players.json    193-player pool (ratings, base prices)
data/teams.json      10 franchises
dev_server.py        local emulator of the same API (for Wi-Fi play / testing)
index.html           landing page
create.html          host a room
join.html            join with code
room.html            live auction room (host engine + joiner view)
results.html         final squads
admin.html           admin login + rating editor
test_api.py          end-to-end API tests (run against dev server)
```

## 🧪 Run the tests

```bash
python dev_server.py &     # start local API
python test_api.py         # 30 end-to-end checks
```
