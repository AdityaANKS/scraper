"""
================================================================================
DATABASE.PY - Database Operations
================================================================================
SQLite database management for storing scraped data, downloads, and metadata.
Efficient queries with proper indexing.
================================================================================
"""

import os
import sqlite3
import json
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager
from dataclasses import asdict

from config import get_config, Platform, ContentType
from models import (
    ScrapedPage, DownloadItem, Playlist, Metadata, MediaInfo,
    DownloadStatus, ExtractedContent, ConnectionGraph
)

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager"""
    
    def __init__(self, db_path: str = None):
        config = get_config()
        self.db_path = db_path or config.paths.database_path
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Get database connection with automatic cleanup"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Domains table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT UNIQUE NOT NULL,
                    platform TEXT DEFAULT 'generic',
                    pages_count INTEGER DEFAULT 0,
                    last_scraped TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Pages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    url_hash TEXT UNIQUE NOT NULL,
                    domain_id INTEGER,
                    
                    title TEXT,
                    description TEXT,
                    content_text TEXT,
                    
                    platform TEXT DEFAULT 'generic',
                    content_type TEXT DEFAULT 'webpage',
                    
                    word_count INTEGER DEFAULT 0,
                    link_count INTEGER DEFAULT 0,
                    image_count INTEGER DEFAULT 0,
                    
                    status_code INTEGER,
                    load_time REAL,
                    
                    parent_url TEXT,
                    depth INTEGER DEFAULT 0,
                    
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    metadata_json TEXT,
                    extra_json TEXT,
                    
                    FOREIGN KEY (domain_id) REFERENCES domains(id)
                )
            ''')
            
            # Links table (connections between pages)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_page_id INTEGER NOT NULL,
                    target_url TEXT NOT NULL,
                    target_page_id INTEGER,
                    
                    link_text TEXT,
                    link_type TEXT DEFAULT 'external',
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (source_page_id) REFERENCES pages(id),
                    FOREIGN KEY (target_page_id) REFERENCES pages(id),
                    UNIQUE(source_page_id, target_url)
                )
            ''')
            
            # Media table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    page_id INTEGER,
                    
                    title TEXT,
                    description TEXT,
                    
                    content_type TEXT NOT NULL,
                    platform TEXT DEFAULT 'generic',
                    
                    filepath TEXT,
                    filename TEXT,
                    filesize INTEGER DEFAULT 0,
                    
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    fps REAL,
                    
                    video_codec TEXT,
                    audio_codec TEXT,
                    video_bitrate INTEGER,
                    audio_bitrate INTEGER,
                    
                    has_audio INTEGER DEFAULT 0,
                    has_thumbnail INTEGER DEFAULT 0,
                    thumbnail_path TEXT,
                    
                    quality TEXT,
                    format TEXT,
                    
                    status TEXT DEFAULT 'pending',
                    error TEXT,
                    
                    download_started TIMESTAMP,
                    download_completed TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    metadata_json TEXT,
                    
                    FOREIGN KEY (page_id) REFERENCES pages(id),
                    UNIQUE(url_hash)
                )
            ''')
            
            # Playlists table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    url_hash TEXT UNIQUE NOT NULL,
                    
                    title TEXT,
                    description TEXT,
                    uploader TEXT,
                    
                    platform TEXT DEFAULT 'generic',
                    
                    total_count INTEGER DEFAULT 0,
                    downloaded_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    
                    output_directory TEXT,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    metadata_json TEXT
                )
            ''')
            
            # Playlist items (join table)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id INTEGER NOT NULL,
                    media_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    
                    FOREIGN KEY (playlist_id) REFERENCES playlists(id),
                    FOREIGN KEY (media_id) REFERENCES media(id),
                    UNIQUE(playlist_id, media_id)
                )
            ''')
            
            # Tags table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Page-tags junction
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS page_tags (
                    page_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (page_id, tag_id),
                    FOREIGN KEY (page_id) REFERENCES pages(id),
                    FOREIGN KEY (tag_id) REFERENCES tags(id)
                )
            ''')
            
            # Media-tags junction
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS media_tags (
                    media_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (media_id, tag_id),
                    FOREIGN KEY (media_id) REFERENCES media(id),
                    FOREIGN KEY (tag_id) REFERENCES tags(id)
                )
            ''')
            
            # Scrape jobs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scrape_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    start_url TEXT NOT NULL,
                    
                    max_depth INTEGER DEFAULT 1,
                    max_pages INTEGER DEFAULT 100,
                    same_domain_only INTEGER DEFAULT 1,
                    
                    pages_scraped INTEGER DEFAULT 0,
                    pages_failed INTEGER DEFAULT 0,
                    media_found INTEGER DEFAULT 0,
                    media_downloaded INTEGER DEFAULT 0,
                    
                    status TEXT DEFAULT 'pending',
                    error TEXT,
                    
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    settings_json TEXT
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_domain ON pages(domain_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_platform ON pages(platform)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pages_scraped ON pages(scraped_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_page_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_page ON media(page_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_type ON media(content_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_status ON media(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_platform ON media(platform)')
            
            logger.info("Database initialized successfully")
    
    # =========================================================================
    # Domain Operations
    # =========================================================================
    
    def add_domain(self, domain: str, platform: str = 'generic') -> int:
        """Add or get domain"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO domains (domain, platform)
                VALUES (?, ?)
            ''', (domain, platform))
            
            cursor.execute('SELECT id FROM domains WHERE domain = ?', (domain,))
            row = cursor.fetchone()
            return row['id'] if row else 0
    
    def update_domain_stats(self, domain_id: int):
        """Update domain statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE domains SET
                    pages_count = (SELECT COUNT(*) FROM pages WHERE domain_id = ?),
                    last_scraped = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (domain_id, domain_id))
    
    # =========================================================================
    # Page Operations
    # =========================================================================
    
    def add_page(self, page: ScrapedPage) -> int:
        """Add scraped page to database"""
        import hashlib
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get or create domain
            domain_id = self.add_domain(page.domain, page.platform.value)
            
            # Prepare metadata JSON
            metadata_json = json.dumps(page.content.metadata.to_dict()) if page.content.metadata else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO pages (
                    url, url_hash, domain_id,
                    title, description, content_text,
                    platform, content_type,
                    word_count, link_count, image_count,
                    status_code, load_time,
                    parent_url, depth,
                    scraped_at, updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                page.url,
                page.url_hash,
                domain_id,
                page.content.title,
                page.content.description,
                page.content.main_text,
                page.platform.value,
                ContentType.WEBPAGE.value,
                page.content.word_count,
                page.content.link_count,
                page.content.image_count,
                page.status_code,
                page.load_time,
                page.parent_url,
                page.depth,
                page.scraped_at.isoformat(),
                datetime.now().isoformat(),
                metadata_json
            ))
            
            page_id = cursor.lastrowid
            
            # Update domain stats
            self.update_domain_stats(domain_id)
            
            return page_id
    
    def get_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Get page by URL"""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pages WHERE url_hash = ?', (url_hash,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def page_exists(self, url: str) -> bool:
        """Check if page exists"""
        return self.get_page(url) is not None
    
    def get_pages_by_domain(self, domain: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all pages for a domain"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.* FROM pages p
                JOIN domains d ON p.domain_id = d.id
                WHERE d.domain = ?
                ORDER BY p.scraped_at DESC
                LIMIT ?
            ''', (domain, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # Link Operations
    # =========================================================================
    
    def add_links(self, page_id: int, links: List[Dict[str, str]]):
        """Add links from a page"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for link in links:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO links (source_page_id, target_url, link_text, link_type)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        page_id,
                        link.get('url', ''),
                        link.get('text', '')[:500],
                        link.get('type', 'external')
                    ))
                except:
                    pass
    
    def get_outgoing_links(self, page_id: int) -> List[Dict[str, Any]]:
        """Get all links from a page"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM links WHERE source_page_id = ?
            ''', (page_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_incoming_links(self, url: str) -> List[Dict[str, Any]]:
        """Get all links pointing to a URL"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT l.*, p.url as source_url, p.title as source_title
                FROM links l
                JOIN pages p ON l.source_page_id = p.id
                WHERE l.target_url = ?
            ''', (url,))
            return [dict(row) for row in cursor.fetchall()]
    
    def build_connection_graph(self, domain: str = None) -> ConnectionGraph:
        """Build connection graph from stored links"""
        graph = ConnectionGraph()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if domain:
                cursor.execute('''
                    SELECT p.url, p.title, p.platform, l.target_url
                    FROM pages p
                    JOIN domains d ON p.domain_id = d.id
                    LEFT JOIN links l ON p.id = l.source_page_id
                    WHERE d.domain = ?
                ''', (domain,))
            else:
                cursor.execute('''
                    SELECT p.url, p.title, p.platform, l.target_url
                    FROM pages p
                    LEFT JOIN links l ON p.id = l.source_page_id
                ''')
            
            for row in cursor.fetchall():
                source_url = row['url']
                target_url = row['target_url']
                
                # Add source node
                node = graph.add_node(
                    source_url,
                    title=row['title'] or '',
                    platform=Platform(row['platform']) if row['platform'] else Platform.GENERIC
                )
                
                # Add link if exists
                if target_url:
                    graph.add_link(source_url, target_url)
        
        return graph
    
    # =========================================================================
    # Media Operations
    # =========================================================================
    
    def add_media(self, item: DownloadItem, page_id: int = None) -> int:
        """Add media item to database"""
        import hashlib
        url_hash = hashlib.md5(item.url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            metadata_json = json.dumps(item.metadata.to_dict()) if item.metadata else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO media (
                    url, url_hash, page_id,
                    title, description,
                    content_type, platform,
                    filepath, filename, filesize,
                    width, height, duration, fps,
                    video_codec, audio_codec,
                    video_bitrate, audio_bitrate,
                    has_audio, has_thumbnail, thumbnail_path,
                    quality, format,
                    status, error,
                    download_started, download_completed,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.url,
                url_hash,
                page_id,
                item.metadata.title if item.metadata else '',
                item.metadata.description if item.metadata else '',
                item.content_type.value,
                item.platform.value,
                item.output_path,
                item.output_filename,
                item.media_info.filesize,
                item.media_info.width,
                item.media_info.height,
                item.media_info.duration,
                item.media_info.fps,
                item.media_info.video_codec,
                item.media_info.audio_codec,
                item.media_info.video_bitrate,
                item.media_info.audio_bitrate,
                1 if item.media_info.has_audio else 0,
                1 if item.media_info.has_thumbnail else 0,
                item.thumbnail_path,
                item.video_quality.label if item.video_quality else '',
                item.media_info.format,
                item.status.value,
                item.error,
                item.started_at.isoformat() if item.started_at else None,
                item.completed_at.isoformat() if item.completed_at else None,
                metadata_json
            ))
            
            return cursor.lastrowid
    
    def update_media_status(self, url: str, status: DownloadStatus, error: str = None):
        """Update media download status"""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if status == DownloadStatus.COMPLETED:
                cursor.execute('''
                    UPDATE media SET
                        status = ?,
                        download_completed = CURRENT_TIMESTAMP
                    WHERE url_hash = ?
                ''', (status.value, url_hash))
            elif status == DownloadStatus.DOWNLOADING:
                cursor.execute('''
                    UPDATE media SET
                        status = ?,
                        download_started = CURRENT_TIMESTAMP
                    WHERE url_hash = ?
                ''', (status.value, url_hash))
            else:
                cursor.execute('''
                    UPDATE media SET
                        status = ?,
                        error = ?
                    WHERE url_hash = ?
                ''', (status.value, error, url_hash))
    
    def get_media(self, url: str) -> Optional[Dict[str, Any]]:
        """Get media by URL"""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM media WHERE url_hash = ?', (url_hash,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_media_by_status(self, status: DownloadStatus, limit: int = 100) -> List[Dict[str, Any]]:
        """Get media by status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM media WHERE status = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (status.value, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_media_by_platform(self, platform: Platform, limit: int = 100) -> List[Dict[str, Any]]:
        """Get media by platform"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM media WHERE platform = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (platform.value, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # Playlist Operations
    # =========================================================================
    
    def add_playlist(self, playlist: Playlist) -> int:
        """Add playlist to database"""
        import hashlib
        url_hash = hashlib.md5(playlist.url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO playlists (
                    url, url_hash,
                    title, description, uploader,
                    platform,
                    total_count, downloaded_count, failed_count,
                    output_directory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                playlist.url,
                url_hash,
                playlist.title,
                playlist.description,
                playlist.uploader,
                playlist.platform.value,
                playlist.total_count,
                playlist.downloaded_count,
                playlist.failed_count,
                ''
            ))
            
            return cursor.lastrowid
    
    def update_playlist_progress(self, url: str, downloaded: int, failed: int = 0):
        """Update playlist download progress"""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE playlists SET
                    downloaded_count = ?,
                    failed_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE url_hash = ?
            ''', (downloaded, failed, url_hash))
    
    # =========================================================================
    # Tag Operations
    # =========================================================================
    
    def add_tag(self, name: str, category: str = 'general') -> int:
        """Add or get tag"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO tags (name, category)
                VALUES (?, ?)
            ''', (name.lower(), category))
            
            cursor.execute('SELECT id FROM tags WHERE name = ?', (name.lower(),))
            row = cursor.fetchone()
            return row['id'] if row else 0
    
    def tag_page(self, page_id: int, tags: List[str]):
        """Add tags to a page"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for tag_name in tags:
                tag_id = self.add_tag(tag_name)
                cursor.execute('''
                    INSERT OR IGNORE INTO page_tags (page_id, tag_id)
                    VALUES (?, ?)
                ''', (page_id, tag_id))
    
    def tag_media(self, media_id: int, tags: List[str]):
        """Add tags to media"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for tag_name in tags:
                tag_id = self.add_tag(tag_name)
                cursor.execute('''
                    INSERT OR IGNORE INTO media_tags (media_id, tag_id)
                    VALUES (?, ?)
                ''', (media_id, tag_id))
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute('SELECT COUNT(*) FROM domains')
            stats['domains'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM pages')
            stats['pages'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM links')
            stats['links'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media')
            stats['total_media'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media WHERE content_type = ?', (ContentType.VIDEO.value,))
            stats['videos'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media WHERE content_type = ?', (ContentType.AUDIO.value,))
            stats['audio'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media WHERE content_type = ?', (ContentType.IMAGE.value,))
            stats['images'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media WHERE status = ?', (DownloadStatus.COMPLETED.value,))
            stats['downloads_completed'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM media WHERE status = ?', (DownloadStatus.FAILED.value,))
            stats['downloads_failed'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM playlists')
            stats['playlists'] = cursor.fetchone()[0]
            
            cursor.execute('SELECT SUM(filesize) FROM media WHERE filesize > 0')
            total_size = cursor.fetchone()[0] or 0
            stats['total_size_bytes'] = total_size
            stats['total_size_human'] = format_size(total_size)
            
            cursor.execute('SELECT COUNT(*) FROM tags')
            stats['tags'] = cursor.fetchone()[0]
            
            return stats
    
    # =========================================================================
    # Search
    # =========================================================================
    
    def search(self, query: str, limit: int = 50) -> Dict[str, List[Dict]]:
        """Search across all tables"""
        results = {'pages': [], 'media': [], 'playlists': []}
        pattern = f'%{query}%'
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Search pages
            cursor.execute('''
                SELECT id, url, title, platform, scraped_at
                FROM pages
                WHERE title LIKE ? OR url LIKE ? OR content_text LIKE ?
                ORDER BY scraped_at DESC
                LIMIT ?
            ''', (pattern, pattern, pattern, limit))
            results['pages'] = [dict(row) for row in cursor.fetchall()]
            
            # Search media
            cursor.execute('''
                SELECT id, url, title, content_type, platform, status, filepath
                FROM media
                WHERE title LIKE ? OR url LIKE ? OR filename LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (pattern, pattern, pattern, limit))
            results['media'] = [dict(row) for row in cursor.fetchall()]
            
            # Search playlists
            cursor.execute('''
                SELECT id, url, title, uploader, platform, total_count, downloaded_count
                FROM playlists
                WHERE title LIKE ? OR url LIKE ? OR uploader LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (pattern, pattern, pattern, limit))
            results['playlists'] = [dict(row) for row in cursor.fetchall()]
        
        return results
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    def cleanup_orphaned_records(self) -> int:
        """Remove orphaned records"""
        removed = 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Remove links to non-existent pages
            cursor.execute('''
                DELETE FROM links
                WHERE source_page_id NOT IN (SELECT id FROM pages)
            ''')
            removed += cursor.rowcount
            
            # Remove orphaned tags
            cursor.execute('''
                DELETE FROM tags
                WHERE id NOT IN (
                    SELECT tag_id FROM page_tags
                    UNION
                    SELECT tag_id FROM media_tags
                )
            ''')
            removed += cursor.rowcount
        
        return removed
    
    def vacuum(self):
        """Optimize database"""
        with self.get_connection() as conn:
            conn.execute('VACUUM')


# Format size helper (if not imported)
def format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get or create global database instance"""
    global _db
    if _db is None:
        _db = Database()
    return _db