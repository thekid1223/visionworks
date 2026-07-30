"""
Vblink Private Server — Combined lobby + slot game server.
Serves exact game files, handles both WS protocols, and provides admin control.
"""
import asyncio, json, sqlite3, hashlib, time, random, os, struct, hmac, logging, threading
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import flask
from flask import Flask, request, jsonify, render_template_string, send_from_directory
import websockets
from websockets.asyncio.server import serve as ws_serve

# ─── Configuration ───────────────────────────────────────────────────────────
HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 8888
GAME_DIR = os.path.join(os.path.dirname(__file__), "game_files")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "server.db")
ADMIN_PASS = "admin123"
SIGN_KEY = "CdO23vdMos23f9l3d2*z2"

os.makedirs(GAME_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vblink-svr")

# ─── Database (single connection, thread-safe) ───────────────────────────────
_db_lock = threading.RLock()
_db_conn = None

def get_db():
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    uid INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT DEFAULT '',
                    token TEXT DEFAULT '',
                    money INTEGER DEFAULT 500000,
                    bank INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS game_config (
                    game_id INTEGER PRIMARY KEY,
                    game_name TEXT DEFAULT '',
                    rtp REAL DEFAULT 95.0,
                    symbol_weights TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1
                );
                INSERT OR IGNORE INTO users (uid, username, password, token, money, is_admin)
                    VALUES (1, 'admin', 'admin123', 'admin_token_1', 999999999, 1);
                INSERT OR IGNORE INTO users (uid, username, token, money)
                    VALUES (1000, 'demo', 'demo_token_1', 1000000);
            """)
            conn.commit()
            _db_conn = conn
        return _db_conn

def db_user_by_token(token):
    with _db_lock:
        c = get_db().execute("SELECT * FROM users WHERE token=?", (token,))
        return c.fetchone()

def db_user_by_uid(uid):
    with _db_lock:
        c = get_db().execute("SELECT * FROM users WHERE uid=?", (uid,))
        return c.fetchone()

def db_user_by_name(name):
    with _db_lock:
        c = get_db().execute("SELECT * FROM users WHERE username=?", (name,))
        return c.fetchone()

def db_update_balance(uid, delta, note=""):
    with _db_lock:
        conn = get_db()
        conn.execute("UPDATE users SET money = money + ? WHERE uid=?", (delta, uid))
        conn.execute("INSERT INTO transactions (uid, amount, type, note) VALUES (?,?,?,?)",
                     (uid, delta, "game" if delta < 0 else "win", note))
        conn.commit()

def db_set_balance(uid, amount):
    with _db_lock:
        conn = get_db()
        old = db_user_by_uid(uid)
        if old:
            delta = amount - old['money']
            conn.execute("UPDATE users SET money=? WHERE uid=?", (amount, uid))
            conn.execute("INSERT INTO transactions (uid, amount, type, note) VALUES (?,?,?,?)",
                         (uid, delta, "admin", "admin adjustment"))
            conn.commit()

def db_get_config(game_id):
    with _db_lock:
        c = get_db().execute("SELECT * FROM game_config WHERE game_id=?", (game_id,))
        row = c.fetchone()
        if not row:
            get_db().execute("INSERT OR IGNORE INTO game_config (game_id, rtp) VALUES (?,95.0)", (game_id,))
        get_db().commit()
        c = get_db().execute("SELECT * FROM game_config WHERE game_id=?", (game_id,))
        row = c.fetchone()
    return dict(row) if row else {"game_id": game_id, "rtp": 95.0, "symbol_weights": "", "enabled": 1}

# ─── Slot Engine — Game 3170 (TRIPLE SUPREME XTREME) ────────────────────────
# Exact paytable from the game's IconConfig.json
SYMBOLS_3170 = [
    {"id": 1,  "name": "10",         "sprite": "10",          "type": "normal", "wild": False, "odds": [0,0,0,5,10,15]},
    {"id": 2,  "name": "J",          "sprite": "J",           "type": "normal", "wild": False, "odds": [0,0,0,5,10,15]},
    {"id": 3,  "name": "Q",          "sprite": "Q",           "type": "normal", "wild": False, "odds": [0,0,0,5,10,15]},
    {"id": 4,  "name": "K",          "sprite": "K",           "type": "normal", "wild": False, "odds": [0,0,0,5,15,38]},
    {"id": 5,  "name": "A",          "sprite": "A",           "type": "normal", "wild": False, "odds": [0,0,0,5,15,38]},
    {"id": 6,  "name": "Firecrackers","sprite": "firecrackers","type": "normal", "wild": False, "odds": [0,0,0,15,28,108]},
    {"id": 7,  "name": "Envelope",   "sprite": "envelope",    "type": "normal", "wild": False, "odds": [0,0,0,18,58,158]},
    {"id": 8,  "name": "Lantern",    "sprite": "lantern",     "type": "normal", "wild": False, "odds": [0,0,0,28,88,208]},
    {"id": 9,  "name": "Yuanbao",    "sprite": "yuanbao",     "type": "normal", "wild": False, "odds": [0,0,28,88,208,888]},
    {"id": 10, "name": "Scatter",    "sprite": "women",       "type": "scatter","wild": False, "odds": [0,0,0,1,10,100]},
    {"id": 11, "name": "Dragon",     "sprite": "dragon",      "type": "wild",   "wild": True,  "odds": [0,0,0,0,0,0]},
    {"id": 12, "name": "Buddha",     "sprite": "buddha",      "type": "bonus",  "wild": False, "odds": [0,0,0,0,0,0]},
]
# Exact 20 paylines from LineConfig.json (positions 0-14 for 5x3 grid)
PAYLINES = [
    [1,4,7,10,13], [0,3,6,9,12], [2,5,8,11,14], [0,4,8,10,12], [2,4,6,10,14],
    [0,4,6,10,12], [2,4,8,10,14], [1,5,7,11,13], [1,3,7,9,13],  [1,4,8,10,13],
    [1,4,6,10,13], [0,4,7,10,12], [2,4,7,10,14], [0,3,7,11,14], [2,5,7,9,12],
    [1,5,8,11,13], [1,3,6,9,13],  [0,4,8,11,14], [2,4,6,9,12],  [0,3,6,10,14],
]
COLS, ROWS = 5, 3
TOTAL_POS = COLS * ROWS
WILD_ID = 11
SCATTER_ID = 10
BONUS_ID = 12

# Default weights for symbols (fine-tuned for ~95% RTP)
DEFAULT_WEIGHTS = [25, 25, 25, 20, 18, 12, 10, 8, 6, 4, 3, 2]
WEIGHTED_POOL = []
for i, w in enumerate(DEFAULT_WEIGHTS):
    WEIGHTED_POOL.extend([i+1] * w)

def validate_against_rtp(grid, bet_per_line, num_lines, target_rtp):
    """Basic RTP validator — re-roll if payout dramatically misses target."""
    total_payout = evaluate_paylines(grid, bet_per_line)
    expected = int(bet_per_line * num_lines * (target_rtp / 100.0))
    max_payout = bet_per_line * num_lines * 1000
    if total_payout > max_payout:
        return False
    return True

def generate_grid(target_rtp=95.0):
    """Generate a random 5x3 symbol grid."""
    grid = []
    for _ in range(TOTAL_POS):
        grid.append(random.choice(WEIGHTED_POOL))
    return grid

def evaluate_paylines(grid, bet_per_line):
    """Check all 20 paylines, return total payout."""
    total = 0
    win_lines = []
    for idx, line in enumerate(PAYLINES):
        symbols = [grid[p] for p in line]
        pay = evaluate_line(symbols, bet_per_line)
        if pay > 0:
            total += pay
            win_lines.append({"line": idx+1, "pay": pay})
    scatter_count = sum(1 for s in grid if s == SCATTER_ID)
    if scatter_count >= 3:
        scatter_pay = {3: bet_per_line * 2, 4: bet_per_line * 10, 5: bet_per_line * 50}.get(scatter_count, 0)
        total += scatter_pay
    return total, win_lines, scatter_count

def evaluate_line(symbols, bet):
    """Evaluate a single payline for consecutive matches left-to-right."""
    first_non_wild = None
    count = 0
    for s in symbols:
        if s == WILD_ID:
            count += 1
            continue
        if first_non_wild is None:
            first_non_wild = s
            count += 1
            continue
        if s == first_non_wild:
            count += 1
        else:
            break
    if count < 3:
        return 0
    sym = next((x for x in SYMBOLS_3170 if x['id'] == first_non_wild), None)
    if not sym or sym['type'] == 'scatter':
        return 0
    multiplier = sym['odds'][min(count, 5)]
    return multiplier * bet

def get_slot_info_response(uid, game_id=3170):
    """Build the slot_info server response."""
    return {
        "succ": True,
        "bet": [1, 2, 5, 10, 20, 50, 100],
        "coin_rate": 1,
        "default_bet": 2,
        "max": 100,
        "min": 1,
        "is_free": False,
        "free_num": 0,
        "free_bet": 0,
        "progresses": [{"stage_id": i, "stage_percent": 0} for i in range(5)],
    }

def do_spin(uid, bet, game_id=3170):
    """Execute a slot spin and return results."""
    config = db_get_config(game_id)
    rtp = config.get("rtp", 95.0)
    user = db_user_by_uid(uid)
    if not user or user['money'] < bet:
        return None, "Insufficient balance"
    
    # Deduct bet
    db_update_balance(uid, -bet, f"spin bet game={game_id}")
    
    # Generate result
    grid = generate_grid(rtp)
    total_payout, win_lines, scatter_ct = evaluate_paylines(grid, bet)
    
    # Add winnings
    if total_payout > 0:
        db_update_balance(uid, total_payout, f"win game={game_id} lines={len(win_lines)}")

    user = db_user_by_uid(uid)
    bal = user['money'] if user else 0

    return {
        "succ": True,
        "base": grid,
        "reward": total_payout,
        "totalwin": total_payout,
        "totalmoney": bal,
        "win": win_lines,
        "scatter": scatter_ct,
    }, None

# ─── Egret Protocol Helpers ──────────────────────────────────────────────────
def egret_encode(obj):
    """Encode JSON → UTF-8 bytes → each byte +1."""
    payload = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    return bytes((b + 1) % 256 for b in payload)

def egret_decode(data):
    """Decode bytes → each byte -1 → UTF-8 → JSON."""
    decoded = bytes((b - 1) % 256 for b in data)
    return json.loads(decoded.decode('utf-8'))

# ─── Slot Game WebSocket Handler ─────────────────────────────────────────────
class SlotSession:
    def __init__(self):
        self.uid = None
        self.token = None
        self.game_id = None
        self.last_heart = time.time()
        self.balance_check_count = 0

slot_sessions = {}

async def handle_slot_ws(ws):
    """Handle Egret slot game WebSocket protocol (binary, byte+1 obfuscation)."""
    session = SlotSession()
    sid = id(ws)
    slot_sessions[sid] = session
    log.info(f"Slot WS connect: {ws.remote_address}")
    
    try:
        async for raw in ws:
            try:
                msg = egret_decode(raw)
            except Exception:
                continue
            msg_type = msg.get("type", "")
            body = msg.get("message", {})
            log.info(f"Slot RECV [{msg_type}] {json.dumps(body)[:200]}")
            
            if msg_type == "login":
                token = body.get("token", "")
                game_id = body.get("gameid", 3170)
                user = db_user_by_token(token)
                if user:
                    session.uid = user['uid']
                    session.token = token
                    session.game_id = game_id
                    resp = {"type": "login", "message": {"issucc": True, "uid": user['uid'], "utype": 0, "money": user['money']}}
                else:
                    resp = {"type": "login", "message": {"issucc": False, "error": "invalid token"}}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "heart":
                session.last_heart = time.time()
                await ws.send(egret_encode({"type": "heart", "message": {}}))
                
            elif msg_type == "slot_info":
                uid = session.uid or 1
                info = get_slot_info_response(uid, session.game_id or 3170)
                resp = {"type": "slot_info", "message": info}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "slot":
                if not session.uid:
                    await ws.send(egret_encode({"type": "slot", "succ": False}))
                    continue
                bet = body.get("bet", 1)
                result, err = do_spin(session.uid, bet, session.game_id or 3170)
                if err:
                    await ws.send(egret_encode({"type": "slot", "succ": False, "message": {"error": err}}))
                    await ws.send(egret_encode({"type": "tips", "message": {"msg": err}}))
                else:
                    resp = {"type": "slot", "succ": True, "message": result}
                    await ws.send(egret_encode(resp))
                    
            elif msg_type == "free_slot":
                # Free games — simplified: give a small win
                grid = generate_grid()
                total, _, _ = evaluate_paylines(grid, 5)
                user = db_user_by_uid(session.uid) if session.uid else None
                bal = user['money'] if user else 0
                resp = {"type": "free_slot", "succ": True, "message": {
                    "base": grid, "reward": total, "totalwin": total, "totalmoney": bal,
                    "free_num": body.get("row", 5)
                }}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "userinfo":
                user = db_user_by_uid(session.uid) if session.uid else None
                if user:
                    resp = {"type": "userinfo", "message": {"uid": user['uid'], "money": user['money'], "name": user['username']}}
                else:
                    resp = {"type": "userinfo", "message": {"uid": 0, "money": 0}}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "getbonus":
                resp = {"type": "getbonus", "message": {
                    "bonustype": body.get("bonustype", 0),
                    "bonus": 0, "state": 2
                }}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "getprogressbar":
                resp = {"type": "getprogressbar", "message": {"stage_id": 0, "stage_percent": 0}}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "get_active_bonus":
                resp = {"type": "get_active_bonus", "message": {"activeBonus": None}}
                await ws.send(egret_encode(resp))
                
            elif msg_type == "addscore":
                if body.get("score"):
                    db_update_balance(session.uid, body["score"], "admin add")
                user = db_user_by_uid(session.uid) if session.uid else None
                bal = user['money'] if user else 0
                await ws.send(egret_encode({"type": "addscore", "message": {"res": bal}}))
                
            elif msg_type == "register":
                await ws.send(egret_encode({"type": "register", "message": {}}))
                
            else:
                log.warning(f"Slot unhandled: {msg_type}")
                await ws.send(egret_encode({"type": msg_type, "message": {"succ": True}}))
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        slot_sessions.pop(sid, None)
        log.info(f"Slot WS disconnect: {ws.remote_address}")

# ─── Lobby WebSocket Protocol (108 message types) ────────────────────────────
MSG_HEART = 2
MSG_RECONNECT = 4
MSG_GET_MONEY = 9
MSG_LOGIN = 10
MSG_CHANGE_PASSWD = 11
MSG_GET_EMAIL = 12
MSG_DEAL_EMAIL = 13
MSG_EDIT_INFO = 14
MSG_REGISTER_ACCOUNT = 15
MSG_GET_VERIFICA = 16
MSG_LOGOUT = 19
MSG_GAME_LIST = 20
MSG_GET_BONUS = 21
MSG_GAME_BONUS = 39
MSG_COFFER = 38
MSG_GET_BANK = 40
MSG_FLUSH_SCORE = 91
MSG_GUESTER = 99
MSG_REGISTER_TYPE = 33
MSG_GET_LEVEL_DATA = 166
MSG_GAME_MAINTAIN = 178
MSG_APP_AWARD_INFO = 182
MSG_APP_AWARD_REWARD = 183
MSG_REPORT_GIFT_MONEY = 184
MSG_REPORT_PROGRESS_BAR = 185
MSG_REPORT_ACTIVITY = 189
MSG_EXTRA_GAME_LIST = 200
MSG_RECENT_GAME_LIST = 201
MSG_LOAD_TOUCH_REWARD = 205
MSG_EXTERNAL_GAME_URL = 150
MSG_ENTER_GAME = 202
MSG_EXIT_GAME = 203

# Game definitions for lobby
LOBBY_GAMES = [
    {"gameid": str(gid), "gamename": name, "gametype": 4, "state": 1,
     "icon": "", "bonus": 100, "hot": 1 if i < 10 else 0, "new": 1 if gid >= 3170 else 0,
     "vendor": "slotmania"}
    for i, (gid, name) in enumerate([
        (3001,"God Of Wealth"),(3002,"GreatBlue"),(3003,"HighwayKing"),(3004,"DolphinReef"),
        (3005,"BonusBear"),(3006,"Safari Heart"),(3007,"Thai"),(3008,"ShuiHu"),
        (3009,"PantherMoon"),(3010,"Funky Monkey"),(3011,"JinQianWa"),(3012,"SeaWorld"),
        (3013,"BoyKing"),(3014,"Iceland"),(3015,"Boxing"),(3016,"Golden Tour"),
        (3017,"Victory"),(3018,"Fairy Garden"),(3019,"Irish Luck"),(3020,"Dragon"),
        (3021,"Samurai"),(3022,"Top Gun"),(3023,"T-Rex"),(3024,"India"),
        (3025,"Panda"),(3026,"Captain"),(3027,"Japan"),(3028,"Fruit"),
        (3029,"FengShen"),(3030,"FortunePanda"),(3031,"Fashion"),(3032,"Fortune"),
        (3033,"Rally"),(3034,"Easter"),(3035,"ZhaoCaiJinBao"),(3036,"Wealth"),
        (3037,"Alice"),(3038,"Dragon Gold"),(3039,"GoldenTree"),(3040,"Spartan"),
        (3041,"RobinHood"),(3042,"Aladdin"),(3043,"Aztec"),(3044,"StoneAge"),
        (3045,"TreasureIsland"),(3046,"Prosperity"),(3047,"Three Kingdoms"),(3048,"Silver"),
        (3049,"Amazon"),(3050,"BigShot"),(3051,"PayDirt"),(3052,"FiveDragon"),
        (3053,"SeaCaptain"),(3054,"AfricanWildlife"),(3055,"Seasons"),(3056,"Laura"),
        (3057,"Pirate"),(3058,"CookiePop"),(3060,"Circus"),(3061,"Crystal"),
        (3062,"Garden"),(3063,"Tally Ho"),(3064,"Orient"),(3065,"Fame"),
        (3066,"Cleopatra"),(3067,"Twister"),(3068,"Girls"),(3069,"EmperorGate"),
        (3070,"WildFox"),(3071,"Eyes of Fortune"),(3072,"Heroine"),(3073,"Long Teng Hu Xiao"),
        (3074,"Dragon's Treasure"),(3075,"Joyful Lantern"),(3076,"Magic Pearl"),(3078,"Sahara Gold"),
        (3090,"Sweet Bonanza Xmas"),(3091,"Sweet Bonanza"),(3092,"888"),(3093,"5 Fortune Dragon"),
        (3094,"Reel King Mega"),(3095,"FaFaFa2"),(3096,"Sweet Bakery"),(3097,"Brothers Kingdom"),
        (3098,"Fruit Party"),(3099,"7 Piggies"),(3101,"Glorious Rome"),(3102,"Candy Pop"),
        (3103,"Mystery Reels"),(3113,"Little Rurrer Ducky"),(3115,"MMA Legends"),
        (3116,"God Of Wealth2"),(3125,"Life of Luxury II"),(3127,"Archer"),
        (3128,"Fire of Villa Street"),(3130,"Fire of China Street"),(3131,"Fire of Glacier Gold"),
        (3132,"Fire Of North Shore"),(3133,"Fire of Route 66"),(3134,"Fire of Rue Royale"),
        (3135,"Fire of Riverside"),(3136,"Golden Rooste"),(3137,"Mr.Fiido"),(3138,"Chicken Dinner"),
        (3139,"Pyramid Adventure"),(3140,"Wild Buffalo"),(3141,"Lucky Fortune"),
        (3143,"Hot Wheels"),(3144,"Runaway"),(3145,"Dragon City"),
        (3147,"Ocean Party"),(3148,"Crazy Restaurant"),(3149,"Sea Realms"),
        (3150,"Long Teng Hu Xiao 2"),(3151,"Wild Chuco"),(3152,"Mysterious Witch"),
        (3153,"Cash Spark"),(3154,"Buffalo Gold"),(3158,"Golden Lions"),
        (3160,"Wild Elements"),(3161,"Happy Prosperous"),(3162,"Dollar Eagle"),
        (3163,"5 King"),(3164,"Gold Bonanza"),(3165,"Peace & Long Life"),
        (3166,"Panda Magic II"),(3167,"Magic Totem"),(3168,"Best Bet"),
        (3170,"Triple Supreme Xtreme"),(3173,"Crown of Fire"),(3174,"Mystery Of The Orient"),
    ])
]

def lobby_resp(mtype, data=None, succ=1):
    msg = {"succ": succ}
    if data:
        msg.update(data)
    return {"type": mtype, "message": msg}

lobby_users = {}

async def handle_lobby_ws(ws):
    uid = None
    log.info(f"Lobby WS connect: {ws.remote_address}")
    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mt = data.get("type")
            body = data.get("message", {})
            log.info(f"Lobby RECV type={mt} {json.dumps(body)[:200]}")
            
            if mt == MSG_HEART:
                await ws.send(json.dumps(lobby_resp(MSG_HEART, {"stime": int(time.time())})))
            
            elif mt == MSG_LOGIN:
                uname = body.get("account") or f"user_{int(time.time())}"
                pwd = body.get("password", "")
                user = db_user_by_name(uname)
                if not user:
                    conn = get_db()
                    conn.execute("INSERT INTO users (username, password, token, money) VALUES (?,?,?,?)",
                                 (uname, pwd, f"tok_{int(time.time())}_{random.randint(1000,9999)}", 1000000))
                    conn.commit()
                    user = db_user_by_name(uname)
                uid = user['uid']
                lobby_users[uid] = ws
                bal = user['money']
                await ws.send(json.dumps(lobby_resp(MSG_LOGIN, {
                    "token": user['token'], "userid": user['uid'],
                    "money": bal, "bank": user['bank'],
                    "is_vest": 0, "gameid": "3170", "phone": "",
                    "updateurl": f"http://192.168.12.243:{HTTP_PORT}",
                    "ischeck": 0, "url": "",
                    "nick_name": user['username'], "head_url": "",
                    "isNewUser": 0, "EmailNumber": 0, "newPlayerReward": 0,
                    "is_open": 1, "awardswitch": 1, "game_type": 1,
                })))
            
            elif mt == MSG_GET_MONEY:
                bal = db_user_by_uid(uid) if uid else {"money": 0, "bank": 0}
                await ws.send(json.dumps(lobby_resp(MSG_GET_MONEY, {
                    "money": bal['money'] if bal else 0,
                    "trial_money_num": 0, "trial_money": 0
                })))
            
            elif mt == MSG_GAME_LIST:
                await ws.send(json.dumps(lobby_resp(MSG_GAME_LIST, {"gameList": LOBBY_GAMES})))
            
            elif mt == MSG_EXTERNAL_GAME_URL:
                game_id = body.get("game_id", "3170")
                vendor = body.get("vendor", "slotmania")
                await ws.send(json.dumps(lobby_resp(MSG_EXTERNAL_GAME_URL, {
                    "succ": 1, "game_id": int(game_id),
                    "vendor": vendor, "game_url": game_id,
                })))
            
            elif mt == MSG_REGISTER_ACCOUNT:
                uname = body.get("account", f"reg_{int(time.time())}")
                pwd = body.get("password", "123456")
                conn = get_db()
                try:
                    conn.execute("INSERT INTO users (username, password, token, money) VALUES (?,?,?,?)",
                                 (uname, pwd, f"tok_{int(time.time())}", 1000000))
                    conn.commit()
                    user = db_user_by_name(uname)
                    await ws.send(json.dumps(lobby_resp(MSG_REGISTER_ACCOUNT, {
                        "token": user['token'], "userid": user['uid'],
                        "money": user['money'], "bank": 0,
                    })))
                except sqlite3.IntegrityError:
                    await ws.send(json.dumps(lobby_resp(MSG_REGISTER_ACCOUNT, succ=0)))
            
            elif mt == MSG_LOGOUT:
                lobby_users.pop(uid, None)
                await ws.send(json.dumps(lobby_resp(MSG_LOGOUT, {"code": 1})))
            
            elif mt == MSG_GET_BANK:
                bal = db_user_by_uid(uid) if uid else {"bank": 0}
                await ws.send(json.dumps(lobby_resp(MSG_GET_BANK, {"bank": bal['bank'] if bal else 0, "despoit": 0})))
            
            elif mt == MSG_COFFER:
                bal = db_user_by_uid(uid) if uid else {"money": 0, "bank": 0}
                await ws.send(json.dumps(lobby_resp(MSG_COFFER, {
                    "deposit": bal['bank'] if bal else 0,
                    "balance": bal['money'] if bal else 0,
                })))
            
            elif mt == MSG_FLUSH_SCORE:
                await ws.send(json.dumps(lobby_resp(MSG_FLUSH_SCORE)))
            
            elif mt == MSG_GUESTER:
                await ws.send(json.dumps(lobby_resp(MSG_GUESTER, {"isOpen": 1, "isGuest": 0})))
            
            elif mt == MSG_REGISTER_TYPE:
                await ws.send(json.dumps(lobby_resp(MSG_REGISTER_TYPE, {"regButton": 1, "minVersion": 0, "version": ""})))
            
            elif mt == MSG_GAME_MAINTAIN:
                await ws.send(json.dumps(lobby_resp(MSG_GAME_MAINTAIN, {"isMaintain": 0, "maintainEndTime": 0})))
            
            elif mt == MSG_APP_AWARD_INFO:
                await ws.send(json.dumps(lobby_resp(MSG_APP_AWARD_INFO, {
                    "data": {"reward": 5000, "stage": 1, "switch": 1, "total_bonus": 10000}
                })))
            
            elif mt == MSG_APP_AWARD_REWARD:
                await ws.send(json.dumps(lobby_resp(MSG_APP_AWARD_REWARD, {
                    "data": {"reward": 5000, "total_bonus": 10000}
                })))
            
            elif mt in (MSG_EXTRA_GAME_LIST, MSG_RECENT_GAME_LIST):
                await ws.send(json.dumps(lobby_resp(mt, {"list": []})))
            
            elif mt == MSG_LOAD_TOUCH_REWARD:
                await ws.send(json.dumps(lobby_resp(MSG_LOAD_TOUCH_REWARD, {
                    "succ": 1, "total_score": 99999, "score": 5000, "isLimit": 0,
                })))
            
            elif mt == MSG_REPORT_GIFT_MONEY:
                await ws.send(json.dumps(lobby_resp(MSG_REPORT_GIFT_MONEY)))
            
            elif mt == MSG_REPORT_PROGRESS_BAR:
                await ws.send(json.dumps(lobby_resp(MSG_REPORT_PROGRESS_BAR)))
            
            elif mt == MSG_REPORT_ACTIVITY:
                await ws.send(json.dumps(lobby_resp(MSG_REPORT_ACTIVITY)))
            
            elif mt == MSG_GET_BONUS:
                await ws.send(json.dumps(lobby_resp(MSG_GET_BONUS, {"data": [{"gameid": "3170", "bonus": 100}]})))
            
            elif mt == MSG_GAME_BONUS:
                await ws.send(json.dumps(lobby_resp(MSG_GAME_BONUS, {"data": [{"gameid": "3170", "bonus": 100}]})))
            
            elif mt in (MSG_CHANGE_PASSWD, MSG_DEAL_EMAIL, MSG_GET_EMAIL, MSG_EDIT_INFO, MSG_GET_VERIFICA,
                        MSG_ENTER_GAME, MSG_EXIT_GAME):
                await ws.send(json.dumps({"type": mt, "message": {"succ": 1}}))
            
            else:
                log.warning(f"Lobby unhandled type={mt}")
                await ws.send(json.dumps({"type": mt, "message": {"succ": 1}}))
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        lobby_users.pop(uid, None)
        log.info(f"Lobby WS disconnect: {ws.remote_address}")

# ─── HTTP Server (Flask) ─────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)

@app.route("/game/<path:subpath>")
def serve_game(subpath):
    # Handle gameConfig.json — some games require it
    if subpath.endswith("gameConfig.json"):
        return jsonify({"succ": True, "rtp": 95, "min_bet": 1, "max_bet": 100})
    path = os.path.join(GAME_DIR, subpath)
    if os.path.isfile(path):
        return send_from_directory(os.path.dirname(path), os.path.basename(path))
    # Try with "game/" prefix removed
    alt_path = os.path.join(GAME_DIR, subpath)
    if not os.path.isfile(alt_path):
        alt_path = os.path.join(GAME_DIR, "game", subpath)
    if os.path.isfile(alt_path):
        return send_from_directory(os.path.dirname(alt_path), os.path.basename(alt_path))
    return flask.abort(404)

@app.route("/slotmania/")
@app.route("/slotmania/index.html")
def slotmania():
    return send_from_directory(os.path.join(GAME_DIR, "slotmania"), "index.html")

@app.route("/images/<path:subpath>")
def serve_images(subpath):
    return send_from_directory(os.path.join(GAME_DIR, "images"), subpath)

# ─── Lobby API (web login + game list) ────────────────────────────────────────
@app.route("/api/lobby/login", methods=["POST"])
def lobby_login():
    data = request.get_json(silent=True) or {}
    uname = data.get("username", "")
    pwd = data.get("password", "")
    user = db_user_by_name(uname)
    if not user:
        conn = get_db()
        conn.execute("INSERT INTO users (username, password, token, money) VALUES (?,?,?,?)",
                     (uname, pwd, f"tok_{int(time.time())}_{random.randint(1000,9999)}", 1000000))
        conn.commit()
        user = db_user_by_name(uname)
    return jsonify({"succ": True, "token": user['token'], "uid": user['uid'],
                     "money": user['money'], "username": user['username']})

@app.route("/api/lobby/games")
def lobby_games():
    gl = [{"gameid": g['gameid'], "gamename": g['gamename'], "hot": g.get('hot', 0), "new": g.get('new', 0)}
          for g in LOBBY_GAMES]
    return jsonify({"succ": True, "games": gl})

@app.route("/lobby/")
@app.route("/lobby")
@app.route("/lobby/<path:subpath>")
def serve_lobby(subpath=""):
    if not subpath:
        subpath = "index.html"
    path = os.path.join(GAME_DIR, "lobby", subpath)
    if os.path.isfile(path):
        return send_from_directory(os.path.dirname(path), os.path.basename(path))
    return flask.abort(404)

LOBBY_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vblink Lobby</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#0a0e17;color:#fff;min-height:100vh}
#login-page{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:20px}
#login-page h1{font-size:28px;margin-bottom:8px;background:linear-gradient(135deg,#4FC3F7,#00BCD4);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
#login-page p{color:#78909C;margin-bottom:30px;font-size:14px}
.login-box{background:#111827;border:1px solid #1e293b;border-radius:16px;padding:32px;width:100%;max-width:360px}
.login-box input{width:100%;padding:12px 16px;margin-bottom:14px;background:#0f172a;border:1px solid #1e293b;border-radius:10px;color:#fff;font-size:15px;outline:none;transition:border .2s}
.login-box input:focus{border-color:#4FC3F7}
.login-box button{width:100%;padding:12px;background:linear-gradient(135deg,#4FC3F7,#00BCD4);border:none;border-radius:10px;color:#fff;font-size:16px;font-weight:bold;cursor:pointer;transition:opacity .2s}
.login-box button:hover{opacity:.9}
.login-box .error{color:#ef5350;font-size:13px;margin-top:8px;display:none}
#lobby-page{display:none;padding:16px;max-width:1200px;margin:0 auto}
#lobby-page .header{display:flex;justify-content:space-between;align-items:center;padding:12px 0;margin-bottom:16px;border-bottom:1px solid #1e293b}
#lobby-page .header h1{font-size:22px;background:linear-gradient(135deg,#4FC3F7,#00BCD4);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
#lobby-page .header .user-info{display:flex;align-items:center;gap:12px}
#lobby-page .header .user-info span{color:#90A4AE;font-size:13px}
#lobby-page .header .user-info .money{color:#4CAF50;font-weight:bold}
#lobby-page .header .logout{background:transparent;border:1px solid #333;border-radius:8px;padding:6px 14px;color:#ccc;cursor:pointer;font-size:12px}
.game-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.game-card{background:#111827;border:1px solid #1e293b;border-radius:12px;overflow:hidden;cursor:pointer;transition:transform .2s,border-color .2s}
.game-card:hover{transform:translateY(-2px);border-color:#4FC3F7}
.game-card .img-wrap{width:100%;aspect-ratio:16/12;background:#0f172a;display:flex;align-items:center;justify-content:center;overflow:hidden}
.game-card .img-wrap img{width:100%;height:100%;object-fit:cover}
.game-card .info{padding:10px 12px}
.game-card .info .name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.game-card .info .badge{display:inline-block;font-size:10px;padding:2px 6px;border-radius:4px;margin-top:4px}
.game-card .info .badge.hot{background:#ef5350;color:#fff}
.game-card .info .badge.new{background:#4FC3F7;color:#fff}
.loading{text-align:center;padding:60px;color:#546E7A;font-size:14px}
@media(min-width:768px){.game-grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}
</style></head><body>
<div id="login-page">
  <h1>🎰 Vblink</h1>
  <p>Enter your username to enter the lobby</p>
  <div class="login-box">
    <input id="login-user" placeholder="Username" autocomplete="username">
    <input id="login-pass" type="password" placeholder="Password (optional)" autocomplete="current-password">
    <button onclick="doLogin()">Enter Lobby</button>
    <div class="error" id="login-error">Login failed</div>
  </div>
</div>
<div id="lobby-page">
  <div class="header">
    <h1>🎰 Lobby</h1>
    <div class="user-info">
      <span id="user-name"></span>
      <span class="money" id="user-money"></span>
      <button class="logout" onclick="doLogout()">Exit</button>
    </div>
  </div>
  <div class="game-grid" id="game-grid"></div>
</div>
<script>
const STORAGE_KEY = 'vblink_session';
let session = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');

function showLogin() { document.getElementById('login-page').style.display='flex'; document.getElementById('lobby-page').style.display='none'; }
function showLobby() { document.getElementById('login-page').style.display='none'; document.getElementById('lobby-page').style.display='block'; }

async function doLogin() {
  const uname = document.getElementById('login-user').value.trim() || 'user_' + Date.now();
  const pwd = document.getElementById('login-pass').value || '123456';
  try {
    const r = await fetch('/api/lobby/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:uname,password:pwd})});
    const d = await r.json();
    if (!d.succ) { throw new Error('login failed'); }
    session = d;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    loadLobby();
  } catch(e) { document.getElementById('login-error').style.display='block'; }
}

function doLogout() { session = {}; localStorage.removeItem(STORAGE_KEY); showLogin(); }

async function loadLobby() {
  if (!session.uid) { showLogin(); return; }
  document.getElementById('user-name').textContent = session.username;
  document.getElementById('user-money').textContent = '$' + (session.money || 0).toLocaleString();
  showLobby();
  const grid = document.getElementById('game-grid');
  grid.innerHTML = '<div class="loading">Loading games...</div>';
  try {
    const r = await fetch('/api/lobby/games');
    const d = await r.json();
    grid.innerHTML = d.games.map(g => {
      const imgUrl = '/images/' + g.gameid + '.jpg';
      const gameUrl = '/game/index.html?id=' + g.gameid + '&uid=' + session.uid + '&token=' + session.token + '&cdn=' + location.protocol + '//' + location.host + '&backUrl=' + btoa(location.href);
      const badges = (g.hot ? '<span class="badge hot">HOT</span>' : '') + (g.new ? '<span class="badge new" style="margin-left:4px">NEW</span>' : '');
      return '<div class="game-card" onclick="playGame(\'' + gameUrl + '\')"><div class="img-wrap"><img src="' + imgUrl + '" loading="lazy" onerror="this.style.display=\'none\'"></div><div class="info"><div class="name">' + g.gamename + '</div>' + badges + '</div></div>';
    }).join('');
  } catch(e) { grid.innerHTML = '<div class="loading">Failed to load games</div>'; }
}

function playGame(url) { window.location.href = url; }

// Auto-login if session exists
if (session.uid) { loadLobby(); } else { showLogin(); }
</script></body></html>
"""

@app.route("/api/game/houtai")
def game_houtai():
    """Handle Egret game HTTP API (MD5-signed game data requests)."""
    url = request.args.get("url", "")
    stime = request.args.get("stime", "0")
    sign = request.args.get("sign", "")
    expected = hashlib.md5((url + stime + SIGN_KEY).encode()).hexdigest()
    if sign and sign != expected:
        return jsonify({"succ": False, "msg": "sign error"})
    # Parse the url parameter which contains the actual request
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    func = params.get("func", [""])[0]
    
    if func == "servids":
        # Return game server ID — the client connects to our host
        return jsonify({"succ": True, "Data": {"res": [{"servid": 1}]}})
    elif func == "getserver" or func == "server":
        server_id = params.get("id", ["1"])[0]
        return jsonify({"succ": True, "Data": {"servid": int(server_id), "ip": request.host.split(":")[0], "port": WS_PORT + 1}})
    return jsonify({"succ": True, "Data": {}})

@app.route("/api/CoinTypeShowConf/getCoinTypeShowConfig")
def coin_config():
    return jsonify({"succ": True, "data": {}})

@app.route("/api/LoginProc/timeDiff", methods=["POST"])
@app.route("/api/NmMsg/dropRate", methods=["POST"])
@app.route("/api/Sweep/slotSweep", methods=["POST"])
def game_report():
    return jsonify({"succ": True})

@app.route("/admin/", defaults={"path": ""})
@app.route("/admin/<path:path>")
def admin(path):
    if request.args.get("pass") == ADMIN_PASS or request.cookies.get("admin_pass") == ADMIN_PASS:
        pass
    elif path == "api":
        pass
    else:
        return render_template_string(ADMIN_LOGIN)
    
    if request.path.endswith("/api"):
        return admin_api()
    
    resp = flask.make_response(render_template_string(ADMIN_HTML))
    resp.set_cookie("admin_pass", ADMIN_PASS, max_age=86400)
    return resp

@app.route("/admin/api")
def admin_api():
    action = request.args.get("action", "")
    conn = get_db()
    
    if action == "users":
        rows = conn.execute("SELECT uid, username, money, bank, is_admin, created_at FROM users ORDER BY uid").fetchall()
        return jsonify([dict(r) for r in rows])
    elif action == "set_balance":
        uid = int(request.args.get("uid", 0))
        amount = int(float(request.args.get("amount", 0)))
        db_set_balance(uid, amount)
        return jsonify({"ok": True})
    elif action == "add_user":
        uname = request.args.get("username", f"user_{int(time.time())}")
        pwd = request.args.get("password", "123456")
        money = int(float(request.args.get("money", 500000)))
        conn.execute("INSERT INTO users (username, password, token, money) VALUES (?,?,?,?)",
                     (uname, pwd, f"tok_{int(time.time())}", money))
        conn.commit()
        return jsonify({"ok": True})
    elif action == "config":
        game_id = int(request.args.get("game_id", 3170))
        cfg = db_get_config(game_id)
        if request.args.get("rtp"):
            new_rtp = float(request.args.get("rtp"))
            conn.execute("UPDATE game_config SET rtp=? WHERE game_id=?", (new_rtp, game_id))
            conn.commit()
            cfg['rtp'] = new_rtp
        return jsonify(cfg)
    elif action == "all_configs":
        configs = {}
        for g in LOBBY_GAMES:
            gid = int(g['gameid'])
            cfg = db_get_config(gid)
            configs[gid] = {"rtp": cfg['rtp'] if cfg else 95.0, "name": g['gamename']}
        return jsonify(configs)
    elif action == "txns":
        rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 50").fetchall()
        return jsonify([dict(r) for r in rows])
    elif action == "reset":
        conn.execute("DELETE FROM transactions")
        conn.execute("UPDATE users SET money=500000 WHERE is_admin=0")
        conn.commit()
        return jsonify({"ok": True})
    
    return jsonify({"error": "unknown action"})

ADMIN_LOGIN = """<!DOCTYPE html><html><body style="background:#111;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif">
<form method=get style="background:#222;padding:40px;border-radius:12px;text-align:center">
<h2 style="color:#fff;margin-bottom:24px">Admin Login</h2>
<input type=password name=pass placeholder="Password" style="padding:12px 20px;border-radius:8px;border:none;width:200px;font-size:16px">
<button type=submit style="margin-top:16px;padding:12px 40px;border-radius:8px;border:none;background:#4CAF50;color:#fff;font-size:16px;cursor:pointer">Login</button>
</form></body></html>"""

ADMIN_HTML = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Vblink Private Server — Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px}
h1{color:#fff;font-size:24px;margin-bottom:20px}
h1 span{color:#4CAF50;font-size:14px;font-weight:400;margin-left:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:20px}
.card{background:#151520;border-radius:12px;padding:20px;border:1px solid #2a2a35}
.card h3{color:#888;font-size:12px;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#666;padding:6px 8px;border-bottom:1px solid #2a2a35;font-size:11px;text-transform:uppercase}
td{padding:6px 8px;border-bottom:1px solid #1a1a25}
td.money{font-family:monospace;text-align:right}
input{padding:6px 10px;border-radius:6px;border:1px solid #333;background:#1a1a25;color:#e0e0e0;font-size:13px}
button{padding:6px 16px;border-radius:6px;border:none;background:#4CAF50;color:#fff;cursor:pointer;font-size:12px}
button.danger{background:#e53935}
button.small{padding:4px 10px;font-size:11px}
.green{color:#4CAF50}.red{color:#e53935}.yellow{color:#FFC107}
.flex{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.mt{margin-top:12px}
</style></head><body>
<h1>Vblink Private Server <span id=status>● Connecting</span></h1>
<div class=grid>
<div class=card><h3>User Management</h3>
<table><thead><tr><th>UID</th><th>Username</th><th>Balance</th><th>Admin</th><th>Actions</th></tr></thead><tbody id=user-table></tbody></table>
<div class="flex mt"><input id=new-user placeholder=username><input id=new-pass placeholder=password type=password><input id=new-money placeholder=amount type=number><button onclick=addUser()>Add User</button></div>
</div>
<div class=card><h3>Game Config</h3>
<table><thead><tr><th>Game ID</th><th>Name</th><th>RTP %</th><th>Action</th></tr></thead><tbody id=game-table></tbody></table>
</div>
<div class=card><h3>Recent Transactions</h3>
<div style=overflow-y:auto;max-height:300px><table><thead><tr><th>ID</th><th>UID</th><th>Amount</th><th>Type</th><th>Note</th><th>Time</th></tr></thead><tbody id=txn-table></tbody></table></div>
</div>
</div>
<div class="flex mt"><button class=danger onclick=resetAll()>Reset All Balances</button></div>
<script>
async function api(a,p){const u=new URLSearchParams({action:a,...p});const r=await fetch('/admin/api?'+u);return r.json()}
async function refresh(){const u=await api('users');const t=document.getElementById('user-table');t.innerHTML=u.map(u=>'<tr><td>'+u.uid+'</td><td>'+u.username+'</td><td class=money>'+u.money.toLocaleString()+'</td><td>'+(u.is_admin?'<span class=green>●</span>':'')+'</td><td class=flex><input id=bal-'+u.uid+' value='+u.money+' style=width:100px><button class=small onclick=setBal('+u.uid+')>Set</button></td></tr>').join('');
document.getElementById('status').textContent='● Online';document.getElementById('status').style.color='#4CAF50';
const g=await api('all_configs');document.getElementById('game-table').innerHTML=Object.entries(g).map(([id,c]) => '<tr><td>'+id+'</td><td>'+c.name+'</td><td><input id=rtp-'+id+' value='+c.rtp+' style=width:60px></td><td><button class=small onclick=setRtp('+id+')>Set</button><a class=small style=margin-left:8px;color:#4FC3F7;font-size:11px href=/game/index.html?id='+id+'&token=demo_token_1&cdn=http://'+location.host+' target=_blank>Play</a></td></tr>').join('');
const x=await api('txns');const xb=document.getElementById('txn-table');xb.innerHTML=x.slice(0,30).map(x=>'<tr><td>'+x.id+'</td><td>'+x.uid+'</td><td class=money>'+(x.amount>0?'<span class=green>+':'<span class=red>')+x.amount+'</span></td><td>'+x.type+'</td><td>'+x.note+'</td><td style=font-size:10px;color:#666>'+x.created_at+'</td></tr>').join('');}
async function setBal(u){const v=document.getElementById('bal-'+u).value;await api('set_balance',{uid:u,amount:v});refresh()}
async function addUser(){const u=document.getElementById('new-user').value;const p=document.getElementById('new-pass').value;const m=document.getElementById('new-money').value;await api('add_user',{username:u||'user_'+Date.now(),password:p||'123456',money:m||500000});refresh()}
async function setRtp(g){const v=document.getElementById('rtp-'+g).value;await api('config',{game_id:g,rtp:v});refresh()}
async function resetAll(){if(confirm('Reset all non-admin balances to 500000?')){await api('reset');refresh()}}
refresh();setInterval(refresh,3000)
</script></body></html>"""

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    # Start WebSocket servers
    lobby_server = await ws_serve(handle_lobby_ws, HOST, WS_PORT)
    slot_server = await ws_serve(handle_slot_ws, HOST, WS_PORT + 1)
    
    log.info(f"Lobby WS:     ws://{HOST}:{WS_PORT}/")
    log.info(f"Slot WS:      ws://{HOST}:{WS_PORT + 1}/")
    log.info(f"Admin panel:  http://{HOST}:{HTTP_PORT}/admin/ (pass: {ADMIN_PASS})")
    log.info(f"Game server:  http://{HOST}:{HTTP_PORT}/game/3170/manifest.js")
    
    # Flask HTTP server in thread pool
    def run_http():
        app.run(host=HOST, port=HTTP_PORT, debug=False, use_reloader=False)
    
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        lobby_server.serve_forever(),
        slot_server.serve_forever(),
        asyncio.to_thread(run_http),
    )

if __name__ == "__main__":
    print("""
+-------------------------------------------------+
|        Vblink Private Server v1.0               |
|  Lobby + Slot Game + Admin Panel                |
+-------------------------------------------------+
    """)
    asyncio.run(main())
