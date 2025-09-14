from __future__ import annotations
from flask import Flask, render_template, request, jsonify
import csv, datetime, hashlib, os, unicodedata, random
from typing import Dict, List, Tuple, Any

DATA_CSV = os.path.join(os.path.dirname(__file__), "kbl_players_2025.csv")
MAX_GUESSES = 9
app = Flask(__name__, static_folder="static", static_url_path="")

CURRENT_ANSWER_IDX = None

def reset_answer():
    global CURRENT_ANSWER_IDX
    if PLAYERS:
        CURRENT_ANSWER_IDX = random.randrange(0, len(PLAYERS))
    else:
        CURRENT_ANSWER_IDX = None

def age_of(p: Dict[str, Any]):
    """CSV에 birth_year가 있으면 그걸로, 없으면 age 필드 숫자를 그대로 사용."""
    try:
        by = str(p.get("birth_year","")).strip()
        if by:
            return this_year_utc() - int(by)
    except Exception:
        pass
    try:
        # 선택적으로 age 열을 직접 채워두면 그 값을 사용
        a = str(p.get("age","")).strip()
        if a:
            return int(a)
    except Exception:
        pass
    return None

def now_utc_date_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

def this_year_utc() -> int:
    return datetime.datetime.now(datetime.timezone.utc).year

def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    s = s.replace(" ", "").lower()
    return s

def within(v1: int, v2: int, d: int) -> bool:
    try:
        return abs(int(v1) - int(v2)) <= d
    except Exception:
        return False

def height_tens_equal(h1: Any, h2: Any) -> bool:
    try:
        return int(h1) // 10 == int(h2) // 10
    except Exception:
        return False

def pos_group(pos: str) -> str:
    p = (pos or "").upper()
    if "C" in p:
        return "C"
    if "F" in p and "G" in p:
        return "F"
    if "F" in p:
        return "F"
    return "G"

def draft_tuple(p: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(p.get("draft_year", "") or ""),
        str(p.get("draft_type", "") or ""),
        str(p.get("draft_round", "") or ""),
        str(p.get("draft_overall", "") or ""),
    )

def draft_yellow(g: Dict[str, Any], a: Dict[str, Any]) -> bool:
    # 노란불: 같은 라운드(예: 1R vs 1R)이고 드래프트 타입도 동일할 때
    gt, at = str(g.get("draft_type", "") or ""), str(a.get("draft_type", "") or "")
    gr, ar = str(g.get("draft_round", "") or ""), str(a.get("draft_round", "") or "")
    if not gt or not at or not gr or not ar:
        return False
    return (gt == at) and (gr == ar)

def load_players(csv_path: str):
    players: List[Dict[str, Any]] = []
    team_roster: Dict[str, List[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            row = { (k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() }
            for k in ["name","team","number","position","height_cm","birth_year","age","player_type","draft_year","draft_type","draft_round","draft_overall"]:
                row.setdefault(k, "")
            players.append(row)
            team_roster.setdefault(row["team"], []).append(f'{row["name"]}({row["number"]})')
    for t in team_roster:
        team_roster[t].sort()
    return players, team_roster

PLAYERS, TEAM_ROSTER = load_players(DATA_CSV)
NAME2IDX: Dict[str,int] = {p["name"]: i for i, p in enumerate(PLAYERS)}
NORMNAME2IDX: Dict[str,int] = {normalize_name(p["name"]): i for i, p in enumerate(PLAYERS)}

def todays_index(total: int) -> int:
    today = now_utc_date_str()
    h = int(hashlib.sha256(today.encode("utf-8")).hexdigest(), 16)
    return h % total if total > 0 else 0

def answer_player() -> Dict[str, Any]:
    # 페이지 새로고침(= / 요청) 때마다 reset_answer()로 랜덤 선정
    # 그 외에는 같은 인덱스를 유지하여 한 판 동안 정답이 바뀌지 않도록 함
    global CURRENT_ANSWER_IDX
    if CURRENT_ANSWER_IDX is None:
        reset_answer()
    return PLAYERS[CURRENT_ANSWER_IDX]

@app.route("/")
def index():
    reset_answer()
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify({"max_guesses": MAX_GUESSES})

@app.route("/api/players")
def api_players():
    return jsonify([p["name"] for p in PLAYERS])

@app.route("/api/teams")
def api_teams():
    return jsonify(TEAM_ROSTER)

def compare_fields(guess: Dict[str, Any], ans: Dict[str, Any]) -> Dict[str,str]:
    out: Dict[str,str] = {}
    out["team"] = "green" if (guess.get("team","")==ans.get("team","")) else "black"
    try:
        gn, an = int(guess.get("number",0)), int(ans.get("number",0))
        out["number"] = "green" if gn==an else ("yellow" if within(gn,an,2) else "black")
    except Exception:
        out["number"]="black"
    gp, ap = (guess.get("position","") or ""), (ans.get("position","") or "")
    out["position"] = "green" if (gp and gp==ap) else ("yellow" if pos_group(gp)==pos_group(ap) else "black")
    gh, ah = guess.get("height_cm",""), ans.get("height_cm","")
    out["height_cm"] = "green" if (gh and ah and str(gh)==str(ah)) else ("yellow" if height_tens_equal(gh,ah) else "black")
    # Removed age comparison as per instructions
    out["player_type"] = "green" if guess.get("player_type","")==ans.get("player_type","") else "black"
    out["draft"] = "green" if draft_tuple(guess)==draft_tuple(ans) else ("yellow" if draft_yellow(guess,ans) else "black")
    # Removed exact answer force green override for age (if present)
    if guess.get("name","") == ans.get("name",""):
        for k in ["team","number","position","height_cm","player_type","draft"]:
            out[k] = "green"
    return out

@app.route("/api/guess", methods=["POST"])
def api_guess():
    data = request.get_json(force=True) or {}
    raw = (data.get("name") or "").strip()
    idx = NAME2IDX.get(raw) or NORMNAME2IDX.get(normalize_name(raw))
    if idx is None:
        return jsonify({"error":"등록되지 않은 선수입니다."}), 400
    g = PLAYERS[idx]; a = answer_player()
    colors = compare_fields(g,a)
    return jsonify({
        "name": g.get("name",""),
        "team": colors["team"],
        "number": colors["number"],
        "position": colors["position"],
        "height_cm": colors["height_cm"],
        # Removed age from response
        "player_type": colors["player_type"],
        "draft": colors["draft"],
        "is_correct": (g.get("name","")==a.get("name",""))
    })

@app.route("/api/player_info")
def api_player_info():
    name = (request.args.get("name") or "").strip()
    idx = NAME2IDX.get(name) or NORMNAME2IDX.get(normalize_name(name))
    if idx is None:
        return jsonify({"error": "not found"}), 404
    p = PLAYERS[idx]
    # Removed age calculation and response
    return jsonify({
        "name": p.get("name",""),
        "team": p.get("team",""),
        "number": p.get("number",""),
        "position": p.get("position",""),
        "height_cm": p.get("height_cm",""),
        "player_type": p.get("player_type",""),
        "draft_year": p.get("draft_year",""),
        "draft_type": p.get("draft_type",""),
        "draft_round": p.get("draft_round",""),
        "draft_overall": p.get("draft_overall","")
    })

@app.route("/test")
def test_page():
    return "OK"

