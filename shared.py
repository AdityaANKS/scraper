"""
Shared infrastructure for scraper + OSINT modules.
Provides: session management, rate limiting, caching, config.
"""

try:
    import aiohttp
except ImportError:
    aiohttp = None

import asyncio
import time
import logging
from typing import Optional, Dict, Any, Tuple, TYPE_CHECKING
from urllib.parse import urlparse

from config import config

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Singleton shared session manager.
    Used by: scraper.py, osint.py, osint_cli.py
    """
    _instance: Optional['SessionManager'] = None

    def __init__(self):
        self._session: Optional['aiohttp.ClientSession'] = None
        self._semaphore = asyncio.Semaphore(15)
        self._host_delays: Dict[str, float] = {}  # host -> last_request_time
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 300  # 5 minutes

    @classmethod
    def get(cls) -> 'SessionManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def session(self) -> aiohttp.ClientSession:
        """Get or create shared session"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=20,
                limit_per_host=5,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': config.network.user_agent},
            )
        return self._session

    async def fetch(self, url: str, use_cache: bool = True, **kwargs) -> Optional[str]:
        """Rate-limited, cached fetch"""
        # Check cache
        if use_cache:
            cached = self._get_cache(url)
            if cached is not None:
                return cached

        host = urlparse(url).netloc
        async with self._semaphore:
            # Per-host rate limiting
            now = time.time()
            last = self._host_delays.get(host, 0)
            wait = max(0, 0.1 - (now - last))
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_delays[host] = time.time()

            session = await self.session()
            try:
                async with session.get(url, **kwargs) as r:
                    if r.status == 200:
                        text = await r.text()
                        if use_cache:
                            self._set_cache(url, text)
                        return text
            except Exception as e:
                logger.debug(f"Fetch failed for {url}: {e}")
        return None

    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
            del self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        self._cache[key] = (time.time(), value)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._cache.clear()
