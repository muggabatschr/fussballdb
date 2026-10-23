"""Backtest: Spieltag für Spieltag nur mit vorher bekannten Daten vorhersagen und mit
Ergebnis und Buchmacher-Quoten vergleichen."""

import numpy as np
import pandas as pd

from fussballdb.features.availability import AvailabilityModel
from fussballdb.model.data import load_market, load_matches
from fussballdb.model.dixon_coles import DixonColes
from fussballdb.model.ensemble import Forecaster


def scores(p: np.ndarray, outcome: np.ndarray) -> dict:
    """p: Spalten Heim/Remis/Auswärts. outcome: 0 Heim, 1 Remis, 2 Auswärts."""
    onehot = np.eye(3)[outcome]
    brier = np.mean(np.sum((p - onehot) ** 2, axis=1))
    logloss = -np.mean(np.log(np.clip(p[np.arange(len(p)), outcome], 1e-12, None)))
    # Ranked Probability Score: Standardmaß im Fußball, berücksichtigt die Reihenfolge H > X > A
    rps = np.mean(np.sum((np.cumsum(p, axis=1) - np.cumsum(onehot, axis=1))[:, :2] ** 2, axis=1) / 2)
    acc = np.mean(p.argmax(axis=1) == outcome)
    return {"n": len(p), "rps": rps, "brier": brier, "logloss": logloss, "accuracy": acc}


