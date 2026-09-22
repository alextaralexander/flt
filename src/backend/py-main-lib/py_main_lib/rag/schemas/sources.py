"""RAG Source Adapter Schemas."""

import fnmatch
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class IndexState(str, Enum):
    """Index state enum."""

    STARTED = "IST_STARTED"
    NOT_INDEX = "IST_NOT_INDEX"
    RUNNING = "IST_RUNNING"
    DONE = "IST_DONE"
    START_FAIL = "IST_START_FAIL"
    FAILED = "IST_FAILED"
    QUEUE = "IST_IN_QUEUE"


class RagDBType(str, Enum):
    """RAG database type enum."""

    milvus = "milvus"
    pg_vector = "pgvector"


class SourceType(str, Enum):
    """Source type enum."""

    S3 = "s3"
    Jira = "jira"
    Confluence = "confluence"
    Archive = "archive"
    Ftp = "ftp"
    Web = "web_source"
    Samba = "samba"


class BaseSettingsSchema(BaseModel):
    """Base settings schema for all sources."""

    chunk_size: int = Field(default=500, description="Size of text chunks", examples=[500])
    chunk_overlap: int = Field(default=200, description="Size of chunk overlap", examples=[200])


class JiraSchema(BaseSettingsSchema):
    """Jira access schema."""

    # Обязательные параметры подключения
    url: str = Field(
        ...,
        description=("URL Jira сервера. Пример: 'https://company.atlassian.net' или 'http://jira.company.com'"),
    )
    project: str = Field(
        ...,
        description="Ключ проекта в Jira. Пример: 'PROJ' или 'DEV'",
    )

    # Настройки аутентификации
    cloud: bool = Field(
        default=False,
        description="Использовать Cloud версию Jira. True = Atlassian Cloud, False = Server/Data Center",
    )
    email: Optional[str] = Field(
        default=None,
        description="Email для Cloud Jira. Пример: 'user@company.com'",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="API токен для Cloud Jira. Создается в настройках аккаунта Atlassian",
    )
    username: Optional[str] = Field(
        default=None,
        description="Имя пользователя для Server Jira. Пример: 'admin'",
    )
    password: Optional[str] = Field(
        default=None,
        description="Пароль для Server Jira",
    )

    # Опциональные параметры
    max_results: int = Field(
        default=50,
        description=("Максимальное количество задач для загрузки. Пример: 500 = загрузить максимум 500 задач"),
    )


class S3Schema(BaseSettingsSchema):
    """S3 access schema."""

    # Обязательные параметры подключения
    aws_access_key_id: str = Field(
        ...,
        description="AWS Access Key ID. Пример: 'minioadmin'",
    )
    aws_secret_access_key: str = Field(
        ...,
        description="AWS Secret Access Key. Пример: 'minioadmin'",
    )
    endpoint_url: str = Field(
        ...,
        description="URL конечной точки S3. Пример: 'http://localhost:9000' или 'https://s3.amazonaws.com'",
    )
    bucket_name: str = Field(
        ...,
        description="Название контейнера (хранилища). Пример: 'documents' или 'my-bucket'",
    )

    # Опциональные параметры подключения
    region_name: str = Field(
        default="us-east-1",
        description="Регион S3. По умолчанию 'us-east-1'",
    )

    # Настройки сканирования файлов
    max_file_size_mb: Optional[int] = Field(
        default=10,
        description="Максимальный размер файла в МБ. Пример: 10 = файлы до 10МБ. None = без ограничений",
    )
    max_files_limit: Optional[int] = Field(
        default=100,
        description=(
            "Максимальное количество файлов для обработки. "
            "Пример: 100 = остановиться после 100 файлов. None = без ограничений"
        ),
    )
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны включения файлов. Пример: ['*.pdf', '*.docx', 'report_*']",
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны исключения файлов. Пример: ['~*'] = игнорировать временные файлы Word",
    )

    @model_validator(mode="after")
    def check_s3_settings(self) -> "S3Schema":
        """Validate required S3 parameters."""
        if not all(
            [
                self.aws_access_key_id,
                self.aws_secret_access_key,
                self.endpoint_url,
                self.bucket_name,
            ]
        ):
            raise ValueError(
                "All required S3 parameters (aws_access_key_id, aws_secret_access_key, "
                "endpoint_url, bucket_name) must be specified."
            )
        return self


