"""
================================================================================
IMAGE.PY - Professional Image Downloader, Scraper & Format Handler
================================================================================
Version: 1.0
Last Updated: 2025

Fixes the broken download_image in scraper.py:
  • Detects ACTUAL format via magic bytes (not just URL extension)
  • Auto-converts WebP/AVIF → PNG/JPG so images OPEN everywhere
  • Validates image integrity after download
  • Deduplicates via content hash

FEATURES:
---------
  • Single image download with format fix
  • Multi-URL download from a list / file
  • Scrape ANY webpage → extract ALL images → bulk download
  • Smart image extraction (img, srcset, og:image, CSS backgrounds, etc.)
  • Concurrent downloads with rate limiting
  • Progress tracking
  • Content-hash deduplication (skip already downloaded)
  • Organize by domain / custom folders
  • Filter by size, format, dimensions

SUPPORTED FORMATS (input):
--------------------------
  JPEG, PNG, GIF, WebP, AVIF, BMP, TIFF, ICO, SVG, HEIC

AUTO-CONVERSION (output):
-------------------------
  WebP  → PNG  (Windows compatible)
  AVIF  → PNG  (universal support)
  HEIC  → JPG  (Apple format → universal)
  BMP   → PNG  (smaller file size)
  TIFF  → PNG  (web-friendly)

SAVE PATH:
----------
  Default: ~/scraper/images/
  OSINT:   ~/scraper/OSINT/media/images/

USAGE:
------
  # Single download
  from image import ImageDownloader
  async with ImageDownloader() as dl:
      result = await dl.download("https://example.com/photo.webp")

  # Bulk from URL list
  results = await dl.download_many([url1, url2, url3])

  # Scrape page → download all images
  results = await dl.scrape_and_download("https://example.com/gallery")

  # CLI
  python image.py https://example.com/photo.jpg
  python image.py --scrape https://example.com/gallery
  python image.py --list urls.txt

================================================================================
"""

import os
import re
import sys
import json
import struct
import asyncio
import hashlib
import shutil
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, unquote, quote

logger = logging.getLogger(__name__)

# =============================================================================
# Optional Dependencies
# =============================================================================

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None

# ImageMagick detection — check PATH first, then common install dirs
HAS_IMAGEMAGICK = False
IMAGEMAGICK_PATH = 'magick'  # Default: assume it's in PATH
try:
    import subprocess as _sp
    import glob as _glob
    _r = _sp.run(['magick', '--version'], capture_output=True, timeout=5)
    if _r.returncode == 0:
        HAS_IMAGEMAGICK = True
    else:
        raise FileNotFoundError
except Exception:
    # Search common Windows install directories
    _search_paths = _glob.glob(r'C:\Program Files\ImageMagick*') + \
                    _glob.glob(r'C:\Program Files (x86)\ImageMagick*')
    for _dir in _search_paths:
        _exe = os.path.join(_dir, 'magick.exe')
        if os.path.isfile(_exe):
            try:
                _r = _sp.run([_exe, '--version'], capture_output=True, timeout=5)
                if _r.returncode == 0:
                    HAS_IMAGEMAGICK = True
                    IMAGEMAGICK_PATH = _exe
                    break
            except Exception:
                pass

try:
    from PIL import Image as PILImage
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    PILImage = None

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False

try:
    from config import config
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False
    config = None

try:
    from utils import (
        safe_print, log_info, log_warn, log_error, log_success, log_debug,
        format_size, sanitize_filename, get_unique_filepath,
        run_command, HAS_FFMPEG
    )
    HAS_UTILS = True
except ImportError:
    HAS_UTILS = False
    HAS_FFMPEG = False

    # Minimal fallbacks if utils not available
    def safe_print(t=""): 
        try: print(t)
        except UnicodeEncodeError: print(t.encode('ascii', 'replace').decode())
    def log_info(t): safe_print(f"  [i] {t}")
    def log_warn(t): safe_print(f"  [!] {t}")
    def log_error(t): safe_print(f"  [X] {t}")
    def log_success(t): safe_print(f"  [OK] {t}")
    def log_debug(t): logger.debug(t)
    def format_size(b):
        for u in ['B','KB','MB','GB']:
            if b < 1024: return f"{b:.1f} {u}"
            b /= 1024
        return f"{b:.1f} TB"
    def sanitize_filename(n):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', n)[:200].strip('. ')
    def get_unique_filepath(p):
        if not os.path.exists(p): return p
        base, ext = os.path.splitext(p)
        i = 1
        while os.path.exists(f"{base}_{i}{ext}"): i += 1
        return f"{base}_{i}{ext}"
    def run_command(cmd, timeout=60):
        import subprocess
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout, r.stderr
        except Exception as e:
            return False, '', str(e)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser('~'), 'scraper', 'images')
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)

# Formats that most OS image viewers can open natively
UNIVERSAL_FORMATS = {'jpeg', 'jpg', 'png', 'gif', 'bmp', 'ico'}

# Formats that need conversion for universal compatibility
NEEDS_CONVERSION = {'webp', 'avif', 'heic', 'heif', 'tiff', 'tif'}

# Minimum image size to filter out tracking pixels (bytes)
MIN_IMAGE_SIZE = 1024  # 1KB - skip tiny tracker pixels

# Maximum concurrent downloads
MAX_CONCURRENT = 8

# Per-host delay (seconds) to avoid rate limiting
HOST_DELAY = 0.15


# =============================================================================
# Magic Byte Detection — Detect REAL format regardless of URL/extension
# =============================================================================

# File signature → (format_name, extension)
MAGIC_BYTES = [
    # Order matters — check longest/most specific signatures first
    (b'\x89PNG\r\n\x1a\n',                'png'),
    (b'\xff\xd8\xff',                      'jpg'),
    (b'GIF87a',                            'gif'),
    (b'GIF89a',                            'gif'),
    (b'RIFF',                              '_riff'),   # WebP check needs 2nd pass
    (b'BM',                                'bmp'),
    (b'\x00\x00\x01\x00',                 'ico'),
    (b'\x00\x00\x02\x00',                 'ico'),     # CUR format
    (b'II\x2a\x00',                        'tiff'),    # TIFF little-endian
    (b'MM\x00\x2a',                        'tiff'),    # TIFF big-endian
    (b'<svg',                              'svg'),
    (b'<?xml',                             '_xml'),    # Could be SVG
]


def detect_format(data: bytes) -> str:
    """
    Detect actual image format from file header bytes.
    Returns format name: 'jpg', 'png', 'gif', 'webp', 'avif', 'bmp', etc.
    Returns 'unknown' if not recognized.
    """
    if len(data) < 12:
        return 'unknown'

    # Check magic bytes
    for signature, fmt in MAGIC_BYTES:
        if data[:len(signature)] == signature:
            if fmt == '_riff':
                # RIFF container — check if it's WebP
                if len(data) >= 12 and data[8:12] == b'WEBP':
                    return 'webp'
                return 'unknown'
            elif fmt == '_xml':
                # XML — check if it's SVG
                header_text = data[:500].decode('utf-8', errors='ignore').lower()
                if '<svg' in header_text:
                    return 'svg'
                return 'unknown'
            return fmt

    # AVIF/HEIC detection (ISO Base Media File Format — ftyp box)
    # Structure: [4-byte size][4-byte 'ftyp'][4-byte brand]
    if len(data) >= 12:
        # ftyp can start at offset 0 or 4
        for offset in (0, 4):
            if data[offset:offset+4] == b'ftyp':
                brand = data[offset+4:offset+8].decode('ascii', errors='ignore').lower().strip('\x00')
                if brand in ('avif', 'avis'):
                    return 'avif'
                elif brand in ('heic', 'heix', 'hevc', 'mif1'):
                    return 'heic'
                break
        # Also check if ftyp is after size bytes
        if data[4:8] == b'ftyp':
            brand = data[8:12].decode('ascii', errors='ignore').lower().strip('\x00')
            if brand in ('avif', 'avis'):
                return 'avif'
            elif brand in ('heic', 'heix', 'hevc', 'mif1'):
                return 'heic'

    # JPEG XL
    if data[:2] == b'\xff\x0a':
        return 'jxl'
    if data[:12] == b'\x00\x00\x00\x0cJXL \r\n\x87\n':
        return 'jxl'

    return 'unknown'


