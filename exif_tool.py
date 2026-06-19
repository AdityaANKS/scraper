"""
================================================================================
EXIF_TOOL.PY - Metadata Extraction for Images & Videos
================================================================================
Extracts EXIF/metadata from images and videos.
Supports: JPEG, PNG, TIFF, WebP, MP4, MKV, AVI, MOV, etc.
Uses Pillow for images and ffprobe for videos.
================================================================================
"""

import os
import re
import json
import struct
import asyncio
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Check ffprobe
HAS_FFPROBE = False
try:
    r = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True, timeout=5)
    HAS_FFPROBE = r.returncode == 0
except Exception:
    pass

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp', '.gif', '.heic', '.heif'}
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.3gp'}


class EXIFExtractor:
    """Extract metadata from images and videos"""

    def extract(self, filepath: str) -> Dict[str, Any]:
        """Extract all metadata from a file"""
        if not os.path.exists(filepath):
            return {'error': f'File not found: {filepath}', 'success': False}

        ext = Path(filepath).suffix.lower()
        result = {
            'file': os.path.basename(filepath),
            'path': filepath,
            'size_bytes': os.path.getsize(filepath),
            'size': self._format_size(os.path.getsize(filepath)),
            'extension': ext,
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
            'created': datetime.fromtimestamp(os.path.getctime(filepath)).isoformat(),
            'success': True,
        }

        if ext in IMAGE_EXTS:
            result['type'] = 'image'
            result.update(self._extract_image(filepath))
        elif ext in VIDEO_EXTS:
            result['type'] = 'video'
            result.update(self._extract_video(filepath))
        else:
            result['type'] = 'unknown'
            result['note'] = 'Unsupported file type for EXIF extraction'

        return result

    async def extract_from_url(self, url: str, save_dir: str = None) -> Dict[str, Any]:
        """Download file from URL and extract metadata"""
        if not HAS_AIOHTTP:
            return {'error': 'aiohttp not available', 'success': False}

        save_dir = save_dir or os.path.join(os.path.expanduser('~'), 'scraper', 'temp')
        os.makedirs(save_dir, exist_ok=True)

        # Download
        from urllib.parse import urlparse
        filename = os.path.basename(urlparse(url).path) or 'downloaded_file'
        filepath = os.path.join(save_dir, filename)

        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, ssl=False) as resp:
                    if resp.status == 200:
                        with open(filepath, 'wb') as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)
                    else:
                        return {'error': f'HTTP {resp.status}', 'success': False}
        except Exception as e:
            return {'error': str(e), 'success': False}

        result = self.extract(filepath)
        result['source_url'] = url
        return result

    # --- Image EXIF ---

    def _extract_image(self, filepath: str) -> Dict:
        data = {}
        if not HAS_PILLOW:
            data['warning'] = 'Pillow not installed - limited extraction'
            return data

        try:
            img = Image.open(filepath)
            data['dimensions'] = f'{img.width}x{img.height}'
            data['width'] = img.width
            data['height'] = img.height
            data['mode'] = img.mode
            data['format'] = img.format

            # EXIF data
            exif_raw = img._getexif() if hasattr(img, '_getexif') else None
            if exif_raw:
                exif = {}
                gps_data = {}
                for tag_id, value in exif_raw.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == 'GPSInfo':
                        for gps_tag_id, gps_value in value.items():
                            gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                            gps_data[gps_tag] = str(gps_value)
                    elif isinstance(value, bytes):
                        try:
                            exif[str(tag)] = value.decode('utf-8', errors='replace')[:200]
                        except Exception:
                            exif[str(tag)] = f'<binary {len(value)} bytes>'
                    else:
                        exif[str(tag)] = str(value)[:500]

                # Key EXIF fields
                data['camera_make'] = exif.get('Make', 'Unknown')
                data['camera_model'] = exif.get('Model', 'Unknown')
                data['software'] = exif.get('Software', 'Unknown')
                data['datetime_original'] = exif.get('DateTimeOriginal', exif.get('DateTime'))
                data['exposure_time'] = exif.get('ExposureTime')
                data['f_number'] = exif.get('FNumber')
                data['iso'] = exif.get('ISOSpeedRatings')
                data['focal_length'] = exif.get('FocalLength')
                data['flash'] = exif.get('Flash')
                data['orientation'] = exif.get('Orientation')
                data['color_space'] = exif.get('ColorSpace')
                data['white_balance'] = exif.get('WhiteBalance')
                data['lens_model'] = exif.get('LensModel')
                data['image_description'] = exif.get('ImageDescription')
                data['copyright'] = exif.get('Copyright')
                data['artist'] = exif.get('Artist')

                # GPS coordinates
                if gps_data:
                    coords = self._parse_gps(gps_data)
                    if coords:
                        data['gps_latitude'] = coords[0]
                        data['gps_longitude'] = coords[1]
                        data['gps_google_maps'] = f'https://maps.google.com/?q={coords[0]},{coords[1]}'
                    data['gps_raw'] = gps_data

                # Store all EXIF
                data['exif_all'] = exif

                # Remove None values
                data = {k: v for k, v in data.items() if v is not None}
            else:
                data['exif'] = 'No EXIF data found'

            img.close()
        except Exception as e:
            data['error'] = str(e)

        return data

    def _parse_gps(self, gps_data: Dict) -> Optional[Tuple[float, float]]:
        """Parse GPS coordinates from EXIF data"""
        try:
            lat = gps_data.get('GPSLatitude')
            lat_ref = gps_data.get('GPSLatitudeRef', 'N')
            lon = gps_data.get('GPSLongitude')
            lon_ref = gps_data.get('GPSLongitudeRef', 'E')

            if not lat or not lon:
                return None

            # Parse coordinate tuples - handle string representation
            def parse_coord(coord_str):
                # Remove parentheses and parse
                nums = re.findall(r'[\d.]+', str(coord_str))
                if len(nums) >= 6:
                    d = float(nums[0]) / float(nums[1]) if float(nums[1]) else float(nums[0])
                    m = float(nums[2]) / float(nums[3]) if float(nums[3]) else float(nums[2])
                    s = float(nums[4]) / float(nums[5]) if float(nums[5]) else float(nums[4])
                    return d + m / 60 + s / 3600
                elif len(nums) >= 3:
                    return float(nums[0]) + float(nums[1]) / 60 + float(nums[2]) / 3600
                return None

            lat_val = parse_coord(lat)
            lon_val = parse_coord(lon)

            if lat_val is None or lon_val is None:
                return None

            if 'S' in str(lat_ref):
                lat_val = -lat_val
            if 'W' in str(lon_ref):
                lon_val = -lon_val

            return (round(lat_val, 6), round(lon_val, 6))
        except Exception:
            return None

    # --- Video Metadata ---

    def _extract_video(self, filepath: str) -> Dict:
        data = {}
        if not HAS_FFPROBE:
            data['warning'] = 'ffprobe not available - limited video extraction'
            return data

        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', filepath
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                data['error'] = 'ffprobe failed'
                return data

            info = json.loads(result.stdout)

            # Format info
            fmt = info.get('format', {})
            data['duration'] = float(fmt.get('duration', 0))
            data['duration_str'] = self._format_duration(data['duration'])
            data['bitrate'] = int(fmt.get('bit_rate', 0))
            data['bitrate_str'] = f"{data['bitrate'] // 1000} kbps" if data['bitrate'] else 'Unknown'
            data['format_name'] = fmt.get('format_name')
            data['format_long'] = fmt.get('format_long_name')

            # Tags
            tags = fmt.get('tags', {})
            data['title'] = tags.get('title')
            data['artist'] = tags.get('artist')
            data['album'] = tags.get('album')
            data['date'] = tags.get('date') or tags.get('creation_time')
            data['comment'] = tags.get('comment')
            data['encoder'] = tags.get('encoder')
            data['copyright'] = tags.get('copyright')

            # Streams
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video' and 'video_codec' not in data:
                    data['video_codec'] = stream.get('codec_name')
                    data['video_codec_long'] = stream.get('codec_long_name')
                    data['width'] = stream.get('width')
                    data['height'] = stream.get('height')
                    data['dimensions'] = f"{stream.get('width')}x{stream.get('height')}"
                    data['fps'] = eval(stream['r_frame_rate']) if stream.get('r_frame_rate') and '/' in str(stream['r_frame_rate']) else stream.get('r_frame_rate')
                    data['pixel_format'] = stream.get('pix_fmt')
                    data['video_bitrate'] = stream.get('bit_rate')
                    data['color_space'] = stream.get('color_space')

                elif stream.get('codec_type') == 'audio' and 'audio_codec' not in data:
                    data['audio_codec'] = stream.get('codec_name')
                    data['audio_codec_long'] = stream.get('codec_long_name')
                    data['sample_rate'] = stream.get('sample_rate')
                    data['channels'] = stream.get('channels')
                    data['audio_bitrate'] = stream.get('bit_rate')

            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}
        except Exception as e:
            data['error'] = str(e)

        return data

    # --- Display ---

    def display(self, result: Dict) -> str:
        """Format metadata for CLI display"""
        lines = []
        lines.append("")
        lines.append("═" * 65)
        lines.append(f"  METADATA: {result.get('file', 'Unknown')}")
        lines.append("═" * 65)

        # Skip internal keys
        skip = {'success', 'exif_all', 'gps_raw'}

        # Group output
        sections = {
            'File Info': ['file', 'path', 'size', 'extension', 'type', 'modified', 'created', 'source_url'],
            'Dimensions': ['dimensions', 'width', 'height', 'mode', 'format'],
            'Camera': ['camera_make', 'camera_model', 'lens_model', 'software'],
            'Exposure': ['datetime_original', 'exposure_time', 'f_number', 'iso', 'focal_length', 'flash', 'white_balance'],
            'GPS': ['gps_latitude', 'gps_longitude', 'gps_google_maps'],
            'Video': ['duration_str', 'video_codec', 'fps', 'pixel_format', 'video_bitrate', 'bitrate_str'],
            'Audio': ['audio_codec', 'sample_rate', 'channels', 'audio_bitrate'],
            'Tags': ['title', 'artist', 'album', 'date', 'comment', 'copyright', 'encoder', 'image_description'],
        }

        for section, keys in sections.items():
            section_data = {k: result[k] for k in keys if k in result and k not in skip}
            if section_data:
                lines.append(f"\n  {section}:")
                lines.append("  " + "─" * 40)
                for k, v in section_data.items():
                    label = k.replace('_', ' ').title()
                    lines.append(f"    {label:<22}: {v}")

        # Warnings / errors
        if result.get('warning'):
            lines.append(f"\n  ⚠ {result['warning']}")
        if result.get('error'):
            lines.append(f"\n  ✗ Error: {result['error']}")

        lines.append("\n" + "═" * 65)
        return '\n'.join(lines)

    def save_report(self, result: Dict, output_dir: str = None) -> str:
        """Save metadata report to JSON file"""
        output_dir = output_dir or os.path.join(os.path.expanduser('~'), 'scraper', 'OSINT', 'metadata')
        os.makedirs(output_dir, exist_ok=True)
        filename = f"exif_{result.get('file', 'unknown')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)
        # Remove non-serializable
        clean = {k: v for k, v in result.items() if k != 'exif_all'}
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2, default=str)
        return filepath

    # --- Helpers ---

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
