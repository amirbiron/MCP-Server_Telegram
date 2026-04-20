"""
Telegram MCP Server
-------------------
MCP Server that exposes tools for sending Telegram messages.
Designed for deployment on Render and connection via Claude.ai Connectors.

Setup (Render):
    1. Create a new Web Service on Render
    2. Connect your GitHub repo or upload files
    3. Build Command: pip install -r requirements.txt
    4. Start Command: python server.py
    5. Add Environment Variables:
         TELEGRAM_BOT_TOKEN  = your bot token from @BotFather
         TELEGRAM_CHAT_ID    = your chat ID from @userinfobot
    6. Deploy — copy the Render URL
    7. In Claude.ai -> Connectors -> Add custom connector -> paste: https://<your-render-url>/mcp

Environment Variables:
    TELEGRAM_BOT_TOKEN  - Your bot token from @BotFather
    TELEGRAM_CHAT_ID    - Your personal chat ID (get from @userinfobot)
"""

import os
import json
import httpx
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ── Constants ──────────────────────────────────────────────────────────────────
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DEFAULT_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Server Init ────────────────────────────────────────────────────────────────
mcp = FastMCP("telegram_mcp")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")
    return TELEGRAM_API_BASE.format(token=BOT_TOKEN)


async def _post(endpoint: str, payload: dict) -> dict:
    """Send a POST request to the Telegram Bot API."""
    url = f"{_base_url()}/{endpoint}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            detail = e.response.json().get("description", "")
        except Exception:
            detail = e.response.text
        return f"Error {e.response.status_code}: {detail}"
    if isinstance(e, ValueError):
        return f"Configuration error: {e}"
    return f"Unexpected error: {type(e).__name__}: {e}"


# ── Input Models ───────────────────────────────────────────────────────────────

class SendMessageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(
        ...,
        description="Message text to send. Supports Markdown formatting (bold, italic, code blocks).",
        min_length=1,
        max_length=4096,
    )
    chat_id: Optional[str] = Field(
        default=None,
        description="Telegram chat ID. If not provided, uses TELEGRAM_CHAT_ID env var.",
    )
    parse_mode: Optional[str] = Field(
        default="Markdown",
        description="Formatting mode: 'Markdown', 'HTML', or None for plain text.",
    )
    disable_notification: Optional[bool] = Field(
        default=False,
        description="Send silently without triggering a notification sound.",
    )


class SendCodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(..., description="Short title / label for the code block.", min_length=1, max_length=200)
    code: str = Field(..., description="Code content to send.", min_length=1, max_length=3500)
    language: Optional[str] = Field(default="", description="Programming language for syntax hint (e.g. python, bash).")
    chat_id: Optional[str] = Field(default=None, description="Telegram chat ID. Defaults to TELEGRAM_CHAT_ID env var.")


class SendSummaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(..., description="Summary title (e.g. 'Task Complete ✅').", min_length=1, max_length=100)
    items: list[str] = Field(..., description="List of bullet-point items for the summary.", min_length=1)
    chat_id: Optional[str] = Field(default=None, description="Telegram chat ID. Defaults to TELEGRAM_CHAT_ID env var.")
    footer: Optional[str] = Field(default=None, description="Optional footer line at the bottom of the message.")


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="telegram_send_message",
    annotations={
        "title": "Send Telegram Message",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def telegram_send_message(params: SendMessageInput) -> str:
    """Send a free-form text message to a Telegram chat.

    Use this to notify about task completion, report progress, ask for input,
    or send any update from Claude Code to the developer.

    Args:
        params (SendMessageInput):
            - text (str): Message content (Markdown supported)
            - chat_id (str, optional): Target chat ID
            - parse_mode (str, optional): 'Markdown', 'HTML', or None
            - disable_notification (bool, optional): Silent send

    Returns:
        str: Success message with Telegram message_id, or error description.
    """
    try:
        chat_id = params.chat_id or DEFAULT_CHAT_ID
        if not chat_id:
            return "Error: No chat_id provided and TELEGRAM_CHAT_ID is not set."

        payload = {
            "chat_id": chat_id,
            "text": params.text,
            "disable_notification": params.disable_notification,
        }
        if params.parse_mode:
            payload["parse_mode"] = params.parse_mode

        result = await _post("sendMessage", payload)
        msg_id = result.get("result", {}).get("message_id", "?")
        return json.dumps({"success": True, "message_id": msg_id})

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="telegram_send_code",
    annotations={
        "title": "Send Code Snippet via Telegram",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def telegram_send_code(params: SendCodeInput) -> str:
    """Send a formatted code snippet to Telegram.

    Wraps the code in a Markdown code block with an optional language label.
    Useful for sharing generated files, diffs, configs, or script outputs.

    Args:
        params (SendCodeInput):
            - title (str): Label shown above the code block
            - code (str): The code content
            - language (str, optional): Language for syntax hint (python, bash, json…)
            - chat_id (str, optional): Target chat ID

    Returns:
        str: JSON with success status and message_id, or error description.
    """
    try:
        chat_id = params.chat_id or DEFAULT_CHAT_ID
        if not chat_id:
            return "Error: No chat_id provided and TELEGRAM_CHAT_ID is not set."

        lang = params.language or ""
        text = f"*{params.title}*\n```{lang}\n{params.code}\n```"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        result = await _post("sendMessage", payload)
        msg_id = result.get("result", {}).get("message_id", "?")
        return json.dumps({"success": True, "message_id": msg_id})

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="telegram_send_summary",
    annotations={
        "title": "Send Structured Summary via Telegram",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def telegram_send_summary(params: SendSummaryInput) -> str:
    """Send a structured bullet-point summary to Telegram.

    Ideal for end-of-task reports: list what was done, files created,
    errors encountered, or next recommended steps.

    Args:
        params (SendSummaryInput):
            - title (str): Bold header (e.g. '✅ Task Complete')
            - items (list[str]): Bullet points
            - chat_id (str, optional): Target chat ID
            - footer (str, optional): Closing line

    Returns:
        str: JSON with success status and message_id, or error description.
    """
    try:
        chat_id = params.chat_id or DEFAULT_CHAT_ID
        if not chat_id:
            return "Error: No chat_id provided and TELEGRAM_CHAT_ID is not set."

        bullets = "\n".join(f"• {item}" for item in params.items)
        text = f"*{params.title}*\n\n{bullets}"
        if params.footer:
            text += f"\n\n_{params.footer}_"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        result = await _post("sendMessage", payload)
        msg_id = result.get("result", {}).get("message_id", "?")
        return json.dumps({"success": True, "message_id": msg_id})

    except Exception as e:
        return _handle_error(e)


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
