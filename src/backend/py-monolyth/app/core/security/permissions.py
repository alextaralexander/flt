"""Permissions сервиса.

Значения — мнемокоды, которые должны приходить в JWT пользователя: напрямую
в claim `PERMISSIONS` или через роли (claim `ROLES` + маппинг `JWT_ROLE_PERMISSIONS`). Скаффолдер
(`make scaffold-entity`) добавляет сюда класс для каждой новой сущности.
"""


class MyEntityPermissions:
    """Права на операции с сущностью-примером `MyEntity`."""

    GET_MODEL = "GET_MY_ENTITY"
    GET_LIST = "GET_MY_ENTITY_LIST"
    CREATE_MODEL = "CREATE_MY_ENTITY"
    UPDATE_MODEL = "UPDATE_MY_ENTITY"
    DELETE_MODEL = "DELETE_MY_ENTITY"


class MetricsPermissions:
    """Права на служебные эндпоинты, раскрывающие сведения о сервисе и системе.

    `/health`, `/ready` и `/metrics` намеренно без авторизации — их опрашивают
    probes и Prometheus; `/info` и `/system-metrics` отдают версию сборки и
    состояние хоста, поэтому закрыты permissions.
    """

    GET_SERVICE_INFO = "GET_SERVICE_INFO"
    GET_SYSTEM_METRICS = "GET_SYSTEM_METRICS"
