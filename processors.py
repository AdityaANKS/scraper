"""
================================================================================
PROCESSORS.PY - Media Processing
================================================================================
Handles all media processing including audio verification, video merging,
thumbnail embedding, format conversion, and file organization.
================================================================================
"""

import os
import re
import json
import shutil
import asyncio
import aiohttp
import aiofiles
import hashlib
import tempfile
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

from config import config, Platform, MediaType, ContentType
from utils import (
    log_info, log_warn, log_error, log_debug, log_success,
    run_command, run_command_async, format_size,
    sanitize_filename, get_unique_filepath,
    HAS_FFMPEG, HAS_FFPROBE
)


# =============================================================================
# Audio Verifier
# =============================================================================

class AudioVerifier:
    """Verify audio presence in media files with triple verification"""
    
    @staticmethod
    def verify(filepath: str) -> bool:
        """
        Verify if file has audio using triple verification.
        Returns True only if at least 2/3 checks pass.
        """
        if not os.path.exists(filepath):
            return False
        
        if os.path.getsize(filepath) < 1000:
            return False
        
        if not HAS_FFPROBE:
            return True  # Assume yes if can't verify
        
        checks = [
            AudioVerifier._check_stream_count(filepath),
            AudioVerifier._check_codec(filepath),
            AudioVerifier._check_duration(filepath)
        ]
        
        passed = sum(checks)
        log_debug(f"Audio verification: {passed}/3 checks passed")
        
        return passed >= 2
    
    @staticmethod
    def _check_stream_count(filepath: str) -> bool:
        """Check if audio stream exists"""
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'a',
            '-show_entries', 'stream=index',
            '-of', 'csv=p=0',
            filepath
        ]
        ok, out, _ = run_command(cmd, 30)
        return ok and bool(out.strip())
    
    @staticmethod
    def _check_codec(filepath: str) -> bool:
        """Check if audio codec is recognized"""
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            filepath
        ]
        ok, out, _ = run_command(cmd, 30)
        
        if ok and out:
            codec = out.strip().lower()
            valid_codecs = ['aac', 'mp3', 'opus', 'vorbis', 'flac', 
                           'ac3', 'eac3', 'pcm', 'alac', 'wmav2']
            return any(c in codec for c in valid_codecs)
        return False
    
    @staticmethod
    def _check_duration(filepath: str) -> bool:
        """Check if audio has non-zero duration"""
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=duration',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            filepath
        ]
        ok, out, _ = run_command(cmd, 30)
        
        if ok and out:
            try:
                duration = float(out.strip())
                return duration > 0.5
            except ValueError:
                pass
        return False
    
    @staticmethod
    def get_file_info(filepath: str) -> Dict[str, Any]:
        """Get detailed file information"""
        info = {
            'filepath': filepath,
            'filesize': 0,
            'duration': 0,
            'width': 0,
            'height': 0,
            'fps': 0,
            'has_video': False,
            'has_audio': False,
            'video_codec': None,
            'audio_codec': None,
            'audio_channels': 0,
            'audio_sample_rate': 0,
            'bitrate': 0
        }
        
        if not os.path.exists(filepath):
            return info
        
        info['filesize'] = os.path.getsize(filepath)
        
        if not HAS_FFPROBE:
            return info
        
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_format', '-show_streams',
            filepath
        ]
        
        ok, out, _ = run_command(cmd, 60)
        
        if not ok or not out:
            return info
        
        try:
            # Find JSON in output
            json_start = out.find('{')
            if json_start == -1:
                return info
            
            data = json.loads(out[json_start:])
            
            # Format info
            fmt = data.get('format', {})
            info['duration'] = float(fmt.get('duration', 0))
            info['bitrate'] = int(fmt.get('bit_rate', 0))
            
            # Stream info
            for stream in data.get('streams', []):
                codec_type = stream.get('codec_type', '').lower()
                
                if codec_type == 'video':
                    # Skip thumbnail streams
                    if stream.get('disposition', {}).get('attached_pic'):
                        continue
                    
                    info['has_video'] = True
                    info['video_codec'] = stream.get('codec_name')
                    info['width'] = int(stream.get('width', 0))
                    info['height'] = int(stream.get('height', 0))
                    
                    # Calculate FPS
                    fps_str = stream.get('r_frame_rate', '0/1')
                    try:
                        num, den = map(int, fps_str.split('/'))
                        info['fps'] = round(num / den) if den else 0
                    except (ValueError, ZeroDivisionError):
                        pass
                
                elif codec_type == 'audio':
                    info['has_audio'] = True
                    info['audio_codec'] = stream.get('codec_name')
                    info['audio_channels'] = int(stream.get('channels', 0))
                    info['audio_sample_rate'] = int(stream.get('sample_rate', 0))
        
        except json.JSONDecodeError:
            pass
        except Exception as e:
            log_debug(f"File info error: {e}")
        
        # Double-check audio
        if not info['has_audio']:
            info['has_audio'] = AudioVerifier.verify(filepath)
        
        return info


