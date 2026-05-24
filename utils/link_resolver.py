"""
Shortened Link Resolver for Hindi Dub channels.

Many Hindi dub channels post shortened/monetized links instead of direct
video files. This module:

1. Detects shortened links in messages
2. Sends them to @Nick_Bypass_Bot to get the real URL
3. Follows the real URL to its destination:
   - Telegram channel message → grabs the video file
   - Telegram bot deep link  → starts the bot, waits for video
4. Returns the file_id of the resolved video

Requires: userbot (Pyrogram user session)
"""

import asyncio
import logging
import re
import time

from pyrogram import Client
from pyrogram.types import Message

log = logging.getLogger(__name__)

BYPASS_BOT = "Nick_Bypass_Bot"
BYPASS_TIMEOUT = 60       # seconds to wait for bypass bot reply
BOT_REPLY_TIMEOUT = 30    # seconds to wait for a bot to send video after /start
CHANNEL_FETCH_TIMEOUT = 15

# Common shortener domains — if a URL matches any of these, it needs bypassing
SHORTENER_DOMAINS = [
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "is.gd", "v.gd",
    "shrinkme.io", "shrinkme.in", "shrinke.me",
    "linkvertise.com", "link-target.net", "link-to.net",
    "za.gl", "za.gy",
    "ouo.io", "ouo.press",
    "exe.io", "exey.io", "exe.app",
    "gplinks.co", "gplinks.in",
    "shareus.io", "shareus.in", "shareus.site",
    "terabox.link", "teraboxlink.com",
    "adrinolinks.in", "adrinolinks.com",
    "mdiskshortner.link",
    "indianshortner.com",
    "earnl.ink", "earnlink.io",
    "links.shortenbuddy.com",
    "short-url.link",
    "shortingly.me", "shortingly.in",
    "tnlink.in", "tnshort.net",
    "xpshort.com",
    "dulink.in",
    "atglinks.com",
    "mplaylink.com",
    "rocklinks.net",
    "urlshortx.com",
    "pdiskshortener.com",
    "telegram.me", "t.me",  # deep links are handled separately
]

# Regex to extract URLs from text
URL_REGEX = re.compile(
    r'https?://[^\s<>\[\]()\"\']+',
    re.IGNORECASE,
)

# Telegram deep link patterns
TG_CHANNEL_MSG = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)/(\d+)',
)
TG_BOT_START = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)\?start=([a-zA-Z0-9_-]+)',
)
TG_BOT_LINK = re.compile(
    r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)',
)


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    return URL_REGEX.findall(text)


def is_shortened_url(url: str) -> bool:
    """Check if a URL is from a known shortener service."""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        # Remove www.
        domain = domain.removeprefix("www.")
        return any(domain == sd or domain.endswith("." + sd) for sd in SHORTENER_DOMAINS)
    except Exception:
        return False


def is_telegram_link(url: str) -> bool:
    """Check if a URL is a Telegram deep link."""
    return bool(TG_CHANNEL_MSG.search(url) or TG_BOT_START.search(url))


def classify_telegram_link(url: str) -> dict | None:
    """
    Parse a Telegram link and classify it.
    Returns:
      {"type": "channel_message", "channel": "...", "message_id": 123}
      {"type": "bot_start", "bot": "...", "param": "..."}
      {"type": "bot", "bot": "..."}
      None if not a Telegram link
    """
    # Channel message: t.me/channel/123
    m = TG_CHANNEL_MSG.search(url)
    if m:
        name = m.group(1)
        msg_id = int(m.group(2))
        # Exclude known bots (they won't have /123 style messages usually)
        return {"type": "channel_message", "channel": name, "message_id": msg_id}

    # Bot with start param: t.me/bot?start=xxx
    m = TG_BOT_START.search(url)
    if m:
        return {"type": "bot_start", "bot": m.group(1), "param": m.group(2)}

    # Plain bot link: t.me/bot
    m = TG_BOT_LINK.search(url)
    if m:
        name = m.group(1)
        # Could be a channel or bot — we'll try both
        return {"type": "bot", "bot": name}

    return None


# ── Bypass Bot Interaction ───────────────────────────────────────────────

