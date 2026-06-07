import json
import math
import os
import re
import unicodedata
from io import StringIO
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests

BASE_URL_FDORG = "https://api.football-data.org/v4"
OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(exist_ok=True)

LEAGUES = [
    {"country": "England", "league_name": "Premier League", "league_code": "E0", "data_mode": "full", "csv": "https://www.football-data.co.uk/mmz4281/2526/E0.csv"},
    {"country": "Germany", "league_name": "Bundesliga", "league_code": "D1", "data_mode": "full", "csv": "https://www.football-data.co.uk/mmz4281/2526/D1.csv"},
    {"country": "Spain", "league_name": "La Liga", "league_code": "SP1", "data_mode": "full", "csv": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"},
    {"country": "France", "league_name": "Ligue 1", "league_code": "F1", "data_mode": "full", "csv": "https://www.football-data.co.uk/mmz4281/2526/F1.csv"},
]

POLAND_META = {"country": "Poland", "league_name": "Ekstraklasa", "league_code": "PL-EKS", "data_mode": "lite", "source": "football-data.org"}

COMMON_COLUMNS = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5"]

ALIASES = {
    "man united": "Manchester United", "man utd": "Manchester United", "psg": "Paris SG", "bayern munich": "Bayern Munchen",
    "ath madrid": "Atletico Madrid", "ath bilbao": "Athletic Club", "legia warszawa": "Legia", "lech poznan": "Lech",
    "rakow czestochowa": "Rakow", "jagiellonia bialystok": "Jagiellonia", "widzew lodz": "Widzew",
    "gornik zabrze": "Gornik Zabrze", "pogon szczecin": "Pogon Szczecin", "zaglebie lubin": "Zaglebie Lubin",
    "wisla plock": "Wisla Plock", "lechia gdansk": "Lechia Gdansk"
}

LEAGUE_BASELINES = {
    'E0': {'home_adv': 0.22, 'goal_base': 1.38},
    'D1': {'home_adv': 0.20, 'goal_base': 1.42},
    'SP1': {'home_adv': 0.18, 'goal_base': 1.24},
    'F1': {'home_adv': 0.19, 'goal_base': 1.26},
    'PL-EKS': {'home_adv': 0.17, 'goal_base': 1.20},
}


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"\b(fc|cf|afc|ac|sc|club|calcio|ks|ssa)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_team_name(name: str) -> str:
    return ALIASES.get(normalize_name(name), str(name).strip())


def fetch_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text))


def import_top4() -> pd.DataFrame:
    parts = []
    for league in LEAGUES:
        df = fetch_csv(league['csv'])
        use = [c for c in COMMON_COLUMNS if c in df.columns]
        out = df[use].copy()
        for c in COMMON_COLUMNS:
            if c not in out.columns:
                out[c] = None
        out['league_name'] = league['league_name']
        out['league_code'] = league['league_code']
        out['data_mode'] = league['data_mode']
        out['source'] = 'football-data.co.uk'
        out['utcDate'] = None
        out['HomeTeam'] = out['HomeTeam'].astype(str)
        out['AwayTeam'] = out['AwayTeam'].astype(str)
        out['home_team_canonical'] = out['HomeTeam'].apply(canonical_team_name)
        out['away_team_canonical'] = out['AwayTeam'].apply(canonical_team_name)
        out['FTHG'] = pd.to_numeric(out['FTHG'], errors='coerce')
        out['FTAG'] = pd.to_numeric(out['FTAG'], errors='coerce')
        out['total_goals'] = out['FTHG'].fillna(0) + out['FTAG'].fillna(0)
        out['over25_result'] = (out['total_goals'] >= 3).astype(int)
        parts.append(out)
    full = pd.concat(parts, ignore_index=True)
    full.to_csv(OUT / 'top4_matches.csv', index=False)
    return full


