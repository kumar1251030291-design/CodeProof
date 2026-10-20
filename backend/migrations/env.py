"""Alembic migration environment using the application's engine and metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import JSON
from sqlalchemy.engine import Connection

from app.core.config import settings
from app.core.database import Base, engine
import app.models  # noqa: F401 - register mapped entities with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def compare_server_default(
    migration_context: object,
    inspected_column: object,
    metadata_column: object,
    rendered_inspected_default: str | None,
    metadata_default: object,
    rendered_metadata_default: str | None,
) -> bool | None:
    """Skip JSON default equality checks unsupported by PostgreSQL's JSON type."""
    if isinstance(getattr(metadata_column, "type", None), JSON):
        return False
    return None


def require_database_url() -> str:
    """Ensure offline migrations have a configured database URL."""
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be configured in the repository-root .env")
    return settings.database_url


def run_migrations_offline() -> None:
    """Render migrations without opening a database connection."""
    context.configure(
        url=require_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=compare_server_default,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the existing application engine."""
    if engine is None:
        require_database_url()
        raise RuntimeError("The application database engine is not configured")

    def configure_connection(connection: Connection) -> None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=compare_server_default,
        )

        with context.begin_transaction():
            context.run_migrations()

    with engine.connect() as connection:
        configure_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
