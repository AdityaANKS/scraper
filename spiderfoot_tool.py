"""
================================================================================
SPIDERFOOT_TOOL.PY - OSINT Automation Tool (Powered by SpiderFoot)
================================================================================
Version: 1.0
Last Updated: 2026

Full-featured OSINT automation tool integrating SpiderFoot's 200+ modules.
Manages a local SpiderFoot server, wraps its REST API, and provides an
interactive CLI for launching scans, viewing results, and exporting data.

FEATURES:
---------
  • Auto-Install        — Clone SpiderFoot from GitHub if not present
  • Server Management   — Start/stop/status of background SpiderFoot server
  • New Scan            — Launch scans against any target type
  • Quick Scan          — One-click scan with smart module selection
  • Scan Monitoring     — Real-time progress tracking
  • Results Viewer      — Browse and search scan results
  • Module Browser      — View all 200+ available modules
  • Export              — Save results as JSON or CSV

SPIDERFOOT: https://github.com/smicallef/spiderfoot
================================================================================
"""

import os
import sys
import json
import time
import signal
import asyncio
import subprocess
import socket
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode, quote

# Import project utilities
from utils import (
    safe_print, log_info, log_warn, log_error, log_success, log_debug,
    sanitize_filename
)
from config import config

# =============================================================================
# Configuration
# =============================================================================

SPIDERFOOT_DIR = os.path.join(config.paths.base_dir, "spiderfoot")
SPIDERFOOT_REPO = "https://github.com/smicallef/spiderfoot.git"
SPIDERFOOT_HOST = "127.0.0.1"
SPIDERFOOT_PORT = 5001
SPIDERFOOT_DATA_DIR = os.path.join(config.paths.base_dir, "spiderfoot_data")
os.makedirs(SPIDERFOOT_DATA_DIR, exist_ok=True)

# Scan types matching SpiderFoot's built-in scan types
SCAN_TYPES = {
    "1": ("ALL", "All modules — comprehensive scan"),
    "2": ("FOOTPRINT", "Footprint — map the target's digital presence"),
    "3": ("INVESTIGATE", "Investigate — detailed deep-dive"),
    "4": ("PASSIVE", "Passive — no direct contact with target"),
}

# Target type detection
TARGET_TYPES = {
    "IP_ADDRESS": "IP Address",
    "INTERNET_NAME": "Domain/Hostname",
    "EMAILADDR": "Email Address",
    "PHONE_NUMBER": "Phone Number",
    "HUMAN_NAME": "Person's Name",
    "USERNAME": "Username",
    "BITCOIN_ADDRESS": "Bitcoin Address",
    "BGP_AS_OWNER": "ASN",
    "NETBLOCK_OWNER": "Network Block (CIDR)",
}


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