async def bypass_link(ub: Client, url: str) -> str | None:
    """
    Send a shortened URL to @Nick_Bypass_Bot and wait for the bypassed URL.
    Returns the bypassed URL string, or None on failure.
    """
    log.info("Bypassing link via @%s: %s", BYPASS_BOT, url[:80])

    try:
        # Send the link to the bypass bot
        await ub.send_message(BYPASS_BOT, url)

        # Wait for a reply
        start = time.time()
        last_msg_id = 0

        while time.time() - start < BYPASS_TIMEOUT:
            await asyncio.sleep(2)

            # Get recent messages from the bypass bot
            async for msg in ub.get_chat_history(BYPASS_BOT, limit=5):
                if msg.id <= last_msg_id:
                    continue
                last_msg_id = max(last_msg_id, msg.id)

                # Skip our own messages
                if msg.outgoing:
                    continue

                # Check for URLs in the reply
                text = (msg.text or "") + " " + (msg.caption or "")
                urls = extract_urls(text)

                if urls:
                    bypassed = urls[0]
                    log.info("Bypass bot returned: %s", bypassed[:80])
                    return bypassed

                # Check for inline buttons with URLs
                if msg.reply_markup:
                    for row in msg.reply_markup.inline_keyboard:
                        for btn in row:
                            if btn.url:
                                log.info("Bypass bot returned (button): %s", btn.url[:80])
                                return btn.url

                # Check if bot says it failed
                lower_text = text.lower()
                if any(w in lower_text for w in ["error", "failed", "not supported", "invalid"]):
                    log.warning("Bypass bot reported error: %s", text[:200])
                    return None

        log.warning("Bypass bot timeout after %ds for %s", BYPASS_TIMEOUT, url[:80])
        return None

    except Exception as e:
        log.error("Bypass bot interaction failed: %s", e)
        return None


# ── Telegram Link Resolution ────────────────────────────────────────────

async def resolve_channel_message(ub: Client, channel: str, message_id: int) -> dict | None:
    """
    Fetch a specific message from a Telegram channel and extract the video file.
    Returns {file_id, file_name, file_size} or None.
    """
    log.info("Resolving channel message: @%s/%d", channel, message_id)
    try:
        msgs = await ub.get_messages(channel, message_id)
        msg = msgs if not isinstance(msgs, list) else msgs[0]

        if msg.video:
            return {
                "file_id": msg.video.file_id,
                "file_name": msg.video.file_name or f"video_{message_id}.mp4",
                "file_size": msg.video.file_size or 0,
                "source": f"@{channel}/{message_id}",
            }
        if msg.document:
            mime = msg.document.mime_type or ""
            fname = msg.document.file_name or ""
            if "video" in mime or any(fname.lower().endswith(e) for e in ['.mp4', '.mkv', '.avi']):
                return {
                    "file_id": msg.document.file_id,
                    "file_name": msg.document.file_name or f"doc_{message_id}",
                    "file_size": msg.document.file_size or 0,
                    "source": f"@{channel}/{message_id}",
                }

        # Maybe the message has a forwarded video or buttons leading to the file
        # Check if message has buttons with links (another level of redirection)
        if msg.reply_markup:
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.url:
                        tg = classify_telegram_link(btn.url)
                        if tg and tg["type"] == "channel_message":
                            # Recursion — but only one level deep
                            return await resolve_channel_message(
                                ub, tg["channel"], tg["message_id"]
                            )

        log.info("Channel message @%s/%d has no video file", channel, message_id)
        return None

    except Exception as e:
        log.warning("Failed to fetch @%s/%d: %s", channel, message_id, e)
        return None


