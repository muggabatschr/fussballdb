"""Test: wird die Prognose besser, wenn ein Sprachmodell die Modellprognose (Dixon-Coles + Elo) und die aufbereiteten
Daten bekommt und die Wahrscheinlichkeiten und den Tipp anpassen darf?

Kein Vorwissen aus der Zukunft:
- Das Sprachmodell ist das lokale aus LM Studio (Qwen 3.8 27B). Es kennt nach eigener Aussage und nach Stichproben
  (CL-Finale 2025, Meister 2024/25, Eröffnungsspiel 2025/26) nichts nach Januar 2025. Getestet werden nur Spiele ab
  2025/26, deren Ergebnis es also nicht aus dem Training kennen kann. Es bekommt keine Werkzeuge und kein Internet.
- Die Modellprognose ist die gespeicherte vom Tippzeitpunkt: live (vor dem Anpfiff gerechnet) oder Rückblick
  (mit Daten bis zum Anpfiff). Live-Prognosen, die nach dem Anpfiff noch einmal überschrieben wurden (as_of nach
  dem Anpfiff), fallen heraus.
- Tabelle, Form und Ausfälle nur mit Spielen vor dem Anpfiff; Ausfälle so, wie das Modell sie zum Stichtag kannte
  (prediction.missing_*). Überschriften nur, wenn sie mindestens 24 Stunden vor dem Anpfiff erschienen sind und
  kein Ergebnis nennen: Vorberichte werden nach dem Spiel umgeschrieben, Google News behält das alte Datum.
- Marktquoten bekommt das Sprachmodell nicht, sie dienen nur als Vergleich.

Gemessen: RPS, Brier, Log-Loss je Wettbewerb und zusammen, dazu die Tipp-Punkte nach der Standardregel für den
Modelltipp, den Tipp des Sprachmodells und den Tipp mit den meisten erwarteten Punkten aus den Wahrscheinlichkeiten
des Sprachmodells. Varianten: mit_modell (Modellprognose, Tabelle, Form, Ausfälle, Überschriften), alles (dazu
Saisonschnitt Heim/Auswärts, Teamstatistik der letzten 5, Tore minus xG, Ruhetage, Kaderwert, Ligainsider-Startelf,
direkte Duelle, Temperatur und Wind) und alles_ohne_modell (dieselben Daten ohne Modellprognose). Ergebnis 11/2026:
alle drei verworfen, mehr Daten machen es schlechter, ohne Modellprognose liegt es klar hinter dem Modell. Antworten werden zwischengespeichert (.cache/ki_tipp.jsonl), ein Abbruch verliert nichts.
"""

import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import text

from fussballdb.config import LOCAL_LLM_MODEL, LOCAL_LLM_URL, TIPP_PUNKTE
from fussballdb.db.session import engine
from fussballdb.model.ensemble import MAX_TIP_GOALS, kicktipp_points
from fussballdb.model.evaluate import scores
from fussballdb.model.tips import tip_options

CACHE = Path(".cache/ki_tipp.jsonl")
FIRST_SEASON = 2025  # erste Saison nach dem Wissensstand des Sprachmodells
NEWS_DAYS = 3
# Überschriften erst ab 24 Stunden vor dem Anpfiff und ohne Ergebnis darin: Zeitungen schreiben Vorberichte nach dem
# Spiel zum Bericht um, Google News behält das alte Datum ("Einfallslose Kölner unterliegen Leverkusen", laut Feed
# drei Minuten vor dem Anpfiff erschienen)
NEWS_GAP_H = 24
NEWS_SCORE = re.compile(r"\d+\s*:\s*\d+")

