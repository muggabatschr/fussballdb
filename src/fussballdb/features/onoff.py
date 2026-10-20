"""On/Off-Wert je Spieler: xG für und gegen das Team pro 90 Minuten mit und ohne ihn auf dem Platz.

Einsatzzeit aus den Understat-Kadern (Startelf: 0 bis Minuten, Einwechslung: Ende minus Minuten bis
Ende), Schüsse mit Minute aus der Tabelle shot. Weil Einsatzzeiten kurz sein können, werden die
Raten mit `prior_minutes` Minuten Teamschnitt geglättet. Fehlt ein Spieler, spielt das Team so, wie
es ohne ihn gespielt hat ("off"); daraus ergeben sich die Faktoren auf eigene Tore und Gegentore."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine

SHOTS_SQL = text("SELECT match_id, team_id, minute, xg FROM shot")
APPS_SQL = text(
    """
    SELECT pm.match_id, pm.team_id, pm.player_id, p.name, pm.started, pm.minutes, m.kickoff
    FROM player_match pm JOIN match m ON m.id = pm.match_id JOIN player p ON p.id = pm.player_id
    WHERE pm.minutes > 0
    """
)


@dataclass
class OnOffModel:
    window_days: int = 365
    prior_minutes: float = 1500.0  # Glättung der Rate ohne den Spieler (Stammspieler fehlen selten)
    max_effect: float = 0.15  # Effekt je Spieler höchstens ±15 %
    floor: float = 0.75
    cap: float = 1.25
    shots: pd.DataFrame = field(default=None, repr=False)
    apps: pd.DataFrame = field(default=None, repr=False)

    def __post_init__(self):
        if self.shots is None:
            self.shots = pd.read_sql(SHOTS_SQL, engine)
        if self.apps is None:
            self.apps = pd.read_sql(APPS_SQL, engine)
            self.apps["kickoff"] = pd.to_datetime(self.apps["kickoff"], utc=True)
        self._shots_by_match = {k: g for k, g in self.shots.groupby("match_id")}
        self._cache: dict = {}

    def player_values(self, team_id: int, before: pd.Timestamp) -> pd.DataFrame:
        """Pro Spieler: Minuten auf dem Platz, Faktor auf eigene Tore und Gegentore, wenn er fehlt."""
        key = (team_id, before)
        if key in self._cache:
            return self._cache[key]
        apps = self.apps[(self.apps["team_id"] == team_id) & (self.apps["kickoff"] < before)
                         & (self.apps["kickoff"] >= before - pd.Timedelta(days=self.window_days))]
        rows, tot_for, tot_against, tot_min = {}, 0.0, 0.0, 0.0
        for match_id, players in apps.groupby("match_id"):
            shots = self._shots_by_match.get(match_id)
            if shots is None:
                continue
            end = max(90.0, float(shots["minute"].max()))
            own = shots["team_id"].to_numpy() == team_id
            minute, xg = shots["minute"].to_numpy(float), shots["xg"].to_numpy(float)
            tot_for += xg[own].sum()
            tot_against += xg[~own].sum()
            tot_min += end
            for p in players.itertuples():
                start, stop = (0.0, float(p.minutes)) if p.started else (end - p.minutes, end)
                on = (minute >= start) & (minute <= stop)
                r = rows.setdefault(p.player_id, {"name": p.name, "min": 0.0, "for": 0.0, "against": 0.0})
                r["min"] += stop - start
                r["for"] += xg[on & own].sum()
                r["against"] += xg[on & ~own].sum()
        if not rows or tot_min <= 0:
            out = pd.DataFrame(columns=["player_id", "name", "min", "attack_mult", "concede_mult"])
        else:
            df = pd.DataFrame.from_dict(rows, orient="index").rename_axis("player_id").reset_index()
            base_for, base_against = tot_for / tot_min, tot_against / tot_min  # pro Minute
            m = self.prior_minutes
            off_min = tot_min - df["min"]
            # Rate ohne den Spieler, geglättet zum Teamschnitt
            off_for = (tot_for - df["for"] + base_for * m) / (off_min + m)
            off_against = (tot_against - df["against"] + base_against * m) / (off_min + m)
            lim = self.max_effect
            df["attack_mult"] = (off_for / base_for).clip(1 - lim, 1 + lim)
            df["concede_mult"] = (off_against / base_against).clip(1 - lim, 1 + lim)
            out = df
        self._cache[key] = out
        return out

    def impact(self, team_id: int, before: pd.Timestamp, missing_ids: set[int]) -> dict:
        vals = self.player_values(team_id, before)
        miss = vals[vals["player_id"].isin(missing_ids)] if len(vals) else vals
        att = float(np.clip(np.prod(miss["attack_mult"]) if len(miss) else 1.0, self.floor, self.cap))
        conc = float(np.clip(np.prod(miss["concede_mult"]) if len(miss) else 1.0, self.floor, self.cap))
        return {"attack_mult": min(att, 1.0), "concede_mult": max(conc, 1.0),
                "missing_regulars": miss.loc[miss["min"] >= 270, "name"].tolist() if len(miss) else [],
                "missing_offense_share": 1 - att, "missing_defensive_regulars": 0}
