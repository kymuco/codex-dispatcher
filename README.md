# Codex Dispatcher

Local Telegram bot that:

- accepts messages from Telegram;
- forwards them to local `codex exec` or `codex exec resume`;
- returns only the final Codex response back to Telegram;
- stores `session_id` per Telegram chat and per named local chat;
- switches Codex accounts by swapping `auth.json`;
- automatically tries the next account when a limit is hit.

## How It Works

The bot keeps a shared `CODEX_HOME` for local Codex sessions so chat history is preserved. Before each run it copies the selected account's `auth.json` into the working `state_dir`, then launches Codex.

That gives us this flow:

1. A Telegram message arrives in the bot.
2. The bot looks up the active local chat for that Telegram chat.
3. If a local `session_id` already exists, it uses `codex exec resume`.
4. If Codex hits a limit, the bot switches accounts and continues the same local session.

## Files

- `config.json`: runtime bot config
- `data/bot_state.json`: mapping between Telegram chats, local chats, and `session_id`
- `.codex-bot-state/`: shared `CODEX_HOME` for Codex runs

## Account Setup

Use the following safe setup flow for each account.

1. Sign in to Codex with that account.

2. Make sure file-based login storage is enabled:

   ```powershell
   codex login -c 'cli_auth_credentials_store="file"'
   ```

3. Save the resulting `auth.json` in a separate account folder, for example:

   ```text
   C:\path\to\accounts\acc1\auth.json
   C:\path\to\accounts\acc2\auth.json
   ```

If your environment needs extra files next to `auth.json`, add them to `extra_files` for the account. The bot copies them into the shared `state_dir` by filename before each run.

## Installation

For local development, install the project in editable mode:

```powershell
python -m pip install -e .
```

After that you can start it either as a module:

```powershell
python -m codex_dispatcher
```

or as a console command:

```powershell
codex-dispatcher
```

## Configuration

1. Copy `config.example.json` to `config.json`.
2. Fill in:
   - `telegram_token`
   - `allowed_chat_ids`
   - `codex.cwd` and `codex.state_dir` (relative paths are fine)
   - the account `auth.json` paths
3. Start the bot:

```powershell
python -m codex_dispatcher
```

You can also pass a config path explicitly:

```powershell
python -m codex_dispatcher C:\path\to\codex-dispatcher\config.json
```

## Bot Commands

- `/start`: compact onboarding message with quick-start actions
- `/help [command]` or `/doc [command]`: show grouped command sections or mini docs for one command
- `/status` or `/state`: show active local chat, `session_id`, queue, and runtime state
- `/threads` or `/chats`: list local chats in the current Telegram chat
- `/sessionid` or `/sid`: show current `session_id` and ready `/attachsession` command
- `/newchat [alias]` or `/new [alias]`: create and activate a local chat
- `/use <alias>` or `/chat <alias>`: switch to an existing local chat
- `/resetchat` or `/reset`: clear active local chat `session_id`
- `/accounts` or `/accs`: list configured accounts
- `/switch <account>` or `/account <account>`: set default account
- `/attachsession <session_id_or_path>` or `/attach ...`: bind existing Codex session
- `/clonevscode [title]` or `/clone [title]`: create temporary VSCode view copy
- `/deletevscodecopy <cloned_session_id>` or `/deletecopy ...`: delete temporary VSCode view copy
- `/edit on|off|full|default`: quick file-edit toggle
- `/sandbox ...` or `/mode ...`: explicit sandbox mode
- `/fullaccess` or `/full`: enable `danger-full-access` (with confirmation)
- `/ask <text>` or `/q <text>`: send a prompt to Codex

Plain text without a command behaves like `/ask`.

The bot also publishes Telegram command hints, so typing `/` shows suggested commands with short descriptions.

## Limits

- The queue is sequential: only one Codex run executes at a time.
- Auto-switching accounts is driven by text markers for limit detection. You can extend them in `config.json`.
- For reliability, do not run other processes that modify `auth.json` in the same `state_dir` at the same time.

## Troubleshooting

1. `Config file not found ... Copy config.example.json to config.json first.`
    Use a valid config path:

    ```powershell
    codex-dispatcher C:\path\to\codex-dispatcher\config.json
    ```

2. `auth.json not found for account ...`
Check `accounts[].auth_file` in `config.json` and make sure each referenced file exists.

3. `Codex binary was not found ...`
Install Codex CLI and verify it is available in `PATH`, or set an explicit path in `codex.binary`.

4. `Codex did not finish successfully.`
Inspect the return code and command output in bot logs. Common causes are invalid sandbox mode for `resume`, missing auth files, or temporary Codex CLI failures.

5. Auto-switch on limits did not trigger.
Update `codex.limit_markers` in `config.json` to include the exact limit text returned by your Codex account.

6. `/attachsession` reports `Session not found for reference ...`
Use a valid session id from `session_index.jsonl` or a correct absolute path to a rollout `.jsonl` file.

7. `/clonevscode` copy looks stale in VSCode.
Create a fresh clone and reopen the thread in VSCode. If needed, remove the temporary copy with `/deletevscodecopy <cloned_session_id>`.

## Session Purge Utility

If you need to remove a specific chat from any Codex home, use the standalone utility. No code changes are required; the target path is provided through `--home`.

Start with a preview so you can see exactly what will be affected:

```powershell
python -m codex_dispatcher.purge_codex_session <session-id> --home C:\Users\<your-user>\.codex
```

If everything looks right, add `--apply`:

```powershell
python -m codex_dispatcher.purge_codex_session <session-id> --home C:\Users\<your-user>\.codex --apply
```

The utility also works with another home, for example the bot's working `.codex-bot-state`:

```powershell
python -m codex_dispatcher.purge_codex_session <session-id> --home C:\path\to\codex-dispatcher\.codex-bot-state
```

What it removes from the selected `--home`:

1. the row from `state_5.sqlite`
2. the entry from `session_index.jsonl`
3. the rollout history file
4. related links in additional SQLite tables, if present

Before making changes, the utility creates a backup of affected files in `backups/purge-<timestamp>/`.

## Local Verification

```powershell
python -m unittest discover -s tests -v
```

## Project Docs

- `CHANGELOG.md`: notable changes by version.
- `RELEASE.md`: release checklist and tagging flow.
- `CONTRIBUTING.md`: contribution guidelines for pull requests.
- `SECURITY.md`: vulnerability reporting process.
- `CODE_OF_CONDUCT.md`: community behavior expectations and enforcement.

## License

Apache 2.0 - see `LICENSE`.