SYSTEM = """Du bist Fußball-Analyst und gibst Tipps für eine Kicktipp-Runde. Du bekommst die Prognose eines
statistischen Modells (Dixon-Coles auf xG mit Form und Elo, Ausfälle schon eingerechnet) und die Daten vor dem
Anpfiff. Deine Aufgabe: die Wahrscheinlichkeiten für Heimsieg, Remis und Auswärtssieg so angeben, wie du sie nach
allen Informationen einschätzt, und einen Ergebnistipp abgeben. Weiche nur vom Modell ab, wenn die Daten einen Grund
liefern, den das Modell nicht kennt oder falsch gewichtet. Punkteregel: {rule}. Antworte nur mit dem JSON."""
SYSTEM_ALONE = """Du bist Fußball-Analyst und gibst Tipps für eine Kicktipp-Runde. Du bekommst die Daten vor dem Anpfiff
(Tabelle, Form, Statistiken, Ausfälle, Kaderwerte, Aufstellung, Meldungen). Deine Aufgabe: die Wahrscheinlichkeiten
für Heimsieg, Remis und Auswärtssieg so angeben, wie du sie nach allen Informationen einschätzt, und einen
Ergebnistipp abgeben. Punkteregel: {rule}. Antworte nur mit dem JSON."""
RULE = "Tendenz richtig {0} Punkte, Tordifferenz richtig {1}, exaktes Ergebnis {2}, richtiges Remis mit falschem Ergebnis {3}"

SCHEMA = {"type": "json_schema", "json_schema": {"name": "tipp", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["p_heim", "p_remis", "p_gast", "tipp_heim", "tipp_gast", "grund"],
    "properties": {"p_heim": {"type": "number"}, "p_remis": {"type": "number"}, "p_gast": {"type": "number"},
                   "tipp_heim": {"type": "integer"}, "tipp_gast": {"type": "integer"},
                   "grund": {"type": "string"}}}}}


def _pct(p: float) -> str:
    return f"{100 * p:.0f} %"


def _table(rows: list, before) -> dict:
    """Tabelle aus den Spielen vor `before`: Platz, Punkte, Tore, Spiele."""
    tab: dict = {}
    for r in rows:
        if r.kickoff >= before or r.hg is None:
            continue
        for t, gf, ga in ((r.h, r.hg, r.ag), (r.a, r.ag, r.hg)):
            x = tab.setdefault(t, [0, 0, 0, 0])
            x[0] += 3 if gf > ga else 1 if gf == ga else 0
            x[1] += gf
            x[2] += ga
            x[3] += 1
    order = sorted(tab, key=lambda t: (-tab[t][0], -(tab[t][1] - tab[t][2]), -tab[t][1]))
    return {t: {"platz": i + 1, "punkte": tab[t][0], "tore": f"{tab[t][1]}:{tab[t][2]}", "spiele": tab[t][3]}
            for i, t in enumerate(order)}


def _form(rows: list, team: int, before, names: dict, n: int = 5) -> list[str]:
    out = []
    for r in sorted((r for r in rows if r.kickoff < before and r.hg is not None and team in (r.h, r.a)),
                    key=lambda r: r.kickoff, reverse=True)[:n]:
        home = r.h == team
        gf, ga = (r.hg, r.ag) if home else (r.ag, r.hg)
        xg = ""
        if getattr(r, "hx", None) is not None and r.ax is not None:
            xf, xa = (r.hx, r.ax) if home else (r.ax, r.hx)
            xg = f", xG {xf:.1f}:{xa:.1f}"
        res = "S" if gf > ga else "N" if gf < ga else "U"
        out.append(f"{res} {gf}:{ga} {'gegen' if home else 'bei'} {names[r.a if home else r.h]}{xg}")
    return out


