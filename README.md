# Codex Dispatcher

[![CI Smoke](https://github.com/kymuco/codex-dispatcher/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kymuco/codex-dispatcher/actions/workflows/ci.yml?query=branch%3Amain)
![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)
![License Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green)

Telegram bot for running local Codex sessions from Telegram chats.

Windows is the primary runtime target. CI also runs a basic Ubuntu sanity check.

## What this bot does

- Receives Telegram messages and runs them through local `codex exec` / `codex exec resume`.
- Sends plain text messages as Codex prompts (no command prefix required).
- Supports multiple local chats (`alias`) inside one Telegram chat.
- Stores and reuses `session_id` per local chat.
- Switches Codex accounts by replacing `auth.json`.
- Can auto-switch accounts when configured limit markers are detected.
- Supports per-chat runtime settings: model, reasoning, sandbox mode.
- Supports session file workflows: attach, clone/export/sync for VSCode views.

## Installation

### 1. Prerequisites

- Python `>=3.13`
- Codex CLI installed and available in `PATH`
- Telegram bot token
- At least one Codex account with file-based auth (`auth.json`)

### 2. Install

```powershell
python -m pip install -e .
```

### 3. Prepare config

Copy the example and fill required fields:

```powershell
Copy-Item config.example.json config.json
```

For a quick first run, keep `allowed_chat_ids` as an empty list (`[]`).  
After the bot works, use `/chatid` and set an explicit allow-list.

Set at least:

- `telegram_token`
- `codex.cwd`
- `codex.state_dir`
- `accounts[].auth_file`

Optional but useful:

- `codex.limit_markers` for auto account switch behavior
- `accounts[].extra_files` if your auth setup requires extra files

Make sure `accounts[].auth_file` points to a real file before running checks.
Example (PowerShell):

```powershell
New-Item -ItemType Directory -Path accounts\acc1 -Force | Out-Null
Copy-Item C:\path\to\real\auth.json accounts\acc1\auth.json
```

### 4. Launch command

```powershell
codex-dispatcher
```

Short alias after install:

```powershell
cdx
```

Or with explicit config path:

```powershell
codex-dispatcher C:\path\to\codex-dispatcher\config.json
```

Read-only CLI snapshots (without Telegram polling):

```powershell
codex-dispatcher --accounts
codex-dispatcher --status-chat-id 123456
codex-dispatcher --health-chat-id 123456
codex-dispatcher --threads-chat-id 123456
```

SDK-backed state updates (without Telegram polling):

```powershell
codex-dispatcher --new-chat 123456 bugfix
codex-dispatcher --use-chat 123456 bugfix
codex-dispatcher --set-model 123456 gpt-5.4
codex-dispatcher --set-reasoning 123456 high
codex-dispatcher --set-sandbox 123456 workspace-write
```

SDK-backed session and VSCode flows (without Telegram polling):

```powershell
codex-dispatcher --attach-session 123456 019d....
codex-dispatcher --clone-vscode 123456
codex-dispatcher --export-vscode 123456
codex-dispatcher --sync-vscode 123456
codex-dispatcher --delete-vscode-copy <cloned-session-id>
```

Run a prompt from CLI via SDK (without Telegram polling):

```powershell
codex-dispatcher --ask 123456 "summarize this repository"
```

Recommended structured SDK CLI mode (no `sdk` prefix):

```powershell
codex-dispatcher status 123456
codex-dispatcher threads 123456
codex-dispatcher new-chat 123456 bugfix
codex-dispatcher set-model 123456 gpt-5.4
codex-dispatcher ask 123456 "summarize this repository"
```

Same commands with short alias:

```powershell
cdx status 123456
cdx threads 123456
cdx ask 123456 "summarize this repository"
```

Backward-compatible legacy form is still supported:

```powershell
codex-dispatcher sdk status 123456
```

## First run

### 1. Validate environment before start

Use one of these checks:

```powershell
codex-dispatcher --check
```

or

```powershell
python scripts/check_env.py
```

The checker validates token/binary/workspace/state-dir/account file basics and prints actionable issues.

### Quick troubleshooting (first run)

- `Problem: Config file not found ...`
  - Fix: copy `config.example.json` to `config.json` or pass an explicit config path.
- `Problem: Telegram token looks invalid or placeholder.`
  - Fix: set a real `telegram_token` in `config.json`.
- `Problem: Codex binary was not found ...`
  - Fix: install Codex CLI or set `codex.binary` to a valid executable path.
- `Problem: account 'acc1' auth_file is missing ...`
  - Fix: point `accounts[].auth_file` to a real auth file and rerun `--check`.
- Telegram says `This bot is not enabled for this chat.`
  - Fix: start with `allowed_chat_ids: []`, then run `/chatid` and lock it down.

If setup still fails, run `codex-dispatcher --check` again and then `/health` after startup.

### 2. Start the bot

```powershell
codex-dispatcher
```

### 3. First interaction in Telegram

1. Send `/start`
2. Send a plain text prompt, for example: `summarize this repository`
3. Check state with `/status`
4. Run `/chatid` and lock down `allowed_chat_ids` in `config.json` if needed

## Typical flows

### Flow 1: First prompt

```text
/start
<send plain text prompt>
/status
/sessionid
```

Use this when validating that routing and session creation work end-to-end.

### Flow 2: Multiple local chats in one Telegram chat

Local chats are separate tracked contexts (`alias`) inside one Telegram chat.

```text
/newchat bugfix
/ask inspect failing tests
/newchat docs
/use bugfix
/threads
```

### Flow 3: Change model/reasoning/sandbox for one chat

These settings apply to the currently active local chat.

```text
/model gpt-5.4
/reasoning high
/sandbox workspace-write
/settings
```

### Flow 4: Resume or attach an existing session

Attach is useful when you already have a session id or rollout file and want to continue it in the active local chat.

```text
/attachsession <session_id>
```

or

```text
/attachsession C:\path\to\rollout-....jsonl
```

### Flow 5: VSCode copy flow

- `clone` creates a temporary independent view copy.
- `export` safely writes a local chat to VSCode home without overwriting.
- `sync` explicitly updates an existing VSCode copy.

```text
/clonevscode
/deletevscodecopy <id>
/exportvscode
/syncvscode
```

### Flow 6: Account switching

```text
/accounts
/switch acc2
```

If `codex.auto_switch_on_limit` is enabled, the bot can also switch accounts automatically on detected limit markers.

## Command map

Use `/help` for grouped command list and `/help <command>` (or `/doc <command>`) for mini docs.

### Onboarding and help

- `/start`
- `/help [command]`

### Chats and sessions

- `/ask <text>`
- `/newchat [alias]`
- `/threads`
- `/use <alias>`
- `/status`
- `/sessionid`
- `/resetchat`
- `/attachsession <session_id_or_path>`

### Runtime and accounts

- `/accounts`
- `/switch <account>`
- `/settings`
- `/model <name|default>`
- `/reasoning <low|medium|high|xhigh|default>`
- `/sandbox <read-only|workspace-write|danger-full-access|default>`
- `/edit on|off|full|default`
- `/fullaccess`

### VSCode and session tools

- `/clonevscode [title]`
- `/deletevscodecopy <cloned_session_id>`
- `/exportvscode [alias]`
- `/syncvscode [alias]`

### Utility

- `/health`
- `/chatid`

Typing `/` in Telegram also shows command hints published by the bot.

## Python SDK facade (preview)

You can drive the same orchestration layer from Python without Telegram:

```python
from codex_dispatcher.sdk import Dispatcher

dispatcher = Dispatcher.from_config("config.json")
code, report = dispatcher.check()
status = dispatcher.status(chat_id=123456)
```

The SDK currently exposes first-step high-level methods for checks, chat/session state, settings, and prompt execution.
See `docs/sdk.md` for method map and practical examples.

## Safety notes

- `danger-full-access` disables sandbox protections and approvals. Use only when you understand the risk.
- `workspace-write` and `read-only` are safer defaults for most tasks.
- Session file operations (`attach`, `clone`, `export`, `sync`) can change what session data is linked or copied. Make sure you understand which session id/path you are using.

## Operational notes

- The execution queue is sequential: one Codex run at a time.
- The bot stores runtime state in `data/bot_state.json`.
- `codex.state_dir` acts as shared `CODEX_HOME` for Codex runs.
- Avoid running other tools that mutate the same auth files in the same `state_dir` during bot execution.

## Troubleshooting

1. `Codex did not finish successfully.`
   - Check return code and bot logs for command output.
2. Auto-switch on limits did not trigger.
   - Update `codex.limit_markers` to match your real limit text.
3. `/attachsession` cannot find session.
   - Use a valid session id from `session_index.jsonl` or a valid rollout file path.
4. VSCode view copy looks stale.
   - Reopen or refresh VSCode view, or create a fresh clone.

## Session purge utility

Use purge utility to remove a specific session from a selected Codex home.

Preview only:

```powershell
python -m codex_dispatcher.purge_codex_session <session-id> --home C:\Users\<your-user>\.codex
```

Apply changes:

```powershell
python -m codex_dispatcher.purge_codex_session <session-id> --home C:\Users\<your-user>\.codex --apply
```

The utility updates:

- `state_5.sqlite`
- `session_index.jsonl`
- rollout history file
- related SQLite links (if present)

Backups are created in `backups/purge-<timestamp>/`.

## Local verification

```powershell
python -m unittest discover -s tests -v
```

## Project docs

- `CHANGELOG.md`
- `docs/architecture.md`
- `docs/sdk.md`
- `docs/release_notes_v0.1.0.md`
- `docs/release_notes_v0.1.1.md`
- `docs/release_checklist.md`
- `RELEASE.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`

## License

Apache 2.0 - see `LICENSE`.