class ArchiveSchema(BaseSettingsSchema):
    """Archive schema."""

    s3_download_key: str = Field(description="S3 key для загрузки архива. Пример: 'uploads/archive_20241003.zip'")


class ConfluenceSchema(BaseSettingsSchema):
    """Confluence access schema."""

    # Обязательные параметры подключения
    url: str = Field(
        ...,
        description=(
            "URL Confluence сервера. Пример: 'https://company.atlassian.net' или 'http://confluence.company.com'"
        ),
    )
    space_key: str = Field(
        ...,
        description="Ключ пространства в Confluence. Пример: 'PROJ' или 'DOCS'",
    )

    # Настройки аутентификации
    cloud: bool = Field(
        default=False,
        description=("Использовать Cloud версию Confluence. True = Atlassian Cloud, False = Server/Data Center"),
    )
    email: Optional[str] = Field(
        default=None,
        description="Email для Cloud Confluence. Пример: 'user@company.com'",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="API токен для Cloud Confluence. Создается в настройках аккаунта Atlassian",
    )
    username: Optional[str] = Field(
        default=None,
        description="Имя пользователя для Server Confluence. Пример: 'admin'",
    )
    password: Optional[str] = Field(
        default=None,
        description="Пароль для Server Confluence",
    )

    # Опциональные параметры
    max_results: int = Field(
        default=100,
        description=("Максимальное количество страниц для загрузки. Пример: 500 = загрузить максимум 500 страниц"),
    )
    include_labels: Optional[List[str]] = Field(
        default=None,
        description="Включить только страницы с указанными метками. Пример: ['important', 'docs']",
    )
    exclude_labels: Optional[List[str]] = Field(
        default=None,
        description="Исключить страницы с указанными метками. Пример: ['draft', 'obsolete']",
    )
    include_attachments: bool = Field(default=False, description="Включать вложения в обработку")


class FTPSchema(BaseSettingsSchema):
    """FTP access schema."""

    # Обязательные параметры подключения
    ftp_host: str = Field(
        ...,
        description="Адрес FTP сервера. Пример: 'ftp.example.com'",
    )
    ftp_username: str = Field(
        ...,
        description="Имя пользователя для подключения",
    )
    ftp_password: str = Field(
        ...,
        description="Пароль пользователя",
    )

    # Опциональные параметры подключения
    ftp_port: int = Field(
        default=21,
        description="Порт FTP сервера. По умолчанию 21",
    )
    ftp_directory: str = Field(
        default="/",
        description="Базовая директория на FTP. Пример: '/' или '/documents'",
    )

    # Настройки сканирования файлов
    max_file_size_mb: Optional[int] = Field(
        default=10,
        description="Максимальный размер файла в МБ. Пример: 10 = файлы до 10МБ. None = без ограничений",
    )
    max_depth: Optional[int] = Field(
        default=None,
        description=(
            "Глубина рекурсии по подпапкам. Пример: 1 = только текущая папка, " "3 = до 3 уровней, None = все уровни"
        ),
    )
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны включения файлов. Пример: ['*.pdf', '*.docx', 'report_*']",
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны исключения файлов. Пример: ['~*'] = игнорировать временные файлы Word",
    )
    max_files_limit: Optional[int] = Field(
        default=100,
        description=(
            "Максимальное количество файлов для обработки. "
            "Пример: 100 = остановиться после 100 файлов. None = без ограничений"
        ),
    )


