from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transaction_context(session: AsyncSession):
    try:
        yield
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e
