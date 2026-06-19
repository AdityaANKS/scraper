
"""
================================================================================
OSINT_CLI.PY - Dedicated OSINT Command Line Interface
================================================================================
Interactive CLI for all OSINT operations. Launched from main CLI option 5.
Auto-organizes results in C:\\\\Users\\\\adity\\\\scraper\\\\OSINT\\\\
================================================================================
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional
from enum import Enum

from config import config
from osint import OSINTEngine, OSINTResult, OSINT_RESOURCES
from utils import safe_print, log_info, log_warn, log_error, log_success
from shared import SessionManager

def paged_print(text: str, page_size: int = 40):
    """Print text with pagination for long output"""
    lines = text.split('\n')
    if len(lines) <= page_size:
        safe_print(text)
        return

    for i in range(0, len(lines), page_size):
        chunk = lines[i:i + page_size]
        for line in chunk:
            safe_print(line)

        if i + page_size < len(lines):
            remaining = len(lines) - (i + page_size)
            response = get_input(f"  --- {remaining} more lines. Press Enter to continue, 'q' to skip ---")
            if response.lower() == 'q':
                break


try:
    from exif_tool import EXIFExtractor
    HAS_EXIF = True
except ImportError:
    HAS_EXIF = False

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


# =============================================================================
# Helpers
# =============================================================================

import re

def _validate_domain(domain: str) -> bool:
    """Validate domain format"""
    domain = domain.replace('https://', '').replace('http://', '').strip('/')
    return bool(re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', domain))

def _validate_email(email: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def _validate_ip(ip: str) -> bool:
    try:
        import ipaddress
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def _validate_phone(phone: str) -> bool:
    digits = re.sub(r'[^\d]', '', phone)
    return len(digits) >= 10

def get_validated_input(prompt: str, validator=None, error_msg: str = "Invalid input") -> Optional[str]:
    """Get input with validation"""
    value = get_input(prompt)
    if not value:
        return None
    if validator and not validator(value):
        safe_print(f"  [X] {error_msg}")
        return None
    return value

def get_input(prompt: str, default: str = "") -> str:
    try:
        result = input(f"  {prompt}: ").strip()
        return result if result else default
    except (EOFError, KeyboardInterrupt):
        return ""

def confirm(prompt: str) -> bool:
    r = get_input(f"{prompt} [y/N]").lower()
    return r in ('y', 'yes')

OSINT_DIR = config.paths.osint


async def _save_result_async(result: OSINTResult, category_folder: str) -> str:
    """Save OSINT result to organized folder (non-blocking)"""
    folder = os.path.join(OSINT_DIR, category_folder)
    os.makedirs(folder, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_query = "".join(c if c.isalnum() or c in '-_.' else '_' for c in result.query)[:50]
    filename = f"{safe_query}_{ts}.json"
    filepath = os.path.join(folder, filename)

    data = json.dumps(result.to_dict(), indent=2, default=str)

    # Non-blocking write
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_file, filepath, data)
    return filepath

def _write_file(filepath: str, data: str):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(data)

def _save_result(result: OSINTResult, category_folder: str) -> str:
    """Synchronous version for EXIF tools or other sync calls"""
    import threading
    folder = os.path.join(OSINT_DIR, category_folder)
    os.makedirs(folder, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_query = "".join(c if c.isalnum() or c in '-_.' else '_' for c in result.query)[:50]
    filename = f"{safe_query}_{ts}.json"
    filepath = os.path.join(folder, filename)

    data = json.dumps(result.to_dict(), indent=2, default=str)
    threading.Thread(target=_write_file, args=(filepath, data)).start()
    return filepath


def _save_tools_report(category: str, tools: list) -> str:
    """Save tools list to file"""
    folder = os.path.join(OSINT_DIR, "_tools_reference")
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{category}_tools.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({'category': category, 'tools': tools, 'exported': datetime.now().isoformat()}, f, indent=2)
    return filepath


def _display_tools(category: str, tools: list, auto_save: bool = True):
    """Display tools for a category with optional auto-save"""
    safe_print(f"\n  {'─'*60}")
    safe_print(f"  {category.upper().replace('_',' ')} TOOLS:")
    safe_print(f"  {'─'*60}")
    for i, t in enumerate(tools, 1):
        safe_print(f"    {i:2}. {t['name']:<22} - {t['desc']}")
        safe_print(f"        {t['url']}")
    safe_print(f"\n  Total: {len(tools)} tools")

    if auto_save:
        fp = _save_tools_report(category, tools)
        safe_print(f"  [OK] Tool list saved: {fp}")


def _write_binary_file(filepath: str, data: bytes):
    with open(filepath, 'wb') as f:
        f.write(data)

async def _download_image(url: str, save_dir: str = None, verify_ssl: bool = True) -> Optional[str]:
    """Download image from URL"""
    if not HAS_AIOHTTP:
        safe_print("  [X] aiohttp not available")
        return None
    
    save_dir = save_dir or os.path.join(OSINT_DIR, "images")
    os.makedirs(save_dir, exist_ok=True)
    
    from urllib.parse import urlparse
    filename = os.path.basename(urlparse(url).path) or f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    # Sanitize filename
    filename = "".join(c if c.isalnum() or c in '-_.' else '_' for c in filename)
    filepath = os.path.join(save_dir, filename)
    
    # Don't overwrite existing files
    if os.path.exists(filepath):
        base, ext = os.path.splitext(filepath)
        counter = 1
        while os.path.exists(filepath):
            filepath = f"{base}_{counter}{ext}"
            counter += 1
            
    try:
        headers = {'User-Agent': config.network.user_agent}
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(ssl=verify_ssl)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    # Validate content type
                    content_type = resp.headers.get('Content-Type', '')
                    if not any(t in content_type for t in ['image/', 'octet-stream']):
                        safe_print(f"  [!] Warning: Content-Type is '{content_type}', may not be an image")

                    # Async file write
                    try:
                        import aiofiles
                        async with aiofiles.open(filepath, 'wb') as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                await f.write(chunk)
                    except ImportError:
                        # Fallback to sync write in executor
                        content = await resp.read()
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, _write_binary_file, filepath, content)

                    file_size = os.path.getsize(filepath)
                    safe_print(f"  [OK] Saved: {filepath} ({file_size:,} bytes)")
                    return filepath
                else:
                    safe_print(f"  [X] HTTP {resp.status}")
    except aiohttp.ClientSSLError:
        if verify_ssl:
            safe_print(f"  [!] SSL error, retrying without verification...")
            return await _download_image(url, save_dir, verify_ssl=False)
    except aiohttp.ClientError as e:
        safe_print(f"  [X] Network error: {e}")
    except Exception as e:
        safe_print(f"  [X] Download failed: {e}")
    return None


# =============================================================================
# OSINT CLI Class
# =============================================================================

class MenuOption(str, Enum):
    DOMAIN_RECON = "1"
    IP_LOOKUP = "2"
    EMAIL_INTEL = "3"
    USERNAME_SEARCH = "4"
    PHONE_OSINT = "5"
    FULL_RECON = "6"
    SOCIAL_NETWORKS = "7"
    PEOPLE_SEARCH = "8"
    IM = "9"
    DATING = "10"
    FORUMS = "11"
    WEB_PAGE = "12"
    IMAGE_DOWNLOAD = "13"
    EXIF = "14"
    REVERSE_IMAGE = "15"
    PUBLIC_RECORDS = "16"
    BUSINESS_RECORDS = "17"
    TRANSPORTATION = "18"
    GEOLOCATION = "19"
    THREAT_INTEL = "20"
    MALWARE_ANALYSIS = "21"
    EXPLOITS = "22"
    DARK_WEB = "23"
    CRYPTO = "24"
    GOOGLE_DORKS = "25"
    ENCODE_DECODE = "26"
    SEARCH_ENGINES = "27"
    AI_TOOLS = "28"
    OPSEC = "29"
    ARCHIVES = "30"
    TRANSLATION = "31"
    MOBILE_EMULATION = "32"
    TERRORISM = "33"
    CLASSIFIEDS = "34"
    EVIDENCE = "35"
    TRAINING = "36"
    SEARCH_TOOLS = "37"
    EXPORT_ALL = "38"
    BROWSE_FOLDER = "39"
    POWERFUL_SCANNER = "40"
    SPIDERFOOT = "41"

class OSINT_CLI:
    """Dedicated OSINT Command Line Interface"""

    def __init__(self):
        self.engine: Optional[OSINTEngine] = None
        self._all_results = []
        self.exif = EXIFExtractor() if HAS_EXIF else None

        # Dispatch table
        self._handlers = {
            MenuOption.DOMAIN_RECON: self._handle_domain_recon,
            MenuOption.IP_LOOKUP: self._handle_ip_lookup,
            MenuOption.EMAIL_INTEL: self._handle_email_intel,
            MenuOption.USERNAME_SEARCH: self._handle_username_search,
            MenuOption.PHONE_OSINT: self._handle_phone_osint,
            MenuOption.FULL_RECON: self._handle_full_recon,
            MenuOption.SOCIAL_NETWORKS: lambda: self._handle_tools_and_search("social_networks", "Social Networks", self._handle_username_search_direct),
            MenuOption.PEOPLE_SEARCH: lambda: self._handle_tools("people_search", "People Search"),
            MenuOption.IM: lambda: self._handle_tools("instant_messaging", "Instant Messaging"),
            MenuOption.DATING: lambda: self._handle_tools("dating", "Dating"),
            MenuOption.FORUMS: lambda: self._handle_tools("forums_blogs", "Forums / Blogs"),
            MenuOption.WEB_PAGE: self._handle_web_page,
            MenuOption.IMAGE_DOWNLOAD: self._handle_image_download,
            MenuOption.EXIF: self._handle_exif,
            MenuOption.REVERSE_IMAGE: lambda: self._handle_tools("images_videos_docs", "Images / Videos / Docs"),
            MenuOption.PUBLIC_RECORDS: lambda: self._handle_tools("public_records", "Public Records"),
            MenuOption.BUSINESS_RECORDS: lambda: self._handle_tools("business_records", "Business Records"),
            MenuOption.TRANSPORTATION: lambda: self._handle_tools("transportation", "Transportation"),
            MenuOption.GEOLOCATION: lambda: self._handle_tools("geolocation", "Geolocation / Maps"),
            MenuOption.THREAT_INTEL: lambda: self._handle_tools("threat_intelligence", "Threat Intelligence"),
            MenuOption.MALWARE_ANALYSIS: lambda: self._handle_tools("malware_analysis", "Malware Analysis"),
            MenuOption.EXPLOITS: lambda: self._handle_tools("exploits_advisories", "Exploits & Advisories"),
            MenuOption.DARK_WEB: lambda: self._handle_tools("dark_web", "Dark Web"),
            MenuOption.CRYPTO: lambda: self._handle_tools("digital_currency", "Digital Currency"),
            MenuOption.GOOGLE_DORKS: self._handle_google_dorks,
            MenuOption.ENCODE_DECODE: self._handle_encode_decode,
            MenuOption.SEARCH_ENGINES: lambda: self._handle_tools("search_engines", "Search Engines"),
            MenuOption.AI_TOOLS: self._handle_ai_tools,
            MenuOption.OPSEC: lambda: self._handle_tools("opsec", "OpSec"),
            MenuOption.ARCHIVES: lambda: self._handle_tools("archives", "Archives"),
            MenuOption.TRANSLATION: lambda: self._handle_tools("translation", "Translation"),
            MenuOption.MOBILE_EMULATION: lambda: self._handle_tools("mobile_emulation", "Mobile Emulation"),
            MenuOption.TERRORISM: lambda: self._handle_tools("terrorism", "Terrorism"),
            MenuOption.CLASSIFIEDS: lambda: self._handle_tools("classifieds", "Classifieds"),
            MenuOption.EVIDENCE: lambda: self._handle_tools("documentation_evidence", "Documentation / Evidence"),
            MenuOption.TRAINING: lambda: self._handle_tools("training", "Training"),
            MenuOption.SEARCH_TOOLS: self._handle_search_tools,
            MenuOption.EXPORT_ALL: self._handle_export_all,
            MenuOption.BROWSE_FOLDER: self._handle_browse_folder,
            MenuOption.POWERFUL_SCANNER: self._handle_powerful_scanner,
            MenuOption.SPIDERFOOT: self._handle_spiderfoot,
        }

    async def _get_engine(self) -> OSINTEngine:
        if not self.engine:
            self.engine = OSINTEngine()
        return self.engine
        
    async def cleanup(self):
        if self.engine:
            await self.engine.close()

    async def _handle_tools(self, category_id: str, display_name: str):
        _display_tools(display_name, OSINTEngine.get_tools(category_id))
        
    async def _handle_tools_and_search(self, category_id: str, display_name: str, search_func=None):
        await self._handle_tools(category_id, display_name)
        if search_func:
            await search_func()
            
    async def _handle_username_search_direct(self):
        username = get_validated_input("\n  Search username across social networks? Enter username (or skip)")
        if username:
            engine = await self._get_engine()
            result = await engine.username_osint(username, check_live=True)
            self._all_results.append(result)
            safe_print(result.summary())
            await _save_result_async(result, "search/social_networks")

    def print_header(self):
        safe_print(f"""
{'='*65}
{'OSINT INTELLIGENCE CENTER':^65}
{'Open Source Intelligence Toolkit':^65}
{'='*65}
  Output: {OSINT_DIR}
{'='*65}""")

    def print_menu(self):
        safe_print("""
  RECONNAISSANCE:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1.  Domain Recon         (DNS, SSL, Subdomains, Tech Stack)
    2.  IP Address Lookup    (Geolocation, Reverse DNS, Abuse)
    3.  Email Intelligence   (Validation, Gravatar, Profiles)
    4.  Username Search      (35+ Platforms Live Check)
    5.  Phone Number OSINT   (NumVerify: Carrier, Location, Line Type)
    6.  Full Auto-Recon      (Auto-detect target, run all modules)

  SEARCH & SOCIAL:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    7.  Social Networks      (Profile Search + Tool Links)
    8.  People Search        (People Finder Tools)
    9.  Instant Messaging    (Telegram, Discord, WhatsApp)
   10.  Dating Sites         (Profile Investigation Tools)
   11.  Forums / Blogs       (Forum Search + Archives)

  MEDIA & METADATA:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   12.  Web Page OSINT       (Extract Emails, Phones, Links)
   13.  Image Download       (Download + Extract from Pages)
   14.  EXIF / Metadata      (Image & Video Metadata Extract)
   15.  Images / Videos      (Reverse Image Search Tools)

  RECORDS & GEO:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   16.  Public Records       (Court, Government, FOIA)
   17.  Business Records     (Company Search, Crunchbase)
   18.  Transportation       (Flight, Ship, Vehicle Tracking)
   19.  Geolocation / Maps   (Satellite, Street View, SunCalc)

  CYBER SECURITY:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   20.  Threat Intelligence  (IOC, MITRE ATT&CK, Feeds)
   21.  Malware Analysis     (VirusTotal, Sandboxes)
   22.  Exploits & CVEs      (Exploit-DB, NVD, Vulners)
   23.  Dark Web             (Tor Search, Onion Scanners)
   24.  Digital Currency     (Blockchain, Wallet Tracking)

  TOOLS & UTILITIES:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   25.  Google Dorking       (Advanced Search Queries)
   26.  Encoding / Decoding  (Base64, Hex, ROT13, Hashes)
   27.  Search Engines       (Google, Bing, Yandex, Ahmia)
   28.  AI Tools             (Dolphin Mistral, Trinity, Serper, SearXNG)
   29.  OpSec Tools          (Tor, VPN, Encryption)
   30.  Archives             (Wayback Machine, Cache)
   31.  Translation          (Google, DeepL, Yandex)
   32.  Mobile Emulation     (Emulators, Testing Tools)
   33.  Terrorism DBs        (GTD, TRAC, SITE Intel)
   34.  Classifieds          (Craigslist, FB Marketplace)

  DOCUMENTATION:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   35.  Evidence Capture     (Hunchly, Archive, HTTrack)
   36.  Training Resources   (OSINT Dojo, TryHackMe, SANS)
   37.  Search All Tools     (Search across all categories)
   38.  Export All Results    (Save everything to JSON)
   39.  Browse OSINT Folder  (Open output directory)

  POWERFUL SCANNERS:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   40.  POWERFUL SCANNER     (Email+Username+Phone → Full Intel)
   41.  SpiderFoot Scan      (Auto-detect target, deep scan)

    0.  Back to Main Menu
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

    async def run(self):
        """Main OSINT CLI loop"""
        self.print_header()

        while True:
            self.print_menu()
            choice = get_input("Select option", "0")

            if choice == "0":
                safe_print("\n  Returning to main menu...\n")
                break

            try:
                await self.handle_choice(choice)
            except KeyboardInterrupt:
                safe_print("\n  Cancelled.")
            except Exception as e:
                safe_print(f"\n  [X] Error: {e}")

            get_input("\n  Press Enter to continue...")
        await self.cleanup()

    async def handle_choice(self, choice: str):
        """Route selection to appropriate handler"""
        try:
            option = MenuOption(choice)
            handler = self._handlers.get(option)
            if handler:
                result = handler()
                if asyncio.iscoroutine(result):
                    await result
            else:
                safe_print("  [!] Handler not implemented")
        except ValueError:
            safe_print("  [X] Invalid option")

    # --- Feature Handlers ---

    async def _handle_domain_recon(self):
        domain = get_validated_input("Enter domain (e.g. example.com)", _validate_domain, "Invalid domain format")
        if domain:
            safe_print("\n  Scanning domain...")
            engine = await self._get_engine()
            result = await engine.domain_recon(domain)
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "recon/domains")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_ip_lookup(self):
        ip = get_validated_input("Enter IP address", _validate_ip, "Invalid IP format")
        if ip:
            safe_print("\n  Looking up IP...")
            engine = await self._get_engine()
            result = await engine.ip_osint(ip)
            self._all_results.append(result)
            safe_print(result.summary())
            fp = await _save_result_async(result, "recon/ip_addresses")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_email_intel(self):
        email = get_validated_input("Enter email address", _validate_email, "Invalid email format")
        if email:
            safe_print("\n  Analyzing email...")
            engine = await self._get_engine()
            result = await engine.email_osint(email)
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "recon/emails")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_username_search(self):
        username = get_validated_input("Enter username")
        if username:
            safe_print("\n  USERNAME SEARCH OPTIONS:")
            safe_print("    1. Standard Search (35+ platforms, fast)")
            safe_print("    2. Sherlock Search (400+ platforms, slower but comprehensive)")
            sub = get_input("Select", "1")
            
            engine = await self._get_engine()
            
            if sub == "1":
                live = confirm("Run live platform checks? (slower but accurate)")
                safe_print(f"\n  Searching {'(live)' if live else '(generating URLs)'}...")
                result = await engine.username_osint(username, check_live=live)
            elif sub == "2":
                safe_print("\n  Running Sherlock across 400+ platforms (this may take a minute)...")
                result = await engine.sherlock_osint(username)
            else:
                safe_print("  [X] Invalid option")
                return
                
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "recon/usernames")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_phone_osint(self):
        phone = get_validated_input("Enter phone number (with country code)", _validate_phone, "Invalid phone format")
        if phone:
            engine = await self._get_engine()
            result = await engine.phone_osint(phone)
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "recon/phones")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_full_recon(self):
        target = get_validated_input("Enter target (email, domain, IP, username, or phone)")
        if target:
            safe_print("\n  Running full auto-recon...")
            engine = await self._get_engine()
            results = await engine.full_recon(target)
            for name, result in results.items():
                self._all_results.append(result)
                paged_print(result.summary())
                await _save_result_async(result, f"recon/full_recon/{name}")
            safe_print(f"\n  [OK] All results saved to: {os.path.join(OSINT_DIR, 'recon/full_recon')}")

    async def _handle_web_page(self):
        url = get_validated_input("Enter URL to analyze")
        if url:
            safe_print("\n  Extracting page intelligence...")
            engine = await self._get_engine()
            result = await engine.page_osint(url)
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "media/web_pages")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_image_download(self):
        safe_print("\n  IMAGE DOWNLOAD:")
        safe_print("    1. Download single image from URL")
        safe_print("    2. Download multiple images (enter URLs)")
        safe_print("    3. Scrape page \u2192 download ALL images")
        safe_print("    4. Download from URL list file")
        safe_print("    5. Fix existing images (convert WebP, fix extensions)")
        sub = get_input("Select", "1")

        try:
            from image import ImageDownloader
        except ImportError:
            safe_print("  [X] image.py module not found")
            return

        img_dir = os.path.join(OSINT_DIR, "media/images")

        if sub == "1":
            url = get_input("Enter image URL")
            if url:
                async with ImageDownloader(output_dir=img_dir) as dl:
                    result = await dl.download(url)
                if result.success:
                    log_success(f"Saved: {result.filepath}")
                    arrow = " \u2192 "
                    log_info(f"Format: {result.original_format}"
                             f"{arrow + result.saved_format if result.was_converted else ''}")
                    log_info(f"Size: {result.size_str} | {result.width}x{result.height}")
                else:
                    log_error(f"Failed: {result.error}")

        elif sub == "2":
            safe_print("  Enter image URLs (one per line, type END to finish):")
            urls = []
            while True:
                try:
                    line = input("    ").strip()
                    if line.upper() == 'END':
                        break
                    if line.startswith(('http://', 'https://')):
                        urls.append(line)
                except (EOFError, KeyboardInterrupt):
                    break
            if urls:
                safe_print(f"\n  Downloading {len(urls)} images...")
                async with ImageDownloader(output_dir=img_dir) as dl:
                    results = await dl.download_many(urls)
                downloaded = sum(1 for r in results if r.success)
                log_success(f"Downloaded: {downloaded}/{len(urls)}")

        elif sub == "3":
            url = get_input("Enter page URL to scrape for images")
            if url:
                max_imgs = int(get_input("Max images to download", "50") or 50)
                safe_print(f"\n  Scraping {url} for images...")
                async with ImageDownloader(output_dir=img_dir) as dl:
                    result = await dl.scrape_and_download(url, max_images=max_imgs)
                safe_print(result.summary())

        elif sub == "4":
            filepath = get_input("Enter path to URL list file")
            if filepath and os.path.exists(filepath):
                async with ImageDownloader(output_dir=img_dir) as dl:
                    results = await dl.download_from_file(filepath)
                downloaded = sum(1 for r in results if r.success)
                log_success(f"Downloaded: {downloaded}/{len(results)}")
            else:
                safe_print("  File not found")

        elif sub == "5":
            target_dir = get_input(f"Enter directory to fix", img_dir)
            if os.path.isdir(target_dir):
                dl = ImageDownloader(output_dir=target_dir)
                stats = dl.fix_existing_images(target_dir)
                safe_print(f"\n  Results: {json.dumps(stats, indent=2)}")
            else:
                safe_print("  Directory not found")

    async def _handle_exif(self):
        if not HAS_EXIF:
            safe_print("  [X] EXIF tool not available (run: pip install Pillow)")
            return
        safe_print("\n  EXIF METADATA:")
        safe_print("    1. Extract from local file")
        safe_print("    2. Extract from URL")
        sub = get_validated_input("Select", lambda x: x in ['1', '2'])
        if sub == "1":
            path = get_validated_input("Enter file path")
            if path and os.path.exists(path):
                result = self.exif.extract(path)
                safe_print(self.exif.display(result))
                fp = self.exif.save_report(result, os.path.join(OSINT_DIR, "media/metadata"))
                safe_print(f"  [OK] Report saved: {fp}")
            else:
                safe_print("  File not found")
        elif sub == "2":
            url = get_validated_input("Enter image/video URL")
            if url:
                safe_print("  Downloading...")
                result = await self.exif.extract_from_url(url, os.path.join(OSINT_DIR, "media/downloads"))
                safe_print(self.exif.display(result))
                fp = self.exif.save_report(result, os.path.join(OSINT_DIR, "media/metadata"))
                safe_print(f"  [OK] Report saved: {fp}")

    async def _handle_google_dorks(self):
        domain = get_validated_input("Enter target domain for Google dorks", _validate_domain, "Invalid domain")
        if domain:
            engine = await self._get_engine()
            result = engine.google_dorks(domain)
            self._all_results.append(result)
            paged_print(result.summary())
            fp = await _save_result_async(result, "tools/google_dorks")
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_encode_decode(self):
        text = get_validated_input("Enter text to encode/decode")
        if text:
            results = OSINTEngine.encode_decode(text)
            safe_print(f"\n  {'─'*50}")
            safe_print(f"  ENCODING / DECODING RESULTS:")
            safe_print(f"  {'─'*50}")
            for fmt, val in results.items():
                safe_print(f"    {fmt:<20}: {val[:80]}")
            folder = os.path.join(OSINT_DIR, "tools/encoding")
            os.makedirs(folder, exist_ok=True)
            fp = os.path.join(folder, f"encode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            import threading
            def _write():
                with open(fp, 'w', encoding='utf-8') as f:
                    json.dump({'input': text, 'results': results}, f, indent=2)
            threading.Thread(target=_write).start()
            safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_ai_tools(self):
        safe_print(f"\n  {'='*60}")
        safe_print(f"  {'AI-POWERED OSINT TOOLS':^60}")
        safe_print(f"  {'='*60}")
        safe_print("""
    1. View AI Tool Links
    2. AI OSINT Analyzer       (Ask AI to analyze a target/data)
    3. AI Google Dork Scanner  (Live dork search + AI analysis)
    4. AI Web Search           (Search via Serper/SearXNG)
    5. AI Profile Summary      (Summarize previous scan results)
    0. Back
        """)
        sub = get_input("Select AI option", "1")

        if sub == "1":
            await self._handle_tools("ai_tools", "AI Tools")

        elif sub == "2":
            safe_print(f"\n  AI OSINT ANALYZER")
            prompt = get_validated_input("Enter your OSINT analysis question/task")
            if prompt:
                context = ""
                if confirm("Add context data? (paste OSINT data)"):
                    safe_print("  Enter context (type END on a new line to finish):")
                    lines = []
                    while True:
                        try:
                            line = input()
                            if line.strip().upper() == 'END':
                                break
                            lines.append(line)
                        except (EOFError, KeyboardInterrupt):
                            break
                    context = '\n'.join(lines)

                search_queries = []
                if confirm("Include live web search? (uses Serper/SearXNG)"):
                    sq = get_validated_input("Enter search query (or leave empty for auto)")
                    if sq:
                        search_queries = [sq]
                    else:
                        search_queries = [prompt[:100]]

                safe_print(f"\n  Analyzing with AI...")
                engine = await self._get_engine()
                result = await engine.ai_analyze(
                    prompt=prompt,
                    context=context,
                    search_queries=search_queries if search_queries else None,
                )
                self._all_results.append(result)
                paged_print(result.summary())

                if result.success and result.data.get('analysis'):
                    safe_print(f"\n  {'─'*60}")
                    for line in result.data['analysis'].split('\n'):
                        safe_print(f"  {line}")
                    safe_print(f"  {'─'*60}")

                fp = await _save_result_async(result, "ai_analysis")
                safe_print(f"\n  [OK] Saved: {fp}")

        elif sub == "3":
            safe_print(f"\n  AI GOOGLE DORK SCANNER")
            target = get_validated_input("Enter target (domain, name, email, phone, keyword, etc.)")
            if target:
                safe_print("\n  Dork category:\n    1. All\n    2. Security\n    3. Social\n    4. Leaks")
                cat_choice = get_input("Select", "1")
                dork_type = {'1': 'all', '2': 'security', '3': 'social', '4': 'leaks'}.get(cat_choice, 'all')

                safe_print(f"\n  Running AI Dork Scanner on '{target}' ({dork_type})...")
                engine = await self._get_engine()
                result = await engine.ai_dork_search(target, dork_type=dork_type)
                self._all_results.append(result)

                if result.data.get('ai_analysis'):
                    safe_print(f"\n  {'─'*60}\n  AI ANALYSIS:\n  {'─'*60}")
                    for line in result.data['ai_analysis'].split('\n'):
                        safe_print(f"  {line}")

                fp = await _save_result_async(result, "ai_analysis/dork_scanner")
                safe_print(f"\n  [OK] Saved: {fp}")

        elif sub == "4":
            safe_print(f"\n  AI WEB SEARCH")
            query = get_validated_input("Enter search query")
            if query:
                safe_print(f"\n  Searching...")
                engine = await self._get_engine()
                result = await engine.web_search(query, num_results=10)
                if result:
                    safe_print(f"\n  Engine: {result.get('search_engine', 'Unknown')}")
                    for i, item in enumerate(result.get('organic_results', []), 1):
                        safe_print(f"  {i:2}. {item.get('title', 'No title')}")
                        safe_print(f"      {item.get('link', '')}")
                    
                    folder = os.path.join(OSINT_DIR, "ai_analysis/web_search")
                    os.makedirs(folder, exist_ok=True)
                    fp = os.path.join(folder, f"search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                    import threading
                    def _write():
                        with open(fp, 'w', encoding='utf-8') as f:
                            json.dump(result, f, indent=2, default=str)
                    threading.Thread(target=_write).start()
                    safe_print(f"  [OK] Saved: {fp}")
                else:
                    safe_print("  [X] No results.")

        elif sub == "5":
            safe_print(f"\n  AI PROFILE SUMMARY")
            safe_print("  Enter data (type END on a new line to finish):")
            lines = []
            while True:
                try:
                    line = input()
                    if line.strip().upper() == 'END':
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    break
            data = '\n'.join(lines)
            if data.strip():
                safe_print(f"\n  Generating AI summary...")
                engine = await self._get_engine()
                result = await engine.ai_analyze(
                    prompt="Create a comprehensive intelligence profile summary from this OSINT data.",
                    context=data,
                )
                self._all_results.append(result)
                if result.success and result.data.get('analysis'):
                    safe_print(f"\n  {'─'*60}\n  AI PROFILE SUMMARY:\n  {'─'*60}")
                    for line in result.data['analysis'].split('\n'):
                        safe_print(f"  {line}")
                else:
                    safe_print(result.summary())
                fp = await _save_result_async(result, "ai_analysis/profile_summary")
                safe_print(f"\n  [OK] Saved: {fp}")

    async def _handle_search_tools(self):
        keyword = get_validated_input("Search keyword")
        if keyword:
            results = OSINTEngine.search_tools(keyword)
            if results:
                safe_print(f"\n  Found {len(results)} tools matching '{keyword}':")
                for t in results:
                    safe_print(f"    [{t['category']}] {t['name']} - {t['desc']}\n      {t['url']}")
            else:
                safe_print(f"  No tools found for '{keyword}'")

    async def _handle_export_all(self):
        if self._all_results:
            # We now correctly persist all OSINT results in the CLI session
            engine = await self._get_engine()
            # Temporarily set engine.results for reuse in export_results
            engine.results = self._all_results
            fp = engine.export_results(os.path.join(OSINT_DIR, "exports/full_export.json"))
            safe_print(f"\n  [OK] Exported {len(self._all_results)} results to: {fp}")
        else:
            safe_print("  No results to export yet. Run some queries first.")

    async def _handle_browse_folder(self):
        os.makedirs(OSINT_DIR, exist_ok=True)
        import subprocess
        if sys.platform == 'win32':
            os.startfile(OSINT_DIR)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', OSINT_DIR])
        else:
            subprocess.Popen(['xdg-open', OSINT_DIR])
        safe_print(f"  Opened: {OSINT_DIR}")

    async def _handle_powerful_scanner(self):
        safe_print(f"\n  {'='*60}\n  {'POWERFUL SCANNER':^60}\n  {'='*60}")
        
        email = get_validated_input("Enter email address (REQUIRED)", _validate_email, "Invalid email format")
        if not email:
            safe_print("  [X] Valid email is required for Powerful Scanner")
            return

        username = get_input("Enter username (optional, press Enter to skip)")
        phone = get_input("Enter phone number with country code (optional)")
        full_name = get_input("Enter full name (optional)")

        if not confirm("Start Powerful Scanner?"):
            return

        def progress_cb(current, total, msg):
            bar_len = 30
            filled = int(bar_len * current / max(total, 1))
            bar = '█' * filled + '░' * (bar_len - filled)
            pct = int(100 * current / max(total, 1))
            # Fix progress to output in-place
            sys.stdout.write(f"\r  [{bar}] {pct:3d}% | Step {current}/{total} | {msg[:30].ljust(30)}")
            sys.stdout.flush()

        safe_print(f"\n  Starting Powerful Scanner...")
        engine = await self._get_engine()
        results = await engine.powerful_scanner(
            email=email,
            username=username,
            phone=phone,
            full_name=full_name,
            progress_callback=progress_cb
        )
        safe_print() # new line after progress bar

        for name, result in results.items():
            if name != '_summary':
                self._all_results.append(result)
            if hasattr(result, 'summary'):
                paged_print(result.summary())
            fp = await _save_result_async(result, f"powerful_scanner/{name}")

        safe_print(f"\n  [OK] All results saved to: {os.path.join(OSINT_DIR, 'powerful_scanner')}")

        import os as _os
        api_key = _os.environ.get('OPENROUTER_API_KEY', '')
        if api_key and api_key != 'sk-or-v1-your-key-here':
            if confirm("\n  Run AI analysis on scan results? (Dolphin Mistral / Trinity)"):
                safe_print(f"\n  Generating AI intelligence summary...")
                all_data = {}
                for name, res in results.items():
                    if name == '_summary': continue
                    if hasattr(res, 'data'): all_data[name] = res.data

                context = json.dumps(all_data, indent=2, default=str)[:8000]
                ai_result = await engine.ai_analyze(
                    prompt=f"Create a complete intelligence dossier from this OSINT scan. Target email: {email}.",
                    context=context,
                )
                if ai_result.success and ai_result.data.get('analysis'):
                    safe_print(f"\n  {'='*60}\n  AI INTELLIGENCE SUMMARY\n  {'='*60}")
                    for line in ai_result.data['analysis'].split('\n'):
                        safe_print(f"  {line}")
                    fp = await _save_result_async(ai_result, "powerful_scanner/ai_summary")
                    safe_print(f"\n  [OK] AI summary saved: {fp}")

    async def _handle_spiderfoot(self):
        target = get_validated_input("Enter target")
        if not target:
            return

        # Fixed: Call static method on class, not instance method incorrectly
        detected = OSINTEngine._detect_target_type(target)
        safe_print(f"\n  Detected type: {detected.upper()}")

        if not confirm(f"Run SpiderFoot scan on '{target}' (type: {detected})?"):
            return

        safe_print(f"\n  Running SpiderFoot-style scan...\n")
        engine = await self._get_engine()
        result = await engine.spiderfoot_scan(target)
        self._all_results.append(result)

        paged_print(result.summary())
        fp = await _save_result_async(result, f"spiderfoot/{detected}")
        safe_print(f"\n  [OK] Saved: {fp}")


# =============================================================================
# Entry Point
# =============================================================================

async def run_osint_cli():
    """Launch the OSINT CLI"""
    cli = OSINT_CLI()
    await cli.run()


if __name__ == "__main__":
    asyncio.run(run_osint_cli())