async def resolve_bot_start(ub: Client, bot_username: str, start_param: str) -> dict | None:
    """
    Start a bot with a deep link parameter and wait for it to send a video file.
    Returns {file_id, file_name, file_size} or None.
    """
    log.info("Starting bot @%s with param=%s", bot_username, start_param)
    try:
        # Send /start command with parameter
        await ub.send_message(bot_username, f"/start {start_param}")

        # Wait for bot to reply with a video
        start = time.time()
        last_msg_id = 0

        while time.time() - start < BOT_REPLY_TIMEOUT:
            await asyncio.sleep(2)

            async for msg in ub.get_chat_history(bot_username, limit=5):
                if msg.id <= last_msg_id:
                    continue
                last_msg_id = max(last_msg_id, msg.id)

                if msg.outgoing:
                    continue

                # Check for video
                if msg.video:
                    return {
                        "file_id": msg.video.file_id,
                        "file_name": msg.video.file_name or f"video_{msg.id}.mp4",
                        "file_size": msg.video.file_size or 0,
                        "source": f"@{bot_username}",
                    }

                if msg.document:
                    mime = msg.document.mime_type or ""
                    fname = msg.document.file_name or ""
                    if "video" in mime or any(fname.lower().endswith(e) for e in ['.mp4', '.mkv', '.avi']):
                        return {
                            "file_id": msg.document.file_id,
                            "file_name": msg.document.file_name or f"doc_{msg.id}",
                            "file_size": msg.document.file_size or 0,
                            "source": f"@{bot_username}",
                        }

                # Check if bot sent a link instead (another redirect)
                text = (msg.text or "") + " " + (msg.caption or "")
                urls = extract_urls(text)
                for url in urls:
                    tg = classify_telegram_link(url)
                    if tg and tg["type"] == "channel_message":
                        return await resolve_channel_message(ub, tg["channel"], tg["message_id"])

                # Check inline buttons
                if msg.reply_markup:
                    for row in msg.reply_markup.inline_keyboard:
                        for btn in row:
                            if btn.url:
                                tg = classify_telegram_link(btn.url)
                                if tg and tg["type"] == "channel_message":
                                    return await resolve_channel_message(
                                        ub, tg["channel"], tg["message_id"]
                                    )

        log.info("Bot @%s didn't send a video within %ds", bot_username, BOT_REPLY_TIMEOUT)
        return None

    except Exception as e:
        log.warning("Bot @%s interaction failed: %s", bot_username, e)
        return None


# ── Master Resolver ──────────────────────────────────────────────────────

async def resolve_link(ub: Client, url: str, progress_cb=None) -> dict | None:
    """
    Full link resolution pipeline:
    1. If it's a Telegram link → resolve directly
    2. If shortened → bypass via @Nick_Bypass_Bot → then resolve
    3. Returns {file_id, file_name, file_size, source} or None
    """
    # Step 1: Check if it's already a Telegram link
    tg = classify_telegram_link(url)
    if tg:
        return await _resolve_tg_link(ub, tg, progress_cb)

    # Step 2: It's a shortened link — bypass it
    if progress_cb:
        await progress_cb("🔓 Bypassing shortened link...")

    bypassed_url = await bypass_link(ub, url)
    if not bypassed_url:
        log.info("Link bypass failed for: %s", url[:80])
        return None

    # Step 3: Resolve the bypassed URL
    tg = classify_telegram_link(bypassed_url)
    if tg:
        return await _resolve_tg_link(ub, tg, progress_cb)

    # The bypassed URL is not a Telegram link — could be a direct download
    # (we don't handle direct HTTP video downloads here for now)
    log.info("Bypassed URL is not a Telegram link: %s", bypassed_url[:80])
    return None


async def _resolve_tg_link(ub: Client, tg: dict, progress_cb=None) -> dict | None:
    """Resolve a classified Telegram link to a video file."""
    link_type = tg["type"]

    if link_type == "channel_message":
        if progress_cb:
            await progress_cb(f"📡 Fetching from @{tg['channel']}...")
        return await resolve_channel_message(ub, tg["channel"], tg["message_id"])

    elif link_type == "bot_start":
        if progress_cb:
            await progress_cb(f"🤖 Talking to @{tg['bot']}...")
        return await resolve_bot_start(ub, tg["bot"], tg["param"])

    elif link_type == "bot":
        # Plain bot link without start param — try with empty start
        if progress_cb:
            await progress_cb(f"🤖 Starting @{tg['bot']}...")
        return await resolve_bot_start(ub, tg["bot"], "")

    return None


# ── Message Analysis ─────────────────────────────────────────────────────

def get_message_links(msg: Message) -> list[str]:
    """
    Extract all resolvable links from a message.
    Checks: text, caption, and inline button URLs.
    """
    urls = []

    # From text/caption
    text = (msg.text or "") + " " + (msg.caption or "")
    urls.extend(extract_urls(text))

    # From inline buttons
    if msg.reply_markup:
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url:
                    urls.append(btn.url)

    return urls


def needs_link_resolution(msg: Message) -> bool:
    """
    Check if a message needs link resolution (has shortened links
    but no direct video file).
    """
    # If it already has a video, no resolution needed
    if msg.video or msg.animation:
        return False
    if msg.document:
        mime = msg.document.mime_type or ""
        if "video" in mime:
            return False

    # Check for links that need resolution
    links = get_message_links(msg)
    for url in links:
        if is_shortened_url(url) or is_telegram_link(url):
            return True

    return False
