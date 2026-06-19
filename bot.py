"""
================================================================================
BOT.PY - Anti-Detection Browser Automation Module
================================================================================
Professional-grade anti-bot detection evasion and browser automation.
Provides stealth capabilities for accessing protected content.

FEATURES:
---------
  • Browser Automation (Playwright/Selenium)
  • Anti-bot Detection Evasion
  • Cloudflare Bypass
  • Cookie Handling & Persistence
  • Session Management
  • Proxy Support (HTTP/SOCKS)
  • User-Agent Rotation
  • JavaScript Rendering
  • CAPTCHA Handling Hints
  • Rate Limiting
  • Request Headers Management
  • Browser Fingerprint Randomization

USAGE:
------
  # As stealth HTTP session
  async with StealthSession() as session:
      html = await session.get("https://example.com")

  # As stealth browser
  async with StealthBrowser() as browser:
      await browser.goto("https://example.com")
      html = await browser.content()

  # High-level function
  html, cookies = await fetch_with_stealth("https://example.com")

REQUIREMENTS:
-------------
  pip install aiohttp requests
  
  # For browser automation (optional but recommended):
  pip install playwright && playwright install chromium
  
  # For better Cloudflare bypass:
  pip install curl_cffi
  
  # For undetected Chrome:
  pip install undetected-chromedriver selenium

================================================================================
"""

import os
import sys
import json
import time
import random
import asyncio
import hashlib
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Dict, List, Optional, Any, Tuple, Set, 
    Callable, Union, Type, Awaitable
)
from urllib.parse import urlparse, urljoin, parse_qs
from enum import Enum, auto
from pathlib import Path
import base64
import re

# =============================================================================
# Optional Imports - Check Availability
# =============================================================================

# Core HTTP
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None

# Browser Automation
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    async_playwright = None
    Browser = None
    Page = None
    BrowserContext = None
    PlaywrightTimeout = Exception

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, WebDriverException, 
        NoSuchElementException, StaleElementReferenceException
    )
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False
    webdriver = None
    ChromeOptions = None
    By = None
    WebDriverWait = None
    EC = None
    TimeoutException = Exception
    WebDriverException = Exception

try:
    import undetected_chromedriver as uc
    HAS_UNDETECTED_CHROME = True
except ImportError:
    HAS_UNDETECTED_CHROME = False
    uc = None

# Cloudflare bypass
try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import Session as CurlSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    curl_requests = None
    CurlSession = None


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class BotConfig:
    """Bot module configuration"""
    
    # Paths
    base_dir: str = os.path.join(tempfile.gettempdir(), "bot_data")
    cookies_dir: str = field(default="")
    profiles_dir: str = field(default="")
    cache_dir: str = field(default="")
    
    # Browser settings
    headless: bool = True
    browser_type: str = "chromium"  # chromium, firefox, webkit
    window_width: int = 1920
    window_height: int = 1080
    
    # Timeouts (seconds)
    page_load_timeout: int = 30
    element_timeout: int = 10
    request_timeout: int = 30
    
    # Rate limiting
    requests_per_minute: int = 30
    min_request_delay: float = 0.5
    max_request_delay: float = 2.0
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # Stealth settings
    use_stealth: bool = True
    rotate_user_agents: bool = True
    randomize_fingerprint: bool = True
    
    # Proxy
    proxy_enabled: bool = False
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    
    # Cloudflare
    solve_cloudflare: bool = True
    cloudflare_timeout: int = 30
    
    # Cookies
    persist_cookies: bool = True
    cookie_ttl_hours: int = 24
    
    def __post_init__(self):
        """Initialize directories"""
        self.cookies_dir = os.path.join(self.base_dir, "cookies")
        self.profiles_dir = os.path.join(self.base_dir, "profiles")
        self.cache_dir = os.path.join(self.base_dir, "cache")
        
        for dir_path in [self.base_dir, self.cookies_dir, 
                         self.profiles_dir, self.cache_dir]:
            os.makedirs(dir_path, exist_ok=True)


# Global config instance
bot_config = BotConfig()


# =============================================================================
# User Agent Database
# =============================================================================

class UserAgentDatabase:
    """Database of real browser user agents"""
    
    # Chrome on Windows (most common)
    CHROME_WINDOWS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ]
    
    # Chrome on macOS
    CHROME_MAC = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    
    # Chrome on Linux
    CHROME_LINUX = [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ]
    
    # Firefox on Windows
    FIREFOX_WINDOWS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
    ]
    
    # Firefox on macOS
    FIREFOX_MAC = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    # Edge on Windows
    EDGE_WINDOWS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    ]
    
    # Safari on macOS
    SAFARI_MAC = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    ]
    
    # Mobile - iOS
    MOBILE_IOS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    ]
    
    # Mobile - Android
    MOBILE_ANDROID = [
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    ]
    
    # All desktop user agents
    ALL_DESKTOP = (
        CHROME_WINDOWS + CHROME_MAC + CHROME_LINUX + 
        FIREFOX_WINDOWS + FIREFOX_MAC + 
        EDGE_WINDOWS + SAFARI_MAC
    )
    
    # All mobile user agents
    ALL_MOBILE = MOBILE_IOS + MOBILE_ANDROID
    
    # All user agents
    ALL = ALL_DESKTOP + ALL_MOBILE
    
    @classmethod
    def get_random(cls, mobile: bool = False) -> str:
        """Get random user agent"""
        if mobile:
            return random.choice(cls.ALL_MOBILE)
        return random.choice(cls.ALL_DESKTOP)
    
    @classmethod
    def get_chrome_windows(cls) -> str:
        """Get Chrome Windows user agent (most common)"""
        return random.choice(cls.CHROME_WINDOWS)
    
    @classmethod
    def get_for_browser(cls, browser: str = "chrome", 
                        platform: str = "windows") -> str:
        """Get user agent for specific browser/platform"""
        key = f"{browser.upper()}_{platform.upper()}"
        agents = getattr(cls, key, cls.CHROME_WINDOWS)
        return random.choice(agents)


# =============================================================================
# Browser Fingerprint
# =============================================================================

