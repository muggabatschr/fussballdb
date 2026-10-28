"""Weiterkommen in einem K.-o.-Spiel (DFB-Pokal): Sieg nach 90 Minuten, sonst Verlängerung, sonst
Elfmeterschießen. Prognose und Tipp gelten weiter für die 90 Minuten.

Verlängerung: 30 Minuten mit einem Drittel der erwarteten Tore aus der Prognose (Poisson, unabhängig);
Elfmeterschießen: 50:50 (Favoriten gewinnen es kaum öfter als Außenseiter). Die Verlängerung ist bei
Unentschieden nach 90 Minuten unabhängig vom Stand angenommen."""

from math import exp, factorial

ET_SHARE = 1 / 3  # Anteil der Torerwartung in der Verlängerung (30 von 90 Minuten)
PENALTY_HOME = 0.5


def _poisson(lam: float, k: int) -> float:
    return exp(-lam) * lam**k / factorial(k)


def extra_time(exp_home: float, exp_away: float, share: float = ET_SHARE, max_goals: int = 8) -> tuple[float, float, float]:
    """Chancen Heimsieg, Gleichstand, Gastsieg in der Verlängerung."""
    lh, la = exp_home * share, exp_away * share
    ph = [_poisson(lh, k) for k in range(max_goals + 1)]
    pa = [_poisson(la, k) for k in range(max_goals + 1)]
    home = sum(ph[i] * pa[j] for i in range(max_goals + 1) for j in range(i))
    draw = sum(ph[i] * pa[i] for i in range(max_goals + 1))
    return home, draw, max(0.0, 1 - home - draw)


def advance(p_home: float, p_draw: float, p_away: float, exp_home: float, exp_away: float,
            share: float = ET_SHARE, penalty_home: float = PENALTY_HOME) -> dict:
    """Chance aufs Weiterkommen je Team und die Anteile der Wege dorthin."""
    et_h, et_d, et_a = extra_time(exp_home, exp_away, share)
    home = p_home + p_draw * (et_h + et_d * penalty_home)
    return {"home": home, "away": 1 - home, "verlaengerung": p_draw, "elfmeterschiessen": p_draw * et_d}