class WebSchema(BaseSettingsSchema):
    """Web scrapper schema."""

    url: str = Field(
        ...,
        description="Базовый URL для сканирования. Пример: 'https://example.com'",
    )
    allowed_domains: Optional[List[str]] = Field(
        default=None,
        description=("Список разрешенных доменов для парсинга. Пример: ['example.com', 'sub.example.com']"),
    )
    max_pages: Optional[int] = Field(
        default=10,
        description="Максимальное количество страниц для сканирования",
    )
    max_depth: Optional[int] = Field(
        default=2,
        description="Максимальная глубина сканирования",
    )
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны URL для включения. Пример: ['*/docs/*', '*/api/*']",
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны URL для исключения. Пример: ['*/admin/*', '*/login/*']",
    )
    follow_external_links: Optional[bool] = Field(
        default=False,
        description="Следовать внешним ссылкам",
    )


class SambaSchema(BaseSettingsSchema):
    """Samba access schema."""

    # Обязательные параметры подключения
    smb_server_ip: str = Field(
        ...,
        description="IP адрес Samba сервера. Пример: '192.168.1.48'",
    )
    smb_share_name: str = Field(
        ...,
        description="Название шары на сервере. Пример: 'documents' или 'shared_folder'",
    )
    smb_username: str = Field(
        ...,
        description="Имя пользователя для подключения",
    )
    smb_password: str = Field(
        ...,
        description="Пароль пользователя",
    )

    # Опциональные параметры подключения
    smb_server_name: Optional[str] = Field(
        default=None,
        description="Имя сервера. Если не указано, используется IP",
    )
    smb_domain: str = Field(
        default="WORKGROUP",
        description="Домен. По умолчанию 'WORKGROUP'",
    )
    smb_port: int = Field(
        default=139,
        description="Порт для подключения. По умолчанию 139",
    )
    smb_base_path: str = Field(
        default="/",
        description="Базовый путь в шаре. Пример: '/' или '/subfolder'",
    )
    smb_use_ntlm_v2: bool = Field(
        default=True,
        description="Использовать NTLM v2 аутентификацию",
    )

    # Настройки сканирования файлов
    max_file_size_mb: Optional[int] = Field(
        default=10,
        description="Максимальный размер файла в МБ. Пример: 10 = файлы до 10МБ. None = без ограничений",
    )
    max_depth: Optional[int] = Field(
        default=None,
        description=(
            "Глубина рекурсии по подпапкам. Пример: 1 = только текущая папка, " "3 = до 3 уровней, None = все уровни"
        ),
    )
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны включения файлов. Пример: ['*.pdf', '*.docx', 'report_*']",
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="Паттерны исключения файлов. Пример: ['~*'] = игнорировать временные файлы Word",
    )
    max_files_limit: Optional[int] = Field(
        default=100,
        description=(
            "Максимальное количество файлов для обработки. "
            "Пример: 100 = остановиться после 100 файлов. None = без ограничений"
        ),
    )

    def should_include_file(self, filename: str) -> bool:
        """Проверяет, должен ли файл быть включен в обработку."""
        # Сначала проверяем паттерны исключения
        if self.exclude_patterns:
            for pattern in self.exclude_patterns:
                if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    return False

        # Затем проверяем паттерны включения
        if self.include_patterns:
            for pattern in self.include_patterns:
                if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    return True
            return False  # Если есть include паттерны, но файл не подходит ни под один

        return True  # Если нет include паттернов, включаем все (кроме исключенных)


class AllSourceSettingsSchema(BaseModel):
    """Объединенная схема, которая может содержать настройки для разных источников."""

    jira: Optional[JiraSchema] = None
    s3: Optional[S3Schema] = None
    archive: Optional[ArchiveSchema] = None
    confluence: Optional[ConfluenceSchema] = None
    ftp: Optional[FTPSchema] = None
    web: Optional[WebSchema] = None
    samba: Optional[SambaSchema] = None
