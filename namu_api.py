"""
================================================================================
NAMU_API.PY - Namu AI FastAPI Backend
================================================================================
Version: 1.0
Last Updated: 2026

FastAPI server exposing Namu AI capabilities as REST endpoints.
Designed for clean structure and scalability.

Endpoints:
  GET  /time           - Current time in Asia/Kolkata (IST)
  GET  /news           - Search current news via Namu AI web_search
  GET  /health         - API health check

================================================================================
"""

import os
import sys
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# ---------------------------------------------------------------------------
# Environment Setup
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(_env_path):
        with open(_env_path, 'r') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# FastAPI Imports
# ---------------------------------------------------------------------------
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# ---------------------------------------------------------------------------
# Timezone Constants
# ---------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))  # Asia/Kolkata  UTC+5:30

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Namu AI API",
    description="REST API for Namu AI agent — time, news search, and more.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the frontend clock widget to fetch from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Endpoint: /time
# ============================================================================

@app.get("/time", tags=["Time"])
async def get_current_time():
    """
    Returns the current time in Asia/Kolkata (IST) timezone.

    Response includes:
      - formatted: Human-readable string  (e.g. "09 Apr 2026, 12:45:30 PM IST")
      - iso:       ISO 8601 timestamp     (e.g. "2026-04-09T12:45:30+05:30")
      - date:      Date only              (e.g. "2026-04-09")
      - time:      Time only 24h          (e.g. "12:45:30")
      - time_12h:  Time only 12h          (e.g. "12:45:30 PM")
      - timezone:  Timezone name          ("Asia/Kolkata")
      - utc_offset:"+05:30"
      - unix:      Unix epoch seconds
      - day_of_week: e.g. "Thursday"
    """
    now = datetime.now(IST)

    return {
        "success": True,
        "timezone": "Asia/Kolkata",
        "utc_offset": "+05:30",
        "formatted": now.strftime("%d %b %Y, %I:%M:%S %p") + " IST",
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "time_12h": now.strftime("%I:%M:%S %p"),
        "day_of_week": now.strftime("%A"),
        "unix": int(now.timestamp()),
    }


# ============================================================================
# Endpoint: /news
# ============================================================================

# Lazy-loaded Namu AI search engine
_search_engine_lock = asyncio.Lock()
_search_ready = False


