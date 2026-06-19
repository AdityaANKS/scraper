"""
================================================================================
CONFIG.PY - Configuration Management
================================================================================
Central configuration for the entire scraper system.
All settings, paths, and constants are defined here.
================================================================================
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum, auto
from pathlib import Path


# =============================================================================
# Enums
# =============================================================================

class Platform(Enum):
    """Supported platforms"""
    YOUTUBE = auto()
    YOUTUBE_PLAYLIST = auto()
    INSTAGRAM = auto()
    TIKTOK = auto()
    TWITTER = auto()
    FACEBOOK = auto()
    REDDIT = auto()
    VIMEO = auto()
    TWITCH = auto()
    DAILYMOTION = auto()
    SOUNDCLOUD = auto()
    PINTEREST = auto()
    TUMBLR = auto()
    LINKEDIN = auto()
    SPOTIFY = auto()
    BILIBILI = auto()
    # Streaming sites
    HIANIME = auto()
    GOGOANIME = auto()
    NINEANIME = auto()
    CRUNCHYROLL = auto()
    # Generic
    STREAMING = auto()
    DIRECT = auto()
    GENERIC = auto()


class MediaType(Enum):
    """Media types"""
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    TEXT = "text"
    SUBTITLE = "subtitle"
    THUMBNAIL = "thumbnail"
    DOCUMENT = "document"
    ARCHIVE = "archive"


class ContentType(Enum):
    """Content categories for organization"""
    ENTERTAINMENT = "entertainment"
    MUSIC = "music"
    EDUCATION = "education"
    NEWS = "news"
    SPORTS = "sports"
    GAMING = "gaming"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    ART = "art"
    FOOD = "food"
    TRAVEL = "travel"
    FASHION = "fashion"
    FITNESS = "fitness"
    BUSINESS = "business"
    ANIME = "anime"
    DOCUMENTARY = "documentary"
    PODCAST = "podcast"
    UNKNOWN = "unknown"


class Quality(Enum):
    """Video quality presets"""
    Q_8K_60 = ("4320p60", 4320, 60)
    Q_8K_30 = ("4320p", 4320, 30)
    Q_4K_60 = ("2160p60", 2160, 60)
    Q_4K_30 = ("2160p", 2160, 30)
    Q_1440_60 = ("1440p60", 1440, 60)
    Q_1440_30 = ("1440p", 1440, 30)
    Q_1080_60 = ("1080p60", 1080, 60)
    Q_1080_30 = ("1080p", 1080, 30)
    Q_720_60 = ("720p60", 720, 60)
    Q_720_30 = ("720p", 720, 30)
    Q_480 = ("480p", 480, 30)
    Q_360 = ("360p", 360, 30)
    Q_240 = ("240p", 240, 30)
    Q_144 = ("144p", 144, 30)
    BEST = ("best", 0, 0)
    WORST = ("worst", 0, 0)
    
    def __init__(self, label: str, height: int, fps: int):
        self.label = label
        self.height = height
        self.fps = fps


class AudioQuality(Enum):
    """Audio quality presets"""
    Q_320 = ("320k", 320)
    Q_256 = ("256k", 256)
    Q_192 = ("192k", 192)
    Q_128 = ("128k", 128)
    Q_96 = ("96k", 96)
    Q_64 = ("64k", 64)
    BEST = ("best", 0)
    
    def __init__(self, label: str, bitrate: int):
        self.label = label
        self.bitrate = bitrate


# =============================================================================
# Path Configuration
# =============================================================================

class PathConfig:
    """Path configuration"""
    
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = base_dir
        else:
            import platform
            if platform.system() == 'Windows':
                self.base_dir = os.path.join(os.environ.get('USERPROFILE', ''), 'scraper')
            else:
                self.base_dir = os.path.join(os.path.expanduser('~'), 'scraper')
    
    @property
    def videos(self) -> str:
        return os.path.join(self.base_dir, "videos")
    
    @property
    def audio(self) -> str:
        return os.path.join(self.base_dir, "audio")
    
    @property
    def images(self) -> str:
        return os.path.join(self.base_dir, "images")
    
    @property
    def text(self) -> str:
        return os.path.join(self.base_dir, "text")
    
    @property
    def subtitles(self) -> str:
        return os.path.join(self.base_dir, "subtitles")
    
    @property
    def thumbnails(self) -> str:
        return os.path.join(self.base_dir, "thumbnails")
    
    @property
    def temp(self) -> str:
        return os.path.join(self.base_dir, "temp")
    
    @property
    def cookies(self) -> str:
        return os.path.join(self.base_dir, "cookies")
    
    @property
    def cache(self) -> str:
        return os.path.join(self.base_dir, "cache")
    
    @property
    def osint(self) -> str:
        return os.path.join(self.base_dir, "OSINT")
    
    @property
    def database(self) -> str:
        return os.path.join(self.base_dir, "scraper.db")
    
    @property
    def log(self) -> str:
        return os.path.join(self.base_dir, "scraper.log")
        
    @property
    def scraped_data(self) -> str:
        return os.path.join(self.base_dir, "scraped_data")
    
    @property
    def ai_data(self) -> str:
        return os.path.join(self.base_dir, "ai_data")
    
    @property
    def ai_reports(self) -> str:
        return os.path.join(self.base_dir, "ai_reports")
    
    def init_all(self) -> None:
        """Create all directories"""
        dirs = [
            self.base_dir, self.videos, self.audio, self.images,
            self.text, self.subtitles, self.thumbnails, self.temp,
            self.cookies, self.cache, self.osint, self.scraped_data,
            self.ai_data, self.ai_reports
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)


# =============================================================================
# Network Configuration
# =============================================================================

class NetworkConfig:
    """Network settings"""
    
    def __init__(self):
        self.request_timeout: int = 30
        self.download_timeout: int = 7200
        self.chunk_size: int = 1024 * 1024  # 1MB
        self.max_retries: int = 3
        self.retry_delay: float = 2.0
        self.concurrent_downloads: int = 3
        self.rate_limit_per_min: int = 60
        self.user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# =============================================================================
# Media Configuration
# =============================================================================

class MediaConfig:
    """Media processing settings"""
    
    def __init__(self):
        self.default_video_quality: Quality = Quality.Q_1080_30
        self.default_audio_quality: AudioQuality = AudioQuality.Q_192
        self.default_video_format: str = "mp4"
        self.default_audio_format: str = "mp3"
        self.embed_thumbnail: bool = True
        self.embed_metadata: bool = True
        self.max_filename_length: int = 200
        self.organize_by_platform: bool = True
        self.organize_by_content_type: bool = True


# =============================================================================
# Scraper Configuration
# =============================================================================

class ScraperConfig:
    """Scraper behavior settings"""
    
    def __init__(self):
        self.extract_text: bool = True
        self.extract_images: bool = True
        self.extract_links: bool = True
        self.extract_metadata: bool = True
        self.follow_links: bool = False
        self.max_depth: int = 2
        self.same_domain_only: bool = True
        self.skip_duplicates: bool = True
        self.auto_categorize: bool = True
        self.save_raw_html: bool = False


# =============================================================================
# Bot Configuration
# =============================================================================

class BotConfig:
    """Bot module settings"""
    
    def __init__(self):
        self.enabled: bool = False
        self.headless: bool = True
        self.use_stealth: bool = True
        self.solve_cloudflare: bool = True
        self.rotate_user_agents: bool = True
        self.use_proxy: bool = False
        self.proxy_url: Optional[str] = None


# =============================================================================
# Constants
# =============================================================================

# Platform detection patterns
PLATFORM_PATTERNS: Dict[Platform, List[str]] = {
    Platform.YOUTUBE: ['youtube.com/watch', 'youtu.be/', 'youtube.com/shorts'],
    Platform.YOUTUBE_PLAYLIST: ['youtube.com/playlist', 'list='],
    Platform.INSTAGRAM: ['instagram.com/p/', 'instagram.com/reel/', 'instagram.com/tv/'],
    Platform.TIKTOK: ['tiktok.com/', 'vm.tiktok.com'],
    Platform.TWITTER: ['twitter.com/', 'x.com/'],
    Platform.FACEBOOK: ['facebook.com/', 'fb.watch', 'fb.com'],
    Platform.REDDIT: ['reddit.com/', 'redd.it/', 'v.redd.it'],
    Platform.VIMEO: ['vimeo.com/'],
    Platform.TWITCH: ['twitch.tv/', 'clips.twitch.tv'],
    Platform.DAILYMOTION: ['dailymotion.com/', 'dai.ly/'],
    Platform.SOUNDCLOUD: ['soundcloud.com/'],
    Platform.PINTEREST: ['pinterest.com/', 'pin.it/'],
    Platform.TUMBLR: ['tumblr.com/'],
    Platform.LINKEDIN: ['linkedin.com/'],
    Platform.SPOTIFY: ['spotify.com/', 'open.spotify.com'],
    Platform.BILIBILI: ['bilibili.com/', 'b23.tv/'],
    Platform.HIANIME: ['hianime.to', 'hianime.sx'],
    Platform.GOGOANIME: ['gogoanime', 'anitaku'],
    Platform.NINEANIME: ['9anime', 'aniwave'],
    Platform.CRUNCHYROLL: ['crunchyroll.com/'],
}

# File extensions
VIDEO_EXTENSIONS: Set[str] = {
    '.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.wmv', '.m4v', '.ts'
}

AUDIO_EXTENSIONS: Set[str] = {
    '.mp3', '.m4a', '.aac', '.opus', '.ogg', '.wav', '.flac', '.wma'
}

IMAGE_EXTENSIONS: Set[str] = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico', '.tiff'
}

DOCUMENT_EXTENSIONS: Set[str] = {
    '.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx'
}

# Streaming hosts
STREAMING_HOSTS: Set[str] = {
    'vidplay', 'vidstream', 'mp4upload', 'streamtape', 'doodstream',
    'filemoon', 'streamwish', 'vidhide', 'vidguard', 'megacloud',
    'rapid-cloud', 'streamsb', 'mixdrop', 'upstream', 'vtube',
    'vidoza', 'voe.sx', 'streamlare', 'fembed', 'kwik'
}


# =============================================================================
# Main Configuration Class
# =============================================================================

class Config:
    """Master configuration class"""
    
    def __init__(self, base_dir: Optional[str] = None):
        # Initialize sub-configs
        self.paths = PathConfig(base_dir)
        self.network = NetworkConfig()
        self.media = MediaConfig()
        self.scraper = ScraperConfig()
        self.bot = BotConfig()
        
        # Constants (reference module-level)
        self.PLATFORM_PATTERNS = PLATFORM_PATTERNS
        self.VIDEO_EXTENSIONS = VIDEO_EXTENSIONS
        self.AUDIO_EXTENSIONS = AUDIO_EXTENSIONS
        self.IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
        self.DOCUMENT_EXTENSIONS = DOCUMENT_EXTENSIONS
        self.STREAMING_HOSTS = STREAMING_HOSTS
        
        # Initialize directories
        self.paths.init_all()
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> 'Config':
        """Load configuration from file or create default"""
        # Could extend to load from JSON/YAML file
        return cls()
    
    def save(self, config_path: Optional[str] = None) -> None:
        """Save configuration to file"""
        # Could implement JSON/YAML saving
        pass


# =============================================================================
# Global Configuration Instance
# =============================================================================

# Create global config instance
config = Config()


# =============================================================================
# Convenience Exports
# =============================================================================

__all__ = [
    # Enums
    'Platform',
    'MediaType', 
    'ContentType',
    'Quality',
    'AudioQuality',
    
    # Config classes
    'PathConfig',
    'NetworkConfig',
    'MediaConfig',
    'ScraperConfig',
    'BotConfig',
    'Config',
    
    # Global instance
    'config',
    
    # Constants
    'PLATFORM_PATTERNS',
    'VIDEO_EXTENSIONS',
    'AUDIO_EXTENSIONS',
    'IMAGE_EXTENSIONS',
    'DOCUMENT_EXTENSIONS',
    'STREAMING_HOSTS',
]