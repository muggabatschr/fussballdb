"""Spielberichte: deutscher Text je Bundesliga-Spiel (ab 2014/15), aus unseren Daten gebaut, nicht von
einem Sprachmodell geschrieben (schnell, rückwirkend für alle Spiele und ohne erfundene Details).

Im Stil einer Sportzeitung: Schlagzeile, Ortszeile, Einstieg im Perfekt (Derby, Spitzenspiel, Comeback, spätes
Siegtor), Spielverlauf je Halbzeit (Tore mit Minute, Schütze, Vorlage und Art, Pfosten, verschossene Elfmeter,
vergebene Großchancen, wer die Halbzeit bestimmte, Doppelpack und Saisontore), Einordnung (verdient oder glücklich
nach den Chancen, Überraschung), Folgen für Tabelle und Serien, Ausfälle, Stadion und Wetter (ab 2026/27), dazu
eine Zeile mit den Zahlen und Stichworte für die Suche.

Gespeichert in match_report mit Volltextindex (Postgres, Deutsch) und Embedding (pgvector, Modell aus LM Studio)
für die Suche in Chat und MCP (search)."""

import json
import random
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from fussballdb.config import LOCAL_LLM_URL, MODEL_FIRST_SEASON
from fussballdb.db.session import engine

BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
SITUATION = {"Penalty": "Elfmeter", "DirectFreekick": "direkter Freistoß", "FromCorner": "nach Ecke",
             "SetPiece": "nach Standard"}
EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
# nomic-embed erwartet diese Präfixe für Dokumente bzw. Suchanfragen
DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "


