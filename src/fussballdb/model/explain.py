"""Kurze Begründung je Prognose, direkt aus den Zahlen des Modells (kein Sprachmodell).
Jeder Punkt ist ein kurzer Satz für die Kachel ("Warum 2:1?"), im Chat und im MCP."""

from fussballdb.ingest.team_mapping import COLLOQUIAL

FAVORIT_ABSTAND = 0.15  # ab so viel Unterschied zwischen Heim- und Auswärtssieg gilt ein Team als Favorit
FORM_SCHWELLE = 0.05  # Form erst erwähnen, wenn sie die Torerwartung um mindestens 5 % verschiebt
AUSFALL_SCHWELLE = 0.03


def short(name: str) -> str:
    return (COLLOQUIAL.get(name) or [name])[0]


def de(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def pct(x: float) -> str:
    return f"{round(x * 100)} %"


def signed_pct(factor: float) -> str:
    v = round((factor - 1) * 100)
    return f"+{v} %" if v > 0 else f"−{abs(v)} %"


def _last_names(names: list[str]) -> str:
    """"Max Mustermann (gesperrt)" -> "Mustermann (gesperrt)" """
    out = []
    for n in names:
        tag = " (gesperrt)" if n.endswith(" (gesperrt)") else ""
        out.append(n.removesuffix(" (gesperrt)").split(" ")[-1] + tag)
    return ", ".join(out)


def explain(p: dict, home: str, away: str, market: tuple[float, float, float] | None = None) -> list[str]:
    """p: Ergebnis von Forecaster.predict_match (mit tip_options, form, impact)."""
    h, a = short(home), short(away)
    lines = []

    # 1. Kräfteverhältnis
    goals = f"erwartet {de(p['exp_home_goals'])} : {de(p['exp_away_goals'])} Tore"
    elo = p.get("elo", {})
    elo_txt = f" (Elo {round(elo['elo_home'])} : {round(elo['elo_away'])})" if elo else ""
    if p["p_home"] - p["p_away"] >= FAVORIT_ABSTAND:
        lines.append(f"{h} Favorit, {pct(p['p_home'])} Siegchance: {goals}{elo_txt}")
    elif p["p_away"] - p["p_home"] >= FAVORIT_ABSTAND:
        lines.append(f"{a} auswärts Favorit, {pct(p['p_away'])} Siegchance: {goals}{elo_txt}")
    else:
        lines.append(f"Ausgeglichen: {goals}{elo_txt}")

    # 2. Form der letzten Wochen
    form = p.get("form") or {}
    parts = [f"{t} {signed_pct(f)} Tore" for t, f in ((h, form.get("home", 1)), (a, form.get("away", 1)))
             if abs(f - 1) >= FORM_SCHWELLE]
    if parts:
        lines.append("Form der letzten Wochen: " + ", ".join(parts))

    # 3. Ausfälle
    impact = p.get("impact") or {}
    for t, side in ((h, "home"), (a, "away")):
        i = impact.get(side) or {}
        missing = i.get("missing_regulars") or []
        att, conc = i.get("attack_mult", 1.0), i.get("concede_mult", 1.0)
        if missing and (1 - att >= AUSFALL_SCHWELLE or conc - 1 >= AUSFALL_SCHWELLE):
            effect = [f"{signed_pct(att)} eigene Tore"] if 1 - att >= AUSFALL_SCHWELLE else []
            if conc - 1 >= AUSFALL_SCHWELLE:
                effect.append(f"{signed_pct(conc)} Gegentore")
            lines.append(f"{t} ohne {_last_names(missing)}: " + ", ".join(effect))

    # 4. Warum genau dieser Tipp (erwartete Punkte nach der Punkteregel)
    opts = p.get("tip_options") or []
    if opts:
        (th, ta), ep = opts[0]
        alt = " · ".join(f"{x}:{y} {de(e, 2)}" for (x, y), e in opts[1:3])
        lines.append(f"{th}:{ta} bringt im Schnitt {de(ep, 2)} Punkte" + (f" (zum Vergleich {alt})" if alt else ""))

    # 5. Buchmacher
    if market:
        mh, md, ma = market
        lines.append(f"Buchmacher: 1 {pct(mh)} · X {pct(md)} · 2 {pct(ma)}")
    return lines