@dataclass
class BrowserFingerprint:
    """
    Browser fingerprint for consistent identity.
    All properties should be internally consistent.
    """
    
    # Core identity
    user_agent: str = ""
    platform: str = "Win32"  # Win32, MacIntel, Linux x86_64
    
    # Language/locale
    language: str = "en-US"
    languages: List[str] = field(default_factory=lambda: ["en-US", "en"])
    timezone: str = "America/New_York"
    timezone_offset: int = -300  # minutes from UTC
    
    # Screen
    screen_width: int = 1920
    screen_height: int = 1080
    avail_width: int = 1920
    avail_height: int = 1040
    color_depth: int = 24
    pixel_ratio: float = 1.0
    
    # Hardware
    hardware_concurrency: int = 8  # CPU cores
    device_memory: int = 8  # GB
    max_touch_points: int = 0
    
    # WebGL
    webgl_vendor: str = "Google Inc. (NVIDIA)"
    webgl_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    
    # Canvas/Audio hashes (for consistency)
    canvas_hash: str = ""
    audio_hash: str = ""
    
    # Plugins (Chrome typically has these)
    plugins: List[str] = field(default_factory=lambda: [
        "PDF Viewer",
        "Chrome PDF Viewer",
        "Chromium PDF Viewer",
        "Microsoft Edge PDF Viewer",
        "WebKit built-in PDF"
    ])
    
    # Features
    webdriver: bool = False
    has_touch: bool = False
    cookies_enabled: bool = True
    do_not_track: Optional[str] = None
    
    @classmethod
    def generate(cls, mobile: bool = False, 
                 user_agent: str = None) -> 'BrowserFingerprint':
        """Generate a random but consistent fingerprint"""
        
        # Get user agent
        ua = user_agent or UserAgentDatabase.get_random(mobile)
        
        # Determine platform from UA
        if "Windows" in ua:
            platform = "Win32"
            if "Win64" in ua or "x64" in ua:
                platform = "Win32"  # Still Win32 in navigator
        elif "Mac" in ua:
            platform = "MacIntel"
        elif "Linux" in ua:
            platform = "Linux x86_64"
        elif "iPhone" in ua or "iPad" in ua:
            platform = "iPhone" if "iPhone" in ua else "iPad"
        elif "Android" in ua:
            platform = "Linux armv8l"
        else:
            platform = "Win32"
        
        # Screen dimensions
        if mobile:
            screens = [
                (390, 844, 3.0),   # iPhone 14
                (393, 873, 3.0),   # iPhone 15
                (412, 915, 2.625), # Pixel 7
                (360, 800, 3.0),   # Samsung
            ]
            width, height, ratio = random.choice(screens)
        else:
            screens = [
                (1920, 1080, 1.0),
                (2560, 1440, 1.0),
                (1680, 1050, 1.0),
                (1440, 900, 1.0),
                (1920, 1080, 1.25),
                (3840, 2160, 2.0),
            ]
            width, height, ratio = random.choice(screens)
        
        # Timezone
        timezones = [
            ("America/New_York", -300),
            ("America/Chicago", -360),
            ("America/Denver", -420),
            ("America/Los_Angeles", -480),
            ("Europe/London", 0),
            ("Europe/Paris", 60),
            ("Asia/Tokyo", 540),
        ]
        tz_name, tz_offset = random.choice(timezones)
        
        # Hardware
        cores = random.choice([4, 8, 12, 16])
        memory = random.choice([4, 8, 16, 32])
        
        # WebGL
        webgl_configs = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ]
        webgl_vendor, webgl_renderer = random.choice(webgl_configs)
        
        # Generate hashes
        canvas_hash = hashlib.md5(f"{ua}{width}{height}".encode()).hexdigest()[:16]
        audio_hash = hashlib.md5(f"{ua}{cores}".encode()).hexdigest()[:16]
        
        return cls(
            user_agent=ua,
            platform=platform,
            language="en-US",
            languages=["en-US", "en"],
            timezone=tz_name,
            timezone_offset=tz_offset,
            screen_width=width,
            screen_height=height,
            avail_width=width,
            avail_height=height - 40,  # Taskbar
            color_depth=24,
            pixel_ratio=ratio,
            hardware_concurrency=cores,
            device_memory=memory,
            max_touch_points=5 if mobile else 0,
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
            canvas_hash=canvas_hash,
            audio_hash=audio_hash,
            has_touch=mobile,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            k: v for k, v in self.__dict__.items() 
            if not k.startswith('_')
        }


# =============================================================================
# Headers Generator
# =============================================================================

