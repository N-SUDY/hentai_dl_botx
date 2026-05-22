"""
HentaiHaven scraper - Python implementation.
Uses cloudscraper for Cloudflare bypass and beautifulsoup4 for HTML parsing.

Based on: https://github.com/sulvii/hentai-api
"""

import asyncio
import json
import logging
import re
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://hentaihaven.xxx"


class HentaiHavenScraper:
    """Scraper for hentaihaven.xxx"""
    
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.soup = None
    
    def get(self, url: str, timeout: int = 30) -> str:
        """Fetch HTML from URL using cloudscraper."""
        try:
            resp = self.scraper.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            log.error(f"Request failed: {e}")
            raise
    
    def search(self, query: str) -> list[dict]:
        """Search hentaihaven.xxx for content."""
        url = f"{BASE_URL}/?s={query}&post_type=wp-manga"
        log.info(f"Searching for '{query}'")
        
        html = self.get(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        results = []
        seen = set()
        
        # Find all search result cards
        for content in soup.find_all('div', class_='c-tabs-item__content'):
            try:
                # Extract image and title first
                img = content.find('img')
                if not img:
                    continue
                
                cover = img.get('src', '')
                alt = img.get('alt', '')
                title = alt.replace(' cover', '').strip() or 'Unknown'
                
                # Find the main watch link
                link = content.find('a', href=re.compile(r'.+/watch/[^/]+/$'))
                if not link:
                    continue
                
                href = link.get('href', '')
                
                # Extract series ID
                match = re.search(r'/watch/([^/]+)/', href)
                if not match:
                    continue
                series_id = match.group(1)
                
                if series_id in seen:
                    continue
                seen.add(series_id)
                
                # Extract alternative title
                alternative = ''
                alt_div = content.find('div', class_='mg_alternative')
                if alt_div:
                    content_div = alt_div.find('div', class_='summary-content')
                    if content_div:
                        alternative = content_div.text.strip()
                
                # Extract author
                author = ''
                author_div = content.find('div', class_='mg_author')
                if author_div:
                    content_div = author_div.find('div', class_='summary-content')
                    if content_div:
                        author = content_div.text.strip()
                
                # Extract release year
                release_div = content.find('div', class_='mg_release')
                released = 0
                if release_div:
                    content_div = release_div.find('div', class_='summary-content')
                    if content_div:
                        released = _get_number(content_div.text) or 0
                
                # Extract episode count
                chap_el = content.find('span', class_='chapter')
                total_episodes = _get_number(chap_el.text) if chap_el else 1
                
                # Extract rating
                rating = 0.0
                rating_span = content.find('span', class_='total_votes')
                if rating_span:
                    rating = float(rating_span.text.strip())
                
                # Extract genres
                genres = []
                for genre_link in content.find_all('a', href=re.compile(r'/genre/')):
                    genres.append({
                        'name': genre_link.text.strip(),
                        'url': genre_link.get('href', '')
                    })
                
                results.append({
                    'id': series_id,
                    'slug': series_id,
                    'title': title,
                    'name': title,
                    'cover': cover.replace(' ', '%20'),
                    'poster_url': cover,
                    'rating': rating,
                    'released': released,
                    'genres': genres,
                    'totalEpisodes': total_episodes,
                    'alternative': alternative,
                    'author': author,
                    'url': href,
                })
            except Exception as e:
                log.warning(f"Failed to parse search result: {e}")
                continue
        
        log.info(f"Found {len(results)} results")
        return results
    
    def details(self, series_id: str) -> dict:
        """Get detailed info about a hentai series."""
        url = f"{BASE_URL}/watch/{series_id}"
        log.info(f"Fetching details for {series_id}")
        
        html = self.get(url)
        
        if not html or "webpage has been blocked" in html:
            log.error(f"Page blocked for {series_id}")
            return {}
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = series_id.replace('-', ' ').title()
        title_el = soup.find('h1', class_='post-title')
        if title_el:
            title = title_el.text.strip()
        
        # Extract cover
        cover = ''
        for img in soup.find_all('img'):
            src = img.get('src', '')
            alt = img.get('alt', '')
            if 'cover' in alt.lower() or 'cover' in src.lower():
                cover = src
                break
        
        # Extract summary
        summary = ""
        desc_el = soup.find('div', class_='description-summary')
        if desc_el:
            p = desc_el.find('p')
            summary = p.text.strip() if p else desc_el.text.strip()
        
        # Extract episodes
        episodes = []
        ep_elements = soup.find_all('li', class_='wp-manga-chapter')
        total_episodes = len(ep_elements)
        
        for i, ep_el in enumerate(ep_elements):
            try:
                link = ep_el.find('a')
                if not link:
                    continue
                
                ep_title = link.text.strip()
                ep_number = total_episodes - i
                
                # Extract episode ID from href
                href = link.get('href', '')
                parts = href.strip('/').split('/')
                if len(parts) >= 2:
                    ep_id = f"{parts[-2]}/{parts[-1]}"
                else:
                    ep_id = f"{series_id}-ep{ep_number}"
                
                date_el = ep_el.find('span', class_='chapter-release-date')
                ep_date = date_el.text.strip() if date_el else ''
                
                episodes.append({
                    'id': ep_id,
                    'slug': f"{series_id}-{ep_number}",
                    'title': ep_title,
                    'number': ep_number,
                    'released': ep_date,
                })
            except Exception as e:
                log.warning(f"Failed to parse episode: {e}")
                continue
        
        return {
            'id': series_id,
            'slug': series_id,
            'title': title,
            'name': title,
            'cover': cover.replace(' ', '%20') if cover else '',
            'poster_url': cover,
            'summary': summary,
            'totalEpisodes': total_episodes,
            'episodes': episodes,
        }
    
    def get_streams(self, ep_id: str) -> dict:
        """Get video sources for an episode."""
        if not ep_id:
            return {'sources': [], 'dl_url': ''}
        
        # Parse episode ID (format: series-1)
        parts = ep_id.rsplit('-', 1)
        if len(parts) != 2:
            log.error(f"Invalid episode ID: {ep_id}")
            return {'sources': [], 'dl_url': ''}
        
        series_id, ep_num = parts
        page_url = f"{BASE_URL}/watch/{series_id}/episode-{ep_num}"
        log.info(f"Fetching streams from {page_url}")
        
        html = self.get(page_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find iframe
        iframe = soup.find('iframe', class_='player_logic_item')
        if not iframe:
            log.error("No iframe found")
            return {'sources': [], 'dl_url': ''}
        
        iframe_src = iframe.get('src', '')
        if not iframe_src:
            log.error("No iframe src found")
            return {'sources': [], 'dl_url': ''}
        
        # Fetch iframe and decrypt (simplified - in production needs full decrypt)
        # For now, return the iframe URL for manual inspection
        return {
            'sources': [{
                'url': iframe_src,
                'label': 'unknown',
                'type': 'iframe',
            }],
            'dl_url': iframe_src,
        }


def _get_number(s: str) -> Optional[int]:
    """Extract first number from string"""
    match = re.search(r'\d+', s)
    return int(match.group()) if match else None


# ── Module-level functions for backward compatibility ──

_scraper = None


def _get_scraper() -> HentaiHavenScraper:
    global _scraper
    if _scraper is None:
        _scraper = HentaiHavenScraper()
    return _scraper


async def search(query: str, page: int = 0) -> list[dict]:
    return _get_scraper().search(query)


async def details(series_id: str) -> dict:
    return _get_scraper().details(series_id)


async def get_streams(ep_id: str) -> dict:
    return _get_scraper().get_streams(ep_id)
