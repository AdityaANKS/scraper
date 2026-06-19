"""
================================================================================
SCRAPER.PY - Professional Web Scraper & Media Downloader
================================================================================
Version: 2.0
Last Updated: 2025

Main orchestrator that coordinates all scraping and downloading operations.
Integrates with all other modules for a complete solution.

FEATURES:
---------
  • Multi-platform video/audio download (YouTube, Instagram, TikTok, X, etc.)
  • Quality selection up to 8K@60fps
  • YouTube playlist support with progress tracking
  • Proper file naming with actual titles
  • Thumbnail embedding in video/audio files
  • Metadata embedding (title, artist, album, etc.)
  • Database storage for tracking downloads
  • Optional anti-detection via bot.py
  • Resume interrupted downloads
  • Batch processing

SUPPORTED PLATFORMS:
--------------------
  YouTube, Instagram, TikTok, X (Twitter), Facebook, Reddit,
  Vimeo, Twitch, Dailymotion, SoundCloud, Bilibili,
  Anime sites (HiAnime, Gogoanime, 9anime, etc.)

SAVE PATHS:
-----------
  Videos: C:\\Users\\adity\\scraper\\videos
  Audio:  C:\\Users\\adity\\scraper\\audio
  Images: C:\\Users\\adity\\scraper\\images
  Text:   C:\\Users\\adity\\scraper\\text

USAGE:
------
  # As module
  from scraper import Scraper
  
  async with Scraper() as scraper:
      result = await scraper.download_video(url)
      result = await scraper.download_audio(url)
      result = await scraper.download_playlist(url)

  # As CLI
  python scraper.py
  python scraper.py URL
  python scraper.py URL --audio

================================================================================
"""

import os
import sys
import json
import csv
import asyncio
import signal
import hashlib
import tempfile
import shutil
import glob
import re
from datetime import datetime
from typing import (
    Dict, List, Optional, Any, Tuple, 
    Callable, Union, Set
)
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urljoin
import traceback
import threading
from contextlib import contextmanager

# =============================================================================
# Import Project Modules
# =============================================================================

from config import (
    config, Config, Platform, MediaType, ContentType,
    Quality, AudioQuality
)

from models import (
    MediaMetadata, DownloadResult, DownloadProgress,
    PlaylistInfo, ScrapedPage, Author, Thumbnail,
    VideoFormat, AudioFormat, ExtractedText, ExtractedLink,
    ExtractedImage, PageMetadata, ScrapeJob, PlaylistDownloadResult
)

from utils import (
    safe_print, log_info, log_warn, log_error, log_success, log_debug,
    format_size, format_duration, sanitize_filename, normalize_url,
    detect_platform, is_streaming_site, get_domain, get_unique_filepath,
    run_command, run_command_async, get_file_size, cleanup_temp_files,
    HAS_FFMPEG, HAS_FFPROBE, HAS_YTDLP, FFMPEG_VERSION, YTDLP_VERSION
)

from extractors import (
    extract_metadata, extract_playlist, extract_page,
    extract_streaming_sources, smart_extract,
    HTMLExtractor, MediaExtractor, StreamingExtractor
)

# Optional imports
try:
    from database import Database
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False
    Database = None

try:
    from bot import (
        StealthSession, StealthBrowser, fetch_with_stealth,
        CloudflareHandler, bot_config
    )
    HAS_BOT = True
except ImportError:
    HAS_BOT = False
    StealthSession = None
    StealthBrowser = None

try:
    import aiohttp
    import aiofiles
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    aiohttp = None
    aiofiles = None

try:
    from image import ImageDownloader, ImageResult, scrape_images, download_image as dl_image
    HAS_IMAGE_MODULE = True
except ImportError:
    HAS_IMAGE_MODULE = False

# =============================================================================
# Scrapling Imports (consolidated — single source of truth)
# =============================================================================
# All other modules (namu_ai, cli) should import Scrapling symbols from here.

HAS_SCRAPLING = False
HAS_SCRAPLING_FETCHERS = False
HAS_SCRAPLING_SPIDERS = False

try:
    from scrapling.parser import Selector
    HAS_SCRAPLING = True
except ImportError:
    Selector = None

try:
    from scrapling.fetchers import (
        Fetcher, AsyncFetcher,
        StealthyFetcher, DynamicFetcher,
        FetcherSession, StealthySession, DynamicSession,
    )
    HAS_SCRAPLING_FETCHERS = True
except ImportError:
    Fetcher = AsyncFetcher = StealthyFetcher = DynamicFetcher = None
    FetcherSession = StealthySession = DynamicSession = None

try:
    from scrapling.spiders import Spider, Request, Response
    HAS_SCRAPLING_SPIDERS = True
except ImportError:
    Spider = Request = Response = None


# =============================================================================
# Output Directory — uses project default: C:\Users\<user>\scraper\scraped_data
# =============================================================================

SCRAPLED_DATA_DIR = os.path.join(config.paths.base_dir, "scraped_data")
os.makedirs(SCRAPLED_DATA_DIR, exist_ok=True)


# =============================================================================
# Display Helpers
# =============================================================================

def _print_line(char: str = "─", width: int = 70) -> None:
    safe_print(char * width)


def _print_header(title: str, width: int = 70) -> None:
    safe_print("")
    safe_print("═" * width)
    padding = (width - len(title) - 2) // 2
    safe_print("║" + " " * padding + title + " " * (width - padding - len(title) - 2) + "║")
    safe_print("═" * width)


def _print_subheader(title: str, width: int = 70) -> None:
    safe_print("")
    safe_print("─" * width)
    safe_print(f"  {title}")
    safe_print("─" * width)


def _get_input(prompt: str, default: str = None) -> str:
    try:
        if default:
            result = input(f"  {prompt} [{default}]: ").strip()
            return result if result else default
        else:
            return input(f"  {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _confirm(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    response = _get_input(prompt + suffix, "").lower()
    if not response:
        return default
    return response in ('y', 'yes', '1', 'true')


def _save_results(data: Any, filename: str, fmt: str = "json") -> str:
    """Save scraped data to file. Returns the filepath."""
    os.makedirs(SCRAPLED_DATA_DIR, exist_ok=True)
    safe_name = sanitize_filename(filename)
    filepath = os.path.join(SCRAPLED_DATA_DIR, f"{safe_name}.{fmt}")

    # Avoid overwriting
    counter = 1
    base = filepath
    while os.path.exists(filepath):
        name, ext = os.path.splitext(base)
        filepath = f"{name}_{counter}{ext}"
        counter += 1

    if fmt == "json":
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    elif fmt == "jsonl":
        with open(filepath, 'w', encoding='utf-8') as f:
            items = data if isinstance(data, list) else [data]
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    elif fmt == "csv":
        items = data if isinstance(data, list) else [data]
        if items and isinstance(items[0], dict):
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=items[0].keys())
                writer.writeheader()
                writer.writerows(items)
        else:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for item in items:
                    writer.writerow([item] if not isinstance(item, (list, tuple)) else item)
    elif fmt in ("txt", "md"):
        with open(filepath, 'w', encoding='utf-8') as f:
            if isinstance(data, str):
                f.write(data)
            elif isinstance(data, list):
                f.write("\n".join(str(d) for d in data))
            else:
                f.write(str(data))

    return filepath


def _display_response_info(page) -> None:
    """Display basic info about a Scrapling response object."""
    safe_print(f"  Status     : {getattr(page, 'status', 'N/A')}")
    safe_print(f"  Encoding   : {getattr(page, 'encoding', 'N/A')}")
    title_el = page.css('title::text')
    title = title_el.get() if title_el else "N/A"
    safe_print(f"  Page Title : {title[:80] if title else 'N/A'}")


# =============================================================================
# 1. Quick Scrape
# =============================================================================

def handle_quick_scrape() -> None:
    """Fast HTTP fetch and extract text, links, and images from a page."""
    _print_header("QUICK SCRAPE")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed. Run: pip install \"scrapling[fetchers]\"")
        return

    url = _get_input("Enter URL to scrape")
    if not url:
        return

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        # Extract text
        body_text = page.css('body').css('::text').getall() if page.css('body') else []
        text_content = ' '.join(t.strip() for t in body_text if t.strip())
        word_count = len(text_content.split())

        # Extract links
        links = page.css('a::attr(href)').getall()
        abs_links = []
        for link in links:
            if link and not link.startswith(('#', 'javascript:', 'mailto:')):
                abs_links.append(urljoin(url, link))
        unique_links = list(dict.fromkeys(abs_links))  # Deduplicate preserving order

        # Extract images
        images = page.css('img::attr(src)').getall()
        abs_images = [urljoin(url, img) for img in images if img]

        _print_subheader("EXTRACTION RESULTS")
        safe_print(f"  Words      : {word_count}")
        safe_print(f"  Links      : {len(unique_links)}")
        safe_print(f"  Images     : {len(abs_images)}")

        # Preview first items
        if unique_links:
            safe_print("\n  First 5 links:")
            for i, link in enumerate(unique_links[:5], 1):
                safe_print(f"    {i}. {link[:80]}")

        if abs_images:
            safe_print(f"\n  First 5 images:")
            for i, img in enumerate(abs_images[:5], 1):
                safe_print(f"    {i}. {img[:80]}")

        # Ask to save
        if _confirm("\n  Save results?"):
            results = {
                "url": url,
                "title": page.css('title::text').get() or "",
                "word_count": word_count,
                "text_preview": text_content[:500],
                "links": unique_links,
                "images": abs_images,
                "scraped_at": datetime.now().isoformat()
            }
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(results, f"quick_scrape_{domain}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Scrape failed: {e}")


# =============================================================================
# 2. Stealth Scrape
# =============================================================================

def handle_stealth_scrape() -> None:
    """Bypass anti-bot protections using StealthyFetcher."""
    _print_header("STEALTH SCRAPE (Anti-Bot Bypass)")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed. Run: pip install \"scrapling[fetchers]\"")
        return

    url = _get_input("Enter URL to scrape (supports Cloudflare-protected sites)")
    if not url:
        return

    solve_cf = _confirm("  Attempt to solve Cloudflare challenge?", default=True)
    headless = _confirm("  Run headless (no visible browser)?", default=True)

    safe_print("\n  Launching stealth browser...")
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=headless,
            network_idle=True,
            solve_cloudflare=solve_cf
        )
        _display_response_info(page)

        body_text = page.css('body').css('::text').getall() if page.css('body') else []
        text_content = ' '.join(t.strip() for t in body_text if t.strip())
        word_count = len(text_content.split())

        links = page.css('a::attr(href)').getall()
        images = page.css('img::attr(src)').getall()

        _print_subheader("STEALTH RESULTS")
        safe_print(f"  Words      : {word_count}")
        safe_print(f"  Links      : {len(links)}")
        safe_print(f"  Images     : {len(images)}")

        if text_content:
            safe_print(f"\n  Text preview (first 300 chars):")
            safe_print(f"  {text_content[:300]}...")

        if _confirm("\n  Save full results?"):
            results = {
                "url": url,
                "method": "stealth",
                "cloudflare_bypass": solve_cf,
                "title": page.css('title::text').get() or "",
                "word_count": word_count,
                "text": text_content,
                "links": [urljoin(url, l) for l in links if l],
                "images": [urljoin(url, i) for i in images if i],
                "scraped_at": datetime.now().isoformat()
            }
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(results, f"stealth_scrape_{domain}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Stealth scrape failed: {e}")


# =============================================================================
# 3. Dynamic Scrape (Full Browser Automation)
# =============================================================================

def handle_dynamic_scrape() -> None:
    """Full Playwright browser automation for JS-heavy sites."""
    _print_header("DYNAMIC SCRAPE (Browser Automation)")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed. Run: pip install \"scrapling[fetchers]\"")
        return

    url = _get_input("Enter URL (JS-heavy / SPA sites)")
    if not url:
        return

    headless = _confirm("  Run headless?", default=True)
    disable_res = _confirm("  Disable images/CSS for speed?", default=True)

    safe_print("\n  Launching browser...")
    try:
        page = DynamicFetcher.fetch(
            url,
            headless=headless,
            network_idle=True,
            disable_resources=disable_res
        )
        _display_response_info(page)

        body_text = page.css('body').css('::text').getall() if page.css('body') else []
        text_content = ' '.join(t.strip() for t in body_text if t.strip())

        _print_subheader("DYNAMIC RESULTS")
        safe_print(f"  Words   : {len(text_content.split())}")
        safe_print(f"  Links   : {len(page.css('a::attr(href)').getall())}")
        safe_print(f"  Scripts : {len(page.css('script').getall())}")

        if text_content:
            safe_print(f"\n  Text preview:")
            safe_print(f"  {text_content[:400]}...")

        if _confirm("\n  Save results?"):
            results = {
                "url": url,
                "method": "dynamic",
                "title": page.css('title::text').get() or "",
                "text": text_content,
                "links": [urljoin(url, l) for l in page.css('a::attr(href)').getall() if l],
                "scraped_at": datetime.now().isoformat()
            }
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(results, f"dynamic_scrape_{domain}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Dynamic scrape failed: {e}")


# =============================================================================
# 4. CSS / XPath Extractor
# =============================================================================

def handle_selector_extract() -> None:
    """Extract specific elements using CSS or XPath selectors."""
    _print_header("CSS / XPATH EXTRACTOR")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    safe_print("\n  Selector type:")
    safe_print("    1. CSS selector   (e.g. .quote .text::text)")
    safe_print("    2. XPath selector (e.g. //div[@class='quote']//text())")
    sel_type = _get_input("  Choose", "1")

    selector = _get_input("  Enter selector expression")
    if not selector:
        return

    # Choose fetcher
    safe_print("\n  Fetcher mode:")
    safe_print("    1. Quick (HTTP only)")
    safe_print("    2. Stealth (anti-bot)")
    safe_print("    3. Dynamic (full browser)")
    mode = _get_input("  Choose", "1")

    safe_print("\n  Fetching page...")
    try:
        if mode == "2":
            page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        elif mode == "3":
            page = DynamicFetcher.fetch(url, headless=True, network_idle=True)
        else:
            page = Fetcher.get(url, stealthy_headers=True)

        _display_response_info(page)

        # Execute selector
        if sel_type == "2":
            results = page.xpath(selector).getall()
        else:
            results = page.css(selector).getall()

        _print_subheader(f"MATCHED ELEMENTS ({len(results)})")

        if not results:
            log_warn("No elements matched the selector.")
            return

        # Show results
        for i, item in enumerate(results[:20], 1):
            text = str(item).strip()
            if len(text) > 100:
                text = text[:100] + "..."
            safe_print(f"  {i:3}. {text}")

        if len(results) > 20:
            safe_print(f"\n  ... and {len(results) - 20} more results")

        if _confirm(f"\n  Save all {len(results)} results?"):
            data = {"url": url, "selector": selector, "type": "css" if sel_type != "2" else "xpath",
                    "count": len(results), "results": results, "scraped_at": datetime.now().isoformat()}
            fp = _save_results(data, f"selector_extract_{datetime.now().strftime('%H%M%S')}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Extraction failed: {e}")


# =============================================================================
# 5. Find by Text
# =============================================================================

