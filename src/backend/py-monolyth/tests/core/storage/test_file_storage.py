"""`FileStorage` против контейнера MinIO: presigned POST и GET, HEAD, удаление, бакеты (ADR-007; SYS-10-R23)."""

from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import MetaData

from app.core.modules import ModuleDefinition
from app.core.storage.file_storage import (
    FileStorage,
    ForbiddenContentTypeError,
    bucket_name,
    public_read_policy,
)
from app.core.storage.init import init_storage, module_buckets
from app.core.storage.models import FileStatus, object_key
from configs.storage_config import storage_settings


pytestmark = [pytest.mark.no_db, pytest.mark.req("SYS-10-R23")]

BUCKET = "flt-pytest-storage"


@pytest.fixture
async def storage() -> AsyncIterator[tuple[FileStorage, str]]:
    """Клиент, бакет теста и префикс; объекты префикса удаляются после теста (`storage_clean`)."""
    client = FileStorage(storage_settings())
    await client.ensure_buckets([BUCKET])
    prefix = f"u/{uuid4()}/"
    yield client, prefix
    await client.delete_prefix(BUCKET, prefix)


async def _upload(storage: FileStorage, key: str, body: bytes, content_type: str = "text/plain") -> httpx.Response:
    """Загрузка по presigned POST, как это делает браузер."""
    post = await storage.create_upload(BUCKET, key, content_type=content_type, max_bytes=1024)
    async with httpx.AsyncClient() as http:
        return await http.post(post.url, data=post.fields, files={"file": ("f", body, content_type)})


async def test_presigned_post_upload_head_and_download(storage: tuple[FileStorage, str]) -> None:
    """Объект загружается по presigned POST, виден в HEAD и скачивается по presigned GET как attachment."""
    # - Arrange -
    client, prefix = storage
    key = f"{prefix}{uuid4()}.txt"

    # - Act -
    uploaded = await _upload(client, key, b"hello")
    info = await client.head(BUCKET, key)
    url = await client.presign_download(BUCKET, key, filename="notes.txt")
    async with httpx.AsyncClient() as http:
        downloaded = await http.get(url)

    # - Assert -
    assert uploaded.status_code == 204, uploaded.text
    assert info is not None
    assert (info.size, info.content_type) == (5, "text/plain")
    assert downloaded.content == b"hello"
    assert downloaded.headers["content-disposition"].startswith("attachment")


async def test_upload_over_max_bytes_is_rejected(storage: tuple[FileStorage, str]) -> None:
    """Хранилище отклоняет загрузку больше `max_bytes`; объект не появляется."""
    # - Arrange -
    client, prefix = storage
    key = f"{prefix}{uuid4()}.bin"

    # - Act -
    response = await _upload(client, key, b"x" * 2048, "application/octet-stream")

    # - Assert -
    assert response.status_code == 400
    assert await client.head(BUCKET, key) is None


async def test_delete_prefix_removes_user_objects(storage: tuple[FileStorage, str]) -> None:
    """`delete_prefix` удаляет все объекты пользователя (152-ФЗ)."""
    # - Arrange -
    client, prefix = storage
    keys = [f"{prefix}{uuid4()}.txt" for _ in range(3)]
    for key in keys:
        await _upload(client, key, b"data")

    # - Act -
    deleted = await client.delete_prefix(BUCKET, prefix)

    # - Assert -
    assert deleted == 3
    assert [await client.head(BUCKET, key) for key in keys] == [None, None, None]


async def test_forbidden_content_type_is_refused(storage: tuple[FileStorage, str]) -> None:
    """HTML и SVG не загружаются никогда (ADR-007, раздел 3.7)."""
    # - Arrange -
    client, prefix = storage

    # - Act / Assert -
    with pytest.raises(ForbiddenContentTypeError):
        await client.create_upload(BUCKET, f"{prefix}x.svg", content_type="image/svg+xml", max_bytes=10)


async def test_presigned_url_uses_public_base_and_path_style() -> None:
    """Подпись строится для публичного адреса и пути `/<bucket>/<key>` (HAProxy не переписывает путь)."""
    # - Arrange -
    settings = storage_settings().model_copy(update={"S3_PUBLIC_BASE_URL": "http://flt.localhost"})
    client = FileStorage(settings)

    # - Act -
    url = await client.presign_download("flt-materials", "u/1/2.pdf", inline=True, content_type="application/pdf")

    # - Assert -
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("http", "flt.localhost", "/flt-materials/u/1/2.pdf")
    assert "X-Amz-Signature" in parse_qs(parts.query)
    assert "response-content-disposition" not in parse_qs(parts.query)


def test_public_url_only_for_cms_public_prefix() -> None:
    """Постоянный URL — только у `flt-cms/public/*`."""
    # - Arrange -
    client = FileStorage(storage_settings())

    # - Act / Assert -
    assert client.public_url("flt-cms", "public/a.png").endswith("/flt-cms/public/a.png")
    with pytest.raises(ValueError, match="flt-cms"):
        client.public_url("flt-materials", "public/a.png")
    assert public_read_policy("flt-cms")["Statement"][0]["Resource"] == ["arn:aws:s3:::flt-cms/public/*"]


async def test_init_storage_creates_buckets_of_storage_modules() -> None:
    """`storage-init` создаёт бакеты только модулям с `storage=True`, повторно — ничего (идемпотентно)."""
    # - Arrange -
    modules = [
        ModuleDefinition(name="pytest_files", metadata=MetaData(schema="pytest_files"), storage=True),
        ModuleDefinition(name="pytest_plain", metadata=MetaData(schema="pytest_plain")),
    ]

    # - Act -
    await init_storage(modules)
    again = await init_storage(modules)

    # - Assert -
    assert module_buckets(modules) == ["flt-pytest-files"]
    assert again == []
    assert bucket_name("pytest_files") == "flt-pytest-files"


def test_object_key_and_statuses() -> None:
    """Ключ объекта пользователя — под `u/<owner_user_id>/`; статусы жизненного цикла файла."""
    # - Arrange -
    owner, file_id = uuid4(), uuid4()

    # - Act / Assert -
    assert object_key(owner, file_id, ".pdf") == f"u/{owner}/{file_id}.pdf"
    assert object_key(None, file_id) == f"public/{file_id}"
    assert [status.value for status in FileStatus] == ["pending", "uploaded", "processing", "ready", "deleted"]
