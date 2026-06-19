# 🧠 Namu AI — Self-Improvement Log (SIAI)

> This file is automatically maintained by Namu AI's self-improvement system.
> Every code change, patch, and improvement is logged here with timestamps.

## How This Works
- Namu AI can read/write its own code files (sandboxed to 4 files).
- Every modification creates a backup in `siai_backups/`.
- Python files are validated for syntax before any write is committed.
- This log tracks what was changed and why.

## Allowed Files
| File | Path | Access |
|---|---|---|
| `namu_ai.py` | `C:\scraper\namu_ai.py` | Patch only (no full rewrite) |
| `namu_report.html` | `C:\scraper\templates\namu_report.html` | Full read/write |
| `namu_ui.html` | `C:\scraper\templates\namu_ui.html` | Full read/write |
| `SIAI.md` | `C:\scraper\SIAI.md` | Full read/write |

## Safety Guards
- **Allowlist**: Only the 4 files above can be accessed. Path traversal is blocked.
- **Backups**: Every modification creates a timestamped backup in `siai_backups/`.
- **Syntax Validation**: `.py` files are compiled and validated before writing. Bad code is rejected.
- **Patch-Only for Python**: `namu_ai.py` cannot be fully rewritten — only targeted find/replace patches.
- **Size Limits**: Max 500KB per write, max 8KB per patch block.
- **Rollback**: Any change can be undone with `siai_rollback`.
- **Checkpoints**: Named version saves for reliable restore points.
- **Audit Trail**: This file logs every change with timestamp, action, and description.

## Optimized Workflow
```
outline → search → targeted read (30-80 lines) → patch/insert → test → log
```
1. `siai_outline` — Get structure map with line numbers (USE FIRST)
2. `siai_search` — Find exact text + line numbers
3. `siai_read_file` — Read ONLY 30-80 lines (never dump whole file)
4. `siai_patch_file` / `siai_insert_code` — Make surgical edits
5. `siai_test` — Verify changes work
6. `siai_hot_reload` — Apply changes without restart
7. `siai_log` — Document what changed and why

## Available SIAI Tools (16 total)

### Core Read Tools
| Tool | Description |
|---|---|
| `siai_outline` | Structure map (classes, functions, sections + line numbers) |
| `siai_search` | Search for patterns across allowed files |
| `siai_read_file` | Read specific line range (auto-outlines if no range given) |
| `siai_list_files` | List all allowed files with sizes |

### Write Tools
| Tool | Description |
|---|---|
| `siai_patch_file` | Find & replace with line-range scoping + syntax validation |
| `siai_insert_code` | Insert new code after a specific line number |
| `siai_write_file` | Full file rewrite (HTML/MD only — blocked for .py) |

### Version Control
| Tool | Description |
|---|---|
| `siai_rollback` | Restore from latest automatic backup |
| `siai_checkpoint` | Save/restore/list named version checkpoints |
| `siai_diff` | Show diff between current and latest backup |

### Testing & Analysis
| Tool | Description |
|---|---|
| `siai_test` | Smoke test: syntax, imports, tool inventory, health |
| `siai_metrics` | Code analysis: lines, functions, tools, complexity |
| `siai_hot_reload` | Reload module so code changes take effect immediately |

### Planning & Tracking
| Tool | Description |
|---|---|
| `siai_goals` | Manage improvement goals (add/complete/remove/list) |
| `siai_log` | Log structured improvement entries |
| `siai_status` | System health dashboard |

---

## Improvement History

