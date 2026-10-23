"""Stärke der aufgebotenen Startelf gegen die übliche Startelf (Rotation), für den Rückblick-Test.

Die Startelf steht etwa eine Stunde vor dem Anpfiff fest (FotMob), bei Kicktipp darf meist bis zum Anpfiff
getippt werden. Im Rückblick nehmen wir die Startelf aus Understat (player_match.started), live käme sie
von FotMob.

Spielerstärke zum Stichtag, immer nur aus Spielen davor (Schnitt der letzten `window` Einsätze mit mindestens
`min_minutes` Minuten, ab `min_apps` Einsätzen, sonst unbekannt):
- kickbase: Kickbase-Punkte je Einsatz (alle Wettbewerbe; nur Spieler, die heute bei Kickbase sind, daher
  erst ab 2025/26 vollständig)
- note: FotMob-Note (ab 2024/25, soweit die Spielseiten geladen sind)
- xgxa: xG + xA je 90 Minuten (Understat, zur Kontrolle: das misst das Modell schon über die Ausfälle)
- mix: Mittel aus kickbase und note (jeweils standardisiert), wo eins fehlt, das andere

Die übliche Startelf sind die 11 Spieler mit den meisten Minuten in den letzten Spielen des Teams
(AvailabilityModel.player_profile). Abstand d = (Ø Stärke Startelf − Ø Stärke übliche Elf) / Streuung der
Spielerstärken; unbekannte Spieler zählen mit dem Schnitt der übrigen und verschieben d nicht (mindestens
`min_known` der beteiligten Spieler brauchen einen Wert).
Wirkung: Torerwartung × exp(k·d), Gegentorerwartung × exp(−k·d), begrenzt wie die Ausfälle."""

import json
import unicodedata
from bisect import bisect_left
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import text

from fussballdb.db.session import engine
from fussballdb.features.availability import AvailabilityModel

SOURCES = ("kickbase", "note", "xgxa", "mix")


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