def de(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def _short(name: str) -> str:
    """Nachname für Torschützen ("Harry Kane" -> "Kane"), Einzelnamen bleiben."""
    parts = name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else name


PROSE = {"HSV": "Hamburg"}  # Abkürzungen, die im Satz einen Artikel bräuchten ("für den HSV")


def _prose(team: str) -> str:
    return PROSE.get(team, team)


def _venue(stadium: str | None) -> str:
    """ "im Volksparkstadion", aber "in der Allianz Arena"."""
    if not stadium:
        return ""
    return f" in der {stadium}" if stadium.lower().endswith("arena") or stadium.lower().endswith("arena an der kaiserlinde") else f" im {stadium}"


METHOD = {"Penalty": " per Elfmeter", "DirectFreekick": " mit einem direkten Freistoß", "FromCorner": " nach einer Ecke"}
ORD = ["", "erste", "zweite", "dritte", "vierte", "fünfte", "sechste", "siebte", "achte", "neunte", "zehnte", "elfte",
       "zwölfte", "dreizehnte", "vierzehnte", "fünfzehnte", "sechzehnte", "siebzehnte", "achtzehnte", "neunzehnte",
       "zwanzigste"]
NUM = ["null", "einem", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf"]
# Derbys und Klassiker: (Dativ für den Einstieg, Akkusativ für die Schlagzeile)
DERBYS = {
    frozenset({"Dortmund", "Schalke"}): ("im Revierderby", "das Revierderby"),
    frozenset({"Bochum", "Schalke"}): ("im Revierderby", "das Revierderby"),
    frozenset({"Bochum", "Dortmund"}): ("im Revierderby", "das Revierderby"),
    frozenset({"HSV", "Bremen"}): ("im Nordderby", "das Nordderby"),
    frozenset({"Hannover", "Bremen"}): ("im Nordderby", "das Nordderby"),
    frozenset({"Hannover", "HSV"}): ("im Nordderby", "das Nordderby"),
    frozenset({"Hannover", "Wolfsburg"}): ("im Niedersachsenderby", "das Niedersachsenderby"),
    frozenset({"HSV", "St. Pauli"}): ("im Hamburger Stadtderby", "das Stadtderby"),
    frozenset({"Köln", "Gladbach"}): ("im rheinischen Derby", "das rheinische Derby"),
    frozenset({"Köln", "Leverkusen"}): ("im rheinischen Derby", "das rheinische Derby"),
    frozenset({"Köln", "Düsseldorf"}): ("im rheinischen Derby", "das rheinische Derby"),
    frozenset({"Gladbach", "Düsseldorf"}): ("im rheinischen Derby", "das rheinische Derby"),
    frozenset({"Gladbach", "Leverkusen"}): ("im rheinischen Derby", "das rheinische Derby"),
    frozenset({"Frankfurt", "Mainz"}): ("im Rhein-Main-Derby", "das Rhein-Main-Derby"),
    frozenset({"Frankfurt", "Darmstadt"}): ("im Hessenderby", "das Hessenderby"),
    frozenset({"Hertha", "Union"}): ("im Berliner Stadtderby", "das Stadtderby"),
    frozenset({"Nürnberg", "Fürth"}): ("im Frankenderby", "das Frankenderby"),
    frozenset({"Bayern", "Dortmund"}): ("im Klassiker", "den Klassiker"),
    frozenset({"Stuttgart", "Freiburg"}): ("im baden-württembergischen Duell", "das Landesduell"),
}


def _ord(n: int) -> str:
    return ORD[n] if n < len(ORD) else f"{n}."


def _num(n: int) -> str:
    return NUM[n] if n < len(NUM) else str(n)


def _pick(rnd: random.Random, *options: str) -> str:
    return rnd.choice(options)


def _vary(rnd: random.Random, key: str, *options: str) -> str:
    """Wie _pick, aber nicht dieselbe Satzform wie beim letzten Mal unter diesem Schlüssel (zwei Tore hintereinander
    sollen nicht beide "legte … nach" heißen)."""
    last = getattr(rnd, "last", None)
    if last is None:
        last = rnd.last = {}
    choices = [i for i in range(len(options)) if i != last.get(key)] or [0]
    i = rnd.choice(choices)
    last[key] = i
    return options[i]


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " und " + names[-1]


def _for_home(m: dict, s: dict) -> bool:
    """Zählt der Schuss (auch ein Eigentor) für die Heimmannschaft?"""
    return (s["team_id"] == m["home_id"]) != (s["result"] == "OwnGoal")


def _when(kick) -> str:
    """ "am Samstagnachmittag", "am Freitagabend" (Anstoß in Berliner Zeit)."""
    part = "abend" if kick.hour >= 18 else "nachmittag" if kick.hour >= 14 else "mittag" if kick.hour >= 12 else ""
    return f"am {WEEKDAYS[kick.weekday()]}{part}"


def _goal_sentence(m: dict, g: dict, before: tuple[int, int], after: tuple[int, int], starters: set[str],
                   winning: dict | None, rnd: random.Random) -> str:
    """Ein Tor als Satz: Führung, Ausgleich, Anschluss, Ausbau, späte Entscheidung, Eigentor."""
    names = {True: _prose(m["home_short"]), False: _prose(m["away_short"])}
    for_home = _for_home(m, g)
    team = names[for_home]
    h, a = after
    mine, theirs = (h, a) if for_home else (a, h)
    score, minute = f"{h}:{a}", g["minute"]
    if g["result"] == "OwnGoal":
        return _vary(rnd, "own", f"Ein Eigentor von {_short(g['player'])} in der {minute}. Minute bedeutete das {score}.",
                     f"In der {minute}. Minute half {_short(g['player'])} unfreiwillig mit: Eigentor zum {score}.",
                     f"Zum {score} traf in der {minute}. Minute ausgerechnet ein Gegenspieler, {_short(g['player'])} lenkte den Ball ins eigene Tor.")
    joker = bool(starters) and g["player"] not in starters
    who = _short(g["player"])
    scorer = f"der eingewechselte {who}" if joker else who
    scorer_dat = f"dem eingewechselten {who}" if joker else who
    Scorer = _cap(scorer)
    how = METHOD.get(g["situation"], "") or (" per Kopf" if g["shot_type"] == "Head" else "")
    assist = (f" nach Vorlage von {_short(g['player_assisted'])}"
              if g["player_assisted"] and g["situation"] != "Penalty" else "")
    if g["situation"] == "FromCorner" and assist:
        how, assist = f" nach einer Ecke von {_short(g['player_assisted'])}", ""
    if g.get("rebound"):  # Elfmeter gehalten, Nachschuss drin
        how, assist = " im Nachschuss, nachdem er zuvor mit einem Elfmeter gescheitert war", ""
    if g is winning and minute >= 85 and before[0] == before[1]:
        return _vary(rnd, "late_level", f"In der {minute}. Minute erlöste {scorer} {team}{how}{assist} mit dem {score}.",
                     f"Die Entscheidung fiel spät: {Scorer} traf in der {minute}. Minute{how}{assist} zum {score}.",
                     f"Als sich alle schon mit dem Remis abgefunden hatten, schlug {scorer} in der {minute}. Minute{how}{assist} zu: {score}.")
    if g is winning and minute >= 85:
        return _vary(rnd, "late", f"Die Entscheidung fiel spät: {Scorer} traf in der {minute}. Minute{how}{assist} zum {score}.",
                     f"In der {minute}. Minute sorgte {scorer}{how}{assist} mit dem {score} für die Entscheidung.")
    if before == (0, 0):
        early = minute <= 10
        return _pick(rnd,
                     f"{Scorer} brachte {team} in der {minute}. Minute{how}{assist} in Führung.",
                     f"{'Schon' if early else 'In'} der {minute}. Minute traf {scorer}{how}{assist} zum {score}.",
                     f"Den ersten Treffer erzielte {scorer} für {team} in der {minute}. Minute{how}{assist}.",
                     f"{'Früh' if early else 'In der ' + str(minute) + '. Minute'} jubelte {team}: {Scorer} traf{how}{assist} zum {score}"
                     + (f" ({minute}.)." if early else "."))
    if mine == theirs:
        return _vary(rnd, "first", f"{Scorer} glich in der {minute}. Minute{how}{assist} zum {score} aus.",
                     f"In der {minute}. Minute gelang {scorer_dat}{how}{assist} der Ausgleich zum {score}.",
                     f"Die Antwort kam in der {minute}. Minute: {Scorer} traf{how}{assist} zum {score}.")
    if mine < theirs:
        return _vary(rnd, "level", f"{Scorer} verkürzte in der {minute}. Minute{how}{assist} auf {score}.",
                     f"Der Anschluss zum {score} gelang {scorer_dat} in der {minute}. Minute{how}{assist}.",
                     f"{team} gab sich nicht auf, {scorer} verkürzte in der {minute}. Minute{how}{assist} auf {score}.")
    if mine - theirs == 1 and before[0] == before[1]:
        return _vary(rnd, "short", f"{Scorer} brachte {team} in der {minute}. Minute{how}{assist} erneut in Führung.",
                     f"In der {minute}. Minute traf {scorer}{how}{assist} zum {score}.",
                     f"Doch {team} schlug zurück: {Scorer} markierte in der {minute}. Minute{how}{assist} das {score}.")
    if mine - theirs >= 3:
        return _vary(rnd, "again", f"{Scorer} schraubte das Ergebnis in der {minute}. Minute{how}{assist} auf {score}.",
                     f"In der {minute}. Minute legte {scorer}{how}{assist} zum {score} nach.",
                     f"Das {score} besorgte {scorer} in der {minute}. Minute{how}{assist}.")
    return _vary(rnd, "big", f"{Scorer} erhöhte in der {minute}. Minute{how}{assist} auf {score}.",
                 f"In der {minute}. Minute legte {scorer}{how}{assist} zum {score} nach.",
                 f"{Scorer} baute die Führung in der {minute}. Minute{how}{assist} auf {score} aus.")


def _misses(m: dict, shots: list[dict], rnd: random.Random) -> list[tuple[int, str]]:
    """Szenen ohne Tor: verschossene Elfmeter, Pfosten und Latte, die größte vergebene Chance je Team.
    Rückgabe (Minute, Satz), höchstens drei, für die Einordnung in den Verlauf."""
    names = {True: _prose(m["home_short"]), False: _prose(m["away_short"])}
    out: list[tuple[int, int, str]] = []  # (Rang, Minute, Satz)
    for s in shots:
        if s["result"] in ("Goal", "OwnGoal") or s.get("rebound_of"):
            continue
        who, minute = _short(s["player"]), s["minute"]
        if s["situation"] == "Penalty":
            out.append((0, minute, f"{who} scheiterte in der {minute}. Minute vom Elfmeterpunkt am Torhüter."
                        if s["result"] == "SavedShot" else
                        _pick(rnd, f"In der {minute}. Minute vergab {who} einen Elfmeter.",
                              f"{who} verschoss in der {minute}. Minute einen Strafstoß.")))
        elif s["result"] == "ShotOnPost":
            out.append((1, minute, _pick(rnd, f"In der {minute}. Minute traf {who} nur das Aluminium.",
                                         f"Pech hatte {who}, dessen Schuss in der {minute}. Minute am Pfosten landete.",
                                         f"{who} scheiterte in der {minute}. Minute am Aluminium.")))
    for home in (True, False):
        best = max((s for s in shots if _for_home(m, s) == home and s["result"] not in ("Goal", "OwnGoal", "ShotOnPost")
                    and s["situation"] != "Penalty"), key=lambda s: s["xg"], default=None)
        if best and best["xg"] >= 0.45:
            who, minute = _short(best["player"]), best["minute"]
            how = "per Kopf " if best["shot_type"] == "Head" else ""
            out.append((2, minute, _pick(rnd, f"Die größte Chance für {names[home]} vergab {who} in der {minute}. Minute {how}aus kurzer Distanz.",
                                         f"In der {minute}. Minute ließ {who} {how}eine Riesenchance für {names[home]} liegen.",
                                         f"{who} hatte in der {minute}. Minute {how}die große Möglichkeit, scheiterte aber.")))
    out.sort()
    return sorted(((minute, text) for _, minute, text in out[:3]))


def _half_flow(m: dict, shots: list[dict], first: bool) -> tuple[str | None, float, float]:
    """Wer bestimmte die Halbzeit? Das klar stärkere Team nach xG der Halbzeit ("die Gastgeber"/"die Gäste"),
    dazu die xG-Summen."""
    part = [s for s in shots if (s["minute"] <= 45) == first and s["result"] != "OwnGoal"]
    hx = sum(s["xg"] for s in part if s["team_id"] == m["home_id"])
    ax = sum(s["xg"] for s in part if s["team_id"] == m["away_id"])
    if max(hx, ax) >= 0.9 and max(hx, ax) >= 2.2 * min(hx, ax):
        return ("Die Gastgeber" if hx > ax else "Die Gäste"), hx, ax
    return None, hx, ax


def _story(m: dict, shots: list[dict], starters: set[str], season_goals: dict,
           rnd: random.Random) -> tuple[list[str], list[str], list[str]]:
    """Spielverlauf als zwei Absätze (erste und zweite Halbzeit): Tore, Pfosten, Elfmeter, vergebene Chancen,
    wer die Halbzeit bestimmte, Pausenstand; dazu ein Satz zu Doppelpack und Saisontoren für die Einordnung."""
    goals = [s for s in shots if s["result"] in ("Goal", "OwnGoal")]
    for s in shots:  # gehaltener Elfmeter, derselbe Spieler trifft im Nachschuss
        if s["situation"] == "Penalty" and s["result"] != "Goal":
            follow = next((g for g in goals if g["player"] == s["player"] and 0 <= g["minute"] - s["minute"] <= 1
                           and g["situation"] != "Penalty"), None)
            if follow:
                s["rebound_of"], follow["rebound"] = True, True
    winning = _winning_goal(m, goals)
    misses = _misses(m, shots, rnd)
    events = sorted([(g["minute"], 0, i, g) for i, g in enumerate(goals)] + [(mi, 1, i, t) for i, (mi, t) in enumerate(misses)],
                    key=lambda e: (e[0], e[1], e[2]))
    halves: tuple[list[str], list[str]] = ([], [])
    h = a = 0
    for first in (True, False):
        out = halves[0 if first else 1]
        boss, hx, ax = _half_flow(m, shots, first)
        part = [e for e in events if (e[0] <= 45) == first]
        has_goal = any(e[1] == 0 for e in part)
        if first:
            if boss and has_goal:
                out.append(_pick(rnd, f"{boss} bestimmten die erste Halbzeit.", f"{boss} erwischten den besseren Start.",
                                 f"{boss} übernahmen von Beginn an die Initiative."))
            elif boss:
                out.append(_pick(rnd, f"{boss} waren vor der Pause die bessere Mannschaft, ließen die Chancen aber ungenutzt.",
                                 f"{boss} drängten in der ersten Halbzeit, ein Tor wollte aber nicht fallen."))
            elif not has_goal:
                out.append(_pick(rnd, "In einer zähen ersten Halbzeit passierte wenig.", "Die erste Halbzeit blieb ohne Treffer.",
                                 "Beide Teams tasteten sich in der ersten Halbzeit ab, Tore fielen keine.")
                           if hx + ax < 1.2 else
                           _pick(rnd, "Vor der Pause gab es Chancen auf beiden Seiten, Tore aber nicht.",
                                 "Die erste Halbzeit blieb trotz guter Gelegenheiten torlos."))
        else:
            low = boss[0].lower() + boss[1:] if boss else ""
            if boss and has_goal:
                out.append(_pick(rnd, f"Nach dem Seitenwechsel übernahmen {low} das Kommando.",
                                 f"Nach der Pause drehten {low} auf.", f"In der zweiten Halbzeit gaben {low} den Ton an."))
            elif boss:
                out.append(_pick(rnd, f"Nach der Pause drängten {low}, doch es fielen keine Tore mehr.",
                                 f"{boss} warfen in der zweiten Halbzeit alles nach vorn, ohne Erfolg."))
            elif not has_goal and goals:
                out.append(_pick(rnd, "Nach der Pause fielen keine Tore mehr.", "Die zweite Halbzeit blieb ohne Treffer.",
                                 "Im zweiten Durchgang änderte sich am Spielstand nichts mehr."))
            elif not has_goal:
                out.append(_pick(rnd, "Auch nach der Pause blieb es beim torlosen Stand.", "Daran änderte sich auch nach dem Seitenwechsel nichts."))
        for minute, kind, _, ev in part:
            if kind == 1:
                out.append(ev)
                continue
            before = (h, a)
            h, a = (h + 1, a) if _for_home(m, ev) else (h, a + 1)
            out.append(_goal_sentence(m, ev, before, (h, a), starters, winning, rnd))
        if first and has_goal and (m["ht_home"] is None or (h, a) == (m["ht_home"], m["ht_away"])):
            # nur wenn die Torminuten zum offiziellen Pausenstand passen, sonst widerspräche sich der Text
            out.append(_pick(rnd, f"Mit {h}:{a} ging es in die Kabinen.", f"Zur Pause stand es {h}:{a}.",
                             f"Mit dem {h}:{a} ging es in die Pause."))
    # Doppelpack und Saisontore: ein Satz für den auffälligsten Torschützen
    star_line: list[str] = []
    tally: dict[str, int] = {}
    for g in goals:
        if g["result"] == "Goal":
            tally[g["player"]] = tally.get(g["player"], 0) + 1
    if tally:
        star = max(tally, key=lambda p: (tally[p], season_goals.get(p, 0)))
        n, total = tally[star], season_goals.get(star, 0)
        pack = {2: "einen Doppelpack", 3: "einen Dreierpack"}.get(n, f"{_num(n)} Tore" if n > 3 else "")
        who = _short(star)
        if pack and total > n:
            star_line.append(f"{who} schnürte {pack} und steht nun bei {_num(total)} Saisontoren.")
        elif pack:
            star_line.append(_pick(rnd, f"{who} schnürte {pack}.", f"Mann des Tages war {who} mit {pack}."))
        elif total >= 5:
            star_line.append(_pick(rnd, f"Für {who} war es bereits das {_ord(total)} Saisontor.",
                                   f"{who} hält nun bei {_num(total)} Saisontoren."))
    return halves[0], halves[1], star_line


def _lead(m: dict, goals: list[dict], keywords: list[str], kick, rnd: random.Random) -> str:
    """Einstieg im Perfekt wie in der Zeitung: wer, wann, wie, mit Derby oder Spitzenspiel."""
    hg, ag = m["home_goals"], m["away_goals"]
    home, away = _prose(m["home_short"]), _prose(m["away_short"])
    when = _when(kick)
    kw = " ".join(keywords)
    tag = (m["ctx"].get("tag") or "")
    def subj(who: str, verb: str = "hat") -> str:  # "Im Nordderby hat Hamburg" / "Hamburg hat"
        return f"{_cap(tag)} {verb} {who}" if tag else f"{who} {verb}"
    if hg == ag:
        both = f"{home} und {away}"
        if hg == 0:
            return _pick(rnd, f"{subj(both, 'sind')} {when} nicht über ein torloses Remis hinausgekommen.",
                         f"{subj(both, 'haben')} sich {when} 0:0 getrennt.")
        deficit, leader = 0, None
        h = a = 0
        for g in goals:
            h, a = (h + 1, a) if _for_home(m, g) else (h, a + 1)
            if abs(h - a) > deficit:
                deficit, leader = abs(h - a), home if h > a else away
        if deficit >= 2:
            chaser = away if leader == home else home
            return f"{subj(chaser)} {when} einen Zwei-Tore-Rückstand gegen {leader} aufgeholt und {hg}:{ag} gespielt."
        if "später Ausgleich" in kw:
            last = goals[-1]
            return f"{subj(both, 'haben')} sich {when} {hg}:{ag} getrennt, der Ausgleich fiel erst in der {last['minute']}. Minute."
        return _pick(rnd, f"{subj(both, 'haben')} sich {when} {hg}:{ag} unentschieden getrennt.",
                     f"{subj(both, 'haben')} sich {when} beim {hg}:{ag} die Punkte geteilt.")
    winner, loser = (home, away) if hg > ag else (away, home)
    ws = f"{max(hg, ag)}:{min(hg, ag)}"
    at = "bei" if ag > hg else "gegen"
    if "Comeback" in kw:
        return f"{subj(winner)} {when} einen Rückstand gegen {loser} gedreht und {ws} gewonnen."
    if "spätes Siegtor" in kw:
        win = _winning_goal(m, goals)
        if win and win["result"] == "Goal":
            return f"{subj(winner)} {when} dank eines späten Treffers von {_short(win['player'])} {ws} {at} {loser} gewonnen."
    if abs(hg - ag) >= 3:
        return _pick(rnd, f"{subj(winner)} {loser} {when} mit {ws} deklassiert.",
                     f"{subj(winner)} {when} {at} {loser} ein Schützenfest gefeiert und {ws} gewonnen."
                     if hg + ag >= 5 else f"{subj(winner)} {loser} {when} beim {ws} keine Chance gelassen.")
    if "Überraschung" in kw:
        return f"{subj(winner)} {when} für eine Überraschung gesorgt und {loser} mit {ws} geschlagen."
    if "glücklicher Sieg" in kw:
        return f"{subj(winner)} {when} einen glücklichen {ws}-Sieg {at} {loser} eingefahren."
    return _pick(rnd, f"{subj(winner)} {when} {ws} {at} {loser} gewonnen.",
                 f"{subj(winner)} {when} einen {ws}-Erfolg {at} {loser} gefeiert.",
                 f"{subj(winner)} {when} {at} {loser} mit {ws} die Oberhand behalten.")


def _assessment(m: dict, stats: dict, rnd: random.Random) -> list[str]:
    """Einordnung: verdient oder glücklich (nach Chancen), Dominanz, Überraschung."""
    out = []
    hg, ag, hx, ax = m["home_goals"], m["away_goals"], m["home_xg"], m["away_xg"]
    home, away = _prose(m["home_short"]), _prose(m["away_short"])
    winner, loser = (home, away) if hg > ag else (away, home) if ag > hg else (None, None)
    hs, as_ = stats.get("home") or {}, stats.get("away") or {}
    if hx is not None and ax is not None:
        wx, lx = (hx, ax) if hg >= ag else (ax, hx)
        if winner:
            diff = wx - lx
            if diff <= -0.5:
                out.append(_pick(rnd, f"Der Sieg war glücklich: {loser} kam auf {de(lx)} erwartete Tore, {winner} nur auf {de(wx)}.",
                                 f"Nach den Chancen hätte {loser} mehr verdient gehabt, {de(lx)} zu {de(wx)} lautete die Bilanz der erwarteten Tore."))
            elif diff >= 0.5:
                out.append(_pick(rnd, f"Der Sieg ging in Ordnung, {winner} erspielte sich Chancen für {de(wx)} Tore, {loser} nur für {de(lx)}.",
                                 f"Ein verdienter Erfolg: {winner} war das gefährlichere Team ({de(wx)} zu {de(lx)} erwartete Tore)."))
            else:
                out.append(_pick(rnd, f"Viel trennte die beiden Teams nicht, die erwarteten Tore lagen bei {de(hx)} zu {de(ax)}.",
                                 f"Es war ein enges Spiel, in dem die Chancen fast gleich verteilt waren ({de(hx)} zu {de(ax)} erwartete Tore)."))
        else:
            better, bx, ox = (home, hx, ax) if hx > ax else (away, ax, hx)
            out.append(f"{better} hätte nach den Chancen gewinnen müssen ({de(bx)} zu {de(ox)} erwartete Tore)." if abs(hx - ax) >= 0.8
                       else _pick(rnd, f"Das Remis ging nach den Chancen in Ordnung ({de(hx)} zu {de(ax)} erwartete Tore).",
                                  f"Eine gerechte Punkteteilung, auch die erwarteten Tore lagen mit {de(hx)} zu {de(ax)} nah beieinander."))
    if hs.get("shots") and as_.get("shots") and max(hs["shots"], as_["shots"]) >= 2 * min(hs["shots"], as_["shots"]) >= 8:
        dom, other = (home, away) if hs["shots"] > as_["shots"] else (away, home)
        many, few = max(hs["shots"], as_["shots"]), min(hs["shots"], as_["shots"])
        out.append(_pick(rnd, f"{dom} gab {many} Schüsse ab, {other} nur {few}.",
                         f"Die Schussbilanz sprach mit {many}:{few} deutlich für {dom}."))
    if m["p_home"] is not None:
        if winner:
            p_win = m["p_home"] if hg > ag else m["p_away"]
            p_lose = m["p_away"] if hg > ag else m["p_home"]
            if p_win < 0.25 and p_lose > 0.5:
                out.append(_pick(rnd, f"Mit diesem Ergebnis hatte kaum jemand gerechnet, {loser} ging als klarer Favorit ins Spiel.",
                                 f"Damit gelang {winner} als Außenseiter ein Coup."))
        else:
            fav, p_fav = (home, m["p_home"]) if m["p_home"] > m["p_away"] else (away, m["p_away"])
            if p_fav > 0.65:
                out.append(f"Für Favorit {fav} war das zu wenig.")
    return out


def _standing(m: dict, rnd: random.Random) -> list[str]:
    """Folgen für Tabelle und Serien: Tabellenführung, Abstiegsplätze, Siegesserien, Durststrecken."""
    out = []
    hg, ag = m["home_goals"], m["away_goals"]
    later = " vorerst" if m["ctx"].get("later") else ""
    for side, gf, ga in (("home", hg, ag), ("away", ag, hg)):
        c = m["ctx"].get(side)
        if not c:
            continue
        team = _prose(m[f"{side}_short"])
        res = "S" if gf > ga else "N" if gf < ga else "U"
        form = c["form"]  # Ergebnisse vor dem Spiel, ältestes zuerst

        def run(pred) -> int:
            n = 0
            for r in reversed(form):
                if not pred(r):
                    break
                n += 1
            return n
        if res == "S":
            wins = run(lambda r: r == "S") + 1
            dry = run(lambda r: r != "S")
            if wins >= 3:
                out.append(_pick(rnd, f"Für {team} war es der {_ord(wins)} Sieg in Folge.",
                                 f"{team} bleibt in der Spur, es war der {_ord(wins)} Sieg nacheinander."))
            elif dry >= 4:
                out.append(_pick(rnd, f"Für {team} endete damit eine Durststrecke von {_num(dry)} Spielen ohne Sieg.",
                                 f"Nach {_num(dry)} sieglosen Spielen durfte {team} endlich wieder jubeln."))
        elif res == "N":
            losses = run(lambda r: r == "N") + 1
            unbeaten = run(lambda r: r != "N")
            winless = run(lambda r: r != "S") + 1
            if unbeaten >= 6:
                out.append(f"Für {team} riss eine Serie von {_num(unbeaten)} Spielen ohne Niederlage.")
            elif losses >= 3:
                out.append(_pick(rnd, f"Für {team} war es bereits die {_ord(losses)} Niederlage in Folge.",
                                 f"{team} steckt in der Krise, es war die {_ord(losses)} Pleite nacheinander."))
            elif winless >= 5:
                out.append(f"{team} ist nach {_num(winless)} Spielen weiter ohne Saisonsieg." if winless > len(form)
                           else f"{team} wartet nun seit {_num(winless)} Spielen auf einen Sieg.")
        else:
            winless = run(lambda r: r != "S") + 1
            if winless >= 5:
                out.append(f"{team} ist nach {_num(winless)} Spielen weiter ohne Saisonsieg." if winless > len(form)
                           else f"{team} wartet weiter auf einen Sieg, seit {_num(winless)} Spielen klappt es nicht mehr.")
        before, after = c["pos_before"], c["pos_after"]
        if c["played"] < 3:
            continue
        if after == 1 and before != 1:
            out.append(_pick(rnd, f"{team} übernahm damit{later} die Tabellenführung.", f"{team} grüßt nun{later} von der Tabellenspitze."))
        elif after == 1 and res == "S":
            out.append(f"{team} bleibt Tabellenführer.")
        elif before == 1 and after != 1:
            out.append(f"{team} ist{later} die Tabellenführung los.")
        elif after == 18 and before != 18:
            out.append(f"{team} rutschte{later} ans Tabellenende.")
        elif after >= 16 and before < 16:
            out.append(f"{team} fiel{later} auf {'den Relegationsrang' if after == 16 else 'einen Abstiegsplatz'} zurück.")
        elif before >= 16 and after < 16:
            out.append(f"{team} verließ{later} die Abstiegszone und steht nun auf Platz {after}.")
        elif res == "S" and before - after >= 3:
            out.append(_pick(rnd, f"{team} kletterte{later} auf Platz {after}.", f"In der Tabelle sprang {team}{later} auf Rang {after}."))
        elif res == "N" and after - before >= 3:
            out.append(f"{team} rutschte{later} auf Platz {after} ab.")
    return out[:3]


def _numbers_line(s: dict) -> str | None:
    h, a = s.get("home") or {}, s.get("away") or {}
    parts = []
    for key, label, digits in (("xg", "xG", 2), ("shots", "Schüsse", 0), ("shots_on_target", "aufs Tor", 0),
                               ("big_chances", "Großchancen", 0), ("corners", "Ecken", 0), ("ppda", "PPDA", 1)):
        if h.get(key) is not None and a.get(key) is not None:
            parts.append(f"{label} {de(h[key], digits)}:{de(a[key], digits)}" if digits else f"{label} {h[key]}:{a[key]}")
    return "Zahlen zum Spiel: " + ", ".join(parts) + "." if parts else None


def _headline(m: dict, goals: list[dict], keywords: list[str], rnd: random.Random) -> str:
    hg, ag = m["home_goals"], m["away_goals"]
    home, away = _prose(m["home_short"]), _prose(m["away_short"])
    winner, loser = (home, away) if hg > ag else (away, home) if ag > hg else (None, None)
    kw = " ".join(keywords)
    score = f"{hg}:{ag}"
    derby = m["ctx"].get("derby")
    wside = "home" if hg > ag else "away"
    if not winner:
        if hg == 0:
            return _pick(rnd, f"Nullnummer zwischen {home} und {away}", f"Keine Tore bei {home} gegen {away}",
                         f"{home} und {away} bleiben ohne Treffer")
        if "später Ausgleich" in kw:
            return _pick(rnd, f"Später Ausgleich: {home} und {away} trennen sich {score}", f"Spätes {score} zwischen {home} und {away}")
        if "Aufholjagd" in kw:
            return f"Aufholjagd beim {score} zwischen {home} und {away}"
        return _pick(rnd, f"{home} und {away} trennen sich {score}", f"Punkteteilung beim {score} zwischen {home} und {away}")
    if "Comeback" in kw:
        return _pick(rnd, f"{winner} dreht das Spiel gegen {loser}", f"{winner} gewinnt nach Rückstand {score}")
    if "spätes Siegtor" in kw:
        win = _winning_goal(m, goals)
        if win and win["result"] == "Goal":
            return _pick(rnd, f"{_short(win['player'])} erlöst {winner} spät", f"Später Jubel für {winner} beim {score}")
        return f"Später Jubel für {winner} beim {score}"
    if derby:
        return f"{winner} gewinnt {derby[1]}"
    c = m["ctx"].get(wside) or {}
    if c.get("pos_after") == 1 and c.get("pos_before") != 1 and c.get("played", 0) >= 3:
        return f"{winner} erobert die Tabellenspitze"
    if abs(hg - ag) >= 3:
        return _pick(rnd, f"{winner} überrollt {loser} mit {score}", f"Deutlicher {score}-Erfolg für {winner}",
                     f"{winner} feiert Kantersieg gegen {loser}")
    if "Überraschung" in kw:
        return f"Überraschung: {winner} schlägt {loser} {score}"
    if "glücklicher Sieg" in kw:
        return _pick(rnd, f"{winner} siegt glücklich gegen {loser}", f"Glücklicher {score}-Sieg für {winner}")
    if ag > hg:
        return _pick(rnd, f"{away} gewinnt {ag}:{hg} in {m['city']}" if m.get("city") else f"Auswärtssieg für {away} bei {home}",
                     f"{away} entführt drei Punkte aus {m['city']}" if m.get("city") else f"{away} entführt drei Punkte bei {home}")
    return _pick(rnd, f"{home} schlägt {away} {score}", f"Heimsieg für {home} gegen {away}", f"{home} bezwingt {away}")


def _winning_goal(m: dict, goals: list[dict]) -> dict | None:
    """Das Siegtor: das Tor des Siegers, das ihn endgültig in Führung brachte (sein Tor Nummer Gegentore + 1)."""
    hg, ag = m["home_goals"], m["away_goals"]
    if hg == ag:
        return None
    home_won = hg > ag
    n = 0
    for g in goals:
        if ((g["team_id"] == m["home_id"]) != (g["result"] == "OwnGoal")) == home_won:
            n += 1
            if n == min(hg, ag) + 1:
                return g
    return None


def _keywords(m: dict, goals: list[dict], starters: set[str], reds: list[dict]) -> list[str]:
    """Stichworte zum Spielverlauf, aus den Daten abgeleitet (helfen der Suche nach Verläufen)."""
    hg, ag = m["home_goals"], m["away_goals"]
    winner = m["home_short"] if hg > ag else m["away_short"] if ag > hg else None
    loser = m["away_short"] if hg > ag else m["home_short"] if ag > hg else None
    words = []
    # Spielstand nach jedem Tor, um Rückstände und späte Entscheidungen zu erkennen
    h = a = 0
    trailed_home = trailed_away = False
    deciding_minute = None  # Remis: Minute des letzten Tores
    for g in goals:
        for_home = (g["team_id"] == m["home_id"]) != (g["result"] == "OwnGoal")
        h, a = (h + 1, a) if for_home else (h, a + 1)
        trailed_home |= h < a
        trailed_away |= a < h
        if (h, a) == (hg, ag):
            deciding_minute = g["minute"]
    winning = _winning_goal(m, goals)
    if winning:
        deciding_minute = winning["minute"]
    if hg > ag and trailed_home or ag > hg and trailed_away:
        words.append(f"Comeback von {winner}, {winner} gewinnt nach Rückstand, Spiel gedreht")
    elif hg == ag and (trailed_home or trailed_away) and hg > 0:
        words.append("Aufholjagd, Rückstand ausgeglichen")
    if hg != ag and deciding_minute and deciding_minute >= 85:
        words.append(f"spätes Siegtor von {winner}, Last-Minute-Tor")
    elif hg == ag and deciding_minute and deciding_minute >= 85:
        words.append("später Ausgleich in der Schlussphase")
    if hg + ag >= 5:
        words.append("Torfestival, Schützenfest, viele Tore")
    if hg + ag == 0:
        words.append("torlos, Nullnummer")
    elif min(hg, ag) == 0:
        words.append("zu null")
    if abs(hg - ag) >= 3:
        words.append(f"Kantersieg von {winner}, hohe Niederlage von {loser}")
    if reds:
        words.append("Platzverweis, Rote Karte, Unterzahl")
    if any(g["situation"] == "Penalty" for g in goals):
        words.append("Elfmetertor")
    if any(g["result"] == "OwnGoal" for g in goals):
        words.append("Eigentor")
    if any(g["result"] == "Goal" and g["player"] not in starters for g in goals) and starters:
        words.append("Joker-Tor, Tor eines Einwechselspielers")
    if m["home_xg"] is not None and m["away_xg"] is not None and hg != ag:
        diff = (m["home_xg"] - m["away_xg"]) * (1 if hg > ag else -1)
        words.append(f"glücklicher Sieg von {winner}, Sieger mit weniger Chancen" if diff <= -0.5
                     else f"verdienter Sieg von {winner}" if diff >= 0.5 else "knappes Spiel")
    if m["p_home"] is not None:
        winner_p = m["p_home"] if hg > ag else m["p_away"] if ag > hg else m["p_draw"]
        if winner_p < 0.25:
            words.append(f"Überraschung, Außenseiter {winner or 'holt Remis'}")
    if winner:
        words.append(f"{'Auswärtssieg' if ag > hg else 'Heimsieg'} von {winner}, Niederlage von {loser}")
    else:
        words.append("Unentschieden, Remis")
    return words


def build(m: dict, shots: list[dict], starters: set[str], reds: list[dict], stats: dict) -> str:
    """Bericht eines Spiels im Stil einer Sportzeitung: Schlagzeile, Ortszeile, Einstieg und erste Halbzeit,
    zweite Halbzeit, Einordnung mit Tabelle und Serien, Zahlen und Stichworte (für die Suche). Formulierungen
    wechseln je Spiel (fester Zufall nach Spiel-ID)."""
    rnd = random.Random(m["id"])
    kick = m["kickoff"].astimezone(BERLIN)
    goals = [s for s in shots if s["result"] in ("Goal", "OwnGoal")]
    keywords = _keywords(m, goals, starters, reds)
    ht = f" ({m['ht_home']}:{m['ht_away']})" if m["ht_home"] is not None else ""
    w = m.get("weather") or {}
    weather = ""
    if w.get("temp_c") is not None:
        if (w.get("precip_mm") or 0) >= 1:
            weather = " bei Regen"
        elif w["temp_c"] <= 3:
            weather = f" bei {de(w['temp_c'], 0)} Grad"
        elif w["temp_c"] >= 27:
            weather = f" bei sommerlichen {de(w['temp_c'], 0)} Grad"
    lines = [_headline(m, goals, keywords, rnd),
             f"{WEEKDAYS[kick.weekday()]}, {kick:%d.%m.%Y}, {m['matchday']}. Spieltag der Bundesliga {m['season_label']}"
             f"{_venue(m.get('stadium'))}{weather}: {m['home']} – {m['away']} {m['home_goals']}:{m['away_goals']}{ht}."]
    first, second, star = _story(m, shots, starters, m.get("season_goals") or {}, rnd)
    for r in reds:
        second.append(_pick(rnd, f"{_prose(r['team'])} musste nach einer Roten Karte für {_short(r['player'])} in Unterzahl auskommen.",
                            f"{_short(r['player'])} sah die Rote Karte, {_prose(r['team'])} spielte fortan mit einem Mann weniger."))
    lines.append(" ".join([_lead(m, goals, keywords, kick, rnd)] + first))
    if second:
        lines.append(" ".join(second))
    close = star + _assessment(m, stats, rnd) + _standing(m, rnd)
    for side in ("home", "away"):
        if m.get(f"missing_{side}"):
            played = m.get("players") or set()
            missing = [_short(n.strip()) for n in m[f"missing_{side}"].split(",")
                       if n.strip() and n.split("(")[0].strip() not in played]
            if missing:
                close.append(f"Bei {_prose(m[f'{side}_short'])} {'fehlte' if len(missing) == 1 else 'fehlten'} {_join(missing)}.")
    if close:
        lines.append(" ".join(close))
    if (nums := _numbers_line(stats)):
        lines.append(nums)
    lines.append("Stichworte: " + "; ".join(keywords) + ".")
    return "\n".join(lines)


def _season_context(conn, seasons: list[int]) -> tuple[dict, dict]:
    """Tabellenplatz vor und nach jedem Spiel, Ergebnisse davor (Serien) und Saisontore der Schützen bis
    einschließlich des Spiels. Tabelle nach Punkten, Tordifferenz, Toren."""
    rows = conn.execute(text("""
        SELECT m.id, s.start_year AS season, m.matchday, m.kickoff, m.finished, m.home_team_id AS h, m.away_team_id AS a,
               m.home_goals AS hg, m.away_goals AS ag
        FROM match m JOIN season s ON s.id = m.season_id WHERE s.start_year = ANY(:s) ORDER BY m.kickoff, m.id"""),
        {"s": seasons}).all()
    ctx: dict[int, dict] = {}
    last_kick: dict[tuple, object] = {}
    for r in rows:
        key = (r.season, r.matchday)
        last_kick[key] = max(last_kick.get(key, r.kickoff), r.kickoff)
    for season in seasons:
        games = [r for r in rows if r.season == season]
        teams = {r.h for r in games} | {r.a for r in games}
        table = {t: [0, 0, 0] for t in teams}  # Punkte, Tordifferenz, Tore
        form = {t: [] for t in teams}
        pos = lambda: {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: [-x for x in table[t]]))}  # noqa: E731
        for r in games:
            if not r.finished or r.hg is None:
                continue
            before = pos()
            c = {"home": {"pos_before": before[r.h], "form": list(form[r.h]), "played": len(form[r.h])},
                 "away": {"pos_before": before[r.a], "form": list(form[r.a]), "played": len(form[r.a])},
                 "later": last_kick[(r.season, r.matchday)] > r.kickoff}
            for t, gf, ga in ((r.h, r.hg, r.ag), (r.a, r.ag, r.hg)):
                table[t][0] += 3 if gf > ga else 1 if gf == ga else 0
                table[t][1] += gf - ga
                table[t][2] += gf
                form[t].append("S" if gf > ga else "N" if gf < ga else "U")
            after = pos()
            c["home"]["pos_after"], c["away"]["pos_after"] = after[r.h], after[r.a]
            ctx[r.id] = c
    goals: dict[int, dict] = {}
    tally: dict[tuple, int] = {}
    for g in conn.execute(text("""
            SELECT sh.match_id, sh.player, s.start_year AS season FROM shot sh JOIN match m ON m.id = sh.match_id
            JOIN season s ON s.id = m.season_id WHERE s.start_year = ANY(:s) AND sh.result = 'Goal'
            ORDER BY m.kickoff, sh.match_id, sh.minute, sh.id"""), {"s": seasons}):
        tally[(g.season, g.player)] = tally.get((g.season, g.player), 0) + 1
        goals.setdefault(g.match_id, {})[g.player] = tally[(g.season, g.player)]
    return ctx, goals


