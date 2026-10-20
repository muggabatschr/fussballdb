from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fussballdb.config import DATABASE_URL

# Zeiten in deutscher Ortszeit ausliefern (API/Chat lesen sie sonst als UTC)
engine = create_engine(DATABASE_URL, future=True, connect_args={"options": "-c timezone=Europe/Berlin"})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
