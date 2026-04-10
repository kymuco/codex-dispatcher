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

Set at least:

- `telegram_token`
- `allowed_chat_ids`
- `codex.cwd`
- `codex.state_dir`
- `accounts[].auth_file`

Optional but useful:

- `codex.limit_markers` for auto account switch behavior
- `accounts[].extra_files` if your auth setup requires extra files

### 4. Launch command

```powershell
codex-dispatcher
```

Or with explicit config path:

```powershell
codex-dispatcher C:\path\to\codex-dispatcher\config.json
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

### 2. Start the bot

```powershell
codex-dispatcher
```

### 3. First interaction in Telegram

1. Send `/start`
2. Send a plain text prompt, for example: `summarize this repository`
3. Check state with `/status`

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

1. `Config file not found ...`
   - Ensure `config.json` exists or pass explicit path to `codex-dispatcher`.
2. `auth.json not found for account ...`
   - Verify `accounts[].auth_file` paths in config.
3. `Codex binary was not found ...`
   - Install Codex CLI or set `codex.binary`.
4. `Codex did not finish successfully.`
   - Check return code and bot logs for command output.
5. Auto-switch on limits did not trigger.
   - Update `codex.limit_markers` to match your real limit text.
6. `/attachsession` cannot find session.
   - Use a valid session id from `session_index.jsonl` or a valid rollout file path.
7. VSCode view copy looks stale.
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
- `docs/release_notes_v0.1.0.md`
- `docs/release_checklist.md`
- `RELEASE.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`

## License

Apache 2.0 - see `LICENSE`.
