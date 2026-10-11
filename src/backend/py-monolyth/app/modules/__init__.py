"""Доменные модули монолита: пакет `app/modules/<module>/` с подпакетом `public/` (ADR-002).

Другие модули импортируют только `app.modules.<module>.public`; состав модулей — `registry.py`.
"""
