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
            
