from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.config import settings

db_url = settings.get_database_url()
connect_args = {}
engine_kwargs = {"pool_pre_ping": True}

if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    if ":memory:" in db_url or db_url.endswith("sqlite://"):
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(db_url, connect_args=connect_args, **engine_kwargs)


if db_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def ensure_sqlite_columns(bind=None) -> None:
    """Additive SQLite columns. Safe to run on every startup."""
    target = bind or engine
    url = str(target.url)
    if not url.startswith("sqlite"):
        return
    statements = (
        ("event", "official_source_name", "VARCHAR"),
        ("event", "mentioned_entities", "JSON"),
        ("article", "publisher_name", "VARCHAR"),
    )
    with target.begin() as conn:
        for table, column, coltype in statements:
            info = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            names = {row[1] for row in info}
            if info and column not in names:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
