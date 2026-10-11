"""Инстанс не хранит состояние в памяти процесса; Redis и Kafka — только через обёртки shared kernel.

SYS-05-R1, R2, R11, R14; ADR-002 §3.6 (`test_redis_keys_are_namespaced`, `test_no_direct_broker_publish`);
ADR-003 (правило 5: кэш в памяти — только для неизменяемой конфигурации); ADR-004 (публикация через outbox).
"""

import tomllib
from pathlib import Path

import pytest

from tests.architecture import checks


pytestmark = pytest.mark.no_db

ALLOWLIST_PATH = Path(__file__).with_name("process_state_allowlist.toml")


def _allowlist() -> dict[str, list[dict[str, str]]]:
    """Содержимое `process_state_allowlist.toml`."""
    return tomllib.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def _allowed_functions() -> set[str]:
    """Функции, которым разрешён кэш `functools` (SYS-05, раздел 6)."""
    return {entry["name"] for entry in _allowlist()["functools_cache"]}


def _allowed_state() -> set[tuple[str, str]]:
    """Пары (файл, имя), которым разрешено изменяемое состояние уровня модуля (SYS-05, раздел 6)."""
    return {(entry["file"], entry["name"]) for entry in _allowlist()["module_state"]}


def _write(root: Path, rel: str, source: str) -> None:
    """Пишет синтетический файл в дерево `root`."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.fixture
def rogue_tree(tmp_path: Path) -> Path:
    """Минимальное дерево с модулем `rogue` и нарушениями хранения состояния."""
    _write(tmp_path, "app/modules/rogue/__init__.py", "")
    _write(
        tmp_path,
        "app/modules/rogue/services/cache.py",
        "import collections\n"
        "import functools as ft\n"
        "from functools import lru_cache\n"
        "from typing import Final\n\n"
        "from async_lru import alru_cache\n\n"
        "SEEN = {}\n"
        "QUEUE = collections.deque()\n"
        "LIMITS: Final = {'a': 1}\n"
        "COUNTER = 0\n"
        "NAMES = ('a',)\n\n\n"
        "@lru_cache(maxsize=128)\n"
        "def load(user_id): ...\n\n\n"
        "class Repo:\n"
        "    @ft.cached_property\n"
        "    def items(self): ...\n\n"
        "    @alru_cache\n"
        "    async def fetch(self): ...\n\n\n"
        "def touch(redis, broker, kafka_router):\n"
        "    global COUNTER\n"
        "    COUNTER += 1\n"
        "    redis.keys('*')\n"
        "    redis.scan_iter(match='*')\n"
        "    broker.publish({}, 'flt.rogue.x.v1')\n"
        "    kafka_router.broker\n"
        "    kafka_router.publisher('flt.rogue.x.v1')\n",
    )
    _write(
        tmp_path,
        "app/modules/rogue/dao/redis.py",
        "from app.core.dao.caching.module_redis import ModuleRedis\n\n"
        "OWN = ModuleRedis(prefix='rogue')\n"
        "FOREIGN = ModuleRedis('identity')\n"
        "DYNAMIC = ModuleRedis(prefix=__name__)\n",
    )
    _write(
        tmp_path,
        "app/core/settings_cache.py",
        "from functools import cache\n\n\n@cache\ndef get_settings(): ...\n\n\n@cache\ndef read_users(): ...\n",
    )
    _write(tmp_path, "app/core/dao/caching/module_redis.py", "def scan(redis):\n    return redis.scan_iter()\n")
    return tmp_path


@pytest.mark.req("SYS-05-R2")
class TestNoFunctoolsCacheOnData:
    """`lru_cache`, `cache`, `cached_property`, `alru_cache`: в модулях запрещены, в ядре — только по allowlist."""

    def test_current_tree(self) -> None:
        """Текущее дерево (с allowlist SYS-05, раздел 6)."""
        assert checks.functools_cache_violations(checks.SERVICE_ROOT, _allowed_functions()) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированные скаффолдером модули."""
        assert checks.functools_cache_violations(sample_tree, _allowed_functions()) == []

    def test_violations_are_reported(self, rogue_tree: Path) -> None:
        """Прямой импорт, псевдоним `functools` и `async_lru` обнаруживаются; allowlist ядра действует."""
        violations = checks.functools_cache_violations(rogue_tree, {"app.core.settings_cache.get_settings"})

        assert violations == [
            "app/core/settings_cache.py:9: @functools.cache на app.core.settings_cache.read_users",
            "app/modules/rogue/services/cache.py:16: @functools.lru_cache на app.modules.rogue.services.cache.load",
            "app/modules/rogue/services/cache.py:21: @functools.cached_property на "
            "app.modules.rogue.services.cache.Repo.items",
            "app/modules/rogue/services/cache.py:24: @async_lru.alru_cache на "
            "app.modules.rogue.services.cache.Repo.fetch",
        ]


