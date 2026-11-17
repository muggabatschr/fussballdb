"""Ligawechsel bei Kickbase: nur Markt und Kader der aktiven Liga bleiben. Läuft gegen die echte Datenbank,
alles in einer Transaktion, die am Ende zurückgerollt wird."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.session import engine
from fussballdb.ingest import kickbase


def test_switching_league_drops_other_leagues(monkeypatch):
    monkeypatch.setattr(kickbase, "session_info_league", lambda: "222")
    answers = {"/market": {"it": [{"i": 9001, "prc": 1e6, "exs": 100}]},
               "/squad": {"it": [{"i": 9002, "mv": 2e6, "lo": 3}], "mppu": 15}, "/me/budget": {"b": -1e6}}
    monkeypatch.setattr(kickbase, "get", lambda path: next(v for k, v in answers.items() if path.endswith(k)))
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("INSERT INTO kb_league_entry (league_id, kb_id, kind, price) VALUES (111, 9003, 'kader', 1)"))
            with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
                assert kickbase.ingest_league(s) == {"markt": 1, "kader": 1, "budget": -1e6}
                s.commit()  # gibt nur den Savepoint frei, die äußere Transaktion rollt am Ende zurück
            rows = conn.execute(text("SELECT league_id, kb_id, kind FROM kb_league_entry ORDER BY kind")).all()
            assert rows == [(222, 9002, "kader"), (222, 9001, "markt")]  # Liga 111 ist weg
            assert conn.execute(text("SELECT lineup_pos FROM kb_league_entry WHERE kind = 'kader'")).scalar() == 3
            assert conn.execute(text("SELECT budget, max_players FROM kb_league_info")).one() == (-1e6, 15)
        finally:
            trans.rollback()
