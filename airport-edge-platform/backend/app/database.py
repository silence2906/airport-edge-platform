"""SQLAlchemy engine, session lifecycle, and small compatibility migrations."""

from collections.abc import Generator

from sqlalchemy import JSON, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    """Common declarative base for the platform's persisted data models."""

    pass


# SQLite needs cross-thread connections for FastAPI's sync database dependencies.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def migrate_schema() -> None:
    """Add newer security-rule fields to an existing database without data loss."""

    if "security_rules" not in inspect(engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(engine).get_columns("security_rules")}
    with engine.begin() as connection:
        if "rule_type" not in columns:
            connection.execute(text(
                "ALTER TABLE security_rules ADD COLUMN rule_type VARCHAR(40) NOT NULL DEFAULT 'OBJECT'"
            ))
        if "conditions" not in columns:
            json_type = JSON().compile(dialect=engine.dialect)
            connection.execute(text(
                f"ALTER TABLE security_rules ADD COLUMN conditions {json_type}"
            ))


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped database session and always close it afterward."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