def fetch_ekstraklasa_fdorg(token: str, competition_code: str = 'EKS', season: int = 2025) -> pd.DataFrame:
    headers = {'X-Auth-Token': token}
    params = {'season': season}
    r = requests.get(f'{BASE_URL_FDORG}/competitions/{competition_code}/matches', headers=headers, params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = []
    for match in payload.get('matches', []):
        score = match.get('score', {})
        ft = score.get('fullTime', {}) if score else {}
        hg = ft.get('home')
        ag = ft.get('away')
        total = (hg + ag) if hg is not None and ag is not None else None
        rows.append({
            'Div': None,
            'Date': None,
            'Time': None,
            'utcDate': match.get('utcDate'),
            'HomeTeam': match.get('homeTeam', {}).get('name'),
            'AwayTeam': match.get('awayTeam', {}).get('name'),
            'FTHG': hg,
            'FTAG': ag,
            'FTR': None,
            'B365H': None,
            'B365D': None,
            'B365A': None,
            'B365>2.5': None,
            'B365<2.5': None,
            'league_name': POLAND_META['league_name'],
            'league_code': POLAND_META['league_code'],
            'data_mode': POLAND_META['data_mode'],
            'source': POLAND_META['source'],
            'home_team_canonical': canonical_team_name(match.get('homeTeam', {}).get('name')),
            'away_team_canonical': canonical_team_name(match.get('awayTeam', {}).get('name')),
            'total_goals': total,
            'over25_result': 1 if total is not None and total >= 3 else (0 if total is not None else None),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'ekstraklasa_matches.csv', index=False)
    return df


def compute_form_features(matches_df: pd.DataFrame, team_name: str, league_code: str, last_n: int = 10) -> dict:
    team_matches = matches_df[(matches_df['league_code'] == league_code) & ((matches_df['home_team_canonical'] == team_name) | (matches_df['away_team_canonical'] == team_name))].copy()
    team_matches = team_matches.dropna(subset=['FTHG', 'FTAG'])
    if 'utcDate' in team_matches.columns and team_matches['utcDate'].notna().any():
        team_matches = team_matches.sort_values('utcDate').tail(last_n)
    else:
        team_matches = team_matches.tail(last_n)
    if team_matches.empty:
        return {'team': team_name, 'matches_used': 0, 'goals_scored_avg': 0.0, 'goals_conceded_avg': 0.0, 'over25_rate': 0.0, 'scored_rate': 0.0, 'v3_form_score': 0.0}
    scored, conceded, overs, v3 = [], [], [], []
    for _, row in team_matches.iterrows():
        is_home = row['home_team_canonical'] == team_name
        gf = row['FTHG'] if is_home else row['FTAG']
        ga = row['FTAG'] if is_home else row['FTHG']
        total = row['total_goals']
        scored.append(gf)
        conceded.append(ga)
        overs.append(1 if total >= 3 else 0)
        v3.append((0.75 if gf >= 1 else -0.75) + (0.5 if total >= 3 else -0.5))
    return {
        'team': team_name,
        'matches_used': int(len(team_matches)),
        'goals_scored_avg': round(sum(scored)/len(scored), 3),
        'goals_conceded_avg': round(sum(conceded)/len(conceded), 3),
        'over25_rate': round(sum(overs)/len(overs), 3),
        'scored_rate': round(sum(1 for x in scored if x >= 1)/len(scored), 3),
        'v3_form_score': round(sum(v3), 3)
    }


def build_feature_table(matches_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for league_code in sorted(matches_df['league_code'].dropna().unique()):
        league_name = matches_df.loc[matches_df['league_code'] == league_code, 'league_name'].iloc[0]
        data_mode = matches_df.loc[matches_df['league_code'] == league_code, 'data_mode'].iloc[0]
        teams = sorted(set(matches_df.loc[matches_df['league_code'] == league_code, 'home_team_canonical'].dropna()) | set(matches_df.loc[matches_df['league_code'] == league_code, 'away_team_canonical'].dropna()))
        for team in teams:
            feat = compute_form_features(matches_df, team, league_code)
            feat['league_code'] = league_code
            feat['league_name'] = league_name
            feat['data_mode'] = data_mode
            rows.append(feat)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'team_form_features.csv', index=False)
    return df


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def estimate_lambdas(home: dict, away: dict, league_code: str):
    base = LEAGUE_BASELINES.get(league_code, {'home_adv': 0.18, 'goal_base': 1.25})
    form_edge = (home['v3_form_score'] - away['v3_form_score']) * 0.035
    attack_home = home['goals_scored_avg'] * 0.55 + away['goals_conceded_avg'] * 0.25
    attack_away = away['goals_scored_avg'] * 0.52 + home['goals_conceded_avg'] * 0.23
    over_boost = (home['over25_rate'] + away['over25_rate'] - 1.0) * 0.25
    score_boost = (home['scored_rate'] + away['scored_rate'] - 1.0) * 0.18
    home_lambda = base['goal_base'] + base['home_adv'] + form_edge + attack_home * 0.35 + over_boost + score_boost
    away_lambda = (base['goal_base'] - 0.10) - form_edge * 0.4 + attack_away * 0.35 + over_boost + score_boost * 0.8
    return max(round(home_lambda, 3), 0.2), max(round(away_lambda, 3), 0.2)


def match_probs(home_lambda: float, away_lambda: float, max_goals: int = 8):
    p1 = px = p2 = over = 0.0
    scores = []
    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            p = poisson_pmf(hg, home_lambda) * poisson_pmf(ag, away_lambda)
            scores.append(((hg, ag), p))
            if hg > ag: p1 += p
            elif hg == ag: px += p
            else: p2 += p
            if hg + ag >= 3: over += p
    top = sorted(scores, key=lambda x: x[1], reverse=True)[:3]
    return {'1': round(p1,4), 'X': round(px,4), '2': round(p2,4), 'Over 2.5': round(over,4), 'Under 2.5': round(1-over,4), 'top_scores': [{'score': f'{a}-{b}', 'probability': round(p,4)} for (a,b),p in top]}


def predict_match(feature_df: pd.DataFrame, league_code: str, home_team: str, away_team: str) -> Dict:
    home = feature_df[(feature_df['league_code'] == league_code) & (feature_df['team'] == home_team)].iloc[0].to_dict()
    away = feature_df[(feature_df['league_code'] == league_code) & (feature_df['team'] == away_team)].iloc[0].to_dict()
    hl, al = estimate_lambdas(home, away, league_code)
    probs = match_probs(hl, al)
    pick = max(['1','X','2','Over 2.5','Under 2.5'], key=lambda k: probs[k])
    return {
        'match': f'{home_team} vs {away_team}',
        'league_code': league_code,
        'expected_goals': {'home': hl, 'away': al},
        'probabilities': {k: probs[k] for k in ['1','X','2','Over 2.5','Under 2.5']},
        'main_tip': pick,
        'confidence': probs[pick],
        'top_scores': probs['top_scores']
    }


def main():
    top4 = import_top4()
    token = os.getenv('FOOTBALL_DATA_API_TOKEN')
    if token:
        try:
            pol = fetch_ekstraklasa_fdorg(token=token, competition_code=os.getenv('FOOTBALL_DATA_COMPETITION', 'EKS'), season=int(os.getenv('FOOTBALL_DATA_SEASON', '2025')))
            all_matches = pd.concat([top4, pol], ignore_index=True)
            pol_status = 'imported from football-data.org'
        except Exception as exc:
            all_matches = top4.copy()
            pol_status = f'error: {exc}'
    else:
        all_matches = top4.copy()
        pol_status = 'skipped - missing FOOTBALL_DATA_API_TOKEN'

    feature_df = build_feature_table(all_matches)

    samples = [
        ('E0', 'Arsenal', 'Brighton'),
        ('D1', 'Bayern Munchen', 'Dortmund'),
        ('SP1', 'Barcelona', 'Betis'),
        ('F1', 'Paris SG', 'Marseille')
    ]
    predictions = []
    for league_code, home, away in samples:
        try:
            predictions.append(predict_match(feature_df, league_code, home, away))
        except Exception as exc:
            predictions.append({'match': f'{home} vs {away}', 'league_code': league_code, 'error': str(exc)})

    summary = {
        'matches_total': int(len(all_matches)),
        'feature_rows': int(len(feature_df)),
        'poland_status': pol_status,
        'predictions': predictions
    }
    (OUT / 'integrated_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