def _cases() -> list[dict]:
    """Spiele ab FIRST_SEASON mit Prognose vom Tippzeitpunkt, Bundesliga und 2. Liga."""
    out = []
    with engine.connect() as conn:
        names = {r.id: r.name for r in conn.execute(text("SELECT id, name FROM team"))}
        bl = conn.execute(text("""
            SELECT m.id, s.start_year AS season, m.matchday, m.kickoff, m.home_team_id AS h, m.away_team_id AS a,
                   m.home_goals AS hg, m.away_goals AS ag, hs.xg AS hx, as_.xg AS ax
            FROM match m JOIN season s ON s.id = m.season_id
            LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
            LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
            WHERE s.start_year >= :f AND m.finished"""), {"f": FIRST_SEASON}).all()
        preds = {r.match_id: r for r in conn.execute(text("""
            SELECT p.* FROM prediction p JOIN match m ON m.id = p.match_id
            WHERE m.finished AND (p.as_of IS NULL OR p.as_of <= m.kickoff)""")).all()}
        odds = {r.match_id: r for r in conn.execute(text("""
            SELECT match_id, home, draw, away FROM odds WHERE bookmaker = 'Avg' AND is_closing""")).all()}
        news: dict = {}
        for r in conn.execute(text("SELECT team_id, title, source, published_at FROM news_item WHERE published_at >= :d"),
                              {"d": "2025-07-01"}):
            news.setdefault(r.team_id, []).append(r)
        x = _extra_data(conn, "BL")
        for m in bl:
            p = preds.get(m.id)
            if not p:
                continue
            season_rows = [r for r in bl if r.season == m.season]
            o = odds.get(m.id)
            out.append({"wettbewerb": "Bundesliga", "comp": "BL", "id": m.id, "saison": m.season, "runde": m.matchday,
                        "kickoff": m.kickoff, "heim": names[m.h], "gast": names[m.a], "hg": m.hg, "ag": m.ag,
                        "p": (p.p_home, p.p_draw, p.p_away), "lam": (p.exp_home_goals, p.exp_away_goals),
                        "tipp": (p.tip_home, p.tip_away), "score_probs": p.score_probs,
                        "begruendung": json.loads(p.explanation) if p.explanation else [],
                        "fehlen": (p.missing_home, p.missing_away),
                        "tabelle": _table(season_rows, m.kickoff), "ids": (m.h, m.a),
                        "form": (_form(season_rows, m.h, m.kickoff, names), _form(season_rows, m.a, m.kickoff, names)),
                        "presse": tuple(_news(news.get(t, []), m.kickoff) for t in (m.h, m.a)),
                        "markt": _market(o) if o else None,
                        "mehr": _extra_lines(x, m, season_rows, names)})
        eu_names = {r.id: r.name for r in conn.execute(text("SELECT id, name FROM eu_team"))}
        d2 = conn.execute(text("""
            SELECT m.id, m.season, m.round_no, m.kickoff, m.home_id AS h, m.away_id AS a, m.home_goals AS hg,
                   m.away_goals AS ag, m.home_xg AS hx, m.away_xg AS ax
            FROM eu_match m WHERE m.competition = 'D2' AND m.season >= :f AND m.finished"""), {"f": FIRST_SEASON}).all()
        eup = {}
        for r in conn.execute(text("""
                SELECT p.* FROM eu_prediction p JOIN eu_match m ON m.id = p.match_id
                WHERE m.competition = 'D2' AND m.finished AND p.as_of <= m.kickoff""")).all():
            if r.match_id not in eup or r.basis == "live":  # live vor dem Anpfiff vor Rückblick
                eup[r.match_id] = r
        x = _extra_data(conn, "D2")
        for m in d2:
            p = eup.get(m.id)
            if not p:
                continue
            season_rows = [r for r in d2 if r.season == m.season]
            out.append({"wettbewerb": "2. Bundesliga", "comp": "D2", "id": m.id, "saison": m.season, "runde": m.round_no,
                        "kickoff": m.kickoff, "heim": eu_names[m.h], "gast": eu_names[m.a], "hg": m.hg, "ag": m.ag,
                        "p": (p.p_home, p.p_draw, p.p_away), "lam": (p.exp_home_goals, p.exp_away_goals),
                        "tipp": (p.tip_home, p.tip_away), "score_probs": None,
                        "begruendung": json.loads(p.explanation) if p.explanation else [],
                        "fehlen": (None, None), "tabelle": _table(season_rows, m.kickoff), "ids": (m.h, m.a),
                        "form": (_form(season_rows, m.h, m.kickoff, eu_names), _form(season_rows, m.a, m.kickoff, eu_names)),
                        "presse": ([], []), "markt": None,
                        "mehr": _extra_lines(x, m, season_rows, eu_names)})
    return sorted(out, key=lambda c: c["kickoff"])


