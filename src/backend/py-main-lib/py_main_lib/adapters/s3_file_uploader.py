"""Uploading helper for temp RAG files in S3."""

import asyncio
import re
import time
import unicodedata
import uuid
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from py_main_lib.colored_logger import get_colored_logger


logger = get_colored_logger(__name__)


# Транслитерация кириллицы
_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "А": "A",
    "Б": "B",
    "В": "V",
    "Г": "G",
    "Д": "D",
    "Е": "E",
    "Ё": "Yo",
    "Ж": "Zh",
    "З": "Z",
    "И": "I",
    "Й": "Y",
    "К": "K",
    "Л": "L",
    "М": "M",
    "Н": "N",
    "О": "O",
    "П": "P",
    "Р": "R",
    "С": "S",
    "Т": "T",
    "У": "U",
    "Ф": "F",
    "Х": "H",
    "Ц": "Ts",
    "Ч": "Ch",
    "Ш": "Sh",
    "Щ": "Sch",
    "Ъ": "",
    "Ы": "Y",
    "Ь": "",
    "Э": "E",
    "Ю": "Yu",
    "Я": "Ya",
}


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """
    Санитизация имени файла для S3 ключа.

    - Транслитерирует кириллицу
    - Убирает спецсимволы
    - Заменяет пробелы на _
    - Ограничивает длину
    """
    if not filename:
        return "unknown"

    # Убираем расширение если есть
    name_without_ext = filename.rsplit(".", 1)[0] if "." in filename else filename

    # Транслитерация кириллицы
    result = []
    for char in name_without_ext:
        if char in _CYRILLIC_TO_LATIN:
            result.append(_CYRILLIC_TO_LATIN[char])
        else:
            result.append(char)
    name = "".join(result)

    # Нормализация Unicode
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")

    # Заменяем пробелы и недопустимые символы
    name = re.sub(r"[^\w\-.]", "_", name)
    name = re.sub(r"_+", "_", name)  # Убираем множественные _
    name = name.strip("_")

    # Ограничиваем длину
    if len(name) > max_length:
        name = name[:max_length]

    return name or "unknown"