def _load(where: str, params: dict) -> list[tuple[int, str]]:
    """Alle Daten für die Berichte der ausgewählten Spiele mit wenigen Abfragen laden und Berichte bauen."""
    from fussballdb.ingest.team_mapping import COLLOQUIAL
    from fussballdb.model.ensemble import MODEL_VERSION

    short = lambda n: (COLLOQUIAL.get(n) or [n])[0]  # noqa: E731
    with engine.connect() as conn:
        matches = [dict(r._mapping) for r in conn.execute(text(f"""
            SELECT m.id, m.kickoff, m.matchday, s.start_year AS season, s.label AS season_label,
                   m.home_team_id AS home_id, m.away_team_id AS away_id, ht.name AS home, at.name AS away,
                   m.home_goals, m.away_goals, m.ht_home_goals AS ht_home, m.ht_away_goals AS ht_away,
                   hs.xg AS home_xg, as_.xg AS away_xg, p.p_home, p.p_draw, p.p_away, p.tip_home, p.tip_away,
                   p.missing_home, p.missing_away, v.stadium, v.city,
                   w.temp_c, w.precip_mm, w.wind_kmh
            FROM match m JOIN season s ON s.id = m.season_id
            JOIN team ht ON ht.id = m.home_team_id JOIN team at ON at.id = m.away_team_id
            LEFT JOIN match_team_stats hs ON hs.match_id = m.id AND hs.team_id = m.home_team_id
            LEFT JOIN match_team_stats as_ ON as_.match_id = m.id AND as_.team_id = m.away_team_id
            LEFT JOIN prediction p ON p.match_id = m.id AND p.model_version = :v
            LEFT JOIN match_venue v ON v.competition = 'BL' AND v.match_id = m.id
            LEFT JOIN match_weather w ON w.competition = 'BL' AND w.match_id = m.id AND w.kind = 'gemessen'
            WHERE m.finished AND s.start_year >= :first AND {where}"""), {"v": MODEL_VERSION, "first": MODEL_FIRST_SEASON, **params})]
        if not matches:
            return []
        ids = [m["id"] for m in matches]
        shots, starters, reds, stats = {}, {}, {}, {}
        for r in conn.execute(text("""SELECT match_id, minute, player, player_assisted, situation, shot_type, xg, result, team_id
                                       FROM shot WHERE match_id = ANY(:ids) ORDER BY match_id, minute, id"""), {"ids": ids}):
            shots.setdefault(r.match_id, []).append(dict(r._mapping))
        players: dict[int, set[str]] = {}
        for r in conn.execute(text("""SELECT pm.match_id, p.name, pm.started, pm.red_cards, t.name AS team
                                       FROM player_match pm JOIN player p ON p.id = pm.player_id JOIN team t ON t.id = pm.team_id
                                       WHERE pm.match_id = ANY(:ids)"""), {"ids": ids}):
            players.setdefault(r.match_id, set()).add(r.name)
            if r.started:
                starters.setdefault(r.match_id, set()).add(r.name)
            if r.red_cards:
                reds.setdefault(r.match_id, []).append({"player": r.name, "team": short(r.team)})
        for r in conn.execute(text("""SELECT x.match_id, x.is_home, x.xg, x.shots, x.shots_on_target, x.big_chances, x.corners, x.ppda
                                       FROM match_team_stats x WHERE x.match_id = ANY(:ids)"""), {"ids": ids}):
            stats.setdefault(r.match_id, {})["home" if r.is_home else "away"] = dict(r._mapping)
        ctx, season_goals = _season_context(conn, sorted({m["season"] for m in matches}))
    out = []
    for m in matches:
        m["home_short"], m["away_short"] = short(m["home"]), short(m["away"])
        m["weather"] = {"temp_c": m.pop("temp_c"), "precip_mm": m.pop("precip_mm"), "wind_kmh": m.pop("wind_kmh")}
        c = m["ctx"] = ctx.get(m["id"], {})
        m["season_goals"] = season_goals.get(m["id"], {})
        m["players"] = players.get(m["id"], set())
        derby = DERBYS.get(frozenset({m["home_short"], m["away_short"]}))
        hc, ac = c.get("home") or {}, c.get("away") or {}
        c["derby"] = derby
        c["tag"] = (derby[0] if derby else
                    "im Spitzenspiel" if hc.get("played", 0) >= 4 and max(hc["pos_before"], ac["pos_before"]) <= 3 else
                    "im Kellerduell" if hc.get("played", 0) >= 4 and min(hc["pos_before"], ac["pos_before"]) >= 15 else None)
        out.append((m["id"], m, build(m, shots.get(m["id"], []), starters.get(m["id"], set()),
                                      reds.get(m["id"], []), stats.get(m["id"], {}))))
    return out


