"""Stilprofil der Presse: wie Zeitungen (Lokalzeitungen, kicker, Sportschau, …) über Bundesliga-Spiele schreiben,
abgeleitet aus den Überschriften in news_item (ingest/news.py). Die Spielberichte (reports.py) richten ihre
Formulierungen danach aus: Schlagzeilen-Verben, Zeitungswörter und Spitznamen der Vereine.

Gespeichert werden nur abgeleitete Zählungen (welches Verb, welches Wort, wie oft), keine fremden Texte außer je
Verb einer Beispielüberschrift zur Kontrolle.

- Verben: Überschriften der 36 Stunden nach einem Spiel, in denen ein Verein den Gegner direkt anspricht ("Elversberg
  überrollt Mainz", "FCA unterliegt Freiburg 1:2", "FC Bayern siegt in Freiburg"). Gezählt wird das Verb mit
  Präposition und dem Ausgang aus Sicht des Subjekts. Aktiv wird ein Verb ab VERB_MIN Treffern, wenn es zu
  mindestens 85 % zum selben Ausgang gehört. Kam es nur bei Siegen mit drei oder mehr Toren Abstand vor
  ("überrollt"), gilt es nur dafür, nicht für ein 1:0.
- Zeitungswörter (WORDS): Befreiungsschlag, Krimi, Joker, Fehlstart … Ab WORD_MIN Überschriften schreibt der Bericht
  die passende Wendung, wenn die Lage passt (Sieg nach langer Durststrecke, spätes Siegtor, Tor eines Einwechselspielers).
- Spitznamen (NICKNAMES): nur die, die die Presse für den Verein wirklich verwendet ("Werkself", "Knappen").
- Form: Anteil der Überschriften, die mit dem Ergebnis beginnen ("0:2 gegen RB Leipzig: Schalke wartet …").

Bei jedem Presse-Import (maintenance, alle 6 Stunden) wird das Profil neu gezählt. Ändert sich etwas, das die
Berichte betrifft (neues Verb, Wort oder Spitzname aktiv oder weggefallen), wird eine neue Version mit den
Änderungen gespeichert und die Berichte werden neu geschrieben; sonst werden nur die Zahlen der letzten Version
aktualisiert.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import text

from fussballdb.db.session import engine

VERB_MIN, WORD_MIN, NICK_MIN = 2, 3, 2
SCORE_FRONT_MIN = 0.08  # ab diesem Anteil Schlagzeilen der Form "3:1 gegen Mainz: …"

# Verben, die ohne Ergänzung keinen Sinn ergeben ("macht … klar", "legt … nach") oder nichts über den Ausgang sagen
INCOMPLETE = {"macht", "legt", "geht", "holt", "baut", "bringt", "hält", "trifft", "gelingt", "empfängt", "fehlt", "fehlte",
              "ist", "hat", "bleibt", "steht", "kommt", "gibt", "lässt", "zeigt", "spielt", "feiert", "will", "muss", "kann",
              "wird", "war", "schlittert", "zieht", "sorgt", "erlebt", "kassiert", "verpasst", "beweist", "meldet"}
PREPS = ("gegen", "bei", "in")  # "bei"/"in" nur für Auswärtssiege ("siegt in Freiburg")
SKIP = re.compile(r"Live-?Ticker|\blive\b|Aufstellung|Noten|Stimmen|Fotos?|Bilder|Video|Highlights|Prognose|Tipp", re.I)

# Zeitungswort -> Suchmuster in den Überschriften (Wortgrenzen; "Gala" nicht in "Galatasaray")
WORDS = {
    "Befreiungsschlag": r"Befreiungsschlag", "Pleite": r"[Pp]leite\b", "Heimpleite": r"Heimpleite", "Dämpfer": r"Dämpfer",
    "Fehlstart": r"Fehlstart", "Krimi": r"Krimi\b|-Krimi", "Arbeitssieg": r"Arbeitssieg", "Gala": r"\bGala\b|Gala-",
    "Punktgewinn": r"Punktgewinn", "Last-Minute": r"Last-Minute", "Joker": r"\bJoker", "Nackenschlag": r"Nackenschlag",
    "Krise": r"Krise\b", "Debakel": r"Debakel", "Klatsche": r"Klatsche", "Torfestival": r"Torfestival|Torspektakel",
    "Derbysieg": r"Derbysieg", "Machtdemonstration": r"Machtdemonstration", "Kantersieg": r"Kantersieg",
}
WORD_RE = {w: re.compile(p) for w, p in WORDS.items()}

# Spitznamen je Verein: (Suchmuster, Akkusativ mit Artikel, Dativ mit Artikel); nur in "für …" und "bei …" verwendet,
# damit Artikel und Verb nie falsch gebeugt werden
NICKNAMES = {
    "Bayer 04 Leverkusen": [(r"Werkself", "die Werkself", "der Werkself")],
    "FC Schalke 04": [(r"Knappen", "die Knappen", "den Knappen"), (r"Königsblaue", "die Königsblauen", "den Königsblauen")],
    "Borussia Mönchengladbach": [(r"Fohlen", "die Fohlen", "den Fohlen")],
    "1. FC Köln": [(r"Geißböcke", "die Geißböcke", "den Geißböcken")],
    "VfL Wolfsburg": [(r"Wölfe", "die Wölfe", "den Wölfen")],
    "VfB Stuttgart": [(r"Schwaben", "die Schwaben", "den Schwaben")],
    "SV Werder Bremen": [(r"Grün-Wei(ß|ss)e", "die Grün-Weißen", "den Grün-Weißen")],
    "Hamburger SV": [(r"Rothosen", "die Rothosen", "den Rothosen")],
    "FC St. Pauli": [(r"Kiezkicker", "die Kiezkicker", "den Kiezkickern")],
    "1. FSV Mainz 05": [(r"05er", "die 05er", "den 05ern")],
    "Borussia Dortmund": [(r"Schwarz-Gelbe", "die Schwarz-Gelben", "den Schwarz-Gelben"), (r"Borussen", "die Borussen", "den Borussen")],
    "FC Bayern München": [(r"\bMünchner\b", "die Münchner", "den Münchnern")],
    "Eintracht Frankfurt": [(r"\bAdler\b", "die Adler", "den Adlern")],
    "SC Freiburg": [(r"Breisgauer", "die Breisgauer", "den Breisgauern")],
    "TSG Hoffenheim": [(r"Kraichgauer", "die Kraichgauer", "den Kraichgauern")],
    "1. FC Union Berlin": [(r"Eisernen", "die Eisernen", "den Eisernen")],
    "FC Augsburg": [(r"Fuggerstädter", "die Fuggerstädter", "den Fuggerstädtern")],
    "RB Leipzig": [(r"Roten Bullen", "die Roten Bullen", "den Roten Bullen")],
    "1. FC Heidenheim 1846": [(r"\bHeidenheimer\b", "die Heidenheimer", "den Heidenheimern")],
    "SV Darmstadt 98": [(r"Lilien", "die Lilien", "den Lilien")],
    "Holstein Kiel": [(r"Störche", "die Störche", "den Störchen")],
    "VfL Bochum": [(r"\bBochumer\b", "die Bochumer", "den Bochumern")],
}

DDL = """CREATE TABLE IF NOT EXISTS press_style (
    id serial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    profile jsonb NOT NULL, changes jsonb NOT NULL DEFAULT '[]')"""


def _aliases(name: str) -> list[str]:
    from fussballdb.ingest.news import NICK, QUERY
    from fussballdb.ingest.team_mapping import COLLOQUIAL

    out = {name, *(COLLOQUIAL.get(name) or []), *(q.strip('"') for q in QUERY.get(name, []))}
    out |= {w.upper() for w in NICK.get(name, ()) if len(w) <= 4 and w.isalpha()}  # FCA, BVB, HSV, SGE
    return sorted(out, key=len, reverse=True)


def _headlines(conn) -> list:
    """Überschriften der 36 Stunden nach Anpfiff eines Bundesliga-Spiels des Vereins, mit dem Spiel dazu."""
    return conn.execute(text("""
        SELECT n.title, n.source, n.team_id, m.home_team_id AS h, m.away_team_id AS a, m.home_goals AS hg, m.away_goals AS ag
        FROM news_item n JOIN match m ON n.team_id IN (m.home_team_id, m.away_team_id) AND m.finished
         AND n.published_at BETWEEN m.kickoff AND m.kickoff + interval '36 hours'""")).all()


def _verbs(rows, names: dict[int, str]) -> dict:
    """Verb (+ Präposition) je Ausgang aus Sicht des Subjekts: S (gewonnen), N (verloren), mit Torabständen."""
    alias = {tid: _aliases(n) for tid, n in names.items()}
    seen, found = set(), defaultdict(lambda: {"n": 0, "S": 0, "N": 0, "U": 0, "abstaende": [], "ergebnis": 0, "beispiel": None})
    for r in rows:
        if (r.title, r.h, r.a) in seen or SKIP.search(r.title):
            continue
        seen.add((r.title, r.h, r.a))
        for subj, obj in ((r.h, r.a), (r.a, r.h)):
            hit = None
            for a in alias[subj]:
                for b in alias[obj]:
                    hit = re.search(rf"(?:^|: |[-–/] )(?:der |die |das )?{re.escape(a)} ([a-zäöüß]+t)"
                                    rf"(?: ({'|'.join(PREPS)}))? (?:den |die |das |dem )?{re.escape(b)}(?![\w-])(.*)$", r.title)
                    if hit:
                        break
                if hit:
                    break
            if not hit or hit.group(1) in INCOMPLETE:
                continue
            verb, prep, rest = hit.group(1), hit.group(2), hit.group(3)
            if prep in ("bei", "in") and subj != r.a:  # "siegt in Freiburg" nur auswärts
                continue
            gf, ga = (r.hg, r.ag) if subj == r.h else (r.ag, r.hg)
            res = "S" if gf > ga else "N" if gf < ga else "U"
            v = found[f"{verb} {prep}" if prep else verb]
            v["n"] += 1
            v[res] += 1
            v["abstaende"].append(abs(gf - ga))
            v["ergebnis"] += bool(re.match(r"\s*(mit )?\d+:\d+", rest))
            v["beispiel"] = v["beispiel"] or r.title
            break
    out = {}
    for key, v in found.items():
        verb, _, prep = key.partition(" ")
        res = max(("S", "N"), key=lambda k: v[k])
        active = v["n"] >= VERB_MIN and v[res] / v["n"] >= 0.85
        decided = [d for d in v["abstaende"] if d > 0]
        high = len(decided) >= 2 and min(decided) >= 3  # nur bei hohen Siegen gesehen ("überrollt")
        out[key] = {"verb": verb, "praep": prep or None, "ausgang": res, "n": v["n"], "aktiv": active,
                    "ab_abstand": 3 if high else 1, "mit_ergebnis": round(v["ergebnis"] / v["n"], 2),
                    "beispiel": v["beispiel"]}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["n"]))


def compute() -> dict:
    """Profil aus allen gespeicherten Überschriften."""
    with engine.connect() as conn:
        names = {r.id: r.name for r in conn.execute(text("SELECT id, name FROM team"))}
        rows = _headlines(conn)
        all_titles = conn.execute(text("SELECT title, source, team_id FROM news_item")).all()
    match_titles = {r.title for r in rows if not SKIP.search(r.title)}
    words = {w: sum(bool(rx.search(t.title)) for t in all_titles) for w, rx in WORD_RE.items()}
    nicks = {}
    for team_id, name in names.items():
        for pattern, acc, dat in NICKNAMES.get(name, []):
            n = sum(bool(re.search(pattern, t.title)) for t in all_titles if t.team_id == team_id)
            if n:
                nicks.setdefault(name, []).append({"name": acc, "dativ": dat, "n": n, "aktiv": n >= NICK_MIN})
    front = sum(bool(re.match(r"\d+:\d+(-\w+)? (gegen|in|bei|beim|im|nach)\b", t)) for t in match_titles)
    colon = sum(":" in re.sub(r"\d+:\d+", "", t) for t in match_titles)
    sources = Counter(t.source for t in all_titles if t.source)
    return {
        "stand": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ueberschriften": len(all_titles), "zu_spielen": len(match_titles),
        "quellen": dict(sources.most_common(15)),
        "verben": _verbs(rows, names),
        "woerter": {w: {"n": n, "aktiv": n >= WORD_MIN} for w, n in sorted(words.items(), key=lambda kv: -kv[1])},
        "spitznamen": nicks,
        "form": {"ergebnis_vorn": round(front / max(len(match_titles), 1), 3),
                 "doppelpunkt": round(colon / max(len(match_titles), 1), 3),
                 "woerter_schnitt": round(sum(len(t.split()) for t in match_titles) / max(len(match_titles), 1), 1)},
    }


def _active(p: dict) -> dict:
    """Der Teil des Profils, der die Berichte verändert."""
    return {"verben": sorted(k for k, v in p.get("verben", {}).items() if v["aktiv"]),
            "woerter": sorted(w for w, v in p.get("woerter", {}).items() if v["aktiv"]),
            "spitznamen": sorted(n["name"] for ns in p.get("spitznamen", {}).values() for n in ns if n["aktiv"]),
            "ergebnis_vorn": p.get("form", {}).get("ergebnis_vorn", 0) >= SCORE_FRONT_MIN}


def _diff(old: dict, new: dict) -> list[str]:
    a, b = _active(old), _active(new)
    out = []
    for key, label in (("verben", "Verb"), ("woerter", "Wort"), ("spitznamen", "Spitzname")):
        out += [f"{label} neu: {x}" for x in b[key] if x not in a[key]]
        out += [f"{label} weg: {x}" for x in a[key] if x not in b[key]]
    if a["ergebnis_vorn"] != b["ergebnis_vorn"]:
        out.append(f"Schlagzeilen mit Ergebnis vorn: {'an' if b['ergebnis_vorn'] else 'aus'}")
    return out


def update() -> list[str]:
    """Profil neu zählen und speichern. Rückgabe: Änderungen, die die Berichte betreffen (leer: nur Zahlen neu)."""
    new = compute()
    with engine.begin() as conn:
        conn.execute(text(DDL))
        last = conn.execute(text("SELECT id, profile FROM press_style ORDER BY id DESC LIMIT 1")).first()
        changes = _diff(last.profile if last else {}, new)
        if last and not changes:
            conn.execute(text("UPDATE press_style SET profile = CAST(:p AS jsonb), updated_at = now() WHERE id = :id"),
                         {"p": json.dumps(new, ensure_ascii=False), "id": last.id})
        else:
            conn.execute(text("INSERT INTO press_style (profile, changes) VALUES (CAST(:p AS jsonb), CAST(:c AS jsonb))"),
                         {"p": json.dumps(new, ensure_ascii=False), "c": json.dumps(changes, ensure_ascii=False)})
    _cache.clear()
    return changes


_cache: dict = {}


def current() -> dict:
    """Aktuelles Profil (leer, solange noch keins gezählt wurde: dann schreiben die Berichte wie bisher)."""
    if "p" not in _cache:
        with engine.connect() as conn:
            conn.execute(text(DDL))
            conn.commit()
            row = conn.execute(text("SELECT profile FROM press_style ORDER BY id DESC LIMIT 1")).first()
        _cache["p"] = row.profile if row else {}
    return _cache["p"]


def history(limit: int = 20) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, created_at, updated_at, changes FROM press_style ORDER BY id DESC LIMIT :n"),
                            {"n": limit}).all()
    return [{"version": r.id, "seit": r.created_at.isoformat(timespec="minutes"),
             "zuletzt_gezaehlt": r.updated_at.isoformat(timespec="minutes"), "aenderungen": r.changes} for r in rows]


class Style:
    """Was die Berichte aus dem Profil brauchen."""

    def __init__(self, profile: dict | None = None):
        p = current() if profile is None else profile
        self.verbs = {"S": [], "N": []}
        for v in p.get("verben", {}).values():
            if v["aktiv"] and v["ausgang"] in self.verbs:
                self.verbs[v["ausgang"]].append(v)
        self.words = {w for w, v in p.get("woerter", {}).items() if v["aktiv"]}
        self.nicks = {team: [n for n in ns if n["aktiv"]] for team, ns in p.get("spitznamen", {}).items()}
        self.score_front = p.get("form", {}).get("ergebnis_vorn", 0) >= SCORE_FRONT_MIN

    def has(self, word: str) -> bool:
        return word in self.words

    def nick(self, team: str) -> dict | None:
        ns = self.nicks.get(team) or []
        return max(ns, key=lambda n: n["n"]) if ns else None
