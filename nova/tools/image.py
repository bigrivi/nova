"""
Image tool - read image files and convert to base64.
"""

import base64
import json
import os
from pathlib import Path

from nova.llm import ToolResult
from nova.tools.registry import tool

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _get_image_format(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    format_map = {
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".gif": "gif",
        ".webp": "webp",
        ".bmp": "bmp",
    }
    return format_map.get(ext, "png")


@tool(
    name="read_image",
    description="Read an image file and convert it to binary data for vision model analysis. Supports common image formats: PNG, JPG, GIF, WebP, BMP.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The absolute or relative path to the image file",
            },
        },
        "required": ["file_path"],
    },
)
async def read_image(file_path: str) -> ToolResult:
    p = Path(file_path).expanduser()

    if not p.exists():
        return ToolResult(success=False, content=f"File not found: {file_path}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        supported = ", ".join(SUPPORTED_FORMATS)
        return ToolResult(
            success=False,
            content=f"Unsupported image format: {ext}. Supported formats: {supported}",
        )

    try:
        with open(p, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        file_name = p.name
        file_size = os.path.getsize(p)
        image_format = _get_image_format(file_path)

        text = f"Image loaded: {file_name}, format: {image_format}, size: {file_size} bytes"

        result_data = {
            "images": [image_data],
            "text": text,
        }

        return ToolResult(content=json.dumps(result_data))
    except Exception as e:
        return ToolResult(success=False, content=f"Error reading image: {e}")