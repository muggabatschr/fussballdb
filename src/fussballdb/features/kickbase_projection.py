"""Erwartete Ereignisse je Spieler für die nächsten Spieltage (Grundlage für Kickbase).

Pro Spieler und Spiel: Einsatzchance, erwartete Minuten, Tore, Vorlagen, Zu-null-Chance (Torwart und
Abwehr) und Kartenrisiko. Die Torerwartung des Teams gegen den jeweiligen Gegner kommt aus der
gespeicherten Live-Prognose, die Spielerraten aus xG/xA der letzten Monate (geglättet zum
Positionsschnitt). Eine Kickbase-Punktzahl wird erst berechnet, wenn echte Kickbase-Punkte zum
Kalibrieren vorliegen."""

from math import exp

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.config import DEFAULT_SEASONS
from fussballdb.db.session import engine

POSITION = {"GK": "TW", "DC": "ABW", "DR": "ABW", "DL": "ABW", "DML": "ABW", "DMR": "ABW",
            "DMC": "MF", "MC": "MF", "AMC": "MF", "AML": "MF", "AMR": "MF", "ML": "MF", "MR": "MF",
            "FW": "ST", "FWL": "ST", "FWR": "ST"}
WINDOW_DAYS = 300
FORM_MATCHES = 5  # Startelf-Quote aus den letzten 5 Spielen des Teams
PRIOR_MINUTES = 900.0  # Glättung der Raten pro 90 Minuten zum Positionsschnitt

APPS_SQL = text(
    """
    SELECT pm.match_id, pm.player_id, p.name, pm.team_id, pm.position, pm.started, pm.minutes,
           pm.xg, pm.xa, pm.goals, pm.assists, pm.yellow_cards, pm.red_cards, m.kickoff
    FROM player_match pm JOIN match m ON m.id = pm.match_id JOIN player p ON p.id = pm.player_id
    WHERE m.kickoff > now() - make_interval(days => :days)
    """
)
FIXTURES_SQL = text(
    """
    SELECT m.id AS match_id, m.matchday, m.kickoff, m.home_team_id, m.away_team_id,
           ht.name AS home, at.name AS away, p.exp_home_goals, p.exp_away_goals, p.p_home, p.p_draw, p.p_away
    FROM match m JOIN season s ON s.id = m.season_id
    JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
    LEFT JOIN prediction p ON p.match_id = m.id AND p.basis = 'live'
    WHERE s.start_year = :y AND NOT m.finished
    ORDER BY m.kickoff
    """
)
ABSENT_SQL = text("SELECT player_id, kind FROM player_absence WHERE active AND player_id IS NOT NULL")
TEAM_XG_SQL = text(
    """
    SELECT x.team_id, avg(x.xg) AS xg, avg(o.xg) AS xga
    FROM match_team_stats x JOIN match_team_stats o ON o.match_id = x.match_id AND o.team_id <> x.team_id
    JOIN match m ON m.id = x.match_id
    WHERE m.finished AND m.kickoff > now() - make_interval(days => :days)
    GROUP BY x.team_id
    """
)
KB_SQL = text(
    """
    SELECT k.kb_id, k.player_id, k.status AS kb_status, k.market_value, k.mv_trend, k.avg_points, k.total_points,
           (SELECT v.value FROM kb_market_value v WHERE v.kb_id = k.kb_id AND v.day <= current_date - 7
            ORDER BY v.day DESC LIMIT 1) AS mv_7d,
           (SELECT e.price FROM kb_league_entry e WHERE e.kb_id = k.kb_id AND e.kind = 'markt' LIMIT 1) AS markt_preis,
           (SELECT e.expires_in FROM kb_league_entry e WHERE e.kb_id = k.kb_id AND e.kind = 'markt' LIMIT 1) AS markt_ablauf,
           EXISTS (SELECT 1 FROM kb_league_entry e WHERE e.kb_id = k.kb_id AND e.kind = 'kader') AS im_kader
    FROM kb_player k WHERE k.player_id IS NOT NULL
    """
)
# Kickbase-Status: 0 fit, 1 verletzt, 2 angeschlagen, 4 Aufbautraining -> Faktor auf die Einsatzchance
KB_STATUS_FACTOR = {0: 1.0, 1: 0.0, 2: 0.6, 4: 0.3}

LINEUP_SQL = text(
    """
    SELECT DISTINCT ON (l.match_id, l.player_id) l.match_id, l.player_id, l.role
    FROM lineup_snapshot l WHERE l.status = 'vorschau' AND l.player_id IS NOT NULL
    ORDER BY l.match_id, l.player_id, l.fetched_at DESC
    """
)