class HeadersGenerator:
    """Generate realistic HTTP headers"""
    
    # Accept headers
    ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ACCEPT_JSON = "application/json, text/plain, */*"
    ACCEPT_ALL = "*/*"
    ACCEPT_IMAGE = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    
    # Accept-Language variants
    ACCEPT_LANGUAGES = [
        "en-US,en;q=0.9",
        "en-GB,en;q=0.9",
        "en-US,en;q=0.9,es;q=0.8",
        "en-US,en;q=0.9,fr;q=0.8",
    ]
    
    ACCEPT_ENCODING = "gzip, deflate, br"
    
    # Sec-CH-UA variants (Chrome)
    SEC_CH_UA_VARIANTS = [
        '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        '"Not_A Brand";v="8", "Chromium";v="121", "Google Chrome";v="121"',
        '"Not_A Brand";v="8", "Chromium";v="119", "Google Chrome";v="119"',
        '"Not_A Brand";v="8", "Chromium";v="122", "Google Chrome";v="122"',
    ]
    
    @classmethod
    def generate(cls,
                 url: str,
                 fingerprint: BrowserFingerprint = None,
                 referer: str = None,
                 is_xhr: bool = False,
                 is_navigation: bool = True,
                 extra_headers: Dict[str, str] = None) -> Dict[str, str]:
        """
        Generate complete, realistic HTTP headers.
        
        Args:
            url: Target URL
            fingerprint: Browser fingerprint to use
            referer: Referer URL
            is_xhr: True for AJAX/fetch requests
            is_navigation: True for page navigation
            extra_headers: Additional headers to include
        """
        fp = fingerprint or BrowserFingerprint.generate()
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        
        # Base headers
        headers = {
            "User-Agent": fp.user_agent,
            "Accept-Language": random.choice(cls.ACCEPT_LANGUAGES),
            "Accept-Encoding": cls.ACCEPT_ENCODING,
            "Connection": "keep-alive",
        }
        
        # Accept header based on request type
        if is_xhr:
            headers["Accept"] = cls.ACCEPT_JSON
        else:
            headers["Accept"] = cls.ACCEPT_HTML
        
        # Chrome-specific headers
        if "Chrome" in fp.user_agent and "Edg" not in fp.user_agent:
            headers["sec-ch-ua"] = random.choice(cls.SEC_CH_UA_VARIANTS)
            headers["sec-ch-ua-mobile"] = "?1" if fp.has_touch else "?0"
            headers["sec-ch-ua-platform"] = f'"{cls._get_platform_name(fp.platform)}"'
        
        # Sec-Fetch headers (modern browsers)
        if is_navigation:
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "none" if not referer else "same-origin"
            headers["Sec-Fetch-User"] = "?1"
            headers["Upgrade-Insecure-Requests"] = "1"
        elif is_xhr:
            headers["Sec-Fetch-Dest"] = "empty"
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Site"] = "same-origin"
        
        # Referer/Origin
        if referer:
            headers["Referer"] = referer
            if is_xhr:
                headers["Origin"] = origin
        
        # Extra headers
        if extra_headers:
            headers.update(extra_headers)
        
        # Remove None values
        return {k: v for k, v in headers.items() if v is not None}
    
    @classmethod
    def _get_platform_name(cls, platform: str) -> str:
        """Convert navigator.platform to sec-ch-ua-platform name"""
        mapping = {
            "Win32": "Windows",
            "MacIntel": "macOS",
            "Linux x86_64": "Linux",
            "Linux armv8l": "Android",
            "iPhone": "iOS",
            "iPad": "iOS",
        }
        return mapping.get(platform, "Windows")
    
    @classmethod
    def generate_xhr(cls, url: str, referer: str = None,
                     fingerprint: BrowserFingerprint = None) -> Dict[str, str]:
        """Generate headers for XHR/fetch request"""
        headers = cls.generate(
            url, fingerprint, referer, 
            is_xhr=True, is_navigation=False
        )
        headers["X-Requested-With"] = "XMLHttpRequest"
        return headers


# =============================================================================
# Cookie Manager
# =============================================================================

class CookieManager:
    """Manage cookies with persistence"""
    
    def __init__(self, domain: str, persist: bool = True):
        self.domain = self._normalize_domain(domain)
        self.persist = persist
        self.cookies: Dict[str, Dict[str, Any]] = {}
        self.filepath = os.path.join(
            bot_config.cookies_dir,
            f"{self._safe_filename(self.domain)}.json"
        )
        
        if persist:
            self._load()
    
    def _normalize_domain(self, domain: str) -> str:
        """Normalize domain (remove www., etc.)"""
        domain = domain.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    
    def _safe_filename(self, name: str) -> str:
        """Convert to safe filename"""
        return re.sub(r'[^\w\-.]', '_', name)
    
    def _load(self) -> None:
        """Load cookies from file"""
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Check expiry
                expires = data.get('_expires', 0)
                if expires > time.time():
                    self.cookies = data.get('cookies', {})
        except Exception:
            pass
    
    def _save(self) -> None:
        """Save cookies to file"""
        if not self.persist:
            return
        
        try:
            data = {
                'domain': self.domain,
                'cookies': self.cookies,
                '_expires': time.time() + (bot_config.cookie_ttl_hours * 3600),
                '_saved_at': datetime.now().isoformat()
            }
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
    
    def set(self, name: str, value: str, **kwargs) -> None:
        """Set a cookie"""
        self.cookies[name] = {
            'value': value,
            'domain': kwargs.get('domain', self.domain),
            'path': kwargs.get('path', '/'),
            'secure': kwargs.get('secure', True),
            'httpOnly': kwargs.get('httpOnly', False),
            'sameSite': kwargs.get('sameSite', 'Lax'),
            'expires': kwargs.get('expires'),
        }
        self._save()
    
    def get(self, name: str) -> Optional[str]:
        """Get cookie value"""
        cookie = self.cookies.get(name)
        if cookie:
            return cookie.get('value')
        return None
    
    def delete(self, name: str) -> None:
        """Delete a cookie"""
        if name in self.cookies:
            del self.cookies[name]
            self._save()
    
    def clear(self) -> None:
        """Clear all cookies"""
        self.cookies = {}
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
    
    def update_from_response(self, response_cookies: Dict[str, str]) -> None:
        """Update cookies from response"""
        for name, value in response_cookies.items():
            self.set(name, value)
    
    def update_from_browser(self, cookies: List[Dict]) -> None:
        """Update cookies from browser cookie list"""
        for cookie in cookies:
            name = cookie.get('name')
            value = cookie.get('value')
            if name and value:
                self.set(name, value, **cookie)
    
    def get_header_string(self) -> str:
        """Get cookies as header string"""
        return "; ".join(
            f"{name}={data['value']}" 
            for name, data in self.cookies.items()
        )
    
    def get_dict(self) -> Dict[str, str]:
        """Get cookies as simple dict"""
        return {
            name: data['value'] 
            for name, data in self.cookies.items()
        }
    
    def get_list(self) -> List[Dict]:
        """Get cookies as list (for browser)"""
        result = []
        for name, data in self.cookies.items():
            cookie = {
                'name': name,
                'value': data['value'],
                'domain': data.get('domain', self.domain),
                'path': data.get('path', '/'),
            }
            if data.get('secure'):
                cookie['secure'] = True
            if data.get('httpOnly'):
                cookie['httpOnly'] = True
            result.append(cookie)
        return result
    
    def has_cloudflare_cookies(self) -> bool:
        """Check if Cloudflare cookies exist"""
        cf_cookies = ['cf_clearance', '__cf_bm', 'cf_chl_2']
        return any(name in self.cookies for name in cf_cookies)


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Rate limiting with per-domain tracking"""
    
    def __init__(self, 
                 requests_per_minute: int = 30,
                 min_delay: float = 0.5,
                 max_delay: float = 2.0):
        self.requests_per_minute = requests_per_minute
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.request_times: Dict[str, List[float]] = {}
        self.lock = threading.Lock()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
    
    def wait(self, url: str = None) -> float:
        """Wait if necessary, return actual wait time"""
        domain = self._get_domain(url) if url else "default"
        
        with self.lock:
            now = time.time()
            
            # Get/create domain entry
            if domain not in self.request_times:
                self.request_times[domain] = []
            
            times = self.request_times[domain]
            
            # Remove old entries (older than 1 minute)
            times = [t for t in times if now - t < 60]
            self.request_times[domain] = times
            
            wait_time = 0.0
            
            # Check rate limit
            if len(times) >= self.requests_per_minute:
                # Wait until oldest request expires
                wait_time = 60 - (now - times[0])
                if wait_time > 0:
                    time.sleep(wait_time)
            
            # Add random delay
            delay = random.uniform(self.min_delay, self.max_delay)
            time.sleep(delay)
            wait_time += delay
            
            # Record this request
            self.request_times[domain].append(time.time())
            
            return wait_time
    
    async def wait_async(self, url: str = None) -> float:
        """Async version of wait"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.wait, url
        )
    
    def get_remaining(self, url: str = None) -> int:
        """Get remaining requests for domain"""
        domain = self._get_domain(url) if url else "default"
        
        with self.lock:
            now = time.time()
            times = self.request_times.get(domain, [])
            times = [t for t in times if now - t < 60]
            return max(0, self.requests_per_minute - len(times))


