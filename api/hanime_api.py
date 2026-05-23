"""
Hanime.tv API wrapper.

Uses hanime.tv's native API endpoints:
- Search: https://search.htv-services.com/ (POST)
- Video details + streams: https://hanime.tv/api/v8/video?id={slug} (GET)

No authentication required for basic usage.
"""

import json
import logging
import random
import re
import time
from typing import Optional
from html import unescape

import requests

log = logging.getLogger(__name__)

SEARCH_URL = "https://search.htv-services.com/"
VIDEO_URL = "https://hanime.tv/api/v8/video"
BASE_URL = "https://hanime.tv"


class HanimeAPI:
    """Wrapper for hanime.tv's native API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Signature-Version': 'web2',
            'X-Signature': 'nonce',
        })
        self._last_request = 0

    def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make an API request with rate limiting and retries."""
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Rate limiting
                elapsed = time.time() - self._last_request
                if elapsed < 0.5:
                    time.sleep(0.5 - elapsed + random.uniform(0.1, 0.3))
                self._last_request = time.time()

                resp = self.session.request(method, url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                log.warning(f"Request failed on attempt {attempt + 1}/{max_retries}: {e}")
                last_error = e
                time.sleep(1 + attempt * 2)

        raise Exception(f"Failed after {max_retries} attempts. Last error: {last_error}")

    def search(self, query: str, page: int = 0) -> list[dict]:
        """
        Search for hentai videos.
        Returns a list of results with: id, name, slug, cover_url, poster_url, tags, views, description.
        """
        payload = {
            "search_text": query,
            "tags": [],
            "tags_mode": "AND",
            "brands": [],
            "blacklist": [],
            "order_by": "created_at_unix",
            "ordering": "desc",
            "page": page,
        }

        log.info(f"Searching for '{query}' on hanime.tv API")
        data = self._request("POST", SEARCH_URL, json=payload)

        hits_raw = data.get("hits", "[]")
        if isinstance(hits_raw, str):
            hits = json.loads(hits_raw)
        else:
            hits = hits_raw

        results = []
        for h in hits:
            results.append({
                'id': h.get('id'),
                'slug': h.get('slug', ''),
                'name': h.get('name', ''),
                'title': h.get('name', ''),
                'cover_url': h.get('cover_url', ''),
                'poster_url': h.get('poster_url', h.get('cover_url', '')),
                'cover': h.get('cover_url', ''),
                'tags': h.get('tags', []),
                'views': h.get('views', 0),
                'brand': h.get('brand', ''),
                'description': h.get('description', ''),
                'url': f"{BASE_URL}/videos/hentai/{h.get('slug', '')}",
            })

        log.info(f"Found {len(results)} results for '{query}'")
        return results

    def details(self, slug: str) -> dict:
        """
        Get detailed info about a hentai video including streams.
        Returns: name, slug, description, poster_url, cover_url, tags, streams, episodes, etc.
        """
        log.info(f"Fetching details for '{slug}' from hanime.tv API")
        data = self._request("GET", VIDEO_URL, params={"id": slug})

        video = data.get("hentai_video", {})

        # Parse tags
        tags = [t.get("text", "") for t in video.get("hentai_tags", [])]

        # Parse description (strip HTML)
        description = video.get("description", "")
        description = re.sub(r'<[^>]+>', '', description)
        description = unescape(description).strip()

        # Parse streams from videos_manifest
        streams = []
        manifest = data.get("videos_manifest", {})
        for server in manifest.get("servers", []):
            for s in server.get("streams", []):
                streams.append({
                    'url': s.get('url', ''),
                    'height': s.get('height', ''),
                    'width': s.get('width', 0),
                    'size_mbs': s.get('filesize_mbs', 0),
                    'kind': s.get('kind', ''),
                    'extension': s.get('extension', ''),
                    'is_downloadable': s.get('is_downloadable', False),
                    'server': server.get('name', ''),
                })

        # Parse related episodes (franchise)
        episodes = []
        for ep in video.get("hentai_franchise_hentai_videos", []):
            episodes.append({
                'id': ep.get('id'),
                'slug': ep.get('slug', ''),
                'name': ep.get('name', ''),
                'title': ep.get('name', ''),
                'cover_url': ep.get('cover_url', ''),
                'poster_url': ep.get('poster_url', ''),
            })

        return {
            'id': video.get('id'),
            'slug': video.get('slug', slug),
            'name': video.get('name', slug.replace('-', ' ').title()),
            'title': video.get('name', slug.replace('-', ' ').title()),
            'description': description,
            'summary': description,
            'poster_url': video.get('poster_url', ''),
            'cover_url': video.get('cover_url', ''),
            'cover': video.get('cover_url', ''),
            'tags': tags,
            'genres': tags,
            'brand': video.get('brand', ''),
            'views': video.get('views', 0),
            'likes': video.get('likes', 0),
            'streams': streams,
            'episodes': episodes,
            'totalEpisodes': len(episodes),
            'url': f"{BASE_URL}/videos/hentai/{video.get('slug', slug)}",
        }

    def get_streams(self, slug: str) -> dict:
        """
        Get streaming URLs for a video.
        Returns: streams list and best dl_url.
        """
        info = self.details(slug)
        streams = info.get('streams', [])

        # Find best download URL (prefer highest quality downloadable)
        dl_url = ""
        best_stream = None

        for s in streams:
            if not best_stream or int(s.get('height', 0) or 0) > int(best_stream.get('height', 0) or 0):
                best_stream = s

        if best_stream:
            dl_url = best_stream.get('url', '')

        return {
            'streams': streams,
            'dl_url': dl_url,
            'sources': [{'url': s['url'], 'label': f"{s['height']}p", 'type': s['kind']} for s in streams],
        }