def _extra_data(conn, comp: str) -> dict:
    """Alle Statistiken, die es außer der Modellprognose gibt (auch die fürs Modell verworfenen): Spiele aller
    Saisons (direkte Duelle, Abschluss gegenüber xG), Schüsse, Großchancen, Ecken, PPDA, Laufdaten der Sportschau,
    Kaderwerte, voraussichtliche Aufstellung (Ligainsider), Temperatur und Wind zum Anpfiff."""
    if comp == "BL":
        games = conn.execute(text("""
            SELECT m.id, m.kickoff, m.home_team_id AS h, m.away_team_id AS a, m.home_goals AS hg, m.away_goals AS ag,
                   hs.xg AS hx, as_.xg AS ax FROM match m
            LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
            LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
            WHERE m.finished""")).all()
        team_stats = {(r.match_id, r.team_id): r for r in conn.execute(text("""
            SELECT match_id, team_id, shots, shots_on_target, big_chances, corners, ppda FROM match_team_stats""")).all()}
        values = conn.execute(text("SELECT team_id, stichtag, value_eur FROM squad_value ORDER BY stichtag")).all()
        lineups: dict = {}
        for r in conn.execute(text("""SELECT team_id, fetched_at, player_name FROM lineup_snapshot
                                       WHERE status = 'vorschau' AND role = 'start' ORDER BY id""")):
            lineups.setdefault(r.team_id, {}).setdefault(r.fetched_at, []).append(r.player_name)
        weather = {r.match_id: r for r in conn.execute(text("""
            SELECT match_id, temp_c, wind_kmh FROM match_weather WHERE competition = 'BL'""")).all()}
    else:
        games = conn.execute(text("""
            SELECT id, kickoff, home_id AS h, away_id AS a, home_goals AS hg, away_goals AS ag, home_xg AS hx, away_xg AS ax,
                   competition FROM eu_match WHERE finished AND competition IN ('D2', 'DFB')""")).all()
        team_stats, lineups = {}, {}
        values = conn.execute(text("SELECT team_id, stichtag, value_eur FROM eu_squad_value ORDER BY stichtag")).all()
        weather = {r.match_id: r for r in conn.execute(text("""
            SELECT match_id, temp_c, wind_kmh FROM match_weather WHERE competition = 'D2'""")).all()}
    extra = {(r.match_id, r.is_home): r for r in conn.execute(text("""
        SELECT match_id, is_home, distance_km, sprints, possession, duels_won_pct, pass_pct FROM match_extra_stats
        WHERE competition = :c"""), {"c": comp}).all()}
    vals: dict = {}
    for r in values:
        vals.setdefault(r.team_id, []).append((r.stichtag, r.value_eur))
    return {"games": sorted(games, key=lambda g: g.kickoff), "stats": team_stats, "extra": extra, "values": vals,
            "lineups": lineups, "weather": weather, "comp": comp}


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _f(v, digits: int = 1) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def _extra_lines(x: dict, m, season_rows: list, names: dict) -> list[str]:
    """Zusätzliche Zeilen für die Variante "alles", nur mit Daten vor dem Anpfiff."""
    k = m.kickoff
    out = []
    before = [g for g in x["games"] if g.kickoff < k and g.hg is not None]
    league = [g for g in before if getattr(g, "competition", "D2") == "D2"] if x["comp"] == "D2" else before
    for t in (m.h, m.a):
        name = names[t]
        # Saison bisher, getrennt nach Heim und Auswärts
        parts = []
        for label, mine in (("zu Hause", lambda r: r.h == t), ("auswärts", lambda r: r.a == t)):
            gs = [r for r in season_rows if r.kickoff < k and r.hg is not None and mine(r)]
            if gs:
                home = label == "zu Hause"
                gf = _avg([r.hg if home else r.ag for r in gs])
                ga = _avg([r.ag if home else r.hg for r in gs])
                xf = _avg([(r.hx if home else r.ax) for r in gs])
                xa = _avg([(r.ax if home else r.hx) for r in gs])
                parts.append(f"{label} {len(gs)} Spiele, Tore {_f(gf)}:{_f(ga)}, xG {_f(xf)}:{_f(xa)} je Spiel")
        if parts:
            out.append(f"Saison bisher {name}: " + "; ".join(parts) + ".")
        last = [g for g in league if t in (g.h, g.a)][-5:]
        if last:
            def side(g, own: bool):
                return (g.h == t) == own
            st = [(x["stats"].get((g.id, t)), x["stats"].get((g.id, g.a if g.h == t else g.h))) for g in last]
            ex = [(x["extra"].get((g.id, g.h == t)), x["extra"].get((g.id, g.h != t))) for g in last]
            bits = []
            if any(a for a, _ in st):
                for label, attr, d in (("Schüsse", "shots", 1), ("aufs Tor", "shots_on_target", 1),
                                       ("Großchancen", "big_chances", 1), ("Ecken", "corners", 1)):
                    bits.append(f"{label} {_f(_avg([getattr(a, attr) for a, _ in st if a]), d)}:"
                                f"{_f(_avg([getattr(b, attr) for _, b in st if b]), d)}")
                bits.append(f"PPDA {_f(_avg([a.ppda for a, _ in st if a]))}")
            if any(a for a, _ in ex):
                for label, attr, d, unit, both in (("Ballbesitz", "possession", 0, " %", False),
                                                   ("Laufleistung", "distance_km", 1, " km", True),
                                                   ("Sprints", "sprints", 0, "", True),
                                                   ("Zweikämpfe gewonnen", "duels_won_pct", 0, " %", False),
                                                   ("Passquote", "pass_pct", 0, " %", False)):
                    own = _avg([getattr(a, attr) for a, _ in ex if a])
                    if own is None:  # 2. Liga: Laufdaten fehlen bei der Sportschau
                        continue
                    opp = _avg([getattr(b, attr) for _, b in ex if b]) if both else None
                    bits.append(f"{label} {_f(own, d)}" + (f":{_f(opp, d)}" if opp is not None else "") + unit)
            if bits:
                out.append(f"Letzte {len(last)} Spiele {name} im Schnitt (eigene:gegnerische): " + ", ".join(bits) + ".")
            rest = (k - last[-1].kickoff).days
            out.append(f"{name}: {rest} Tage seit dem letzten Ligaspiel.")
        ten = [g for g in league if t in (g.h, g.a) and g.hx is not None][-10:]
        if len(ten) >= 5:
            diff = sum((g.hg - g.hx) if g.h == t else (g.ag - g.ax) for g in ten)
            conc = sum((g.ag - g.ax) if g.h == t else (g.hg - g.hx) for g in ten)
            out.append(f"{name} in den letzten {len(ten)} Spielen: Tore minus xG {diff:+.1f}, Gegentore minus xG des Gegners {conc:+.1f}.")
        v = [val for day, val in x["values"].get(t, []) if day <= k.date()]
        if v:
            out.append(f"Kaderwert {name}: {v[-1] / 1e6:.0f} Mio. €.")
        snaps = {at: ps for at, ps in x["lineups"].get(t, {}).items() if k - _days(4) <= at < k}
        if snaps:
            at = max(snaps)
            out.append(f"Voraussichtliche Startelf {name} (Ligainsider, {at:%d.%m. %H:%M}): " + ", ".join(snaps[at]) + ".")
    h2h = [g for g in before if {g.h, g.a} == {m.h, m.a}][-5:]
    if h2h:
        out.append("Direkte Duelle (zuletzt): " + "; ".join(
            f"{g.kickoff:%d.%m.%Y} {names.get(g.h, '?')} {g.hg}:{g.ag} {names.get(g.a, '?')}" for g in reversed(h2h)) + ".")
    w = x["weather"].get(m.id)
    if w and w.temp_c is not None:  # gemessen, Regen weggelassen (stünde nicht sicher in der Vorhersage)
        out.append(f"Wetter zum Anpfiff: {w.temp_c:.0f} Grad, Wind {_f(w.wind_kmh, 0)} km/h.")
    return out


