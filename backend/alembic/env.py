from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from config import DATABASE_URL
from apps.database import Base

# ✅ IMPORTAR TODOS LOS MODELOS (ESTO FALTABA)
from apps.models.user import User
from apps.models.oauth_connection import OAuthConnection
from apps.models.conversation import Conversation
from apps.models.message import Message
from apps.models.agent_action import AgentAction
from apps.models.email_verification import EmailVerification
from apps.models.context_file import ContextFile
from apps.models.subscription import Subscription, UsageLimits

# this is the Alembic Config object
config = context.config

# Configurar URL desde .env
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ Ahora Base.metadata tiene todos los modelos
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()