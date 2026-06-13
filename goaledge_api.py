from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import pandas as pd

from goaledge_integrated_v1 import import_top4, build_feature_table, predict_match

HOST = os.getenv("GOALEdge_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10000"))
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

_FEATURE_DF: Optional[pd.DataFrame] = None

def load_or_build_features() -> pd.DataFrame:
    global _FEATURE_DF
    if _FEATURE_DF is not None:
        return _FEATURE_DF
    fpath = DATA / "team_form_features.csv"
    if fpath.exists():
        _FEATURE_DF = pd.read_csv(fpath)
        return _FEATURE_DF
    matches = import_top4()
    _FEATURE_DF = build_feature_table(matches)
    _FEATURE_DF.to_csv(fpath, index=False)
    return _FEATURE_DF

DEMO_FIXTURES: Dict[str, List[Dict[str, Any]]] = {
    "today": [
        {"league_code": "E0", "league_name": "Premier League", "home_team": "Arsenal", "away_team": "Brighton", "utc_date": "2026-06-07T15:00:00Z"},
        {"league_code": "D1", "league_name": "Bundesliga", "home_team": "Bayern Munchen", "away_team": "Dortmund", "utc_date": "2026-06-07T16:30:00Z"},
        {"league_code": "SP1", "league_name": "La Liga", "home_team": "Barcelona", "away_team": "Betis", "utc_date": "2026-06-07T18:00:00Z"},
        {"league_code": "F1", "league_name": "Ligue 1", "home_team": "Paris SG", "away_team": "Marseille", "utc_date": "2026-06-07T19:00:00Z"},
    ],
    "tomorrow": [
        {"league_code": "E0", "league_name": "Premier League", "home_team": "Arsenal", "away_team": "Brighton", "utc_date": "2026-06-08T15:00:00Z"},
        {"league_code": "SP1", "league_name": "La Liga", "home_team": "Barcelona", "away_team": "Betis", "utc_date": "2026-06-08T18:00:00Z"},
    ],
}

def predict_fixture(fix: Dict[str, Any], feature_df: pd.DataFrame) -> Dict[str, Any]:
    league_code = fix["league_code"]
    home = fix["home_team"]
    away = fix["away_team"]
    try:
        pred = predict_match(feature_df, league_code, home, away)
    except Exception:
        pred = {
            "expected_goals": {"home": 1.0, "away": 1.0},
            "probabilities": {"1": 0.33, "X": 0.34, "2": 0.33, "Over 2.5": 0.5, "Under 2.5": 0.5},
            "main_tip": "Over 2.5",
            "confidence": 0.5,
            "top_scores": [{"score": "1-1", "probability": 0.1}],
        }
    return {
        "match_id": f"{league_code}|{home}|{away}",
        "league_code": league_code,
        "league_name": fix["league_name"],
        "home_team": home,
        "away_team": away,
        "utc_date": fix.get("utc_date"),
        "status": fix.get("status", "SCHEDULED"),
        "expected_goals": pred.get("expected_goals", {"home": 1.0, "away": 1.0}),
        "probabilities": pred.get("probabilities", {"1": 0.33, "X": 0.34, "2": 0.33, "Over 2.5": 0.5, "Under 2.5": 0.5}),
        "main_tip": pred.get("main_tip", "Over 2.5"),
        "confidence": pred.get("confidence", 0.5),
        "top_scores": pred.get("top_scores", [{"score": "1-1", "probability": 0.1}]),
        "home_xg": float(pred.get("expected_goals", {}).get("home", 1.0)),
        "away_xg": float(pred.get("expected_goals", {}).get("away", 1.0)),
    }

def get_matches(query: Dict[str, List[str]]) -> Dict[str, Any]:
    date_str = query.get("date_str", ["today"])[0].lower()
    league = query.get("league", [None])[0]
    offset = int(query.get("offset", [0])[0])
    limit = int(query.get("limit", [20])[0])
    sort_by = query.get("sort_by", ["confidence"])[0]
    fixtures = DEMO_FIXTURES.get(date_str, DEMO_FIXTURES["today"])
    feature_df = load_or_build_features()
    matches = [predict_fixture(f, feature_df) for f in fixtures]
    if league:
        matches = [m for m in matches if m["league_code"] == league]
    if sort_by == "confidence":
        matches.sort(key=lambda x: x["confidence"], reverse=True)
    total = len(matches)
    page = matches[offset:offset + limit]
    groups: Dict[str, Dict[str, Any]] = {}
    for m in page:
        g = groups.setdefault(m["league_code"], {"league_code": m["league_code"], "league_name": m["league_name"], "matches": []})
        g["matches"].append(m)
    return {"total": total, "offset": offset, "limit": limit, "date": date_str, "groups": list(groups.values())}

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if parsed.path == "/matches":
            query = parse_qs(parsed.query)
            return self._send_json(200, get_matches(query))
        return self._send_json(404, {"error": "not found"})

def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"GoalEdge API running on http://{HOST}:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()