def _player_table(apps: pd.DataFrame) -> pd.DataFrame:
    """Raten pro 90 Minuten je Spieler (letzter Verein), Position, Startelf-Quote."""
    apps = apps.sort_values("kickoff")
    last_team = apps.groupby("player_id")["team_id"].last()
    apps = apps[apps["team_id"] == apps["player_id"].map(last_team)]
    played = apps[apps["position"] != "Sub"]
    pos = played.groupby("player_id")["position"].agg(lambda s: s.mode().iat[0]).map(POSITION).fillna("MF")
    agg = apps.groupby("player_id").agg(name=("name", "last"), team_id=("team_id", "last"), minutes=("minutes", "sum"),
                                        xg=("xg", "sum"), xa=("xa", "sum"), goals=("goals", "sum"),
                                        assists=("assists", "sum"), yellow=("yellow_cards", "sum"),
                                        apps=("match_id", "nunique"))
    agg["position"] = pos.reindex(agg.index).fillna("MF")
    # Startelf-Quote und Einwechsel-Minuten aus den letzten Spielen des Teams
    team_matches = apps.groupby("team_id")["match_id"].apply(lambda s: list(dict.fromkeys(s))[-FORM_MATCHES:])
    starts, sub_min = {}, {}
    for pid, row in agg.iterrows():
        recent = team_matches.get(row["team_id"], [])
        mine = apps[(apps["player_id"] == pid) & apps["match_id"].isin(recent)]
        starts[pid] = mine["started"].sum() / max(len(recent), 1)
        subs = mine[~mine["started"]]
        sub_min[pid] = (subs["minutes"].mean() if len(subs) else 20.0, len(subs) / max(len(recent), 1))
    agg["p_start"] = pd.Series(starts)
    agg["sub_minutes"] = pd.Series({k: v[0] for k, v in sub_min.items()})
    agg["p_sub"] = pd.Series({k: v[1] for k, v in sub_min.items()})
    # Raten pro 90, geglättet zum Positionsschnitt
    for col in ("xg", "xa", "yellow"):
        pos_rate = agg.groupby("position").apply(lambda g: g[col].sum() / max(g["minutes"].sum(), 1))
        prior = agg["position"].map(pos_rate)
        agg[f"{col}90"] = (agg[col] + prior * PRIOR_MINUTES) / (agg["minutes"] + PRIOR_MINUTES) * 90
    return agg


