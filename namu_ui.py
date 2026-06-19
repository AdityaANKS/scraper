"""
================================================================================
NAMU_UI.PY - Namu AI Agent Web UI Server
================================================================================
Version: 1.0
Last Updated: 2026

Launches a local web server and opens the browser.

Features:
  - Full chat with all CLI tools available
  - Free OpenRouter model selection
  - Media & document upload
  - Conversation history
  - Dark theme
================================================================================
"""

import os
import sys
import json
import asyncio
import threading
import webbrowser
import traceback
import base64
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from typing import Dict, List, Optional, Any

from config import config
from utils import safe_print, log_info, log_warn, log_error, log_success, sanitize_filename

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

# Import NVIDIA status from namu_ai (lazy — will be available after first _get_agent call)
_nvidia_available = False
try:
    from namu_ai import _nvidia_client as _nv_client, NVIDIA_GLM_MODEL_ID
    _nvidia_available = _nv_client is not None
except ImportError:
    NVIDIA_GLM_MODEL_ID = "nvidia/glm4.7"

# =============================================================================
# Paths
# =============================================================================

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
UI_TEMPLATE = os.path.join(TEMPLATE_DIR, "namu_ui.html")
UPLOAD_DIR = os.path.join(config.paths.base_dir, "ai_data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =============================================================================
# Shared State (single-user local server)
# =============================================================================

_namu_agent = None
_event_loop = None
_active_model = None
_uploaded_files: List[Dict[str, str]] = []


def _get_agent():
    """Get or create the NamuAI agent singleton."""
    global _namu_agent
    if _namu_agent is None:
        from namu_ai import NamuAI
        _namu_agent = NamuAI()
        # In web UI mode, auto-approve windows_tools actions
        # (user already initiated the request from the browser)
        try:
            import windows_tools
            windows_tools.REQUIRE_CONFIRMATION = False
        except ImportError:
            pass
    return _namu_agent


def _reset_agent():
    """Destroy and recreate the agent (for New Chat)."""
    global _namu_agent
    if _namu_agent:
        try:
            _run_async(_namu_agent.cleanup())
        except Exception:
            pass
        _namu_agent = None


def _run_async(coro):
    """Run an async coroutine from sync code using the shared event loop."""
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.new_event_loop()
        t = threading.Thread(target=_event_loop.run_forever, daemon=True)
        t.start()
    future = asyncio.run_coroutine_threadsafe(coro, _event_loop)
    return future.result(timeout=300)


# =============================================================================
# Free Model Fetcher
# =============================================================================

def fetch_free_models() -> List[Dict[str, str]]:
    """Fetch free models from OpenRouter API."""
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return []

    async def _fetch():
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            async with session.get(
                'https://openrouter.ai/api/v1/models',
                headers=headers,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    models = data.get('data', [])
                    free_models = []
                    for m in models:
                        model_id = m.get('id', '')
                        # Free models have :free suffix or zero pricing
                        pricing = m.get('pricing', {})
                        prompt_price = str(pricing.get('prompt', '1'))
                        completion_price = str(pricing.get('completion', '1'))
                        is_free = (
                            ':free' in model_id or
                            (prompt_price == '0' and completion_price == '0')
                        )
                        if is_free:
                            free_models.append({
                                'id': model_id,
                                'name': m.get('name', model_id),
                                'context_length': m.get('context_length', 0),
                                'description': m.get('description', '')[:120],
                            })
                    # Sort by name
                    free_models.sort(key=lambda x: x['name'])
                    return free_models
                return []

    try:
        return _run_async(_fetch())
    except Exception as e:
        log_error(f"Failed to fetch models: {e}")
        return []


# =============================================================================
# Request Handler
# =============================================================================

class NamuUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Namu AI web UI."""

    def log_message(self, format, *args):
        """Suppress default logging to keep terminal clean."""
        pass

    def _send_json(self, data: Any, status: int = 200):
        """Send a JSON response."""
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200):
        """Send an HTML response."""
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        """Read the request body."""
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length) if length > 0 else b''

    def _parse_json_body(self) -> Dict:
        """Parse JSON request body."""
        try:
            body = self._read_body()
            return json.loads(body) if body else {}
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------------------
    # Route: GET
    # -------------------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/index.html':
            self._serve_ui()
        elif path == '/api/models':
            self._handle_get_models()
        elif path == '/api/history':
            self._handle_get_history()
        elif path == '/api/model':
            self._handle_get_active_model()
        elif path.startswith('/api/uploads/'):
            self._serve_upload(path)
        else:
            self.send_error(404)

    # -------------------------------------------------------------------------
    # Route: POST
    # -------------------------------------------------------------------------

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/chat':
            self._handle_chat()
        elif path == '/api/model':
            self._handle_set_model()
        elif path == '/api/upload':
            self._handle_upload()
        else:
            self.send_error(404)

    # -------------------------------------------------------------------------
    # Route: DELETE
    # -------------------------------------------------------------------------

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/history':
            self._handle_clear_history()
        else:
            self.send_error(404)

    # -------------------------------------------------------------------------
    # Route: OPTIONS (CORS)
    # -------------------------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    def _serve_ui(self):
        """Serve the main UI HTML page."""
        if os.path.exists(UI_TEMPLATE):
            with open(UI_TEMPLATE, 'r', encoding='utf-8') as f:
                html = f.read()
            self._send_html(html)
        else:
            self._send_html("<h1>UI template not found</h1>", 500)

    def _serve_upload(self, path):
        """Serve an uploaded file for preview."""
        filename = path.replace('/api/uploads/', '')
        filepath = os.path.join(UPLOAD_DIR, filename)
        if not os.path.exists(filepath) or not os.path.abspath(filepath).startswith(os.path.abspath(UPLOAD_DIR)):
            self.send_error(404)
            return
        mime_type = mimetypes.guess_type(filepath)[0] or 'application/octet-stream'
        with open(filepath, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers()
        self.wfile.write(data)

    def _handle_get_models(self):
        """Return list of available models including NVIDIA."""
        models = []

        # Add NVIDIA GLM4.7 at the very top if available
        nvidia_models = []
        if _nvidia_available:
            nvidia_models.append({
                'id': NVIDIA_GLM_MODEL_ID,
                'name': 'NVIDIA GLM4.7 (Reasoning)',
                'context_length': 16384,
                'description': 'NVIDIA-hosted GLM4.7 with reasoning/thinking capability',
            })

        # Fetch OpenRouter free models
        or_models = fetch_free_models()

        # Add the default OpenRouter models
        defaults = [
            {'id': 'arcee-ai/trinity-large-preview:free', 'name': 'Trinity Large (OpenRouter)', 'context_length': 24576, 'description': 'Default OpenRouter primary model'},
            {'id': 'cognitivecomputations/dolphin-mistral-24b-venice-edition:free', 'name': 'Dolphin Mistral 24B (OpenRouter)', 'context_length': 32768, 'description': 'Default OpenRouter fallback model'},
        ]

        # Remove duplicates from fetched models
        default_ids = {d['id'] for d in defaults} | {NVIDIA_GLM_MODEL_ID}
        or_models = [m for m in or_models if m['id'] not in default_ids]

        all_models = nvidia_models + defaults + or_models
        self._send_json({'models': all_models})

    def _handle_get_active_model(self):
        """Return the currently active model."""
        global _active_model
        agent = _get_agent()
        current = _active_model or agent.MODELS[0]
        self._send_json({'model': current})

    def _handle_set_model(self):
        """Set the active model."""
        global _active_model
        data = self._parse_json_body()
        model_id = data.get('model', '')
        if not model_id:
            self._send_json({'error': 'model required'}, 400)
            return
        # Validate NVIDIA selection
        if model_id == NVIDIA_GLM_MODEL_ID and not _nvidia_available:
            self._send_json({'error': 'NVIDIA API key not configured. Set NVIDIA_API_KEY in .env'}, 400)
            return
        _active_model = model_id
        agent = _get_agent()
        agent.set_model(model_id)
        display_name = 'NVIDIA GLM4.7' if model_id == NVIDIA_GLM_MODEL_ID else model_id
        print(f"  [UI] Model set to: {display_name}")
        print(f"  [UI] Model order: {agent.MODELS}")
        self._send_json({'success': True, 'model': model_id})

    def _handle_chat(self):
        """Handle a chat message."""
        global _uploaded_files, _active_model
        import re
        import io

        data = self._parse_json_body()
        message = data.get('message', '').strip()

        if not message:
            self._send_json({'error': 'message required'}, 400)
            return

        # Append uploaded file context to the message
        if _uploaded_files:
            file_context_parts = []
            for uf in _uploaded_files:
                file_context_parts.append(f"[Attached file: {uf['name']} at {uf['path']}]")
            message = message + "\n\n" + "\n".join(file_context_parts)
            _uploaded_files.clear()

        agent = _get_agent()
        current_model = _active_model or (agent.MODELS[0] if agent.MODELS else 'unknown')
        print(f"  [UI] Chat: {message[:80]}...")

        try:
            # Capture stdout from tool execution
            captured = io.StringIO()
            old_stdout = sys.stdout

            class TeeOutput:
                def __init__(self, original, capture):
                    self.original = original
                    self.capture = capture
                def write(self, s):
                    self.original.write(s)
                    self.capture.write(s)
                def flush(self):
                    self.original.flush()

            sys.stdout = TeeOutput(old_stdout, captured)
            try:
                response = _run_async(agent.chat(message))
            finally:
                sys.stdout = old_stdout

            tool_output = captured.getvalue().strip()

            # Parse tool output into structured activity steps
            activity_steps = []
            if tool_output:
                for line in tool_output.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    # Strip ANSI codes
                    clean_line = re.sub(r'\033\[[0-9;]*m', '', line)

                    if '[AGENT]' in clean_line and 'Executing' in clean_line:
                        tool_match = re.search(r'Executing:\s*(\S+)', clean_line)
                        tool_name = tool_match.group(1) if tool_match else 'unknown'
                        activity_steps.append({'type': 'tool_start', 'tool': tool_name, 'status': 'running', 'detail': clean_line})
                    elif '[OK]' in clean_line:
                        tool_match = re.search(r'\?\s*(\S+)\s+OK', clean_line)
                        tool_name = tool_match.group(1) if tool_match else ''
                        activity_steps.append({'type': 'tool_done', 'tool': tool_name, 'status': 'success', 'detail': clean_line})
                    elif '[FAIL]' in clean_line:
                        activity_steps.append({'type': 'tool_fail', 'tool': '', 'status': 'error', 'detail': clean_line})
                    elif '[WARN]' in clean_line:
                        activity_steps.append({'type': 'warning', 'tool': '', 'status': 'warn', 'detail': clean_line})
                    elif 'Thinking' in clean_line or 'Planning' in clean_line:
                        activity_steps.append({'type': 'thinking', 'tool': '', 'status': 'thinking', 'detail': clean_line})
                    elif 'Sub-agent' in clean_line or 'sub-agent' in clean_line:
                        activity_steps.append({'type': 'subagent', 'tool': '', 'status': 'running', 'detail': clean_line})
                    elif clean_line.startswith(('  ', 'url:', 'path:', 'query:', 'target:')):
                        # Tool argument lines
                        if activity_steps:
                            activity_steps[-1]['detail'] += '\n' + clean_line

            # Clean response
            cleaned = response or ''
            cleaned = re.sub(r'```(?:json)?\s*\n?\s*\{[^`]+?\}\s*\n?\s*```', '', cleaned, flags=re.DOTALL)
            cleaned = re.sub(r'\{"tool"\s*:\s*"[^"]+"[^}]*\}', '', cleaned)
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

            if not cleaned:
                if tool_output:
                    lines = [l.strip() for l in tool_output.split('\n') if l.strip()]
                    clean_lines = [l for l in lines if not l.startswith('[Namu] Thinking')]
                    cleaned = '\n'.join(clean_lines) if clean_lines else 'Task completed.'
                else:
                    cleaned = 'Request processed. Check terminal for details.'

            print(f"  [UI] Response: {cleaned[:100]}...")

            self._send_json({
                'success': True,
                'response': cleaned,
                'model': current_model,
                'activity': activity_steps,
                'tool_output': tool_output[:3000] if tool_output else '',
                'message_count': len(agent.messages),
            })
        except Exception as e:
            sys.stdout = sys.__stdout__
            print(f"  [UI] ERROR: {e}")
            traceback.print_exc()
            self._send_json({'error': str(e)}, 500)

    def _handle_get_history(self):
        """Return conversation history."""
        import re
        agent = _get_agent()
        history = []
        seen_content = set()  # Deduplicate
        for msg in agent.messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role not in ('user', 'assistant'):
                continue
            # Skip internal tool execution summaries injected by chat()
            if role == 'user' and content.startswith('Executed ') and 'tools:' in content:
                continue
            if role == 'user' and content.startswith('Sub-agent plan results:'):
                continue
            # Clean assistant messages
            if role == 'assistant':
                content = re.sub(r'```(?:json)?\s*\n?\s*\{[^`]+?\}\s*\n?\s*```', '', content, flags=re.DOTALL)
                content = re.sub(r'\{"tool"\s*:\s*"[^"]+"[^}]*\}', '', content)
                content = re.sub(r'\n{3,}', '\n\n', content).strip()
            if content and content not in seen_content:
                seen_content.add(content)
                history.append({'role': role, 'content': content})
        self._send_json({'history': history})

    def _handle_clear_history(self):
        """Clear conversation history and reset agent."""
        _reset_agent()
        self._send_json({'success': True})

    def _handle_upload(self):
        """Handle file upload (multipart/form-data parser)."""
        global _uploaded_files
        content_type = self.headers.get('Content-Type', '')

        if 'multipart/form-data' not in content_type:
            # Try base64 JSON upload
            data = self._parse_json_body()
            filename = data.get('filename', 'upload')
            file_data_b64 = data.get('data', '')
            file_type = data.get('type', 'unknown')

            if not file_data_b64:
                self._send_json({'error': 'No file data'}, 400)
                return

            try:
                file_bytes = base64.b64decode(file_data_b64)
            except Exception:
                self._send_json({'error': 'Invalid base64 data'}, 400)
                return

            safe_name = sanitize_filename(filename)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_name = f"{ts}_{safe_name}"
            save_path = os.path.join(UPLOAD_DIR, save_name)

            with open(save_path, 'wb') as f:
                f.write(file_bytes)

            file_info = {
                'name': filename,
                'path': save_path,
                'type': file_type,
                'size': len(file_bytes),
                'save_name': save_name,
                'preview_url': f'/api/uploads/{save_name}',
            }
            _uploaded_files.append(file_info)

            self._send_json({
                'success': True,
                'file': file_info,
                'message': f'File uploaded: {save_name}',
            })
        else:
            # Simple multipart parser
            boundary = content_type.split('boundary=')[-1].encode()
            body = self._read_body()
            parts = body.split(b'--' + boundary)

            for part in parts:
                if b'filename=' not in part:
                    continue

                # Extract filename
                header_end = part.find(b'\r\n\r\n')
                if header_end == -1:
                    continue
                headers_raw = part[:header_end].decode('utf-8', errors='replace')
                file_content = part[header_end + 4:]
                if file_content.endswith(b'\r\n'):
                    file_content = file_content[:-2]

                # Parse filename from Content-Disposition
                filename = 'upload'
                for line in headers_raw.split('\r\n'):
                    if 'filename=' in line:
                        fname_start = line.find('filename="') + 10
                        fname_end = line.find('"', fname_start)
                        if fname_start > 9 and fname_end > fname_start:
                            filename = line[fname_start:fname_end]
                        break

                safe_name = sanitize_filename(filename)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                save_name = f"{ts}_{safe_name}"
                save_path = os.path.join(UPLOAD_DIR, save_name)

                with open(save_path, 'wb') as f:
                    f.write(file_content)

                # Detect type
                mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                if mime_type.startswith('image') or mime_type.startswith('video'):
                    file_type = 'media'
                else:
                    file_type = 'document'

                file_info = {
                    'name': filename,
                    'path': save_path,
                    'type': file_type,
                    'size': len(file_content),
                }
                _uploaded_files.append(file_info)

                self._send_json({
                    'success': True,
                    'file': file_info,
                    'message': f'File uploaded: {save_name}',
                })
                return

            self._send_json({'error': 'No file found in upload'}, 400)


# =============================================================================
# Server Runner
# =============================================================================

def run_namu_ui(port: int = 7860):
    """Start the Namu AI web UI server and open in browser."""
    safe_print(f"""
{'='*66}
{'NAMU AI — WEB UI':^66}
{'='*66}
  Server: http://localhost:{port}
  Status: Starting...
{'='*66}
""")

    server = HTTPServer(('127.0.0.1', port), NamuUIHandler)

    # Open browser
    url = f'http://localhost:{port}'
    safe_print(f"  [OK] Server running at {url}")
    safe_print(f"  [OK] Opening browser...")
    safe_print(f"  Press Ctrl+C to stop the server and return to menu.\n")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("\n  [OK] Shutting down Namu AI Web UI...")
    finally:
        server.server_close()
        # Cleanup agent
        global _namu_agent, _event_loop
        if _namu_agent:
            try:
                _run_async(_namu_agent.cleanup())
            except Exception:
                pass
            _namu_agent = None
        if _event_loop and not _event_loop.is_closed():
            _event_loop.call_soon_threadsafe(_event_loop.stop)
            _event_loop = None
        safe_print("  [OK] Server stopped.\n")


# =============================================================================
# Module Entry
# =============================================================================

if __name__ == "__main__":
    run_namu_ui()
