# Scraper, OSINT & Namu AI Intelligence Suite

Welcome to the **Scraper, OSINT & Namu AI Intelligence Suite**—a unified, professional platform for web scraping, media downloading, Open Source Intelligence (OSINT) gathering, and AI-powered research. 

This repository coordinates several command-line tools and web-based applications to help you retrieve, analyze, and document information from anywhere on the web.

---

## 🏗️ Project Architecture

Here is how the repository is structured, including all core modules and files:

| File | Description |
| :--- | :--- |
| **[`scraper.py`](file:///c:/scraper/scraper.py)** | Core media downloader (up to 8K, playlists, thumbnail & metadata embeds) and advanced web scraper using Scrapling (quick scrape, stealth anti-bot bypass, dynamic session browser, custom spider crawl). |
| **[`osint_cli.py`](file:///c:/scraper/osint_cli.py)** & **[`osint.py`](file:///c:/scraper/osint.py)** | The **OSINT Intelligence Center** CLI and engine. Handles domain, IP, email, phone (via NumVerify), and username recon (including Sherlock search), Google dorks, hash solvers, and SpiderFoot scans. |
| **[`namu_ai.py`](file:///c:/scraper/namu_ai.py)** | **Namu AI Research Agent**—a Perplexity-style reasoning assistant. Automatically chains search, scraping, OSINT, and downloading tools to answer queries with inline citations and generate HTML reports. |
| **[`namu_ui.py`](file:///c:/scraper/namu_ui.py)** | A local, dark-themed **Web Chat UI** for interacting with Namu AI, including file upload capability, detailed tool logs, and model selection. |
| **[`namu_api.py`](file:///c:/scraper/namu_api.py)** | A **FastAPI REST Server** that exposes time and news endpoints, complete with a beautiful live clock widget and search frontend page. |
| **[`SIAI.md`](file:///c:/scraper/SIAI.md)** | Sandboxed **Self-Improvement AI** log, listing the sandboxing rules, tools, and logs tracking how Namu AI optimizes its own codebase. |
| **[`config.py`](file:///c:/scraper/config.py)** | Central configuration management defining media quality, network settings, and save directories. |
| **[`database.py`](file:///c:/scraper/database.py)** | SQLite database module (`scraper.db`) for logging and tracking downloads, scrape sessions, and media history. |
| **[`extractors.py`](file:///c:/scraper/extractors.py)** | Page content parser that extracts metadata, streaming video sources, images, and text. |
| **[`processors.py`](file:///c:/scraper/processors.py)** | Processes and converts downloaded media (integrating FFmpeg for merging streams, audio extraction, scaling, and metadata tagging). |
| **[`spiderfoot_tool.py`](file:///c:/scraper/spiderfoot_tool.py)** | Core connector for running SpiderFoot scans and retrieving module details. |
| **[`image.py`](file:///c:/scraper/image.py)** | Dedicated bulk image scraper, downloader, and format corrector (e.g., WebP/HEIC conversion). |
| **[`exif_tool.py`](file:///c:/scraper/exif_tool.py)** | Tool to inspect and extract EXIF metadata from local files or URL-based media. |
| **[`windows_tools.py`](file:///c:/scraper/windows_tools.py)** | Integrates Windows system automation commands (open files, launch applications, browse folders). |
| **[`utils.py`](file:///c:/scraper/utils.py)** | Core logging utilities, string sanitization, and terminal formatting. |
| **[`models.py`](file:///c:/scraper/models.py)** | Shared dataclasses and schemas defining the internal data models. |
| **[`shared.py`](file:///c:/scraper/shared.py)** | Shares runtime context, flags, and database handles. |

---

## ⚡ Main Modules & Features

### 1. Web Scraper & Media Downloader ([`scraper.py`](file:///c:/scraper/scraper.py))
A full-featured scraper and download wrapper:
* **Audio Downloader**: Powered by `yt-dlp`. Downloads audio streams (MP3/M4A), processes playlists, embeds cover images (thumbnails) and metadata (title, year, platform), and logs completed downloads to a database. *(Note: Video downloading is disabled/removed).*
* **Web Scraping**: Powered by the modern `scrapling` engine:
  * **Quick Scrape**: Simple, fast HTTP requests.
  * **Stealth Scrape**: Launches an anti-bot browser bypass session supporting Cloudflare challenges.
  * **Dynamic Scrape**: Performs JS execution / SPA parsing using browser rendering.
  * **CSS/XPath Extraction**: Lets you target specific nodes with custom rules.
  * **Spider Crawling**: Automates multi-page crawling and outputs formatted JSON/CSV lists.

### 2. OSINT Intelligence Center ([`osint_cli.py`](file:///c:/scraper/osint_cli.py))
An interactive, categorized recon dashboard:
* **Target Recon**: Query domain information (DNS, SSL, stack), IP details, email lookup, phone numbers (with carrier/line validations via NumVerify), and usernames (Sherlock integration).
* **Automated Scanners**:
  * **Powerful Scanner**: Chimes together email, phone, name, and username to compose a complete target dossier.
  * **SpiderFoot Scan**: Integrates with SpiderFoot for footprinting and passive intelligence.
* **Dorking & Encodes**: Generates specialized Google dorks, decodes base64, hashes, hex strings, or ROT13.

### 3. Namu AI Research Agent ([`namu_ai.py`](file:///c:/scraper/namu_ai.py))
A Perplexity-like research agent that acts on your command:
* **Tool Chaining**: Converts natural language requests into step-by-step tool actions. For example, *"Scrape python.org, compile a report, and open it"* will automatically fetch, construct a styled HTML layout, and launch the file.
* **Dual-Model Support**: Automatically routes tasks to **NVIDIA GLM4.7 (Reasoning)** or falls back to free models via **OpenRouter** (e.g., Trinity, Dolphin Mistral).
* **HTML Reports**: Generates premium dark-themed intelligence dossiers with stat grids, galleries, and interactive code sections.
* **Self-Improvement AI (SIAI)**: Under strict sandboxing rules defined in **[`SIAI.md`](file:///c:/scraper/SIAI.md)**, Namu AI can outline, search, patch, and hot-reload its own files for performance tuning.

---

## ⚙️ Configuration & Setup

### 1. Prerequisites
Ensure you have the following installed on your system:
* **Python 3.10 or higher**
* **FFmpeg** (Recommended for video/audio conversion and tagging; ensure it is added to your system `PATH`)
* **Google Chrome** (For stealth/dynamic selenium scraper sessions)

### 2. Installation
Install the project dependencies using `pip` inside your virtual environment:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a file named **`.env`** in the project root directory (or update the existing one) with your credentials:
```env
# AI APIs
OPENROUTER_API_KEY=your_openrouter_api_key_here
NVIDIA_API_KEY=your_nvidia_api_key_here

# OSINT API keys
SERPER_API_KEY=your_serper_api_key_here
NUMVERIFY_API_KEY=your_numverify_api_key_here

# Self-Hosted SearXNG Search (Optional Fallback)
SEARXNG_URL=http://localhost:8888
```

---

## 🚀 How to Run the Tools

### 🌐 Web Scraper & Downloader CLI
Run direct media downloads or open the interactive scraping manager:
```bash
# Open interactive scraper panel
python scraper.py

# Download audio directly to MP3
python scraper.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --audio

# Show system dependency health
python scraper.py --status
```

### 🔎 OSINT Intelligence Center
Launch the terminal-based OSINT panel with 40+ modular operations:
```bash
python osint_cli.py
```

### 🧠 Namu AI Chat Bot (Terminal Mode)
Converse directly with the reasoning assistant in your shell:
```bash
python namu_ai.py
```
*Useful chat commands:*
* `/tools` — Prints all available 65+ tools categorized.
* `/siai` — Details the status and health of the Self-Improvement files.
* `/status` — Displays current model routing, uptime, and request statistics.
* `/clear` — Wipes current session history.

### 🖥️ Namu AI Web UI Server
Launch the local web server to chat in a modern dashboard interface:
```bash
python namu_ui.py
```
* Serves the local UI at **`http://localhost:7860`**.
* Features file uploads, interactive tool execution steps, and a model selector.

### 🕒 Clock & News API (FastAPI)
Run the FastAPI backend with a liveclock dashboard:
```bash
python namu_api.py
```
* Starts a server at **`http://localhost:8000`**.
* Open your browser and navigate to `http://localhost:8000` to interact with the **Live Clock & News search widget**.
* Explore API endpoints at `http://localhost:8000/docs`.

---

## 📂 Output & Save Directories

All outputs are saved cleanly inside a centralized folder (`~/scraper` or `C:\Users\<username>\scraper` by default):

* **`/audio`** — Processed audio tracks (MP3/M4A).
* **`/images`** & **`/thumbnails`** — Scraped web images and audio thumbnail cards.
* **`/text`** & **`/subtitles`** — Text previews and video caption documents.
* **`/scraped_data`** — HTML, JSON, or CSV records generated by scraping.
* **`/OSINT`** — Geolocation, domain reports, usernames, and full recon dossiers.
* **`/ai_reports`** — Cited research files and styled HTML dossiers generated by Namu AI.
* **`/ai_data/uploads`** — Files uploaded through the Namu Web UI.
* **`scraper.db`** — SQLite database containing all tracking indices.
* **`scraper.log`** — System execution logs.

---

Enjoy scraping and research! Always ensure you scrape responsibly and comply with target websites' terms of service.
