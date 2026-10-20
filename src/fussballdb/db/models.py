from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Season(Base):
    __tablename__ = "season"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_year: Mapped[int] = mapped_column(unique=True)
    label: Mapped[str] = mapped_column(String(9))  # "2026/27"


class Team(Base):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)  # Name laut OpenLigaDB
    aliases: Mapped[list["TeamAlias"]] = relationship(back_populates="team")


class TeamAlias(Base):
    """Name eines Teams in einer bestimmten Quelle (football-data, understat, openligadb, kurz)."""

    __tablename__ = "team_alias"
    __table_args__ = (UniqueConstraint("source", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    source: Mapped[str] = mapped_column(String(20))
    alias: Mapped[str] = mapped_column(String(80))
    team: Mapped[Team] = relationship(back_populates="aliases")


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (UniqueConstraint("season_id", "home_team_id", "away_team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    matchday: Mapped[int]
    kickoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    home_goals: Mapped[int | None]
    away_goals: Mapped[int | None]
    ht_home_goals: Mapped[int | None]
    ht_away_goals: Mapped[int | None]
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    openligadb_id: Mapped[int | None] = mapped_column(unique=True)
    understat_id: Mapped[int | None] = mapped_column(unique=True)

    season: Mapped[Season] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class MatchTeamStats(Base):
    """Kennzahlen eines Teams in einem Spiel. Pro Spiel genau zwei Zeilen."""

    __tablename__ = "match_team_stats"

    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), primary_key=True)
    is_home: Mapped[bool]
    goals: Mapped[int | None]
    # Understat
    xg: Mapped[float | None] = mapped_column(Float)
    npxg: Mapped[float | None] = mapped_column(Float)
    xpts: Mapped[float | None] = mapped_column(Float)
    ppda: Mapped[float | None] = mapped_column(Float)  # gegnerische Pässe pro eigener Defensivaktion
    deep: Mapped[int | None]  # Pässe/Läufe bis ~20 m vor das Tor
    big_chances: Mapped[int | None]  # Schüsse mit xG >= 0.3 (aus Understat-Schüssen abgeleitet)
    # football-data.co.uk
    xg_fd: Mapped[float | None] = mapped_column(Float)  # xG laut football-data (erst ab 2026/27)
    shots: Mapped[int | None]
    shots_on_target: Mapped[int | None]
    corners: Mapped[int | None]
    fouls: Mapped[int | None]
    yellow_cards: Mapped[int | None]
    red_cards: Mapped[int | None]
    # aktuell keine frei zugängliche Quelle
    possession: Mapped[float | None] = mapped_column(Float)


class Shot(Base):
    __tablename__ = "shot"

    id: Mapped[int] = mapped_column(primary_key=True)  # Understat-Schuss-ID
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    player: Mapped[str] = mapped_column(String(80))
    player_assisted: Mapped[str | None] = mapped_column(String(80))
    minute: Mapped[int]
    xg: Mapped[float] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(20))  # Goal, SavedShot, MissedShots, BlockedShot, ShotOnPost, OwnGoal
    situation: Mapped[str] = mapped_column(String(20))  # OpenPlay, FromCorner, SetPiece, DirectFreekick, Penalty
    shot_type: Mapped[str] = mapped_column(String(20))
    last_action: Mapped[str | None] = mapped_column(String(30))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)


class Odds(Base):
    __tablename__ = "odds"

    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), primary_key=True)
    bookmaker: Mapped[str] = mapped_column(String(20), primary_key=True)  # B365, Avg, Max, ...
    is_closing: Mapped[bool] = mapped_column(primary_key=True)
    home: Mapped[float | None] = mapped_column(Float)
    draw: Mapped[float | None] = mapped_column(Float)
    away: Mapped[float | None] = mapped_column(Float)
    over25: Mapped[float | None] = mapped_column(Float)
    under25: Mapped[float | None] = mapped_column(Float)


class EloRating(Base):
    """Elo eines Teams vor und nach einem Spiel."""

    __tablename__ = "elo_rating"

    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), primary_key=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elo_before: Mapped[float] = mapped_column(Float)
    elo_after: Mapped[float] = mapped_column(Float)


class Prediction(Base):
    __tablename__ = "prediction"
    __table_args__ = (UniqueConstraint("match_id", "model_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"))
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    exp_home_goals: Mapped[float] = mapped_column(Float)
    exp_away_goals: Mapped[float] = mapped_column(Float)
    p_over25: Mapped[float] = mapped_column(Float)
    p_btts: Mapped[float] = mapped_column(Float)
    # Stand der Daten, auf dem die Prognose beruht (live: Zeitpunkt der Berechnung,
    # rueckblick: Anpfiff des ersten Spiels des Spieltags)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis: Mapped[str | None] = mapped_column(String(12))  # live | rueckblick
    tip_home: Mapped[int | None]
    tip_away: Mapped[int | None]
    missing_home: Mapped[str | None] = mapped_column(String(400))  # angenommene Ausfälle (Stammspieler)
    missing_away: Mapped[str | None] = mapped_column(String(400))
    explanation: Mapped[str | None] = mapped_column(Text)  # JSON-Liste kurzer Sätze (model/explain.py)


class SquadValue(Base):
    """Kaderwert (Transfermarkt) eines Teams zu einem Stichtag (1. eines Monats)."""

    __tablename__ = "squad_value"

    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), primary_key=True)
    stichtag: Mapped[date] = mapped_column(Date, primary_key=True)
    value_eur: Mapped[float] = mapped_column(Float)