# =============================================================================
# Media Merger
# =============================================================================

class MediaMerger:
    """Merge video and audio streams"""
    
    @staticmethod
    def merge_video_audio(video_path: str, audio_path: str, 
                          output_path: str) -> bool:
        """
        Merge video and audio files into single file.
        
        Args:
            video_path: Path to video file
            audio_path: Path to audio file
            output_path: Path for output file
        
        Returns:
            True if successful
        """
        if not HAS_FFMPEG:
            log_error("FFmpeg not available")
            return False
        
        if not os.path.exists(video_path):
            log_error(f"Video not found: {video_path}")
            return False
        
        if not os.path.exists(audio_path):
            log_error(f"Audio not found: {audio_path}")
            return False
        
        log_info("Merging video + audio...")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ac', '2',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',
            '-movflags', '+faststart',
            output_path
        ]
        
        ok, _, err = run_command(cmd, 3600)
        
        if not ok:
            log_error(f"Merge failed: {err[:200] if err else 'Unknown'}")
            return False
        
        if not os.path.exists(output_path):
            log_error("Output file not created")
            return False
        
        # Verify result has audio
        if not AudioVerifier.verify(output_path):
            log_error("Merged file has no audio")
            return False
        
        log_success("Merge complete")
        return True
    
    @staticmethod
    def remux(input_path: str, output_path: str, 
              container: str = 'mp4') -> bool:
        """
        Remux file to different container without re-encoding.
        
        Args:
            input_path: Input file path
            output_path: Output file path
            container: Target container format
        
        Returns:
            True if successful
        """
        if not HAS_FFMPEG:
            return False
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            output_path
        ]
        
        ok, _, err = run_command(cmd, 1800)
        
        if not ok:
            log_error(f"Remux failed: {err[:100] if err else 'Unknown'}")
            return False
        
        return os.path.exists(output_path)


# =============================================================================
# Thumbnail Processor
# =============================================================================

