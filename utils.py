"""
================================================================================
UTILS.PY - Utility Functions
================================================================================
"""

import os
import sys
import re
import json
import hashlib
import subprocess
import asyncio
import unicodedata
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse, urljoin

from config import config, Platform, PLATFORM_PATTERNS, STREAMING_HOSTS

# =============================================================================
# System Info
# =============================================================================

IS_WINDOWS = sys.platform == 'win32'


# =============================================================================
# Logging Setup
# =============================================================================

# Define custom log formats
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[94m',    # Blue
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[1;91m', # Bold Red
        'SUCCESS': '\033[1;92m' # Bold Green
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, getattr(self, 'RESET', ''))
        message = super().format(record)
        return f"{color}{message}{self.RESET}"

# Setup root logger
logger = logging.getLogger('scraper')
logger.setLevel(logging.DEBUG)

# File handler
os.makedirs(os.path.dirname(config.paths.log) if os.path.dirname(config.paths.log) else '.', exist_ok=True)
file_handler = logging.FileHandler(config.paths.log, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = ColoredFormatter('[%(levelname)s] %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Custom success level
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, 'SUCCESS')
def success(self, message, *args, **kws):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kws)
logging.Logger.success = success


# =============================================================================
# Console Output (Legacy Wrappers)
# =============================================================================

def safe_print(msg: str = "", end: str = "\n") -> None:
    """Print with encoding safety for Windows (legacy)"""
    try:
        safe_msg = ''.join(c if ord(c) < 128 else '?' for c in str(msg))
        sys.stdout.write(safe_msg + end)
        sys.stdout.flush()
    except Exception:
        pass


def log_info(msg: str) -> None:
    logger.info(msg)


def log_warn(msg: str) -> None:
    logger.warning(msg)


def log_error(msg: str) -> None:
    logger.error(msg)


def log_success(msg: str) -> None:
    logger.success(msg)


def log_debug(msg: str) -> None:
    """Write to log file only"""
    logger.debug(msg)


# =============================================================================
# String Utilities
# =============================================================================

def sanitize_filename(name: str, max_length: int = 200, replacement: str = "_") -> str:
    """Sanitize string for use as filename"""
    if not name:
        return "unnamed"
    
    # Normalize Unicode
    name = unicodedata.normalize('NFKD', str(name))
    
    # Remove/replace invalid characters
    invalid_chars = '<>:"/\\|?*\x00'
    for char in invalid_chars:
        name = name.replace(char, replacement)
    
    # Replace special chars
    name = ''.join(c if ord(c) < 0x10000 and c.isprintable() else replacement for c in name)
    
    # Clean up
    name = re.sub(rf'{re.escape(replacement)}+', replacement, name)
    name = name.strip(f'. {replacement}')
    
    # Truncate
    if len(name) > max_length:
        name = name[:max_length].rsplit(' ', 1)[0].rstrip(f'. {replacement}')
    
    return name or "unnamed"


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds to human readable duration"""
    if not seconds or seconds < 0:
        return "0:00"
    
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


# =============================================================================
# URL Utilities
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize URL for consistency"""
    if not url:
        return ""
    
    url = url.strip()
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    return url.rstrip('/')


def get_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def detect_platform(url: str) -> Platform:
    """Detect platform from URL"""
    url_lower = url.lower()
    
    # Check for playlist first
    if 'youtube.com' in url_lower:
        if 'list=' in url_lower:
            return Platform.YOUTUBE_PLAYLIST
        if any(x in url_lower for x in ['/watch', '/shorts', 'youtu.be']):
            return Platform.YOUTUBE
    
    # Check patterns
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in url_lower:
                return platform
    
    # Check streaming hosts
    for host in STREAMING_HOSTS:
        if host in url_lower:
            return Platform.STREAMING
    
    # Check for direct media
    ext = os.path.splitext(url.split('?')[0])[1].lower()
    if ext in config.VIDEO_EXTENSIONS | config.AUDIO_EXTENSIONS:
        return Platform.DIRECT
    
    if '.m3u8' in url_lower or '.mpd' in url_lower:
        return Platform.DIRECT
    
    return Platform.GENERIC


def is_streaming_site(url: str) -> bool:
    """Check if URL is from a streaming site"""
    url_lower = url.lower()
    patterns = [
        'hianime', 'gogoanime', '9anime', 'aniwatch', 'animesuge',
        'animepahe', 'animixplay', 'kaido', 'aniwave', 'anitaku',
        'crunchyroll', 'funimation'
    ]
    return any(p in url_lower for p in patterns)


def is_supported_platform(url: str) -> bool:
    """Check if URL is from a supported platform"""
    platform = detect_platform(url)
    return platform != Platform.GENERIC


# =============================================================================
# File Utilities
# =============================================================================

def get_unique_filepath(filepath: str) -> str:
    """Get unique filepath by adding counter if exists"""
    if not os.path.exists(filepath):
        return filepath
    
    base, ext = os.path.splitext(filepath)
    counter = 1
    
    while os.path.exists(filepath):
        filepath = f"{base} ({counter}){ext}"
        counter += 1
    
    return filepath


def get_file_size(filepath: str) -> int:
    """Get file size in bytes"""
    try:
        return os.path.getsize(filepath)
    except Exception:
        return 0


def cleanup_temp_files(max_age_hours: int = 24) -> int:
    """Remove old temp files"""
    from datetime import timedelta
    
    removed = 0
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    
    temp_dir = config.paths.temp
    if not os.path.exists(temp_dir):
        return 0
    
    for filename in os.listdir(temp_dir):
        filepath = os.path.join(temp_dir, filename)
        try:
            if os.path.isfile(filepath):
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    removed += 1
        except Exception:
            pass
    
    return removed


# =============================================================================
# Process Utilities
# =============================================================================

def run_command(cmd: List[str], timeout: int = 300) -> Tuple[bool, str, str]:
    """Run command synchronously"""
    try:
        kwargs: Dict[str, Any] = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'stdin': subprocess.DEVNULL,
        }
        
        if IS_WINDOWS:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = si
        
        proc = subprocess.Popen(cmd, **kwargs)
        stdout, stderr = proc.communicate(timeout=timeout)
        
        def decode(data: bytes) -> str:
            if not data:
                return ""
            for enc in ['utf-8', 'cp1252', 'latin-1']:
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode('utf-8', errors='replace')
        
        return proc.returncode == 0, decode(stdout), decode(stderr)
    
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, "", "Timeout"
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, "", str(e)