class LineupSnapshot(Base):
    """Aufstellung laut Ligainsider zu einem Abrufzeitpunkt. Vor dem Spiel ist es die voraussichtliche
    Aufstellung (status 'vorschau'), danach die tatsächliche (status 'gespielt')."""

    __tablename__ = "lineup_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), index=True)
    match_kickoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))  # vorschau | gespielt
    role: Mapped[str] = mapped_column(String(12))  # start | alternative | bank
    position_row: Mapped[int | None]  # 1 = Tor, 2 = Abwehr, ... (Reihe im Spielfeld)
    player_name: Mapped[str] = mapped_column(String(80))
    ligainsider_id: Mapped[int] = mapped_column()
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id"))


class PlayerInjury(Base):
    """Verletzungshistorie eines Spielers laut Transfermarkt (für den Rückblick-Test der Ausfälle)."""

    __tablename__ = "player_injury"
    __table_args__ = (UniqueConstraint("tm_player_id", "von", "injury"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tm_player_id: Mapped[int] = mapped_column(index=True)
    player_name: Mapped[str] = mapped_column(String(80))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id"), index=True)  # Understat
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))  # Verein zum Zeitpunkt der Verletzung
    injury: Mapped[str] = mapped_column(String(120))
    von: Mapped[date] = mapped_column(Date)
    bis: Mapped[date | None] = mapped_column(Date)  # leer = noch verletzt
    days: Mapped[int | None]
    missed_games: Mapped[int | None]


class UpdateLog(Base):
    """Protokoll der Update-Schritte (fussballdb ensure), damit Schritte nicht ständig wiederholt werden."""

    __tablename__ = "update_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    step: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None]
    reason: Mapped[str | None] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(String(1000))


class KbPlayer(Base):
    """Spieler laut Kickbase (aktueller Stand, täglich aktualisiert)."""

    __tablename__ = "kb_player"

    kb_id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(80))
    kb_team_id: Mapped[int]
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id"), index=True)  # Understat
    position: Mapped[int]  # 1 TW, 2 ABW, 3 MF, 4 ST
    status: Mapped[int | None]  # 0 fit, sonst verletzt/angeschlagen/Aufbau
    market_value: Mapped[float | None] = mapped_column(Float)
    mv_trend: Mapped[int | None]  # 0 gleich, 1 steigt, 2 fällt
    total_points: Mapped[int | None]
    avg_points: Mapped[int | None]
    image: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbPoints(Base):
    """Kickbase-Punkte eines Spielers je Bundesliga-Spiel (aus der Performance-Historie)."""

    __tablename__ = "kb_points"

    kb_id: Mapped[int] = mapped_column(ForeignKey("kb_player.kb_id", ondelete="CASCADE"), primary_key=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("match.id"), index=True)
    season: Mapped[str] = mapped_column(String(9))
    matchday: Mapped[int]
    points: Mapped[int]
    minutes: Mapped[int]


class KbMarketValue(Base):
    __tablename__ = "kb_market_value"

    kb_id: Mapped[int] = mapped_column(ForeignKey("kb_player.kb_id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class KbLeagueEntry(Base):
    """Stand in der eigenen Kickbase-Liga: Spieler auf dem Transfermarkt bzw. im eigenen Kader."""

    __tablename__ = "kb_league_entry"

    league_id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)  # markt | kader
    price: Mapped[float | None] = mapped_column(Float)
    expires_in: Mapped[int | None]  # Sekunden bis Ablauf des Angebots
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Spalten, die nach dem ersten Anlegen dazugekommen sind (create_all ergänzt keine Spalten)
MIGRATIONS = [
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS as_of timestamptz",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS basis varchar(12)",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS tip_home integer",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS tip_away integer",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS missing_home varchar(400)",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS missing_away varchar(400)",
    "ALTER TABLE prediction ADD COLUMN IF NOT EXISTS explanation text",
]


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)  # Understat-Spieler-ID
    name: Mapped[str] = mapped_column(String(80), index=True)


class PlayerMatch(Base):
    """Einsatz eines Spielers in einem Spiel (Understat-Kader). Ergibt die Aufstellungen."""

    __tablename__ = "player_match"

    match_id: Mapped[int] = mapped_column(ForeignKey("match.id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), index=True)
    position: Mapped[str] = mapped_column(String(10))  # GK, DC, AML, FW, Sub ...
    started: Mapped[bool]
    minutes: Mapped[int]
    goals: Mapped[int]
    assists: Mapped[int]
    shots: Mapped[int]
    key_passes: Mapped[int]
    xg: Mapped[float] = mapped_column(Float)
    xa: Mapped[float] = mapped_column(Float)
    xg_chain: Mapped[float] = mapped_column(Float)  # xG aller Angriffe, an denen er beteiligt war
    xg_buildup: Mapped[float] = mapped_column(Float)
    yellow_cards: Mapped[int]
    red_cards: Mapped[int]


class PlayerAbsence(Base):
    """Ausfälle (Verletzung/Krankheit von Transfermarkt, Sperren abgeleitet aus Karten).
    Jeder Abruf ist ein Schnappschuss, ältere Einträge werden auf active=False gesetzt."""

    __tablename__ = "player_absence"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"), index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id"))
    player_name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(12))  # injury | suspension
    reason: Mapped[str | None] = mapped_column(String(120))
    expected_return: Mapped[str | None] = mapped_column(String(40))
    market_value: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active: Mapped[bool] = mapped_column(default=True, index=True)