def handle_find_by_text() -> None:
    """Find elements by their text content."""
    _print_header("FIND BY TEXT")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    search_text = _get_input("  Text to search for")
    if not search_text:
        return

    tag_filter = _get_input("  Filter by tag (e.g. div, span, a) or leave empty", "")

    safe_print("\n  Fetching and searching...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        kwargs = {}
        if tag_filter:
            kwargs['tag'] = tag_filter

        results = page.find_by_text(search_text, **kwargs)

        _print_subheader(f"FOUND ELEMENTS ({len(results) if results else 0})")

        if not results:
            log_warn(f"No elements found containing '{search_text}'")
            return

        for i, el in enumerate(results[:15], 1):
            tag = getattr(el, 'tag', 'unknown')
            text = el.text[:80] if hasattr(el, 'text') and el.text else str(el)[:80]
            safe_print(f"  {i:3}. <{tag}> {text}")

        if len(results) > 15:
            safe_print(f"\n  ... and {len(results) - 15} more")

    except Exception as e:
        log_error(f"Find by text failed: {e}")


# =============================================================================
# 6. Spider Crawl (Multi-page)
# =============================================================================

def handle_spider_crawl() -> None:
    """Run a Scrapling Spider for multi-page crawling."""
    _print_header("SPIDER CRAWL (Multi-Page)")

    if not HAS_SCRAPLING_SPIDERS:
        log_error("Scrapling spiders not available. Run: pip install \"scrapling[all]\"")
        return

    url = _get_input("Enter start URL")
    if not url:
        return

    css_selector = _get_input("  CSS selector for data extraction (e.g. .quote)")
    if not css_selector:
        css_selector = "*"

    follow_selector = _get_input("  CSS selector for next-page links (e.g. .next a) or empty to skip", "")
    max_concurrent = _get_input("  Max concurrent requests", "5")
    spider_name = _get_input("  Spider name", "cli_spider")

    try:
        concurrent = int(max_concurrent)
    except ValueError:
        concurrent = 5

    safe_print(f"\n  Starting spider '{spider_name}' on {url}...")
    safe_print(f"  Concurrency: {concurrent} | Selector: {css_selector}")
    safe_print("  Press Ctrl+C to stop.\n")

    try:
        # Dynamically create a spider class
        _follow = follow_selector
        _css = css_selector

        class CLISpider(Spider):
            name = spider_name
            start_urls = [url]
            concurrent_requests = concurrent

            async def parse(self, response: Response):
                for element in response.css(_css):
                    # Try to extract structured data
                    item = {}
                    # Get direct text
                    text = element.css('::text').getall()
                    item['text'] = ' '.join(t.strip() for t in text if t.strip())
                    # Get any links
                    links = element.css('a::attr(href)').getall()
                    if links:
                        item['links'] = links
                    # Get any images
                    imgs = element.css('img::attr(src)').getall()
                    if imgs:
                        item['images'] = imgs

                    if item.get('text') or item.get('links'):
                        yield item

                # Follow next page links
                if _follow:
                    next_links = response.css(_follow)
                    if next_links:
                        try:
                            href = next_links[0].attrib.get('href', '')
                            if href:
                                yield response.follow(href)
                        except Exception:
                            pass

        result = CLISpider(crawldir=os.path.join(SCRAPLED_DATA_DIR, f"crawl_{spider_name}")).start()

        _print_subheader("CRAWL COMPLETE")
        item_count = len(result.items) if result and hasattr(result, 'items') else 0
        safe_print(f"  Items scraped: {item_count}")

        if item_count > 0:
            safe_print("\n  First 5 items:")
            items_list = list(result.items)[:5]
            for i, item in enumerate(items_list, 1):
                preview = str(item)[:100]
                safe_print(f"  {i}. {preview}")

            if _confirm(f"\n  Save all {item_count} items?"):
                safe_print("\n  Export format:")
                safe_print("    1. JSON")
                safe_print("    2. JSONL")
                safe_print("    3. CSV")
                fmt_choice = _get_input("  Choose", "1")

                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                if fmt_choice == "2":
                    fp = os.path.join(SCRAPLED_DATA_DIR, f"spider_{spider_name}_{ts}.jsonl")
                    result.items.to_jsonl(fp)
                elif fmt_choice == "3":
                    fp = _save_results(list(result.items), f"spider_{spider_name}_{ts}", "csv")
                else:
                    fp = os.path.join(SCRAPLED_DATA_DIR, f"spider_{spider_name}_{ts}.json")
                    result.items.to_json(fp)
                log_success(f"Saved to: {fp}")

    except KeyboardInterrupt:
        safe_print("\n  Spider stopped by user.")
    except Exception as e:
        log_error(f"Spider crawl failed: {e}")


# =============================================================================
# 7. Session Scrape
# =============================================================================

def handle_session_scrape() -> None:
    """Persistent session with cookie/state management across requests."""
    _print_header("SESSION SCRAPE")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    safe_print("  Session type:")
    safe_print("    1. HTTP Session (FetcherSession)")
    safe_print("    2. Stealth Session (browser, anti-bot)")
    safe_print("    3. Dynamic Session (full browser)")
    session_type = _get_input("  Choose", "1")

    impersonate = _get_input("  Impersonate browser (chrome/firefox/edge) or empty", "chrome")

    safe_print("\n  Session started. Enter URLs to scrape (empty to quit).\n")

    results = []
    request_count = 0

    try:
        if session_type == "2":
            session_ctx = StealthySession(headless=True)
        elif session_type == "3":
            session_ctx = DynamicSession(headless=True, network_idle=True)
        else:
            session_ctx = FetcherSession(impersonate=impersonate if impersonate else 'chrome')

        with session_ctx as session:
            while True:
                url = _get_input(f"  [{request_count + 1}] URL (empty to finish)")
                if not url:
                    break

                try:
                    if session_type in ("2", "3"):
                        page = session.fetch(url)
                    else:
                        page = session.get(url, stealthy_headers=True)

                    request_count += 1
                    title = page.css('title::text').get() or "N/A"
                    text_els = page.css('body').css('::text').getall() if page.css('body') else []
                    text = ' '.join(t.strip() for t in text_els if t.strip())
                    word_count = len(text.split())
                    link_count = len(page.css('a::attr(href)').getall())

                    safe_print(f"    Status: {getattr(page, 'status', 'OK')} | "
                               f"Title: {title[:40]} | Words: {word_count} | Links: {link_count}")

                    results.append({
                        "url": url,
                        "title": title,
                        "word_count": word_count,
                        "link_count": link_count,
                        "text_preview": text[:200],
                        "cookies": getattr(page, 'cookies', {}),
                    })

                except Exception as e:
                    safe_print(f"    Error: {e}")

        _print_subheader("SESSION SUMMARY")
        safe_print(f"  Pages fetched : {request_count}")
        safe_print(f"  Session type  : {['HTTP', 'Stealth', 'Dynamic'][int(session_type) - 1]}")

        if results and _confirm("\n  Save session results?"):
            fp = _save_results(results, f"session_{datetime.now().strftime('%H%M%S')}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Session error: {e}")


# =============================================================================
# 8. Page to Text / Markdown
# =============================================================================

def handle_page_to_text() -> None:
    """Convert a webpage to clean text or markdown."""
    _print_header("PAGE TO TEXT / MARKDOWN")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    safe_print("\n  Output format:")
    safe_print("    1. Plain text (.txt)")
    safe_print("    2. Markdown (.md)")
    fmt = _get_input("  Choose", "1")

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        # Extract main content (skip nav, footer, script, style)
        # Remove script and style content
        body = page.css('body')
        if not body:
            log_error("No body content found.")
            return

        # Get all text nodes
        all_text = body.css('::text').getall()
        clean_text = '\n'.join(t.strip() for t in all_text if t.strip())

        if fmt == "2":
            # Build simple markdown
            title = page.css('title::text').get() or "Untitled"
            md_content = f"# {title}\n\n"
            md_content += f"**Source:** {url}\n\n"
            md_content += f"**Scraped:** {datetime.now().isoformat()}\n\n"
            md_content += "---\n\n"

            # Try to extract headings
            for h_level in range(1, 7):
                for h in page.css(f'h{h_level}'):
                    h_text = h.css('::text').get() or ""
                    if h_text.strip():
                        md_content += f"{'#' * h_level} {h_text.strip()}\n\n"

            # Paragraphs
            for p in page.css('p'):
                p_text = ' '.join(t.strip() for t in p.css('::text').getall() if t.strip())
                if p_text:
                    md_content += f"{p_text}\n\n"

            # Lists
            for li in page.css('li'):
                li_text = ' '.join(t.strip() for t in li.css('::text').getall() if t.strip())
                if li_text:
                    md_content += f"- {li_text}\n"

            content = md_content
            ext = "md"
        else:
            content = clean_text
            ext = "txt"

        # Preview
        safe_print(f"\n  Content length: {len(content)} chars")
        safe_print(f"\n  Preview (first 500 chars):")
        safe_print(f"  {'─' * 60}")
        for line in content[:500].split('\n'):
            safe_print(f"  {line}")
        safe_print(f"  {'─' * 60}")

        if _confirm("\n  Save to file?"):
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(content, f"page_{domain}", ext)
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Conversion failed: {e}")


# =============================================================================
# 9. Extract All Links
# =============================================================================

def handle_extract_links() -> None:
    """Extract, categorize, and deduplicate all links from a page."""
    _print_header("EXTRACT ALL LINKS")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        raw_links = page.css('a')
        parsed_base = urlparse(url)

        internal_links = []
        external_links = []
        other_links = []

        for a_el in raw_links:
            href = a_el.attrib.get('href', '') if hasattr(a_el, 'attrib') else ''
            if not href:
                href_list = a_el.css('::attr(href)').getall()
                href = href_list[0] if href_list else ''
            if not href or href.startswith(('#', 'javascript:')):
                continue

            text_parts = a_el.css('::text').getall()
            link_text = ' '.join(t.strip() for t in text_parts if t.strip()) if text_parts else ""
            abs_url = urljoin(url, href)
            parsed = urlparse(abs_url)

            entry = {"url": abs_url, "text": link_text[:100]}

            if parsed.netloc == parsed_base.netloc:
                internal_links.append(entry)
            elif parsed.scheme in ('http', 'https'):
                external_links.append(entry)
            else:
                other_links.append(entry)

        # Deduplicate
        seen_urls = set()
        for link_list in [internal_links, external_links, other_links]:
            deduped = []
            for item in link_list:
                if item['url'] not in seen_urls:
                    seen_urls.add(item['url'])
                    deduped.append(item)
            link_list[:] = deduped

        _print_subheader("LINK SUMMARY")
        safe_print(f"  Internal links : {len(internal_links)}")
        safe_print(f"  External links : {len(external_links)}")
        safe_print(f"  Other links    : {len(other_links)}")
        safe_print(f"  Total unique   : {len(internal_links) + len(external_links) + len(other_links)}")

        if internal_links:
            safe_print("\n  Internal links (first 10):")
            for i, l in enumerate(internal_links[:10], 1):
                safe_print(f"    {i:3}. {l['url'][:70]}")

        if external_links:
            safe_print("\n  External links (first 10):")
            for i, l in enumerate(external_links[:10], 1):
                safe_print(f"    {i:3}. {l['url'][:70]}")

        if _confirm("\n  Save all links?"):
            data = {
                "url": url,
                "internal": internal_links,
                "external": external_links,
                "other": other_links,
                "total": len(internal_links) + len(external_links) + len(other_links),
                "scraped_at": datetime.now().isoformat()
            }
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(data, f"links_{domain}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Link extraction failed: {e}")


# =============================================================================
# 10. Extract All Images
# =============================================================================

def handle_extract_images() -> None:
    """Extract all image URLs from a page."""
    _print_header("EXTRACT ALL IMAGES")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        images = []
        for img in page.css('img'):
            src = ''
            if hasattr(img, 'attrib'):
                src = img.attrib.get('src', '') or img.attrib.get('data-src', '')
            if not src:
                src_list = img.css('::attr(src)').getall()
                src = src_list[0] if src_list else ''
            if not src:
                src_list = img.css('::attr(data-src)').getall()
                src = src_list[0] if src_list else ''

            if not src:
                continue

            alt = ''
            if hasattr(img, 'attrib'):
                alt = img.attrib.get('alt', '')
            if not alt:
                alt_list = img.css('::attr(alt)').getall()
                alt = alt_list[0] if alt_list else ''

            abs_src = urljoin(url, src)
            images.append({"src": abs_src, "alt": alt})

        # Also check for background images and picture/source elements
        for source in page.css('source::attr(srcset)').getall():
            if source:
                parts = source.strip().split(',')
                for part in parts:
                    src = part.strip().split()[0]
                    if src:
                        images.append({"src": urljoin(url, src), "alt": "srcset"})

        # Deduplicate by src
        seen = set()
        unique_images = []
        for img in images:
            if img['src'] not in seen:
                seen.add(img['src'])
                unique_images.append(img)

        _print_subheader(f"FOUND {len(unique_images)} IMAGES")

        for i, img in enumerate(unique_images[:20], 1):
            alt_text = f' | alt="{img["alt"][:30]}"' if img['alt'] else ''
            safe_print(f"  {i:3}. {img['src'][:70]}{alt_text}")

        if len(unique_images) > 20:
            safe_print(f"\n  ... and {len(unique_images) - 20} more")

        if unique_images and _confirm("\n  Save image list?"):
            data = {
                "url": url,
                "image_count": len(unique_images),
                "images": unique_images,
                "scraped_at": datetime.now().isoformat()
            }
            domain = urlparse(url).netloc.replace('.', '_')
            fp = _save_results(data, f"images_{domain}", "json")
            log_success(f"Saved to: {fp}")

    except Exception as e:
        log_error(f"Image extraction failed: {e}")


# =============================================================================
# 11. Find Similar Elements
# =============================================================================

def handle_find_similar() -> None:
    """Find elements similar to a matched CSS selector."""
    _print_header("FIND SIMILAR ELEMENTS")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    css_sel = _get_input("  CSS selector for the reference element (e.g. .product)")
    if not css_sel:
        return

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        matched = page.css(css_sel)
        if not matched:
            log_warn("No elements matched the CSS selector.")
            return

        first = matched[0]
        safe_print(f"\n  Reference element: <{getattr(first, 'tag', '?')}> "
                   f"{(first.css('::text').get() or '')[:60]}")

        similar = first.find_similar()

        _print_subheader(f"SIMILAR ELEMENTS ({len(similar) if similar else 0})")

        if not similar:
            safe_print("  No similar elements found.")
            return

        for i, el in enumerate(similar[:15], 1):
            tag = getattr(el, 'tag', '?')
            text = el.css('::text').get() or str(el)[:60]
            safe_print(f"  {i:3}. <{tag}> {text[:70]}")

        if len(similar) > 15:
            safe_print(f"\n  ... and {len(similar) - 15} more")

    except Exception as e:
        log_error(f"Find similar failed: {e}")


# =============================================================================
# 12. DOM Navigation
# =============================================================================

def handle_dom_navigation() -> None:
    """Interactive DOM traversal — parent, siblings, children, below."""
    _print_header("DOM NAVIGATION")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL")
    if not url:
        return

    css_sel = _get_input("  CSS selector for starting element")
    if not css_sel:
        return

    safe_print("\n  Fetching page...")
    try:
        page = Fetcher.get(url, stealthy_headers=True)
        _display_response_info(page)

        matched = page.css(css_sel)
        if not matched:
            log_warn("No elements matched.")
            return

        current = matched[0]
        safe_print(f"\n  Current: <{getattr(current, 'tag', '?')}> "
                   f"{(current.css('::text').get() or '')[:60]}")

        while True:
            safe_print("\n  Navigate:")
            safe_print("    1. Parent")
            safe_print("    2. Next sibling")
            safe_print("    3. Previous sibling")
            safe_print("    4. Children")
            safe_print("    5. Elements below")
            safe_print("    6. Get text content")
            safe_print("    7. Get attributes")
            safe_print("    8. Generate CSS selector")
            safe_print("    0. Back to menu")

            choice = _get_input("  Choose")

            if choice == "0" or not choice:
                break
            elif choice == "1":
                parent = current.parent
                if parent:
                    current = parent
                    safe_print(f"    → Parent: <{getattr(current, 'tag', '?')}>")
                else:
                    safe_print("    No parent found.")
            elif choice == "2":
                sib = current.next_sibling
                if sib:
                    current = sib
                    safe_print(f"    → Next: <{getattr(current, 'tag', '?')}> "
                               f"{(current.css('::text').get() or '')[:60]}")
                else:
                    safe_print("    No next sibling.")
            elif choice == "3":
                sib = current.previous_sibling
                if sib:
                    current = sib
                    safe_print(f"    → Prev: <{getattr(current, 'tag', '?')}> "
                               f"{(current.css('::text').get() or '')[:60]}")
                else:
                    safe_print("    No previous sibling.")
            elif choice == "4":
                children = current.children
                if children:
                    safe_print(f"    Children ({len(children)}):")
                    for i, child in enumerate(list(children)[:10], 1):
                        tag = getattr(child, 'tag', '?')
                        text = child.css('::text').get() or ""
                        safe_print(f"      {i}. <{tag}> {text[:50]}")
                else:
                    safe_print("    No children.")
            elif choice == "5":
                below = current.below_elements()
                if below:
                    safe_print(f"    Below elements ({len(below)}):")
                    for i, el in enumerate(below[:10], 1):
                        tag = getattr(el, 'tag', '?')
                        text = el.css('::text').get() or ""
                        safe_print(f"      {i}. <{tag}> {text[:50]}")
                else:
                    safe_print("    No elements below.")
            elif choice == "6":
                text = current.css('::text').getall()
                full_text = ' '.join(t.strip() for t in text if t.strip())
                safe_print(f"    Text: {full_text[:200]}")
            elif choice == "7":
                attribs = current.attrib if hasattr(current, 'attrib') else {}
                if attribs:
                    for key, val in attribs.items():
                        safe_print(f"    {key} = {val[:60]}")
                else:
                    safe_print("    No attributes.")
            elif choice == "8":
                try:
                    gen_sel = current.generate_css_selector() if hasattr(current, 'generate_css_selector') else "N/A"
                    safe_print(f"    CSS: {gen_sel}")
                except Exception:
                    safe_print("    Could not generate selector.")

    except Exception as e:
        log_error(f"DOM navigation failed: {e}")


# =============================================================================
# 13. Proxy Rotation Scrape
# =============================================================================

def handle_proxy_scrape() -> None:
    """Scrape with automatic proxy rotation."""
    _print_header("PROXY ROTATION SCRAPE")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    url = _get_input("Enter URL to scrape")
    if not url:
        return

    safe_print("\n  Enter proxy list (one per line, format: http://ip:port or socks5://ip:port)")
    safe_print("  Empty line to finish:\n")

    proxies = []
    while True:
        proxy = _get_input(f"  Proxy {len(proxies) + 1}")
        if not proxy:
            break
        proxies.append(proxy)

    if not proxies:
        log_warn("No proxies provided. Using direct connection.")

    safe_print(f"\n  Loaded {len(proxies)} proxies. Scraping...")

    try:
        if proxies:
            # Use proxy with Fetcher
            results = []
            for i, proxy in enumerate(proxies, 1):
                safe_print(f"\n  [{i}/{len(proxies)}] Using proxy: {proxy[:40]}...")
                try:
                    page = Fetcher.get(url, stealthy_headers=True, proxy=proxy)
                    status = getattr(page, 'status', 'unknown')
                    title = page.css('title::text').get() or "N/A"
                    safe_print(f"    Status: {status} | Title: {title[:40]}")
                    results.append({"proxy": proxy, "status": str(status), "title": title, "success": True})
                except Exception as e:
                    safe_print(f"    Failed: {e}")
                    results.append({"proxy": proxy, "error": str(e), "success": False})

            _print_subheader("PROXY RESULTS")
            success_count = sum(1 for r in results if r.get('success'))
            safe_print(f"  Successful: {success_count}/{len(results)}")

            if _confirm("\n  Save results?"):
                fp = _save_results(results, f"proxy_scrape_{datetime.now().strftime('%H%M%S')}", "json")
                log_success(f"Saved to: {fp}")
        else:
            page = Fetcher.get(url, stealthy_headers=True)
            _display_response_info(page)

    except Exception as e:
        log_error(f"Proxy scrape failed: {e}")


# =============================================================================
# 14. Batch URL Scrape
# =============================================================================

def handle_batch_scrape() -> None:
    """Scrape multiple URLs in one go."""
    _print_header("BATCH URL SCRAPE")

    if not HAS_SCRAPLING_FETCHERS:
        log_error("Scrapling fetchers not installed.")
        return

    safe_print("  Enter URLs (one per line, empty to finish):\n")
    urls = []
    while True:
        url = _get_input(f"  URL {len(urls) + 1}")
        if not url:
            break
        if url.startswith('http'):
            urls.append(url)
        else:
            safe_print(f"    Skipped (invalid): {url[:30]}")

    if not urls:
        safe_print("  No URLs provided.")
        return

    # Optional CSS selector
    css_sel = _get_input("\n  CSS selector to extract (empty for full page text)", "")

    safe_print(f"\n  Processing {len(urls)} URLs...\n")

    results = []
    for i, url in enumerate(urls, 1):
        safe_print(f"  [{i}/{len(urls)}] {url[:60]}...")
        try:
            page = Fetcher.get(url, stealthy_headers=True)
            status = getattr(page, 'status', 'unknown')
            title = page.css('title::text').get() or ""

            if css_sel:
                extracted = page.css(css_sel).getall()
                result_data = {
                    "url": url, "status": str(status), "title": title,
                    "selector": css_sel, "matches": len(extracted),
                    "data": extracted, "success": True
                }
            else:
                text_els = page.css('body').css('::text').getall() if page.css('body') else []
                text = ' '.join(t.strip() for t in text_els if t.strip())
                result_data = {
                    "url": url, "status": str(status), "title": title,
                    "word_count": len(text.split()), "text_preview": text[:300],
                    "success": True
                }

            safe_print(f"    [OK] {title[:40]} (status: {status})")
            results.append(result_data)

        except Exception as e:
            safe_print(f"    [FAIL] {e}")
            results.append({"url": url, "error": str(e), "success": False})

    _print_subheader("BATCH SUMMARY")
    success = sum(1 for r in results if r.get('success'))
    safe_print(f"  Successful : {success}/{len(results)}")
    safe_print(f"  Failed     : {len(results) - success}")

    if results and _confirm("\n  Save all results?"):
        safe_print("\n  Export format:")
        safe_print("    1. JSON")
        safe_print("    2. JSONL")
        safe_print("    3. CSV")
        fmt_choice = _get_input("  Choose", "1")

        fmt_map = {"1": "json", "2": "jsonl", "3": "csv"}
        fmt = fmt_map.get(fmt_choice, "json")
        fp = _save_results(results, f"batch_scrape_{datetime.now().strftime('%H%M%S')}", fmt)
        log_success(f"Saved to: {fp}")


# =============================================================================
# 15. Export Results
# =============================================================================

def handle_export_results() -> None:
    """View and re-export previously saved scrape results."""
    _print_header("EXPORT / VIEW RESULTS")

    if not os.path.exists(SCRAPLED_DATA_DIR):
        safe_print("  No scraped data found.")
        return

    files = []
    for f in os.listdir(SCRAPLED_DATA_DIR):
        fp = os.path.join(SCRAPLED_DATA_DIR, f)
        if os.path.isfile(fp):
            size = os.path.getsize(fp)
            files.append((f, fp, size))

    if not files:
        safe_print("  No scraped data files found.")
        return

    files.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)

    safe_print(f"\n  Found {len(files)} files in {SCRAPLED_DATA_DIR}:\n")
    for i, (name, fp, size) in enumerate(files[:20], 1):
        size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
        safe_print(f"  {i:3}. {name[:50]:50} {size_str:>10}")

    if len(files) > 20:
        safe_print(f"\n  ... and {len(files) - 20} more files")

    safe_print(f"\n  Data directory: {SCRAPLED_DATA_DIR}")

    choice = _get_input("\n  Enter file number to view/convert, or 0 to go back", "0")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(files):
            name, fp, size = files[idx]
            safe_print(f"\n  File: {name}")
            safe_print(f"  Size: {size} bytes")

            # Preview content
            ext = os.path.splitext(name)[1].lower()
            if ext in ('.json', '.jsonl', '.csv', '.txt', '.md'):
                with open(fp, 'r', encoding='utf-8') as f:
                    content = f.read(2000)
                safe_print(f"\n  Preview:\n  {'─' * 60}")
                for line in content[:1500].split('\n')[:30]:
                    safe_print(f"  {line[:80]}")
                safe_print(f"  {'─' * 60}")

            # Convert option
            if ext == '.json':
                safe_print("\n  Convert to:")
                safe_print("    1. JSONL")
                safe_print("    2. CSV")
                safe_print("    0. Skip")
                conv = _get_input("  Choose", "0")
                if conv in ("1", "2"):
                    with open(fp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    new_fmt = "jsonl" if conv == "1" else "csv"
                    base_name = os.path.splitext(name)[0]
                    new_fp = _save_results(data if isinstance(data, list) else [data],
                                           base_name, new_fmt)
                    log_success(f"Converted to: {new_fp}")
    except (ValueError, IndexError):
        pass


# =============================================================================
# Parse HTML from Clipboard / String (Bonus)
# =============================================================================

def handle_parse_html() -> None:
    """Parse raw HTML string using Scrapling's Selector."""
    _print_header("PARSE RAW HTML")

    if not HAS_SCRAPLING:
        log_error("Scrapling not installed. Run: pip install scrapling")
        return

    safe_print("  Paste HTML content (type END on a new line to finish):\n")

    lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == "END":
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break

    html = '\n'.join(lines)
    if not html.strip():
        safe_print("  No HTML provided.")
        return

    page = Selector(html)
    safe_print(f"\n  Parsed HTML ({len(html)} chars)")

    css = _get_input("  Enter CSS selector to extract")
    if css:
        results = page.css(css).getall()
        safe_print(f"\n  Matched {len(results)} elements:")
        for i, r in enumerate(results[:10], 1):
            safe_print(f"  {i}. {str(r)[:80]}")


# =============================================================================
# Scrapling Tool Sub-Menu
# =============================================================================

def display_scrapling_menu() -> None:
    """Display the Scrapling tool sub-menu."""
    safe_print("""
 WEB SCRAPING TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FETCHING:
    1.  Quick Scrape          (Fast HTTP fetch + extract)
    2.  Stealth Scrape        (Anti-bot / Cloudflare bypass)
    3.  Dynamic Scrape        (Full browser automation)

  EXTRACTION:
    4.  CSS / XPath Extractor (Extract specific elements)
    5.  Find by Text          (Search elements by text)
    6.  Extract All Links     (Categorize page links)
    7.  Extract All Images    (Collect image URLs)
    8.  Find Similar Elements (Auto-locate similar items)

  ADVANCED:
    9.  Spider Crawl          (Multi-page concurrent crawling)
   10.  Session Scrape        (Persistent session + cookies)
   11.  DOM Navigation        (Interactive element traversal)
   12.  Proxy Rotation Scrape (Scrape via proxy list)

  DATA:
   13.  Page to Text / MD     (Convert page to text/markdown)
   14.  Batch URL Scrape      (Scrape multiple URLs at once)
   15.  Parse Raw HTML        (Parse HTML string)
   16.  View / Export Results  (View saved data, convert formats)

    0.  Back to Main Menu
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


def _check_scrapling_status() -> None:
    """Show Scrapling installation status."""
    safe_print("\n  Scrapling Status:")
    safe_print(f"    Parser (Selector) : {'[OK]' if HAS_SCRAPLING else '[X] pip install scrapling'}")
    safe_print(f"    Fetchers          : {'[OK]' if HAS_SCRAPLING_FETCHERS else '[X] pip install scrapling[fetchers]'}")
    safe_print(f"    Spiders           : {'[OK]' if HAS_SCRAPLING_SPIDERS else '[X] pip install scrapling[all]'}")
    safe_print(f"    Data directory    : {SCRAPLED_DATA_DIR}")
    safe_print("")


async def run_scrapling_cli() -> None:
    """Run the Scrapling tool interactive CLI."""
    while True:
        display_scrapling_menu()
        _check_scrapling_status()

        choice = _get_input("Enter choice")

        if choice == "0" or not choice:
            break

        handler_map = {
            "1": handle_quick_scrape,
            "2": handle_stealth_scrape,
            "3": handle_dynamic_scrape,
            "4": handle_selector_extract,
            "5": handle_find_by_text,
            "6": handle_extract_links,
            "7": handle_extract_images,
            "8": handle_find_similar,
            "9": handle_spider_crawl,
            "10": handle_session_scrape,
            "11": handle_dom_navigation,
            "12": handle_proxy_scrape,
            "13": handle_page_to_text,
            "14": handle_batch_scrape,
            "15": handle_parse_html,
            "16": handle_export_results,
        }

        handler = handler_map.get(choice)
        if handler:
            try:
                handler()
            except KeyboardInterrupt:
                safe_print("\n  Cancelled.")
            except Exception as e:
                log_error(f"Error: {e}")
        else:
            safe_print("  Invalid choice.")

        safe_print("")
        _get_input("Press Enter to continue...")


# =============================================================================
# Database Integration
# =============================================================================

class ScraperDatabase:
    """Database wrapper for scraper operations"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.paths.database
        self._local = threading.local()
        self._init_db()
    
    def _get_conn(self):
        """Thread-local connection reuse"""
        import sqlite3
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")      # better concurrency
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _transaction(self):
        """Context manager for database transactions"""
        conn = self._get_conn()
        try:
            yield conn.cursor()
            conn.commit()
        except Exception as e:
            conn.rollback()
            log_debug(f"Database transaction failed: {e}")
            raise
    
    def _init_db(self):
        """Initialize database tables"""
        conn = self._get_conn()
        c = conn.cursor()
        
        # Downloads table
        c.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                platform TEXT,
                media_type TEXT,
                title TEXT,
                filename TEXT,
                filepath TEXT,
                filesize INTEGER,
                duration REAL,
                width INTEGER,
                height INTEGER,
                quality TEXT,
                has_audio INTEGER,
                has_video INTEGER,
                thumbnail_embedded INTEGER,
                metadata_embedded INTEGER,
                download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'complete'
            )
        ''')
        
        # Playlists table
        c.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                platform TEXT,
                title TEXT,
                author TEXT,
                video_count INTEGER,
                downloaded_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Playlist items table
        c.execute('''
            CREATE TABLE IF NOT EXISTS playlist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER,
                download_id INTEGER,
                position INTEGER,
                FOREIGN KEY (playlist_id) REFERENCES playlists(id),
                FOREIGN KEY (download_id) REFERENCES downloads(id)
            )
        ''')
        
        # Scraped pages table
        c.execute('''
            CREATE TABLE IF NOT EXISTS scraped_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                domain TEXT,
                title TEXT,
                content_type TEXT,
                word_count INTEGER,
                image_count INTEGER,
                link_count INTEGER,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
    
    def add_download(self, result: DownloadResult) -> int:
        """Add download record"""
        try:
            with self._transaction() as c:
                c.execute('''
                    INSERT OR REPLACE INTO downloads 
                    (url, platform, media_type, title, filename, filepath, 
                     filesize, duration, width, height, quality, 
                     has_audio, has_video, thumbnail_embedded, metadata_embedded, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    result.url,
                    result.platform.name if result.platform else None,
                    result.media_type.value if result.media_type else None,
                    result.title,
                    result.filename,
                    result.filepath,
                    result.filesize,
                    result.duration,
                    result.width,
                    result.height,
                    result.quality,
                    1 if result.has_audio else 0,
                    1 if result.has_video else 0,
                    1 if result.thumbnail_embedded else 0,
                    1 if result.metadata_embedded else 0,
                    'complete' if result.success else 'failed'
                ))
                return c.lastrowid
        except Exception as e:
            return -1
    
    def add_playlist(self, playlist: PlaylistInfo) -> int:
        """Add playlist record"""
        try:
            with self._transaction() as c:
                c.execute('''
                    INSERT OR REPLACE INTO playlists
                    (url, platform, title, author, video_count, downloaded_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    playlist.url,
                    playlist.platform.name,
                    playlist.title,
                    playlist.author.name if playlist.author else None,
                    playlist.video_count,
                    playlist.downloaded_count
                ))
                return c.lastrowid
        except Exception as e:
            return -1
    
    def update_playlist_progress(self, url: str, downloaded: int) -> None:
        """Update playlist download progress"""
        try:
            with self._transaction() as c:
                c.execute('''
                    UPDATE playlists 
                    SET downloaded_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE url = ?
                ''', (downloaded, url))
        except Exception:
            pass
    
    def add_scraped_page(self, page: ScrapedPage) -> int:
        """Add scraped page record"""
        try:
            with self._transaction() as c:
                c.execute('''
                    INSERT OR REPLACE INTO scraped_pages
                    (url, domain, title, content_type, word_count, image_count, link_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    page.url,
                    get_domain(page.url),
                    page.metadata.title if page.metadata else '',
                    page.content_type.value,
                    page.text_content.word_count if page.text_content else 0,
                    len(page.images),
                    len(page.links)
                ))
                return c.lastrowid
        except Exception as e:
            return -1
    
    def get_download(self, url: str) -> Optional[Dict]:
        """Get download by URL"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM downloads WHERE url = ?', (url,))
        row = c.fetchone()
        return dict(row) if row else None
    
    def is_downloaded(self, url: str) -> bool:
        """Check if URL was already downloaded"""
        download = self.get_download(url)
        return download is not None and download.get('status') == 'complete'
    
    def get_stats(self) -> Dict[str, Any]:
        """Get download statistics"""
        conn = self._get_conn()
        c = conn.cursor()
        
        stats = {}
        
        c.execute('SELECT COUNT(*) FROM downloads WHERE status = "complete"')
        stats['total_downloads'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM downloads WHERE media_type = "video"')
        stats['videos'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM downloads WHERE media_type = "audio"')
        stats['audio_files'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM downloads WHERE has_audio = 1')
        stats['videos_with_audio'] = c.fetchone()[0]
        
        c.execute('SELECT SUM(filesize) FROM downloads')
        total_bytes = c.fetchone()[0] or 0
        stats['total_size_gb'] = total_bytes / (1024 ** 3)
        
        c.execute('SELECT COUNT(*) FROM playlists')
        stats['playlists'] = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM scraped_pages')
        stats['scraped_pages'] = c.fetchone()[0]
        
        return stats
    
    def search(self, query: str) -> Dict[str, List[Dict]]:
        """Search downloads and pages"""
        conn = self._get_conn()
        c = conn.cursor()
        
        results = {'downloads': [], 'pages': []}
        
        c.execute('''
            SELECT * FROM downloads 
            WHERE title LIKE ? OR filename LIKE ? OR url LIKE ?
            ORDER BY download_date DESC LIMIT 50
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))
        results['downloads'] = [dict(r) for r in c.fetchall()]
        
        c.execute('''
            SELECT * FROM scraped_pages
            WHERE title LIKE ? OR url LIKE ?
            ORDER BY scraped_at DESC LIMIT 50
        ''', (f'%{query}%', f'%{query}%'))
        results['pages'] = [dict(r) for r in c.fetchall()]
        
        return results
    
    def list_downloads(self, media_type: str = None, limit: int = 50) -> List[Dict]:
        """List recent downloads"""
        conn = self._get_conn()
        c = conn.cursor()
        
        if media_type:
            c.execute('''
                SELECT * FROM downloads 
                WHERE media_type = ? 
                ORDER BY download_date DESC LIMIT ?
            ''', (media_type, limit))
        else:
            c.execute('''
                SELECT * FROM downloads 
                ORDER BY download_date DESC LIMIT ?
            ''', (limit,))
        
        results = [dict(r) for r in c.fetchall()]
        return results
        
    def close(self):
        """Close thread-local connection"""
        if hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None


