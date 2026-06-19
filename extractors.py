"""
================================================================================
MODELS.PY - Data Models
================================================================================
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from enum import Enum

from config import Platform, MediaType, ContentType, Quality


@dataclass
class Author:
    """Content author/uploader"""
    name: str
    id: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Thumbnail:
    """Thumbnail information"""
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class VideoFormat:
    """Video format info"""
    format_id: str
    extension: str
    quality: str
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    filesize: Optional[int] = None


@dataclass
class AudioFormat:
    """Audio format info"""
    format_id: str
    extension: str
    quality: str
    acodec: Optional[str] = None
    abr: Optional[float] = None
    filesize: Optional[int] = None


@dataclass
class MediaMetadata:
    """Media metadata"""
    id: str
    title: str
    url: str
    platform: Platform
    media_type: MediaType
    
    description: Optional[str] = None
    duration: Optional[float] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    
    author: Optional[Author] = None
    upload_date: Optional[datetime] = None
    
    thumbnails: List[Thumbnail] = field(default_factory=list)
    video_formats: List[VideoFormat] = field(default_factory=list)
    audio_formats: List[AudioFormat] = field(default_factory=list)
    
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    content_type: ContentType = ContentType.UNKNOWN
    
    raw_data: Optional[Dict] = None
    
    @property
    def best_thumbnail(self) -> Optional[Thumbnail]:
        if not self.thumbnails:
            return None
        return max(self.thumbnails, key=lambda t: (t.width or 0) * (t.height or 0))
    
    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "0:00"
        mins, secs = divmod(int(self.duration), 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"


@dataclass
class DownloadProgress:
    """Download progress"""
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    status: str = "pending"
    
    @property
    def percentage(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return (self.downloaded_bytes / self.total_bytes) * 100


@dataclass
class DownloadResult:
    """Download result"""
    success: bool = False
    url: str = ""
    filepath: Optional[str] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    
    filesize: int = 0
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    quality: Optional[str] = None
    
    has_audio: bool = False
    has_video: bool = False
    
    thumbnail_embedded: bool = False
    metadata_embedded: bool = False
    
    platform: Optional[Platform] = None
    media_type: Optional[MediaType] = None
    
    error: Optional[str] = None


@dataclass
class PlaylistInfo:
    """Playlist information"""
    id: str
    title: str
    url: str
    platform: Platform
    
    description: Optional[str] = None
    author: Optional[Author] = None
    thumbnail: Optional[Thumbnail] = None
    
    video_count: int = 0
    entries: List[MediaMetadata] = field(default_factory=list)
    
    downloaded_count: int = 0
    failed_count: int = 0


@dataclass
class ExtractedText:
    """Extracted text content"""
    title: str = ""
    description: str = ""
    headings: List[Dict] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    word_count: int = 0


@dataclass
class ExtractedLink:
    """Extracted link"""
    url: str
    text: Optional[str] = None
    link_type: str = "unknown"


@dataclass
class ExtractedImage:
    """Extracted image"""
    url: str
    alt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class PageMetadata:
    """Page metadata"""
    url: str
    title: str = ""
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    og_image: Optional[str] = None


@dataclass
class ScrapedPage:
    """Scraped page data"""
    url: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    metadata: Optional[PageMetadata] = None
    text_content: Optional[ExtractedText] = None
    
    links: List[ExtractedLink] = field(default_factory=list)
    images: List[ExtractedImage] = field(default_factory=list)
    videos: List[MediaMetadata] = field(default_factory=list)
    
    platform: Platform = Platform.GENERIC
    content_type: ContentType = ContentType.UNKNOWN
    tags: Set[str] = field(default_factory=set)
    
    success: bool = True
    error: Optional[str] = None


@dataclass
class ScrapeJob:
    """Scrape job"""
    id: str
    url: str
    job_type: str = "single"
    status: str = "pending"
    progress: float = 0.0


__all__ = [
    'Author', 'Thumbnail', 'VideoFormat', 'AudioFormat',
    'MediaMetadata', 'DownloadProgress', 'DownloadResult',
    'PlaylistInfo', 'ExtractedText', 'ExtractedLink', 
    'ExtractedImage', 'PageMetadata', 'ScrapedPage', 'ScrapeJob',
    'extract_metadata', 'extract_playlist', 'extract_page',
    'extract_streaming_sources', 'smart_extract',
    'HTMLExtractor', 'MediaExtractor', 'StreamingExtractor',
]


# =============================================================================
# Imports for extraction functions
# =============================================================================

import os
import re
import json
import asyncio
import subprocess
import logging
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    BeautifulSoup = None

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Check yt-dlp
HAS_YTDLP = False
try:
    r = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, timeout=5)
    HAS_YTDLP = r.returncode == 0
except Exception:
    pass


# =============================================================================
# yt-dlp Helper
# =============================================================================

async def _run_ytdlp(args: list) -> Optional[dict]:
    """Run yt-dlp with args and return parsed JSON output"""
    cmd = ['yt-dlp', '--dump-json', '--no-download', '--no-warnings'] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if stdout:
            return json.loads(stdout.decode('utf-8', errors='replace').strip().split('\n')[0])
    except Exception as e:
        logger.debug(f"yt-dlp error: {e}")
    return None


async def _run_ytdlp_multi(args: list) -> List[dict]:
    """Run yt-dlp and return multiple JSON entries (for playlists)"""
    cmd = ['yt-dlp', '--dump-json', '--no-download', '--no-warnings', '--flat-playlist'] + args
    results = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if stdout:
            for line in stdout.decode('utf-8', errors='replace').strip().split('\n'):
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        logger.debug(f"yt-dlp playlist error: {e}")
    return results


def _parse_platform(url: str) -> Platform:
    """Detect platform from URL"""
    domain = urlparse(url).netloc.lower().replace('www.', '')
    platform_map = {
        'youtube.com': Platform.YOUTUBE, 'youtu.be': Platform.YOUTUBE,
        'instagram.com': Platform.INSTAGRAM,
        'tiktok.com': Platform.TIKTOK,
        'twitter.com': Platform.TWITTER, 'x.com': Platform.TWITTER,
        'facebook.com': Platform.FACEBOOK, 'fb.watch': Platform.FACEBOOK,
        'reddit.com': Platform.REDDIT,
        'vimeo.com': Platform.VIMEO,
        'twitch.tv': Platform.TWITCH,
        'dailymotion.com': Platform.DAILYMOTION,
        'soundcloud.com': Platform.SOUNDCLOUD,
        'bilibili.com': Platform.BILIBILI,
    }
    for key, plat in platform_map.items():
        if key in domain:
            return plat
    return Platform.GENERIC


def _build_metadata(info: dict, url: str) -> MediaMetadata:
    """Build MediaMetadata from yt-dlp info dict"""
    platform = _parse_platform(url)

    # Parse author
    author = None
    uploader = info.get('uploader') or info.get('channel')
    if uploader:
        author = Author(
            name=uploader,
            id=info.get('uploader_id') or info.get('channel_id'),
            url=info.get('uploader_url') or info.get('channel_url')
        )

    # Parse thumbnails
    thumbnails = []
    for t in (info.get('thumbnails') or []):
        if t.get('url'):
            thumbnails.append(Thumbnail(
                url=t['url'],
                width=t.get('width'),
                height=t.get('height')
            ))

    # Parse video formats
    video_formats = []
    audio_formats = []
    for f in (info.get('formats') or []):
        if f.get('vcodec') and f['vcodec'] != 'none':
            video_formats.append(VideoFormat(
                format_id=f.get('format_id', ''),
                extension=f.get('ext', 'mp4'),
                quality=f.get('format_note', ''),
                width=f.get('width'),
                height=f.get('height'),
                fps=f.get('fps'),
                vcodec=f.get('vcodec'),
                acodec=f.get('acodec'),
                filesize=f.get('filesize') or f.get('filesize_approx')
            ))
        if f.get('acodec') and f['acodec'] != 'none' and (not f.get('vcodec') or f['vcodec'] == 'none'):
            audio_formats.append(AudioFormat(
                format_id=f.get('format_id', ''),
                extension=f.get('ext', 'mp3'),
                quality=f.get('format_note', ''),
                acodec=f.get('acodec'),
                abr=f.get('abr'),
                filesize=f.get('filesize') or f.get('filesize_approx')
            ))

    # Parse upload date
    upload_date = None
    date_str = info.get('upload_date')
    if date_str and len(date_str) == 8:
        try:
            upload_date = datetime.strptime(date_str, '%Y%m%d')
        except ValueError:
            pass

    return MediaMetadata(
        id=info.get('id', ''),
        title=info.get('title', 'Untitled'),
        url=info.get('webpage_url') or url,
        platform=platform,
        media_type=MediaType.VIDEO if video_formats else MediaType.AUDIO,
        description=info.get('description'),
        duration=info.get('duration'),
        view_count=info.get('view_count'),
        like_count=info.get('like_count'),
        author=author,
        upload_date=upload_date,
        thumbnails=thumbnails,
        video_formats=video_formats,
        audio_formats=audio_formats,
        categories=info.get('categories') or [],
        tags=info.get('tags') or [],
        raw_data=info
    )


# =============================================================================
# Extract Functions
# =============================================================================

async def extract_metadata(url: str) -> Optional[MediaMetadata]:
    """Extract media metadata from URL using yt-dlp"""
    if not HAS_YTDLP:
        logger.warning("yt-dlp not available for metadata extraction")
        return None

    info = await _run_ytdlp([url])
    if info:
        return _build_metadata(info, url)
    return None


async def extract_playlist(url: str) -> Optional[PlaylistInfo]:
    """Extract playlist information from URL using yt-dlp"""
    if not HAS_YTDLP:
        logger.warning("yt-dlp not available for playlist extraction")
        return None

    entries_data = await _run_ytdlp_multi([url])
    if not entries_data:
        return None

    # Get playlist-level info
    cmd = ['yt-dlp', '--dump-single-json', '--no-download', '--no-warnings',
           '--flat-playlist', url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        playlist_info = json.loads(stdout.decode('utf-8', errors='replace')) if stdout else {}
    except Exception:
        playlist_info = {}

    platform = _parse_platform(url)

    # Parse entries
    entries = []
    for e in entries_data:
        entry_url = e.get('url') or e.get('webpage_url') or ''
        if not entry_url and e.get('id'):
            if 'youtube' in url.lower():
                entry_url = f"https://www.youtube.com/watch?v={e['id']}"
        entries.append(MediaMetadata(
            id=e.get('id', ''),
            title=e.get('title', 'Untitled'),
            url=entry_url,
            platform=platform,
            media_type=MediaType.VIDEO,
            duration=e.get('duration'),
        ))

    # Author
    author = None
    uploader = playlist_info.get('uploader') or playlist_info.get('channel')
    if uploader:
        author = Author(name=uploader)

    return PlaylistInfo(
        id=playlist_info.get('id', ''),
        title=playlist_info.get('title', 'Playlist'),
        url=url,
        platform=platform,
        description=playlist_info.get('description'),
        author=author,
        video_count=len(entries),
        entries=entries
    )


async def extract_page(url: str) -> Optional[ScrapedPage]:
    """Scrape and extract content from a web page"""
    if not HAS_AIOHTTP:
        logger.warning("aiohttp not available for page extraction")
        return None

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return ScrapedPage(url=url, success=False, error=f"HTTP {resp.status}")
                html = await resp.text()
    except Exception as e:
        return ScrapedPage(url=url, success=False, error=str(e))

    extractor = HTMLExtractor()
    return extractor.parse_html(html, url)


async def extract_streaming_sources(url: str) -> List[dict]:
    """Extract video/audio source URLs from a streaming page"""
    if not HAS_YTDLP:
        return []

    cmd = ['yt-dlp', '--dump-json', '--no-download', '--no-warnings', url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        if stdout:
            info = json.loads(stdout.decode('utf-8', errors='replace'))
            sources = []
            for f in (info.get('formats') or []):
                sources.append({
                    'url': f.get('url', ''),
                    'format_id': f.get('format_id', ''),
                    'ext': f.get('ext', ''),
                    'quality': f.get('format_note', ''),
                    'width': f.get('width'),
                    'height': f.get('height'),
                    'fps': f.get('fps'),
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec'),
                    'filesize': f.get('filesize'),
                })
            return sources
    except Exception as e:
        logger.debug(f"Streaming source extraction failed: {e}")
    return []


async def smart_extract(url: str) -> dict:
    """Auto-detect content type and extract appropriately"""
    result = {'url': url, 'type': 'unknown', 'data': None}

    # Check if it's a playlist
    if any(kw in url.lower() for kw in ['playlist', '/sets/', '/album/']):
        playlist = await extract_playlist(url)
        if playlist:
            result['type'] = 'playlist'
            result['data'] = playlist
            return result

    # Try media extraction
    metadata = await extract_metadata(url)
    if metadata:
        result['type'] = 'media'
        result['data'] = metadata
        return result

    # Fall back to page scraping
    page = await extract_page(url)
    if page:
        result['type'] = 'page'
        result['data'] = page
        return result

    return result


# =============================================================================
# HTML Extractor Class
# =============================================================================

class HTMLExtractor:
    """Extract structured data from HTML content"""

    def parse_html(self, html: str, url: str) -> ScrapedPage:
        """Parse HTML and extract all content"""
        page = ScrapedPage(url=url)
        base_domain = urlparse(url).scheme + "://" + urlparse(url).netloc

        if HAS_BS4 and BeautifulSoup:
            soup = BeautifulSoup(html, 'html.parser')
            page.metadata = self._extract_meta(soup, url)
            page.text_content = self._extract_text(soup)
            page.links = self._extract_links(soup, base_domain)
            page.images = self._extract_images(soup, base_domain)
            page.videos = self._extract_video_sources(soup, base_domain)
        else:
            # Regex fallback
            page.metadata = self._extract_meta_regex(html, url)
            page.text_content = self._extract_text_regex(html)
            page.links = self._extract_links_regex(html, base_domain)
            page.images = self._extract_images_regex(html, base_domain)
            page.videos = []

        return page

    # --- BeautifulSoup methods ---

    def _extract_meta(self, soup, url: str) -> PageMetadata:
        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ''
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        desc = desc_tag.get('content', '') if desc_tag else ''
        kw_tag = soup.find('meta', attrs={'name': 'keywords'})
        keywords = [k.strip() for k in kw_tag.get('content', '').split(',')] if kw_tag else []
        og_img = soup.find('meta', attrs={'property': 'og:image'})
        og_image = og_img.get('content') if og_img else None
        return PageMetadata(url=url, title=title, description=desc,
                          keywords=keywords, og_image=og_image)

    def _extract_text(self, soup) -> ExtractedText:
        text = ExtractedText()
        title_tag = soup.find('title')
        text.title = title_tag.get_text(strip=True) if title_tag else ''
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        text.description = desc_tag.get('content', '') if desc_tag else ''
        for h in soup.find_all(re.compile(r'^h[1-6]$')):
            text.headings.append({'level': int(h.name[1]), 'text': h.get_text(strip=True)})
        for p in soup.find_all('p'):
            t = p.get_text(strip=True)
            if t:
                text.paragraphs.append(t)
        body = soup.get_text()
        text.emails = list(set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', body)))
        text.phones = list(set(re.findall(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,15}', body)))
        text.word_count = len(body.split())
        return text

    def _extract_links(self, soup, base: str) -> List[ExtractedLink]:
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith(('javascript:', '#', 'mailto:')):
                continue
            if not href.startswith('http'):
                href = urljoin(base, href)
            link_type = 'internal' if urlparse(base).netloc in href else 'external'
            links.append(ExtractedLink(url=href, text=a.get_text(strip=True), link_type=link_type))
        return links

    def _extract_images(self, soup, base: str) -> List[ExtractedImage]:
        images = []
        for img in soup.find_all('img', src=True):
            src = img['src']
            if not src.startswith('http'):
                src = urljoin(base, src)
            images.append(ExtractedImage(
                url=src, alt=img.get('alt'),
                width=int(img['width']) if img.get('width', '').isdigit() else None,
                height=int(img['height']) if img.get('height', '').isdigit() else None
            ))
        return images

    def _extract_video_sources(self, soup, base: str) -> List[MediaMetadata]:
        videos = []
        for vid in soup.find_all(['video', 'iframe']):
            src = vid.get('src') or ''
            if vid.name == 'video':
                source = vid.find('source')
                if source:
                    src = source.get('src', '')
            if src:
                if not src.startswith('http'):
                    src = urljoin(base, src)
                videos.append(MediaMetadata(
                    id=src, title=vid.get('title', src),
                    url=src, platform=Platform.GENERIC,
                    media_type=MediaType.VIDEO
                ))
        return videos

    # --- Regex fallback methods ---

    def _extract_meta_regex(self, html: str, url: str) -> PageMetadata:
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        desc_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', html, re.I)
        og_m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']*)["\']', html, re.I)
        return PageMetadata(
            url=url,
            title=title_m.group(1).strip() if title_m else '',
            description=desc_m.group(1) if desc_m else '',
            og_image=og_m.group(1) if og_m else None
        )

    def _extract_text_regex(self, html: str) -> ExtractedText:
        text = ExtractedText()
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        text.title = title_m.group(1).strip() if title_m else ''
        clean = re.sub(r'<[^>]+>', ' ', html)
        text.emails = list(set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', clean)))
        text.word_count = len(clean.split())
        return text

    def _extract_links_regex(self, html: str, base: str) -> List[ExtractedLink]:
        links = []
        for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.I):
            href = m.group(1)
            if href.startswith(('javascript:', '#')):
                continue
            if not href.startswith('http'):
                href = urljoin(base, href)
            links.append(ExtractedLink(url=href))
        return links

    def _extract_images_regex(self, html: str, base: str) -> List[ExtractedImage]:
        images = []
        for m in re.finditer(r'<img\s+[^>]*src=["\']([^"\']+)["\']', html, re.I):
            src = m.group(1)
            if not src.startswith('http'):
                src = urljoin(base, src)
            images.append(ExtractedImage(url=src))
        return images


# Aliases for backward compatibility
class MediaExtractor(HTMLExtractor):
    """Alias for HTMLExtractor — extracts media from HTML"""
    pass

class StreamingExtractor(HTMLExtractor):
    """Alias for HTMLExtractor — extracts streaming sources"""
    pass