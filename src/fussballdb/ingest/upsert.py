from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

BATCH = 1000


def upsert(session: Session, model, rows: list[dict], keys: list[str]) -> None:
    """INSERT ... ON CONFLICT DO UPDATE in Batches. Ein None in den neuen Daten
    überschreibt keinen vorhandenen Wert (COALESCE), so ergänzen sich die Quellen."""
    if not rows:
        return
    table = model.__table__
    columns = sorted({k for row in rows for k in row})
    rows = [{c: row.get(c) for c in columns} for row in rows]
    for start in range(0, len(rows), BATCH):
        stmt = insert(table).values(rows[start : start + BATCH])
        update_cols = {
            c: func.coalesce(stmt.excluded[c], table.c[c]) for c in columns if c not in keys
        }
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=keys, set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=keys)
        session.execute(stmt)
