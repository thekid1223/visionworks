"""Chess Analyst — uses chess.com API to pull real game state."""
from __future__ import annotations
import json, logging, re, time
from urllib.request import Request, urlopen
from urllib.error import URLError

log = logging.getLogger("kai_prime.chess")

CHESS_COM_HEADERS = {
    "User-Agent": "KaiPrime/2.0 (AI Assistant)",
    "Accept": "application/json",
}


def _fetch(url: str, timeout: int = 10) -> dict | None:
    try:
        req = Request(url, headers=CHESS_COM_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("chess.com fetch failed: %s", e)
        return None


def get_player_profile(username: str) -> str:
    data = _fetch(f"https://api.chess.com/pub/player/{username.lower()}")
    if not data:
        return f"Could not find player '{username}' on chess.com"
    stats = data.get("stats", {})
    ratings = {}
    for key in ["chess_bullet", "chess_blitz", "chess_rapid", "chess_daily"]:
        if key in stats:
            rt = stats[key].get("last", {})
            ratings[key.replace("chess_", "")] = rt.get("rating", "?")
    status = "online" if data.get("online") else "offline"
    return (
        f"Player: {data.get('username', username)}\n"
        f"Title: {data.get('title', 'None')}\n"
        f"Status: {status}\n"
        f"Ratings: {json.dumps(ratings)}\n"
        f"URL: {data.get('url', 'N/A')}"
    )


def get_current_games(username: str) -> str:
    data = _fetch(f"https://api.chess.com/pub/player/{username.lower()}/games/archives")
    if not data or not data.get("archives"):
        return f"No game archives found for '{username}'"
    latest = data["archives"][-1]
    games_data = _fetch(latest)
    if not games_data or not games_data.get("games"):
        return "No recent games found"
    games = games_data["games"]
    results = []
    for g in games[-3:]:
        wp = g.get("white", {}).get("username", "?")
        bp = g.get("black", {}).get("username", "?")
        wr = g.get("white", {}).get("result", "?")
        br = g.get("black", {}).get("result", "?")
        tc = g.get("time_class", "?")
        results.append(f"  {wp} (white, {wr}) vs {bp} (black, {br}) [{tc}]")
    return f"Recent games:\n" + "\n".join(results)


def analyze_game_pgn(pgn: str) -> str:
    moves = re.findall(r'\d+\.\s*(\S+)\s*(\S+)?', pgn)
    total = len(moves)
    if total == 0:
        return "No moves found in PGN"
    last_move = moves[-1]
    turn_num = total
    is_white_turn = len(moves) % 2 == 1
    turn = "White" if is_white_turn else "Black"
    return (
        f"Total moves: {total}\n"
        f"Current turn: {turn} (move {turn_num})\n"
        f"Last move: {last_move[0]}" + (f" {last_move[1]}" if last_move[1] else "") +
        f"\nPGN:\n{pgn[:500]}"
    )


TOOLS = {
    "chess_profile": {
        "description": "Look up a chess.com player profile, ratings, and online status",
        "function": get_player_profile,
        "params": {"username": "str"},
    },
    "chess_games": {
        "description": "Get recent games from a chess.com player",
        "function": get_current_games,
        "params": {"username": "str"},
    },
    "chess_analyze_pgn": {
        "description": "Analyze a chess game PGN string — counts moves, identifies current turn",
        "function": analyze_game_pgn,
        "params": {"pgn": "str"},
    },
}