# =============================================================================
# Cloudflare Detection & Bypass
# =============================================================================

class CloudflareHandler:
    """Detect and handle Cloudflare protection"""
    
    # Detection patterns
    CHALLENGE_PATTERNS = [
        "Checking your browser",
        "Please Wait... | Cloudflare",
        "Just a moment...",
        "cf-browser-verification",
        "challenge-platform",
        "cf_chl_opt",
        "ray ID:",
        "_cf_chl_tk",
    ]
    
    CHALLENGE_TITLES = [
        "Just a moment...",
        "Attention Required! | Cloudflare",
        "Please Wait... | Cloudflare",
    ]
    
    COOKIE_NAMES = ['cf_clearance', '__cf_bm', 'cf_chl_2', 'cf_chl_rc_i']
    
    @classmethod
    def is_challenge(cls, html: str, status_code: int = 200) -> bool:
        """Check if response is a Cloudflare challenge"""
        if not html:
            return False
        
        # Check status code
        if status_code in [403, 503]:
            if any(p in html for p in cls.CHALLENGE_PATTERNS):
                return True
        
        # Check for challenge patterns
        html_lower = html.lower()
        
        for pattern in cls.CHALLENGE_PATTERNS:
            if pattern.lower() in html_lower:
                return True
        
        # Check title
        title_match = re.search(r'<title>([^<]+)</title>', html, re.I)
        if title_match:
            title = title_match.group(1)
            for cf_title in cls.CHALLENGE_TITLES:
                if cf_title.lower() in title.lower():
                    return True
        
        return False
    
    @classmethod
    def is_blocked(cls, html: str) -> bool:
        """Check if blocked by Cloudflare"""
        if not html:
            return False
        
        block_patterns = [
            "Access denied",
            "Error 1015",
            "You have been blocked",
            "Sorry, you have been blocked",
        ]
        
        return any(p.lower() in html.lower() for p in block_patterns)
    
    @classmethod
    async def solve_with_browser(cls,
                                  url: str,
                                  headless: bool = False,
                                  timeout: int = 30) -> Optional[Dict]:
        """
        Solve Cloudflare challenge using browser.
        Returns cookies and content if successful.
        """
        if not HAS_PLAYWRIGHT:
            return None
        
        try:
            async with StealthBrowser(headless=headless) as browser:
                # Navigate to page
                await browser.goto(url, timeout=timeout * 1000)
                
                # Wait for challenge to complete
                start = time.time()
                while time.time() - start < timeout:
                    content = await browser.content()
                    
                    if not cls.is_challenge(content):
                        # Challenge passed
                        cookies = await browser.get_cookies()
                        return {
                            'success': True,
                            'content': content,
                            'cookies': cookies,
                            'user_agent': browser.fingerprint.user_agent
                        }
                    
                    await asyncio.sleep(1)
                
                return {'success': False, 'error': 'Timeout'}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def solve_with_curl_cffi(cls, url: str, 
                              timeout: int = 30) -> Optional[Tuple[int, str, Dict]]:
        """
        Attempt bypass using curl_cffi's browser impersonation.
        Returns (status_code, content, cookies) if successful.
        """
        if not HAS_CURL_CFFI:
            return None
        
        try:
            # curl_cffi impersonates browser TLS fingerprint
            response = curl_requests.get(
                url,
                impersonate="chrome110",
                timeout=timeout,
                allow_redirects=True
            )
            
            return (
                response.status_code,
                response.text,
                dict(response.cookies)
            )
        except Exception:
            return None


# =============================================================================
# Stealth Session (HTTP-based)
# =============================================================================

