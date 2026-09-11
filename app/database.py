from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

# NullPool is deliberate. Each serverless invocation is a short-lived process;
# a pool held across invocations would leak connections and exhaust Neon's limit.
# Connection reuse is the pooler endpoint's job, not SQLAlchemy's.
engine = create_engine(
    settings.sqlalchemy_url,
    poolclass=NullPool,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