class ThumbnailProcessor:
    """Process and embed thumbnails"""
    
    @staticmethod
    async def download(url: str, output_path: str = None) -> Optional[str]:
        """Download thumbnail from URL"""
        if not url:
            return None
        
        try:
            if not output_path:
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
                output_path = os.path.join(
                    config.paths.temp, f'thumb_{url_hash}.jpg'
                )
            
            headers = {'User-Agent': config.network.user_agent}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        
                        async with aiofiles.open(output_path, 'wb') as f:
                            await f.write(content)
                        
                        # Convert to JPEG if needed
                        if HAS_FFMPEG and not output_path.lower().endswith('.jpg'):
                            jpg_path = output_path.rsplit('.', 1)[0] + '.jpg'
                            cmd = [
                                'ffmpeg', '-y', '-i', output_path,
                                '-vf', 'scale=1280:-1',
                                jpg_path
                            ]
                            ok, _, _ = run_command(cmd, 30)
                            if ok and os.path.exists(jpg_path):
                                os.remove(output_path)
                                return jpg_path
                        
                        return output_path
        
        except Exception as e:
            log_debug(f"Thumbnail download error: {e}")
        
        return None
    
    @staticmethod
    async def embed_in_video(video_path: str, thumbnail_url: str) -> bool:
        """Embed thumbnail in video file"""
        if not HAS_FFMPEG:
            return False
        
        # Download thumbnail
        thumb_path = await ThumbnailProcessor.download(thumbnail_url)
        if not thumb_path:
            return False
        
        try:
            temp_output = video_path + '.temp.mp4'
            
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-i', thumb_path,
                '-map', '0',
                '-map', '1',
                '-c', 'copy',
                '-c:v:1', 'png',
                '-disposition:v:1', 'attached_pic',
                temp_output
            ]
            
            ok, _, err = run_command(cmd, 120)
            
            if ok and os.path.exists(temp_output):
                os.remove(video_path)
                shutil.move(temp_output, video_path)
                log_debug("Thumbnail embedded in video")
                return True
            
            if os.path.exists(temp_output):
                os.remove(temp_output)
            
            log_debug(f"Thumbnail embed failed: {err[:100] if err else 'Unknown'}")
        
        finally:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        
        return False
    
    @staticmethod
    def embed_in_audio(audio_path: str, thumb_path: str,
                       title: str = None, artist: str = None) -> bool:
        """Embed thumbnail and metadata in audio file"""
        if not HAS_FFMPEG:
            return False
        
        if not thumb_path or not os.path.exists(thumb_path):
            return False
        
        try:
            temp_output = audio_path + '.temp' + os.path.splitext(audio_path)[1]
            ext = os.path.splitext(audio_path)[1].lower()
            
            # Build metadata args
            metadata = []
            if title:
                safe_title = ''.join(c if ord(c) < 128 else '?' for c in title)
                metadata.extend(['-metadata', f'title={safe_title}'])
            if artist:
                safe_artist = ''.join(c if ord(c) < 128 else '?' for c in artist)
                metadata.extend(['-metadata', f'artist={safe_artist}'])
            
            if ext == '.mp3':
                cmd = [
                    'ffmpeg', '-y',
                    '-i', audio_path,
                    '-i', thumb_path,
                    '-map', '0:a',
                    '-map', '1:v',
                    '-c:a', 'copy',
                    '-c:v', 'mjpeg',
                    '-id3v2_version', '3',
                    '-metadata:s:v', 'title=Cover',
                    '-metadata:s:v', 'comment=Cover (front)',
                ] + metadata + [temp_output]
            else:
                cmd = [
                    'ffmpeg', '-y',
                    '-i', audio_path,
                    '-i', thumb_path,
                    '-map', '0:a',
                    '-map', '1:v',
                    '-c:a', 'copy',
                    '-c:v', 'png',
                    '-disposition:v:0', 'attached_pic',
                ] + metadata + [temp_output]
            
            ok, _, err = run_command(cmd, 120)
            
            if ok and os.path.exists(temp_output):
                os.remove(audio_path)
                shutil.move(temp_output, audio_path)
                log_debug("Thumbnail embedded in audio")
                return True
            
            if os.path.exists(temp_output):
                os.remove(temp_output)
        
        except Exception as e:
            log_debug(f"Audio thumbnail embed error: {e}")
        
        return False
    
    @staticmethod
    def save_thumbnail(thumb_path: str, title: str) -> Optional[str]:
        """Save thumbnail to thumbnails directory"""
        if not thumb_path or not os.path.exists(thumb_path):
            return None
        
        try:
            safe_title = sanitize_filename(title)
            dest_path = os.path.join(config.paths.thumbnails, f"{safe_title}.jpg")
            dest_path = get_unique_filepath(dest_path)
            
            shutil.copy2(thumb_path, dest_path)
            return dest_path
        except Exception as e:
            log_debug(f"Thumbnail save error: {e}")
        
        return None


# =============================================================================
# Format Converter
# =============================================================================

