"""Pure message helpers shared by Nova and standalone novakit users."""

from __future__ import annotations

import logging

from novakit.llm import Message as LLMMessage
from novakit.llm.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_BYTES,
    downscale_image,
    image_data_url,
    image_size_bytes,
)

log = logging.getLogger(__name__)


def build_user_message(
    user_input: str,
    attachments: list[dict] | None = None,
    display_text: str | None = None,
) -> tuple[str, list[str], str]:
    """Fold attachments into the text and image payload of a user message.

    Documents are prepended to the prompt because the model reads them as
    context for the request; images travel separately as data URLs so the media
    type reaches the provider (providers used to be told every image was PNG).

    Args:
        user_input: The text the user typed.
        attachments: Attachment dicts from the client, if any.

    Returns:
        ``(message_text, image_data_urls, display_text)``. The first is what the
        model reads (documents inlined, references appended by the client); the
        last is what a transcript should show. Images over the size budget are
        dropped with a warning rather than failing the whole message, and the
        ones that survive are downscaled to what a provider would use anyway.
    """
    image_data: list[str] = []
    image_bytes = 0
    message_text = user_input
    for attachment in attachments or []:
        if attachment.get("type") == "image":
            for content_part in attachment.get("content", []):
                if content_part.get("type") != "image":
                    continue
                image_url = content_part.get("image", "")
                # Remote references cannot be inlined without fetching them.
                if not image_url or "://" in image_url:
                    continue
                size = image_size_bytes(image_url)
                if size > MAX_IMAGE_BYTES or image_bytes + size > MAX_IMAGES_BYTES:
                    log.warning(
                        "Dropping attachment image (%d bytes, budget %d)",
                        size,
                        MAX_IMAGES_BYTES,
                    )
                    continue
                image_bytes += size
                image_data.append(downscale_image(image_data_url(image_url)))
        elif attachment.get("type") == "document":
            for content_part in attachment.get("content", []):
                if content_part.get("type") == "text":
                    message_text = content_part.get("text", "") + "\n\n" + message_text
    return (
        message_text,
        image_data,
        display_text if display_text is not None else user_input,
    )


def count_user_turns(messages: list) -> int:
    """How many user turns this conversation has, including the current one."""
    return sum(
        1
        for message in messages
        if (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        == "user"
    )


def convert_to_llm_messages(loaded_messages: list) -> list:
    """Convert stored session messages to provider-facing LLM messages.

    Drops tool results whose assistant call was compacted away and trims tool
    calls whose result is gone, keeping the assistant->tool pairing providers
    require. All message content, images, reasoning and provider metadata are
    carried over unchanged.
    """
    resolved_tool_call_ids = {
        loaded_message.tool_call_id
        for loaded_message in loaded_messages
        if loaded_message.role == "tool" and loaded_message.tool_call_id
    }
    declared_tool_call_ids: set[str] = set()
    for loaded_message in loaded_messages:
        if loaded_message.role == "assistant" and loaded_message.tool_calls:
            for tool_call in loaded_message.tool_calls:
                tool_call_identifier = (
                    tool_call.get("id") if isinstance(tool_call, dict) else None
                )
                if tool_call_identifier:
                    declared_tool_call_ids.add(tool_call_identifier)

    converted_messages: list = []
    for loaded_message in loaded_messages:
        if (
            loaded_message.role == "tool"
            and loaded_message.tool_call_id not in declared_tool_call_ids
        ):
            continue
        llm_message = LLMMessage(
            role=loaded_message.role, content=loaded_message.content
        )
        if loaded_message.tool_calls:
            llm_message.tool_calls = [
                tool_call
                for tool_call in loaded_message.tool_calls
                if (
                    isinstance(tool_call, dict)
                    and tool_call.get("id")
                    and tool_call["id"] in resolved_tool_call_ids
                )
            ]
        if loaded_message.tool_call_id:
            llm_message.tool_call_id = loaded_message.tool_call_id
        if loaded_message.images:
            llm_message.images = loaded_message.images
        if loaded_message.reasoning_content:
            llm_message.reasoning_content = loaded_message.reasoning_content
        if loaded_message.provider_meta:
            llm_message.provider_meta = loaded_message.provider_meta
        if loaded_message.model:
            llm_message.model = loaded_message.model
        converted_messages.append(llm_message)
    return converted_messages


__all__ = ["build_user_message", "convert_to_llm_messages", "count_user_turns"]
