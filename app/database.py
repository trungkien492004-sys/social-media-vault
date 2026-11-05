from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

def _normalize_db_url(url: str) -> str:
    # Supabase/Heroku style URLs use "postgres://"; SQLAlchemy needs an explicit driver
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url

DATABASE_URL = _normalize_db_url(settings.DATABASE_URL)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from app import models
    Base.metadata.create_all(bind=engine)
    # Lightweight migration: add columns introduced after the first release
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(engine).get_columns("media_items")}
    if "file_url" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE media_items ADD COLUMN file_url VARCHAR(1000)"))
