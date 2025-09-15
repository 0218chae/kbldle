# api/index.py
from __future__ import annotations
from flask import Flask, render_template, request, jsonify
import csv, datetime, hashlib, os, unicodedata, random, re
from typing import Dict, List, Tuple, Any, Optional

# --- 경로 설정 (api/ 기준으로 상위 폴더의 자원 접근) ---
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))  # 프로젝트 루트
DATA_CSV = os.path.join(ROOT_DIR, "kbl_players_2025.csv")

app = Flask(
    __name__,
    template_folder=os.path.join(ROOT_DIR, "templates"),
    static_folder=os.path.join(ROOT_DIR, "static"),
    static_url_path=""
)

MAX_GUESSES = 9
CURRENT_ANSWER_IDX = None

def now_utc_date_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

def this_year_utc() -> int:
    return datetime.datetime.now(datetime.timezone.utc).year

def normalize_name(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFC", str(s)).replace(" ", "").lower()
    return s

def within(v1: int, v2: int, d: int) -> bool:
    try: return abs(int(v1) - int(v2)) <= d
    except: return False

def height_tens_equal(h1: Any, h2: Any) -> bool:
    try: return int(h1) // 10 == int(h2) // 10
    except: return False

def pos_group(pos: str) -> str:
    p = (pos or "").upper()
    if "C" in p: return "C"
    if "F" in p and "G" in p: return "F"
    if "F" in p: return "F"
    return "G"

def draft_tuple(p: Dict[str, Any]) -> Tuple[str,str,str,str]:
    return (str(p.get("draft_year","") or ""),
            str(p.get("draft_type","") or ""),
            str(p.get("draft_round","") or ""),
            str(p.get("draft_overall","") or ""))

# 노란불: 같은 '드래프트 타입' + 같은 '라운드'일 때만
def draft_yellow(g: Dict[str, Any], a: Dict[str, Any]) -> bool:
    gt, at = str(g.get("draft_type","") or ""), str(a.get("draft_type","") or "")
    gr, ar = str(g.get("draft_round","") or ""), str(a.get("draft_round","") or "")
    if not gt or not at or not gr or not ar: return False
    return (gt == at) and (gr == ar)

def load_players(csv_path: str):
    players: List[Dict[str, Any]] = []
    team_roster: Dict[str, List[str]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            row = { (k or "").strip(): (v.strip() if isinstance(v,str) else v) for k,v in row.items() }
            for k in ["name","team","number","position","height_cm","birth_year","player_type","draft_year","draft_type","draft_round","draft_overall"]:
                row.setdefault(k, "")
            players.append(row)
            team_roster.setdefault(row["team"], []).append(f'{row["name"]}({row["number"]})')
    for t in team_roster: team_roster[t].sort()
    return players, team_roster

PLAYERS, TEAM_ROSTER = load_players(DATA_CSV)
NAME2IDX: Dict[str,int] = {p["name"]: i for i,p in enumerate(PLAYERS)}
NORMNAME2IDX: Dict[str,int] = {normalize_name(p["name"]): i for i,p in enumerate(PLAYERS)}

def reset_answer():
    global CURRENT_ANSWER_IDX
    if PLAYERS: CURRENT_ANSWER_IDX = random.randrange(0, len(PLAYERS))
    else: CURRENT_ANSWER_IDX = None

def answer_player() -> Dict[str, Any]:
    global CURRENT_ANSWER_IDX
    if CURRENT_ANSWER_IDX is None:
        reset_answer()
    return PLAYERS[CURRENT_ANSWER_IDX]

@app.route("/")
def index():
    reset_answer()  # 새로고침 시 매번 랜덤
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify({"max_guesses": MAX_GUESSES})

@app.route("/health")
def health():
    info = {
        "ROOT_DIR": ROOT_DIR,
        "DATA_CSV": DATA_CSV,
        "csv_exists": os.path.exists(DATA_CSV),
    }
    return jsonify(info)

@app.route("/api/players")
def api_players():
    return jsonify([p["name"] for p in PLAYERS])

@app.route("/api/teams")
def api_teams():
    return jsonify(TEAM_ROSTER)

def _int_or_none(x: Any) -> Optional[int]:
    if x is None:
        return None
    s = str(x).strip()
    m = re.search(r"-?\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None

def _ptype_norm(x: Any) -> str:
    s = str(x or "").strip()
    s = unicodedata.normalize("NFC", s)
    # common variants -> unified labels
    table = {
        "국내": "국내", "국내선수": "국내",
        "외국": "외국", "외국선수": "외국", "외국인": "외국",
        "귀화": "귀화", "귀화선수": "귀화",
    }
    return table.get(s, s)

def _fmt_draft(p: Dict[str, Any]) -> str:
    y = str(p.get("draft_year") or "").strip()
    t = str(p.get("draft_type") or "").strip()
    r = str(p.get("draft_round") or "").strip()
    o = str(p.get("draft_overall") or "").strip()
    parts = []
    if y: parts.append(y)
    if t: parts.append(t)
    if r: parts.append(f"{r}R")
    if o: parts.append(o)
    return " ".join(parts)

def compare_fields(guess: Dict[str, Any], ans: Dict[str, Any]) -> Dict[str,str]:
    out: Dict[str,str] = {}
    out["team"] = "green" if (guess.get("team","")==ans.get("team","")) else "black"
    # number (노란불은 등번호 차이가 ±2일 때만)
    gn = _int_or_none(guess.get("number"))
    an = _int_or_none(ans.get("number"))
    if gn is not None and an is not None:
        if gn == an:
            out["number"] = "green"
        elif abs(gn - an) <= 2:
            out["number"] = "yellow"
        else:
            out["number"] = "black"
    else:
        out["number"] = "black"
    # position
    gp, ap = (guess.get("position","") or ""), (ans.get("position","") or "")
    out["position"] = "green" if (gp and gp==ap) else ("yellow" if pos_group(gp)==pos_group(ap) else "black")
    # height (그린: 동일, 옐로우: ±3cm)
    gh = _int_or_none(guess.get("height_cm"))
    ah = _int_or_none(ans.get("height_cm"))
    if gh is not None and ah is not None:
        if gh == ah:
            out["height_cm"] = "green"
        elif abs(gh - ah) <= 3:
            out["height_cm"] = "yellow"
        else:
            out["height_cm"] = "black"
    else:
        out["height_cm"] = "black"
    # player_type (정규화 후 정확히 같을 때만 green)
    out["player_type"] = "green" if _ptype_norm(guess.get("player_type","")) == _ptype_norm(ans.get("player_type","")) else "black"
    # draft
    out["draft"] = "green" if draft_tuple(guess)==draft_tuple(ans) else ("yellow" if draft_yellow(guess,ans) else "black")
    # 정답이면 전부 초록
    if (guess.get("name","") == ans.get("name","")):
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
        "player_type": colors["player_type"],
        "draft": colors["draft"],
        # ---- display values for cells ----
        "team_value": g.get("team",""),
        "number_value": (str(_int_or_none(g.get("number"))) if _int_or_none(g.get("number")) is not None else str(g.get("number",""))),
        "position_value": g.get("position",""),
        "height_cm_value": (str(_int_or_none(g.get("height_cm"))) + "cm" if _int_or_none(g.get("height_cm")) is not None else str(g.get("height_cm",""))),
        "player_type_value": g.get("player_type",""),
        "draft_value": _fmt_draft(g),
        "is_correct": (g.get("name","")==a.get("name",""))
    })

@app.route("/api/player_info")
def api_player_info():
    name = (request.args.get("name") or "").strip()
    idx = NAME2IDX.get(name) or NORMNAME2IDX.get(normalize_name(name))
    if idx is None:
        return jsonify({"error": "not found"}), 404
    p = PLAYERS[idx]
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

@app.route("/api/_answer")
def api__answer():
    a = answer_player()
    return jsonify({
        "name": a.get("name",""),
        "team": a.get("team",""),
        "number": a.get("number",""),
        "position": a.get("position",""),
        "height_cm": a.get("height_cm",""),
        "player_type": a.get("player_type",""),
        "draft_year": a.get("draft_year",""),
        "draft_type": a.get("draft_type",""),
        "draft_round": a.get("draft_round",""),
        "draft_overall": a.get("draft_overall",""),
    })

@app.route("/api/answer")
def api_answer_public():
    a = answer_player()
    return jsonify({
        "name": a.get("name",""),
        "team_value": a.get("team",""),
        "number_value": (str(_int_or_none(a.get("number"))) if _int_or_none(a.get("number")) is not None else str(a.get("number",""))),
        "position_value": a.get("position",""),
        "height_cm_value": (str(_int_or_none(a.get("height_cm"))) + "cm" if _int_or_none(a.get("height_cm")) is not None else str(a.get("height_cm",""))),
        "player_type_value": a.get("player_type",""),
        "draft_value": _fmt_draft(a),
    })

@app.route("/api/_guess_debug")
def api__guess_debug():
    name = (request.args.get("name") or "").strip()
    idx = NAME2IDX.get(name) or NORMNAME2IDX.get(normalize_name(name))
    if idx is None:
        return jsonify({"error": "unknown player"}), 400
    g = PLAYERS[idx]
    a = answer_player()
    gn = _int_or_none(g.get("number"))
    an = _int_or_none(a.get("number"))
    diff = (abs(gn - an) if gn is not None and an is not None else None)
    colors = compare_fields(g, a)
    return jsonify({
        "guess_name": g.get("name",""),
        "guess_number_raw": g.get("number",""),
        "guess_number_int": gn,
        "answer_name": a.get("name",""),
        "answer_number_raw": a.get("number",""),
        "answer_number_int": an,
        "abs_diff": diff,
        "number_color": colors.get("number"),
    })