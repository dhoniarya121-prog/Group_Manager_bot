# 🤖 Telegram Group Manager Bot — Version 1.0

Ek all-in-one group moderation bot (Python + Pyrogram + SQLite).

👨‍💻 **Created by [@roaroic0](https://t.me/roaroic0)**
📢 **Developer Channel:** https://t.me/roaroic0

## ✨ Features

1. **Moderation** – warn, mute, ban, kick (auto action jab warn limit poori ho)
2. **Welcome & Verification** – welcome/goodbye message, button ya math CAPTCHA verification, force subscribe, service message cleaning
3. **Admin Control Panel** – `/purge`, `/id`, `/info`, inline `/settings` panel
4. **Group Management** – member stats, auto-delete, custom rules aur commands, admin-only controls

## 🎨 Button Interface (v1.0)

- `/start` – sundar welcome menu: Add to Group, Commands, Features, Setup Guide, Developer Channel (owner ko 👑 Owner Panel bhi)
- `/help` – category buttons: Moderation, Welcome, Automod, Tools, Management, Full list
- `/settings` – live dashboard: har button dabane par status text turant update hota hai (Welcome, Goodbye, Verify, Anti-link, Anti-bot, Flood, Raid, Warn action/limit, Auto-delete, Locks page, Stats, Rules, Help)
- 🔒 **Locks page** – har media type ka lock/unlock button

## 👑 Bot Owner Tools

`.env` me `OWNER_IDS=123456789` (comma se alag kar ke kai IDs) set karein.

| Command | Kaam |
|---|---|
| `/panel` | Owner panel: bot users, groups, groups list, broadcast guide |
| `/stats` (private me) | Global stats (users + groups) |
| `/broadcast` | Kisi message par reply karke likhein, phir Users / Groups / All button chuniye |

Dead users/groups (jinhone bot block kiya ya bot hata diya) broadcast ke dauran automatically list se hat jate hain.

## 🔎 Keyword Filters

`/filter hello | Namaste!` – jab koi message me "hello" likhe to bot reply karta hai. `/filters` se list, `/stopfilter hello` se hatayein.

## 🚀 Advanced Features (v1.0)

| Command | Kaam |
|---|---|
| `/tban <10m\|2h\|1d\|1w> [reason]` | Temporary ban (time ke baad user khud unban) |
| `/lockdown on\|off` | Poora group turant lock/unlock (sirf admins bol sakte hain) |
| `/nightmode on\|off` | Raat ko group auto-lock, subah auto-unlock |
| `/nightmode 23:00 06:00` | Night mode ka time set + ON |
| `/timezone +5:30` | Group ka time zone (default India `+5:30`). Render server UTC par chalta hai, isliye ye zaroori hai |
| `/schedule <10m\|2h\|1d> <text>` | Ek baar baad me message bhejo |
| `/repeat <time> <text>` | Har itne time baad message baar-baar bhejo (min 5 minute) |
| `/schedules` / `/unschedule <id>` | Schedules dekhein / hatayein (max 10 per group) |
| `/antirepeat on\|off` | 60 second me same message 3 baar bheja to delete + warn |
| `/rank` / `/top` | Level, progress bar aur group leaderboard |
| `/levels on\|off` | Level-up announcement on/off |

**Levels:** har message se XP milta hai. Level = √(messages ÷ 10), titles: 🌱 Newbie → 🙂 Member → ⭐ Active → 🔥 Pro → 💎 Elite → 👑 Legend.

**Night mode / Lockdown ke liye** bot ke paas "Restrict members" (aur group permissions badalne ka) admin right chahiye. Unlock par members ko normal permissions (text, media, polls, links preview, invite) wapas milti hain.

**Scheduler** bot ke andar background me har 30 second me check karta hai. Render par restart hone par DB reset ho to schedules bhi chale jate hain (neeche disk wali baat dekhein).

## 🚀 Setup

1. Python 3.9+ install karein.
2. Dependencies install karein:
   ```bash
   pip install -r requirements.txt
   ```
3. `env.example.txt` ko copy karke `.env` naam se save karein aur values bharein:
   ```
   API_ID=12345
   API_HASH=your_api_hash
   BOT_TOKEN=123456:your_bot_token
   OWNER_IDS=123456789
   ```
   `OWNER_IDS` aapki numeric Telegram ID hai (@userinfobot se pata chalti hai).
   - `API_ID` aur `API_HASH`: https://my.telegram.org se
   - `BOT_TOKEN`: @BotFather se
4. Bot chalayein:
   ```bash
   python group_manager_bot.py
   ```
5. Bot ko apne group me add karein aur **admin** banayein (Delete messages, Restrict/Ban users, Invite users permissions ke saath).

## 📋 Commands

### Moderation
| Command | Kaam |
|---|---|
| `/ban` | User ko ban karta hai (reply ya ID/@username) |
| `/unban` | Ban hatata hai |
| `/kick` | Group se nikaalta hai (dobara join kar sakta hai) |
| `/mute [10m/2h/1d]` | Mute karta hai, time na do to permanent |
| `/unmute` | Mute hatata hai |
| `/warn [reason]` | Warn deta hai, limit par auto action |
| `/unwarn` | Ek warn hatata hai |
| `/warns` | Warns dekhein |

### Admin tools
| Command | Kaam |
|---|---|
| `/purge` | Kisi message par reply karke likhein, wahan se aakhir tak sab delete |
| `/id` | User aur chat ID |
| `/info` | User ki poori info (status, warns, messages) |
| `/settings` | Inline button panel |

### Welcome & Verification
| Command | Kaam |
|---|---|
| `/setwelcome <text>` | Welcome message set karein |
| `/setgoodbye <text>` | Leave message set karein |
| `/verify off\|button\|captcha` | Join verification mode |
| `/forcesub @channel [invite_link]` | Force subscribe ON |
| `/forcesub off` | Force subscribe OFF |

**Placeholders:** `{first}` `{mention}` `{id}` `{username}` `{chat}` `{count}`
HTML tags (jaise `<b>bold</b>`) bhi chalte hain.

### Group management
| Command | Kaam |
|---|---|
| `/stats` | Members, aaj/7 din ke joins, leaves, messages, top users |
| `/setrules <text>` | Rules set karein |
| `/rules` | Rules dekhein |
| `/autodelete <seconds>` | Bot ke replies/welcome auto-delete (0 = off) |
| `/warnlimit <1-10>` | Kitne warn par action |
| `/warnaction mute\|kick\|ban` | Limit par kya ho |
| `/addcmd <name> <reply>` | Custom command banayein |
| `/delcmd <name>` | Custom command hatayein |
| `/cmds` | Saare custom commands |

## 🛡 Advanced features (Automod)

Automod admins aur `/approve` kiye gaye users par laagu nahi hota.

| Command | Kaam |
|---|---|
| `/lock <type>` / `/unlock <type\|all>` / `/locks` | Media lock: `sticker photo video document audio voice gif poll contact forward` (message delete hota hai) |
| `/antilink on\|off` | Links (`http`, `t.me`, `site.com`) aur `@username` wale messages delete + warn |
| `/antimention on\|off` | Anti-link ON ho to `@username` wale messages bhi delete + warn (default ON) |
| `/antibot on\|off` | Non-admin dwara add kiye gaye bots auto-remove |
| `/setflood <n>` | 10 second me n se zyada messages par 5 min mute (0 = off) |
| `/antiraid <n>` | 30 second me n se zyada joins par 5 min tak naye members auto-kick (0 = off) |
| `/addblacklist <word>` / `/rmblacklist <word>` / `/blacklist` | Blacklisted word/phrase par message delete + warn |
| `/approve` / `/unapprove` / `/approved` | Trusted users ko automod se exempt karein |

## 🧰 Extra tools

| Command | Kaam |
|---|---|
| `/report` | Message par reply karke admins ko tag karta hai (sab members use kar sakte hain) |
| `/admins` | Admin list |
| `/pin [loud]` / `/unpin` / `/unpinall` | Pin management |
| `/slowmode <10\|30\|60\|300\|900\|3600>` / `/slowmode off` | Group slow mode on/off |
| `/promote` / `/demote` | Admin banana/hatana (sirf group owner) |
| `/setlog <channel_id>` / `/setlog off` | Ban, mute, kick, warn, automod, raid ke logs ek channel me bhejta hai |

`/settings` panel me bhi Anti-link, Anti-bot aur Anti-flood ke buttons hain.

## 🌍 Public bot (koi bhi apne group me add kar sake)

Bot already multi-group hai: har group ki settings, warns, stats alag `chat_id` ke hisaab se save hoti hain. Bas BotFather me ye setup karein:

1. `/mybots` → apna bot → **Bot Settings**
2. **Allow Groups?** → **Turn groups on**
3. **Group Privacy** → **Turn off** (taaki bot saare messages dekh sake; automod, flood, links ke liye zaroori)
4. `/setcommands` me ye list paste karein:

```
start - Bot shuru karein
help - Saare commands
ban - User ko ban karein
unban - Ban hatayein
kick - Group se nikalein
mute - Mute karein
unmute - Unmute karein
warn - Warn dein
unwarn - Warn hatayein
warns - Warns dekhein
purge - Messages delete karein
id - User/Chat ID
info - User info
settings - Settings panel
stats - Group stats
rules - Rules dekhein
report - Admins ko report
admins - Admin list
```

5. `/setdescription` aur `/setabouttext` me bot ka intro likhein (credit: @roaroic0).
6. Bot ke `/start` message me **"➕ Apne Group me add karein"** button hai. Isse koi bhi user bot ko admin rights ke saath apne group me add kar sakta hai.

Bot ko 24x7 chalane ke liye VPS ya hosting par `python group_manager_bot.py` chalayein (jaise `screen`, `pm2` ya systemd ke saath).

## ☁️ Render par deploy

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python group_manager_bot.py`
- **Environment:** `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_IDS`, `PYTHON_VERSION=3.11.9`
- Repo me `render.yaml` bhi hai (Blueprint deploy ke liye)
- Repo ke root me `.python-version` file (3.11.9) honi chahiye, warna Render Python 3.14 use karta hai aur bot crash hota hai. Dashboard me `PYTHON_VERSION=3.11.9` daalna bhi chalta hai.
- **Web Service** par chalane par bot khud ek chhota keep-alive server `PORT` par chalata hai, isliye "No open ports detected" error nahi aata.
- Free Web Service 15 minute idle rehne par so jati hai. [UptimeRobot](https://uptimerobot.com) me apne Render URL ka HTTP monitor 5 minute interval par lagayein.
- Render ka disk restart par khali ho jata hai, isliye `group_manager.db` (settings/warns) reset ho sakta hai. Permanent data ke liye Persistent Disk ya external database lagayein.

## ⚠️ Dhyan rakhein

- Force subscribe ke liye bot us **channel me bhi admin** hona chahiye.
- Private channel ho to `/forcesub <channel_id> <invite_link>` use karein.
- Pending verifications memory me rehti hain, bot restart par unka timer reset ho jata hai.
- Saare moderation aur settings commands sirf group admins chala sakte hain.
- Bot admin par ban/mute/kick nahi kar sakta.
- Data `group_manager.db` file me save hota hai. Isko backup rakhein.

## 🗂 Files

- `group_manager_bot.py` – poora bot
- `requirements.txt` – dependencies
- `env.example.txt` / `.env.example` – `.env` ka template
- `render.yaml` – Render Blueprint
- `.gitignore` – `.env` aur database ko GitHub se bachata hai
- `README.md` – ye file
