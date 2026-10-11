"""`FileStorage` поверх `aioboto3`: presigned POST и GET, HEAD, удаление (ADR-007, разделы 3.1, 3.6).

Байты файлов через монолит не проходят: клиент загружает объект по presigned POST и читает
по presigned GET. Подписи строятся клиентом с `endpoint_url = S3_PUBLIC_BASE_URL` и path-style
адресацией — ровно для того хоста и пути `/<bucket>/<key>`, которые MinIO получит через HAProxy
без переписывания; операции самого монолита идут на внутренний `S3_ENDPOINT_URL`.
`aioboto3` и `botocore` импортируются только в этом пакете (import-linter, ADR-002).
"""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from configs.storage_config import StorageSettings


# Типы, которые shared kernel запрещает всегда (ADR-007, раздел 3.7).
FORBIDDEN_CONTENT_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "image/svg+xml", "application/x-msdownload", "application/x-sh"}
)
# Типы, которые браузер показывает inline; остальные отдаются с `Content-Disposition: attachment`.
INLINE_PREFIXES = ("image/", "video/", "audio/", "application/pdf")
PUBLIC_PREFIX = "public/"
PUBLIC_BUCKET = "flt-cms"


class ForbiddenContentTypeError(ValueError):
    """Тип содержимого запрещён shared kernel."""


@dataclass(frozen=True)
class PresignedPost:
    """Presigned POST загрузки: адрес формы и её поля."""

    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ObjectInfo:
    """Метаданные объекта из `HEAD`."""

    size: int
    content_type: str
    etag: str


def bucket_name(module: str) -> str:
    """Бакет модуля: `flt-<module>` (подчёркивания недопустимы в имени бакета → дефисы)."""
    return f"flt-{module.replace('_', '-')}"


class FileStorage:
    """Клиент хранилища: один экземпляр на процесс.

    Attributes:
        settings: Настройки секции `storage`.
    """

    def __init__(self, settings: StorageSettings) -> None:
        """Создаёт сессию `aioboto3` с ключами учётной записи монолита."""
        self.settings = settings
        self._session = aioboto3.Session(
            aws_access_key_id=settings.S3_ACCESS_KEY.get_secret_value(),
            aws_secret_access_key=settings.S3_SECRET_KEY.get_secret_value(),
            region_name=settings.S3_REGION,
        )
        self._config = Config(signature_version="s3v4", s3={"addressing_style": "path"})

    def _client(self, *, public: bool) -> Any:
        """Клиент S3: публичный адрес — для подписей, внутренний — для операций монолита."""
        endpoint = self.settings.S3_PUBLIC_BASE_URL if public else self.settings.S3_ENDPOINT_URL
        return self._session.client("s3", endpoint_url=endpoint, config=self._config)

    async def create_upload(
        self, bucket: str, key: str, *, content_type: str, max_bytes: int, expires_in: int | None = None
    ) -> PresignedPost:
        """Presigned POST с ограничением типа и размера (`content-length-range`).

        Raises:
            ForbiddenContentTypeError: Тип из запрещённого списка.
        """
        if content_type.split(";", 1)[0].strip().lower() in FORBIDDEN_CONTENT_TYPES:
            raise ForbiddenContentTypeError(content_type)
        async with self._client(public=True) as client:
            post = await client.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
                ExpiresIn=expires_in or self.settings.S3_UPLOAD_TTL_SECONDS,
            )
        return PresignedPost(url=post["url"], fields=dict(post["fields"]))

    async def presign_download(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int | None = None,
        filename: str | None = None,
        inline: bool = False,
        content_type: str | None = None,
    ) -> str:
        """Presigned GET; не изображение, видео, аудио или PDF отдаётся как `attachment` (ADR-007, 3.7)."""
        params: dict[str, str] = {"Bucket": bucket, "Key": key}
        show_inline = inline and content_type is not None and content_type.startswith(INLINE_PREFIXES)
        if not show_inline:
            disposition = "attachment"
            if filename:
                disposition += f"; filename*=UTF-8''{quote(filename)}"
            params["ResponseContentDisposition"] = disposition
        async with self._client(public=True) as client:
            url: str = await client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in or self.settings.S3_PRESIGN_TTL_SECONDS
            )
        return url

    def public_url(self, bucket: str, key: str) -> str:
        """Постоянный URL публичного объекта (только `flt-cms/public/*`)."""
        if bucket != PUBLIC_BUCKET or not key.startswith(PUBLIC_PREFIX):
            raise ValueError("Публичные URL есть только у объектов flt-cms/public/* (ADR-007).")
        return f"{self.settings.S3_PUBLIC_BASE_URL.rstrip('/')}/{bucket}/{quote(key)}"

    async def head(self, bucket: str, key: str) -> ObjectInfo | None:
        """Метаданные объекта или None, если объекта нет (подтверждение загрузки)."""
        async with self._client(public=False) as client:
            try:
                response = await client.head_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    return None
                raise
        return ObjectInfo(
            size=int(response["ContentLength"]),
            content_type=str(response.get("ContentType", "")),
            etag=str(response.get("ETag", "")).strip('"'),
        )

    async def delete(self, bucket: str, key: str) -> None:
        """Удаляет объект (отсутствующий объект — не ошибка)."""
        async with self._client(public=False) as client:
            await client.delete_object(Bucket=bucket, Key=key)

    async def delete_prefix(self, bucket: str, prefix: str) -> int:
        """Удаляет все объекты под префиксом (`u/<owner_user_id>/` при удалении аккаунта, 152-ФЗ)."""
        deleted = 0
        async with self._client(public=False) as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if keys:
                    await client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
                    deleted += len(keys)
        return deleted

    async def ensure_buckets(self, buckets: list[str]) -> list[str]:
        """Идемпотентно создаёт бакеты и политику анонимного чтения `flt-cms/public/*`.

        Returns:
            Бакеты, созданные этим вызовом.
        """
        created: list[str] = []
        async with self._client(public=False) as client:
            existing = {item["Name"] for item in (await client.list_buckets()).get("Buckets", [])}
            for bucket in buckets:
                if bucket not in existing:
                    await client.create_bucket(Bucket=bucket)
                    created.append(bucket)
                if bucket == PUBLIC_BUCKET:
                    await client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(public_read_policy(bucket)))
        return created


def public_read_policy(bucket: str) -> dict[str, Any]:
    """Политика: анонимно только `s3:GetObject` на `<bucket>/public/*` (ADR-007, раздел 3.6)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/{PUBLIC_PREFIX}*"],
            }
        ],
    }
