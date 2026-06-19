"""
================================================================================
NAMU_AI.PY - Namu AI Personal Research Agent
================================================================================
Version: 2.0
Last Updated: 2026-05

AI-powered personal research agent (like Perplexity) with real tool execution.
Searches the web, scrapes websites, runs OSINT, downloads media, and presents
rich cited answers.

MODELS:
  Primary:  NVIDIA GLM4.7 (reasoning + thinking)
  Fallback: OpenRouter free models (Gemma 4, Nemotron 3)

CAPABILITIES:
  - Perplexity-style search-first research with source citations
  - Natural language task execution (scraping, OSINT, downloads)
  - Multi-tool chaining and sub-agent task planning
  - HTML report generation with dark UI
  - Self-improvement AI (SIAI) for code self-modification
  - 65+ integrated tools across 8 categories

================================================================================
"""

import os
import sys
import json
import re
import asyncio
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, urljoin

from config import config
from utils import (
    safe_print, log_info, log_warn, log_error, log_success, log_debug,
    sanitize_filename, format_size, detect_platform
)

# =============================================================================
# Optional Imports (graceful degradation)
# =============================================================================

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual .env loader fallback
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(_env_path):
        with open(_env_path, 'r') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

try:
    import windows_tools
    HAS_WINDOWS_TOOLS = True
except ImportError:
    HAS_WINDOWS_TOOLS = False

try:
    from openai import OpenAI as _OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# ---------------------------------------------------------------------------
# NVIDIA GLM4.7 Client (OpenAI-compatible)
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
_REASONING_COLOR = "\033[90m" if _USE_COLOR else ""
_RESET_COLOR = "\033[0m" if _USE_COLOR else ""

_nvidia_client = None
if HAS_OPENAI:
    _nvidia_api_key = os.environ.get("NVIDIA_API_KEY", "") or os.environ.get("NVIDIA_API_kEY", "")
    if _nvidia_api_key:
        _nvidia_client = _OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=_nvidia_api_key,
        )

# NVIDIA model constant — used for routing
NVIDIA_GLM_MODEL_ID = "nvidia/glm4.7"

# =============================================================================
# Paths
# =============================================================================

AI_DATA_DIR = os.path.join(config.paths.base_dir, "ai_data")
AI_REPORTS_DIR = os.path.join(config.paths.base_dir, "ai_reports")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "namu_report.html")
os.makedirs(AI_DATA_DIR, exist_ok=True)
os.makedirs(AI_REPORTS_DIR, exist_ok=True)

# =============================================================================
# SIAI — Self-Improvement AI System (Sandboxed)
# =============================================================================

_SCRAPER_ROOT = os.path.dirname(os.path.abspath(__file__))

SIAI_ALLOWED_FILES: Dict[str, str] = {
    "namu_ai.py":        os.path.join(_SCRAPER_ROOT, "namu_ai.py"),
    "namu_report.html":  os.path.join(_SCRAPER_ROOT, "templates", "namu_report.html"),
    "namu_ui.html":      os.path.join(_SCRAPER_ROOT, "templates", "namu_ui.html"),
    "SIAI.md":           os.path.join(_SCRAPER_ROOT, "SIAI.md"),
}

SIAI_LOG_FILE  = SIAI_ALLOWED_FILES["SIAI.md"]
SIAI_BACKUP_DIR = os.path.join(_SCRAPER_ROOT, "siai_backups")
SIAI_MAX_FILE_SIZE = 512_000          # 500 KB per write
SIAI_MAX_PATCH_SIZE = 8_000           # 8 KB per patch find/replace block
SIAI_PY_ONLY_PATCH = True             # .py files: patch-only, no full rewrite
os.makedirs(SIAI_BACKUP_DIR, exist_ok=True)


# =============================================================================
# HTML Template Loader & Builder
# =============================================================================

def _load_template() -> str:
    """Load the HTML report template from file."""
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    log_warn(f"Template not found: {TEMPLATE_FILE}")
    # Minimal fallback
    return """<!DOCTYPE html><html><head><meta charset='UTF-8'>
<title>{{TITLE}}</title>
<style>body{font-family:sans-serif;background:#141414;color:#d4d4d4;padding:40px;max-width:960px;margin:auto}
.section{background:#222;border-radius:8px;padding:20px;margin:16px 0;border-left:3px solid #e8651a}
h1{color:#e0e0e0}h2{color:#ccc;font-size:16px}a{color:#ff8642}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #333;text-align:left}
th{color:#e8651a}pre{background:#1a1a1a;padding:12px;border-radius:4px;overflow:auto}
.footer{margin-top:30px;padding-top:12px;border-top:1px solid #333;font-size:11px;color:#555;text-align:center}
</style></head><body><h1>{{TITLE}}</h1><p style='color:#888'>{{TIMESTAMP}} | {{TOPIC}}</p>
{{CONTENT}}<div class='footer'>Namu AI Agent — {{TIMESTAMP}}</div></body></html>"""


def _esc(text: str) -> str:
    """Escape HTML special chars for safe attribute/text insertion."""
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _is_image_url(url: str) -> bool:
    """Check if URL points to an image."""
    img_ext = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico')
    clean = url.split('?')[0].lower()
    return any(clean.endswith(e) for e in img_ext) or 'image' in url.lower()


def _is_video_url(url: str) -> bool:
    """Check if URL points to a video."""
    vid_ext = ('.mp4', '.webm', '.ogg', '.mov', '.avi')
    clean = url.split('?')[0].lower()
    return any(clean.endswith(e) for e in vid_ext)


def _render_media(url: str, alt: str = '') -> str:
    """Render an image or video with proper container."""
    if _is_video_url(url):
        return (f'<div class="media-container">'
                f'<video src="{_esc(url)}" controls preload="metadata"'
                f' style="width:100%"></video>'
                f'{"<div class=" + chr(34) + "media-caption" + chr(34) + ">" + _esc(alt) + "</div>" if alt else ""}'
                f'</div>')
    else:
        return (f'<div class="media-container">'
                f'<img src="{_esc(url)}" alt="{_esc(alt)}" loading="lazy"'
                f' onerror="this.parentElement.style.display=\'none\'">'
                f'{"<div class=" + chr(34) + "media-caption" + chr(34) + ">" + _esc(alt) + "</div>" if alt else ""}'
                f'</div>')


def _build_stats(stats: Dict[str, Any]) -> str:
    """Build animated stat cards grid."""
    if not stats:
        return ''
    cards = []
    for label, value in stats.items():
        display_val = f'{value:,}' if isinstance(value, int) else str(value)
        display_label = str(label).replace('_', ' ').title()
        cards.append(f'<div class="stat-card"><div class="value">{_esc(display_val)}</div>'
                     f'<div class="label">{_esc(display_label)}</div></div>')
    return f'<div class="stats-grid">{chr(10).join(cards)}</div>'


def _build_kv_table(data: Dict[str, Any]) -> str:
    """Build a key-value table (README style)."""
    rows = []
    for k, v in data.items():
        key_display = str(k).replace('_', ' ').title()
        if isinstance(v, bool):
            val = '✅ Yes' if v else '❌ No'
        elif isinstance(v, str) and v.startswith('http'):
            if _is_image_url(v):
                val = f'<a href="{_esc(v)}" target="_blank"><img src="{_esc(v)}" alt="" style="max-height:60px;border-radius:4px"></a>'
            else:
                short = v[:70] + ('...' if len(v) > 70 else '')
                val = f'<a href="{_esc(v)}" target="_blank">{_esc(short)}</a>'
        elif isinstance(v, (list, dict)):
            val = f'<code>{_esc(str(v)[:200])}</code>'
        else:
            val = _esc(str(v)[:500])
        rows.append(f'<tr><td class="key">{_esc(key_display)}</td><td>{val}</td></tr>')
    return f'<table><thead><tr><th>Property</th><th>Value</th></tr></thead><tbody>{chr(10).join(rows)}</tbody></table>'


def _build_link_list(links: list) -> str:
    """Build a styled link list."""
    items = []
    for link in links[:60]:
        if isinstance(link, dict):
            url = link.get('url', link.get('link', link.get('href', '#')))
            text = link.get('text', link.get('title', ''))
            if not text or text == url:
                text = url[:80]
            items.append(f'<li><span class="dot"></span>'
                        f'<div><a href="{_esc(url)}" target="_blank">{_esc(str(text)[:80])}</a>'
                        f'<div class="link-meta">{_esc(str(url)[:100])}</div></div></li>')
        else:
            url = str(link)
            items.append(f'<li><span class="dot"></span>'
                        f'<a href="{_esc(url)}" target="_blank">{_esc(url[:100])}</a></li>')
    return f'<ul class="link-list">{chr(10).join(items)}</ul>'


def _build_gallery(images: list) -> str:
    """Build an image gallery grid."""
    cards = []
    for img in images[:30]:
        if isinstance(img, dict):
            src = img.get('url', img.get('src', ''))
            alt = img.get('alt', img.get('title', ''))
        else:
            src = str(img)
            alt = ''
        if src and _is_image_url(src):
            caption = alt or src.split('/')[-1][:40]
            cards.append(f'<div class="gallery-item">'
                        f'<img src="{_esc(src)}" alt="{_esc(alt)}" loading="lazy"'
                        f' onerror="this.parentElement.style.display=\'none\'">'
                        f'<div class="caption">{_esc(caption)}</div></div>')
    if not cards:
        return ''
    return f'<div class="gallery">{chr(10).join(cards)}</div>'


def _build_collapsible(title: str, content: str, badge: str = '', open_default: bool = True) -> str:
    """Build a collapsible section block."""
    badge_html = f'<span class="badge">{_esc(badge)}</span>' if badge else ''
    open_attr = ' open' if open_default else ''
    return (f'<details class="section-block"{open_attr}>'
            f'<summary>{_esc(title)}{badge_html}</summary>'
            f'<div class="section-content">{content}</div></details>')


def _build_code_block(code: str, lang: str = '') -> str:
    """Build a styled code block with header and copy button."""
    lang_display = lang or 'text'
    return (f'<pre><div class="code-header"><span class="lang-tag">{_esc(lang_display)}</span>'
            f'<button class="copy-btn" onclick="navigator.clipboard.writeText(this.closest(\'pre\').querySelector(\'code\').textContent).then(()=>{{this.textContent=\'Copied!\';setTimeout(()=>this.textContent=\'Copy\',1500)}})">Copy</button></div>'
            f'<code>{_esc(code)}</code></pre>')


def _detect_content_type(text: str) -> str:
    """Detect if text content is HTML, code, or plain text."""
    stripped = text.strip()
    if stripped.startswith('<') and ('>' in stripped[:50]):
        return 'html'
    if any(kw in stripped[:200] for kw in ('def ', 'import ', 'class ', 'function ', 'const ', 'var ', 'let ')):
        return 'code'
    return 'text'


def build_html_from_data(title: str, data: Any, topic: str = '',
                         subtitle: str = '', tags: list = None) -> str:
    """
    Build a complete HTML report from data using the external template.
    Renders content properly — images display inline, HTML is rendered,
    code has syntax blocks, links are clickable, data is structured.
    """
    template = _load_template()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    topic = topic or sanitize_filename(title)[:40]

    # Build tags
    tags_html = ''
    if tags:
        tags_html = ' '.join(f'<span class="tag">{_esc(t)}</span>' for t in tags)

    stats_html = ''
    stats = {}
    content_parts = []

    if isinstance(data, dict):
        # --- Extract numeric stats for dashboard ---
        for k, v in data.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                stats[k] = v
        if stats:
            stats_html = _build_stats(stats)

        # --- Process each data key into README-style sections ---
        for key, value in data.items():
            nice_key = str(key).replace('_', ' ').title()

            # Skip stats already shown
            if key in stats and len(str(value)) < 20:
                continue

            # Skip internal keys
            if key in ('success', 'error') and isinstance(value, bool):
                continue

            # -- URL value: show as link or media --
            if isinstance(value, str) and value.startswith('http'):
                if _is_image_url(value):
                    content_parts.append(f'<h3>{_esc(nice_key)}</h3>')
                    content_parts.append(_render_media(value, nice_key))
                elif _is_video_url(value):
                    content_parts.append(f'<h3>{_esc(nice_key)}</h3>')
                    content_parts.append(_render_media(value, nice_key))
                else:
                    content_parts.append(f'<p><strong>{_esc(nice_key)}:</strong> '
                                        f'<a href="{_esc(value)}" target="_blank">{_esc(value)}</a></p>')
                continue

            # -- Dict value: render as table --
            if isinstance(value, dict):
                content_parts.append(
                    _build_collapsible(nice_key, _build_kv_table(value), f'{len(value)} fields')
                )
                continue

            # -- List value: smart rendering --
            if isinstance(value, list):
                if not value:
                    continue
                first = value[0] if value else None

                # List of image URLs or image dicts
                if isinstance(first, str) and _is_image_url(first):
                    inner = _build_gallery(value)
                elif isinstance(first, dict) and any(k in first for k in ('url', 'src')):
                    # Could be links or images
                    sample_url = first.get('url', first.get('src', ''))
                    if _is_image_url(sample_url):
                        inner = _build_gallery(value)
                    else:
                        inner = _build_link_list(value)
                elif isinstance(first, str) and first.startswith('http'):
                    inner = _build_link_list(value)
                elif isinstance(first, dict):
                    # List of dicts — render as tables
                    tables = []
                    for i, item in enumerate(value[:20]):
                        tables.append(f'<h4>#{i+1}</h4>' + _build_kv_table(item))
                    inner = chr(10).join(tables)
                else:
                    inner = '<ul>' + chr(10).join(
                        f'<li>{_esc(str(item)[:200])}</li>' for item in value[:50]
                    ) + '</ul>'

                content_parts.append(
                    _build_collapsible(nice_key, inner, f'{len(value)} items')
                )
                continue

            # -- Long text: detect type --
            if isinstance(value, str) and len(value) > 200:
                ct = _detect_content_type(value)
                if ct == 'html':
                    # Render HTML directly!
                    content_parts.append(f'<h2>{_esc(nice_key)}</h2>')
                    content_parts.append(value)
                elif ct == 'code':
                    content_parts.append(f'<h2>{_esc(nice_key)}</h2>')
                    content_parts.append(_build_code_block(value))
                else:
                    # Plain text: wrap in paragraphs
                    paragraphs = value.split('\n\n')
                    content_parts.append(f'<h2>{_esc(nice_key)}</h2>')
                    for p in paragraphs[:30]:
                        stripped = p.strip()
                        if stripped:
                            content_parts.append(f'<p>{_esc(stripped)}</p>')
                continue

            # -- Bool --
            if isinstance(value, bool):
                icon = '✅' if value else '❌'
                content_parts.append(f'<p><strong>{_esc(nice_key)}:</strong> {icon}</p>')
                continue

            # -- Default: short text --
            content_parts.append(f'<p><strong>{_esc(nice_key)}:</strong> {_esc(str(value)[:2000])}</p>')

    elif isinstance(data, list):
        first = data[0] if data else None
        if isinstance(first, dict) and any(k in first for k in ('url', 'link', 'src')):
            content_parts.append(_build_link_list(data))
        elif isinstance(first, dict):
            for i, item in enumerate(data[:20]):
                content_parts.append(f'<h3>#{i+1}</h3>' + _build_kv_table(item))
        else:
            content_parts.append('<ul>' + chr(10).join(
                f'<li>{_esc(str(item)[:200])}</li>' for item in data[:50]
            ) + '</ul>')

    elif isinstance(data, str):
        ct = _detect_content_type(data)
        if ct == 'html':
            # Direct HTML rendering — this is the key fix!
            content_parts.append(data)
        elif ct == 'code':
            content_parts.append(_build_code_block(data))
        else:
            paragraphs = data.split('\n\n')
            for p in paragraphs[:40]:
                stripped = p.strip()
                if stripped:
                    content_parts.append(f'<p>{_esc(stripped)}</p>')
    else:
        content_parts.append(_build_code_block(str(data)[:5000]))

    # --- Fill template ---
    html = template
    html = html.replace('{{TITLE}}', _esc(title))
    html = html.replace('{{TIMESTAMP}}', timestamp)
    html = html.replace('{{TOPIC}}', _esc(topic))
    html = html.replace('{{SUBTITLE}}', _esc(subtitle or 'Generated by Namu AI Agent'))
    html = html.replace('{{TAGS}}', tags_html)
    html = html.replace('{{STATS_SECTION}}', stats_html)
    html = html.replace('{{CONTENT}}', chr(10).join(content_parts))

    return html


