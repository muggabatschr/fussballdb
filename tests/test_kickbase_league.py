"""Ligawechsel bei Kickbase: nur Markt und Kader der aktiven Liga bleiben. Läuft gegen die echte Datenbank,
alles in einer Transaktion, die am Ende zurückgerollt wird."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from fussballdb.db.session import engine
from fussballdb.ingest import kickbase


def test_switching_league_drops_other_leagues(monkeypatch):
    monkeypatch.setattr(kickbase, "session_info_league", lambda: "222")
    monkeypatch.setattr(kickbase, "get", lambda path: {"it": [{"i": 9001, "prc": 1e6, "exs": 100}]}
                        if path.endswith("/market") else {"it": [{"i": 9002, "mv": 2e6}]})
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("INSERT INTO kb_league_entry (league_id, kb_id, kind, price) VALUES (111, 9003, 'kader', 1)"))
            with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
                assert kickbase.ingest_league(s) == {"markt": 1, "kader": 1}
                s.commit()  # gibt nur den Savepoint frei, die äußere Transaktion rollt am Ende zurück
            rows = conn.execute(text("SELECT league_id, kb_id, kind FROM kb_league_entry ORDER BY kind")).all()
            assert rows == [(222, 9002, "kader"), (222, 9001, "markt")]  # Liga 111 ist weg
        finally:
            trans.rollback()
