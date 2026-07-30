"""
Custom game server that mimics the real game backend.
Intercepts and modifies award/balance messages.
"""
import asyncio, json, logging, time, random
from websockets.asyncio.server import serve

HOST = "0.0.0.0"
PORT = 8888

# Protocol message types
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
MSG_REGISTER_TYPE = 33
MSG_COFFER = 38
MSG_GAME_BONUS = 39
MSG_GET_BANK = 40
MSG_FLUSH_SCORE = 91
MSG_GUESTER = 99
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

# Inflated values (100x real)
INFLATE = 100

logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")
log = logging.getLogger("game-server")

# User state
users = {}
game_id_counter = 0

def make_response(msg_type, data=None, succ=1):
    msg = {"succ": succ}
    if data:
        msg.update(data)
    return {"type": msg_type, "message": msg}

async def handle_client(ws):
    log.info(f"New connection from {ws.remote_address}")
    user_id = None

    async for raw_msg in ws:
        try:
            data = json.loads(raw_msg)
            msg_type = data.get("type")
            msg_body = data.get("message", {})
            log.info(f"RECV type={msg_type} body={json.dumps(msg_body, ensure_ascii=False)[:300]}")

            if msg_type == MSG_HEART:
                await ws.send(json.dumps(make_response(MSG_HEART, {"stime": int(time.time())})))

            elif msg_type == MSG_RECONNECT:
                await ws.send(json.dumps(make_response(MSG_RECONNECT)))

            elif msg_type == MSG_GET_MONEY:
                user_id = user_id or "guest_1"
                bal = users.setdefault(user_id, {"money": 10000, "bank": 50000})
                await ws.send(json.dumps(make_response(MSG_GET_MONEY, {
                    "money": bal["money"] * INFLATE,
                    "trial_money_num": 0,
                    "trial_money": 0
                })))

            elif msg_type == MSG_LOGIN:
                user_id = msg_body.get("account") or f"user_{int(time.time())}"
                users.setdefault(user_id, {"money": 10000, "bank": 50000, "token": f"tok_{int(time.time())}"})
                user_data = users[user_id]
                game_id_counter = 3113
                await ws.send(json.dumps(make_response(MSG_LOGIN, {
                    "token": user_data["token"],
                    "userid": hash(user_id) % 100000,
                    "money": user_data["money"] * INFLATE,
                    "bank": user_data["bank"] * INFLATE,
                    "is_vest": 0,
                    "gameid": str(game_id_counter),
                    "phone": "",
                    "updateurl": "",
                    "ischeck": 0,
                    "url": "",
                    "nick_name": "Player",
                    "head_url": "",
                    "isNewUser": 0,
                    "EmailNumber": 0,
                    "newPlayerReward": 0,
                    "is_open": 1,
                    "awardswitch": 1,
                    "game_type": 1,
                })))

            elif msg_type == MSG_REGISTER_ACCOUNT:
                await ws.send(json.dumps(make_response(MSG_REGISTER_ACCOUNT, {
                    "token": f"reg_tok_{int(time.time())}",
                    "userid": random.randint(10000, 99999),
                    "money": 10000 * INFLATE,
                    "bank": 0,
                })))

            elif msg_type == MSG_LOGOUT:
                await ws.send(json.dumps(make_response(MSG_LOGOUT, {"code": 1})))

            elif msg_type == MSG_GAME_LIST:
                await ws.send(json.dumps(make_response(MSG_GAME_LIST, {
                    "gameList": [{
                        "gameid": "3113",
                        "gamename": "Test Game",
                        "gametype": 1,
                        "gameicon": "",
                        "state": 1,
                        "bonus": 100,
                        "hot": 1,
                        "new": 1,
                    }]
                })))

            elif msg_type == MSG_REGISTER_TYPE:
                await ws.send(json.dumps(make_response(MSG_REGISTER_TYPE, {
                    "regButton": 1,
                    "minVersion": 0,
                    "version": "",
                })))

            elif msg_type == MSG_COFFER:
                bal = users.get(user_id, {"money": 10000, "bank": 50000})
                await ws.send(json.dumps(make_response(MSG_COFFER, {
                    "deposit": bal["bank"] * INFLATE,
                    "balance": bal["money"] * INFLATE,
                })))

            elif msg_type == MSG_GET_BANK:
                bal = users.get(user_id, {"money": 10000, "bank": 50000})
                await ws.send(json.dumps(make_response(MSG_GET_BANK, {
                    "bank": bal["bank"] * INFLATE,
                    "despoit": bal["bank"] * INFLATE,
                })))

            elif msg_type == MSG_FLUSH_SCORE:
                await ws.send(json.dumps(make_response(MSG_FLUSH_SCORE)))

            elif msg_type == MSG_GAME_MAINTAIN:
                await ws.send(json.dumps(make_response(MSG_GAME_MAINTAIN, {
                    "isMaintain": 0,
                    "maintainEndTime": 0,
                })))

            elif msg_type == MSG_APP_AWARD_INFO:
                # Return award info with inflated values
                await ws.send(json.dumps(make_response(MSG_APP_AWARD_INFO, {
                    "data": {
                        "reward": 5000 * INFLATE,
                        "stage": 1,
                        "switch": 1,
                        "total_bonus": 10000 * INFLATE,
                    }
                })))

            elif msg_type == MSG_APP_AWARD_REWARD:
                # Claim award - return success with inflated reward
                await ws.send(json.dumps(make_response(MSG_APP_AWARD_REWARD, {
                    "data": {
                        "reward": 5000 * INFLATE,
                        "total_bonus": 10000 * INFLATE,
                    }
                })))

            elif msg_type == MSG_GET_LEVEL_DATA:
                await ws.send(json.dumps(make_response(MSG_GET_LEVEL_DATA, {
                    "level": 1,
                    "exp": 0,
                    "is_show": 1,
                })))

            elif msg_type == MSG_GUESTER:
                await ws.send(json.dumps(make_response(MSG_GUESTER, {
                    "isOpen": 1,
                    "isGuest": 0,
                })))

            elif msg_type in (MSG_EXTRA_GAME_LIST, MSG_RECENT_GAME_LIST):
                await ws.send(json.dumps(make_response(msg_type, {"list": []})))

            elif msg_type == MSG_LOAD_TOUCH_REWARD:
                await ws.send(json.dumps(make_response(MSG_LOAD_TOUCH_REWARD, {
                    "succ": 1,
                    "total_score": 99999 * INFLATE,
                    "score": 5000 * INFLATE,
                    "isLimit": 0,
                })))

            elif msg_type == MSG_REPORT_GIFT_MONEY:
                await ws.send(json.dumps(make_response(MSG_REPORT_GIFT_MONEY)))

            elif msg_type == MSG_REPORT_PROGRESS_BAR:
                await ws.send(json.dumps(make_response(MSG_REPORT_PROGRESS_BAR)))

            elif msg_type == MSG_REPORT_ACTIVITY:
                await ws.send(json.dumps(make_response(MSG_REPORT_ACTIVITY)))

            elif msg_type == MSG_GET_BONUS:
                await ws.send(json.dumps(make_response(MSG_GET_BONUS, {
                    "data": [{"gameid": "3113", "bonus": 100}]
                })))

            elif msg_type == MSG_GAME_BONUS:
                await ws.send(json.dumps(make_response(MSG_GAME_BONUS, {
                    "data": [{"gameid": "3113", "bonus": 100}]
                })))

            else:
                # Unknown message - return generic success
                log.warning(f"UNHANDLED type={msg_type}, body={json.dumps(msg_body, ensure_ascii=False)[:200]}")
                await ws.send(json.dumps({"type": msg_type, "message": {"succ": 1}}))

        except json.JSONDecodeError:
            log.error(f"Invalid JSON: {raw_msg[:200]}")
        except Exception as e:
            log.error(f"Error handling message: {e}")
            import traceback
            traceback.print_exc()

    log.info(f"Client disconnected: {ws.remote_address}")

async def main():
    server = await serve(handle_client, HOST, PORT)
    log.info(f"Game server listening on ws://{HOST}:{PORT}")
    log.info(f"Inflating values by {INFLATE}x")
    log.info("Waiting for connections...")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
