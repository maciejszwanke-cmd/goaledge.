from __future__ import annotations
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

from goaledge_integrated_v1 import import_top4, build_feature_table, predict_match

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "10000"))
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

LEAGUE_MAP = {
    "E0": {"competition": "PL", "name": "Premier League"},
    "D1": {"competition": "BL1", "name": "Bundesliga"},
    "SP1": {"competition": "PD", "name": "La Liga"},
    "F1": {"competition": "FL1", "name": "Ligue 1"},
}
COMP_TO_LOCAL = {v["competition"]: k for k, v in LEAGUE_MAP.items()}

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


def resolve_date(date_str: str) -> str:
    now = datetime.now(timezone.utc).date()
    raw = (date_str or "today").lower()
    if raw == "today":
        return now.isoformat()
    if raw == "tomorrow":
        return (now + timedelta(days=1)).isoformat()
    return raw


def predict_fixture(fix: Dict[str, Any], feature_df: pd.DataFrame) -> Dict[str, Any]:
    league_code = fix["league_code"]
    home = fix["home_team"]
    away = fix["away_team"]
    try:
        pred = predict_match(feature_df, league_code, home, away)
    except Exception:
        pred = {
            "expected_goals": {"home": 1.0, "away": 1.0},
            "probabilities": {
                "1": 0.33,
                "X": 0.34,
                "2": 0.33,
                "Over 2.5": 0.5,
                "Under 2.5": 0.5,
            },
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
        "probabilities": pred.get(
            "probabilities",
            {"1": 0.33, "X": 0.34, "2": 0.33, "Over 2.5": 0.5, "Under 2.5": 0.5},
        ),
        "main_tip": pred.get("main_tip", "Over 2.5"),
        "confidence": pred.get("confidence", 0.5),
        "top_scores": pred.get("top_scores", [{"score": "1-1", "probability": 0.1}]),
        "home_xg": float(pred.get("expected_goals", {}).get("home", 1.0)),
        "away_xg": float(pred.get("expected_goals", {}).get("away", 1.0)),
    }


def fetch_fixtures(date_str: str, league: Optional[str]) -> List[Dict[str, Any]]:
    if not API_KEY:
        raise RuntimeError("Brak FOOTBALL_DATA_API_KEY w Render Environment Variables")

    resolved = resolve_date(date_str)
    headers = {"X-Auth-Token": API_KEY}
    params = {"dateFrom": resolved, "dateTo": resolved}

    if league and league in LEAGUE_MAP:
        competition = LEAGUE_MAP[league]["competition"]
        url = f"https://api.football-data.org/v4/competitions/{competition}/matches"
    else:
        url = "https://api.football-data.org/v4/matches"

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    raw_matches = payload.get("matches", [])

    fixtures: List[Dict[str, Any]] = []
    for m in raw_matches:
        competition_code = (m.get("competition") or {}).get("code")
        local_code = COMP_TO_LOCAL.get(competition_code)
        if league and league in LEAGUE_MAP and local_code != league:
            continue
        if local_code not in LEAGUE_MAP:
            continue

        fixtures.append(
            {
                "league_code": local_code,
                "league_name": LEAGUE_MAP[local_code]["name"],
                "home_team": ((m.get("homeTeam") or {}).get("name") or "Home").replace("FC ", "").strip(),
                "away_team": ((m.get("awayTeam") or {}).get("name") or "Away").replace("FC ", "").strip(),
                "utc_date": m.get("utcDate"),
                "status": m.get("status", "SCHEDULED"),
            }
        )

    return fixtures


def get_matches(query: Dict[str, List[str]]) -> Dict[str, Any]:
    date_str = query.get("date_str", ["today"])[0].lower()
    league = query.get("league", [None])[0]
    offset = int(query.get("offset", [0])[0])
    limit = int(query.get("limit", [20])[0])
    sort_by = query.get("sort_by", ["confidence"])[0]

    fixtures = fetch_fixtures(date_str, league)
    feature_df = load_or_build_features()
    matches = [predict_fixture(f, feature_df) for f in fixtures]

    if sort_by == "confidence":
        matches.sort(key=lambda x: x["confidence"], reverse=True)

    total = len(matches)
    page = matches[offset : offset + limit]
    groups: Dict[str, Dict[str, Any]] = {}

    for m in page:
        g = groups.setdefault(
            m["league_code"],
            {
                "league_code": m["league_code"],
                "league_name": m["league_name"],
                "matches": [],
            },
        )
        g["matches"].append(m)

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "date": resolve_date(date_str),
        "groups": list(groups.values()),
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                return self._send_json(200, {"status": "ok"})
            if parsed.path == "/matches":
                query = parse_qs(parsed.query)
                return self._send_json(200, get_matches(query))
            return self._send_json(404, {"error": "not found"})
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 502
            return self._send_json(status, {"error": "football-data API error", "details": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": "internal server error", "details": str(e)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"GoalEdge API running on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
            