class FormatConverter:
    """Convert between media formats"""
    
    # Video codec mappings
    VIDEO_CODECS = {
        'mp4': 'libx264',
        'mp4_hevc': 'libx265',
        'webm': 'libvpx-vp9',
        'mkv': 'copy',  # Container only
        'avi': 'mpeg4',
    }
    
    # Audio codec mappings
    AUDIO_CODECS = {
        'mp3': 'libmp3lame',
        'm4a': 'aac',
        'aac': 'aac',
        'opus': 'libopus',
        'ogg': 'libvorbis',
        'flac': 'flac',
        'wav': 'pcm_s16le',
    }
    
    @staticmethod
    def convert_video(input_path: str, output_path: str,
                      video_codec: str = None,
                      audio_codec: str = 'aac',
                      quality: str = 'medium') -> bool:
        """
        Convert video to different format.
        
        Args:
            input_path: Input file path
            output_path: Output file path
            video_codec: Video codec (or 'copy')
            audio_codec: Audio codec (or 'copy')
            quality: Quality preset (low, medium, high)
        
        Returns:
            True if successful
        """
        if not HAS_FFMPEG:
            return False
        
        if not os.path.exists(input_path):
            return False
        
        # Determine codec from output extension
        ext = os.path.splitext(output_path)[1][1:].lower()
        if not video_codec:
            video_codec = FormatConverter.VIDEO_CODECS.get(ext, 'libx264')
        
        # Quality presets
        quality_args = {
            'low': ['-crf', '28', '-preset', 'faster'],
            'medium': ['-crf', '23', '-preset', 'medium'],
            'high': ['-crf', '18', '-preset', 'slow'],
        }
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-c:v', video_codec,
            '-c:a', audio_codec,
        ]
        
        if video_codec not in ['copy', 'libvpx-vp9']:
            cmd.extend(quality_args.get(quality, quality_args['medium']))
        
        cmd.extend(['-movflags', '+faststart', output_path])
        
        log_info(f"Converting to {ext}...")
        ok, _, err = run_command(cmd, 7200)
        
        if not ok:
            log_error(f"Conversion failed: {err[:100] if err else 'Unknown'}")
            return False
        
        return os.path.exists(output_path)
    
    @staticmethod
    def convert_audio(input_path: str, output_path: str,
                      codec: str = None,
                      bitrate: str = '192k') -> bool:
        """
        Convert audio to different format.
        
        Args:
            input_path: Input file path
            output_path: Output file path
            codec: Audio codec
            bitrate: Audio bitrate
        
        Returns:
            True if successful
        """
        if not HAS_FFMPEG:
            return False
        
        if not os.path.exists(input_path):
            return False
        
        ext = os.path.splitext(output_path)[1][1:].lower()
        if not codec:
            codec = FormatConverter.AUDIO_CODECS.get(ext, 'libmp3lame')
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vn',  # No video
            '-c:a', codec,
            '-b:a', bitrate,
            output_path
        ]
        
        log_info(f"Converting to {ext}...")
        ok, _, err = run_command(cmd, 1800)
        
        if not ok:
            log_error(f"Audio conversion failed: {err[:100] if err else 'Unknown'}")
            return False
        
        return os.path.exists(output_path)
    
    @staticmethod
    def extract_audio(video_path: str, output_path: str = None,
                      format: str = 'mp3', bitrate: str = '192k') -> Optional[str]:
        """
        Extract audio from video file.
        
        Args:
            video_path: Input video path
            output_path: Output audio path (auto-generated if None)
            format: Output format
            bitrate: Audio bitrate
        
        Returns:
            Output path if successful
        """
        if not output_path:
            base = os.path.splitext(video_path)[0]
            output_path = f"{base}.{format}"
            output_path = get_unique_filepath(output_path)
        
        if FormatConverter.convert_audio(video_path, output_path, bitrate=bitrate):
            return output_path
        
        return None


# =============================================================================
# File Organizer
# =============================================================================

