import httpx as httpx
from fastapi import HTTPException

from py_main_lib.security.schemas import UserSecuritySchema


async def check_user(token: str, ms_auth_url: str) -> UserSecuritySchema:
    async with httpx.AsyncClient(timeout=7) as client:
        response = await client.post(f"{ms_auth_url}/auth/oauth/check_token", params={"token": token}, timeout=7)
        if response.status_code != 200:
            raise HTTPException(status_code=403, detail="У вас нет доступа к данной операции")
        user = UserSecuritySchema.from_token_claims(response.json())
    return user