class LineupStrength:
    def __init__(self, availability: AvailabilityModel | None = None, window: int = 10, min_minutes: int = 20,
                 min_apps: int = 3, min_known: int = 8):
        self.av = availability or AvailabilityModel()
        self.window, self.min_minutes, self.min_apps, self.min_known = window, min_minutes, min_apps, min_known
        apps = self.av.apps
        self.starters = apps[apps["started"]].groupby(["match_id", "team_id"])["player_id"].apply(set).to_dict()
        # je Quelle und Spieler: sortierte Anstoßzeiten und Werte
        self.series: dict[str, dict[int, tuple[list, list]]] = {}
        played = apps[apps["minutes"] >= min_minutes]
        self._add("xgxa", played["player_id"], played["kickoff"], 90 * played["xgxa"] / played["minutes"].clip(lower=1))
        self._load_kickbase()
        self._load_notes()
        self.center, self.sd = {}, {}
        for src in ("kickbase", "note", "xgxa"):
            self.center[src], self.sd[src] = self._spread(src)
        self._cache: dict = {}

    def _add(self, source: str, players, kickoffs, values) -> None:
        by: dict[int, list] = defaultdict(list)
        for p, k, v in zip(players, kickoffs, values):
            if p is not None and not pd.isna(p) and not pd.isna(v):
                by[int(p)].append((pd.Timestamp(k), float(v)))
        self.series[source] = {p: ([k for k, _ in sorted(x)], [v for _, v in sorted(x)]) for p, x in by.items()}

    def _load_kickbase(self) -> None:
        df = pd.read_sql(text("""
            SELECT p.player_id, k.kickoff, k.points FROM kb_points k JOIN kb_player p ON p.kb_id = k.kb_id
            WHERE p.player_id IS NOT NULL AND k.minutes >= :m AND k.kickoff IS NOT NULL"""), engine,
                         params={"m": self.min_minutes})
        df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
        self._add("kickbase", df["player_id"], df["kickoff"], df["points"])

    def _load_notes(self) -> None:
        """FotMob-Noten den Understat-Spielern zuordnen: gleiches Spiel, gleiches Team, Name (voll oder Nachname)."""
        pages = pd.read_sql(text("""
            SELECT p.match_id, p.lineup, m.kickoff, m.home_team_id, m.away_team_id FROM match_page p
            JOIN match m ON m.id = p.match_id WHERE p.competition = 'BL' AND p.lineup IS NOT NULL AND m.finished"""), engine)
        apps = self.av.apps
        names = {(r.match_id, r.team_id): {} for r in apps[["match_id", "team_id"]].drop_duplicates().itertuples()}
        for r in apps[["match_id", "team_id", "player_id", "name"]].itertuples():
            d = names.get((r.match_id, r.team_id))
            d[_norm(r.name)] = r.player_id
            d.setdefault("_last:" + _norm(r.name).split(" ")[-1], r.player_id)
        rows = []
        for pg in pages.itertuples():
            lu = json.loads(pg.lineup)
            for side, team in (("home", pg.home_team_id), ("away", pg.away_team_id)):
                d = names.get((pg.match_id, team)) or {}
                for p in (lu.get(side) or {}).get("startelf", []) + (lu.get(side) or {}).get("bank", []):
                    if p.get("note") is None:
                        continue
                    if p.get("rein") is not None and (90 - p["rein"]) < self.min_minutes:
                        continue  # Kurzeinsatz: Note kaum aussagekräftig
                    full = _norm(p.get("voller_name") or "")
                    pid = d.get(full) or d.get("_last:" + _norm(p.get("name") or "").split(" ")[-1])
                    if pid is not None:
                        rows.append((pid, pg.kickoff, p["note"]))
        df = pd.DataFrame(rows, columns=["player_id", "kickoff", "note"])
        df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
        self.note_coverage = len(df)
        self._add("note", df["player_id"], df["kickoff"], df["note"])

    def _spread(self, source: str) -> tuple[float, float]:
        """Mitte und Streuung der Spielerstärken (Schnitt je Spieler), zum Standardisieren."""
        means = [np.mean(v[-self.window:]) for _, v in self.series[source].values() if len(v) >= self.min_apps]
        return float(np.mean(means)), float(np.std(means)) or 1.0

    def value(self, source: str, player_id: int, before: pd.Timestamp) -> float | None:
        """Standardisierte Stärke ((Schnitt − Mitte) / Streuung), None ohne genug Einsätze."""
        if source == "mix":
            vals = [v for v in (self.value("kickbase", player_id, before), self.value("note", player_id, before))
                    if v is not None]
            return float(np.mean(vals)) if vals else None
        s = self.series[source].get(player_id)
        if not s:
            return None
        i = bisect_left(s[0], before)
        vals = s[1][max(0, i - self.window):i]
        return (float(np.mean(vals)) - self.center[source]) / self.sd[source] if len(vals) >= self.min_apps else None

    def gap(self, source: str, team_id: int, match_id: int, before: pd.Timestamp) -> float | None:
        """d = Ø Stärke Startelf − Ø Stärke übliche Elf (in Streuungen); None ohne Startelf oder Werte."""
        key = (source, team_id, match_id)
        if key in self._cache:
            return self._cache[key]
        xi = self.starters.get((match_id, team_id))
        out = None
        if xi:
            prof = self.av.player_profile(team_id, before)
            usual = set(prof.sort_values("minutes", ascending=False)["player_id"].head(11))
        if xi and len(usual) >= 11:  # Aufsteiger ohne Vorgeschichte: keine übliche Elf
            vals = {p: self.value(source, p, before) for p in xi | usual}
            known = [v for v in vals.values() if v is not None]
            if len(known) >= self.min_known:
                fill = float(np.mean(known))
                mean = lambda ps: np.mean([vals[p] if vals[p] is not None else fill for p in ps])  # noqa: E731
                out = float(mean(xi) - mean(usual))
        self._cache[key] = out
        return out

    @staticmethod
    def apply(impact: dict | None, d: float | None, k: float, floor: float = 0.75, cap: float = 1.25) -> dict:
        """Ausfall-Wirkung um den Abstand der Startelf ergänzen (d > 0 = stärker als üblich)."""
        out = dict(impact or {"attack_mult": 1.0, "concede_mult": 1.0})
        if d is None or not k:
            return out
        out["attack_mult"] = float(np.clip(out["attack_mult"] * np.exp(k * d), floor, cap))
        out["concede_mult"] = float(np.clip(out["concede_mult"] * np.exp(-k * d), floor, cap))
        return out