async def run_command_async(cmd: List[str], timeout: int = 7200) -> Tuple[bool, str, str]:
    """Run command asynchronously"""
    try:
        kwargs: Dict[str, Any] = {
            'stdout': asyncio.subprocess.PIPE,
            'stderr': asyncio.subprocess.PIPE,
            'stdin': asyncio.subprocess.DEVNULL,
        }
        
        if IS_WINDOWS:
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        
        proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return False, "", "Timeout"
        
        def decode(data: bytes) -> str:
            if not data:
                return ""
            for enc in ['utf-8', 'cp1252', 'latin-1']:
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode('utf-8', errors='replace')
        
        return proc.returncode == 0, decode(stdout), decode(stderr)
    
    except Exception as e:
        return False, "", str(e)


# =============================================================================
# Dependency Checking
# =============================================================================

def check_ffmpeg() -> Tuple[bool, str]:
    """Check if FFmpeg is available"""
    ok, out, _ = run_command(['ffmpeg', '-version'], 10)
    if ok and out:
        version = out.split('\n')[0][:60]
        return True, version
    return False, ""


def check_ffprobe() -> bool:
    """Check if FFprobe is available"""
    ok, _, _ = run_command(['ffprobe', '-version'], 10)
    return ok


def check_ytdlp() -> Tuple[bool, str]:
    """Check if yt-dlp is available"""
    ok, out, _ = run_command(['yt-dlp', '--version'], 10)
    if ok and out:
        return True, out.strip()
    return False, ""


def get_dependencies(refresh: bool = False) -> Dict[str, Tuple[bool, str]]:
    """Check all dependencies"""
    deps = {}
    
    ok, ver = check_ffmpeg()
    deps['ffmpeg'] = (ok, ver)
    deps['ffprobe'] = (check_ffprobe(), "")
    
    ok, ver = check_ytdlp()
    deps['yt-dlp'] = (ok, ver)
    
    packages = ['aiohttp', 'aiofiles', 'bs4', 'requests']
    for pkg in packages:
        try:
            __import__(pkg)
            deps[pkg] = (True, "")
        except ImportError:
            deps[pkg] = (False, "")
    
    return deps


# Check on import
HAS_FFMPEG, FFMPEG_VERSION = check_ffmpeg()
HAS_FFPROBE = check_ffprobe()
HAS_YTDLP, YTDLP_VERSION = check_ytdlp()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Console
    'safe_print', 'log_info', 'log_warn', 'log_error', 'log_success', 'log_debug',
    
    # String
    'sanitize_filename', 'format_size', 'format_duration',
    
    # URL
    'normalize_url', 'get_domain', 'detect_platform', 'is_streaming_site',
    'is_supported_platform',
    
    # File
    'get_unique_filepath', 'get_file_size', 'cleanup_temp_files',
    
    # Process
    'run_command', 'run_command_async',
    
    # Dependencies
    'check_ffmpeg', 'check_ffprobe', 'check_ytdlp', 'get_dependencies',
    'HAS_FFMPEG', 'HAS_FFPROBE', 'HAS_YTDLP', 'FFMPEG_VERSION', 'YTDLP_VERSION',
    
    # Constants
    'IS_WINDOWS',
]