def projections(matchdays: int = 1) -> pd.DataFrame:
    apps = pd.read_sql(APPS_SQL, engine, params={"days": WINDOW_DAYS})
    apps["kickoff"] = pd.to_datetime(apps["kickoff"], utc=True)
    fixtures = pd.read_sql(FIXTURES_SQL, engine, params={"y": max(DEFAULT_SEASONS)})
    if fixtures.empty:
        return pd.DataFrame()
    first = fixtures["matchday"].min()
    fixtures = fixtures[fixtures["matchday"] < first + matchdays]
    team_xg = pd.read_sql(TEAM_XG_SQL, engine, params={"days": WINDOW_DAYS}).set_index("team_id")
    absent = pd.read_sql(ABSENT_SQL, engine)
    absent = dict(zip(absent["player_id"], absent["kind"]))
    kb = pd.read_sql(KB_SQL, engine).drop_duplicates("player_id").set_index("player_id")
    lineup = pd.read_sql(LINEUP_SQL, engine)
    lineup = {(r.match_id, r.player_id): r.role for r in lineup.itertuples()}
    players = _player_table(apps)

    rows = []
    for f in fixtures.itertuples():
        for team, opp, own_goals, opp_goals in ((f.home_team_id, f.away, f.exp_home_goals, f.exp_away_goals),
                                                (f.away_team_id, f.home, f.exp_away_goals, f.exp_home_goals)):
            if pd.isna(own_goals):
                continue
            base = team_xg.loc[team] if team in team_xg.index else None
            scale = own_goals / base["xg"] if base is not None and base["xg"] > 0 else 1.0
            p_clean = exp(-opp_goals)  # Poisson: Gegner trifft nicht
            home_side = team == f.home_team_id
            p_win = f.p_home if home_side else f.p_away
            p_draw = f.p_draw
            team_name = f.home if team == f.home_team_id else f.away
            for pid, p in players[players["team_id"] == team].iterrows():
                status = absent.get(pid)
                role = lineup.get((f.match_id, pid))
                if status:
                    p_start = p_sub = 0.0
                elif role == "start":
                    p_start, p_sub = 0.9, 0.05
                elif role == "alternative":
                    p_start, p_sub = 0.35, 0.4
                else:
                    p_start, p_sub = float(p["p_start"]), float(p["p_sub"])
                kbp = kb.loc[pid] if pid in kb.index else None
                if kbp is not None and not status:
                    factor = KB_STATUS_FACTOR.get(int(kbp["kb_status"] or 0), 1.0)
                    p_start, p_sub = p_start * factor, p_sub * factor
                    if factor == 0:
                        status = "injury"
                minutes = p_start * 85 + p_sub * float(p["sub_minutes"])
                share = minutes / 90
                rows.append({
                    "player_id": int(pid), "name": p["name"], "team_id": int(team), "team_name": team_name,
                    "position": p["position"],
                    "matchday": int(f.matchday), "kickoff": f.kickoff, "gegner": opp, "heim": team == f.home_team_id,
                    "ausfall": status, "aufstellung": role, "einsatz": round(p_start, 2), "minuten": round(minutes),
                    "tore": p["xg90"] * share * scale, "vorlagen": p["xa90"] * share * scale,
                    "zu_null": p_clean * min(share, 1.0) if p["position"] in ("TW", "ABW") else None,
                    "gelb": p["yellow90"] * share,
                    "saison_tore": int(p["goals"]), "saison_vorlagen": int(p["assists"]),
                    "kb_id": int(kbp["kb_id"]) if kbp is not None else None,
                    "p_play": min(p_start + p_sub, 1.0), "p_start": p_start,
                    "p_win": (p_win or 0) * min(p_start + p_sub, 1.0), "p_draw": (p_draw or 0) * min(p_start + p_sub, 1.0),
                    "conceded_exp": opp_goals * min(share, 1.0), "clean_exp": p_clean * p_start,
                })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["kb_punkte"] = _expected_kickbase_points(df)
    # über mehrere Spieltage aufsummieren
    agg = df.groupby(["player_id", "name", "team_id", "team_name", "position"], as_index=False).agg(
        spiele=("matchday", "nunique"), einsatz=("einsatz", "mean"), minuten=("minuten", "sum"),
        tore=("tore", "sum"), vorlagen=("vorlagen", "sum"), zu_null=("zu_null", "sum"), gelb=("gelb", "sum"),
        ausfall=("ausfall", "first"), aufstellung=("aufstellung", "first"),
        gegner=("gegner", lambda s: list(s)), heim=("heim", lambda s: list(s)),
        saison_tore=("saison_tore", "first"), saison_vorlagen=("saison_vorlagen", "first"),
        kb_punkte=("kb_punkte", lambda x: x.sum(min_count=1)), kb_id=("kb_id", "first"))
    agg["torbeteiligung"] = agg["tore"] + agg["vorlagen"]
    agg = agg.merge(kb.reset_index()[["player_id", "market_value", "mv_7d", "avg_points", "markt_preis", "markt_ablauf",
                                      "im_kader"]], on="player_id", how="left")
    agg["marktwert"] = agg["market_value"]
    agg["trend_7t"] = (agg["market_value"] / agg["mv_7d"] - 1).where(agg["mv_7d"] > 0)
    agg["punkte_pro_mio"] = (agg["kb_punkte"] / (agg["market_value"] / 1e6)).where(agg["market_value"] > 0)
    agg["im_kader"] = agg["im_kader"].fillna(False).astype(bool)
    agg = agg.drop(columns=["market_value", "mv_7d"])
    return agg.sort_values("kb_punkte", ascending=False).round(
        {"einsatz": 2, "tore": 2, "vorlagen": 2, "zu_null": 2, "gelb": 2, "torbeteiligung": 2, "kb_punkte": 0,
         "trend_7t": 3, "punkte_pro_mio": 1})


_MODEL: dict = {}


def _expected_kickbase_points(df: pd.DataFrame) -> np.ndarray:
    """Erwartete Kickbase-Punkte je Spieler und Spiel aus den erwarteten Ereignissen (Modell aus
    features/kickbase_points.py, eingestellt an allen vorhandenen Kickbase-Punkten)."""
    from fussballdb.features.kickbase_points import KickbasePointsModel, load_training

    data = load_training()
    if data.empty:
        return np.full(len(df), np.nan)
    if _MODEL.get("n") != len(data):
        _MODEL.update(n=len(data), model=KickbasePointsModel().fit(data))
    model = _MODEL["model"]
    feats = pd.DataFrame({
        "kb_id": df["kb_id"], "played": df["p_play"], "started": df["p_start"], "minutes": df["minuten"],
        "goals": df["tore"], "assists": df["vorlagen"], "conceded": df["conceded_exp"],
        "clean_sheet": df["clean_exp"], "win": df["p_win"], "draw": df["p_draw"], "yellow": df["gelb"],
        "red": 0.01 * df["p_play"],
    })
    pos = df["position"]
    pts = model.predict(feats, pos)
    return np.where(df["kb_id"].notna(), pts, np.nan)
