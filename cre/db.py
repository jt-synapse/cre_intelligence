"""Connection factories for the runtime; migrations use a separate credential."""

import os
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text


@lru_cache
def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def engine() -> Engine:
    return _engine(os.environ["DATABASE_URL"])


def tenant_scope(conn: Connection, org_id: str | UUID) -> None:
    conn.execute(
        text("select set_config('app.org_id', :org, true)"),
        {"org": str(UUID(str(org_id)))},
    )
