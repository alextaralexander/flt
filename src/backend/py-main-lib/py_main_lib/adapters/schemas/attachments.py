from typing import Optional

from pydantic import BaseModel, Field


class ImageUrl(BaseModel):
    """URL изображения или s3_key для S3."""

    url: Optional[str] = Field(None, description="URL изображения в формате data:image/jpeg;base64,...")
    s3_key: Optional[str] = Field(None, description="S3 ключ для сгенерированного изображения")


class GeneratedImage(BaseModel):
    """Сгенерированное изображение."""

    type: str = Field(default="image_url", description="Тип изображения")
    image_url: ImageUrl = Field(description="URL сгенерированного изображения")


class TextContent(BaseModel):
    """Текстовое содержимое."""

    type: str = Field(default="text", description="Тип содержимого")
    text: str = Field(description="Текст сообщения")


class ImageContent(BaseModel):
    """Содержимое с изображением."""

    type: str = Field(default="image_url", description="Тип содержимого")
    image_url: ImageUrl = Field(description="URL изображения")