def generate(only_missing: bool = True, recent_days: int = 14) -> int:
    """Berichte für gespielte Spiele schreiben: fehlende und (neu) die der letzten Tage, weil xG und Statistik
    einige Tage nachträglich kommen können. Ändert sich der Text, wird das Embedding neu berechnet."""
    where = ("(NOT EXISTS (SELECT 1 FROM match_report r WHERE r.match_id = m.id) "
             "OR m.kickoff > now() - make_interval(days => :d))") if only_missing else "true"
    rows = _load(where, {"d": recent_days})
    with engine.begin() as conn:
        for match_id, m, body in rows:
            conn.execute(text("""
                INSERT INTO match_report (match_id, season, matchday, kickoff, home_id, away_id, text, updated_at)
                VALUES (:id, :season, :md, :k, :h, :a, :t, now())
                ON CONFLICT (match_id) DO UPDATE SET text = EXCLUDED.text, updated_at = now(),
                    embedding = CASE WHEN match_report.text = EXCLUDED.text THEN match_report.embedding END"""),
                {"id": match_id, "season": m["season"], "md": m["matchday"], "k": m["kickoff"],
                 "h": m["home_id"], "a": m["away_id"], "t": body})
    return len(rows)


def embed(texts: list[str], prefix: str = DOC_PREFIX) -> list[list[float]]:
    """Embeddings über LM Studio (OpenAI-kompatibel)."""
    resp = httpx.post(f"{LOCAL_LLM_URL}/embeddings", json={"model": EMBED_MODEL, "input": [prefix + t for t in texts]},
                      timeout=120)
    resp.raise_for_status()
    return [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]


