import logging

from pyrogram import Client
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from api.hanime import details
from utils.auth import approved_only
from utils.fsub import force_sub

log = logging.getLogger(__name__)


@approved_only
@force_sub
async def infohentai(client: Client, callback_query: CallbackQuery):
    """Show details for a selected hentai (info_<slug> callback)."""
    slug = callback_query.data.split("_", 1)[1]

    try:
        await callback_query.answer("Loading details...")
    except Exception:
        pass

    try:
        info = await details(slug)
    except Exception:
        log.exception("Details fetch failed for slug=%s", slug)
        try:
            await callback_query.answer("❌ API unavailable, try again later.", show_alert=True)
        except Exception:
            pass
        return

    name = info["name"]
    poster = info["poster_url"]
    views = f'{info["views"]:,}' if isinstance(info["views"], int) else info["views"]
    released = info["released_date"]
    likes = f'{info["likes"]:,}' if isinstance(info["likes"], int) else info["likes"]
    dislikes = f'{info["dislikes"]:,}' if isinstance(info["dislikes"], int) else info["dislikes"]
    duration = info["duration"]
    brand = info["brand"]
    tags = info["tags"]

    tags_str = ", ".join(tags[:10]) if tags else "N/A"
    if len(tags) > 10:
        tags_str += f" (+{len(tags) - 10} more)"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️ Download Now", callback_data=f"dlt_{slug}")],
        [InlineKeyboardButton("🔗 Stream Links", callback_data=f"link_{slug}")],
    ])

    text = (
        f"**{name}**\n\n"
        f"👁 **Views:** {views}\n"
        f"👍 **Likes:** {likes}  |  👎 **Dislikes:** {dislikes}\n"
        f"⏱ **Duration:** {duration}\n"
        f"📅 **Released:** {released}\n"
        f"🏷 **Brand:** {brand}\n"
        f"🔖 **Tags:** {tags_str}"
    )

    # Strategy 1: Try editing the existing message with text (safest, no deletion)
    # Strategy 2: If photo needed, send photo WITHOUT deleting first
    # Strategy 3: Pure text fallback

    sent_photo = False
    if poster:
        try:
            await client.send_photo(
                chat_id=callback_query.from_user.id,
                photo=poster,
                caption=text,
                reply_markup=keyboard,
            )
            sent_photo = True
            # Only delete the old message AFTER photo succeeds
            try:
                await callback_query.message.delete()
            except Exception:
                pass
        except Exception:
            log.warning("Failed to send poster for %s, falling back to text", slug)

    if not sent_photo:
        try:
            await callback_query.edit_message_text(text, reply_markup=keyboard)
        except Exception:
            # Last resort: send as new message
            try:
                await client.send_message(
                    chat_id=callback_query.from_user.id,
                    text=text,
                    reply_markup=keyboard,
                )
            except Exception:
                log.exception("All methods failed for info_%s", slug)
