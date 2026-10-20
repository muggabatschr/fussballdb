"""Kickbase-Punktemodell: erklärt echte Kickbase-Punkte eines Spiels aus Ereignissen, die wir kennen.

Je Position (TW, ABW, MF, ST) eine lineare Regression der Punkte auf: Einsatz, Startelf, Minuten,
Tore, Vorlagen, Gegentore, Zu null, Sieg, Remis, Gelb, Rot. Was Understat nicht misst (Zweikämpfe,
Pässe, Paraden …), steckt im Spielerwert: dem geglätteten mittleren Rest des Spielers.
Die Prognose setzt erwartete statt tatsächliche Ereignisse ein; weil das Modell linear ist, ist das
der Erwartungswert der Punkte."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

POS = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}
FEATURES = ["played", "started", "minutes90", "goals", "assists", "conceded", "clean_sheet", "win", "draw",
            "yellow", "red"]
PLAYER_PRIOR = 8.0  # Spiele, mit denen der Spielerwert zum Mittel (0) gezogen wird

TRAIN_SQL = text(
    """
    SELECT k.kb_id, k.points, k.kickoff, s.start_year AS season, kp.position,
           coalesce(pm.minutes, 0) AS minutes, coalesce(pm.started, false) AS started,
           coalesce(pm.goals, 0) AS goals, coalesce(pm.assists, 0) AS assists,
           coalesce(pm.yellow_cards, 0) AS yellow, coalesce(pm.red_cards, 0) AS red,
           CASE WHEN pm.team_id = m.home_team_id THEN m.home_goals ELSE m.away_goals END AS team_goals,
           CASE WHEN pm.team_id = m.home_team_id THEN m.away_goals ELSE m.home_goals END AS opp_goals
    FROM kb_points k
    JOIN kb_player kp ON kp.kb_id = k.kb_id
    JOIN match m ON m.id = k.match_id
    JOIN season s ON s.id = m.season_id
    LEFT JOIN player_match pm ON pm.match_id = k.match_id AND pm.player_id = kp.player_id
    WHERE kp.player_id IS NOT NULL
    """
)


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Merkmale aus tatsächlichen (Training) oder erwarteten (Prognose) Ereignissen."""
    played = (df["minutes"] > 0).astype(float) if "played" not in df else df["played"]
    share = (df["minutes"] / 90).clip(0, 1)
    return pd.DataFrame({
        "played": played,
        "started": df["started"].astype(float),
        "minutes90": share,
        "goals": df["goals"],
        "assists": df["assists"],
        # Gegentore und Zu-null zählen nur anteilig zur eigenen Spielzeit
        "conceded": df["opp_goals"] * share if "conceded" not in df else df["conceded"],
        "clean_sheet": ((df["opp_goals"] == 0) & (df["minutes"] >= 60)).astype(float) if "clean_sheet" not in df else df["clean_sheet"],
        "win": ((df["team_goals"] > df["opp_goals"]) * played).astype(float) if "win" not in df else df["win"],
        "draw": ((df["team_goals"] == df["opp_goals"]) * played).astype(float) if "draw" not in df else df["draw"],
        "yellow": df["yellow"],
        "red": df["red"],
    })[FEATURES]


@dataclass
class KickbasePointsModel:
    coef: dict[str, np.ndarray] = field(default_factory=dict)
    player_effect: dict[int, float] = field(default_factory=dict)

    def fit(self, data: pd.DataFrame) -> "KickbasePointsModel":
        data = data.assign(pos=data["position"].map(POS))
        residuals = []
        for pos, g in data.groupby("pos"):
            # ohne Achsenabschnitt: ohne Einsatz gibt es 0 Punkte, "played" ist der Grundwert bei Einsatz
            X = features(g).to_numpy(float)
            y = g["points"].to_numpy(float)
            lam = np.eye(X.shape[1]) * 1.0  # leichte Ridge-Regularisierung für stabile Koeffizienten
            self.coef[pos] = np.linalg.solve(X.T @ X + lam, X.T @ y)
            residuals.append(pd.DataFrame({"kb_id": g["kb_id"], "res": y - X @ self.coef[pos],
                                           "played": features(g)["played"]}))
        res = pd.concat(residuals)
        res = res[res["played"] > 0]  # Spielerwert nur aus Einsätzen
        agg = res.groupby("kb_id")["res"].agg(["sum", "count"])
        self.player_effect = (agg["sum"] / (agg["count"] + PLAYER_PRIOR)).to_dict()
        return self

    def predict(self, df: pd.DataFrame, pos: str | pd.Series) -> np.ndarray:
        """df mit (erwarteten) Ereignissen; pos je Zeile ("TW", "ABW", "MF", "ST")."""
        pos = pd.Series(pos, index=df.index) if isinstance(pos, str) else pos
        X = features(df).to_numpy(float)
        out = np.zeros(len(df))
        for p in pos.unique():
            idx = (pos == p).to_numpy()
            c = self.coef.get(p)
            if c is not None:
                out[idx] = X[idx] @ c
        effect = df["kb_id"].map(self.player_effect).fillna(0).to_numpy() if "kb_id" in df else 0
        return out + effect * X[:, 0]


def load_training() -> pd.DataFrame:
    return pd.read_sql(TRAIN_SQL, engine)


def evaluate(test_season: int) -> dict:
    """Einstellen an Saisons vor test_season, prüfen an test_season (tatsächliche Ereignisse).
    Vergleich: Punkte-Schnitt des Spielers aus den Vorsaisons bei Einsatz."""
    data = load_training()
    train, test = data[data["season"] < test_season], data[data["season"] == test_season]
    model = KickbasePointsModel().fit(train)
    pred = model.predict(test, test["position"].map(POS))
    played = (test["minutes"] > 0).to_numpy()
    avg = train[train["minutes"] > 0].groupby("kb_id")["points"].mean()
    naive = test["kb_id"].map(avg).fillna(train.loc[train["minutes"] > 0, "points"].mean()).to_numpy() * played
    y = test["points"].to_numpy(float)
    corr = lambda a, b: float(np.corrcoef(a, b)[0, 1])
    return {"spiele": int(len(test)), "mae_modell": float(np.abs(y - pred).mean()),
            "mae_spielerschnitt": float(np.abs(y - naive).mean()), "korrelation_modell": corr(y, pred),
            "korrelation_spielerschnitt": corr(y, naive),
            "koeffizienten": {p: dict(zip(FEATURES, np.round(c, 1))) for p, c in model.coef.items()}}