class S3FileUploader:
    """Асинхронный загрузчик файлов в S3 с простой retry логикой."""

    def __init__(
        self,
        bucket_name: str,
        temp_prefix: str = "temp-files/rag-indexer/",
        retry_attempts: int = 3,
        client_params: dict[str, Any] | None = None,
        session: aioboto3.Session | None = None,
    ):
        if not bucket_name:
            raise ValueError("bucket_name is required for S3 uploads")

        self.bucket_name = bucket_name
        self.temp_prefix = self._normalize_prefix(temp_prefix)
        self.retry_attempts = max(1, retry_attempts)
        self.client_params = client_params or {}
        self._session = session or aioboto3.Session()
        self._bucket_ensured = False

    async def _ensure_bucket_exists(self) -> None:
        """Создаёт bucket если он не существует (вызывается один раз)."""
        if self._bucket_ensured:
            return

        try:
            async with self._session.client("s3", **self.client_params) as client:
                try:
                    await client.head_bucket(Bucket=self.bucket_name)
                    logger.info(f"Bucket '{self.bucket_name}' exists")
                except ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code", "")
                    if error_code in ("404", "NoSuchBucket"):
                        await client.create_bucket(Bucket=self.bucket_name)
                        logger.info(f"Created bucket '{self.bucket_name}'")
                    else:
                        raise
            self._bucket_ensured = True
        except Exception as exc:
            logger.warning(f"Could not ensure bucket exists: {exc}")

    def generate_temp_key(
        self,
        source_id: str,
        extension: str = "txt",
        original_filename: str | None = None,
    ) -> str:
        """Генерирует уникальный S3 ключ с изоляцией по source_id."""
        safe_source = (source_id or "unknown").replace("/", "_").replace("\\", "_")
        normalized_extension = extension.lstrip(".") or "txt"

        short_uuid = uuid.uuid4().hex[:8]

        if original_filename:
            # Санитизируем оригинальное имя
            safe_name = sanitize_filename(original_filename, max_length=80)
            filename = f"{safe_name}_{short_uuid}.{normalized_extension}"
        else:
            # Fallback на старое поведение
            filename = f"file_{uuid.uuid4()}.{normalized_extension}"

        return f"{self.temp_prefix}source_{safe_source}/{filename}"

    async def upload_text_file(
        self,
        s3_key: str,
        content: str,
        content_type: str = "text/plain; charset=utf-8",
        encoding: str = "utf-8",
    ) -> str:
        """Загрузка текстового файла по готовому ключу."""
        return await self._put_object(
            s3_key=self._normalize_key(s3_key),
            body=content.encode(encoding),
            content_type=content_type,
        )

    async def upload_binary_file(self, s3_key: str, content: bytes, content_type: str) -> str:
        """Загрузка бинарного файла по готовому ключу."""
        return await self._put_object(
            s3_key=self._normalize_key(s3_key),
            body=content,
            content_type=content_type,
        )

    async def _put_object(self, s3_key: str, body: bytes, content_type: str) -> str:
        """Базовый put_object с экспоненциальным backoff."""
        await self._ensure_bucket_exists()

        attempt = 0
        delay = 1.0
        last_error: Exception | None = None

        while attempt < self.retry_attempts:
            attempt += 1
            start_time = time.perf_counter()
            try:
                async with self._session.client("s3", **self.client_params) as client:
                    await client.put_object(
                        Bucket=self.bucket_name,
                        Key=s3_key,
                        Body=body,
                        ContentType=content_type,
                    )

                elapsed = time.perf_counter() - start_time
                logger.info(
                    f"Uploaded to s3://{self.bucket_name}/{s3_key} "
                    f"({len(body)} bytes) in {elapsed:.3f}s (attempt {attempt})"
                )
                return s3_key

            except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
                last_error = exc
                logger.warning(
                    f"S3 upload attempt {attempt}/{self.retry_attempts} failed for "
                    f"{s3_key}: {type(exc).__name__}: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.error(
                    f"Unexpected error uploading {s3_key} on attempt "
                    f"{attempt}/{self.retry_attempts}: {type(exc).__name__}: {exc}"
                )

            if attempt < self.retry_attempts:
                await asyncio.sleep(delay)
                delay *= 2

        raise RuntimeError(f"Failed to upload {s3_key} after {self.retry_attempts} attempts") from last_error

    async def delete_temp_file(self, s3_key: str) -> bool:
        """Удаляет временный файл из S3 с retry логикой."""
        normalized_key = self._normalize_key(s3_key)
        attempt = 0
        delay = 1.0
        last_error: Exception | None = None

        while attempt < self.retry_attempts:
            attempt += 1
            start_time = time.perf_counter()
            try:
                async with self._session.client("s3", **self.client_params) as client:
                    await client.delete_object(Bucket=self.bucket_name, Key=normalized_key)

                elapsed = time.perf_counter() - start_time
                logger.info(
                    f"Deleted temp file s3://{self.bucket_name}/{normalized_key} "
                    f"in {elapsed:.3f}s (attempt {attempt})"
                )
                return True

            except (ClientError, EndpointConnectionError, BotoCoreError) as exc:
                last_error = exc
                logger.warning(
                    f"S3 delete attempt {attempt}/{self.retry_attempts} failed for "
                    f"{normalized_key}: {type(exc).__name__}: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.error(
                    f"Unexpected error deleting {normalized_key} on attempt "
                    f"{attempt}/{self.retry_attempts}: {type(exc).__name__}: {exc}"
                )

            if attempt < self.retry_attempts:
                await asyncio.sleep(delay)
                delay *= 2

        logger.error(
            f"Failed to delete temp file s3://{self.bucket_name}/{normalized_key} "
            f"after {self.retry_attempts} attempts: {last_error}"
        )
        return False

    async def delete_multiple_files(self, s3_keys: list[str]) -> tuple[int, int]:
        """
        Удаляет несколько файлов из S3.

        Returns:
            Tuple[успешно удалено, не удалось удалить]
        """
        if not s3_keys:
            return 0, 0

        success_count = 0
        fail_count = 0

        for s3_key in s3_keys:
            if await self.delete_temp_file(s3_key):
                success_count += 1
            else:
                fail_count += 1

        logger.info(
            f"Batch delete completed: {success_count} deleted, {fail_count} failed " f"out of {len(s3_keys)} total"
        )
        return success_count, fail_count

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        normalized = prefix.lstrip("/")
        if normalized and not normalized.endswith("/"):
            normalized += "/"
        return normalized

    @staticmethod
    def _normalize_key(s3_key: str) -> str:
        return s3_key.lstrip("/")