class FileOrganizer:
    """Organize downloaded files"""
    
    @staticmethod
    def organize_by_platform(filepath: str, platform: Platform) -> str:
        """Move file to platform-specific directory"""
        if not os.path.exists(filepath):
            return filepath
        
        # Determine base directory
        ext = os.path.splitext(filepath)[1].lower()
        if ext in config.VIDEO_EXTENSIONS:
            base_dir = config.paths.videos
        elif ext in config.AUDIO_EXTENSIONS:
            base_dir = config.paths.audio
        elif ext in config.IMAGE_EXTENSIONS:
            base_dir = config.paths.images
        else:
            return filepath
        
        # Create platform subdirectory
        platform_name = platform.name.replace('_', ' ').title()
        platform_dir = os.path.join(base_dir, platform_name)
        os.makedirs(platform_dir, exist_ok=True)
        
        # Move file
        filename = os.path.basename(filepath)
        new_path = os.path.join(platform_dir, filename)
        new_path = get_unique_filepath(new_path)
        
        shutil.move(filepath, new_path)
        return new_path
    
    @staticmethod
    def organize_by_content_type(filepath: str, 
                                  content_type: ContentType) -> str:
        """Move file to content-type specific directory"""
        if not os.path.exists(filepath):
            return filepath
        
        # Determine base directory
        ext = os.path.splitext(filepath)[1].lower()
        if ext in config.VIDEO_EXTENSIONS:
            base_dir = config.paths.videos
        elif ext in config.AUDIO_EXTENSIONS:
            base_dir = config.paths.audio
        else:
            return filepath
        
        # Create content type subdirectory
        type_name = content_type.value.title()
        type_dir = os.path.join(base_dir, type_name)
        os.makedirs(type_dir, exist_ok=True)
        
        # Move file
        filename = os.path.basename(filepath)
        new_path = os.path.join(type_dir, filename)
        new_path = get_unique_filepath(new_path)
        
        shutil.move(filepath, new_path)
        return new_path
    
    @staticmethod
    def organize_playlist(files: List[str], playlist_name: str,
                          base_dir: str = None) -> str:
        """Organize playlist files into directory"""
        base_dir = base_dir or config.paths.videos
        
        safe_name = sanitize_filename(playlist_name)
        playlist_dir = os.path.join(base_dir, safe_name)
        os.makedirs(playlist_dir, exist_ok=True)
        
        for filepath in files:
            if os.path.exists(filepath):
                filename = os.path.basename(filepath)
                new_path = os.path.join(playlist_dir, filename)
                shutil.move(filepath, new_path)
        
        return playlist_dir
    
    @staticmethod
    def cleanup_empty_dirs(base_dir: str = None):
        """Remove empty directories"""
        base_dir = base_dir or config.paths.base_dir
        
        for root, dirs, files in os.walk(base_dir, topdown=False):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except OSError:
                    pass


# =============================================================================
# Metadata Embedder
# =============================================================================

class MetadataEmbedder:
    """Embed metadata into media files"""
    
    @staticmethod
    def embed_video_metadata(filepath: str,
                              title: str = None,
                              artist: str = None,
                              album: str = None,
                              year: str = None,
                              comment: str = None,
                              description: str = None) -> bool:
        """Embed metadata in video file"""
        if not HAS_FFMPEG:
            return False
        
        if not os.path.exists(filepath):
            return False
        
        temp_output = filepath + '.meta.tmp'
        
        cmd = ['ffmpeg', '-y', '-i', filepath]
        
        # Add metadata
        if title:
            cmd.extend(['-metadata', f'title={title}'])
        if artist:
            cmd.extend(['-metadata', f'artist={artist}'])
        if album:
            cmd.extend(['-metadata', f'album={album}'])
        if year:
            cmd.extend(['-metadata', f'year={year}'])
        if comment:
            cmd.extend(['-metadata', f'comment={comment}'])
        if description:
            cmd.extend(['-metadata', f'description={description}'])
        
        cmd.extend(['-c', 'copy', temp_output])
        
        ok, _, _ = run_command(cmd, 300)
        
        if ok and os.path.exists(temp_output):
            os.remove(filepath)
            shutil.move(temp_output, filepath)
            return True
        
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        return False
    
    @staticmethod
    def embed_audio_metadata(filepath: str,
                              title: str = None,
                              artist: str = None,
                              album: str = None,
                              track: int = None,
                              year: str = None,
                              genre: str = None) -> bool:
        """Embed metadata in audio file"""
        if not HAS_FFMPEG:
            return False
        
        if not os.path.exists(filepath):
            return False
        
        temp_output = filepath + '.meta.tmp'
        
        cmd = ['ffmpeg', '-y', '-i', filepath]
        
        if title:
            cmd.extend(['-metadata', f'title={title}'])
        if artist:
            cmd.extend(['-metadata', f'artist={artist}'])
        if album:
            cmd.extend(['-metadata', f'album={album}'])
        if track:
            cmd.extend(['-metadata', f'track={track}'])
        if year:
            cmd.extend(['-metadata', f'year={year}'])
        if genre:
            cmd.extend(['-metadata', f'genre={genre}'])
        
        cmd.extend(['-c', 'copy', temp_output])
        
        ok, _, _ = run_command(cmd, 300)
        
        if ok and os.path.exists(temp_output):
            os.remove(filepath)
            shutil.move(temp_output, filepath)
            return True
        
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        return False