def embed_missing(batch: int = 64, progress=None) -> int:
    """Embeddings für Berichte ohne Vektor nachtragen. Ohne LM Studio: Fehler, die Volltextsuche geht weiter."""
    total = 0
    while True:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT match_id, text FROM match_report WHERE embedding IS NULL ORDER BY kickoff LIMIT :n"),
                                {"n": batch}).all()
        if not rows:
            return total
        vectors = embed([r.text for r in rows])
        with engine.begin() as conn:
            for r, v in zip(rows, vectors):
                conn.execute(text("UPDATE match_report SET embedding = CAST(:v AS vector), embed_model = :m WHERE match_id = :id"),
                             {"v": json.dumps(v), "m": EMBED_MODEL, "id": r.match_id})
        total += len(rows)
        if progress:
            progress(total)


RRF_K = 60  # Reciprocal Rank Fusion: Gewicht der Ränge aus Vektor- und Volltextsuche
VECTOR_WEIGHT = 0.5  # die Berichte sind gleich aufgebaut, die Vektorsuche bringt mehr Rauschen als die Stichworte


def search(query: str, team_id: int | None = None, season: int | None = None, limit: int = 8,
           newest_first: bool = False) -> list[dict]:
    """Berichte zur Frage: Vektorsuche (Bedeutung, Embedding aus LM Studio) und Volltextsuche (Deutsch) getrennt,
    Ränge mit Reciprocal Rank Fusion kombiniert. Ohne LM Studio nur Volltext. Optional nach Team und Saison
    gefiltert; ohne Frage die jüngsten Spiele des Filters. newest_first: unter den Volltexttreffern die jüngsten
    (für Fragen wie "wann zuletzt …")."""
    filters, params = ["true"], {"n": max(limit * 4, 30)}
    if team_id:
        filters.append(":t IN (r.home_id, r.away_id)")
        params["t"] = team_id
    if season:
        filters.append("r.season = :y")
        params["y"] = season
    where = " AND ".join(filters)
    ranks: dict[int, float] = {}
    methods = []
    with engine.connect() as conn:
        if not query.strip():
            ids = [r[0] for r in conn.execute(text(f"SELECT match_id FROM match_report r WHERE {where} "
                                                   "ORDER BY kickoff DESC LIMIT :n"), params)]
            ranks = {i: -k for k, i in enumerate(ids)}
            methods.append("neueste")
        else:
            fts = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where}
                                        AND r.tsv @@ websearch_to_tsquery('german', :q)
                                        ORDER BY ts_rank(r.tsv, websearch_to_tsquery('german', :q)) DESC LIMIT :n"""),
                               {**params, "q": query}).all()
            if not fts:  # Volltext mit allen Wörtern zu streng: mit ODER
                fts = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where}
                                            AND r.tsv @@ to_tsquery('german', :q)
                                            ORDER BY ts_rank(r.tsv, to_tsquery('german', :q)) DESC LIMIT :n"""),
                                   {**params, "q": " | ".join(w for w in query.replace("'", " ").split() if w.isalnum()) or "x"}).all()
            for k, (i,) in enumerate(fts):
                ranks[i] = ranks.get(i, 0) + 1 / (RRF_K + k)
            methods.append("volltext")
            if newest_first and fts:  # jüngste Volltexttreffer statt der relevantesten
                sql = f"""SELECT match_id, text FROM match_report r WHERE {where}
                          AND r.tsv @@ websearch_to_tsquery('german', :q) ORDER BY kickoff DESC LIMIT 200"""
                found = conn.execute(text(sql), {**params, "q": query}).all()
                if team_id:  # mit Team: nur Spiele, in denen das gesuchte Ereignis diesem Team gehört
                    short = _team_short(conn, team_id)
                    found = [r for r in found if _owns(r.text, short, query)] or found
                newest = [r.match_id for r in found[:limit]]
                if newest:
                    ranks = {i: -k for k, i in enumerate(newest)}
                    methods.append("neueste")
            try:
                if "neueste" in methods:
                    raise KeyError  # keine Vektorsuche nötig
                vec = json.dumps(embed([query], QUERY_PREFIX)[0])
                vrows = conn.execute(text(f"""SELECT match_id FROM match_report r WHERE {where} AND r.embedding IS NOT NULL
                                              ORDER BY r.embedding <=> CAST(:q AS vector) LIMIT :n"""),
                                     {**params, "q": vec}).all()
                for k, (i,) in enumerate(vrows):
                    ranks[i] = ranks.get(i, 0) + VECTOR_WEIGHT / (RRF_K + k)
                methods.append("vektor")
            except (httpx.HTTPError, KeyError, IndexError):
                pass
        if team_id and "neueste" not in methods and ranks:
            # mit Teamfilter: Berichte bevorzugen, deren Stichworte das Ereignis diesem Team zuschreiben
            # ("Comeback von Gladbach" statt "Comeback von Mainz" im Spiel gegen Gladbach)
            short = _team_short(conn, team_id)
            for r in conn.execute(text("SELECT match_id, text FROM match_report WHERE match_id = ANY(:ids)"), {"ids": list(ranks)}):
                if _owns(r.text, short, query):
                    ranks[r.match_id] += 1
        top = sorted(ranks, key=lambda i: -ranks[i])[:limit]
        rows = {r.match_id: r for r in conn.execute(text(
            "SELECT match_id, kickoff, season, matchday, text FROM match_report WHERE match_id = ANY(:ids)"), {"ids": top})}
    return [{"match_id": i, "datum": rows[i].kickoff.astimezone(BERLIN).date().isoformat(), "saison": rows[i].season,
             "spieltag": rows[i].matchday, "bericht": rows[i].text, "relevanz": round(ranks[i], 4),
             "suche": "+".join(methods), "link": f"/spiel/{i}"} for i in top]