class StealthSession:
    """
    Stealth HTTP session with anti-detection features.
    Uses aiohttp with realistic headers and rate limiting.
    """
    
    def __init__(self,
                 fingerprint: BrowserFingerprint = None,
                 proxy: str = None,
                 rate_limit: bool = True,
                 persist_cookies: bool = True):
        
        self.fingerprint = fingerprint or BrowserFingerprint.generate()
        self.proxy = proxy or (bot_config.proxy_url if bot_config.proxy_enabled else None)
        self.rate_limiter = RateLimiter() if rate_limit else None
        self.persist_cookies = persist_cookies
        
        self.cookie_managers: Dict[str, CookieManager] = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self._closed = False
    
    async def __aenter__(self):
        await self._ensure_session()
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    async def _ensure_session(self) -> None:
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(
                ssl=False,
                limit=10,
                ttl_dns_cache=300
            )
            
            timeout = aiohttp.ClientTimeout(
                total=bot_config.request_timeout,
                connect=10
            )
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
    
    def _get_cookie_manager(self, url: str) -> CookieManager:
        """Get or create cookie manager for domain"""
        domain = urlparse(url).netloc
        if domain not in self.cookie_managers:
            self.cookie_managers[domain] = CookieManager(
                domain, persist=self.persist_cookies
            )
        return self.cookie_managers[domain]
    
    async def get(self,
                  url: str,
                  referer: str = None,
                  headers: Dict[str, str] = None,
                  allow_redirects: bool = True,
                  timeout: int = None,
                  solve_cloudflare: bool = True) -> Optional[str]:
        """
        Make GET request with stealth headers.
        Returns response text or None on failure.
        """
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp not available")
        
        await self._ensure_session()
        
        # Rate limiting
        if self.rate_limiter:
            await self.rate_limiter.wait_async(url)
        
        # Get cookies
        cookie_mgr = self._get_cookie_manager(url)
        
        # Generate headers
        req_headers = HeadersGenerator.generate(
            url,
            fingerprint=self.fingerprint,
            referer=referer
        )
        
        if headers:
            req_headers.update(headers)
        
        # Make request
        try:
            async with self.session.get(
                url,
                headers=req_headers,
                cookies=cookie_mgr.get_dict(),
                allow_redirects=allow_redirects,
                timeout=aiohttp.ClientTimeout(total=timeout or bot_config.request_timeout),
                proxy=self.proxy
            ) as response:
                
                # Update cookies
                if response.cookies:
                    cookie_mgr.update_from_response(
                        {c.key: c.value for c in response.cookies.values()}
                    )
                
                text = await response.text()
                
                # Check for Cloudflare
                if solve_cloudflare and CloudflareHandler.is_challenge(text, response.status):
                    return await self._handle_cloudflare(url, referer)
                
                return text
        
        except Exception as e:
            if bot_config.solve_cloudflare:
                # Try Cloudflare bypass
                return await self._handle_cloudflare(url, referer)
            return None
    
    async def post(self,
                   url: str,
                   data: Any = None,
                   json_data: Dict = None,
                   referer: str = None,
                   headers: Dict[str, str] = None,
                   timeout: int = None) -> Optional[str]:
        """Make POST request"""
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp not available")
        
        await self._ensure_session()
        
        if self.rate_limiter:
            await self.rate_limiter.wait_async(url)
        
        cookie_mgr = self._get_cookie_manager(url)
        
        req_headers = HeadersGenerator.generate_xhr(
            url,
            fingerprint=self.fingerprint,
            referer=referer
        )
        
        if json_data:
            req_headers["Content-Type"] = "application/json"
        
        if headers:
            req_headers.update(headers)
        
        try:
            async with self.session.post(
                url,
                data=data,
                json=json_data,
                headers=req_headers,
                cookies=cookie_mgr.get_dict(),
                timeout=aiohttp.ClientTimeout(total=timeout or bot_config.request_timeout),
                proxy=self.proxy
            ) as response:
                
                if response.cookies:
                    cookie_mgr.update_from_response(
                        {c.key: c.value for c in response.cookies.values()}
                    )
                
                return await response.text()
        
        except Exception:
            return None
    
    async def get_json(self, url: str, **kwargs) -> Optional[Dict]:
        """Get JSON response"""
        text = await self.get(url, **kwargs)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        return None
    
    async def _handle_cloudflare(self, url: str, referer: str = None) -> Optional[str]:
        """Handle Cloudflare challenge"""
        
        # Try curl_cffi first (faster)
        if HAS_CURL_CFFI:
            result = CloudflareHandler.solve_with_curl_cffi(url)
            if result:
                status, text, cookies = result
                if not CloudflareHandler.is_challenge(text, status):
                    # Update cookies
                    cookie_mgr = self._get_cookie_manager(url)
                    cookie_mgr.update_from_response(cookies)
                    return text
        
        # Try browser
        if HAS_PLAYWRIGHT:
            result = await CloudflareHandler.solve_with_browser(
                url,
                headless=bot_config.headless,
                timeout=bot_config.cloudflare_timeout
            )
            
            if result and result.get('success'):
                # Update cookies
                cookie_mgr = self._get_cookie_manager(url)
                cookie_mgr.update_from_browser(result['cookies'])
                return result['content']
        
        return None
    
    async def download(self,
                       url: str,
                       filepath: str,
                       referer: str = None,
                       chunk_size: int = 1024 * 1024,
                       progress_callback: Callable = None) -> bool:
        """Download file with progress"""
        await self._ensure_session()
        
        cookie_mgr = self._get_cookie_manager(url)
        
        headers = HeadersGenerator.generate(
            url,
            fingerprint=self.fingerprint,
            referer=referer,
            is_navigation=False
        )
        
        try:
            async with self.session.get(
                url,
                headers=headers,
                cookies=cookie_mgr.get_dict(),
                proxy=self.proxy
            ) as response:
                
                if response.status != 200:
                    return False
                
                total = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                
                with open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback:
                            progress_callback(downloaded, total)
                
                return True
        
        except Exception:
            return False
    
    async def close(self) -> None:
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
        self._closed = True


# =============================================================================
# Stealth Browser (Playwright-based)
# =============================================================================

