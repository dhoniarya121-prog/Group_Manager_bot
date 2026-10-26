"""
All-in-one Telegram Group Manager Bot (Pyrogram + SQLite)
Created by @roaroic0
Version 1.0

Features
  1. Moderation  : /warn /unwarn /warns /mute /unmute /ban /unban /kick
  2. Welcome     : welcome/goodbye msgs, button or math-CAPTCHA verification,
                   force subscribe, service message cleaning
  3. Admin tools : /purge /id /info /settings (inline panel)
  4. Management  : /stats, auto-delete, /setrules, custom commands, admin-only controls
"""
import asyncio
import html
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv

# Python 3.10+/3.14 par pyrogram import se pehle ek event loop zaroori hai
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, enums, filters  # noqa: E402
from pyrogram.errors import RPCError
from pyrogram.types import ChatPermissions
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Kb

__version__ = "1.0"

load_dotenv()
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_IDS = {
    int(x) for x in os.environ.get("OWNER_IDS", "").replace(" ", "").split(",")
    if x.lstrip("-").isdigit()
}

app = Client(
    "group_manager",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    parse_mode=enums.ParseMode.HTML,
)

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
db = sqlite3.connect("group_manager.db", check_same_thread=False)
db.executescript(
    """
CREATE TABLE IF NOT EXISTS settings (chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (chat_id, key));
CREATE TABLE IF NOT EXISTS warns (chat_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id));
CREATE TABLE IF NOT EXISTS cmds (chat_id INTEGER, name TEXT, reply TEXT, PRIMARY KEY (chat_id, name));
CREATE TABLE IF NOT EXISTS stats (chat_id INTEGER, day TEXT, joins INTEGER DEFAULT 0, leaves INTEGER DEFAULT 0, messages INTEGER DEFAULT 0, PRIMARY KEY (chat_id, day));
CREATE TABLE IF NOT EXISTS users (chat_id INTEGER, user_id INTEGER, name TEXT, messages INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id));
"""
)
db.commit()

DEFAULTS = {
    "welcome_on": "1",
    "welcome_text": "👋 Welcome {mention} to <b>{chat}</b>!\nTotal members: {count}",
    "goodbye_on": "0",
    "goodbye_text": "😢 {first} ne group chhod diya.",
    "verify": "off",  # off | button | captcha
    "verify_timeout": "120",
    "forcesub": "",
    "forcesub_link": "",
    "rules": "",
    "autodelete": "0",  # seconds, 0 = off
    "cleanup": "300",  # group ka har message itne seconds baad delete (0 = off)
    "admin_secs": "30",  # admin msgs + bot command-replies itne sec baad delete (0 = cleanup wala time)
    "hide": "1",  # 1 = non-admin members ke messages turant delete (sirf admin/owner ke msgs + bot ka welcome dikhe)
    "clean_service": "0",
    "warn_limit": "3",
    "warn_action": "mute",  # mute | kick | ban
    "antilink": "0",
    "antirepeat": "0",
    "levels": "1",
    "night_on": "0",
    "night_start": "23:00",
    "night_end": "06:00",
    "night_state": "0",
    "tz": "+05:30",
    "link_mentions": "1",  # anti-link me @username bhi block
    "antibot": "0",
    "flood_limit": "0",  # msgs per 10s, 0 = off
    "raid_limit": "0",  # joins per 30s, 0 = off
    "locks": "",
    "logchan": "",
}


def cfg(chat_id, key):
    row = db.execute(
        "SELECT value FROM settings WHERE chat_id=? AND key=?", (chat_id, key)
    ).fetchone()
    return row[0] if row else DEFAULTS[key]


def setcfg(chat_id, key, value):
    db.execute(
        "INSERT OR REPLACE INTO settings VALUES (?,?,?)", (chat_id, key, str(value))
    )
    db.commit()


def get_warns(chat_id, user_id):
    row = db.execute(
        "SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)
    ).fetchone()
    return row[0] if row else 0


def set_warns(chat_id, user_id, n):
    n = max(0, n)
    db.execute("INSERT OR REPLACE INTO warns VALUES (?,?,?)", (chat_id, user_id, n))
    db.commit()
    return n


def bump(chat_id, col):
    day = time.strftime("%Y-%m-%d")
    db.execute("INSERT OR IGNORE INTO stats(chat_id, day) VALUES (?,?)", (chat_id, day))
    db.execute(f"UPDATE stats SET {col}={col}+1 WHERE chat_id=? AND day=?", (chat_id, day))
    db.commit()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
ADMIN = (enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR)
RESERVED = {
    "start", "help", "ban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
    "warns", "purge", "id", "info", "settings", "stats", "rules", "setrules",
    "setwelcome", "setgoodbye", "verify", "forcesub", "autodelete", "cleanup", "hide", "adminclean", "warnlimit",
    "warnaction", "addcmd", "delcmd", "cmds",
    "approve", "unapprove", "approved", "lock", "unlock", "locks", "antilink",
    "antibot", "setflood", "antiraid", "addblacklist", "rmblacklist", "blacklist",
    "setlog", "report", "admins", "slowmode", "pin", "unpin", "unpinall",
    "promote", "demote", "antimention", "menu", "mod", "tban", "lockdown", "nightmode", "timezone", "schedule", "repeat",
    "schedules", "unschedule", "rank", "top", "levels", "antirepeat", "panel", "broadcast", "filter", "filters", "stopfilter",
}

_tasks = set()
_me_id = None
pending = {}  # (chat_id, user_id) -> {"ans": str, "msg": int}
admin_cache = {}  # chat_id -> (timestamp, set(ids))
joined_cache = {}  # (channel, user_id) -> timestamp


async def my_id(client):
    global _me_id
    if _me_id is None:
        _me_id = (await client.get_me()).id
    return _me_id


def mention(u):
    return f'<a href="tg://user?id={u.id}">{html.escape(u.first_name or "User")}</a>'


def err(e):
    return html.escape(str(e))


async def _delete_later(msg, secs):
    await asyncio.sleep(secs)
    try:
        await msg.delete()
    except Exception:
        pass


def autodel(chat_id, msg, secs=None):
    secs = int(cfg(chat_id, "autodelete")) if secs is None else secs
    if secs > 0:
        t = asyncio.create_task(_delete_later(msg, secs))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)


# Bot ka har message (welcome sahit) group me CLEANUP seconds baad delete ho jaye
_orig_send_message = app.send_message


async def _send_and_clean(chat_id, *args, **kwargs):
    m = await _orig_send_message(chat_id, *args, **kwargs)
    try:
        if m and m.chat and m.chat.type in (
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ):
            secs = int(cfg(m.chat.id, "cleanup"))
            if secs > 0:
                autodel(m.chat.id, m, secs)
    except Exception:
        pass
    return m


app.send_message = _send_and_clean


async def say(message, text, **kw):
    m = await message.reply_text(text, **kw)
    cid = message.chat.id
    secs = int(cfg(cid, "autodelete")) or int(cfg(cid, "admin_secs"))
    autodel(cid, m, secs if secs > 0 else None)
    return m


async def is_admin(client, chat_id, user_id):
    try:
        m = await client.get_chat_member(chat_id, user_id)
        return m.status in ADMIN
    except RPCError:
        return False


async def admin_ids(client, chat_id):
    ts, ids = admin_cache.get(chat_id, (0, set()))
    if time.time() - ts < 60:
        return ids
    ids = set()
    try:
        async for m in client.get_chat_members(
            chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS
        ):
            ids.add(m.user.id)
    except RPCError:
        pass
    admin_cache[chat_id] = (time.time(), ids)
    return ids


def admin_only(func):
    @wraps(func)
    async def wrapper(client, message):
        anon = message.sender_chat and message.sender_chat.id == message.chat.id
        if not anon:
            if not message.from_user or not await is_admin(
                client, message.chat.id, message.from_user.id
            ):
                return await say(message, "⛔ Ye command sirf admins ke liye hai.")
        return await func(client, message)

    return wrapper


