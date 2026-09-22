"""Продовый запуск: миграции (опционально) + uvicorn. Точка входа Docker-образа."""

import uvicorn
from alembic import command
from alembic.config import Config

from app.core.logging import logger_settings
from configs.settings import settings


if __name__ == "__main__":
    logger_settings.setup_logging()

    # В многорепличном деплое миграции выполняются отдельным шагом
    # (job/init-container: `alembic upgrade head`) с MIGRATE_ON_START=false.
    if settings.MIGRATE_ON_START:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_uri)
        command.upgrade(alembic_cfg, "head")

    uvicorn.run(
        "app.main:app",
        host=settings.FAST_API_HOST,
        port=settings.FAST_API_PORT,
        log_config=None,
    )