class StealthBrowser:
    """
    Stealth browser automation using Playwright.
    Implements anti-detection techniques.
    """
    
    def __init__(self,
                 headless: bool = None,
                 fingerprint: BrowserFingerprint = None,
                 proxy: str = None,
                 browser_type: str = "chromium"):
        
        if not HAS_PLAYWRIGHT:
            raise ImportError(
                "Playwright not available. Install with: "
                "pip install playwright && playwright install"
            )
        
        self.headless = headless if headless is not None else bot_config.headless
        self.fingerprint = fingerprint or BrowserFingerprint.generate()
        self.proxy = proxy or (bot_config.proxy_url if bot_config.proxy_enabled else None)
        self.browser_type = browser_type
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        
        self.cookie_managers: Dict[str, CookieManager] = {}
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    async def start(self) -> 'StealthBrowser':
        """Start browser"""
        self._playwright = await async_playwright().start()
        
        # Select browser type
        browser_launcher = getattr(self._playwright, self.browser_type)
        
        # Launch options
        launch_options = {
            "headless": self.headless,
            "args": self._get_browser_args()
        }
        
        if self.proxy:
            launch_options["proxy"] = {"server": self.proxy}
        
        self._browser = await browser_launcher.launch(**launch_options)
        
        # Context options
        context_options = self._get_context_options()
        self._context = await self._browser.new_context(**context_options)
        
        # Inject stealth scripts
        await self._inject_stealth()
        
        # Create page
        self._page = await self._context.new_page()
        
        return self
    
    def _get_browser_args(self) -> List[str]:
        """Get browser launch arguments"""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-browser-side-navigation",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            f"--window-size={self.fingerprint.screen_width},{self.fingerprint.screen_height}",
        ]
        
        if self.headless:
            args.append("--headless=new")
        
        return args
    
    def _get_context_options(self) -> Dict[str, Any]:
        """Get browser context options"""
        fp = self.fingerprint
        
        return {
            "viewport": {
                "width": fp.screen_width,
                "height": fp.screen_height
            },
            "user_agent": fp.user_agent,
            "locale": fp.language,
            "timezone_id": fp.timezone,
            "device_scale_factor": fp.pixel_ratio,
            "is_mobile": fp.has_touch,
            "has_touch": fp.has_touch,
            "color_scheme": "light",
            "reduced_motion": "no-preference",
            "forced_colors": "none",
        }
    
    async def _inject_stealth(self) -> None:
        """Inject stealth JavaScript to avoid detection"""
        
        stealth_js = """
        () => {
            // Remove webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true
            });
            
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const plugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' }
                    ];
                    plugins.item = (i) => plugins[i];
                    plugins.namedItem = (name) => plugins.find(p => p.name === name);
                    plugins.refresh = () => {};
                    return plugins;
                },
                configurable: true
            });
            
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
                configurable: true
            });
            
            // Chrome object
            if (!window.chrome) {
                window.chrome = {};
            }
            window.chrome.runtime = {
                PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
                PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
                RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
                OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
                OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
            };
            
            // Permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // WebGL vendor/renderer
            const getParameterProto = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Google Inc. (NVIDIA)';
                }
                if (parameter === 37446) {
                    return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return getParameterProto.call(this, parameter);
            };
            
            // WebGL2
            if (typeof WebGL2RenderingContext !== 'undefined') {
                const getParameter2Proto = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) {
                        return 'Google Inc. (NVIDIA)';
                    }
                    if (parameter === 37446) {
                        return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                    }
                    return getParameter2Proto.call(this, parameter);
                };
            }
            
            // Hardware concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8,
                configurable: true
            });
            
            // Device memory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8,
                configurable: true
            });
            
            // Connection
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                }),
                configurable: true
            });
            
            // Console.debug (detection method)
            const originalDebug = console.debug;
            console.debug = function(...args) {
                if (args.length && typeof args[0] === 'string' && args[0].includes('puppeteer')) {
                    return;
                }
                return originalDebug.apply(console, args);
            };
            
            // Iframe contentWindow
            const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
            Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
                get: function() {
                    const window = originalContentWindow.get.call(this);
                    if (window) {
                        // Apply stealth to iframe
                        try {
                            Object.defineProperty(window.navigator, 'webdriver', {
                                get: () => undefined
                            });
                        } catch (e) {}
                    }
                    return window;
                }
            });
        }
        """
        
        await self._context.add_init_script(stealth_js)
    
    async def goto(self, 
                   url: str,
                   wait_until: str = "domcontentloaded",
                   timeout: int = None) -> bool:
        """Navigate to URL"""
        try:
            await self._page.goto(
                url,
                wait_until=wait_until,
                timeout=(timeout or bot_config.page_load_timeout) * 1000
            )
            return True
        except PlaywrightTimeout:
            return False
        except Exception:
            return False
    
    async def content(self) -> str:
        """Get page HTML content"""
        return await self._page.content()
    
    async def wait_for_selector(self, 
                                 selector: str,
                                 timeout: int = None,
                                 state: str = "visible") -> bool:
        """Wait for element"""
        try:
            await self._page.wait_for_selector(
                selector,
                timeout=(timeout or bot_config.element_timeout) * 1000,
                state=state
            )
            return True
        except PlaywrightTimeout:
            return False
    
    async def wait_for_load(self, state: str = "networkidle") -> bool:
        """Wait for page to finish loading"""
        try:
            await self._page.wait_for_load_state(state)
            return True
        except Exception:
            return False
    
    async def click(self, selector: str, timeout: int = None) -> bool:
        """Click element"""
        try:
            await self._page.click(
                selector,
                timeout=(timeout or bot_config.element_timeout) * 1000
            )
            return True
        except Exception:
            return False
    
    async def type(self, 
                   selector: str, 
                   text: str,
                   delay: int = 50) -> bool:
        """Type text with human-like delay"""
        try:
            await self._page.type(selector, text, delay=delay)
            return True
        except Exception:
            return False
    
    async def fill(self, selector: str, text: str) -> bool:
        """Fill input field"""
        try:
            await self._page.fill(selector, text)
            return True
        except Exception:
            return False
    
    async def evaluate(self, script: str) -> Any:
        """Execute JavaScript"""
        return await self._page.evaluate(script)
    
    async def scroll_down(self, pixels: int = 500) -> None:
        """Scroll down"""
        await self._page.evaluate(f"window.scrollBy(0, {pixels})")
        await asyncio.sleep(random.uniform(0.2, 0.5))
    
    async def scroll_to_bottom(self) -> None:
        """Scroll to page bottom"""
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(random.uniform(0.3, 0.7))
    
    async def scroll_to_element(self, selector: str) -> bool:
        """Scroll element into view"""
        try:
            await self._page.evaluate(f"""
                document.querySelector('{selector}').scrollIntoView({{
                    behavior: 'smooth',
                    block: 'center'
                }})
            """)
            await asyncio.sleep(random.uniform(0.3, 0.5))
            return True
        except Exception:
            return False
    
    async def human_scroll(self, scrolls: int = 3) -> None:
        """Scroll like a human"""
        for _ in range(scrolls):
            await self.scroll_down(random.randint(200, 500))
            await self.random_mouse_move()
            await asyncio.sleep(random.uniform(0.5, 1.5))
    
    async def random_mouse_move(self) -> None:
        """Move mouse randomly"""
        x = random.randint(100, self.fingerprint.screen_width - 100)
        y = random.randint(100, self.fingerprint.screen_height - 100)
        await self._page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
    
    async def random_delay(self, min_sec: float = 0.5, max_sec: float = 2.0) -> None:
        """Random delay"""
        await asyncio.sleep(random.uniform(min_sec, max_sec))
    
    async def get_cookies(self) -> List[Dict]:
        """Get all cookies"""
        return await self._context.cookies()
    
    async def set_cookies(self, cookies: List[Dict]) -> None:
        """Set cookies"""
        await self._context.add_cookies(cookies)
    
    async def clear_cookies(self) -> None:
        """Clear all cookies"""
        await self._context.clear_cookies()
    
    async def screenshot(self, 
                         path: str = None,
                         full_page: bool = False) -> bytes:
        """Take screenshot"""
        options = {"full_page": full_page}
        if path:
            options["path"] = path
        return await self._page.screenshot(**options)
    
    async def pdf(self, path: str) -> bytes:
        """Generate PDF (only in headless)"""
        return await self._page.pdf(path=path)
    
    async def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Get element attribute"""
        try:
            element = await self._page.query_selector(selector)
            if element:
                return await element.get_attribute(attribute)
        except Exception:
            pass
        return None
    
    async def get_text(self, selector: str) -> Optional[str]:
        """Get element text content"""
        try:
            element = await self._page.query_selector(selector)
            if element:
                return await element.text_content()
        except Exception:
            pass
        return None
    
    async def get_all_text(self, selector: str) -> List[str]:
        """Get text from all matching elements"""
        try:
            elements = await self._page.query_selector_all(selector)
            return [await el.text_content() for el in elements]
        except Exception:
            return []
    
    async def intercept_requests(self, 
                                  handler: Callable) -> None:
        """Intercept network requests"""
        await self._page.route("**/*", handler)
    
    async def block_resources(self, 
                               resource_types: List[str] = None) -> None:
        """Block specific resource types"""
        if resource_types is None:
            resource_types = ["image", "stylesheet", "font", "media"]
        
        async def block_handler(route):
            if route.request.resource_type in resource_types:
                await route.abort()
            else:
                await route.continue_()
        
        await self._page.route("**/*", block_handler)
    
    async def wait_for_response(self, 
                                 url_pattern: str,
                                 timeout: int = 30) -> Optional[Dict]:
        """Wait for specific response"""
        try:
            response = await self._page.wait_for_response(
                lambda r: url_pattern in r.url,
                timeout=timeout * 1000
            )
            return {
                'url': response.url,
                'status': response.status,
                'headers': response.headers,
                'body': await response.text()
            }
        except Exception:
            return None
    
    async def solve_cloudflare(self, timeout: int = 30) -> bool:
        """Wait for Cloudflare challenge to complete"""
        start = time.time()
        
        while time.time() - start < timeout:
            content = await self.content()
            
            if not CloudflareHandler.is_challenge(content):
                return True
            
            await asyncio.sleep(1)
        
        return False
    
    async def close(self) -> None:
        """Close browser"""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass


# =============================================================================
# Selenium Browser (Alternative)
# =============================================================================

class SeleniumBrowser:
    """
    Stealth browser using Selenium with undetected-chromedriver.
    Fallback when Playwright is not available.
    """
    
    def __init__(self,
                 headless: bool = None,
                 fingerprint: BrowserFingerprint = None,
                 proxy: str = None):
        
        if not HAS_SELENIUM:
            raise ImportError("Selenium not available")
        
        self.headless = headless if headless is not None else bot_config.headless
        self.fingerprint = fingerprint or BrowserFingerprint.generate()
        self.proxy = proxy or (bot_config.proxy_url if bot_config.proxy_enabled else None)
        
        self.driver = None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def start(self) -> 'SeleniumBrowser':
        """Start browser"""
        
        if HAS_UNDETECTED_CHROME:
            options = uc.ChromeOptions()
            
            if self.headless:
                options.add_argument("--headless=new")
            
            options.add_argument(f"--window-size={self.fingerprint.screen_width},{self.fingerprint.screen_height}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            
            if self.proxy:
                options.add_argument(f"--proxy-server={self.proxy}")
            
            self.driver = uc.Chrome(options=options)
        
        else:
            options = ChromeOptions()
            
            if self.headless:
                options.add_argument("--headless=new")
            
            options.add_argument(f"--window-size={self.fingerprint.screen_width},{self.fingerprint.screen_height}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-infobars")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            
            if self.proxy:
                options.add_argument(f"--proxy-server={self.proxy}")
            
            self.driver = webdriver.Chrome(options=options)
            
            # Stealth script
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """
            })
        
        return self
    
    def goto(self, url: str, timeout: int = None) -> bool:
        """Navigate to URL"""
        try:
            self.driver.set_page_load_timeout(
                timeout or bot_config.page_load_timeout
            )
            self.driver.get(url)
            return True
        except TimeoutException:
            return False
        except Exception:
            return False
    
    def content(self) -> str:
        """Get page source"""
        return self.driver.page_source
    
    def wait_for_element(self, 
                         selector: str, 
                         timeout: int = None,
                         by: str = "css") -> bool:
        """Wait for element"""
        try:
            by_type = By.CSS_SELECTOR if by == "css" else By.XPATH
            WebDriverWait(
                self.driver, 
                timeout or bot_config.element_timeout
            ).until(
                EC.presence_of_element_located((by_type, selector))
            )
            return True
        except TimeoutException:
            return False
    
    def click(self, selector: str, by: str = "css") -> bool:
        """Click element"""
        try:
            by_type = By.CSS_SELECTOR if by == "css" else By.XPATH
            element = self.driver.find_element(by_type, selector)
            element.click()
            return True
        except Exception:
            return False
    
    def type(self, selector: str, text: str, by: str = "css") -> bool:
        """Type text"""
        try:
            by_type = By.CSS_SELECTOR if by == "css" else By.XPATH
            element = self.driver.find_element(by_type, selector)
            element.send_keys(text)
            return True
        except Exception:
            return False
    
    def execute_script(self, script: str) -> Any:
        """Execute JavaScript"""
        return self.driver.execute_script(script)
    
    def scroll_down(self, pixels: int = 500) -> None:
        """Scroll down"""
        self.driver.execute_script(f"window.scrollBy(0, {pixels})")
        time.sleep(random.uniform(0.2, 0.5))
    
    def get_cookies(self) -> List[Dict]:
        """Get cookies"""
        return self.driver.get_cookies()
    
    def set_cookies(self, cookies: List[Dict]) -> None:
        """Set cookies"""
        for cookie in cookies:
            try:
                self.driver.add_cookie(cookie)
            except Exception:
                pass
    
    def screenshot(self, path: str) -> bool:
        """Take screenshot"""
        try:
            self.driver.save_screenshot(path)
            return True
        except Exception:
            return False
    
    def close(self) -> None:
        """Close browser"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass


# =============================================================================
# High-Level Functions
# =============================================================================

async def fetch_with_stealth(
    url: str,
    referer: str = None,
    use_browser: bool = False,
    solve_cloudflare: bool = True,
    headless: bool = True
) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    High-level function to fetch page with anti-detection.
    
    Args:
        url: Target URL
        referer: Referer URL
        use_browser: Force browser usage
        solve_cloudflare: Attempt Cloudflare bypass
        headless: Run browser headlessly
    
    Returns:
        Tuple of (html_content, cookies_dict) or None
    """
    
    # Try simple session first
    async with StealthSession() as session:
        html = await session.get(
            url, 
            referer=referer,
            solve_cloudflare=solve_cloudflare
        )
        
        if html and not CloudflareHandler.is_challenge(html):
            cookies = session._get_cookie_manager(url).get_dict()
            return html, cookies
    
    # Fallback to browser
    if use_browser or (solve_cloudflare and HAS_PLAYWRIGHT):
        try:
            async with StealthBrowser(headless=headless) as browser:
                if await browser.goto(url):
                    # Wait for Cloudflare if needed
                    if solve_cloudflare:
                        await browser.solve_cloudflare()
                    
                    html = await browser.content()
                    cookies_list = await browser.get_cookies()
                    cookies = {c['name']: c['value'] for c in cookies_list}
                    
                    return html, cookies
        except Exception:
            pass
    
    return None