@pytest.mark.req("SYS-05-R1")
class TestNoModuleLevelMutableState:
    """Нет изменяемых объектов уровня модуля, которые меняются после старта процесса."""

    def test_current_tree(self) -> None:
        """Текущее дерево (с allowlist SYS-05, раздел 6)."""
        assert checks.module_state_violations(checks.SERVICE_ROOT, _allowed_state()) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированные скаффолдером модули."""
        assert checks.module_state_violations(sample_tree, _allowed_state()) == []

    def test_violations_are_reported(self, rogue_tree: Path) -> None:
        """Пустой контейнер, `deque()` и `global` обнаруживаются; `Final` и неизменяемые значения — нет."""
        violations = checks.module_state_violations(rogue_tree)

        assert violations == [
            "app/modules/rogue/services/cache.py:11: COUNTER — изменяется в функциях файла",
            "app/modules/rogue/services/cache.py:9: QUEUE — изменяемый контейнер уровня модуля",
            "app/modules/rogue/services/cache.py:8: SEEN — изменяемый контейнер уровня модуля",
        ]


@pytest.mark.req("SYS-05-R1")
@pytest.mark.req("SYS-05-R2")
def test_allowlist_entries_exist() -> None:
    """Каждая запись allowlist ссылается на существующую функцию или имя уровня модуля."""
    # - Arrange -
    functions = checks.function_names(checks.SERVICE_ROOT)
    state_names = checks.module_state_names(checks.SERVICE_ROOT)

    # - Act -
    dangling = sorted(_allowed_functions() - functions) + sorted(map(str, _allowed_state() - state_names))

    # - Assert -
    assert dangling == []


@pytest.mark.req("SYS-05-R14")
class TestNoKeysOrUnscopedScan:
    """Команды `KEYS`, `SCAN`, `FLUSHDB`, `FLUSHALL` — только в `ModuleRedis` (`scan_module_keys`)."""

    def test_current_tree(self) -> None:
        """Текущее дерево."""
        assert checks.redis_command_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированные скаффолдером модули."""
        assert checks.redis_command_violations(sample_tree) == []

    def test_violations_are_reported(self, rogue_tree: Path) -> None:
        """Вызовы `.keys()` и `.scan_iter()` в модуле обнаруживаются, в `module_redis.py` — разрешены."""
        assert checks.redis_command_violations(rogue_tree) == [
            "app/modules/rogue/services/cache.py:30: вызов .keys()",
            "app/modules/rogue/services/cache.py:31: вызов .scan_iter()",
        ]


@pytest.mark.req("SYS-05-R11")
class TestRedisKeysAreNamespaced:
    """`ModuleRedis(prefix=...)` в модуле создаётся с префиксом — именем пакета модуля."""

    def test_current_tree(self) -> None:
        """Текущее дерево."""
        assert checks.module_redis_prefix_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированные скаффолдером модули."""
        assert checks.module_redis_prefix_violations(sample_tree) == []

    def test_violations_are_reported(self, rogue_tree: Path) -> None:
        """Чужой и вычисляемый префикс обнаруживаются."""
        assert checks.module_redis_prefix_violations(rogue_tree) == [
            "app/modules/rogue/dao/redis.py:4: ModuleRedis(prefix='identity'), ожидается 'rogue'",
            "app/modules/rogue/dao/redis.py:5: ModuleRedis(prefix=__name__), ожидается 'rogue'",
        ]


@pytest.mark.req("SYS-04-R24")
class TestNoDirectBrokerPublish:
    """В модулях нет `broker.publish`, `<router>.publisher` и доступа к `.broker` — только `OutboxPublisher`."""

    def test_current_tree(self) -> None:
        """Текущее дерево."""
        assert checks.broker_publish_violations(checks.SERVICE_ROOT) == []

    def test_sample_tree(self, sample_tree: Path) -> None:
        """Сгенерированный скаффолдером Kafka-консьюмер."""
        assert checks.broker_publish_violations(sample_tree) == []

    def test_violations_are_reported(self, rogue_tree: Path) -> None:
        """Публикация через брокер, роутер и `router.broker` обнаруживается."""
        assert checks.broker_publish_violations(rogue_tree) == [
            "app/modules/rogue/services/cache.py:32: broker.publish",
            "app/modules/rogue/services/cache.py:33: kafka_router.broker",
            "app/modules/rogue/services/cache.py:34: kafka_router.publisher",
        ]
