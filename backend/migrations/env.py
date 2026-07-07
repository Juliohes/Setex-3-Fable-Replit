"""Entorno Alembic (modo offline/online síncrono vía URL de entorno).

El esquema inicial lo crea `shared.bootstrap.init_db` en el arranque
(AUTO_MIGRATE=1, ADR-0012). A partir de ahí, los cambios de esquema se
gestionan aquí con `alembic revision --autogenerate` + `alembic upgrade head`
usando una DATABASE_URL síncrona (postgresql+psycopg2:// o postgresql://).
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shared.bootstrap import _register_all_models  # noqa: E402
from shared.db import Base  # noqa: E402

_register_all_models()
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