def _news(items: list, kickoff) -> list[str]:
    from fussballdb.reports import PRESS_SKIP

    ok = [n for n in items if kickoff - _days(NEWS_DAYS) <= n.published_at <= kickoff - _hours(NEWS_GAP_H)
          and not NEWS_SCORE.search(n.title) and not PRESS_SKIP.search(n.title)]
    return [n.title for n in sorted(ok, key=lambda n: n.published_at, reverse=True)][:5]


def _hours(n: int):
    from datetime import timedelta

    return timedelta(hours=n)


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


def _market(o) -> tuple | None:
    if not (o.home and o.draw and o.away):
        return None
    inv = np.array([1 / o.home, 1 / o.draw, 1 / o.away])
    return tuple(inv / inv.sum())


def prompt(c: dict, with_model: bool = True, full: bool = False) -> str:
    """Alles, was zum Tippzeitpunkt bekannt war, als Text."""
    h, a = c["heim"], c["gast"]
    th, ta = (c["tabelle"].get(t) for t in c["ids"])
    lines = [f"{c['wettbewerb']} {c['saison']}/{str(c['saison'] + 1)[2:]}, {c['runde']}. Spieltag, "
             f"{c['kickoff']:%d.%m.%Y}: {h} (Heim) gegen {a} (Gast)."]
    if with_model:
        ph, pd_, pa = c["p"]
        lines.append(f"Modell: Heimsieg {_pct(ph)}, Remis {_pct(pd_)}, Auswärtssieg {_pct(pa)}; "
                     f"erwartete Tore {c['lam'][0]:.2f} : {c['lam'][1]:.2f}; Modelltipp {c['tipp'][0]}:{c['tipp'][1]}.")
        if c["score_probs"]:
            m = np.asarray(json.loads(c["score_probs"]), dtype=float)
            top = sorted(((m[i, j], i, j) for i in range(m.shape[0]) for j in range(m.shape[1])), reverse=True)[:5]
            lines.append("Wahrscheinlichste Ergebnisse: " + ", ".join(f"{i}:{j} {_pct(v)}" for v, i, j in top) + ".")
        if c["begruendung"]:
            lines.append("Begründung des Modells: " + " | ".join(c["begruendung"]))
    for team, t in ((h, th), (a, ta)):
        if t:
            lines.append(f"Tabelle vor dem Spiel: {team} Platz {t['platz']}, {t['punkte']} Punkte, Tore {t['tore']} "
                         f"nach {t['spiele']} Spielen.")
    for team, f in zip((h, a), c["form"]):
        if f:
            lines.append(f"Letzte Spiele {team} (neueste zuerst): " + "; ".join(f) + ".")
    for team, f in zip((h, a), c["fehlen"]):
        if f:
            lines.append(f"Fehlen bei {team}: {f}.")
    for team, n in zip((h, a), c["presse"]):
        if n:
            lines.append(f"Überschriften der letzten {NEWS_DAYS} Tage zu {team}: " + " | ".join(n))
    if full:
        lines += c["mehr"]
    return "\n".join(lines)


