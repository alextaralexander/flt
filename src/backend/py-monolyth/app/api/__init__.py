"""Пакет API-приложения."""

from __future__ import annotations

from fastapi import FastAPI


def setup_routers(app: FastAPI) -> None:
    """Подключает router'ы пакета API."""
    _ = app
