"""Сервис для работы с сервисом ms-auth."""

import os
from typing import Any, Callable, Dict, List, Optional, cast

import requests  # type: ignore[import-untyped]

from py_main_lib.exceptions import MsAuthIsNotAvailableError


TokenProvider = Callable[[], str]


class PermissionService:
    """Сервис для работы с ms-auth."""

    def __init__(
        self,
        ms_auth_url: str,
        token_provider: TokenProvider | None = None,
        timeout: float = 10.0,
    ):
        self.ms_auth_url = ms_auth_url.rstrip("/")
        self._token_provider = token_provider
        self._timeout = timeout

    # TODO Егору вынести куда-то токен
    TOKEN_TECH_ACCOUNT = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX25hbWUiOiJUZWNoIiwiVVNFUl9JRCI6IjAwMDAwMDAwLTAwM"
        "DAtMDAwMC0wMDAwLTAwMDAwMDAwMDAwMCIsIkZJUlNUTkFNRSI6IlRlY2giLCJDTiI6IlRlY2giLCJjbGllbnRfaWQiOiJ"
        "jbGllbnQiLCJNSURETEVOQU1FIjoiVGVjaCIsIlJPTEVTIjpbIlRFQ0hOSUNBTF9ST0xFIl0sIkxBU1ROQU1FIjoiVGV"
        "jaCIsIlVTRVJfVFlQRSI6IlRFQ0hOSUNBTCIsInNjb3BlIjpbInJlYWQiLCJ3cml0ZSJdLCJVU0VSTkFNRSI6IlRlY2g"
        "iLCJQRVJNSVNTSU9OUyI6WyJURUNIX0FDQ0VTUyJdLCJleHAiOjM3NDYxNDcwOTAsImp0aSI6InVFNkNncmFwRWV1WGt"
        "RRXNZVXkzZ1ZUenhNUSJ9.O6qeOvT9-hRUXf57lc7Usq9f_iQqgFBScDvm1z95y_E"
    )  # nosec B105

    def _resolve_token(self, token: Optional[str]) -> str:
        if token:
            return token
        if self._token_provider is not None:
            resolved = self._token_provider()
            if resolved:
                return resolved
        env_token = os.getenv("MS_AUTH_TECH_TOKEN")
        if env_token:
            return env_token
        return self.TOKEN_TECH_ACCOUNT

    def _auth_headers(self, token: Optional[str]) -> Dict[str, str]:
        resolved_token = self._resolve_token(token)
        return {"Authorization": f"Bearer {resolved_token}"}

    def create_permission(self, permission: str, description: str, token: Optional[str], role: List[str]) -> bool:
        """Создает новое разрешение в ms_auth сервисе и возвращает его ID."""
        url = f"{self.ms_auth_url}/auth/permission/create-with-roles"
        response = requests.post(
            url,
            headers=self._auth_headers(token),
            json={
                "permission": {"name": permission, "description": description},
                "roleNames": role,
            },
            timeout=self._timeout,
        )
        if response.status_code == 200:
            return True
        raise MsAuthIsNotAvailableError(url, "POST")

    def get_permission_by_id(self, permission: str, token: Optional[str]) -> str:
        """Получает ID разрешения по имени из ms_auth сервиса."""
        url = f"{self.ms_auth_url}/auth/permission/filter"
        response = requests.post(
            url,
            headers=self._auth_headers(token),
            json={"filter": {"name": [permission]}, "sort": []},
            timeout=self._timeout,
        )
        data_response = cast(Dict[str, Any], response.json())
        if response.status_code == 200 and data_response.get("result"):
            result = data_response["result"][0]
            permission_id = result.get("id")
            if isinstance(permission_id, str):
                return permission_id
        raise MsAuthIsNotAvailableError(url, "POST")

    def update_permission(self, permission_id: str, permission: str, description: str, token: Optional[str]) -> bool:
        """Обновляет разрешение в ms_auth сервисе."""
        url = f"{self.ms_auth_url}/auth/permission"
        response = requests.put(
            url,
            headers=self._auth_headers(token),
            json={
                "id": permission_id,
                "name": permission,
                "description": description,
            },
            timeout=self._timeout,
        )
        if response.status_code == 200:
            return True
        raise MsAuthIsNotAvailableError(url, "PUT")

    def delete_permission_by_name(self, permission: str, token: Optional[str]) -> bool:
        """Удаляет разрешение по имени из ms_auth сервиса."""
        url = f"{self.ms_auth_url}/auth/permission/delete-by-name"
        response = requests.delete(
            url,
            headers=self._auth_headers(token),
            json={"name": permission},
            timeout=self._timeout,
        )

        if response.status_code != 200:
            raise MsAuthIsNotAvailableError(url, "DELETE")

        return True