def _key(c: dict, variant: str, body: str) -> str:
    return hashlib.sha1(f"{c['comp']}|{c['id']}|{variant}|{LOCAL_LLM_MODEL}|{body}".encode()).hexdigest()


def _cache() -> dict:
    if not CACHE.exists():
        return {}
    return {d["key"]: d for d in map(json.loads, CACHE.read_text().splitlines()) if d.get("key")}


def ask(body: str, reasoning: str = "none", timeout: float = 600, system: str = SYSTEM) -> dict:
    payload = {"model": LOCAL_LLM_MODEL, "temperature": 0, "max_tokens": 4000, "response_format": SCHEMA,
               "messages": [{"role": "system", "content": system.format(rule=RULE.format(*TIPP_PUNKTE))},
                            {"role": "user", "content": body}]}
    if reasoning:
        payload["reasoning_effort"] = reasoning
    r = httpx.post(f"{LOCAL_LLM_URL}/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(re.search(r"\{.*\}", content, re.S).group(0))


def run(variants: tuple[str, ...] = ("mit_modell",), comps: tuple[str, ...] = ("BL", "D2"), limit: int | None = None,
        workers: int = 2, reasoning: str = "none", log=print) -> None:
    """Fehlende Antworten holen. Varianten: mit_modell (Modellprognose + Tabelle, Form, Ausfälle, Überschriften),
    alles (dazu alle übrigen Statistiken, auch die fürs Modell verworfenen), alles_ohne_modell (alle Daten, aber
    ohne die Modellprognose: kann das Sprachmodell allein mithalten?)."""
    cases = [c for c in _cases() if c["comp"] in comps]
    if limit:
        cases = cases[-limit:]
    cache = _cache()
    todo = []
    for v in variants:
        for c in cases:
            body = prompt(c, with_model=v in ("mit_modell", "alles"), full=v.startswith("alles"))
            k = _key(c, v + reasoning, body)
            if k not in cache:
                todo.append((k, c, v, body))
    log(f"{len(cases)} Spiele, {len(todo)} Anfragen offen")
    CACHE.parent.mkdir(exist_ok=True)

    def one(item):
        k, c, v, body = item
        try:
            ans = ask(body, reasoning, system=SYSTEM_ALONE if v == "alles_ohne_modell" else SYSTEM)
        except Exception as exc:  # einzelne Antwort kaputt: beim nächsten Lauf erneut
            return None, f"{c['comp']} {c['id']}: {type(exc).__name__}"
        return {"key": k, "comp": c["comp"], "id": c["id"], "variante": v + reasoning, "antwort": ans}, None

    done = 0
    with ThreadPoolExecutor(workers) as pool, CACHE.open("a") as f:
        for rec, err in pool.map(one, todo):
            done += 1
            if rec:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            if err:
                log("  " + err)
            if done % 25 == 0:
                log(f"  {done}/{len(todo)}")


def _llm_p(ans: dict, fallback: tuple) -> np.ndarray:
    p = np.array([ans.get("p_heim", 0), ans.get("p_remis", 0), ans.get("p_gast", 0)], dtype=float)
    if p.max() > 1.5:  # in Prozent geantwortet
        p = p / 100
    if not np.isfinite(p).all() or p.sum() <= 0:
        return np.array(fallback)
    return np.clip(p / p.sum(), 1e-4, 1)


def _matrix(c: dict) -> np.ndarray:
    """Ergebnis-Wahrscheinlichkeiten des Modells; ohne gespeicherte Matrix (2. Liga) Poisson aus den erwarteten Toren."""
    if c["score_probs"]:
        m = np.asarray(json.loads(c["score_probs"]), dtype=float)
    else:
        g = np.arange(11)
        ph = np.array([math.exp(-c["lam"][0]) * c["lam"][0] ** k / math.factorial(k) for k in g])
        pa = np.array([math.exp(-c["lam"][1]) * c["lam"][1] ** k / math.factorial(k) for k in g])
        m = np.outer(ph, pa)
    return m / m.sum()


def _rescaled(m: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Ergebnis-Matrix des Modells auf die 1X2-Wahrscheinlichkeiten `p` umgewichtet (Form der Verteilung bleibt)."""
    i, j = np.indices(m.shape)
    out = m.copy()
    for mask, target in ((i > j, p[0]), (i == j, p[1]), (i < j, p[2])):
        s = m[mask].sum()
        if s > 0:
            out[mask] *= target / s
    return out / out.sum()


def evaluate(variant: str = "mit_modellnone", comps: tuple[str, ...] = ("BL", "D2")) -> dict:
    """Modell gegen Sprachmodell (und 50/50-Mischung): Wahrscheinlichkeiten und Tipp-Punkte, mit Bootstrap."""
    cache = {(d["comp"], d["id"]): d["antwort"] for d in _cache().values() if d["variante"] == variant}
    rows = []
    for c in _cases():
        ans = cache.get((c["comp"], c["id"]))
        if c["comp"] not in comps or ans is None:
            continue
        pm = np.array(c["p"])
        pl = _llm_p(ans, c["p"])
        mix = (pm + pl) / 2
        res = 0 if c["hg"] > c["ag"] else 1 if c["hg"] == c["ag"] else 2
        m = _matrix(c)
        best = lambda p: tip_options(_rescaled(m, p).tolist(), TIPP_PUNKTE, 1)[0][0]  # noqa: E731
        lt = (min(int(ans.get("tipp_heim", 0)), MAX_TIP_GOALS), min(int(ans.get("tipp_gast", 0)), MAX_TIP_GOALS))
        pts = lambda t: kicktipp_points(t[0], t[1], c["hg"], c["ag"])  # noqa: E731
        rows.append({"comp": c["comp"], "saison": c["saison"], "res": res, "pm": pm, "pl": pl, "mix": mix,
                     "markt": c["markt"], "pts_modell": pts(c["tipp"]), "pts_ki_tipp": pts(lt),
                     "pts_ki_p": pts(best(pl)), "pts_mix": pts(best(mix)),
                     "abw": float(np.abs(pl - pm).sum() / 2)})
    out = {}
    for label, sel in [("zusammen", rows)] + [(k, [r for r in rows if r["comp"] == k]) for k in comps] + \
            [(f"saison {s}", [r for r in rows if r["saison"] == s]) for s in sorted({r["saison"] for r in rows})]:
        if not sel:
            continue
        y = np.array([r["res"] for r in sel])
        res = {k: scores(np.array([r[k] for r in sel]), y) for k in ("pm", "pl", "mix")}
        mk = [r for r in sel if r["markt"] is not None]
        if mk:
            res["markt"] = scores(np.array([r["markt"] for r in mk]), np.array([r["res"] for r in mk]))
            res["modell_auf_markt"] = scores(np.array([r["pm"] for r in mk]), np.array([r["res"] for r in mk]))
        # Bootstrap: Anteil der Ziehungen, in denen das Sprachmodell (RPS) und sein Tipp (Punkte) besser sind
        rng = np.random.default_rng(0)
        d_rps = np.array([_rps(r["pl"], r["res"]) - _rps(r["pm"], r["res"]) for r in sel])
        d_pts = np.array([r["pts_ki_p"] - r["pts_modell"] for r in sel])
        idx = rng.integers(0, len(sel), (2000, len(sel)))
        out[label] = {**{k: {m: round(v, 4) for m, v in s.items()} for k, s in res.items()},
                      "punkte": {k: round(float(np.mean([r[k] for r in sel])), 3)
                                 for k in ("pts_modell", "pts_ki_tipp", "pts_ki_p", "pts_mix")},
                      "ki_besser_rps": round(float((d_rps[idx].mean(axis=1) < 0).mean()), 3),
                      "ki_besser_punkte": round(float((d_pts[idx].mean(axis=1) > 0).mean()), 3),
                      "mittlere_abweichung": round(float(np.mean([r["abw"] for r in sel])), 3)}
    return out


def _rps(p: np.ndarray, res: int) -> float:
    onehot = np.eye(3)[res]
    return float(np.sum((np.cumsum(p) - np.cumsum(onehot))[:2] ** 2) / 2)
