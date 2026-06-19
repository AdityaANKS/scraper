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


@dataclass
class PlaylistDownloadResult:
    """Result of a playlist download operation"""
    success: bool = False
    playlist_title: str = ""
    total: int = 0
    downloaded: int = 0
    failed: int = 0
    skipped: int = 0
    total_bytes: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


__all__ = [
    'Author', 'Thumbnail', 'VideoFormat', 'AudioFormat',
    'MediaMetadata', 'DownloadProgress', 'DownloadResult',
    'PlaylistInfo', 'ExtractedText', 'ExtractedLink', 
    'ExtractedImage', 'PageMetadata', 'ScrapedPage', 'ScrapeJob',
    'PlaylistDownloadResult'
]