def fetch_with_stealth_sync(url: str, **kwargs) -> Optional[Tuple[str, Dict[str, str]]]:
    """Synchronous wrapper for fetch_with_stealth"""
    return asyncio.run(fetch_with_stealth(url, **kwargs))


async def solve_cloudflare(url: str, headless: bool = False) -> Optional[Dict]:
    """
    Solve Cloudflare challenge and return cookies.
    
    Returns:
        Dict with 'cookies', 'user_agent', 'content' if successful
    """
    return await CloudflareHandler.solve_with_browser(url, headless=headless)


# =============================================================================
# Module Information
# =============================================================================

def get_available_features() -> Dict[str, bool]:
    """Get available features based on installed packages"""
    return {
        "aiohttp": HAS_AIOHTTP,
        "requests": HAS_REQUESTS,
        "playwright": HAS_PLAYWRIGHT,
        "selenium": HAS_SELENIUM,
        "undetected_chromedriver": HAS_UNDETECTED_CHROME,
        "curl_cffi": HAS_CURL_CFFI,
        "stealth_session": HAS_AIOHTTP,
        "stealth_browser": HAS_PLAYWRIGHT or HAS_SELENIUM,
        "cloudflare_bypass": HAS_PLAYWRIGHT or HAS_CURL_CFFI,
    }