def _owns(report_text: str, team: str, query: str) -> bool:
    """Schreiben die Stichworte das gesuchte Ereignis diesem Team zu? Eine Teilaussage muss ein Wort der Suche
    enthalten (Wortanfang, 5 Zeichen) und das Team nennen ("Gladbach gewinnt nach Rückstand"), nicht nur
    "Niederlage von Gladbach" neben "Heimsieg von Freiburg"."""
    line = next((x for x in report_text.splitlines() if x.startswith("Stichworte:")), "")
    team_words = {w.lower()[:5] for w in team.split()}
    stems = [s for s in (w.lower()[:5] for w in query.split() if len(w) >= 4) if s not in team_words
             and s not in ("borus", "spiel")]  # Teamname zählt nicht als Suchwort
    for clause in line.removeprefix("Stichworte:").replace(";", ",").split(","):  # jede Teilaussage einzeln
        c = clause.lower()
        if (f"von {team.lower()}" in c or c.strip().startswith(team.lower())) and (not stems or any(s in c for s in stems)):
            return True
    return False


def _team_short(conn, team_id: int) -> str:
    """Kurzname wie in den Stichworten ("Gladbach")."""
    from fussballdb.ingest.team_mapping import COLLOQUIAL

    name = conn.scalar(text("SELECT name FROM team WHERE id = :t"), {"t": team_id})
    return (COLLOQUIAL.get(name) or [name])[0]


def report(match_id: int) -> str | None:
    with engine.connect() as conn:
        return conn.scalar(text("SELECT text FROM match_report WHERE match_id = :id"), {"id": match_id})