def parse_time(s):
    m = re.fullmatch(r"(\d+)([smhdw])", s.lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{{"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[unit]: n})


async def get_target(client, message):
    args = message.command[1:]
    r = message.reply_to_message
    if r and r.from_user:
        return r.from_user, args
    if not args:
        return None, []
    try:
        ref = int(args[0]) if args[0].lstrip("-").isdigit() else args[0]
        return await client.get_users(ref), args[1:]
    except Exception:
        return None, args


async def prep(client, message):
    user, rest = await get_target(client, message)
    if not user:
        await say(message, "⚠️ Kisi user ko reply karein ya ID/@username dein.")
        return None
    if user.id == await my_id(client):
        await say(message, "😅 Main khud par ye action nahi kar sakta.")
        return None
    if await is_admin(client, message.chat.id, user.id):
        await say(message, "⚠️ Admin par ye action nahi ho sakta.")
        return None
    return user, rest


async def unrestrict(client, chat_id, user_id):
    chat = await client.get_chat(chat_id)
    perms = chat.permissions or ChatPermissions(can_send_messages=True)
    await client.restrict_chat_member(chat_id, user_id, perms)


async def kick(client, chat_id, user_id):
    await client.ban_chat_member(chat_id, user_id)
    await client.unban_chat_member(chat_id, user_id)


async def punish(client, chat_id, user_id, action):
    """Returns None on success, error text on failure."""
    try:
        if action == "ban":
            await client.ban_chat_member(chat_id, user_id)
        elif action == "kick":
            await kick(client, chat_id, user_id)
        else:
            await client.restrict_chat_member(
                chat_id, user_id, ChatPermissions(),
                until_date=datetime.now() + timedelta(days=1),
            )
    except RPCError as e:
        return err(e)
    return None


def fmt(text, user, chat, count=""):
    name = html.escape(user.first_name or "User")
    rep = {
        "{first}": name,
        "{mention}": f'<a href="tg://user?id={user.id}">{name}</a>',
        "{id}": str(user.id),
        "{username}": f"@{user.username}" if user.username else name,
        "{chat}": html.escape(chat.title or ""),
        "{count}": str(count),
    }
    for k, v in rep.items():
        text = text.replace(k, v)
    return text


def text_arg(message):
    parts = message.text.split(None, 1)
    if len(parts) > 1:
        return parts[1]
    r = message.reply_to_message
    if r:
        return r.text or r.caption
    return None


# --------------------------------------------------------------------------- #
# /start /help
# --------------------------------------------------------------------------- #
HELP = """<b>🤖 Group Manager Bot</b> · v1.0

<b>Moderation</b>
/ban /unban /kick /mute [10m|2h|1d] /unmute
/warn /unwarn /warns

<b>Admin tools</b>
/purge (reply karke) · /id · /info · /settings

<b>Welcome &amp; Verification</b>
/setwelcome &lt;text&gt; · /setgoodbye &lt;text&gt;
/verify off|button|captcha
/forcesub @channel [invite_link] | off
Placeholders: {first} {mention} {id} {username} {chat} {count}

<b>Group management</b>
/stats · /setrules &lt;text&gt; · /rules
/autodelete &lt;seconds&gt; (0 = off)
/warnlimit &lt;n&gt; · /warnaction mute|kick|ban
/addcmd &lt;name&gt; &lt;reply&gt; · /delcmd &lt;name&gt; · /cmds

<b>Automod (advanced)</b>
/lock &lt;type&gt; · /unlock &lt;type|all&gt; · /locks
/antilink on|off · /antimention on|off · /antibot on|off
/setflood &lt;n&gt; · /antiraid &lt;n&gt;
/addblacklist &lt;word&gt; · /rmblacklist &lt;word&gt; · /blacklist
/approve · /unapprove · /approved

<b>Extra tools</b>
/report · /admins · /pin · /unpin · /unpinall
/slowmode &lt;sec|off&gt; · /promote · /demote (owner)
/setlog &lt;channel_id&gt; | off

<b>Keyword filters</b>
/filter word | reply · /filters · /stopfilter word

<b>Bot owner</b>
/panel · /broadcast · /stats (private)

Bot ko group me <b>admin</b> banayein (delete, restrict, ban, invite permissions ke saath).

👨‍💻 Created by @roaroic0"""


# --------------------------------------------------------------------------- #
# Moderation: ban / unban / kick / mute / unmute
# --------------------------------------------------------------------------- #
@app.on_message(filters.command("ban") & filters.group)
@admin_only
async def ban_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, rest = r
    try:
        await client.ban_chat_member(message.chat.id, user.id)
    except RPCError as e:
        return await say(message, f"❌ Ban fail: <code>{err(e)}</code>")
    reason = f"\nKaran: {html.escape(' '.join(rest))}" if rest else ""
    await log_action(client, message.chat, f"🔨 <b>Ban</b>\nUser: {mention(user)} (<code>{user.id}</code>)\nBy: {actor(message)}{reason}")
    await say(message, f"🔨 {mention(user)} ko <b>ban</b> kar diya gaya.{reason}")


@app.on_message(filters.command("unban") & filters.group)
@admin_only
async def unban_cmd(client, message):
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    try:
        await client.unban_chat_member(message.chat.id, user.id)
    except RPCError as e:
        return await say(message, f"❌ Unban fail: <code>{err(e)}</code>")
    await say(message, f"✅ {mention(user)} ko <b>unban</b> kar diya gaya.")


@app.on_message(filters.command("kick") & filters.group)
@admin_only
async def kick_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, _ = r
    try:
        await kick(client, message.chat.id, user.id)
    except RPCError as e:
        return await say(message, f"❌ Kick fail: <code>{err(e)}</code>")
    await log_action(client, message.chat, f"👢 <b>Kick</b>\nUser: {mention(user)} (<code>{user.id}</code>)\nBy: {actor(message)}")
    await say(message, f"👢 {mention(user)} ko group se <b>kick</b> kar diya gaya.")


@app.on_message(filters.command("mute") & filters.group)
@admin_only
async def mute_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, rest = r
    delta = parse_time(rest[0]) if rest else None
    dur_label = "permanent"
    if delta:
        dur_label = rest[0]
        rest = rest[1:]
    try:
        if delta:
            await client.restrict_chat_member(
                message.chat.id, user.id, ChatPermissions(),
                until_date=datetime.now() + delta,
            )
        else:
            await client.restrict_chat_member(message.chat.id, user.id, ChatPermissions())
    except RPCError as e:
        return await say(message, f"❌ Mute fail: <code>{err(e)}</code>")
    dur = f" ({dur_label})"
    reason = f"\nKaran: {html.escape(' '.join(rest))}" if rest else ""
    await log_action(client, message.chat, f"🔇 <b>Mute</b>{dur}\nUser: {mention(user)} (<code>{user.id}</code>)\nBy: {actor(message)}{reason}")
    await say(message, f"🔇 {mention(user)} ko <b>mute</b> kar diya gaya{dur}.{reason}")


@app.on_message(filters.command("unmute") & filters.group)
@admin_only
async def unmute_cmd(client, message):
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    try:
        await unrestrict(client, message.chat.id, user.id)
    except RPCError as e:
        return await say(message, f"❌ Unmute fail: <code>{err(e)}</code>")
    await say(message, f"🔊 {mention(user)} ko <b>unmute</b> kar diya gaya.")


# --------------------------------------------------------------------------- #
# Warn system
# --------------------------------------------------------------------------- #
@app.on_message(filters.command("warn") & filters.group)
@admin_only
async def warn_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, rest = r
    cid = message.chat.id
    count = set_warns(cid, user.id, get_warns(cid, user.id) + 1)
    limit = int(cfg(cid, "warn_limit"))
    reason = f"\nKaran: {html.escape(' '.join(rest))}" if rest else ""
    await log_action(client, message.chat, f"⚠️ <b>Warn</b> ({count}/{limit})\nUser: {mention(user)} (<code>{user.id}</code>)\nBy: {actor(message)}{reason}")
    if count >= limit:
        action = cfg(cid, "warn_action")
        problem = await punish(client, cid, user.id, action)
        set_warns(cid, user.id, 0)
        if problem:
            return await say(message, f"❌ Action fail: <code>{problem}</code>")
        return await say(
            message,
            f"🚫 {mention(user)} ke {count}/{limit} warns ho gaye → <b>{action}</b>.{reason}",
        )
    kb = Kb([[Btn("🗑 Warn hatao", callback_data=f"unwarn:{cid}:{user.id}")]])
    await say(message, f"⚠️ {mention(user)} ko warn mila ({count}/{limit}).{reason}", reply_markup=kb)


@app.on_message(filters.command("unwarn") & filters.group)
@admin_only
async def unwarn_cmd(client, message):
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    n = set_warns(message.chat.id, user.id, get_warns(message.chat.id, user.id) - 1)
    await say(message, f"✅ {mention(user)} ka ek warn hata diya gaya. Ab: {n}")


@app.on_message(filters.command("warns") & filters.group)
async def warns_cmd(client, message):
    user, _ = await get_target(client, message)
    user = user or message.from_user
    if not user:
        return
    n = get_warns(message.chat.id, user.id)
    await say(message, f"📋 {mention(user)} ke warns: {n}/{cfg(message.chat.id, 'warn_limit')}")


@app.on_callback_query(filters.regex(r"^unwarn:"))
async def unwarn_cb(client, cb):
    _, chat_id, user_id = cb.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)
    if not await is_admin(client, chat_id, cb.from_user.id):
        return await cb.answer("Sirf admins!", show_alert=True)
    n = set_warns(chat_id, user_id, get_warns(chat_id, user_id) - 1)
    await cb.message.edit_text(f"✅ Warn hata diya gaya (ab {n}) by {mention(cb.from_user)}.")


# --------------------------------------------------------------------------- #
# Admin tools: purge, id, info
# --------------------------------------------------------------------------- #
@app.on_message(filters.command("purge") & filters.group)
@admin_only
async def purge_cmd(client, message):
    if not message.reply_to_message:
        return await say(message, "⚠️ Jis message se delete shuru karna hai, us par reply karke /purge likhein.")
    ids = list(range(message.reply_to_message.id, message.id + 1))
    deleted = 0
    for i in range(0, len(ids), 100):
        try:
            await client.delete_messages(message.chat.id, ids[i : i + 100])
            deleted += len(ids[i : i + 100])
        except RPCError:
            pass
    m = await client.send_message(message.chat.id, f"🧹 Purge complete ({deleted} messages).")
    autodel(message.chat.id, m, 5)


@app.on_message(filters.command("id"))
async def id_cmd(client, message):
    lines = []
    r = message.reply_to_message
    if r and r.from_user:
        lines.append(f"👤 User ID: <code>{r.from_user.id}</code>")
    elif message.from_user:
        lines.append(f"👤 Aapki ID: <code>{message.from_user.id}</code>")
    lines.append(f"💬 Chat ID: <code>{message.chat.id}</code>")
    await say(message, "\n".join(lines))


@app.on_message(filters.command("info") & filters.group)
async def info_cmd(client, message):
    user, _ = await get_target(client, message)
    user = user or message.from_user
    if not user:
        return
    cid = message.chat.id
    try:
        status = (await client.get_chat_member(cid, user.id)).status.name.title()
    except RPCError:
        status = "Unknown"
    row = db.execute(
        "SELECT messages FROM users WHERE chat_id=? AND user_id=?", (cid, user.id)
    ).fetchone()
    text = (
        f"ℹ️ <b>User Info</b>\n"
        f"Naam: {mention(user)}\n"
        f"ID: <code>{user.id}</code>\n"
        f"Username: {('@' + user.username) if user.username else '—'}\n"
        f"Status: {status}\n"
        f"Warns: {get_warns(cid, user.id)}/{cfg(cid, 'warn_limit')}\n"
        f"Messages (is group me): {row[0] if row else 0}"
    )
    await say(message, text)


# --------------------------------------------------------------------------- #
# Settings panel + text settings
# --------------------------------------------------------------------------- #
AD_CYCLE = ["0", "30", "60", "300"]
VERIFY_CYCLE = ["off", "button", "captcha"]
ACTION_CYCLE = ["mute", "kick", "ban"]


@app.on_message(filters.command("setwelcome") & filters.group)
@admin_only
async def setwelcome_cmd(client, message):
    t = text_arg(message)
    if not t:
        return await say(message, "Usage: /setwelcome &lt;text&gt;\nPlaceholders: {first} {mention} {id} {username} {chat} {count}")
    setcfg(message.chat.id, "welcome_text", t)
    setcfg(message.chat.id, "welcome_on", "1")
    await say(message, "✅ Welcome message set ho gaya.")


@app.on_message(filters.command("setgoodbye") & filters.group)
@admin_only
async def setgoodbye_cmd(client, message):
    t = text_arg(message)
    if not t:
        return await say(message, "Usage: /setgoodbye &lt;text&gt;")
    setcfg(message.chat.id, "goodbye_text", t)
    setcfg(message.chat.id, "goodbye_on", "1")
    await say(message, "✅ Goodbye message set ho gaya.")


@app.on_message(filters.command("setrules") & filters.group)
@admin_only
async def setrules_cmd(client, message):
    t = text_arg(message)
    if not t:
        return await say(message, "Usage: /setrules &lt;text&gt;")
    setcfg(message.chat.id, "rules", t)
    await say(message, "✅ Rules save ho gaye. Dekhne ke liye /rules")


@app.on_message(filters.command("rules") & filters.group)
async def rules_cmd(client, message):
    r = cfg(message.chat.id, "rules")
    await say(message, f"📜 <b>Group Rules</b>\n\n{r}" if r else "Abhi koi rules set nahi hain.")


@app.on_callback_query(filters.regex(r"^rules:"))
async def rules_cb(client, cb):
    cid = int(cb.data.split(":")[1])
    r = cfg(cid, "rules")
    m = await client.send_message(cid, f"📜 <b>Group Rules</b>\n\n{r}" if r else "Koi rules set nahi hain.")
    autodel(cid, m, 60)
    await cb.answer()


@app.on_message(filters.command("verify") & filters.group)
@admin_only
async def verify_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg not in VERIFY_CYCLE:
        return await say(message, "Usage: /verify off|button|captcha")
    setcfg(message.chat.id, "verify", arg)
    await say(message, f"🛡 Verification mode: <b>{arg}</b>")


@app.on_message(filters.command("forcesub") & filters.group)
@admin_only
async def forcesub_cmd(client, message):
    args = message.command[1:]
    if not args:
        return await say(message, "Usage: /forcesub @channel [invite_link] ya /forcesub off\n(Bot us channel me admin hona chahiye.)")
    if args[0].lower() == "off":
        setcfg(message.chat.id, "forcesub", "")
        setcfg(message.chat.id, "forcesub_link", "")
        return await say(message, "📢 Force subscribe band kar diya.")
    ref = int(args[0]) if args[0].lstrip("-").isdigit() else args[0]
    try:
        ch = await client.get_chat(ref)
        await client.get_chat_member(ch.id, await my_id(client))
    except RPCError as e:
        return await say(message, f"❌ Channel check fail (bot ko channel me admin banayein): <code>{err(e)}</code>")
    link = args[1] if len(args) > 1 else (f"https://t.me/{ch.username}" if ch.username else "")
    if not link:
        return await say(message, "⚠️ Private channel hai - invite link bhi dein: /forcesub &lt;id&gt; &lt;invite_link&gt;")
    setcfg(message.chat.id, "forcesub", ch.id)
    setcfg(message.chat.id, "forcesub_link", link)
    await say(message, f"📢 Force subscribe ON: <b>{html.escape(ch.title or str(ch.id))}</b>")


@app.on_message(filters.command("autodelete") & filters.group)
@admin_only
async def autodelete_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await say(message, "Usage: /autodelete &lt;seconds&gt; (0 = off)\nBot ke replies aur welcome messages itne seconds baad delete honge.")
    setcfg(message.chat.id, "autodelete", int(message.command[1]))
    await say(message, f"⏱ Auto-delete: {message.command[1]}s")


@app.on_message(filters.command("warnlimit") & filters.group)
@admin_only
async def warnlimit_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit() or not 1 <= int(message.command[1]) <= 10:
        return await say(message, "Usage: /warnlimit &lt;1-10&gt;")
    setcfg(message.chat.id, "warn_limit", int(message.command[1]))
    await say(message, f"⚖️ Warn limit: {message.command[1]}")


@app.on_message(filters.command("warnaction") & filters.group)
@admin_only
async def warnaction_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg not in ACTION_CYCLE:
        return await say(message, "Usage: /warnaction mute|kick|ban")
    setcfg(message.chat.id, "warn_action", arg)
    await say(message, f"⚖️ Warn limit par action: <b>{arg}</b>")


# --------------------------------------------------------------------------- #
# Custom commands
# --------------------------------------------------------------------------- #
@app.on_message(filters.command("addcmd") & filters.group)
@admin_only
async def addcmd_cmd(client, message):
    parts = message.text.split(None, 2)
    if len(parts) < 2:
        return await say(message, "Usage: /addcmd &lt;name&gt; &lt;reply text&gt; (ya kisi message par reply karke)")
    name = parts[1].lower().lstrip("/")
    reply = parts[2] if len(parts) > 2 else (
        (message.reply_to_message.text or message.reply_to_message.caption)
        if message.reply_to_message else None
    )
    if not re.fullmatch(r"[a-z0-9_]{1,32}", name) or name in RESERVED:
        return await say(message, "⚠️ Naam invalid hai ya reserved hai (a-z, 0-9, _ only).")
    if not reply:
        return await say(message, "⚠️ Reply text dein.")
    db.execute("INSERT OR REPLACE INTO cmds VALUES (?,?,?)", (message.chat.id, name, reply))
    db.commit()
    await say(message, f"✅ Custom command <code>/{name}</code> add ho gaya.")


@app.on_message(filters.command("delcmd") & filters.group)
@admin_only
async def delcmd_cmd(client, message):
    if len(message.command) < 2:
        return await say(message, "Usage: /delcmd &lt;name&gt;")
    name = message.command[1].lower().lstrip("/")
    cur = db.execute("DELETE FROM cmds WHERE chat_id=? AND name=?", (message.chat.id, name))
    db.commit()
    await say(message, "🗑 Delete ho gaya." if cur.rowcount else "Aisa koi command nahi mila.")


@app.on_message(filters.command("cmds") & filters.group)
async def cmds_cmd(client, message):
    rows = db.execute("SELECT name FROM cmds WHERE chat_id=? ORDER BY name", (message.chat.id,)).fetchall()
    await say(message, "📌 <b>Custom commands</b>\n" + "\n".join(f"/{r[0]}" for r in rows) if rows else "Koi custom command nahi hai.")


@app.on_message(filters.group & filters.text, group=3)
async def custom_cmd_handler(client, message):
    text = message.text or ""
    if not text.startswith("/"):
        return
    name = text[1:].split()[0].split("@")[0].lower()
    row = db.execute("SELECT reply FROM cmds WHERE chat_id=? AND name=?", (message.chat.id, name)).fetchone()
    if row:
        await say(message, row[0])


# --------------------------------------------------------------------------- #
# Privacy + auto cleanup
#   * Admin/owner ke ilawa kisi member ka message group me nahi rukta
#     (turant delete; commands 3 sec baad taaki bot reply kar sake).
#     Agar /setlog channel set hai to delete se pehle message wahan copy ho jata hai.
#   * Baaki sab (admin msgs, bot ka welcome/replies) CLEANUP seconds (default 5 min) baad delete.
# --------------------------------------------------------------------------- #
async def is_staff(client, message):
    if message.sender_chat:  # anonymous admin
        return message.sender_chat.id == message.chat.id
    u = message.from_user
    if not u:
        return False
    if u.id in OWNER_IDS:
        return True
    ids = await admin_ids(client, message.chat.id)
    if u.id in ids:
        return True
    if not ids:  # admin list fetch fail hui -> galti se admins ke msg na udein
        return await is_admin(client, message.chat.id, u.id)
    return False


@app.on_message(filters.group & ~filters.service, group=-1)
async def privacy_cleaner(client, message):
    cid = message.chat.id
    secs = int(cfg(cid, "cleanup"))
    if cfg(cid, "hide") == "1" and not await is_staff(client, message):
        ch = cfg(cid, "logchan")
        if ch:
            try:
                await message.copy(int(ch))
            except Exception:
                pass
        if (message.text or message.caption or "").startswith("/"):
            autodel(cid, message, 3)
        else:
            try:
                await message.delete()
            except RPCError:
                pass
        return
    # admin/owner ka message: commands turant, normal msg admin_secs baad
    asecs = int(cfg(cid, "admin_secs")) if cfg(cid, "hide") == "1" else secs
    if (message.text or message.caption or "").startswith("/"):
        asecs = min(asecs, 2) if asecs > 0 else 2
    if asecs > 0:
        autodel(cid, message, asecs)
    elif secs > 0:
        autodel(cid, message, secs)


@app.on_message(filters.command("adminclean") & filters.group)
@admin_only
async def adminclean_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await say(message, "Usage: /adminclean &lt;seconds&gt; (default 30)\nAdmin ke messages aur bot ke command-replies itne sec baad delete.")
    setcfg(message.chat.id, "admin_secs", int(message.command[1]))
    await say(message, f"🕶 Admin privacy: {message.command[1]}s")


@app.on_message(filters.command("cleanup") & filters.group)
@admin_only
async def cleanup_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await say(message, "Usage: /cleanup &lt;seconds&gt; (0 = off, default 300)\nGroup ke saare messages itne seconds baad delete honge.")
    setcfg(message.chat.id, "cleanup", int(message.command[1]))
    await say(message, f"🧹 Cleanup: {message.command[1]}s")


@app.on_message(filters.command("hide") & filters.group)
@admin_only
async def hide_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /hide on|off\nON: admin/owner ke ilawa kisi ka message group me nahi dikhega.")
    setcfg(message.chat.id, "hide", v)
    await say(message, f"🙈 Hide mode: {'ON' if v == '1' else 'OFF'}")


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
@app.on_message(filters.group & ~filters.service, group=4)
async def count_messages(client, message):
    u = message.from_user
    if not u or u.is_bot:
        return
    bump(message.chat.id, "messages")
    track_chat(message.chat)
    db.execute("INSERT OR IGNORE INTO users(chat_id, user_id, name) VALUES (?,?,?)", (message.chat.id, u.id, u.first_name))
    db.execute(
        "UPDATE users SET messages=messages+1, name=? WHERE chat_id=? AND user_id=?",
        (u.first_name, message.chat.id, u.id),
    )
    db.commit()


# --------------------------------------------------------------------------- #
# Join / leave / verification
# --------------------------------------------------------------------------- #
async def send_welcome(client, chat, user):
    cid = chat.id
    if cfg(cid, "welcome_on") != "1":
        return
    try:
        count = await client.get_chat_members_count(cid)
    except RPCError:
        count = ""
    kb = Kb([[Btn("📜 Rules", callback_data=f"rules:{cid}")]]) if cfg(cid, "rules") else None
    m = await client.send_message(cid, fmt(cfg(cid, "welcome_text"), user, chat, count), reply_markup=kb)
    autodel(cid, m)


async def verify_timeout(client, chat_id, user_id, secs):
    await asyncio.sleep(secs)
    p = pending.pop((chat_id, user_id), None)
    if p:
        try:
            await kick(client, chat_id, user_id)
            await client.delete_messages(chat_id, p["msg"])
        except RPCError:
            pass


async def start_verification(client, chat, user, mode):
    cid = chat.id
    try:
        await client.restrict_chat_member(cid, user.id, ChatPermissions())
    except RPCError:
        return await send_welcome(client, chat, user)  # bot lacks rights -> skip verification
    secs = int(cfg(cid, "verify_timeout"))
    if mode == "button":
        ans = "ok"
        text = f"🛡 {mention(user)}, group me bolne ke liye neeche button dabayein.\n⏳ {secs} second ka time hai."
        kb = Kb([[Btn("✅ Main insaan hoon", callback_data=f"cap:{cid}:{user.id}:ok")]])
    else:
        a, b = random.randint(1, 9), random.randint(1, 9)
        ans = str(a + b)
        opts = {a + b}
        while len(opts) < 4:
            opts.add(random.randint(2, 18))
        opts = random.sample(sorted(opts), 4)
        text = f"🛡 {mention(user)}, verify karein: <b>{a} + {b} = ?</b>\n⏳ {secs} second ka time hai."
        kb = Kb([[Btn(str(o), callback_data=f"cap:{cid}:{user.id}:{o}") for o in opts]])
    m = await client.send_message(cid, text, reply_markup=kb)
    pending[(cid, user.id)] = {"ans": ans, "msg": m.id}
    t = asyncio.create_task(verify_timeout(client, cid, user.id, secs))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@app.on_message(filters.new_chat_members & filters.group)
async def on_join(client, message):
    chat = message.chat
    me = await my_id(client)
    for u in message.new_chat_members:
        if u.id == me:
            if await is_admin(client, chat.id, me):
                note = "✅ Mere paas admin rights hain. /settings se setup karein, /help me saare commands hain."
            else:
                note = ("⚠️ Mujhe <b>admin</b> banayein (Delete messages, Restrict/Ban users, Invite users) "
                        "tabhi main kaam karunga. Phir /settings se setup karein.")
            track_chat(chat)
            await message.reply_text(f"👋 Thanks for adding me!\n{note}")
            continue
        if (chat.id, u.id) in kicked_set:
            kicked_set.discard((chat.id, u.id))
            continue
        if u.is_bot:
            continue
        bump(chat.id, "joins")
        mode = cfg(chat.id, "verify")
        if mode != "off":
            await start_verification(client, chat, u, mode)
        else:
            await send_welcome(client, chat, u)


@app.on_callback_query(filters.regex(r"^cap:"))
async def captcha_cb(client, cb):
    _, chat_id, user_id, choice = cb.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)
    if cb.from_user.id != user_id:
        return await cb.answer("Ye button aapke liye nahi hai.", show_alert=True)
    p = pending.get((chat_id, user_id))
    if not p:
        return await cb.answer("Verification expire ho chuka hai.", show_alert=True)
    pending.pop((chat_id, user_id), None)
    if choice == p["ans"]:
        try:
            await unrestrict(client, chat_id, user_id)
        except RPCError:
            pass
        await cb.answer("✅ Verified!")
        chat = cb.message.chat
        await cb.message.delete()
        await send_welcome(client, chat, cb.from_user)
    else:
        await cb.answer("❌ Galat jawab. Dobara join karke try karein.", show_alert=True)
        try:
            await kick(client, chat_id, user_id)
            await cb.message.delete()
        except RPCError:
            pass


@app.on_message(filters.left_chat_member & filters.group)
async def on_leave(client, message):
    u = message.left_chat_member
    if not u or u.is_bot:
        return
    bump(message.chat.id, "leaves")
    if cfg(message.chat.id, "goodbye_on") == "1":
        m = await client.send_message(message.chat.id, fmt(cfg(message.chat.id, "goodbye_text"), u, message.chat))
        autodel(message.chat.id, m)


@app.on_message(filters.service & filters.group, group=5)
async def clean_service(client, message):
    if cfg(message.chat.id, "clean_service") == "1":
        try:
            await message.delete()
        except RPCError:
            pass


# --------------------------------------------------------------------------- #
# Force subscribe
# --------------------------------------------------------------------------- #
async def has_joined(client, channel, user_id):
    key = (channel, user_id)
    if time.time() - joined_cache.get(key, 0) < 60:
        return True
    try:
        m = await client.get_chat_member(int(channel), user_id)
    except RPCError as e:
        # UserNotParticipant => not joined; anything else => don't block users
        return "USER_NOT_PARTICIPANT" not in str(e).upper()
    if m.status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED):
        return False
    if m.status == enums.ChatMemberStatus.RESTRICTED and not getattr(m, "is_member", True):
        return False
    joined_cache[key] = time.time()
    return True


