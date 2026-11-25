import os

from alembic import context
from sqlalchemy import create_engine, pool

database_url = os.environ.get("CRE_MIGRATION_URL") or os.environ["DATABASE_URL"]
if context.is_offline_mode():
    context.configure(url=database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(database_url, poolclass=pool.NullPool).connect() as conn:
        context.configure(connection=conn, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