# Lazy Database Singleton
_db_instance: Optional[ScraperDatabase] = None

def get_db() -> ScraperDatabase:
    """Lazy database singleton"""
    global _db_instance
    if _db_instance is None:
        _db_instance = ScraperDatabase()
    return _db_instance


# =============================================================================
# Thumbnail Handler
# =============================================================================

class ThumbnailHandler:
    """Handle thumbnail downloading and embedding"""
    
    def __init__(self, temp_dir: str = None):
        self.temp_dir = temp_dir or config.paths.temp
        os.makedirs(self.temp_dir, exist_ok=True)
    
    async def download(self, url: str) -> Optional[str]:
        """Download thumbnail to temp file"""
        if not url:
            return None
        
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            output = os.path.join(self.temp_dir, f'thumb_{url_hash}.jpg')
            
            # Use bot module if available
            if HAS_BOT and HAS_AIOHTTP:
                async with StealthSession() as session:
                    success = await session.download(url, output)
                    if success:
                        return output
            
            # Fallback to aiohttp
            elif HAS_AIOHTTP:
                from shared import SessionManager
                session = await SessionManager.get().session()
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(output, 'wb') as f:
                            await f.write(await resp.read())
                        return output
        
        except Exception as e:
            log_debug(f"Thumbnail download error: {e}")
        
        return None
    
    def embed_in_video(self, video_path: str, thumb_path: str) -> bool:
        """Embed thumbnail into video file"""
        if not HAS_FFMPEG or not thumb_path or not os.path.exists(thumb_path):
            return False
        
        if not os.path.exists(video_path):
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
                '-c:v:1', 'mjpeg',
                '-disposition:v:1', 'attached_pic',
                temp_output
            ]
            
            ok, _, err = run_command(cmd, 120)
            
            if ok and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
                os.remove(video_path)
                shutil.move(temp_output, video_path)
                log_debug("Thumbnail embedded in video")
                return True
            
            if os.path.exists(temp_output):
                os.remove(temp_output)
        
        except Exception as e:
            log_debug(f"Video thumbnail embed error: {e}")
        
        return False
    
    def embed_in_audio(self, audio_path: str, thumb_path: str,
                       title: str = None, artist: str = None,
                       album: str = None) -> bool:
        """Embed thumbnail and metadata into audio file"""
        if not HAS_FFMPEG or not thumb_path or not os.path.exists(thumb_path):
            return False
        
        if not os.path.exists(audio_path):
            return False
        
        try:
            ext = os.path.splitext(audio_path)[1].lower()
            temp_output = audio_path + '.temp' + ext
            
            # Build metadata arguments
            metadata = []
            if title:
                metadata.extend(['-metadata', f'title={title}'])
            if artist:
                metadata.extend(['-metadata', f'artist={artist}'])
            if album:
                metadata.extend(['-metadata', f'album={album}'])
            
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
            
            if ok and os.path.exists(temp_output) and os.path.getsize(temp_output) > 1000:
                os.remove(audio_path)
                shutil.move(temp_output, audio_path)
                log_debug("Thumbnail embedded in audio")
                return True
            
            if os.path.exists(temp_output):
                os.remove(temp_output)
        
        except Exception as e:
            log_debug(f"Audio thumbnail embed error: {e}")
        
        return False
    
    def save_separately(self, thumb_path: str, title: str) -> Optional[str]:
        """Save thumbnail to thumbnails directory"""
        if not thumb_path or not os.path.exists(thumb_path):
            return None
        
        try:
            safe_title = sanitize_filename(title)
            dest = os.path.join(config.paths.thumbnails, f'{safe_title}.jpg')
            dest = get_unique_filepath(dest)
            shutil.copy2(thumb_path, dest)
            return dest
        except Exception as e:
            log_debug(f"Thumbnail save error: {e}")
        
        return None