# =============================================================================
# File Integrity Checker
# =============================================================================

class IntegrityChecker:
    """Check file integrity"""
    
    @staticmethod
    def verify_video(filepath: str) -> Dict[str, Any]:
        """Verify video file integrity"""
        result = {
            'valid': False,
            'has_video': False,
            'has_audio': False,
            'playable': False,
            'duration': 0,
            'errors': []
        }
        
        if not os.path.exists(filepath):
            result['errors'].append("File not found")
            return result
        
        if os.path.getsize(filepath) < 1000:
            result['errors'].append("File too small")
            return result
        
        if not HAS_FFPROBE:
            result['valid'] = True  # Assume valid
            return result
        
        # Check with ffprobe
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-show_streams',
            '-of', 'json',
            filepath
        ]
        
        ok, out, err = run_command(cmd, 60)
        
        if not ok:
            result['errors'].append(err[:100] if err else "FFprobe failed")
            return result
        
        try:
            json_start = out.find('{')
            if json_start == -1:
                result['errors'].append("Invalid ffprobe output")
                return result
            
            data = json.loads(out[json_start:])
            
            # Check streams
            for stream in data.get('streams', []):
                codec_type = stream.get('codec_type', '').lower()
                if codec_type == 'video':
                    if not stream.get('disposition', {}).get('attached_pic'):
                        result['has_video'] = True
                elif codec_type == 'audio':
                    result['has_audio'] = True
            
            # Check duration
            fmt = data.get('format', {})
            result['duration'] = float(fmt.get('duration', 0))
            
            result['playable'] = result['has_video'] and result['duration'] > 0
            result['valid'] = result['playable']
        
        except Exception as e:
            result['errors'].append(str(e))
        
        return result
    
    @staticmethod
    def verify_audio(filepath: str) -> Dict[str, Any]:
        """Verify audio file integrity"""
        result = {
            'valid': False,
            'duration': 0,
            'sample_rate': 0,
            'channels': 0,
            'errors': []
        }
        
        if not os.path.exists(filepath):
            result['errors'].append("File not found")
            return result
        
        if os.path.getsize(filepath) < 100:
            result['errors'].append("File too small")
            return result
        
        result['valid'] = AudioVerifier.verify(filepath)
        
        if result['valid']:
            info = AudioVerifier.get_file_info(filepath)
            result['duration'] = info.get('duration', 0)
            result['sample_rate'] = info.get('audio_sample_rate', 0)
            result['channels'] = info.get('audio_channels', 0)
        
        return result


# =============================================================================
# Temp File Manager
# =============================================================================

class TempFileManager:
    """Manage temporary files"""
    
    @staticmethod
    def cleanup(max_age_hours: int = 24) -> int:
        """Clean up old temporary files"""
        import time
        from datetime import datetime, timedelta
        
        removed = 0
        cutoff = time.time() - (max_age_hours * 3600)
        
        temp_dir = config.paths.temp
        if not os.path.exists(temp_dir):
            return 0
        
        for filename in os.listdir(temp_dir):
            filepath = os.path.join(temp_dir, filename)
            try:
                if os.path.isfile(filepath):
                    if os.path.getmtime(filepath) < cutoff:
                        os.remove(filepath)
                        removed += 1
            except Exception:
                pass
        
        log_info(f"Cleaned up {removed} temp files")
        return removed
    
    @staticmethod
    def get_temp_path(prefix: str = "", suffix: str = "") -> str:
        """Get path for temporary file"""
        import uuid
        
        filename = f"{prefix}{uuid.uuid4().hex[:8]}{suffix}"
        return os.path.join(config.paths.temp, filename)
    
    @staticmethod
    def create_temp_dir(prefix: str = "dl_") -> str:
        """Create temporary directory"""
        return tempfile.mkdtemp(prefix=prefix, dir=config.paths.temp)