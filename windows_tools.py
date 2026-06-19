"""
================================================================================
WINDOWS_TOOLS.PY - Windows OS Integration for Namu AI Agent
================================================================================
Version: 1.1 — WITH SAFETY GUARDS
Last Updated: 2026

Provides OS-level actions that the Namu AI agent can execute:
  - Open files with default or specific applications
  - Open folders in Windows Explorer
  - Open URLs in default browser
  - Launch applications (VS Code, Notepad++, etc.)
  - Find recent files in directories
  - Search for files by name/extension

SAFETY FEATURES:
  - User confirmation prompt before every OS action
  - Path sandboxing — only allowed directories can be accessed
  - App whitelist — only known-safe apps can be launched
  - Blocked file extensions — prevents opening executables/scripts
  - Action audit log — every action is logged to file
  - URL safety checks — warns about non-HTTPS / suspicious URLs

================================================================================
"""

import os
import sys
import glob
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


# Simple colored output (no dependency)
def _cprint(text: str, color: str = ''):
    """Print with ANSI color. Used for the safety confirmation banner."""
    colors = {'yellow': '\033[93m', 'green': '\033[92m', 'red': '\033[91m', 'reset': '\033[0m', 'bold': '\033[1m'}
    prefix = colors.get(color, '')
    reset = colors.get('reset', '')
    print(f"{prefix}{text}{reset}")


# =============================================================================
# SAFETY CONFIGURATION
# =============================================================================

# Directories the AI is allowed to access (will be expanded with resolved paths)
ALLOWED_DIRECTORIES = [
    os.path.normpath(os.path.dirname(os.path.abspath(__file__))),       # Project root (c:\scraper)
    os.path.normpath(os.path.expanduser("~")),                          # User home
]

# File extensions the AI is BLOCKED from opening (security risk)
BLOCKED_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.ps1', '.vbs', '.vbe', '.js', '.jse',
    '.wsf', '.wsh', '.msi', '.msp', '.scr', '.com', '.pif', '.reg',
    '.inf', '.cpl', '.hta', '.lnk', '.sys', '.dll',
}

# Apps the AI is ALLOWED to launch (whitelist)
WHITELISTED_APPS = {
    # Code editors
    "vscode", "vs code", "code",
    "notepad++", "notepad", "sublime", "vim",
    # Browsers
    "chrome", "firefox", "edge", "brave",
    # Media
    "vlc",
    # File managers
    "explorer",
    # Terminal (read-only context)
    "cmd", "powershell", "terminal",
}

