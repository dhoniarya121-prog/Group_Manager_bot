# 🤖 Telegram Group Manager Bot — Version 1.0

Ek all-in-one group moderation bot (Python + Pyrogram + SQLite).

👨‍💻 **Created by [@roaroic0](https://t.me/roaroic0)**
📢 **Developer Channel:** https://t.me/roaroic0

## ✨ Features

1. **Moderation** – warn, mute, ban, kick (auto action jab warn limit poori ho)
2. **Welcome & Verification** – welcome/goodbye message, button ya math CAPTCHA verification, force subscribe, service message cleaning
3. **Admin Control Panel** – `/purge`, `/id`, `/info`, inline `/settings` panel
4. **Group Management** – member stats, auto-delete, custom rules aur commands, admin-only controls

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
   ```
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
| `/antilink on\|off` | Links wale messages delete + warn |
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
- `env.example.txt` – `.env` ka template
- `README.md` – ye file