@app.on_message(filters.group & ~filters.service, group=-1)
async def force_sub(client, message):
    cid = message.chat.id
    ch = cfg(cid, "forcesub")
    u = message.from_user
    if not ch or not u or u.is_bot:
        return
    if u.id in await admin_ids(client, cid):
        return
    if await has_joined(client, ch, u.id):
        return
    try:
        await message.delete()
    except RPCError:
        pass
    kb = Kb(
        [
            [Btn("📢 Channel join karein", url=cfg(cid, "forcesub_link"))],
            [Btn("✅ Maine join kar liya", callback_data=f"fs:{cid}:{u.id}")],
        ]
    )
    m = await client.send_message(
        cid, f"⚠️ {mention(u)}, group me message karne ke liye pehle hamara channel join karein.", reply_markup=kb
    )
    autodel(cid, m, 30)
    message.stop_propagation()


@app.on_callback_query(filters.regex(r"^fs:"))
async def forcesub_cb(client, cb):
    _, chat_id, user_id = cb.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)
    if cb.from_user.id != user_id:
        return await cb.answer("Ye button aapke liye nahi hai.", show_alert=True)
    if await has_joined(client, cfg(chat_id, "forcesub"), user_id):
        await cb.answer("✅ Thanks! Ab aap message kar sakte hain.", show_alert=True)
        await cb.message.delete()
    else:
        await cb.answer("❌ Aapne abhi tak channel join nahi kiya.", show_alert=True)


# --------------------------------------------------------------------------- #
# ADVANCED: automod (locks, anti-link, blacklist, anti-flood), anti-raid,
# anti-bot, approved users, log channel, report, pin, slowmode, promote...
# --------------------------------------------------------------------------- #
from pyrogram.types import ChatPrivileges  # noqa: E402

db.executescript(
    """
CREATE TABLE IF NOT EXISTS approved (chat_id INTEGER, user_id INTEGER, PRIMARY KEY (chat_id, user_id));
CREATE TABLE IF NOT EXISTS blacklist (chat_id INTEGER, word TEXT, PRIMARY KEY (chat_id, word));
"""
)
db.commit()

FLOOD_CYCLE = ["0", "5", "8", "12"]
URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)\S+", re.I)
DOMAIN_RE = re.compile(r"\b[\w-]+\.(?:com|in|net|org|io|me|xyz|info|link|co|app|ly|gg|site|online|shop|top|club|vip)\b", re.I)
MENTION_RE = re.compile(r"(?<![\w])@[A-Za-z][A-Za-z0-9_]{4,31}\b")
flood = {}  # (chat_id, user_id) -> [timestamps]
join_times = {}  # chat_id -> [timestamps]
raid_until = {}  # chat_id -> timestamp
kicked_set = set()  # (chat_id, user_id) kicked by join guard

LOCKS = {
    "sticker": lambda m: bool(m.sticker),
    "photo": lambda m: bool(m.photo),
    "video": lambda m: bool(m.video or m.video_note),
    "document": lambda m: bool(m.document),
    "audio": lambda m: bool(m.audio),
    "voice": lambda m: bool(m.voice),
    "gif": lambda m: bool(m.animation),
    "poll": lambda m: bool(m.poll),
    "contact": lambda m: bool(m.contact),
    "forward": lambda m: bool(
        getattr(m, "forward_date", None) or getattr(m, "forward_origin", None)
    ),
}


def actor(message):
    return mention(message.from_user) if message.from_user else "Anonymous admin"


async def log_action(client, chat, text):
    ch = cfg(chat.id, "logchan")
    if not ch:
        return
    try:
        await client.send_message(
            int(ch), f"📂 <b>{html.escape(chat.title or str(chat.id))}</b>\n{text}"
        )
    except Exception:
        pass


