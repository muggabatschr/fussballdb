"""Alternativtipp: dasselbe Modell wie live, dazu die Tor-Skalierung (xG auf das Torniveau der Liga) und als Faktor
Schüsse, Schüsse aufs Tor, Ecken (je mehr als der Gegner, desto besser) und Ruhetage der letzten 10 Spiele
(features/stat_form.py).

Herkunft (November 2026, fussballdb statistik-test): unter 502 Kombinationen der übrigen Teamstatistik die beste im
Einstellzeitraum 2016–20; im Test 2021–26 RPS −0,0007, besser in 91 % der Bootstrap-Ziehungen und 9 von 11
Saisons, nach der Standardregel 2.186 statt 2.170 Punkte. Knapp an der Schwelle und nach vielen Versuchen gefunden,
deshalb nicht im Hauptmodell: Die Kombination ist hier fest eingefroren und läuft als Alternativtipp mit
(prediction.model_version = ALT_VERSION). Am Saisonende 2026/27 zählen nur die Live-Tipps ab dem 11.11.2026
(`fussballdb alternativ-bilanz`): Holt sie dort mehr Punkte und ist der RPS besser, wird sie ins Modell übernommen.
"""

import json

import numpy as np
import pandas as pd

from fussballdb.features.stat_form import METRICS, REST, StatForm
from fussballdb.model.dixon_coles import DixonColes
from fussballdb.model.ensemble import Forecaster
from fussballdb.model.tips import tip_options, tip_line
from fussballdb.config import TIPP_PUNKTE

ALT_VERSION = "alt-schuss-ruhe-v1"
ALT_BETAS = {"schuesse": 0.015, "aufs_tor": 0.015, "ecken": 0.015, REST: -0.015}
LIVE_SINCE = pd.Timestamp("2026-11-11", tz="UTC")  # ab hier zählen die Alternativtipps für den Nachtest

LABELS = {"schuesse": "Schüsse", "aufs_tor": "Schüsse aufs Tor", "ecken": "Ecken"}
INTRO = ("Alternativmodell: wie das Hauptmodell, dazu xG auf das echte Torniveau gerechnet und Schüsse, Schüsse aufs "
         "Tor, Ecken und Ruhetage der letzten 10 Spiele. Im Rückblick 2021–26 knapp besser (2.186 statt 2.170 "
         "Punkte), aber noch nicht sicher belegt; wird bis Saisonende 2026/27 live geprüft.")


def alt_forecaster(values: pd.DataFrame | None = None) -> Forecaster:
    return Forecaster(dc=DixonColes(goal_scale=True), values=values)


def adjust(hi: dict, ai: dict, sf: StatForm, home_id: int, away_id: int, cutoff: pd.Timestamp,
           kickoff: pd.Timestamp) -> tuple[dict, dict, dict]:
    """Wirkungen des Hauptmodells (Ausfälle, Belastung, Ballbesitz) um die Statistik-Faktoren ergänzen. Liefert
    dazu die Rohwerte für die Begründung."""
    zh, za = sf.z(home_id, pd.Timestamp(cutoff)), sf.z(away_id, pd.Timestamp(cutoff))
    rest = sf.rest_z(home_id, away_id, kickoff)
    info = {"z_home": zh, "z_away": za, "rest_home": sf.rest_days(home_id, kickoff),
            "rest_away": sf.rest_days(away_id, kickoff), "scale": sf.scale, "rest_z": rest}
    return StatForm.apply(hi, zh, ALT_BETAS, rest), StatForm.apply(ai, za, ALT_BETAS, -rest), info


def _de(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def _team_line(team: str, z: dict | None, scale: dict) -> str | None:
    if not z:
        return None
    parts, s = [], 0.0
    for name in ("schuesse", "aufs_tor", "ecken"):
        if np.isnan(z.get(name, np.nan)):
            continue
        s += ALT_BETAS[name] * z[name]
        diff = z[name] * scale[METRICS[name]]
        parts.append(f"{LABELS[name]} {'+' if diff >= 0 else '−'}{_de(abs(diff))}")
    if not parts:
        return None
    pct = (np.exp(s) - 1) * 100
    return (f"{team} je Spiel gegenüber den Gegnern: {', '.join(parts)} → Torerwartung "
            f"{'+' if pct >= 0 else '−'}{_de(abs(pct))} %")


def explanation(main: dict, alt: dict, info: dict, home: str, away: str) -> list[str]:
    """Begründung des Alternativtipps: was das Alternativmodell anders sieht als das Hauptmodell."""
    lines = [INTRO]
    for team, z in ((home, info["z_home"]), (away, info["z_away"])):
        line = _team_line(team, z, info["scale"])
        if line:
            lines.append(line)
    rh, ra = info["rest_home"], info["rest_away"]
    if abs(rh - ra) >= 1:
        more, less = (home, away) if rh > ra else (away, home)
        pct = (np.exp(abs(ALT_BETAS[REST] * info["rest_z"])) - 1) * 100
        days = round(abs(rh - ra))
        lines.append(f"{more} hatte {days} {'Tag' if days == 1 else 'Tage'} mehr Pause seit dem letzten Ligaspiel; im Rückblick "
                     f"lag das Team mit mehr Pause minimal schlechter → {less} +{_de(pct)} %")
    lines.append(f"Erwartete Tore {_de(alt['exp_home_goals'])} : {_de(alt['exp_away_goals'])} (Hauptmodell "
                 f"{_de(main['exp_home_goals'])} : {_de(main['exp_away_goals'])}), Sieg {home} "
                 f"{alt['p_home'] * 100:.0f} %, Remis {alt['p_draw'] * 100:.0f} %, Sieg {away} "
                 f"{alt['p_away'] * 100:.0f} % (Hauptmodell {main['p_home'] * 100:.0f} / {main['p_draw'] * 100:.0f} / "
                 f"{main['p_away'] * 100:.0f} %)")
    lines.append(tip_line(tip_options(alt["score_probs"], TIPP_PUNKTE)))
    return lines


def explanation_json(main: dict, alt: dict, info: dict, home: str, away: str) -> str:
    return json.dumps(explanation(main, alt, info, home, away), ensure_ascii=False)
