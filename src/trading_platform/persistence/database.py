from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from trading_platform.persistence.models import Base


class DatabaseManager:
    def __init__(self, database_url: str, echo: bool = False) -> None:
        self._engine = create_engine(database_url, echo=echo)
        self._initialized = False

    def init_db(self) -> None:
        if self._initialized:
            return
        Base.metadata.create_all(self._engine)
        self._initialized = True

    def close(self) -> None:
        self._engine.dispose()
        self._initialized = False

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        session = Session(self._engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def is_initialized(self) -> bool:
        return self._initialized
