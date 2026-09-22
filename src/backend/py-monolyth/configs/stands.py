"""Выбор env-файлов по стенду — единая точка для всех Settings-классов.

Файлы стендов лежат по схеме ``envs/<stand>/[<prefix>_]<stand>.env``
(например ``envs/dev/dev.env``, ``envs/dev/kafka_dev.env``).
"""

import os


KNOWN_STANDS = ("local", "dev", "test", "prod")
DEFAULT_STAND_NAME = "local"


def current_stand() -> str:
    """Имя текущего стенда (`STAND_NAME` из окружения, по умолчанию local).

    Raises:
        RuntimeError: STAND_NAME не входит в список известных стендов.
    """
    stand = os.getenv("STAND_NAME", DEFAULT_STAND_NAME)
    if stand not in KNOWN_STANDS:
        raise RuntimeError(f"Неизвестный STAND_NAME={stand!r}; ожидается один из {KNOWN_STANDS}.")
    return stand


def stand_env_file(prefix: str = "") -> str:
    """Путь к env-файлу текущего стенда: общий (`local.env`) или компонентный (`kafka_local.env`)."""
    stand = current_stand()
    file_name = f"{prefix}_{stand}.env" if prefix else f"{stand}.env"
    return f"envs/{stand}/{file_name}"
