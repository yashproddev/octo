import os
import sys
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    return create_engine(settings.sqlalchemy_direct_url)


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    Tests run against the real Neon database, so nothing may be left behind.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