def is_approved(chat_id, user_id):
    return (
        db.execute(
            "SELECT 1 FROM approved WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()
        is not None
    )


def onoff_arg(message):
    a = message.command[1].lower() if len(message.command) > 1 else ""
    return {"on": "1", "off": "0", "yes": "1", "no": "0"}.get(a)


def has_link(message, mentions=True):
    """URL, t.me link, bare domain, hidden link ya (mentions=True par) @username."""
    text = message.text or message.caption or ""
    if URL_RE.search(text) or DOMAIN_RE.search(text):
        return True
    if mentions and MENTION_RE.search(text):
        return True
    for ent in message.entities or message.caption_entities or []:
        if ent.type in (enums.MessageEntityType.URL, enums.MessageEntityType.TEXT_LINK):
            return True
        if mentions and ent.type == enums.MessageEntityType.MENTION:
            return True
    return False


async def violation(client, message, reason, warn=True):
    """Delete the message, optionally warn (and punish at limit), then stop other handlers."""
    cid = message.chat.id
    user = message.from_user
    try:
        await message.delete()
    except RPCError:
        pass
    await log_action(
        client, message.chat,
        f"🛡 <b>Automod</b>: {reason}\nUser: {mention(user)} (<code>{user.id}</code>)",
    )
    if warn:
        count = set_warns(cid, user.id, get_warns(cid, user.id) + 1)
        limit = int(cfg(cid, "warn_limit"))
        if count >= limit:
            action = cfg(cid, "warn_action")
            problem = await punish(client, cid, user.id, action)
            set_warns(cid, user.id, 0)
            text = (
                f"🚫 {mention(user)}: {reason} ({count}/{limit} warns) → <b>{action}</b>"
                if not problem
                else f"❌ Action fail: <code>{problem}</code>"
            )
        else:
            text = f"⚠️ {mention(user)}, {reason}. Warn {count}/{limit}."
    else:
        text = f"⚠️ {mention(user)}, {reason}."
    m = await client.send_message(cid, text)
    autodel(cid, m, 10)
    message.stop_propagation()


@app.on_message(filters.group & ~filters.service, group=-2)
async def automod(client, message):
    u = message.from_user
    if not u or u.is_bot:
        return
    cid = message.chat.id
    if u.id in await admin_ids(client, cid) or is_approved(cid, u.id):
        return

    # 1) Locks (media types / forwards) -> delete only
    for name in [x for x in cfg(cid, "locks").split(",") if x]:
        fn = LOCKS.get(name)
        if fn and fn(message):
            return await violation(client, message, f"<b>{name}</b> yahan allowed nahi hai", warn=False)

    # 2) Anti-link -> delete + warn
    if cfg(cid, "antilink") == "1" and has_link(message, cfg(cid, "link_mentions") == "1"):
        return await violation(client, message, "links aur @username allowed nahi hain")

    # 3) Blacklist words -> delete + warn
    text = (message.text or message.caption or "").lower()
    if text:
        for (w,) in db.execute("SELECT word FROM blacklist WHERE chat_id=?", (cid,)).fetchall():
            if w in text:
                return await violation(client, message, "blacklisted word use kiya")

    # 3b) Anti-repeat -> same text 3 times in 60s: delete + warn
    if cfg(cid, "antirepeat") == "1" and len(text) >= 4:
        now_t = time.time()
        rkey = (cid, u.id)
        hist = [(t, x) for t, x in repeat_hist.get(rkey, []) if now_t - t < 60]
        hist.append((now_t, text))
        repeat_hist[rkey] = hist
        if sum(1 for _, x in hist if x == text) >= 3:
            repeat_hist[rkey] = []
            return await violation(client, message, "same message baar-baar bhejna allowed nahi hai")

    # 4) Anti-flood -> mute 5 minutes
    limit = int(cfg(cid, "flood_limit"))
    if limit:
        now = time.time()
        key = (cid, u.id)
        lst = [t for t in flood.get(key, []) if now - t < 10]
        lst.append(now)
        flood[key] = lst
        if len(lst) > limit:
            flood[key] = []
            try:
                await client.restrict_chat_member(
                    cid, u.id, ChatPermissions(),
                    until_date=datetime.now() + timedelta(minutes=5),
                )
            except RPCError:
                return
            m = await client.send_message(cid, f"🌊 {mention(u)} flood karne par 5 minute ke liye mute.")
            autodel(cid, m, 10)
            await log_action(client, message.chat, f"🌊 <b>Flood mute</b>: {mention(u)} (<code>{u.id}</code>)")
            message.stop_propagation()


# ----- Join guard: anti-bot + anti-raid ------------------------------------ #
@app.on_message(filters.new_chat_members & filters.group, group=-3)
async def join_guard(client, message):
    cid = message.chat.id
    me = await my_id(client)
    admins = await admin_ids(client, cid)
    now = time.time()
    for u in message.new_chat_members:
        if u.id == me:
            continue
        if u.is_bot:
            if cfg(cid, "antibot") != "1":
                continue
            adder = message.from_user
            if adder and adder.id != u.id and adder.id in admins:
                continue  # admin ne khud bot add kiya
            try:
                await kick(client, cid, u.id)
                kicked_set.add((cid, u.id))
                m = await client.send_message(cid, f"🤖 Bot {mention(u)} hata diya gaya (anti-bot ON).")
                autodel(cid, m, 10)
                await log_action(client, message.chat, f"🤖 <b>Anti-bot</b>: {mention(u)} removed")
            except RPCError:
                pass
            continue

        limit = int(cfg(cid, "raid_limit"))
        if not limit:
            continue
        lst = [t for t in join_times.get(cid, []) if now - t < 30]
        lst.append(now)
        join_times[cid] = lst
        if len(lst) > limit and raid_until.get(cid, 0) < now:
            raid_until[cid] = now + 300
            m = await client.send_message(cid, "🚨 <b>Raid detected!</b> Agle 5 minute naye members auto-kick honge.")
            autodel(cid, m, 30)
            await log_action(client, message.chat, "🚨 <b>Raid mode ON</b> (5 min)")
        if raid_until.get(cid, 0) > now:
            try:
                await kick(client, cid, u.id)
                kicked_set.add((cid, u.id))
            except RPCError:
                pass


# ----- Approved users ------------------------------------------------------ #
@app.on_message(filters.command("approve") & filters.group)
@admin_only
async def approve_cmd(client, message):
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    db.execute("INSERT OR IGNORE INTO approved VALUES (?,?)", (message.chat.id, user.id))
    db.commit()
    await say(message, f"✅ {mention(user)} approve ho gaya (automod se exempt).")


@app.on_message(filters.command("unapprove") & filters.group)
@admin_only
async def unapprove_cmd(client, message):
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    db.execute("DELETE FROM approved WHERE chat_id=? AND user_id=?", (message.chat.id, user.id))
    db.commit()
    await say(message, f"🗑 {mention(user)} ka approval hata diya.")


@app.on_message(filters.command("approved") & filters.group)
@admin_only
async def approved_cmd(client, message):
    rows = db.execute(
        "SELECT a.user_id, u.name FROM approved a LEFT JOIN users u "
        "ON u.chat_id=a.chat_id AND u.user_id=a.user_id WHERE a.chat_id=?",
        (message.chat.id,),
    ).fetchall()
    if not rows:
        return await say(message, "Koi approved user nahi hai.")
    await say(message, "✅ <b>Approved users</b>\n" + "\n".join(
        f'• <a href="tg://user?id={i}">{html.escape(n or str(i))}</a>' for i, n in rows))


# ----- Locks --------------------------------------------------------------- #
@app.on_message(filters.command("lock") & filters.group)
@admin_only
async def lock_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg not in LOCKS:
        return await say(message, "Usage: /lock &lt;type&gt;\nTypes: " + ", ".join(sorted(LOCKS)))
    cid = message.chat.id
    cur = {x for x in cfg(cid, "locks").split(",") if x}
    cur.add(arg)
    setcfg(cid, "locks", ",".join(sorted(cur)))
    await say(message, f"🔒 <b>{arg}</b> lock ho gaya.")


@app.on_message(filters.command("unlock") & filters.group)
@admin_only
async def unlock_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    cid = message.chat.id
    if arg == "all":
        setcfg(cid, "locks", "")
        return await say(message, "🔓 Saare locks hata diye.")
    if arg not in LOCKS:
        return await say(message, "Usage: /unlock &lt;type|all&gt;")
    cur = {x for x in cfg(cid, "locks").split(",") if x}
    cur.discard(arg)
    setcfg(cid, "locks", ",".join(sorted(cur)))
    await say(message, f"🔓 <b>{arg}</b> unlock ho gaya.")


@app.on_message(filters.command("locks") & filters.group)
async def locks_cmd(client, message):
    cur = {x for x in cfg(message.chat.id, "locks").split(",") if x}
    lines = [f"{'🔒' if n in cur else '🔓'} {n}" for n in sorted(LOCKS)]
    await say(message, "<b>Locks</b>\n" + "\n".join(lines))


# ----- Toggles / limits ---------------------------------------------------- #
@app.on_message(filters.command("antilink") & filters.group)
@admin_only
async def antilink_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /antilink on|off")
    setcfg(message.chat.id, "antilink", v)
    await say(message, f"🔗 Anti-link: <b>{'ON' if v == '1' else 'OFF'}</b>")


@app.on_message(filters.command("antimention") & filters.group)
@admin_only
async def antimention_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /antimention on|off\n(ON par Anti-link ke saath @username wale messages bhi delete + warn honge.)")
    setcfg(message.chat.id, "link_mentions", v)
    await say(message, f"@ Mention-link: <b>{'ON' if v == '1' else 'OFF'}</b>")


@app.on_message(filters.command("antibot") & filters.group)
@admin_only
async def antibot_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /antibot on|off\n(Non-admin dwara add kiye gaye bots hata diye jayenge.)")
    setcfg(message.chat.id, "antibot", v)
    await say(message, f"🤖 Anti-bot: <b>{'ON' if v == '1' else 'OFF'}</b>")


@app.on_message(filters.command("setflood") & filters.group)
@admin_only
async def setflood_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit() or int(message.command[1]) > 30:
        return await say(message, "Usage: /setflood &lt;0-30&gt;\nUser 10 second me itne se zyada messages bheje to 5 min mute. 0 = off.")
    setcfg(message.chat.id, "flood_limit", int(message.command[1]))
    await say(message, f"🌊 Anti-flood: {message.command[1]} msg/10s")


@app.on_message(filters.command("antiraid") & filters.group)
@admin_only
async def antiraid_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit() or int(message.command[1]) > 100:
        return await say(message, "Usage: /antiraid &lt;0-100&gt;\n30 second me itne se zyada joins hone par 5 min ke liye naye members auto-kick. 0 = off.")
    setcfg(message.chat.id, "raid_limit", int(message.command[1]))
    await say(message, f"🚨 Anti-raid limit: {message.command[1]} joins/30s")


# ----- Blacklist ----------------------------------------------------------- #
@app.on_message(filters.command("addblacklist") & filters.group)
@admin_only
async def addblacklist_cmd(client, message):
    parts = message.text.split(None, 1)
    if len(parts) < 2 or len(parts[1]) > 50:
        return await say(message, "Usage: /addblacklist &lt;word ya phrase&gt;")
    db.execute("INSERT OR IGNORE INTO blacklist VALUES (?,?)", (message.chat.id, parts[1].strip().lower()))
    db.commit()
    await say(message, "✅ Blacklist me add ho gaya.")


@app.on_message(filters.command("rmblacklist") & filters.group)
@admin_only
async def rmblacklist_cmd(client, message):
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await say(message, "Usage: /rmblacklist &lt;word&gt;")
    cur = db.execute("DELETE FROM blacklist WHERE chat_id=? AND word=?", (message.chat.id, parts[1].strip().lower()))
    db.commit()
    await say(message, "🗑 Hata diya." if cur.rowcount else "Ye word blacklist me nahi mila.")


@app.on_message(filters.command("blacklist") & filters.group)
@admin_only
async def blacklist_cmd(client, message):
    rows = db.execute("SELECT word FROM blacklist WHERE chat_id=? ORDER BY word", (message.chat.id,)).fetchall()
    await say(message, "🚫 <b>Blacklist</b>\n" + "\n".join(f"• {html.escape(r[0])}" for r in rows) if rows else "Blacklist khali hai.")


# ----- Log channel --------------------------------------------------------- #
@app.on_message(filters.command("setlog") & filters.group)
@admin_only
async def setlog_cmd(client, message):
    if len(message.command) < 2:
        return await say(message, "Usage: /setlog &lt;channel_id|@channel&gt; ya /setlog off\n(Bot us channel me admin hona chahiye.)")
    if message.command[1].lower() == "off":
        setcfg(message.chat.id, "logchan", "")
        return await say(message, "📝 Log channel band.")
    a = message.command[1]
    try:
        ch = await client.get_chat(int(a) if a.lstrip("-").isdigit() else a)
        await client.send_message(ch.id, f"✅ Log channel connected: <b>{html.escape(message.chat.title or '')}</b>")
    except Exception as e:
        return await say(message, f"❌ Channel me message nahi bhej paya (bot admin hai?): <code>{err(e)}</code>")
    setcfg(message.chat.id, "logchan", ch.id)
    await say(message, "📝 Log channel set ho gaya. Ban/mute/kick/warn/automod ke logs wahan aayenge.")


# ----- Report / admins ----------------------------------------------------- #
@app.on_message(filters.command("report") & filters.group)
async def report_cmd(client, message):
    r = message.reply_to_message
    if not r:
        return await say(message, "⚠️ Jis message ko report karna hai us par reply karke /report likhein.")
    cid = message.chat.id
    me = await my_id(client)
    ids = [i for i in await admin_ids(client, cid) if i != me][:10]
    tags = "".join(f'<a href="tg://user?id={i}">\u200b</a>' for i in ids)
    try:
        link = r.link
    except Exception:
        link = None
    text = f"🚨 <b>Report</b> by {actor(message)}{tags}"
    if link:
        text += f'\n<a href="{link}">Message dekhein</a>'
    rkb = mc_kb(r.from_user.id, r.id, compact=True) if r.from_user and not r.from_user.is_bot else None
    await client.send_message(cid, text, reply_to_message_id=r.id, reply_markup=rkb)
    await log_action(client, message.chat, f"🚨 <b>Report</b> by {actor(message)}" + (f"\n{link}" if link else ""))


@app.on_message(filters.command("admins") & filters.group)
async def admins_cmd(client, message):
    lines = []
    try:
        async for m in client.get_chat_members(
            message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS
        ):
            if m.user.is_bot:
                continue
            icon = "👑" if m.status == enums.ChatMemberStatus.OWNER else "👮"
            lines.append(f"{icon} {mention(m.user)}")
    except RPCError as e:
        return await say(message, f"❌ <code>{err(e)}</code>")
    await say(message, "<b>Group Admins</b>\n" + ("\n".join(lines) or "—"))


# ----- Pin / promote -------------------------------------------------------- # #
@app.on_message(filters.command("slowmode") & filters.group)
@admin_only
async def slowmode_cmd(client, message):
    valid = {0, 10, 30, 60, 300, 900, 3600}
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg == "off":
        arg = "0"
    if not arg.isdigit() or int(arg) not in valid:
        return await say(message, "Usage: /slowmode &lt;10|30|60|300|900|3600&gt; (seconds) ya /slowmode off")
    n = int(arg)
    try:
        await client.set_slow_mode(message.chat.id, n or None)
    except RPCError as e:
        return await say(message, f"❌ <code>{err(e)}</code>")
    await say(message, f"🐢 Slowmode: {n}s" if n else "🐢 Slowmode <b>OFF</b> kar diya gaya.")


@app.on_message(filters.command("pin") & filters.group)
@admin_only
async def pin_cmd(client, message):
    r = message.reply_to_message
    if not r:
        return await say(message, "⚠️ Jis message ko pin karna hai us par reply karein. (Notification ke liye: /pin loud)")
    loud = len(message.command) > 1 and message.command[1].lower() == "loud"
    try:
        await client.pin_chat_message(message.chat.id, r.id, disable_notification=not loud)
    except RPCError as e:
        await say(message, f"❌ <code>{err(e)}</code>")


@app.on_message(filters.command("unpin") & filters.group)
@admin_only
async def unpin_cmd(client, message):
    r = message.reply_to_message
    if not r:
        return await say(message, "⚠️ Jis message ko unpin karna hai us par reply karein.")
    try:
        await client.unpin_chat_message(message.chat.id, r.id)
    except RPCError as e:
        await say(message, f"❌ <code>{err(e)}</code>")


@app.on_message(filters.command("unpinall") & filters.group)
@admin_only
async def unpinall_cmd(client, message):
    try:
        await client.unpin_all_chat_messages(message.chat.id)
        await say(message, "📌 Saare pinned messages hata diye.")
    except RPCError as e:
        await say(message, f"❌ <code>{err(e)}</code>")


async def _owner_only(client, message):
    if not message.from_user:
        return False
    try:
        m = await client.get_chat_member(message.chat.id, message.from_user.id)
    except RPCError:
        return False
    if m.status != enums.ChatMemberStatus.OWNER:
        await say(message, "⛔ Ye command sirf group owner chala sakta hai.")
        return False
    return True


@app.on_message(filters.command("promote") & filters.group)
async def promote_cmd(client, message):
    if not await _owner_only(client, message):
        return
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    try:
        await client.promote_chat_member(
            message.chat.id, user.id,
            ChatPrivileges(
                can_manage_chat=True, can_delete_messages=True,
                can_restrict_members=True, can_invite_users=True, can_pin_messages=True,
            ),
        )
    except RPCError as e:
        return await say(message, f"❌ <code>{err(e)}</code>")
    admin_cache.pop(message.chat.id, None)
    await say(message, f"👮 {mention(user)} ab admin hai.")
    await log_action(client, message.chat, f"👮 <b>Promote</b>: {mention(user)} by {actor(message)}")


@app.on_message(filters.command("demote") & filters.group)
async def demote_cmd(client, message):
    if not await _owner_only(client, message):
        return
    user, _ = await get_target(client, message)
    if not user:
        return await say(message, "⚠️ Reply karein ya ID/@username dein.")
    try:
        await client.promote_chat_member(message.chat.id, user.id, ChatPrivileges(can_manage_chat=False))
    except RPCError as e:
        return await say(message, f"❌ <code>{err(e)}</code>")
    admin_cache.pop(message.chat.id, None)
    await say(message, f"⬇️ {mention(user)} ab admin nahi raha.")
    await log_action(client, message.chat, f"⬇️ <b>Demote</b>: {mention(user)} by {actor(message)}")


# --------------------------------------------------------------------------- #
# UI v2: beautiful start/help menus, settings dashboard, locks page,
# owner panel, broadcast, global stats, keyword filters
# --------------------------------------------------------------------------- #
from pyrogram.errors import FloodWait  # noqa: E402

DEV_URL = "https://t.me/roaroic0"
LINE = "━━━━━━━━━━━━━━━━━━"
RAID_CYCLE = ["0", "5", "10", "20"]

db.executescript(
    """
CREATE TABLE IF NOT EXISTS bot_users (user_id INTEGER PRIMARY KEY, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS bot_chats (chat_id INTEGER PRIMARY KEY, title TEXT, type TEXT, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS kwfilters (chat_id INTEGER, keyword TEXT, reply TEXT, PRIMARY KEY (chat_id, keyword));
"""
)
db.commit()

seen_chats = set()
seen_users = set()


def is_owner(user_id):
    return user_id in OWNER_IDS


def track_chat(chat):
    if chat.id in seen_chats:
        return
    seen_chats.add(chat.id)
    db.execute(
        "INSERT OR REPLACE INTO bot_chats(chat_id, title, type, first_seen) VALUES "
        "(?,?,?,COALESCE((SELECT first_seen FROM bot_chats WHERE chat_id=?),?))",
        (chat.id, chat.title or "", chat.type.name, chat.id, int(time.time())),
    )
    db.commit()


def track_user(user_id):
    if user_id in seen_users:
        return
    seen_users.add(user_id)
    db.execute(
        "INSERT OR IGNORE INTO bot_users(user_id, first_seen) VALUES (?,?)",
        (user_id, int(time.time())),
    )
    db.commit()


async def ui_edit(cb, text, kb=None):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except RPCError:
        pass  # "message not modified" etc.


def add_url_for(username):
    return (
        f"https://t.me/{username}?startgroup=true"
        "&admin=delete_messages+restrict_members+invite_users+pin_messages+promote_members+manage_chat"
    )


# ----- Start / Help pages -------------------------------------------------- #
async def start_content(client, user, private=True):
    me = await client.get_me()
    add_url = add_url_for(me.username)
    name = mention(user) if user else "dost"
    if private:
        text = (
            f"✨ <b>Group Manager Bot</b> ✨\n{LINE}\n"
            f"Namaste {name}! 👋\n"
            "Main aapke group ko <b>safe, clean aur organized</b> rakhne wala all-in-one manager hoon.\n\n"
            "🛡 Moderation • 👋 Welcome &amp; CAPTCHA\n"
            "🔗 Anti-link / Flood • 🚨 Anti-raid\n"
            "📢 Force Subscribe • 🔒 Locks • 🧹 Automod\n"
            "📊 Stats • ⚙️ Button Settings Panel\n\n"
            "➕ Mujhe apne group me add karein aur <b>admin</b> banayein.\n"
            f"{LINE}\n"
            f"👨‍💻 Created by @roaroic0 • v{__version__}"
        )
        rows = [
            [Btn("➕ Apne Group me add karein", url=add_url)],
            [Btn("📚 Commands", callback_data="help:home"), Btn("✨ Features", callback_data="info:features")],
            [Btn("🚀 Setup Guide", callback_data="info:setup"), Btn("📢 Developer Channel", url=DEV_URL)],
        ]
        if user and is_owner(user.id):
            rows.append([Btn("👑 Owner Panel", callback_data="own:home")])
    else:
        text = (
            f"✨ <b>Group Manager Bot</b> • v{__version__}\n{LINE}\n"
            "Main active hoon! 🟢\n"
            "🎛 Control Center: /menu   ⚙️ Settings: /settings\n📚 Help: /help\n"
            f"{LINE}\n👨‍💻 @roaroic0"
        )
        rows = [
            [Btn("📚 Commands", callback_data="help:home"), Btn("➕ Add to group", url=add_url)],
            [Btn("📢 Developer Channel", url=DEV_URL)],
        ]
    return text, Kb(rows)


@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    private = message.chat.type == enums.ChatType.PRIVATE
    if private and message.from_user:
        track_user(message.from_user.id)
    text, kb = await start_content(client, message.from_user, private)
    m = await message.reply_text(text, reply_markup=kb)
    if not private:
        autodel(message.chat.id, m, 120)


HELP_PAGES = {
    "mod": (
        f"🛡 <b>Moderation</b>\n{LINE}\n"
        "🔨 /ban – ban karein\n"
        "♻️ /unban – ban hatayein\n"
        "👢 /kick – group se nikalein\n"
        "🔇 /mute [10m|2h|1d] – mute karein\n"
        "🔊 /unmute – unmute karein\n"
        "⚠️ /warn [reason] – warn dein\n"
        "✅ /unwarn – ek warn hatayein\n"
        "📋 /warns – warns dekhein\n"
        "🧹 /purge – reply karke wahan se delete\n\n"
        "<i>Reply karein ya ID/@username dein. Warn limit par auto action: /warnlimit, /warnaction</i>"
    ),
    "welcome": (
        f"👋 <b>Welcome &amp; Verification</b>\n{LINE}\n"
        "✏️ /setwelcome &lt;text&gt; • /setgoodbye &lt;text&gt;\n"
        "🛡 /verify off|button|captcha\n"
        "📢 /forcesub @channel [link] | off\n"
        "📜 /setrules &lt;text&gt; • /rules\n\n"
        "<b>Placeholders:</b> {first} {mention} {id} {username} {chat} {count}"
    ),
    "auto": (
        f"🧹 <b>Automod</b>\n{LINE}\n"
        "🔒 /lock &lt;type&gt; • /unlock &lt;type|all&gt; • /locks\n"
        "🔗 /antilink on|off • @ /antimention on|off\n🤖 /antibot on|off\n"
        "🌊 /setflood &lt;n&gt; • 🚨 /antiraid &lt;n&gt;\n"
        "🚫 /addblacklist • /rmblacklist • /blacklist\n"
        "✅ /approve • /unapprove • /approved\n"
        "🔎 /filter word | reply • /filters • /stopfilter word"
    ),
    "tools": (
        f"🧰 <b>Tools</b>\n{LINE}\n"
        "🆔 /id • ℹ️ /info • 👮 /admins • 🚨 /report\n"
        "📌 /pin [loud] • /unpin • /unpinall\n"
        "🐢 /slowmode &lt;sec|off&gt;\n"
        "⬆️ /promote • ⬇️ /demote (group owner)\n"
        "📝 /setlog &lt;channel_id&gt; | off\n"
        "💬 /addcmd • /delcmd • /cmds"
    ),
    "manage": (
        f"📊 <b>Management</b>\n{LINE}\n"
        "⚙️ /settings – button panel (sab kuch yahin se)\n"
        "📊 /stats – group statistics\n"
        "⏱ /autodelete &lt;sec&gt;\n"
        "⚖️ /warnlimit &lt;n&gt; • /warnaction mute|kick|ban\n\n"
        "<b>Owner (bot owner):</b> /panel • /broadcast • /stats (private)"
    ),
}


def help_home_text():
    return (
        f"📚 <b>Help Menu</b>\n{LINE}\n"
        "Neeche se category chuniye 👇"
    )


def help_home_kb():
    return Kb(
        [
            [Btn("🛡 Moderation", callback_data="help:mod"), Btn("👋 Welcome", callback_data="help:welcome")],
            [Btn("🧹 Automod", callback_data="help:auto"), Btn("🧰 Tools", callback_data="help:tools")],
            [Btn("📊 Management", callback_data="help:manage"), Btn("📜 Full list", callback_data="help:all")],
            [Btn("🏠 Home", callback_data="home:start")],
        ]
    )


@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    m = await message.reply_text(help_home_text(), reply_markup=help_home_kb())
    if message.chat.type != enums.ChatType.PRIVATE:
        autodel(message.chat.id, m, 180)


INFO_PAGES = {
    "features": (
        f"✨ <b>Features</b>\n{LINE}\n"
        "🛡 Ban / Mute / Kick / Warn system\n"
        "👋 Welcome &amp; goodbye with placeholders\n"
        "🔐 Button ya Math-CAPTCHA verification\n"
        "📢 Force subscribe (channel join zaroori)\n"
        "🧹 Automod: links, blacklist, flood, locks\n"
        "🚨 Anti-raid &amp; Anti-bot\n"
        "🔎 Keyword filters &amp; custom commands\n"
        "📊 Group stats &amp; top active users\n"
        "📝 Log channel &amp; report system\n"
        "⚙️ Poora button settings panel"
    ),
    "setup": (
        f"🚀 <b>Setup Guide</b>\n{LINE}\n"
        "1️⃣ \"➕ Apne Group me add karein\" dabayein\n"
        "2️⃣ Bot ko <b>admin</b> banayein (Delete, Ban/Restrict, Invite)\n"
        "3️⃣ Group me /settings kholkar features ON karein\n"
        "4️⃣ /setwelcome aur /setrules se customize karein\n"
        "5️⃣ Madad ke liye /help"
    ),
}


@app.on_callback_query(filters.regex(r"^(help|home|info):"))
async def nav_cb(client, cb):
    kind, page = cb.data.split(":", 1)
    private = cb.message.chat.type == enums.ChatType.PRIVATE
    back = Kb([[Btn("⬅️ Back", callback_data="help:home" if kind == "help" else "home:start"),
                Btn("🏠 Home", callback_data="home:start")]])
    if kind == "home":
        text, kb = await start_content(client, cb.from_user, private)
    elif kind == "help":
        if page == "home":
            text, kb = help_home_text(), help_home_kb()
        elif page == "all":
            text, kb = HELP, Kb([[Btn("⬅️ Back", callback_data="help:home"), Btn("🏠 Home", callback_data="home:start")]])
        else:
            text, kb = HELP_PAGES.get(page, help_home_text()), Kb(
                [[Btn("⬅️ Back", callback_data="help:home"), Btn("🏠 Home", callback_data="home:start")]]
            )
    else:
        text, kb = INFO_PAGES.get(page, "—"), back
    await ui_edit(cb, text, kb)
    await cb.answer()


# ----- Settings dashboard -------------------------------------------------- #
def _yn(cid, key):
    return "✅" if cfg(cid, key) == "1" else "❌"


def panel_text(chat):
    cid = chat.id
    ad = cfg(cid, "autodelete")
    fl = cfg(cid, "flood_limit")
    rl = cfg(cid, "raid_limit")
    locks = [x for x in cfg(cid, "locks").split(",") if x]
    return (
        f"⚙️ <b>Group Settings</b>\n<i>{html.escape(chat.title or '')}</i>\n{LINE}\n"
        f"👋 Welcome: {_yn(cid, 'welcome_on')}   🚪 Goodbye: {_yn(cid, 'goodbye_on')}\n"
        f"🛡 Verify: <b>{cfg(cid, 'verify')}</b>   🧹 Service clean: {_yn(cid, 'clean_service')}\n"
        f"🔗 Anti-link: {_yn(cid, 'antilink')}   🤖 Anti-bot: {_yn(cid, 'antibot')}\n"
        f"@ Mention = link: {_yn(cid, 'link_mentions')}\n"
        f"🌊 Flood: <b>{'off' if fl == '0' else fl + ' msg/10s'}</b>   🚨 Raid: <b>{'off' if rl == '0' else rl + ' join/30s'}</b>\n"
        f"🔁 Anti-repeat: {_yn(cid, 'antirepeat')}   🏆 Levels: {_yn(cid, 'levels')}\n"
        f"🌙 Night mode: <b>{night_label(cid)}</b>\n"
        f"⚖️ Warns: <b>{cfg(cid, 'warn_limit')}</b> → <b>{cfg(cid, 'warn_action')}</b>\n"
        f"⏱ Auto-delete: <b>{'off' if ad == '0' else ad + 's'}</b>\n"
        f"📢 Force sub: <b>{'on' if cfg(cid, 'forcesub') else 'off'}</b>   📝 Log: <b>{'on' if cfg(cid, 'logchan') else 'off'}</b>\n"
        f"🔒 Locks: <b>{', '.join(locks) if locks else 'none'}</b>\n"
        f"📜 Rules: <b>{'set' if cfg(cid, 'rules') else 'not set'}</b>\n"
        f"{LINE}\nNeeche ke buttons se settings badlein 👇"
    )


def panel(cid):
    def onoff(k):
        return "✅" if cfg(cid, k) == "1" else "❌"

    fl = cfg(cid, "flood_limit")
    rl = cfg(cid, "raid_limit")
    ad = cfg(cid, "autodelete")
    return Kb(
        [
            [
                Btn(f"👋 Welcome {onoff('welcome_on')}", callback_data="set:welcome_on"),
                Btn(f"🚪 Goodbye {onoff('goodbye_on')}", callback_data="set:goodbye_on"),
            ],
            [
                Btn(f"🛡 Verify: {cfg(cid, 'verify')}", callback_data="set:verify"),
                Btn(f"🧹 Clean {onoff('clean_service')}", callback_data="set:clean_service"),
            ],
            [
                Btn(f"🔗 Anti-link {onoff('antilink')}", callback_data="set:antilink"),
                Btn(f"🤖 Anti-bot {onoff('antibot')}", callback_data="set:antibot"),
            ],
            [Btn(f"@ Mention = link {onoff('link_mentions')}", callback_data="set:link_mentions")],
            [
                Btn(f"🌊 Flood: {'off' if fl == '0' else fl}", callback_data="set:flood"),
                Btn(f"🚨 Raid: {'off' if rl == '0' else rl}", callback_data="set:raid"),
            ],
            [
                Btn(f"🔁 Repeat {onoff('antirepeat')}", callback_data="set:antirepeat"),
                Btn(f"🏆 Levels {onoff('levels')}", callback_data="set:levels"),
            ],
            [Btn(f"🌙 Night mode: {'ON' if cfg(cid, 'night_on') == '1' else 'OFF'}", callback_data="set:night")],
            [
                Btn(f"⚖️ Action: {cfg(cid, 'warn_action')}", callback_data="set:warn_action"),
                Btn(f"⏱ Del: {'off' if ad == '0' else ad + 's'}", callback_data="set:autodelete"),
            ],
            [
                Btn("➖", callback_data="set:warn_dn"),
                Btn(f"Warn limit: {cfg(cid, 'warn_limit')}", callback_data="set:noop"),
                Btn("➕", callback_data="set:warn_up"),
            ],
            [Btn("✏️ Welcome style", callback_data="set:wstyle"), Btn("🎛 Control Center", callback_data="cc:home")],
            [Btn("🔒 Locks", callback_data="set:locks"), Btn("📊 Stats", callback_data="set:stats")],
            [Btn("📜 Rules", callback_data="set:rules"), Btn("📚 Help", callback_data="set:help")],
            [Btn("✖️ Close", callback_data="set:close")],
        ]
    )


def locks_text():
    return f"🔒 <b>Locks</b>\n{LINE}\nButton dabakar lock/unlock karein.\n🔒 = locked (message delete hoga)\n🔓 = allowed"


def locks_kb(cid):
    cur = {x for x in cfg(cid, "locks").split(",") if x}
    rows, row = [], []
    for n in sorted(LOCKS):
        row.append(Btn(f"{'🔒' if n in cur else '🔓'} {n}", callback_data=f"lk:{n}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("⬅️ Back", callback_data="lk:back")])
    return Kb(rows)


@app.on_message(filters.command("settings") & filters.group)
@admin_only
async def settings_cmd(client, message):
    await message.reply_text(panel_text(message.chat), reply_markup=panel(message.chat.id))


@app.on_callback_query(filters.regex(r"^set:"))
async def settings_cb(client, cb):
    chat = cb.message.chat
    cid = chat.id
    key = cb.data.split(":", 1)[1]
    if not await is_admin(client, cid, cb.from_user.id):
        return await cb.answer("⛔ Sirf admins ke liye!", show_alert=True)
    if key == "close":
        try:
            await cb.message.delete()
        except RPCError:
            pass
        return
    if key == "noop":
        return await cb.answer()
    if key == "stats":
        m = await client.send_message(cid, await build_stats(client, cid))
        autodel(cid, m, 60)
        return await cb.answer()
    if key == "rules":
        r = cfg(cid, "rules")
        m = await client.send_message(cid, f"📜 <b>Group Rules</b>\n\n{r}" if r else "📜 Abhi koi rules set nahi hain. /setrules se set karein.")
        autodel(cid, m, 60)
        return await cb.answer()
    if key == "help":
        m = await client.send_message(cid, help_home_text(), reply_markup=help_home_kb())
        autodel(cid, m, 180)
        return await cb.answer()
    if key == "wstyle":
        await ui_edit(cb, wstyle_text(), wstyle_kb())
        return await cb.answer()
    if key == "locks":
        await ui_edit(cb, locks_text(), locks_kb(cid))
        return await cb.answer()

    if key in ("welcome_on", "goodbye_on", "clean_service", "antilink", "antibot", "link_mentions", "antirepeat", "levels"):
        setcfg(cid, key, "0" if cfg(cid, key) == "1" else "1")
    elif key == "night":
        new = "0" if cfg(cid, "night_on") == "1" else "1"
        setcfg(cid, "night_on", new)
        if new == "0" and cfg(cid, "night_state") == "1":
            await night_unlock(client, cid)
    elif key == "flood":
        cur = cfg(cid, "flood_limit")
        cur = cur if cur in FLOOD_CYCLE else "0"
        setcfg(cid, "flood_limit", FLOOD_CYCLE[(FLOOD_CYCLE.index(cur) + 1) % len(FLOOD_CYCLE)])
    elif key == "raid":
        cur = cfg(cid, "raid_limit")
        cur = cur if cur in RAID_CYCLE else "0"
        setcfg(cid, "raid_limit", RAID_CYCLE[(RAID_CYCLE.index(cur) + 1) % len(RAID_CYCLE)])
    elif key == "verify":
        cur = cfg(cid, "verify")
        setcfg(cid, "verify", VERIFY_CYCLE[(VERIFY_CYCLE.index(cur) + 1) % 3])
    elif key == "warn_action":
        cur = cfg(cid, "warn_action")
        setcfg(cid, "warn_action", ACTION_CYCLE[(ACTION_CYCLE.index(cur) + 1) % 3])
    elif key == "autodelete":
        cur = cfg(cid, "autodelete")
        cur = cur if cur in AD_CYCLE else "0"
        setcfg(cid, "autodelete", AD_CYCLE[(AD_CYCLE.index(cur) + 1) % len(AD_CYCLE)])
    elif key in ("warn_up", "warn_dn"):
        n = int(cfg(cid, "warn_limit")) + (1 if key == "warn_up" else -1)
        setcfg(cid, "warn_limit", min(10, max(1, n)))
    await ui_edit(cb, panel_text(chat), panel(cid))
    await cb.answer("✅ Updated")


@app.on_callback_query(filters.regex(r"^lk:"))
async def locks_cb(client, cb):
    chat = cb.message.chat
    cid = chat.id
    if not await is_admin(client, cid, cb.from_user.id):
        return await cb.answer("⛔ Sirf admins ke liye!", show_alert=True)
    name = cb.data.split(":", 1)[1]
    if name == "back":
        await ui_edit(cb, panel_text(chat), panel(cid))
        return await cb.answer()
    if name in LOCKS:
        cur = {x for x in cfg(cid, "locks").split(",") if x}
        if name in cur:
            cur.discard(name)
        else:
            cur.add(name)
        setcfg(cid, "locks", ",".join(sorted(cur)))
        await ui_edit(cb, locks_text(), locks_kb(cid))
    await cb.answer()


# ----- Stats (group + owner global) --------------------------------------- #
async def build_stats(client, cid):
    try:
        members = await client.get_chat_members_count(cid)
    except RPCError:
        members = "?"
    day = time.strftime("%Y-%m-%d")
    row = db.execute(
        "SELECT joins, leaves, messages FROM stats WHERE chat_id=? AND day=?", (cid, day)
    ).fetchone() or (0, 0, 0)
    week = db.execute(
        "SELECT SUM(joins), SUM(leaves), SUM(messages) FROM stats WHERE chat_id=? AND day>=?",
        (cid, time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))),
    ).fetchone()
    top = db.execute(
        "SELECT name, messages FROM users WHERE chat_id=? ORDER BY messages DESC LIMIT 5", (cid,)
    ).fetchall()
    text = (
        f"📊 <b>Group Stats</b>\n{LINE}\n"
        f"👥 Total members: <b>{members}</b>\n\n"
        f"📅 <b>Aaj</b>\n➕ {row[0]} joins • ➖ {row[1]} leaves • 💬 {row[2]} msgs\n\n"
        f"🗓 <b>Pichhle 7 din</b>\n➕ {week[0] or 0} joins • ➖ {week[1] or 0} leaves • 💬 {week[2] or 0} msgs\n"
    )
    if top:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        text += f"\n🏆 <b>Top active</b>\n" + "\n".join(
            f"{medals[i]} {html.escape(n or 'User')} — {m}" for i, (n, m) in enumerate(top)
        )
    return text


@app.on_message(filters.command("stats"))
async def stats_cmd(client, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user or not is_owner(message.from_user.id):
            return await message.reply_text("📊 Stats dekhne ke liye group me /stats use karein.")
        return await message.reply_text(owner_text(), reply_markup=owner_kb())
    await say(message, await build_stats(client, message.chat.id))


# ----- Owner panel --------------------------------------------------------- #
def counts():
    u = db.execute("SELECT COUNT(*) FROM bot_users").fetchone()[0]
    g = db.execute("SELECT COUNT(*) FROM bot_chats").fetchone()[0]
    return u, g


def owner_text():
    u, g = counts()
    return (
        f"👑 <b>Owner Panel</b>\n{LINE}\n"
        f"👤 Bot users: <b>{u}</b>\n"
        f"👥 Groups: <b>{g}</b>\n"
        f"🤖 Version: <b>v{__version__}</b>\n{LINE}\n"
        "Neeche se option chuniye 👇"
    )


def owner_kb():
    return Kb(
        [
            [Btn("👥 Groups list", callback_data="own:groups"), Btn("📣 Broadcast", callback_data="own:bc")],
            [Btn("🔄 Refresh", callback_data="own:home"), Btn("✖️ Close", callback_data="own:close")],
        ]
    )


@app.on_message(filters.command("panel"))
async def panel_cmd(client, message):
    if not message.from_user or not is_owner(message.from_user.id):
        if message.chat.type == enums.ChatType.PRIVATE:
            await message.reply_text("⛔ Ye panel sirf bot owner ke liye hai.\n(Owner ID <code>OWNER_IDS</code> me set hoti hai.)")
        return
    await message.reply_text(owner_text(), reply_markup=owner_kb())


@app.on_callback_query(filters.regex(r"^own:"))
async def owner_cb(client, cb):
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Sirf bot owner ke liye!", show_alert=True)
    page = cb.data.split(":", 1)[1]
    back = Kb([[Btn("⬅️ Back", callback_data="own:home")]])
    if page == "close":
        try:
            await cb.message.delete()
        except RPCError:
            pass
        return
    if page == "home":
        await ui_edit(cb, owner_text(), owner_kb())
    elif page == "groups":
        rows = db.execute(
            "SELECT title, chat_id FROM bot_chats ORDER BY first_seen DESC LIMIT 20"
        ).fetchall()
        text = f"👥 <b>Groups</b> (latest 20)\n{LINE}\n" + (
            "\n".join(f"• {html.escape(t or 'Untitled')} — <code>{i}</code>" for t, i in rows)
            if rows else "Abhi koi group record nahi hua."
        )
        await ui_edit(cb, text, back)
    elif page == "bc":
        text = (
            f"📣 <b>Broadcast</b>\n{LINE}\n"
            "1️⃣ Bot ko private me wo message bhejein jo sab tak pahunchana hai\n"
            "2️⃣ Us message par <b>reply</b> karke /broadcast likhein\n"
            "3️⃣ Users / Groups / All me se chuniye"
        )
        await ui_edit(cb, text, back)
    await cb.answer()


BAD_TARGET = (
    "USER_IS_BLOCKED", "INPUT_USER_DEACTIVATED", "USER_DEACTIVATED",
    "PEER_ID_INVALID", "CHAT_WRITE_FORBIDDEN", "CHANNEL_PRIVATE",
)


@app.on_message(filters.command("broadcast"))
async def broadcast_cmd(client, message):
    if not message.from_user or not is_owner(message.from_user.id):
        if message.chat.type == enums.ChatType.PRIVATE:
            await message.reply_text("⛔ Ye command sirf bot owner ke liye hai.")
        return
    r = message.reply_to_message
    if not r:
        return await message.reply_text("⚠️ Jo message bhejna hai us par reply karke /broadcast likhein.")
    u, g = counts()
    base = f"{message.chat.id}:{r.id}"
    kb = Kb(
        [
            [Btn(f"👤 Users ({u})", callback_data=f"bc:users:{base}"), Btn(f"👥 Groups ({g})", callback_data=f"bc:groups:{base}")],
            [Btn(f"🌐 All ({u + g})", callback_data=f"bc:all:{base}")],
            [Btn("✖️ Cancel", callback_data="bc:cancel:0:0")],
        ]
    )
    await message.reply_text(f"📣 <b>Broadcast</b>\n{LINE}\nYe message kis ko bhejna hai?", reply_markup=kb, reply_to_message_id=r.id)


async def _run_broadcast(client, status, src_chat, src_msg, targets):
    sent = failed = 0
    for i, t in enumerate(targets, 1):
        try:
            await client.copy_message(t, src_chat, src_msg)
            sent += 1
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await client.copy_message(t, src_chat, src_msg)
                sent += 1
            except Exception:
                failed += 1
        except RPCError as e:
            failed += 1
            if any(b in str(e).upper() for b in BAD_TARGET):
                db.execute("DELETE FROM bot_users WHERE user_id=?", (t,))
                db.execute("DELETE FROM bot_chats WHERE chat_id=?", (t,))
                db.commit()
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
        if i % 50 == 0:
            try:
                await status.edit_text(f"⏳ Broadcast chal raha hai... {i}/{len(targets)}")
            except RPCError:
                pass
    try:
        await status.edit_text(
            f"✅ <b>Broadcast complete</b>\n{LINE}\n📤 Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b>"
        )
    except RPCError:
        pass


@app.on_callback_query(filters.regex(r"^bc:"))
async def broadcast_cb(client, cb):
    if not is_owner(cb.from_user.id):
        return await cb.answer("⛔ Sirf bot owner ke liye!", show_alert=True)
    _, mode, chat_id, msg_id = cb.data.split(":")
    if mode == "cancel":
        await ui_edit(cb, "❌ Broadcast cancel kar diya.")
        return await cb.answer()
    targets = []
    if mode in ("users", "all"):
        targets += [x[0] for x in db.execute("SELECT user_id FROM bot_users")]
    if mode in ("groups", "all"):
        targets += [x[0] for x in db.execute("SELECT chat_id FROM bot_chats")]
    targets = list(dict.fromkeys(targets))
    if not targets:
        await ui_edit(cb, "⚠️ Koi target nahi mila.")
        return await cb.answer()
    await ui_edit(cb, f"⏳ Broadcast shuru... {len(targets)} targets")
    await cb.answer()
    t = asyncio.create_task(_run_broadcast(client, cb.message, int(chat_id), int(msg_id), targets))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@app.on_message(filters.private, group=7)
async def track_private(client, message):
    if message.from_user:
        track_user(message.from_user.id)


# ----- Keyword filters ----------------------------------------------------- #
@app.on_message(filters.command("filter") & filters.group)
@admin_only
async def filter_cmd(client, message):
    raw = message.text.partition(" ")[2].strip()
    if "|" not in raw:
        return await say(message, "Usage: /filter keyword | reply text")
    keyword, reply = [x.strip() for x in raw.split("|", 1)]
    if not keyword or not reply or len(keyword) > 80 or len(reply) > 800:
        return await say(message, "⚠️ Keyword/reply invalid ya bahut lamba hai.")
    db.execute(
        "INSERT OR REPLACE INTO kwfilters VALUES (?,?,?)",
        (message.chat.id, keyword.casefold(), reply),
    )
    db.commit()
    await say(message, f"✅ Filter save: <code>{html.escape(keyword)}</code>")


@app.on_message(filters.command("filters") & filters.group)
async def filters_list_cmd(client, message):
    rows = db.execute(
        "SELECT keyword FROM kwfilters WHERE chat_id=? ORDER BY keyword LIMIT 50", (message.chat.id,)
    ).fetchall()
    await say(message, "🔎 <b>Filters</b>\n" + "\n".join(f"• <code>{html.escape(r[0])}</code>" for r in rows) if rows else "Koi filter set nahi hai.")


@app.on_message(filters.command("stopfilter") & filters.group)
@admin_only
async def stopfilter_cmd(client, message):
    keyword = message.text.partition(" ")[2].strip().casefold()
    if not keyword:
        return await say(message, "Usage: /stopfilter keyword")
    cur = db.execute("DELETE FROM kwfilters WHERE chat_id=? AND keyword=?", (message.chat.id, keyword))
    db.commit()
    await say(message, "🗑 Filter hata diya." if cur.rowcount else "Aisa filter nahi mila.")


@app.on_message(filters.group & filters.text & ~filters.service, group=6)
async def keyword_filter_handler(client, message):
    text = message.text or ""
    if not text or text.startswith("/"):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    rows = db.execute("SELECT keyword, reply FROM kwfilters WHERE chat_id=?", (message.chat.id,)).fetchall()
    low = text.casefold()
    for keyword, reply in rows:
        if keyword in low:
            await say(message, reply)
            break


# --------------------------------------------------------------------------- #
# ADVANCED v2: Levels/XP, Night mode, Timezone, Scheduled messages,
# Temp-ban, Anti-repeat, Lockdown, background scheduler
# --------------------------------------------------------------------------- #
from datetime import timezone  # noqa: E402
from pyrogram import idle  # noqa: E402

db.executescript(
    """
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, text TEXT, run_at INTEGER, repeat INTEGER DEFAULT 0
);
"""
)
db.commit()

repeat_hist = {}  # (chat_id, user_id) -> [(ts, text)]

# ----- help pages extended -------------------------------------------------- #
HELP_PAGES["auto"] += "\n🔁 /antirepeat on|off – same message baar-baar bhejna block"
HELP_PAGES["tools"] += (
    "\n\n⏳ /tban &lt;10m|2h|1d&gt; – temporary ban\n"
    "🚧 /lockdown on|off – poora group lock/unlock\n"
    "🌙 /nightmode on|off|&lt;start&gt; &lt;end&gt; – raat ko auto lock\n"
    "🕒 /timezone +5:30 – group ka time zone\n"
    "⏰ /schedule &lt;time&gt; &lt;text&gt; • /repeat &lt;time&gt; &lt;text&gt;\n"
    "📋 /schedules • /unschedule &lt;id&gt;"
)
HELP_PAGES["manage"] += "\n\n🏆 /rank • /top • /levels on|off"
INFO_PAGES["features"] += (
    "\n🏆 Levels / XP &amp; leaderboard\n🌙 Night mode &amp; Lockdown\n⏰ Scheduled &amp; repeating messages\n🔁 Anti-repeat • ⏳ Temp-ban"
)
HELP = HELP.replace(
    "\n\n👨‍💻 Created by @roaroic0",
    "\n\n<b>Advanced</b>\n"
    "/tban · /lockdown · /nightmode · /timezone\n"
    "/schedule · /repeat · /schedules · /unschedule\n"
    "/antirepeat on|off · /rank · /top · /levels on|off"
    "\n\n👨‍💻 Created by @roaroic0",
)


# ----- Helpers -------------------------------------------------------------- #
def full_perms():
    try:
        return ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_send_polls=True,
            can_add_web_page_previews=True, can_invite_users=True,
        )
    except TypeError:
        return ChatPermissions(can_send_messages=True)


def parse_tz(s):
    m = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", s.strip())
    if not m:
        return None
    h, mi = int(m.group(2)), int(m.group(3) or 0)
    if h > 14 or mi not in (0, 15, 30, 45):
        return None
    return f"{m.group(1)}{h:02d}:{mi:02d}"


def tz_delta(s):
    sign = -1 if s[0] == "-" else 1
    h, m = s[1:].split(":")
    return sign * timedelta(hours=int(h), minutes=int(m))


def parse_hm(s):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", s.strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def hm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def local_now(chat_id):
    return datetime.now(timezone.utc) + tz_delta(cfg(chat_id, "tz"))


def night_label(chat_id):
    if cfg(chat_id, "night_on") != "1":
        return "off"
    return f"{cfg(chat_id, 'night_start')}–{cfg(chat_id, 'night_end')} (UTC{cfg(chat_id, 'tz')})"


def is_night_now(chat_id):
    s, e = hm_to_min(cfg(chat_id, "night_start")), hm_to_min(cfg(chat_id, "night_end"))
    if s == e:
        return False
    now = local_now(chat_id)
    nowm = now.hour * 60 + now.minute
    return (s <= nowm < e) if s < e else (nowm >= s or nowm < e)


async def night_lock(client, cid):
    try:
        await client.set_chat_permissions(cid, ChatPermissions())
    except RPCError:
        return False
    setcfg(cid, "night_state", "1")
    try:
        m = await client.send_message(
            cid, f"🌙 <b>Night mode ON</b>\nGroup {cfg(cid, 'night_end')} tak band hai. Shubh ratri! 😴"
        )
        autodel(cid, m, 600)
    except RPCError:
        pass
    return True


async def night_unlock(client, cid):
    try:
        await client.set_chat_permissions(cid, full_perms())
    except RPCError:
        return False
    setcfg(cid, "night_state", "0")
    try:
        m = await client.send_message(cid, "☀️ <b>Night mode OFF</b>\nGroup khul gaya. Good morning! 🌅")
        autodel(cid, m, 600)
    except RPCError:
        pass
    return True


# ----- Background scheduler ------------------------------------------------- #
async def _run_schedules(client):
    now = int(time.time())
    rows = db.execute(
        "SELECT id, chat_id, text, repeat FROM schedules WHERE run_at<=?", (now,)
    ).fetchall()
    for sid, cid, text, rep in rows:
        try:
            try:
                await client.send_message(cid, text)
            except RPCError as e:
                if any(k in str(e).upper() for k in ("ENTITY", "PARSE", "TAG")):
                    await client.send_message(cid, text, parse_mode=enums.ParseMode.DISABLED)
        except Exception:
            pass
        if rep:
            nxt = now + rep
            db.execute("UPDATE schedules SET run_at=? WHERE id=?", (nxt, sid))
        else:
            db.execute("DELETE FROM schedules WHERE id=?", (sid,))
    if rows:
        db.commit()


async def _run_night(client):
    chats = [r[0] for r in db.execute("SELECT chat_id FROM settings WHERE key='night_on' AND value='1'")]
    for cid in chats:
        state = cfg(cid, "night_state") == "1"
        night = is_night_now(cid)
        if night and not state:
            await night_lock(client, cid)
        elif not night and state:
            await night_unlock(client, cid)


async def scheduler_loop(client):
    await asyncio.sleep(5)
    while True:
        try:
            await _run_schedules(client)
            await _run_night(client)
        except Exception as e:  # never let the loop die
            print("scheduler error:", e)
        await asyncio.sleep(30)


async def _main():
    await app.start()
    t = asyncio.create_task(scheduler_loop(app))
    _tasks.add(t)
    print("Bot started ✅")
    await idle()
    await app.stop()


# ----- Temp ban ------------------------------------------------------------- #
@app.on_message(filters.command("tban") & filters.group)
@admin_only
async def tban_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, rest = r
    delta = parse_time(rest[0]) if rest else None
    if not delta:
        return await say(message, "Usage: /tban &lt;10m|2h|1d|1w&gt; [reason] (reply ya ID/@username ke saath)")
    reason = f"\nKaran: {html.escape(' '.join(rest[1:]))}" if len(rest) > 1 else ""
    try:
        await client.ban_chat_member(message.chat.id, user.id, until_date=datetime.now() + delta)
    except RPCError as e:
        return await say(message, f"❌ Ban fail: <code>{err(e)}</code>")
    await log_action(client, message.chat, f"⏳ <b>Temp-ban</b> ({rest[0]})\nUser: {mention(user)} (<code>{user.id}</code>)\nBy: {actor(message)}{reason}")
    await say(message, f"⏳ {mention(user)} ko <b>{rest[0]}</b> ke liye ban kar diya gaya.{reason}")


# ----- Lockdown / Night mode / Timezone ------------------------------------- #
@app.on_message(filters.command("lockdown") & filters.group)
@admin_only
async def lockdown_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /lockdown on|off\nON: koi bhi member message nahi bhej sakta (sirf admins).")
    try:
        await client.set_chat_permissions(message.chat.id, ChatPermissions() if v == "1" else full_perms())
    except RPCError as e:
        return await say(message, f"❌ <code>{err(e)}</code>")
    await log_action(client, message.chat, f"🚧 <b>Lockdown {'ON' if v == '1' else 'OFF'}</b> by {actor(message)}")
    await say(message, "🚧 <b>Lockdown ON</b> – group lock ho gaya." if v == "1" else "✅ <b>Lockdown OFF</b> – group khul gaya.")


@app.on_message(filters.command("timezone") & filters.group)
@admin_only
async def timezone_cmd(client, message):
    cid = message.chat.id
    if len(message.command) < 2:
        now = local_now(cid)
        return await say(message, f"🕒 Time zone: <b>UTC{cfg(cid, 'tz')}</b>\nAbhi: {now.strftime('%H:%M')}\nBadalne ke liye: /timezone +5:30")
    tz = parse_tz(message.command[1])
    if not tz:
        return await say(message, "⚠️ Format: /timezone +5:30 (ya -4:00, +0)")
    setcfg(cid, "tz", tz)
    await say(message, f"🕒 Time zone set: <b>UTC{tz}</b> (abhi {local_now(cid).strftime('%H:%M')})")


@app.on_message(filters.command("nightmode") & filters.group)
@admin_only
async def nightmode_cmd(client, message):
    cid = message.chat.id
    args = message.command[1:]
    if not args:
        return await say(
            message,
            f"🌙 <b>Night mode:</b> {night_label(cid)}\n\n"
            "/nightmode on|off\n/nightmode 23:00 06:00 (start end, local time)\n/timezone +5:30 se time zone set karein.\n"
            "<i>Bot ko 'Restrict members' / 'Change group info' admin right chahiye.</i>",
        )
    if len(args) == 2:
        a, b = parse_hm(args[0]), parse_hm(args[1])
        if not a or not b or a == b:
            return await say(message, "⚠️ Format: /nightmode 23:00 06:00")
        setcfg(cid, "night_start", a)
        setcfg(cid, "night_end", b)
        setcfg(cid, "night_on", "1")
        return await say(message, f"🌙 Night mode ON: <b>{a} – {b}</b> (UTC{cfg(cid, 'tz')})")
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /nightmode on|off ya /nightmode 23:00 06:00")
    setcfg(cid, "night_on", v)
    if v == "0" and cfg(cid, "night_state") == "1":
        await night_unlock(client, cid)
    await say(message, f"🌙 Night mode: <b>{'ON' if v == '1' else 'OFF'}</b>")


# ----- Anti-repeat / Levels toggles ----------------------------------------- #
@app.on_message(filters.command("antirepeat") & filters.group)
@admin_only
async def antirepeat_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /antirepeat on|off\n60 second me same message 3 baar bheja to delete + warn.")
    setcfg(message.chat.id, "antirepeat", v)
    await say(message, f"🔁 Anti-repeat: <b>{'ON' if v == '1' else 'OFF'}</b>")


@app.on_message(filters.command("levels") & filters.group)
@admin_only
async def levels_cmd(client, message):
    v = onoff_arg(message)
    if v is None:
        return await say(message, "Usage: /levels on|off (level-up messages)")
    setcfg(message.chat.id, "levels", v)
    await say(message, f"🏆 Level-up messages: <b>{'ON' if v == '1' else 'OFF'}</b>")


# ----- Scheduled messages --------------------------------------------------- #
def _fmt_delta(sec):
    for unit, n in (("din", 86400), ("ghante", 3600), ("minute", 60)):
        if sec >= n:
            return f"{sec // n} {unit}"
    return f"{sec} second"


async def _add_schedule(client, message, repeating):
    cid = message.chat.id
    parts = message.text.split(None, 2)
    cmd = "repeat" if repeating else "schedule"
    delta = parse_time(parts[1]) if len(parts) > 1 else None
    text = parts[2].strip() if len(parts) > 2 else None
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption
    if not delta or not text:
        return await say(message, f"Usage: /{cmd} &lt;10m|2h|1d&gt; &lt;text&gt;\nExample: /{cmd} 6h Rules padh lein 📜")
    secs = int(delta.total_seconds())
    if secs < 60 or (repeating and secs < 300):
        return await say(message, "⚠️ Minimum: schedule 1 minute, repeat 5 minute.")
    if len(text) > 1000:
        return await say(message, "⚠️ Text bahut lamba hai (max 1000).")
    count = db.execute("SELECT COUNT(*) FROM schedules WHERE chat_id=?", (cid,)).fetchone()[0]
    if count >= 10:
        return await say(message, "⚠️ Ek group me max 10 schedules. /schedules dekhein, /unschedule se hatayein.")
    cur = db.execute(
        "INSERT INTO schedules(chat_id, text, run_at, repeat) VALUES (?,?,?,?)",
        (cid, text, int(time.time()) + secs, secs if repeating else 0),
    )
    db.commit()
    kind = f"🔁 Har {_fmt_delta(secs)} me" if repeating else f"⏰ {_fmt_delta(secs)} baad"
    await say(message, f"{kind} bhejunga.\nID: <code>{cur.lastrowid}</code> (hatane ke liye /unschedule {cur.lastrowid})")


@app.on_message(filters.command("schedule") & filters.group)
@admin_only
async def schedule_cmd(client, message):
    await _add_schedule(client, message, False)


@app.on_message(filters.command("repeat") & filters.group)
@admin_only
async def repeat_cmd(client, message):
    await _add_schedule(client, message, True)


@app.on_message(filters.command("schedules") & filters.group)
@admin_only
async def schedules_cmd(client, message):
    cid = message.chat.id
    rows = db.execute(
        "SELECT id, text, run_at, repeat FROM schedules WHERE chat_id=? ORDER BY run_at", (cid,)
    ).fetchall()
    if not rows:
        return await say(message, "⏰ Koi schedule nahi hai.")
    lines = []
    for sid, text, run_at, rep in rows:
        when = (datetime.fromtimestamp(run_at, timezone.utc) + tz_delta(cfg(cid, "tz"))).strftime("%d %b %H:%M")
        tag = f"🔁 {_fmt_delta(rep)}" if rep else "⏰ once"
        preview = html.escape(text[:40] + ("…" if len(text) > 40 else ""))
        lines.append(f"<code>{sid}</code> • {tag} • {when}\n   {preview}")
    await say(message, "⏰ <b>Schedules</b>\n" + "\n".join(lines))


@app.on_message(filters.command("unschedule") & filters.group)
@admin_only
async def unschedule_cmd(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await say(message, "Usage: /unschedule &lt;id&gt; (ID /schedules me dikhti hai)")
    cur = db.execute("DELETE FROM schedules WHERE id=? AND chat_id=?", (int(message.command[1]), message.chat.id))
    db.commit()
    await say(message, "🗑 Schedule hata diya." if cur.rowcount else "Ye ID is group me nahi mili.")


# ----- Levels / XP ---------------------------------------------------------- #
LEVEL_TITLES = ["🌱 Newbie", "🙂 Member", "⭐ Active", "🔥 Pro", "💎 Elite", "👑 Legend"]


def level_of(msgs):
    return int((msgs / 10) ** 0.5)


def level_title(level):
    return LEVEL_TITLES[min(level // 2, len(LEVEL_TITLES) - 1)]


def bar(frac):
    n = max(0, min(10, int(frac * 10)))
    return "▰" * n + "▱" * (10 - n)


@app.on_message(filters.command("rank") & filters.group)
async def rank_cmd(client, message):
    cid = message.chat.id
    user, _ = await get_target(client, message)
    user = user or message.from_user
    if not user:
        return
    row = db.execute("SELECT messages FROM users WHERE chat_id=? AND user_id=?", (cid, user.id)).fetchone()
    msgs = row[0] if row else 0
    lvl = level_of(msgs)
    cur_xp, nxt_xp = lvl ** 2 * 10, (lvl + 1) ** 2 * 10
    frac = (msgs - cur_xp) / (nxt_xp - cur_xp)
    pos = db.execute("SELECT COUNT(*) FROM users WHERE chat_id=? AND messages>?", (cid, msgs)).fetchone()[0] + 1
    await say(
        message,
        f"🏅 <b>Rank Card</b>\n{LINE}\n"
        f"👤 {mention(user)}\n"
        f"{level_title(lvl)} • Level <b>{lvl}</b>\n"
        f"{bar(frac)} {msgs}/{nxt_xp}\n"
        f"💬 Messages: <b>{msgs}</b>\n"
        f"🏆 Group rank: <b>#{pos}</b>",
    )


@app.on_message(filters.command("top") & filters.group)
async def top_cmd(client, message):
    rows = db.execute(
        "SELECT user_id, name, messages FROM users WHERE chat_id=? ORDER BY messages DESC LIMIT 10",
        (message.chat.id,),
    ).fetchall()
    if not rows:
        return await say(message, "Abhi koi data nahi hai.")
    medals = ["🥇", "🥈", "🥉"] + [f"{i}." for i in range(4, 11)]
    lines = [
        f"{medals[i]} {html.escape(n or 'User')} — L{level_of(m)} • {m} msgs"
        for i, (_, n, m) in enumerate(rows)
    ]
    await say(message, f"🏆 <b>Leaderboard</b>\n{LINE}\n" + "\n".join(lines))


@app.on_message(filters.group & ~filters.service, group=8)
async def level_up_handler(client, message):
    u = message.from_user
    if not u or u.is_bot:
        return
    cid = message.chat.id
    if cfg(cid, "levels") != "1":
        return
    row = db.execute("SELECT messages FROM users WHERE chat_id=? AND user_id=?", (cid, u.id)).fetchone()
    if not row or row[0] < 10:
        return
    now, before = level_of(row[0]), level_of(row[0] - 1)
    if now > before:
        m = await client.send_message(
            cid, f"🎉 {mention(u)} ab <b>Level {now}</b> par pahunch gaya! {level_title(now)}"
        )
        autodel(cid, m, 30)


# --------------------------------------------------------------------------- #
# ONE-CLICK UI: /mod panel, report buttons, /menu control center,
# slowmode / night presets, welcome style presets
# --------------------------------------------------------------------------- #
HELP_PAGES["manage"] += (
    "\n\n🎛 /menu – Control Center (sab kuch ek click me)\n"
    "🛠 /mod – user ke message par reply karke ek-click mod panel"
)
INFO_PAGES["features"] += "\n🎛 One-click Control Center &amp; Mod panel"
HELP = HELP.replace(
    "<b>Advanced</b>",
    "<b>One-click buttons</b>\n/menu · /mod (reply karke)\n\n<b>Advanced</b>",
)

WELCOME_PRESETS = {
    "1": ("Simple", "👋 Welcome {mention} to <b>{chat}</b>!"),
    "2": ("Friendly", "🎉 Hey {mention}! <b>{chat}</b> family me swagat hai 🥳\nRules padhna mat bhoolna: /rules"),
    "3": ("Formal", "Namaste {mention}, <b>{chat}</b> me aapka swagat hai. Kripya group ke niyam /rules me padhein."),
    "4": ("Minimal", "{mention} joined 👋"),
}


# ----- Mod panel (one click per action) ------------------------------------- #
def mc_kb(uid, mid, compact=False):
    c = 1 if compact else 0

    def d(a):
        return f"mc:{a}:{uid}:{mid}:{c}"

    if compact:
        return Kb(
            [
                [Btn("⚠️ Warn", callback_data=d("wn")), Btn("🔇 Mute 1h", callback_data=d("m1")), Btn("🔨 Ban", callback_data=d("bn"))],
                [Btn("🗑 Msg delete", callback_data=d("dl")), Btn("✅ Ignore", callback_data=d("cl"))],
            ]
        )
    return Kb(
        [
            [Btn("⚠️ Warn", callback_data=d("wn")), Btn("✅ Unwarn", callback_data=d("uw")), Btn("📋 Warns", callback_data=d("wi"))],
            [Btn("🔇 Mute 1h", callback_data=d("m1")), Btn("🔇 Mute 1d", callback_data=d("m24")), Btn("🔊 Unmute", callback_data=d("um"))],
            [Btn("👢 Kick", callback_data=d("kk")), Btn("🔨 Ban", callback_data=d("bn")), Btn("♻️ Unban", callback_data=d("ub"))],
            [Btn("🗑 Msg delete", callback_data=d("dl")), Btn("✖️ Close", callback_data=d("cl"))],
        ]
    )


def mc_text(user, cid, last=""):
    note = f"\n{last}" if last else ""
    return (
        f"🛠 <b>Mod Panel</b>\n{LINE}\n"
        f"👤 {mention(user)}\n🆔 <code>{user.id}</code>\n"
        f"⚠️ Warns: <b>{get_warns(cid, user.id)}/{cfg(cid, 'warn_limit')}</b>{note}\n"
        f"{LINE}\nEk click me action chuniye 👇"
    )


@app.on_message(filters.command("mod") & filters.group)
@admin_only
async def mod_cmd(client, message):
    r = await prep(client, message)
    if not r:
        return
    user, _ = r
    mid = message.reply_to_message.id if message.reply_to_message else 0
    m = await message.reply_text(mc_text(user, message.chat.id), reply_markup=mc_kb(user.id, mid))
    autodel(message.chat.id, m, 300)


@app.on_callback_query(filters.regex(r"^mc:"))
async def mc_cb(client, cb):
    _, act, uid, mid, compact = cb.data.split(":")
    uid, mid, compact = int(uid), int(mid), compact == "1"
    chat = cb.message.chat
    cid = chat.id
    if not await is_admin(client, cid, cb.from_user.id):
        return await cb.answer("⛔ Sirf admins ke liye!", show_alert=True)
    if act == "cl":
        try:
            await cb.message.delete()
        except RPCError:
            pass
        return
    try:
        user = await client.get_users(uid)
    except Exception:
        return await cb.answer("User nahi mila.", show_alert=True)
    if act in ("wn", "m1", "m24", "kk", "bn") and (
        uid == await my_id(client) or await is_admin(client, cid, uid)
    ):
        return await cb.answer("⚠️ Admin ya bot par ye action nahi ho sakta.", show_alert=True)

    result = ""
    try:
        if act == "wn":
            count = set_warns(cid, uid, get_warns(cid, uid) + 1)
            limit = int(cfg(cid, "warn_limit"))
            if count >= limit:
                action = cfg(cid, "warn_action")
                problem = await punish(client, cid, uid, action)
                set_warns(cid, uid, 0)
                if problem:
                    return await cb.answer(f"❌ {problem[:150]}", show_alert=True)
                result = f"🚫 Warn limit poori → <b>{action}</b>"
            else:
                result = f"⚠️ Warn diya ({count}/{limit})"
        elif act == "uw":
            n = set_warns(cid, uid, get_warns(cid, uid) - 1)
            result = f"✅ Ek warn hata diya (ab {n})"
        elif act == "wi":
            return await cb.answer(f"Warns: {get_warns(cid, uid)}/{cfg(cid, 'warn_limit')}", show_alert=True)
        elif act in ("m1", "m24"):
            hours = 1 if act == "m1" else 24
            await client.restrict_chat_member(
                cid, uid, ChatPermissions(), until_date=datetime.now() + timedelta(hours=hours)
            )
            result = f"🔇 Mute: {'1 ghanta' if hours == 1 else '1 din'}"
        elif act == "um":
            await unrestrict(client, cid, uid)
            result = "🔊 Unmute ho gaya"
        elif act == "kk":
            await kick(client, cid, uid)
            result = "👢 Kick kar diya"
        elif act == "bn":
            await client.ban_chat_member(cid, uid)
            result = "🔨 Ban kar diya"
        elif act == "ub":
            await client.unban_chat_member(cid, uid)
            result = "♻️ Unban ho gaya"
        elif act == "dl":
            if not mid:
                return await cb.answer("Is panel ke saath koi message juda nahi hai.", show_alert=True)
            await client.delete_messages(cid, mid)
            result = "🗑 Message delete ho gaya"
    except RPCError as e:
        return await cb.answer(f"❌ {str(e)[:150]}", show_alert=True)

    await log_action(
        client, chat,
        f"🛠 <b>Mod panel</b>: {result}\nUser: {mention(user)} (<code>{uid}</code>)\nBy: {mention(cb.from_user)}",
    )
    await ui_edit(cb, mc_text(user, cid, f"✅ {result}"), mc_kb(uid, mid, compact))
    await cb.answer("✅ Done")


# ----- Control center ------------------------------------------------------- #
def cc_text(chat, note=""):
    extra = f"\n{note}\n" if note else "\n"
    return (
        f"🎛 <b>Control Center</b>\n<i>{html.escape(chat.title or '')}</i>\n{LINE}{extra}"
        "Sab kuch ek click me 👇"
    )


def cc_kb():
    return Kb(
        [
            [Btn("⚙️ Settings", callback_data="cc:settings"), Btn("🛠 Mod tools", callback_data="cc:mod")],
            [Btn("🚧 Lock group", callback_data="cc:lock:on"), Btn("✅ Unlock group", callback_data="cc:lock:off")],
            [Btn("🐢 Slowmode", callback_data="cc:slow"), Btn("🌙 Night mode", callback_data="cc:night")],
            [Btn("📊 Stats", callback_data="cc:stats"), Btn("📜 Rules", callback_data="cc:rules")],
            [Btn("📚 Help", callback_data="cc:help"), Btn("✖️ Close", callback_data="cc:close")],
        ]
    )


def slow_kb():
    opts = [("Off", 0), ("10s", 10), ("30s", 30), ("1m", 60), ("5m", 300), ("15m", 900), ("1h", 3600)]
    rows = [[Btn(f"🐢 {lbl}", callback_data=f"cc:sl:{n}") for lbl, n in opts[i:i + 4]] for i in range(0, len(opts), 4)]
    rows.append([Btn("⬅️ Back", callback_data="cc:home")])
    return Kb(rows)


def night_kb():
    return Kb(
        [
            [Btn("🌙 Turn ON", callback_data="cc:ng:on"), Btn("☀️ Turn OFF", callback_data="cc:ng:off")],
            [Btn("22:00–06:00", callback_data="cc:ng:2200-0600"), Btn("23:00–07:00", callback_data="cc:ng:2300-0700")],
            [Btn("00:00–07:00", callback_data="cc:ng:0000-0700"), Btn("🇮🇳 India time", callback_data="cc:tzin")],
            [Btn("⬅️ Back", callback_data="cc:home")],
        ]
    )


def night_page_text(cid):
    return (
        f"🌙 <b>Night mode</b>\n{LINE}\n"
        f"Status: <b>{night_label(cid)}</b>\n"
        f"🕒 Time zone: UTC{cfg(cid, 'tz')} (abhi {local_now(cid).strftime('%H:%M')})\n\n"
        "Preset chuniye 👇\n<i>Doosra time zone: /timezone +5:30</i>"
    )


@app.on_message(filters.command("menu"))
async def menu_cmd(client, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("🎛 Ye menu group ke liye hai. Group me /menu likhein.")
    if not message.from_user or not await is_admin(client, message.chat.id, message.from_user.id):
        return await say(message, "⛔ Ye menu sirf admins ke liye hai.")
    m = await message.reply_text(cc_text(message.chat), reply_markup=cc_kb())
    autodel(message.chat.id, m, 600)


@app.on_callback_query(filters.regex(r"^cc:"))
async def cc_cb(client, cb):
    chat = cb.message.chat
    cid = chat.id
    if not await is_admin(client, cid, cb.from_user.id):
        return await cb.answer("⛔ Sirf admins ke liye!", show_alert=True)
    parts = cb.data.split(":")
    page = parts[1]
    arg = parts[2] if len(parts) > 2 else ""
    back = Kb([[Btn("⬅️ Back", callback_data="cc:home")]])

    if page == "close":
        try:
            await cb.message.delete()
        except RPCError:
            pass
        return
    if page == "home":
        await ui_edit(cb, cc_text(chat), cc_kb())
    elif page == "settings":
        await ui_edit(cb, panel_text(chat), panel(cid))
    elif page == "mod":
        await ui_edit(
            cb,
            f"🛠 <b>Mod tools</b>\n{LINE}\n"
            "1️⃣ Kisi user ke message par <b>reply</b> karke /mod likhein\n"
            "2️⃣ Warn / Mute / Kick / Ban / Msg delete — sab <b>ek click</b> me\n\n"
            "🚨 Members /report karein to admins ko bhi wahi buttons milte hain.",
            back,
        )
    elif page == "lock":
        on = arg == "on"
        try:
            await client.set_chat_permissions(cid, ChatPermissions() if on else full_perms())
        except RPCError as e:
            return await cb.answer(f"❌ {str(e)[:150]}", show_alert=True)
        await log_action(client, chat, f"🚧 <b>Lockdown {'ON' if on else 'OFF'}</b> by {mention(cb.from_user)}")
        await ui_edit(cb, cc_text(chat, "🚧 Group <b>LOCK</b> ho gaya." if on else "✅ Group <b>UNLOCK</b> ho gaya."), cc_kb())
        return await cb.answer("🚧 Locked" if on else "✅ Unlocked")
    elif page == "slow":
        await ui_edit(cb, f"🐢 <b>Slowmode</b>\n{LINE}\nEk click me interval chuniye 👇", slow_kb())
    elif page == "sl":
        n = int(arg)
        try:
            await client.set_slow_mode(cid, n or None)
        except RPCError as e:
            return await cb.answer(f"❌ {str(e)[:150]}", show_alert=True)
        await ui_edit(
            cb,
            f"🐢 <b>Slowmode</b>\n{LINE}\n✅ Ab: <b>{'OFF' if n == 0 else str(n) + 's'}</b>",
            slow_kb(),
        )
        return await cb.answer("✅ Done")
    elif page == "night":
        await ui_edit(cb, night_page_text(cid), night_kb())
    elif page == "ng":
        if arg == "on":
            setcfg(cid, "night_on", "1")
        elif arg == "off":
            setcfg(cid, "night_on", "0")
            if cfg(cid, "night_state") == "1":
                await night_unlock(client, cid)
        else:
            setcfg(cid, "night_start", f"{arg[:2]}:{arg[2:4]}")
            setcfg(cid, "night_end", f"{arg[5:7]}:{arg[7:9]}")
            setcfg(cid, "night_on", "1")
        await ui_edit(cb, night_page_text(cid), night_kb())
        return await cb.answer("✅ Done")
    elif page == "tzin":
        setcfg(cid, "tz", "+05:30")
        await ui_edit(cb, night_page_text(cid), night_kb())
        return await cb.answer("🇮🇳 India time set")
    elif page == "stats":
        m = await client.send_message(cid, await build_stats(client, cid))
        autodel(cid, m, 60)
    elif page == "rules":
        r = cfg(cid, "rules")
        m = await client.send_message(cid, f"📜 <b>Group Rules</b>\n\n{r}" if r else "📜 Abhi koi rules set nahi hain. /setrules se set karein.")
        autodel(cid, m, 60)
    elif page == "help":
        m = await client.send_message(cid, help_home_text(), reply_markup=help_home_kb())
        autodel(cid, m, 180)
    await cb.answer()


# ----- Welcome style presets (one click) ------------------------------------ #
def wstyle_kb():
    items = list(WELCOME_PRESETS.items())
    rows = [
        [Btn(f"{k}. {name}", callback_data=f"wp:{k}") for k, (name, _) in items[i:i + 2]]
        for i in range(0, len(items), 2)
    ]
    rows.append([Btn("⬅️ Back", callback_data="wp:back")])
    return Kb(rows)


def wstyle_text():
    body = "\n\n".join(f"<b>{k}. {name}</b>\n{html.escape(text)}" for k, (name, text) in WELCOME_PRESETS.items())
    return f"✏️ <b>Welcome style</b>\n{LINE}\n{body}\n{LINE}\nEk click me style chuniye 👇\n<i>Apna text: /setwelcome</i>"


@app.on_callback_query(filters.regex(r"^wp:"))
async def wstyle_cb(client, cb):
    chat = cb.message.chat
    cid = chat.id
    if not await is_admin(client, cid, cb.from_user.id):
        return await cb.answer("⛔ Sirf admins ke liye!", show_alert=True)
    key = cb.data.split(":", 1)[1]
    if key == "back":
        await ui_edit(cb, panel_text(chat), panel(cid))
        return await cb.answer()
    if key in WELCOME_PRESETS:
        setcfg(cid, "welcome_text", WELCOME_PRESETS[key][1])
        setcfg(cid, "welcome_on", "1")
        await ui_edit(cb, panel_text(chat), panel(cid))
        return await cb.answer(f"✅ Welcome style: {WELCOME_PRESETS[key][0]}")
    await cb.answer()


# --------------------------------------------------------------------------- #
# Keep-alive web server (Render/Koyeb/Heroku jaise Web Service hosts ke liye)
# Sirf tab chalta hai jab PORT environment variable set ho.
# --------------------------------------------------------------------------- #
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402


class _PingHandler(BaseHTTPRequestHandler):
    def _ok(self, body=b""):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._ok(f"Group Manager Bot v{__version__} is running".encode())

    def do_HEAD(self):
        self._ok()

    def log_message(self, *args):
        pass


def start_keepalive():
    port = os.environ.get("PORT")
    if not port:
        return
    server = HTTPServer(("0.0.0.0", int(port)), _PingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Keep-alive server listening on port {port}")


if __name__ == "__main__":
    print(f"Group Manager Bot v{__version__} (created by @roaroic0) starting...")
    start_keepalive()
    app.run(_main())