TOOL_DEFINITIONS = """
Available tools you can call (return JSON with "tool" and "args" keys):

SCRAPING:
- web_scrape: Scrape a webpage. Args: {"url": "..."}
- stealth_scrape: Anti-bot scrape (Cloudflare bypass). Args: {"url": "..."}
- dynamic_scrape: Full browser JS scrape. Args: {"url": "..."}
- extract_links: Get all links from page. Args: {"url": "..."}
- extract_images: Get all images from page. Args: {"url": "..."}
- page_to_text: Convert page to text. Args: {"url": "...", "format": "txt|md"}
- css_extract: Extract elements by CSS selector. Args: {"url": "...", "selector": "..."}
- spider_crawl: Crawl multiple pages. Args: {"url": "...", "selector": "...", "max_pages": 5}
- batch_scrape: Scrape multiple URLs. Args: {"urls": ["...", "..."]}

DOWNLOADS:
- download_video: [DISABLED] Video downloading is disabled/removed.
- download_audio: Download audio from URL. Args: {"url": "...", "format": "mp3"}
- download_image: Download image from URL. Args: {"url": "..."}
- download_playlist: Download playlist. Args: {"url": "...", "audio_only": true} (audio_only must be true; video playlist downloads are disabled)
- download_thumbnail: Download video thumbnail. Args: {"url": "..."}

OSINT:
- osint_domain: Domain recon (DNS, SSL, subdomains). Args: {"domain": "..."}
- osint_ip: IP lookup (geo, reverse DNS). Args: {"ip": "..."}
- osint_email: Email intelligence. Args: {"email": "..."}
- osint_username: Username search (35+ platforms). Args: {"username": "..."}
- osint_phone: Phone number OSINT. Args: {"phone": "..."}
- numverify_lookup: NumVerify phone validation — carrier, location, line type, validation. Fast direct lookup. Args: {"phone": "+1234567890"}
- osint_full_recon: Full auto-recon on any target. Args: {"target": "..."}
- google_dorks: Generate Google dork queries. Args: {"domain": "..."}
- ai_dork_search: AI dork scanner with live search. Args: {"target": "...", "type": "all|security|social|leaks"}

SEARCH & ANALYSIS:
- web_search: Search the web (Serper/SearXNG). Args: {"query": "..."}
- encode_decode: Encode/decode text (base64, hex, md5, etc). Args: {"text": "..."}
- exif_extract: Extract EXIF metadata from file. Args: {"path": "..."}
- exif_from_url: Extract EXIF from image URL. Args: {"url": "..."}

FILE READING:
- read_user_file: Read ANY file from the user's filesystem (JSON, TXT, CSV, MD, LOG, etc). USE THIS when the user asks you to read, summarize, analyze, or view a file from their computer. Args: {"path": "C:/path/to/file.json"}
  IMPORTANT: This is NOT the same as siai_read_file. Use THIS for user files. Use siai_read_file ONLY for your own code files.

SPIDERFOOT (OSINT Automation — 200+ modules):
- spiderfoot_scan: Start a SpiderFoot OSINT scan. Args: {"target": "...", "scan_type": "ALL|FOOTPRINT|INVESTIGATE|PASSIVE"}
- spiderfoot_results: Get results of a SpiderFoot scan. Args: {"scan_id": "..."}
- spiderfoot_status: Check SpiderFoot server status and running scans. Args: {}
- spiderfoot_modules: List available SpiderFoot modules. Args: {}

HISTORY & STATS:
- download_history: View recent downloads. Args: {"limit": 20}
- search_downloads: Search download history. Args: {"query": "..."}
- view_statistics: View download stats (total count, size, etc). Args: {}
- resume_failed: List/resume failed downloads. Args: {}

HTML & DATA:
- create_html: Create a rich HTML page/report from data. USE THIS when the user wants HTML, UI, webpage, report, or visual output. Args: {"title": "...", "data": {...}, "tags": ["tag1", "tag2"]}
- save_html: Save raw data as a basic HTML report. Args: {"title": "...", "data": {...}}
- save_json: Save data as JSON file. Args: {"filename": "...", "data": {...}}

WINDOWS / OS ACTIONS:
- open_file: Open a file with default or specific app. Args: {"path": "...", "app": "vscode"} (app is optional)
- open_folder: Open a folder in Windows Explorer. Args: {"path": "..."}
- open_url: Open a URL in the default browser. Args: {"url": "...", "browser": "chrome"} (browser is optional)
- launch_app: Launch an application. Args: {"app": "vscode", "args": ["..."]}
- open_recent: Get and optionally open the most recent file from a directory. Args: {"directory": "ai_reports|ai_data|path", "extension": ".html", "open": true, "app": ""}
- search_files: Search for files by name in a directory. Args: {"directory": "...", "query": "...", "extensions": [".html", ".json"]}

SYSTEM:
- check_dependencies: Check installed tools (ffmpeg, yt-dlp, packages). Args: {}
- verify_directories: Verify/create storage directories. Args: {}
- clear_temp: Clear temporary files. Args: {}
- update_ytdlp: Update yt-dlp to latest version. Args: {}

SELF-IMPROVEMENT (SIAI):
You have sandboxed read/write access to your own code for self-improvement.
Allowed files: namu_ai.py, namu_report.html, namu_ui.html, SIAI.md
WORKFLOW: ALWAYS follow this order: outline → search → targeted read → patch → log
- siai_outline: Get the structure map of a file (classes, functions, sections with line numbers). USE THIS FIRST before reading. Args: {"file": "namu_ai.py"}
- siai_search: Search for a pattern. Use to find exact line numbers before reading/patching. Args: {"query": "...", "file": "namu_ai.py"}  (file optional)
- siai_read_file: Read a SPECIFIC line range (REQUIRED for .py files). Args: {"file": "namu_ai.py", "start_line": 100, "end_line": 150}  NEVER read without a line range for large files.
- siai_patch_file: Targeted find-and-replace edit. Creates backup. Args: {"file": "namu_ai.py", "find": "old code", "replace": "new code", "description": "what and why", "start_line": 100, "end_line": 200}  (start_line/end_line optional — use to scope when find text appears multiple times)
- siai_insert_code: Insert new code at a specific line number. Args: {"file": "namu_ai.py", "after_line": 150, "code": "new code here", "description": "what and why"}  (inserts AFTER the specified line)
- siai_write_file: Full rewrite (HTML/MD only — blocked for .py). Args: {"file": "namu_report.html", "content": "...", "description": "what and why"}
- siai_rollback: Restore from most recent backup. Args: {"file": "namu_ai.py"}
- siai_diff: Diff current vs latest backup. Args: {"file": "namu_ai.py"}
- siai_log: Log improvement to SIAI.md. Args: {"section": "...", "description": "...", "changes": "..."}
- siai_list_files: List allowed files with sizes. Args: {}
- siai_status: Health, backups, recent logs. Args: {}
- siai_hot_reload: Reload namu_ai module after patching so changes take effect immediately without restart. Args: {}
- siai_test: Run a smoke test on SIAI system — syntax check, import test, tool count, health report. Args: {"tool": "web_scrape"}  (tool optional — tests a specific tool handler exists)
- siai_goals: Manage improvement goals. Args: {"action": "list|add|complete|remove", "goal": "...", "priority": "high|medium|low"}
- siai_checkpoint: Create or restore a named version checkpoint. Args: {"action": "save|restore|list", "name": "v1.2-added-search", "file": "namu_ai.py"}
- siai_metrics: Analyze code metrics — line count, tool count, function count, complexity trends. Args: {"file": "namu_ai.py"}  (file optional — analyzes all if omitted)

MULTI-TOOL & PLANNING:
You can call MULTIPLE tools in a single response by returning multiple JSON blocks:
```json
{"tool": "web_scrape", "args": {"url": "..."}}
```
```json
{"tool": "create_html", "args": {"title": "...", "data": "USE_PREVIOUS_RESULT"}}
```
Use "USE_PREVIOUS_RESULT" in data/args to reference the output of the previous tool.

For COMPLEX tasks requiring many steps, create a plan:
```json
{"tool": "task_plan", "args": {"task": "...", "steps": [
  {"step": 1, "tool": "web_scrape", "args": {"url": "..."}, "description": "Scrape the target page"},
  {"step": 2, "tool": "create_html", "args": {"title": "..."}, "description": "Create HTML report from scraped data"},
  {"step": 3, "tool": "open_file", "args": {}, "description": "Open the generated report"}
]}}
```
"""

SYSTEM_PROMPT_TEMPLATE = """You are Namu — a personal AI research agent, like Perplexity but with real tool execution power. You don't just answer questions — you search the web, scrape websites, run OSINT reconnaissance, download media, and present rich, cited answers.

CURRENT DATE AND TIME: {current_datetime}
TIMEZONE: {timezone}

═══════════════════════════════════════════════════════════════════
CORE IDENTITY: PERPLEXITY-STYLE RESEARCH AGENT
═══════════════════════════════════════════════════════════════════

SEARCH-FIRST BEHAVIOR:
1. For ANY factual, current, or knowledge question — ALWAYS use web_search FIRST. Never rely on training data for facts, news, stats, prices, people, events, or anything time-sensitive.
2. After getting search results, synthesize a clear, structured answer with SOURCE CITATIONS:
   - Use [1], [2], [3] inline citations referencing the search result URLs
   - List sources at the end as "Sources: [1] title - url"
3. If the user asks about a website/URL, SCRAPE it first, then answer based on actual scraped content.
4. For OSINT queries (domain, IP, email, username, phone), use the appropriate OSINT tool — don't just search the web.

RESPONSE FORMAT:
- Lead with a direct, clear answer (no filler or "I'll help you with that")
- Use bullet points for structured data
- Use bold **key terms** for scannability
- Include source citations [1][2] when data comes from tools
- End with relevant follow-up suggestions when appropriate
- Keep responses focused and information-dense

TOOL EXECUTION RULES:
5. Format tool calls as: ```json\\n{{"tool": "tool_name", "args": {{"key": "value"}}}}\\n```
6. You CAN call MULTIPLE tools in ONE response — include multiple ```json blocks. They execute sequentially.
7. If the next tool needs data from the previous tool, use "USE_PREVIOUS_RESULT" as the value.
8. For COMPLEX multi-step tasks, use the task_plan tool to create a step-by-step execution plan.
9. Extract URLs, domains, emails, IPs, usernames from the user's message automatically.
10. NEVER make up data. Only report what tools actually return.
11. After ANY save/create, tell the user the full file path.
12. The current year is {current_year}. Include the year in search queries for fresh results.

AUTO-ACTION PATTERNS — when the user says these, act immediately:
- "search/find/look up [topic]" → web_search
- "search/find/summarize/what is [domain.com/URL]" → web_scrape (if it is a website, scrape it directly)
- "scrape/extract/crawl X" → web_scrape (or stealth_scrape for protected sites)
- "download X" → download_audio/download_image based on context (video downloads are disabled)
- "OSINT/recon/investigate X" → osint_domain/email/username/full_recon
- "who is / what is / tell me about X" → web_search first, then answer with citations
- "open/launch/show X" → open_file/open_url/launch_app
- "save/export X" → save_json or create_html
- "report on X" → scrape/search → create_html → open_file
- "read file X" → read_user_file (for user files on disk)

SELF-IMPROVEMENT (SIAI):
- You can read/modify your own code (namu_ai.py, namu_report.html, namu_ui.html, SIAI.md)
- Workflow: siai_outline → siai_search → siai_read_file (30-80 lines) → siai_patch_file → siai_log
- Never read more than 100 lines at once. Never do full rewrites of .py files.
- Always create backups. Always log changes.

EXAMPLE — Research question (Perplexity-style):
User: "What is Scrapling?"
Response:
```json
{{"tool": "web_search", "args": {{"query": "Scrapling Python web scraping library 2026"}}}}
```
(Then after results: synthesize answer with [1][2] citations and source list)

EXAMPLE — Multi-tool chain:
User: "scrape github.com/D4Vinci/Scrapling and create html report and open it"
Response:
```json
{{"tool": "web_scrape", "args": {{"url": "https://github.com/D4Vinci/Scrapling"}}}}
```
```json
{{"tool": "create_html", "args": {{"title": "Scrapling", "data": "USE_PREVIOUS_RESULT", "tags": ["GitHub", "Scraping"]}}}}
```
```json
{{"tool": "open_file", "args": {{"path": "USE_PREVIOUS_RESULT.filepath"}}}}
```

EXAMPLE — OSINT task plan:
User: "full recon on example.com, save everything and make a report"
Response:
```json
{{"tool": "task_plan", "args": {{"task": "Full recon on example.com", "steps": [
  {{"step": 1, "tool": "osint_domain", "args": {{"domain": "example.com"}}, "description": "Domain reconnaissance"}},
  {{"step": 2, "tool": "save_json", "args": {{"filename": "example_com_recon"}}, "description": "Save raw data"}},
  {{"step": 3, "tool": "create_html", "args": {{"title": "Example.com Recon Report", "tags": ["OSINT"]}}, "description": "Generate HTML report"}},
  {{"step": 4, "tool": "open_file", "args": {{}}, "description": "Open report"}}
]}}}}
```

""" + TOOL_DEFINITIONS


def _build_system_prompt() -> str:
    """Build the system prompt with current date/time injected."""
    now = datetime.now()
    # Use .replace() instead of .format() because TOOL_DEFINITIONS contains
    # raw JSON braces like {"url": "..."} which .format() misinterprets as
    # named placeholders, causing KeyError: '"url"'.
    prompt = SYSTEM_PROMPT_TEMPLATE
    prompt = prompt.replace('{current_datetime}', now.strftime('%Y-%m-%d %H:%M:%S'))
    prompt = prompt.replace('{timezone}', str(now.astimezone().tzinfo or 'local'))
    prompt = prompt.replace('{current_year}', str(now.year))
    return prompt


# =============================================================================
# Tool Executor
# =============================================================================