# =============================================================================
# Audio Verifier
# =============================================================================

class AudioVerifier:
    """Verify audio presence in media files"""
    
    @staticmethod
    async def has_audio_async(filepath: str) -> bool:
        """Check if file has audio (triple verification) in parallel"""
        if not os.path.exists(filepath):
            return False
        
        if os.path.getsize(filepath) < 1000:
            return False
        
        if not HAS_FFPROBE:
            return True  # Assume yes if can't verify
        
        # Run three independent checks in parallel via executor
        loop = asyncio.get_event_loop()
        checks = await asyncio.gather(
            loop.run_in_executor(None, AudioVerifier._check_stream, filepath),
            loop.run_in_executor(None, AudioVerifier._check_codec, filepath),
            loop.run_in_executor(None, AudioVerifier._check_duration, filepath)
        )
        
        # Require at least 2 confirmations
        confirmations = sum(checks)
        log_debug(f"Audio verification: {confirmations}/3 checks passed")
        
        return confirmations >= 2

    # Keeping synchronous version for backward compatibility
    @staticmethod
    def has_audio(filepath: str) -> bool:
        return asyncio.run(AudioVerifier.has_audio_async(filepath))
    
    @staticmethod
    def _check_stream(filepath: str) -> bool:
        """Check for audio stream presence"""
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'a',
            '-show_entries', 'stream=index', '-of', 'csv=p=0',
            filepath
        ]
        ok, out, _ = run_command(cmd, 10)
        return ok and bool(out.strip())
    
    @staticmethod
    def _check_codec(filepath: str) -> bool:
        """Check for audio codec"""
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            filepath
        ]
        ok, out, _ = run_command(cmd, 10)
        
        if ok and out:
            codec = out.strip().lower()
            audio_codecs = ['aac', 'mp3', 'opus', 'vorbis', 'flac', 'ac3', 'pcm', 'alac', 'eac3']
            return any(c in codec for c in audio_codecs)
        return False
    
    @staticmethod
    def _check_duration(filepath: str) -> bool:
        """Check audio stream duration"""
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=duration',
            '-of', 'default=nokey=1:noprint_wrappers=1',
            filepath
        ]
        ok, out, _ = run_command(cmd, 10)
        
        try:
            return ok and float(out.strip()) > 0.5
        except (ValueError, AttributeError):
            return False
    
    @staticmethod
    def get_media_info(filepath: str) -> Dict[str, Any]:
        """Get detailed media information"""
        info = {
            'filepath': filepath,
            'filesize': 0,
            'duration': 0.0,
            'width': 0,
            'height': 0,
            'has_video': False,
            'has_audio': False,
            'video_codec': None,
            'audio_codec': None,
            'bitrate': 0,
            'fps': 0.0
        }
        
        if not os.path.exists(filepath):
            return info
        
        info['filesize'] = os.path.getsize(filepath)
        
        if not HAS_FFPROBE:
            return info
        
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', filepath
        ]
        ok, out, _ = run_command(cmd, 60)
        
        if not ok or not out:
            return info
        
        try:
            # Find JSON start
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
                    # Skip attached pics
                    if stream.get('disposition', {}).get('attached_pic'):
                        continue
                    
                    info['has_video'] = True
                    info['video_codec'] = stream.get('codec_name')
                    info['width'] = stream.get('width', 0)
                    info['height'] = stream.get('height', 0)
                    
                    # Calculate FPS
                    fps_str = stream.get('r_frame_rate', '0/1')
                    try:
                        num, den = map(int, fps_str.split('/'))
                        info['fps'] = num / den if den else 0
                    except (ValueError, ZeroDivisionError):
                        pass
                
                elif codec_type == 'audio':
                    info['has_audio'] = True
                    info['audio_codec'] = stream.get('codec_name')
        
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log_debug(f"Media info parse error: {e}")
        
        # Double-check audio
        if not info['has_audio']:
            info['has_audio'] = AudioVerifier.has_audio(filepath)
        
        return info


# =============================================================================
# Video/Audio Merger
# =============================================================================

class MediaMerger:
    """Merge video and audio streams"""
    
    @staticmethod
    def merge(video_path: str, audio_path: str, output_path: str,
              timeout: int = 3600) -> bool:
        """Merge video and audio files"""
        if not HAS_FFMPEG:
            log_error("FFmpeg not available")
            return False
        
        if not os.path.exists(video_path):
            log_error(f"Video file not found: {video_path}")
            return False
        
        if not os.path.exists(audio_path):
            log_error(f"Audio file not found: {audio_path}")
            return False
        
        log_info("Merging video and audio streams...")
        
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
        
        ok, _, err = run_command(cmd, timeout)
        
        if not ok:
            log_error(f"Merge failed: {err[:200] if err else 'Unknown error'}")
            return False
        
        if not os.path.exists(output_path):
            log_error("Merged output file not created")
            return False
        
        if not AudioVerifier.has_audio(output_path):
            log_warn("Merged file may not have audio")
        
        log_success("Merge complete")
        return True
    
    @staticmethod
    def convert_audio(input_path: str, output_path: str,
                      format: str = 'mp3', bitrate: str = '192k') -> bool:
        """Convert audio to different format"""
        if not HAS_FFMPEG:
            return False
        
        codec_map = {
            'mp3': 'libmp3lame',
            'm4a': 'aac',
            'aac': 'aac',
            'opus': 'libopus',
            'flac': 'flac',
            'wav': 'pcm_s16le',
            'ogg': 'libvorbis'
        }
        
        codec = codec_map.get(format.lower(), 'libmp3lame')
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-c:a', codec,
            '-b:a', bitrate,
            output_path
        ]
        
        ok, _, _ = run_command(cmd, 600)
        return ok and os.path.exists(output_path)


# =============================================================================
# Download Progress Tracker
# =============================================================================

class ProgressTracker:
    """Track and display download progress"""
    
    def __init__(self, title: str = "", total_size: int = 0):
        self.title = title
        self.total_size = total_size
        self.downloaded = 0
        self.speed = 0.0
        self.eta = 0.0
        self.status = "Starting..."
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        self.callback: Optional[Callable] = None
    
    def set_callback(self, callback: Callable) -> None:
        """Set progress callback function"""
        self.callback = callback
    
    def update(self, downloaded: int, total: int = None,
               speed: float = None, status: str = None) -> None:
        """Update progress"""
        self.downloaded = downloaded
        
        if total:
            self.total_size = total
        
        if speed:
            self.speed = speed
        else:
            # Calculate speed
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed > 0:
                self.speed = self.downloaded / elapsed
        
        # Calculate ETA
        if self.speed > 0 and self.total_size > 0:
            remaining = self.total_size - self.downloaded
            self.eta = remaining / self.speed
        
        if status:
            self.status = status
        
        # Call callback if set
        if self.callback:
            self.callback(self._get_progress())
        
        self._display()
    
    def _get_progress(self) -> DownloadProgress:
        """Get progress as DownloadProgress object"""
        return DownloadProgress(
            total_bytes=self.total_size,
            downloaded_bytes=self.downloaded,
            speed=self.speed,
            eta=self.eta,
            status=self.status
        )
    
    def _display(self) -> None:
        """Display progress bar"""
        # Calculate percentage
        if self.total_size > 0:
            pct = (self.downloaded / self.total_size) * 100
            filled = int(40 * self.downloaded / self.total_size)
        else:
            pct = 0
            filled = 0
        
        bar = "█" * filled + "░" * (40 - filled)
        
        # Format sizes
        dl_str = format_size(self.downloaded)
        total_str = format_size(self.total_size) if self.total_size else "???"
        speed_str = f"{format_size(int(self.speed))}/s" if self.speed else "---"
        
        # Format ETA
        if self.eta > 0:
            mins, secs = divmod(int(self.eta), 60)
            eta_str = f"{mins:02d}:{secs:02d}"
        else:
            eta_str = "--:--"
        
        # Print progress line
        line = f"\r[{bar}] {pct:5.1f}% | {dl_str}/{total_str} | {speed_str} | ETA: {eta_str}"
        
        # Get terminal width dynamically
        import shutil
        term_width = shutil.get_terminal_size((80, 20)).columns
        
        sys.stdout.write(line.ljust(term_width)[:term_width])
        sys.stdout.flush()
    
    def complete(self, success: bool = True) -> None:
        """Mark as complete"""
        sys.stdout.write("\r" + " " * 79 + "\r")
        sys.stdout.flush()
        
        if success:
            log_success(f"Downloaded: {self.title[:50]}")
        else:
            log_error(f"Failed: {self.title[:50]}")
    
    def fail(self, error: str) -> None:
        """Mark as failed"""
        sys.stdout.write("\n")
        log_error(error)


# =============================================================================
# Main Scraper Class
# =============================================================================