# Known Applications Registry (exe paths)
APP_REGISTRY = {
    "vscode":       ["code"],
    "vs code":      ["code"],
    "code":         ["code"],
    "notepad++":    ["notepad++"],
    "notepad":      ["notepad"],
    "sublime":      ["subl"],
    "vim":          ["vim"],
    "chrome":       [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "firefox":      [r"C:\Program Files\Mozilla Firefox\firefox.exe"],
    "edge":         ["msedge"],
    "brave":        [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "vlc":          [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                     r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
    "explorer":     ["explorer"],
    "cmd":          ["cmd"],
    "powershell":   ["powershell"],
    "terminal":     ["wt"],
}

# Audit log file path
AUDIT_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_action_log.txt")

# Safety mode: if True, user must confirm every OS action
REQUIRE_CONFIRMATION = True


# =============================================================================
# SAFETY FUNCTIONS
# =============================================================================

def _log_action(action: str, target: str, result: str, user_approved: bool = True):
    """Log every OS action to audit file for tracking."""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status = "APPROVED" if user_approved else "DENIED"
        entry = f"[{timestamp}] [{status}] {action}: {target} -> {result}\n"
        with open(AUDIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(entry)
    except Exception:
        pass  # Logging should never break functionality


def _ask_user_confirmation(action: str, target: str, details: str = '') -> bool:
    """
    Ask the user for explicit confirmation before performing an OS action.
    Returns True if user approves, False otherwise.
    """
    if not REQUIRE_CONFIRMATION:
        return True

    print()
    _cprint("╔══════════════════════════════════════════════════════╗", "yellow")
    _cprint("║         🛡️  AI SAFETY — ACTION APPROVAL            ║", "yellow")
    _cprint("╠══════════════════════════════════════════════════════╣", "yellow")
    _cprint(f"║  Action : {action:<42} ║", "yellow")

    # Truncate target for display if too long
    target_display = target[:40] + "..." if len(target) > 40 else target
    _cprint(f"║  Target : {target_display:<42} ║", "yellow")

    if details:
        details_display = details[:40] + "..." if len(details) > 40 else details
        _cprint(f"║  Detail : {details_display:<42} ║", "yellow")

    _cprint("╚══════════════════════════════════════════════════════╝", "yellow")

    try:
        response = input("  Allow this action? (y/n): ").strip().lower()
        approved = response in ('y', 'yes')

        if approved:
            _cprint("  ✅ Action approved", "green")
        else:
            _cprint("  ❌ Action denied by user", "red")

        return approved
    except (EOFError, KeyboardInterrupt):
        _cprint("\n  ❌ Action cancelled", "red")
        return False


def _is_path_allowed(filepath: str) -> bool:
    """Check if a path is within the allowed directories."""
    normalized = os.path.normpath(os.path.abspath(filepath))
    for allowed in ALLOWED_DIRECTORIES:
        if normalized.startswith(allowed):
            return True
    return False


def _is_extension_blocked(filepath: str) -> bool:
    """Check if a file's extension is in the blocked list."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in BLOCKED_EXTENSIONS


def _is_app_whitelisted(app_name: str) -> bool:
    """Check if an application is in the whitelist."""
    return app_name.lower().strip() in WHITELISTED_APPS


def _is_url_safe(url: str) -> dict:
    """
    Basic URL safety check.
    Returns dict with 'safe' bool and 'warnings' list.
    """
    warnings = []

    if url.startswith('http://'):
        warnings.append("⚠️  Non-HTTPS URL (unencrypted connection)")

    if url.startswith('file://'):
        warnings.append("⚠️  Local file URL")

    suspicious_patterns = [
        'javascript:', 'data:', 'vbscript:',
        '.exe', '.bat', '.cmd', '.msi',
    ]
    url_lower = url.lower()
    for pattern in suspicious_patterns:
        if pattern in url_lower:
            warnings.append(f"⚠️  Suspicious pattern in URL: {pattern}")

    return {"safe": len(warnings) == 0, "warnings": warnings}


# =============================================================================
# SAFE Core Functions (with guards)
# =============================================================================

def open_file(filepath: str, app: str = '') -> Dict[str, Any]:
    """
    Open a file with the default application or a specified app.
    GUARDED: Requires user confirmation, path check, extension check.
    """
    filepath = os.path.normpath(filepath)

    if not os.path.exists(filepath):
        return {"success": False, "error": f"File not found: {filepath}"}

    # --- SAFETY CHECK: Blocked extensions ---
    if _is_extension_blocked(filepath):
        ext = os.path.splitext(filepath)[1]
        _log_action("OPEN_FILE", filepath, f"BLOCKED (extension {ext})", False)
        return {"success": False,
                "error": f"🛡️ Safety block: Cannot open {ext} files (executable/script)",
                "blocked_extension": ext}

    # --- SAFETY CHECK: Path sandboxing ---
    if not _is_path_allowed(filepath):
        _log_action("OPEN_FILE", filepath, "BLOCKED (outside allowed dirs)", False)
        return {"success": False,
                "error": f"🛡️ Safety block: Path is outside allowed directories",
                "allowed_dirs": ALLOWED_DIRECTORIES}

    # --- SAFETY CHECK: App whitelist ---
    if app and not _is_app_whitelisted(app):
        _log_action("OPEN_FILE", filepath, f"BLOCKED (app '{app}' not whitelisted)", False)
        return {"success": False,
                "error": f"🛡️ Safety block: App '{app}' is not whitelisted",
                "whitelisted_apps": sorted(WHITELISTED_APPS)}

    # --- USER CONFIRMATION ---
    detail = f"App: {app}" if app else "Default app"
    if not _ask_user_confirmation("Open File", filepath, detail):
        _log_action("OPEN_FILE", filepath, "DENIED by user", False)
        return {"success": False, "error": "Action denied by user"}

    try:
        if app:
            app_lower = app.lower().strip()
            exe_paths = APP_REGISTRY.get(app_lower, [app_lower])

            for exe in exe_paths:
                try:
                    subprocess.Popen([exe, filepath], shell=False,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    _log_action("OPEN_FILE", filepath, f"Opened in {app}")
                    return {
                        "success": True, "action": "opened_file",
                        "filepath": filepath, "app": app,
                        "message": f"Opened {os.path.basename(filepath)} in {app}"
                    }
                except FileNotFoundError:
                    continue

            return {"success": False,
                    "error": f"Application '{app}' not found. Available: {', '.join(sorted(WHITELISTED_APPS))}"}
        else:
            os.startfile(filepath)
            _log_action("OPEN_FILE", filepath, "Opened with default app")
            return {
                "success": True, "action": "opened_file",
                "filepath": filepath, "app": "default",
                "message": f"Opened {os.path.basename(filepath)} with default application"
            }
    except Exception as e:
        _log_action("OPEN_FILE", filepath, f"ERROR: {e}")
        return {"success": False, "error": str(e)}


def open_folder(folderpath: str) -> Dict[str, Any]:
    """
    Open a folder in Windows Explorer.
    GUARDED: Requires user confirmation, path check.
    """
    folderpath = os.path.normpath(folderpath)

    if not os.path.exists(folderpath):
        parent = os.path.dirname(folderpath)
        if os.path.exists(parent):
            folderpath = parent
        else:
            return {"success": False, "error": f"Path not found: {folderpath}"}

    # --- SAFETY CHECK: Path sandboxing ---
    if not _is_path_allowed(folderpath):
        _log_action("OPEN_FOLDER", folderpath, "BLOCKED (outside allowed dirs)", False)
        return {"success": False,
                "error": f"🛡️ Safety block: Path is outside allowed directories"}

    # --- USER CONFIRMATION ---
    if not _ask_user_confirmation("Open Folder", folderpath):
        _log_action("OPEN_FOLDER", folderpath, "DENIED by user", False)
        return {"success": False, "error": "Action denied by user"}

    try:
        if os.path.isfile(folderpath):
            subprocess.Popen(["explorer", "/select,", folderpath])
            _log_action("OPEN_FOLDER", folderpath, "Opened (file selected)")
            return {
                "success": True, "action": "opened_folder",
                "path": os.path.dirname(folderpath),
                "selected_file": os.path.basename(folderpath),
                "message": f"Opened folder with {os.path.basename(folderpath)} selected"
            }
        else:
            subprocess.Popen(["explorer", folderpath])
            _log_action("OPEN_FOLDER", folderpath, "Opened")
            return {
                "success": True, "action": "opened_folder",
                "path": folderpath,
                "message": f"Opened folder: {folderpath}"
            }
    except Exception as e:
        _log_action("OPEN_FOLDER", folderpath, f"ERROR: {e}")
        return {"success": False, "error": str(e)}


def open_url(url: str, browser: str = '') -> Dict[str, Any]:
    """
    Open a URL in the default or specified browser.
    GUARDED: Requires user confirmation, URL safety check.
    """
    if not url.startswith(('http://', 'https://', 'file://')):
        url = 'https://' + url

    # --- SAFETY CHECK: URL inspection ---
    url_check = _is_url_safe(url)
    warning_text = ""
    if not url_check['safe']:
        warning_text = " | ".join(url_check['warnings'])

    # --- SAFETY CHECK: Browser whitelist ---
    if browser and not _is_app_whitelisted(browser):
        _log_action("OPEN_URL", url, f"BLOCKED (browser '{browser}' not whitelisted)", False)
        return {"success": False,
                "error": f"🛡️ Safety block: Browser '{browser}' is not whitelisted"}

    # --- USER CONFIRMATION ---
    detail = warning_text if warning_text else (f"Browser: {browser}" if browser else "Default browser")
    if not _ask_user_confirmation("Open URL", url, detail):
        _log_action("OPEN_URL", url, "DENIED by user", False)
        return {"success": False, "error": "Action denied by user"}

    try:
        if browser:
            browser_lower = browser.lower().strip()
            exe_paths = APP_REGISTRY.get(browser_lower, [])

            for exe in exe_paths:
                try:
                    subprocess.Popen([exe, url],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    _log_action("OPEN_URL", url, f"Opened in {browser}")
                    return {
                        "success": True, "action": "opened_url",
                        "url": url, "browser": browser,
                        "message": f"Opened {url} in {browser}"
                    }
                except FileNotFoundError:
                    continue

            webbrowser.open(url)
            _log_action("OPEN_URL", url, "Opened in default (fallback)")
            return {
                "success": True, "action": "opened_url",
                "url": url, "browser": "default (requested browser not found)",
                "message": f"Opened {url} in default browser"
            }
        else:
            webbrowser.open(url)
            _log_action("OPEN_URL", url, "Opened in default browser")
            return {
                "success": True, "action": "opened_url",
                "url": url, "browser": "default",
                "message": f"Opened {url} in default browser"
            }
    except Exception as e:
        _log_action("OPEN_URL", url, f"ERROR: {e}")
        return {"success": False, "error": str(e)}


def launch_app(app_name: str, args: List[str] = None) -> Dict[str, Any]:
    """
    Launch an application by name.
    GUARDED: Requires user confirmation, app whitelist.
    """
    # --- SAFETY CHECK: App whitelist ---
    if not _is_app_whitelisted(app_name):
        _log_action("LAUNCH_APP", app_name, "BLOCKED (not whitelisted)", False)
        return {"success": False,
                "error": f"🛡️ Safety block: App '{app_name}' is not whitelisted",
                "whitelisted_apps": sorted(WHITELISTED_APPS)}

    cmd_args = args or []

    # --- SAFETY CHECK: If args contain paths, verify them ---
    for arg in cmd_args:
        if os.path.sep in arg or '/' in arg:
            if not _is_path_allowed(arg):
                _log_action("LAUNCH_APP", f"{app_name} {arg}", "BLOCKED (path arg outside allowed dirs)", False)
                return {"success": False,
                        "error": f"🛡️ Safety block: Argument path '{arg}' is outside allowed directories"}

    # --- USER CONFIRMATION ---
    detail = f"Args: {' '.join(cmd_args)}" if cmd_args else "No arguments"
    if not _ask_user_confirmation("Launch App", app_name, detail):
        _log_action("LAUNCH_APP", app_name, "DENIED by user", False)
        return {"success": False, "error": "Action denied by user"}

    app_lower = app_name.lower().strip()
    exe_paths = APP_REGISTRY.get(app_lower, [app_lower])

    for exe in exe_paths:
        try:
            subprocess.Popen([exe] + cmd_args,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _log_action("LAUNCH_APP", app_name, f"Launched with args: {cmd_args}")
            return {
                "success": True, "action": "launched_app",
                "app": app_name, "args": cmd_args,
                "message": f"Launched {app_name}"
            }
        except FileNotFoundError:
            continue

    return {
        "success": False,
        "error": f"Could not find application: {app_name}",
        "available_apps": sorted(WHITELISTED_APPS)
    }


def get_recent_files(directory: str, extension: str = '', count: int = 5) -> Dict[str, Any]:
    """
    Get the most recently modified files in a directory.
    SAFE: Read-only operation, no confirmation needed.
    """
    directory = os.path.normpath(directory)

    if not os.path.isdir(directory):
        return {"success": False, "error": f"Directory not found: {directory}"}

    # --- SAFETY CHECK: Path sandboxing ---
    if not _is_path_allowed(directory):
        return {"success": False,
                "error": f"🛡️ Safety block: Directory is outside allowed paths"}

    try:
        pattern = f"**/*{extension}" if extension else "**/*"
        files = []

        for f in Path(directory).glob(pattern):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "path": str(f),
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    "modified_ts": stat.st_mtime,
                })

        files.sort(key=lambda x: x['modified_ts'], reverse=True)

        for f in files:
            del f['modified_ts']

        _log_action("GET_RECENT", directory, f"Found {len(files)} files")
        return {
            "success": True,
            "directory": directory,
            "extension_filter": extension or "all",
            "total_found": len(files),
            "files": files[:count]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_files(directory: str, query: str, extensions: List[str] = None) -> Dict[str, Any]:
    """
    Search for files by name in a directory.
    SAFE: Read-only operation, no confirmation needed.
    """
    directory = os.path.normpath(directory)

    if not os.path.isdir(directory):
        return {"success": False, "error": f"Directory not found: {directory}"}

    # --- SAFETY CHECK: Path sandboxing ---
    if not _is_path_allowed(directory):
        return {"success": False,
                "error": f"🛡️ Safety block: Directory is outside allowed paths"}

    try:
        matches = []
        query_lower = query.lower()

        for root, dirs, files in os.walk(directory):
            for fname in files:
                if query_lower in fname.lower():
                    if extensions:
                        ext = os.path.splitext(fname)[1].lower()
                        if ext not in [e.lower() for e in extensions]:
                            continue

                    full_path = os.path.join(root, fname)
                    stat = os.stat(full_path)
                    matches.append({
                        "path": full_path,
                        "name": fname,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    })

        matches.sort(key=lambda x: x['modified'], reverse=True)

        _log_action("SEARCH_FILES", f"{query} in {directory}", f"{len(matches)} matches")
        return {
            "success": True,
            "query": query,
            "directory": directory,
            "total_matches": len(matches),
            "files": matches[:20]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_in_vscode(path: str) -> Dict[str, Any]:
    """Shortcut to open a file or folder in VS Code (whitelisted)."""
    return open_file(path, app="vscode") if os.path.isfile(path) else launch_app("vscode", [path])


# =============================================================================
# Safety Management
# =============================================================================

def get_security_status() -> Dict[str, Any]:
    """Return current security configuration for transparency."""
    return {
        "confirmation_required": REQUIRE_CONFIRMATION,
        "allowed_directories": ALLOWED_DIRECTORIES,
        "blocked_extensions": sorted(BLOCKED_EXTENSIONS),
        "whitelisted_apps": sorted(WHITELISTED_APPS),
        "audit_log": AUDIT_LOG_FILE,
    }


def view_audit_log(last_n: int = 20) -> str:
    """Read the last N entries from the audit log."""
    try:
        if not os.path.exists(AUDIT_LOG_FILE):
            return "No actions logged yet."
        with open(AUDIT_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return "".join(lines[-last_n:]) if lines else "Log is empty."
    except Exception as e:
        return f"Error reading log: {e}"
