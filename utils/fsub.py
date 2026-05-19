"""
Force Subscribe decorator.

Checks if a user has joined the main channel before allowing access.
If no main channel is configured, the check is skipped.

Usage:
    from utils.fsub import force_sub

    @approved_only
    @force_sub
    async def my_handler(client, update):
        ...
"""

import logging
from functools import wraps

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatMemberStatus

from utils.db import get_db

log = logging.getLogger(__name__)


async def _get_main_channel() -> int | None:
    """Get the main channel ID from config."""
    db = get_db()
    doc = await db.config.find_one({"key": "main_channel"})
    if doc:
        return int(doc["value"])
    return None


async def _is_member(client: Client, channel_id: int, user_id: int) -> bool:
    """Check if user is a member of the channel."""
    try:
        member = await client.get_chat_member(channel_id, user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        # If we can't check (bot not admin in channel, user never interacted, etc.),
        # allow access to avoid blocking users unnecessarily
        log.warning("Could not check membership for user %s in channel %s", user_id, channel_id)
        return True


def _make_join_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    """Create an inline keyboard with a join button."""
    # Convert channel_id to invite link format
    chan_str = str(channel_id)
    if chan_str.startswith("-100"):
        chan_str = chan_str[4:]
    invite_url = f"https://t.me/c/{chan_str}/1"

    # Try using a generic invite link; the user should have a public link ideally
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=invite_url)],
    ])


NOT_JOINED_TEXT = (
    "⚠️ **You must join our channel to use this bot!**\n\n"
    "Please join the channel below and try again."
)


def force_sub(func):
    """Decorator: check if user has joined the main channel."""

    @wraps(func)
    async def wrapper(client: Client, update, *args, **kwargs):
        channel_id = await _get_main_channel()

        # No main channel set — skip check
        if not channel_id:
            return await func(client, update, *args, **kwargs)

        if isinstance(update, CallbackQuery):
            user_id = update.from_user.id
            if not await _is_member(client, channel_id, user_id):
                await update.answer("⚠️ Join our channel first!", show_alert=True)
                try:
                    await client.send_message(
                        chat_id=user_id,
                        text=NOT_JOINED_TEXT,
                        reply_markup=_make_join_keyboard(channel_id),
                    )
                except Exception:
                    pass
                return
        elif isinstance(update, Message):
            user_id = update.from_user.id
            if not await _is_member(client, channel_id, user_id):
                await update.reply_text(
                    NOT_JOINED_TEXT,
                    reply_markup=_make_join_keyboard(channel_id),
                )
                return
        else:
            return

        return await func(client, update, *args, **kwargs)

    return wrapper
