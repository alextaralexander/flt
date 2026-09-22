from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase

from py_main_lib.entities.alchemy import BaseEntityModel


class Base(BaseEntityModel, DeclarativeBase, AsyncAttrs):
    """Base model for all models."""
