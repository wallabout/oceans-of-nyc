"""LLM-based SMS conversation handler using Claude API with tool use."""

import os
from datetime import datetime

import anthropic

from chat.history import ChatHistory
from chat.prompts import SYSTEM_PROMPT, build_image_context
from chat.tools import ALL_TOOLS, ConversationContext, execute_tool

MODEL = "claude-haiku-4-5-20251001"
MAX_TOOL_ROUNDS = 5


def handle_incoming_sms_llm(
    from_number: str,
    body: str,
    num_media: int = 0,
    media_urls: list[str] | None = None,
    media_types: list[str] | None = None,
    volume_path: str = "/data",
    channel_type: str = "sms",
) -> str | None:
    """Process an incoming SMS using Claude LLM with tool use.

    Returns plain text response to send back via SMS, or None if no response needed.
    """
    ctx = ConversationContext.load(from_number=from_number, volume_path=volume_path)
    history = ChatHistory(from_number)
    image_context = None

    # Step 1: Process image if present (reuses existing pipeline)
    if num_media > 0 and media_urls:
        image_context = _process_image(media_urls[0], from_number, volume_path, channel_type, ctx)

    # Step 2: Load conversation history
    recent_messages = history.get_recent()

    # Step 3: Build messages array for Claude API
    messages = _build_messages(recent_messages, body, image_context)

    if not messages:
        return None

    # Step 4: Call Claude and handle tool use loop
    client = anthropic.Anthropic()
    response_text, tools_called = _run_conversation(client, messages, ctx)

    # Step 5: Guard against hallucinated confirmations.
    # If the model claims a sighting was saved but never actually called
    # save_sighting, override with a corrective response.
    if response_text and "save_sighting" not in tools_called:
        if _looks_like_save_confirmation(response_text):
            print(f"BLOCKED hallucinated save confirmation: {response_text!r}")
            response_text = (
                "Hmm, something went wrong on my end — the sighting didn't actually save. "
                "Can you send the details again? (photo + plate + borough)"
            )

    # Step 6: Persist conversation context for multi-turn flows
    ctx.save()

    # Step 7: Save messages to history
    # If a sighting was successfully saved, clear old history first so
    # prior success messages don't teach the model to skip tool calls.
    if "save_sighting" in tools_called:
        history.clear()

    if image_context:
        history.add_message("system", image_context)
    if body:
        history.add_message("user", body)
    elif num_media > 0:
        history.add_message("user", "(photo)")
    if response_text:
        history.add_message("assistant", response_text)

    return response_text


def _process_image(
    media_url: str,
    from_number: str,
    volume_path: str,
    channel_type: str,
    ctx: ConversationContext,
) -> str | None:
    """Download and process an image, updating the ConversationContext.

    Returns an image context string for the LLM, or None on failure.
    """
    from chat.webhook import download_media
    from geolocate.exif import extract_image_metadata, extract_image_timestamp_from_bytes
    from utils.image_processor import ImageProcessor

    twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    print(f"Downloading image from {media_url}")
    image_data = download_media(media_url, (twilio_account_sid, twilio_auth_token))
    if not image_data:
        print("Failed to download image")
        return None

    processor = ImageProcessor(volume_path=volume_path)

    # Extract image timestamp from EXIF
    image_timestamp = extract_image_timestamp_from_bytes(image_data)
    if image_timestamp is None:
        image_timestamp = datetime.now()

    # Save with temporary filename
    temp_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    phone_suffix = from_number[-4:]
    temp_filename = f"pending_{temp_timestamp}_{phone_suffix}.jpg"

    image_paths = processor.process_sighting_image(image_data, temp_filename, upload_to_r2=False)
    image_path = image_paths["original_path"]
    print(f"Saved image: {image_path}")

    # Extract metadata (GPS)
    metadata = extract_image_metadata(image_path)
    print(f"Image metadata: {metadata}")

    # Update context with image data
    ctx.pending_image_path = image_path
    ctx.pending_image_timestamp = image_timestamp

    lat = metadata.get("latitude")
    lon = metadata.get("longitude")
    if lat is not None and lon is not None:
        ctx.pending_latitude = lat
        ctx.pending_longitude = lon

    # Timestamp from EXIF or fallback
    try:
        ctx.pending_timestamp = datetime.fromisoformat(metadata.get("timestamp", ""))
    except (ValueError, TypeError):
        ctx.pending_timestamp = datetime.now()

    timestamp_str = image_timestamp.strftime("%Y-%m-%d %H:%M") if image_timestamp else None

    return build_image_context(
        has_gps=lat is not None,
        latitude=lat,
        longitude=lon,
        timestamp=timestamp_str,
    )


def _build_messages(
    recent_messages: list[dict],
    body: str | None,
    image_context: str | None,
) -> list[dict]:
    """Build the messages array for the Claude API call."""
    messages = []

    # Add conversation history
    for msg in recent_messages:
        role = msg["role"]
        content = msg["content"]

        if role == "system":
            # Inject system context as user message with bracketed prefix
            # (Claude API doesn't support system role in messages array)
            messages.append({"role": "user", "content": content})
            messages.append({"role": "assistant", "content": "Understood."})
        elif role in ("user", "assistant"):
            # Strip legacy tool-use metadata prefix from older history entries
            if role == "assistant" and content.startswith("[Tools used:"):
                content = content.split("] ", 1)[-1]
            messages.append({"role": role, "content": content})

    # Add current turn: image context + user message
    if image_context:
        messages.append({"role": "user", "content": image_context})
        messages.append({"role": "assistant", "content": "Understood."})

    if body:
        messages.append({"role": "user", "content": body})
    elif image_context:
        # Photo with no text — add a placeholder user message
        messages.append({"role": "user", "content": "(photo sent with no text)"})

    # Ensure messages alternate correctly and start with user
    if not messages:
        return []

    return messages


def _run_conversation(
    client: anthropic.Anthropic,
    messages: list[dict],
    ctx: ConversationContext,
) -> tuple[str | None, list[str]]:
    """Run the Claude conversation loop, executing tools as needed.

    Returns (response_text, list_of_tool_names_called).
    """
    tools_called: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
            messages=messages,
        )

        # Check if we got a final text response (no tool use)
        if response.stop_reason == "end_of_turn":
            return _extract_text(response), tools_called

        # Process tool use blocks
        if response.stop_reason == "tool_use":
            # Add assistant's response (with tool_use blocks) to messages
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"Tool call: {block.name}({block.input})")
                    tools_called.append(block.name)
                    result = execute_tool(block.name, block.input, ctx)
                    print(f"Tool result: {result}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — return whatever text we have
        return _extract_text(response), tools_called

    # Exhausted tool rounds — return last text
    return _extract_text(response), tools_called


def _looks_like_save_confirmation(text: str) -> bool:
    """Detect if a response claims a sighting was saved."""
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in ("sighting saved", "sighting logged", "saved!", "logged!", "sighting #")
    )


def _extract_text(response) -> str | None:
    """Extract text content from a Claude API response."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return None
