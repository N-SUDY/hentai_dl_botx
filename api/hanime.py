"""
Wrapper around external hentai-api service (Node.js).
Uses https://github.com/sulvii/hentai-api

Functions:
    search(query, page=0)   -> list of hit dicts
    details(slug)           -> dict with video metadata + episodes
    get_streams(slug)       -> dict with 'streams' list and 'dl_url'

Backward compatible with old hanime.tv signatures.
"""

import asyncio
import logging
import re
from typing import Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

log = logging.getLogger(__name__)

# Change this to your deployed hentai-api URL
HENTAI_API_BASE = "https://hentai-api.example.com"  # Replace with actual URL
# For local testing: "http://localhost:3000"


async def _get_http(url: str, timeout: int = 20) -> dict:
    """Helper to make async HTTP GET requests."""
    if aiohttp is None:
        raise ImportError("aiohttp is required. Run: pip install aiohttp")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    log.error(f"API error: {resp.status} for {url}")
                    return {}
    except Exception as e:
        log.error(f"HTTP request failed: {e}")
        return {}


def _episode_from_slug(slug: str) -> tuple[str, int]:
    """Split 'overflow-1' into ('overflow', 1)."""
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return slug, 1


# ── Search ──────────────────────────────────────────────────────────────

async def search(query: str, page: int = 0) -> list[dict]:
    """
    Search hentaihaven via the external hentai-api service.
    Returns list of hit dicts compatible with old hanime API.
    """
    log.info(f"Searching for '{query}' via hentai-api")
    
    url = f"{HENTAI_API_BASE}/api/hentaihaven/search?query={query}&page={page}"
    data = await _get_http(url)
    
    if not data or "results" not in data:
        log.warning(f"No results from hentai-api for query='{query}'")
        return []
    
    hits = []
    for item in data.get("results", []):
        hits.append({
            "id": item.get("id", 0),
            "slug": item.get("slug", item.get("id", "")),
            "name": item.get("title", item.get("name", "Unknown")),
            "url": item.get("url", ""),
            "poster_url": item.get("poster", item.get("image", "")),
            "cover_url": item.get("cover", item.get("poster", "")),
            "description": item.get("description", ""),
            "views": item.get("views", 0),
            "interests": item.get("interests", 0),
            "likes": item.get("likes", 0),
            "dislikes": item.get("dislikes", 0),
            "duration_in_ms": item.get("duration_ms", 0),
            "brand": item.get("brand", "N/A"),
            "tags": item.get("tags", []),
            "titles": item.get("titles", [item.get("title", item.get("name", "Unknown"))]),
            "created_at": item.get("created_at", 0),
            "released_at": item.get("released_at", 0),
        })
    
    log.info(f"Found {len(hits)} results")
    return hits


# ── Video Details ───────────────────────────────────────────────────────

async def details(slug: str) -> dict:
    """
    Get detailed info for a video by slug.
    Returns dict with same shape as old hanime API for compatibility.
    """
    log.info(f"Fetching details for slug='{slug}'")
    
    url = f"{HENTAI_API_BASE}/api/hentaihaven/info?id={slug}"
    data = await _get_http(url)
    
    if not data:
        log.warning(f"No details found for slug='{slug}'")
        return {
            "name": slug,
            "slug": slug,
            "views": 0,
            "poster_url": "",
            "cover_url": "",
            "description": "",
            "released_date": "N/A",
            "likes": 0,
            "dislikes": 0,
            "duration": "N/A",
            "duration_ms": 0,
            "brand": "N/A",
            "tags": [],
            "titles": [],
            "episodes": [],
        }
    
    # Parse episodes
    episodes = []
    ep_list = data.get("episodes", [])
    if isinstance(ep_list, list):
        for ep in ep_list:
            if isinstance(ep, dict):
                episodes.append({
                    "name": ep.get("name", f"Episode {ep.get('number', 1)}"),
                    "slug": ep.get("slug", ep.get("id", "")),
                    "poster_url": ep.get("poster", ep.get("image", "")),
                })
            else:
                # If episodes are just strings/IDs
                episodes.append({
                    "name": f"Episode {ep}",
                    "slug": f"{slug}-{ep}",
                    "poster_url": "",
                })
    
    return {
        "name": data.get("title", data.get("name", slug)),
        "slug": slug,
        "views": data.get("views", 0),
        "poster_url": data.get("poster", data.get("image", "")),
        "cover_url": data.get("cover", data.get("poster", "")),
        "description": data.get("description", ""),
        "released_date": data.get("released_date", "N/A"),
        "likes": data.get("likes", 0),
        "dislikes": data.get("dislikes", 0),
        "duration": data.get("duration", "N/A"),
        "duration_ms": data.get("duration_ms", 0),
        "brand": data.get("brand", "N/A"),
        "tags": data.get("tags", []),
        "titles": data.get("titles", [data.get("title", data.get("name", slug))]),
        "episodes": episodes,
    }


# ── Streams ─────────────────────────────────────────────────────────────

async def get_streams(slug: str) -> dict:
    """
    Get stream URLs for a video via the hentai-api service.
    """
    log.info(f"Fetching streams for slug='{slug}'")
    
    url = f"{HENTAI_API_BASE}/api/hentaihaven/streams?id={slug}"
    data = await _get_http(url, timeout=60)
    
    if not data:
        log.warning(f"No streams found for slug='{slug}'")
        return {"streams": [], "dl_url": ""}
    
    stream_urls = []
    for stream in data.get("streams", []):
        if isinstance(stream, dict):
            stream_urls.append({
                "url": stream.get("url", ""),
                "height": stream.get("height", stream.get("quality", 0)),
                "width": stream.get("width", 1280),
                "kind": stream.get("kind", "hls"),
                "filename": f"{slug}.mp4",
                "filesize_mbs": stream.get("filesize_mbs", 0),
                "is_downloadable": True,
            })
        else:
            # If stream is just a URL string
            stream_urls.append({
                "url": stream,
                "height": 0,
                "width": 1280,
                "kind": "hls",
                "filename": f"{slug}.mp4",
                "filesize_mbs": 0,
                "is_downloadable": True,
            })
    
    # Sort by quality (highest first)
    stream_urls.sort(key=lambda s: s.get("height", 0) or 0, reverse=True)
    dl_url = stream_urls[0]["url"] if stream_urls else ""
    
    log.info(f"Found {len(stream_urls)} streams")
    return {
        "streams": stream_urls,
        "dl_url": dl_url,
    }
