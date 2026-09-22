from typing import List

from pydantic import UUID4, BaseModel, Field
from typing_extensions import Any, Self


class MsAuthCheckTokenResponseSchema(BaseModel):
    """Response ms-auth на `/auth/oauth/check_token`."""

    user_name: str
    USER_ID: UUID4
    active: bool
    FIRSTNAME: str
    CN: str
    client_id: str
    MIDDLENAME: str
    ROLES: List[str]
    LASTNAME: str
    USER_TYPE: str
    scope: List[str]
    USERNAME: str
    exp: int
    jti: str
    ACCESS_TOKEN: str


class UserSecuritySchema(BaseModel):
    user_id: str = Field(
        description="ID пользователя в UUID формате.",
    )
    permissions: set[str] = Field(
        description="Набор прав пользователя.",
    )
    access_token: str | None = Field(
        default=None,
        description="JWT токен пользователя.",
    )
    roles: List[str] = Field(default_factory=list)

    @classmethod
    def from_response(cls, response: MsAuthCheckTokenResponseSchema) -> Self:
        return cls(
            user_id=str(response.USER_ID),
            permissions=set(),
            access_token=response.ACCESS_TOKEN,
        )

    @classmethod
    def from_token_claims(cls, token_claims: dict[str, Any]) -> Self:
        return cls(
            user_id=token_claims["USER_ID"],
            permissions=set(token_claims["PERMISSIONS"]),
            roles=token_claims["ROLES"],
            access_token=None,
        )


class TokenSettingsRedisSchema(BaseModel):
    """Значение `token_settings` из Redis."""

    name: str
    signKey: str
    _class: str