class ToolExecutor:
    """Executes tools by name with given arguments."""

    def __init__(self):
        self._scraper = None
        self._osint_engine = None
        self._exif = None
        self._last_result = None

    async def _get_scraper(self):
        if self._scraper is None:
            try:
                from scraper import Scraper
                self._scraper = Scraper()
                await self._scraper.__aenter__()
            except Exception as e:
                log_debug(f"Scraper init error: {e}")
                self._scraper = None
        return self._scraper

    async def _get_osint(self):
        if self._osint_engine is None:
            try:
                from osint import OSINTEngine
                self._osint_engine = OSINTEngine()
            except Exception as e:
                log_debug(f"OSINT init error: {e}")
                self._osint_engine = None
        return self._osint_engine

    async def cleanup(self):
        if self._scraper:
            try:
                await self._scraper.__aexit__(None, None, None)
            except Exception:
                pass
            self._scraper = None
        if self._osint_engine:
            try:
                await self._osint_engine.close()
            except Exception:
                pass
            self._osint_engine = None

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return results."""
        handler = getattr(self, f'_tool_{tool_name}', None)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        try:
            result = await handler(args)
            self._last_result = result
            return result
        except Exception as e:
            log_debug(f"Tool {tool_name} error: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    # ---- Scraping Tools ----

    async def _tool_web_scrape(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}

        # Try scrapling first
        try:
            from scraper import Fetcher, HAS_SCRAPLING_FETCHERS
            if HAS_SCRAPLING_FETCHERS:
                page = Fetcher.get(url, stealthy_headers=True)
                title = page.css('title::text').get() or ''
                body_text = page.css('body').css('::text').getall() if page.css('body') else []
                text = ' '.join(t.strip() for t in body_text if t.strip())
                links = page.css('a::attr(href)').getall()
                abs_links = list(dict.fromkeys(
                    urljoin(url, l) for l in links
                    if l and not l.startswith(('#', 'javascript:', 'mailto:'))
                ))
                images = [urljoin(url, i) for i in page.css('img::attr(src)').getall() if i]
                return {
                    "success": True, "url": url, "title": title,
                    "word_count": len(text.split()), "text_preview": text[:1000],
                    "links_count": len(abs_links), "links": abs_links[:30],
                    "images_count": len(images), "images": images[:20],
                    "message": f"Scraped '{title[:50]}' — {len(text.split())} words, {len(abs_links)} links, {len(images)} images",
                }
        except Exception as scrapling_err:
            safe_print(f"  [WARN] Scrapling failed: {scrapling_err}, falling back to aiohttp...")

        # Fallback: use aiohttp with SSL disabled
        try:
            import aiohttp, ssl as ssl_mod
            from html.parser import HTMLParser

            class SimpleHTMLParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.title = ''
                    self.text_parts = []
                    self.links = []
                    self.images = []
                    self._in_title = False
                    self._skip_tags = {'script', 'style', 'noscript'}
                    self._skip_depth = 0

                def handle_starttag(self, tag, attrs):
                    attrs_dict = dict(attrs)
                    if tag == 'title': self._in_title = True
                    if tag in self._skip_tags: self._skip_depth += 1
                    if tag == 'a' and 'href' in attrs_dict: self.links.append(attrs_dict['href'])
                    if tag == 'img' and 'src' in attrs_dict: self.images.append(attrs_dict['src'])

                def handle_endtag(self, tag):
                    if tag == 'title': self._in_title = False
                    if tag in self._skip_tags: self._skip_depth = max(0, self._skip_depth - 1)

                def handle_data(self, data):
                    if self._in_title: self.title += data
                    elif self._skip_depth == 0:
                        stripped = data.strip()
                        if stripped: self.text_parts.append(stripped)

            ssl_ctx = ssl_mod.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl_mod.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    html = await resp.text()

            parser = SimpleHTMLParser()
            parser.feed(html)
            text = ' '.join(parser.text_parts)
            abs_links = list(dict.fromkeys(
                urljoin(url, l) for l in parser.links
                if l and not l.startswith(('#', 'javascript:', 'mailto:'))
            ))
            images = [urljoin(url, i) for i in parser.images if i]

            t = parser.title.strip()
            return {
                "success": True, "url": url, "title": t,
                "word_count": len(text.split()), "text_preview": text[:1500],
                "links_count": len(abs_links), "links": abs_links[:30],
                "images_count": len(images), "images": images[:20],
                "note": "Fetched via aiohttp (SSL bypass)",
                "message": f"Scraped '{t[:50]}' — {len(text.split())} words, {len(abs_links)} links",
            }
        except Exception as e:
            return {"success": False, "error": f"All fetch methods failed: {e}"}

    async def _tool_stealth_scrape(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import StealthyFetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = StealthyFetcher.fetch(url, headless=True, network_idle=True, solve_cloudflare=True)
            title = page.css('title::text').get() or ''
            body_text = page.css('body').css('::text').getall() if page.css('body') else []
            text = ' '.join(t.strip() for t in body_text if t.strip())
            links = [urljoin(url, l) for l in page.css('a::attr(href)').getall() if l]

            return {
                "success": True, "url": url, "title": title,
                "word_count": len(text.split()),
                "text_preview": text[:1000],
                "links_count": len(links),
                "links": links[:30],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_dynamic_scrape(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import DynamicFetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = DynamicFetcher.fetch(url, headless=True, network_idle=True)
            title = page.css('title::text').get() or ''
            body_text = page.css('body').css('::text').getall() if page.css('body') else []
            text = ' '.join(t.strip() for t in body_text if t.strip())

            return {
                "success": True, "url": url, "title": title,
                "word_count": len(text.split()),
                "text_preview": text[:1000],
                "links_count": len(page.css('a::attr(href)').getall()),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_extract_links(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import Fetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = Fetcher.get(url, stealthy_headers=True)
            links = page.css('a')
            result_links = []
            for a in links:
                href = a.attrib.get('href', '')
                if href and not href.startswith(('#', 'javascript:')):
                    text = a.css('::text').get() or ''
                    result_links.append({
                        "url": urljoin(url, href),
                        "text": text.strip()[:80]
                    })

            # Deduplicate
            seen = set()
            unique = []
            for l in result_links:
                if l['url'] not in seen:
                    seen.add(l['url'])
                    unique.append(l)

            return {"success": True, "url": url, "total": len(unique), "links": unique[:50]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_extract_images(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import Fetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = Fetcher.get(url, stealthy_headers=True)
            images = []
            for img in page.css('img'):
                src = img.attrib.get('src', '')
                if src:
                    images.append({
                        "url": urljoin(url, src),
                        "alt": img.attrib.get('alt', '')[:80],
                    })

            return {"success": True, "url": url, "total": len(images), "images": images[:50]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_page_to_text(self, args: Dict) -> Dict:
        url = args.get('url', '')
        fmt = args.get('format', 'txt')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import Fetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = Fetcher.get(url, stealthy_headers=True)
            body = page.css('body')
            if not body:
                return {"success": False, "error": "No body content"}

            all_text = body.css('::text').getall()
            clean_text = '\n'.join(t.strip() for t in all_text if t.strip())

            if fmt == 'md':
                title = page.css('title::text').get() or 'Untitled'
                content = f"# {title}\n\n**Source:** {url}\n\n---\n\n"
                for p in page.css('p'):
                    p_text = ' '.join(t.strip() for t in p.css('::text').getall() if t.strip())
                    if p_text:
                        content += f"{p_text}\n\n"
            else:
                content = clean_text

            return {
                "success": True, "url": url, "format": fmt,
                "char_count": len(content),
                "content": content[:3000],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_css_extract(self, args: Dict) -> Dict:
        url = args.get('url', '')
        selector = args.get('selector', '')
        if not url or not selector:
            return {"success": False, "error": "URL and selector required"}
        try:
            from scraper import Fetcher, HAS_SCRAPLING_FETCHERS
            if not HAS_SCRAPLING_FETCHERS:
                return {"success": False, "error": "Scrapling not installed"}

            page = Fetcher.get(url, stealthy_headers=True)
            results = page.css(selector).getall()
            return {
                "success": True, "url": url, "selector": selector,
                "count": len(results),
                "results": [str(r)[:200] for r in results[:30]]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_spider_crawl(self, args: Dict) -> Dict:
        url = args.get('url', '')
        selector = args.get('selector', '*')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from scraper import Spider, Request, Response, HAS_SCRAPLING_SPIDERS
            if not HAS_SCRAPLING_SPIDERS:
                return {"success": False, "error": "Scrapling spiders not installed"}

            max_pages = min(int(args.get('max_pages', 5)), 10)
            _sel = selector
            _crawl_dir = os.path.join(AI_DATA_DIR, f"crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

            class AgentSpider(Spider):
                name = "namu_spider"
                start_urls = [url]
                concurrent_requests = 3

                async def parse(self, response: Response):
                    for el in response.css(_sel):
                        text = el.css('::text').getall()
                        item = {'text': ' '.join(t.strip() for t in text if t.strip())}
                        links = el.css('a::attr(href)').getall()
                        if links:
                            item['links'] = links
                        if item.get('text'):
                            yield item

            result = AgentSpider(crawldir=_crawl_dir).start()
            items = list(result.items)[:50] if result and hasattr(result, 'items') else []
            return {"success": True, "url": url, "items_found": len(items), "items": items[:20]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_batch_scrape(self, args: Dict) -> Dict:
        urls = args.get('urls', [])
        if not urls:
            return {"success": False, "error": "URLs list required"}

        results = []
        for url in urls[:10]:  # Max 10
            r = await self._tool_web_scrape({"url": url})
            results.append({"url": url, "success": r.get("success", False),
                          "title": r.get("title", ""), "word_count": r.get("word_count", 0)})
        return {"success": True, "total": len(results), "results": results}

    # ---- Download Tools ----

    async def _tool_download_video(self, args: Dict) -> Dict:
        return {"success": False, "error": "Video download feature has been removed/disabled."}

    async def _tool_download_audio(self, args: Dict) -> Dict:
        url = args.get('url', '')
        fmt = args.get('format', 'mp3')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            scraper = await self._get_scraper()
            if not scraper:
                return {"success": False, "error": "Scraper not available"}
            result = await scraper.download_audio(url, format=fmt)
            fsize = format_size(result.filesize) if result.filesize else "N/A"
            return {
                "success": result.success,
                "title": result.title, "filepath": result.filepath,
                "filesize": fsize,
                "error": result.error,
                "message": f"Downloaded audio '{result.title[:50]}' ({fsize}) → {result.filepath}" if result.success else result.error,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_download_image(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            scraper = await self._get_scraper()
            if not scraper:
                return {"success": False, "error": "Scraper not available"}
            result = await scraper.download_image(url)
            if result.get('success') and not result.get('message'):
                result['message'] = f"Image saved: {result.get('filepath', '?')} ({result.get('size', '?')})"
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_download_playlist(self, args: Dict) -> Dict:
        url = args.get('url', '')
        audio_only = args.get('audio_only', False)
        if not url:
            return {"success": False, "error": "URL required"}
        if not audio_only:
            return {"success": False, "error": "Video download feature has been removed/disabled. Only audio playlist downloads are supported."}
        try:
            scraper = await self._get_scraper()
            if not scraper:
                return {"success": False, "error": "Scraper not available"}
            result = await scraper.download_playlist(url, audio_only=audio_only)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- OSINT Tools ----

    async def _tool_osint_domain(self, args: Dict) -> Dict:
        domain = args.get('domain', '')
        if not domain:
            return {"success": False, "error": "Domain required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.domain_recon(domain)
        d = result.data
        parts = [f"Domain: {domain}"]
        if d.get('dns_a'): parts.append(f"IPs: {', '.join(d['dns_a'][:3])}")
        if d.get('server'): parts.append(f"Server: {d['server']}")
        if d.get('subdomain_count'): parts.append(f"Subdomains: {d['subdomain_count']}")
        if d.get('technologies'): parts.append(f"Tech: {', '.join(d['technologies'][:5])}")
        return {"success": result.success, "error": result.error, "data": d, "message": ' | '.join(parts), "summary": result.summary()[:2000]}

    async def _tool_osint_ip(self, args: Dict) -> Dict:
        ip = args.get('ip', '')
        if not ip:
            return {"success": False, "error": "IP required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.ip_osint(ip)
        d = result.data
        parts = [f"IP: {ip}"]
        geo = d.get('geolocation', {})
        if geo: parts.append(f"{geo.get('city', '?')}, {geo.get('country', '?')} | ISP: {geo.get('isp', '?')}")
        if d.get('reverse_dns'): parts.append(f"rDNS: {d['reverse_dns']}")
        return {"success": result.success, "error": result.error, "data": d, "message": ' | '.join(parts), "summary": result.summary()[:2000]}

    async def _tool_osint_email(self, args: Dict) -> Dict:
        email = args.get('email', '')
        if not email:
            return {"success": False, "error": "Email required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.email_osint(email)
        d = result.data
        parts = [f"Email: {email}", f"Provider: {d.get('email_provider', '?')}"]
        profiles = d.get('verified_profiles', {})
        if profiles:
            parts.append(f"Found on {len(profiles)} platforms: {', '.join(list(profiles.keys())[:8])}")
        else:
            parts.append(f"Checked {d.get('platforms_checked', 0)} platforms, none found")
        if d.get('has_gravatar'): parts.append("Has Gravatar")
        rep = d.get('email_reputation', {})
        if rep: parts.append(f"Reputation: {rep.get('reputation', '?')}")
        gh = d.get('github_profile', {})
        if gh: parts.append(f"GitHub: {gh.get('username', '?')} ({gh.get('public_repos', 0)} repos, {gh.get('followers', 0)} followers)")
        return {"success": result.success, "error": result.error, "data": d, "message": ' | '.join(parts), "summary": result.summary()[:2000]}

    async def _tool_osint_username(self, args: Dict) -> Dict:
        username = args.get('username', '')
        if not username:
            return {"success": False, "error": "Username required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.username_osint(username, check_live=True)
        d = result.data
        found = d.get('found_profiles', {})
        checked = d.get('checked_count', 0)
        parts = [f"Username: {username}"]
        if found:
            parts.append(f"Found on {len(found)}/{checked} platforms: {', '.join(list(found.keys())[:10])}")
        else:
            parts.append(f"Not found on any of {checked} platforms checked")
        # Include diagnostics if available
        diag = d.get('check_diagnostics', {})
        if diag:
            timeouts = diag.get('timeouts', 0)
            blocked = diag.get('blocked', 0)
            if timeouts: parts.append(f"{timeouts} timed out")
            if blocked: parts.append(f"{blocked} blocked/rate-limited")
        return {"success": result.success, "error": result.error, "data": d, "message": ' | '.join(parts), "summary": result.summary()[:2000]}

    async def _tool_osint_phone(self, args: Dict) -> Dict:
        phone = args.get('phone', '')
        if not phone:
            return {"success": False, "error": "Phone required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.phone_osint(phone)
        d = result.data
        parts = [f"Phone: {phone}"]
        if d.get('country'): parts.append(f"Country: {d['country']}")
        if d.get('country_code'): parts.append(f"Code: {d['country_code']}")
        parts.append(f"Digits: {d.get('digits', '?')}")
        return {"success": result.success, "error": result.error, "data": d, "message": ' | '.join(parts), "summary": result.summary()[:2000]}

    async def _tool_numverify_lookup(self, args: Dict) -> Dict:
        """Direct NumVerify API lookup for phone validation, carrier, location, line type."""
        phone = args.get('phone', '')
        if not phone:
            return {"success": False, "error": "Phone number required. Use international format e.g. +14158586273"}

        import re
        clean = re.sub(r'[^\d+]', '', phone)
        if len(clean) < 7:
            return {"success": False, "error": "Phone number too short. Use international format e.g. +14158586273"}

        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}

        nv = await engine._api_numverify(clean)
        if not nv:
            api_key = os.environ.get('NUMVERIFY_API_KEY', '')
            if not api_key:
                return {"success": False, "error": "NumVerify API key not configured. Set NUMVERIFY_API_KEY in .env"}
            return {"success": False, "error": "NumVerify API returned no data. Check API key or quota."}

        # Build rich response
        valid = nv.get('valid', False)
        parts = [f"Phone: {phone}"]
        parts.append(f"Valid: {'Yes' if valid else 'No'}")
        if nv.get('carrier'): parts.append(f"Carrier: {nv['carrier']}")
        if nv.get('line_type'): parts.append(f"Type: {nv['line_type']}")
        if nv.get('country_name'): parts.append(f"Country: {nv['country_name']}")
        if nv.get('location'): parts.append(f"Location: {nv['location']}")

        return {
            "success": True,
            "phone": phone,
            "valid": valid,
            "international_format": nv.get('international_format', ''),
            "local_format": nv.get('local_format', ''),
            "country": nv.get('country_name', ''),
            "country_code": nv.get('country_code', ''),
            "country_prefix": nv.get('country_prefix', ''),
            "location": nv.get('location', ''),
            "carrier": nv.get('carrier', ''),
            "line_type": nv.get('line_type', ''),
            "message": ' | '.join(parts),
        }

    async def _tool_osint_full_recon(self, args: Dict) -> Dict:
        target = args.get('target', '')
        if not target:
            return {"success": False, "error": "Target required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        results = await engine.full_recon(target)
        combined = {}
        summaries = []
        for name, result in results.items():
            combined[name] = result.data  # Pass ACTUAL data, not just keys
            if result.success:
                summaries.append(f"{name}: {len(result.data)} fields")
            else:
                summaries.append(f"{name}: FAILED - {result.error}")
        msg = f"Full recon on '{target}' — {len(results)} modules: {', '.join(summaries)}"
        return {"success": True, "modules_run": len(results), "data": combined, "message": msg}

    async def _tool_google_dorks(self, args: Dict) -> Dict:
        domain = args.get('domain', '')
        if not domain:
            return {"success": False, "error": "Domain required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = engine.google_dorks(domain)
        return {"success": result.success, "data": result.data}

    async def _tool_ai_dork_search(self, args: Dict) -> Dict:
        target = args.get('target', '')
        dork_type = args.get('type', 'all')
        if not target:
            return {"success": False, "error": "Target required"}
        engine = await self._get_osint()
        if not engine:
            return {"success": False, "error": "OSINT engine not available"}
        result = await engine.ai_dork_search(target, dork_type=dork_type)
        return {"success": result.success, "data": result.data, "summary": result.summary()[:2000]}

    # ---- SpiderFoot Tools ----

    async def _tool_spiderfoot_scan(self, args: Dict) -> Dict:
        target = args.get('target', '')
        scan_type = args.get('scan_type', 'PASSIVE')
        if not target:
            return {"success": False, "error": "Target required"}
        try:
            from spiderfoot_tool import spiderfoot_scan
            return await spiderfoot_scan(target, scan_type=scan_type)
        except ImportError:
            return {"success": False, "error": "SpiderFoot tool not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_spiderfoot_results(self, args: Dict) -> Dict:
        scan_id = args.get('scan_id', '')
        if not scan_id:
            return {"success": False, "error": "scan_id required"}
        try:
            from spiderfoot_tool import spiderfoot_results
            return await spiderfoot_results(scan_id)
        except ImportError:
            return {"success": False, "error": "SpiderFoot tool not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_spiderfoot_status(self, args: Dict) -> Dict:
        try:
            from spiderfoot_tool import spiderfoot_status
            return await spiderfoot_status()
        except ImportError:
            return {"success": False, "error": "SpiderFoot tool not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_spiderfoot_modules(self, args: Dict) -> Dict:
        try:
            from spiderfoot_tool import spiderfoot_modules
            return await spiderfoot_modules()
        except ImportError:
            return {"success": False, "error": "SpiderFoot tool not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_web_search(self, args: Dict) -> Dict:
        query = args.get('query', '')
        if not query:
            return {"success": False, "error": "Query required"}

        # Include current date context in the query info for better results
        search_date = datetime.now().strftime('%Y-%m-%d %H:%M')

        # --- Method 1: Direct Serper API (primary, most reliable) ---
        serper_key = os.environ.get('SERPER_API_KEY', '')
        if serper_key and serper_key != 'your-serper-key-here':
            try:
                import aiohttp, ssl as ssl_mod
                ssl_ctx = ssl_mod.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl_mod.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        'https://google.serper.dev/search',
                        json={'q': query, 'num': 10},
                        headers={'X-API-KEY': serper_key, 'Content-Type': 'application/json'},
                        timeout=aiohttp.ClientTimeout(total=20)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            results = []
                            for item in data.get('organic', [])[:10]:
                                results.append({
                                    'title': item.get('title', ''),
                                    'link': item.get('link', ''),
                                    'snippet': item.get('snippet', ''),
                                    'date': item.get('date', ''),
                                    'position': item.get('position', 0),
                                })
                            answer_box = data.get('answerBox', {})
                            knowledge = data.get('knowledgeGraph', {})
                            news_results = []
                            for item in data.get('news', [])[:5]:
                                news_results.append({
                                    'title': item.get('title', ''),
                                    'link': item.get('link', ''),
                                    'snippet': item.get('snippet', ''),
                                    'date': item.get('date', ''),
                                    'source': item.get('source', ''),
                                })

                            return {
                                "success": True,
                                "search_engine": "Serper (Google)",
                                "query": query,
                                "searched_at": search_date,
                                "answer_box": {
                                    "title": answer_box.get('title', ''),
                                    "answer": answer_box.get('answer', answer_box.get('snippet', '')),
                                } if answer_box else None,
                                "knowledge_graph": {
                                    "title": knowledge.get('title', ''),
                                    "type": knowledge.get('type', ''),
                                    "description": knowledge.get('description', ''),
                                } if knowledge else None,
                                "results": results,
                                "news": news_results if news_results else None,
                                "total_results": len(results),
                            }
                        else:
                            safe_print(f"  [WARN] Serper HTTP {resp.status}: {await resp.text()}")
            except Exception as e:
                safe_print(f"  [WARN] Serper search failed: {e}")

        # --- Method 2: SearXNG fallback (self-hosted) ---
        searxng_url = os.environ.get('SEARXNG_URL', '')
        if searxng_url:
            try:
                import aiohttp, ssl as ssl_mod
                ssl_ctx = ssl_mod.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl_mod.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                async with aiohttp.ClientSession(connector=connector) as session:
                    params = {'q': query, 'format': 'json', 'engines': 'google,duckduckgo,bing'}
                    async with session.get(
                        f'{searxng_url.rstrip("/")}/search',
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            results = []
                            for item in data.get('results', [])[:10]:
                                results.append({
                                    'title': item.get('title', ''),
                                    'link': item.get('url', ''),
                                    'snippet': item.get('content', ''),
                                })
                            if results:
                                return {
                                    "success": True,
                                    "search_engine": "SearXNG",
                                    "query": query,
                                    "searched_at": search_date,
                                    "results": results,
                                    "total_results": len(results),
                                }
            except Exception as e:
                safe_print(f"  [WARN] SearXNG search failed: {e}")

        return {"success": False, "error": "No search results. Check SERPER_API_KEY in .env or set up SearXNG."}

    async def _tool_encode_decode(self, args: Dict) -> Dict:
        text = args.get('text', '')
        if not text:
            return {"success": False, "error": "Text required"}
        from osint import OSINTEngine
        results = OSINTEngine.encode_decode(text)
        return {"success": True, "results": results}

    # ---- EXIF Tools ----

    async def _tool_exif_extract(self, args: Dict) -> Dict:
        path = args.get('path', '')
        if not path or not os.path.exists(path):
            return {"success": False, "error": "Valid file path required"}
        try:
            from exif_tool import EXIFExtractor
            exif = EXIFExtractor()
            result = exif.extract(path)
            field_count = len(result) if isinstance(result, dict) else 0
            return {"success": True, "data": result, "message": f"Extracted {field_count} EXIF fields from {os.path.basename(path)}"}
        except ImportError:
            return {"success": False, "error": "EXIF tool not installed (pip install Pillow)"}

    async def _tool_exif_from_url(self, args: Dict) -> Dict:
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from exif_tool import EXIFExtractor
            exif = EXIFExtractor()
            result = await exif.extract_from_url(url, os.path.join(AI_DATA_DIR, "exif_downloads"))
            field_count = len(result) if isinstance(result, dict) else 0
            return {"success": True, "data": result, "message": f"Extracted {field_count} EXIF fields from URL"}
        except ImportError:
            return {"success": False, "error": "EXIF tool not installed"}

    # ---- File Reading Tool (User Files) ----

    async def _tool_read_user_file(self, args: Dict) -> Dict:
        """Read any file from the user's filesystem. Supports JSON, TXT, CSV, MD, LOG, and other text files."""
        path = args.get('path', args.get('file', ''))
        if not path:
            return {"success": False, "error": "File path required. Args: {\"path\": \"C:/path/to/file.json\"}"}

        # Normalize path
        path = os.path.normpath(os.path.abspath(path))

        if not os.path.exists(path):
            return {"success": False, "error": f"File not found: {path}"}

        if not os.path.isfile(path):
            return {"success": False, "error": f"Not a file: {path}"}

        # Size guard (max 5 MB)
        file_size = os.path.getsize(path)
        if file_size > 5_000_000:
            return {"success": False, "error": f"File too large ({format_size(file_size)}). Max: 5 MB"}

        try:
            ext = os.path.splitext(path)[1].lower()

            if ext == '.json':
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    data = json.load(f)
                # For very large JSON, provide a summary structure
                data_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
                truncated = len(data_str) > 15000
                return {
                    "success": True,
                    "path": path,
                    "filename": os.path.basename(path),
                    "type": "json",
                    "size": format_size(file_size),
                    "data": data,
                    "truncated": truncated,
                    "message": f"Read JSON file: {os.path.basename(path)} ({format_size(file_size)})"
                }
            else:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                truncated = len(content) > 15000
                line_count = content.count('\n') + 1
                return {
                    "success": True,
                    "path": path,
                    "filename": os.path.basename(path),
                    "type": ext.lstrip('.') or "text",
                    "size": format_size(file_size),
                    "lines": line_count,
                    "content": content[:15000],
                    "truncated": truncated,
                    "message": f"Read file: {os.path.basename(path)} ({format_size(file_size)}, {line_count} lines)"
                }
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON in {os.path.basename(path)}: {e}"}
        except UnicodeDecodeError:
            return {"success": False, "error": f"Cannot read {os.path.basename(path)} — binary file, not text."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- Data / Save Tools ----

    async def _tool_create_html(self, args: Dict) -> Dict:
        """Create a rich HTML report using the external template."""
        title = args.get('title', 'Namu AI Report')
        data = args.get('data', {})
        topic = sanitize_filename(args.get('topic', title))[:50]
        subtitle = args.get('subtitle', '')
        tags = args.get('tags', [])
        content = args.get('content', '')  # Allow raw HTML content from AI

        # If AI passed raw HTML content string instead of data dict, wrap it
        if content and not data:
            data = content

        # If the AI sent the last tool result, use that
        if not data and self._last_result:
            data = self._last_result

        html = build_html_from_data(
            title=title, data=data, topic=topic,
            subtitle=subtitle, tags=tags
        )

        # Save
        topic_dir = os.path.join(AI_REPORTS_DIR, topic)
        os.makedirs(topic_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(topic_dir, f"{sanitize_filename(title)}_{ts}.html")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        # Always tell the user where the file was saved
        print(f"\n  📄 HTML saved: {filepath}")

        return {"success": True, "filepath": filepath, "size": len(html),
                "template": TEMPLATE_FILE,
                "message": f"HTML report saved to: {filepath}"}

    async def _tool_save_html(self, args: Dict) -> Dict:
        """Alias for create_html (backward compat)."""
        return await self._tool_create_html(args)

    async def _tool_save_json(self, args: Dict) -> Dict:
        filename = args.get('filename', 'data')
        data = args.get('data', {})
        topic = sanitize_filename(args.get('topic', filename))[:50]

        # If no data passed, use last tool result
        if not data and self._last_result:
            data = self._last_result

        topic_dir = os.path.join(AI_DATA_DIR, topic)
        os.makedirs(topic_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(topic_dir, f"{sanitize_filename(filename)}_{ts}.json")

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        # Always tell the user where the file was saved
        print(f"\n  💾 JSON saved: {filepath}")

        return {"success": True, "filepath": filepath,
                "message": f"JSON data saved to: {filepath}"}

    # ---- Windows / OS Tools ----

    async def _tool_open_file(self, args: Dict) -> Dict:
        """Open a file with default or specified application."""
        path = args.get('path', args.get('filepath', ''))
        app = args.get('app', '')
        if not path:
            # Try to open last saved file
            if self._last_result and isinstance(self._last_result, dict):
                path = self._last_result.get('filepath', '')
            if not path:
                return {"success": False, "error": "No file path provided"}
        if not HAS_WINDOWS_TOOLS:
            return {"success": False, "error": "windows_tools module not available"}
        result = windows_tools.open_file(path, app=app)
        if result.get('success'):
            print(f"\n  📂 Opened: {path}" + (f" in {app}" if app else ""))
        return result

    async def _tool_open_folder(self, args: Dict) -> Dict:
        """Open a folder in Windows Explorer."""
        path = args.get('path', args.get('directory', ''))
        if not path:
            # Default to ai_reports or ai_data
            path = AI_REPORTS_DIR
        if not HAS_WINDOWS_TOOLS:
            return {"success": False, "error": "windows_tools module not available"}
        result = windows_tools.open_folder(path)
        if result.get('success'):
            print(f"\n  📁 Opened folder: {path}")
        return result

    async def _tool_open_url(self, args: Dict) -> Dict:
        """Open a URL in the browser."""
        url = args.get('url', '')
        browser = args.get('browser', '')
        if not url:
            return {"success": False, "error": "URL required"}
        if not HAS_WINDOWS_TOOLS:
            import webbrowser
            webbrowser.open(url if url.startswith('http') else f'https://{url}')
            return {"success": True, "url": url, "message": f"Opened {url} in browser"}
        result = windows_tools.open_url(url, browser=browser)
        if result.get('success'):
            print(f"\n  🌐 Opened URL: {url}")
        return result

    async def _tool_launch_app(self, args: Dict) -> Dict:
        """Launch an application."""
        app = args.get('app', args.get('name', ''))
        app_args = args.get('args', [])
        if not app:
            return {"success": False, "error": "App name required"}
        if not HAS_WINDOWS_TOOLS:
            return {"success": False, "error": "windows_tools module not available"}
        result = windows_tools.launch_app(app, args=app_args)
        if result.get('success'):
            print(f"\n  🚀 Launched: {app}")
        return result

    async def _tool_open_recent(self, args: Dict) -> Dict:
        """Get most recent file(s) from a directory, optionally open it."""
        directory = args.get('directory', 'ai_reports')
        extension = args.get('extension', '')
        should_open = args.get('open', False)
        app = args.get('app', '')
        count = args.get('count', 1)

        # Map shorthand names to full paths
        dir_map = {
            'ai_reports': AI_REPORTS_DIR,
            'ai_data': AI_DATA_DIR,
            'reports': AI_REPORTS_DIR,
            'data': AI_DATA_DIR,
        }
        directory = dir_map.get(directory.lower(), directory)

        if not HAS_WINDOWS_TOOLS:
            return {"success": False, "error": "windows_tools module not available"}

        result = windows_tools.get_recent_files(directory, extension=extension, count=count)

        if result.get('success') and result.get('files') and should_open:
            recent_file = result['files'][0]['path']
            open_result = windows_tools.open_file(recent_file, app=app)
            result['opened'] = open_result
            print(f"\n  📂 Opened recent: {recent_file}")

        return result

    async def _tool_search_files(self, args: Dict) -> Dict:
        """Search for files by name in a directory."""
        directory = args.get('directory', AI_REPORTS_DIR)
        query = args.get('query', '')
        extensions = args.get('extensions', None)

        if not query:
            return {"success": False, "error": "Search query required"}

        # Map shorthand names
        dir_map = {
            'ai_reports': AI_REPORTS_DIR,
            'ai_data': AI_DATA_DIR,
            'reports': AI_REPORTS_DIR,
            'data': AI_DATA_DIR,
        }
        directory = dir_map.get(directory.lower(), directory)

        if not HAS_WINDOWS_TOOLS:
            return {"success": False, "error": "windows_tools module not available"}

        return windows_tools.search_files(directory, query, extensions=extensions)

    # ---- Download Extras ----

    async def _tool_download_thumbnail(self, args: Dict) -> Dict:
        """Download thumbnail from a video URL."""
        url = args.get('url', '')
        if not url:
            return {"success": False, "error": "URL required"}
        try:
            from extractors import extract_metadata
            metadata = await extract_metadata(url)
            if not metadata or not metadata.best_thumbnail:
                return {"success": False, "error": "Could not find thumbnail for this URL"}
            thumb_url = metadata.best_thumbnail.url
            scraper = await self._get_scraper()
            if not scraper:
                return {"success": False, "error": "Scraper not available"}
            result = await scraper.download_image(
                thumb_url,
                output_dir=os.path.join(config.paths.base_dir, "thumbnails")
            )
            if result.get('success'):
                result['message'] = f"Thumbnail saved: {result.get('filepath', '?')} ({result.get('size', '?')})"
                result['video_title'] = getattr(metadata, 'title', '')
            return result
        except ImportError:
            return {"success": False, "error": "Extractors module not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- History / Stats Tools ----

    async def _tool_download_history(self, args: Dict) -> Dict:
        """View download history."""
        limit = min(int(args.get('limit', 20)), 50)
        try:
            from database import DownloadDatabase
            db = DownloadDatabase()
            history = db.list_media(limit=limit)
            if not history:
                return {"success": True, "data": [], "message": "No downloads found in history"}
            items = []
            for item in history:
                items.append({
                    "title": item.get('title') or item.get('filename', 'Unknown'),
                    "size": format_size(item.get('filesize', 0)),
                    "type": item.get('media_type', 'unknown'),
                    "has_audio": item.get('has_audio', False),
                    "filepath": item.get('filepath', ''),
                })
            return {
                "success": True, "total": len(items), "downloads": items,
                "message": f"Found {len(items)} downloads in history"
            }
        except ImportError:
            return {"success": False, "error": "Database module not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_search_downloads(self, args: Dict) -> Dict:
        """Search download history."""
        query = args.get('query', '')
        if not query:
            return {"success": False, "error": "Search query required"}
        try:
            from database import DownloadDatabase
            db = DownloadDatabase()
            results = db.search(query)
            media = results.get('media', [])
            items = [{"title": m.get('title', 'Unknown'), "type": m.get('media_type', '?'),
                       "filepath": m.get('filepath', '')} for m in media[:20]]
            return {
                "success": True, "query": query, "total": len(media),
                "results": items,
                "message": f"Found {len(media)} results for '{query}'"
            }
        except ImportError:
            return {"success": False, "error": "Database module not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_view_statistics(self, args: Dict) -> Dict:
        """View download statistics."""
        try:
            from database import DownloadDatabase
            db = DownloadDatabase()
            stats = db.get_stats()
            msg_parts = []
            if stats.get('total_downloads'): msg_parts.append(f"{stats['total_downloads']} total downloads")
            if stats.get('videos'): msg_parts.append(f"{stats['videos']} videos")
            if stats.get('audio_files'): msg_parts.append(f"{stats['audio_files']} audio")
            if stats.get('total_size_gb'): msg_parts.append(f"{stats['total_size_gb']:.2f} GB total")
            return {
                "success": True, "data": stats,
                "message": "Stats: " + " | ".join(msg_parts) if msg_parts else "No statistics available"
            }
        except ImportError:
            return {"success": False, "error": "Database module not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_resume_failed(self, args: Dict) -> Dict:
        """Resume failed downloads."""
        try:
            from database import DownloadDatabase
            db = DownloadDatabase()
            failed = db.list_media(status='failed', limit=20)
            if not failed:
                return {"success": True, "data": [], "message": "No failed downloads to resume"}
            items = [{"title": f.get('title', 'Unknown'), "url": f.get('url', ''),
                       "error": f.get('error', '')} for f in failed]
            return {
                "success": True, "total": len(items), "failed_downloads": items,
                "message": f"Found {len(items)} failed downloads that can be retried"
            }
        except ImportError:
            return {"success": False, "error": "Database module not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- System Tools ----

    async def _tool_check_dependencies(self, args: Dict) -> Dict:
        """Check system dependencies."""
        from utils import run_command
        deps = {}
        # Check ffmpeg
        ok, out, _ = run_command(['ffmpeg', '-version'], timeout=10)
        ver = out.split('\n')[0][:60] if ok and out else 'Not found'
        deps['ffmpeg'] = {"installed": ok, "version": ver}
        # Check ffprobe
        ok2, _, _ = run_command(['ffprobe', '-version'], timeout=10)
        deps['ffprobe'] = {"installed": ok2}
        # Check yt-dlp
        ok3, out3, _ = run_command(['yt-dlp', '--version'], timeout=10)
        deps['yt-dlp'] = {"installed": ok3, "version": out3.strip()[:30] if ok3 and out3 else 'Not found'}
        # Python packages
        for pkg in ['aiohttp', 'aiofiles', 'bs4', 'PIL', 'scrapling']:
            try:
                __import__(pkg if pkg != 'PIL' else 'PIL')
                deps[pkg] = {"installed": True}
            except ImportError:
                deps[pkg] = {"installed": False}
        installed = sum(1 for v in deps.values() if v.get('installed'))
        return {
            "success": True, "data": deps,
            "message": f"Dependencies: {installed}/{len(deps)} installed"
        }

    async def _tool_verify_directories(self, args: Dict) -> Dict:
        """Verify and create storage directories."""
        config.paths.init_all()
        dirs = {
            "videos": config.paths.videos,
            "audio": config.paths.audio,
            "images": config.paths.images,
            "osint": config.paths.osint,
        }
        if hasattr(config.paths, 'thumbnails'):
            dirs["thumbnails"] = config.paths.thumbnails
        status = {}
        for name, path in dirs.items():
            exists = os.path.isdir(path)
            status[name] = {"path": path, "exists": exists}
        return {
            "success": True, "data": status,
            "message": f"All {len(dirs)} directories verified and ready"
        }

    async def _tool_clear_temp(self, args: Dict) -> Dict:
        """Clear temporary files."""
        try:
            from utils import cleanup_temp_files
            count = cleanup_temp_files(max_age_hours=1)
            return {
                "success": True, "removed": count,
                "message": f"Removed {count} temporary files" if count else "No temporary files to remove"
            }
        except ImportError:
            return {"success": False, "error": "cleanup_temp_files not available in utils"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_update_ytdlp(self, args: Dict) -> Dict:
        """Update yt-dlp to latest version."""
        from utils import run_command
        # Get current version
        ok_old, old_ver, _ = run_command(['yt-dlp', '--version'], timeout=10)
        old_ver = old_ver.strip() if ok_old and old_ver else 'unknown'
        # Update
        ok, out, err = run_command(['pip', 'install', '-U', 'yt-dlp'], timeout=120)
        if not ok:
            return {"success": False, "error": f"Update failed: {err[:150] if err else 'Unknown error'}"}
        # Get new version
        ok_new, new_ver, _ = run_command(['yt-dlp', '--version'], timeout=10)
        new_ver = new_ver.strip() if ok_new and new_ver else 'unknown'
        if old_ver == new_ver:
            msg = f"yt-dlp is already up to date (v{new_ver})"
        else:
            msg = f"yt-dlp updated: v{old_ver} → v{new_ver}"
        return {"success": True, "old_version": old_ver, "new_version": new_ver, "message": msg}

    # =========================================================================
    # SIAI — Self-Improvement AI Tools (Sandboxed)
    # =========================================================================

    def _siai_resolve(self, shortname: str) -> Optional[str]:
        """Resolve a short filename to its allowed absolute path. Returns None if not allowed."""
        # Accept both shortnames and full paths
        if shortname in SIAI_ALLOWED_FILES:
            return SIAI_ALLOWED_FILES[shortname]
        # Check if user passed the full path
        norm = os.path.normpath(os.path.abspath(shortname))
        for allowed_path in SIAI_ALLOWED_FILES.values():
            if os.path.normpath(allowed_path) == norm:
                return allowed_path
        return None

    def _siai_backup(self, filepath: str) -> str:
        """Create a timestamped backup of a file. Returns the backup path."""
        if not os.path.exists(filepath):
            return ""
        basename = os.path.basename(filepath)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(SIAI_BACKUP_DIR, f"{basename}.{ts}.bak")
        import shutil
        shutil.copy2(filepath, backup_path)
        log_info(f"SIAI backup: {backup_path}")
        return backup_path

    def _siai_latest_backup(self, filepath: str) -> Optional[str]:
        """Find the most recent backup file for a given source file."""
        basename = os.path.basename(filepath)
        prefix = f"{basename}."
        backups = sorted(
            [f for f in os.listdir(SIAI_BACKUP_DIR) if f.startswith(prefix) and f.endswith('.bak')],
            reverse=True
        )
        if backups:
            return os.path.join(SIAI_BACKUP_DIR, backups[0])
        return None

    def _siai_validate_py(self, content: str, filepath: str) -> Optional[str]:
        """Validate Python syntax. Returns error message or None if OK."""
        try:
            compile(content, filepath, 'exec')
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"

    # ---- SIAI Tool: List Files ----

    async def _tool_siai_list_files(self, args: Dict) -> Dict:
        """List all SIAI-allowed files with metadata."""
        files_info = []
        for shortname, fullpath in SIAI_ALLOWED_FILES.items():
            info = {"name": shortname, "path": fullpath, "exists": os.path.exists(fullpath)}
            if info["exists"]:
                stat = os.stat(fullpath)
                info["size_bytes"] = stat.st_size
                info["size"] = format_size(stat.st_size)
                info["last_modified"] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                # Count lines for text files
                try:
                    with open(fullpath, 'r', encoding='utf-8', errors='replace') as f:
                        info["lines"] = sum(1 for _ in f)
                except Exception:
                    info["lines"] = "?"
            files_info.append(info)

        # Count backups
        backup_count = len([f for f in os.listdir(SIAI_BACKUP_DIR) if f.endswith('.bak')])

        return {
            "success": True,
            "files": files_info,
            "backup_count": backup_count,
            "backup_dir": SIAI_BACKUP_DIR,
            "message": f"SIAI access: {len(files_info)} files, {backup_count} backups"
        }

    # ---- SIAI Tool: Outline (Structure Map) ----

    async def _tool_siai_outline(self, args: Dict) -> Dict:
        """Get the structure map of a file — classes, functions, sections with line numbers."""
        shortname = args.get('file', '')

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {shortname}"}

        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            total_lines = len(lines)
            structure = []

            if filepath.endswith('.py'):
                # Parse Python structure: classes, functions, section comments
                for i, line in enumerate(lines, 1):
                    stripped = line.rstrip()
                    # Section headers (# ===... or # ---...)
                    if stripped.startswith('# =') and len(stripped) > 20:
                        # Next non-empty line is the section title
                        for j in range(i, min(i + 3, total_lines)):
                            title_line = lines[j - 1].strip().strip('# ').strip('=-').strip()
                            if title_line and not title_line.startswith('='):
                                structure.append({"line": i, "type": "section", "name": title_line})
                                break
                    elif stripped.startswith('class ') and '(' in stripped:
                        name = stripped.split('(')[0].replace('class ', '').strip()
                        structure.append({"line": i, "type": "class", "name": name})
                    elif re.match(r'^    def |^    async def ', stripped):
                        name = stripped.split('(')[0].replace('async ', '').replace('def ', '').strip()
                        structure.append({"line": i, "type": "method", "name": name})
                    elif re.match(r'^def |^async def ', stripped):
                        name = stripped.split('(')[0].replace('async ', '').replace('def ', '').strip()
                        structure.append({"line": i, "type": "function", "name": name})
            elif filepath.endswith('.html'):
                # Parse HTML structure: major tags, sections, scripts
                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if any(stripped.startswith(f'<{t}') for t in ['head', 'body', 'style', 'script', 'nav', 'main', 'footer', 'header', 'section', 'div class', 'div id']):
                        tag = stripped[:80].rstrip('>')
                        structure.append({"line": i, "type": "tag", "name": tag})
                    elif '<!--' in stripped and len(stripped) > 6:
                        structure.append({"line": i, "type": "comment", "name": stripped[:80]})
            elif filepath.endswith('.md'):
                # Parse Markdown structure: headings
                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        structure.append({"line": i, "type": "heading", "name": stripped[:80]})

            # Build compact output
            outline_text = f"{shortname} — {total_lines} lines\n"
            for item in structure:
                indent = "  " if item["type"] in ("method",) else ""
                outline_text += f"  {indent}L{item['line']:>5}  [{item['type']:>8}]  {item['name']}\n"

            return {
                "success": True,
                "file": shortname,
                "total_lines": total_lines,
                "structure_count": len(structure),
                "structure": structure,
                "outline": outline_text,
                "message": f"Outline of {shortname}: {len(structure)} items across {total_lines} lines"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- SIAI Tool: Read File (Targeted) ----

    async def _tool_siai_read_file(self, args: Dict) -> Dict:
        """Read a SPECIFIC line range of an allowed file. For large files, line range is required."""
        shortname = args.get('file', '')
        start_line = args.get('start_line', None)
        end_line = args.get('end_line', None)

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist. Allowed: {', '.join(SIAI_ALLOWED_FILES.keys())}"}
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {shortname}"}

        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            total_lines = len(lines)

            # For large files WITHOUT a line range → return outline instead
            if total_lines > 100 and start_line is None and end_line is None:
                safe_print(f"  [SIAI] {shortname} has {total_lines} lines — returning outline. Use start_line/end_line for content.")
                return await self._tool_siai_outline({"file": shortname})

            # Apply line range
            if start_line is not None or end_line is not None:
                s = max(1, int(start_line or 1)) - 1
                e = min(total_lines, int(end_line or total_lines))
                # Cap at 100 lines per read
                if (e - s) > 100:
                    e = s + 100
                selected = lines[s:e]
                content = ''.join(f"{s+1+i:>5}: {l}" for i, l in enumerate(selected))
                range_desc = f"lines {s+1}-{e} of {total_lines}"
            else:
                # Small file — return all with line numbers
                content = ''.join(f"{i+1:>5}: {l}" for i, l in enumerate(lines))
                range_desc = f"all {total_lines} lines"

            return {
                "success": True,
                "file": shortname,
                "total_lines": total_lines,
                "range": range_desc,
                "content": content,
                "message": f"Read {shortname}: {range_desc}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- SIAI Tool: Search ----

    async def _tool_siai_search(self, args: Dict) -> Dict:
        """Search for a pattern within allowed files."""
        query = args.get('query', '')
        target_file = args.get('file', '')

        if not query:
            return {"success": False, "error": "Search query required"}

        files_to_search = {}
        if target_file:
            filepath = self._siai_resolve(target_file)
            if not filepath:
                return {"success": False, "error": f"Access denied: '{target_file}' not in SIAI allowlist"}
            files_to_search = {target_file: filepath}
        else:
            files_to_search = dict(SIAI_ALLOWED_FILES)

        results = []
        for shortname, fullpath in files_to_search.items():
            if not os.path.exists(fullpath):
                continue
            try:
                with open(fullpath, 'r', encoding='utf-8', errors='replace') as f:
                    for line_num, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append({
                                "file": shortname,
                                "line": line_num,
                                "content": line.rstrip()[:200],
                            })
                            if len(results) >= 50:
                                break
            except Exception:
                continue
            if len(results) >= 50:
                break

        return {
            "success": True,
            "query": query,
            "total_matches": len(results),
            "matches": results,
            "message": f"Found {len(results)} matches for '{query}'" + (f" in {target_file}" if target_file else " across all SIAI files")
        }

    # ---- SIAI Tool: Patch File (Find & Replace — with optional line-range scoping) ----

    async def _tool_siai_patch_file(self, args: Dict) -> Dict:
        """Apply a targeted find-and-replace patch. Supports line-range scoping for disambiguation."""
        shortname = args.get('file', '')
        find_text = args.get('find', '')
        replace_text = args.get('replace', '')
        description = args.get('description', 'No description provided')
        scope_start = args.get('start_line', None)
        scope_end = args.get('end_line', None)

        if not shortname or not find_text:
            return {"success": False, "error": "Required args: file, find, replace"}

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {shortname}"}

        # Size guard
        if len(find_text) > SIAI_MAX_PATCH_SIZE or len(replace_text) > SIAI_MAX_PATCH_SIZE:
            return {"success": False, "error": f"Patch too large. Max {SIAI_MAX_PATCH_SIZE} chars per find/replace block."}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            original = ''.join(lines)

            # --- Line-range scoping: operate on a slice of the file ---
            if scope_start is not None or scope_end is not None:
                s = max(1, int(scope_start or 1)) - 1
                e = min(len(lines), int(scope_end or len(lines)))
                scoped_text = ''.join(lines[s:e])

                occurrences = scoped_text.count(find_text)
                if occurrences == 0:
                    return {
                        "success": False,
                        "error": f"Find text not found in {shortname} lines {s+1}-{e}.",
                        "hint": "Use siai_search to find the exact text and line numbers first."
                    }
                if occurrences > 1:
                    return {
                        "success": False,
                        "error": f"Find text matches {occurrences} times in lines {s+1}-{e}. Narrow the range or make find text more specific.",
                    }

                # Replace within the scoped section
                patched_scope = scoped_text.replace(find_text, replace_text, 1)
                new_lines = lines[:s] + patched_scope.splitlines(True) + lines[e:]
                new_content = ''.join(new_lines)
            else:
                # --- Full-file find/replace (original behavior) ---
                occurrences = original.count(find_text)
                if occurrences == 0:
                    return {
                        "success": False,
                        "error": f"Find text not found in {shortname}. Make sure it matches exactly (whitespace, indentation).",
                        "hint": "Use siai_search or siai_read_file to view the exact current code first."
                    }
                if occurrences > 1:
                    # Instead of failing, tell the AI to scope it
                    # Find all line numbers where the text starts
                    match_lines = []
                    offset = 0
                    for li, line_text in enumerate(lines, 1):
                        if find_text in ''.join(lines[offset:])[:len(find_text) + 500]:
                            pass  # simplified
                    return {
                        "success": False,
                        "error": f"Find text matches {occurrences} locations. Use start_line/end_line to scope the patch to the correct one.",
                        "hint": f"Run siai_search to find line numbers, then add start_line/end_line args to scope.",
                        "occurrences": occurrences,
                    }

                new_content = original.replace(find_text, replace_text, 1)

            # Create backup
            backup_path = self._siai_backup(filepath)

            # Validate .py syntax
            if filepath.endswith('.py'):
                syntax_err = self._siai_validate_py(new_content, filepath)
                if syntax_err:
                    return {
                        "success": False,
                        "error": f"Patch rejected — syntax error: {syntax_err}",
                        "hint": "Backup was NOT overwritten. Fix your code and try again."
                    }

            # Write patched content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

            safe_print(f"  [SIAI] ✏️  Patched {shortname}: {description}")
            await self._siai_auto_log(shortname, "patch", description, len(find_text), len(replace_text))

            return {
                "success": True,
                "file": shortname,
                "backup": backup_path,
                "find_length": len(find_text),
                "replace_length": len(replace_text),
                "lines_delta": replace_text.count('\n') - find_text.count('\n'),
                "scoped": bool(scope_start or scope_end),
                "description": description,
                "message": f"✏️ Patched {shortname} — {description} (backup: {os.path.basename(backup_path)})"
            }
        except Exception as e:
            return {"success": False, "error": f"Patch failed: {str(e)}"}

    # ---- SIAI Tool: Insert Code (at a specific line) ----

    async def _tool_siai_insert_code(self, args: Dict) -> Dict:
        """Insert new code after a specific line number. Creates backup first."""
        shortname = args.get('file', '')
        after_line = args.get('after_line', None)
        code = args.get('code', '')
        description = args.get('description', 'No description provided')

        if not shortname or after_line is None or not code:
            return {"success": False, "error": "Required args: file, after_line, code"}

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {shortname}"}

        after_line = int(after_line)

        # Size guard
        if len(code) > SIAI_MAX_PATCH_SIZE:
            return {"success": False, "error": f"Insert too large ({len(code)} chars). Max: {SIAI_MAX_PATCH_SIZE} chars."}

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if after_line < 0 or after_line > len(lines):
                return {"success": False, "error": f"Line {after_line} out of range (file has {len(lines)} lines). Use 0 to insert at the top."}

            # Ensure code ends with newline
            if not code.endswith('\n'):
                code += '\n'

            # Insert
            new_lines = lines[:after_line] + code.splitlines(True) + lines[after_line:]
            new_content = ''.join(new_lines)

            # Create backup
            backup_path = self._siai_backup(filepath)

            # Validate .py syntax
            if filepath.endswith('.py'):
                syntax_err = self._siai_validate_py(new_content, filepath)
                if syntax_err:
                    return {
                        "success": False,
                        "error": f"Insert rejected — syntax error: {syntax_err}",
                        "hint": "Backup was NOT overwritten. Fix your code and try again."
                    }

            # Write
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

            inserted_lines = len(code.splitlines())
            safe_print(f"  [SIAI] ➕ Inserted {inserted_lines} lines after L{after_line} in {shortname}: {description}")
            await self._siai_auto_log(shortname, "insert", f"After L{after_line}: {description}", 0, len(code))

            return {
                "success": True,
                "file": shortname,
                "backup": backup_path,
                "after_line": after_line,
                "lines_inserted": inserted_lines,
                "new_total_lines": len(new_lines),
                "description": description,
                "message": f"➕ Inserted {inserted_lines} lines after L{after_line} in {shortname} — {description}"
            }
        except Exception as e:
            return {"success": False, "error": f"Insert failed: {str(e)}"}

    # ---- SIAI Tool: Write File (Full Rewrite — HTML/MD only) ----

    async def _tool_siai_write_file(self, args: Dict) -> Dict:
        """Full file rewrite. Blocked for .py files. Creates backup first."""
        shortname = args.get('file', '')
        content = args.get('content', '')
        description = args.get('description', 'No description provided')

        if not shortname or not content:
            return {"success": False, "error": "Required args: file, content"}

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}

        # Block full rewrite for .py files
        if SIAI_PY_ONLY_PATCH and filepath.endswith('.py'):
            return {
                "success": False,
                "error": "Full rewrite is blocked for .py files (safety). Use siai_patch_file for targeted edits.",
                "hint": "Read the section you want to change with siai_read_file, then use siai_patch_file with find/replace."
            }

        # Size guard
        if len(content) > SIAI_MAX_FILE_SIZE:
            return {"success": False, "error": f"Content too large ({len(content)} bytes). Max: {SIAI_MAX_FILE_SIZE} bytes."}

        try:
            # Backup existing file
            backup_path = ""
            if os.path.exists(filepath):
                backup_path = self._siai_backup(filepath)

            # Write new content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            safe_print(f"  [SIAI] 📝 Wrote {shortname}: {description}")

            # Auto-log
            await self._siai_auto_log(shortname, "write", description, 0, len(content))

            return {
                "success": True,
                "file": shortname,
                "backup": backup_path,
                "size_bytes": len(content),
                "size": format_size(len(content)),
                "description": description,
                "message": f"📝 Wrote {shortname} ({format_size(len(content))}) — {description}"
            }
        except Exception as e:
            return {"success": False, "error": f"Write failed: {str(e)}"}

    # ---- SIAI Tool: Rollback ----

    async def _tool_siai_rollback(self, args: Dict) -> Dict:
        """Restore a file from its most recent backup."""
        shortname = args.get('file', '')

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}

        backup_path = self._siai_latest_backup(filepath)
        if not backup_path:
            return {"success": False, "error": f"No backups found for {shortname}"}

        try:
            import shutil
            # First, backup the current (potentially broken) state
            broken_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            broken_backup = os.path.join(SIAI_BACKUP_DIR, f"{os.path.basename(filepath)}.{broken_ts}.pre_rollback.bak")
            if os.path.exists(filepath):
                shutil.copy2(filepath, broken_backup)

            # Restore from backup
            shutil.copy2(backup_path, filepath)

            safe_print(f"  [SIAI] ⏪ Rolled back {shortname} from {os.path.basename(backup_path)}")

            # Log the rollback
            await self._siai_auto_log(shortname, "rollback", f"Restored from {os.path.basename(backup_path)}", 0, 0)

            return {
                "success": True,
                "file": shortname,
                "restored_from": backup_path,
                "pre_rollback_saved": broken_backup,
                "message": f"⏪ Rolled back {shortname} to {os.path.basename(backup_path)}"
            }
        except Exception as e:
            return {"success": False, "error": f"Rollback failed: {str(e)}"}

    # ---- SIAI Tool: Diff ----

    async def _tool_siai_diff(self, args: Dict) -> Dict:
        """Show diff between current file and its latest backup."""
        shortname = args.get('file', '')

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {shortname}"}

        backup_path = self._siai_latest_backup(filepath)
        if not backup_path:
            return {"success": False, "error": f"No backups found for {shortname}. Nothing to diff against."}

        try:
            import difflib

            with open(backup_path, 'r', encoding='utf-8', errors='replace') as f:
                old_lines = f.readlines()
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                new_lines = f.readlines()

            diff = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"backup/{os.path.basename(backup_path)}",
                tofile=shortname,
                lineterm=''
            ))

            if not diff:
                return {
                    "success": True,
                    "file": shortname,
                    "diff": "(no differences)",
                    "message": f"No differences between {shortname} and its latest backup"
                }

            # Cap diff output
            diff_text = '\n'.join(diff[:200])
            if len(diff) > 200:
                diff_text += f"\n... ({len(diff) - 200} more diff lines truncated)"

            added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
            removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

            return {
                "success": True,
                "file": shortname,
                "backup": os.path.basename(backup_path),
                "lines_added": added,
                "lines_removed": removed,
                "diff": diff_text,
                "message": f"Diff for {shortname}: +{added} -{removed} lines vs {os.path.basename(backup_path)}"
            }
        except Exception as e:
            return {"success": False, "error": f"Diff failed: {str(e)}"}

    # ---- SIAI Tool: Log ----

    async def _tool_siai_log(self, args: Dict) -> Dict:
        """Log a structured improvement entry to SIAI.md."""
        section = args.get('section', 'General')
        description = args.get('description', '')
        changes = args.get('changes', '')

        if not description:
            return {"success": False, "error": "Description required for log entry"}

        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = f"\n### [{ts}] {section}\n"
            entry += f"**Description:** {description}\n"
            if changes:
                entry += f"**Changes:**\n```\n{changes}\n```\n"
            entry += "\n---\n"

            # Read existing content or create fresh
            existing = ""
            if os.path.exists(SIAI_LOG_FILE):
                with open(SIAI_LOG_FILE, 'r', encoding='utf-8') as f:
                    existing = f.read()

            # If file is empty or new, add the header
            if not existing.strip():
                existing = """# 🧠 Namu AI — Self-Improvement Log (SIAI)

> This file is automatically maintained by Namu AI's self-improvement system.
> Every code change, patch, and improvement is logged here with timestamps.

## How This Works
- Namu AI can read/write its own code files (sandboxed to 4 files).
- Every modification creates a backup in `siai_backups/`.
- This log tracks what was changed and why.

---

## Improvement History

"""

            # Append entry
            with open(SIAI_LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(existing + entry)

            safe_print(f"  [SIAI] 📋 Logged: {section} — {description[:60]}")

            return {
                "success": True,
                "section": section,
                "description": description,
                "message": f"📋 Logged improvement to SIAI.md: [{section}] {description[:80]}"
            }
        except Exception as e:
            return {"success": False, "error": f"Log failed: {str(e)}"}

    # ---- SIAI Tool: Status ----

    async def _tool_siai_status(self, args: Dict) -> Dict:
        """Show SIAI system status: files, backups, recent log entries."""
        # Files status
        files_status = {}
        for shortname, fullpath in SIAI_ALLOWED_FILES.items():
            if os.path.exists(fullpath):
                stat = os.stat(fullpath)
                files_status[shortname] = {
                    "size": format_size(stat.st_size),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    "healthy": True,
                }
                # Syntax check for .py
                if fullpath.endswith('.py'):
                    try:
                        with open(fullpath, 'r', encoding='utf-8') as f:
                            compile(f.read(), fullpath, 'exec')
                        files_status[shortname]["syntax"] = "✅ OK"
                    except SyntaxError as e:
                        files_status[shortname]["syntax"] = f"❌ Error: {e.msg} (line {e.lineno})"
                        files_status[shortname]["healthy"] = False
            else:
                files_status[shortname] = {"exists": False, "healthy": False}

        # Backups
        backups = sorted(
            [f for f in os.listdir(SIAI_BACKUP_DIR) if f.endswith('.bak')],
            reverse=True
        )
        recent_backups = []
        for b in backups[:10]:
            bpath = os.path.join(SIAI_BACKUP_DIR, b)
            bstat = os.stat(bpath)
            recent_backups.append({
                "name": b,
                "size": format_size(bstat.st_size),
                "date": datetime.fromtimestamp(bstat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            })

        # Recent SIAI.md entries (last 5)
        recent_logs = []
        if os.path.exists(SIAI_LOG_FILE):
            with open(SIAI_LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            # Parse ### entries
            import re as _re
            entries = _re.findall(r'### \[([^\]]+)\] (.+)', content)
            recent_logs = [{"timestamp": ts, "section": sec} for ts, sec in entries[-5:]]

        all_healthy = all(f.get("healthy", False) for f in files_status.values())

        return {
            "success": True,
            "overall_health": "✅ All systems healthy" if all_healthy else "⚠️ Issues detected",
            "files": files_status,
            "total_backups": len(backups),
            "recent_backups": recent_backups,
            "recent_log_entries": recent_logs,
            "message": f"SIAI Status: {len(files_status)} files, {len(backups)} backups, {'✅ healthy' if all_healthy else '⚠️ issues detected'}"
        }

    # ---- SIAI Tool: Hot Reload ----

    async def _tool_siai_hot_reload(self, args: Dict) -> Dict:
        """Reload the namu_ai module so code changes take effect without restart."""
        import importlib
        filepath = SIAI_ALLOWED_FILES.get("namu_ai.py", "")

        # First validate syntax
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                source = f.read()
            compile(source, filepath, 'exec')
        except SyntaxError as e:
            return {
                "success": False,
                "error": f"Cannot reload — syntax error at line {e.lineno}: {e.msg}",
                "hint": "Fix the syntax error first with siai_patch_file or siai_rollback."
            }

        try:
            import namu_ai as _self_module
            # Snapshot old tool count
            old_tools = [m for m in dir(self) if m.startswith('_tool_')]
            old_count = len(old_tools)

            # Reload the module
            importlib.reload(_self_module)

            # Re-bind tool methods from the reloaded ToolExecutor class
            new_executor_cls = _self_module.ToolExecutor
            new_methods = [m for m in dir(new_executor_cls) if m.startswith('_tool_')]

            # Copy new/updated methods to self
            rebound = 0
            new_tools = []
            for method_name in new_methods:
                new_method = getattr(new_executor_cls, method_name)
                old_method = getattr(self.__class__, method_name, None)
                # Bind the new method to this instance
                import types
                setattr(self, method_name, types.MethodType(new_method, self))
                rebound += 1
                if method_name not in old_tools:
                    new_tools.append(method_name.replace('_tool_', ''))

            safe_print(f"  [SIAI] 🔄 Hot-reloaded! {rebound} tool methods rebound.")
            if new_tools:
                safe_print(f"  [SIAI] ✨ New tools: {', '.join(new_tools)}")

            await self._siai_auto_log("namu_ai.py", "hot_reload",
                f"Reloaded module. {rebound} methods rebound, {len(new_tools)} new tools.", 0, 0)

            return {
                "success": True,
                "methods_rebound": rebound,
                "new_tools": new_tools,
                "total_tools": len(new_methods),
                "message": f"🔄 Hot-reloaded! {rebound} methods active, {len(new_tools)} new tools."
            }
        except Exception as e:
            return {"success": False, "error": f"Hot reload failed: {str(e)}",
                    "hint": "The old code is still running. Fix the issue and try again."}

    # ---- SIAI Tool: Self-Test ----

    async def _tool_siai_test(self, args: Dict) -> Dict:
        """Run a smoke test: syntax check, import test, tool inventory, health report."""
        test_tool = args.get('tool', '')
        results = {"syntax": {}, "imports": {}, "tools": {}, "health": {}}

        # 1. Syntax check all .py SIAI files
        for name, path in SIAI_ALLOWED_FILES.items():
            if path.endswith('.py') and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        compile(f.read(), path, 'exec')
                    results["syntax"][name] = "✅ OK"
                except SyntaxError as e:
                    results["syntax"][name] = f"❌ Line {e.lineno}: {e.msg}"

        # 2. Import test — ensure critical modules load
        critical_imports = ['os', 'sys', 'json', 're', 'asyncio', 'datetime', 'traceback']
        for mod in critical_imports:
            try:
                __import__(mod)
                results["imports"][mod] = "✅"
            except ImportError:
                results["imports"][mod] = "❌"

        # 3. Tool inventory
        all_tools = sorted([m.replace('_tool_', '') for m in dir(self) if m.startswith('_tool_')])
        results["tools"]["count"] = len(all_tools)
        results["tools"]["list"] = all_tools

        # 4. Test specific tool handler exists
        if test_tool:
            handler = getattr(self, f'_tool_{test_tool}', None)
            if handler:
                results["tools"][f"test_{test_tool}"] = f"✅ Handler exists ({handler.__doc__[:60] if handler.__doc__ else 'no docstring'})"
            else:
                results["tools"][f"test_{test_tool}"] = "❌ Handler NOT found"

        # 5. File health
        for name, path in SIAI_ALLOWED_FILES.items():
            if os.path.exists(path):
                stat = os.stat(path)
                results["health"][name] = {
                    "size": format_size(stat.st_size),
                    "lines": sum(1 for _ in open(path, 'r', encoding='utf-8', errors='replace')),
                    "ok": True
                }
            else:
                results["health"][name] = {"ok": False, "error": "File missing"}

        # 6. Backup integrity
        backup_count = len([f for f in os.listdir(SIAI_BACKUP_DIR) if f.endswith('.bak')])
        results["backups"] = backup_count

        all_ok = all(v == "✅ OK" for v in results["syntax"].values()) and \
                 all(v == "✅" for v in results["imports"].values())

        return {
            "success": True,
            "overall": "✅ All tests passed" if all_ok else "⚠️ Issues found",
            "data": results,
            "tool_count": len(all_tools),
            "message": f"Self-test: {'✅ PASS' if all_ok else '⚠️ ISSUES'} — {len(all_tools)} tools, {backup_count} backups"
        }

    # ---- SIAI Tool: Goals ----

    async def _tool_siai_goals(self, args: Dict) -> Dict:
        """Manage improvement goals tracked in SIAI.md."""
        action = args.get('action', 'list').lower()
        goal_text = args.get('goal', '')
        priority = args.get('priority', 'medium').lower()

        goals_file = os.path.join(SIAI_BACKUP_DIR, "siai_goals.json")

        # Load existing goals
        goals = []
        if os.path.exists(goals_file):
            try:
                with open(goals_file, 'r', encoding='utf-8') as f:
                    goals = json.load(f)
            except Exception:
                goals = []

        if action == 'list':
            if not goals:
                return {"success": True, "goals": [], "message": "No improvement goals set. Use action='add' to create one."}
            pending = [g for g in goals if g.get('status') != 'done']
            done = [g for g in goals if g.get('status') == 'done']
            return {
                "success": True,
                "pending": pending,
                "completed": done,
                "total": len(goals),
                "message": f"📋 {len(pending)} pending goals, {len(done)} completed"
            }

        elif action == 'add':
            if not goal_text:
                return {"success": False, "error": "Goal text required. Args: {\"action\": \"add\", \"goal\": \"...\", \"priority\": \"high|medium|low\"}"}
            new_goal = {
                "id": len(goals) + 1,
                "goal": goal_text,
                "priority": priority,
                "status": "pending",
                "created": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "completed_at": None,
            }
            goals.append(new_goal)
            with open(goals_file, 'w', encoding='utf-8') as f:
                json.dump(goals, f, indent=2)
            safe_print(f"  [SIAI] 🎯 Goal added: [{priority.upper()}] {goal_text}")
            return {
                "success": True,
                "goal": new_goal,
                "message": f"🎯 Goal #{new_goal['id']} added: [{priority.upper()}] {goal_text}"
            }

        elif action == 'complete':
            if not goal_text:
                return {"success": False, "error": "Specify goal text or ID to complete"}
            found = False
            for g in goals:
                if (str(g.get('id')) == str(goal_text)) or (goal_text.lower() in g.get('goal', '').lower()):
                    g['status'] = 'done'
                    g['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    found = True
                    safe_print(f"  [SIAI] ✅ Goal completed: {g['goal']}")
                    break
            if not found:
                return {"success": False, "error": f"Goal not found: {goal_text}"}
            with open(goals_file, 'w', encoding='utf-8') as f:
                json.dump(goals, f, indent=2)
            return {"success": True, "message": f"✅ Goal completed: {goal_text}"}

        elif action == 'remove':
            if not goal_text:
                return {"success": False, "error": "Specify goal text or ID to remove"}
            before = len(goals)
            goals = [g for g in goals if str(g.get('id')) != str(goal_text) and goal_text.lower() not in g.get('goal', '').lower()]
            if len(goals) == before:
                return {"success": False, "error": f"Goal not found: {goal_text}"}
            with open(goals_file, 'w', encoding='utf-8') as f:
                json.dump(goals, f, indent=2)
            return {"success": True, "message": f"🗑️ Goal removed: {goal_text}"}

        return {"success": False, "error": f"Unknown action: {action}. Use list|add|complete|remove"}

    # ---- SIAI Tool: Checkpoint (Named Versions) ----

    async def _tool_siai_checkpoint(self, args: Dict) -> Dict:
        """Create, restore, or list named version checkpoints."""
        action = args.get('action', 'list').lower()
        name = args.get('name', '')
        shortname = args.get('file', 'namu_ai.py')

        filepath = self._siai_resolve(shortname)
        if not filepath:
            return {"success": False, "error": f"Access denied: '{shortname}' not in SIAI allowlist"}

        checkpoint_dir = os.path.join(SIAI_BACKUP_DIR, "checkpoints")
        os.makedirs(checkpoint_dir, exist_ok=True)

        if action == 'save':
            if not name:
                return {"success": False, "error": "Checkpoint name required. Example: {\"action\": \"save\", \"name\": \"v1.2-fixed-search\"}"}
            if not os.path.exists(filepath):
                return {"success": False, "error": f"File not found: {shortname}"}

            # Sanitize name
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
            checkpoint_path = os.path.join(checkpoint_dir, f"{os.path.basename(filepath)}.{safe_name}.checkpoint")

            import shutil
            shutil.copy2(filepath, checkpoint_path)

            # Save metadata
            meta_path = checkpoint_path + ".meta"
            meta = {
                "name": name,
                "file": shortname,
                "created": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "size": os.path.getsize(filepath),
                "lines": sum(1 for _ in open(filepath, 'r', encoding='utf-8', errors='replace')),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)

            safe_print(f"  [SIAI] 📌 Checkpoint saved: {name} ({shortname})")
            await self._siai_auto_log(shortname, "checkpoint", f"Saved checkpoint: {name}", 0, meta["size"])

            return {
                "success": True,
                "name": name,
                "file": shortname,
                "path": checkpoint_path,
                "message": f"📌 Checkpoint '{name}' saved for {shortname}"
            }

        elif action == 'restore':
            if not name:
                return {"success": False, "error": "Checkpoint name required to restore"}

            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
            checkpoint_path = os.path.join(checkpoint_dir, f"{os.path.basename(filepath)}.{safe_name}.checkpoint")

            if not os.path.exists(checkpoint_path):
                # Try fuzzy match
                candidates = [f for f in os.listdir(checkpoint_dir) if f.startswith(os.path.basename(filepath)) and f.endswith('.checkpoint')]
                return {
                    "success": False,
                    "error": f"Checkpoint '{name}' not found for {shortname}",
                    "available": [c.split('.', 1)[1].replace('.checkpoint', '') for c in candidates]
                }

            # Backup current before restoring
            self._siai_backup(filepath)

            import shutil
            shutil.copy2(checkpoint_path, filepath)
            safe_print(f"  [SIAI] ⏪ Restored checkpoint: {name}")
            await self._siai_auto_log(shortname, "checkpoint_restore", f"Restored to checkpoint: {name}", 0, 0)

            return {
                "success": True,
                "name": name,
                "file": shortname,
                "message": f"⏪ Restored {shortname} to checkpoint '{name}'"
            }

        elif action == 'list':
            checkpoints = []
            for f in sorted(os.listdir(checkpoint_dir)):
                if f.endswith('.checkpoint'):
                    meta_path = os.path.join(checkpoint_dir, f + ".meta")
                    if os.path.exists(meta_path):
                        with open(meta_path, 'r', encoding='utf-8') as mf:
                            meta = json.load(mf)
                        checkpoints.append(meta)
                    else:
                        parts = f.rsplit('.checkpoint', 1)[0].split('.', 1)
                        checkpoints.append({
                            "name": parts[1] if len(parts) > 1 else f,
                            "file": parts[0],
                            "size": os.path.getsize(os.path.join(checkpoint_dir, f))
                        })

            if not checkpoints:
                return {"success": True, "checkpoints": [], "message": "No checkpoints saved yet. Use action='save' to create one."}

            return {
                "success": True,
                "checkpoints": checkpoints,
                "total": len(checkpoints),
                "message": f"📌 {len(checkpoints)} checkpoint(s) saved"
            }

        return {"success": False, "error": f"Unknown action: {action}. Use save|restore|list"}

    # ---- SIAI Tool: Metrics (Code Analysis) ----

    async def _tool_siai_metrics(self, args: Dict) -> Dict:
        """Analyze code metrics: line count, tool count, function count, complexity."""
        target_file = args.get('file', '')

        files_to_analyze = {}
        if target_file:
            filepath = self._siai_resolve(target_file)
            if not filepath:
                return {"success": False, "error": f"Access denied: '{target_file}' not in SIAI allowlist"}
            files_to_analyze = {target_file: filepath}
        else:
            files_to_analyze = dict(SIAI_ALLOWED_FILES)

        metrics = {}
        total_lines = 0
        total_functions = 0
        total_classes = 0

        for shortname, fullpath in files_to_analyze.items():
            if not os.path.exists(fullpath):
                metrics[shortname] = {"exists": False}
                continue

            with open(fullpath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            file_metrics = {
                "lines": len(lines),
                "size": format_size(os.path.getsize(fullpath)),
                "blank_lines": sum(1 for l in lines if not l.strip()),
                "comment_lines": 0,
                "code_lines": 0,
            }

            if fullpath.endswith('.py'):
                functions = []
                classes = []
                tools = []
                imports = 0
                docstrings = 0
                in_docstring = False

                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        file_metrics["comment_lines"] += 1
                    elif stripped.startswith('"""') or stripped.startswith("'''"):
                        docstrings += 1
                        in_docstring = not in_docstring
                    elif stripped.startswith('import ') or stripped.startswith('from '):
                        imports += 1
                    elif stripped.startswith('class ') and '(' in stripped:
                        classes.append(stripped.split('(')[0].replace('class ', '').strip())
                    elif stripped.startswith('def ') or stripped.startswith('async def '):
                        name = stripped.split('(')[0].replace('async ', '').replace('def ', '').strip()
                        functions.append(name)
                        if name.startswith('_tool_'):
                            tools.append(name.replace('_tool_', ''))
                    elif re.match(r'^\s+(async )?def ', stripped):
                        name = stripped.split('(')[0].replace('async ', '').replace('def ', '').strip()
                        functions.append(name)
                        if name.startswith('_tool_'):
                            tools.append(name.replace('_tool_', ''))

                file_metrics["code_lines"] = len(lines) - file_metrics["blank_lines"] - file_metrics["comment_lines"]
                file_metrics["functions"] = len(functions)
                file_metrics["classes"] = len(classes)
                file_metrics["class_names"] = classes
                file_metrics["tools"] = len(tools)
                file_metrics["tool_names"] = tools
                file_metrics["imports"] = imports
                file_metrics["code_ratio"] = f"{file_metrics['code_lines'] / max(len(lines), 1) * 100:.1f}%"

                total_functions += len(functions)
                total_classes += len(classes)

            elif fullpath.endswith('.html'):
                file_metrics["comment_lines"] = sum(1 for l in lines if '<!--' in l)
                file_metrics["code_lines"] = len(lines) - file_metrics["blank_lines"]
                tags = sum(1 for l in lines if '<' in l and '>' in l)
                file_metrics["html_tags_approx"] = tags

            elif fullpath.endswith('.md'):
                headings = [l.strip() for l in lines if l.strip().startswith('#')]
                file_metrics["headings"] = len(headings)
                file_metrics["heading_list"] = headings[:20]

            total_lines += len(lines)
            metrics[shortname] = file_metrics

        summary = {
            "total_lines": total_lines,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "files_analyzed": len(metrics),
        }

        # Check for tool count specifically (useful metric)
        if "namu_ai.py" in metrics:
            tool_count = metrics["namu_ai.py"].get("tools", 0)
            summary["total_tools"] = tool_count

        return {
            "success": True,
            "summary": summary,
            "files": metrics,
            "message": f"📊 Metrics: {total_lines} lines, {total_functions} functions, {total_classes} classes across {len(metrics)} files"
        }

    # ---- SIAI Internal: Auto-log changes ----

    async def _siai_auto_log(self, filename: str, action: str, description: str, old_size: int, new_size: int):
        """Automatically append a log entry to SIAI.md after any file modification."""
        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = f"\n### [{ts}] Auto: {action} → {filename}\n"
            entry += f"**Action:** `{action}` on `{filename}`\n"
            entry += f"**Description:** {description}\n"
            if old_size and new_size:
                entry += f"**Size:** {old_size} → {new_size} chars\n"
            elif new_size:
                entry += f"**Size:** {new_size} chars written\n"
            entry += "\n---\n"

            existing = ""
            if os.path.exists(SIAI_LOG_FILE):
                with open(SIAI_LOG_FILE, 'r', encoding='utf-8') as f:
                    existing = f.read()

            if not existing.strip():
                existing = """# 🧠 Namu AI — Self-Improvement Log (SIAI)

> This file is automatically maintained by Namu AI's self-improvement system.
> Every code change, patch, and improvement is logged here with timestamps.

## How This Works
- Namu AI can read/write its own code files (sandboxed to 4 files).
- Every modification creates a backup in `siai_backups/`.
- This log tracks what was changed and why.

---

## Improvement History

"""

            with open(SIAI_LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(existing + entry)
        except Exception as e:
            log_debug(f"SIAI auto-log error: {e}")


# =============================================================================
# OpenRouter AI Client
# =============================================================================

class NamuAI:
    """AI-powered agent — personal Perplexity with scraping, OSINT, and tool execution."""

    DEFAULT_MODELS = [
        "openrouter/free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super:free",
    ]

    # Model shorthand aliases for /model command
    MODEL_ALIASES = {
        'nvidia': NVIDIA_GLM_MODEL_ID, 'glm': NVIDIA_GLM_MODEL_ID,
        'glm4': NVIDIA_GLM_MODEL_ID, 'glm4.7': NVIDIA_GLM_MODEL_ID,
        'gemma': 'google/gemma-4-31b-it:free', 'gemma4': 'google/gemma-4-31b-it:free',
        'nemotron': 'nvidia/nemotron-3-super:free',
        'free': 'openrouter/free', 'auto': 'openrouter/free',
    }

    def __init__(self):
        self.api_keys = []
        key1 = os.environ.get('OPENROUTER_API_KEY', '')
        key2 = os.environ.get('OPENROUTER_API_KEY1', '')
        if key1 and key1 != 'sk-or-v1-your-key-here':
            self.api_keys.append(key1)
        if key2 and key2 != 'sk-or-v1-your-key-here':
            self.api_keys.append(key2)
        self.api_key = self.api_keys[0] if self.api_keys else ''
        self.messages: List[Dict[str, str]] = []
        self.tool_executor = ToolExecutor()
        # Instance-level model list — allows per-session model switching
        self.MODELS = list(self.DEFAULT_MODELS)
        # By default, use openrouter/free for snappy responses.
        # User can switch to reasoning using `/model nvidia`.
        # if _nvidia_client:
        #     self.MODELS.insert(0, NVIDIA_GLM_MODEL_ID)
        self.session: Optional[aiohttp.ClientSession] = None
        self._topic = "general"
        self._blacklisted_models: set = set()  # Models that failed this session (404/gone)
        self._request_count = 0
        self._start_time = datetime.now()

    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                connector=aiohttp.TCPConnector(ssl=False)
            )

    async def cleanup(self):
        await self.tool_executor.cleanup()
        if self.session and not self.session.closed:
            await self.session.close()

    def _check_api_key(self) -> bool:
        # NVIDIA GLM4.7 works without OpenRouter
        if _nvidia_client:
            return True
        if not self.api_key or self.api_key == 'sk-or-v1-your-key-here':
            safe_print("\n  [X] No AI API keys configured!")
            safe_print("  Setup either:")
            safe_print("    Option A — NVIDIA (recommended):")
            safe_print("      1. Set NVIDIA_API_KEY=nvapi-... in .env")
            safe_print("    Option B — OpenRouter:")
            safe_print("      1. Go to https://openrouter.ai/keys")
            safe_print("      2. Set OPENROUTER_API_KEY=sk-or-v1-... in .env")
            safe_print("    Then restart the tool.")
            return False
        return True

    def _is_nvidia_selected(self) -> bool:
        """Check if the currently selected primary model is NVIDIA GLM4.7."""
        return bool(self.MODELS and self.MODELS[0] == NVIDIA_GLM_MODEL_ID)

    async def chat(self, user_message: str) -> str:
        """Send message to AI and get response. Perplexity-style search + tool execution."""
        import time as _time
        _start = _time.monotonic()
        self._request_count += 1

        if not self._check_api_key():
            return "API key not configured. See instructions above."
        # --- Programmatic override: Force web_scrape for URLs ---
        import re
        content_to_send = user_message
        url_pattern = re.compile(r'(?:https?://)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)')
        if url_pattern.search(user_message):
            content_to_send += "\n\n(System Hint: The user provided a URL/domain name. You MUST use the `web_scrape` tool on it immediately. Do NOT use `web_search`.)"
            
        self.messages.append({"role": "user", "content": content_to_send})

        # Smart context window — keep last 8 pairs, drop bloated tool JSON from old messages
        recent = self._build_context_window()

        # Show which model is processing
        primary = self.MODELS[0] if self.MODELS else 'unknown'
        model_label = 'NVIDIA GLM4.7' if primary == NVIDIA_GLM_MODEL_ID else primary
        safe_print(f"  ⚡ Model: {model_label}")

        # Get AI response — route based on selected model
        if self._is_nvidia_selected():
            ai_response = await self._call_nvidia_glm(recent)
        else:
            ai_response = await self._call_openrouter(recent)
        if not ai_response:
            return "All AI models failed. Please check your API key or try again."

        self.messages.append({"role": "assistant", "content": ai_response})

        # Auto-detect topic
        self._topic = self._extract_topic(user_message)

        # --- Extract the AI's thinking/narrative text (for tool detection) ---
        ai_thinking = self._strip_json_blocks(ai_response)

        # --- Check for TASK PLAN (sub-agent mode) ---
        task_plan = self._parse_task_plan(ai_response)
        if task_plan:
            safe_print(f"  🤖 Task plan detected: {task_plan.get('task', 'multi-step task')}")
            return await self._execute_task_plan(task_plan)

        # --- Check for MULTIPLE tool calls ---
        tool_calls = self._parse_all_tool_calls(ai_response)

        if not tool_calls:
            return ai_response  # Just a chat message

        # Show tool detection
        tool_names = [tc.get('tool', '?') for tc in tool_calls]
        safe_print(f"  🔧 Tools detected: {', '.join(tool_names)}")

        # === MULTI-TOOL EXECUTION LOOP ===
        all_results = []
        prev_result = None
        final_text_parts = []

        for i, tool_call in enumerate(tool_calls):
            tool_name = tool_call.get('tool', '')
            tool_args = tool_call.get('args', {})

            # Inject previous result where "USE_PREVIOUS_RESULT" is used
            tool_args = self._inject_previous_result(tool_args, prev_result)

            step_label = f"[{i+1}/{len(tool_calls)}]" if len(tool_calls) > 1 else ""
            safe_print(f"\n  [AGENT] {step_label} Executing: {tool_name}")
            if tool_args:
                for k, v in tool_args.items():
                    val_str = str(v)[:60]
                    safe_print(f"          {k}: {val_str}")

            # Execute
            result = await self.tool_executor.execute(tool_name, tool_args)
            prev_result = result
            all_results.append({"tool": tool_name, "result": result})

            # Auto-save successful results
            if result.get('success', False):
                await self._auto_save(tool_name, result)

            # Show inline status
            if result.get('success'):
                filepath = result.get('filepath', '')
                msg = result.get('message', f"✓ {tool_name} OK")
                safe_print(f"  [OK] {msg}")
                if filepath:
                    safe_print(f"  [PATH] {filepath}")
            else:
                err = result.get('error', 'Unknown error')
                safe_print(f"  [FAIL] {tool_name}: {err}")
                # Don't continue chain if a critical tool fails
                if tool_name not in ('open_file', 'open_folder', 'open_url', 'launch_app'):
                    final_text_parts.append(f"Step {i+1} ({tool_name}) failed: {err}")
                    break

            final_text_parts.append(f"Step {i+1}: {tool_name} — " +
                                    (result.get('message', 'Done') if result.get('success') else result.get('error', 'Failed')))

        # --- Summarize with AI ---
        safe_print(f"  📝 Synthesizing answer from {len(all_results)} tool result(s)...")
        result_summary = "\n".join(final_text_parts)

        # Build compact data for ALL results (not just the last one)
        all_compact = {}
        for entry in all_results:
            tname = entry['tool']
            tresult = entry['result']
            all_compact[tname] = self._compact_result(tresult) if isinstance(tresult, dict) else tresult

        summary_msg = (f"Executed {len(all_results)} tools:\n{result_summary}\n\n"
                       f"All results:\n{json.dumps(all_compact, indent=1, default=str)[:4000]}")
        self.messages.append({"role": "user", "content": summary_msg})

        summary_system = ("You are summarizing tool execution results for the user. "
                          "Present a clear, Perplexity-style answer:\n"
                          "- Lead with a direct answer based on the ACTUAL data returned\n"
                          "- Use inline citations [1], [2] referencing URLs from results\n"
                          "- Use bullet points for structured data\n"
                          "- End with 'Sources:' listing [1] title - url\n"
                          "- NEVER fabricate or paraphrase with old knowledge\n"
                          "- If results contain file paths, always mention them\n"
                          "- Keep it concise but information-dense")
        if self._is_nvidia_selected():
            # Disable reasoning for the synthesis step to save ~80s of unnecessary thinking
            summary = await self._call_nvidia_glm(
                self.messages[-6:], 
                system_override=summary_system,
                disable_reasoning=True
            )
        else:
            summary = await self._call_openrouter(self.messages[-6:], system_override=summary_system)

        if summary:
            self.messages.append({"role": "assistant", "content": summary})
            return summary
        else:
            return f"Completed {len(all_results)} steps:\n" + result_summary

    # --- Sub-Agent: Task Plan Executor ---

    def _parse_task_plan(self, response: str) -> Optional[Dict]:
        """Extract a task_plan from AI response."""
        # Look for task_plan tool call
        for tc in self._parse_all_tool_calls(response):
            if tc.get('tool') == 'task_plan':
                return tc.get('args', {})
        return None

    async def _execute_task_plan(self, plan: Dict) -> str:
        """Execute a multi-step task plan as a sub-agent."""
        task_name = plan.get('task', 'Unnamed Task')
        steps = plan.get('steps', [])

        if not steps:
            return "Task plan has no steps."

        safe_print(f"\n  ┌─────────────────────────────────────────────┐")
        safe_print(f"  │  🤖 SUB-AGENT: {task_name[:38]:<38} │")
        safe_print(f"  │  Steps: {len(steps):<41} │")
        safe_print(f"  └─────────────────────────────────────────────┘")

        prev_result = None
        step_results = []
        step_log = []

        for step_info in steps:
            step_num = step_info.get('step', len(step_results) + 1)
            tool_name = step_info.get('tool', '')
            tool_args = step_info.get('args', {})
            description = step_info.get('description', tool_name)

            safe_print(f"\n  ── Step {step_num}/{len(steps)}: {description} ──")

            if not tool_name:
                safe_print(f"  [SKIP] No tool specified")
                step_log.append(f"Step {step_num}: Skipped (no tool)")
                continue

            # Inject previous result
            tool_args = self._inject_previous_result(tool_args, prev_result)

            # Show what's being executed
            safe_print(f"  [AGENT] Executing: {tool_name}")
            if tool_args:
                for k, v in tool_args.items():
                    safe_print(f"          {k}: {str(v)[:60]}")

            # Execute
            result = await self.tool_executor.execute(tool_name, tool_args)
            prev_result = result
            step_results.append({"step": step_num, "tool": tool_name, "result": result})

            # Auto-save
            if result.get('success', False):
                await self._auto_save(tool_name, result)
                msg = result.get('message', result.get('summary', 'Done')[:100] if result.get('summary') else 'Done')
                filepath = result.get('filepath', '')
                safe_print(f"  [OK] {msg[:120]}")
                if filepath:
                    safe_print(f"  [PATH] {filepath}")
                step_log.append(f"Step {step_num}: ✓ {description}" +
                               (f" → {filepath}" if filepath else ""))
            else:
                err = result.get('error', 'Failed')
                safe_print(f"  [FAIL] {err}")
                step_log.append(f"Step {step_num}: ✗ {description} — {err}")
                # Continue plan even if non-critical step fails
                if tool_name not in ('open_file', 'open_folder', 'open_url', 'launch_app', 'save_json'):
                    safe_print(f"  [ABORT] Critical step failed, stopping plan.")
                    break

        safe_print(f"\n  ── Task Complete: {len(step_results)}/{len(steps)} steps ──")

        # Summarize via AI
        plan_summary = f"Task: {task_name}\nSteps completed: {len(step_results)}/{len(steps)}\n" + "\n".join(step_log)
        self.messages.append({"role": "user", "content": f"Sub-agent plan results:\n{plan_summary}"})

        plan_summary_system = "Summarize the completed task plan results. List each step's outcome, file paths, and key findings. Be concise."
        if self._is_nvidia_selected():
            summary = await self._call_nvidia_glm(self.messages[-6:], system_override=plan_summary_system)
        else:
            summary = await self._call_openrouter(self.messages[-6:], system_override=plan_summary_system)

        if summary:
            self.messages.append({"role": "assistant", "content": summary})
            return summary
        return f"Task '{task_name}' completed:\n" + "\n".join(step_log)

    def _inject_previous_result(self, args: Dict, prev_result: Optional[Dict]) -> Dict:
        """Replace USE_PREVIOUS_RESULT placeholders with actual data."""
        if not prev_result or not args:
            return args

        injected = {}
        for k, v in args.items():
            if isinstance(v, str):
                if v == 'USE_PREVIOUS_RESULT':
                    injected[k] = prev_result
                elif v.startswith('USE_PREVIOUS_RESULT.'):
                    # e.g. USE_PREVIOUS_RESULT.filepath
                    field = v.split('.', 1)[1]
                    injected[k] = prev_result.get(field, v)
                else:
                    injected[k] = v
            else:
                injected[k] = v
        return injected

    def _build_context_window(self) -> List[Dict]:
        """Smart context window: keep last 8 user/assistant pairs, compact old tool JSON."""
        if len(self.messages) <= 16:
            return list(self.messages)

        # Keep last 16 messages (8 pairs)
        recent = self.messages[-16:]

        # For older messages in the window, strip bloated tool result JSON
        compacted = []
        for msg in recent:
            if msg['role'] == 'user' and len(msg.get('content', '')) > 2000:
                # Truncate very long tool result dumps
                content = msg['content']
                if '"success"' in content and '"data"' in content:
                    content = content[:1500] + '\n... [tool results truncated for context] ...'
                compacted.append({"role": msg['role'], "content": content})
            else:
                compacted.append(msg)
        return compacted

    async def _call_openrouter(self, messages: List[Dict], system_override: str = None) -> Optional[str]:
        """Call OpenRouter API with model blacklisting, key fallback, and clean errors."""
        await self._ensure_session()

        system_prompt = system_override or _build_system_prompt()
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        keys_to_try = self.api_keys if self.api_keys else [self.api_key]

        # Filter out blacklisted models
        available_models = [m for m in self.MODELS
                           if m != NVIDIA_GLM_MODEL_ID and m not in self._blacklisted_models]

        if not available_models and not _nvidia_client:
            safe_print("  [!] All OpenRouter models blacklisted this session. Try /model to switch.")
            return None

        for api_key in keys_to_try:
            if not api_key:
                continue

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://github.com/namu-ai-agent',
                'X-Title': 'Namu AI Agent',
            }

            for model in available_models:
                safe_print(f"  🌐 Querying: {model}...")
                try:
                    payload = json.dumps({
                        "model": model,
                        "messages": full_messages,
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    })

                    async with self.session.post(
                        'https://openrouter.ai/api/v1/chat/completions',
                        data=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=45)
                    ) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            if 'error' in data:
                                err = data['error']
                                err_msg = err.get('message', str(err)) if isinstance(err, dict) else str(err)
                                log_debug(f"Model {model} error: {err_msg}")
                                self._blacklisted_models.add(model)
                                continue

                            choices = data.get('choices', [])
                            if choices:
                                content = choices[0].get('message', {}).get('content', '')
                                if content:
                                    return content
                        elif r.status in (404, 410):
                            # Model gone — blacklist for session
                            self._blacklisted_models.add(model)
                            safe_print(f"  ⚠️  Model unavailable, trying next...")
                        elif r.status == 429:
                            safe_print(f"  ⚠️  Rate limited, waiting...")
                            await asyncio.sleep(2)  # Brief backoff
                        elif r.status in (401, 403):
                            log_debug(f"API key rejected for {model}")
                            break  # Try next key

                except asyncio.TimeoutError:
                    safe_print(f"  ⚠️  Model timed out, trying next...")
                except Exception as e:
                    safe_print(f"  ⚠️  Model error, trying next...")
                    log_debug(f"OpenRouter {model} error: {e}")

        # --- Fallback: NVIDIA GLM4.7 ---
        if _nvidia_client:
            safe_print(f"  🔄 Falling back to NVIDIA GLM4.7...")
        nvidia_resp = await self._call_nvidia_glm(messages, system_override)
        if nvidia_resp:
            return nvidia_resp

        return None

    def _parse_all_tool_calls(self, response: str) -> List[Dict]:
        """Extract ALL tool call JSONs from AI response (supports multi-tool)."""
        tool_calls = []

        # Find all JSON blocks in code fences
        fence_pattern = r'```(?:json)?\s*\n?\s*(\{[^`]+?\})\s*\n?\s*```'
        for match in re.finditer(fence_pattern, response, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                if 'tool' in data:
                    tool_calls.append(data)
            except json.JSONDecodeError:
                continue

        # Also check for bare JSON with "tool" key (no code fence)
        if not tool_calls:
            bare_pattern = r'(\{"tool"\s*:\s*"[^"]+"[^}]*\})'
            for match in re.finditer(bare_pattern, response, re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                    if 'tool' in data:
                        tool_calls.append(data)
                except json.JSONDecodeError:
                    continue

        return tool_calls

    def _parse_tool_call(self, response: str) -> Optional[Dict]:
        """Extract first tool call (backward compat)."""
        calls = self._parse_all_tool_calls(response)
        return calls[0] if calls else None

    def _strip_json_blocks(self, text: str) -> str:
        """Remove JSON code blocks from AI response, keeping the narrative text."""
        # Remove fenced JSON blocks
        cleaned = re.sub(r'```(?:json)?\s*\n?\s*\{[^`]+?\}\s*\n?\s*```', '', text, flags=re.DOTALL)
        # Remove bare {"tool":...} JSON
        cleaned = re.sub(r'\{"tool"\s*:\s*"[^"]+"[^}]*\}', '', cleaned)
        # Clean up excess whitespace
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def _extract_topic(self, message: str) -> str:
        """Extract topic name from user message for folder organization."""
        # Try to find domain/URL
        url_match = re.search(r'https?://(?:www\.)?([^/\s]+)', message)
        if url_match:
            return sanitize_filename(url_match.group(1).replace('.', '_'))[:40]

        # Use first meaningful words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', message)
        skip = {'the', 'and', 'for', 'from', 'with', 'this', 'that', 'can', 'you',
                'scrape', 'download', 'search', 'find', 'get', 'show', 'please',
                'want', 'need', 'help', 'about', 'what', 'how'}
        topic_words = [w for w in words if w.lower() not in skip][:3]
        if topic_words:
            return sanitize_filename('_'.join(topic_words))[:40]

        return "general"

    def _compact_result(self, result: Dict) -> Dict:
        """Compact result to save API tokens while preserving key OSINT data."""
        # Keys whose values should be preserved more generously
        IMPORTANT_KEYS = {
            'verified_profiles', 'found_profiles', 'email_reputation',
            'github_profile', 'reddit_profile', 'gravatar_profile',
            'geolocation', 'message', 'summary', 'error',
            'check_diagnostics', 'title', 'filepath', 'url',
        }
        compact = {}
        for k, v in result.items():
            if k in IMPORTANT_KEYS:
                # Preserve important fields with higher limits
                if isinstance(v, str) and len(v) > 2000:
                    compact[k] = v[:2000] + '...'
                elif isinstance(v, dict) and len(json.dumps(v, default=str)) > 3000:
                    compact[k] = {sk: str(sv)[:500] for sk, sv in list(v.items())[:20]}
                else:
                    compact[k] = v
            elif isinstance(v, str) and len(v) > 500:
                compact[k] = v[:500] + '...'
            elif isinstance(v, list) and len(v) > 15:
                compact[k] = v[:15]
                compact[f'{k}_total'] = len(v)
            elif isinstance(v, dict) and len(json.dumps(v, default=str)) > 1000:
                compact[k] = {sk: str(sv)[:300] for sk, sv in list(v.items())[:10]}
            else:
                compact[k] = v
        return compact

    async def _auto_save(self, tool_name: str, result: Dict):
        """Auto-save tool results to topic folder."""
        try:
            topic_dir = os.path.join(AI_DATA_DIR, self._topic)
            os.makedirs(topic_dir, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = os.path.join(topic_dir, f"{tool_name}_{ts}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)
            log_debug(f"Auto-saved: {filepath}")
        except Exception as e:
            log_debug(f"Auto-save error: {e}")

    def clear_history(self):
        """Clear conversation history."""
        self.messages.clear()

    def set_model(self, model_id: str):
        """Set the primary model for chat. The selected model becomes first in the list."""
        if not model_id:
            return
        # Remove from current position if present
        self.MODELS = [m for m in self.MODELS if m != model_id]
        # Insert at front as primary
        self.MODELS.insert(0, model_id)
        if model_id == NVIDIA_GLM_MODEL_ID:
            safe_print(f"  [MODEL] Switched to: NVIDIA GLM4.7 (direct)")
        else:
            safe_print(f"  [MODEL] Switched to: {model_id}")

    async def _call_nvidia_glm(self, messages: List[Dict], system_override: str = None, disable_reasoning: bool = False) -> Optional[str]:
        """Call NVIDIA GLM4.7 via OpenAI-compatible API. Runs sync stream in thread to avoid blocking."""
        if not _nvidia_client:
            return None

        system_prompt = system_override or _build_system_prompt()
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        def _sync_stream():
            """Run in a thread so the sync OpenAI SDK doesn't block the event loop."""
            collected_content = []
            reasoning_chunk_count = 0
            reasoning_shown = False
            content_started = False

            try:
                completion = _nvidia_client.chat.completions.create(
                    model="z-ai/glm4.7",
                    messages=full_messages,
                    temperature=0.7,
                    top_p=0.95,
                    max_tokens=16384,
                    extra_body={"chat_template_kwargs": {"enable_thinking": not disable_reasoning, "clear_thinking": False}},
                    stream=True,
                )

                for chunk in completion:
                    if not getattr(chunk, "choices", None):
                        continue
                    if len(chunk.choices) == 0 or getattr(chunk.choices[0], "delta", None) is None:
                        continue
                    delta = chunk.choices[0].delta

                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        reasoning_chunk_count += 1
                        if not reasoning_shown:
                            safe_print(f"  💭 Reasoning...")
                            reasoning_shown = True
                        # Show periodic progress every ~80 chunks
                        if reasoning_chunk_count % 80 == 0:
                            safe_print(f"  💭 Still reasoning... ({reasoning_chunk_count} steps)")

                    content = getattr(delta, "content", None)
                    if content is not None:
                        if not content_started:
                            safe_print(f"  ✍️  Generating response...")
                            content_started = True
                        collected_content.append(content)

                return "".join(collected_content) if collected_content else None

            except Exception as e:
                safe_print(f"  [!] NVIDIA GLM4.7: {e}")
                return None

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_sync_stream),
                timeout=240  # 4 min max for GLM reasoning
            )
            return result
        except asyncio.TimeoutError:
            safe_print(f"  ⚠️  NVIDIA GLM4.7 timed out (240s)")
            return None
        except Exception as e:
            safe_print(f"  [!] NVIDIA GLM4.7: {e}")
            return None


# =============================================================================
# Chat CLI
# =============================================================================

def _print_chat_header():
    # Determine engine description
    has_or = bool(os.environ.get('OPENROUTER_API_KEY', ''))
    has_nv = _nvidia_client is not None
    if has_or and has_nv:
        engine_line = 'NVIDIA GLM4.7 + OpenRouter'
    elif has_nv:
        engine_line = 'NVIDIA GLM4.7'
    elif has_or:
        engine_line = 'OpenRouter'
    else:
        engine_line = 'No API configured'

    safe_print(f"""
{'═'*66}
{'NAMU AI':^66}
{'Personal Research Agent':^66}
{'─'*66}
{f'Engine: {engine_line}':^66}
{'═'*66}

  Ask me anything — I search the web, scrape sites, run OSINT,
  download media, generate reports, and present cited answers.

  Commands: /help  /model  /status  /tools  /clear  /siai  0 (exit)
{'─'*66}
""")


async def run_namu_ai_chat():
    """Main entry point for the Namu AI chat interface."""
    _print_chat_header()

    agent = NamuAI()

    # Show active model
    primary = agent.MODELS[0] if agent.MODELS else 'none'
    model_name = 'NVIDIA GLM4.7' if primary == NVIDIA_GLM_MODEL_ID else primary
    has_search = bool(os.environ.get('SERPER_API_KEY', ''))
    safe_print(f"  Model: {model_name}")
    safe_print(f"  Search: {'✓ Serper' if has_search else '✗ No search API (set SERPER_API_KEY)'}")
    safe_print(f"  Tools: {len([m for m in dir(agent.tool_executor) if m.startswith('_tool_')])} available")

    try:
        while True:
            try:
                safe_print("")
                user_input = input("  You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            # Handle commands (also works through natural language — AI handles it)
            lower = user_input.lower().strip()

            if lower in ('0', '/exit', '/quit', 'exit', 'quit', 'bye'):
                safe_print("\n  [Namu] Goodbye! 👋\n")
                break

            if lower in ('/clear', '/reset'):
                agent.clear_history()
                safe_print("  [OK] Chat history cleared.\n")
                continue

            # /model — switch model from CLI
            if lower == '/model' or lower.startswith('/model '):
                parts = user_input.strip().split(None, 1)
                if len(parts) < 2:
                    cur = agent.MODELS[0] if agent.MODELS else 'none'
                    cur_name = 'NVIDIA GLM4.7' if cur == NVIDIA_GLM_MODEL_ID else cur
                    safe_print(f"\n  ┌─ Model Selection ─────────────────────────────────────┐")
                    safe_print(f"  │  Active: {cur_name:<48}│")
                    safe_print(f"  ├──────────────────────────────────────────────────────────┤")
                    if _nvidia_client:
                        marker = " ← active" if cur == NVIDIA_GLM_MODEL_ID else ""
                        safe_print(f"  │  nvidia  → NVIDIA GLM4.7 (reasoning){marker:<20}│")
                    for m in agent.DEFAULT_MODELS:
                        alias = next((a for a, v in agent.MODEL_ALIASES.items() if v == m), m.split('/')[0])
                        marker = " ← active" if cur == m else ""
                        short = m[:45]
                        safe_print(f"  │  {alias:<6} → {short:<40}{marker:<10}│")
                    safe_print(f"  ├──────────────────────────────────────────────────────────┤")
                    safe_print(f"  │  Usage: /model nvidia   or   /model gemma               │")
                    safe_print(f"  └──────────────────────────────────────────────────────────┘")
                else:
                    model_id = parts[1].strip()
                    model_id = agent.MODEL_ALIASES.get(model_id.lower(), model_id)
                    if model_id == NVIDIA_GLM_MODEL_ID and not _nvidia_client:
                        safe_print("  ✗ NVIDIA API key not configured. Set NVIDIA_API_KEY in .env")
                    else:
                        agent.set_model(model_id)
                continue

            if lower == '/help':
                safe_print("""
  ┌─ NAMU AI — Quick Reference ──────────────────────────────────┐
  │                                                              │
  │  🔍 RESEARCH & SEARCH                                       │
  │  "What is [topic]?"           → Search + cited answer        │
  │  "Search for [query]"         → Web search with sources      │
  │  "Latest news about [X]"      → Current events               │
  │                                                              │
  │  🌐 SCRAPING & DATA                                          │
  │  "Scrape [URL]"               → Extract page content         │
  │  "Extract images from [URL]"  → Image extraction             │
  │  "Get links from [URL]"       → Link extraction              │
  │                                                              │
  │  📥 DOWNLOADS                                                │
  │  "Download video from [URL]"  → Video download               │
  │  "Download audio from [URL]"  → Audio download               │
  │                                                              │
  │  🔎 OSINT & RECON                                            │
  │  "OSINT on example.com"       → Domain intelligence          │
  │  "Lookup email user@test.com" → Email reputation             │
  │  "Search username john_doe"   → Username search              │
  │  "Full recon on [target]"     → Comprehensive OSINT          │
  │                                                              │
  │  📊 SAVE & REPORT                                            │
  │  "Save as HTML report"        → Generate styled report       │
  │  "Save as JSON"               → Export structured data       │
  │                                                              │
  │  🔗 CHAIN COMMANDS (automatic!)                              │
  │  "Scrape X, create report, open it"                          │
  │  "Full recon on X, save JSON and make HTML"                  │
  │                                                              │
  │  ⌨️  COMMANDS                                                │
  │  /model    — Switch AI model   /status — Session info        │
  │  /tools    — List all tools    /siai   — Self-improvement    │
  │  /clear    — Reset history     /help   — This screen         │
  │  0 or /exit — Quit                                           │
  └──────────────────────────────────────────────────────────────┘
""")
                continue

            # /status — session stats
            if lower == '/status':
                import time as _time
                uptime = datetime.now() - agent._start_time
                mins = int(uptime.total_seconds() / 60)
                cur = agent.MODELS[0] if agent.MODELS else 'none'
                cur_name = 'NVIDIA GLM4.7' if cur == NVIDIA_GLM_MODEL_ID else cur
                safe_print(f"\n  ┌─ Session Status ──────────────────────────────────────┐")
                safe_print(f"  │  Model:      {cur_name:<44}│")
                safe_print(f"  │  Requests:   {agent._request_count:<44}│")
                safe_print(f"  │  Messages:   {len(agent.messages):<44}│")
                safe_print(f"  │  Session:    {mins} min{'s' if mins != 1 else '':<43}│")
                bl = len(agent._blacklisted_models)
                safe_print(f"  │  Blacklisted:{bl} model{'s' if bl != 1 else '':<43}│")
                safe_print(f"  │  Data dir:   {AI_DATA_DIR[:44]:<44}│")
                safe_print(f"  │  Reports:    {AI_REPORTS_DIR[:44]:<44}│")
                or_key = '✓' if agent.api_key else '✗'
                nv_key = '✓' if _nvidia_client else '✗'
                sr_key = '✓' if os.environ.get('SERPER_API_KEY') else '✗'
                safe_print(f"  │  APIs:       OpenRouter {or_key}  NVIDIA {nv_key}  Serper {sr_key:<15}│")
                safe_print(f"  └──────────────────────────────────────────────────────────┘")
                continue

            # /tools — categorized tool list
            if lower == '/tools':
                tool_methods = [m for m in dir(agent.tool_executor) if m.startswith('_tool_')]
                categories = {
                    '🌐 Scraping': ['web_scrape', 'stealth_scrape', 'extract_images', 'extract_links', 'extract_emails', 'page_to_markdown'],
                    '🔎 OSINT': ['osint_domain', 'osint_email', 'osint_username', 'osint_phone', 'osint_ip', 'osint_full_recon', 'google_dorking'],
                    '📥 Downloads': ['download_audio', 'download_image'],
                    '🔍 Search': ['web_search'],
                    '💾 Save': ['save_json', 'create_html'],
                    '🖥️ OS': ['open_file', 'open_folder', 'open_url', 'open_recent', 'launch_app'],
                    '🔧 Utility': ['encode_decode', 'read_user_file'],
                    '🧠 SIAI': ['siai_list_files', 'siai_outline', 'siai_search', 'siai_read_file', 'siai_patch_file', 'siai_write_file', 'siai_log', 'siai_status', 'siai_test', 'siai_rollback', 'siai_diff', 'siai_checkpoint', 'siai_goals', 'siai_metrics', 'siai_hot_reload'],
                }
                safe_print(f"\n  ┌─ Available Tools ({len(tool_methods)}) ──────────────────────────────┐")
                for cat, tools in categories.items():
                    safe_print(f"  │  {cat:<56}│")
                    for t in tools:
                        has = f'_tool_{t}' in tool_methods
                        marker = '✓' if has else '✗'
                        safe_print(f"  │    {marker} {t:<52}│")
                safe_print(f"  └──────────────────────────────────────────────────────────┘")
                continue

            if lower == '/history':
                safe_print(f"\n  Chat history: {len(agent.messages)} messages")
                for msg in agent.messages[-10:]:
                    role = msg['role'].upper()
                    content = msg['content'][:80]
                    safe_print(f"    [{role}] {content}...")
                continue

            # /siai — quick SIAI status
            if lower == '/siai':
                safe_print("\n  🧠 SIAI — Self-Improvement AI System")
                safe_print("  ──────────────────────────────────────────────────────────────")
                for name, path in SIAI_ALLOWED_FILES.items():
                    if os.path.exists(path):
                        stat = os.stat(path)
                        sz = format_size(stat.st_size)
                        mod = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                        health = "✅"
                        if path.endswith('.py'):
                            try:
                                with open(path, 'r', encoding='utf-8') as _f:
                                    compile(_f.read(), path, 'exec')
                            except SyntaxError:
                                health = "❌ SYNTAX ERROR"
                        safe_print(f"    {health} {name:25s} {sz:>10s}  {mod}")
                    else:
                        safe_print(f"    ⚠️  {name:25s} (not found)")
                backup_count = len([f for f in os.listdir(SIAI_BACKUP_DIR) if f.endswith('.bak')])
                safe_print(f"\n  Backups: {backup_count} in {SIAI_BACKUP_DIR}")
                if os.path.exists(SIAI_LOG_FILE):
                    with open(SIAI_LOG_FILE, 'r', encoding='utf-8') as _f:
                        log_content = _f.read()
                    import re as _re
                    entries = _re.findall(r'### \[([^\]]+)\] (.+)', log_content)
                    if entries:
                        safe_print(f"  Log entries: {len(entries)}")
                        for ts, sec in entries[-3:]:
                            safe_print(f"    • [{ts}] {sec}")
                    else:
                        safe_print("  Log entries: 0 (no improvements yet)")
                safe_print("  ──────────────────────────────────────────────────────────────")
                safe_print("  Ask me to 'improve yourself' or 'read your code' to get started!")
                continue

            # Send to AI with typing indicator + response time
            import time as _time
            _t0 = _time.monotonic()
            safe_print("\n  ⏳ Searching & thinking...")
            response = await agent.chat(user_input)
            _elapsed = _time.monotonic() - _t0

            # Display response (cleaned — no raw JSON tool blocks)
            safe_print(f"\n  ─── Namu {'─'*53}")
            cleaned = response
            cleaned = re.sub(r'```(?:json)?\s*\n?\s*\{[^`]+?\}\s*\n?\s*```', '', cleaned, flags=re.DOTALL)
            cleaned = re.sub(r'\{"tool"\s*:\s*"[^"]+"[^}]*\}', '', cleaned)
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
            for line in cleaned.split('\n'):
                safe_print(f"  {line}")
            safe_print(f"\n  ─── {_elapsed:.1f}s {'─'*54}")

    except KeyboardInterrupt:
        safe_print("\n\n  [Namu] Interrupted. Goodbye!\n")
    finally:
        await agent.cleanup()


# =============================================================================
# Module Entry
# =============================================================================

if __name__ == "__main__":
    asyncio.run(run_namu_ai_chat())