def get_correct_extension(detected_format: str) -> str:
    """Get the correct file extension for a detected format"""
    ext_map = {
        'jpg': '.jpg', 'jpeg': '.jpg', 'png': '.png', 'gif': '.gif',
        'webp': '.webp', 'bmp': '.bmp', 'ico': '.ico', 'tiff': '.tiff',
        'tif': '.tiff', 'svg': '.svg', 'avif': '.avif', 'heic': '.heic',
        'heif': '.heic', 'jxl': '.jxl',
    }
    return ext_map.get(detected_format, f'.{detected_format}')


# =============================================================================
# Image Format Converter — Make every image openable
# =============================================================================

class ImageConverter:
    """
    Convert images to universally openable formats.
    Uses Pillow (preferred) or FFmpeg (fallback).
    """

    @staticmethod
    def needs_conversion(fmt: str) -> bool:
        """Check if format needs conversion for universal compatibility"""
        return fmt.lower() in NEEDS_CONVERSION

    @staticmethod
    def get_target_format(source_fmt: str) -> str:
        """Determine best target format for conversion"""
        # Formats with transparency → PNG
        if source_fmt in ('webp', 'avif', 'tiff', 'tif'):
            return 'png'
        # Photo formats → JPG (smaller)
        if source_fmt in ('heic', 'heif', 'jxl'):
            return 'jpg'
        return 'png'  # Default safe choice

    @staticmethod
    def convert(input_path: str, output_path: str = None,
                target_format: str = None) -> Tuple[bool, str]:
        """
        Convert image to target format.
        Returns (success, output_path).
        """
        if not os.path.exists(input_path):
            return False, input_path

        # Detect source format
        with open(input_path, 'rb') as f:
            header = f.read(64)
        source_fmt = detect_format(header)

        if not target_format:
            target_format = ImageConverter.get_target_format(source_fmt)

        if not output_path:
            base = os.path.splitext(input_path)[0]
            output_path = f"{base}.{target_format}"

        # Try Pillow first (best quality, most formats)
        if HAS_PILLOW:
            success = ImageConverter._convert_pillow(input_path, output_path, target_format)
            if success:
                return True, output_path

        # Fallback to ImageMagick
        if HAS_IMAGEMAGICK:
            success = ImageConverter._convert_imagemagick(input_path, output_path)
            if success:
                return True, output_path

        # Fallback to FFmpeg
        if HAS_FFMPEG:
            success = ImageConverter._convert_ffmpeg(input_path, output_path)
            if success:
                return True, output_path

        log_warn(f"Cannot convert {source_fmt} → {target_format} (install Pillow, ImageMagick, or FFmpeg)")
        return False, input_path

    @staticmethod
    def _convert_pillow(input_path: str, output_path: str,
                        target_format: str) -> bool:
        """Convert using Pillow"""
        try:
            img = PILImage.open(input_path)

            # Handle animated images (GIF, animated WebP)
            if getattr(img, 'is_animated', False) and target_format not in ('gif', 'webp'):
                # Save first frame only for static formats
                img.seek(0)

            # Handle transparency → RGBA for PNG, RGB for JPG
            if target_format in ('jpg', 'jpeg'):
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Composite on white background
                    background = PILImage.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                img.save(output_path, 'JPEG', quality=95, optimize=True)
            elif target_format == 'png':
                if img.mode == 'P' and 'transparency' in img.info:
                    img = img.convert('RGBA')
                img.save(output_path, 'PNG', optimize=True)
            elif target_format == 'gif':
                img.save(output_path, 'GIF')
            else:
                img.save(output_path)

            img.close()
            log_debug(f"Pillow converted: {os.path.basename(input_path)} → .{target_format}")
            return True

        except Exception as e:
            log_debug(f"Pillow conversion failed: {e}")
            return False

    @staticmethod
    def _convert_imagemagick(input_path: str, output_path: str) -> bool:
        """Convert using ImageMagick v7 (magick command — no 'convert' subcommand)"""
        try:
            _, out_ext = os.path.splitext(output_path)
            # IM7 syntax: magick input [options...] output
            cmd = [IMAGEMAGICK_PATH, input_path]

            # Format-specific optimisations
            if out_ext.lower() in ('.jpg', '.jpeg'):
                # Flatten transparency onto white, good JPEG quality
                cmd += [
                    '-background', 'white', '-flatten',
                    '-quality', '95',
                    '-sampling-factor', '4:2:0',
                    '-interlace', 'Plane',       # Progressive JPEG
                ]
            elif out_ext.lower() == '.png':
                cmd += ['-quality', '95']

            cmd += ['-strip', output_path]       # Remove metadata

            ok, _, err = run_command(cmd, 30)
            if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                log_debug(f"ImageMagick converted: {os.path.basename(input_path)}")
                return True
            elif err:
                log_debug(f"ImageMagick stderr: {err[:200]}")
        except Exception as e:
            log_debug(f"ImageMagick conversion failed: {e}")
        return False

    @staticmethod
    def _convert_ffmpeg(input_path: str, output_path: str) -> bool:
        """Convert using FFmpeg"""
        try:
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', input_path,
                '-frames:v', '1',  # Single frame (handles video thumbnails too)
                output_path
            ]
            ok, _, err = run_command(cmd, 30)
            if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                log_debug(f"FFmpeg converted: {os.path.basename(input_path)}")
                return True
        except Exception as e:
            log_debug(f"FFmpeg conversion failed: {e}")
        return False


# =============================================================================
# Image Validator — Verify downloaded images are valid
# =============================================================================

class ImageValidator:
    """Validate image files after download"""

    @staticmethod
    def validate(filepath: str) -> Dict[str, Any]:
        """
        Validate an image file.
        Returns dict with: valid, format, width, height, filesize, error
        """
        result = {
            'valid': False,
            'format': 'unknown',
            'width': 0,
            'height': 0,
            'filesize': 0,
            'error': None,
        }

        if not os.path.exists(filepath):
            result['error'] = 'File not found'
            return result

        filesize = os.path.getsize(filepath)
        result['filesize'] = filesize

        if filesize < 100:
            result['error'] = 'File too small (likely corrupt or empty)'
            return result

        # Read header for format detection
        with open(filepath, 'rb') as f:
            header = f.read(64)

        fmt = detect_format(header)
        result['format'] = fmt

        if fmt == 'unknown':
            result['error'] = 'Unrecognized image format'
            return result

        # Validate with Pillow if available
        if HAS_PILLOW and fmt != 'svg':
            try:
                img = PILImage.open(filepath)
                img.verify()  # Verify integrity without full decode
                # Re-open for dimensions (verify() invalidates)
                img = PILImage.open(filepath)
                result['width'] = img.width
                result['height'] = img.height
                result['mode'] = img.mode
                img.close()
                result['valid'] = True
            except Exception as e:
                result['error'] = f'Image corrupt: {str(e)[:100]}'
                return result
        else:
            # Without Pillow — basic validation by format header
            result['valid'] = fmt != 'unknown'
            # Try to get dimensions from headers
            dims = ImageValidator._get_dimensions_from_header(filepath, fmt)
            if dims:
                result['width'], result['height'] = dims

        return result

    @staticmethod
    def _get_dimensions_from_header(filepath: str, fmt: str) -> Optional[Tuple[int, int]]:
        """Extract dimensions from file header without Pillow"""
        try:
            with open(filepath, 'rb') as f:
                data = f.read(4096)

            if fmt == 'png' and len(data) >= 24:
                w = struct.unpack('>I', data[16:20])[0]
                h = struct.unpack('>I', data[20:24])[0]
                return (w, h)

            elif fmt in ('jpg', 'jpeg'):
                # Parse JPEG markers for SOF
                i = 2
                while i < len(data) - 9:
                    if data[i] != 0xFF:
                        break
                    marker = data[i + 1]
                    if marker in (0xC0, 0xC1, 0xC2):  # SOF0, SOF1, SOF2
                        h = struct.unpack('>H', data[i+5:i+7])[0]
                        w = struct.unpack('>H', data[i+7:i+9])[0]
                        return (w, h)
                    length = struct.unpack('>H', data[i+2:i+4])[0]
                    i += 2 + length

            elif fmt == 'gif' and len(data) >= 10:
                w = struct.unpack('<H', data[6:8])[0]
                h = struct.unpack('<H', data[8:10])[0]
                return (w, h)

            elif fmt == 'bmp' and len(data) >= 26:
                w = struct.unpack('<I', data[18:22])[0]
                h = abs(struct.unpack('<i', data[22:26])[0])
                return (w, h)

        except Exception:
            pass
        return None

    @staticmethod
    def is_tracking_pixel(filepath: str) -> bool:
        """Check if image is a 1x1 tracking pixel"""
        v = ImageValidator.validate(filepath)
        if v.get('width', 0) <= 2 and v.get('height', 0) <= 2:
            return True
        if v.get('filesize', 0) < 200:
            return True
        return False