async def _do_web_search(query: str) -> Dict[str, Any]:
    """
    Perform a web search using the same Serper / SearXNG pipeline as Namu AI.
    This is extracted from ToolExecutor._tool_web_search for direct use.
    """
    import aiohttp
    import ssl as ssl_mod

    search_date = datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')

    # --- Method 1: Serper API (primary) ---
    serper_key = os.environ.get('SERPER_API_KEY', '')
    if serper_key and serper_key != 'your-serper-key-here':
        try:
            ssl_ctx = ssl_mod.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl_mod.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    'https://google.serper.dev/news',
                    json={'q': query, 'num': 10, 'gl': 'in'},
                    headers={
                        'X-API-KEY': serper_key,
                        'Content-Type': 'application/json',
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        news_items = []
                        for item in data.get('news', data.get('organic', []))[:10]:
                            news_items.append({
                                'title': item.get('title', ''),
                                'link': item.get('link', ''),
                                'snippet': item.get('snippet', ''),
                                'date': item.get('date', ''),
                                'source': item.get('source', ''),
                                'imageUrl': item.get('imageUrl', ''),
                            })
                        return {
                            "success": True,
                            "search_engine": "Serper (Google News)",
                            "query": query,
                            "searched_at": search_date,
                            "results": news_items,
                            "total_results": len(news_items),
                        }
                    else:
                        error_text = await resp.text()
                        print(f"  [WARN] Serper HTTP {resp.status}: {error_text}")
        except Exception as e:
            print(f"  [WARN] Serper news search failed: {e}")

    # --- Method 2: Serper standard search fallback ---
    if serper_key and serper_key != 'your-serper-key-here':
        try:
            ssl_ctx = ssl_mod.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl_mod.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    'https://google.serper.dev/search',
                    json={'q': query, 'num': 10},
                    headers={
                        'X-API-KEY': serper_key,
                        'Content-Type': 'application/json',
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
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
                                'source': item.get('source', ''),
                            })
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
                            "results": news_results if news_results else results,
                            "total_results": len(news_results or results),
                        }
        except Exception as e:
            print(f"  [WARN] Serper search fallback failed: {e}")

    # --- Method 3: SearXNG (self-hosted fallback) ---
    searxng_url = os.environ.get('SEARXNG_URL', '')
    if searxng_url:
        try:
            ssl_ctx = ssl_mod.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl_mod.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(connector=connector) as session:
                params = {
                    'q': query,
                    'format': 'json',
                    'engines': 'google news,bing news,duckduckgo',
                    'categories': 'news',
                }
                async with session.get(
                    f'{searxng_url.rstrip("/")}/search',
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        for item in data.get('results', [])[:10]:
                            results.append({
                                'title': item.get('title', ''),
                                'link': item.get('url', ''),
                                'snippet': item.get('content', ''),
                                'date': item.get('publishedDate', ''),
                                'source': item.get('engine', ''),
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
            print(f"  [WARN] SearXNG news search failed: {e}")

    return {
        "success": False,
        "error": "No search results. Check SERPER_API_KEY in .env or set up SearXNG.",
        "query": query,
        "searched_at": search_date,
    }


@app.get("/news", tags=["News"])
async def search_news(
    q: str = Query(
        default="latest news India",
        description="Search query for current news",
        min_length=1,
        max_length=500,
    ),
):
    """
    Search current news using Namu AI's search pipeline (Serper / SearXNG).

    Query params:
      - q: Search query  (default: "latest news India")

    Returns news articles with title, link, snippet, date, source.
    """
    result = await _do_web_search(q)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Search failed"))
    return result


# ============================================================================
# Endpoint: /health
# ============================================================================

@app.get("/health", tags=["System"])
async def health_check():
    """API health check — confirms the server is running."""
    now = datetime.now(IST)
    serper_configured = bool(os.environ.get('SERPER_API_KEY', ''))
    searxng_configured = bool(os.environ.get('SEARXNG_URL', ''))
    return {
        "status": "healthy",
        "timestamp": now.isoformat(),
        "search_engines": {
            "serper": serper_configured,
            "searxng": searxng_configured,
        },
    }


# ============================================================================
# Static: Serve the clock widget frontend
# ============================================================================

CLOCK_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Namu AI — Live Clock & News</title>
<meta name="description" content="Live updating clock widget and news search powered by Namu AI">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-primary: #0a0a0f;
    --bg-card: rgba(18, 18, 28, 0.85);
    --bg-card-hover: rgba(24, 24, 38, 0.95);
    --glass-border: rgba(255, 255, 255, 0.06);
    --glass-border-hover: rgba(255, 255, 255, 0.12);
    --accent-1: #6366f1;
    --accent-2: #8b5cf6;
    --accent-3: #a78bfa;
    --accent-glow: rgba(99, 102, 241, 0.25);
    --text-primary: #f0f0f5;
    --text-secondary: #8b8b9e;
    --text-muted: #55556a;
    --success: #22c55e;
    --error: #ef4444;
    --warning: #f59e0b;
    --news-accent: #f472b6;
    --gradient-main: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%);
    --gradient-warm: linear-gradient(135deg, #f472b6 0%, #f59e0b 100%);
    --gradient-bg: radial-gradient(ellipse at 20% 50%, rgba(99, 102, 241, 0.08) 0%, transparent 50%),
                   radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.06) 0%, transparent 50%),
                   radial-gradient(ellipse at 50% 80%, rgba(244, 114, 182, 0.04) 0%, transparent 50%);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    overflow-x: hidden;
  }

  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background: var(--gradient-bg);
    pointer-events: none;
    z-index: 0;
  }

  /* Animated background orbs */
  .orb {
    position: fixed;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.3;
    animation: float 20s ease-in-out infinite;
    pointer-events: none;
    z-index: 0;
  }
  .orb-1 { width: 400px; height: 400px; background: var(--accent-1); top: -100px; left: -100px; animation-delay: 0s; }
  .orb-2 { width: 300px; height: 300px; background: var(--accent-2); bottom: -50px; right: -50px; animation-delay: -7s; }
  .orb-3 { width: 200px; height: 200px; background: var(--news-accent); top: 40%; left: 60%; animation-delay: -14s; }

  @keyframes float {
    0%, 100% { transform: translate(0, 0) scale(1); }
    33% { transform: translate(30px, -30px) scale(1.05); }
    66% { transform: translate(-20px, 20px) scale(0.95); }
  }

  .container {
    position: relative;
    z-index: 1;
    max-width: 1100px;
    margin: 0 auto;
    padding: 40px 24px;
  }

  /* Header */
  .header {
    text-align: center;
    margin-bottom: 48px;
  }
  .header-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 16px;
    background: rgba(99, 102, 241, 0.12);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 100px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--accent-3);
    margin-bottom: 20px;
  }
  .header-badge .pulse {
    width: 8px; height: 8px;
    background: var(--success);
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }
  .header h1 {
    font-size: 36px;
    font-weight: 800;
    background: var(--gradient-main);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 8px;
    letter-spacing: -0.5px;
  }
  .header p {
    color: var(--text-secondary);
    font-size: 15px;
    font-weight: 400;
  }

  /* Glass card base */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .card:hover {
    background: var(--bg-card-hover);
    border-color: var(--glass-border-hover);
    transform: translateY(-2px);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3), 0 0 40px var(--accent-glow);
  }

  /* ========== CLOCK WIDGET ========== */
  .clock-section {
    padding: 48px 40px;
    text-align: center;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
  }
  .clock-section::before {
    content: '';
    position: absolute;
    top: 0; left: 50%;
    transform: translateX(-50%);
    width: 200px; height: 2px;
    background: var(--gradient-main);
    border-radius: 2px;
  }
  .clock-label {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 16px;
  }
  .clock-time {
    font-family: 'JetBrains Mono', monospace;
    font-size: 72px;
    font-weight: 700;
    background: var(--gradient-main);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 2px;
    line-height: 1;
    margin-bottom: 8px;
    animation: clockGlow 3s ease-in-out infinite;
  }
  @keyframes clockGlow {
    0%, 100% { filter: brightness(1); }
    50% { filter: brightness(1.15); }
  }
  .clock-ampm {
    font-family: 'JetBrains Mono', monospace;
    font-size: 24px;
    font-weight: 500;
    color: var(--accent-3);
    margin-bottom: 16px;
    display: block;
  }
  .clock-date {
    font-size: 18px;
    font-weight: 500;
    color: var(--text-secondary);
    margin-bottom: 4px;
  }
  .clock-day {
    font-size: 14px;
    color: var(--text-muted);
    font-weight: 400;
  }
  .clock-meta {
    display: flex;
    justify-content: center;
    gap: 32px;
    margin-top: 24px;
    padding-top: 24px;
    border-top: 1px solid var(--glass-border);
  }
  .clock-meta-item {
    text-align: center;
  }
  .clock-meta-item .label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 4px;
  }
  .clock-meta-item .value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    color: var(--text-secondary);
    font-weight: 500;
  }
  .clock-seconds-ring {
    width: 6px; height: 6px;
    background: var(--accent-1);
    border-radius: 50%;
    display: inline-block;
    animation: blink 1s steps(1) infinite;
    vertical-align: middle;
    margin-left: 4px;
  }
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }
  .status-badge.live {
    background: rgba(34, 197, 94, 0.12);
    color: var(--success);
    border: 1px solid rgba(34, 197, 94, 0.2);
  }
  .status-badge.error {
    background: rgba(239, 68, 68, 0.12);
    color: var(--error);
    border: 1px solid rgba(239, 68, 68, 0.2);
  }

  /* ========== NEWS SECTION ========== */
  .news-section {
    margin-bottom: 32px;
  }
  .news-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 28px;
    border-bottom: 1px solid var(--glass-border);
  }
  .news-header h2 {
    font-size: 18px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .news-header h2 .icon {
    font-size: 20px;
  }

  .search-bar {
    display: flex;
    gap: 10px;
    padding: 16px 28px;
    border-bottom: 1px solid var(--glass-border);
  }
  .search-bar input {
    flex: 1;
    padding: 10px 16px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    color: var(--text-primary);
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    outline: none;
    transition: all 0.2s;
  }
  .search-bar input:focus {
    border-color: var(--accent-1);
    box-shadow: 0 0 0 3px var(--accent-glow);
  }
  .search-bar input::placeholder { color: var(--text-muted); }
  .search-bar button {
    padding: 10px 24px;
    background: var(--gradient-main);
    border: none;
    border-radius: 12px;
    color: white;
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .search-bar button:hover {
    transform: scale(1.02);
    box-shadow: 0 4px 20px var(--accent-glow);
  }
  .search-bar button:active { transform: scale(0.98); }
  .search-bar button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }

  .news-list {
    padding: 8px 0;
  }
  .news-list:empty::after {
    content: 'Search for news above...';
    display: block;
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
    font-size: 14px;
  }

  .news-item {
    display: flex;
    gap: 16px;
    padding: 16px 28px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    transition: background 0.2s;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
  }
  .news-item:last-child { border-bottom: none; }
  .news-item:hover { background: rgba(255, 255, 255, 0.03); }

  .news-item .index {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 700;
    color: var(--accent-1);
    background: rgba(99, 102, 241, 0.1);
    width: 28px; height: 28px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 2px;
  }
  .news-item .content { flex: 1; min-width: 0; }
  .news-item .title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .news-item:hover .title { color: var(--accent-3); }
  .news-item .snippet {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 6px;
  }
  .news-item .meta {
    display: flex;
    gap: 12px;
    font-size: 11px;
    color: var(--text-muted);
    font-weight: 500;
  }
  .news-item .meta .source {
    color: var(--news-accent);
    font-weight: 600;
  }

  .news-loading {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
    font-size: 14px;
  }
  .news-loading .spinner {
    width: 24px; height: 24px;
    border: 2px solid var(--glass-border);
    border-top-color: var(--accent-1);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 12px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .news-error {
    text-align: center;
    padding: 32px;
    color: var(--error);
    font-size: 14px;
  }

  .news-footer {
    padding: 12px 28px;
    border-top: 1px solid var(--glass-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    color: var(--text-muted);
  }

  /* ========== FOOTER ========== */
  .footer {
    text-align: center;
    padding: 32px 0;
    color: var(--text-muted);
    font-size: 12px;
  }
  .footer a {
    color: var(--accent-3);
    text-decoration: none;
  }
  .footer a:hover { text-decoration: underline; }

  /* Responsive */
  @media (max-width: 640px) {
    .container { padding: 24px 16px; }
    .clock-time { font-size: 48px; }
    .clock-ampm { font-size: 18px; }
    .clock-meta { gap: 16px; flex-wrap: wrap; }
    .clock-section { padding: 32px 20px; }
    .search-bar { flex-direction: column; }
    .search-bar button { width: 100%; }
    .news-header { flex-direction: column; gap: 8px; }
  }
</style>
</head>
<body>
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>

  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="header-badge"><span class="pulse"></span> NAMU AI</div>
      <h1>Live Clock &amp; News</h1>
      <p>Real-time IST clock with AI-powered news search</p>
    </div>

    <!-- Clock Widget -->
    <div class="card clock-section" id="clockWidget">
      <div class="clock-label">Asia / Kolkata (IST) <span class="clock-seconds-ring"></span></div>
      <div class="clock-time" id="clockTime">--:--:--</div>
      <span class="clock-ampm" id="clockAmPm">--</span>
      <div class="clock-date" id="clockDate">Loading...</div>
      <div class="clock-day" id="clockDay"></div>
      <div class="clock-meta">
        <div class="clock-meta-item">
          <div class="label">Timezone</div>
          <div class="value" id="metaTz">IST</div>
        </div>
        <div class="clock-meta-item">
          <div class="label">UTC Offset</div>
          <div class="value" id="metaOffset">+05:30</div>
        </div>
        <div class="clock-meta-item">
          <div class="label">Unix Epoch</div>
          <div class="value" id="metaUnix">--</div>
        </div>
        <div class="clock-meta-item">
          <div class="label">Status</div>
          <div class="value"><span class="status-badge live" id="clockStatus"><span class="pulse"></span> LIVE</span></div>
        </div>
      </div>
    </div>

    <!-- News Section -->
    <div class="card news-section" id="newsWidget">
      <div class="news-header">
        <h2><span class="icon">📰</span> News Search</h2>
        <span class="status-badge live" id="newsEngine">Powered by Serper</span>
      </div>
      <div class="search-bar">
        <input type="text" id="newsQuery" placeholder="Search current news... (e.g. AI, India, tech)" value="latest news today">
        <button id="newsSearchBtn" onclick="searchNews()">Search</button>
      </div>
      <div class="news-list" id="newsList"></div>
      <div class="news-footer">
        <span id="newsCount"></span>
        <span id="newsTimestamp"></span>
      </div>
    </div>

    <!-- Footer -->
    <div class="footer">
      Namu AI Agent &mdash; <a href="/docs">API Docs</a> &bull; <a href="/health">Health</a>
    </div>
  </div>

<script>
  const API_BASE = window.location.origin;

  // ===== CLOCK =====
  let clockInterval = null;

  async function fetchTime() {
    try {
      const res = await fetch(`${API_BASE}/time`);
      const data = await res.json();
      if (data.success) {
        updateClockUI(data);
      }
    } catch (err) {
      document.getElementById('clockStatus').className = 'status-badge error';
      document.getElementById('clockStatus').innerHTML = '⚠ OFFLINE';
    }
  }

  function updateClockUI(data) {
    // Parse time parts from time_12h: "12:45:30 PM"
    const parts = data.time_12h.split(' ');
    const timePart = parts[0];   // "12:45:30"
    const ampm = parts[1] || ''; // "PM"

    document.getElementById('clockTime').textContent = timePart;
    document.getElementById('clockAmPm').textContent = ampm;
    document.getElementById('clockDate').textContent = data.formatted.split(',')[0];  // "09 Apr 2026"
    document.getElementById('clockDay').textContent = data.day_of_week;
    document.getElementById('metaTz').textContent = 'IST';
    document.getElementById('metaOffset').textContent = data.utc_offset;
    document.getElementById('metaUnix').textContent = data.unix;

    document.getElementById('clockStatus').className = 'status-badge live';
    document.getElementById('clockStatus').innerHTML = '<span class="pulse"></span> LIVE';
  }

  // Start clock: fetch every second for a live-updating clock
  function startClock() {
    fetchTime();
    clockInterval = setInterval(fetchTime, 1000);
  }

  // ===== NEWS =====
  async function searchNews() {
    const query = document.getElementById('newsQuery').value.trim();
    if (!query) return;

    const btn = document.getElementById('newsSearchBtn');
    const list = document.getElementById('newsList');
    btn.disabled = true;
    btn.textContent = 'Searching...';
    list.innerHTML = '<div class="news-loading"><div class="spinner"></div>Searching with Namu AI...</div>';

    try {
      const res = await fetch(`${API_BASE}/news?q=${encodeURIComponent(query)}`);
      const data = await res.json();

      if (data.success && data.results && data.results.length > 0) {
        renderNews(data);
      } else {
        list.innerHTML = `<div class="news-error">No results found for "${query}". ${data.error || ''}</div>`;
      }
    } catch (err) {
      list.innerHTML = `<div class="news-error">Failed to reach API: ${err.message}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Search';
    }
  }

  function renderNews(data) {
    const list = document.getElementById('newsList');
    list.innerHTML = '';

    data.results.forEach((item, i) => {
      const a = document.createElement('a');
      a.className = 'news-item';
      a.href = item.link;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.innerHTML = `
        <div class="index">${i + 1}</div>
        <div class="content">
          <div class="title">${escapeHtml(item.title)}</div>
          ${item.snippet ? `<div class="snippet">${escapeHtml(item.snippet)}</div>` : ''}
          <div class="meta">
            ${item.source ? `<span class="source">${escapeHtml(item.source)}</span>` : ''}
            ${item.date ? `<span>${escapeHtml(item.date)}</span>` : ''}
          </div>
        </div>
      `;
      list.appendChild(a);
    });

    document.getElementById('newsCount').textContent = `${data.total_results} results`;
    document.getElementById('newsTimestamp').textContent = `Searched: ${data.searched_at}`;
    document.getElementById('newsEngine').textContent = data.search_engine || 'Serper';
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
  }

  // Enter key to search
  document.getElementById('newsQuery').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchNews();
  });

  // Boot
  startClock();
</script>
</body>
</html>"""


@app.get("/", tags=["UI"], include_in_schema=False)
async def serve_clock_widget():
    """Serve the live clock & news widget frontend."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=CLOCK_HTML)


# ============================================================================
# CLI Runner
# ============================================================================

def main():
    """Run the Namu AI FastAPI server."""
    import argparse
    parser = argparse.ArgumentParser(description="Namu AI FastAPI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    print(f"""
{'='*66}
{'NAMU AI - FastAPI SERVER':^66}
{'='*66}
  Endpoints:
    GET  /          -> Live Clock & News Widget (frontend)
    GET  /time      -> Current time (Asia/Kolkata IST)
    GET  /news?q=   -> News search via Serper/SearXNG
    GET  /health    -> API health check
    GET  /docs      -> Interactive API docs (Swagger)

  Server: http://{args.host}:{args.port}
{'='*66}
""")

    uvicorn.run(
        "namu_api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
