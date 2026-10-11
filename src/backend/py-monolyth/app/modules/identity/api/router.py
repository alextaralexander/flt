"""REST-роутер модуля `identity`: префикс `/api/v1/identity` (ADR-004, SYS-03)."""

from fastapi import APIRouter


router = APIRouter(prefix="/api/v1/identity", tags=["identity"])

# Роутеры ресурсов подключает `make scaffold-entity module=identity name=<Entity>` (ниже).
