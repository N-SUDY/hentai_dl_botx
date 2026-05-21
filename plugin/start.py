"""
/start command handler.

On first run (no admins exist), the user who sends /start becomes the owner.
Sends a welcome photo with bot info.
"""

import logging
from datetime import datetime, timezone

from pyrogram import Client
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from utils.db import get_db
from utils.fsub import check_force_sub, send_force_sub_message
from utils.poster import download_poster
import os

log = logging.getLogger(__name__)

WELCOME_TEXT = (
    "✨ **Welcome to Hentai DL Bot** ✨\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🎌 Your ultimate hentai companion — search, stream,\n"
    "and download your favorite titles directly to Telegram.\n\n"
    "💬 **Just type any hentai name to search!**\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚡ Powered by Hanime.tv API & FFmpeg\n"
)

OWNER_SETUP_TEXT = (
    "👑 **Owner Setup Complete!**\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "You are the **super admin** of this bot.\n\n"
    "**🛡 Admin Commands:**\n"
    "• `/addadmin <user_id>` — Add admins\n"
    "• `/removeadmin <user_id>` — Remove admins\n"
    "• `/admins` — List all admins\n\n"
    "**👥 User Management:**\n"
    "• `/pending` — View access requests\n"
    "• `/approve / /reject <user_id>`\n"
    "• `/adduser / /removeuser <user_id>`\n"
    "• `/users` — List approved users\n\n"
    "**📢 Channel Setup:**\n"
    "• `/setlog <channel_id>` — Set log channel\n"
    "• `/setchannel <channel_id>` — Set archive channel\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚡ Powered by Hanime.tv API & FFmpeg\n"
)

# Poster URL for welcome image
WELCOME_POSTER = "https://hanime-cdn.com/images/covers/overflow-1.jpg"


async def _send_welcome_photo(client: Client, chat_id: int, text: str, keyboard):
    """Download a poster and send as welcome photo."""
    poster_path = await download_poster(WELCOME_POSTER)
    if poster_path:
        try:
            await client.send_photo(
                chat_id=chat_id,
                photo=poster_path,
                caption=text,
                reply_markup=keyboard,
            )
            return
        except Exception:
            log.warning("Failed to send welcome poster")
        finally:
            try:
                os.unlink(poster_path)
            except Exception:
                pass

    # Fallback: text only
    await client.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )


async def checksub_callback(client, callback_query):
    """Handle 'I've Joined' button — re-check membership."""
    user_id = callback_query.from_user.id
    passed, channel_id = await check_force_sub(client, user_id)
    if passed:
        await callback_query.answer("✅ Verified! You can now use the bot.", show_alert=True)
        try:
            await callback_query.message.delete()
        except Exception:
            pass
    else:
        await callback_query.answer("❌ You haven't joined yet! Please join the channel first.", show_alert=True)


async def start_command(client: Client, message: Message):
    user = message.from_user
    db = get_db()

    # Force-sub check FIRST (before anything else)
    passed, channel_id = await check_force_sub(client, user.id)
    if not passed and channel_id:
        await send_force_sub_message(client, message.chat.id, channel_id)
        return

    # Check if any admins exist
    admin_count = await db.admins.count_documents({})
    if admin_count == 0:
        # First user becomes owner
        await db.admins.insert_one({
            "user_id": user.id,
            "role": "owner",
            "added_at": datetime.now(timezone.utc),
        })

        # Also auto-approve the owner
        await db.approved_users.update_one(
            {"user_id": user.id},
            {"$set": {
                "user_id": user.id,
                "username": user.username or "",
                "approved_by": user.id,
                "approved_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

        log.info("Owner set up: user_id=%s username=%s", user.id, user.username)
        await _send_welcome_photo(client, message.chat.id, OWNER_SETUP_TEXT, None)
        return

    # Regular /start
    await _send_welcome_photo(client, message.chat.id, WELCOME_TEXT, None)
