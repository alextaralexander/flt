"""Права служебных эндпоинтов shared kernel.

Права доменных модулей объявляются в `app/modules/<module>/permissions.py`
(формат `<module>:<resource>:<action>`, SYS-06); скаффолдер добавляет их туда.
"""


class MetricsPermissions:
    """Права на служебные эндпоинты, раскрывающие сведения о сервисе и системе.

    `/health`, `/ready` и `/metrics` намеренно без авторизации — их опрашивают
    probes и Prometheus; `/info` и `/system-metrics` отдают версию сборки и
    состояние хоста, поэтому закрыты permissions.
    """

    GET_SERVICE_INFO = "GET_SERVICE_INFO"
    GET_SYSTEM_METRICS = "GET_SYSTEM_METRICS"
