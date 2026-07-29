"""Alembic environment. Resolves DATABASE_URL at runtime and targets our models."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.base import Base
from db.session import database_url
import db.models  # noqa: F401  (import registers all models on Base.metadata)
import db.voice_models  # noqa: F401  (Voice City models)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the real URL (from DATABASE_URL) into the Alembic config.
config.set_main_option("sqlalchemy.url", database_url())

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render our custom GUID type as ``db.base.GUID`` in generated migrations.

    GUID maps to native UUID on PostgreSQL and String(36) elsewhere. Rendering
    it as a plain String (the old behavior) made child columns varchar while
    parent PKs were uuid, so foreign keys failed to create on Postgres."""
    from db.base import GUID

    if type_ == "type" and isinstance(obj, GUID):
        autogen_context.imports.add("import db.base")
        return "db.base.GUID(length=36)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # needed for SQLite ALTER support
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