# =============================================================================
# HTML Image Extractor — Find ALL images in a web page
# =============================================================================

class HTMLImageExtractor:
    """
    Extract image URLs from HTML using multiple strategies.
    Finds images that simple regex misses.
    """

    # Patterns for extracting image URLs from various HTML contexts
    IMG_PATTERNS = [
        # Standard img tags — src and data-src variants
        re.compile(
            r'<img\s[^>]*?(?:src|data-src|data-lazy-src|data-original|data-srcset)\s*=\s*'
            r'["\']([^"\']+?\.(?:jpe?g|png|gif|webp|avif|bmp|svg|ico|tiff?|heic)[^"\']*)["\']',
            re.I
        ),
        # Catch-all img src (any URL in img tag)
        re.compile(
            r'<img\s[^>]*?src\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        # srcset individual URLs
        re.compile(
            r'srcset\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        # <picture> <source> tags
        re.compile(
            r'<source\s[^>]*?srcset\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        # CSS background-image
        re.compile(
            r'background(?:-image)?\s*:\s*url\(\s*["\']?([^"\')\s]+)["\']?\s*\)',
            re.I
        ),
        # Open Graph image
        re.compile(
            r'<meta\s[^>]*?property\s*=\s*["\']og:image["\'][^>]*?content\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        re.compile(
            r'<meta\s[^>]*?content\s*=\s*["\']([^"\']+)["\'][^>]*?property\s*=\s*["\']og:image["\']',
            re.I
        ),
        # Twitter card image
        re.compile(
            r'<meta\s[^>]*?name\s*=\s*["\']twitter:image["\'][^>]*?content\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        # Video poster
        re.compile(
            r'<video\s[^>]*?poster\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
        # Favicons and apple-touch-icon
        re.compile(
            r'<link\s[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*?rel\s*=\s*["\'](?:icon|shortcut icon|apple-touch-icon)["\']',
            re.I
        ),
        re.compile(
            r'<link\s[^>]*?rel\s*=\s*["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]*?href\s*=\s*["\']([^"\']+)["\']',
            re.I
        ),
    ]

    # JSON patterns for JavaScript-rendered content
    JSON_IMG_PATTERN = re.compile(
        r'["\'](?:image|img|photo|picture|thumbnail|thumb|poster|avatar|banner|cover)'
        r'(?:_url|Url|URL|_src|Src)?\s*["\']'
        r'\s*:\s*["\']'
        r'(https?://[^"\']+\.(?:jpe?g|png|gif|webp|avif|svg)(?:\?[^"\']*)?)["\']',
        re.I
    )

    # Known tracking/pixel domains to skip
    TRACKING_DOMAINS = {
        'pixel.', 'beacon.', 'track.', 'analytics.', 'stat.',
        'doubleclick.net', 'googlesyndication.com', 'facebook.com/tr',
        'googleadservices.com', 'google-analytics.com', 'adsrv.',
    }

    # Known image CDN patterns (high priority)
    CDN_PATTERNS = [
        'cdn.', 'img.', 'image.', 'images.', 'media.', 'static.',
        'uploads.', 'photos.', 'picture.', 'assets.',
        'cloudinary.com', 'imgur.com', 'imgix.net',
        'cloudfront.net', 'akamaihd.net', 'fastly.net',
        'wp-content/uploads',
    ]

    @classmethod
    def extract(cls, html: str, base_url: str,
                include_favicons: bool = False,
                include_data_uris: bool = False,
                min_url_length: int = 10) -> List[Dict[str, Any]]:
        """
        Extract all image URLs from HTML.

        Returns list of dicts:
            [{'url': str, 'alt': str, 'source': str, 'priority': int}, ...]

        Priority: 1=high (og:image, main content), 5=low (favicon, tiny)
        """
        if not html:
            return []

        found_urls: Dict[str, Dict] = {}  # url → info dict (dedup)

        # --- Strategy 1: Regex patterns ---
        for pattern in cls.IMG_PATTERNS:
            for match in pattern.finditer(html):
                raw_url = match.group(1).strip()
                cls._process_url(raw_url, base_url, found_urls, 'html_tag')

        # --- Strategy 2: srcset parsing (contains multiple URLs) ---
        for match in re.finditer(r'srcset\s*=\s*["\']([^"\']+)["\']', html, re.I):
            srcset = match.group(1)
            for entry in srcset.split(','):
                entry = entry.strip()
                url_part = entry.split()[0] if entry else ''
                if url_part:
                    cls._process_url(url_part, base_url, found_urls, 'srcset')

        # --- Strategy 3: JSON/JS embedded images ---
        for match in cls.JSON_IMG_PATTERN.finditer(html):
            url = match.group(1)
            cls._process_url(url, base_url, found_urls, 'json_data')

        # --- Strategy 4: Any URL ending with image extension ---
        for match in re.finditer(
            r'(https?://[^\s"\'<>]+\.(?:jpe?g|png|gif|webp|avif|bmp|svg|ico|tiff?)(?:\?[^\s"\'<>]*)?)',
            html, re.I
        ):
            cls._process_url(match.group(1), base_url, found_urls, 'url_pattern')

        # --- Strategy 5: Extract alt text for naming ---
        for match in re.finditer(
            r'<img\s[^>]*?src\s*=\s*["\']([^"\']+)["\'][^>]*?alt\s*=\s*["\']([^"\']*)["\']',
            html, re.I
        ):
            url, alt = match.group(1), match.group(2)
            full_url = urljoin(base_url, url)
            if full_url in found_urls:
                found_urls[full_url]['alt'] = alt.strip()

        # Reverse check: alt before src
        for match in re.finditer(
            r'<img\s[^>]*?alt\s*=\s*["\']([^"\']*)["\'][^>]*?src\s*=\s*["\']([^"\']+)["\']',
            html, re.I
        ):
            alt, url = match.group(1), match.group(2)
            full_url = urljoin(base_url, url)
            if full_url in found_urls:
                found_urls[full_url]['alt'] = alt.strip()

        # --- Filter and sort ---
        results = []
        for url, info in found_urls.items():
            # Skip data URIs unless requested
            if url.startswith('data:') and not include_data_uris:
                continue

            # Skip very short URLs
            if len(url) < min_url_length:
                continue

            # Skip tracking pixels
            if cls._is_tracking(url):
                info['priority'] = 9  # Mark but include
                continue  # Actually skip trackers

            # Skip favicons unless requested
            if not include_favicons and info.get('source') == 'favicon':
                continue

            # Assign priority
            priority = cls._calc_priority(url, info)
            info['priority'] = priority

            results.append({'url': url, **info})

        # Sort by priority (1=best, 9=worst)
        results.sort(key=lambda x: x.get('priority', 5))

        return results

    @classmethod
    def _process_url(cls, raw_url: str, base_url: str,
                     found_urls: Dict, source: str):
        """Process and normalize a raw URL"""
        raw_url = raw_url.strip()
        if not raw_url:
            return

        # Skip data URIs, javascript:, mailto:
        if raw_url.startswith(('data:', 'javascript:', 'mailto:', '#')):
            return

        # Handle protocol-relative URLs
        if raw_url.startswith('//'):
            parsed_base = urlparse(base_url)
            raw_url = f"{parsed_base.scheme}:{raw_url}"

        # Resolve relative URLs
        full_url = urljoin(base_url, raw_url)

        # Clean up URL
        full_url = full_url.split('#')[0]  # Remove fragment
        full_url = full_url.strip()

        # Validate
        parsed = urlparse(full_url)
        if parsed.scheme not in ('http', 'https'):
            return

        # Dedup — keep first occurrence but update info
        if full_url not in found_urls:
            found_urls[full_url] = {
                'alt': '',
                'source': source,
                'domain': parsed.netloc,
            }

    @classmethod
    def _is_tracking(cls, url: str) -> bool:
        """Check if URL is a tracking pixel"""
        url_lower = url.lower()
        for domain in cls.TRACKING_DOMAINS:
            if domain in url_lower:
                return True
        # Check for common tracking patterns
        if re.search(r'[?&](?:tracking|pixel|beacon|impressio|stat)=', url_lower):
            return True
        # 1x1 in URL
        if re.search(r'[/=_-]1x1[./=_-]', url_lower):
            return True
        return False

    @classmethod
    def _calc_priority(cls, url: str, info: Dict) -> int:
        """Calculate image priority (1=highest, 9=lowest)"""
        source = info.get('source', '')
        url_lower = url.lower()

        # og:image / twitter:image — usually the main image
        if source in ('og_image', 'twitter_image'):
            return 1

        # CDN-hosted images — usually real content
        for cdn in cls.CDN_PATTERNS:
            if cdn in url_lower:
                return 2

        # Large image indicators in URL
        if any(s in url_lower for s in ('original', 'full', 'large', 'high', '1920', '1080')):
            return 2

        # Standard img tag with alt text — likely real content
        if source == 'html_tag' and info.get('alt'):
            return 3

        # Standard img tag without alt
        if source == 'html_tag':
            return 4

        # srcset images
        if source == 'srcset':
            return 4

        # JSON/JS embedded
        if source == 'json_data':
            return 3

        # URL pattern match
        if source == 'url_pattern':
            return 5

        # Small image indicators
        if any(s in url_lower for s in ('thumb', 'small', 'tiny', 'icon', '32x32', '16x16')):
            return 7

        return 5


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ImageResult:
    """Result from a single image download"""
    url: str
    success: bool = False
    filepath: Optional[str] = None
    filename: Optional[str] = None
    original_format: str = 'unknown'
    saved_format: str = 'unknown'
    was_converted: bool = False
    filesize: int = 0
    width: int = 0
    height: int = 0
    content_hash: str = ''
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None

    @property
    def size_str(self) -> str:
        return format_size(self.filesize) if self.filesize else '0 B'

    def to_dict(self) -> Dict:
        return {
            'url': self.url, 'success': self.success,
            'filepath': self.filepath, 'filename': self.filename,
            'original_format': self.original_format,
            'saved_format': self.saved_format,
            'was_converted': self.was_converted,
            'filesize': self.filesize, 'width': self.width,
            'height': self.height, 'content_hash': self.content_hash,
            'error': self.error, 'skipped': self.skipped,
            'skip_reason': self.skip_reason,
        }


@dataclass
class ScrapeResult:
    """Result from scraping a page for images"""
    page_url: str
    success: bool = False
    images_found: int = 0
    images_downloaded: int = 0
    images_failed: int = 0
    images_skipped: int = 0
    total_bytes: int = 0
    output_dir: str = ''
    results: List[ImageResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def total_size_str(self) -> str:
        return format_size(self.total_bytes)

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  IMAGE SCRAPE RESULTS",
            f"{'='*60}",
            f"  Page:       {self.page_url}",
            f"  Found:      {self.images_found} images",
            f"  Downloaded: {self.images_downloaded}",
            f"  Failed:     {self.images_failed}",
            f"  Skipped:    {self.images_skipped}",
            f"  Total Size: {self.total_size_str}",
            f"  Output:     {self.output_dir}",
        ]
        if self.error:
            lines.append(f"  Error:      {self.error}")

        # Show first 20 successful downloads
        downloaded = [r for r in self.results if r.success]
        if downloaded:
            lines.append(f"\n  Downloaded files:")
            for r in downloaded[:20]:
                conv = " (converted)" if r.was_converted else ""
                lines.append(
                    f"    {r.filename:<40} {r.size_str:>10} "
                    f"{r.original_format:>5}{conv}"
                )
            if len(downloaded) > 20:
                lines.append(f"    ... and {len(downloaded)-20} more")

        # Show failures
        failed = [r for r in self.results if not r.success and not r.skipped]
        if failed:
            lines.append(f"\n  Failed downloads:")
            for r in failed[:10]:
                lines.append(f"    {r.url[:60]} — {r.error}")

        lines.append(f"{'='*60}")
        return '\n'.join(lines)


# =============================================================================
# Main Image Downloader
# =============================================================================

class ImageDownloader:
    """
    Professional image downloader with format detection and conversion.

    Features:
    - Downloads single images or bulk
    - Scrapes pages for all images
    - Auto-detects real format (magic bytes)
    - Converts WebP/AVIF/HEIC → PNG/JPG
    - Validates downloads
    - Deduplicates by content hash
    - Rate-limited concurrent downloads
    """

    def __init__(self,
                 output_dir: str = None,
                 auto_convert: bool = True,
                 skip_duplicates: bool = True,
                 min_size: int = MIN_IMAGE_SIZE,
                 max_concurrent: int = MAX_CONCURRENT,
                 organize_by_domain: bool = True,
                 user_agent: str = None):
        """
        Args:
            output_dir:         Where to save images
            auto_convert:       Convert WebP/AVIF → PNG/JPG
            skip_duplicates:    Skip already-downloaded images (by hash)
            min_size:           Minimum file size (filters tracking pixels)
            max_concurrent:     Max simultaneous downloads
            organize_by_domain: Create subfolders per source domain
            user_agent:         Custom User-Agent header
        """
        if HAS_CONFIG and config:
            self.output_dir = output_dir or config.paths.images
        else:
            self.output_dir = output_dir or DEFAULT_OUTPUT_DIR

        self.auto_convert = auto_convert
        self.skip_duplicates = skip_duplicates
        self.min_size = min_size
        self.max_concurrent = max_concurrent
        self.organize_by_domain = organize_by_domain

        if HAS_CONFIG and config:
            self.user_agent = user_agent or config.network.user_agent
        else:
            self.user_agent = user_agent or DEFAULT_USER_AGENT

        self._session: Optional[aiohttp.ClientSession] = None
        self._owns_session = False
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._host_delays: Dict[str, float] = {}
        self._downloaded_hashes: Set[str] = set()
        self._converter = ImageConverter()
        self._validator = ImageValidator()

        # Load existing hashes from output dir for dedup
        if skip_duplicates:
            self._load_existing_hashes()

        # Stats
        self._stats = {
            'downloaded': 0,
            'converted': 0,
            'skipped': 0,
            'failed': 0,
            'bytes': 0,
        }

        os.makedirs(self.output_dir, exist_ok=True)

    def _load_existing_hashes(self):
        """Load content hashes of already-downloaded images"""
        hash_file = os.path.join(self.output_dir, '.image_hashes.json')
        if os.path.exists(hash_file):
            try:
                with open(hash_file, 'r') as f:
                    data = json.load(f)
                self._downloaded_hashes = set(data.get('hashes', []))
                log_debug(f"Loaded {len(self._downloaded_hashes)} existing image hashes")
            except Exception:
                pass

    def _save_hashes(self):
        """Save content hashes for future dedup"""
        hash_file = os.path.join(self.output_dir, '.image_hashes.json')
        try:
            with open(hash_file, 'w') as f:
                json.dump({
                    'hashes': list(self._downloaded_hashes),
                    'updated': datetime.now().isoformat(),
                }, f)
        except Exception:
            pass

    # ---- Session management ----

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _ensure_session(self):
        """Create aiohttp session if needed"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.max_concurrent * 2,
                limit_per_host=4,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=60, connect=15)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                # Increase max header size to handle sites like X/Twitter
                # that send very large cookie/Set-Cookie headers (default
                # is 8190 bytes which is too small for many social media
                # sites).
                max_line_size=32768,
                max_field_size=32768,
            )
            self._owns_session = True

    async def close(self):
        """Close session and save state"""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._save_hashes()

    # ---- Rate limiting ----

    async def _rate_limit(self, host: str):
        """Per-host rate limiting"""
        import time
        now = time.time()
        last = self._host_delays.get(host, 0)
        wait = max(0, HOST_DELAY - (now - last))
        if wait > 0:
            await asyncio.sleep(wait)
        self._host_delays[host] = time.time()

    # ---- Social media URL resolution ----

    async def _resolve_social_media_url(self, url: str) -> str:
        """
        Resolve social media page URLs to direct image URLs.

        Supported:
        - X/Twitter:    x.com/.../status/.../photo/N → pbs.twimg.com image
        - Instagram:    instagram.com/p/CODE          → CDN image
        - Pinterest:    pinterest.com/pin/ID           → og:image
        - Reddit:       reddit.com/.../comments/...    → i.redd.it image
        - Imgur:        imgur.com/HASH                 → i.imgur.com direct
        """
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace('www.', '')

        await self._ensure_session()

        # --- X / Twitter tweet photo URLs ---
        if host in ('x.com', 'twitter.com'):
            resolved = await self._resolve_twitter(url, parsed)
            if resolved != url:
                return resolved

        # --- Instagram post/reel ---
        elif host in ('instagram.com', 'instagr.am'):
            resolved = await self._resolve_instagram(url, parsed)
            if resolved != url:
                return resolved

        # --- Pinterest pin ---
        elif 'pinterest' in host:
            resolved = await self._resolve_pinterest(url, parsed)
            if resolved != url:
                return resolved

        # --- Reddit post ---
        elif host in ('reddit.com', 'old.reddit.com', 'new.reddit.com',
                       'i.redd.it', 'preview.redd.it'):
            # i.redd.it and preview.redd.it are already direct image links
            if host in ('i.redd.it', 'preview.redd.it'):
                return url
            resolved = await self._resolve_reddit(url, parsed)
            if resolved != url:
                return resolved

        # --- Imgur ---
        elif host in ('imgur.com', 'i.imgur.com', 'm.imgur.com'):
            resolved = self._resolve_imgur(url, parsed)
            if resolved != url:
                return resolved

        return url  # Return original URL if no resolution needed/possible

    # ----- Platform-specific resolvers -----

    async def _resolve_twitter(self, url: str, parsed) -> str:
        """Resolve X/Twitter status URL → direct image URL"""
        match = re.search(r'/status/(\d+)(?:/photo/(\d+))?', parsed.path)
        if not match:
            return url

        tweet_id = match.group(1)

        # Try syndication API first (public, no auth)
        api_url = f'https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=0'
        try:
            async with self._session.get(
                api_url,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'application/json',
                    'Referer': 'https://platform.twitter.com/',
                },
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    photos = data.get('mediaDetails', [])
                    if photos:
                        photo_idx = int(match.group(2) or '1') - 1
                        photo_idx = min(photo_idx, len(photos) - 1)
                        img_url = photos[photo_idx].get('media_url_https', '')
                        if img_url:
                            if '?' not in img_url:
                                img_url += '?format=jpg&name=orig'
                            log_info(f"Resolved X/Twitter image: {img_url[:80]}")
                            return img_url
        except Exception as e:
            log_debug(f"X/Twitter syndication API failed: {e}")

        # Fallback: fxtwitter API
        try:
            fx_url = f'https://api.fxtwitter.com/status/{tweet_id}'
            async with self._session.get(
                fx_url,
                headers={'User-Agent': self.user_agent},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    tweet = data.get('tweet', {})
                    media = tweet.get('media', {})
                    photos = media.get('photos', [])
                    if photos:
                        photo_idx = int(match.group(2) or '1') - 1
                        photo_idx = min(photo_idx, len(photos) - 1)
                        img_url = photos[photo_idx].get('url', '')
                        if img_url:
                            log_info(f"Resolved via fxtwitter: {img_url[:80]}")
                            return img_url
        except Exception as e2:
            log_debug(f"fxtwitter fallback also failed: {e2}")

        return url

    async def _resolve_instagram(self, url: str, parsed) -> str:
        """Resolve Instagram post URL → direct image URL via embed page"""
        # Extract shortcode from /p/CODE/ or /reel/CODE/
        match = re.search(r'/(?:p|reel|tv)/([A-Za-z0-9_-]+)', parsed.path)
        if not match:
            return url

        shortcode = match.group(1)
        # Instagram's public embed endpoint returns HTML with og:image
        embed_url = f'https://www.instagram.com/p/{shortcode}/embed/'
        try:
            async with self._session.get(
                embed_url,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html',
                },
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text(errors='replace')
                    # Look for og:image or the image in the embed HTML
                    og_match = re.search(
                        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                        html, re.I
                    )
                    if not og_match:
                        og_match = re.search(
                            r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                            html, re.I
                        )
                    if og_match:
                        img_url = og_match.group(1).replace('&amp;', '&')
                        log_info(f"Resolved Instagram image: {img_url[:80]}")
                        return img_url

                    # Fallback: look for display_url in embedded JSON
                    json_match = re.search(
                        r'"display_url"\s*:\s*"(https?://[^"]+)"', html
                    )
                    if json_match:
                        img_url = json_match.group(1).replace('\\u0026', '&')
                        log_info(f"Resolved Instagram image (JSON): {img_url[:80]}")
                        return img_url
        except Exception as e:
            log_debug(f"Instagram resolution failed: {e}")

        return url

    async def _resolve_pinterest(self, url: str, parsed) -> str:
        """Resolve Pinterest pin URL → direct image URL via og:image"""
        try:
            async with self._session.get(
                url,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html',
                },
                ssl=False,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text(errors='replace')
                    # Pinterest puts the full-res image in og:image
                    og_match = re.search(
                        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                        html, re.I
                    )
                    if not og_match:
                        og_match = re.search(
                            r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                            html, re.I
                        )
                    if og_match:
                        img_url = og_match.group(1).replace('&amp;', '&')
                        # Upgrade to original size (replace /236x/ or /564x/ → /originals/)
                        img_url = re.sub(r'/\d+x/', '/originals/', img_url)
                        log_info(f"Resolved Pinterest image: {img_url[:80]}")
                        return img_url
        except Exception as e:
            log_debug(f"Pinterest resolution failed: {e}")

        return url

    async def _resolve_reddit(self, url: str, parsed) -> str:
        """Resolve Reddit post URL → direct image URL via JSON API"""
        try:
            # Reddit's public JSON API: append .json
            json_url = url.rstrip('/') + '.json'
            async with self._session.get(
                json_url,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'application/json',
                },
                ssl=False,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    # Reddit JSON: [listing, comments]
                    if isinstance(data, list) and len(data) > 0:
                        post_data = data[0].get('data', {}).get('children', [{}])[0].get('data', {})
                        # Direct image link (i.redd.it)
                        post_url = post_data.get('url', '')
                        if post_url and re.search(
                            r'\.(jpe?g|png|gif|webp|avif)$', post_url, re.I
                        ):
                            log_info(f"Resolved Reddit image: {post_url[:80]}")
                            return post_url
                        # Gallery posts — get first image
                        media_metadata = post_data.get('media_metadata', {})
                        if media_metadata:
                            for media_id, meta in media_metadata.items():
                                if meta.get('status') == 'valid' and meta.get('s', {}).get('u'):
                                    img_url = meta['s']['u'].replace('&amp;', '&')
                                    log_info(f"Resolved Reddit gallery image: {img_url[:80]}")
                                    return img_url
                        # Preview image as last resort
                        preview = post_data.get('preview', {}).get('images', [{}])
                        if preview:
                            source = preview[0].get('source', {}).get('url', '')
                            if source:
                                img_url = source.replace('&amp;', '&')
                                log_info(f"Resolved Reddit preview image: {img_url[:80]}")
                                return img_url
        except Exception as e:
            log_debug(f"Reddit resolution failed: {e}")

        return url

    @staticmethod
    def _resolve_imgur(url: str, parsed) -> str:
        """Resolve Imgur page URL → direct i.imgur.com URL"""
        host = parsed.netloc.lower().replace('www.', '')

        # Already a direct image link
        if host == 'i.imgur.com':
            return url

        # imgur.com/HASH → i.imgur.com/HASH.jpg
        # Skip albums (/a/) and galleries (/gallery/)
        path = parsed.path.strip('/')
        if '/' in path:
            # Could be /a/HASH or /gallery/HASH — can't resolve simply
            return url

        if path and re.match(r'^[A-Za-z0-9]+$', path):
            # Simple image hash — construct direct link
            direct_url = f'https://i.imgur.com/{path}.jpg'
            log_info(f"Resolved Imgur image: {direct_url}")
            return direct_url

        return url

    # =========================================================================
    # Core: Download Single Image
    # =========================================================================

    async def download(self, url: str,
                       filename: str = None,
                       subfolder: str = None,
                       referer: str = None) -> ImageResult:
        """
        Download a single image with format detection and conversion.

        Args:
            url:       Image URL
            filename:  Custom filename (without extension — auto-detected)
            subfolder: Subfolder within output_dir
            referer:   Referer header for hotlink protection bypass

        Returns:
            ImageResult with status, path, format info
        """
        # Preserve original URL for folder naming before resolution
        original_url = url

        # Resolve social media page URLs → direct image URLs
        url = await self._resolve_social_media_url(url)

        result = ImageResult(url=url)

        if not HAS_AIOHTTP:
            result.error = 'aiohttp not installed (pip install aiohttp)'
            return result

        await self._ensure_session()

        parsed = urlparse(url)
        host = parsed.netloc

        # Build output directory — use ORIGINAL domain (e.g. x.com)
        # not the resolved CDN domain (e.g. pbs.twimg.com)
        out_dir = self.output_dir
        if subfolder:
            out_dir = os.path.join(out_dir, sanitize_filename(subfolder))
        elif self.organize_by_domain:
            original_host = urlparse(original_url).netloc
            domain_folder = (original_host or host).replace('www.', '').split(':')[0]
            out_dir = os.path.join(out_dir, sanitize_filename(domain_folder))
        os.makedirs(out_dir, exist_ok=True)

        async with self._semaphore:
            await self._rate_limit(host)

            try:
                # --- Download ---
                headers = {'User-Agent': self.user_agent}
                if referer:
                    headers['Referer'] = referer
                elif parsed.scheme and parsed.netloc:
                    headers['Referer'] = f"{parsed.scheme}://{parsed.netloc}/"

                async with self._session.get(url, headers=headers,
                                             allow_redirects=True,
                                             ssl=False) as resp:
                    if resp.status != 200:
                        result.error = f"HTTP {resp.status}"
                        self._stats['failed'] += 1
                        return result

                    # Check content type header
                    content_type = resp.headers.get('Content-Type', '')
                    if content_type and not any(t in content_type for t in
                            ['image/', 'octet-stream', 'binary',
                             'application/webp', 'application/avif']):
                        result.error = f"Not an image: {content_type}"
                        result.skipped = True
                        result.skip_reason = f"Content-Type: {content_type}"
                        self._stats['skipped'] += 1
                        return result

                    # Read content
                    content = await resp.read()

                if not content or len(content) < 100:
                    result.error = "Empty or too small response"
                    self._stats['failed'] += 1
                    return result

                # --- Deduplication by content hash ---
                content_hash = hashlib.sha256(content).hexdigest()[:16]
                result.content_hash = content_hash

                if self.skip_duplicates and content_hash in self._downloaded_hashes:
                    result.skipped = True
                    result.skip_reason = "Duplicate (already downloaded)"
                    self._stats['skipped'] += 1
                    return result

                # --- Detect REAL format from magic bytes ---
                detected_fmt = detect_format(content[:64])
                result.original_format = detected_fmt

                if detected_fmt == 'unknown':
                    # Try Content-Type as fallback
                    if 'jpeg' in content_type or 'jpg' in content_type:
                        detected_fmt = 'jpg'
                    elif 'png' in content_type:
                        detected_fmt = 'png'
                    elif 'gif' in content_type:
                        detected_fmt = 'gif'
                    elif 'webp' in content_type:
                        detected_fmt = 'webp'
                    elif 'svg' in content_type:
                        detected_fmt = 'svg'
                    else:
                        detected_fmt = 'jpg'  # Default fallback
                    result.original_format = detected_fmt

                # --- Build filename ---
                if filename:
                    safe_name = sanitize_filename(filename)
                else:
                    # Try to get name from URL path
                    url_path = unquote(parsed.path)
                    base_name = os.path.basename(url_path)
                    base_name = base_name.split('?')[0]
                    if base_name and '.' in base_name:
                        safe_name = sanitize_filename(os.path.splitext(base_name)[0])
                    elif base_name:
                        safe_name = sanitize_filename(base_name)
                    else:
                        safe_name = f"image_{content_hash}"

                    # Avoid super long names
                    if len(safe_name) > 120:
                        safe_name = safe_name[:100] + '_' + content_hash[:8]

                # Determine final extension
                correct_ext = get_correct_extension(detected_fmt)
                save_path = os.path.join(out_dir, f"{safe_name}{correct_ext}")
                save_path = get_unique_filepath(save_path)

                # --- Write file ---
                with open(save_path, 'wb') as f:
                    f.write(content)

                # --- Min size filter ---
                if len(content) < self.min_size:
                    # Check if it's a tracking pixel
                    if ImageValidator.is_tracking_pixel(save_path):
                        os.remove(save_path)
                        result.skipped = True
                        result.skip_reason = "Tracking pixel (too small)"
                        self._stats['skipped'] += 1
                        return result

                # --- Auto-convert if needed ---
                if self.auto_convert and ImageConverter.needs_conversion(detected_fmt):
                    target_fmt = ImageConverter.get_target_format(detected_fmt)
                    converted_path = os.path.splitext(save_path)[0] + f'.{target_fmt}'

                    success, final_path = ImageConverter.convert(save_path, converted_path, target_fmt)

                    if success and final_path != save_path:
                        # Remove original, use converted
                        try:
                            os.remove(save_path)
                        except OSError:
                            pass
                        save_path = final_path
                        result.was_converted = True
                        result.saved_format = target_fmt
                        self._stats['converted'] += 1
                        log_debug(f"Converted {detected_fmt} → {target_fmt}: {os.path.basename(save_path)}")
                    else:
                        result.saved_format = detected_fmt
                else:
                    result.saved_format = detected_fmt

                # --- Validate final image ---
                validation = ImageValidator.validate(save_path)
                if not validation['valid'] and validation.get('error'):
                    log_warn(f"Image validation warning: {validation['error']} — {os.path.basename(save_path)}")
                    # Don't delete — user might still want it

                result.width = validation.get('width', 0)
                result.height = validation.get('height', 0)

                # --- Success ---
                result.success = True
                result.filepath = save_path
                result.filename = os.path.basename(save_path)
                result.filesize = os.path.getsize(save_path)

                # Track hash for dedup
                self._downloaded_hashes.add(content_hash)
                self._stats['downloaded'] += 1
                self._stats['bytes'] += result.filesize

                return result

            except asyncio.TimeoutError:
                result.error = "Download timed out"
                self._stats['failed'] += 1
            except aiohttp.ClientError as e:
                result.error = f"Network error: {str(e)[:200]}"
                self._stats['failed'] += 1
            except Exception as e:
                result.error = f"Error: {str(e)[:200]}"
                self._stats['failed'] += 1
                log_debug(f"Image download error for {url}: {e}")

        return result

    # =========================================================================
    # Download Multiple URLs
    # =========================================================================

    async def download_many(self, urls: List[str],
                            subfolder: str = None,
                            referer: str = None,
                            progress_callback: Callable = None) -> List[ImageResult]:
        """
        Download multiple images concurrently.

        Args:
            urls:              List of image URLs
            subfolder:         Subfolder for all downloads
            referer:           Referer header
            progress_callback: fn(current, total, result) called per image

        Returns:
            List of ImageResult
        """
        if not urls:
            return []

        # Deduplicate input URLs
        seen = set()
        unique_urls = []
        for u in urls:
            normalized = u.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_urls.append(normalized)

        total = len(unique_urls)
        log_info(f"Downloading {total} images (max {self.max_concurrent} concurrent)...")

        results: List[Optional[ImageResult]] = [None] * total

        async def _dl_one(idx: int, url: str):
            result = await self.download(url, subfolder=subfolder, referer=referer)
            results[idx] = result
            if progress_callback:
                progress_callback(idx + 1, total, result)
            else:
                # Simple console progress
                status = '✓' if result.success else ('⊘' if result.skipped else '✗')
                name = result.filename or os.path.basename(urlparse(url).path)[:30] or url[:30]
                sys.stdout.write(
                    f"\r  [{idx+1}/{total}] {status} {name:<35} {result.size_str if result.success else (result.skip_reason or result.error or '')[:30]}"
                )
                sys.stdout.flush()
                if idx + 1 == total:
                    sys.stdout.write('\n')

        # Run with bounded concurrency
        tasks = [_dl_one(i, url) for i, url in enumerate(unique_urls)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Fill any None slots (shouldn't happen but defensive)
        final = []
        for i, r in enumerate(results):
            if r is None:
                final.append(ImageResult(url=unique_urls[i], error="Task failed"))
            else:
                final.append(r)

        # Print summary
        downloaded = sum(1 for r in final if r.success)
        skipped = sum(1 for r in final if r.skipped)
        failed = sum(1 for r in final if not r.success and not r.skipped)
        total_bytes = sum(r.filesize for r in final if r.success)

        log_info(f"  Done: {downloaded} downloaded, {skipped} skipped, {failed} failed | {format_size(total_bytes)}")

        return final

    # =========================================================================
    # Download from File (list of URLs)
    # =========================================================================

    async def download_from_file(self, filepath: str,
                                 subfolder: str = None) -> List[ImageResult]:
        """
        Download images from a text file (one URL per line).

        Supports:
          - Plain text: one URL per line
          - JSON: list of URLs or list of objects with 'url' key
          - Lines starting with # are skipped (comments)
        """
        if not os.path.exists(filepath):
            log_error(f"File not found: {filepath}")
            return []

        urls = []
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        # Try JSON first
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict) and 'url' in item:
                        urls.append(item['url'])
            log_info(f"Parsed {len(urls)} URLs from JSON file")
        except (json.JSONDecodeError, ValueError):
            # Plain text — one URL per line
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Extract URL from line (handles lines with extra text)
                    url_match = re.search(r'(https?://\S+)', line)
                    if url_match:
                        urls.append(url_match.group(1))
                    elif line.startswith(('http://', 'https://', '//')):
                        urls.append(line)
            log_info(f"Parsed {len(urls)} URLs from text file")

        if not urls:
            log_warn("No valid URLs found in file")
            return []

        return await self.download_many(urls, subfolder=subfolder)

    # =========================================================================
    # Scrape Page → Find Images → Download All
    # =========================================================================

    async def scrape_and_download(self, page_url: str,
                                  subfolder: str = None,
                                  max_images: int = 200,
                                  include_favicons: bool = False,
                                  min_priority: int = 7,
                                  progress_callback: Callable = None
                                  ) -> ScrapeResult:
        """
        Scrape a web page, extract all image URLs, download them all.

        Args:
            page_url:          URL of the page to scrape
            subfolder:         Custom subfolder (default: domain name)
            max_images:        Maximum images to download
            include_favicons:  Include favicon/icon images
            min_priority:      Only download images with priority <= this (1=best, 9=worst)
            progress_callback: fn(current, total, result)

        Returns:
            ScrapeResult with all download results
        """
        result = ScrapeResult(page_url=page_url)

        if not HAS_AIOHTTP:
            result.error = 'aiohttp not installed'
            return result

        await self._ensure_session()

        # --- Fetch page HTML ---
        log_info(f"Fetching page: {page_url[:70]}")

        html = None
        try:
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            async with self._session.get(page_url, headers=headers,
                                         allow_redirects=True,
                                         timeout=aiohttp.ClientTimeout(total=30)
                                         ) as resp:
                if resp.status != 200:
                    result.error = f"HTTP {resp.status}"
                    return result
                html = await resp.text(errors='replace')
                # Get final URL after redirects
                final_url = str(resp.url)
        except Exception as e:
            result.error = f"Failed to fetch page: {str(e)[:100]}"
            return result

        if not html:
            result.error = "Empty page response"
            return result

        # --- Extract image URLs ---
        log_info("Extracting image URLs...")
        extracted = HTMLImageExtractor.extract(
            html, final_url,
            include_favicons=include_favicons,
        )

        # Filter by priority
        extracted = [img for img in extracted if img.get('priority', 5) <= min_priority]

        result.images_found = len(extracted)
        log_info(f"Found {result.images_found} images on page")

        if not extracted:
            result.success = True  # Page scraped OK, just no images
            return result

        # Limit
        if len(extracted) > max_images:
            log_info(f"Limiting to first {max_images} images")
            extracted = extracted[:max_images]

        # --- Build output directory ---
        if not subfolder:
            domain = urlparse(final_url).netloc.replace('www.', '').split(':')[0]
            subfolder = sanitize_filename(domain)

        out_dir = os.path.join(self.output_dir, subfolder)
        os.makedirs(out_dir, exist_ok=True)
        result.output_dir = out_dir

        # --- Download all images ---
        urls = [img['url'] for img in extracted]
        download_results = await self.download_many(
            urls,
            subfolder=subfolder,
            referer=page_url,
            progress_callback=progress_callback,
        )

        result.results = download_results
        result.images_downloaded = sum(1 for r in download_results if r.success)
        result.images_failed = sum(1 for r in download_results if not r.success and not r.skipped)
        result.images_skipped = sum(1 for r in download_results if r.skipped)
        result.total_bytes = sum(r.filesize for r in download_results if r.success)
        result.success = True

        return result

    # =========================================================================
    # Scrape Multiple Pages
    # =========================================================================

    async def scrape_multiple_pages(self, page_urls: List[str],
                                     max_images_per_page: int = 100
                                     ) -> List[ScrapeResult]:
        """
        Scrape multiple pages for images.

        Args:
            page_urls:          List of page URLs to scrape
            max_images_per_page: Max images per page
        """
        results = []
        for i, url in enumerate(page_urls, 1):
            log_info(f"\n[Page {i}/{len(page_urls)}] {url[:60]}")
            result = await self.scrape_and_download(url, max_images=max_images_per_page)
            results.append(result)
            # Delay between pages
            if i < len(page_urls):
                await asyncio.sleep(1.0)
        return results

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get download statistics"""
        return {
            **self._stats,
            'total_size': format_size(self._stats['bytes']),
            'known_hashes': len(self._downloaded_hashes),
        }

    @staticmethod
    def convert_image(input_path: str, target_format: str = 'png') -> Tuple[bool, str]:
        """
        Convert a local image file to a different format.

        Args:
            input_path:    Path to source image
            target_format: 'png', 'jpg', 'gif', 'bmp'

        Returns:
            (success, output_path)
        """
        return ImageConverter.convert(input_path, target_format=target_format)

    @staticmethod
    def validate_image(filepath: str) -> Dict[str, Any]:
        """Validate an image file"""
        return ImageValidator.validate(filepath)

    @staticmethod
    def detect_image_format(filepath: str) -> str:
        """Detect the real format of an image file"""
        with open(filepath, 'rb') as f:
            header = f.read(64)
        return detect_format(header)

    def fix_existing_images(self, directory: str = None) -> Dict[str, Any]:
        """
        Scan a directory and fix all images:
        - Correct wrong extensions
        - Convert unsupported formats
        - Report invalid files

        Returns stats dict.
        """
        directory = directory or self.output_dir
        stats = {'scanned': 0, 'fixed_ext': 0, 'converted': 0, 'invalid': 0}

        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
                      '.ico', '.tiff', '.tif', '.avif', '.heic', '.svg', '.jxl'}

        for root, _, files in os.walk(directory):
            for fname in files:
                fpath = os.path.join(root, fname)
                _, ext = os.path.splitext(fname)

                if ext.lower() not in image_exts:
                    continue

                stats['scanned'] += 1

                # Read header
                try:
                    with open(fpath, 'rb') as f:
                        header = f.read(64)
                except Exception:
                    continue

                detected = detect_format(header)
                if detected == 'unknown':
                    stats['invalid'] += 1
                    log_warn(f"Invalid/unknown: {fpath}")
                    continue

                correct_ext = get_correct_extension(detected)

                # Fix wrong extension
                if ext.lower() != correct_ext and ext.lower() not in ('.jpeg', '.jpg'):
                    new_path = os.path.splitext(fpath)[0] + correct_ext
                    new_path = get_unique_filepath(new_path)
                    os.rename(fpath, new_path)
                    fpath = new_path
                    stats['fixed_ext'] += 1
                    log_info(f"Fixed extension: {fname} → {os.path.basename(new_path)}")

                # Convert if needed
                if self.auto_convert and ImageConverter.needs_conversion(detected):
                    target = ImageConverter.get_target_format(detected)
                    success, new_path = ImageConverter.convert(fpath, target_format=target)
                    if success and new_path != fpath:
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                        stats['converted'] += 1

        log_info(f"Fix scan: {stats['scanned']} scanned, "
                 f"{stats['fixed_ext']} extensions fixed, "
                 f"{stats['converted']} converted, "
                 f"{stats['invalid']} invalid")
        return stats


# =============================================================================
# Convenience Functions (for use from scraper.py)
# =============================================================================

async def download_image(url: str, output_dir: str = None, **kwargs) -> ImageResult:
    """Quick single image download — replacement for scraper.py's broken version"""
    async with ImageDownloader(output_dir=output_dir) as dl:
        return await dl.download(url, **kwargs)


async def download_images(urls: List[str], output_dir: str = None, **kwargs) -> List[ImageResult]:
    """Quick multi-image download"""
    async with ImageDownloader(output_dir=output_dir) as dl:
        return await dl.download_many(urls, **kwargs)


async def scrape_images(page_url: str, output_dir: str = None, **kwargs) -> ScrapeResult:
    """Quick page scrape and download all images"""
    async with ImageDownloader(output_dir=output_dir) as dl:
        return await dl.scrape_and_download(page_url, **kwargs)


def download_image_sync(url: str, output_dir: str = None, **kwargs) -> ImageResult:
    """Synchronous single image download"""
    return asyncio.run(download_image(url, output_dir=output_dir, **kwargs))


# =============================================================================
# CLI Interface
# =============================================================================

def print_status():
    """Print module status"""
    safe_print(f"""
{'='*65}
{'IMAGE DOWNLOADER & SCRAPER':^65}
{'Professional Image Tool with Format Detection':^65}
{'='*65}

  Output:   {DEFAULT_OUTPUT_DIR}

  Dependencies:
    [{'OK' if HAS_AIOHTTP  else 'X ':}] aiohttp      (async HTTP)
    [{'OK' if HAS_PILLOW   else 'X ':}] Pillow       (format conversion - RECOMMENDED)
    [{'OK' if HAS_IMAGEMAGICK else '- ':}] ImageMagick  (fallback converter — {'v7 at ' + IMAGEMAGICK_PATH if HAS_IMAGEMAGICK else 'not found'})
    [{'OK' if HAS_AIOFILES else '- ':}] aiofiles     (async file I/O)
    [{'OK' if HAS_FFMPEG   else '- ':}] FFmpeg       (fallback converter)

  Features:
    [OK] Magic byte format detection  (JPEG, PNG, GIF, WebP, AVIF, HEIC, BMP, TIFF)
    [OK] Auto-convert WebP/AVIF → PNG (images open on any OS)
    [OK] Content-hash deduplication   (skip already downloaded)
    [OK] Bulk download from URL list
    [OK] Scrape page → extract → download all images
    [OK] Rate-limited concurrent downloads
    [{'OK' if HAS_PILLOW else '!!'}] Image validation {'(FULL)' if HAS_PILLOW else '(BASIC — install Pillow for full validation)'}

{'='*65}
""")


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Professional Image Downloader & Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python image.py https://example.com/photo.webp          Download single image
  python image.py --scrape https://example.com/gallery     Scrape page for all images
  python image.py --list urls.txt                          Download from URL list
  python image.py --list urls.txt --no-convert             Keep original formats
  python image.py --fix ~/scraper/images/                  Fix existing images
  python image.py --status                                 Show module info
  python image.py URL1 URL2 URL3                           Download multiple images
        """
    )

    parser.add_argument('urls', nargs='*', help='Image URL(s) to download')
    parser.add_argument('--scrape', '-s', metavar='URL',
                        help='Scrape page URL for all images')
    parser.add_argument('--list', '-l', metavar='FILE',
                        help='Download URLs from text/JSON file')
    parser.add_argument('--output', '-o', metavar='DIR',
                        help='Output directory')
    parser.add_argument('--max', '-m', type=int, default=200,
                        help='Max images when scraping (default: 200)')
    parser.add_argument('--concurrent', '-c', type=int, default=MAX_CONCURRENT,
                        help=f'Max concurrent downloads (default: {MAX_CONCURRENT})')
    parser.add_argument('--no-convert', action='store_true',
                        help='Skip format conversion (keep WebP, AVIF, etc.)')
    parser.add_argument('--no-dedup', action='store_true',
                        help='Skip duplicate detection')
    parser.add_argument('--no-organize', action='store_true',
                        help='Don\'t organize by domain')
    parser.add_argument('--include-favicons', action='store_true',
                        help='Include favicons when scraping')
    parser.add_argument('--fix', metavar='DIR',
                        help='Fix existing images (correct extensions, convert)')
    parser.add_argument('--validate', metavar='FILE',
                        help='Validate an image file')
    parser.add_argument('--detect', metavar='FILE',
                        help='Detect real format of image file')
    parser.add_argument('--status', action='store_true',
                        help='Show module status')

    args = parser.parse_args()

    # --- Status ---
    if args.status:
        print_status()
        return

    # --- Validate single file ---
    if args.validate:
        result = ImageValidator.validate(args.validate)
        safe_print(f"\n  File: {args.validate}")
        for k, v in result.items():
            safe_print(f"  {k}: {v}")
        return

    # --- Detect format ---
    if args.detect:
        if not os.path.exists(args.detect):
            log_error(f"File not found: {args.detect}")
            sys.exit(1)
        with open(args.detect, 'rb') as f:
            header = f.read(64)
        fmt = detect_format(header)
        _, ext = os.path.splitext(args.detect)
        correct_ext = get_correct_extension(fmt)
        safe_print(f"\n  File:            {args.detect}")
        safe_print(f"  Current ext:     {ext}")
        safe_print(f"  Detected format: {fmt}")
        safe_print(f"  Correct ext:     {correct_ext}")
        if ext.lower() != correct_ext:
            safe_print(f"  ⚠ Extension mismatch! File is actually {fmt.upper()}")
        return

    # --- Fix existing images ---
    if args.fix:
        if not os.path.isdir(args.fix):
            log_error(f"Directory not found: {args.fix}")
            sys.exit(1)
        dl = ImageDownloader(output_dir=args.fix, auto_convert=not args.no_convert)
        stats = dl.fix_existing_images(args.fix)
        safe_print(f"\n  Scan complete: {json.dumps(stats, indent=2)}")
        return

    # --- Must have URLs, --scrape, or --list ---
    if not args.urls and not args.scrape and not args.list:
        print_status()
        safe_print("  Usage: python image.py <URL> [options]")
        safe_print("         python image.py --help")
        return

    # --- Run downloads ---
    async def run():
        async with ImageDownloader(
            output_dir=args.output,
            auto_convert=not args.no_convert,
            skip_duplicates=not args.no_dedup,
            max_concurrent=args.concurrent,
            organize_by_domain=not args.no_organize,
        ) as dl:

            if args.scrape:
                # Scrape page
                result = await dl.scrape_and_download(
                    args.scrape,
                    max_images=args.max,
                    include_favicons=args.include_favicons,
                )
                safe_print(result.summary())
                return result.success

            elif args.list:
                # Download from file
                results = await dl.download_from_file(args.list)
                downloaded = sum(1 for r in results if r.success)
                safe_print(f"\n  Total: {downloaded}/{len(results)} downloaded")
                return downloaded > 0

            elif args.urls:
                if len(args.urls) == 1:
                    # Single image
                    result = await dl.download(args.urls[0])
                    if result.success:
                        log_success(f"Saved: {result.filepath}")
                        log_info(f"Format: {result.original_format}"
                                 f"{' → ' + result.saved_format if result.was_converted else ''}")
                        log_info(f"Size: {result.size_str}")
                        if result.width:
                            log_info(f"Dimensions: {result.width}x{result.height}")
                    else:
                        log_error(f"Failed: {result.error}")
                    return result.success
                else:
                    # Multiple URLs
                    results = await dl.download_many(args.urls)
                    downloaded = sum(1 for r in results if r.success)
                    return downloaded > 0

    try:
        success = asyncio.run(run())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        safe_print("\n\n  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()