class Scraper:
    """
    Main scraper and downloader class.
    Orchestrates all download and scraping operations.
    """
    
    def __init__(self,
                 video_dir: str = None,
                 audio_dir: str = None,
                 use_bot: bool = None,
                 embed_thumbnail: bool = True,
                 embed_metadata: bool = True,
                 organize_by_platform: bool = True):
        """
        Initialize scraper.
        
        Args:
            video_dir: Custom video output directory
            audio_dir: Custom audio output directory
            use_bot: Enable bot module for anti-detection
            embed_thumbnail: Embed thumbnails in media files
            embed_metadata: Embed metadata in media files
            organize_by_platform: Organize downloads by platform
        """
        self.video_dir = video_dir or config.paths.videos
        self.audio_dir = audio_dir or config.paths.audio
        
        self.use_bot = use_bot if use_bot is not None else (HAS_BOT and config.bot.enabled)
        self.embed_thumbnail = embed_thumbnail
        self.embed_metadata = embed_metadata
        self.organize_by_platform = organize_by_platform
        
        # Initialize lazily
        self._temp_dir = None
        self._bot = None
        self._osint_engine = None
        
        # Components
        self.thumbnail_handler = ThumbnailHandler()
        
        # Stats tracking
        self.stats = {
            'started': datetime.now(),
            'videos': 0,
            'audio': 0,
            'images': 0,
            'pages': 0,
            'bytes': 0
        }
        
        # Ensure directories exist
        os.makedirs(self.video_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)
        
        log_info(f"Initialized Scraper (bot: {use_bot})")
    
    @property
    def db(self) -> ScraperDatabase:
        """Lazy access to global database wrapper"""
        return get_db()
    
    @property
    def temp_dir(self) -> str:
        """Lazy creation of temporary directory"""
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="scraper_")
        return self._temp_dir
        
    def _cleanup_temp(self):
        """Clean up the temp directory if it was created"""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception as e:
                log_error(f"Error cleaning up temp dir: {e}")
            finally:
                self._temp_dir = None
                
    def __del__(self):
        """Fallback cleanup on garbage collection"""
        self._cleanup_temp()
        
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._cleanup_temp()
    
    # =========================================================================
    # Video Download
    # =========================================================================
    
    async def download_video(self,
                             url: str,
                             quality: Quality = None,
                             format: str = 'mp4',
                             output_dir: str = None,
                             filename: str = None,
                             progress_callback: Callable = None) -> DownloadResult:
        """
        Download video from URL.
        
        Args:
            url: Video URL
            quality: Video quality (default: 1080p)
            format: Output format (mp4, mkv, webm)
            output_dir: Custom output directory
            filename: Custom filename (without extension)
            progress_callback: Progress callback function
        
        Returns:
            DownloadResult with download status and file info
        """
        result = DownloadResult(
            url=url,
            platform=detect_platform(url),
            media_type=MediaType.VIDEO
        )
        
        result.success = False
        result.error = "Video download feature has been removed/disabled"
        log_error(result.error)
        return result
        
        quality = quality or config.media.default_video_quality
        
        # Fetch metadata first
        log_info("Fetching video information...")
        metadata = await extract_metadata(url)
        
        if metadata:
            result.title = metadata.title
            result.duration = metadata.duration
            log_info(f"Title: {result.title[:60]}")
            log_info(f"Duration: {format_duration(metadata.duration)}")
        else:
            result.title = f"video_{hashlib.md5(url.encode()).hexdigest()[:10]}"
            log_warn("Could not fetch metadata, using fallback title")
        
        # Determine output path
        out_dir = output_dir or self.video_dir
        
        if self.organize_by_platform:
            out_dir = os.path.join(out_dir, result.platform.name.title())
        
        os.makedirs(out_dir, exist_ok=True)
        
        safe_title = filename or sanitize_filename(result.title)
        output_path = os.path.join(out_dir, f'{safe_title}.{format}')
        output_path = get_unique_filepath(output_path)
        
        # Download with retry
        for attempt in range(1, config.network.max_retries + 1):
            log_info(f"Downloading (attempt {attempt}/{config.network.max_retries})...")
            
            result = await self._download_video_ytdlp(
                url=url,
                output_path=output_path,
                quality=quality,
                format=format,
                metadata=metadata,
                result=result,
                progress_callback=progress_callback
            )
            
            if result.success:
                break
            
            if attempt < config.network.max_retries:
                log_warn(f"Retrying in {config.network.retry_delay}s...")
                await asyncio.sleep(config.network.retry_delay)
        
        # Post-process if successful
        if result.success:
            # Embed thumbnail
            if self.embed_thumbnail and metadata:
                thumb_url = metadata.best_thumbnail.url if metadata.best_thumbnail else None
                if thumb_url:
                    thumb_path = await self.thumbnail_handler.download(thumb_url)
                    if thumb_path:
                        if self.thumbnail_handler.embed_in_video(result.filepath, thumb_path):
                            result.thumbnail_embedded = True
                        # Also save separately
                        self.thumbnail_handler.save_separately(thumb_path, result.title)
                        # Cleanup temp thumbnail
                        try:
                            os.remove(thumb_path)
                        except:
                            pass
            
            # Update stats
            self.stats['videos'] += 1
            self.stats['bytes'] += result.filesize
            
            # Save to database
            self.db.add_download(result)
            
            log_success(f"Saved: {os.path.basename(result.filepath)}")
            log_info(f"Size: {format_size(result.filesize)}")
            log_info(f"Audio: {'Yes' if result.has_audio else 'No'}")
        
        return result
    
    async def _download_video_ytdlp(self,
                                     url: str,
                                     output_path: str,
                                     quality: Quality,
                                     format: str,
                                     metadata: MediaMetadata,
                                     result: DownloadResult,
                                     progress_callback: Callable = None) -> DownloadResult:
        """Execute yt-dlp download"""
        
        # Build format selector
        if quality == Quality.BEST:
            fmt_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == Quality.WORST:
            fmt_selector = 'worstvideo+worstaudio/worst'
        else:
            height = quality.height
            fps = quality.fps
            
            if fps > 30:
                fmt_selector = (
                    f'bestvideo[height<={height}][fps>={fps}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'best[height<={height}]/best'
                )
            else:
                fmt_selector = (
                    f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/'
                    f'best[height<={height}]/best'
                )
        
        # Build command
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--no-playlist',
            '--continue',
            '--no-overwrites',
            '-f', fmt_selector,
            '--merge-output-format', format,
            '-o', output_path,
            '--retries', '3',
            '--fragment-retries', '3',
        ]
        
        # Add metadata options
        if self.embed_metadata:
            cmd.append('--add-metadata')
        
        if self.embed_thumbnail:
            cmd.append('--embed-thumbnail')
            cmd.append('--write-thumbnail')
        
        # Add URL
        cmd.append(url)
        
        # Execute
        progress = ProgressTracker(result.title)
        if progress_callback:
            progress.set_callback(progress_callback)
        
        ok, out, err = await run_command_async(cmd, config.network.download_timeout)
        
        if not ok:
            result.error = err[:200] if err else "Download failed"
            progress.fail(result.error)
            return result
        
        # Find output file
        if os.path.exists(output_path):
            filepath = output_path
        else:
            # Try to find with different extension
            base = os.path.splitext(output_path)[0]
            for ext in ['.mp4', '.mkv', '.webm', '.avi']:
                if os.path.exists(base + ext):
                    filepath = base + ext
                    break
            else:
                result.error = "Output file not found"
                progress.fail(result.error)
                return result
        
        # Get file info
        info = AudioVerifier.get_media_info(filepath)
        
        result.success = True
        result.filepath = filepath
        result.filename = os.path.basename(filepath)
        result.filesize = info['filesize']
        result.duration = info['duration']
        result.width = info['width']
        result.height = info['height']
        result.has_video = info['has_video']
        result.has_audio = info['has_audio']
        result.quality = f"{info['height']}p" if info['height'] else "unknown"
        result.metadata_embedded = self.embed_metadata
        
        progress.complete(True)
        return result
    
    # =========================================================================
    # Audio Download
    # =========================================================================
    
    async def download_audio(self,
                             url: str,
                             quality: AudioQuality = None,
                             format: str = 'mp3',
                             output_dir: str = None,
                             filename: str = None,
                             progress_callback: Callable = None) -> DownloadResult:
        """
        Download audio from URL.
        
        Args:
            url: Audio/video URL
            quality: Audio quality (default: 192kbps)
            format: Output format (mp3, m4a, flac, etc.)
            output_dir: Custom output directory
            filename: Custom filename (without extension)
            progress_callback: Progress callback function
        
        Returns:
            DownloadResult with download status and file info
        """
        result = DownloadResult(
            url=url,
            platform=detect_platform(url),
            media_type=MediaType.AUDIO
        )
        
        if not HAS_YTDLP:
            result.error = "yt-dlp not installed"
            return result
        
        quality = quality or config.media.default_audio_quality
        
        # Fetch metadata
        log_info("Fetching audio information...")
        metadata = await extract_metadata(url)
        
        if metadata:
            result.title = metadata.title
            result.duration = metadata.duration
            log_info(f"Title: {result.title[:60]}")
            log_info(f"Duration: {format_duration(metadata.duration)}")
        else:
            result.title = f"audio_{hashlib.md5(url.encode()).hexdigest()[:10]}"
        
        # Determine output path
        out_dir = output_dir or self.audio_dir
        
        if self.organize_by_platform:
            out_dir = os.path.join(out_dir, result.platform.name.title())
        
        os.makedirs(out_dir, exist_ok=True)
        
        safe_title = filename or sanitize_filename(result.title)
        output_path = os.path.join(out_dir, f'{safe_title}.{format}')
        output_path = get_unique_filepath(output_path)
        
        # Build yt-dlp command
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--no-playlist',
            '-f', 'bestaudio[ext=m4a]/bestaudio',
            '-x',
            '--audio-format', format,
            '--audio-quality', quality.label if quality != AudioQuality.BEST else '0',
            '-o', output_path,
        ]
        
        if self.embed_metadata:
            cmd.append('--add-metadata')
        
        if self.embed_thumbnail:
            cmd.append('--embed-thumbnail')
            cmd.append('--write-thumbnail')
        
        cmd.append(url)
        
        # Execute
        progress = ProgressTracker(result.title)
        if progress_callback:
            progress.set_callback(progress_callback)
        
        log_info("Downloading audio...")
        
        ok, out, err = await run_command_async(cmd, config.network.download_timeout)
        
        if not ok:
            result.error = err[:200] if err else "Download failed"
            progress.fail(result.error)
            return result
        
        # Find output file
        base = os.path.splitext(output_path)[0]
        for ext in [f'.{format}', '.mp3', '.m4a', '.opus', '.ogg', '.flac']:
            if os.path.exists(base + ext):
                filepath = base + ext
                break
        else:
            result.error = "Output file not found"
            progress.fail(result.error)
            return result
        
        result.success = True
        result.filepath = filepath
        result.filename = os.path.basename(filepath)
        result.filesize = os.path.getsize(filepath)
        result.has_audio = True
        result.metadata_embedded = self.embed_metadata
        
        # Embed thumbnail if not already done
        if self.embed_thumbnail and metadata:
            thumb_url = metadata.best_thumbnail.url if metadata.best_thumbnail else None
            if thumb_url:
                thumb_path = await self.thumbnail_handler.download(thumb_url)
                if thumb_path:
                    artist = metadata.author.name if metadata.author else None
                    if self.thumbnail_handler.embed_in_audio(
                        filepath, thumb_path, result.title, artist
                    ):
                        result.thumbnail_embedded = True
                    
                    self.thumbnail_handler.save_separately(thumb_path, result.title)
                    
                    try:
                        os.remove(thumb_path)
                    except:
                        pass
        
        progress.complete(True)
        
        # Update stats
        self.stats['audio'] += 1
        self.stats['bytes'] += result.filesize
        
        # Save to database
        self.db.add_download(result)
        
        log_success(f"Saved: {os.path.basename(filepath)}")
        log_info(f"Size: {format_size(result.filesize)}")
        
        return result
    
    # =========================================================================
    # Playlist Download
    # =========================================================================
    
    async def download_playlist(self,
                                url: str,
                                audio_only: bool = False,
                                quality: Quality = None,
                                audio_quality: AudioQuality = None,
                                format: str = None,
                                start: int = 1,
                                end: int = None,
                                output_dir: str = None,
                                progress_callback: Callable = None) -> PlaylistDownloadResult:
        """
        Download YouTube playlist.
        
        Args:
            url: Playlist URL
            audio_only: Download audio only
            quality: Video quality
            audio_quality: Audio quality (if audio_only)
            format: Output format
            start: Start index (1-based)
            end: End index (inclusive)
            output_dir: Custom output directory
            progress_callback: Progress callback function
        
        Returns:
            PlaylistDownloadResult with playlist info and results
        """
        result = PlaylistDownloadResult()
        if not audio_only:
            result.success = False
            result.error = "Video download feature has been removed/disabled. Only audio playlist downloads are supported."
            log_error(result.error)
            return result
            
        if not HAS_YTDLP:
            result.error = "yt-dlp not installed"
            return result
        
        # Get playlist info
        log_info("Fetching playlist information...")
        playlist = await extract_playlist(url)
        
        if not playlist:
            result.error = "Could not fetch playlist information"
            return result
        
        result.playlist_title = playlist.title
        result.total = playlist.video_count
        
        log_info(f"Playlist: {playlist.title}")
        log_info(f"Videos: {playlist.video_count}")
        if playlist.author:
            log_info(f"Creator: {playlist.author.name}")
        
        # Determine range
        entries = playlist.entries[start - 1:end] if end else playlist.entries[start - 1:]
        
        log_info(f"Downloading {len(entries)} items (#{start} to #{start + len(entries) - 1})")
        
        # Create output directory
        if output_dir:
            out_dir = output_dir
        else:
            base_dir = self.audio_dir if audio_only else self.video_dir
            out_dir = os.path.join(base_dir, sanitize_filename(playlist.title))
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Save playlist to database
        self.db.add_playlist(playlist)
        
        # Download each item
        fmt = format or ('mp3' if audio_only else 'mp4')
        vid_quality = quality or config.media.default_video_quality
        aud_quality = audio_quality or config.media.default_audio_quality
        
        for idx, entry in enumerate(entries, start=start):
            video_id = entry.id
            video_title = entry.title or f"Video {idx}"
            
            # Build video URL
            if playlist.platform == Platform.YOUTUBE_PLAYLIST:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                video_url = entry.url or url
            
            log_info(f"\n[{idx}/{result.total}] {video_title[:50]}")
            
            # Check if already downloaded
            if self.db.is_downloaded(video_url):
                log_info("  Already downloaded, skipping...")
                result.skipped += 1
                continue
            
            try:
                # Download
                if audio_only:
                    dl_result = await self.download_audio(
                        url=video_url,
                        quality=aud_quality,
                        format=fmt,
                        output_dir=out_dir,
                        filename=f"{idx:03d}. {sanitize_filename(video_title)}",
                        progress_callback=progress_callback
                    )
                else:
                    dl_result = await self.download_video(
                        url=video_url,
                        quality=vid_quality,
                        format=fmt,
                        output_dir=out_dir,
                        filename=f"{idx:03d}. {sanitize_filename(video_title)}",
                        progress_callback=progress_callback
                    )
                
                if dl_result.success:
                    result.downloaded += 1
                    result.total_bytes += dl_result.filesize
                    result.items.append({
                        'index': idx,
                        'title': video_title,
                        'success': True,
                        'filepath': dl_result.filepath,
                        'size': dl_result.filesize
                    })
                else:
                    result.failed += 1
                    result.items.append({
                        'index': idx,
                        'title': video_title,
                        'success': False,
                        'error': dl_result.error
                    })
            
            except Exception as e:
                result.failed += 1
                result.items.append({
                    'index': idx,
                    'title': video_title,
                    'success': False,
                    'error': str(e)
                })
                log_error(f"  Error: {str(e)[:50]}")
            
            # Update playlist progress
            self.db.update_playlist_progress(url, result.downloaded)
            
            # Small delay between downloads
            await asyncio.sleep(0.5)
        
        result.success = result.downloaded > 0
        
        # Summary
        log_info("")
        log_success("Playlist download complete!")
        log_info(f"Downloaded: {result.downloaded}/{len(entries)}")
        log_info(f"Failed: {result.failed}")
        log_info(f"Skipped: {result.skipped}")
        log_info(f"Total size: {format_size(result.total_bytes)}")
        log_info(f"Location: {out_dir}")
        
        return result
    
    # =========================================================================
    # Page Scraping
    # =========================================================================
    
    async def scrape_page(self,
                          url: str,
                          download_videos: bool = False,
                          download_images: bool = False,
                          extract_text: bool = True,
                          max_videos: int = 10,
                          max_images: int = 50) -> ScrapedPage:
        """
        Scrape content from a web page.
        
        Args:
            url: Page URL
            download_videos: Download found videos
            download_images: Download found images
            extract_text: Extract text content
            max_videos: Maximum videos to download
            max_images: Maximum images to download
        
        Returns:
            ScrapedPage with extracted content
        """
        platform = detect_platform(url)
        
        # For video platforms, just download
        if platform not in [Platform.GENERIC, Platform.DIRECT]:
            page = ScrapedPage(url=url, platform=platform)
            
            if download_videos:
                result = await self.download_video(url)
                if result.success:
                    page.videos.append(MediaMetadata(
                        id=result.filename,
                        title=result.title,
                        url=url,
                        platform=platform,
                        media_type=MediaType.VIDEO
                    ))
            
            page.success = True
            return page
        
        # Fetch page content
        log_info(f"Scraping: {url[:60]}")
        
        html = None
        
        # Use bot module if available
        if self.use_bot and HAS_BOT:
            try:
                result = await fetch_with_stealth(url)
                if result:
                    html = result[0]
            except Exception as e:
                log_debug(f"Bot fetch failed: {e}")
        
        # Fallback to simple fetch
        if not html and HAS_AIOHTTP:
            try:
                from shared import SessionManager
                html = await SessionManager.get().fetch(url, timeout=config.network.request_timeout)
            except Exception as e:
                log_debug(f"Fetch failed: {e}")
        
        if not html:
            return ScrapedPage(url=url, error="Failed to fetch page")
        
        # Parse HTML
        extractor = HTMLExtractor()
        page = extractor.parse_html(html, url)
        
        # Download videos
        if download_videos and page.videos:
            log_info(f"Found {len(page.videos)} videos")
            for video in page.videos[:max_videos]:
                try:
                    await self.download_video(video.url)
                except Exception as e:
                    log_error(f"Video download failed: {e}")
        
        # Download images
        if download_images and page.images:
            log_info(f"Found {len(page.images)} images")
            await self._download_images(page.images[:max_images], url)
        
        # Save text content
        if extract_text and page.text_content:
            self._save_text_content(page, url)
        
        # Update stats
        self.stats['pages'] += 1
        
        # Save to database
        self.db.add_scraped_page(page)
        
        page.success = True
        return page
    
    async def _download_images(self, images: List[ExtractedImage], 
                                referer: str) -> List[str]:
        """Download images from list"""
        downloaded = []
        
        if not HAS_AIOHTTP:
            return downloaded
        
        from shared import SessionManager
        session = await SessionManager.get().session()
        
        for img in images:
            try:
                # Add referer header if not doing so already
                async with session.get(img.url, headers={'Referer': referer}, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        
                        # Generate filename
                        url_hash = hashlib.md5(img.url.encode()).hexdigest()[:12]
                        ext = '.jpg'
                        for e in ['.jpg', '.png', '.gif', '.webp']:
                            if e in img.url.lower():
                                ext = e
                                break
                        
                        filepath = os.path.join(
                            config.paths.images, 
                            f'img_{url_hash}{ext}'
                        )
                        
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(content)
                        
                        downloaded.append(filepath)
                        self.stats['images'] += 1
                        self.stats['bytes'] += len(content)
            
            except Exception as e:
                log_debug(f"Image download failed: {e}")
        
        log_info(f"Downloaded {len(downloaded)} images")
        return downloaded
    
    def _save_text_content(self, page: ScrapedPage, url: str) -> Optional[str]:
        """Save extracted text to file"""
        if not page.text_content:
            return None
        
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
            domain = get_domain(url).replace('.', '_')
            filename = f'{domain}_{url_hash}.txt'
            filepath = os.path.join(config.paths.text, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"URL: {url}\n")
                f.write(f"Scraped: {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n\n")
                
                if page.metadata:
                    f.write(f"TITLE: {page.metadata.title}\n\n")
                    if page.metadata.description:
                        f.write(f"DESCRIPTION: {page.metadata.description}\n\n")
                
                f.write("CONTENT:\n")
                f.write("-" * 40 + "\n\n")
                
                for h in page.text_content.headings:
                    f.write(f"{'#' * h['level']} {h['text']}\n\n")
                
                for p in page.text_content.paragraphs:
                    f.write(f"{p}\n\n")
                
                if page.text_content.emails:
                    f.write("\nEMAILS:\n")
                    for email in page.text_content.emails:
                        f.write(f"  - {email}\n")
                
                if page.text_content.phones:
                    f.write("\nPHONES:\n")
                    for phone in page.text_content.phones:
                        f.write(f"  - {phone}\n")
            
            log_info(f"Text saved: {filename}")
            return filepath
        
        except Exception as e:
            log_debug(f"Text save failed: {e}")
            return None
    
    # =========================================================================
    # Batch Operations
    # =========================================================================
    
    async def batch_download(self,
                             urls: List[str],
                             audio_only: bool = False,
                             quality: Quality = None,
                             format: str = None) -> List[DownloadResult]:
        """
        Download multiple URLs concurrently.
        
        Args:
            urls: List of URLs
            audio_only: Download audio only
            quality: Quality setting
            format: Output format
        
        Returns:
            List of DownloadResults
        """
        results = []
        
        log_info(f"Batch download: {len(urls)} URLs")
        
        semaphore = asyncio.Semaphore(10)  # Max concurrent downloads
        
        async def _download_single(url: str, idx: int, total: int) -> DownloadResult:
            async with semaphore:
                log_info(f"\nProcessing [{idx}/{total}] {url[:60]}")
                try:
                    if audio_only:
                        return await self.download_audio(url, format=format or 'mp3')
                    else:
                        return await self.download_video(url, quality=quality, format=format or 'mp4')
                except Exception as e:
                    log_error(f"Failed [{idx}/{total}]: {e}")
                    return DownloadResult(
                        url=url,
                        success=False,
                        error=str(e)
                    )

        tasks = [_download_single(url, i, len(urls)) for i, url in enumerate(urls, 1)]
        results = await asyncio.gather(*tasks)
        
        # Summary
        success = sum(1 for r in results if r.success)
        log_info(f"\nBatch complete: {success}/{len(urls)} successful")
        
        return results
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    async def get_metadata(self, url: str) -> Optional[MediaMetadata]:
        """Get media metadata without downloading"""
        return await extract_metadata(url)
    
    async def get_playlist_info(self, url: str) -> Optional[PlaylistInfo]:
        """Get playlist information without downloading"""
        return await extract_playlist(url)
    
    async def extract_streaming_sources(self, url: str) -> List[Dict]:
        """Extract video sources from streaming site"""
        return await extract_streaming_sources(url)
    
    async def download_image(self, url: str,
                             output_dir: str = None,
                             filename: str = None) -> Dict[str, Any]:
        """
        Download image \u2014 delegates to image.py for proper format handling.
        """
        if HAS_IMAGE_MODULE:
            async with ImageDownloader(
                output_dir=output_dir or config.paths.images,
                organize_by_domain=self.organize_by_platform,
            ) as dl:
                result = await dl.download(url, filename=filename)
                
                # Update scraper stats
                if result.success:
                    self.stats['images'] += 1
                    self.stats['bytes'] += result.filesize

                return {
                    'success': result.success,
                    'url': result.url,
                    'filepath': result.filepath,
                    'filename': result.filename,
                    'filesize': result.filesize,
                    'size': result.size_str,
                    'format': result.saved_format,
                    'original_format': result.original_format,
                    'converted': result.was_converted,
                    'width': result.width,
                    'height': result.height,
                    'error': result.error,
                }
        else:
            # Fallback (old behavior \u2014 should not reach here)
            log_warn("image.py not found, using basic download")
            return await self._download_image_basic(url, output_dir, filename)

    async def _download_image_basic(self, url: str,
                                    output_dir: str = None,
                                    filename: str = None) -> Dict[str, Any]:
        """
        Basic fallback download image from URL.
        """
        result = {
            'success': False,
            'url': url,
            'filepath': None,
            'error': None
        }
        
        if not HAS_AIOHTTP:
            result['error'] = 'aiohttp not available'
            return result
        
        out_dir = output_dir or config.paths.images
        
        if self.organize_by_platform:
            platform = detect_platform(url)
            out_dir = os.path.join(out_dir, platform.name.title())
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Determine filename
        if not filename:
            parsed = urlparse(url)
            fname = os.path.basename(parsed.path)
            if not fname or '.' not in fname:
                fname = f"image_{hashlib.md5(url.encode()).hexdigest()[:10]}.jpg"
            filename = sanitize_filename(fname)
        
        filepath = os.path.join(out_dir, filename)
        
        try:
            from shared import SessionManager
            session = await SessionManager.get().session()
            headers = {'User-Agent': config.network.user_agent}
            
            # Helper function for the actual download
            async def _do_download(use_ssl: bool) -> bool:
                async with session.get(url, headers=headers, ssl=use_ssl,
                                       timeout=aiohttp.ClientTimeout(total=config.network.request_timeout)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(content)
                        
                        result['success'] = True
                        result['filepath'] = filepath
                        result['filename'] = filename
                        result['filesize'] = len(content)
                        result['size'] = format_size(len(content))
                        self.stats['images'] += 1
                        self.stats['bytes'] += len(content)
                        
                        # Record in database
                        if self.db:
                            # Fixed download_image crashing on DB insert by passing DownloadResult object
                            dl_record = DownloadResult(
                                url=url,
                                platform=detect_platform(url),
                                media_type=MediaType.IMAGE,
                                title=filename,
                                filepath=filepath,
                                filename=filename,
                                filesize=len(content),
                                success=True,
                            )
                            self.db.add_download(dl_record)
                        
                        log_info(f"Image saved: {filepath} ({result['size']})")
                        return True
                    else:
                        result['error'] = f"HTTP {resp.status}"
                        log_error(f"Image download failed: HTTP {resp.status}")
                        return False
            
            # Try with SSL first
            try:
                success = await _do_download(use_ssl=True)
            except getattr(aiohttp, 'ClientSSLError', Exception):
                # Fallback to without SSL
                log_debug(f"SSL error for {url}, retrying without SSL...")
                success = await _do_download(use_ssl=False)
                
        except Exception as e:
            result['error'] = str(e)
            log_error(f"Image download failed: {e}")
        
        return result
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get current session statistics"""
        elapsed = (datetime.now() - self.stats['started']).total_seconds()
        
        return {
            'videos': self.stats['videos'],
            'audio': self.stats['audio'],
            'images': self.stats['images'],
            'pages': self.stats['pages'],
            'total_bytes': self.stats['bytes'],
            'total_size': format_size(self.stats['bytes']),
            'elapsed_seconds': elapsed,
            'elapsed_formatted': format_duration(elapsed)
        }
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        return self.db.get_stats()
    
    def search(self, query: str) -> Dict[str, List[Dict]]:
        """Search downloads and scraped pages"""
        return self.db.search(query)
    
    def list_downloads(self, media_type: str = None, limit: int = 50) -> List[Dict]:
        """List recent downloads"""
        return self.db.list_downloads(media_type, limit)


# =============================================================================
# Convenience Functions
# =============================================================================

async def download_video(url: str, **kwargs) -> DownloadResult:
    """Quick video download"""
    async with Scraper() as scraper:
        return await scraper.download_video(url, **kwargs)


async def download_audio(url: str, **kwargs) -> DownloadResult:
    """Quick audio download"""
    async with Scraper() as scraper:
        return await scraper.download_audio(url, **kwargs)


async def download_playlist(url: str, **kwargs) -> Dict:
    """Quick playlist download"""
    async with Scraper() as scraper:
        return await scraper.download_playlist(url, **kwargs)


def download_video_sync(url: str, **kwargs) -> DownloadResult:
    """Synchronous video download"""
    return asyncio.run(download_video(url, **kwargs))


def download_audio_sync(url: str, **kwargs) -> DownloadResult:
    """Synchronous audio download"""
    return asyncio.run(download_audio(url, **kwargs))


def download_playlist_sync(url: str, **kwargs) -> Dict:
    """Synchronous playlist download"""
    return asyncio.run(download_playlist(url, **kwargs))


# =============================================================================
# Module Information
# =============================================================================

def print_status() -> None:
    """Print module status and available features"""
    safe_print("")
    safe_print("=" * 70)
    safe_print("          PROFESSIONAL WEB SCRAPER & MEDIA DOWNLOADER")
    safe_print("                         Version 2.0")
    safe_print("=" * 70)
    safe_print("")
    
    safe_print("SAVE PATHS:")
    safe_print(f"  Videos:     {config.paths.videos}")
    safe_print(f"  Audio:      {config.paths.audio}")
    safe_print(f"  Images:     {config.paths.images}")
    safe_print(f"  Text:       {config.paths.text}")
    safe_print("")
    
    safe_print("DEPENDENCIES:")
    safe_print(f"  [{'OK' if HAS_FFMPEG else 'X ':}] FFmpeg: {FFMPEG_VERSION if HAS_FFMPEG else 'Not found'}")
    safe_print(f"  [{'OK' if HAS_FFPROBE else 'X ':}] FFprobe")
    safe_print(f"  [{'OK' if HAS_YTDLP else 'X ':}] yt-dlp: {YTDLP_VERSION if HAS_YTDLP else 'Not found'}")
    safe_print(f"  [{'OK' if HAS_AIOHTTP else 'X ':}] aiohttp")
    safe_print(f"  [{'OK' if HAS_BOT else '- ':}] bot.py (anti-detection)")
    safe_print("")
    
    safe_print("SUPPORTED PLATFORMS:")
    platforms = [
        "YouTube", "Instagram", "TikTok", "X (Twitter)", "Facebook",
        "Reddit", "Vimeo", "Twitch", "Dailymotion", "SoundCloud", "Bilibili"
    ]
    safe_print(f"  {', '.join(platforms)}")
    safe_print("")
    
    safe_print("QUALITY OPTIONS:")
    safe_print("  Video: 144p to 8K@60fps")
    safe_print("  Audio: 64kbps to 320kbps / FLAC")
    safe_print("")
    safe_print("=" * 70)


def get_version() -> str:
    """Get module version"""
    return "2.0.0"



# =============================================================================
# CLI Module (merged from cli.py)
# =============================================================================

# =============================================================================
# CLI Configuration
# =============================================================================

@dataclass
class CLIConfig:
    """CLI-specific configuration"""
    show_banner: bool = True
    colored_output: bool = True
    confirm_downloads: bool = True
    show_progress: bool = True
    default_quality: Quality = Quality.Q_1080_30
    default_audio_quality: AudioQuality = AudioQuality.Q_192
    default_video_format: str = "mp4"
    default_audio_format: str = "mp3"
    auto_embed_thumbnail: bool = True
    auto_embed_metadata: bool = True
    organize_by_platform: bool = True


cli_config = CLIConfig()


# =============================================================================
# CLI Optional Module Imports
# =============================================================================

try:
    from downloaders import VideoDownloader, AudioDownloader, PlaylistDownloader
    HAS_DOWNLOADERS = True
except ImportError:
    HAS_DOWNLOADERS = False
    VideoDownloader = AudioDownloader = PlaylistDownloader = None

# run_scrapling_cli is defined earlier in this same file (line ~1530)
HAS_SCRAPLING_TOOL = HAS_SCRAPLING_FETCHERS

try:
    from namu_ai import run_namu_ai_chat
    HAS_NAMU_AI = True
except ImportError:
    HAS_NAMU_AI = False
    async def run_namu_ai_chat():
        safe_print("\n  [X] Namu AI not available.")

try:
    from namu_ui import run_namu_ui
    HAS_NAMU_UI = True
except ImportError:
    HAS_NAMU_UI = False
    def run_namu_ui():
        safe_print("\n  [X] Namu UI not available.")

try:
    from spiderfoot_tool import run_spiderfoot_cli
    HAS_SPIDERFOOT_TOOL = True
except ImportError:
    HAS_SPIDERFOOT_TOOL = False
    async def run_spiderfoot_cli():
        safe_print("\n  [X] SpiderFoot tool not available.")


# =============================================================================
# Display Helpers
# =============================================================================

class Colors:
    """ANSI color codes (disabled on Windows by default)"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    @classmethod
    def disable(cls):
        """Disable colors"""
        for attr in dir(cls):
            if not attr.startswith('_') and attr.isupper():
                setattr(cls, attr, '')


# Disable colors on Windows unless explicitly supported
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        Colors.disable()


def print_line(char: str = "─", width: int = 70) -> None:
    """Print a horizontal line"""
    safe_print(char * width)


def print_header(title: str, width: int = 70) -> None:
    """Print a section header"""
    safe_print("")
    safe_print("═" * width)
    padding = (width - len(title) - 2) // 2
    safe_print("║" + " " * padding + title + " " * (width - padding - len(title) - 2) + "║")
    safe_print("═" * width)


def print_subheader(title: str, width: int = 70) -> None:
    """Print a subsection header"""
    safe_print("")
    safe_print("─" * width)
    safe_print(f"  {title}")
    safe_print("─" * width)


def print_box(lines: List[str], width: int = 70) -> None:
    """Print text in a box"""
    safe_print("┌" + "─" * (width - 2) + "┐")
    for line in lines:
        # Truncate if too long
        if len(line) > width - 4:
            line = line[:width - 7] + "..."
        padding = width - len(line) - 4
        safe_print(f"│ {line}" + " " * padding + " │")
    safe_print("└" + "─" * (width - 2) + "┘")


def print_key_value(key: str, value: Any, key_width: int = 15) -> None:
    """Print key-value pair"""
    safe_print(f"  {key:<{key_width}}: {value}")


def print_menu_item(number: str, text: str, indent: int = 4) -> None:
    """Print menu item"""
    safe_print(f"{' ' * indent}{number:>3}. {text}")


def print_status_indicator(ok: bool, message: str) -> None:
    """Print status message"""
    status = "[OK]" if ok else "[X]"
    safe_print(f"  {status} {message}")


def clear_screen() -> None:
    """Clear terminal screen"""
    os.system('cls' if sys.platform == 'win32' else 'clear')


def get_input(prompt: str, default: str = None) -> str:
    """Get user input with optional default"""
    try:
        if default:
            result = input(f"{prompt} [{default}]: ").strip()
            return result if result else default
        else:
            return input(f"{prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def get_choice(prompt: str, valid_choices: List[str], default: str = None) -> str:
    """Get validated choice from user"""
    while True:
        choice = get_input(prompt, default)
        if choice in valid_choices or (not choice and default):
            return choice if choice else default
        safe_print(f"Invalid choice. Valid options: {', '.join(valid_choices)}")


def confirm(prompt: str, default: bool = True) -> bool:
    """Get yes/no confirmation"""
    suffix = " [Y/n]" if default else " [y/N]"
    response = get_input(prompt + suffix, "").lower()
    
    if not response:
        return default
    return response in ('y', 'yes', '1', 'true')


# =============================================================================
# Progress Display
# =============================================================================

class ProgressDisplay:
    """Display download progress"""
    
    def __init__(self, title: str = "", total_bytes: int = 0):
        self.title = title
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.speed = 0.0
        self.eta = 0.0
        self.status = "Starting..."
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        self._bar_width = 40
    
    def update(self, downloaded: int, total: int = None, speed: float = None, 
               status: str = None) -> None:
        """Update progress"""
        self.downloaded_bytes = downloaded
        if total:
            self.total_bytes = total
        if speed:
            self.speed = speed
        if status:
            self.status = status
        
        # Calculate ETA
        if self.speed > 0 and self.total_bytes > 0:
            remaining = self.total_bytes - self.downloaded_bytes
            self.eta = remaining / self.speed
        
        self._render()
    
    def _render(self) -> None:
        """Render progress bar"""
        # Calculate percentage
        if self.total_bytes > 0:
            percentage = (self.downloaded_bytes / self.total_bytes) * 100
            filled = int(self._bar_width * self.downloaded_bytes / self.total_bytes)
        else:
            percentage = 0
            filled = 0
        
        # Build progress bar
        bar = "█" * filled + "░" * (self._bar_width - filled)
        
        # Format sizes
        downloaded_str = format_size(self.downloaded_bytes)
        total_str = format_size(self.total_bytes) if self.total_bytes else "???"
        
        # Format speed
        speed_str = f"{format_size(int(self.speed))}/s" if self.speed else "---"
        
        # Format ETA
        if self.eta > 0:
            mins, secs = divmod(int(self.eta), 60)
            eta_str = f"{mins:02d}:{secs:02d}"
        else:
            eta_str = "--:--"
        
        # Build line
        line = f"\r[{bar}] {percentage:5.1f}% | {downloaded_str}/{total_str} | {speed_str} | ETA: {eta_str}"
        
        # Print (overwrite same line)
        sys.stdout.write(line[:79])  # Limit to terminal width
        sys.stdout.flush()
    
    def complete(self, success: bool = True) -> None:
        """Mark as complete"""
        if success:
            sys.stdout.write("\r" + " " * 79 + "\r")  # Clear line
            safe_print(f"[OK] Downloaded: {self.title[:50]}")
        else:
            sys.stdout.write("\n")
            safe_print(f"[X] Failed: {self.title[:50]}")
    
    def error(self, message: str) -> None:
        """Display error"""
        sys.stdout.write("\n")
        safe_print(f"[ERROR] {message}")


# =============================================================================
# Quality Selection
# =============================================================================

def display_quality_menu() -> Quality:
    """Display video quality selection menu"""
    print_subheader("VIDEO QUALITY OPTIONS")
    
    qualities = [
        ("1", Quality.Q_8K_60, "8K (4320p) @ 60fps - Maximum quality"),
        ("2", Quality.Q_8K_30, "8K (4320p) @ 30fps"),
        ("3", Quality.Q_4K_60, "4K (2160p) @ 60fps - Ultra HD"),
        ("4", Quality.Q_4K_30, "4K (2160p) @ 30fps"),
        ("5", Quality.Q_1440_60, "1440p @ 60fps - 2K"),
        ("6", Quality.Q_1440_30, "1440p @ 30fps"),
        ("7", Quality.Q_1080_60, "1080p @ 60fps - Full HD"),
        ("8", Quality.Q_1080_30, "1080p @ 30fps [Recommended]"),
        ("9", Quality.Q_720_60, "720p @ 60fps - HD"),
        ("10", Quality.Q_720_30, "720p @ 30fps"),
        ("11", Quality.Q_480, "480p - SD"),
        ("12", Quality.Q_360, "360p - Low"),
        ("13", Quality.Q_240, "240p - Minimum"),
        ("14", Quality.BEST, "Best Available"),
        ("15", Quality.WORST, "Lowest Available"),
    ]
    
    for num, quality, desc in qualities:
        print_menu_item(num, desc)
    
    safe_print("")
    choice = get_input("Select quality", "8")
    
    for num, quality, _ in qualities:
        if choice == num:
            return quality
    
    return Quality.Q_1080_30


def display_audio_quality_menu() -> AudioQuality:
    """Display audio quality selection menu"""
    print_subheader("AUDIO QUALITY OPTIONS")
    
    qualities = [
        ("1", AudioQuality.Q_320, "320 kbps - Maximum quality"),
        ("2", AudioQuality.Q_256, "256 kbps - High quality"),
        ("3", AudioQuality.Q_192, "192 kbps - Standard [Recommended]"),
        ("4", AudioQuality.Q_128, "128 kbps - Compressed"),
        ("5", AudioQuality.BEST, "Best Available"),
    ]
    
    for num, quality, desc in qualities:
        print_menu_item(num, desc)
    
    safe_print("")
    choice = get_input("Select quality", "3")
    
    for num, quality, _ in qualities:
        if choice == num:
            return quality
    
    return AudioQuality.Q_192


def display_format_menu(media_type: str = "video") -> str:
    """Display format selection menu"""
    if media_type == "video":
        print_subheader("VIDEO FORMAT OPTIONS")
        formats = [
            ("1", "mp4", "MP4 (H.264) - Universal [Recommended]"),
            ("2", "mkv", "MKV - Best container"),
            ("3", "webm", "WebM (VP9) - Web optimized"),
            ("4", "mov", "MOV - Apple devices"),
        ]
        default = "1"
    else:
        print_subheader("AUDIO FORMAT OPTIONS")
        formats = [
            ("1", "mp3", "MP3 - Universal [Recommended]"),
            ("2", "m4a", "M4A/AAC - Apple ecosystem"),
            ("3", "flac", "FLAC - Lossless"),
            ("4", "opus", "Opus - Best quality/size"),
            ("5", "wav", "WAV - Uncompressed"),
        ]
        default = "1"
    
    for num, fmt, desc in formats:
        print_menu_item(num, desc)
    
    safe_print("")
    choice = get_input("Select format", default)
    
    for num, fmt, _ in formats:
        if choice == num:
            return fmt
    
    return formats[0][1]


# =============================================================================
# Media Info Display
# =============================================================================

def display_media_info(metadata: MediaMetadata) -> None:
    """Display media information"""
    print_header("MEDIA INFORMATION")
    
    lines = [
        f"Title: {metadata.title[:60]}",
        f"Platform: {metadata.platform.name}",
        f"Duration: {metadata.duration_str}",
    ]
    
    if metadata.author:
        lines.append(f"Uploader: {metadata.author.name}")
    
    if metadata.view_count:
        lines.append(f"Views: {metadata.view_count:,}")
    
    if metadata.upload_date:
        lines.append(f"Uploaded: {metadata.upload_date.strftime('%Y-%m-%d')}")
    
    print_box(lines)
    
    # Available qualities
    if metadata.video_formats:
        safe_print("\nAvailable Qualities:")
        seen = set()
        for fmt in sorted(metadata.video_formats, 
                         key=lambda f: (f.height or 0, f.fps or 0), reverse=True)[:10]:
            res = fmt.resolution
            if res not in seen:
                seen.add(res)
                size_str = f" ({format_size(fmt.filesize)})" if fmt.filesize else ""
                safe_print(f"  • {res} [{fmt.extension}]{size_str}")


def display_playlist_info(playlist: PlaylistInfo) -> None:
    """Display playlist information"""
    print_header("PLAYLIST INFORMATION")
    
    lines = [
        f"Title: {playlist.title[:55]}",
        f"Platform: {playlist.platform.name}",
        f"Videos: {playlist.video_count}",
    ]
    
    if playlist.author:
        lines.append(f"Creator: {playlist.author.name}")
    
    print_box(lines)
    
    # Show first few items
    if playlist.entries:
        safe_print("\nFirst 5 videos:")
        for i, entry in enumerate(playlist.entries[:5], 1):
            title = entry.title[:50] if entry.title else "Unknown"
            duration = format_duration(entry.duration) if entry.duration else "--:--"
            safe_print(f"  {i:2}. {title} [{duration}]")
        
        if len(playlist.entries) > 5:
            safe_print(f"  ... and {len(playlist.entries) - 5} more")


# =============================================================================
# Download Handlers
# =============================================================================

async def handle_video_download(url: str) -> Optional[DownloadResult]:
    """Handle single video download"""
    log_error("Video download feature has been removed/disabled. Only audio/text/image downloading and scraping are supported.")
    return None


async def handle_audio_download(url: str) -> Optional[DownloadResult]:
    """Handle audio-only download"""
    safe_print("\nFetching audio information...")
    
    # Get metadata
    metadata = await extract_metadata(url)
    
    if not metadata:
        log_error("Could not fetch audio information")
        return None
    
    # Display info
    print_header("AUDIO INFORMATION")
    lines = [
        f"Title: {metadata.title[:60]}",
        f"Platform: {metadata.platform.name}",
        f"Duration: {metadata.duration_str}",
    ]
    if metadata.author:
        lines.append(f"Artist: {metadata.author.name}")
    print_box(lines)
    
    # Get quality
    quality = display_audio_quality_menu()
    safe_print(f"\nSelected: {quality.label}")
    
    # Get format
    fmt = display_format_menu("audio")
    safe_print(f"Format: {fmt.upper()}")
    
    # Confirm
    if cli_config.confirm_downloads:
        if not confirm("\nProceed with download?"):
            safe_print("Download cancelled.")
            return None
    
    # Start download
    safe_print("")
    log_info(f"Downloading: {metadata.title[:50]}")
    
    progress = ProgressDisplay(metadata.title)
    
    try:
        if HAS_DOWNLOADERS:
            async with AudioDownloader() as downloader:
                result = await downloader.download(
                    url,
                    quality=quality,
                    format=fmt,
                    embed_thumbnail=cli_config.auto_embed_thumbnail,
                    embed_metadata=cli_config.auto_embed_metadata,
                    progress_callback=progress.update
                )
        else:
            result = await download_with_ytdlp(
                url,
                metadata=metadata,
                quality=quality,
                format=fmt,
                audio_only=True,
                progress=progress
            )
        
        if result and result.success:
            progress.complete(True)
            safe_print("")
            log_success(f"Saved to: {result.filepath}")
            return result
        else:
            progress.complete(False)
            if result:
                log_error(result.error or "Download failed")
            return result
    
    except KeyboardInterrupt:
        safe_print("\n\nDownload cancelled by user.")
        return None
    except Exception as e:
        progress.error(str(e))
        return None


async def handle_playlist_download(url: str, audio_only: bool = False) -> Dict:
    """Handle playlist download"""
    safe_print("\nFetching playlist information...")
    
    # Get playlist info
    playlist = await extract_playlist(url)
    
    if not playlist:
        log_error("Could not fetch playlist information")
        return {'success': False, 'error': 'Failed to fetch playlist'}
    
    # Display info
    display_playlist_info(playlist)
    
    # Download options
    print_subheader("DOWNLOAD OPTIONS")
    print_menu_item("1", f"Download all ({playlist.video_count} videos)")
    print_menu_item("2", "Download range (e.g., 5-15)")
    print_menu_item("3", "Download specific videos")
    print_menu_item("4", "Skip already downloaded")
    print_menu_item("0", "Cancel")
    
    safe_print("")
    option = get_input("Select option", "1")
    
    if option == "0":
        safe_print("Download cancelled.")
        return {'success': False, 'cancelled': True}
    
    # Determine range
    start_idx = 1
    end_idx = playlist.video_count
    
    if option == "2":
        range_input = get_input("Enter range (e.g., 5-15)", f"1-{playlist.video_count}")
        try:
            parts = range_input.split('-')
            start_idx = int(parts[0])
            end_idx = int(parts[1]) if len(parts) > 1 else playlist.video_count
        except (ValueError, IndexError):
            log_warn("Invalid range, downloading all")
    
    elif option == "3":
        indices_input = get_input("Enter video numbers (comma-separated)", "1")
        # TODO: Handle specific indices
    
    # Quality selection
    if audio_only:
        quality = display_audio_quality_menu()
        fmt = display_format_menu("audio")
        mode = "audio"
    else:
        quality = display_quality_menu()
        fmt = display_format_menu("video")
        mode = "video"
    
    # Confirm
    count = min(end_idx, playlist.video_count) - start_idx + 1
    safe_print(f"\nWill download {count} {mode} files")
    safe_print(f"Quality: {quality.label}")
    safe_print(f"Format: {fmt.upper()}")
    
    if not confirm("\nProceed?"):
        safe_print("Download cancelled.")
        return {'success': False, 'cancelled': True}
    
    # Create output directory
    playlist_dir = os.path.join(
        config.paths.audio if audio_only else config.paths.videos,
        sanitize_filename(playlist.title)
    )
    os.makedirs(playlist_dir, exist_ok=True)
    
    # Start downloads
    print_header("DOWNLOADING PLAYLIST")
    safe_print(f"Saving to: {playlist_dir}\n")
    
    results = {
        'success': True,
        'playlist_title': playlist.title,
        'total': count,
        'downloaded': 0,
        'failed': 0,
        'skipped': 0,
        'total_bytes': 0,
        'items': []
    }
    
    entries = playlist.entries[start_idx-1:end_idx]
    
    for i, entry in enumerate(entries, start=start_idx):
        # Get video URL
        video_id = entry.id
        if playlist.platform == Platform.YOUTUBE_PLAYLIST:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            video_url = entry.url or url
        
        title = entry.title or f"Video {i}"
        safe_print(f"[{i}/{end_idx}] {title[:50]}...")
        
        try:
            # Download
            if HAS_DOWNLOADERS:
                if audio_only:
                    async with AudioDownloader(output_dir=playlist_dir) as dl:
                        result = await dl.download(
                            video_url,
                            quality=quality,
                            format=fmt,
                            filename_prefix=f"{i:03d}. "
                        )
                else:
                    async with VideoDownloader(output_dir=playlist_dir) as dl:
                        result = await dl.download(
                            video_url,
                            quality=quality,
                            format=fmt,
                            filename_prefix=f"{i:03d}. "
                        )
            else:
                # Fallback
                metadata = MediaMetadata(
                    id=video_id, title=title, url=video_url,
                    platform=playlist.platform, media_type=MediaType.VIDEO
                )
                result = await download_with_ytdlp(
                    video_url,
                    metadata=metadata,
                    quality=quality,
                    format=fmt,
                    audio_only=audio_only,
                    output_dir=playlist_dir,
                    filename_prefix=f"{i:03d}. "
                )
            
            if result and result.success:
                results['downloaded'] += 1
                results['total_bytes'] += result.filesize
                results['items'].append({
                    'title': title,
                    'success': True,
                    'path': result.filepath
                })
                safe_print(f"       [OK] {format_size(result.filesize)}")
            else:
                results['failed'] += 1
                results['items'].append({
                    'title': title,
                    'success': False,
                    'error': result.error if result else 'Unknown error'
                })
                safe_print(f"       [FAILED]")
        
        except Exception as e:
            results['failed'] += 1
            results['items'].append({
                'title': title,
                'success': False,
                'error': str(e)
            })
            safe_print(f"       [ERROR] {str(e)[:30]}")
        
        # Small delay between downloads
        await asyncio.sleep(0.5)
    
    # Summary
    print_header("DOWNLOAD COMPLETE")
    safe_print(f"  Playlist: {playlist.title[:50]}")
    safe_print(f"  Downloaded: {results['downloaded']}/{results['total']}")
    safe_print(f"  Failed: {results['failed']}")
    safe_print(f"  Total size: {format_size(results['total_bytes'])}")
    safe_print(f"  Location: {playlist_dir}")
    
    return results


async def handle_batch_download(audio_only: bool = False) -> Dict:
    """Handle batch download of multiple URLs"""
    print_header("BATCH DOWNLOAD")
    safe_print("Enter URLs (one per line, empty line to finish):\n")
    
    urls = []
    while True:
        try:
            url = input().strip()
            if not url:
                break
            if url.startswith('http'):
                urls.append(url)
            else:
                safe_print(f"  [Skip] Invalid URL: {url[:30]}")
        except (EOFError, KeyboardInterrupt):
            break
    
    if not urls:
        safe_print("No URLs provided.")
        return {'success': False}
    
    safe_print(f"\nFound {len(urls)} URLs")
    
    # Quality selection
    if audio_only:
        quality = display_audio_quality_menu()
        fmt = display_format_menu("audio")
    else:
        quality = display_quality_menu()
        fmt = display_format_menu("video")
    
    if not confirm(f"\nDownload {len(urls)} {'audio' if audio_only else 'video'} files?"):
        return {'success': False, 'cancelled': True}
    
    # Process URLs
    results = {
        'success': True,
        'total': len(urls),
        'downloaded': 0,
        'failed': 0,
        'items': []
    }
    
    print_header("DOWNLOADING")
    
    for i, url in enumerate(urls, 1):
        safe_print(f"\n[{i}/{len(urls)}] {url[:50]}...")
        
        try:
            if audio_only:
                result = await handle_audio_download(url)
            else:
                result = await handle_video_download(url)
            
            if result and result.success:
                results['downloaded'] += 1
                results['items'].append({'url': url, 'success': True})
            else:
                results['failed'] += 1
                results['items'].append({'url': url, 'success': False})
        
        except Exception as e:
            results['failed'] += 1
            results['items'].append({'url': url, 'success': False, 'error': str(e)})
            log_error(str(e))
    
    # Summary
    print_header("BATCH COMPLETE")
    safe_print(f"  Downloaded: {results['downloaded']}/{results['total']}")
    safe_print(f"  Failed: {results['failed']}")
    
    return results


# =============================================================================
# yt-dlp Fallback Downloader
# =============================================================================

async def download_with_ytdlp(
    url: str,
    metadata: MediaMetadata,
    quality: Quality,
    format: str,
    audio_only: bool = False,
    output_dir: str = None,
    filename_prefix: str = "",
    progress: ProgressDisplay = None
) -> DownloadResult:
    """Download using yt-dlp directly (fallback)"""
    from utils import run_command_async
    import tempfile
    import shutil
    
    result = DownloadResult(
        url=url,
        title=metadata.title,
        platform=metadata.platform,
        media_type=MediaType.AUDIO if audio_only else MediaType.VIDEO
    )
    
    if not audio_only:
        result.success = False
        result.error = "Video download feature has been removed/disabled"
        return result
    
    if not HAS_YTDLP:
        result.error = "yt-dlp not installed"
        return result
    
    # Determine output directory
    if output_dir:
        out_dir = output_dir
    elif audio_only:
        out_dir = config.paths.audio
    else:
        out_dir = config.paths.videos
    
    # Organize by platform
    if cli_config.organize_by_platform:
        out_dir = os.path.join(out_dir, metadata.platform.name.title())
    
    os.makedirs(out_dir, exist_ok=True)
    
    # Build filename
    safe_title = sanitize_filename(metadata.title)
    filename = f"{filename_prefix}{safe_title}.{format}"
    output_path = os.path.join(out_dir, filename)
    
    # Handle duplicates
    counter = 1
    base_path = output_path
    while os.path.exists(output_path):
        name, ext = os.path.splitext(base_path)
        output_path = f"{name} ({counter}){ext}"
        counter += 1
    
    # Build yt-dlp command
    cmd = ['yt-dlp', '--no-warnings', '--no-playlist']
    
    if audio_only:
        cmd.extend([
            '-f', 'bestaudio[ext=m4a]/bestaudio',
            '-x',
            '--audio-format', format,
            '--audio-quality', '0'
        ])
    else:
        # Build format selector based on quality
        if quality == Quality.BEST:
            fmt_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == Quality.WORST:
            fmt_selector = 'worstvideo+worstaudio/worst'
        else:
            height = quality.height
            fps = quality.fps
            if fps > 30:
                fmt_selector = f'bestvideo[height<={height}][fps>={fps}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]/best'
            else:
                fmt_selector = f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]/best'
        
        cmd.extend(['-f', fmt_selector])
        
        if format == 'mp4':
            cmd.extend(['--merge-output-format', 'mp4'])
        elif format == 'mkv':
            cmd.extend(['--merge-output-format', 'mkv'])
    
    # Add metadata and thumbnail embedding
    if cli_config.auto_embed_thumbnail:
        cmd.append('--embed-thumbnail')
    
    if cli_config.auto_embed_metadata:
        cmd.append('--add-metadata')
    
    # Output template
    cmd.extend(['-o', output_path])
    
    # Add URL
    cmd.append(url)
    
    # Execute
    if progress:
        progress.update(0, status="Starting download...")
    
    ok, out, err = await run_command_async(cmd, timeout=config.network.download_timeout)
    
    if ok and os.path.exists(output_path):
        result.success = True
        result.filepath = output_path
        result.filename = os.path.basename(output_path)
        result.filesize = os.path.getsize(output_path)
        
        # Verify audio
        from utils import check_ffprobe
        if HAS_FFPROBE and not audio_only:
            # Could add audio verification here
            result.has_audio = True
        
        result.thumbnail_embedded = cli_config.auto_embed_thumbnail
        result.metadata_embedded = cli_config.auto_embed_metadata
    else:
        result.error = err[:200] if err else "Download failed"
    
    return result


# =============================================================================
# View/Statistics Handlers
# =============================================================================

def display_statistics() -> None:
    """Display download statistics"""
    print_header("STATISTICS")
    
    if HAS_DATABASE and db:
        stats = db.get_stats()
        
        print_subheader("DATABASE")
        print_key_value("Total downloads", stats.get('total_downloads', 0))
        print_key_value("Videos", stats.get('videos', 0))
        print_key_value("Audio files", stats.get('audio_files', 0))
        print_key_value("With audio", stats.get('videos_with_audio', 0))
        print_key_value("Total size", f"{stats.get('total_size_gb', 0):.2f} GB")
        print_key_value("Playlists", stats.get('playlists', 0))
    
    print_subheader("STORAGE")
    print_key_value("Videos dir", config.paths.videos)
    print_key_value("Audio dir", config.paths.audio)
    print_key_value("Used space", f"{config.paths.get_storage_used_gb():.2f} GB" 
                    if hasattr(config.paths, 'get_storage_used_gb') else "N/A")
    
    print_subheader("SESSION")
    # Would track session stats here
    safe_print("  Session statistics not yet implemented")


def display_download_history(limit: int = 20) -> None:
    """Display recent downloads"""
    print_header("DOWNLOAD HISTORY")
    
    if not HAS_DATABASE or not db:
        safe_print("Database not available.")
        return
    
    history = db.list_media(limit=limit)
    
    if not history:
        safe_print("No downloads found.")
        return
    
    safe_print(f"Recent {len(history)} downloads:\n")
    
    for i, item in enumerate(history, 1):
        title = item.get('title') or item.get('filename', 'Unknown')
        size = format_size(item.get('filesize', 0))
        media_type = item.get('media_type', 'unknown')
        has_audio = "A" if item.get('has_audio') else "_"
        
        safe_print(f"  {i:2}. [{has_audio}] [{media_type[:5]:5}] {title[:40]:40} {size:>10}")


def search_downloads(query: str) -> None:
    """Search download history"""
    print_header(f"SEARCH: {query}")
    
    if not HAS_DATABASE or not db:
        safe_print("Database not available.")
        return
    
    results = db.search(query)
    
    total = len(results.get('media', []))
    safe_print(f"Found {total} results:\n")
    
    for item in results.get('media', [])[:20]:
        title = item.get('title') or item.get('filename', 'Unknown')
        safe_print(f"  • {title[:60]}")


# =============================================================================
# System Handlers
# =============================================================================

def check_dependencies() -> None:
    """Check system dependencies"""
    print_header("DEPENDENCY CHECK")
    
    deps = get_dependencies(refresh=True)
    
    print_subheader("REQUIRED")
    
    # FFmpeg
    ok, ver = deps.get('ffmpeg', (False, ''))
    print_status_indicator(ok, f"FFmpeg: {ver[:50] if ver else 'Not found'}")
    if not ok:
        safe_print("       Install: https://ffmpeg.org/download.html")
    
    # FFprobe
    ok, _ = deps.get('ffprobe', (False, ''))
    print_status_indicator(ok, "FFprobe: " + ("Available" if ok else "Not found"))
    
    # yt-dlp
    ok, ver = deps.get('yt-dlp', (False, ''))
    print_status_indicator(ok, f"yt-dlp: {ver if ver else 'Not found'}")
    if not ok:
        safe_print("       Install: pip install yt-dlp")
    
    print_subheader("PYTHON PACKAGES")
    
    packages = ['aiohttp', 'aiofiles', 'bs4', 'requests', 'PIL']
    for pkg in packages:
        ok, _ = deps.get(pkg, (False, ''))
        print_status_indicator(ok, pkg)
    
    print_subheader("OPTIONAL MODULES")
    
    print_status_indicator(HAS_DATABASE, "Database module")
    print_status_indicator(HAS_DOWNLOADERS, "Downloaders module")
    print_status_indicator(HAS_BOT, "Bot module (anti-detection)")


def display_settings() -> None:
    """Display current settings"""
    print_header("CURRENT SETTINGS")
    
    print_subheader("PATHS")
    print_key_value("Videos", config.paths.videos, 20)
    print_key_value("Audio", config.paths.audio, 20)
    print_key_value("Images", config.paths.images, 20)
    print_key_value("Text", config.paths.text, 20)
    
    print_subheader("DEFAULTS")
    print_key_value("Video quality", cli_config.default_quality.label, 20)
    print_key_value("Audio quality", cli_config.default_audio_quality.label, 20)
    print_key_value("Video format", cli_config.default_video_format, 20)
    print_key_value("Audio format", cli_config.default_audio_format, 20)
    
    print_subheader("OPTIONS")
    print_key_value("Embed thumbnail", cli_config.auto_embed_thumbnail, 20)
    print_key_value("Embed metadata", cli_config.auto_embed_metadata, 20)
    print_key_value("Organize by platform", cli_config.organize_by_platform, 20)
    print_key_value("Confirm downloads", cli_config.confirm_downloads, 20)
    
    print_subheader("BOT MODULE")
    print_key_value("Enabled", config.bot.enabled, 20)
    print_key_value("Available", HAS_BOT, 20)


def update_ytdlp() -> None:
    """Update yt-dlp"""
    print_header("UPDATE YT-DLP")
    
    safe_print("Updating yt-dlp...")
    
    from utils import run_command
    ok, out, err = run_command(['pip', 'install', '-U', 'yt-dlp'], timeout=120)
    
    if ok:
        log_success("yt-dlp updated successfully!")
        # Refresh version
        ok, ver = check_ytdlp()
        if ok:
            safe_print(f"New version: {ver}")
    else:
        log_error(f"Update failed: {err[:100] if err else 'Unknown error'}")


def clear_temp_files() -> None:
    """Clear temporary files"""
    print_header("CLEAR TEMP FILES")
    
    count = cleanup_temp_files(max_age_hours=1)
    
    if count > 0:
        log_success(f"Removed {count} temporary files")
    else:
        safe_print("No temporary files to remove")


def verify_file() -> None:
    """Verify a downloaded file"""
    print_header("VERIFY FILE")
    
    filepath = get_input("Enter file path").strip('"\'')
    
    if not filepath or not os.path.exists(filepath):
        log_error("File not found")
        return
    
    safe_print("\nAnalyzing file...\n")
    
    # Get file info
    from utils import get_file_size
    
    print_key_value("Path", filepath, 15)
    print_key_value("Size", format_size(get_file_size(filepath)), 15)
    
    # Check with ffprobe if available
    if HAS_FFPROBE:
        from utils import run_command
        import json
        
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', filepath]
        ok, out, _ = run_command(cmd, 30)
        
        if ok and out:
            try:
                start = out.find('{')
                if start != -1:
                    data = json.loads(out[start:])
                    
                    fmt = data.get('format', {})
                    print_key_value("Duration", format_duration(float(fmt.get('duration', 0))), 15)
                    print_key_value("Bitrate", f"{int(fmt.get('bit_rate', 0)) // 1000} kbps", 15)
                    
                    has_video = False
                    has_audio = False
                    
                    for stream in data.get('streams', []):
                        codec_type = stream.get('codec_type', '')
                        if codec_type == 'video':
                            has_video = True
                            print_key_value("Video", f"{stream.get('width')}x{stream.get('height')}", 15)
                            print_key_value("Video codec", stream.get('codec_name'), 15)
                        elif codec_type == 'audio':
                            has_audio = True
                            print_key_value("Audio codec", stream.get('codec_name'), 15)
                            print_key_value("Channels", stream.get('channels'), 15)
                    
                    safe_print("")
                    print_status_indicator(has_video, "Has video")
                    print_status_indicator(has_audio, "Has audio")
            
            except (json.JSONDecodeError, KeyError):
                log_error("Could not parse file info")
    else:
        log_warn("FFprobe not available for detailed analysis")


# =============================================================================
# Main Menu
# =============================================================================

def display_banner() -> None:
    """Display application banner"""
    clear_screen()
    safe_print(f"""
{'='*66}
{'PERSONAL SCRAPER':^66}
{'Professional Edition':^66}
{'='*66}
  Platforms: YouTube, Instagram, X, Facebook, Reddit, TikTok
  OSINT Tools | EXIF Tool | SpiderFoot
  Quality: Up to 8K@60fps | Audio: Up to 320kbps/FLAC
{'='*66}
""")


def display_main_menu() -> None:
    """Display main menu"""
    safe_print("""
MAIN MENU:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DOWNLOAD:
    1.  Download Video
    2.  Download Audio Only
    3.  Download Image
    4.  Download Thumbnail
    
  TOOLS:
    5.  OSINT
    6.  EXIF / Metadata
    7.  Web Scraping           [Scrapling]
    8.  View Download History
    9.  Search Downloads
   10.  View Statistics
   11.  Resume Failed Downloads
    
  SYSTEM:
   12.  Check Dependencies
   13.  Verify Directories
   14.  Clear Temp Files
   15.  Update yt-dlp

  AI:
   16.  Namu AI Agent           (AI Chatbot — Ask Anything)

  OSINT AUTOMATION:
   17.  SpiderFoot              (200+ Module OSINT Scanner)
    
    0.  Exit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


async def handle_menu_choice(choice: str) -> bool:
    """Handle menu choice, return False to exit"""
    
    if choice == "0":
        safe_print("\nGoodbye!")
        return False
    
    elif choice == "1":
        url = get_input("\nEnter video URL")
        if url:
            await handle_video_download(url)
    
    elif choice == "2":
        url = get_input("\nEnter URL")
        if url:
            await handle_audio_download(url)
    
    elif choice == "3":
        # Image download
        url = get_input("\nEnter image URL (or page URL to extract images)")
        if url:
            from scraper import Scraper
            async with Scraper() as s:
                result = await s.download_image(url)
            if result.get('success'):
                safe_print(f"\n  [OK] Image saved: {result['filepath']} ({result['size']})")
            else:
                safe_print(f"\n  [X] Failed: {result.get('error')}")
    
    elif choice == "4":
        url = get_input("\nEnter video URL to download its thumbnail")
        if url:
            safe_print("\nFetching thumbnail...")
            from extractors import extract_metadata
            metadata = await extract_metadata(url)
            if metadata and metadata.best_thumbnail:
                from scraper import Scraper
                async with Scraper() as s:
                    result = await s.download_image(
                        metadata.best_thumbnail.url,
                        output_dir=config.paths.thumbnails
                    )
                if result.get('success'):
                    safe_print(f"  [OK] Thumbnail saved: {result['filepath']}")
                else:
                    safe_print(f"  [X] Failed: {result.get('error')}")
            else:
                safe_print("  [X] Could not find thumbnail for this URL")
    
    elif choice == "5":
        # OSINT sub-CLI
        try:
            from osint_cli import run_osint_cli
            await run_osint_cli()
            display_banner()
        except ImportError:
            safe_print("\n  [X] OSINT module not available")
    
    elif choice == "6":
        # EXIF Tool
        try:
            from exif_tool import EXIFExtractor
            exif = EXIFExtractor()
            safe_print("\n  EXIF / METADATA EXTRACTION:")
            safe_print("    1. Extract from local file")
            safe_print("    2. Extract from URL")
            sub = get_input("  Select", "1")
            if sub == "1":
                path = get_input("  Enter file path")
                if path and os.path.exists(path):
                    result = exif.extract(path)
                    safe_print(exif.display(result))
                    fp = exif.save_report(result)
                    safe_print(f"  [OK] Report saved: {fp}")
                else:
                    safe_print("  File not found")
            elif sub == "2":
                url = get_input("  Enter image/video URL")
                if url:
                    safe_print("  Downloading...")
                    result = await exif.extract_from_url(url)
                    safe_print(exif.display(result))
                    fp = exif.save_report(result)
                    safe_print(f"  [OK] Report saved: {fp}")
        except ImportError:
            safe_print("\n  [X] EXIF tool needs Pillow: pip install Pillow")
    
    elif choice == "7":
        # Web Scraping [Scrapling]
        if HAS_SCRAPLING_TOOL:
            await run_scrapling_cli()
            display_banner()
        else:
            safe_print("\n  [X] Scrapling tool not available.")
            safe_print("      Install: pip install \"scrapling[all]\"")
            safe_print("      Then:    scrapling install")
    
    elif choice == "8":
        display_download_history()
    
    elif choice == "9":
        query = get_input("\nSearch query")
        if query:
            search_downloads(query)
    
    elif choice == "10":
        display_statistics()
    
    elif choice == "11":
        verify_file()
    
    elif choice == "12":
        check_dependencies()
    
    elif choice == "13":
        safe_print("\nChecking directories...")
        config.paths.init_all()
        safe_print(f"  Videos:     {config.paths.videos}")
        safe_print(f"  Audio:      {config.paths.audio}")
        safe_print(f"  Images:     {config.paths.images}")
        safe_print(f"  OSINT:      {config.paths.osint}")
        safe_print(f"  Thumbnails: {config.paths.thumbnails}")
        safe_print("  [OK] All directories verified")
    
    elif choice == "14":
        clear_temp_files()
    
    elif choice == "15":
        update_ytdlp()
    
    elif choice == "16":
        # Namu AI Agent — Sub-menu: UI or CLI
        if not HAS_NAMU_AI and not HAS_NAMU_UI:
            safe_print("\n  [X] Namu AI Agent not available.")
            safe_print("      Ensure namu_ai.py is present and aiohttp is installed.")
            safe_print("      Install: pip install aiohttp")
        else:
            safe_print("""
  NAMU AI AGENT:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1.  🌐 Web UI    (Opens in Browser)
    2.  ⌨️  CLI Chat   (Terminal Mode)
    0.  ◀  Back
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
            sub = get_input("  Select mode").strip()
            if sub == "1":
                if HAS_NAMU_UI:
                    run_namu_ui()
                    display_banner()
                else:
                    safe_print("\n  [X] Web UI module not available.")
                    safe_print("      Ensure namu_ui.py is present.")
            elif sub == "2":
                if HAS_NAMU_AI:
                    await run_namu_ai_chat()
                    display_banner()
                else:
                    safe_print("\n  [X] CLI Chat not available.")
                    safe_print("      Ensure namu_ai.py is present.")
    
    elif choice == "17":
        # SpiderFoot OSINT Automation
        if HAS_SPIDERFOOT_TOOL:
            await run_spiderfoot_cli()
            display_banner()
        else:
            safe_print("\n  [X] SpiderFoot tool not available.")
            safe_print("      Ensure spiderfoot_tool.py is present.")

    else:
        safe_print("Invalid choice")
    
    return True


# =============================================================================
# Quick Download Mode (Direct URL argument)
# =============================================================================

async def quick_download(url: str, audio_only: bool = False) -> None:
    """Quick download from command line argument"""
    platform = detect_platform(url)
    
    safe_print(f"\nDetected platform: {platform.name}")
    
    # Check if playlist
    if platform == Platform.YOUTUBE_PLAYLIST:
        if confirm("Download entire playlist?"):
            await handle_playlist_download(url, audio_only=audio_only)
        else:
            safe_print("Cancelled")
        return
    
    # Single download
    if audio_only:
        await handle_audio_download(url)
    else:
        await handle_video_download(url)


# =============================================================================
# CLI Entry Point
# =============================================================================

class CLI:
    """Main CLI class"""
    
    def __init__(self):
        self.running = True
        
        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, self._handle_interrupt)
    
    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signal"""
        safe_print("\n\nInterrupted. Cleaning up...")
        self.running = False
        sys.exit(0)
    
    async def run(self) -> None:
        """Run the CLI"""
        # Show banner
        if cli_config.show_banner:
            display_banner()
        
        # Check essentials
        if not HAS_YTDLP:
            log_error("yt-dlp not found! Please install: pip install yt-dlp")
            safe_print("")
        
        if not HAS_FFMPEG:
            log_warn("FFmpeg not found! Some features may not work.")
            safe_print("Install from: https://ffmpeg.org/download.html\n")
        
        # Main loop
        while self.running:
            display_main_menu()
            
            try:
                choice = get_input("Enter choice")
                
                if not await handle_menu_choice(choice):
                    break
                
                # Pause before showing menu again
                if choice != "0":
                    safe_print("")
                    get_input("Press Enter to continue...")
            
            except KeyboardInterrupt:
                safe_print("\n")
                continue
            except Exception as e:
                log_error(f"Error: {e}")
                log_debug(f"Exception: {e}")
    
    def run_sync(self) -> None:
        """Synchronous wrapper for run()"""
        asyncio.run(self.run())


def cli_main():
    """Main CLI entry point (merged from cli.py)"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Professional Media Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                           # Interactive mode
  python cli.py URL                       # Quick download video
  python cli.py URL --audio               # Quick download audio
  python cli.py URL --quality 1080p       # Specify quality
  python cli.py --batch urls.txt          # Batch download from file
        """
    )
    
    parser.add_argument('url', nargs='?', help='URL to download')
    parser.add_argument('-a', '--audio', action='store_true', 
                        help='Download audio only')
    parser.add_argument('-q', '--quality', default='1080p',
                        help='Video quality (e.g., 1080p, 4k, best)')
    parser.add_argument('-f', '--format', default='mp4',
                        help='Output format (mp4, mkv, mp3, etc.)')
    parser.add_argument('--batch', metavar='FILE',
                        help='Batch download from file')
    parser.add_argument('--no-banner', action='store_true',
                        help='Hide banner')
    parser.add_argument('--no-confirm', action='store_true',
                        help='Skip confirmation prompts')
    
    args = parser.parse_args()
    
    # Apply arguments
    if args.no_banner:
        cli_config.show_banner = False
    
    if args.no_confirm:
        cli_config.confirm_downloads = False
    
    # Handle quick download
    if args.url:
        display_banner() if cli_config.show_banner else None
        asyncio.run(quick_download(args.url, audio_only=args.audio))
        return
    
    # Handle batch file
    if args.batch:
        display_banner() if cli_config.show_banner else None
        if os.path.exists(args.batch):
            with open(args.batch, 'r') as f:
                urls = [line.strip() for line in f if line.strip().startswith('http')]
            safe_print(f"Found {len(urls)} URLs in {args.batch}")
            # TODO: Process batch
        else:
            log_error(f"File not found: {args.batch}")
        return
    
    # Interactive mode
    cli = CLI()
    cli.run_sync()


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Professional Web Scraper & Media Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                        # Interactive mode (uses cli.py)
  python scraper.py URL                    # Download video
  python scraper.py URL --audio            # Download audio only
  python scraper.py URL --quality 4k       # Specify quality
  python scraper.py URL --playlist         # Download as playlist
  python scraper.py --status               # Show module status
        """
    )
    
    parser.add_argument('url', nargs='?', help='URL to download')
    parser.add_argument('-a', '--audio', action='store_true', help='Download audio only')
    parser.add_argument('-q', '--quality', default='1080p', help='Video quality')
    parser.add_argument('-f', '--format', help='Output format')
    parser.add_argument('-o', '--output', help='Output directory')
    parser.add_argument('--playlist', action='store_true', help='Download as playlist')
    parser.add_argument('--start', type=int, default=1, help='Playlist start index')
    parser.add_argument('--end', type=int, help='Playlist end index')
    parser.add_argument('--status', action='store_true', help='Show status')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    
    args = parser.parse_args()
    
    # Show status
    if args.status:
        print_status()
        return
    
    # Show statistics
    if args.stats:
        print_status()
        safe_print("\nDATABASE STATISTICS:")
        stats = db.get_stats()
        for key, value in stats.items():
            safe_print(f"  {key}: {value}")
        return
    
    # No URL provided - launch CLI
    if not args.url:
        cli_main()
        return
    
    # URL provided - direct download
    print_status()
    
    # Parse quality
    quality_map = {
        '8k60': Quality.Q_8K_60, '8k': Quality.Q_8K_30,
        '4k60': Quality.Q_4K_60, '4k': Quality.Q_4K_30,
        '1440p60': Quality.Q_1440_60, '1440p': Quality.Q_1440_30,
        '1080p60': Quality.Q_1080_60, '1080p': Quality.Q_1080_30,
        '720p60': Quality.Q_720_60, '720p': Quality.Q_720_30,
        '480p': Quality.Q_480, '360p': Quality.Q_360,
        'best': Quality.BEST, 'worst': Quality.WORST
    }
    quality = quality_map.get(args.quality.lower(), Quality.Q_1080_30)
    
    async def run():
        async with Scraper() as scraper:
            if args.playlist:
                result = await scraper.download_playlist(
                    args.url,
                    audio_only=args.audio,
                    quality=quality,
                    format=args.format,
                    start=args.start,
                    end=args.end,
                    output_dir=args.output
                )
                return result['success']
            elif args.audio:
                result = await scraper.download_audio(
                    args.url,
                    format=args.format or 'mp3',
                    output_dir=args.output
                )
                return result.success
            else:
                result = await scraper.download_video(
                    args.url,
                    quality=quality,
                    format=args.format or 'mp4',
                    output_dir=args.output
                )
                return result.success
    
    try:
        success = asyncio.run(run())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        safe_print("\n\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()