def print_status() -> None:
    """Print module status"""
    features = get_available_features()
    
    print("\n" + "=" * 60)
    print("BOT.PY - Anti-Detection Module Status")
    print("=" * 60)
    print("\nCore HTTP:")
    print(f"  [{'OK' if features['aiohttp'] else 'X'}] aiohttp")
    print(f"  [{'OK' if features['requests'] else 'X'}] requests")
    
    print("\nBrowser Automation:")
    print(f"  [{'OK' if features['playwright'] else 'X'}] Playwright")
    print(f"  [{'OK' if features['selenium'] else 'X'}] Selenium")
    print(f"  [{'OK' if features['undetected_chromedriver'] else 'X'}] undetected-chromedriver")
    
    print("\nCloudflare Bypass:")
    print(f"  [{'OK' if features['curl_cffi'] else 'X'}] curl_cffi")
    
    print("\nCapabilities:")
    print(f"  [{'OK' if features['stealth_session'] else 'X'}] Stealth HTTP Session")
    print(f"  [{'OK' if features['stealth_browser'] else 'X'}] Stealth Browser")
    print(f"  [{'OK' if features['cloudflare_bypass'] else 'X'}] Cloudflare Bypass")
    
    print("\nRecommended installations:")
    if not features['playwright']:
        print("  pip install playwright && playwright install chromium")
    if not features['curl_cffi']:
        print("  pip install curl_cffi")
    
    print("=" * 60 + "\n")


# =============================================================================
# Module Initialization
# =============================================================================

# Export public API
__all__ = [
    # Config
    'BotConfig',
    'bot_config',
    
    # Core classes
    'BrowserFingerprint',
    'UserAgentDatabase',
    'HeadersGenerator',
    'CookieManager',
    'RateLimiter',
    'CloudflareHandler',
    
    # Sessions/Browsers
    'StealthSession',
    'StealthBrowser',
    'SeleniumBrowser',
    
    # High-level functions
    'fetch_with_stealth',
    'fetch_with_stealth_sync',
    'solve_cloudflare',
    
    # Utilities
    'get_available_features',
    'print_status',
    
    # Feature flags
    'HAS_PLAYWRIGHT',
    'HAS_SELENIUM',
    'HAS_AIOHTTP',
    'HAS_CURL_CFFI',
]


# =============================================================================
# Main (for testing)
# =============================================================================

if __name__ == "__main__":
    print_status()
    
    # Test example
    async def test():
        print("\n--- Testing StealthSession ---")
        async with StealthSession() as session:
            html = await session.get("https://httpbin.org/headers")
            if html:
                print(f"Success! Response length: {len(html)}")
            else:
                print("Failed!")
        
        if HAS_PLAYWRIGHT:
            print("\n--- Testing StealthBrowser ---")
            async with StealthBrowser(headless=True) as browser:
                if await browser.goto("https://bot.sannysoft.com/"):
                    print("Navigated successfully!")
                    await browser.screenshot("bot_test.png")
                    print("Screenshot saved: bot_test.png")
    
    asyncio.run(test())