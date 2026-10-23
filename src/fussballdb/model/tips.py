"""Tipps und Tipp-Punkte je Tipprunde. Das Modell rechnet einmal die Wahrscheinlichkeit jedes Ergebnisses
(prediction.score_probs); daraus folgt für jede Punkteregel der Tipp mit den meisten erwarteten Punkten.
Für die Standardregel (config.TIPP_PUNKTE) gelten die gespeicherten Tipps unverändert."""

import json
import re
from functools import lru_cache

import numpy as np

from fussballdb.config import TIPP_PUNKTE
from fussballdb.model.ensemble import MAX_TIP_GOALS, kicktipp_points

Rule = tuple[int, int, int, int]  # Sieg Tendenz, Sieg Tordifferenz, exakt, Remis Tendenz
TIP_LINE = re.compile(r"^\d+:\d+ bringt im Schnitt ")


@lru_cache(maxsize=16)
def _table(rule: Rule, goals: int) -> np.ndarray:
    """Punkte je Tipp (bis MAX_TIP_GOALS) und Ergebnis (bis goals-1)."""
    return np.array([[[[kicktipp_points(th, ta, h, a, rule) for a in range(goals)] for h in range(goals)]
                      for ta in range(MAX_TIP_GOALS + 1)] for th in range(MAX_TIP_GOALS + 1)], dtype=float)


def tip_options(score_probs: str | list, rule: Rule, n: int = 3) -> list[tuple[tuple[int, int], float]]:
    """Die n Tipps mit den meisten erwarteten Punkten nach `rule`."""
    m = np.asarray(json.loads(score_probs) if isinstance(score_probs, str) else score_probs, dtype=float)
    m = m / m.sum()
    expected = np.tensordot(_table(rule, m.shape[0]), m, axes=([2, 3], [0, 1]))
    order = np.argsort(expected, axis=None)[::-1][:n]
    return [((int(h), int(a)), float(expected[h, a])) for h, a in (np.unravel_index(i, expected.shape) for i in order)]


def tip_line(options: list[tuple[tuple[int, int], float]]) -> str:
    """Begründungszeile wie in model/explain.py: "2:1 bringt im Schnitt 1,65 Punkte (zum Vergleich …)"."""
    de = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731
    (th, ta), ep = options[0]
    alt = " · ".join(f"{x}:{y} {de(e)}" for (x, y), e in options[1:3])
    return f"{th}:{ta} bringt im Schnitt {de(ep)} Punkte" + (f" (zum Vergleich {alt})" if alt else "")


def apply_rule(game: dict, rule: Rule) -> dict:
    """Tipp, Tipp-Punkte und Begründungszeile eines Spiels (Felder wie in /matchday) nach `rule` umrechnen.
    Ohne score_probs oder bei der Standardregel bleibt alles, wie es gespeichert ist."""
    probs = game.pop("score_probs", None)
    if tuple(rule) == tuple(TIPP_PUNKTE) or not probs or game.get("tip_home") is None:
        return game
    opts = tip_options(probs, rule)
    game["tip_home"], game["tip_away"] = opts[0][0]
    if game.get("finished") and game.get("home_goals") is not None:
        game["points"] = kicktipp_points(game["tip_home"], game["tip_away"], game["home_goals"], game["away_goals"], rule)
    if isinstance(game.get("explanation"), list):
        game["explanation"] = [tip_line(opts) if TIP_LINE.match(line) else line for line in game["explanation"]]
    return game


def summary(points: list[int], rule: Rule) -> dict:
    """Bilanz wie in /matchday: Spiele, Punkte, richtige Tendenzen, exakte Treffer."""
    return {"spiele": len(points), "punkte": sum(points), "tendenz": sum(1 for p in points if p > 0),
            "exakt": sum(1 for p in points if p == rule[2])}