def _detect_target_type(target: str) -> str:
    """Auto-detect SpiderFoot target type from input string."""
    import re
    target = target.strip()

    # IP address
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', target):
        return "IP_ADDRESS"
    # CIDR
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$', target):
        return "NETBLOCK_OWNER"
    # Email
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', target):
        return "EMAILADDR"
    # Phone
    if re.match(r'^\+?\d[\d\s\-()]{8,}$', target):
        return "PHONE_NUMBER"
    # ASN
    if re.match(r'^AS\d+$', target, re.I):
        return "BGP_AS_OWNER"
    # Bitcoin
    if re.match(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', target):
        return "BITCOIN_ADDRESS"
    # Username (starts with @)
    if target.startswith('@'):
        return "USERNAME"
    # Domain/hostname
    if re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$', target):
        return "INTERNET_NAME"
    # Default: human name
    return "HUMAN_NAME"


# =============================================================================
# SpiderFoot REST API Client
# =============================================================================

class SpiderFootClient:
    """Client for SpiderFoot's REST API."""

    def __init__(self, host: str = SPIDERFOOT_HOST, port: int = SPIDERFOOT_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._process = None

    # ---- Server lifecycle ----

    def is_installed(self) -> bool:
        """Check if SpiderFoot is cloned locally."""
        sf_script = os.path.join(SPIDERFOOT_DIR, "sf.py")
        return os.path.isfile(sf_script)

    def install(self) -> bool:
        """Clone SpiderFoot from GitHub and install requirements."""
        _print_header("INSTALLING SPIDERFOOT")
        safe_print(f"  Cloning from: {SPIDERFOOT_REPO}")
        safe_print(f"  Into:         {SPIDERFOOT_DIR}")
        safe_print("")

        try:
            # Clone
            result = subprocess.run(
                ["git", "clone", "--depth", "1", SPIDERFOOT_REPO, SPIDERFOOT_DIR],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                log_error(f"Git clone failed: {result.stderr[:200]}")
                return False
            log_success("Repository cloned successfully!")

            # Install requirements
            safe_print("  Installing Python dependencies...")
            req_file = os.path.join(SPIDERFOOT_DIR, "requirements.txt")
            if os.path.isfile(req_file):
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    log_warn(f"Some dependencies may have failed: {result.stderr[:200]}")
                else:
                    log_success("Dependencies installed!")

            return True

        except FileNotFoundError:
            log_error("Git not found. Please install Git: https://git-scm.com/downloads")
            return False
        except subprocess.TimeoutExpired:
            log_error("Installation timed out. Check your network connection.")
            return False
        except Exception as e:
            log_error(f"Installation failed: {e}")
            return False

    def _find_free_port(self, start: int = 5001, end: int = 5010) -> int:
        """Find a free port in the given range."""
        for port in range(start, end):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind((self.host, port))
                    return port
            except OSError:
                continue
        return start  # fallback

    def is_running(self) -> bool:
        """Check if the SpiderFoot server is responding."""
        try:
            import urllib.request
            url = f"{self.base_url}/ping"
            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_server(self) -> bool:
        """Start the SpiderFoot server as a background process."""
        if self.is_running():
            log_info(f"SpiderFoot is already running on {self.base_url}")
            return True

        if not self.is_installed():
            if _confirm("SpiderFoot is not installed. Install now?"):
                if not self.install():
                    return False
            else:
                return False

        # Find free port
        self.port = self._find_free_port(SPIDERFOOT_PORT)
        self.base_url = f"http://{self.host}:{self.port}"

        sf_script = os.path.join(SPIDERFOOT_DIR, "sf.py")
        safe_print(f"  Starting SpiderFoot on {self.base_url}...")

        try:
            self._process = subprocess.Popen(
                [sys.executable, sf_script, "-l", f"{self.host}:{self.port}"],
                cwd=SPIDERFOOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )

            # Wait for server to come online (up to 60s — SF can be slow)
            for i in range(60):
                # Check if process died early
                if self._process.poll() is not None:
                    _, stderr = self._process.communicate(timeout=2)
                    err_msg = stderr.decode('utf-8', errors='replace')[:300] if stderr else 'Unknown error'
                    log_error(f"SpiderFoot process exited unexpectedly:\n  {err_msg}")
                    self._process = None
                    return False

                time.sleep(1)
                if self.is_running():
                    log_success(f"SpiderFoot server started on {self.base_url}")
                    log_info(f"  Web UI available at: {self.base_url}")
                    return True
                if i % 5 == 0:
                    safe_print(f"  Waiting for server... ({i+1}s)")

            log_error("Server failed to start within 60 seconds.")
            self.stop_server()
            return False

        except Exception as e:
            log_error(f"Failed to start server: {e}")
            return False

    def stop_server(self) -> None:
        """Stop the SpiderFoot server."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
                log_info("SpiderFoot server stopped.")
            except subprocess.TimeoutExpired:
                self._process.kill()
                log_warn("SpiderFoot server force-killed.")
            except Exception as e:
                log_debug(f"Stop error: {e}")
            self._process = None
        else:
            log_info("No managed SpiderFoot process to stop.")

    # ---- API methods ----

    def _api_get(self, endpoint: str, params: Dict = None) -> Any:
        """Make a GET request to a SpiderFoot CherryPy endpoint."""
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/{endpoint}"
        if params:
            url += f"?{urlencode(params)}"

        try:
            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode('utf-8')
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return data
        except urllib.error.HTTPError as e:
            log_debug(f"SpiderFoot API HTTP {e.code}: {endpoint} — {e.reason}")
            return None
        except urllib.error.URLError as e:
            log_debug(f"SpiderFoot API connection error: {e.reason}")
            return None
        except Exception as e:
            log_debug(f"SpiderFoot API error: {e}")
            return None

    def _api_post(self, endpoint: str, data: Dict) -> Any:
        """Make a POST request with form data to SpiderFoot."""
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/{endpoint}"
        post_data = urlencode(data).encode('utf-8')

        try:
            req = urllib.request.Request(url, data=post_data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            req.add_header('Accept', 'application/json')
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode('utf-8')
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    return body
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:300] if e.fp else ''
            log_debug(f"SpiderFoot POST {endpoint} HTTP {e.code}: {body}")
            return None
        except Exception as e:
            log_debug(f"SpiderFoot POST error: {e}")
            return None

    def list_scans(self) -> Optional[List]:
        """List all scans."""
        return self._api_get("scanlist")

    def new_scan(self, target: str, scan_name: str = None,
                 scan_type: str = "ALL", modules: str = "") -> Optional[str]:
        """Start a new scan via POST /startscan. Returns scan ID."""
        if not scan_name:
            scan_name = f"Scan_{target}_{datetime.now().strftime('%H%M%S')}"

        target_type = _detect_target_type(target)

        # SpiderFoot uses its own regex-based target type detection.
        # We must format the target string to match its expectations:
        #   HUMAN_NAME:   "First Last" (must be wrapped in double quotes)
        #   USERNAME:     "username"   (wrapped in double quotes)
        #   PHONE_NUMBER: +1234567890  (must have + prefix)
        scan_target = target
        if target_type == "HUMAN_NAME":
            if not scan_target.startswith('"'):
                scan_target = f'"{scan_target}"'
        elif target_type == "USERNAME":
            clean = scan_target.lstrip('@')
            if not clean.startswith('"'):
                scan_target = f'"{clean}"'
        elif target_type == "PHONE_NUMBER":
            if not scan_target.startswith('+'):
                scan_target = f'+{scan_target}'

        # SpiderFoot usecase: 'all' (special) or title-case group names: Passive, Footprint, Investigate
        usecase_val = scan_type.strip().upper()
        if usecase_val == "ALL":
            usecase_val = "all"
        else:
            # Title case: PASSIVE -> Passive, FOOTPRINT -> Footprint
            usecase_val = scan_type.strip().capitalize()

        form_data = {
            "scanname": scan_name,
            "scantarget": scan_target,
            "usecase": usecase_val,
            "modulelist": modules,
            "typelist": "",
        }

        result = self._api_post("startscan", form_data)

        # SpiderFoot returns ["SUCCESS", scanId] when Accept: application/json
        if result and isinstance(result, list) and len(result) >= 2:
            if result[0] == "SUCCESS":
                return str(result[1])
            elif result[0] == "ERROR":
                log_error(f"SpiderFoot scan error: {result[1]}")
                return None
        elif result and isinstance(result, dict):
            return str(result.get('scanId', result.get('id', ''))) or None
        elif result and isinstance(result, str) and len(result) < 100:
            # Could be a plain scan ID string
            cleaned = result.strip()
            if cleaned and cleaned != "SUCCESS":
                return cleaned

        # Fallback: check scanlist for the newest scan
        time.sleep(1)
        scans = self.list_scans()
        if scans and isinstance(scans, list) and len(scans) > 0:
            newest = scans[0]
            if isinstance(newest, list) and len(newest) > 0:
                return str(newest[0])
        return None

    def scan_status(self, scan_id: str) -> Optional[Dict]:
        """Get scan status."""
        result = self._api_get("scanstatus", {"id": scan_id})
        if result and isinstance(result, list) and len(result) > 0:
            # SpiderFoot returns [id, name, created, started, ended, status, riskmatrix]
            row = result
            return {
                "scan_id": row[0] if len(row) > 0 else scan_id,
                "name": row[1] if len(row) > 1 else "Unknown",
                "created": row[2] if len(row) > 2 else "",
                "started": row[3] if len(row) > 3 else "",
                "ended": row[4] if len(row) > 4 else "",
                "status": row[5] if len(row) > 5 else "UNKNOWN",
                "risk_matrix": row[6] if len(row) > 6 else {},
            }
        return None

    def scan_results(self, scan_id: str, event_type: str = "ALL") -> Optional[List]:
        """Get scan results via /scaneventresults."""
        params = {"id": scan_id}
        if event_type != "ALL":
            params["eventType"] = event_type
        return self._api_get("scaneventresults", params)

    def scan_result_summary(self, scan_id: str) -> Optional[List]:
        """Get summary of result types in a scan."""
        return self._api_get("scansummary", {"id": scan_id, "by": "type"})

    def delete_scan(self, scan_id: str) -> bool:
        """Delete a scan."""
        result = self._api_get("scandelete", {"id": scan_id})
        return result is not None

    def list_modules(self) -> Optional[List]:
        """List available modules."""
        return self._api_get("modules")

    def list_event_types(self) -> Optional[List]:
        """List available event types."""
        return self._api_get("eventtypes")

    def search_results(self, scan_id: str, query: str) -> Optional[List]:
        """Search within scan results."""
        return self._api_get("scaneventresults", {"id": scan_id, "eventType": query})

    def scan_logs(self, scan_id: str, limit: int = 50) -> Optional[List]:
        """Get scan logs."""
        return self._api_get("scanlog", {"id": scan_id, "limit": str(limit)})


# =============================================================================
# Global Client Instance
# =============================================================================

_client = SpiderFootClient()


# =============================================================================
# CLI Handlers
# =============================================================================

def handle_server_management() -> None:
    """Start/stop/check SpiderFoot server."""
    _print_header("SERVER MANAGEMENT")

    is_installed = _client.is_installed()
    is_running = _client.is_running()

    safe_print(f"  Installed : {'[OK] ' + SPIDERFOOT_DIR if is_installed else '[X] Not installed'}")
    safe_print(f"  Running   : {'[OK] ' + _client.base_url if is_running else '[X] Not running'}")

    safe_print("")
    safe_print("  Actions:")
    if not is_installed:
        safe_print("    1. Install SpiderFoot")
    elif not is_running:
        safe_print("    1. Start Server")
    else:
        safe_print("    1. Open Web UI in Browser")
    safe_print("    2. Stop Server")
    safe_print("    3. Reinstall / Update")
    safe_print("    0. Back")

    choice = _get_input("  Select")

    if choice == "1":
        if not is_installed:
            _client.install()
        elif not is_running:
            _client.start_server()
        else:
            import webbrowser
            webbrowser.open(_client.base_url)
            log_info(f"Opened {_client.base_url} in browser")
    elif choice == "2":
        _client.stop_server()
    elif choice == "3":
        if os.path.isdir(SPIDERFOOT_DIR):
            if _confirm("Delete existing installation and re-clone?", default=False):
                import shutil
                shutil.rmtree(SPIDERFOOT_DIR, ignore_errors=True)
                _client.install()
        else:
            _client.install()


def handle_new_scan() -> None:
    """Launch a new SpiderFoot scan."""
    _print_header("NEW SPIDERFOOT SCAN")

    if not _client.is_running():
        safe_print("  Server is not running.")
        if _confirm("  Start server now?"):
            if not _client.start_server():
                return
        else:
            return

    target = _get_input("  Enter target (domain, IP, email, phone, username, etc.)")
    if not target:
        return

    target_type = _detect_target_type(target)
    safe_print(f"  Detected type: {TARGET_TYPES.get(target_type, target_type)}")

    safe_print("")
    safe_print("  Scan type:")
    for key, (name, desc) in SCAN_TYPES.items():
        safe_print(f"    {key}. {name:12} — {desc}")

    scan_choice = _get_input("  Select scan type", "4")
    scan_type = SCAN_TYPES.get(scan_choice, SCAN_TYPES["4"])[0]

    scan_name = _get_input("  Scan name (optional)",
                           f"Scan_{target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    safe_print(f"\n  Starting {scan_type} scan on {target}...")

    scan_id = _client.new_scan(target, scan_name, scan_type)

    if scan_id:
        log_success(f"Scan started! ID: {scan_id}")
        safe_print(f"  View in browser: {_client.base_url}/scaninfo?id={scan_id}")

        if _confirm("\n  Monitor scan progress?"):
            _monitor_scan(scan_id)
    else:
        log_error("Failed to start scan. Check server logs.")


def _monitor_scan(scan_id: str) -> None:
    """Monitor a running scan with progress updates."""
    safe_print("\n  Monitoring scan (Ctrl+C to stop monitoring)...\n")

    try:
        while True:
            status = _client.scan_status(scan_id)
            if not status:
                safe_print("  Could not fetch status.")
                break

            state = status.get('status', 'UNKNOWN')
            elements = status.get('elements', 0)
            name = status.get('name', 'Unknown')

            # Build progress display
            if state in ("FINISHED", "ABORTED", "ERROR-FAILED"):
                safe_print(f"\r  [{state}] {name} — {elements} data elements found")
                break
            else:
                safe_print(f"\r  [{state}] {name} — {elements} elements found so far...", end="")
                sys.stdout.flush()

            time.sleep(5)

    except KeyboardInterrupt:
        safe_print("\n\n  Monitoring stopped. Scan continues in background.")

    safe_print("")


def handle_view_scans() -> None:
    """View all scans."""
    _print_header("ALL SCANS")

    if not _client.is_running():
        log_error("Server is not running. Start it first.")
        return

    scans = _client.list_scans()
    if not scans:
        safe_print("  No scans found.")
        return

    safe_print(f"  {'#':>3}  {'Status':10}  {'Target':25}  {'Name':25}  {'Elements':>8}")
    _print_line()

    for i, scan in enumerate(scans, 1):
        if isinstance(scan, list) and len(scan) >= 7:
            scan_id = scan[0]
            name = str(scan[1])[:25]
            target = str(scan[2])[:25]
            status = str(scan[5])
            elements = scan[6] if len(scan) > 6 else 0
            safe_print(f"  {i:3}  {status:10}  {target:25}  {name:25}  {elements:>8}")

    safe_print("")
    choice = _get_input("  Enter scan # to view results (or 0 to go back)")
    if choice and choice != "0":
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(scans):
                scan_id = scans[idx][0]
                handle_scan_results_detail(str(scan_id))
        except ValueError:
            pass


def handle_scan_results_detail(scan_id: str) -> None:
    """View detailed results for a specific scan."""
    _print_subheader(f"SCAN RESULTS — {scan_id}")

    # Get summary of event types
    summary = _client.scan_result_summary(scan_id)
    if summary:
        safe_print(f"\n  {'Event Type':40}  {'Count':>8}")
        _print_line("─", 55)
        total = 0
        for row in summary:
            if isinstance(row, list) and len(row) >= 2:
                etype = str(row[0])[:40]
                count = row[1]
                total += count
                safe_print(f"  {etype:40}  {count:>8}")
        _print_line("─", 55)
        safe_print(f"  {'TOTAL':40}  {total:>8}")

    safe_print("")
    safe_print("  Options:")
    safe_print("    1. View all results")
    safe_print("    2. Search results")
    safe_print("    3. Export to JSON")
    safe_print("    4. Export to CSV")
    safe_print("    5. Delete this scan")
    safe_print("    0. Back")

    choice = _get_input("  Select")

    if choice == "1":
        results = _client.scan_results(scan_id)
        if results:
            _display_results(results[:50])
        else:
            safe_print("  No results found.")

    elif choice == "2":
        query = _get_input("  Search query")
        if query:
            results = _client.search_results(scan_id, query)
            if results:
                _display_results(results[:50])
            else:
                safe_print("  No matching results.")

    elif choice == "3":
        _export_results(scan_id, "json")

    elif choice == "4":
        _export_results(scan_id, "csv")

    elif choice == "5":
        if _confirm("  Really delete this scan?", default=False):
            if _client.delete_scan(scan_id):
                log_success("Scan deleted.")
            else:
                log_error("Failed to delete scan.")


def _display_results(results: List, max_display: int = 50) -> None:
    """Display scan results in a readable format."""
    safe_print(f"\n  Showing {min(len(results), max_display)} of {len(results)} results:\n")

    for i, row in enumerate(results[:max_display], 1):
        if isinstance(row, list) and len(row) >= 4:
            event_type = row[0] if len(row) > 0 else ""
            data = str(row[1])[:80] if len(row) > 1 else ""
            module = row[3] if len(row) > 3 else ""
            safe_print(f"  {i:3}. [{event_type:30}] {data}")
            if module:
                safe_print(f"       Module: {module}")

    if len(results) > max_display:
        safe_print(f"\n  ... and {len(results) - max_display} more results")


def _export_results(scan_id: str, fmt: str = "json") -> None:
    """Export scan results to file."""
    results = _client.scan_results(scan_id)
    if not results:
        log_error("No results to export.")
        return

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"spiderfoot_{scan_id}_{ts}"

    if fmt == "json":
        filepath = os.path.join(SPIDERFOOT_DATA_DIR, f"{filename}.json")
        structured = []
        for row in results:
            if isinstance(row, list) and len(row) >= 4:
                structured.append({
                    "event_type": row[0],
                    "data": row[1],
                    "source_module": row[3] if len(row) > 3 else "",
                    "source_data": row[2] if len(row) > 2 else "",
                    "confidence": row[4] if len(row) > 4 else "",
                })
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(structured, f, indent=2, ensure_ascii=False, default=str)

    elif fmt == "csv":
        import csv
        filepath = os.path.join(SPIDERFOOT_DATA_DIR, f"{filename}.csv")
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Event Type", "Data", "Source Data", "Module", "Confidence"])
            for row in results:
                if isinstance(row, list):
                    writer.writerow(row[:5] if len(row) >= 5 else row + [""] * (5 - len(row)))

    log_success(f"Exported to: {filepath}")


def handle_quick_scan() -> None:
    """Quick one-step scan with smart defaults."""
    _print_header("QUICK SCAN")

    if not _client.is_running():
        safe_print("  Server is not running.")
        if _confirm("  Start server now?"):
            if not _client.start_server():
                return
        else:
            return

    target = _get_input("  Enter target")
    if not target:
        return

    target_type = _detect_target_type(target)
    safe_print(f"  Detected: {TARGET_TYPES.get(target_type, target_type)}")
    safe_print("  Running PASSIVE scan (no direct contact with target)...")

    scan_name = f"Quick_{target}_{datetime.now().strftime('%H%M%S')}"
    scan_id = _client.new_scan(target, scan_name, "PASSIVE")

    if scan_id:
        log_success(f"Quick scan started! ID: {scan_id}")
        _monitor_scan(scan_id)

        # Auto-show results
        summary = _client.scan_result_summary(scan_id)
        if summary:
            safe_print("")
            _print_subheader("RESULTS SUMMARY")
            total = 0
            for row in summary:
                if isinstance(row, list) and len(row) >= 2:
                    safe_print(f"  {str(row[0]):40}  {row[1]:>6}")
                    total += row[1]
            safe_print(f"  {'─' * 49}")
            safe_print(f"  {'TOTAL':40}  {total:>6}")

        if _confirm("\n  Export results to JSON?"):
            _export_results(scan_id, "json")
    else:
        log_error("Failed to start scan.")


def handle_list_modules() -> None:
    """List all available SpiderFoot modules."""
    _print_header("AVAILABLE MODULES")

    if not _client.is_running():
        log_error("Server is not running. Start it first.")
        return

    modules = _client.list_modules()
    if not modules:
        safe_print("  Could not retrieve module list.")
        return

    if isinstance(modules, list):
        safe_print(f"  Total modules: {len(modules)}\n")
        for i, mod in enumerate(modules, 1):
            if isinstance(mod, list) and len(mod) >= 3:
                name = mod[0]
                desc = str(mod[1])[:60]
                safe_print(f"  {i:3}. {name:30}  {desc}")
            elif isinstance(mod, dict):
                name = mod.get('name', mod.get('module', ''))
                desc = str(mod.get('descr', mod.get('description', '')))[:60]
                safe_print(f"  {i:3}. {name:30}  {desc}")
    elif isinstance(modules, dict):
        safe_print(f"  Total modules: {len(modules)}\n")
        for i, (name, info) in enumerate(modules.items(), 1):
            desc = ""
            if isinstance(info, dict):
                desc = str(info.get('descr', info.get('description', '')))[:60]
            safe_print(f"  {i:3}. {name:30}  {desc}")


def handle_export_results() -> None:
    """Export scan results."""
    _print_header("EXPORT RESULTS")

    if not _client.is_running():
        log_error("Server is not running.")
        return

    scans = _client.list_scans()
    if not scans:
        safe_print("  No scans available.")
        return

    safe_print(f"  {'#':>3}  {'Status':10}  {'Target':25}  {'Name':25}")
    _print_line()
    for i, scan in enumerate(scans, 1):
        if isinstance(scan, list) and len(scan) >= 6:
            safe_print(f"  {i:3}  {str(scan[5]):10}  {str(scan[2])[:25]:25}  {str(scan[1])[:25]:25}")

    choice = _get_input("  Select scan # to export")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(scans):
            scan_id = str(scans[idx][0])
            safe_print("  Format:")
            safe_print("    1. JSON")
            safe_print("    2. CSV")
            fmt_choice = _get_input("  Select", "1")
            fmt = "csv" if fmt_choice == "2" else "json"
            _export_results(scan_id, fmt)
    except ValueError:
        safe_print("  Invalid selection.")


# =============================================================================
# SpiderFoot Tool Sub-Menu
# =============================================================================

def display_spiderfoot_menu() -> None:
    """Display the SpiderFoot tool sub-menu."""
    safe_print("""
 SPIDERFOOT — OSINT AUTOMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SCANNING:
    1.  Quick Scan            (One-click passive OSINT)
    2.  New Scan              (Custom scan with type selection)
    3.  View All Scans        (List & browse scan results)

  MODULES:
    4.  List Modules          (View 200+ available modules)

  DATA:
    5.  Export Results         (Save scan data as JSON/CSV)

  SERVER:
    6.  Server Management     (Start / Stop / Install / Web UI)

    0.  Back to Main Menu
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


def _check_spiderfoot_status() -> None:
    """Show SpiderFoot status."""
    safe_print("  SpiderFoot Status:")
    safe_print(f"    Installed  : {'[OK]' if _client.is_installed() else '[X] Not installed'}")
    safe_print(f"    Server     : {'[OK] ' + _client.base_url if _client.is_running() else '[X] Not running'}")
    safe_print(f"    Data dir   : {SPIDERFOOT_DATA_DIR}")
    safe_print("")


async def run_spiderfoot_cli() -> None:
    """Run the SpiderFoot tool interactive CLI."""
    while True:
        display_spiderfoot_menu()
        _check_spiderfoot_status()

        choice = _get_input("Enter choice")

        if choice == "0" or not choice:
            break

        handler_map = {
            "1": handle_quick_scan,
            "2": handle_new_scan,
            "3": handle_view_scans,
            "4": handle_list_modules,
            "5": handle_export_results,
            "6": handle_server_management,
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
# Public API for Namu AI Integration
# =============================================================================

async def spiderfoot_scan(target: str, scan_type: str = "PASSIVE",
                          scan_name: str = None) -> Dict[str, Any]:
    """Launch a SpiderFoot scan (for Namu AI tool calls)."""
    if not _client.is_running():
        if not _client.start_server():
            return {"success": False, "error": "Could not start SpiderFoot server"}

    target_type = _detect_target_type(target)

    if not scan_name:
        scan_name = f"AI_Scan_{target}_{datetime.now().strftime('%H%M%S')}"

    scan_id = _client.new_scan(target, scan_name, scan_type.upper())

    if scan_id:
        return {
            "success": True,
            "scan_id": scan_id,
            "target": target,
            "target_type": TARGET_TYPES.get(target_type, target_type),
            "scan_type": scan_type,
            "scan_name": scan_name,
            "web_ui": f"{_client.base_url}/scaninfo?id={scan_id}",
            "message": f"SpiderFoot {scan_type} scan started on {target} (ID: {scan_id}). "
                       f"Use spiderfoot_results with this scan_id to get results.",
        }
    return {"success": False, "error": "Failed to start scan"}


async def spiderfoot_results(scan_id: str) -> Dict[str, Any]:
    """Get SpiderFoot scan results (for Namu AI tool calls)."""
    if not _client.is_running():
        return {"success": False, "error": "SpiderFoot server is not running"}

    status = _client.scan_status(scan_id)
    if not status:
        return {"success": False, "error": f"Scan {scan_id} not found"}

    summary = _client.scan_result_summary(scan_id)
    result_data = {
        "success": True,
        "scan_id": scan_id,
        "status": status.get("status", "UNKNOWN"),
        "target": status.get("target", ""),
        "name": status.get("name", ""),
        "elements": status.get("elements", 0),
    }

    if summary:
        result_data["event_types"] = {}
        for row in summary:
            if isinstance(row, list) and len(row) >= 2:
                result_data["event_types"][row[0]] = row[1]

    # Get actual results (limited)
    results = _client.scan_results(scan_id)
    if results:
        structured = []
        for row in results[:100]:
            if isinstance(row, list) and len(row) >= 2:
                structured.append({
                    "type": row[0],
                    "data": str(row[1])[:200],
                    "module": row[3] if len(row) > 3 else "",
                })
        result_data["results"] = structured
        result_data["total_results"] = len(results)

    return result_data


async def spiderfoot_status() -> Dict[str, Any]:
    """Get SpiderFoot server status and running scans (for Namu AI)."""
    is_running = _client.is_running()
    result = {
        "success": True,
        "installed": _client.is_installed(),
        "running": is_running,
        "url": _client.base_url if is_running else None,
    }

    if is_running:
        scans = _client.list_scans()
        if scans:
            result["scans"] = []
            for scan in scans:
                if isinstance(scan, list) and len(scan) >= 7:
                    result["scans"].append({
                        "id": scan[0],
                        "name": scan[1],
                        "target": scan[2],
                        "status": scan[5],
                        "elements": scan[6] if len(scan) > 6 else 0,
                    })

    return result


async def spiderfoot_modules() -> Dict[str, Any]:
    """List available SpiderFoot modules (for Namu AI)."""
    if not _client.is_running():
        return {"success": False, "error": "SpiderFoot server is not running"}

    modules = _client.list_modules()
    if not modules:
        return {"success": False, "error": "Could not retrieve modules"}

    mod_list = []
    if isinstance(modules, list):
        for mod in modules:
            if isinstance(mod, list) and len(mod) >= 3:
                mod_list.append({"name": mod[0], "description": mod[1], "type": mod[2]})
            elif isinstance(mod, dict):
                mod_list.append(mod)
    elif isinstance(modules, dict):
        for name, info in modules.items():
            entry = {"name": name}
            if isinstance(info, dict):
                entry.update(info)
            mod_list.append(entry)

    return {
        "success": True,
        "total": len(mod_list),
        "modules": mod_list[:50],
        "message": f"SpiderFoot has {len(mod_list)} modules available.",
    }