def backtest(seasons: list[int], xi: float = 0.003, w_xg: float = 1.0, alpha: float = 0.7,
             absences: str = "verletzte") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rückblick wie die gespeicherten Prognosen. absences: "verletzte" (Verletztenliste zum Stichtag,
    wie das Modell rechnet), "keine" oder "aufstellung" (echte Aufstellung = Wissen aus der Zukunft,
    nur als Obergrenze)."""
    from fussballdb.model.data import load_squad_values

    df = load_matches()
    values = load_squad_values()
    availability = AvailabilityModel() if absences != "keine" else None
    injuries = load_injuries() if absences == "verletzte" else None
    preds = []
    for season in seasons:
        sdf = df[(df["season"] == season) & df["finished"]]
        for md in sorted(sdf["matchday"].unique()):
            test = sdf[sdf["matchday"] == md]
            cutoff = test["kickoff"].min()
            if not (df["finished"] & (df["kickoff"] < cutoff)).any():
                continue
            model = Forecaster(alpha=alpha, dc=DixonColes(xi=xi, w_xg=w_xg), values=values).fit(df, cutoff)
            for r in test.itertuples():
                hi = ai = None
                if absences == "verletzte":
                    hi = availability.impact(r.home_id, cutoff, availability.injured_as_of(r.home_id, cutoff, injuries))
                    ai = availability.impact(r.away_id, cutoff, availability.injured_as_of(r.away_id, cutoff, injuries))
                elif absences == "aufstellung":
                    hi = availability.impact(r.home_id, cutoff, availability.missing_from_lineup(r.home_id, r.match_id, cutoff))
                    ai = availability.impact(r.away_id, cutoff, availability.missing_from_lineup(r.away_id, r.match_id, cutoff))
                p = model.predict_match(r.home_id, r.away_id, r.match_id, hi, ai)
                preds.append({"match_id": r.match_id, "season": season, "matchday": md,
                              "home": r.home, "away": r.away, "hg": r.hg, "ag": r.ag,
                              "p_home": p["p_home"], "p_draw": p["p_draw"], "p_away": p["p_away"],
                              "dc_home": p["dc"]["p_home"], "dc_draw": p["dc"]["p_draw"], "dc_away": p["dc"]["p_away"],
                              "elo_home": p["elo"]["p_home"], "elo_draw": p["elo"]["p_draw"], "elo_away": p["elo"]["p_away"]})
    pred = pd.DataFrame(preds)
    outcome = np.where(pred["hg"] > pred["ag"], 0, np.where(pred["hg"] == pred["ag"], 1, 2))
    market = load_market()
    rows = []
    for name, cols in (("Ensemble", ["p_home", "p_draw", "p_away"]),
                       ("Dixon-Coles", ["dc_home", "dc_draw", "dc_away"]),
                       ("Elo", ["elo_home", "elo_draw", "elo_away"])):
        rows.append({"modell": name, **scores(pred[cols].to_numpy(), outcome)})
    for closing, label in ((False, "Markt Eröffnung"), (True, "Markt Schluss")):
        m = pred[["match_id"]].merge(market[market["is_closing"] == closing], on="match_id", how="left")
        ok = m["p_home"].notna().to_numpy()
        rows.append({"modell": label, **scores(m.loc[ok, ["p_home", "p_draw", "p_away"]].to_numpy(), outcome[ok])})
    rows.append({"modell": "Basis (Ø-Verteilung)", **scores(
        np.tile(np.bincount(outcome, minlength=3) / len(outcome), (len(outcome), 1)), outcome)})
    return pd.DataFrame(rows), pred


def compare_xg_variants(seasons: list[int], variants=("xg", "npxg", "npxg_pen", "close"),
                        w_xgs=(0.9, 1.0), red_weights=(1.0, 0.5)) -> pd.DataFrame:
    """Rückblick-Test der xG-Varianten (features/xg_variants.py): pro Spieltag nur Daten davor,
    ohne Ausfälle. Liefert RPS des Ensembles je Kombination, sortiert."""
    from fussballdb.features.xg_variants import apply_variant, team_match_xg

    from fussballdb.model.data import load_squad_values

    base = load_matches()
    values = load_squad_values()
    xg = team_match_xg()
    test = base[base["finished"] & base["season"].isin(seasons)]
    groups = list(test.groupby(["season", "matchday"]))
    # Ergebnisse in derselben Reihenfolge wie die Prognosen (nach Spieltag, nicht nach Anstoß)
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    rows = []
    for variant in variants:
        df = apply_variant(base, variant, xg)
        for w_xg in w_xgs:
            for red_w in red_weights:
                probs = []
                for (season, md), games in groups:
                    cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
                    model = Forecaster(dc=DixonColes(w_xg=w_xg, red_card_weight=red_w), values=values).fit(df, cutoff)
                    for r in games.itertuples():
                        p = model.predict_match(r.home_id, r.away_id, r.match_id)
                        probs.append([p["p_home"], p["p_draw"], p["p_away"]])
                s = scores(np.array(probs), outcome)
                rows.append({"variante": variant, "w_xg": w_xg, "rote_karten_gewicht": red_w,
                             "rps": s["rps"], "logloss": s["logloss"], "n": s["n"]})
    return pd.DataFrame(rows).sort_values("rps")


def compare_squad_value(tune_seasons=(2024,), test_seasons=(2025, 2026),
                        ks=(0.0, 0.2, 0.3, 0.5), ridges=(2.0, 5.0),
                        newcomers_only=(False, True)) -> pd.DataFrame:
    """Kaderwert als Startstärke im Rückblick-Test. Gewicht und Dämpfung werden nur an den
    tune_seasons gewählt, bewertet wird an den test_seasons. RPS gesamt und für Spieltag 1–8."""
    from fussballdb.model.data import load_squad_values

    df = load_matches()
    values = load_squad_values()
    test = df[df["finished"] & df["season"].isin(tune_seasons + test_seasons)]
    groups = list(test.groupby(["season", "matchday"]))
    meta = [(season, md, 0 if r.hg > r.ag else 1 if r.hg == r.ag else 2) for (season, md), g in groups for r in g.itertuples()]
    seasons_arr = np.array([m[0] for m in meta])
    md_arr = np.array([m[1] for m in meta])
    outcome = np.array([m[2] for m in meta])
    rows = []
    combos = [(k, r, n) for k in ks for r in ridges for n in newcomers_only if not (k == 0 and n)]
    for k, ridge, only_new in combos:
        probs = []
        for (season, md), games in groups:
            cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
            model = Forecaster(dc=DixonColes(ridge=ridge), value_k=k, values=values,
                               value_newcomers_only=only_new).fit(df, cutoff)
            for r in games.itertuples():
                p = model.predict_match(r.home_id, r.away_id, r.match_id)
                probs.append([p["p_home"], p["p_draw"], p["p_away"]])
        p = np.array(probs)
        row = {"k": k, "ridge": ridge, "nur_aufsteiger": only_new}
        for label, mask in (("tune", np.isin(seasons_arr, tune_seasons)), ("test", np.isin(seasons_arr, test_seasons))):
            row[f"rps_{label}"] = scores(p[mask], outcome[mask])["rps"]
            early = mask & (md_arr <= 8)
            row[f"rps_{label}_st1_8"] = scores(p[early], outcome[early])["rps"]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("rps_tune")


EXTRA_CONFIGS: dict[str, dict] = {
    "basis": {},
    "halbwertszeit 5 Mon. (xi 0,005)": {"dc": {"xi": 0.005}},
    "halbwertszeit 3 Mon. (xi 0,008)": {"dc": {"xi": 0.008}},
    "halbwertszeit 2 Mon. (xi 0,012)": {"dc": {"xi": 0.012}},
    "form 20 %, 5 Wochen": {"form_weight": 0.2, "form_xi": 0.02},
    "form 40 %, 5 Wochen": {"form_weight": 0.4, "form_xi": 0.02},
    "form 20 %, 2,5 Wochen": {"form_weight": 0.2, "form_xi": 0.04},
    "form 40 %, 2,5 Wochen": {"form_weight": 0.4, "form_xi": 0.04},
    "heim je team, dämpfung 5": {"dc": {"team_home_ridge": 5.0}},
    "heim je team, dämpfung 20": {"dc": {"team_home_ridge": 20.0}},
    "heim je team, dämpfung 50": {"dc": {"team_home_ridge": 50.0}},
    "duelle, dämpfung 2 xG": {"h2h_c": 2.0},
    "duelle, dämpfung 5 xG": {"h2h_c": 5.0},
    "duelle, dämpfung 10 xG": {"h2h_c": 10.0},
}


def extra_predictions(configs: dict[str, dict], seasons=(2024, 2025, 2026)):
    """Rückblick-Prognosen (nur Daten vor jedem Spieltag) für mehrere Modellvarianten.
    Liefert (Metadaten je Spiel, {Name: Wahrscheinlichkeiten}, Ergebnisse) in gleicher Reihenfolge."""
    from fussballdb.model.data import load_squad_values

    df = load_matches()
    values = load_squad_values()
    test = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(test.groupby(["season", "matchday"]))
    meta = pd.DataFrame([{"season": s, "matchday": md} for (s, md), g in groups for _ in range(len(g))])
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    probs = {}
    for name, cfg in configs.items():
        out = []
        for (season, md), games in groups:
            cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
            kw = {k: v for k, v in cfg.items() if k != "dc"}
            model = Forecaster(dc=DixonColes(**cfg.get("dc", {})), values=values, **kw).fit(df, cutoff)
            for r in games.itertuples():
                p = model.predict_match(r.home_id, r.away_id, r.match_id)
                out.append([p["p_home"], p["p_draw"], p["p_away"]])
        probs[name] = np.array(out)
    return meta, probs, outcome


def rps_per_match(p: np.ndarray, outcome: np.ndarray) -> np.ndarray:
    onehot = np.eye(3)[outcome]
    return np.sum((np.cumsum(p, 1) - np.cumsum(onehot, 1))[:, :2] ** 2, 1) / 2


def compare_extras(configs: dict[str, dict] | None = None, tune=(2024,), test=(2025, 2026), seed: int = 0) -> pd.DataFrame:
    """Form, Heimvorteil je Team, direkte Duelle gegen das aktuelle Modell ("basis").
    Spalten: RPS-Differenz im Tuning- und Testzeitraum (negativ = besser) und Anteil der
    Bootstrap-Ziehungen im Testzeitraum, in denen die Variante besser ist."""
    configs = configs or EXTRA_CONFIGS
    meta, probs, outcome = extra_predictions(configs, tune + test)
    base = rps_per_match(probs["basis"], outcome)
    is_tune = meta["season"].isin(tune).to_numpy()
    rng = np.random.default_rng(seed)
    test_idx = np.flatnonzero(~is_tune)
    boot = rng.choice(test_idx, (2000, len(test_idx)))
    rows = []
    for name, p in probs.items():
        d = rps_per_match(p, outcome) - base
        rows.append({"variante": name, "rps_test": rps_per_match(p, outcome)[~is_tune].mean(),
                     "delta_tune": d[is_tune].mean(), "delta_test": d[~is_tune].mean(),
                     "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean() if name != "basis" else np.nan})
    return pd.DataFrame(rows).sort_values("delta_tune")


def compare_tips(seasons=(2023, 2024, 2025, 2026), seed: int = 0, rule=None, dc_kwargs: dict | None = None,
                 base_dc_kwargs: dict | None = None) -> pd.DataFrame:
    """Bisheriger Tipp (wahrscheinlichste Tendenz, darin wahrscheinlichstes Ergebnis) gegen den Tipp
    mit den meisten erwarteten Kicktipp-Punkten. Rückblick, nur Daten vor jedem Spieltag."""
    from fussballdb.model.data import load_squad_values
    from fussballdb.config import TIPP_PUNKTE
    from fussballdb.model.ensemble import kicktipp_points, points_table, tip, tip_expected_points

    rule = rule or TIPP_PUNKTE
    table = points_table(rule)

    df = load_matches()
    values = load_squad_values()
    played = df[df["finished"] & df["season"].isin(seasons)]
    rows = []
    for (season, md), games in played.groupby(["season", "matchday"]):
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        if not (df["finished"] & (df["kickoff"] < cutoff)).any():
            continue
        base = Forecaster(values=values, dc=DixonColes(**(base_dc_kwargs or {}))).fit(df, cutoff)
        model = Forecaster(values=values, dc=DixonColes(**(dc_kwargs or {}))).fit(df, cutoff) if dc_kwargs else base
        for r in games.itertuples():
            pb = base.predict_match(r.home_id, r.away_id, r.match_id)
            old = tip(base.dc.score_matrix(r.home_id, r.away_id), pb)
            p = model.predict_match(r.home_id, r.away_id, r.match_id)
            m = model.dc.score_matrix(r.home_id, r.away_id)
            new = tip_expected_points(m, p, table)
            rows.append({"season": season, "alt": kicktipp_points(*old, int(r.hg), int(r.ag), rule),
                         "neu": kicktipp_points(*new, int(r.hg), int(r.ag), rule),
                         "alt_remis": old[0] == old[1], "neu_remis": new[0] == new[1],
                         "neu_tipp": f"{new[0]}:{new[1]}"})
    res = pd.DataFrame(rows)
    rng = np.random.default_rng(seed)
    out = []
    for label, part in [*res.groupby("season"), ("gesamt", res)]:
        d = (part["neu"] - part["alt"]).to_numpy()
        boots = d[rng.integers(0, len(d), (4000, len(d)))].mean(1)
        out.append({"saison": label, "spiele": len(part), "pkt_alt": part["alt"].mean(), "pkt_neu": part["neu"].mean(),
                    "neu_besser_pct": 100 * (boots > 0).mean(), "remis_tipps_alt_pct": 100 * part["alt_remis"].mean(),
                    "remis_tipps_neu_pct": 100 * part["neu_remis"].mean()})
    print("Häufigste neue Tipps:", res["neu_tipp"].value_counts().head(6).to_dict())
    return pd.DataFrame(out)


def load_injuries() -> pd.DataFrame:
    from sqlalchemy import text as sql

    from fussballdb.db.session import engine

    df = pd.read_sql(sql("SELECT player_id, team_id, von, bis FROM player_injury WHERE player_id IS NOT NULL"), engine)
    df["von"] = pd.to_datetime(df["von"]).dt.date
    df["bis"] = pd.to_datetime(df["bis"]).dt.date
    return df


def compare_injuries(seasons=(2024, 2025, 2026), betas=(0.5, 0.8, 1.0), seed: int = 0) -> pd.DataFrame:
    """Ausfälle aus der Verletzungshistorie (Stand: Stichtag des Spieltags) gegen keine Ausfälle.
    Zusätzlich zur Einordnung: echte Aufstellungen (Wissen aus der Zukunft, nur Obergrenze)."""
    from fussballdb.model.data import load_squad_values

    df = load_matches()
    values = load_squad_values()
    injuries = load_injuries()
    av = AvailabilityModel()
    test = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(test.groupby(["season", "matchday"]))
    meta = pd.DataFrame([{"season": s, "matchday": md} for (s, md), g in groups for _ in range(len(g))])
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    variants = {"keine": None, **{f"verletzte β={b}": b for b in betas}, "echte aufstellung (obergrenze)": "lineup"}
    probs = {k: [] for k in variants}
    n_missing = []
    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        model = Forecaster(values=values).fit(df, cutoff)
        for r in games.itertuples():
            inj_h, inj_a = av.injured_as_of(r.home_id, cutoff, injuries), av.injured_as_of(r.away_id, cutoff, injuries)
            n_missing.append(len(inj_h) + len(inj_a))
            for name, beta in variants.items():
                if beta is None:
                    p = model.predict_match(r.home_id, r.away_id, r.match_id)
                elif beta == "lineup":
                    av.beta = 0.8
                    p = model.predict_match(r.home_id, r.away_id, r.match_id,
                                            av.impact(r.home_id, cutoff, av.missing_from_lineup(r.home_id, r.match_id, cutoff)),
                                            av.impact(r.away_id, cutoff, av.missing_from_lineup(r.away_id, r.match_id, cutoff)))
                else:
                    av.beta = beta
                    p = model.predict_match(r.home_id, r.away_id, r.match_id,
                                            av.impact(r.home_id, cutoff, inj_h), av.impact(r.away_id, cutoff, inj_a))
                probs[name].append([p["p_home"], p["p_draw"], p["p_away"]])
    base = rps_per_match(np.array(probs["keine"]), outcome)
    rng = np.random.default_rng(seed)
    rows = []
    for name, p in probs.items():
        d = rps_per_match(np.array(p), outcome) - base
        row = {"variante": name, "rps": base.mean() + d.mean(), "delta": d.mean()}
        for s in seasons:
            row[f"delta_{s}"] = d[(meta["season"] == s).to_numpy()].mean()
        row["besser_pct"] = 100 * (d[rng.integers(0, len(d), (4000, len(d)))].mean(1) < 0).mean() if name != "keine" else np.nan
        rows.append(row)
    print(f"Ø verletzt gemeldete Spieler je Spiel (beide Teams, mit Understat-Zuordnung): {np.mean(n_missing):.2f}")
    return pd.DataFrame(rows)


# Alle Erweiterungen, die einzeln getestet wurden, in ihrer jeweils besten Einstellung
COMBO_PARTS: dict[str, dict] = {
    "form": {"form_weight": 0.4, "form_xi": 0.02},
    "heim_je_team": {"dc": {"team_home_ridge": 20.0}},
    "duelle": {"h2h_c": 10.0},
    "verletzte": {"injury_beta": 0.5},
    "remis_kalibrierung": {"dc": {"draw_calibration": True}},
}


def _merge(*cfgs: dict) -> dict:
    out: dict = {}
    for c in cfgs:
        for k, v in c.items():
            if k == "dc":
                out.setdefault("dc", {}).update(v)
            else:
                out[k] = v
    return out


def combo_configs() -> dict[str, dict]:
    parts = COMBO_PARTS
    cfgs = {"basis": {}, "alles an": _merge(*parts.values())}
    for name in parts:
        cfgs[f"alles an ohne {name}"] = _merge(*(v for k, v in parts.items() if k != name))
    return cfgs


def combo_predictions(configs: dict[str, dict], seasons) -> tuple[pd.DataFrame, dict, np.ndarray]:
    """Wie extra_predictions, zusätzlich mit Ausfällen aus der Verletzungshistorie (Schlüssel injury_beta)."""
    from fussballdb.model.data import load_squad_values

    from fussballdb.features.onoff import OnOffModel

    df = load_matches()
    values = load_squad_values()
    injuries = load_injuries()
    av = AvailabilityModel()
    onoff = {}  # je Glättung ein Modell (Cache je Team und Stichtag)
    test = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(test.groupby(["season", "matchday"]))
    meta = pd.DataFrame([{"season": s, "matchday": md} for (s, md), g in groups for _ in range(len(g))])
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    probs = {k: [] for k in configs}
    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        injured = {}
        for name, cfg in configs.items():
            kw = {k: v for k, v in cfg.items() if k not in ("dc", "injury_beta", "injury_mode", "onoff_prior", "suspensions")}
            model = Forecaster(dc=DixonColes(**cfg.get("dc", {})), values=values, **kw).fit(df, cutoff)
            beta = cfg.get("injury_beta")
            for r in games.itertuples():
                hi = ai = None
                if beta:
                    av.beta = beta
                    for t in (r.home_id, r.away_id):
                        if t not in injured:
                            injured[t] = av.injured_as_of(t, cutoff, injuries)
                    if cfg.get("suspensions"):
                        for t in (r.home_id, r.away_id):
                            injured[(t, "s")] = injured.get((t, "s")) or (injured[t] | av.suspended_as_of(t, cutoff))
                        inj_h, inj_a = injured[(r.home_id, "s")], injured[(r.away_id, "s")]
                    else:
                        inj_h, inj_a = injured[r.home_id], injured[r.away_id]
                    if cfg.get("injury_mode") == "onoff":
                        prior = cfg.get("onoff_prior", 1500.0)
                        if prior not in onoff:
                            onoff[prior] = OnOffModel(prior_minutes=prior, shots=next(iter(onoff.values())).shots if onoff else None,
                                                      apps=next(iter(onoff.values())).apps if onoff else None)
                        m = onoff[prior]
                        hi = m.impact(r.home_id, cutoff, inj_h)
                        ai = m.impact(r.away_id, cutoff, inj_a)
                    else:
                        hi = av.impact(r.home_id, cutoff, inj_h)
                        ai = av.impact(r.away_id, cutoff, inj_a)
                p = model.predict_match(r.home_id, r.away_id, r.match_id, hi, ai)
                probs[name].append([p["p_home"], p["p_draw"], p["p_away"]])
    return meta, {k: np.array(v) for k, v in probs.items()}, outcome


def compare_combo(tune=tuple(range(2016, 2021)), test=tuple(range(2021, 2027)), seed: int = 0) -> pd.DataFrame:
    """Alle Erweiterungen zusammen und jeweils eine weggelassen, gegen das aktuelle Modell.
    delta < 0 = besser. Bootstrap-Anteil über den Testzeitraum."""
    configs = combo_configs()
    meta, probs, outcome = combo_predictions(configs, tune + test)
    base = rps_per_match(probs["basis"], outcome)
    is_tune = meta["season"].isin(tune).to_numpy()
    rng = np.random.default_rng(seed)
    test_idx = np.flatnonzero(~is_tune)
    boot = rng.choice(test_idx, (4000, len(test_idx)))
    rows = []
    for name, p in probs.items():
        d = rps_per_match(p, outcome) - base
        rows.append({"variante": name, "rps_test": rps_per_match(p, outcome)[~is_tune].mean(),
                     "delta_tune": d[is_tune].mean(), "delta_test": d[~is_tune].mean(),
                     "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean() if name != "basis" else np.nan,
                     "saisons_besser": f"{sum(d[(meta['season'] == s).to_numpy()].mean() < 0 for s in tune + test)}/{len(tune + test)}"})
    return pd.DataFrame(rows)


FINISH_VARIANTS: dict[str, dict] = {
    "5 Spiele, ungedämpft": {"finish_games": 5},
    "5 Spiele, Dämpfung 5 xG": {"finish_games": 5, "finish_c": 5.0},
    "5 Spiele, ungedämpft, mit Gegentoren": {"finish_games": 5, "finish_defense": True},
    "1 Jahr, Dämpfung 10 xG": {"finish_days": 365, "finish_c": 10.0},
    "1 Jahr, Dämpfung 20 xG": {"finish_days": 365, "finish_c": 20.0},
    "1 Jahr, Dämpfung 10 xG, mit Gegentoren": {"finish_days": 365, "finish_c": 10.0, "finish_defense": True},
}


def compare_finishing(tune=tuple(range(2016, 2021)), test=tuple(range(2021, 2027)), seed: int = 0,
                      variants: dict[str, dict] | None = None, progress=None) -> pd.DataFrame:
    """Über-/Unterperformance (Tore gegenüber xG) als Faktor auf die Torerwartung, gegen das aktuelle
    Modell (Form, Verletzte, Sperren). delta < 0 = besser, Bootstrap-Anteil über den Testzeitraum."""
    return compare_finishing_combo({"": {}}, variants or FINISH_VARIANTS, tune, test, seed, progress)


# Einzeln verworfene Erweiterungen (siehe README), für den Test in Kombination mit dem Abschluss-Faktor
REJECTED_PARTS: dict[str, dict] = {
    "heim je team": {"dc": {"team_home_ridge": 20.0}},
    "duelle": {"h2h_c": 10.0},
    "remis-kalibrierung": {"dc": {"draw_calibration": True}},
    "halbwertszeit 3 Mon.": {"dc": {"xi": 0.008}},
    "tor-skalierung": {"dc": {"goal_scale": True}},
}
FINISH_COMBO_VARIANTS: dict[str, dict] = {
    "5 Spiele": {"finish_games": 5},
    "5 Spiele gedämpft": {"finish_games": 5, "finish_c": 5.0},
    "1 Jahr gedämpft": {"finish_days": 365, "finish_c": 20.0},
}


def finishing_combo_configs() -> dict[str, dict]:
    cfgs = {"": {}}
    for name, part in REJECTED_PARTS.items():
        cfgs[name] = part
    cfgs["alle verworfenen"] = _merge(*REJECTED_PARTS.values())
    return cfgs


def compare_finishing_combo(fit_configs: dict[str, dict] | None = None, variants: dict[str, dict] | None = None,
                            tune=tuple(range(2016, 2021)), test=tuple(range(2021, 2027)), seed: int = 0,
                            progress=None) -> pd.DataFrame:
    """Modellvarianten (je Spieltag einmal trainiert) jeweils ohne und mit Abschluss-Faktor (nur bei der
    Vorhersage), alles gegen das aktuelle Modell. Ausfälle wie live: Verletzte aus der Historie und Sperren."""
    from fussballdb.model.data import load_squad_values

    fit_configs = fit_configs or finishing_combo_configs()
    variants = variants if variants is not None else FINISH_COMBO_VARIANTS
    df = load_matches()
    values = load_squad_values()
    injuries = load_injuries()
    av = AvailabilityModel()
    seasons = tune + test
    games_all = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(games_all.groupby(["season", "matchday"]))
    meta = pd.DataFrame([{"season": s, "matchday": md} for (s, md), g in groups for _ in range(len(g))])
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    off = {"finish_games": 0, "finish_days": 0, "finish_c": 0.0, "finish_defense": False}
    labels = {}
    for fit_name in fit_configs:
        for fin_name in ["", *variants]:
            label = " + ".join(x for x in (fit_name, fin_name) if x) or "basis"
            labels[label] = (fit_name, fin_name)
    probs = {label: [] for label in labels}
    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        impacts = {}
        for r in games.itertuples():
            for t in (r.home_id, r.away_id):
                impacts[t] = av.impact(t, cutoff, av.injured_as_of(t, cutoff, injuries) | av.suspended_as_of(t, cutoff))
        for fit_name, cfg in fit_configs.items():
            kw = {k: v for k, v in cfg.items() if k != "dc"}
            model = Forecaster(dc=DixonColes(**cfg.get("dc", {})), values=values, **kw).fit(df, cutoff)
            for fin_name in ["", *variants]:
                for k, v in (off | variants.get(fin_name, {})).items():
                    setattr(model, k, v)
                label = " + ".join(x for x in (fit_name, fin_name) if x) or "basis"
                for r in games.itertuples():
                    p = model.predict_match(r.home_id, r.away_id, r.match_id, impacts[r.home_id], impacts[r.away_id])
                    probs[label].append([p["p_home"], p["p_draw"], p["p_away"]])
        if progress:
            progress(season, md)
    probs = {k: np.array(v) for k, v in probs.items()}
    base = rps_per_match(probs["basis"], outcome)
    is_tune = meta["season"].isin(tune).to_numpy()
    rng = np.random.default_rng(seed)
    test_idx = np.flatnonzero(~is_tune)
    boot = rng.choice(test_idx, (4000, len(test_idx)))
    rows = []
    for name, p in probs.items():
        d = rps_per_match(p, outcome) - base
        rows.append({"variante": name, "rps_test": rps_per_match(p, outcome)[~is_tune].mean(),
                     "delta_tune": d[is_tune].mean(), "delta_test": d[~is_tune].mean(),
                     "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean() if name != "basis" else np.nan,
                     "saisons_besser": f"{sum(d[(meta['season'] == s).to_numpy()].mean() < 0 for s in seasons)}/{len(seasons)}"})
    return pd.DataFrame(rows).sort_values("delta_test")


def euro_matches_by_team() -> dict[int, list[pd.Timestamp]]:
    """Anstoßzeiten der Europapokalspiele (CL, EL) je Bundesliga-Team."""
    from fussballdb.features.euro_load import euro_schedule

    return {t: [k for k, _ in games] for t, games in euro_schedule().items()}


EURO_LOAD_VARIANTS = {
    "Angriff −3 %": (0.03, False),
    "Angriff −6 %": (0.06, False),
    "Angriff −10 %": (0.10, False),
    "Angriff −6 %, Abwehr +6 %": (0.06, True),
}


def compare_euro_load(seasons=(2024, 2025, 2026), days: int = 4, seed: int = 0, progress=None) -> pd.DataFrame:
    """Europapokal-Belastung: Team mit Europapokalspiel in den `days` Tagen vor dem Bundesliga-Spiel bekommt
    eine geringere Torerwartung (und optional mehr Gegentore). Gegen das Modell ohne Belastung (Form,
    Verletzte, Sperren); Bootstrap über die betroffenen Spiele."""
    from fussballdb.model.data import load_squad_values

    df = load_matches()
    values = load_squad_values()
    injuries = load_injuries()
    av = AvailabilityModel()
    euro = euro_matches_by_team()
    games_all = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(games_all.groupby(["season", "matchday"]))
    outcome, loaded, season_of, probs = [], [], [], {name: [] for name in ["basis", *EURO_LOAD_VARIANTS]}

    def tired(team: int, kickoff: pd.Timestamp) -> bool:
        return any(pd.Timedelta(0) < kickoff - k <= pd.Timedelta(days=days) for k in euro.get(team, []))

    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        model = Forecaster(values=values).fit(df, cutoff)
        for r in games.itertuples():
            imp = {t: av.impact(t, cutoff, av.injured_as_of(t, cutoff, injuries) | av.suspended_as_of(t, cutoff))
                   for t in (r.home_id, r.away_id)}
            th, ta = tired(r.home_id, r.kickoff), tired(r.away_id, r.kickoff)
            loaded.append(th or ta)
            season_of.append(season)
            outcome.append(0 if r.hg > r.ag else 1 if r.hg == r.ag else 2)
            for name, (delta, defence) in [("basis", (0.0, False)), *EURO_LOAD_VARIANTS.items()]:
                hi, ai = dict(imp[r.home_id]), dict(imp[r.away_id])
                for side, flag in ((hi, th), (ai, ta)):
                    if flag:
                        side["attack_mult"] = side["attack_mult"] * (1 - delta)
                        if defence:
                            side["concede_mult"] = side["concede_mult"] * (1 + delta)
                p = model.predict_match(r.home_id, r.away_id, r.match_id, hi, ai)
                probs[name].append([p["p_home"], p["p_draw"], p["p_away"]])
        if progress:
            progress(season, md)
    outcome, loaded, season_of = np.array(outcome), np.array(loaded), np.array(season_of)
    base = rps_per_match(np.array(probs["basis"]), outcome)
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(loaded)
    boot = rng.choice(idx, (4000, len(idx)))
    rows = []
    for name, p in probs.items():
        d = rps_per_match(np.array(p), outcome) - base
        rows.append({"variante": name, "spiele_mit_belastung": int(loaded.sum()), "spiele": len(outcome),
                     "delta_belastet": d[loaded].mean(), "delta_alle": d.mean(),
                     "besser_pct": 100 * (d[boot].mean(1) < 0).mean() if name != "basis" else np.nan,
                     "saisons_besser": f"{sum(d[loaded & (season_of == s)].mean() < 0 for s in seasons)}/{len(seasons)}"})
    return pd.DataFrame(rows)


def compare_elo_history(first_long: int = 1993, tune=tuple(range(2015, 2020)), test=tuple(range(2020, 2027)),
                        seed: int = 0) -> pd.DataFrame:
    """Elo mit Vorgeschichte ab `first_long` (ältere Saisons nur mit Toren) gegen die Elo ab 2014/15.

    Beide Varianten bewerten dieselben Spiele ab 2015/16; das Ergebnis-Logit wird je Saison auf denselben
    Spielen davor (ab 2014/15) angepasst, der Unterschied liegt also nur in den Elo-Werten. Spalten wie bei
    compare_extras: RPS, Differenz (negativ = Vorgeschichte besser) und Anteil der Bootstrap-Ziehungen im
    Testzeitraum, in denen die Vorgeschichte besser ist."""
    from fussballdb.config import MODEL_FIRST_SEASON
    from fussballdb.model.elo import Elo, EloOutcomeModel

    short, long_ = load_matches(), load_matches(first_long)
    tables = {name: Elo().run(df).set_index("match_id") for name, df in (("ab 2014/15", short), (f"ab {first_long}", long_))}
    played = short[short["finished"]].set_index("match_id")
    outcome_all = pd.Series(np.where(played["hg"] > played["ag"], 2, np.where(played["hg"] == played["ag"], 1, 0)),
                            index=played.index)
    probs: dict[str, list[np.ndarray]] = {name: [] for name in tables}
    meta, outcomes = [], []
    for season in tune + test:
        train = played[(played["season"] >= MODEL_FIRST_SEASON) & (played["season"] < season)].index
        target = played[played["season"] == season].index
        for name, tab in tables.items():
            model = EloOutcomeModel().fit(tab.loc[train, "elo_home"], tab.loc[train, "elo_away"], outcome_all[train])
            p = model.predict(tab.loc[target, "elo_home"], tab.loc[target, "elo_away"])  # Auswärts, Remis, Heim
            probs[name].append(p[:, ::-1])  # Heim, Remis, Auswärts
        meta += [season] * len(target)
        outcomes.append(2 - outcome_all[target].to_numpy())  # 0 = Heimsieg wie in scores()
    outcome = np.concatenate(outcomes)
    season_arr = np.array(meta)
    p_short, p_long = (np.vstack(probs[n]) for n in tables)
    r_short, r_long = rps_per_match(p_short, outcome), rps_per_match(p_long, outcome)
    d = r_long - r_short
    is_tune = np.isin(season_arr, tune)
    test_idx = np.flatnonzero(~is_tune)
    boot = np.random.default_rng(seed).choice(test_idx, (2000, len(test_idx)))
    rows = [{"variante": name, "rps_einstellen": r[is_tune].mean(), "rps_test": r[~is_tune].mean()}
            for name, r in zip(tables, (r_short, r_long))]
    rows[1] |= {"delta_test": d[~is_tune].mean(), "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean(),
                "saisons_besser": int(sum(d[season_arr == s].mean() < 0 for s in test)), "saisons": len(test)}
    return pd.DataFrame(rows)


LINEUP_KS = (0.1, 0.2, 0.4)


def compare_lineup_strength(fit_configs: dict[str, dict] | None = None, tune=(2024,), test=(2025, 2026),
                            seed: int = 0, progress=None) -> pd.DataFrame:
    """Startelf-Korrektur (features/lineup_strength.py) im Rückblick: Stärke der aufgebotenen gegen die übliche
    Elf, Spielerstärke aus Kickbase-Punkten, FotMob-Noten, xG+xA oder gemischt, je mit k aus LINEUP_KS.
    Modus "+": zusätzlich zu den Ausfällen (Verletzte, Sperren); "statt": nur die Startelf (die Ausfälle stecken
    darin). Dazu "startelf xg-anteil": fehlende Stammspieler aus der Startelf mit der bisherigen Gewichtung.
    Jede Modellvariante (aktuelles Modell, jede verworfene Erweiterung, alle verworfenen) ohne und mit Korrektur,
    alles gegen das aktuelle Modell wie live (Ausfälle, Europapokal-Belastung). Der mittlere Abstand je Quelle
    im Einstellzeitraum wird abgezogen (die übliche Elf ist im Schnitt etwas stärker als die aufgebotene)."""
    from fussballdb.config import TIPP_PUNKTE
    from fussballdb.features import euro_load
    from fussballdb.features.lineup_strength import SOURCES, LineupStrength
    from fussballdb.model.data import load_squad_values
    from fussballdb.model.ensemble import kicktipp_points

    fit_configs = fit_configs or finishing_combo_configs()
    df = load_matches()
    values = load_squad_values()
    injuries = load_injuries()
    av = AvailabilityModel()
    ls = LineupStrength(av)
    schedule = euro_load.euro_schedule()
    seasons = tune + test
    games_all = df[df["finished"] & df["season"].isin(seasons)]
    groups = list(games_all.groupby(["season", "matchday"]))
    meta = pd.DataFrame([{"season": s, "matchday": md} for (s, md), g in groups for _ in range(len(g))])
    outcome = np.array([0 if r.hg > r.ag else 1 if r.hg == r.ag else 2 for _, g in groups for r in g.itertuples()])
    goals = [(r.hg, r.ag) for _, g in groups for r in g.itertuples()]

    # Abstände vorab (hängen nicht von der Modellvariante ab), Mittelwert im Einstellzeitraum je Quelle
    gaps: dict[tuple, float | None] = {}
    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        for r in games.itertuples():
            for t in (r.home_id, r.away_id):
                for src in SOURCES:
                    gaps[(src, t, r.match_id)] = ls.gap(src, t, r.match_id, cutoff)
    tune_ids = set(games_all.loc[games_all["season"].isin(tune), "match_id"])
    offset = {src: float(np.mean([v for (s, _, m), v in gaps.items() if s == src and m in tune_ids and v is not None]))
              for src in SOURCES}
    coverage = {src: np.mean([v is not None for (s, _, _), v in gaps.items() if s == src]) for src in SOURCES}

    variants = {"": None, "startelf xg-anteil": ("anteil", None, None)}
    for src in SOURCES:
        for k in LINEUP_KS:
            variants[f"{src} + k={k}"] = ("plus", src, k)
            variants[f"{src} statt k={k}"] = ("statt", src, k)
    labels = {" + ".join(x for x in (f, v) if x) or "basis": (f, v) for f in fit_configs for v in variants}
    probs = {label: [] for label in labels}
    points = {label: [] for label in labels}
    for (season, md), games in groups:
        cutoff = df.loc[(df["season"] == season) & (df["matchday"] == md), "kickoff"].min()
        base_imp, xi_imp = {}, {}
        for r in games.itertuples():
            for t in (r.home_id, r.away_id):
                susp = av.suspended_as_of(t, cutoff)
                base_imp[t] = av.impact(t, cutoff, av.injured_as_of(t, cutoff, injuries) | susp, susp)
                prof = av.player_profile(t, cutoff)
                xi = ls.starters.get((r.match_id, t))
                missing = set(prof.loc[prof["regular"], "player_id"]) - xi if xi else set()
                xi_imp[t] = av.impact(t, cutoff, missing)
        for fit_name, cfg in fit_configs.items():
            kw = {k: v for k, v in cfg.items() if k != "dc"}
            model = Forecaster(dc=DixonColes(**cfg.get("dc", {})), values=values, **kw).fit(df, cutoff)
            for var_name, spec in variants.items():
                label = " + ".join(x for x in (fit_name, var_name) if x) or "basis"
                for r in games.itertuples():
                    imps = []
                    for t in (r.home_id, r.away_id):
                        if spec is None:
                            imp = base_imp[t]
                        elif spec[0] == "anteil":
                            imp = xi_imp[t]
                        else:
                            mode, src, k = spec
                            d = gaps[(src, t, r.match_id)]
                            d = None if d is None else d - offset[src]
                            imp = LineupStrength.apply(base_imp[t] if mode == "plus" else None, d, k)
                        imps.append(euro_load.apply(imp, t, r.kickoff, schedule))
                    p = model.predict_match(r.home_id, r.away_id, r.match_id, imps[0], imps[1])
                    probs[label].append([p["p_home"], p["p_draw"], p["p_away"]])
                    points[label].append(p["tip"])
        if progress:
            progress(season, md)
    is_tune = meta["season"].isin(tune).to_numpy()
    rng = np.random.default_rng(seed)
    test_idx = np.flatnonzero(~is_tune)
    boot = rng.choice(test_idx, (4000, len(test_idx)))
    base = rps_per_match(np.array(probs["basis"]), outcome)
    rows = []
    for name, p in probs.items():
        d = rps_per_match(np.array(p), outcome) - base
        pts = np.array([kicktipp_points(th, ta, h, a, TIPP_PUNKTE) for (th, ta), (h, a) in zip(points[name], goals)])
        rows.append({"variante": name, "rps_test": base[~is_tune].mean() + d[~is_tune].mean(),
                     "delta_tune": d[is_tune].mean(), "delta_test": d[~is_tune].mean(),
                     "test_besser_pct": 100 * (d[boot].mean(1) < 0).mean() if name != "basis" else np.nan,
                     "saisons_besser": f"{sum(d[(meta['season'] == s).to_numpy()].mean() < 0 for s in seasons)}/{len(seasons)}",
                     "punkte_tune": pts[is_tune].mean(), "punkte_test": pts[~is_tune].mean()})
    print("Abdeckung je Quelle (Anteil Team-Spiele mit Abstand):", {k: round(v, 2) for k, v in coverage.items()})
    print("Mittlerer Abstand im Einstellzeitraum (abgezogen):", {k: round(v, 3) for k, v in offset.items()})
    return pd.DataFrame(rows).sort_values("delta_test")
